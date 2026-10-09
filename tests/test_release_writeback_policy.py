import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "build.yml"


def step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    next_step = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start:] if next_step == -1 else workflow[start:next_step]


def allowed_events(condition: str) -> set[str]:
    return set(re.findall(r"github\.event_name\s*==\s*['\"]([^'\"]+)['\"]", condition))


class ReleaseWritebackPolicyTest(unittest.TestCase):
    def test_only_push_can_select_a_source_branch_for_writeback(self) -> None:
        workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
        commit_target = step_block(workflow, "Bepaal branch voor terugschrijven")
        condition = re.search(r"^\s+if:\s*(.+)$", commit_target, re.MULTILINE)

        self.assertIsNotNone(condition, "De terugschrijfstap moet een eventvoorwaarde hebben.")
        self.assertEqual(
            allowed_events(condition.group(1)),
            {"push"},
            "Alleen een push mag een bronbranch voor terugschrijven selecteren.",
        )


if __name__ == "__main__":
    unittest.main()
