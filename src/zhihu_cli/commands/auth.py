"""Auth command group — manage authentication (cURL headers / QR login / captcha)."""

import os
import sys
from pathlib import Path

import click

from zhihu_cli.content.handlers.cache_manager import cache_manager
from zhihu_cli.content.handlers.captcha import detect_captcha, get_captcha_info, handle_captcha, parse_redirect
from zhihu_cli.content.handlers.requests import reload_session, session
from zhihu_cli.output import (
    blank,
    echo,
    error,
    f_bold,
    f_green,
    f_label,
    f_name,
    f_num,
    info,
    print_json,
    success,
    warning,
)


def register_auth(main_group) -> None:
    """Register the auth command group on a Click group."""

    @main_group.group()
    def auth() -> None:
        """Manage authentication (cURL headers)."""

    @auth.command("paste")
    @click.option("--profile", "-p", "profile_name", default=None, help="Save to a named profile")
    def auth_paste(profile_name: str | None) -> None:
        """Paste a cURL command from browser DevTools to cache headers.

        \033[2m1. Open Zhihu in browser, F12 → Network tab\033[0m
        \033[2m2. Find any API request, right-click → Copy → Copy as cURL\033[0m
        \033[2m3. Paste here and press Ctrl+D\033[0m

        Use --profile to save to a named profile (e.g. work, personal).
        """
        if profile_name and profile_name.startswith("_"):
            error("Profile names starting with '_' are reserved for internal use.")
            raise SystemExit(1)

        echo("Paste cURL command (Ctrl+D to finish):")
        try:
            curl_text = sys.stdin.read()
        except EOFError:
            curl_text = ""

        if not curl_text.strip():
            error("No input detected.")
            raise SystemExit(1)

        import re

        headers: dict[str, str] = {}
        for h in re.findall(r"(?:-H|--header)\s+['\"]([^'\"]+)['\"]", curl_text):
            if ":" in h:
                k, v = h.split(":", 1)
                if k.strip().lower() not in ("accept-encoding", "content-length"):
                    headers[k.strip()] = v.strip()

        if not headers:
            error("Could not parse any headers from the input.")
            raise SystemExit(1)

        cache_manager.save_headers(headers, profile_name=profile_name)
        active = cache_manager.get_active_profile() or "default"
        success(f"Saved {len(headers)} headers to profile '{active}'")

    @auth.command("cookie")
    @click.option(
        "--cookie",
        "cookie_text",
        default=None,
        help="Cookie header text. If omitted, ZHIHU_COOKIE or a hidden prompt is used.",
    )
    @click.option("--profile", "-p", "profile_name", default=None, help="Save to a named profile")
    @click.option(
        "--browser",
        type=click.Choice(["auto", "edge", "chrome"], case_sensitive=False),
        default="auto",
        show_default=True,
        help="Browser identity associated with this Cookie",
    )
    def auth_cookie(cookie_text: str | None, profile_name: str | None, browser: str) -> None:
        """Import a Cookie header directly and persist it as a profile."""
        if profile_name and profile_name.startswith("_"):
            error("Profile names starting with '_' are reserved for internal use.")
            raise SystemExit(1)

        cookie_text = cookie_text or os.environ.get("ZHIHU_COOKIE")
        if not cookie_text:
            cookie_text = click.prompt("Cookie", hide_input=True)

        cookie_pairs = {}
        for item in cookie_text.split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key and value:
                cookie_pairs[key] = value

        if "z_c0" not in cookie_pairs:
            error("Cookie must contain z_c0. Copy a complete Cookie header from an authenticated Zhihu request.")
            raise SystemExit(1)

        from zhihu_cli.content.handlers.auth_login import _browser_identity

        _, user_agent, _ = _browser_identity(browser)
        headers = {"Cookie": cookie_text.strip(), "User-Agent": user_agent}
        cache_manager.save_headers(headers, profile_name=profile_name)
        active = cache_manager.get_active_profile() or "default"
        success(f"Saved Cookie credentials to profile '{active}'")
        reload_session()

    @auth.command("login")
    @click.option("--profile", "-p", "profile_name", default=None, help="Save to a named profile")
    @click.option(
        "--qr-path",
        type=click.Path(path_type=Path, dir_okay=False),
        default=None,
        help="Save the QR image to this path (default: ~/.zhihu-cli/login_qrcode.png)",
    )
    @click.option("--open-browser/--no-browser", default=True, help="Open risk-control verification in a browser")
    @click.option(
        "--browser",
        type=click.Choice(["auto", "edge", "chrome"], case_sensitive=False),
        default="auto",
        show_default=True,
        help="Browser identity and verification-page target",
    )
    def auth_login(profile_name: str | None, qr_path: Path | None, open_browser: bool, browser: str) -> None:
        """Login to Zhihu via QR code. Scan with the Zhihu App to authenticate.

        Displays a QR code in the terminal. Open the Zhihu App, go to
        \033[2mMy → Settings → Scan\033[0m, and scan the code to log in.

        This generates fresh cookies and saves them as a profile, so you
        don't need to manually paste cURL headers.
        """
        if profile_name and profile_name.startswith("_"):
            error("Profile names starting with '_' are reserved for internal use.")
            raise SystemExit(1)

        from zhihu_cli.content.handlers.auth_login import qr_login

        info("Starting QR code login...")
        try:
            headers = qr_login(qr_path=qr_path, open_browser=open_browser, browser=browser)
        except RuntimeError as e:
            error(f"{e}")
            raise SystemExit(1)

        if not headers:
            error("Login failed.")
            raise SystemExit(1)

        cache_manager.save_headers(headers, profile_name=profile_name)
        active = cache_manager.get_active_profile() or "default"
        success(f"Saved credentials to profile '{active}'")
        reload_session()

    @auth.command("whoami")
    @click.option("--json", "output_json", is_flag=True, default=False, help="Output as JSON")
    def auth_whoami(output_json: bool) -> None:
        """Verify the active credentials against Zhihu and show the account."""
        headers = cache_manager.load_headers()
        if not headers or "cookie" not in {key.lower() for key in headers}:
            error("Not authenticated. Run 'zhihu auth login' or 'zhihu auth cookie'.")
            raise SystemExit(1)

        try:
            resp = session.get("https://www.zhihu.com/api/v4/me", timeout=10)
        except Exception as exc:
            error(f"Failed to verify credentials: {exc}")
            raise SystemExit(1) from exc

        if resp.status_code != 200:
            error(f"Authentication verification failed: HTTP {resp.status_code}")
            raise SystemExit(1)

        me = resp.json()
        if output_json:
            print_json(me)
            return

        echo(f"  {f_label('Username:')} {f_name(me.get('name', 'unknown'))}")
        if me.get("id"):
            echo(f"  {f_label('User ID:')} {f_num(me['id'])}")
        if me.get("url_token"):
            echo(f"  {f_label('URL token:')} {me['url_token']}")

    @auth.command("status")
    @click.option("--json", "output_json", is_flag=True, default=False, help="Output as JSON")
    def auth_status(output_json: bool) -> None:
        """Show authentication status and active profile."""
        active = cache_manager.get_active_profile()
        profiles = [p for p in cache_manager.list_profiles() if not p.startswith("_")]
        headers = cache_manager.load_headers()
        has_cookie = "cookie" in {k.lower() for k in headers} if headers else False

        # Fetch authenticated user info from /api/v4/me
        username = None
        uid = None
        user_id = None
        url_token = None
        if has_cookie:
            try:
                resp = session.get("https://www.zhihu.com/api/v4/me", timeout=10)
                if resp.status_code == 200:
                    me = resp.json()
                    username = me.get("name")
                    user_id = me.get("id")
                    url_token = me.get("url_token")
                    uid = me.get("uid")
            except Exception:
                pass  # Silently ignore — user info is a best-effort bonus

        if output_json:
            print_json(
                {
                    "active_profile": active,
                    "profiles": profiles,
                    "headers_count": len(headers),
                    "has_cookie": has_cookie,
                    "username": username,
                    "user_id": user_id,
                    "url_token": url_token,
                    "uid": uid,
                }
            )
            return

        if active:
            echo(f"  {f_label('Active profile:')} {f_bold(active)}")
        else:
            info("No active profile set.")

        if profiles:
            echo(f"  {f_label('Saved profiles:')} {', '.join(profiles)}")

        if headers:
            echo(f"  {f_label('Headers:')} {f_num(len(headers))} cached")
            if has_cookie:
                echo(f"  {f_label('Cookie:')} {f_green('present')}")
                if username:
                    echo(f"  {f_label('Username:')} {f_name(username)}")
                    if user_id:
                        echo(f"  {f_label('User ID:')} {f_num(user_id)}")
                    if url_token:
                        echo(f"  {f_label('URL token:')} {url_token}")
                    if uid:
                        echo(f"  {f_label('UID:')} {f_num(uid)}")
            else:
                warning("No Cookie header found.")
        else:
            error("No headers cached. Run 'zhihu auth paste' first.")

    @auth.command("clear")
    def auth_clear() -> None:
        """Remove cached headers."""
        cache_manager.save_headers({})
        success("Headers cache cleared.")

    @auth.command("captcha")
    @click.option("--url", "-u", "test_url", default=None, help="URL to test for captcha (default: hot list API)")
    @click.option("--open-browser/--no-browser", default=True, help="Auto-open browser for verification")
    def auth_captcha(test_url: str | None, open_browser: bool) -> None:
        """Check and resolve Zhihu risk-control / captcha challenges.

        Tests the current session against a Zhihu API endpoint. If the
        response indicates a captcha is required, displays instructions
        and optionally opens the verification page in a browser.

        \033[2mExamples:\033[0m
          zhihu auth captcha                    # test with hot list API
          zhihu auth captcha --url <api-url>    # test a specific API
          zhihu auth captcha --no-browser       # don't auto-open browser
        """
        from zhihu_cli.content.handlers.requests import session

        if test_url is None:
            test_url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=1&desktop=true"

        info(f"Testing endpoint for captcha: {test_url}")
        blank()

        # Temporarily disable automatic captcha handling — we control the flow here
        old_handler = session.captcha_handler
        session.captcha_handler = "ignore"

        def _test_request():
            """Make a test request and return the response (auto-handler disabled)."""
            return session.get(test_url)

        try:
            resp = _test_request()
        except Exception as e:
            session.captcha_handler = old_handler
            error(f"Error making request: {e}")
            raise SystemExit(1)

        captcha_error = detect_captcha(resp)
        if captcha_error is None:
            if resp.status_code == 200:
                success("No captcha detected — session is working normally.")
            else:
                echo(f"  {f_label('Status:')} {resp.status_code} (non-captcha error)")
                try:
                    body = resp.text[:500]
                    echo(f"  {f_label('Response:')} {body}")
                except Exception:
                    pass
            return

        # Captcha detected
        warning("Captcha/risk-control detected!")
        blank()

        redirect_url = captcha_error.get("redirect", "")
        params = parse_redirect(redirect_url)
        captcha_type = params.get("type", "unknown")
        session_id = params.get("session", "")

        echo(f"  {f_label('Type:')}    {captcha_type}")
        echo(f"  {f_label('Session:')} {session_id}")
        echo(f"  {f_label('Message:')} {captcha_error.get('message', 'N/A')}")
        blank()

        # Try to get more details from the appeal API
        if session_id:
            try:
                captcha_info = get_captcha_info(session, session_id)
                echo(f"  {f_label('Block level:')} {captcha_info.get('block_level', 'N/A')}")
                img = captcha_info.get("img_base64", "")
                if img:
                    echo(f"  {f_label('Captcha image:')} {len(img)} chars (base64)")
                redirect_msg = captcha_info.get("redirect_url", "")
                if redirect_msg:
                    from urllib.parse import unquote

                    echo(f"  {f_label('Detail:')} {unquote(redirect_msg)[:200]}")
            except Exception as e:
                info(f"(Could not fetch captcha details: {e})")

        blank()

        # Handle the captcha
        result = handle_captcha(
            session,
            captcha_error,
            interactive=True,
            auto_open_browser=open_browser,
        )

        if result == "resolved":
            # Verify by retesting
            blank()
            try:
                resp2 = _test_request()
                if resp2.status_code == 200:
                    success("Verification successful — session is now working.")
                else:
                    warning(f"Still getting status {resp2.status_code} after verification.")
                    captcha_error2 = detect_captcha(resp2)
                    if captcha_error2:
                        echo("   Captcha is still active. Try using a browser or 'zhihu auth login'.")
            except Exception as e:
                warning(f"Error during verification test: {e}")
        elif result == "skipped":
            echo("Skipped. You can retry later with 'zhihu auth captcha'.")
        else:
            echo("Cancelled.")

        # Restore original handler mode
        session.captcha_handler = old_handler
