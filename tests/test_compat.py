import click
from click.testing import CliRunner

from zhihu_cli.commands.compat import register_compat


def _build_cli():
    @click.group()
    def root():
        pass

    @root.group()
    def browse():
        pass

    @browse.command("hot")
    @click.option("--limit", type=int, default=30)
    def hot(limit):
        click.echo(f"HOT={limit}")

    register_compat(root)
    return root


def test_hot_alias_forwards_options():
    result = CliRunner().invoke(_build_cli(), ["hot", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "HOT=3" in result.output


def test_hot_alias_forwards_help():
    result = CliRunner().invoke(_build_cli(), ["hot", "--help"])
    assert result.exit_code == 0, result.output
    assert "--limit" in result.output
