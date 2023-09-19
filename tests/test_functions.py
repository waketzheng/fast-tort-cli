import os
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
import typer

from fast_tort_cli.cli import (
    TOML_FILE,
    DryRun,
    exit_if_run_failed,
    get_current_version,
    load_bool,
    parse_files,
    run_and_echo,
)


def test_utils():
    # parse files
    assert parse_files([]) == []
    assert parse_files(["-a", "--a"]) == []
    assert parse_files(["i", "-a", "--a"]) == ["i"]
    assert parse_files(["i", "-a", "--a", "j"]) == ["i", "j"]

    # load bool
    assert load_bool("NOT_EXIST_ENV") is False
    assert load_bool("NOT_EXIST_ENV", True) is True
    name = "TEST_LOAD_BOOL"
    os.environ[name] = "no"
    assert load_bool(name, True) is False
    assert load_bool(name) is False
    os.environ[name] = "NO"
    assert load_bool(name) is False
    os.environ[name] = "off"
    assert load_bool(name) is False
    os.environ[name] = "OFF"
    assert load_bool(name) is False
    os.environ[name] = "0"
    assert load_bool(name) is False
    os.environ[name] = "false"
    assert load_bool(name) is False
    os.environ[name] = "False"
    assert load_bool(name) is False
    os.environ[name] = "FALSE"
    assert load_bool(name) is False
    os.environ[name] = "1"
    assert load_bool(name) is True
    os.environ[name] = "yes"
    assert load_bool(name) is True
    os.environ[name] = "true"
    assert load_bool(name) is True
    os.environ.pop(name)
    assert load_bool(name) is False


def test_run_shell():
    # current version
    version = get_current_version()
    assert version in Path(TOML_FILE).read_text()
    stream = StringIO()
    write_to_stream = redirect_stdout(stream)
    with write_to_stream:
        get_current_version(True)
    assert "poetry version -s" in stream.getvalue()

    name = "TEST_EXIT_IF_RUN_FAILED"
    value = "foo"
    cmd = 'python -c "import os;print(list(os.environ))"'
    with redirect_stdout(StringIO()):
        r = exit_if_run_failed(cmd, env={name: value}, capture_output=True)
    assert name in r.stdout.decode()

    assert run_and_echo("echo foo", capture_output=True) == 0

    with pytest.raises(SystemExit):
        exit_if_run_failed("in_valid_command", _exit=True, capture_output=True)
    with pytest.raises(typer.Exit):
        exit_if_run_failed("in_valid_command", _exit=False, capture_output=True)
    with pytest.raises(NotImplementedError):

        class A(DryRun):
            pass

        A().run()
