"""Labor view — work hours tracking per project and employee."""
import sqlite3
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QHBoxLayout, QComboBox, QDialog, QLineEdit, QMessageBox
from PyQt6.QtCore import QDate, Qt
from helpers import (clear_content, create_table_with_scrollbar, add_row_to_table, sort_table_by_column,
                     parse_date, BlankDateEdit, apply_saved_sort,
                     create_filter_panel, add_filter_row, create_input_table, add_input_row,
                     add_button_row, copy_table_row_to_clipboard, is_date_in_range,
                     populate_table, db_fetch_all, db_fetch_column, db_fetch_scalar, db_execute, confirm_dialog)


def get_labor_from_db():
    return db_fetch_all("""
        SELECT l.id, l.project_id, l.employee_id, l.work_date, l.hours_worked, l.hourly_rate, l.total_cost,
               p.project_code, e.name as person_name
        FROM labor l
        LEFT JOIN projects p ON l.project_id = p.id
        LEFT JOIN employees e ON l.employee_id = e.id
        ORDER BY l.work_date DESC
    """)


def get_employees_from_labor_db():
    """Get all employee names from employees table."""
    return db_fetch_column("SELECT name FROM employees WHERE status = 'active' ORDER BY name")


def get_projects_from_db():
    """Get all projects from database."""
    return db_fetch_all("SELECT id, project_code FROM projects ORDER BY project_code")


def get_hourly_rate_for_employee(employee_name):
    """Get hourly rate for an employee from employees table."""
    result = db_fetch_scalar("SELECT hourly_rate FROM employees WHERE name = ?", (employee_name,))
    return result if result else 0


def get_employee_id_by_name(employee_name):
    """Get employee ID by name."""
    return db_fetch_scalar("SELECT id FROM employees WHERE name = ?", (employee_name,))


def get_latest_labor_date():
    """Get the latest labor date from database, or today if no labor exists."""
    result = db_fetch_scalar("SELECT work_date FROM labor ORDER BY id DESC LIMIT 1")
    
    if not result:
        return QDate.currentDate()
    
    try:
        date_obj = QDate.fromString(result, "dd-MM-yyyy")
        return date_obj if date_obj.isValid() else QDate.currentDate()
    except:
        return QDate.currentDate()


def _format_labor_row(item):
    """Format a labor item dict into a row of strings for the table."""
    return [
        item.get("work_date", ""),
        item.get("project_code", ""),
        item.get("person_name", ""),
        f"{item.get('hours_worked', 0):.2f}",
        f"{item.get('hourly_rate', 0):.2f}".replace('.', ','),
        f"{item.get('total_cost', 0):.2f}".replace('.', ',')
    ]


