import re
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GITHUB_DIR = REPOSITORY_ROOT / ".github"
# Bron van de aanroepende workflows die naar documentrepos worden uitgerold.
CALLER_GITHUB_DIR = REPOSITORY_ROOT / "document-repo" / ".github"
UPDATE_SCRIPT = REPOSITORY_ROOT / "scripts" / "update-document-repos.mjs"
ROLLOUT_WORKFLOW = GITHUB_DIR / "workflows" / "update-workflows.yml"
CENTRAL_PREFIX = "Geonovum/NL-ReSpec-workflows/.github/workflows/"


def string_list(source: str, name: str) -> list[str]:
    block = source.split(f"const {name} = [")[1].split("];")[0]
    return re.findall(r'"([^"]+)"', block)


def workflow(name: str, github_dir: Path = GITHUB_DIR) -> dict:
    # PyYAML leest de sleutel "on" als True.
    return yaml.safe_load((github_dir / "workflows" / name).read_text(encoding="utf-8"))


def caller(name: str) -> dict:
    return workflow(name, CALLER_GITHUB_DIR)


class CentralWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        source = UPDATE_SCRIPT.read_text(encoding="utf-8")
        self.managed = string_list(source, "MANAGED_FILES")
        self.removed = string_list(source, "REMOVED_MANAGED_FILES")

    def test_document_repositories_only_receive_caller_workflows(self) -> None:
        self.assertEqual(sorted(self.managed), ["workflows/main.yml", "workflows/visual-regression.yml"])

    def test_old_copies_are_removed_from_document_repositories(self) -> None:
        for name in (
            "dependabot.yml",
            "workflows/build.yml",
            "workflows/publish.yml",
            "workflows/pdf.js",
            "workflows/normalize-mermaid-svg.mjs",
            "mermaid-svg/package.json",
            "mermaid-svg/package-lock.json",
        ):
            self.assertIn(name, self.removed)
        self.assertFalse(set(self.managed) & set(self.removed))

    def test_callers_use_central_reusable_workflows_on_the_major_tag(self) -> None:
        for name in self.managed:
            jobs = caller(Path(name).name)["jobs"]
            for job_name, job in jobs.items():
                uses = job.get("uses", "")
                with self.subTest(file=name, job=job_name):
                    self.assertTrue(uses.startswith(CENTRAL_PREFIX), uses)
                    self.assertTrue(uses.endswith("@v1"), uses)
                    target = workflow(uses[len(CENTRAL_PREFIX):].split("@")[0])
                    self.assertIn("workflow_call", target[True])

    def test_caller_grants_the_permissions_the_reusable_jobs_need(self) -> None:
        jobs = caller("main.yml")["jobs"]
        self.assertEqual(jobs["build"]["permissions"], {"contents": "write"})
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "write", "pull-requests": "write"})

    def test_rollout_copies_callers_from_document_repo_directory(self) -> None:
        for name in self.managed:
            self.assertTrue((CALLER_GITHUB_DIR / name).is_file(), name)
            # Aanroepende workflows draaien niet in deze repository zelf.
            self.assertFalse((GITHUB_DIR / name).exists(), name)
        steps = workflow("update-workflows.yml")["jobs"]["update"]["steps"]
        env = next(step["env"] for step in steps if "TEMPLATE_GITHUB_DIR" in step.get("env", {}))
        self.assertEqual(env["TEMPLATE_GITHUB_DIR"], "${{ github.workspace }}/document-repo/.github")

    def test_template_tests_its_own_build_workflow(self) -> None:
        jobs = workflow("template-regression.yml")["jobs"]
        self.assertEqual(jobs["build"]["uses"], "./.github/workflows/build.yml")

    def test_version_tag_moves_major_tag(self) -> None:
        release = workflow("release-tag.yml")
        self.assertEqual(release[True]["push"]["tags"], ["v[0-9]+.[0-9]+.[0-9]+"])


if __name__ == "__main__":
    unittest.main()
