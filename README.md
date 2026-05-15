# staticpypi
Maintain a PyPI-compatible index on a static server.

## Purpose

`staticpypi` is a desktop application for publishing Python wheel files (`.whl`) to a static host over FTP, while maintaining a `simple` index that tools like `pip` can consume.

The application:

- connects to an FTP server using user-provided credentials
- gathers existing wheel files from the server
- adds wheel file(s) selected by the user
- uploads the selected wheel files
- creates/updates the required simple-index HTML files

The result is a static directory/file structure that can be served over HTTP(S).

## Framework

- Python
- PySide6 for the desktop UI
- `QSettings` (PySide6 settings module) for storing host, username, password, and remote root

## Current implementation

The app provides:

- FTP host/username/password/remote-root configuration
- persistent settings storage through `QSettings`
- wheel file selection (`*.whl`)
- test connection action
- publish action that:
  - uploads wheel files to `packages/`
  - rebuilds and uploads:
    - `simple/index.html`
    - `simple/<normalized-package-name>/index.html`

Package names in the simple index are normalized per PEP 503 style (`[-_.]+` collapsed to `-`, lowercase).

## Installation

```bash
python -m pip install -e .
```

## Run

```bash
staticpypi
```

or:

```bash
python -m staticpypi.main
```

## Expected server layout

After publishing, your FTP root (or configured remote root) contains:

```text
packages/
  your_package-1.2.3-py3-none-any.whl
simple/
  index.html
  your-package/
    index.html
```

Where:

- `simple/index.html` links to package pages
- `simple/<package>/index.html` links to wheel files in `packages/`

## References

- [PyPA Simple Repository API](https://packaging.python.org/en/latest/specifications/simple-repository-api/)
- [PEP 503 - Simple Repository API](https://peps.python.org/pep-0503/)
