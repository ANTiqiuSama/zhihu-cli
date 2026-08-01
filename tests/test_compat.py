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

    @root.group()
    def auth():
        pass

    @auth.command("login")
    @click.option("--browser")
    @click.option("--open-browser/--no-browser")
    def login(browser, open_browser):
        click.echo(f"LOGIN={browser};OPEN={open_browser}")

    @auth.command("cookie")
    @click.option("--cookie")
    @click.option("--browser")
    def cookie(cookie, browser):
        click.echo(f"COOKIE={bool(cookie)};BROWSER={browser}")

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


def test_login_alias_forwards_explicit_edge_browser():
    result = CliRunner().invoke(_build_cli(), ["login", "--qrcode", "--browser", "edge", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "LOGIN=edge;OPEN=False" in result.output


def test_cookie_login_alias_forwards_explicit_edge_browser():
    result = CliRunner().invoke(_build_cli(), ["login", "--cookie", "z_c0=test", "--browser", "edge"])
    assert result.exit_code == 0, result.output
    assert "COOKIE=True;BROWSER=edge" in result.output
