from __future__ import annotations

from ftplib import all_errors
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from staticpypi.ftp_repository import FTPRepository
from staticpypi.index_builder import (
    build_package_index,
    build_root_index,
    group_wheels_by_package,
)
from staticpypi.settings import AppSettings, ConnectionSettings


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("staticpypi")

        self._settings = AppSettings()
        self._wheel_paths: list[Path] = []

        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)

        form_layout = QFormLayout()
        layout.addLayout(form_layout)

        self.host_input = QLineEdit()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.remote_root_input = QLineEdit()

        form_layout.addRow("FTP host", self.host_input)
        form_layout.addRow("Username", self.username_input)
        form_layout.addRow("Password", self.password_input)
        form_layout.addRow("Remote root", self.remote_root_input)

        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("Wheel files to add"))

        self.select_files_button = QPushButton("Select wheels")
        self.select_files_button.clicked.connect(self.select_wheels)
        files_header.addWidget(self.select_files_button)
        layout.addLayout(files_header)

        self.selected_files_list = QListWidget()
        layout.addWidget(self.selected_files_list)

        actions = QHBoxLayout()
        self.connect_button = QPushButton("Test connection")
        self.connect_button.clicked.connect(self.test_connection)
        self.publish_button = QPushButton("Publish")
        self.publish_button.clicked.connect(self.publish)

        actions.addWidget(self.connect_button)
        actions.addWidget(self.publish_button)
        layout.addLayout(actions)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        self._load_settings()

    def _load_settings(self) -> None:
        cfg = self._settings.load()
        self.host_input.setText(cfg.host)
        self.username_input.setText(cfg.username)
        self.password_input.clear()
        self.remote_root_input.setText(cfg.remote_root)

    def _read_settings(self) -> ConnectionSettings:
        remote_root_input = self.remote_root_input.text().strip()
        if not remote_root_input:
            remote_root = "/"
        else:
            remote_root = f"/{remote_root_input.lstrip('/')}"

        cfg = ConnectionSettings(
            host=self.host_input.text().strip(),
            username=self.username_input.text().strip(),
            password=self.password_input.text(),
            remote_root=remote_root,
        )
        self._settings.save(cfg)
        return cfg

    def log(self, message: str) -> None:
        self.log_output.append(message)

    def select_wheels(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select wheel files",
            "",
            "Wheel files (*.whl)",
        )
        if not files:
            return
        self._wheel_paths = [Path(p) for p in files]
        self.selected_files_list.clear()
        self.selected_files_list.addItems([p.name for p in self._wheel_paths])
        self.log(f"Selected {len(self._wheel_paths)} wheel file(s)")

    def test_connection(self) -> None:
        cfg = self._read_settings()
        if not cfg.host:
            QMessageBox.warning(self, "Missing host", "Please provide an FTP host.")
            return
        try:
            with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
                existing = repo.list_wheels("packages")
            self.log(
                f"Connected to {cfg.host}. Found {len(existing)} existing wheel file(s)."
            )
        except (all_errors, OSError) as exc:
            QMessageBox.critical(self, "Connection failed", str(exc))
            self.log(f"Connection failed: {exc}")
        finally:
            self.password_input.clear()

    def publish(self) -> None:
        cfg = self._read_settings()
        if not cfg.host:
            QMessageBox.warning(self, "Missing host", "Please provide an FTP host.")
            return
        if not self._wheel_paths:
            QMessageBox.warning(self, "No files", "Please select wheel files to publish.")
            return

        try:
            with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
                existing_wheels = repo.list_wheels("packages")
                self.log(f"Found {len(existing_wheels)} wheel(s) on server.")

                for wheel in self._wheel_paths:
                    remote_path = f"packages/{wheel.name}"
                    repo.upload_file(wheel, remote_path)
                    self.log(f"Uploaded {wheel.name}")

                all_wheels = sorted(set(existing_wheels + [p.name for p in self._wheel_paths]))
                grouped = group_wheels_by_package(all_wheels)

                repo.upload_text(build_root_index(list(grouped.keys())), "simple/index.html")
                self.log("Updated simple/index.html")

                for package, wheels in grouped.items():
                    package_index = build_package_index(package, wheels)
                    repo.upload_text(package_index, f"simple/{package}/index.html")
                self.log(f"Updated {len(grouped)} package index file(s)")

            QMessageBox.information(self, "Done", "Publish completed successfully.")
        except ValueError as exc:
            message = str(exc)
            QMessageBox.critical(self, "Publish failed", message)
            self.log(f"Publish failed: {message}")
        except (all_errors, OSError) as exc:
            QMessageBox.critical(self, "Publish failed", str(exc))
            self.log(f"Publish failed: {exc}")
        finally:
            self.password_input.clear()
