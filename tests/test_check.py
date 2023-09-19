from contextlib import chdir
from pathlib import Path

from fast_tort_cli.cli import capture_cmd_output


def test_check():
    root = Path(__file__).parent.parent
    with chdir(root):
        assert capture_cmd_output("fast check --dry") == (
            "--> isort --check-only --src=fast_tort_cli . && black --check --fast . && ruff . && mypy ."
        )
