"""NovaNote 启动入口。

用法：
    python main.py                 # 正常启动
    python main.py --workspace D:\\path\\to\\ws   # 直接打开指定工作空间
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

# 允许从源码目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from novanote import icons  # noqa: E402
from novanote.config import (  # noqa: E402
    APP_NAME,
    APP_NAME_CN,
    APP_VERSION,
    LOG_PATH,
    Settings,
)
from novanote.services.workspace import WorkspaceError, WorkspaceRegistry  # noqa: E402
from novanote.theme import build_qss, resolve_font, Fonts  # noqa: E402
from novanote.ui.dialogs import WorkspaceSetupDialog  # noqa: E402
from novanote.ui.main_window import MainWindow  # noqa: E402


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n===== {APP_NAME} {APP_VERSION} =====\n{msg}\n")
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def _setup_workspace(settings: Settings, registry: WorkspaceRegistry):
    dlg = WorkspaceSetupDialog(settings.theme, registry.recent(), mode="welcome")
    if dlg.exec() != QDialog.Accepted:
        return None
    if dlg.result_action == "open":
        ws_id = getattr(dlg, "selected_ws_id", None)
        if ws_id:
            return registry.activate(ws_id)
        return None
    if dlg.result_action == "create":
        return registry.create(dlg.workspace_path, dlg.workspace_name)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME, description=f"{APP_NAME} · {APP_NAME_CN}")
    parser.add_argument("--workspace", "-w", help="直接打开指定工作空间目录")
    parser.add_argument("--theme", choices=["light", "dark"], help="覆盖主题")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    _install_excepthook()

    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} · {APP_NAME_CN}")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("NovaLab")

    ui_font = resolve_font(Fonts.ui, [Fonts.ui_fallback, "Segoe UI", "sans-serif"])
    f = QFont(ui_font)
    f.setPointSizeF(9.75)
    app.setFont(f)
    app.setWindowIcon(icons.app_icon())

    settings = Settings.load()
    if args.theme:
        settings.theme = args.theme
    app.setStyleSheet(build_qss(settings.theme))

    registry = WorkspaceRegistry(settings)

    ws = None
    if args.workspace:
        try:
            ws = registry.open(args.workspace)
        except WorkspaceError as e:
            QMessageBox.critical(None, APP_NAME, f"无法打开工作空间：\n{e}")
            return 2
    else:
        ws = registry.resolve_startup_workspace()
        if ws is None:
            try:
                ws = _setup_workspace(settings, registry)
            except WorkspaceError as e:
                QMessageBox.critical(None, APP_NAME, f"创建失败：\n{e}")
                return 2
            if ws is None:
                return 0
    settings.first_run_done = True
    settings.save()

    window = MainWindow(settings, registry)
    window.show()
    return app.exec()


if __name__ == "__main__":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    sys.exit(main())
