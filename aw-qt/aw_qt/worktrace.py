"""Top-of-screen capture controls backed by the Work trace server API."""
import json
from datetime import datetime

from PyQt6.QtCore import QByteArray, QDateTime, QPoint, QSettings, Qt, QTimer, QUrl, QSize
from PyQt6.QtGui import QDesktopServices, QCursor, QIcon, QPalette
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget, QFrame,
)
from aw_core.dirs import get_config_dir
from pathlib import Path


def brand_icon():
    return QIcon(str(Path(__file__).resolve().parent.parent / "media" / "worktrace.png"))


def apply_windows_style(app):
    """Use the system light/dark preference without an additional UI toolkit."""
    dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if __import__("sys").platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                dark = not bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
        except OSError:
            pass
    background, surface, text, border, hover = (
        ("#202020", "#2b2b2b", "#f5f5f5", "#424242", "#383838") if dark else
        ("#f3f3f3", "#ffffff", "#202020", "#dedede", "#e9e9e9")
    )
    app.setWindowIcon(brand_icon())
    app.setStyleSheet(f"""
        QWidget {{ font: 13px 'Segoe UI', 'Microsoft YaHei UI'; color: {text}; }}
        QDialog, QMessageBox, QInputDialog {{ background: {background}; }}
        QFrame#dockPanel {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}
        QFrame#dockEdge {{ background: {'#8b8b8b' if dark else '#747474'}; border-radius: 3px; }}
        QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 4px; padding: 6px 12px; min-height: 18px; }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: {border}; }}
        QPushButton:disabled {{ color: #929292; }}
        QPushButton#brandButton {{ background: transparent; border: none; padding: 2px; }}
        QPushButton#primaryAction {{ background: #0067c0; color: white; border-color: #0067c0; }}
        QPushButton#primaryAction:hover {{ background: #1975c5; }}
        QComboBox, QDateTimeEdit, QDoubleSpinBox, QLineEdit {{ background: {surface}; border: 1px solid {border}; border-radius: 4px; padding: 5px 8px; min-height: 20px; }}
        QTextEdit {{ background: {surface}; border: 1px solid {border}; border-bottom: 2px solid #0067c0; border-radius: 4px; padding: 8px; }}
        QMenu, QAbstractItemView {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px; }}
        QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 4px; }}
        QMenu::item:selected, QAbstractItemView::item:selected {{ background: {hover}; color: {text}; }}
        QLabel#captureStatus {{ color: {'#9da6ad' if dark else '#626262'}; font-size: 12px; padding-right: 4px; }}
    """)


class Handle(QLabel):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.offset = event.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "offset"):
            self.window().move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        self.window().dock_to_top()


