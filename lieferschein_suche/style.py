APP_STYLE = """
QMainWindow, QWidget { background: #f5f7fb; color: #172033; font-family: "Segoe UI"; font-size: 10pt; }
QFrame#sidebar { background: #14213d; border-radius: 12px; }
QFrame#sidebar QLabel { color: #e8eefb; background: transparent; }
QLabel#appTitle { color: white; font-size: 18pt; font-weight: 650; }
QLabel#appSubtitle { color: #9fb1d4; }
QLabel#sectionTitle { font-size: 12pt; font-weight: 650; }
QLineEdit { background: white; border: 1px solid #cbd5e1; border-radius: 9px; padding: 10px 12px; font-size: 12pt; }
QLineEdit:focus { border: 2px solid #2563eb; }
QPushButton { background: #e7edf7; border: none; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #d8e3f4; }
QPushButton#primary { background: #2563eb; color: white; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#danger { background: #fee2e2; color: #991b1b; }
QPushButton:disabled { color: #94a3b8; background: #e2e8f0; }
QCheckBox { spacing: 8px; }
QTreeWidget { background: white; border: 1px solid #dbe3ef; border-radius: 10px; alternate-background-color: #f8fafc; }
QTreeWidget::item { padding: 9px 5px; }
QTreeWidget::item:selected { background: #dbeafe; color: #172033; }
QHeaderView::section { background: #edf2f9; padding: 8px; border: none; font-weight: 650; }
QScrollArea { background: #dce3ed; border: 1px solid #cbd5e1; border-radius: 8px; }
QLabel#previewImage { background: #dce3ed; color: #64748b; }
QProgressBar { border: none; border-radius: 5px; background: #dce3ed; height: 10px; text-align: center; }
QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
QStatusBar { background: white; border-top: 1px solid #e2e8f0; }
"""

