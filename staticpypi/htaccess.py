"""Access control for the static index: .htpasswd users, .htaccess protection, and a verification check."""

from __future__ import annotations

import re
import secrets
import urllib.error
import urllib.request
from base64 import b64encode
from dataclasses import dataclass
from posixpath import basename
from typing import Protocol

import bcrypt

DEFAULT_HTPASSWD_PATH = ".htpasswd"
DEFAULT_REALM = "Private PyPI"
HTACCESS_PATH = ".htaccess"

MANAGED_BEGIN = "# BEGIN staticpypi"
MANAGED_END = "# END staticpypi"
_MANAGED_RE = re.compile(
    rf"^{re.escape(MANAGED_BEGIN)}\n.*?^{re.escape(MANAGED_END)}\n?",
    re.DOTALL | re.MULTILINE,
)

BCRYPT_MAX_BYTES = 72


class Repository(Protocol):
    """The subset of FTPRepository used here."""

    def download_text(self, remote_path: str) -> str | None: ...
    def upload_text(self, content: str, remote_path: str) -> None: ...
    def delete_file(self, remote_path: str) -> None: ...


# --- htpasswd -------------------------------------------------------------------------------


def validate_username(username: str) -> None:
    if not username or username != username.strip():
        raise ValueError("Username must be non-empty and have no leading/trailing whitespace.")
    if ":" in username or any(ch in username for ch in "\r\n\t"):
        raise ValueError("Username must not contain ':' or control characters.")


def hash_password(password: str) -> str:
    """Return a bcrypt hash in the `$2y$` form that Apache expects (as written by `htpasswd -B`)."""
    raw = password.encode("utf-8")
    if not raw:
        raise ValueError("Password must not be empty.")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes (bcrypt limit).")
    hashed = bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")
    return "$2y$" + hashed[4:]


