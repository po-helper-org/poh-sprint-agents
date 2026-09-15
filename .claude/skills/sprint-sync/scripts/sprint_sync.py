#!/usr/bin/env python3
"""sprint_sync — выгрузка актуального состояния спринта из JIRA.

Читает секцию `## jira` доменного профиля, тянет активный спринт доски (или
произвольный JQL), строит модель «исполнитель → история → сделано/осталось» и
рендерит два артефакта: самодостаточную HTML-страницу и текстовую таблицу.

Только GET-запросы — скрипт ничего не пишет в трекер (принцип «обратимость
первой»). Внешних зависимостей нет, только стандартная библиотека.

Офлайн-режим: `--from-json` рендерит из сохранённого payload (`--save-raw`),
это же используют тесты — сеть в тестах не нужна.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_API = 3

DEFAULT_SP_FIELD = "customfield_10016"
DEFAULT_STALE_DAYS = 3
PAGE_SIZE = 100
RETRY_BACKOFF = (2, 4, 8)

ISSUE_FIELDS = [
    "summary", "status", "assignee", "issuetype", "parent", "subtasks",
    "updated", "duedate", "labels", "priority", "resolutiondate",
]

CATEGORY_DONE = "done"
CATEGORY_PROGRESS = "indeterminate"
CATEGORY_TODO = "new"
CATEGORY_TITLES = {
    CATEGORY_DONE: "Готово",
    CATEGORY_PROGRESS: "В работе",
    CATEGORY_TODO: "Не начато",
}
UNASSIGNED = "[УТОЧНИТЬ исполнителя]"


# --------------------------------------------------------------------------
# Доменный профиль
# --------------------------------------------------------------------------

def parse_profile(path: str) -> dict[str, dict[str, str]]:
    """Разбирает domain-profile.md в {секция: {ключ: значение}}.

    Формат профиля: `## секция`, далее строки `ключ: значение   # комментарий`.
    Комментарий отрезается по ` #` (пробел-решётка), как в шаблоне профиля.
    Значение вида `[УТОЧНИТЬ …]` считается незаполненным и не возвращается.
    """
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return sections
    for line in text.splitlines():
        heading = re.match(r"^##\s+(\S+)", line)
        if heading:
            current = sections.setdefault(heading.group(1).strip().lower(), {})
            continue
        if current is None or not line.strip() or line.lstrip().startswith("#"):
            continue
        pair = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not pair:
            continue
        value = re.split(r"\s+#", pair.group(2), maxsplit=1)[0].strip()
        # незаполненный слот профиля (`[УТОЧНИТЬ …]`) — не значение: лучше явная
        # ошибка конфигурации, чем запрос к плейсхолдеру
        if value and not value.startswith("[УТОЧНИТЬ"):
            current[pair.group(1)] = value
    return sections


@dataclass
class Config:
    base_url: str = ""
    board_id: str = ""
    jql: str = ""
    sprint: str = ""
    story_points_field: str = DEFAULT_SP_FIELD
    done_statuses: tuple[str, ...] = ()
    stale_days: int = DEFAULT_STALE_DAYS
    out_dir: str = "."
    html_path: str = ""
    text_path: str = ""
    save_raw: str = ""
    from_json: str = ""
    timeout: int = 30


def build_config(args: argparse.Namespace, env: dict[str, str]) -> Config:
    profile = parse_profile(args.profile)
    jira = profile.get("jira", {})
    paths = profile.get("paths", {})

    cfg = Config()
    cfg.base_url = (args.base_url or env.get("JIRA_BASE_URL") or jira.get("base_url", "")).rstrip("/")
    cfg.board_id = args.board or jira.get("board_id", "")
    cfg.jql = args.jql or jira.get("jql", "")
    cfg.sprint = args.sprint or ""
    cfg.story_points_field = jira.get("story_points_field", DEFAULT_SP_FIELD)
    cfg.done_statuses = tuple(
        s.strip().lower() for s in jira.get("done_statuses", "").split(",") if s.strip()
    )
    cfg.stale_days = args.stale_days if args.stale_days is not None else _to_int(
        jira.get("stale_days"), DEFAULT_STALE_DAYS
    )
    cfg.from_json = args.from_json or ""
    cfg.save_raw = args.save_raw or ""
    cfg.timeout = args.timeout

    out_dir = args.out_dir or jira.get("sync_output_dir") or paths.get("sprint_workspace") or "."
    cfg.out_dir = out_dir
    return cfg


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def resolve_out_paths(cfg: Config, sprint_name: str) -> Config:
    """Подставляет {sprint} в выходные пути. Вызывается после того, как имя спринта известно."""
    slug = re.sub(r"[^\w.\-]+", "-", sprint_name).strip("-") or "sprint"
    out_dir = cfg.out_dir.replace("{sprint}", slug)
    cfg.out_dir = out_dir
    cfg.html_path = cfg.html_path or os.path.join(out_dir, f"sprint-sync-{slug}.html")
    cfg.text_path = cfg.text_path or os.path.join(out_dir, f"sprint-sync-{slug}.md")
    return cfg


# --------------------------------------------------------------------------
# JIRA-клиент (только GET)
# --------------------------------------------------------------------------

class JiraError(RuntimeError):
    """Транспортный отказ: JIRA не ответила."""


class JiraConfigError(JiraError):
    """Отказ конфигурации или доступа: нет токена, нет прав, не тот board/JQL/спринт."""


class JiraClient:
    """Минимальный GET-клиент JIRA на urllib. Bearer (Server/DC PAT) или Basic (Cloud)."""

    def __init__(self, base_url: str, auth_header: str, timeout: int = 30, ca_bundle: str = ""):
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout
        # проверка TLS не отключается; корпоративный CA подкладывается через JIRA_CA_BUNDLE
        self.context = ssl.create_default_context(cafile=ca_bundle or None)
        # свой opener: ProxyHandler читает окружение в момент создания клиента
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),
            urllib.request.HTTPSHandler(context=self.context),
        )

    def get(self, path: str, params: dict[str, object] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            "Authorization": self.auth_header,
            "Accept": "application/json",
            "User-Agent": "poh-sprint-agents/sprint-sync",
        })
        last_error: Exception | None = None
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", "replace")[:400]
                if error.code in (401, 403):
                    raise JiraConfigError(
                        f"JIRA отклонила запрос ({error.code}). Проверь токен и права на доску. {body}"
                    ) from error
                if error.code == 404:
                    raise JiraConfigError(f"JIRA: не найдено ({url}). Проверь board_id/JQL. {body}") from error
                if error.code < 500:
                    raise JiraConfigError(f"JIRA {error.code} на {path}: {body}") from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as error:
                last_error = error
            if attempt < len(RETRY_BACKOFF):
                time.sleep(RETRY_BACKOFF[attempt])
        raise JiraError(f"JIRA недоступна после {len(RETRY_BACKOFF) + 1} попыток: {last_error}")

    def paginate(self, path: str, params: dict[str, object], key: str = "issues") -> list[dict]:
        items: list[dict] = []
        start_at = 0
        while True:
            page = self.get(path, {**params, "startAt": start_at, "maxResults": PAGE_SIZE})
            chunk = page.get(key, [])
            items.extend(chunk)
            total = page.get("total")
            start_at += len(chunk)
            if not chunk or (isinstance(total, int) and start_at >= total) or page.get("isLast") is True:
                break
        return items


def auth_header(env: dict[str, str]) -> str:
    """Bearer из JIRA_TOKEN (Server/DC PAT) либо Basic из JIRA_EMAIL + JIRA_API_TOKEN (Cloud)."""
    token = env.get("JIRA_TOKEN", "").strip()
    if token:
        return f"Bearer {token}"
    email = env.get("JIRA_EMAIL", "").strip()
    api_token = env.get("JIRA_API_TOKEN", "").strip()
    if email and api_token:
        pair = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        return f"Basic {pair}"
    raise JiraConfigError(
        "Нет учётных данных JIRA. Задай JIRA_TOKEN (Server/DC: personal access token) "
        "или пару JIRA_EMAIL + JIRA_API_TOKEN (Cloud). Значения токенов не логируются."
    )


def fetch_payload(client: JiraClient, cfg: Config) -> dict:
    """Тянет спринт и его задачи. Возвращает сырой payload (его же пишет --save-raw)."""
    fields = ",".join(ISSUE_FIELDS + [cfg.story_points_field])
    sprint_meta: dict = {}

    if cfg.jql:
        jql = cfg.jql.replace("{sprint}", cfg.sprint) if cfg.sprint else cfg.jql
        issues = client.paginate("/rest/api/2/search", {"jql": jql, "fields": fields})
        sprint_meta = {"name": cfg.sprint or "по JQL", "jql": jql}
    else:
        sprints = client.paginate(
            f"/rest/agile/1.0/board/{cfg.board_id}/sprint", {"state": "active"}, key="values"
        )
        if not sprints:
            raise JiraConfigError(f"На доске {cfg.board_id} нет активного спринта.")
        if cfg.sprint:
            matched = [s for s in sprints if cfg.sprint.lower() in str(s.get("name", "")).lower()]
            if not matched:
                names = ", ".join(str(s.get("name")) for s in sprints)
                raise JiraConfigError(f"Спринт «{cfg.sprint}» не найден среди активных: {names}")
            sprint_meta = matched[0]
        elif len(sprints) > 1:
            names = ", ".join(str(s.get("name")) for s in sprints)
            raise JiraConfigError(f"Активных спринтов несколько — уточни --sprint: {names}")
        else:
            sprint_meta = sprints[0]
        issues = client.paginate(
            f"/rest/agile/1.0/sprint/{sprint_meta['id']}/issue", {"fields": fields}
        )

    return {
        "meta": {
            "base_url": cfg.base_url,
            "board_id": cfg.board_id,
            "story_points_field": cfg.story_points_field,
            "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        },
        "sprint": sprint_meta,
        "issues": issues,
    }


# --------------------------------------------------------------------------
# Модель отчёта
# --------------------------------------------------------------------------

@dataclass
class Child:
    key: str
    summary: str
    status: str
    category: str
    assignee: str = ""


@dataclass
class Story:
    key: str
    summary: str
    status: str
    category: str
    assignee: str
    sp: float | None = None
    epic: str = ""
    issue_type: str = ""
    updated: datetime | None = None
    days_idle: int | None = None
    due: str = ""
    labels: tuple[str, ...] = ()
    url: str = ""
    children: list[Child] = field(default_factory=list)

    @property
    def done_children(self) -> list[Child]:
        return [c for c in self.children if c.category == CATEGORY_DONE]

    @property
    def is_done(self) -> bool:
        return self.category == CATEGORY_DONE


@dataclass
class Person:
    name: str
    stories: list[Story] = field(default_factory=list)

    @property
    def sp_total(self) -> float:
        return sum(s.sp or 0 for s in self.stories)

    @property
    def sp_done(self) -> float:
        return sum(s.sp or 0 for s in self.stories if s.is_done)

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.stories if s.is_done)


@dataclass
class Report:
    sprint_name: str
    base_url: str
    fetched_at: str
    people: list[Person]
    stories: list[Story]
    start: str = ""
    end: str = ""
    goal: str = ""
    board_id: str = ""
    jql: str = ""
    stale_days: int = DEFAULT_STALE_DAYS
    unassigned: list[Story] = field(default_factory=list)
    stale: list[Story] = field(default_factory=list)
    overdue: list[Story] = field(default_factory=list)
    no_estimate: list[Story] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        counts = {CATEGORY_DONE: 0, CATEGORY_PROGRESS: 0, CATEGORY_TODO: 0}
        for story in self.stories:
            counts[story.category] = counts.get(story.category, 0) + 1
        counts["all"] = len(self.stories)
        return counts

    @property
    def sp_total(self) -> float:
        return sum(s.sp or 0 for s in self.stories)

    @property
    def sp_done(self) -> float:
        return sum(s.sp or 0 for s in self.stories if s.is_done)

    @property
    def day_of(self) -> tuple[int, int] | None:
        start, end = _parse_dt(self.start), _parse_dt(self.end)
        if not start or not end:
            return None
        now = _parse_dt(self.fetched_at) or datetime.now(timezone.utc)
        total = max((end.date() - start.date()).days, 1)
        elapsed = (now.date() - start.date()).days
        return max(0, min(elapsed, total)), total


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def category_of(status_node: dict, done_statuses: tuple[str, ...]) -> str:
    """Категория статуса. Опора на statusCategory (стабильна между инстансами JIRA),
    fallback — список done_statuses из профиля."""
    name = str(status_node.get("name", "")).strip()
    key = str(status_node.get("statusCategory", {}).get("key", "")).lower()
    if key in (CATEGORY_DONE, CATEGORY_PROGRESS, CATEGORY_TODO):
        return key
    if name.lower() in done_statuses:
        return CATEGORY_DONE
    return CATEGORY_TODO


def build_report(payload: dict, cfg: Config) -> Report:
    meta = payload.get("meta", {})
    sprint = payload.get("sprint", {}) or {}
    issues = payload.get("issues", []) or []
    sp_field = meta.get("story_points_field") or cfg.story_points_field
    base_url = (meta.get("base_url") or cfg.base_url or "").rstrip("/")
    fetched_at = meta.get("fetched_at") or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    now = _parse_dt(fetched_at) or datetime.now(timezone.utc)

    stories: dict[str, Story] = {}
    subtasks: list[tuple[str, Child]] = []

    for issue in issues:
        fields = issue.get("fields", {}) or {}
        status_node = fields.get("status", {}) or {}
        category = category_of(status_node, cfg.done_statuses)
        assignee_node = fields.get("assignee") or {}
        assignee = str(assignee_node.get("displayName") or assignee_node.get("name") or "").strip()
        issue_type = fields.get("issuetype", {}) or {}
        parent = fields.get("parent") or {}

        if issue_type.get("subtask"):
            subtasks.append((str(parent.get("key", "")), Child(
                key=issue.get("key", ""),
                summary=str(fields.get("summary", "")),
                status=str(status_node.get("name", "")),
                category=category,
                assignee=assignee,
            )))
            continue

        updated = _parse_dt(fields.get("updated"))
        stories[issue.get("key", "")] = Story(
            key=issue.get("key", ""),
            summary=str(fields.get("summary", "")),
            status=str(status_node.get("name", "")),
            category=category,
            assignee=assignee or UNASSIGNED,
            sp=_to_sp(fields.get(sp_field)),
            epic=str(parent.get("key", "")) if parent else "",
            issue_type=str(issue_type.get("name", "")),
            updated=updated,
            days_idle=(now - updated).days if updated else None,
            due=str(fields.get("duedate") or ""),
            labels=tuple(str(x) for x in (fields.get("labels") or [])),
            url=f"{base_url}/browse/{issue.get('key', '')}" if base_url else "",
            children=[],
        )

    # подзадачи: полные объекты из спринта имеют приоритет, заглушки fields.subtasks — добор
    for parent_key, child in subtasks:
        if parent_key in stories:
            stories[parent_key].children.append(child)
    for issue in issues:
        fields = issue.get("fields", {}) or {}
        story = stories.get(issue.get("key", ""))
        if not story:
            continue
        known = {c.key for c in story.children}
        for stub in fields.get("subtasks") or []:
            if stub.get("key") in known:
                continue
            stub_fields = stub.get("fields", {}) or {}
            story.children.append(Child(
                key=stub.get("key", ""),
                summary=str(stub_fields.get("summary", "")),
                status=str((stub_fields.get("status") or {}).get("name", "")),
                category=category_of(stub_fields.get("status") or {}, cfg.done_statuses),
            ))

    ordered = sorted(stories.values(), key=lambda s: (s.assignee == UNASSIGNED, s.assignee, s.key))
    people: dict[str, Person] = {}
    for story in ordered:
        people.setdefault(story.assignee, Person(name=story.assignee)).stories.append(story)

    report = Report(
        sprint_name=str(sprint.get("name") or cfg.sprint or "[УТОЧНИТЬ спринт]"),
        base_url=base_url,
        fetched_at=fetched_at,
        people=list(people.values()),
        stories=ordered,
        start=str(sprint.get("startDate") or ""),
        end=str(sprint.get("endDate") or ""),
        goal=str(sprint.get("goal") or ""),
        board_id=str(meta.get("board_id") or ""),
        jql=str(sprint.get("jql") or ""),
        stale_days=cfg.stale_days,
    )
    report.unassigned = [s for s in ordered if s.assignee == UNASSIGNED]
    report.stale = [
        s for s in ordered
        if not s.is_done and s.days_idle is not None and s.days_idle >= cfg.stale_days
    ]
    today = now.date()
    report.overdue = [
        s for s in ordered
        if not s.is_done and s.due and (_parse_dt(s.due) or now).date() < today
    ]
    report.no_estimate = [s for s in ordered if s.sp is None]
    return report


def _to_sp(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def fmt_sp(value: float | None) -> str:
    if value is None:
        return "—"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


# --------------------------------------------------------------------------
# Текстовый отчёт
# --------------------------------------------------------------------------

def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма существительного после числительного: 1 истории, 2 истории, 5 историй."""
    if count % 100 in range(11, 15):
        return many
    tail = count % 10
    if tail == 1:
        return one
    if tail in (2, 3, 4):
        return few
    return many


