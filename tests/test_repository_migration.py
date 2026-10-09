import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_MODULE = REPOSITORY_ROOT / "scripts" / "lib" / "repository-migration.mjs"


class RepositoryMigrationTest(unittest.TestCase):
    def test_removes_checks_directory_without_overwriting_local_ignore_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / ".gitignore").write_text(
                "node_modules/\n.checks/*\n!.checks/*.txt\n!.checks/*.json\nlocal-only/\n",
                encoding="utf-8",
            )
            checks = repository / ".checks"
            checks.mkdir()
            (checks / "link-check.txt").write_text("links", encoding="utf-8")
            (checks / "wcag-report.json").write_text("{}", encoding="utf-8")

            javascript = (
                f'import {{ migrateChecksDirectory }} from {json.dumps(MIGRATION_MODULE.as_uri())};'
                "console.log(JSON.stringify(migrateChecksDirectory(process.argv[1])));"
            )
            result = subprocess.run(
                ["node", "--input-type=module", "--eval", javascript, str(repository)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(json.loads(result.stdout), [".gitignore", ".checks"])
            self.assertFalse(checks.exists())
            self.assertEqual(
                (repository / ".gitignore").read_text(encoding="utf-8"),
                "node_modules/\nlocal-only/\n",
            )


if __name__ == "__main__":
    unittest.main()
