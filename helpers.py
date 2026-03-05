"""Shared UI helpers, database utilities, and reusable widgets."""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QFrame,
                             QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QCalendarWidget, QDialog, QMessageBox, QApplication, QAbstractItemView)
from PyQt6.QtCore import Qt, QDate
from datetime import datetime
import json
import os
import sqlite3
import config


def db_fetch_all(sql, params=None):
    """Execute a query and return all results as list of dicts (Row factory)."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(sql, params or ())
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def db_fetch_one(sql, params=None):
    """Execute a query and return one result as dict, or None."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(sql, params or ())
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def db_fetch_column(sql, params=None):
    """Execute a query and return first column of all rows as flat list."""
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute(sql, params or ())
    values = [row[0] for row in c.fetchall()]
    conn.close()
    return values


def db_fetch_scalar(sql, params=None):
    """Execute a query and return a single scalar value."""
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute(sql, params or ())
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def db_execute(sql, params=None):
    """Execute an INSERT/UPDATE/DELETE statement and commit."""
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute(sql, params or ())
    conn.commit()
    conn.close()


def db_execute_many(statements):
    """Execute multiple SQL statements in a single transaction.
    
    Args:
        statements: List of (sql, params) tuples
    """
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    for sql, params in statements:
        c.execute(sql, params or ())
    conn.commit()
    conn.close()


def populate_table(table, items, format_row_fn, numeric_columns=None):
    """Clear table and populate it with items using a row-formatting function.
    
    Each source item dict is stored in the first cell's UserRole so that
    handlers (context menu, double-click) can retrieve the original data
    regardless of visual sort order.
    
    Args:
        table: QTableWidget to populate
        items: List of data items (dicts)
        format_row_fn: Function that takes an item and returns a list of string values for the row
        numeric_columns: List of column indices to right-align
    """
    if numeric_columns is None:
        numeric_columns = []
    table.setRowCount(0)
    for item in items:
        row_pos = table.rowCount()
        add_row_to_table(table, format_row_fn(item), numeric_columns=numeric_columns)
        # Store the source data dict so sort-independent lookup is possible
        first_cell = table.item(row_pos, 0)
        if first_cell is not None:
            first_cell.setData(Qt.ItemDataRole.UserRole, item)


