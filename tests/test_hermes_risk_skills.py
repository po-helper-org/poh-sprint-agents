"""Навыки рисков Hermes (hermes/quarter-risks, hermes/sprint-risk-notes): установщик ставит их в профиль со
ссылкой на знание команды из ежедневной рефлексии (team-pulse + уроки PO), без пустых подстановок."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = {"quarter-risks": "install-quarter-risks.sh", "sprint-risk-notes": "install-sprint-risk-notes.sh"}


class RiskSkillsReadTeamPulse(unittest.TestCase):
    def install(self, skill, script, mode="", widget_config=None, reports=True):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "hermes"
            prof = home / "profiles" / "po-gds"
            (prof / "cron").mkdir(parents=True)
            # задача cron уже есть — установщик не зовёт hermes, только ставит навык
            (prof / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "j1", "name": f"{skill}-gds"}]}))
            env = dict(os.environ, HERMES_HOME=str(home), HERMES="/bin/false", AGENTS_DIR=str(ROOT),
                       WIDGET_DIR=str(Path(d) / "widget"), WIDGET_CONFIG=str(Path(d) / "widget-config.json"))
            env.pop("REPORTS_DIR", None)
            env.pop("CONFIG", None)
            if reports:
                env["REPORTS_DIR"] = str(Path(d) / "reports")
            if widget_config is not None:
                Path(env["WIDGET_CONFIG"]).write_text(json.dumps(widget_config))
            args = ["bash", str(ROOT / "hermes" / script)] + ([mode] if mode else []) + ["po-gds:gds:0 9 * * 1"]
            p = subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)
            out = p.stdout + p.stderr
            installed = prof / "skills" / skill / "SKILL.md"
            text = installed.read_text(encoding="utf-8") if installed.exists() else ""
            return p.returncode, out, text, str(prof / "skills" / "team-pulse")

    def test_installed_skill_points_to_profile_team_pulse_and_po_feedback(self):
        for skill, script in SKILLS.items():
            with self.subTest(skill=skill):
                code, out, text, pulse = self.install(skill, script)
                self.assertEqual(0, code, out)
                self.assertNotIn("{{", text)
                self.assertIn(f"{pulse}/SKILL.md", text)
                self.assertIn(f"{pulse}/references/po-feedback.md", text)
                self.assertIn("уроки PO — обязательные правила", text)
                self.assertIn("только из facts" if skill == "quarter-risks" else "сверь с Jira", text)

    def test_paths_come_from_widget_config(self):
        # на сервере снимок и конфиг колоды — в ~/.local/share, а не в клонах: умолчания из настроек виджета
        cfg = {"observe_workspace": "/srv/obs/workspace", "workspace": "/srv/biz/workspace"}
        code, out, text, _ = self.install("sprint-risk-notes", SKILLS["sprint-risk-notes"], widget_config=cfg, reports=False)
        self.assertEqual(0, code, out)
        self.assertIn("C=/srv/biz/workspace/sprint-report.config.toml", text)
        self.assertIn("/srv/obs/workspace/reports/sprint-risk-notes.drafts/gds.json", text)
        code, out, text, _ = self.install("quarter-risks", SKILLS["quarter-risks"], widget_config=cfg, reports=False)
        self.assertIn("R=/srv/obs/workspace/reports", text)

    def test_without_widget_config_falls_back_to_clone_paths(self):
        code, out, text, _ = self.install("sprint-risk-notes", SKILLS["sprint-risk-notes"], reports=False)
        self.assertEqual(0, code, out)
        self.assertIn("/widget/workspace/sprint-report.config.toml", text)
        self.assertIn("poh-widget-sprint-observe/workspace/reports", text)

    def test_team_pulse_read_is_inside_step_1_that_cron_prompts_run(self):
        # cron-промты велят пройти «шаги 1–7» — чтение рефлексии не должно быть отдельным шагом 0
        for skill in SKILLS:
            text = (ROOT / "hermes" / skill / "SKILL.md").read_text(encoding="utf-8")
            step1 = text.split("\n1. ", 1)[1].split("\n2. ", 1)[0]
            self.assertIn("{{PULSE}}/SKILL.md", step1, skill)


if __name__ == "__main__":
    unittest.main()