def parse_htpasswd(text: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, hashed = line.split(":", 1)
        users[name] = hashed
    return users


def format_htpasswd(users: dict[str, str]) -> str:
    return "".join(f"{name}:{hashed}\n" for name, hashed in users.items())


# --- htaccess -------------------------------------------------------------------------------


def _check_directive_value(label: str, value: str) -> None:
    if not value or any(ch in value for ch in '"\r\n'):
        raise ValueError(f"{label} must be non-empty and must not contain quotes or newlines.")


def build_protection_block(auth_user_file: str, realm: str = DEFAULT_REALM) -> str:
    """The managed .htaccess section: basic auth for the whole tree, and the password file itself is denied."""
    _check_directive_value("Auth user file", auth_user_file)
    _check_directive_value("Realm", realm)
    password_file_name = basename(auth_user_file.replace("\\", "/"))
    return (
        f"{MANAGED_BEGIN}\n"
        "AuthType Basic\n"
        f'AuthName "{realm}"\n'
        f'AuthUserFile "{auth_user_file}"\n'
        "Require valid-user\n"
        f'<Files "{password_file_name}">\n'
        "    Require all denied\n"
        "</Files>\n"
        f"{MANAGED_END}\n"
    )


def _norm(text: str | None) -> str:
    return (text or "").replace("\r\n", "\n")


def merge_protection_block(existing: str | None, block: str) -> str:
    """Insert or replace the managed block, leaving any other .htaccess content untouched."""
    existing = _norm(existing)
    if _MANAGED_RE.search(existing):
        return _MANAGED_RE.sub(lambda _m: block, existing, count=1)
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + ("\n" if existing.strip() else "") + block


def remove_protection_block(existing: str | None) -> str:
    """Return the .htaccess content without the managed block (empty string if nothing else is left)."""
    remaining = _MANAGED_RE.sub("", _norm(existing), count=1).strip()
    return remaining + "\n" if remaining else ""


def has_foreign_auth(existing: str | None) -> bool:
    """True if the file has authentication directives outside the managed block (e.g. hand-written ones)."""
    outside = _MANAGED_RE.sub("", _norm(existing))
    return bool(re.search(r"^\s*(AuthType|AuthUserFile|Require)\b", outside, re.MULTILINE))


def is_protected(htaccess_text: str | None) -> bool:
    return bool(_MANAGED_RE.search(_norm(htaccess_text)))


# --- operations on the server ---------------------------------------------------------------


def load_users(repo: Repository, htpasswd_path: str = DEFAULT_HTPASSWD_PATH) -> dict[str, str]:
    return parse_htpasswd(repo.download_text(htpasswd_path) or "")


def set_user_password(
    repo: Repository, username: str, password: str, htpasswd_path: str = DEFAULT_HTPASSWD_PATH
) -> bool:
    """Add the user or replace their password. Returns True if the user was newly created."""
    validate_username(username)
    hashed = hash_password(password)
    users = load_users(repo, htpasswd_path)
    created = username not in users
    users[username] = hashed
    repo.upload_text(format_htpasswd(users), htpasswd_path)
    return created


def remove_user(repo: Repository, username: str, htpasswd_path: str = DEFAULT_HTPASSWD_PATH) -> bool:
    """Returns False if the user did not exist."""
    users = load_users(repo, htpasswd_path)
    if username not in users:
        return False
    del users[username]
    repo.upload_text(format_htpasswd(users), htpasswd_path)
    return True


def enable_protection(
    repo: Repository,
    auth_user_file: str,
    htpasswd_path: str = DEFAULT_HTPASSWD_PATH,
    realm: str = DEFAULT_REALM,
) -> None:
    """Write the managed block into .htaccess. Refuses if there are no users, which would lock everyone out."""
    if not load_users(repo, htpasswd_path):
        raise ValueError(f"No users found in {htpasswd_path!r}; add at least one user before enabling protection.")
    block = build_protection_block(auth_user_file, realm)
    repo.upload_text(merge_protection_block(repo.download_text(HTACCESS_PATH), block), HTACCESS_PATH)


def disable_protection(repo: Repository) -> bool:
    """Remove the managed block. Returns False if protection was not enabled by staticpypi."""
    existing = repo.download_text(HTACCESS_PATH)
    if not is_protected(existing):
        return False
    remaining = remove_protection_block(existing)
    if remaining:
        repo.upload_text(remaining, HTACCESS_PATH)
    else:
        repo.delete_file(HTACCESS_PATH)
    return True


# --- verification ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[override]
        return None  # never follow: credentials must not be forwarded to wherever a redirect points


def _status(url: str, credentials: tuple[str, str] | None, timeout: float) -> tuple[int | None, str]:
    """GET the URL and return (status, note). status is None if the server could not be reached."""
    request = urllib.request.Request(url, method="GET")
    if credentials:
        token = b64encode(f"{credentials[0]}:{credentials[1]}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(1)
            return response.status, ""
    except urllib.error.HTTPError as exc:
        challenge = exc.headers.get("WWW-Authenticate", "")
        location = exc.headers.get("Location", "")
        note = f"challenge: {challenge}" if challenge else (f"redirects to {location}" if location else "")
        return exc.code, note
    except (urllib.error.URLError, OSError) as exc:
        return None, str(getattr(exc, "reason", exc))


def check_protection(
    base_url: str,
    username: str | None = None,
    password: str | None = None,
    password_file_name: str = DEFAULT_HTPASSWD_PATH,
    timeout: float = 15.0,
) -> list[CheckResult]:
    """Probe the public URL and report whether the index really requires authentication.

    Without credentials this checks that anonymous and wrong-credential requests are rejected.
    With credentials it additionally checks that they are accepted and that the password file is not downloadable.
    """
    base = base_url.rstrip("/")
    results: list[CheckResult] = []

    server_error = "server error - the AuthUserFile path is probably wrong, or .htaccess is not allowed (AllowOverride)"

    def expect(name: str, url: str, credentials: tuple[str, str] | None, accepted: tuple[int, ...], hints: dict[int, str]) -> None:
        status, note = _status(url, credentials, timeout)
        wanted = " or ".join(str(code) for code in accepted)
        if status is None:
            detail = f"could not connect: {note}"
        elif status in accepted:
            detail = f"HTTP {status} as expected"
        else:
            hint = hints.get(status, server_error if status >= 500 else "")
            detail = f"expected {wanted}, got HTTP {status}" + (f" ({hint})" if hint else "") + (f"; {note}" if note else "")
        results.append(CheckResult(name, status in accepted, detail))

    probe = (f"staticpypi-probe-{secrets.token_hex(4)}", secrets.token_urlsafe(12))
    for path in ("index.html", "packages/"):
        expect(f"anonymous /{path}", f"{base}/{path}", None, (401,), {200: "readable without a login"})
    expect(
        "wrong credentials /index.html",
        f"{base}/index.html",
        probe,
        (401,),
        {200: "any login is accepted"},
    )

    if username is not None and password is not None:
        creds = (username, password)
        expect(
            "valid credentials /index.html",
            f"{base}/index.html",
            creds,
            (200,),
            {401: "login rejected - wrong password, or the server cannot read/verify the password file"},
        )
        expect(
            f"password file /{password_file_name}",
            f"{base}/{password_file_name}",
            creds,
            (403, 404),
            {200: "the password file is downloadable!"},
        )
    return results
