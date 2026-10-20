"""Shared light palette and readable, quiet desktop controls."""
STYLE='''
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #27364e; }
QMainWindow, QDialog { background: #f5f7fb; }
QFrame#header { background: #ffffff; border: none; border-bottom: 1px solid #e6eaf1; }
QLabel#brand { color: #3e50d5; font-size: 23px; font-weight: 700; }
QLabel#projectName { color: #52627b; font-size: 13px; }
QLabel#saveState { color: #5966a0; background: #eef0ff; border-radius: 8px; padding: 4px 8px; font-size: 11px; }
QFrame#card { background: #ffffff; border: 1px solid #e4e9f2; border-radius: 12px; }
QWidget#workspace { background: #ffffff; border: none; }
QLabel#heading { color: #1f2e45; font-size: 17px; font-weight: 600; }
QLabel#sectionTitle { color: #364660; font-size: 13px; font-weight: 600; }
QLabel#muted { color: #77859a; font-size: 12px; }
QLabel#eyebrow { color: #6978da; font-size: 12px; font-weight: 600; }
QLabel#welcomeTitle { color: #23324d; font-size: 29px; font-weight: 700; }
QLabel#welcomeSubtitle { color: #73829a; font-size: 14px; }
QFrame#workflowBanner { background: #f0f2ff; border: 1px solid #e2e7fc; border-radius: 10px; }
QLabel#nextHint { color: #596988; font-size: 12px; }
QPushButton { background: #ffffff; border: 1px solid #dfe5ef; border-radius: 7px; padding: 8px 11px; min-height: 19px; }
QPushButton:hover { background: #f5f6ff; border-color: #b8c1f2; }
QPushButton:pressed { background: #eaedff; }
QPushButton:disabled { color: #a0aabd; background: #f7f8fb; border-color: #edf0f5; }
QPushButton#workflowStep { min-height: 62px; max-height: 62px; padding: 0; border: none; background: transparent; }
QPushButton#primary { background: #5263e8; color: white; border-color: #5263e8; font-weight: 600; }
QPushButton#primary:hover { background: #4657d6; }
QPushButton#primary:disabled { color: #a3abce; background: #e8ebf8; border-color: #e8ebf8; }
QPushButton#textButton { background: transparent; border: none; color: #6473c8; padding: 5px 3px; text-align: left; }
QPushButton#iconButton { background: transparent; border: 1px solid transparent; padding: 7px; min-width: 20px; }
QPushButton#iconButton:hover { background: #f1f3fb; border-color: #e1e6f1; }
QToolButton#sourceSwitch { background: #ffffff; border: 1px solid #dfe5ef; border-radius: 7px; padding: 8px 15px 8px 8px; min-height: 19px; }
QToolButton#sourceSwitch:hover { background: #f5f6ff; border-color: #b8c1f2; }
QToolButton#sourceSwitch::menu-button { width: 14px; border-left: 1px solid #e4e9f2; }
QToolButton#disclosure { border: none; border-top: 1px solid #edf0f5; background: transparent; padding: 11px 2px; text-align: left; color: #687995; }
QToolButton#fontCard { background: #f8f9fe; border: 1px solid #e3e8f4; border-radius: 9px; padding: 8px; }
QToolButton#fontCard:hover { border-color: #a5b0ed; background: #f0f2ff; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #ffffff; border: 1px solid #dfe5ef; border-radius: 6px; padding: 7px; selection-background-color: #e3e8ff; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #8b9aee; }
QTableWidget { background: #ffffff; alternate-background-color: #f8faff; border: 1px solid #e6ebf3; border-radius: 7px; gridline-color: #edf0f6; selection-background-color: #e8edff; selection-color: #3448a9; }
QListWidget { background: #ffffff; border: 1px solid #e6ebf3; border-radius: 7px; }
QListWidget::item:selected { background: #e9edff; color: #4053b7; }
QListWidget#lyricsList { border: none; background: transparent; }
QListWidget#recentList { border: none; background: #f7f9fc; border-radius: 8px; font-size: 12px; }
QListWidget#recentList::item { padding: 5px 12px; }
QListWidget#recentList::item:hover { background: #edf0ff; }
QListWidget#recentList::item:selected { background: #e9edff; color: #3548af; }
QHeaderView::section { background: #f7f9fc; color: #7d8da5; border: none; padding: 9px 7px; font-weight: 500; }
QTabWidget#calibrationSections::pane { border: none; background: white; padding-top: 8px; }
QTabWidget#calibrationSections QTabBar::tab { color: #73839b; background: #f5f7fb; border: none; padding: 9px 16px; margin-right: 4px; border-radius: 6px; }
QTabWidget#calibrationSections QTabBar::tab:selected { color: #4556bb; background: #e9edff; font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #f5f7fb; }
QSlider::groove:horizontal { height: 4px; background: #e3e8f3; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; border-radius: 6px; background: #6e7ee9; }
QSlider::groove:vertical { width: 4px; background: #e3e8f3; border-radius: 2px; margin: 6px 0; }
QSlider::handle:vertical { height: 12px; margin: 0 -5px; border-radius: 6px; background: #6e7ee9; }
QProgressBar { background: #e9edf7; border: none; border-radius: 4px; text-align: center; font-size: 11px; }
QProgressBar::chunk { background: #8c9bed; border-radius: 4px; }
QToolTip { color: #33445e; background: #ffffff; border: 1px solid #dce3f0; padding: 7px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #d5ddeb; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
'''
