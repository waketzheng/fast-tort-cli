from contextlib import chdir
from pathlib import Path

from fast_tort_cli.cli import capture_cmd_output


def test_test():
    root = Path(__file__).parent.parent
    with chdir(root):
        assert (
            capture_cmd_output("python fast_tort_cli/cli.py test --dry")
            == '--> coverage run -m pytest -s && coverage report --omit="tests/*" -m'
        )
