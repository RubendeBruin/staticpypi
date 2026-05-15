from __future__ import annotations

from ftplib import all_errors
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
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


class DragDropListWidget(QListWidget):
    """Custom QListWidget that accepts drag and drop for wheel files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.on_drop_callback = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # Check if any of the URLs are .whl files
            urls = event.mimeData().urls()
            has_wheel_files = any(
                Path(url.toLocalFile()).suffix.lower() == ".whl" for url in urls
            )
            if has_wheel_files:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            has_wheel_files = any(
                Path(url.toLocalFile()).suffix.lower() == ".whl" for url in urls
            )
            if has_wheel_files:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            files = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
            # Filter for .whl files only
            wheel_files = [f for f in files if f.suffix.lower() == ".whl"]
            if wheel_files and self.on_drop_callback:
                self.on_drop_callback(wheel_files)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()


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

        self.selected_files_list = DragDropListWidget()
        self.selected_files_list.on_drop_callback = self._add_wheel_files
        layout.addWidget(self.selected_files_list)

        server_header = QHBoxLayout()
        server_header.addWidget(QLabel("Server packages"))
        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.clicked.connect(self.fetch_server_wheels)
        server_header.addWidget(self.fetch_button)
        layout.addLayout(server_header)

        self.server_wheels_list = QListWidget()
        self.server_wheels_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.server_wheels_list)

        remove_layout = QHBoxLayout()
        remove_layout.addStretch()
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self.remove_selected_wheels)
        remove_layout.addWidget(self.remove_button)
        layout.addLayout(remove_layout)

        actions = QHBoxLayout()
        self.connect_button = QPushButton("Test connection")
        self.connect_button.clicked.connect(self.test_connection)
        self.publish_button = QPushButton("Publish")
        self.publish_button.clicked.connect(self.publish)
        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(self.update_indices)

        actions.addWidget(self.connect_button)
        actions.addWidget(self.publish_button)
        actions.addWidget(self.update_button)
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

    def _add_wheel_files(self, files: list[Path]) -> None:
        """Add wheel files to the selected files list."""
        self._wheel_paths.extend(files)
        self.selected_files_list.clear()
        self.selected_files_list.addItems([p.name for p in self._wheel_paths])
        self.log(f"Added {len(files)} wheel file(s) (total: {len(self._wheel_paths)})")

    def select_wheels(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select wheel files",
            "",
            "Wheel files (*.whl)",
        )
        if not files:
            return
        self._add_wheel_files([Path(p) for p in files])

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
        except Exception as exc:
            QMessageBox.critical(self, "Connection failed", str(exc))
            self.log(f"Connection failed: {exc}")

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

                repo.upload_text(build_root_index(list(grouped.keys())), "index.html")
                self.log("Updated index.html")

                for package, wheels in grouped.items():
                    package_index = build_package_index(package, wheels)
                    repo.upload_text(package_index, f"{package}/index.html")
                self.log(f"Updated {len(grouped)} package index file(s)")

            QMessageBox.information(self, "Done", "Publish completed successfully.")
        except ValueError as exc:
            message = str(exc)
            QMessageBox.critical(self, "Publish failed", message)
            self.log(f"Publish failed: {message}")
        except Exception as exc:
            QMessageBox.critical(self, "Publish failed", str(exc))
            self.log(f"Publish failed: {exc}")

    def update_indices(self) -> None:
        """Update server indices without uploading new packages."""
        cfg = self._read_settings()
        if not cfg.host:
            QMessageBox.warning(self, "Missing host", "Please provide an FTP host.")
            return

        try:
            with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
                existing_wheels = repo.list_wheels("packages")
                self.log(f"Found {len(existing_wheels)} wheel(s) on server.")

                grouped = group_wheels_by_package(existing_wheels)

                repo.upload_text(build_root_index(list(grouped.keys())), "index.html")
                self.log("Updated index.html")

                for package, wheels in grouped.items():
                    package_index = build_package_index(package, wheels)
                    repo.upload_text(package_index, f"{package}/index.html")
                self.log(f"Updated {len(grouped)} package index file(s)")

            QMessageBox.information(self, "Done", "Indices updated successfully.")
        except ValueError as exc:
            message = str(exc)
            QMessageBox.critical(self, "Update failed", message)
            self.log(f"Update failed: {message}")
        except Exception as exc:
            QMessageBox.critical(self, "Update failed", str(exc))
            self.log(f"Update failed: {exc}")

    def fetch_server_wheels(self) -> None:
        cfg = self._read_settings()
        if not cfg.host:
            QMessageBox.warning(self, "Missing host", "Please provide an FTP host.")
            return
        try:
            with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
                wheels = repo.list_wheels("packages")
            self.server_wheels_list.clear()
            self.server_wheels_list.addItems(wheels)
            self.log(f"Fetched {len(wheels)} wheel(s) from server.")
        except Exception as exc:
            QMessageBox.critical(self, "Fetch failed", str(exc))
            self.log(f"Fetch failed: {exc}")

    def remove_selected_wheels(self) -> None:
        selected = [item.text() for item in self.server_wheels_list.selectedItems()]
        if not selected:
            QMessageBox.warning(self, "No selection", "Please select wheel(s) to remove.")
            return

        names = "\n".join(selected)
        reply = QMessageBox.question(
            self,
            "Confirm removal",
            f"Remove {len(selected)} wheel(s) from the server?\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cfg = self._read_settings()
        try:
            with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
                for wheel in selected:
                    repo.delete_file(f"packages/{wheel}")
                    self.log(f"Deleted {wheel}")

                remaining_wheels = repo.list_wheels("packages")
                grouped = group_wheels_by_package(remaining_wheels) if remaining_wheels else {}

                repo.upload_text(build_root_index(list(grouped.keys())), "index.html")
                self.log("Updated index.html")

                for package, wheels in grouped.items():
                    package_index = build_package_index(package, wheels)
                    repo.upload_text(package_index, f"{package}/index.html")
                self.log(f"Updated {len(grouped)} package index file(s)")

            self.server_wheels_list.clear()
            self.server_wheels_list.addItems(remaining_wheels)
            QMessageBox.information(self, "Done", f"Removed {len(selected)} wheel(s) and updated indices.")
        except Exception as exc:
            QMessageBox.critical(self, "Remove failed", str(exc))
            self.log(f"Remove failed: {exc}")
