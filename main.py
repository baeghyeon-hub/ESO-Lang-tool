"""ESO Lang Tool — 앱 진입점."""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow
from ui.theme import apply_dark_theme


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ESO Lang Tool")

    # HiDPI 지원
    app.setStyle("Fusion")

    # 다크 테마
    apply_dark_theme(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
