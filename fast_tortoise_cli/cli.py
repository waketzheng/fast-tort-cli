import os
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

import anyio
import typer

cli = typer.Typer()
TOML_FILE = "pyproject.toml"


async def get_work_dir(name=TOML_FILE) -> Path:
    parent = await anyio.Path.cwd()
    for _ in range(5):
        if await parent.joinpath(name).exists():
            return parent._path
        parent = parent.parent
    else:
        raise Exception(f"{name} not found! Make sure this is a poetry project.")


ROOT = anyio.run(get_work_dir)


class PartChoices(StrEnum):
    patch = "patch"
    minor = "minor"
    major = "major"


def get_part(s: str) -> str:
    choices: dict[str, str] = {}
    for i, p in enumerate(PartChoices, 1):
        v = str(p)
        choices.update({str(i): v, v: v})
    try:
        return choices[s]
    except KeyError as e:
        typer.echo(f"Invalid part: {s!r}")
        raise typer.Exit(1) from e


def run_and_echo(cmd: str, **kw) -> int:
    typer.echo(f"--> {cmd}")
    kw.setdefault("shell", True)
    return subprocess.call(cmd, **kw)


def capture_cmd_output(command: list[str] | str, **kw) -> str:
    r = subprocess.run(command, capture_output=True, **kw)
    return r.stdout.strip().decode()


def get_current_version(echo=False) -> str:
    cmd = ["poetry", "version", "-s"]
    if echo:
        command = " ".join(cmd)
        typer.echo(f"--> {command}")
    return capture_cmd_output(cmd)


def exit_if_run_failed(cmd: str, env=None, _exit=False, **kw) -> None:
    if env is not None:
        env = {**os.environ, **env}
    if rc := run_and_echo(cmd, env=env, **kw):
        if _exit:
            sys.exit(rc)
        raise typer.Exit(rc)


@cli.command(name="bump")
def bump_version(
    part: PartChoices,
    commit: bool = typer.Option(
        False, "--commit", "-c", help="Whether run `git commit` after version changed"
    ),
):
    return _bump(commit, part.value)


def bump():
    part, commit = "", False
    if args := sys.argv[2:]:
        if "-c" in args or "--commit" in args:
            commit = True
        for a in args:
            if not a.startswith("-"):
                part = a
                break
    return _bump(commit, part)


def _bump(commit: bool, part: str, filename=TOML_FILE):
    version = get_current_version()
    typer.echo(f"Current version(@{filename}): {version}")
    if part:
        part = get_part(part)
    else:
        tip = "Which one?"
        if a := input(tip).strip():
            part = get_part(a)
        else:
            part = "patch"
    parse = '"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"'
    cmd = f"bumpversion --parse {parse} --current-version {version} {part} {filename}"
    if commit:
        if part != "patch":
            cmd += " --tag"
        cmd += " --commit && git push && git push --tags && git log -1"
    else:
        cmd += " --allow-dirty"
    exit_if_run_failed(cmd)
    if not commit:
        new_version = get_current_version(True)
        typer.echo(new_version)
        if part != "patch":
            typer.echo("You may want to pin tag by `fast tag`")