class WorkTraceBar(QWidget):
    def __init__(self, root_url):
        super().__init__()
        self.root_url = root_url
        self.state = {}
        self.projects = []
        self.loading = False
        self.expanded = False
        self.setWindowTitle("Work trace")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowIcon(brand_icon())
        self.settings = QSettings(str(Path(get_config_dir("aw-qt")) / "worktrace-window.ini"), QSettings.Format.IniFormat)
        self.network = QNetworkAccessManager(self)
        self.network.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.pending_requests = {}
        self.network.finished.connect(self.request_complete)
        apply_windows_style(QApplication.instance())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edge = QFrame()
        self.edge.setObjectName("dockEdge")
        self.edge.setToolTip("Work trace")
        layout.addWidget(self.edge)
        self.panel = QFrame()
        self.panel.setObjectName("dockPanel")
        panel_layout = QHBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 7, 10, 7)
        panel_layout.setSpacing(8)
        brand = self.add_button(panel_layout, "", self.open_dashboard)
        brand.setObjectName("brandButton")
        brand.setIcon(brand_icon())
        brand.setIconSize(QSize(24, 24))
        brand.setToolTip("打开工作台")
        brand.setAccessibleName("打开工作台")
        handle = Handle("Work trace")
        handle.setCursor(Qt.CursorShape.SizeAllCursor)
        handle.setToolTip("拖动以调整顶部位置")
        panel_layout.addWidget(handle)
        self.status = QLabel("连接中…")
        self.status.setObjectName("captureStatus")
        panel_layout.addWidget(self.status)
        self.controls = QWidget()
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.project = QComboBox()
        self.project.setFixedWidth(145)
        self.project.setToolTip("当前项目")
        self.project.activated.connect(self.switch_project)
        controls.addWidget(self.project)
        note = self.add_button(controls, "记一笔", lambda: self.new_note("note"))
        note.setObjectName("primaryAction")
        self.add_button(controls, "完成", lambda: self.new_note("done"))
        self.pause = self.add_button(controls, "暂停", self.toggle_pause)
        summary = self.add_button(controls, "总结", lambda: None)
        menu = QMenu(summary)
        for kind, label in [("day", "生成今日总结"), ("week", "生成本周总结"), ("month", "生成本月总结")]:
            menu.addAction(label, lambda checked=False, k=kind: self.generate(k))
        menu.addSeparator()
        menu.addAction("记录里程碑", lambda: self.new_note("milestone"))
        menu.addAction("项目总结与历史记录", self.open_dashboard)
        summary.setMenu(menu)
        panel_layout.addWidget(self.controls)
        layout.addWidget(self.panel)
        self.controls.setEnabled(False)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.maybe_retract)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        screen = QApplication.primaryScreen().availableGeometry()
        self.anchor = self.settings.value("dockAnchor", QPoint(screen.center().x(), screen.top()))
        if not any(s.availableGeometry().contains(self.anchor) for s in QApplication.screens()):
            self.anchor = QPoint(screen.center().x(), screen.top())
        self.set_expanded(False)
        self.refresh()

    def add_button(self, layout, text, action):
        button = QPushButton(text)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def save_position(self):
        self.settings.setValue("dockAnchor", self.anchor)

    def toggle_collapsed(self):
        self.set_expanded(not self.expanded)

    def dock_to_top(self):
        screen = (QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
        self.anchor = QPoint(self.frameGeometry().center().x(), screen.top())
        self.set_expanded(True)
        self.save_position()

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.panel.setVisible(expanded)
        self.edge.setVisible(not expanded)
        screen = (QApplication.screenAt(self.anchor) or QApplication.primaryScreen()).availableGeometry()
        width = min(self.panel.sizeHint().width(), screen.width()) if expanded else 112
        height = self.panel.sizeHint().height() if expanded else 5
        self.setFixedSize(width, height)
        x = max(screen.left(), min(self.anchor.x() - width // 2, screen.right() - width + 1))
        self.move(x, screen.top())

    def enterEvent(self, event):
        self.hide_timer.stop()
        if not self.expanded:
            self.set_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hide_timer.start(650)
        super().leaveEvent(event)

    def maybe_retract(self):
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            self.hide_timer.start(650)
        elif not self.frameGeometry().contains(QCursor.pos()):
            self.set_expanded(False)

    def reveal(self):
        self.show()
        self.set_expanded(True)
        self.hide_timer.start(1800)

    def closeEvent(self, event):
        self.save_position()
        self.hide()
        event.ignore()

    def request(self, method, path, data=None, done=None, silent=False, finished=None):
        request = QNetworkRequest(QUrl(self.root_url + "/api/0/worktrace" + path))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setTransferTimeout(5000)
        payload = QByteArray(json.dumps(data or {}).encode("utf-8"))
        reply = self.network.sendCustomRequest(request, method.encode(), payload if method != "GET" else QByteArray())
        self.pending_requests[reply] = (done, silent, finished)

    def request_complete(self, reply):
        # Keep replies alive through dispatch; never let a reply own a closure
        # that captures itself while Qt is deleting its native object.
        done, silent, finished = self.pending_requests.pop(reply, (None, True, None))
        try:
            raw = bytes(reply.readAll()).decode("utf-8")
            result = json.loads(raw) if raw else {}
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(result.get("message", reply.errorString()))
            if done:
                done(result)
        except (ValueError, UnicodeError) as error:
            if silent:
                self.status.setText("服务未连接")
                self.controls.setEnabled(False)
            else:
                QMessageBox.warning(self, "Work trace", str(error))
        finally:
            reply.deleteLater()
            if finished:
                finished()

    def refresh(self):
        if self.loading:
            return
        self.loading = True

        def state_loaded(state):
            self.state = state
            self.status.setText("已暂停" if state["paused"] else "● 记录中")
            self.pause.setText("继续" if state["paused"] else "暂停")
            self.controls.setEnabled(True)
            self.request("GET", "/projects", done=self.projects_loaded, silent=True)
        self.request("GET", "/state", done=state_loaded, silent=True, finished=lambda: setattr(self, "loading", False))

    def projects_loaded(self, projects):
        self.projects = projects
        if self.project.view().isVisible():
            return
        self.project.blockSignals(True)
        self.project.clear()
        self.project.addItem("未关联项目", None)
        for project in projects:
            if not project["archived"]:
                self.project.addItem(project["name"], project["id"])
        self.project.addItem("＋ 新建项目", "__new__")
        self.project.setCurrentIndex(max(0, self.project.findData(self.state.get("project_id"))))
        self.project.blockSignals(False)

    def switch_project(self):
        if self.project.currentData() == "__new__":
            self.new_project()
            self.projects_loaded(self.projects)
            return
        self.request("PATCH", "/state", {"project_id": self.project.currentData()}, done=lambda _: self.refresh())

    def toggle_pause(self):
        self.request("PATCH", "/state", {"paused": not self.state.get("paused", False)}, done=lambda _: self.refresh())

    def new_project(self):
        name, accepted = QInputDialog.getText(self, "新建项目", "项目名称")
        if accepted and name.strip():
            self.request("POST", "/projects", {"name": name}, done=lambda result: self.request("PATCH", "/state", {"project_id": result["id"]}, done=lambda _: self.refresh()))

    def new_note(self, kind):
        dialog = QDialog(self)
        dialog.setWindowTitle("记一笔")
        dialog.setWindowIcon(brand_icon())
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        project = QComboBox()
        project.addItem("未关联项目", None)
        for item in self.projects:
            if not item["archived"]:
                project.addItem(item["name"], item["id"])
        project.setCurrentIndex(max(0, project.findData(self.state.get("project_id"))))
        category = QComboBox()
        for key, label in [("note", "工作记录"), ("done", "完成事项"), ("milestone", "里程碑"), ("issue", "问题"), ("todo", "下一步")]:
            category.addItem(label, key)
        category.setCurrentIndex(category.findData(kind))
        occurred = QDateTimeEdit(QDateTime.currentDateTime())
        occurred.setDisplayFormat("yyyy-MM-dd HH:mm")
        occurred.setCalendarPopup(True)
        minutes = QDoubleSpinBox()
        minutes.setRange(0, 1440)
        minutes.setSuffix(" 分钟")
        content = QTextEdit()
        content.setPlaceholderText("记录工作内容")
        content.setMinimumHeight(120)
        form.addRow("项目", project)
        form.addRow("类型", category)
        form.addRow("内容", content)
        layout.addLayout(form)
        details = QWidget()
        detail_form = QFormLayout(details)
        detail_form.setContentsMargins(0, 0, 0, 0)
        detail_form.addRow("发生时间", occurred)
        detail_form.addRow("补录时长", minutes)
        more = QPushButton("更多选项")
        more.setCheckable(True)
        more.toggled.connect(details.setVisible)
        layout.addWidget(more)
        layout.addWidget(details)
        details.hide()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存记录")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")

        def save():
            if not content.toPlainText().strip():
                QMessageBox.information(dialog, "Work trace", "请填写记录内容")
                return
            buttons.setEnabled(False)
            data = {"project_id": project.currentData(), "kind": category.currentData(), "content": content.toPlainText(), "occurred": occurred.dateTime().toPyDateTime().astimezone().isoformat(), "minutes": minutes.value()}
            self.request("POST", "/notes", data, done=lambda _: dialog.accept(), finished=lambda: buttons.setEnabled(True))
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def generate(self, kind):
        self.request("POST", "/reports", {"kind": kind, "date": datetime.now().date().isoformat()}, done=lambda _: self.open_dashboard())

    def open_dashboard(self):
        QDesktopServices.openUrl(QUrl(self.root_url + "/#/worktrace"))
