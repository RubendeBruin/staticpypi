from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

from staticpypi import htaccess
from staticpypi.ftp_repository import FTPRepository
from staticpypi.index_builder import (
    build_package_index,
    build_root_index,
    group_wheels_by_package,
)
from staticpypi.settings import ConnectionSettings


def _connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=os.environ.get("STATICPYPI_HOST", ""), help="FTP host, optionally host:port (env: STATICPYPI_HOST)")
    parser.add_argument("--username", default=os.environ.get("STATICPYPI_USERNAME", ""), help="FTP username (env: STATICPYPI_USERNAME)")
    parser.add_argument("--password", default=os.environ.get("STATICPYPI_PASSWORD", ""), help="FTP password (env: STATICPYPI_PASSWORD)")
    parser.add_argument("--remote-root", default=os.environ.get("STATICPYPI_REMOTE_ROOT", "/"), help="Remote root path (env: STATICPYPI_REMOTE_ROOT)")


def _make_cfg(args: argparse.Namespace) -> ConnectionSettings:
    if not args.host:
        print("Error: --host is required (or set STATICPYPI_HOST)", file=sys.stderr)
        sys.exit(1)
    return ConnectionSettings(
        host=args.host,
        username=args.username,
        password=args.password,
        remote_root=args.remote_root or "/",
    )


def _update_indices(repo: FTPRepository, extra_wheels: list[str] | None = None) -> None:
    existing_wheels = repo.list_wheels("packages")
    print(f"Found {len(existing_wheels)} wheel(s) on server.")

    all_wheels = sorted(set(existing_wheels + (extra_wheels or [])))
    grouped = group_wheels_by_package(all_wheels)

    repo.upload_text(build_root_index(list(grouped.keys())), "index.html")
    print("Updated index.html")

    for package, wheels in grouped.items():
        package_index = build_package_index(package, wheels)
        repo.upload_text(package_index, f"{package}/index.html")
    print(f"Updated {len(grouped)} package index file(s)")


def cmd_publish(args: argparse.Namespace) -> int:
    cfg = _make_cfg(args)
    wheel_paths: list[Path] = []
    for pattern in args.wheels:
        matches = list(Path().glob(pattern)) if "*" in pattern else [Path(pattern)]
        wheel_paths.extend(p for p in matches if p.suffix.lower() == ".whl")

    if not wheel_paths:
        print("Error: no .whl files found.", file=sys.stderr)
        return 1

    try:
        with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
            for wheel in wheel_paths:
                repo.upload_file(wheel, f"packages/{wheel.name}")
                print(f"Uploaded {wheel.name}")
            _update_indices(repo, [p.name for p in wheel_paths])
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    cfg = _make_cfg(args)
    try:
        with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
            _update_indices(repo)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from staticpypi.main import main as gui_main
    except ImportError:
        print(
            "Error: the GUI requires PySide6. Install with: pip install 'staticpypi[gui]'\n"
            "or run with: uvx --from 'staticpypi[gui]' staticpypi gui",
            file=sys.stderr,
        )
        return 1
    return gui_main()


def _htpasswd_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--htpasswd-path",
        default=os.environ.get("STATICPYPI_HTPASSWD_PATH", htaccess.DEFAULT_HTPASSWD_PATH),
        help="Remote path of the password file, relative to the remote root (env: STATICPYPI_HTPASSWD_PATH)",
    )


