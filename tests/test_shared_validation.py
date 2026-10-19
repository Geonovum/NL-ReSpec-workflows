import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GITHUB_DIR = REPOSITORY_ROOT / ".github"
ACTIONS_DIR = GITHUB_DIR / "actions"


def action(name: str) -> dict:
    return yaml.safe_load((ACTIONS_DIR / name / "action.yml").read_text(encoding="utf-8"))


def only_step(name: str) -> dict:
    steps = action(name)["runs"]["steps"]
    return next(step for step in steps if "uses" in step)


class SharedValidationTest(unittest.TestCase):
    def test_validate_html_keeps_the_build_options(self) -> None:
        step = only_step("validate-html")

        self.assertTrue(step["uses"].startswith("anishathalye/proof-html@"))
        self.assertEqual(step["with"]["directory"], "${{ inputs.directory }}")
        self.assertIs(step["with"]["check_html"], True)
        self.assertIs(step["with"]["check_css"], False)
        self.assertIs(step["with"]["disable_external"], True)
        self.assertIs(step["with"]["check_external_hash"], False)
        self.assertIs(step["with"]["enforce_https"], False)
        self.assertIs(step["with"]["ignore_empty_alt"], True)

    def test_check_links_is_offline_and_blocking(self) -> None:
        step = only_step("check-links")
        args = step["with"]["args"]

        self.assertTrue(step["uses"].startswith("lycheeverse/lychee-action@"))
        self.assertIn("--offline", args)
        self.assertIn('--root-dir "${{ inputs.root-dir }}"', args)
        self.assertIn("${{ inputs.files }}", args)
        self.assertIs(step["with"]["fail"], True)
        self.assertIs(step["with"]["failIfEmpty"], True)

    def test_validation_tools_are_only_pinned_in_shared_actions(self) -> None:
        # Eén plek voor versies: build.yml en docs.geostandaarden.nl gebruiken deze acties.
        for path in (GITHUB_DIR / "workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn("anishathalye/proof-html", text)
                self.assertNotIn("lycheeverse/lychee-action", text)

    def test_dependabot_scans_shared_actions(self) -> None:
        config = yaml.safe_load((GITHUB_DIR / "dependabot.yml").read_text(encoding="utf-8"))
        update = next(item for item in config["updates"] if item["package-ecosystem"] == "github-actions")

        self.assertIn("/", update["directories"])
        self.assertIn("/.github/actions/*", update["directories"])


if __name__ == "__main__":
    unittest.main()
