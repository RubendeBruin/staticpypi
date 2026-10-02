from __future__ import annotations

import base64
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import bcrypt
import pytest

from staticpypi import cli, htaccess


class FakeRepo:
    """In-memory stand-in for FTPRepository."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = dict(files or {})

    def __enter__(self) -> "FakeRepo":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def download_text(self, remote_path: str) -> str | None:
        return self.files.get(remote_path)

    def upload_text(self, content: str, remote_path: str) -> None:
        self.files[remote_path] = content

    def delete_file(self, remote_path: str) -> None:
        del self.files[remote_path]


# --- htpasswd -------------------------------------------------------------------------------


def test_hash_is_apache_bcrypt_and_verifies() -> None:
    hashed = htaccess.hash_password("s3cret")
    assert hashed.startswith("$2y$12$")
    assert bcrypt.checkpw(b"s3cret", hashed.encode())
    assert not bcrypt.checkpw(b"other", hashed.encode())


@pytest.mark.parametrize("password", ["", "x" * 73])
def test_hash_rejects_unusable_passwords(password: str) -> None:
    with pytest.raises(ValueError):
        htaccess.hash_password(password)


@pytest.mark.parametrize("name", ["", " alice", "al:ice", "al\nice"])
def test_invalid_usernames(name: str) -> None:
    with pytest.raises(ValueError):
        htaccess.validate_username(name)


def test_htpasswd_roundtrip_keeps_foreign_hashes() -> None:
    text = "# comment\nalice:$apr1$abc$def\n\nbob:$2y$12$xyz\n"
    users = htaccess.parse_htpasswd(text)
    assert users == {"alice": "$apr1$abc$def", "bob": "$2y$12$xyz"}
    assert htaccess.format_htpasswd(users) == "alice:$apr1$abc$def\nbob:$2y$12$xyz\n"


def test_add_update_remove_user() -> None:
    repo = FakeRepo()
    assert htaccess.set_user_password(repo, "alice", "pw1") is True
    first = htaccess.load_users(repo)["alice"]
    assert htaccess.set_user_password(repo, "alice", "pw2") is False
    assert htaccess.load_users(repo)["alice"] != first
    assert htaccess.remove_user(repo, "alice") is True
    assert htaccess.remove_user(repo, "alice") is False
    assert htaccess.load_users(repo) == {}


# --- htaccess -------------------------------------------------------------------------------


def test_block_contents() -> None:
    block = htaccess.build_protection_block("/home/me/.htpasswd")
    assert 'AuthUserFile "/home/me/.htpasswd"' in block
    assert "Require valid-user" in block
    assert '<Files ".htpasswd">' in block


@pytest.mark.parametrize("value", ['/a"b', "/a\nb", ""])
def test_block_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        htaccess.build_protection_block(value)


def test_merge_is_idempotent_and_preserves_other_content() -> None:
    block = htaccess.build_protection_block("/p/.htpasswd")
    once = htaccess.merge_protection_block("Options -Indexes\n", block)
    assert once.startswith("Options -Indexes\n")
    assert htaccess.merge_protection_block(once, block) == once

    changed = htaccess.build_protection_block("/other/.htpasswd")
    twice = htaccess.merge_protection_block(once, changed)
    assert twice.count(htaccess.MANAGED_BEGIN) == 1
    assert "/other/.htpasswd" in twice and "/p/.htpasswd" not in twice
    assert twice.startswith("Options -Indexes\n")


def test_merge_handles_crlf() -> None:
    block = htaccess.build_protection_block("/p/.htpasswd")
    existing = htaccess.merge_protection_block("Options -Indexes\n", block).replace("\n", "\r\n")
    assert htaccess.is_protected(existing)
    assert htaccess.remove_protection_block(existing) == "Options -Indexes\n"


def test_remove_block() -> None:
    block = htaccess.build_protection_block("/p/.htpasswd")
    assert htaccess.remove_protection_block(block) == ""
    merged = htaccess.merge_protection_block("Options -Indexes\n", block)
    assert htaccess.remove_protection_block(merged) == "Options -Indexes\n"


def test_foreign_auth_detection() -> None:
    block = htaccess.build_protection_block("/p/.htpasswd")
    assert not htaccess.has_foreign_auth(block)
    assert htaccess.has_foreign_auth("AuthType Basic\nRequire valid-user\n" + block)


def test_enable_refuses_without_users() -> None:
    repo = FakeRepo()
    with pytest.raises(ValueError, match="at least one user"):
        htaccess.enable_protection(repo, "/p/.htpasswd")
    assert ".htaccess" not in repo.files


def test_enable_then_disable() -> None:
    repo = FakeRepo({".htaccess": "Options -Indexes\n"})
    htaccess.set_user_password(repo, "alice", "pw")
    htaccess.enable_protection(repo, "/p/.htpasswd")
    assert htaccess.is_protected(repo.files[".htaccess"])

    assert htaccess.disable_protection(repo) is True
    assert repo.files[".htaccess"] == "Options -Indexes\n"
    assert htaccess.disable_protection(repo) is False
    assert ".htpasswd" in repo.files  # password file is kept


def test_disable_deletes_htaccess_when_nothing_else_is_left() -> None:
    repo = FakeRepo()
    htaccess.set_user_password(repo, "alice", "pw")
    htaccess.enable_protection(repo, "/p/.htpasswd")
    htaccess.disable_protection(repo)
    assert ".htaccess" not in repo.files


# --- check_protection against a local HTTP server -------------------------------------------

USER, PASSWORD = "alice", "s3cret"


def _make_handler(mode: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _authorized(self) -> bool:
            expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
            return self.headers.get("Authorization") == expected

        def _reply(self, status: int, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_GET(self) -> None:
            if mode == "open":
                return self._reply(200)
            if mode == "broken":
                return self._reply(500)
            if mode == "redirect":
                return self._reply(301, {"Location": "https://example.invalid/"})
            if not self._authorized():
                return self._reply(401, {"WWW-Authenticate": 'Basic realm="Private PyPI"'})
            if self.path.endswith(".htpasswd"):
                return self._reply(200 if mode == "leaky" else 403)
            self._reply(200)

    return Handler


@pytest.fixture
def serve():
    servers: list[HTTPServer] = []

    def start(mode: str) -> str:
        server = HTTPServer(("127.0.0.1", 0), _make_handler(mode))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}/pypi"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _failed(results: list[htaccess.CheckResult]) -> set[str]:
    return {r.name for r in results if not r.passed}


def test_check_passes_on_protected_site(serve) -> None:
    results = htaccess.check_protection(serve("protected"), USER, PASSWORD)
    assert len(results) == 5
    assert _failed(results) == set()


def test_check_without_credentials_runs_anonymous_checks_only(serve) -> None:
    results = htaccess.check_protection(serve("protected"))
    assert len(results) == 3
    assert _failed(results) == set()


def test_check_detects_open_site(serve) -> None:
    results = htaccess.check_protection(serve("open"), USER, PASSWORD)
    failed = _failed(results)
    assert {"anonymous /index.html", "anonymous /packages/", "wrong credentials /index.html"} <= failed
    assert "readable without a login" in next(r.detail for r in results if r.name == "anonymous /index.html")


def test_check_detects_server_error_from_bad_auth_user_file(serve) -> None:
    results = htaccess.check_protection(serve("broken"), USER, PASSWORD)
    assert "valid credentials /index.html" in _failed(results)
    assert "AuthUserFile" in next(r.detail for r in results if r.name == "valid credentials /index.html")


def test_check_detects_downloadable_password_file(serve) -> None:
    results = htaccess.check_protection(serve("leaky"), USER, PASSWORD)
    assert _failed(results) == {"password file /.htpasswd"}


def test_check_detects_rejected_credentials(serve) -> None:
    results = htaccess.check_protection(serve("protected"), USER, "wrong")
    assert _failed(results) == {"valid credentials /index.html", "password file /.htpasswd"}


def test_check_does_not_follow_redirects(serve) -> None:
    results = htaccess.check_protection(serve("redirect"))
    assert _failed(results) == {r.name for r in results}
    assert "redirects to" in results[0].detail


def test_check_reports_unreachable_server() -> None:
    results = htaccess.check_protection("http://127.0.0.1:1/pypi", timeout=2)
    assert _failed(results) == {r.name for r in results}
    assert "could not connect" in results[0].detail


# --- CLI ------------------------------------------------------------------------------------


@pytest.fixture
def cli_repo(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(cli, "FTPRepository", lambda *a, **k: repo)
    return repo


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["staticpypi", *argv])
    return cli.main()


FTP = ("--host", "ftp.example.com", "--username", "u", "--password", "p")


def test_cli_user_and_protect_flow(monkeypatch, capsys, cli_repo, serve) -> None:
    assert _run(monkeypatch, "user", "add", "alice", "--auth-password", PASSWORD, *FTP) == 0
    assert _run(monkeypatch, "user", "list", *FTP) == 0
    assert "alice" in capsys.readouterr().out

    assert _run(monkeypatch, "protect", "enable", "--auth-user-file", "/p/.htpasswd", *FTP) == 0
    assert htaccess.is_protected(cli_repo.files[".htaccess"])

    assert _run(monkeypatch, "protect", "test", serve("protected"), "--auth-user", USER, "--auth-password", PASSWORD) == 0
    assert _run(monkeypatch, "protect", "test", serve("open")) == 1
    assert "Protection check FAILED" in capsys.readouterr().out

    assert _run(monkeypatch, "protect", "disable", *FTP) == 0
    assert ".htaccess" not in cli_repo.files


def test_cli_enable_without_users_fails(monkeypatch, capsys, cli_repo) -> None:
    assert _run(monkeypatch, "protect", "enable", "--auth-user-file", "/p/.htpasswd", *FTP) == 1
    assert "at least one user" in capsys.readouterr().err


def test_cli_remove_unknown_user_fails(monkeypatch, cli_repo) -> None:
    assert _run(monkeypatch, "user", "remove", "ghost", *FTP) == 1


def test_cli_enable_with_test_url_returns_check_result(monkeypatch, cli_repo, serve) -> None:
    _run(monkeypatch, "user", "add", "alice", "--auth-password", PASSWORD, *FTP)
    argv = ["protect", "enable", "--auth-user-file", "/p/.htpasswd", *FTP, "--auth-user", USER, "--auth-password", PASSWORD]
    assert _run(monkeypatch, *argv, "--test-url", serve("protected")) == 0
    assert _run(monkeypatch, *argv, "--test-url", serve("open")) == 1
