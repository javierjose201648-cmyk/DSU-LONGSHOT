"""Tema oscuro de la app."""

ESTILO = """
* { font-family: "Segoe UI"; font-size: 10pt; color: #e8e8ee; }
QMainWindow, QWidget#central, QDialog { background: #141418; }
QListWidget#nav { background: #0f0f13; border: none; outline: none; padding-top: 8px; }
QListWidget#nav::item { padding: 12px 18px; border-left: 3px solid transparent; color: #a8a8b4; }
QListWidget#nav::item:selected { background: #1d1d24; border-left: 3px solid #8d4fc7; color: #ffffff; }
QListWidget#nav::item:hover { background: #18181e; }
QLabel#titulo { font-size: 17pt; font-weight: 600; }
QLabel#sub { color: #9a9aa6; }
QLabel#grande { font-size: 15pt; font-weight: 600; }
QLabel#aviso { color: #ffb020; }
QLabel#error { color: #ff6b70; }
QLabel#ok { color: #2fbf71; }
QLabel#dato { font-family: Consolas; font-size: 11pt; }
QFrame#tarjeta { background: #1b1b21; border: 1px solid #26262e; border-radius: 10px; }
QPushButton { background: #2a2a33; border: 1px solid #383844; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #33333e; }
QPushButton:pressed { background: #26262e; }
QPushButton:disabled { color: #6a6a74; background: #1e1e24; border-color: #2a2a32; }
QPushButton#primario { background: #8d4fc7; border-color: #a66be0; font-weight: 600; padding: 9px 20px; }
QPushButton#primario:hover { background: #9c5fd6; }
QPushButton#primario:disabled { background: #3d2c52; color: #8a8a96; border-color: #3d2c52; }
QPushButton#verde { background: #1f8f55; border-color: #2fbf71; font-weight: 600; padding: 12px 26px; font-size: 12pt; }
QPushButton#verde:hover { background: #25a362; }
QPushButton#rojo { background: #8f2a2e; border-color: #e5484d; font-weight: 600; padding: 12px 26px; font-size: 12pt; }
QPushButton#escucha { background: #5a3d00; border-color: #ffb020; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #101014; border: 1px solid #33333d;
    border-radius: 6px; padding: 6px 8px; selection-background-color: #8d4fc7; }
QComboBox QAbstractItemView { background: #1b1b21; selection-background-color: #8d4fc7; }
QTableWidget { background: #17171c; border: 1px solid #26262e; border-radius: 8px; gridline-color: #24242b; }
QTableWidget::item { padding: 4px; }
QHeaderView::section { background: #1f1f26; border: none; padding: 6px; color: #a8a8b4; }
QProgressBar { background: #26262d; border: none; border-radius: 6px; height: 12px; text-align: center; }
QProgressBar::chunk { background: #8d4fc7; border-radius: 6px; }
QSlider::groove:horizontal { height: 6px; background: #2a2a33; border-radius: 3px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #8d4fc7; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QListWidget { background: #17171c; border: 1px solid #26262e; border-radius: 8px; }
QListWidget::item { padding: 7px; }
QListWidget::item:selected { background: #3a2a52; }
QScrollArea { border: none; background: transparent; }
QToolTip { background: #26262e; color: #e8e8ee; border: 1px solid #44444f; }
QPlainTextEdit { background: #101014; border: 1px solid #26262e; border-radius: 6px; font-family: Consolas; }
"""
