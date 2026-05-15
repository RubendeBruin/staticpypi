from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from staticpypi.ftp_repository import FTPRepository
from staticpypi.index_builder import (
    build_package_index,
    build_root_index,
    group_wheels_by_package,
)
from staticpypi.settings import ConnectionSettings


def _connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=os.environ.get("STATICPYPI_HOST", ""), help="FTP host (env: STATICPYPI_HOST)")
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="staticpypi-cli", description="Manage a static PyPI index over FTP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish", help="Upload wheel files and update indices")
    _connection_args(publish_parser)
    publish_parser.add_argument("wheels", nargs="+", metavar="WHEEL", help=".whl file(s) to upload")

    update_parser = subparsers.add_parser("update", help="Rebuild indices without uploading new packages")
    _connection_args(update_parser)

    args = parser.parse_args()

    if args.command == "publish":
        return cmd_publish(args)
    elif args.command == "update":
        return cmd_update(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
