"""Short top-level commands for common read and authentication workflows."""

from __future__ import annotations

from collections.abc import Sequence

import click


def _forward(
    main_group: click.Group,
    current_context: click.Context,
    command_path: Sequence[str],
    args: Sequence[str],
) -> object:
    forwarded_args = [*command_path, *args]
    forwarded_context = main_group.make_context(
        main_group.name or "zhihu",
        forwarded_args,
        parent=current_context.parent,
    )
    with forwarded_context:
        return main_group.invoke(forwarded_context)


def _register_passthrough_alias(
    main_group: click.Group,
    *,
    name: str,
    command_path: Sequence[str],
    help_text: str,
) -> None:
    @click.command(
        name,
        help=help_text,
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "help_option_names": [],
        },
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def alias_command(context: click.Context, args: tuple[str, ...]) -> object:
        return _forward(main_group, context, command_path, args)

    main_group.add_command(alias_command)


def register_compat(main_group: click.Group) -> None:
    """Register short aliases while preserving the complete grouped CLI."""

    @main_group.command("login")
    @click.option("--qrcode", is_flag=True, help="Use QR login (the default when --cookie is absent)")
    @click.option("--cookie", "cookie_text", default=None, help="Import an authenticated Cookie header")
    @click.option("--profile", "-p", "profile_name", default=None, help="Save to a named profile")
    @click.option(
        "--qr-path",
        type=click.Path(dir_okay=False),
        default=None,
        help="Save the QR image to this path",
    )
    @click.option("--open-browser/--no-browser", default=True, help="Open risk-control verification in a browser")
    @click.option(
        "--browser",
        type=click.Choice(["auto", "edge", "chrome"], case_sensitive=False),
        default="auto",
        show_default=True,
        help="Browser identity and verification-page target",
    )
    @click.pass_context
    def login_alias(
        context: click.Context,
        qrcode: bool,
        cookie_text: str | None,
        profile_name: str | None,
        qr_path: str | None,
        open_browser: bool,
        browser: str,
    ) -> object:
        """Authenticate using a QR code or Cookie text."""
        del qrcode  # QR is the default mode and the flag is retained for compatibility.
        if cookie_text:
            args = ["--cookie", cookie_text, "--browser", browser]
            if profile_name:
                args.extend(["--profile", profile_name])
            return _forward(main_group, context, ("auth", "cookie"), args)

        args = []
        if profile_name:
            args.extend(["--profile", profile_name])
        if qr_path:
            args.extend(["--qr-path", qr_path])
        args.extend(["--browser", browser])
        args.append("--open-browser" if open_browser else "--no-browser")
        return _forward(main_group, context, ("auth", "login"), args)

    _register_passthrough_alias(
        main_group,
        name="status",
        command_path=("auth", "status"),
        help_text="Show authentication status. Alias for 'auth status'.",
    )
    _register_passthrough_alias(
        main_group,
        name="whoami",
        command_path=("auth", "whoami"),
        help_text="Verify and show the active account. Alias for 'auth whoami'.",
    )
    _register_passthrough_alias(
        main_group,
        name="logout",
        command_path=("auth", "clear"),
        help_text="Clear credentials for the active profile. Alias for 'auth clear'.",
    )

    aliases = {
        "hot": (("browse", "hot"), "View the real-time hot list."),
        "feed": (("browse", "feed"), "View the recommendation or following feed."),
        "question": (("browse", "question"), "View a question."),
        "answer": (("browse", "answer"), "View an answer."),
        "notifications": (("browse", "notifications"), "View notifications."),
        "user": (("people", "show"), "View a user profile."),
        "user-answers": (("people", "answers"), "View a user's answers."),
        "user-articles": (("people", "articles"), "View a user's articles."),
        "collections": (("interact", "collect", "list"), "List collections."),
    }
    for alias_name, (path, help_text) in aliases.items():
        _register_passthrough_alias(
            main_group,
            name=alias_name,
            command_path=path,
            help_text=f"{help_text} Compatibility alias.",
        )
