import importlib.util
import sys
from pathlib import Path

# Имя файла с дефисами не импортируется как модуль, а переименовывать его
# нельзя: команды навыка зовут скрипт по этому имени.
SCRIPTS = Path(__file__).resolve().parents[1] / ".claude/skills/sprint-result/scripts"
_spec = importlib.util.spec_from_file_location(
    "sprint_report_style_lint", SCRIPTS / "sprint-report-style-lint.py")
lint_mod = importlib.util.module_from_spec(_spec)
# Регистрация до exec обязательна: @dataclass ищет модуль класса в sys.modules.
sys.modules[_spec.name] = lint_mod
_spec.loader.exec_module(lint_mod)


def _codes(text, tmp_path):
    f = tmp_path / "report.md"
    f.write_text(text, encoding="utf-8")
    return {f_.code for f_ in lint_mod.lint(f)}


def test_ideal_report_is_clean(tmp_path):
    ideal = SCRIPTS.parent / "examples/ideal_sprint_report.md"
    assert lint_mod.lint(ideal) == []


def test_stop_word_flagged(tmp_path):
    assert "SW002" in _codes("Загрузчик обеспечивает загрузку каталога.", tmp_path)


def test_hedge_flagged(tmp_path):
    assert "HG002" in _codes("В некоторых случаях события не доезжают.", tmp_path)


def test_meta_comment_flagged(tmp_path):
    assert "MC002" in _codes("Важно понимать, что стрим не двинулся.", tmp_path)


def test_empty_intensifier_flagged(tmp_path):
    assert "QF007" in _codes("Задача успешно выполнена.", tmp_path)


def test_verbal_passive_flagged(tmp_path):
    # caveman §5: глагол вместо отглагольного пассива.
    assert "TA002" in _codes("Была произведена выкатка на прод.", tmp_path)


def test_long_heading_flagged(tmp_path):
    long_head = ("### СТРИМ: Перенос нагрузки с легаси-платформы на новое ядро "
                 "силами двух команд\n")
    assert "CV001" in _codes(long_head, tmp_path)


def test_short_heading_passes(tmp_path):
    assert "CV001" not in _codes("### СТРИМ: Перенос нагрузки\n", tmp_path)


def test_overlong_cell_flagged(tmp_path):
    cell = " ".join(["слово"] * 50)
    assert "CV002" in _codes(f"| Задача | {cell} | 100% |\n", tmp_path)


def test_annotation_quote_is_skipped(tmp_path):
    # Аннотация эталона цитирует, а не пишет: срабатывание на ней ложное.
    assert _codes("> Отчёт обеспечивает наглядность.\n", tmp_path) == set()


def test_fenced_block_is_skipped(tmp_path):
    assert _codes("```\nобеспечивает\n```\n", tmp_path) == set()
