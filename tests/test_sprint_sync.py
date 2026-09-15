"""Тесты sprint-sync: офлайн-рендер из фикстуры, без сети.

Фикстура `fixtures/jira-sample/sprint-2026Q3-S7.json` — сохранённый ответ JIRA
(тот же домен, что demo-domain). Сеть не требуется: всё идёт через --from-json.
"""
import importlib.util
import json
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
FIXTURE = os.path.join(TESTS_DIR, "fixtures", "jira-sample", "sprint-2026Q3-S7.json")
SCRIPT = os.path.join(ROOT, ".claude", "skills", "sprint-sync", "scripts", "sprint_sync.py")

_spec = importlib.util.spec_from_file_location("sprint_sync", SCRIPT)
sprint_sync = importlib.util.module_from_spec(_spec)
sys.modules["sprint_sync"] = sprint_sync
_spec.loader.exec_module(sprint_sync)


def _report():
    payload = json.load(open(FIXTURE, encoding="utf-8"))
    return sprint_sync.build_report(payload, sprint_sync.Config())


def _story(report, key):
    return next(s for s in report.stories if s.key == key)


# --- модель -----------------------------------------------------------------

def test_subtasks_do_not_become_stories():
    report = _report()
    keys = {s.key for s in report.stories}
    assert "GDSLV-1503" not in keys  # подзадача крепится к истории, а не стоит отдельной строкой
    assert len(report.stories) == 6


def test_full_subtasks_attach_to_parent():
    children = {c.key for c in _story(_report(), "GDSLV-1501").children}
    assert children == {"GDSLV-1502", "GDSLV-1503", "GDSLV-1504"}


def test_embedded_subtask_stubs_used_when_full_issue_absent():
    # GDSLV-1511/1512 приходят только внутри fields.subtasks родителя
    children = {c.key for c in _story(_report(), "GDSLV-1510").children}
    assert children == {"GDSLV-1511", "GDSLV-1512"}


def test_status_category_drives_classification():
    report = _report()
    assert _story(report, "GDSLV-1456").category == sprint_sync.CATEGORY_DONE
    assert _story(report, "GDSLV-1501").category == sprint_sync.CATEGORY_PROGRESS
    assert _story(report, "GDSLV-1510").category == sprint_sync.CATEGORY_TODO


def test_done_statuses_fallback_without_status_category():
    payload = {"meta": {}, "sprint": {"name": "S1"}, "issues": [{
        "key": "X-1",
        "fields": {"summary": "s", "status": {"name": "Закрыто"},
                   "issuetype": {"name": "Story", "subtask": False}},
    }]}
    cfg = sprint_sync.Config(done_statuses=("закрыто",))
    assert sprint_sync.build_report(payload, cfg).stories[0].category == sprint_sync.CATEGORY_DONE


def test_unassigned_story_is_not_given_an_owner():
    report = _report()
    assert _story(report, "GDSLV-1602").assignee == sprint_sync.UNASSIGNED
    assert report.unassigned and report.unassigned[0].key == "GDSLV-1602"
    assert report.people[-1].name == sprint_sync.UNASSIGNED  # без исполнителя — последней группой


def test_totals_count_only_stories():
    report = _report()
    totals = report.totals
    assert (totals["all"], totals[sprint_sync.CATEGORY_DONE]) == (6, 2)
    assert (report.sp_done, report.sp_total) == (6, 22)
    assert report.day_of == (6, 13)


def test_detectors_on_fixture():
    report = _report()
    assert {s.key for s in report.stale} == {"GDSLV-1510", "GDSLV-1602"}
    assert [s.key for s in report.overdue] == ["GDSLV-1152"]
    assert [s.key for s in report.no_estimate] == ["GDSLV-1602"]


def test_missing_story_points_stay_empty():
    assert _story(_report(), "GDSLV-1602").sp is None
    assert sprint_sync.fmt_sp(None) == "—"


# --- текстовый отчёт --------------------------------------------------------

def test_done_and_left_columns():
    report = _report()
    story = _story(report, "GDSLV-1501")
    assert sprint_sync.done_text(story) == "подзадачи 1/3: GDSLV-1502 [SA] Изучить контракт P24"
    left = sprint_sync.left_text(story)
    assert "в работе: GDSLV-1503" in left and "не начато: GDSLV-1504" in left

    closed = _story(report, "GDSLV-1456")
    assert sprint_sync.done_text(closed).startswith("история закрыта")
    assert sprint_sync.left_text(closed) == "—"

    untouched = _story(report, "GDSLV-1152")
    assert sprint_sync.done_text(untouched) == "—"
    assert sprint_sync.left_text(untouched) == "вся история · статус In Progress"


def test_text_report_shape():
    text = sprint_sync.render_text(_report())
    assert "| Команда | История | Что сделано | Что осталось |" in text
    assert "день 6 из 13" in text
    assert "без движения ≥3 дн.: GDSLV-1510" in text
    assert text.count("| BE-2 |") == 1  # имя исполнителя не дублируется по строкам


def test_cell_escapes_table_separator():
    assert sprint_sync.cell("a | b\nc") == "a / b c"


# --- HTML -------------------------------------------------------------------

def test_html_is_self_contained_and_complete():
    page = sprint_sync.render_html(_report())
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    for block in ("Требует внимания", "По исполнителям", "Краткий отчёт",
                  "<th>Что осталось</th>", "prefers-color-scheme"):
        assert block in page
    assert "src=\"http" not in page and "<script" not in page  # без внешних запросов и скриптов
    assert 'href="https://jira.demo.local/browse/GDSLV-1501"' in page