def show_labor(window):
    """Display labor entries with filters, sorting, and CRUD operations."""
    clear_content(window)
    
    # Main horizontal layout for filters (left) and table (right)
    main_h_layout = QHBoxLayout()
    
    # Filter panel (LEFT SIDE)
    employees = get_employees_from_labor_db()
    filter_frame, filter_table, filter_layout, filter_btn, reset_btn = create_filter_panel(window, 3)
    
    from_date = BlankDateEdit()
    add_filter_row(filter_table, 0, "Data od:", from_date)
    
    until_date = BlankDateEdit()
    add_filter_row(filter_table, 1, "Data do:", until_date)
    
    employee_combo = QComboBox()
    employee_combo.addItems([""] + employees)
    employee_combo.setEditable(True)
    add_filter_row(filter_table, 2, "Pracownik:", employee_combo, widget_height=27)
    
    # Add labor button
    add_labor_btn = QPushButton("Dodaj robociznę")
    filter_layout.addWidget(add_labor_btn)
    
    # Add employee button
    add_employee_btn = QPushButton("Dodaj pracownika")
    filter_layout.addWidget(add_employee_btn)
    
    # Edit employee button
    edit_employee_btn = QPushButton("Edytuj pracownika")
    filter_layout.addWidget(edit_employee_btn)
    
    filter_layout.addStretch()
    
    main_h_layout.addWidget(filter_frame, 0, Qt.AlignmentFlag.AlignTop)
    
    # Right side layout (RIGHT SIDE) - containing table
    right_layout = QVBoxLayout()
    
    # Table (RIGHT SIDE)
    columns = ["Data", "Projekt", "Pracownik", "Godziny", "Stawka", "Suma"]
    table = create_table_with_scrollbar(window, columns, True, "labor_list")
    
    # Enable context menu
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    
    # Initialize sort attributes
    table.sort_column = -1
    table.sort_ascending = True
    
    # Make headers clickable for sorting
    header = table.horizontalHeader()
    header.sectionClicked.connect(lambda col: sort_table_by_column(table, col, numeric_columns=[3, 4, 5], table_name="labor_list"))
    
    right_layout.addWidget(table)
    main_h_layout.addLayout(right_layout, 1)
    
    # Add the main horizontal layout to content
    window.content_layout.addLayout(main_h_layout)
    
    items = get_labor_from_db()
    populate_table(table, items, _format_labor_row, numeric_columns=[3, 4, 5])
    
    # Apply saved sort preference after table is populated
    apply_saved_sort(table, "labor_list", numeric_columns=[3, 4, 5])
    
    def filter_action():
        filtered = [
            item for item in items
            if (not employee_combo.currentText() or item.get("person_name", "") == employee_combo.currentText())
            and (item_date := parse_date(item.get("work_date", ""), "%d-%m-%Y")) is not None
            and is_date_in_range(item_date, from_date, until_date)
        ]
        populate_table(table, filtered, _format_labor_row, numeric_columns=[3, 4, 5])
    
    def add_labor_dialog():
        """Show dialog to add new labor entry."""
        dialog = QDialog(window)
        dialog.setWindowTitle("Dodaj robociznę")
        dialog.setGeometry(100, 100, 530, 247)
        
        layout = QVBoxLayout(dialog)
        
        # Create table for inputs
        input_table = create_input_table(6)
        
        # Row 0: Date
        date_input = BlankDateEdit()
        date_input.setDate(get_latest_labor_date())
        add_input_row(input_table, 0, "Data:", date_input)
        
        # Row 1: Project
        projects = get_projects_from_db()
        project_combo = QComboBox()
        project_combo.addItem("", None)
        for proj in projects:
            project_combo.addItem(proj['project_code'], proj['id'])
        add_input_row(input_table, 1, "Projekt:", project_combo)
        
        # Row 2: Employee
        labor_employee_combo = QComboBox()
        fresh_employees = get_employees_from_labor_db()
        labor_employee_combo.addItem("")
        labor_employee_combo.addItems(fresh_employees)
        labor_employee_combo.setEditable(True)
        add_input_row(input_table, 2, "Pracownik:", labor_employee_combo)
        
        # Row 3: Hours
        hours_input = QLineEdit()
        add_input_row(input_table, 3, "Godziny:", hours_input)
        
        # Row 4: Rate
        rate_input = QLineEdit()
        add_input_row(input_table, 4, "Stawka:", rate_input)
        
        # Function to update rate display when employee changes
        def on_employee_changed():
            selected_employee = labor_employee_combo.currentText().strip()
            if selected_employee:
                hourly_rate = get_hourly_rate_for_employee(selected_employee)
                if hourly_rate > 0:
                    rate_input.setText(f"{hourly_rate:.2f}".replace('.', ','))
        
        # Connect employee selection change
        labor_employee_combo.currentTextChanged.connect(on_employee_changed)
        
        # Row 5: Buttons
        ok_btn = QPushButton("Zapisz")
        ok_btn.setDefault(True)
        add_button_row(input_table, 5, ok_btn)
        
        layout.addWidget(input_table)
        dialog.setLayout(layout)
        
        def save_labor():
            try:
                work_date = date_input.date().toString("dd-MM-yyyy")
                project_id = project_combo.currentData()
                employee_name = labor_employee_combo.currentText().strip()
                hours_str = hours_input.text().strip().replace(',', '.')
                hours_worked = float(hours_str) if hours_str else 0
                rate_str = rate_input.text().strip().replace(',', '.')
                hourly_rate = float(rate_str) if rate_str else 0
                
                if not employee_name:
                    QMessageBox.warning(dialog, "Błąd", "Wybierz pracownika.")
                    return
                
                if project_id is None:
                    QMessageBox.warning(dialog, "Błąd", "Wybierz projekt.")
                    return
                
                if hours_worked <= 0:
                    QMessageBox.warning(dialog, "Błąd", "Godziny muszą być większe od 0.")
                    return
                
                if hourly_rate <= 0:
                    QMessageBox.warning(dialog, "Błąd", "Stawka musi być większa od 0.")
                    return
                
                # Get employee ID
                employee_id = get_employee_id_by_name(employee_name)
                if employee_id is None:
                    QMessageBox.warning(dialog, "Błąd", f"Pracownik '{employee_name}' nie znaleziony.")
                    return
                
                total_cost = hours_worked * hourly_rate
                
                # Insert into database
                db_execute("""
                    INSERT INTO labor (project_id, employee_id, work_date, hours_worked, hourly_rate, total_cost)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (project_id, employee_id, work_date, hours_worked, hourly_rate, total_cost))
                
                # Refresh table
                items.clear()
                items.extend(get_labor_from_db())
                reset_action()
                
                # Close dialog only after successful save
                dialog.accept()
                
            except ValueError:
                QMessageBox.warning(dialog, "Błąd", "Niepoprawny format godzin.")
        
        ok_btn.clicked.connect(save_labor)
        
        dialog.exec()
    
    def reset_action():
        from_date.setDate(QDate())
        until_date.setDate(QDate())
        employee_combo.setCurrentIndex(0)
        populate_table(table, items, _format_labor_row, numeric_columns=[3, 4, 5])
        apply_saved_sort(table, "labor_list", numeric_columns=[3, 4, 5])
    
    def employee_dialog(employee_name=None):
        """Show dialog to add or edit employee."""
        edit_mode = employee_name is not None
        
        dialog = QDialog(window)
        dialog.setWindowTitle("Edytuj pracownika" if edit_mode else "Dodaj pracownika")
        dialog.setGeometry(100, 100, 530, 143)
        
        layout = QVBoxLayout(dialog)
        
        # Create table for inputs
        input_table = create_input_table(3)
        
        # Row 0: Employee name / selector
        if edit_mode:
            name_widget = QComboBox()
            all_employees = get_employees_from_labor_db()
            name_widget.addItems(all_employees)
            if employee_name in all_employees:
                name_widget.setCurrentText(employee_name)
        else:
            name_widget = QLineEdit()
        add_input_row(input_table, 0, "Pracownik:", name_widget)
        
        # Row 1: Hourly rate
        rate_input = QLineEdit()
        add_input_row(input_table, 1, "Stawka:", rate_input)
        
        if edit_mode:
            def on_employee_changed():
                selected = name_widget.currentText().strip()
                if selected:
                    rate = get_hourly_rate_for_employee(selected)
                    if rate > 0:
                        rate_input.setText(f"{rate:.2f}".replace('.', ','))
            name_widget.currentTextChanged.connect(on_employee_changed)
            on_employee_changed()
        
        # Row 2: Buttons
        ok_btn = QPushButton("Zapisz")
        add_button_row(input_table, 2, ok_btn)
        
        layout.addWidget(input_table)
        dialog.setLayout(layout)
        
        ok_btn.clicked.connect(dialog.accept)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                emp_name = (name_widget.currentText() if edit_mode else name_widget.text()).strip()
                rate_str = rate_input.text().strip().replace(',', '.')
                hourly_rate = float(rate_str) if rate_str else 0
                
                if not emp_name:
                    QMessageBox.warning(window, "Błąd", "Wpisz nazwę pracownika." if not edit_mode else "Wybierz pracownika.")
                    return
                
                if hourly_rate <= 0:
                    QMessageBox.warning(window, "Błąd", "Stawka musi być większa od 0.")
                    return
                
                if edit_mode:
                    db_execute("UPDATE employees SET hourly_rate = ? WHERE name = ?", (hourly_rate, emp_name))
                    QMessageBox.information(window, "Sukces", f"Pracownik '{emp_name}' zaktualizowany. Nowa stawka: {hourly_rate:.2f}")
                    items.clear()
                    items.extend(get_labor_from_db())
                    reset_action()
                else:
                    today = QDate.currentDate().toString("dd-MM-yyyy")
                    db_execute("""
                        INSERT INTO employees (name, hourly_rate, hire_date, status)
                        VALUES (?, ?, ?, 'active')
                    """, (emp_name, hourly_rate, today))
                    QMessageBox.information(window, "Sukces", f"Pracownik '{emp_name}' dodany z stawką {hourly_rate:.2f}")
                    fresh = get_employees_from_labor_db()
                    employee_combo.clear()
                    employee_combo.addItems([""] + fresh)
                
            except ValueError:
                QMessageBox.warning(window, "Błąd", "Niepoprawna stawka.")
            except sqlite3.IntegrityError:
                QMessageBox.warning(window, "Błąd", f"Pracownik '{emp_name}' już istnieje.")
    
    def delete_labor_record(row):
        """Delete labor record from database."""
        if row < 0 or row >= len(items):
            return
        
        labor_item = items[row]
        labor_id = labor_item.get('id')
        
        if not labor_id:
            QMessageBox.warning(window, "Błąd", "Nie można usunąć rekordu.")
            return
        
        if confirm_dialog(window, "Potwierdzenie", f"Usunąć robociznę: {labor_item.get('person_name', '')} ({labor_item.get('hours_worked', 0)} h)?"):
            db_execute("DELETE FROM labor WHERE id = ?", (labor_id,))
            
            # Remove from items list and refresh
            items.pop(row)
            reset_action()
    
    def edit_labor_record(row):
        """Edit labor record."""
        if row < 0 or row >= len(items):
            return
        
        labor_item = items[row]
        labor_id = labor_item.get('id')
        
        if not labor_id:
            QMessageBox.warning(window, "Błąd", "Nie można edytować rekordu.")
            return
        
        dialog = QDialog(window)
        dialog.setWindowTitle("Edytuj robociznę")
        dialog.setGeometry(100, 100, 530, 247)
        
        layout = QVBoxLayout(dialog)
        
        # Create table for inputs
        input_table = create_input_table(6)
        
        # Row 0: Date
        date_input = BlankDateEdit()
        work_date = labor_item.get('work_date', '')
        if work_date:
            parts = work_date.split('-')
            if len(parts) == 3:
                date_input.setDate(QDate(int(parts[2]), int(parts[1]), int(parts[0])))
        add_input_row(input_table, 0, "Data:", date_input)
        
        # Row 1: Project
        projects = get_projects_from_db()
        project_combo = QComboBox()
        project_combo.addItem("", None)
        current_project_id = labor_item.get('project_id')
        for proj in projects:
            project_combo.addItem(proj['project_code'], proj['id'])
            if proj['id'] == current_project_id:
                project_combo.setCurrentIndex(project_combo.count() - 1)
        add_input_row(input_table, 1, "Projekt:", project_combo)
        
        # Row 2: Employee (read-only)
        employee_label = QLineEdit()
        employee_label.setText(labor_item.get('person_name', ''))
        employee_label.setReadOnly(True)
        add_input_row(input_table, 2, "Pracownik:", employee_label)
        
        # Row 3: Hours
        hours_input = QLineEdit()
        hours_input.setText(f"{labor_item.get('hours_worked', 0):.2f}".replace('.', ','))
        add_input_row(input_table, 3, "Godziny:", hours_input)
        
        # Row 4: Rate
        rate_input = QLineEdit()
        rate_input.setText(f"{labor_item.get('hourly_rate', 0):.2f}".replace('.', ','))
        add_input_row(input_table, 4, "Stawka:", rate_input)
        
        # Row 5: Buttons
        ok_btn = QPushButton("Zapisz")
        ok_btn.setDefault(True)
        add_button_row(input_table, 5, ok_btn)
        
        layout.addWidget(input_table)
        dialog.setLayout(layout)
        
        ok_btn.clicked.connect(dialog.accept)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                work_date = date_input.date().toString("dd-MM-yyyy")
                project_id = project_combo.currentData()
                hours_str = hours_input.text().strip().replace(',', '.')
                hours_worked = float(hours_str) if hours_str else 0
                rate_str = rate_input.text().strip().replace(',', '.')
                hourly_rate = float(rate_str) if rate_str else 0
                
                if hours_worked <= 0:
                    QMessageBox.warning(window, "Błąd", "Godziny muszą być większe od 0.")
                    return
                
                if hourly_rate <= 0:
                    QMessageBox.warning(window, "Błąd", "Stawka musi być większa od 0.")
                    return
                
                # Calculate total cost based on edited values
                total_cost = hours_worked * hourly_rate
                
                # Update in database
                db_execute("""
                    UPDATE labor SET work_date = ?, project_id = ?, hours_worked = ?, hourly_rate = ?, total_cost = ?
                    WHERE id = ?
                """, (work_date, project_id, hours_worked, hourly_rate, total_cost, labor_id))
                
                # Refresh table
                items.clear()
                items.extend(get_labor_from_db())
                reset_action()
                
                QMessageBox.information(window, "Sukces", "Robocizna zaktualizowana.")
                
            except ValueError:
                QMessageBox.warning(window, "Błąd", "Niepoprawny format danych.")
    
    def show_context_menu(position):
        """Show context menu for labor table."""
        from PyQt6.QtWidgets import QMenu, QApplication
        menu = QMenu()
        
        row = table.rowAt(position.y())
        if row < 0:
            return
        
        # Edit option
        edit_action = menu.addAction("Edytuj")
        edit_action.triggered.connect(lambda: edit_labor_record(row))
        
        # Copy option
        copy_action = menu.addAction("Kopiuj")
        copy_action.triggered.connect(lambda: copy_table_row_to_clipboard(table, row))
        
        # Delete option
        delete_action = menu.addAction("Usuń")
        delete_action.triggered.connect(lambda: delete_labor_record(row))
        
        menu.exec(table.mapToGlobal(position))
    
    table.customContextMenuRequested.connect(show_context_menu)
    
    filter_btn.clicked.connect(filter_action)
    reset_btn.clicked.connect(reset_action)
    add_labor_btn.clicked.connect(add_labor_dialog)
    add_employee_btn.clicked.connect(lambda: employee_dialog())
    edit_employee_btn.clicked.connect(lambda: employee_dialog(""))
