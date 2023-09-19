from contextlib import chdir
from pathlib import Path

import pytest
from tests.utils import capture_stdout, mock_sys_argv

from fast_tort_cli.cli import LintCode, capture_cmd_output, check_only, lint, make_style


@pytest.fixture
def mock_no_fix(monkeypatch):
    monkeypatch.setenv("NO_FIX", "1")


@pytest.fixture
def mock_skip_mypy(monkeypatch):
    monkeypatch.setenv("SKIP_MYPY", "1")


def test_check():
    command = capture_cmd_output("fast check --dry")
    assert (
        "isort --check-only --src=fast_tort_cli . && " in command
        and "black --check --fast . && " in command
        and "ruff . && " in command
        and "mypy ." in command
    )


def test_lint_cmd():
    command = capture_cmd_output("poetry run python fast_tort_cli/cli.py lint . --dry")
    assert (
        capture_cmd_output("poetry run python fast_tort_cli/cli.py lint --dry")
        == capture_cmd_output("poetry run fast lint --dry")
        == command
    )
    assert (
        "isort --src=fast_tort_cli . && " in command
        and "black . && " in command
        and "ruff --fix . && " in command
        and "mypy ." in command
    )
    assert (
        capture_cmd_output("poetry run python fast_tort_cli/cli.py lint .")
        == capture_cmd_output("poetry run python fast_tort_cli/cli.py lint")
        == capture_cmd_output("poetry run fast lint")
    )


def test_make_style(mocker):
    mocker.patch("fast_tort_cli.cli.is_venv", return_value=True)
    with capture_stdout() as stream:
        make_style(".", check_only=False, dry=True)
    assert (
        "isort --src=fast_tort_cli . && black . && ruff --fix . && mypy ."
        in stream.getvalue()
    )
    with capture_stdout() as stream:
        make_style(".", check_only=True, dry=True)
    assert (
        "isort --check-only --src=fast_tort_cli . && black --check --fast . && ruff . && mypy ."
        in stream.getvalue()
    )
    with capture_stdout() as stream:
        check_only(dry=True)
    assert (
        "isort --check-only --src=fast_tort_cli . && black --check --fast . && ruff . && mypy ."
        in stream.getvalue()
    )


def test_lint_class(mocker):
    mocker.patch("fast_tort_cli.cli.is_venv", return_value=True)
    assert LintCode(".").gen() == (
        "isort --src=fast_tort_cli . && black . && ruff --fix . && mypy ."
    )
    check = LintCode(".", check_only=True)
    assert check.gen() == (
        "isort --check-only --src=fast_tort_cli . && black --check --fast . && ruff . && mypy ."
    )


def test_lint_func(mocker):
    mocker.patch("fast_tort_cli.cli.is_venv", return_value=True)
    with capture_stdout() as stream:
        lint(".", dry=True)
    assert (
        "isort --src=fast_tort_cli . && black . && ruff --fix . && mypy ."
        in stream.getvalue()
    )
    with mock_sys_argv(["tests"]), capture_stdout() as stream:
        lint(dry=True)
    assert (
        "isort --src=fast_tort_cli tests && black tests && ruff --fix tests && mypy tests"
        in stream.getvalue()
    )


def test_no_fix(mock_no_fix, mocker):
    mocker.patch("fast_tort_cli.cli.is_venv", return_value=True)
    assert LintCode(".").gen() == (
        "isort --src=fast_tort_cli . && black . && ruff . && mypy ."
    )


def test_skip_mypy(mock_skip_mypy, mocker):
    mocker.patch("fast_tort_cli.cli.is_venv", return_value=True)
    assert LintCode(".").gen() == (
        "isort --src=fast_tort_cli . && black . && ruff --fix ."
    )


def test_not_in_root(mocker):
    mocker.patch("fast_tort_cli.cli.is_venv", return_value=True)
    root = Path(__file__).parent.parent
    with chdir(root / "fast_tort_cli"):
        assert (
            LintCode(".").gen()
            == "isort --src=. . && black . && ruff --fix . && mypy ."
        )
    with chdir(root / "tests"):
        assert (
            LintCode(".").gen()
            == "isort --src=../fast_tort_cli . && black . && ruff --fix . && mypy ."
        )
        sub = Path("temp_dir")
        sub.mkdir()
        with chdir(sub):
            cmd = LintCode(".").gen()
        sub.rmdir()
        assert (
            cmd
            == "isort --src=../../fast_tort_cli . && black . && ruff --fix . && mypy ."
        )
