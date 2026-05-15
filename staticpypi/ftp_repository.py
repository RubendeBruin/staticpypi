from __future__ import annotations

from ftplib import FTP, all_errors, error_perm
from io import BytesIO
from pathlib import Path
from types import TracebackType


class FTPRepository:
    DEFAULT_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        remote_root: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.remote_root = remote_root or "/"
        self.timeout_seconds = timeout_seconds
        self._ftp: FTP | None = None

    def __enter__(self) -> "FTPRepository":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> None:
        ftp = FTP(self.host, timeout=self.timeout_seconds)
        ftp.login(self.username, self.password)
        self._ftp = ftp
        self._chdir(self.remote_root)

    def close(self) -> None:
        if self._ftp is None:
            return
        try:
            self._ftp.quit()
        except all_errors:
            self._ftp.close()
        finally:
            self._ftp = None

    def _require_connection(self) -> FTP:
        if self._ftp is None:
            raise RuntimeError("Not connected")
        return self._ftp

    def _chdir(self, path: str) -> None:
        ftp = self._require_connection()
        ftp.cwd(path)

    def ensure_dir(self, path: str) -> None:
        ftp = self._require_connection()
        normalized = path.strip("/")
        if not normalized:
            return
        current = ftp.pwd()
        parts = normalized.split("/")
        try:
            ftp.cwd("/")
            for part in parts:
                try:
                    ftp.mkd(part)
                except error_perm as exc:
                    message = str(exc).lower()
                    if "exist" not in message and "already" not in message:
                        raise
                ftp.cwd(part)
        finally:
            ftp.cwd(current)

    def list_wheels(self, relative_dir: str = "packages") -> list[str]:
        ftp = self._require_connection()
        self.ensure_dir(relative_dir)
        current = ftp.pwd()
        try:
            ftp.cwd(relative_dir)
            names = ftp.nlst()
        except error_perm:
            names = []
        finally:
            ftp.cwd(current)
        return sorted(Path(n).name for n in names if str(n).endswith(".whl"))

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        ftp = self._require_connection()
        remote = remote_path.strip("/")
        remote_dir = str(Path(remote).parent)
        if remote_dir != ".":
            self.ensure_dir(remote_dir)
        with local_path.open("rb") as file_stream:
            ftp.storbinary(f"STOR {remote}", file_stream)

    def upload_text(self, content: str, remote_path: str) -> None:
        ftp = self._require_connection()
        remote = remote_path.strip("/")
        remote_dir = str(Path(remote).parent)
        if remote_dir != ".":
            self.ensure_dir(remote_dir)
        buffer = BytesIO(content.encode("utf-8"))
        ftp.storbinary(f"STOR {remote}", buffer)
