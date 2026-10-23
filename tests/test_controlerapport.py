import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCRIPT = REPOSITORY_ROOT / ".github" / "workflows" / "controlerapport.mjs"
FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "controlerapport"

ALL_SUCCESS = {
    "OUTCOME_RAW_LINKS": "success",
    "OUTCOME_RESPEC": "success",
    "OUTCOME_HEADER_LINKS": "",
    "OUTCOME_HTML": "success",
    "OUTCOME_WCAG": "success",
    "OUTCOME_LINKS": "success",
    "JOB_STATUS": "success",
    "EVENT_NAME": "push",
}

WCAG_VIOLATION = [
    {
        "url": "http://localhost:8080/snapshot.html",
        "id": "color-contrast",
        "impact": "serious",
        "description": "Ensure the contrast between foreground and background colors meets WCAG 2 AA",
        "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
        "nodes": [
            {"target": ["#intro > p > a"], "html": "<a>", "failureSummary": ""},
            {"target": [".note"], "html": "<div>", "failureSummary": ""},
        ],
    }
]


class ReportRun:
    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.workspace = root / "workspace"
        self.output = root / "nl-respec-validation"
        (self.workspace / "publication-validation").mkdir(parents=True)
        self.output.mkdir()
        shutil.copy(FIXTURES / "index.html", self.workspace / "publication-validation" / "index.html")
        self.write("wcag-report.json", "[]")
        self.write("link-check.json", json.dumps({"error_map": {}}))

    def write(self, name: str, content: str) -> None:
        (self.output / name).write_text(content, encoding="utf-8")

    def copy_fixture(self, name: str) -> None:
        shutil.copy(FIXTURES / name, self.output / name)

    def run(self, **outcomes: str) -> subprocess.CompletedProcess:
        environment = {key: value for key, value in os.environ.items() if key != "GITHUB_STEP_SUMMARY"}
        environment.update(ALL_SUCCESS)
        environment.update(outcomes)
        environment["WORKSPACE"] = str(self.workspace)
        return subprocess.run(
            ["node", str(REPORT_SCRIPT), str(self.output)],
            env=environment,
            capture_output=True,
            text=True,
        )

    def report(self) -> str:
        return (self.output / "controlerapport.md").read_text(encoding="utf-8")

    def close(self) -> None:
        self._temporary.cleanup()


class ControlerapportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = ReportRun()
        self.addCleanup(self.report.close)

    def test_all_checks_passing_is_ready_for_publication(self) -> None:
        result = self.report.run()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report.report()
        self.assertIn("✅ **Publicatiegereed: ja**", report)
        self.assertIn("| HTML | ✅ geslaagd | ja |", report)
        self.assertNotIn("<details", report)
        # Optionele controle zonder script in de documentrepo blijft weg.
        self.assertNotIn("Voorblad", report)

    def test_html_findings_block_and_point_to_the_section(self) -> None:
        self.report.copy_fixture("html.log")

        result = self.report.run(OUTCOME_HTML="failure")

        self.assertEqual(result.returncode, 1)
        report = self.report.report()
        self.assertIn("❌ **Publicatiegereed: nee** (1 blokkerende controle)", report)
        self.assertIn("| HTML | ❌ 9 fouten | ja |", report)
        self.assertIn("Duplicate ID “dubbel”.", report)
        self.assertIn('sectie "Intro" (regel 9 van snapshot.html)', report)
        self.assertIn("Images: internal image media/missing.png does not exist", report)
        self.assertIn("::error title=HTML::", result.stdout)

    def test_all_findings_are_reported_in_one_run(self) -> None:
        self.report.copy_fixture("html.log")
        self.report.copy_fixture("respec.log")
        self.report.write("wcag-report.json", json.dumps(WCAG_VIOLATION))
        root = self.report.workspace / "publication-validation"
        self.report.write(
            "link-check.json",
            json.dumps(
                {
                    "error_map": {
                        "./index.html": [
                            {"url": (root / "media" / "weg.html").as_uri(), "status": {"text": "Cannot find file"}}
                        ]
                    }
                }
            ),
        )

        result = self.report.run(OUTCOME_HTML="failure", OUTCOME_LINKS="failure")

        self.assertEqual(result.returncode, 1)
        report = self.report.report()
        self.assertIn("(2 blokkerende controles)", report)
        self.assertIn("| ReSpec | ⚠️ 2 fouten, 3 waarschuwingen | nee |", report)
        self.assertIn('Reference "[BESTAATNIET]" not found.', report)
        self.assertIn("Tip: Search for", report)
        self.assertNotIn("\u001b[", report)
        self.assertIn("| WCAG 2.2 (axe) | ⚠️ 2 waarschuwingen | nee |", report)
        self.assertIn("(2×): serious:", report)
        self.assertIn("Cannot find file: media/weg.html", report)

    def test_non_blocking_findings_keep_the_build_green(self) -> None:
        self.report.copy_fixture("respec.log")
        self.report.write("wcag-report.json", json.dumps(WCAG_VIOLATION))

        result = self.report.run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("✅ **Publicatiegereed: ja**", self.report.report())

    def test_raw_links_only_block_a_release(self) -> None:
        self.report.write("raw-links.txt", '12:<script src="https://raw.githubusercontent.com/x/y/a.js"></script>\n')

        push = self.report.run()
        self.assertEqual(push.returncode, 0, push.stderr)
        self.assertIn("⚠️ 1 waarschuwing | nee |", self.report.report())

        release = self.report.run(EVENT_NAME="release", OUTCOME_RAW_LINKS="failure")
        self.assertEqual(release.returncode, 1)
        self.assertIn("❌ 1 fout | ja |", self.report.report())
        self.assertIn("index.html regel 12: &lt;script", self.report.report())

    def test_header_link_error_is_shown_when_the_check_runs(self) -> None:
        self.report.write(
            "header-links.log",
            "file:///x.mjs:9\n  throw new Error(\"...\");\n  ^\n\n"
            "Error: De GitHub-issueslink op het voorblad is nog Engelstalig.\n    at file:///x.mjs:9:9\n",
        )

        result = self.report.run(OUTCOME_HEADER_LINKS="failure")

        self.assertEqual(result.returncode, 1)
        self.assertIn("De GitHub-issueslink op het voorblad is nog Engelstalig.", self.report.report())

    def test_failed_check_without_output_points_to_the_log(self) -> None:
        result = self.report.run(OUTCOME_LINKS="failure")

        self.assertEqual(result.returncode, 1)
        self.assertIn("| Links | ❌ mislukt | ja |", self.report.report())
        self.assertIn("zie de log van deze stap", self.report.report())

    def test_unreadable_wcag_report_is_shown_but_not_blocking(self) -> None:
        self.report.write("wcag-report.json", json.dumps({"error": "WCAG-check mislukt (axe-cli)."}))

        result = self.report.run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| WCAG 2.2 (axe) | ❌ mislukt | nee |", self.report.report())
        self.assertIn("WCAG-check mislukt (axe-cli).", self.report.report())

    def test_aborted_build_is_never_ready(self) -> None:
        result = self.report.run(
            OUTCOME_RESPEC="failure",
            OUTCOME_HTML="skipped",
            OUTCOME_WCAG="skipped",
            OUTCOME_LINKS="skipped",
            JOB_STATUS="failure",
        )

        self.assertEqual(result.returncode, 1)
        report = self.report.report()
        self.assertIn("❌ **Publicatiegereed: nee**", report)
        self.assertIn("De build is afgebroken", report)
        self.assertIn("| HTML | ⏭️ niet uitgevoerd | ja |", report)

    def test_report_is_written_to_the_job_summary(self) -> None:
        with tempfile.NamedTemporaryFile("r", suffix=".md") as summary:
            os.environ["GITHUB_STEP_SUMMARY"] = summary.name
            try:
                environment = dict(os.environ, **ALL_SUCCESS, WORKSPACE=str(self.report.workspace))
                subprocess.run(
                    ["node", str(REPORT_SCRIPT), str(self.report.output)],
                    env=environment,
                    check=True,
                    capture_output=True,
                )
            finally:
                del os.environ["GITHUB_STEP_SUMMARY"]
            self.assertIn("## Controlerapport", Path(summary.name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
