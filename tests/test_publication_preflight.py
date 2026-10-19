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

    def test_html_validation_is_blocking_for_the_publication_tree(self) -> None:
        step = find_step("Validate publication HTML")
        self.assertIsNotNone(step, "De build moet het publicatiepakket als HTML valideren.")

        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("if", step)
        self.assertEqual(
            step["with"]["directory"],
            "publication-validation",
        )
        self.assertIs(step["with"]["check_html"], True)
        self.assertIs(step["with"]["check_css"], False)
        self.assertIs(step["with"]["disable_external"], True)
        self.assertIs(step["with"]["ignore_empty_alt"], True)

    def test_lychee_checks_only_generated_index_and_fails_on_errors(self) -> None:
        step = find_step("Validate publication links")
        self.assertIsNotNone(step, "De build moet publicatielinks met Lychee valideren.")

        self.assertNotIn("continue-on-error", step)
        self.assertEqual(step.get("if"), "${{ !cancelled() }}")
        self.assertTrue(step["uses"].startswith("lycheeverse/lychee-action@"))
        self.assertIs(step["with"]["fail"], True)
        self.assertEqual(
            step["with"]["workingDirectory"],
            "${{ github.workspace }}/publication-validation",
        )
        self.assertIn("--offline", step["with"]["args"])
        self.assertIn("--root-dir", step["with"]["args"])
        self.assertIn("./index.html", step["with"]["args"])
        self.assertNotIn("./**/*.html", step["with"]["args"])

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
        self.assertIn(
            "${{ runner.temp }}/nl-respec-validation/link-check.txt",
            artifact_step["with"]["path"],
        )

        cleanup_step = find_step("Remove validation working directory")
        self.assertIsNotNone(cleanup_step)
        self.assertEqual(cleanup_step.get("if"), "${{ always() }}")

    def test_summary_always_reports_whether_the_commit_is_ready_for_publication(self) -> None:
        html_step = find_step("Validate publication HTML")
        link_step = find_step("Validate publication links")
        summary_step = find_step("Summarize publication preflight")

        self.assertIsNotNone(html_step)
        self.assertIsNotNone(link_step)
        self.assertIsNotNone(summary_step, "De build moet de publicatiegereedheid samenvatten.")
        self.assertEqual(html_step.get("id"), "publication-html")
        self.assertEqual(link_step.get("id"), "publication-links")
        self.assertEqual(summary_step.get("if"), "${{ always() }}")
        self.assertIn("GITHUB_STEP_SUMMARY", summary_step["run"])
        self.assertIn("Publicatiegereed", summary_step["run"])
        self.assertIn("${{ job.status }}", summary_step["run"])
        self.assertIn('BUILD_STATUS" == "success', summary_step["run"])


if __name__ == "__main__":
    unittest.main()
