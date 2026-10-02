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
- optionally restricts read access to the index with users and passwords (see [Access control](#access-control-apache))

The result is a static directory/file structure that can be served over HTTP(S).

## Framework

- Python (CLI: standard library plus `bcrypt` for password hashing)
- PySide6 for the desktop UI (optional `gui` extra)
- `QSettings` (PySide6 settings module) for storing host, username, remote root and the access-control inputs (server path of the password file, public URL)

## Current implementation

The app provides:

- FTP host (optionally `host:port`)/username/password/remote-root configuration
- persistent settings storage through `QSettings` (password is not persisted)
- wheel file selection via button or drag and drop (`*.whl`)
- test connection action
- publish action that:
  - uploads wheel files to `packages/`
  - rebuilds and uploads:
    - `index.html`
    - `<normalized-package-name>/index.html`
- update action that rebuilds the index without uploading new packages
- fetch/remove actions to list wheels on the server and delete selected ones (the index is rebuilt afterwards)
- access control: manage index users, switch password protection on/off and verify it (GUI dialog and `user` / `protect` CLI commands)

Package names in the index are normalized per PEP 503 style (`[-_.]+` collapsed to `-`, lowercase).

## Installation

The CLI has no dependencies. The GUI needs the `gui` extra (PySide6).

Without installing, via `uvx`:

```bash
uvx staticpypi publish dist/*.whl            # CLI
uvx --from "staticpypi[gui]" staticpypi gui  # GUI
```

Or install (editable) from a checkout:

```bash
uv pip install -e ".[gui]"
```

## Run (GUI)

```bash
staticpypi gui
```

or:

```bash
python -m staticpypi gui
```

## Run (CLI)

### Publish wheels

Upload one or more `.whl` files and update the index:

```bash
staticpypi publish --host ftp.example.com --username USER --password PASS --remote-root /pypi dist/*.whl
```

### Update indices only

Rebuild the index from the wheels already on the server, without uploading anything new:

```bash
staticpypi update --host ftp.example.com --username USER --password PASS --remote-root /pypi
```

### Environment variables

Connection settings can be provided via environment variables to avoid repeating them on every invocation:

| Variable                  | Flag             |
|---------------------------|------------------|
| `STATICPYPI_HOST`         | `--host`         |
| `STATICPYPI_USERNAME`     | `--username`     |
| `STATICPYPI_PASSWORD`     | `--password`     |
| `STATICPYPI_REMOTE_ROOT`  | `--remote-root`  |
| `STATICPYPI_HTPASSWD_PATH`  | `--htpasswd-path` (`user` / `protect` commands) |
| `STATICPYPI_AUTH_USER_FILE` | `--auth-user-file` (`protect enable`) |

`--host` may include a port (`ftp.example.com:2121`). All remote paths are relative to the remote root.

Example (PowerShell):

```powershell
$env:STATICPYPI_HOST = "ftp.example.com"
$env:STATICPYPI_USERNAME = "user"
$env:STATICPYPI_PASSWORD = "secret"
$env:STATICPYPI_REMOTE_ROOT = "/pypi"

staticpypi publish dist/MyPackage-1.0-py3-none-any.whl
```

## Access control (Apache)

Restrict who can read the index with HTTP basic authentication. `staticpypi` manages the `.htpasswd` file (bcrypt hashes) and a marked block in `.htaccess` on the FTP server, so the web server must be Apache with `AllowOverride AuthConfig` (see [docs/htaccess-protection.md](docs/htaccess-protection.md)). The GUI offers the same in **Access control…**.

```bash
# 1. add users (prompts for the password; or use --auth-password)
staticpypi user add alice
staticpypi user list
staticpypi user remove alice

# 2. switch protection on; --auth-user-file is the path of .htpasswd on the *web server's* filesystem
staticpypi protect enable --auth-user-file /home/me/pypi/.htpasswd

# 3. verify from the outside that it really works
staticpypi protect test https://example.com/pypi --auth-user alice
```

The password file is uploaded to `.htpasswd` in the remote root (override with `--htpasswd-path`), so it sits inside the served directory; the generated `.htaccess` block denies web access to it. `--auth-user-file` is where the web server sees that same file: if the remote root is `/pypi` and the web server's document root is `/home/me/public_html`, that is typically `/home/me/public_html/pypi/.htpasswd`. A wrong path makes the server answer `500` for everything, which `protect test` reports.

`protect enable` refuses to run while there are no users (that would lock everyone out) and only touches its own block in `.htaccess`; `protect disable` removes just that block and keeps the password file. `--test-url` on `enable` runs the test straight away.

`protect test` makes plain HTTP requests (no FTP needed) and checks that:

- anonymous requests for `index.html` and `packages/` get `401`
- a wrong login gets `401`
- with `--auth-user`: the valid login gets `200`, and the password file itself is not downloadable (`403`/`404`)

It exits non-zero if any check fails, and does not follow redirects (so use the final `https://` URL). The connection options (`--host`, ...) and `--htpasswd-path` (default `.htpasswd` in the remote root) work as for `publish`.

Clients then use `https://alice:PASSWORD@example.com/pypi` as index URL, or a `~/.netrc` entry. Use HTTPS: basic auth sends the password in clear text.

> Git Bash on Windows rewrites arguments that start with `/` (e.g. `/home/me/.htpasswd`) into Windows paths. Use PowerShell, or set `MSYS_NO_PATHCONV=1`.

## Development

```bash
uv run --extra gui --group dev pytest
```

## Expected server layout

After publishing, your FTP remote root contains:

```text
packages/
  your_package-1.2.3-py3-none-any.whl
index.html
your-package/
  index.html
.htaccess      # only with access control enabled
.htpasswd      # only with access control enabled
```

Where:

- `index.html` links to package pages
- `<package>/index.html` links to wheel files in `packages/`
- `.htaccess` / `.htpasswd` hold the basic-auth block and the user hashes

## Consuming the index

```bash
uv pip install MyPackage --extra-index-url http://example.com/pypi
pip install MyPackage --extra-index-url http://example.com/pypi
```

For a protected index include the credentials: `https://alice:PASSWORD@example.com/pypi` (see [Access control](#access-control-apache)).

## References

- [PyPA Simple Repository API](https://packaging.python.org/en/latest/specifications/simple-repository-api/)
- [PEP 503 - Simple Repository API](https://peps.python.org/pep-0503/)
