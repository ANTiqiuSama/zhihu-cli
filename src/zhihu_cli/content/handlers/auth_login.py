"""QR code login for Zhihu.

The implementation combines curl-cffi browser impersonation and explicit
risk-control handling with an Agent-friendly QR image written to disk.
"""

import os
import sys
import time
import webbrowser
from pathlib import Path

from curl_cffi import requests as curl_requests

from zhihu_cli.content.handlers import get_user_agent
from zhihu_cli.content.utils.wait import wait

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
CHROME_SEC_CH_UA = '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
EDGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
)
EDGE_SEC_CH_UA = '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"'
DESKTOP_SEC_CH_UA_MOBILE = "?0"
DESKTOP_SEC_CH_UA_PLATFORM = '"Windows"'
BROWSER_CHOICES = ("auto", "edge", "chrome")

SIGNIN_URL = "https://www.zhihu.com/signin?next=%2F"
SIGNIN_REFERER = "https://www.zhihu.com/signin"
UDID_URL = "https://www.zhihu.com/udid"
CAPTCHA_URL = "https://www.zhihu.com/api/v3/oauth/captcha/v2?type=captcha_sign_in"
QRCODE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode"
ME_URL = "https://www.zhihu.com/api/v4/me"
HOME_URL = "https://www.zhihu.com/"
RISK_CONTROL_FALLBACK = "https://www.zhihu.com/account/risk_control/"
DEFAULT_QR_PATH = Path.home() / ".zhihu-cli" / "login_qrcode.png"

RISK_CONTROL_EXIT = object()


