"""zhihu CLI — unified entry point for all Zhihu operations."""

import sys

import click

from zhihu_cli.commands.agora import register_agora
from zhihu_cli.commands.auth import register_auth
from zhihu_cli.commands.browse import register_browse
from zhihu_cli.commands.chat import register_chat
from zhihu_cli.commands.compat import register_compat
from zhihu_cli.commands.config import register_config
from zhihu_cli.commands.consult import register_consult
from zhihu_cli.commands.convert import register_convert
from zhihu_cli.commands.daemon import register_daemon
from zhihu_cli.commands.download import register_download
from zhihu_cli.commands.draft import register_draft
from zhihu_cli.commands.interact import register_interact
from zhihu_cli.commands.listen import register_listen
from zhihu_cli.commands.official import register_official
from zhihu_cli.commands.people import register_people
from zhihu_cli.commands.profile import register_profile
from zhihu_cli.commands.publish import register_publish
from zhihu_cli.commands.scrape import register_scrape
from zhihu_cli.commands.search import register_search
from zhihu_cli.commands.stats import register_stats
from zhihu_cli.commands.tools import register_tools
from zhihu_cli.extensions import discover_extensions


def _configure_standard_streams() -> None:
    """Prevent decorative Unicode output from crashing legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


@click.group()
@click.version_option(version="0.3.0", prog_name="zhihu-cli")
def main() -> None:
    """zhihu-cli — Zhihu scraping, automation, and analysis toolkit.

    Authenticate once with \033[1mzhihu-cli auth paste\033[0m, then use any command.
    """
    _configure_standard_streams()


# ── register built-in command groups ───────────────────────────────────────

register_agora(main)
register_auth(main)
register_browse(main)
register_chat(main)
register_config(main)
register_consult(main)
register_convert(main)
register_daemon(main)
register_draft(main)
register_download(main)
register_interact(main)
register_listen(main)
register_official(main)
register_people(main)
register_profile(main)
register_publish(main)
register_scrape(main)
register_search(main)
register_stats(main)
register_tools(main)
register_compat(main)

# ── extensions ─────────────────────────────────────────────────────────────

# Auto-discover and register extension command groups.
for _ext_mod in discover_extensions():
    _ext_mod.register_cli(main)

if __name__ == "__main__":
    main()
