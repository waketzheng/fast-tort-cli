from contextlib import chdir
from pathlib import Path

from fast_tort_cli.cli import capture_cmd_output


def test_lint():
    root = Path(__file__).parent.parent
    with chdir(root):
        assert capture_cmd_output("python fast_tort_cli/cli.py lint . --dry") == (
            "--> poetry run isort --src=fast_tort_cli . "
            "&& poetry run black . && poetry run ruff --fix . && poetry run mypy ."
        )