def shorten(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cell(text: str) -> str:
    """Ячейка markdown-таблицы: без переносов и без разделителя столбцов."""
    return " ".join(str(text).split()).replace("|", "/")


def child_list(children: list[Child], limit: int = 3, width: int = 34) -> str:
    names = [f"{c.key} {shorten(c.summary, width)}".strip() for c in children[:limit]]
    if len(children) > limit:
        names.append(f"+{len(children) - limit}")
    return ", ".join(names)


def done_text(story: Story) -> str:
    parts: list[str] = []
    if story.is_done:
        parts.append(f"история закрыта · {story.status}")
    done = story.done_children
    if done:
        parts.append(f"подзадачи {len(done)}/{len(story.children)}: {child_list(done)}")
    return " · ".join(parts) if parts else "—"


def left_text(story: Story) -> str:
    in_progress = [c for c in story.children if c.category == CATEGORY_PROGRESS]
    todo = [c for c in story.children if c.category == CATEGORY_TODO]
    parts: list[str] = []
    if in_progress:
        parts.append(f"в работе: {child_list(in_progress)}")
    if todo:
        parts.append(f"не начато: {child_list(todo)}")
    if story.is_done:
        return " · ".join(parts) if parts else "—"
    if not parts:
        # подзадач нет (или все закрыты) — остаток описывает сама история
        scope = "подзадачи закрыты, история" if story.children else "вся история"
        parts.append(f"{scope} · статус {story.status}")
    return " · ".join(parts)


def progress_line(report: Report) -> str:
    totals = report.totals
    parts = [
        f"задачи {totals[CATEGORY_DONE]}/{totals['all']} {CATEGORY_TITLES[CATEGORY_DONE].lower()}",
        f"{CATEGORY_TITLES[CATEGORY_PROGRESS].lower()} {totals[CATEGORY_PROGRESS]}",
        f"{CATEGORY_TITLES[CATEGORY_TODO].lower()} {totals[CATEGORY_TODO]}",
        f"SP {fmt_sp(report.sp_done)}/{fmt_sp(report.sp_total)}",
    ]
    day = report.day_of
    if day:
        parts.append(f"день {day[0]} из {day[1]}")
    return " · ".join(parts)


def render_text(report: Report) -> str:
    lines = [f"# Sprint Sync — {report.sprint_name}", ""]
    source = report.base_url or "[УТОЧНИТЬ base_url]"
    if report.board_id:
        source += f" · доска {report.board_id}"
    if report.jql:
        source += f" · JQL: {report.jql}"
    lines.append(f"Источник: {source} · синк {report.fetched_at}")
    if report.start or report.end:
        lines.append(f"Период: {fmt_date(report.start)} — {fmt_date(report.end)}")
    if report.goal:
        lines.append(f"Цель спринта (из JIRA): {report.goal}")
    lines += [f"Прогресс: {progress_line(report)}", ""]

    lines += ["| Команда | История | Что сделано | Что осталось |",
              "| --- | --- | --- | --- |"]
    for person in report.people:
        for index, story in enumerate(person.stories):
            name = person.name if index == 0 else ""
            sp = f" · {fmt_sp(story.sp)} SP" if story.sp is not None else ""
            title = f"{story.key} {shorten(story.summary, 52)}{sp}"
            lines.append(f"| {cell(name)} | {cell(title)} | {cell(done_text(story))} | {cell(left_text(story))} |")

    lines += ["", "Итого по исполнителям:"]
    for person in report.people:
        total = len(person.stories)
        lines.append(
            f"- {person.name}: закрыто {person.done_count} из {total} {plural(total, 'истории', 'историй', 'историй')} · "
            f"{fmt_sp(person.sp_done)}/{fmt_sp(person.sp_total)} SP"
        )

    attention = attention_items(report)
    if attention:
        lines += ["", "Требует внимания:"]
        lines += [f"- {item}" for item in attention]
    lines += ["", f"Все цифры — из JIRA на момент синка. Запись в трекер не выполнялась (только GET)."]
    return "\n".join(lines) + "\n"


def attention_items(report: Report) -> list[str]:
    items: list[str] = []
    if report.unassigned:
        items.append("без исполнителя: " + ", ".join(f"{s.key} {shorten(s.summary, 40)}" for s in report.unassigned))
    if report.stale:
        items.append(
            f"без движения ≥{report.stale_days} дн.: "
            + ", ".join(f"{s.key} ({s.days_idle} дн., {s.status})" for s in report.stale)
        )
    if report.overdue:
        items.append("просрочены: " + ", ".join(f"{s.key} (срок {fmt_date(s.due)})" for s in report.overdue))
    if report.no_estimate:
        items.append("без оценки SP: " + ", ".join(s.key for s in report.no_estimate))
    return items


def fmt_date(value: str) -> str:
    parsed = _parse_dt(value)
    return parsed.strftime("%d.%m.%Y") if parsed else (value or "—")


# --------------------------------------------------------------------------
# HTML-страница (самодостаточная: без внешних запросов, шрифтов и скриптов)
# --------------------------------------------------------------------------

CSS = """
:root {
  color-scheme: light;
  --bg: #f6f7f9; --card: #ffffff; --ink: #14181f; --muted: #616a78;
  --line: #e3e7ed; --accent: #2f6df6;
  --done: #1a7f4b; --done-bg: #e6f4ec;
  --prog: #9a6400; --prog-bg: #fdf1dc; --prog-fill: #e0a33a;
  --todo: #5a6472; --todo-bg: #eef0f4;
  --warn: #a33a2a; --warn-bg: #fbeae7;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0f1216; --card: #171b21; --ink: #e8ecf2; --muted: #9aa5b4;
    --line: #262c35; --accent: #6f9bff;
    --done: #63d18f; --done-bg: #16301f;
    --prog: #e0b15c; --prog-bg: #33270f; --prog-fill: #b8862f;
    --todo: #9aa5b4; --todo-bg: #21262e;
    --warn: #f08a76; --warn-bg: #351a15;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 56px; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.wrap { max-width: 1120px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 32px 0 12px; }
.muted { color: var(--muted); font-size: 13px; margin: 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
header.head { padding: 18px 20px; margin-bottom: 20px; }
.bar { height: 8px; border-radius: 99px; background: var(--todo-bg); overflow: hidden; margin-top: 14px; display: flex; }
.bar i { display: block; height: 100%; }
.bar .b-done { background: var(--done); }
.bar .b-prog { background: var(--prog-fill); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 10px; font-size: 13px; color: var(--muted); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tile { padding: 14px 16px; }
.tile b { display: block; font-size: 24px; font-weight: 650; letter-spacing: -0.02em; }
.tile span { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.people { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
.person { padding: 16px 18px; }
.person header { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.person h3 { margin: 0; font-size: 16px; }
.story { border-top: 1px solid var(--line); padding: 10px 0 2px; }
.story:first-of-type { border-top: 0; }
.story.is-done .title span:not(.chip) { color: var(--muted); }
.story .title { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.story .title a, .story .title span.key { font-weight: 600; color: var(--accent); text-decoration: none; }
.sub { margin: 6px 0 8px; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 6px; }
.sub li { font-size: 12px; padding: 2px 8px; border-radius: 99px; background: var(--todo-bg); color: var(--todo); }
.sub li.done { background: var(--done-bg); color: var(--done); text-decoration: line-through; }
.sub li.prog { background: var(--prog-bg); color: var(--prog); }
.chip { font-size: 12px; padding: 2px 9px; border-radius: 99px; white-space: nowrap; }
.chip.done { background: var(--done-bg); color: var(--done); }
.chip.prog { background: var(--prog-bg); color: var(--prog); }
.chip.todo { background: var(--todo-bg); color: var(--todo); }
.chip.warn { background: var(--warn-bg); color: var(--warn); }
.sp { font-size: 12px; color: var(--muted); white-space: nowrap; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
.scroll { overflow-x: auto; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
td.team { font-weight: 600; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
ul.plain { margin: 0; padding-left: 18px; }
ul.plain li { margin: 4px 0; }
.attention { padding: 14px 18px; border-left: 3px solid var(--warn); }
.toggle { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted);
  margin-left: auto; cursor: pointer; user-select: none; }
.toggle::before { content: "☐"; font-size: 15px; line-height: 1; }
#hide-done:checked ~ .wrap .toggle::before { content: "☑"; color: var(--accent); }
#hide-done { position: absolute; opacity: 0; pointer-events: none; }
#hide-done:checked ~ .wrap .story.is-done { display: none; }
#hide-done:checked ~ .wrap tr.is-done { display: none; }
footer { margin-top: 32px; font-size: 12px; color: var(--muted); }
@media (max-width: 560px) { body { padding: 16px 12px 40px; } h1 { font-size: 19px; } }
"""

CHIP_CLASS = {CATEGORY_DONE: "done", CATEGORY_PROGRESS: "prog", CATEGORY_TODO: "todo"}


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def story_link(story: Story) -> str:
    if story.url:
        return f'<a href="{esc(story.url)}">{esc(story.key)}</a>'
    return f'<span class="key">{esc(story.key)}</span>'


def render_html(report: Report) -> str:
    totals = report.totals
    all_count = max(totals["all"], 1)
    done_pct = round(totals[CATEGORY_DONE] * 100 / all_count)
    prog_pct = round(totals[CATEGORY_PROGRESS] * 100 / all_count)
    day = report.day_of

    source = esc(report.base_url or "источник не указан")
    if report.base_url:
        source = f'<a href="{esc(report.base_url)}">{esc(report.base_url)}</a>'
    meta_bits = [f"синк {esc(report.fetched_at)}", f"источник {source}"]
    if report.board_id:
        meta_bits.insert(0, f"доска {esc(report.board_id)}")
    if report.start or report.end:
        meta_bits.insert(0, f"{esc(fmt_date(report.start))} — {esc(fmt_date(report.end))}")

    out: list[str] = []
    out.append("<!doctype html>")
    out.append('<html lang="ru"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f"<title>Sprint Sync — {esc(report.sprint_name)}</title>")
    out.append(f"<style>{CSS}</style></head><body>")
    out.append('<input type="checkbox" id="hide-done">')
    out.append('<div class="wrap">')

    out.append('<header class="head card">')
    out.append(f"<h1>Sprint Sync — {esc(report.sprint_name)}</h1>")
    out.append(f'<p class="muted">{" · ".join(meta_bits)}</p>')
    if report.goal:
        out.append(f'<p class="muted">Цель спринта из JIRA: {esc(report.goal)}</p>')
    out.append('<div class="bar">'
               f'<i class="b-done" style="width:{done_pct}%"></i>'
               f'<i class="b-prog" style="width:{prog_pct}%"></i></div>')
    legend = [f"{CATEGORY_TITLES[key]} {totals[key]}"
              for key in (CATEGORY_DONE, CATEGORY_PROGRESS, CATEGORY_TODO)]
    legend.append(f"SP {fmt_sp(report.sp_done)} из {fmt_sp(report.sp_total)}")
    if day:
        legend.append(f"День {day[0]} из {day[1]}")
    out.append('<div class="legend">' + "".join(f"<span>{esc(x)}</span>" for x in legend))
    out.append('<label class="toggle" for="hide-done">скрыть закрытые истории</label></div>')
    out.append("</header>")

    out.append('<section class="tiles">')
    tiles = [
        (str(totals["all"]), plural(totals["all"], "история в спринте", "истории в спринте",
                                    "историй в спринте")),
        (str(totals[CATEGORY_DONE]), CATEGORY_TITLES[CATEGORY_DONE].lower()),
        (str(totals[CATEGORY_PROGRESS]), CATEGORY_TITLES[CATEGORY_PROGRESS].lower()),
        (str(totals[CATEGORY_TODO]), CATEGORY_TITLES[CATEGORY_TODO].lower()),
        (f"{fmt_sp(report.sp_done)}/{fmt_sp(report.sp_total)}", "SP закрыто"),
    ]
    if day:
        tiles.append((f"{day[0]}/{day[1]}", "день спринта"))
    for value, caption in tiles:
        out.append(f'<div class="tile card"><b>{esc(value)}</b><span>{esc(caption)}</span></div>')
    out.append("</section>")

    attention = attention_items(report)
    if attention:
        out.append("<h2>Требует внимания</h2>")
        out.append('<section class="attention card"><ul class="plain">')
        out.extend(f"<li>{esc(item)}</li>" for item in attention)
        out.append("</ul></section>")

    out.append("<h2>По исполнителям</h2>")
    out.append('<section class="people">')
    for person in report.people:
        out.append('<article class="person card"><header>')
        out.append(f"<h3>{esc(person.name)}</h3>")
        out.append(f'<span class="sp">{person.done_count}/{len(person.stories)} закрыто · '
                   f"{esc(fmt_sp(person.sp_done))}/{esc(fmt_sp(person.sp_total))} SP</span>")
        out.append("</header>")
        for story in person.stories:
            klass = "story is-done" if story.is_done else "story"
            out.append(f'<div class="{klass}"><div class="title">{story_link(story)}'
                       f"<span>{esc(story.summary)}</span>"
                       f'<span class="chip {CHIP_CLASS[story.category]}">{esc(story.status)}</span>')
            if story.sp is not None:
                out.append(f'<span class="sp">{esc(fmt_sp(story.sp))} SP</span>')
            if not story.is_done and story.days_idle is not None and story.days_idle >= report.stale_days:
                out.append(f'<span class="chip warn">без движения {story.days_idle} дн.</span>')
            out.append("</div>")
            if story.children:
                out.append('<ul class="sub">')
                for child in story.children:
                    out.append(f'<li class="{CHIP_CLASS[child.category]}">{esc(child.key)} '
                               f"{esc(shorten(child.summary, 46))}</li>")
                out.append("</ul>")
            out.append("</div>")
        out.append("</article>")
    out.append("</section>")

    out.append("<h2>Краткий отчёт</h2>")
    out.append('<section class="card scroll"><table><thead><tr>'
               "<th>Команда</th><th>История</th><th>Что сделано</th><th>Что осталось</th>"
               "</tr></thead><tbody>")
    for person in report.people:
        for index, story in enumerate(person.stories):
            row_class = ' class="is-done"' if story.is_done else ""
            out.append(f"<tr{row_class}>")
            if index == 0:
                out.append(f'<td class="team" rowspan="{len(person.stories)}">{esc(person.name)}</td>')
            sp = f' <span class="sp">{esc(fmt_sp(story.sp))} SP</span>' if story.sp is not None else ""
            out.append(f"<td>{story_link(story)} {esc(story.summary)}{sp}</td>")
            out.append(f"<td>{esc(done_text(story))}</td>")
            out.append(f"<td>{esc(left_text(story))}</td></tr>")
    out.append("</tbody></table></section>")

    out.append("<footer>Данные получены из JIRA только чтением (GET), запись в трекер не выполнялась. "
               f"Страница сгенерирована {esc(report.fetched_at)} командой /sprint-sync.</footer>")
    out.append("</div></body></html>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sprint_sync.py",
        description="Выгрузка актуального состояния спринта из JIRA: HTML-страница + текстовая таблица.",
    )
    parser.add_argument("--profile", default=".claude/domain-profile.md",
                        help="доменный профиль с секцией ## jira (по умолчанию .claude/domain-profile.md)")
    parser.add_argument("--base-url", default="", help="переопределить jira.base_url")
    parser.add_argument("--board", default="", help="переопределить jira.board_id")
    parser.add_argument("--jql", default="", help="произвольный JQL вместо активного спринта доски")
    parser.add_argument("--sprint", default="", help="имя спринта (если активных несколько)")
    parser.add_argument("--out-dir", default="", help="каталог для артефактов")
    parser.add_argument("--html", dest="html_path", default="", help="путь HTML-страницы")
    parser.add_argument("--text", dest="text_path", default="", help="путь текстового отчёта")
    parser.add_argument("--from-json", default="", help="офлайн-рендер из сохранённого payload")
    parser.add_argument("--save-raw", default="", help="сохранить сырой payload JIRA в файл")
    parser.add_argument("--stale-days", type=int, default=None,
                        help=f"порог «без движения», дней (по умолчанию {DEFAULT_STALE_DAYS})")
    parser.add_argument("--timeout", type=int, default=30, help="таймаут HTTP-запроса, сек")
    parser.add_argument("--quiet", action="store_true", help="не печатать текстовый отчёт в stdout")
    return parser.parse_args(argv)


def run(argv: list[str], env: dict[str, str] | None = None) -> int:
    env = dict(os.environ if env is None else env)
    args = parse_args(argv)
    cfg = build_config(args, env)
    cfg.html_path = args.html_path
    cfg.text_path = args.text_path

    if cfg.from_json:
        try:
            with open(cfg.from_json, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Не читается сохранённый ответ JIRA ({cfg.from_json}): {error}", file=sys.stderr)
            return EXIT_CONFIG
    else:
        if not cfg.base_url:
            print("Не задан jira.base_url: заполни секцию ## jira в domain-profile или передай --base-url.",
                  file=sys.stderr)
            return EXIT_CONFIG
        if not cfg.board_id and not cfg.jql:
            print("Не задан ни jira.board_id, ни jira.jql — непонятно, какой спринт выгружать.", file=sys.stderr)
            return EXIT_CONFIG
        try:
            client = JiraClient(cfg.base_url, auth_header(env), cfg.timeout, env.get("JIRA_CA_BUNDLE", ""))
            payload = fetch_payload(client, cfg)
        except JiraConfigError as error:
            print(str(error), file=sys.stderr)
            return EXIT_CONFIG
        except JiraError as error:
            print(str(error), file=sys.stderr)
            return EXIT_API

    report = build_report(payload, cfg)
    cfg = resolve_out_paths(cfg, report.sprint_name)

    text = render_text(report)
    page = render_html(report)
    for path, content in ((cfg.text_path, text), (cfg.html_path, page)):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
    if cfg.save_raw:
        directory = os.path.dirname(cfg.save_raw)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(cfg.save_raw, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(text)
    print(f"HTML: {cfg.html_path}", file=sys.stderr)
    print(f"Текст: {cfg.text_path}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
