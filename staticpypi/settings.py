from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


@dataclass
class ConnectionSettings:
    host: str = ""
    username: str = ""
    password: str = ""
    remote_root: str = "/"


class AppSettings:
    def __init__(self) -> None:
        self._settings = QSettings("staticpypi", "staticpypi")

    def load(self) -> ConnectionSettings:
        return ConnectionSettings(
            host=self._settings.value("host", "", type=str),
            username=self._settings.value("username", "", type=str),
            password="",
            remote_root=self._settings.value("remote_root", "/", type=str),
        )

    def save(self, config: ConnectionSettings) -> None:
        self._settings.setValue("host", config.host)
        self._settings.setValue("username", config.username)
        self._settings.setValue("remote_root", config.remote_root)
        self._settings.remove("password")
        self._settings.sync()