def confirm_dialog(parent, title, message):
    """Show a Yes/No confirmation dialog with Polish button labels (Tak/Nie).
    
    Returns True if the user clicked 'Tak' (Yes), False otherwise.
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(title)
    msg.setText(message)
    yes_btn = msg.addButton("Tak", QMessageBox.ButtonRole.YesRole)
    msg.addButton("Nie", QMessageBox.ButtonRole.NoRole)
    msg.exec()
    return msg.clickedButton() == yes_btn


# Column width settings file
COLUMN_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "data", ".column_widths.json")


def save_column_widths(table, table_name):
    """Save column widths for a table to a JSON file."""
    try:
        # Load existing settings
        if os.path.exists(COLUMN_SETTINGS_FILE):
            with open(COLUMN_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
        else:
            settings = {}
        
        # Save current table's column widths
        column_widths = []
        for col in range(table.columnCount()):
            column_widths.append(table.columnWidth(col))
        
        settings[table_name] = column_widths
        
        # Write back to file
        with open(COLUMN_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception as e:
        pass


def load_column_widths(table, table_name):
    """Load and apply saved column widths for a table."""
    try:
        if not os.path.exists(COLUMN_SETTINGS_FILE):
            return
        
        with open(COLUMN_SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
        
        if table_name in settings:
            column_widths = settings[table_name]
            for col, width in enumerate(column_widths):
                if col < table.columnCount():
                    table.setColumnWidth(col, width)
    except Exception as e:
        pass


def save_window_geometry(window):
    """Save window geometry (position and size) to preferences.json."""
    try:
        geometry = window.geometry()
        
        # Load existing preferences
        if os.path.exists(config.PREFERENCES_PATH):
            with open(config.PREFERENCES_PATH, 'r') as f:
                prefs = json.load(f)
        else:
            prefs = {}
        
        # Save geometry
        prefs['window_geometry'] = {
            'x': geometry.x(),
            'y': geometry.y(),
            'width': geometry.width(),
            'height': geometry.height()
        }
        
        # Write back to file
        with open(config.PREFERENCES_PATH, 'w') as f:
            json.dump(prefs, f, indent=2)
    except Exception as e:
        pass


def load_window_geometry(window):
    """Load window geometry from preferences.json and validate it fits on screen."""
    try:
        if not os.path.exists(config.PREFERENCES_PATH):
            return False
        
        with open(config.PREFERENCES_PATH, 'r') as f:
            prefs = json.load(f)
        
        if 'window_geometry' not in prefs:
            return False
        
        geom = prefs['window_geometry']
        x, y, width, height = geom['x'], geom['y'], geom['width'], geom['height']
        
        # Get the screen geometry
        screen = window.screen()
        if not screen:
            return False
        
        screen_geom = screen.availableGeometry()
        
        # Validate window fits within screen bounds
        # Adjust if window is partially or fully outside screen
        if x + width > screen_geom.right():
            x = max(0, screen_geom.right() - width)
        if y + height > screen_geom.bottom():
            y = max(0, screen_geom.bottom() - height)
        if x < screen_geom.left():
            x = screen_geom.left()
        if y < screen_geom.top():
            y = screen_geom.top()
        
        # Ensure minimum size
        width = max(800, min(width, screen_geom.width()))
        height = max(600, min(height, screen_geom.height()))
        
        window.setGeometry(x, y, width, height)
        return True
    except Exception as e:
        return False


# Custom date widget that displays blank when no date is selected
class BlankDateEdit(QWidget):
    """Custom date widget with QLineEdit display and calendar popup."""
    def __init__(self):
        super().__init__()
        self._date = QDate(1900, 1, 1)  # Minimum date
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Line edit for display (read-only)
        self.line_edit = QLineEdit()
        self.line_edit.setReadOnly(True)
        self.line_edit.setPlaceholderText("")
        layout.addWidget(self.line_edit)
        
        # Calendar button
        self.cal_btn = QPushButton("📅")
        self.cal_btn.setMaximumWidth(35)
        self.cal_btn.clicked.connect(self.open_calendar)
        layout.addWidget(self.cal_btn)
        
        self.update_display()
    
    def open_calendar(self):
        """Open calendar dialog."""
        from PyQt6.QtWidgets import QDialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Date")
        dlayout = QVBoxLayout(dialog)
        
        calendar = QCalendarWidget()
        if self._date != QDate(1900, 1, 1):
            calendar.setSelectedDate(self._date)
        dlayout.addWidget(calendar)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        clear_btn = QPushButton("Clear")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(clear_btn)
        dlayout.addLayout(btn_layout)
        
        ok_btn.clicked.connect(lambda: self.set_date(calendar.selectedDate()) or dialog.accept())
        clear_btn.clicked.connect(lambda: self.set_date(QDate(1900, 1, 1)) or dialog.accept())
        
        dialog.exec()
    
    def set_date(self, date):
        """Set the date."""
        self._date = date
        self.update_display()
    
    def date(self):
        """Get the date."""
        return self._date
    
    def update_display(self):
        """Update the line edit display."""
        if self._date == QDate(1900, 1, 1):
            self.line_edit.setText("")
        else:
            self.line_edit.setText(self._date.toString("dd-MM-yyyy"))
    
    def setDate(self, date):
        """PyQt compatibility method."""
        self.set_date(date)
    
    def setCalendarPopup(self, enabled):
        """PyQt compatibility method (for our case, calendar is always available)."""
        pass
    
    def minimumDate(self):
        """Return the minimum date (1900-01-01)."""
        return QDate(1900, 1, 1)


def clear_content(parent_window):
    """Remove all widgets and layouts from the main content layout."""
    layout = parent_window.content_layout
    
    def clear_layout(layout_to_clear):
        """Recursively clear all items from a layout."""
        while layout_to_clear.count() > 0:
            item = layout_to_clear.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.deleteLater()
            elif item.layout():
                clear_layout(item.layout())
                item.layout().deleteLater()
    
    clear_layout(layout)


class CopyableTableWidget(QTableWidget):
    """Custom QTableWidget with Ctrl+C support to copy all data including headers."""
    
    def keyPressEvent(self, event):
        """Handle Ctrl+C to copy all table data with headers."""
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Copy all table data including headers to clipboard
            self.copy_table_to_clipboard()
        else:
            super().keyPressEvent(event)
    
    def copy_table_to_clipboard(self):
        """Copy all table data including headers as tab-separated text."""
        clipboard = QApplication.clipboard()
        
        # Collect all data
        rows_text = []
        
        # Add header row
        headers = []
        for col in range(self.columnCount()):
            header_item = self.horizontalHeaderItem(col)
            headers.append(header_item.text() if header_item else f"Column {col}")
        rows_text.append('\t'.join(headers))
        
        # Add all data rows
        for row in range(self.rowCount()):
            row_data = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                row_data.append(item.text() if item else "")
            rows_text.append('\t'.join(row_data))
        
        # Copy to clipboard
        clipboard.setText('\n'.join(rows_text))


def create_table_with_scrollbar(parent, columns, show_row_numbers=True, table_name=None):
    """Create a PyQt6 table widget with dark theme formatting and resizable columns."""
    # Create table widget
    table = CopyableTableWidget(parent)
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.table_name = table_name  # Store table name for settings
    
    # Store original data in table for sorting
    table.original_data = []
    table.sort_column = -1
    table.sort_ascending = True
    
    # Get header
    header = table.horizontalHeader()
    
    # Style the table with dark theme
    header.setStyleSheet("""
        QHeaderView::section {
            background-color: #1e1e1e;
            color: white;
            padding: 5px;
            border: 1px solid #333333;
            font-weight: bold;
        }
    """)
    # Allow user to resize columns interactively
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(True)
    
    # Dark theme for table
    table.setStyleSheet("""
        QTableWidget {
            gridline-color: #333333;
            background-color: #212121;
            color: white;
            border: 1px solid #333333;
        }
        QTableWidget::item {
            padding: 5px;
            color: white;
        }
        QTableWidget::item:alternate {
            background-color: #2a2a2a;
        }
        QTableWidget::item:hover {
            background-color: #404040;
        }
        QTableWidget::item:alternate:hover {
            background-color: #404040;
        }
        QTableWidget::item:selected {
            background-color: #0d47a1;
        }
    """)
    
    table.setAlternatingRowColors(True)
    
    # Set default column widths
    for i in range(len(columns)):
        table.setColumnWidth(i, 150)
    
    # Load saved column widths if available
    if table_name:
        load_column_widths(table, table_name)
        # Connect to auto-save when columns are resized
        header.sectionResized.connect(lambda: save_column_widths(table, table_name))
    
    return table


def add_row_to_table(table, values, numeric_columns=None):
    """Add a row to the table with given values. Right-align numeric_columns."""
    if numeric_columns is None:
        numeric_columns = []
    
    row_position = table.rowCount()
    table.insertRow(row_position)
    
    for col, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Make read-only
        
        # Right-align numeric columns
        if col in numeric_columns:
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        
        table.setItem(row_position, col, item)


def parse_date(date_string, date_format="%d-%m-%Y"):
    """Parse a date string safely. Returns None if parsing fails."""
    try:
        return datetime.strptime(date_string, date_format).date()
    except (ValueError, TypeError):
        return None


def sort_table_by_column(table, column, numeric_columns=None, table_name=None):
    """Sort table by column. Click again to reverse sort direction."""
    if numeric_columns is None:
        numeric_columns = []
    
    # Initialize sort state if not exists
    if not hasattr(table, 'sort_column'):
        table.sort_column = -1
    if not hasattr(table, 'sort_ascending'):
        table.sort_ascending = False
    
    # Toggle sort direction if clicking same column
    if table.sort_column == column:
        table.sort_ascending = not table.sort_ascending
    else:
        table.sort_column = column
        table.sort_ascending = False  # Start descending for new column
    
    # Save sorting preference if table_name provided
    if table_name:
        # Convert toggle state to actual direction
        # sort_ascending=False means currently ascending, so save True
        # sort_ascending=True means currently descending, so save False
        actual_ascending = not table.sort_ascending
        save_table_sort_preference(table_name, table.sort_column, actual_ascending)
    
    # Get all rows from table (preserve UserRole data from first column)
    rows = []
    for row in range(table.rowCount()):
        row_data = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            value = item.text() if item else ""
            row_data.append(value)
        first_item = table.item(row, 0)
        user_data = first_item.data(Qt.ItemDataRole.UserRole) if first_item else None
        rows.append((row_data, user_data))
    
    # Determine if column should be sorted as numeric
    col_name = table.horizontalHeaderItem(column).text() if column < table.columnCount() else ""
    is_numeric = column in numeric_columns or col_name in numeric_columns
    
    # Detect if column contains dates (by checking column name)
    is_date = col_name.lower() in ['data', 'date', 'data od', 'data do', 'invoice_date', 'work_date', 'cost_date', 'start_date', 'end_date', 'data faktury', 'data płatności', 'data płatnosci', 'data płatno', 'data wynagr', 'data koniec']
    
    # Sort rows
    def sort_key(entry):
        val = entry[0][column] if column < len(entry[0]) else ""
        if is_numeric:
            try:
                return float(val.replace(',', '.').replace(',', ''))
            except:
                return 0
        elif is_date:
            # Parse date in dd-mm-yyyy format
            try:
                val_clean = val.strip()
                parts = val_clean.split('-')
                if len(parts) == 3:
                    return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                return datetime(1900, 1, 1)
            except:
                return datetime(1900, 1, 1)
        return val.lower()
    
    rows.sort(key=sort_key, reverse=table.sort_ascending)
    
    # Rebuild table
    table.setRowCount(0)
    for row_data, user_data in rows:
        row_position = table.rowCount()
        table.insertRow(row_position)
        for col, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            
            # Keep numeric columns right-aligned even when sorted
            if col in numeric_columns:
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            
            # Restore UserRole data on the first column
            if col == 0 and user_data is not None:
                item.setData(Qt.ItemDataRole.UserRole, user_data)
            
            table.setItem(row_position, col, item)


def save_table_sort_preference(table_name, column, ascending):
    """Save table sorting preference to preferences file."""
    try:
        preferences = {}
        
        # Load existing preferences
        if os.path.exists(config.PREFERENCES_PATH):
            try:
                with open(config.PREFERENCES_PATH, 'r') as f:
                    preferences = json.load(f)
            except:
                pass
        
        # Ensure table_sorts key exists
        if 'table_sorts' not in preferences:
            preferences['table_sorts'] = {}
        
        # Save this table's sort preference
        preferences['table_sorts'][table_name] = {
            'column': column,
            'ascending': ascending
        }
        
        # Write back to file
        with open(config.PREFERENCES_PATH, 'w') as f:
            json.dump(preferences, f, indent=2)
    except Exception as e:
        pass


def load_table_sort_preference(table_name):
    """Load table sorting preference from preferences file."""
    try:
        if not os.path.exists(config.PREFERENCES_PATH):
            return None
        
        with open(config.PREFERENCES_PATH, 'r') as f:
            preferences = json.load(f)
        
        if 'table_sorts' in preferences and table_name in preferences['table_sorts']:
            sort_data = preferences['table_sorts'][table_name]
            return (sort_data.get('column'), sort_data.get('ascending'))
    except Exception as e:
        pass
    
    return None


def apply_saved_sort(table, table_name, numeric_columns=None):
    """Apply saved sort preference to table by directly sorting without toggle logic."""
    if numeric_columns is None:
        numeric_columns = []
    
    # Initialize sort state if not exists
    if not hasattr(table, 'sort_column'):
        table.sort_column = -1
    if not hasattr(table, 'sort_ascending'):
        table.sort_ascending = True
    
    if table.rowCount() == 0:
        return
    
    sort_pref = load_table_sort_preference(table_name)
    if not sort_pref:
        return
    
    column, ascending = sort_pref
    if column is None or column < 0 or column >= table.columnCount():
        return
    
    # Directly sort rows without using the toggle logic
    # Get all rows (preserve UserRole data from first column)
    rows = []
    for row in range(table.rowCount()):
        row_data = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            value = item.text() if item else ""
            row_data.append(value)
        first_item = table.item(row, 0)
        user_data = first_item.data(Qt.ItemDataRole.UserRole) if first_item else None
        rows.append((row_data, user_data))
    
    # Determine sort parameters
    col_name = table.horizontalHeaderItem(column).text() if column < table.columnCount() else ""
    is_numeric = column in numeric_columns or col_name in numeric_columns
    is_date = col_name.lower() in ['data', 'date', 'data od', 'data do', 'invoice_date', 'work_date', 'cost_date', 'start_date', 'end_date', 'data faktury', 'data płatności', 'data płatnosci', 'data płatno', 'data wynagr', 'data koniec']
    
    # Sort key function
    def sort_key(entry):
        val = entry[0][column] if column < len(entry[0]) else ""
        if is_numeric:
            try:
                return float(val.replace(',', '.').replace(',', ''))
            except:
                return 0
        elif is_date:
            try:
                val_clean = val.strip()  # Remove whitespace
                parts = val_clean.split('-')
                if len(parts) == 3:
                    parsed = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                    return parsed
                else:
                    return datetime(1900, 1, 1)
            except Exception as e:
                return datetime(1900, 1, 1)
        return val.lower()
    
    # Sort with the saved direction (ascending=True means ascending order)
    rows.sort(key=sort_key, reverse=not ascending)
    
    # Rebuild table
    table.setRowCount(0)
    for row_data, user_data in rows:
        row_position = table.rowCount()
        table.insertRow(row_position)
        for col, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col in numeric_columns:
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            if col == 0 and user_data is not None:
                item.setData(Qt.ItemDataRole.UserRole, user_data)
            table.setItem(row_position, col, item)
    
    # Set the sort state for future clicks
    table.sort_column = column
    table.sort_ascending = not ascending  # Opposite of current, since next click will toggle


def split_row(table, row, numeric_columns=None, editable_columns=None, parent=None):
    """Split a row into two rows. Divides netto, vat, and brutto by 2 (rounded).
    Ensures split rows add up to original by adjusting ±0.01 if needed.
    """
    if numeric_columns is None:
        numeric_columns = []
    if editable_columns is None:
        editable_columns = []
    
    if row < 0 or row >= table.rowCount():
        return
    
    # Get current row data
    row_data = []
    for col in range(table.columnCount()):
        item = table.item(row, col)
        if item:
            row_data.append(item.text())
        else:
            row_data.append("")
    
    # Parse quantity
    try:
        original_quantity = float(row_data[1].replace(',', '.'))
    except:
        QMessageBox.warning(parent, "Błąd", "Nie można przeczytać ilości")
        return
    
    # Parse original netto and brutto
    try:
        original_netto = float(row_data[3].replace(',', '.'))
        original_brutto = float(row_data[4].replace(',', '.'))
    except:
        QMessageBox.warning(parent, "Błąd", "Nie można przeczytać wartości netto lub brutto")
        return
    
    # Calculate original VAT
    original_vat = original_brutto - original_netto
    
    # Show dialog for quantity input
    dialog = QDialog(parent)
    dialog.setWindowTitle("Podziel rząd")
    layout = QVBoxLayout(dialog)
    
    layout.addWidget(QLabel(f"Oryginalna ilość: {original_quantity}"))
    layout.addWidget(QLabel("Ilość dla drugiego wiersza:"))
    
    qty_spin = QDoubleSpinBox()
    qty_spin.setValue(original_quantity / 2)
    qty_spin.setMinimum(0)
    qty_spin.setMaximum(original_quantity)
    qty_spin.setDecimals(2)
    layout.addWidget(qty_spin)
    
    button_layout = QHBoxLayout()
    ok_btn = QPushButton("OK")
    cancel_btn = QPushButton("Anuluj")
    
    ok_btn.clicked.connect(dialog.accept)
    cancel_btn.clicked.connect(dialog.reject)
    
    button_layout.addWidget(ok_btn)
    button_layout.addWidget(cancel_btn)
    layout.addLayout(button_layout)
    
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    
    second_quantity = qty_spin.value()
    first_quantity = original_quantity - second_quantity
    
    if first_quantity < 0 or second_quantity < 0:
        QMessageBox.warning(parent, "Błąd", "Ilość musi być dodatnia")
        return
    
    # Calculate split values: divide by 2 and round
    first_netto = round(original_netto / 2, 2)
    first_vat = round(original_vat / 2, 2)
    first_brutto = first_netto + first_vat
    
    # Second row gets the remainder
    second_netto = original_netto - first_netto
    second_vat = original_vat - first_vat
    second_brutto = second_netto + second_vat
    
    # Verify and adjust if needed
    if abs((first_netto + second_netto) - original_netto) > 0.001:
        # Adjust second netto by ±0.01 to make it match
        diff = original_netto - (first_netto + second_netto)
        second_netto += diff
        second_brutto = second_netto + second_vat
    
    if abs((first_vat + second_vat) - original_vat) > 0.001:
        # Adjust second vat by ±0.01 to make it match
        diff = original_vat - (first_vat + second_vat)
        second_vat += diff
        second_brutto = second_netto + second_vat
    
    # Update current row with first split values
    first_qty_str = f"{first_quantity:.2f}".replace('.', ',')
    table.item(row, 1).setText(first_qty_str)
    table.item(row, 3).setText(f"{first_netto:.2f}".replace('.', ','))
    table.item(row, 4).setText(f"{first_brutto:.2f}".replace('.', ','))
    
    # Create new row data with second split values
    new_row_data = row_data.copy()
    second_qty_str = f"{second_quantity:.2f}".replace('.', ',')
    new_row_data[1] = second_qty_str
    new_row_data[3] = f"{second_netto:.2f}".replace('.', ',')
    new_row_data[4] = f"{second_brutto:.2f}".replace('.', ',')
    new_row_data[8] = ""  # Split row is not original, so empty the "Wiersz pierwotny" column
    
    # Insert new row after current row
    table.insertRow(row + 1)
    for col, value in enumerate(new_row_data):
        new_item = QTableWidgetItem(value)
        
        # Set editability based on column type
        if col in editable_columns:
            new_item.setFlags(new_item.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        
        # Maintain numeric column alignment
        if col in numeric_columns:
            new_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        
        # Center align assignment columns (5, 6, 7) and "Wiersz pierwotny" (8)
        if col in [5, 6, 7, 8]:
            new_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
        
        table.setItem(row + 1, col, new_item)
    
    # Track split relationships
    if not hasattr(table, 'split_rows'):
        table.split_rows = {}
    table.split_rows[row + 1] = row  # New row points to original row


def delete_row(table, row, numeric_columns=None, parent=None):
    """Delete a row. If it's a split row, add quantity back to original row."""
    if numeric_columns is None:
        numeric_columns = []
    
    if row < 0 or row >= table.rowCount():
        return
    
    # Check if this is a split row
    if not hasattr(table, 'split_rows'):
        table.split_rows = {}
    
    if row not in table.split_rows:
        QMessageBox.warning(parent, "Błąd", "Można usunąć tylko wiersze stworzone przez podział")
        return
    
    # Get the original row
    original_row = table.split_rows[row]
    
    # Get quantities
    try:
        deleted_qty_text = table.item(row, 1).text()
        deleted_qty = float(deleted_qty_text.replace(',', '.'))
        
        original_qty_text = table.item(original_row, 1).text()
        original_qty = float(original_qty_text.replace(',', '.'))
    except:
        QMessageBox.warning(parent, "Błąd", "Nie można przeczytać ilości")
        return
    
    # Add back to original row
    new_original_qty = original_qty + deleted_qty
    new_qty_str = f"{new_original_qty:.2f}".replace('.', ',')
    table.item(original_row, 1).setText(new_qty_str)
    
    # Delete the row
    table.removeRow(row)
    
    # Update split_rows dictionary - remove this row and shift indices if needed
    rows_to_update = []
    for split_row_idx, orig_idx in list(table.split_rows.items()):
        if split_row_idx == row:
            del table.split_rows[split_row_idx]
        elif split_row_idx > row:
            rows_to_update.append((split_row_idx, orig_idx))
    
    # Shift indices after deleted row
    for split_row_idx, orig_idx in rows_to_update:
        del table.split_rows[split_row_idx]
        new_idx = split_row_idx - 1
        new_orig_idx = orig_idx if orig_idx < row else orig_idx - 1
        table.split_rows[new_idx] = new_orig_idx


