"""Bridge to Zhihu's official Open Platform CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click

from zhihu_cli.official import (
    OfficialCliError,
    install_official_cli,
    install_official_skill,
    resolve_official_binary,
    resolve_official_skill,
)
from zhihu_cli.output import echo, error, info

_HELP = """Zhihu official Open Platform provider.

Internal commands:
  zhihu-cli official install [--force]  Download and verify the official binary
  zhihu-cli official path               Print the resolved official binary path
  zhihu-cli official skill install      Install the verified official Codex Skill
  zhihu-cli official skill path         Print the installed Codex Skill path

All other arguments are forwarded unchanged to the official CLI:
  zhihu-cli official capabilities --pretty
  zhihu-cli official search zhihu --query "AI Agent" --count 5 --pretty
  zhihu-cli official search global --query "research automation" --count 10
  zhihu-cli official hot --limit 10 --pretty
  zhihu-cli official answer --query "什么是科研自动化" --output text --stream

For credentials, use stdin so the Access Secret is not stored in shell history:
  zhihu-cli official auth set --secret-stdin
"""


def _run_official(binary: Path, arguments: tuple[str, ...]) -> int:
    result = subprocess.run([str(binary), *arguments], check=False)
    return result.returncode


def _blocks_secret_argument(arguments: tuple[str, ...]) -> bool:
    if len(arguments) >= 2 and arguments[:2] == ("auth", "set"):
        return arguments[2:] != ("--secret-stdin",)
    if arguments and arguments[0] == "init":
        return any(arg == "--secret" or arg.startswith("--secret=") for arg in arguments[1:])
    return False


def register_official(main_group: click.Group) -> None:
    """Register the official Open Platform provider."""

    @main_group.command(
        "official",
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []},
    )
    @click.argument("official_args", nargs=-1, type=click.UNPROCESSED)
    def official(official_args: tuple[str, ...]) -> None:
        """Install or call Zhihu's official Open Platform CLI."""
        if not official_args or official_args == ("--help",):
            echo(_HELP.rstrip())
            return

        action = official_args[0]
        if action == "install":
            if len(official_args) == 2 and official_args[1] in {"--help", "-h"}:
                echo("Usage: zhihu-cli official install [--force]")
                return
            unknown = [arg for arg in official_args[1:] if arg != "--force"]
            if unknown:
                error(f"Unknown official install option: {unknown[0]}")
                raise click.exceptions.Exit(2)
            try:
                result = install_official_cli(force="--force" in official_args[1:])
            except OfficialCliError as exc:
                error(str(exc))
                raise click.exceptions.Exit(1) from exc
            click.echo(json.dumps(result, ensure_ascii=False))
            return

        if action == "path":
            if len(official_args) != 1:
                error("Usage: zhihu-cli official path")
                raise click.exceptions.Exit(2)
            try:
                binary = resolve_official_binary()
            except OfficialCliError as exc:
                error(str(exc))
                raise click.exceptions.Exit(1) from exc
            click.echo(str(binary))
            return

        if action == "skill":
            if len(official_args) == 1 or official_args[1] in {"--help", "-h"}:
                echo("Usage:\n  zhihu-cli official skill install [--force]\n  zhihu-cli official skill path")
                return
            skill_action = official_args[1]
            if skill_action == "install":
                unknown = [arg for arg in official_args[2:] if arg != "--force"]
                if unknown:
                    error(f"Unknown official skill install option: {unknown[0]}")
                    raise click.exceptions.Exit(2)
                try:
                    result = install_official_skill(force="--force" in official_args[2:])
                except OfficialCliError as exc:
                    error(str(exc))
                    raise click.exceptions.Exit(1) from exc
                click.echo(json.dumps(result, ensure_ascii=False))
                return
            if skill_action == "path":
                if len(official_args) != 2:
                    error("Usage: zhihu-cli official skill path")
                    raise click.exceptions.Exit(2)
                try:
                    skill = resolve_official_skill()
                except OfficialCliError as exc:
                    error(str(exc))
                    raise click.exceptions.Exit(1) from exc
                click.echo(str(skill))
                return
            error(f"Unknown official skill action: {skill_action}")
            raise click.exceptions.Exit(2)

        if _blocks_secret_argument(official_args):
            error(
                "Refusing to place an Access Secret in process arguments. "
                "Use `zhihu-cli official auth set --secret-stdin`."
            )
            raise click.exceptions.Exit(2)

        try:
            binary = resolve_official_binary()
        except OfficialCliError as exc:
            error(str(exc))
            info("Install it with: zhihu-cli official install")
            raise click.exceptions.Exit(1) from exc

        return_code = _run_official(binary, official_args)
        if return_code:
            raise click.exceptions.Exit(return_code)