class UpgradeDependencies:
    @staticmethod
    def parse_value(version_info: str, key: str) -> str:
        sep = key + " = "
        rest = version_info.split(sep, 1)[-1].strip(" =").split(",", 1)[0]
        return rest.split("}")[0].strip().strip('[]"')

    @classmethod
    def build_args(
        cls, package_lines: list[str]
    ) -> tuple[list[str], dict[str, list[str]]]:
        args: list[str] = []  # ['typer[all]', 'fastapi']
        specials: dict[str, list[str]] = {}  # {'--platform linux': ['gunicorn']}
        for line in package_lines:
            if not (m := line.strip()) or m.startswith("#"):
                continue
            try:
                package, version_info = m.split("=", 1)
            except ValueError as e:
                typer.echo(f"{m = }")
                raise e
            if (package := package.strip()).lower() == "python":
                continue
            elif (version_info := version_info.strip()).startswith("{url = }"):
                typer.echo(f"No need to upgrade for: {line}")
                continue
            elif version_info == "*":
                typer.echo(f"Skip wide case line: {line}")
                continue
            if (extras_tip := "extras") in version_info:
                package += "[" + cls.parse_value(version_info, extras_tip) + "]"
            item = f'"{package}@latest"'
            key = None
            if (pf := "platform") in version_info:
                platform = cls.parse_value(version_info, pf)
                key = f"--{pf}={platform}"
            elif (sc := "source") in version_info:
                source = cls.parse_value(version_info, sc)
                key = f"--{sc}={source}"
            if key is not None:
                specials[key] = specials.get(key, []) + [item]
            else:
                args.append(item)
        return args, specials

    @classmethod
    def get_args(cls) -> tuple[list[str], list[str], list[list[str]], str]:
        others: list[list[str]] = []
        main_title = "[tool.poetry.dependencies]"
        toml_file = ROOT.resolve() / TOML_FILE  # to be optimize
        text = toml_file.read_text("utf8").split(main_title)[-1]
        dev_flag = " --group dev"
        if (dev_title := "[tool.poetry.group.dev.dependencies]") not in text:
            dev_title = "[tool.poetry.dev-dependencies]"  # For poetry<=1.2
            dev_flag = " --dev"
        try:
            main_toml, dev_toml = text.split(dev_title)
        except ValueError:
            dev_toml = ""
            main_toml = text.split("[tool.")[0].split("[build-system]")[0]
        else:
            dev_toml = dev_toml.split("[tool.")[0].split("[build-system]")[0]
        devs = dev_toml.strip().splitlines()
        mains = main_toml.strip().splitlines()
        prod_packs, specials = cls.build_args(mains)
        if specials:
            others.extend([[k] + v for k, v in specials.items()])
        dev_packs, specials = cls.build_args(devs)
        if specials:
            others.extend([[k] + v + [dev_flag] for k, v in specials.items()])
        return prod_packs, dev_packs, others, dev_flag

    @classmethod
    def gen_cmd(cls) -> str:
        main_args, dev_args, others, dev_flags = cls.get_args()
        command = "poetry add"
        upgrade = ""
        if main_args:
            upgrade = command + " ".join(main_args)
        if dev_args:
            if upgrade:
                upgrade += " && "
            upgrade += command + dev_flags + " " + " ".join(dev_args)
        for single in others:
            upgrade += f" && poetry add {' '.join(single)}"
        return upgrade


@cli.command()
def upgrade():
    exit_if_run_failed(UpgradeDependencies.get_cmd())


@cli.command(name="lint")
def make_style(files: list[str], remove: bool = typer.Option(False, "-remove", "-r")):
    _lint(remove, files)


def lint(remove=None):
    _lint(remove, sys.argv[1:])


def check():
    _lint(None, sys.argv[1:], True, True)


def _lint(remove, args, check_only=False, _exit=False):
    cmd = ""
    paths = "."
    if args:
        paths = " ".join(args)
    tools = ["isort", "black", "ruff --fix", "mypy"]
    if check_only:
        tools[0] += " --check-only"
        tools[1] += " --check --fast"
        tools[2] = tools[2].split()[0]
    if (skip_mypy := os.getenv("SKIP_MYPY")) and skip_mypy.lower() not in (
        "0",
        "false",
    ):
        tools = tools[-1]
    lint_them = " && ".join("{0}{%d} {1}" % i for i in range(2, len(tools) + 2))
    if (app_dir := ROOT / ROOT.name).exists() or (app_dir := ROOT / "app").exists():
        if (current_path := Path.cwd()) == app_dir:
            tools[0] += " --src=."
        elif current_path == ROOT:
            tools[0] += f" --src={app_dir.name}"
        else:
            tools[0] += f" --src={app_dir}"
    is_in_virtual_environment = False
    prefix = "" if is_in_virtual_environment else "poetry run "
    cmd += lint_them.format(prefix, paths, *tools)
    exit_if_run_failed(cmd, _exit=_exit)


@cli.command()
def sync(
    filename="dev_requirements.txt",
    save: bool = typer.Option(
        False, "--save", "-s", help="Whether save the requirement file"
    ),
):
    should_remove = not Path.cwd().joinpath(filename).exists()
    install_cmd = (
        "poetry export --with=dev --without-hashes -o {0}"
        "&& poetry run pip install -r {0}"
    )
    if should_remove and not save:
        install_cmd += " && rm -f {0}"
    exit_if_run_failed(install_cmd.format(filename))


if __name__ == "__main__":
    cli()
