import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "build.yml"
PUBLISH_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "publish.yml"
RESPEC_CONFIG = REPOSITORY_ROOT / "js" / "config.js"


def build_steps() -> list[dict]:
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["build"]["steps"]


def find_step(name: str) -> dict | None:
    return next((step for step in build_steps() if step.get("name") == name), None)


def publish_steps() -> list[dict]:
    workflow = yaml.safe_load(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["release"]["steps"]


def find_publish_step(name: str) -> dict | None:
    return next((step for step in publish_steps() if step.get("name") == name), None)


class PublicationPreflightTest(unittest.TestCase):
    def test_local_post_processors_preserve_organisation_processors(self) -> None:
        config = RESPEC_CONFIG.read_text(encoding="utf-8")

        self.assertIn(
            "...(organisationConfig.postProcess ?? [])",
            config,
            "Lokale post-processors mogen de Mermaid-processor uit de organisatieconfig niet vervangen.",
        )

    def test_snapshot_uses_pinned_respec_on_supported_node(self) -> None:
        setup = find_step("Set up Node.js")
        generate = find_step("Generate HTML snapshot")

        self.assertIsNotNone(setup, "De build moet expliciet een ondersteunde Node-versie installeren.")
        self.assertTrue(setup["uses"].startswith("actions/setup-node@"))
        self.assertEqual(str(setup["with"]["node-version"]), "24")
        self.assertIsNotNone(generate)
        self.assertIn("npx --yes respec@37.3.2", generate["run"])

    def test_validation_tree_keeps_assets_but_excludes_respec_source_fragments(self) -> None:
        step = find_step("Prepare publication for validation")
        self.assertIsNotNone(step, "De build moet het toekomstige publicatiepakket voorbereiden.")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "snapshot.html").write_text("snapshot", encoding="utf-8")
            for asset_directory in ("data", "media", "js", "css"):
                target = source / asset_directory
                target.mkdir()
                (target / "asset.txt").write_text(asset_directory, encoding="utf-8")
                fragments = target / "nested"
                fragments.mkdir()
                (fragments / "model.respec.html").write_text("fragment", encoding="utf-8")
                (fragments / "model.respec.catalog.xhtml").write_text(
                    "catalog", encoding="utf-8"
                )

            stale = source / "publication-validation"
            stale.mkdir(parents=True)
            (stale / "stale.html").write_text("stale", encoding="utf-8")

            environment = os.environ.copy()
            environment["GITHUB_WORKSPACE"] = str(source)
            subprocess.run(
                ["bash", "-euo", "pipefail", "-c", step["run"]],
                cwd=source,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            publication = source / "publication-validation"
            self.assertEqual((publication / "index.html").read_text(encoding="utf-8"), "snapshot")
            self.assertFalse((publication / "snapshot.html").exists())
            self.assertFalse((publication / "stale.html").exists())
            self.assertFalse((source / ".checks").exists())
            for asset_directory in ("data", "media", "js", "css"):
                self.assertEqual(
                    (publication / asset_directory / "asset.txt").read_text(encoding="utf-8"),
                    asset_directory,
                )
                self.assertFalse(
                    (publication / asset_directory / "nested" / "model.respec.html").exists()
                )
                self.assertFalse(
                    (
                        publication
                        / asset_directory
                        / "nested"
                        / "model.respec.catalog.xhtml"
                    ).exists()
                )

            published_html = sorted(
                path.relative_to(publication).as_posix()
                for path in publication.rglob("*")
                if path.is_file() and path.suffix.lower() in {".html", ".xhtml"}
            )
            self.assertEqual(published_html, ["index.html"])

    def test_publish_content_keeps_assets_but_excludes_respec_source_fragments(self) -> None:
        step = find_publish_step("Prepare content")
        self.assertIsNotNone(step, "De publicatie moet het definitieve contentpakket voorbereiden.")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "snapshot.html").write_text("snapshot", encoding="utf-8")
            for asset_directory in ("data", "media", "js", "css"):
                target = source / asset_directory
                target.mkdir()
                (target / "asset.txt").write_text(asset_directory, encoding="utf-8")
                fragments = target / "nested"
                fragments.mkdir()
                (fragments / "model.respec.html").write_text("fragment", encoding="utf-8")
                (fragments / "model.respec.catalog.xhtml").write_text(
                    "catalog", encoding="utf-8"
                )

            subprocess.run(
                ["bash", "-euo", "pipefail", "-c", step["run"]],
                cwd=source,
                check=True,
                capture_output=True,
                text=True,
            )

            content = source / "content"
            self.assertEqual((content / "index.html").read_text(encoding="utf-8"), "snapshot")
            for asset_directory in ("data", "media", "js", "css"):
                self.assertEqual(
                    (content / asset_directory / "asset.txt").read_text(encoding="utf-8"),
                    asset_directory,
                )
                self.assertFalse(
                    (content / asset_directory / "nested" / "model.respec.html").exists()
                )
                self.assertFalse(
                    (
                        content / asset_directory / "nested" / "model.respec.catalog.xhtml"
                    ).exists()
                )

    def test_html_validation_checks_the_publication_tree_and_keeps_its_log(self) -> None:
        step = find_step("Validate publication HTML")
        self.assertIsNotNone(step, "De build moet het publicatiepakket als HTML valideren.")

        # Blokkerend via het controlerapport, zodat de overige controles ook draaien.
        self.assertIs(step.get("continue-on-error"), True)
        self.assertNotIn("if", step)
        self.assertEqual(step["uses"], "./.nl-respec-tooling/.github/actions/validate-html")
        self.assertEqual(step["with"]["directory"], "publication-validation")
        self.assertEqual(step["with"]["log"], "${{ runner.temp }}/nl-respec-validation/html.log")

    def test_lychee_checks_only_generated_index_and_reports_json(self) -> None:
        step = find_step("Validate publication links")
        self.assertIsNotNone(step, "De build moet publicatielinks met Lychee valideren.")

        self.assertIs(step.get("continue-on-error"), True)
        self.assertEqual(step.get("if"), "${{ !cancelled() }}")
        self.assertEqual(step["with"]["format"], "json")
        self.assertEqual(step["with"]["job-summary"], "false")
        self.assertEqual(
            step["with"]["output"], "${{ runner.temp }}/nl-respec-validation/link-check.json"
        )
        self.assertEqual(step["uses"], "./.nl-respec-tooling/.github/actions/check-links")
        self.assertEqual(step["with"]["files"], "'./index.html'")
        self.assertEqual(step["with"]["root-dir"], "${{ github.workspace }}/publication-validation")
        self.assertEqual(
            step["with"]["working-directory"],
            "${{ github.workspace }}/publication-validation",
        )

    def test_tooling_checkout_contains_shared_actions_at_workflow_commit(self) -> None:
        tooling = find_step("Determine tooling ref")
        checkout = find_step("Checkout workflow tooling")

        self.assertEqual(tooling["env"]["WORKFLOW_SHA"], "${{ job.workflow_sha }}")
        self.assertEqual(tooling["env"]["WORKFLOW_REPOSITORY"], "${{ job.workflow_repository }}")
        self.assertEqual(checkout["with"]["path"], ".nl-respec-tooling")
        self.assertIn(".github/actions", checkout["with"]["sparse-checkout"].split())

    def test_validation_reports_are_artifacts_and_not_committed(self) -> None:
        commit_step = find_step("Commit all results")
        artifact_step = find_step("Upload validation reports")

        self.assertIsNotNone(commit_step)
        self.assertNotIn(".checks", commit_step["run"])
        self.assertNotIn("CHECK_DIR", commit_step["run"])
        self.assertIsNotNone(artifact_step)
        self.assertEqual(artifact_step.get("if"), "${{ always() }}")
        self.assertIn(
            "${{ runner.temp }}/nl-respec-validation/wcag-report.json",
            artifact_step["with"]["path"],
        )
        for report in ("controlerapport.md", "link-check.json", "html.log", "respec.log"):
            self.assertIn(
                f"${{{{ runner.temp }}}}/nl-respec-validation/{report}",
                artifact_step["with"]["path"],
            )

        cleanup_step = find_step("Remove validation working directory")
        self.assertIsNotNone(cleanup_step)
        self.assertEqual(cleanup_step.get("if"), "${{ always() }}")

    def test_report_collects_all_check_outcomes_before_writeback(self) -> None:
        report_step = find_step("Controlerapport")
        self.assertIsNotNone(report_step, "De build moet alle controles in één rapport bundelen.")
        self.assertEqual(report_step.get("if"), "${{ !cancelled() }}")
        self.assertNotIn("continue-on-error", report_step)
        self.assertIn(".github/workflows/controlerapport.mjs", report_step["run"])
        self.assertEqual(report_step["env"]["JOB_STATUS"], "${{ job.status }}")

        steps = build_steps()
        ids = {step.get("id") for step in steps}
        for variable, value in report_step["env"].items():
            if variable.startswith("OUTCOME_"):
                step_id = value.removeprefix("${{ steps.").removesuffix(".outcome }}")
                self.assertIn(step_id, ids, f"{variable} verwijst naar een onbekende stap.")

        names = [step.get("name") for step in steps]
        self.assertLess(names.index("Validate publication links"), names.index("Controlerapport"))
        self.assertLess(names.index("Controlerapport"), names.index("Commit all results"))

    def test_checks_continue_so_the_report_shows_all_findings(self) -> None:
        for name in (
            "Blokkeer raw.githubusercontent.com-links in bronbestand",
            "Check localized header links",
            "Validate publication HTML",
            "Validate publication links",
        ):
            with self.subTest(step=name):
                self.assertIs(find_step(name).get("continue-on-error"), True)

        # Zonder snapshot valt er niets te controleren: die stap blijft direct falen.
        self.assertNotIn("continue-on-error", find_step("Generate HTML snapshot"))


if __name__ == "__main__":
    unittest.main()