def test_html_escapes_user_content():
    payload = json.load(open(FIXTURE, encoding="utf-8"))
    payload["issues"][0]["fields"]["summary"] = '<img src=x onerror="alert(1)">'
    page = sprint_sync.render_html(sprint_sync.build_report(payload, sprint_sync.Config()))
    assert "<img src=x" not in page and "&lt;img src=x" in page


# --- CLI и профиль ----------------------------------------------------------

def test_profile_parsing():
    sections = sprint_sync.parse_profile(os.path.join(ROOT, "domain-profile.template.md"))
    assert "jira" in sections
    assert sections["jira"]["story_points_field"] == "customfield_10016"
    assert sections["jira"]["sync_output_dir"] == "GROUND/SPRINTS/{sprint}/sync"  # комментарий отрезан
    assert "base_url" not in sections["jira"]  # незаполненный [УТОЧНИТЬ …] не считается значением
    assert sections["capacity"]["focus_factor"] == "0.7"


def test_run_writes_both_artifacts(tmp_path, capsys):
    code = sprint_sync.run(["--from-json", FIXTURE, "--out-dir", str(tmp_path)], env={})
    assert code == sprint_sync.EXIT_OK
    assert (tmp_path / "sprint-sync-2026Q3-S7.html").exists()
    assert (tmp_path / "sprint-sync-2026Q3-S7.md").exists()
    assert "| Команда | История |" in capsys.readouterr().out


def test_run_without_credentials_stops_before_network(tmp_path, capsys):
    code = sprint_sync.run(
        ["--base-url", "https://jira.invalid", "--board", "42", "--out-dir", str(tmp_path)], env={}
    )
    assert code == sprint_sync.EXIT_CONFIG
    assert "JIRA_TOKEN" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_run_with_unreadable_payload_reports_config_error(tmp_path, capsys):
    code = sprint_sync.run(["--from-json", str(tmp_path / "нет.json"), "--out-dir", str(tmp_path)], env={})
    assert code == sprint_sync.EXIT_CONFIG
    assert "Не читается сохранённый ответ JIRA" in capsys.readouterr().err


def test_run_without_base_url_reports_config_error(tmp_path, capsys):
    code = sprint_sync.run(["--profile", "нет-такого-файла.md", "--out-dir", str(tmp_path)], env={})
    assert code == sprint_sync.EXIT_CONFIG
    assert "base_url" in capsys.readouterr().err


# --- сетевой путь на локальной заглушке JIRA ---------------------------------

def _stub_server(sprints, issue_pages, seen):
    """Поднимает локальную заглушку JIRA-эндпоинтов. Возвращает (server, thread)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import urllib.parse as urlparse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse.urlparse(self.path)
            query = urlparse.parse_qs(parsed.query)
            seen.append((parsed.path, query, self.headers.get("Authorization")))
            if parsed.path.endswith("/sprint"):
                body = sprints
            else:
                body = issue_pages[int(query.get("startAt", ["0"])[0])]
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _issue(key, summary, status_key, assignee):
    return {"key": key, "fields": {
        "summary": summary,
        "status": {"name": status_key, "statusCategory": {"key": status_key}},
        "assignee": {"displayName": assignee},
        "issuetype": {"name": "Story", "subtask": False},
        "updated": "2026-07-24T09:00:00.000+03:00",
    }}


def test_board_mode_fetches_paginates_and_authenticates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    sprints = {"values": [{"id": 77, "name": "2026Q3-S7", "state": "active"}], "isLast": True}
    pages = {
        0: {"total": 2, "issues": [_issue("X-1", "первая", "done", "BE-1")]},
        1: {"total": 2, "issues": [_issue("X-2", "вторая", "new", "FE-1")]},
    }
    seen: list = []
    server, _ = _stub_server(sprints, pages, seen)
    try:
        code = sprint_sync.run(
            ["--base-url", f"http://127.0.0.1:{server.server_port}", "--board", "42",
             "--out-dir", str(tmp_path), "--save-raw", str(tmp_path / "raw.json")],
            env={"JIRA_TOKEN": "s3cret", "no_proxy": "127.0.0.1"},
        )
    finally:
        server.shutdown()

    assert code == sprint_sync.EXIT_OK
    assert [path for path, _, _ in seen] == [
        "/rest/agile/1.0/board/42/sprint",
        "/rest/agile/1.0/sprint/77/issue",
        "/rest/agile/1.0/sprint/77/issue",
    ]
    assert {auth for _, _, auth in seen} == {"Bearer s3cret"}   # токен уходит только в заголовке
    text = capsys.readouterr().out
    assert "X-1" in text and "X-2" in text                      # обе страницы выдачи собраны
    assert (tmp_path / "sprint-sync-2026Q3-S7.html").exists()
    assert json.load(open(tmp_path / "raw.json", encoding="utf-8"))["sprint"]["id"] == 77


def test_several_active_sprints_stop_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    sprints = {"values": [{"id": 1, "name": "S7"}, {"id": 2, "name": "S8"}], "isLast": True}
    seen: list = []
    server, _ = _stub_server(sprints, {}, seen)
    try:
        code = sprint_sync.run(
            ["--base-url", f"http://127.0.0.1:{server.server_port}", "--board", "42",
             "--out-dir", str(tmp_path)],
            env={"JIRA_TOKEN": "s3cret"},
        )
    finally:
        server.shutdown()
    assert code == sprint_sync.EXIT_CONFIG
    assert "уточни --sprint" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
