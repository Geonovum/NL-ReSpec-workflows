import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEFTOVERS_MODULE = REPOSITORY_ROOT / "scripts" / "lib" / "template-leftovers.mjs"
UPDATE_SCRIPT = REPOSITORY_ROOT / "scripts" / "update-document-repos.mjs"
ROLLOUT_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "update-workflows.yml"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit(repository: Path, files: dict[str, str], message: str) -> None:
    for name, content in files.items():
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "-c", "user.name=test", "-c", "user.email=test@example.org", "commit", "-qm", message)


class TemplateLeftoversTest(unittest.TestCase):
    def test_removes_only_exact_historical_copies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history"
            history.mkdir()
            git(history, "init", "-q")
            commit(history, {"scripts/sync-repos.mjs": "v1\n", ".github/repos.json": "{}\n"}, "eerste")
            commit(history, {"scripts/sync-repos.mjs": "v2\n"}, "tweede")
            git(history, "rm", "-q", ".github/repos.json")
            git(history, "-c", "user.name=test", "-c", "user.email=test@example.org", "commit", "-qm", "weg")

            target = root / "document"
            (target / "scripts").mkdir(parents=True)
            (target / ".github").mkdir()
            (target / "scripts" / "sync-repos.mjs").write_text("v1\n", encoding="utf-8")  # oude versie
            (target / ".github" / "repos.json").write_text("{}\n", encoding="utf-8")  # verwijderd bestand
            (target / "scripts" / "update-document-repos.mjs").write_text("eigen\n", encoding="utf-8")
            (target / "scripts" / "eigen.mjs").write_text("v1\n", encoding="utf-8")  # niet in de lijst

            files = ["scripts/sync-repos.mjs", ".github/repos.json", "scripts/update-document-repos.mjs"]
            javascript = (
                f"import {{ knownTemplateBlobs, removeTemplateLeftovers }} from {json.dumps(LEFTOVERS_MODULE.as_uri())};"
                f"const known = knownTemplateBlobs(process.argv[1], {json.dumps(files)});"
                "console.log(JSON.stringify(removeTemplateLeftovers(process.argv[2], known)));"
            )
            result = subprocess.run(
                ["node", "--input-type=module", "--eval", javascript, str(history), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )

            removed = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(sorted(removed), [".github/repos.json", "scripts/sync-repos.mjs"])
            self.assertTrue((target / "scripts" / "update-document-repos.mjs").exists())
            self.assertTrue((target / "scripts" / "eigen.mjs").exists())

    def test_candidates_never_include_document_or_caller_files(self) -> None:
        javascript = (
            f"import {{ TEMPLATE_LEFTOVER_FILES }} from {json.dumps(LEFTOVERS_MODULE.as_uri())};"
            "console.log(JSON.stringify(TEMPLATE_LEFTOVER_FILES));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", javascript], check=True, capture_output=True, text=True
        )
        candidates = json.loads(result.stdout)

        for protected in (
            "index.html",
            "js/config.js",
            "README.md",
            "LICENSE",
            "snapshot.html",
            ".gitignore",
            ".github/workflows/main.yml",
            ".github/workflows/visual-regression.yml",
        ):
            self.assertNotIn(protected, candidates)

    def test_rollout_removes_leftovers_with_full_history(self) -> None:
        source = UPDATE_SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(source.count("removeTemplateLeftovers(repoDir, templateBlobs)"), 2)

        steps = yaml.safe_load(ROLLOUT_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["update"]["steps"]
        checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["fetch-depth"], 0)


if __name__ == "__main__":
    unittest.main()
