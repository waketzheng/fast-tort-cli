import os
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

try:
    import typer
    from typer import Option, echo

    cli = typer.Typer()
    if len(sys.argv) == 2 and sys.argv[1] == "lint":
        sys.argv.append(".")
except ModuleNotFoundError:
    import click
    from click import echo
    from click import option as Option  # type:ignore
    from click.core import Group

    def command(self, *args, **kwargs):
        from click.decorators import command

        def decorator(f):
            if kwargs.get("name") == "lint":
                import functools

                def auto_fill_args(func):
                    @functools.wraps(func)
                    def runner(*arguments, **kw):
                        if not arguments and "files" not in kw:
                            arguments = (".",)
                        return func(*arguments, **kw)

                    return runner

                f = auto_fill_args(f)
                if sys.argv[2:]:
                    f = click.argument("files", nargs=-1)(f)
            cmd = command(*args, **kwargs)(f)
            self.add_command(cmd)
            return cmd

        return decorator

    Group.command = command  # type:ignore

    @click.group()
    def cli() -> None:
        pass


TOML_FILE = "pyproject.toml"


def run_and_echo(cmd: str, dry=False, **kw) -> int:
    echo(f"--> {cmd}")
    if dry:
        return 0
    kw.setdefault("shell", True)
    return subprocess.run(cmd, **kw).returncode


def capture_cmd_output(command: list[str] | str, **kw) -> str:
    if isinstance(command, str) and not kw.get("shell"):
        command = command.split()
    r = subprocess.run(command, capture_output=True, **kw)
    return r.stdout.strip().decode()


def get_current_version(verbose=False) -> str:
    cmd = ["poetry", "version", "-s"]
    if verbose:
        command = " ".join(cmd)
        echo(f"--> {command}")
    return capture_cmd_output(cmd)


def exit_if_run_failed(cmd: str, env=None, _exit=False, dry=False, **kw) -> None:
    if env is not None:
        env = {**os.environ, **env}
    if rc := run_and_echo(cmd, env=env, dry=dry, **kw):
        if _exit or "typer" not in locals():
            sys.exit(rc)
        raise typer.Exit(rc)


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
        echo(f"Invalid part: {s!r}")
        if "typer" not in locals():
            sys.exit(1)
        raise typer.Exit(1) from e


