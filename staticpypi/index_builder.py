from __future__ import annotations

from html import escape
from pathlib import Path
import re
from collections import defaultdict


_WHEEL_RE = re.compile(
    r"^(?P<name>.+?)-(?P<version>[^-]+)(?:-[^-]+){3,}\.whl$"
)


def normalize_project_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def package_from_wheel(filename: str) -> str:
    wheel_name = Path(filename).name
    match = _WHEEL_RE.match(wheel_name)
    if not match:
        raise ValueError(f"Unsupported wheel filename: {filename}")
    return normalize_project_name(match.group("name"))


def group_wheels_by_package(wheel_filenames: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for wheel in sorted(set(Path(w).name for w in wheel_filenames)):
        grouped[package_from_wheel(wheel)].append(wheel)
    return dict(grouped)


def build_root_index(packages: list[str]) -> str:
    links = "\n".join(
        f'<a href="{escape(package)}/">{escape(package)}</a><br/>'
        for package in sorted(set(packages))
    )
    return f"""<!doctype html>
<html>
  <head><meta charset=\"utf-8\"><title>Simple index</title></head>
  <body>
{links}
  </body>
</html>
"""


def build_package_index(package: str, wheels: list[str]) -> str:
    links = "\n".join(
        f'<a href="../../packages/{escape(wheel)}">{escape(wheel)}</a><br/>'
        for wheel in sorted(set(Path(w).name for w in wheels))
    )
    return f"""<!doctype html>
<html>
  <head><meta charset=\"utf-8\"><title>{escape(package)} wheels</title></head>
  <body>
{links}
  </body>
</html>
"""
