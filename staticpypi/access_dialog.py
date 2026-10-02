from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from staticpypi import htaccess
from staticpypi.ftp_repository import FTPRepository
from staticpypi.settings import AppSettings, ConnectionSettings


class AccessDialog(QDialog):
    """Manage who may read the index: users (.htpasswd), protection (.htaccess) and its verification."""

    def __init__(
        self,
        parent: QWidget,
        read_connection: Callable[[], ConnectionSettings],
        settings: AppSettings,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Access control")
        self.resize(560, 640)
        self._read_connection = read_connection
        self._settings = settings

        layout = QVBoxLayout(self)

        users_box = QGroupBox("Users")
        users_layout = QVBoxLayout(users_box)
        self.users_list = QListWidget()
        users_layout.addWidget(self.users_list)
        buttons = QHBoxLayout()
        for text, handler in (
            ("Refresh", self.refresh_users),
            ("Add / change password…", self.add_user),
            ("Remove selected", self.remove_user),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        users_layout.addLayout(buttons)
        layout.addWidget(users_box)

        protection_box = QGroupBox("Protection")
        protection_layout = QVBoxLayout(protection_box)
        form = QFormLayout()
        self.auth_user_file_input = QLineEdit(self._settings.get("auth_user_file"))
        self.auth_user_file_input.setPlaceholderText("/home/you/private/.htpasswd")
        self.public_url_input = QLineEdit(self._settings.get("public_url"))
        self.public_url_input.setPlaceholderText("https://example.com/pypi")
        self.test_user_input = QLineEdit()
        self.test_password_input = QLineEdit()
        self.test_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("AuthUserFile (server path)", self.auth_user_file_input)
        form.addRow("Public URL (for the test)", self.public_url_input)
        form.addRow("Test user (optional)", self.test_user_input)
        form.addRow("Test password", self.test_password_input)
        protection_layout.addLayout(form)
        protection_layout.addWidget(
            QLabel("The password file is stored at '.htpasswd' in the remote root; AuthUserFile is where the web server finds it.")
        )
        actions = QHBoxLayout()
        for text, handler in (
            ("Enable protection", self.enable_protection),
            ("Disable protection", self.disable_protection),
            ("Test protection", self.test_protection),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            actions.addWidget(button)
        protection_layout.addLayout(actions)
        layout.addWidget(protection_box)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

    def log(self, message: str) -> None:
        self.log_output.append(message)

    def _connection(self) -> ConnectionSettings | None:
        cfg = self._read_connection()
        if not cfg.host:
            QMessageBox.warning(self, "Missing host", "Please provide an FTP host in the main window.")
            return None
        return cfg

    def _with_repo(self, title: str, action: Callable[[FTPRepository], None]) -> bool:
        cfg = self._connection()
        if cfg is None:
            return False
        try:
            with FTPRepository(cfg.host, cfg.username, cfg.password, cfg.remote_root) as repo:
                action(repo)
            return True
        except Exception as exc:
            QMessageBox.critical(self, title, str(exc))
            self.log(f"{title}: {exc}")
            return False

    def refresh_users(self) -> None:
        def action(repo: FTPRepository) -> None:
            users = list(htaccess.load_users(repo))
            self.users_list.clear()
            self.users_list.addItems(users)
            self.log(f"Found {len(users)} user(s).")

        self._with_repo("Fetch users failed", action)

    def add_user(self) -> None:
        name, ok = QInputDialog.getText(self, "Add / change password", "User name:")
        name = name.strip()
        if not ok or not name:
            return
        password, ok = QInputDialog.getText(
            self, "Add / change password", f"Password for {name}:", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        repeat, ok = QInputDialog.getText(self, "Add / change password", "Repeat password:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        if repeat != password:
            QMessageBox.warning(self, "Mismatch", "The passwords do not match.")
            return
        try:
            htaccess.validate_username(name)
            htaccess.hash_password(password)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        def action(repo: FTPRepository) -> None:
            created = htaccess.set_user_password(repo, name, password)
            self.log(f"{'Added' if created else 'Updated password of'} user {name!r}.")

        if self._with_repo("Add user failed", action):
            self.refresh_users()

    def remove_user(self) -> None:
        selected = [item.text() for item in self.users_list.selectedItems()]
        if not selected:
            QMessageBox.warning(self, "No selection", "Please select user(s) to remove.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm removal",
            "Remove user(s) from the server?\n\n" + "\n".join(selected),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def action(repo: FTPRepository) -> None:
            for name in selected:
                htaccess.remove_user(repo, name)
                self.log(f"Removed user {name!r}.")
            if not htaccess.load_users(repo):
                self.log("Warning: no users left; with protection enabled nobody can read the index.")

        if self._with_repo("Remove user failed", action):
            self.refresh_users()

    def _remember_inputs(self) -> None:
        self._settings.set("auth_user_file", self.auth_user_file_input.text().strip())
        self._settings.set("public_url", self.public_url_input.text().strip())

    def enable_protection(self) -> None:
        self._remember_inputs()
        auth_user_file = self.auth_user_file_input.text().strip()
        if not auth_user_file:
            QMessageBox.warning(self, "Missing path", "Please provide the AuthUserFile path as seen by the web server.")
            return

        def action(repo: FTPRepository) -> None:
            if htaccess.has_foreign_auth(repo.download_text(htaccess.HTACCESS_PATH)):
                self.log("Warning: .htaccess already contains authentication directives outside the staticpypi block.")
            htaccess.enable_protection(repo, auth_user_file)
            self.log("Protection enabled (.htaccess updated). Use 'Test protection' to verify it.")

        self._with_repo("Enable protection failed", action)

    def disable_protection(self) -> None:
        def action(repo: FTPRepository) -> None:
            if htaccess.disable_protection(repo):
                self.log("Protection disabled. The password file was kept.")
            else:
                self.log("Protection was not enabled by staticpypi; nothing changed.")

        self._with_repo("Disable protection failed", action)

    def test_protection(self) -> None:
        self._remember_inputs()
        url = self.public_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please provide the public URL of the index.")
            return
        user = self.test_user_input.text().strip() or None
        password = self.test_password_input.text() if user else None
        self.log(f"Checking protection of {url} ...")
        results = htaccess.check_protection(url, user, password)
        for result in results:
            self.log(f"[{'PASS' if result.passed else 'FAIL'}] {result.name}: {result.detail}")
        if all(r.passed for r in results):
            self.log("Protection verified." + ("" if user else " (Enter a test user to also verify logins.)"))
        else:
            self.log("Protection check FAILED.")
