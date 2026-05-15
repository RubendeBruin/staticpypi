# Protecting your static PyPI repository with .htaccess

Apache's `.htaccess` mechanism lets you restrict access to the generated repository without modifying your server's main configuration. The examples below assume the repository root (the directory that contains `index.html` and `packages/`) is served by Apache.

---

## 1. Basic authentication (username + password)

This is the most common approach. `pip` and `uv` both support embedding credentials directly in the index URL.

### 1.1 Create a password file

Run the following command **outside** the web root (e.g. in `/etc/apache2/`):

```bash
htpasswd -c /etc/apache2/.htpasswd alice
```

To add more users omit `-c` (which would overwrite the file):

```bash
htpasswd /etc/apache2/.htpasswd bob
```

#### Alternatively

If you do not have a console, then you may use an online generator to generate a password. For example:

https://www.transip.nl/htpasswd/

test:$2a$13$xk016sb0TyHVtxKiQsFirOROc0IhcgGrcxMt7xYMV8zBKGOM4Z8uC

--> user test, pwd: vinkentering


### 1.2 Add .htaccess to the repository root

Place the file at the root of the repository (next to `index.html`):

The AuthUserFile points to the .htpasswd file created earlier.

```apache
AuthType Basic
AuthName "Private PyPI"
AuthUserFile /etc/apache2/.htpasswd
Require valid-user
```

This protects the root index and every subdirectory (`packages/`, per-package index pages, etc.).

### 1.3 Consume the protected index

Pass the credentials in the URL so that `pip` / `uv` can authenticate automatically:

```bash
# pip
pip install MyPackage --extra-index-url https://alice:secret@example.com/pypi

# uv
uv pip install MyPackage --extra-index-url https://alice:secret@example.com/pypi
```

Alternatively, store the credentials in `~/.netrc` to avoid exposing them on the command line:

```netrc
machine example.com
  login alice
  password secret
```

Or configure them permanently in `pip`'s `pip.ini` / `pip.conf`:

```ini
[global]
extra-index-url = https://alice:secret@example.com/pypi
```


## 2. If it does not work : Enabling .htaccess in Apache

`.htaccess` overrides are disabled by default in many Apache installations. Ensure the relevant `<Directory>` block in your server configuration contains:

```apache
AllowOverride AuthConfig Options FileInfo
```

or simply:

```apache
AllowOverride All
```

Then reload Apache:

```bash
sudo systemctl reload apache2
```
