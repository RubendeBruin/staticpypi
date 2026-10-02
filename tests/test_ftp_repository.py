from __future__ import annotations

import threading
from pathlib import Path

import pytest
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

from staticpypi import htaccess
from staticpypi.ftp_repository import FTPRepository, split_host_port


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("ftp.example.com", ("ftp.example.com", 21)),
        ("ftp.example.com:2121", ("ftp.example.com", 2121)),
        ("127.0.0.1:2121", ("127.0.0.1", 2121)),
        ("[::1]", ("::1", 21)),
        ("[::1]:2121", ("::1", 2121)),
        ("::1", ("::1", 21)),
        ("ftp.example.com:", ("ftp.example.com", 21)),
    ],
)
def test_split_host_port(host: str, expected: tuple[str, int]) -> None:
    assert split_host_port(host) == expected


@pytest.mark.parametrize("host", ["h:abc", "h:0", "h:70000"])
def test_split_host_port_rejects_bad_port(host: str) -> None:
    with pytest.raises(ValueError):
        split_host_port(host)


@pytest.fixture
def ftp_server(tmp_path: Path):
    authorizer = DummyAuthorizer()
    authorizer.add_user("u", "p", str(tmp_path), perm="elradfmw")

    class Handler(FTPHandler):
        pass

    Handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"handle_exit": False}, daemon=True)
    thread.start()
    yield f"127.0.0.1:{server.address[1]}", tmp_path
    server.close_all()
    thread.join(timeout=5)


def _repo(host: str, remote_root: str) -> FTPRepository:
    return FTPRepository(host, "u", "p", remote_root)


@pytest.mark.parametrize("remote_root", ["/", "/pypi", "/deep/er/pypi"])
def test_directories_are_created_below_the_remote_root(ftp_server, remote_root: str) -> None:
    host, home = ftp_server
    (home / remote_root.strip("/")).mkdir(parents=True, exist_ok=True)
    wheel = home / "pkg-1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")

    with _repo(host, remote_root) as repo:
        assert repo.list_wheels("packages") == []
        repo.upload_file(wheel, "packages/pkg-1.0-py3-none-any.whl")
        repo.upload_text("<html/>", "pkg/index.html")
        repo.upload_text("<html/>", "index.html")
        assert repo.list_wheels("packages") == ["pkg-1.0-py3-none-any.whl"]

    root = home / remote_root.strip("/")
    assert (root / "packages" / "pkg-1.0-py3-none-any.whl").read_bytes() == b"wheel"
    assert (root / "pkg" / "index.html").read_text() == "<html/>"
    assert (root / "index.html").exists()
    if remote_root != "/":
        assert not (home / "packages").exists()  # nothing leaked into the FTP root
        assert not (home / "pkg").exists()


def test_download_text(ftp_server) -> None:
    host, home = ftp_server
    with _repo(host, "/") as repo:
        assert repo.download_text("missing.txt") is None
        assert repo.download_text("no/such/dir/file.txt") is None
        repo.upload_text("héllo\n", "sub/file.txt")
        assert repo.download_text("sub/file.txt") == "héllo\n"
        assert repo.download_text("/sub/file.txt") == "héllo\n"


def test_protection_flow_over_real_ftp(ftp_server) -> None:
    host, home = ftp_server
    (home / "pypi").mkdir()
    with _repo(host, "/pypi") as repo:
        htaccess.set_user_password(repo, "alice", "pw")
        htaccess.enable_protection(repo, "/srv/.htpasswd")
    assert (home / "pypi" / ".htpasswd").read_text().startswith("alice:$2y$12$")
    assert 'AuthUserFile "/srv/.htpasswd"' in (home / "pypi" / ".htaccess").read_text()
    with _repo(host, "/pypi") as repo:
        assert htaccess.disable_protection(repo)
    assert not (home / "pypi" / ".htaccess").exists()