def _read_windows_https_progid() -> str | None:
    """Return the current Windows HTTPS handler ProgId, if available."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "ProgId")
        return str(value)
    except (ImportError, OSError):
        return None


def _browser_from_user_agent(user_agent: str) -> str | None:
    if "Edg/" in user_agent:
        return "edge"
    if "Chrome/" in user_agent:
        return "chrome"
    return None


def _resolve_browser(browser: str = "auto") -> str:
    """Resolve an explicit or automatic browser choice for login identity."""
    normalized = browser.lower()
    if normalized not in BROWSER_CHOICES:
        raise ValueError(f"Unsupported browser {browser!r}; choose auto, edge, or chrome")
    if normalized != "auto":
        return normalized

    configured = get_user_agent() or ""
    configured_browser = _browser_from_user_agent(configured)
    if configured_browser:
        return configured_browser

    progid = (_read_windows_https_progid() or "").lower()
    if "msedge" in progid:
        return "edge"
    if "chrome" in progid:
        return "chrome"
    return "chrome"


def _browser_identity(browser: str = "auto") -> tuple[str, str, str]:
    """Return (browser family, User-Agent, sec-ch-ua) for QR login."""
    normalized = browser.lower()
    resolved = _resolve_browser(normalized)
    configured = get_user_agent() if normalized == "auto" else None
    if resolved == "edge":
        return resolved, configured or EDGE_USER_AGENT, EDGE_SEC_CH_UA
    return resolved, configured or CHROME_USER_AGENT, CHROME_SEC_CH_UA


def _browser_executable(browser: str) -> Path | None:
    if sys.platform != "win32":
        return None
    roots = [
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA"),
    ]
    relative_paths = {
        "edge": Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
        "chrome": Path("Google") / "Chrome" / "Application" / "chrome.exe",
    }
    relative = relative_paths[browser]
    for root in roots:
        if not root:
            continue
        candidate = Path(root) / relative
        if candidate.is_file():
            return candidate
    return None


def _open_browser_url(url: str, browser: str = "auto") -> bool:
    """Open *url* in the selected browser without a silent explicit-choice fallback."""
    normalized = browser.lower()
    resolved = _resolve_browser(normalized)
    if normalized == "auto":
        return bool(webbrowser.open(url, new=2))

    executable = _browser_executable(resolved)
    if executable is None:
        raise RuntimeError(f"Requested browser '{resolved}' is not installed or could not be located")
    return bool(webbrowser.BackgroundBrowser(str(executable)).open(url, new=2))


def _desktop_headers(referer: str | None = None, *, browser: str = "auto") -> dict[str, str]:
    _, ua, sec_ch_ua = _browser_identity(browser)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": ua,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": DESKTOP_SEC_CH_UA_MOBILE,
        "sec-ch-ua-platform": DESKTOP_SEC_CH_UA_PLATFORM,
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _login_headers(
    session: curl_requests.Session,
    referer: str,
    *,
    polling: bool = False,
    browser: str = "auto",
) -> dict[str, str]:
    headers = _desktop_headers(referer, browser=browser)
    headers["Origin"] = HOME_URL.rstrip("/")
    headers["x-requested-with"] = "fetch"
    headers["content-type"] = "application/json;charset=UTF-8"
    if polling:
        headers["Accept"] = "*/*"
        headers["sec-fetch-dest"] = "empty"
        headers["sec-fetch-mode"] = "cors"
        headers["sec-fetch-site"] = "same-origin"
        headers["x-zse-93"] = "101_3_3.0"
    xsrf = _cookie_value(session, "_xsrf")
    if xsrf:
        headers["x-xsrftoken"] = xsrf
    return headers


def _cookie_value(session: curl_requests.Session, name: str) -> str | None:
    return session.cookies.get(name)


def _cookies_to_header(session: curl_requests.Session) -> str:
    parts = [f"{k}={v}" for k, v in session.cookies.get_dict().items() if k and v]
    return "; ".join(parts)


def _resolve_qr_path(qr_path: str | Path | None) -> Path:
    path = Path(qr_path).expanduser() if qr_path else DEFAULT_QR_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _print_qr(url: str, qr_path: str | Path | None = None) -> Path:
    print("Scan the QR code with the Zhihu App:\n")
    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make()
    qr.print_ascii(invert=True)
    output_path = _resolve_qr_path(qr_path)
    qr.make_image(fill_color="black", back_color="white").save(output_path)
    print(f"\nQR image saved to: {output_path}")
    print(f"\nOr open this link in browser: {url}\n")
    return output_path


def _detect_risk_control(data: dict) -> str | None:
    """If ``data`` contains a risk-control error, return the redirect URL."""
    error = data.get("error", {})
    if isinstance(error, dict):
        if error.get("code") == 40352 or error.get("need_login"):
            return error.get("redirect") or RISK_CONTROL_FALLBACK
    return None


def _prompt_risk_control_verification(
    session: curl_requests.Session,
    redirect_url: str,
    *,
    open_browser: bool = True,
    browser: str = "auto",
) -> None:
    """Prompt the user to complete browser verification, then refresh session cookies."""
    print()
    print("=" * 60)
    print("  ⚠️  Zhihu needs to verify your network environment.")
    print()
    print("  Open this URL in a \033[1mbrowser\033[0m:")
    print(f"  \033[34m{redirect_url}\033[0m")
    print()
    print("  After completing the verification, press Enter to continue...")
    print("=" * 60)

    if open_browser:
        try:
            opened = _open_browser_url(redirect_url, browser)
            if opened:
                print(f"  Opened the verification page in {_resolve_browser(browser)}.")
        except Exception as exc:
            print(f"  Could not open the requested browser automatically: {exc}")

    try:
        input()
    except (EOFError, KeyboardInterrupt):
        raise

    # After verification, re-visit risk_control page with the session to pick
    # up any new cookies that the verification set.
    try:
        session.get(redirect_url, headers=_login_headers(session, SIGNIN_REFERER, browser=browser))
    except Exception:
        pass


def _is_login_success(scan_info: dict) -> bool:
    """Return True when scan_info indicates the user successfully logged in."""
    if scan_info.get("user_id") or scan_info.get("userId"):
        return True
    if scan_info.get("zC0") or scan_info.get("z_c0"):
        return True
    if scan_info.get("access_token"):
        return True
    if scan_info.get("success") or scan_info.get("logged_in"):
        return True
    login_status = str(scan_info.get("loginStatus") or scan_info.get("login_status") or "").upper()
    if login_status in ("CONFIRMED", "LOGIN_SUCCESS", "SUCCESS", "OK", "LOGGED_IN"):
        return True
    return False


def _check_scan_result(scan_info: dict) -> str:
    """Check a scan_info response and return a result code.

    :param scan_info: The JSON response from the scan_info endpoint.
    :returns: ``"success"`` if login is complete, ``"risk"`` if risk control
        is triggered, or ``"waiting"`` otherwise.
    """
    if _detect_risk_control(scan_info):
        return "risk"
    if _is_login_success(scan_info):
        return "success"
    return "waiting"


def _handle_risk_control(
    session: curl_requests.Session,
    risk_url: str,
    risk_control_count: int,
    *,
    qr_path: str | Path | None = None,
    open_browser: bool = True,
    browser: str = "auto",
) -> tuple[str, str, float] | None:
    """Handle a risk control challenge during QR polling.

    Prompts the user to complete browser verification, then requests a fresh
    QR code. Returns the updated token, link, and deadline for the new QR
    code, or ``None`` if the QR code could not be refreshed.

    :param session: The current requests session.
    :param risk_url: URL for risk control verification.
    :param risk_control_count: Number of risk control events so far
        (1-indexed).
    :returns: ``(token, link, deadline)`` if a fresh QR was obtained, or
        ``None``.
    :raises RuntimeError: If ``risk_control_count > 3``.
    """
    if risk_control_count > 3:
        raise RuntimeError(
            "Too many risk-control challenges. Zhihu is throttling this network. "
            "Try again later or use 'zhihu auth paste' instead."
        )

    _prompt_risk_control_verification(session, risk_url, open_browser=open_browser, browser=browser)

    # Re-request a fresh QR code after verification
    resp = session.post(QRCODE_URL, json={}, headers=_login_headers(session, SIGNIN_REFERER, browser=browser))
    if resp.status_code != 200:
        return None

    data = resp.json()
    token = data.get("token") or data.get("qrcode_token")
    link = data.get("link")
    if not token or not link:
        return None

    _print_qr(link, qr_path)

    expires_at_raw = data.get("expires_at", 0)
    if 0 < expires_at_raw < 10_000_000_000:
        expires_at_raw *= 1000
    deadline = (expires_at_raw / 1000.0) if expires_at_raw else (time.time() + 120)

    return token, link, deadline


def qr_login(
    *,
    qr_path: str | Path | None = None,
    open_browser: bool = True,
    browser: str = "auto",
) -> dict[str, str]:
    """Execute QR code login flow. Returns headers dict suitable for cache_manager.save_headers()."""

    resolved_browser, user_agent, _ = _browser_identity(browser)
    session = curl_requests.Session(impersonate=resolved_browser)

    # Step 1: visit signin page to seed initial cookies (d_c0, _xsrf)
    session.get(SIGNIN_URL, headers=_desktop_headers(SIGNIN_REFERER, browser=browser))

    # Step 2: register device UDID
    try:
        session.post(UDID_URL, json={}, headers=_login_headers(session, SIGNIN_REFERER, browser=browser))
    except Exception:
        pass

    # Step 3: fetch captcha context
    try:
        session.get(CAPTCHA_URL, headers=_login_headers(session, SIGNIN_REFERER, browser=browser))
    except Exception:
        pass

    # Step 4: request QR code
    resp = session.post(QRCODE_URL, json={}, headers=_login_headers(session, SIGNIN_REFERER, browser=browser))
    data = resp.json()

    # Check for risk control before QR code is issued
    risk_url = _detect_risk_control(data)
    if risk_url:
        _prompt_risk_control_verification(session, risk_url, open_browser=open_browser, browser=browser)
        resp = session.post(QRCODE_URL, json={}, headers=_login_headers(session, SIGNIN_REFERER, browser=browser))
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to request QR code after verification: HTTP {resp.status_code}")
        data = resp.json()

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to request QR code: HTTP {resp.status_code}")

    token = data.get("token") or data.get("qrcode_token")
    link = data.get("link")
    if not token or not link:
        raise RuntimeError(f"QR code response missing token/link: {data}")

    # Step 5: display QR code
    _print_qr(link, qr_path)

    # Step 6: poll scan_info
    expires_at = data.get("expires_at", 0)
    if 0 < expires_at < 10_000_000_000:
        expires_at *= 1000
    if not expires_at or expires_at <= 0:
        expires_at = int(time.time() * 1000) + 120_000
    deadline = expires_at / 1000.0

    print("Waiting for scan...")
    scanned_reported = False
    risk_control_count = 0
    last_poll_error: Exception | None = None

    while time.time() < deadline:
        try:
            resp = session.get(
                f"{QRCODE_URL}/{token}/scan_info",
                headers=_login_headers(session, SIGNIN_URL, polling=True, browser=browser),
            )

            scan_info = resp.json() if resp.text else {}
            last_poll_error = None

            result = _check_scan_result(scan_info)

            # Guard: risk control encountered
            if result == "risk":
                risk_control_count += 1
                risk_url = _detect_risk_control(scan_info)
                refreshed = _handle_risk_control(
                    session,
                    risk_url,
                    risk_control_count,
                    qr_path=qr_path,
                    open_browser=open_browser,
                    browser=browser,
                )
                if refreshed:
                    token, link, deadline = refreshed
                    scanned_reported = False
                    print("Waiting for scan...")
                continue

            # Update z_c0 cookie from scan response
            zc0 = scan_info.get("zC0") or scan_info.get("z_c0")
            if zc0 and not _cookie_value(session, "z_c0"):
                session.cookies.set("z_c0", zc0, domain=".zhihu.com")

            if scan_info.get("status") == 1 and not scanned_reported:
                print("Scanned! Please confirm login in the Zhihu App...")
                scanned_reported = True

            # Guard: login complete
            if result == "success":
                if not _cookie_value(session, "z_c0"):
                    try:
                        session.get(ME_URL, headers=_login_headers(session, SIGNIN_URL, polling=True, browser=browser))
                    except Exception:
                        pass
                if _cookie_value(session, "z_c0") or scan_info.get("userId"):
                    break

        except KeyboardInterrupt:
            print("\nCancelled.")
            return {}
        except Exception as exc:
            last_poll_error = exc

        wait(1.0)

    if not _cookie_value(session, "z_c0"):
        if last_poll_error is not None:
            raise RuntimeError(
                "QR code polling failed before credentials were issued: "
                f"{type(last_poll_error).__name__}: {last_poll_error}"
            ) from last_poll_error
        raise RuntimeError("QR code expired or login was not completed. Please try again.")

    # Step 7: verify login and get username
    resp = session.get(ME_URL)
    if resp.status_code == 200:
        me = resp.json()
        username = me.get("name", "unknown")
        print(f"Login successful! Welcome, {username}.")

        headers = {
            "Cookie": _cookies_to_header(session),
            "User-Agent": user_agent,
        }
        return headers

    raise RuntimeError(f"Login verification failed: HTTP {resp.status_code}")
