# staticpypi
Maintain a PyPI-compatible index on a static server.

## Purpose

`staticpypi` is a tool for publishing Python wheel files (`.whl`) to a static host over FTP, while maintaining an index that tools like `pip` and `uv` can consume.

It is available both as a **desktop GUI** and a **command-line interface (CLI)**.

The tool:

- connects to an FTP server using user-provided credentials
- gathers existing wheel files from the server
- uploads new wheel file(s)
- creates/updates the required index HTML files

The result is a static directory/file structure that can be served over HTTP(S).

## Framework

- Python
- PySide6 for the desktop UI
- `QSettings` (PySide6 settings module) for storing host, username, and remote root

## Current implementation

The app provides:

- FTP host/username/password/remote-root configuration
- persistent settings storage through `QSettings` (password is not persisted)
- wheel file selection via button or drag and drop (`*.whl`)
- test connection action
- publish action that:
  - uploads wheel files to `packages/`
  - rebuilds and uploads:
    - `index.html`
    - `<normalized-package-name>/index.html`
- update action that rebuilds the index without uploading new packages

Package names in the index are normalized per PEP 503 style (`[-_.]+` collapsed to `-`, lowercase).

## Installation

```bash
uv pip install -e .
```

## Run (GUI)

```bash
staticpypi
```

or:

```bash
python -m staticpypi.main
```

## Run (CLI)

### Publish wheels

Upload one or more `.whl` files and update the index:

```bash
staticpypi-cli publish --host ftp.example.com --username USER --password PASS --remote-root /pypi dist/*.whl
```

### Update indices only

Rebuild the index from the wheels already on the server, without uploading anything new:

```bash
staticpypi-cli update --host ftp.example.com --username USER --password PASS --remote-root /pypi
```

### Environment variables

Connection settings can be provided via environment variables to avoid repeating them on every invocation:

| Variable                  | Flag             |
|---------------------------|------------------|
| `STATICPYPI_HOST`         | `--host`         |
| `STATICPYPI_USERNAME`     | `--username`     |
| `STATICPYPI_PASSWORD`     | `--password`     |
| `STATICPYPI_REMOTE_ROOT`  | `--remote-root`  |

Example (PowerShell):

```powershell
$env:STATICPYPI_HOST = "ftp.example.com"
$env:STATICPYPI_USERNAME = "user"
$env:STATICPYPI_PASSWORD = "secret"
$env:STATICPYPI_REMOTE_ROOT = "/pypi"

staticpypi-cli publish dist/MyPackage-1.0-py3-none-any.whl
```

## Expected server layout

After publishing, your FTP remote root contains:

```text
packages/
  your_package-1.2.3-py3-none-any.whl
index.html
your-package/
  index.html
```

Where:

- `index.html` links to package pages
- `<package>/index.html` links to wheel files in `packages/`

## Consuming the index

```bash
uv pip install MyPackage --extra-index-url http://example.com/pypi
pip install MyPackage --extra-index-url http://example.com/pypi
```

## References

- [PyPA Simple Repository API](https://packaging.python.org/en/latest/specifications/simple-repository-api/)
- [PEP 503 - Simple Repository API](https://peps.python.org/pep-0503/)