def _credential_args(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument("--auth-user", help=f"Index user {what}")
    parser.add_argument("--auth-password", help=f"Index user password {what} (prompted for if omitted)")


def _prompt_password(user: str, confirm: bool) -> str:
    password = getpass.getpass(f"Password for index user {user!r}: ")
    if confirm and getpass.getpass("Repeat password: ") != password:
        raise ValueError("Passwords do not match.")
    return password


def _run_with_repo(args: argparse.Namespace, action: Callable[[FTPRepository], int]) -> int:
    cfg = _make_cfg(args)
    try:
        with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
            return action(repo)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_user(args: argparse.Namespace) -> int:
    htpasswd_path = args.htpasswd_path

    if args.user_command == "add":
        try:
            htaccess.validate_username(args.name)
            password = args.auth_password or _prompt_password(args.name, confirm=True)
            htaccess.hash_password(password)  # fail on an unusable password before connecting
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        def add(repo: FTPRepository) -> int:
            created = htaccess.set_user_password(repo, args.name, password, htpasswd_path)
            print(f"{'Added' if created else 'Updated password of'} user {args.name!r}.")
            if not htaccess.is_protected(repo.download_text(htaccess.HTACCESS_PATH)):
                print("Note: protection is not enabled yet; run 'staticpypi protect enable'.")
            return 0

        return _run_with_repo(args, add)

    if args.user_command == "remove":

        def remove(repo: FTPRepository) -> int:
            if not htaccess.remove_user(repo, args.name, htpasswd_path):
                print(f"Error: user {args.name!r} does not exist.", file=sys.stderr)
                return 1
            print(f"Removed user {args.name!r}.")
            if not htaccess.load_users(repo, htpasswd_path):
                print("Warning: no users left; with protection enabled nobody can read the index.")
            return 0

        return _run_with_repo(args, remove)

    def list_users(repo: FTPRepository) -> int:
        users = htaccess.load_users(repo, htpasswd_path)
        for name in users:
            print(name)
        if not users:
            print("No users.")
        return 0

    return _run_with_repo(args, list_users)


def _run_checks(url: str, user: str | None, password: str | None, htpasswd_path: str) -> int:
    if user and password is None:
        password = _prompt_password(user, confirm=False)
    if password is not None and not user:
        print("Error: --auth-password requires --auth-user.", file=sys.stderr)
        return 1
    print(f"Checking protection of {url}")
    results = htaccess.check_protection(url, user, password, htpasswd_path)
    for result in results:
        print(f"  [{'PASS' if result.passed else 'FAIL'}] {result.name}: {result.detail}")
    if not user:
        print("  (pass --auth-user to also verify valid logins and that the password file is not downloadable)")
    ok = all(r.passed for r in results)
    print("Protection verified." if ok else "Protection check FAILED.")
    return 0 if ok else 1


def cmd_protect(args: argparse.Namespace) -> int:
    if args.protect_command == "test":
        return _run_checks(args.url, args.auth_user, args.auth_password, args.htpasswd_path)

    if args.protect_command == "enable":

        def enable(repo: FTPRepository) -> int:
            if htaccess.has_foreign_auth(repo.download_text(htaccess.HTACCESS_PATH)):
                print("Warning: .htaccess already contains authentication directives outside the staticpypi block.")
            htaccess.enable_protection(repo, args.auth_user_file, args.htpasswd_path, args.realm)
            print("Protection enabled (.htaccess updated).")
            return 0

        code = _run_with_repo(args, enable)
        if code == 0 and args.test_url:
            return _run_checks(args.test_url, args.auth_user, args.auth_password, args.htpasswd_path)
        if code == 0:
            print("Run 'staticpypi protect test URL' to verify that it works on the server.")
        return code

    def disable(repo: FTPRepository) -> int:
        if htaccess.disable_protection(repo):
            print("Protection disabled (staticpypi block removed from .htaccess). The password file was kept.")
        else:
            print("Protection was not enabled by staticpypi; nothing changed.")
        return 0

    return _run_with_repo(args, disable)


def main() -> int:
    parser = argparse.ArgumentParser(prog="staticpypi", description="Manage a static PyPI index over FTP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish", help="Upload wheel files and update indices")
    _connection_args(publish_parser)
    publish_parser.add_argument("wheels", nargs="+", metavar="WHEEL", help=".whl file(s) to upload")

    update_parser = subparsers.add_parser("update", help="Rebuild indices without uploading new packages")
    _connection_args(update_parser)

    user_parser = subparsers.add_parser("user", help="Manage the users who may read the index (.htpasswd)")
    user_sub = user_parser.add_subparsers(dest="user_command", required=True)
    user_add = user_sub.add_parser("add", help="Add a user, or change the password of an existing one")
    user_add.add_argument("name", help="Index user name")
    user_add.add_argument("--auth-password", help="Password for the user (prompted for if omitted)")
    user_remove = user_sub.add_parser("remove", help="Remove a user")
    user_remove.add_argument("name", help="Index user name")
    user_list = user_sub.add_parser("list", help="List users")
    for sub in (user_add, user_remove, user_list):
        _connection_args(sub)
        _htpasswd_arg(sub)

    protect_parser = subparsers.add_parser("protect", help="Require a login to read the index (Apache .htaccess)")
    protect_sub = protect_parser.add_subparsers(dest="protect_command", required=True)
    protect_enable = protect_sub.add_parser("enable", help="Write the basic-auth block into .htaccess")
    _connection_args(protect_enable)
    _htpasswd_arg(protect_enable)
    protect_enable.add_argument(
        "--auth-user-file",
        default=os.environ.get("STATICPYPI_AUTH_USER_FILE", ""),
        required=not os.environ.get("STATICPYPI_AUTH_USER_FILE"),
        help="Absolute path of the password file as seen by the web server (env: STATICPYPI_AUTH_USER_FILE)",
    )
    protect_enable.add_argument("--realm", default=htaccess.DEFAULT_REALM, help="Login prompt text")
    protect_enable.add_argument("--test-url", help="Public URL of the index; if given, run the protection test afterwards")
    _credential_args(protect_enable, "to use for --test-url")
    protect_disable = protect_sub.add_parser("disable", help="Remove the staticpypi block from .htaccess")
    _connection_args(protect_disable)
    protect_test = protect_sub.add_parser("test", help="Verify over HTTP that the index really requires a login")
    protect_test.add_argument("url", help="Public URL of the index, e.g. https://example.com/pypi")
    _credential_args(protect_test, "to verify (optional)")
    _htpasswd_arg(protect_test)

    subparsers.add_parser("gui", help="Launch the desktop GUI (requires the 'gui' extra)")

    args = parser.parse_args()

    if args.command == "gui":
        return cmd_gui(args)
    if args.command == "user":
        return cmd_user(args)
    if args.command == "protect":
        return cmd_protect(args)
    if args.command == "publish":
        return cmd_publish(args)
    elif args.command == "update":
        return cmd_update(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
