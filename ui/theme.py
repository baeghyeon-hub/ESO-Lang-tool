"""다크/라이트 테마 스타일시트."""

DARK_STYLE = """
QMainWindow, QDialog {
    background-color: #1e1e1e;
    color: #d4d4d4;
}

QMenuBar {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border-bottom: 1px solid #404040;
}
QMenuBar::item:selected {
    background-color: #094771;
}

QMenu {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #404040;
}
QMenu::item:selected {
    background-color: #094771;
}

QToolBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #404040;
    spacing: 4px;
    padding: 2px;
}
QToolBar QToolButton {
    background-color: transparent;
    color: #d4d4d4;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 8px;
}
QToolBar QToolButton:hover {
    background-color: #3e3e3e;
    border-color: #505050;
}

QTableView {
    background-color: #1e1e1e;
    color: #d4d4d4;
    gridline-color: #333333;
    selection-background-color: #094771;
    selection-color: #ffffff;
    border: 1px solid #404040;
    font-size: 13px;
}
QTableView::item {
    padding: 2px 6px;
}
QTableView::item:hover {
    background-color: #2a2d2e;
}

QHeaderView::section {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #404040;
    padding: 4px 8px;
    font-weight: bold;
    font-size: 12px;
}

QTreeView {
    background-color: #252526;
    color: #d4d4d4;
    border: 1px solid #404040;
    font-size: 13px;
}
QTreeView::item {
    padding: 3px 4px;
}
QTreeView::item:selected {
    background-color: #094771;
    color: #ffffff;
}
QTreeView::item:hover {
    background-color: #2a2d2e;
}

QLineEdit {
    background-color: #3c3c3c;
    color: #d4d4d4;
    border: 1px solid #505050;
    border-radius: 3px;
    padding: 4px 8px;
    font-size: 13px;
    selection-background-color: #094771;
}
QLineEdit:focus {
    border-color: #007acc;
}

QTextEdit {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #404040;
    font-size: 13px;
    selection-background-color: #094771;
}

QPushButton {
    background-color: #0e639c;
    color: #ffffff;
    border: none;
    border-radius: 3px;
    padding: 5px 14px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #1177bb;
}
QPushButton:pressed {
    background-color: #094771;
}
QPushButton:disabled {
    background-color: #3c3c3c;
    color: #6d6d6d;
}

QComboBox {
    background-color: #3c3c3c;
    color: #d4d4d4;
    border: 1px solid #505050;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 12px;
}
QComboBox:hover {
    border-color: #007acc;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #d4d4d4;
    selection-background-color: #094771;
    border: 1px solid #404040;
}

QCheckBox {
    color: #d4d4d4;
    spacing: 6px;
    font-size: 12px;
}

QSplitter::handle {
    background-color: #404040;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}

QStatusBar {
    background-color: #f5d90a;
    color: #111111;
    font-size: 12px;
}
QStatusBar QLabel {
    color: #111111;
}

QProgressBar {
    background-color: #3c3c3c;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: #d4d4d4;
    font-size: 11px;
    height: 16px;
}
QProgressBar::chunk {
    background-color: #0e639c;
    border-radius: 2px;
}

QProgressDialog {
    background-color: #2d2d2d;
    color: #d4d4d4;
}

QLabel {
    color: #d4d4d4;
    font-size: 12px;
}

QScrollBar:vertical {
    background-color: #1e1e1e;
    width: 12px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #424242;
    border-radius: 3px;
    min-height: 30px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: #555555;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #1e1e1e;
    height: 12px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #424242;
    border-radius: 3px;
    min-width: 30px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #555555;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QTabWidget::pane {
    border: 1px solid #404040;
    background-color: #1e1e1e;
}
QTabBar::tab {
    background-color: #2d2d2d;
    color: #969696;
    border: 1px solid #404040;
    padding: 6px 16px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border-bottom-color: #1e1e1e;
}
QTabBar::tab:hover {
    color: #d4d4d4;
}
"""


def apply_dark_theme(app):
    """QApplication에 다크 테마 적용."""
    app.setStyleSheet(DARK_STYLE)
