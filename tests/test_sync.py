from contextlib import chdir
from pathlib import Path

from tests.utils import capture_stdout, temp_file

from fast_tort_cli.cli import TOML_FILE, Sync, sync

TOML_TEXT = """
[tool.poetry]
name = "foo"
version = "0.1.0"
description = ""
authors = []
readme = ""

[tool.poetry.dependencies]
python = "^3.11"
click = ">=7.1.1"
anyio = {version = "^4.0", optional = true}

[tool.poetry.extras]
all = ["anyio"]

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
"""


def test_sync():
    assert (
        Sync("req.txt", "", True, dry=True).gen()
        == "poetry export --with=dev --without-hashes -o req.txt && poetry run pip install -r req.txt"
    )
    test_dir = Path(__file__).parent
    with temp_file(TOML_FILE, TOML_TEXT), chdir(test_dir):
        cmd = Sync("req.txt", "all", save=False, dry=True).gen()
    assert (
        cmd
        == "poetry export --extras='all' --without-hashes -o req.txt && poetry run pip install -r req.txt && rm -f req.txt"
    )
    with capture_stdout() as stream:
        sync(extras="all", save=False, dry=True)
    assert "pip install -r" in stream.getvalue()