@cli.command(name="bump")
def bump_version(
    part: PartChoices,
    commit: bool = Option(
        False, "--commit", "-c", help="Whether run `git commit` after version changed"
    ),
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    return _bump(commit, part.value, dry=dry)


def bump():
    part, commit = "", False
    if args := sys.argv[2:]:
        if "-c" in args or "--commit" in args:
            commit = True
        for a in args:
            if not a.startswith("-"):
                part = a
                break
    return _bump(commit, part, dry="--dry" in args)


def _bump(commit: bool, part: str, filename=TOML_FILE, dry=False):
    version = get_current_version()
    echo(f"Current version(@{filename}): {version}")
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
    exit_if_run_failed(cmd, dry=dry)
    if not commit and not dry:
        new_version = get_current_version(True)
        echo(new_version)
        if part != "patch":
            echo("You may want to pin tag by `fast tag`")


class Project:
    @staticmethod
    async def work_dir(name: str, cwd) -> Path | None:
        parent = await cwd()
        for _ in range(5):
            if await parent.joinpath(name).exists():
                return parent._path
            parent = parent.parent
        return None

    @staticmethod
    def workdir(name: str) -> Path | None:
        parent = Path.cwd()
        for _ in range(5):
            if parent.joinpath(name).exists():
                return parent
            parent = parent.parent
        return None

    @classmethod
    def get_work_dir(cls, name=TOML_FILE) -> Path:
        try:
            from anyio import Path, run

            if (p := run(cls.work_dir, name, Path.cwd)) is not None:
                return p
        except ModuleNotFoundError:
            if (path := cls.workdir(name)) is not None:
                return path
        raise Exception(f"{name} not found! Make sure this is a poetry project.")

    @classmethod
    def load_toml_text(cls):
        toml_file = cls.get_work_dir().resolve() / TOML_FILE  # to be optimize
        return toml_file.read_text("utf8")


class UpgradeDependencies(Project):
    class DevFlag(StrEnum):
        new = "[tool.poetry.group.dev.dependencies]"
        old = "[tool.poetry.dev-dependencies]"

    @staticmethod
    def parse_value(version_info: str, key: str) -> str:
        sep = key + " = "
        rest = version_info.split(sep, 1)[-1].strip(" =").split(",", 1)[0]
        return rest.split("}")[0].strip().strip('[]"')

    @staticmethod
    def no_need_upgrade(version_info: str, line: str) -> bool:
        if (v := version_info.replace(" ", "")).startswith("{url="):
            echo(f"No need to upgrade for: {line}")
            return True
        if (f := "version=") in v:
            v = v.split(f)[1].strip('"').split('"')[0]
        if v == "*":
            echo(f"Skip wildcard line: {line}")
            return True
        elif v.startswith(">") or v.startswith("<"):
            echo(f"Ignore bigger and smaller: {line}")
            return True
        return False

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
                raise Exception(f"{m = }") from e
            if (package := package.strip()).lower() == "python":
                continue
            if cls.no_need_upgrade(version_info := version_info.strip(' "'), line):
                continue
            if (extras_tip := "extras") in version_info:
                package += "[" + cls.parse_value(version_info, extras_tip) + "]"
            item = f'"{package}@latest"'
            key = None
            if (pf := "platform") in version_info:
                platform = cls.parse_value(version_info, pf)
                key = f"--{pf}={platform}"
            if (sc := "source") in version_info:
                source = cls.parse_value(version_info, sc)
                key = ("" if key is None else (key + " ")) + f"--{sc}={source}"
            if "optional = true" in version_info:
                key = ("" if key is None else (key + " ")) + "--optional"
            if key is not None:
                specials[key] = specials.get(key, []) + [item]
            else:
                args.append(item)
        return args, specials

    @classmethod
    def should_with_dev(cls):
        text = cls.load_toml_text()
        return cls.DevFlag.new in text or cls.DevFlag.old in text

    @staticmethod
    def parse_item(toml_str) -> list[str]:
        lines: list[str] = []
        for line in toml_str.splitlines():
            if (line := line.strip()).startswith("["):
                if lines:
                    break
            else:
                lines.append(line)
        return lines

    @classmethod
    def get_args(cls) -> tuple[list[str], list[str], list[list[str]], str]:
        others: list[list[str]] = []
        main_title = "[tool.poetry.dependencies]"
        text = cls.load_toml_text().split(main_title)[-1]
        dev_flag = "--group dev"
        if (dev_title := cls.DevFlag.new.value) not in text:
            dev_title = cls.DevFlag.old.value  # For poetry<=1.2
            dev_flag = "--dev"
        try:
            main_toml, dev_toml = text.split(dev_title)
        except ValueError:
            dev_toml = ""
            main_toml = text
        mains, devs = cls.parse_item(main_toml), cls.parse_item(dev_toml)
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
        command = "poetry add "
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
def upgrade(
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    """Upgrade dependencies in pyproject.toml to latest versions"""
    exit_if_run_failed(UpgradeDependencies.gen_cmd(), dry=dry)


@cli.command()
def tag(
    message: str = Option("", "-m", "--message"),
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    """Run shell command: git tag -a <current-version-in-pyproject.toml> -m {message}"""
    gs = capture_cmd_output("git status")
    if "working tree clean" not in gs:
        run_and_echo("git status")
        echo("ERROR: Please run git commit to make sure working tree is clean!")
        return
    version = get_current_version(verbose=False)
    cmd = f"git tag -a {version} -m {message!r} && git push --tags"
    if "git push" in gs:
        cmd += " && git push"
    exit_if_run_failed(cmd, dry=dry)
    if not dry:
        echo("You may want to publish package:\n poetry publish --build")


@cli.command(name="lint")
def make_style(
    files: list[str],
    check_only: bool = Option(False, "--check-only", "-c"),
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    """Run: isort+black+ruff to reformat code and then mypy to check"""
    if isinstance(files, str):
        files = [files]
    if check_only:
        _lint(files, True, True, dry=dry)
    else:
        _lint(files, dry=dry)


def lint():
    _lint(sys.argv[1:])


@cli.command(name="check")
def check_only(
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    _lint(".", True, True, dry=dry)


def check():
    _lint(sys.argv[1:], True, True)


def load_bool(name: str, default=False) -> bool:
    if not (v := os.getenv(name)):
        return default
    return v.lower() not in ("0", "false", "off", "no", "n")


def _lint(args, check_only=False, _exit=False, dry=False):
    cmd = ""
    paths = "."
    if args:
        paths = " ".join(args)
    tools = ["isort", "black", "ruff --fix", "mypy"]
    if check_only:
        tools[0] += " --check-only"
        tools[1] += " --check --fast"
        tools[2] = tools[2].split()[0]
    elif load_bool("NO_FIX"):
        tools[2] = tools[2].split()[0]
    if load_bool("SKIP_MYPY"):
        # Sometimes mypy is too slow
        tools = tools[-1]
    lint_them = " && ".join("{0}{%d} {1}" % i for i in range(2, len(tools) + 2))
    root = Project.get_work_dir()
    app_name = root.name.replace("-", "_")
    if (app_dir := root / app_name).exists() or (app_dir := root / "app").exists():
        if (current_path := Path.cwd()) == app_dir:
            tools[0] += " --src=."
        elif current_path == root:
            tools[0] += f" --src={app_dir.name}"
        else:
            tools[0] += f" --src={app_dir}"
    is_in_virtual_environment = False
    prefix = "" if is_in_virtual_environment else "poetry run "
    cmd += lint_them.format(prefix, paths, *tools)
    exit_if_run_failed(cmd, _exit=_exit, dry=dry)


@cli.command()
def sync(
    filename="dev_requirements.txt",
    extras: str = Option("", "--extras", "-E"),
    save: bool = Option(
        False, "--save", "-s", help="Whether save the requirement file"
    ),
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    should_remove = not Path.cwd().joinpath(filename).exists()
    install_cmd = (
        "poetry export --with=dev --without-hashes -o {0}"
        " && poetry run pip install -r {0}"
    )
    if not UpgradeDependencies.should_with_dev():
        install_cmd = install_cmd.replace(" --with=dev", "")
    if extras and isinstance(extras, str | list):
        install_cmd = install_cmd.replace("export", f"export --{extras=}")
    if should_remove and not save:
        install_cmd += " && rm -f {0}"
    exit_if_run_failed(install_cmd.format(filename), dry=dry)


@cli.command()
def test(
    dry: bool = Option(False, "--dry", help="Only print, not really run shell command"),
):
    cmd = 'coverage run -m pytest -s && coverage report --omit="tests/*" -m'
    exit_if_run_failed(cmd, dry=dry)


if __name__ == "__main__":
    cli()
