from contextlib import chdir
from pathlib import Path

from fast_tort_cli.cli import capture_cmd_output


def test_check():
    root = Path(__file__).parent.parent
    expected = (
        "--> poetry run isort --check-only --src=fast_tort_cli . "
        "&& poetry run black --check --fast . && poetry run ruff . && poetry run mypy ."
    )
    with chdir(root):
        assert capture_cmd_output("fast check --dry") == expected