def center_widget_in_cell(widget):
    """Wrap a widget in a container to center it vertically in a table cell."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addStretch()
    layout.addWidget(widget)
    layout.addStretch()
    return container


def create_filter_panel(window, row_count, height=350):
    """Create a standard filter panel with frame, table, and filter/reset buttons.
    
    Returns:
        tuple: (filter_frame, filter_table, filter_layout, filter_btn, reset_btn)
    """
    filter_frame = QFrame(window)
    filter_frame.setMaximumWidth(275)
    filter_frame.setFixedHeight(height)
    filter_layout = QVBoxLayout(filter_frame)
    filter_layout.setContentsMargins(10, 10, 10, 10)
    
    filter_table = QTableWidget()
    filter_table.setColumnCount(2)
    filter_table.setRowCount(row_count)
    filter_table.setHorizontalHeaderLabels(["", ""])
    filter_table.horizontalHeader().setVisible(False)
    filter_table.verticalHeader().setVisible(False)
    filter_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    filter_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    
    filter_table.setColumnWidth(0, 72)
    filter_table.setColumnWidth(1, 180)
    for row in range(row_count):
        filter_table.setRowHeight(row, 37)
    
    button_layout = QHBoxLayout()
    filter_btn = QPushButton("Filtruj")
    reset_btn = QPushButton("Resetuj filtry")
    button_layout.addWidget(filter_btn)
    button_layout.addWidget(reset_btn)
    filter_layout.addLayout(button_layout)
    filter_layout.addWidget(filter_table)
    
    return filter_frame, filter_table, filter_layout, filter_btn, reset_btn


def add_filter_row(table, row, label, widget, widget_height=32):
    """Add a labeled row to a filter or input table.
    
    Args:
        table: QTableWidget to add the row to
        row: Row index
        label: Label text for column 0
        widget: Widget to place in column 1
        widget_height: Fixed height for the widget
    """
    item = QTableWidgetItem(label)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    table.setItem(row, 0, item)
    widget.setFixedHeight(widget_height)
    table.setCellWidget(row, 1, center_widget_in_cell(widget))


def create_input_table(row_count, col1_width=150, col2_width=350):
    """Create a standard input table for dialogs (2 columns, hidden headers, no grid).
    
    Returns:
        QTableWidget configured for form-style input
    """
    input_table = QTableWidget()
    input_table.setColumnCount(2)
    input_table.setRowCount(row_count)
    input_table.setHorizontalHeaderLabels(["", ""])
    input_table.horizontalHeader().setVisible(False)
    input_table.verticalHeader().setVisible(False)
    input_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    input_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    input_table.setShowGrid(False)
    
    input_table.setColumnWidth(0, col1_width)
    input_table.setColumnWidth(1, col2_width)
    
    for row in range(row_count - 1):
        input_table.setRowHeight(row, 35)
    input_table.setRowHeight(row_count - 1, 45)
    
    return input_table


def add_input_row(table, row, label, widget, widget_height=27):
    """Add a labeled row to an input table (no alignment flags on label, simpler version).
    
    Args:
        table: QTableWidget to add the row to
        row: Row index
        label: Label text for column 0
        widget: Widget to place in column 1
        widget_height: Fixed height for the widget
    """
    item = QTableWidgetItem(label)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
    table.setItem(row, 0, item)
    widget.setFixedHeight(widget_height)
    table.setCellWidget(row, 1, center_widget_in_cell(widget))


def add_button_row(table, row, button, span_cols=2):
    """Add a full-width button row to an input table.
    
    Args:
        table: QTableWidget to add to
        row: Row index for the button
        button: QPushButton to place
        span_cols: Number of columns to span
    """
    button_layout = QHBoxLayout()
    button_layout.addWidget(button)
    button_container = QWidget()
    button_container.setLayout(button_layout)
    table.setCellWidget(row, 0, button_container)
    table.setSpan(row, 0, 1, span_cols)


def copy_table_row_to_clipboard(table, row):
    """Copy all cell texts from a table row as tab-separated text to clipboard."""
    clipboard = QApplication.clipboard()
    row_data = []
    for col in range(table.columnCount()):
        item = table.item(row, col)
        if item:
            row_data.append(item.text())
    clipboard.setText("\t".join(row_data))


def create_details_table(detail_items, col0_width=72, col1_width=180, row_height=35):
    """Create a 2-column read-only details table (label/value).
    
    Args:
        detail_items: List of (label, value) tuples
        col0_width: Width of label column
        col1_width: Width of value column
        row_height: Height of each row
    
    Returns:
        QTableWidget populated with the detail items
    """
    details_table = QTableWidget()
    details_table.setColumnCount(2)
    details_table.setRowCount(len(detail_items))
    details_table.setHorizontalHeaderLabels(["", ""])
    details_table.horizontalHeader().setVisible(False)
    details_table.verticalHeader().setVisible(False)
    details_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    details_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    
    for row, (label, value) in enumerate(detail_items):
        label_item = QTableWidgetItem(label)
        label_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
        details_table.setItem(row, 0, label_item)
        
        value_item = QTableWidgetItem(value)
        value_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
        details_table.setItem(row, 1, value_item)
        details_table.setRowHeight(row, row_height)
    
    details_table.setColumnWidth(0, col0_width)
    details_table.setColumnWidth(1, col1_width)
    
    return details_table


def create_details_table_with_copy(detail_items, col0_width=150, col1_width=350, col2_width=80, row_height=30):
    """Create a 3-column read-only details table with copy buttons.
    
    Args:
        detail_items: List of (label, value) tuples
        col0_width, col1_width, col2_width: Column widths
        row_height: Height of each row
    
    Returns:
        QTableWidget populated with details and copy buttons
    """
    details_table = QTableWidget()
    details_table.setColumnCount(3)
    details_table.setRowCount(len(detail_items))
    details_table.setHorizontalHeaderLabels(["", "", ""])
    details_table.horizontalHeader().setVisible(False)
    details_table.verticalHeader().setVisible(False)
    details_table.setColumnWidth(0, col0_width)
    details_table.setColumnWidth(1, col1_width)
    details_table.setColumnWidth(2, col2_width)
    details_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    details_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    details_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    details_table.setShowGrid(False)
    
    for row_idx, (label, value) in enumerate(detail_items):
        label_item = QTableWidgetItem(label)
        label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
        details_table.setItem(row_idx, 0, label_item)
        
        value_item = QTableWidgetItem(value)
        value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
        details_table.setItem(row_idx, 1, value_item)
        
        copy_btn = QPushButton("Kopiuj")
        copy_btn.setMaximumWidth(70)
        copy_btn.clicked.connect(lambda checked, val=value: QApplication.clipboard().setText(val))
        details_table.setCellWidget(row_idx, 2, center_widget_in_cell(copy_btn))
        
        details_table.setRowHeight(row_idx, row_height)
    
    return details_table


def is_date_in_range(item_date, from_date_widget, until_date_widget):
    """Check if a date falls within the range specified by from/until date widgets.
    
    Args:
        item_date: datetime.date object to check
        from_date_widget: BlankDateEdit widget for start date
        until_date_widget: BlankDateEdit widget for end date
    
    Returns:
        True if date is in range (or no range set), False if outside range
    """
    from_qdate = from_date_widget.date()
    until_qdate = until_date_widget.date()
    
    if from_qdate.isValid() and from_qdate.toPyDate() > item_date:
        return False
    if until_qdate.isValid() and until_qdate.toPyDate() < item_date:
        return False
    return True
