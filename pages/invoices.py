"""Invoices view — invoice list, XML import, KSeF download, item assignment."""
import sqlite3
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QComboBox, QTableWidget, QTableWidgetItem, 
                             QFrame, QDialog, QMessageBox, QMenu, QAbstractItemView, QLineEdit,
                             QApplication, QProgressDialog)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal
import config
from helpers import (clear_content, create_table_with_scrollbar, add_row_to_table, sort_table_by_column,
                     parse_date, BlankDateEdit, split_row, delete_row, apply_saved_sort,
                     create_filter_panel, add_filter_row, create_details_table, copy_table_row_to_clipboard,
                     is_date_in_range, populate_table, db_fetch_all, db_fetch_column, db_fetch_scalar, db_fetch_one, db_execute)
from . import projects


def convert_date_to_standard(date_str):
    """Convert date from YYYY-MM-DD (XML format) to DD-MM-YYYY format."""
    if not date_str or date_str == "":
        return ""
    try:
        # Try to parse as YYYY-MM-DD
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        # Convert to DD-MM-YYYY
        return date_obj.strftime("%d-%m-%Y")
    except (ValueError, TypeError):
        # If already in correct format or unparseable, return as-is
        return date_str


def get_payment_type_name(forma_platnosci_code):
    """Convert FormaPlatnosci code to payment type name.
    1 = Gotówka (Cash)
    2 = Karta płatnicza (Credit Card)
    6 = Przelew (Transfer)
    """
    payment_types = {
        '1': 'Gotówka',
        '2': 'Karta płatnicza',
        '6': 'Przelew'
    }
    return payment_types.get(str(forma_platnosci_code), '')


def get_invoice_type_name(rodzaj_faktury_code):
    """Convert RodzajFaktury code to invoice type name.
    KOR = Korekta (Correction)
    VAT = Zakup (Purchase)
    """
    invoice_types = {
        'KOR': 'Korekta',
        'VAT': 'Zakup'
    }
    return invoice_types.get(str(rodzaj_faktury_code), rodzaj_faktury_code)


def get_invoices_from_db():
    """Get all invoices from database, excluding manually added ones (MAN-*)."""
    return db_fetch_all("SELECT * FROM invoices WHERE invoice_number NOT LIKE 'MAN-%' ORDER BY invoice_date DESC")


def get_invoice_assignments_description(invoice_id):
    """Get description of assignments for an invoice.
    Returns comma-separated list of project codes, 'M' for warehouse, and 'KF' for company cost."""
    assignments = []
    
    project_codes = db_fetch_column("""
        SELECT DISTINCT p.project_code FROM projects p
        JOIN project_assignments pa ON p.id = pa.project_id
        JOIN invoice_items ii ON pa.invoice_item_id = ii.id
        WHERE ii.invoice_id = ?
        ORDER BY p.project_code
    """, (invoice_id,))
    assignments.extend(project_codes)
    
    if db_fetch_scalar("""
        SELECT COUNT(*) FROM warehouse_assignments wa
        JOIN invoice_items ii ON wa.invoice_item_id = ii.id
        WHERE ii.invoice_id = ?
    """, (invoice_id,)) > 0:
        assignments.append("M")
    
    if db_fetch_scalar("""
        SELECT COUNT(*) FROM company_cost_assignments cca
        JOIN invoice_items ii ON cca.invoice_item_id = ii.id
        WHERE ii.invoice_id = ?
    """, (invoice_id,)) > 0:
        assignments.append("KF")
    
    return ", ".join(assignments) if assignments else ""


def get_companies_from_db():
    """Get all unique company names from database, excluding manually added invoices (MAN-*)."""
    return db_fetch_column("SELECT DISTINCT seller_name FROM invoices WHERE invoice_number NOT LIKE 'MAN-%' ORDER BY seller_name")


def get_invoice_description_status(invoice_id):
    """Get invoice description status by comparing assigned vs total quantities.
    Accounts for partial assignments after splitting items."""
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    
    # Get all items with their quantities
    c.execute("""
        SELECT id, quantity FROM invoice_items WHERE invoice_id = ?
    """, (invoice_id,))
    items = c.fetchall()
    
    if not items:
        conn.close()
        return "Nie opisane"
    
    fully_assigned = 0
    partially_assigned = 0
    not_assigned = 0
    
    for item_id, original_qty in items:
        # Get total assigned quantity from warehouse
        c.execute("SELECT COALESCE(SUM(quantity_assigned), 0) FROM warehouse_assignments WHERE invoice_item_id = ?", (item_id,))
        warehouse_qty = c.fetchone()[0]
        
        # Get total assigned quantity from projects
        c.execute("SELECT COALESCE(SUM(quantity_assigned), 0) FROM project_assignments WHERE invoice_item_id = ?", (item_id,))
        project_qty = c.fetchone()[0]
        
        # Get total assigned quantity from company costs
        c.execute("SELECT COALESCE(SUM(quantity_assigned), 0) FROM company_cost_assignments WHERE invoice_item_id = ?", (item_id,))
        company_cost_qty = c.fetchone()[0]
        
        total_assigned = warehouse_qty + project_qty + company_cost_qty
        
        if total_assigned == 0:
            not_assigned += 1
        elif abs(total_assigned - original_qty) < 0.001:  # Fully assigned (within rounding tolerance)
            fully_assigned += 1
        else:  # Partially assigned
            partially_assigned += 1
    
    conn.close()
    
    total_items = len(items)
    
    if not_assigned == total_items:
        return "Nie opisane"
    elif partially_assigned > 0 or (fully_assigned > 0 and not_assigned > 0):
        return "Opisane częściowo"
    elif fully_assigned == total_items:
        return "Opisane w całości"
    else:
        return "Opisane częściowo"


def get_invoice_details_from_db(invoice_number):
    """Get invoice details including line items and their assignments."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM invoices WHERE invoice_number = ?", (invoice_number,))
    invoice = c.fetchone()
    
    if not invoice:
        conn.close()
        return None
    
    invoice_id = invoice['id']
    
    # Get unassigned items (not in any assignment table)
    c.execute("""
        SELECT ii.* FROM invoice_items ii
        WHERE ii.invoice_id = ?
        AND ii.id NOT IN (SELECT invoice_item_id FROM warehouse_assignments)
        AND ii.id NOT IN (SELECT invoice_item_id FROM project_assignments)
        AND ii.id NOT IN (SELECT invoice_item_id FROM company_cost_assignments)
    """, (invoice_id,))
    invoice_items = [dict(row) for row in c.fetchall()]
    
    # Get warehouse assigned items (with original quantity for detecting splits)
    c.execute("""
        SELECT ii.id, ii.invoice_id, ii.item_description, ii.quantity as original_quantity,
               wa.quantity_assigned as quantity, ii.unit_price, wa.id as assignment_id FROM invoice_items ii
        JOIN warehouse_assignments wa ON ii.id = wa.invoice_item_id
        WHERE ii.invoice_id = ?
    """, (invoice_id,))
    warehouse_items = [dict(row) for row in c.fetchall()]
    
    # Get project assigned items (with original quantity for detecting splits)
    c.execute("""
        SELECT ii.id, ii.invoice_id, ii.item_description, ii.quantity as original_quantity,
               pa.quantity_assigned as quantity, ii.unit_price, pa.project_id, pa.id as assignment_id,
               p.project_code FROM invoice_items ii
        JOIN project_assignments pa ON ii.id = pa.invoice_item_id
        JOIN projects p ON pa.project_id = p.id
        WHERE ii.invoice_id = ?
    """, (invoice_id,))
    project_items = [dict(row) for row in c.fetchall()]
    
    # Get company cost assigned items (with original quantity for detecting splits)
    c.execute("""
        SELECT ii.id, ii.invoice_id, ii.item_description, ii.quantity as original_quantity,
               cca.quantity_assigned as quantity, ii.unit_price, cca.id as assignment_id FROM invoice_items ii
        JOIN company_cost_assignments cca ON ii.id = cca.invoice_item_id
        WHERE ii.invoice_id = ?
    """, (invoice_id,))
    company_cost_items = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    return {
        "invoice": dict(invoice),
        "invoice_items": invoice_items,
        "warehouse_items": warehouse_items,
        "project_items": project_items,
        "company_cost_items": company_cost_items
    }


def _format_invoice_row(invoice):
    """Format an invoice dict into a row of strings for the table."""
    return [
        invoice["seller_name"],
        invoice["seller_nip"],
        invoice["invoice_number"],
        get_invoice_type_name(invoice.get("invoice_type", "")),
        invoice["invoice_date"],
        invoice.get("due_date", ""),
        get_payment_type_name(invoice.get("payment_type", "")),
        f"{invoice['total_netto']:.2f}".replace('.', ','),
        f"{invoice['total_vat']:.2f}".replace('.', ','),
        f"{invoice['total_brutto']:.2f}".replace('.', ','),
        get_invoice_description_status(invoice["id"]),
        get_invoice_assignments_description(invoice["id"])
    ]


def show_invoices(window, status_filter=None, payment_filter=None):
    """Display invoices from DB in a sortable table.
    
    Args:
        window: Main window
        status_filter: Optional status to auto-filter ("Opisane w całości", "Opisane częściowo", "Nie opisane")
        payment_filter: Optional payment filter ("unpaid" for all unpaid, "unpaid_close" for unpaid with due date < 7 days)
    """
    clear_content(window)
    
    # Main horizontal layout for filters (left) and table (right)
    main_h_layout = QHBoxLayout()
    
    # Filter panel (LEFT SIDE)
    companies = get_companies_from_db()
    filter_frame, filter_table, filter_layout, filter_btn, reset_btn = create_filter_panel(window, 5, height=450)
    
    # Get unique invoice types from database
    def get_invoice_types_from_db():
        return [get_invoice_type_name(t) for t in db_fetch_column(
            "SELECT DISTINCT invoice_type FROM invoices WHERE invoice_type IS NOT NULL AND invoice_type != '' ORDER BY invoice_type"
        )]
    
    from_date = BlankDateEdit()
    current_year = datetime.now().year
    from_date.setDate(QDate(current_year, 1, 1))
    add_filter_row(filter_table, 0, "Data od:", from_date)
    
    until_date = BlankDateEdit()
    until_date.setDate(QDate(current_year, 12, 31))
    add_filter_row(filter_table, 1, "Data do:", until_date)
    
    company_combo = QComboBox()
    company_combo.addItems([""] + companies)
    company_combo.setEditable(True)
    add_filter_row(filter_table, 2, "Firma:", company_combo, widget_height=27)
    
    invoice_type_combo = QComboBox()
    invoice_types = get_invoice_types_from_db()
    invoice_type_combo.addItems([""] + invoice_types)
    add_filter_row(filter_table, 3, "Typ:", invoice_type_combo, widget_height=27)
    
    opis_combo = QComboBox()
    opis_combo.addItems(["", "Opisane w całości", "Opisane częściowo", "Nie opisane"])
    add_filter_row(filter_table, 4, "Status:", opis_combo, widget_height=27)
    
    # Import button
    import_btn = QPushButton("Importuj faktury")
    filter_layout.addWidget(import_btn)
    
    filter_layout.addStretch()
    
    main_h_layout.addWidget(filter_frame, 0, Qt.AlignmentFlag.AlignTop)
    
    # Right side layout (RIGHT SIDE) - containing title and table
    right_layout = QVBoxLayout()
    
    # Table (RIGHT SIDE)
    columns = ["Nazwa firmy", "NIP", "Numer faktury", "Typ", "Data faktury", "Data płatności", "Rodzaj płatności", "Netto", "VAT", "Brutto", "Status", "Opis"]
    table = create_table_with_scrollbar(window, columns, True, "invoices_list")
    
    # Custom context menu for invoices list
    def show_invoices_context_menu(pos):
        index = table.indexAt(pos)
        if index.row() < 0:
            return
        menu = QMenu()
        
        # Open action
        open_action = menu.addAction("Otwórz")
        open_action.triggered.connect(lambda: open_invoice_details_dialog(window, table, index))
        
        # Copy action
        copy_action = menu.addAction("Kopiuj")
        copy_action.triggered.connect(lambda: copy_table_row_to_clipboard(table, index.row()))
        
        menu.exec(table.mapToGlobal(pos))
    
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show_invoices_context_menu)
    
    # Initialize sort attributes
    table.sort_column = -1
    table.sort_ascending = True
    
    # Make headers clickable for sorting
    header = table.horizontalHeader()
    header.sectionClicked.connect(lambda col: sort_table_by_column(table, col, numeric_columns=[7, 8, 9], table_name="invoices_list"))
    
    right_layout.addWidget(table)
    main_h_layout.addLayout(right_layout)
    
    # Add the main horizontal layout to content
    window.content_layout.addLayout(main_h_layout)
    
    # Populate table
    invoices = get_invoices_from_db()
    populate_table(table, invoices, _format_invoice_row, numeric_columns=[7, 8, 9])
    
    # Connect double-click to details
    table.doubleClicked.connect(lambda index: open_invoice_details_dialog(window, table, index))
    
    # Connect filter button
    def filter_invoices_action():
        filtered = []
        for invoice in invoices:
            if company_combo.currentText() and invoice["seller_name"] != company_combo.currentText():
                continue
            inv_date = parse_date(invoice["invoice_date"], "%d-%m-%Y")
            if inv_date is None:
                continue
            if not is_date_in_range(inv_date, from_date, until_date):
                continue
            if invoice_type_combo.currentText():
                if get_invoice_type_name(invoice.get("invoice_type", "")) != invoice_type_combo.currentText():
                    continue
            if opis_combo.currentText():
                if get_invoice_description_status(invoice["id"]) != opis_combo.currentText():
                    continue
            if payment_filter:
                is_paid = db_fetch_one("SELECT id FROM payments WHERE invoice_id = ? AND payment_date IS NOT NULL", (invoice["id"],)) is not None
                if payment_filter == "unpaid" and is_paid:
                    continue
                elif payment_filter == "unpaid_close":
                    if is_paid:
                        continue
                    due_date_str = invoice.get("due_date", "")
                    if not due_date_str:
                        continue
                    try:
                        due_date = datetime.strptime(due_date_str, "%d-%m-%Y")
                        days_until_due = (due_date - datetime.now()).days
                        if not (0 <= days_until_due < 7):
                            continue
                    except (ValueError, TypeError):
                        continue
            filtered.append(invoice)
        populate_table(table, filtered, _format_invoice_row, numeric_columns=[7, 8, 9])
    
    def reset_filters_action():
        from_date.setDate(QDate())
        until_date.setDate(QDate())
        company_combo.setCurrentIndex(0)
        invoice_type_combo.setCurrentIndex(0)
        opis_combo.setCurrentIndex(0)
        populate_table(table, invoices, _format_invoice_row, numeric_columns=[7, 8, 9])
    
    filter_btn.clicked.connect(filter_invoices_action)
    reset_btn.clicked.connect(reset_filters_action)
    import_btn.clicked.connect(lambda: import_invoices(window))
    
    # Apply filter based on parameters
    if payment_filter:
        filter_invoices_action()
    elif status_filter:
        opis_combo.setCurrentText(status_filter)
        filter_invoices_action()
    else:
        filter_invoices_action()
    
    # Apply saved sort preference AFTER filtering is done
    apply_saved_sort(table, "invoices_list", numeric_columns=[7, 8, 9])


def open_invoice_details_dialog(window, table, index):
    """Open invoice details when table cell is clicked."""
    if index.row() >= 0:
        invoice_number = table.item(index.row(), 2).text()
        show_invoice_details(window, invoice_number)


def show_invoice_details(window, invoice_number):
    """Show invoice details with items from database."""
    clear_content(window)
    
    # Get invoice and items from database
    invoice_data = get_invoice_details_from_db(invoice_number)
    
    if not invoice_data:
        error_label = QLabel("Faktura nie znaleziona")
        window.content_layout.addWidget(error_label)
        return
    
    invoice = invoice_data["invoice"]
    invoice_items = invoice_data["invoice_items"]
    warehouse_items = invoice_data.get("warehouse_items", [])
    project_items = invoice_data.get("project_items", [])
    company_cost_items = invoice_data.get("company_cost_items", [])
    
    # Main horizontal layout
    main_h_layout = QHBoxLayout()
    
    # LEFT SIDE - Invoice Details Frame
    details_frame = QFrame(window)
    details_frame.setMaximumWidth(275)
    details_layout = QVBoxLayout(details_frame)
    details_layout.setContentsMargins(10, 10, 10, 10)
    
    # Details table - 2 columns (label, value) with all main list info
    detail_items = [
        ("Nazwa firmy:", invoice['seller_name']),
        ("NIP:", invoice['seller_nip']),
        ("Numer faktury:", invoice['invoice_number']),
        ("Typ:", get_invoice_type_name(invoice.get('invoice_type', ''))),
        ("Data faktury:", invoice['invoice_date']),
        ("Data płatności:", invoice.get('due_date', '')),
        ("Rodzaj płatności:", get_payment_type_name(invoice.get('payment_type', ''))),
        ("Netto:", f"{invoice['total_netto']:.2f}".replace('.', ',')),
        ("VAT:", f"{invoice['total_vat']:.2f}".replace('.', ',')),
        ("Brutto:", f"{invoice['total_brutto']:.2f}".replace('.', ','))
    ]
    
    details_table = create_details_table(detail_items, row_height=35)
    
    details_layout.addWidget(details_table)
    
    # Buttons layout
    buttons_layout = QVBoxLayout()
    
    # Back button
    back_btn = QPushButton("Powrót do listy faktur")
    back_btn.clicked.connect(lambda: show_invoices(window))
    back_btn.setFixedHeight(27)
    buttons_layout.addWidget(back_btn)
    
    # Save button
    save_btn = QPushButton("Zapisz zmiany")
    
    def save_invoice_changes():
        """Save all assigned items to appropriate assignment tables."""
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        c = conn.cursor()
        
        saved_count = 0
        deleted_count = 0
        rows_processed = 0
        skipped_count = 0
        
        # Helper to insert/update assignment in a table
        def save_assignment(table, item_id, qty, project_id=None):
            if qty <= 0:
                return False
            
            if table == 'warehouse_assignments':
                c.execute("SELECT id FROM warehouse_assignments WHERE invoice_item_id = ?", (item_id,))
                if c.fetchone():
                    c.execute("UPDATE warehouse_assignments SET quantity_assigned = ? WHERE invoice_item_id = ?", (qty, item_id))
                else:
                    c.execute("INSERT INTO warehouse_assignments (invoice_item_id, quantity_assigned) VALUES (?, ?)", (item_id, qty))
            
            elif table == 'company_cost_assignments':
                c.execute("SELECT id FROM company_cost_assignments WHERE invoice_item_id = ?", (item_id,))
                if c.fetchone():
                    c.execute("UPDATE company_cost_assignments SET quantity_assigned = ? WHERE invoice_item_id = ?", (qty, item_id))
                else:
                    c.execute("INSERT INTO company_cost_assignments (invoice_item_id, quantity_assigned) VALUES (?, ?)", (item_id, qty))
            
            elif table == 'project_assignments' and project_id:
                c.execute("SELECT id FROM project_assignments WHERE invoice_item_id = ?", (item_id,))
                if c.fetchone():
                    c.execute("UPDATE project_assignments SET quantity_assigned = ?, project_id = ? WHERE invoice_item_id = ?", (qty, project_id, item_id))
                else:
                    c.execute("INSERT INTO project_assignments (invoice_item_id, project_id, quantity_assigned) VALUES (?, ?, ?)", (item_id, project_id, qty))
            
            return True
        
        try:
            # Pass 1: Find split items AND items being reassigned
            item_row_count = {}
            previously_assigned_items = set()  # Items with metadata (loaded from assignment tables)
            
            for row in range(items_table.rowCount()):
                col0 = items_table.item(row, 0)
                if not col0:
                    continue
                metadata = col0.data(Qt.ItemDataRole.UserRole)
                if metadata:
                    item_id = metadata.get('invoice_item_id')
                    # Always add to previously_assigned_items for deletion (even if no current assignment)
                    previously_assigned_items.add(item_id)
                    # Count only rows with current assignments for split detection
                    if any(items_table.item(row, c).text().strip() 
                           for c in [5, 6, 7] if items_table.item(row, c)):
                        item_row_count[item_id] = item_row_count.get(item_id, 0) + 1
            
            # Delete all assignments for split items AND reassigned items
            items_to_delete = {iid for iid, cnt in item_row_count.items() if cnt > 1}
            items_to_delete.update(previously_assigned_items)  # Add previously assigned items
            
            for item_id in items_to_delete:
                c.execute("DELETE FROM warehouse_assignments WHERE invoice_item_id = ?", (item_id,))
                c.execute("DELETE FROM company_cost_assignments WHERE invoice_item_id = ?", (item_id,))
                c.execute("DELETE FROM project_assignments WHERE invoice_item_id = ?", (item_id,))
            
            deleted_count = len(items_to_delete)
            
            # Pass 2: Group rows by item and extract assignments
            item_assignments = {}
            
            for row in range(items_table.rowCount()):
                col0 = items_table.item(row, 0)
                col1 = items_table.item(row, 1)
                col2 = items_table.item(row, 2)
                col5 = items_table.item(row, 5)
                col6 = items_table.item(row, 6)
                col7 = items_table.item(row, 7)
                
                if not all([col0, col1, col2]):
                    continue
                
                # Check if this is a remainder row (virtual unassigned portion of split item)
                metadata = col0.data(Qt.ItemDataRole.UserRole)
                if metadata and metadata.get('is_remainder'):
                    rows_processed += 1
                    skipped_count += 1
                    continue
                
                try:
                    qty = float(col1.text().replace(',', '.')) if col1.text() else 0
                    unit_price = float(col2.text().replace(',', '.')) if col2.text() else 0
                except:
                    continue
                
                project_code = col5.text().strip() if col5 else ""
                warehouse_mark = col6.text().strip() if col6 else ""
                company_cost_mark = col7.text().strip() if col7 else ""
                
                assignment_count = sum([bool(project_code), warehouse_mark == "✓", company_cost_mark == "✓"])
                
                if assignment_count == 0:
                    rows_processed += 1
                    skipped_count += 1
                    continue
                

                # Find invoice_item_id
                if not metadata:
                    c.execute("SELECT ii.id FROM invoice_items ii WHERE ii.invoice_id = ? AND ii.item_description = ? AND ii.unit_price = ?", 
                             (invoice['id'], col0.text(), unit_price))
                    item_row = c.fetchone()
                    if not item_row:
                        rows_processed += 1
                        skipped_count += 1
                        continue
                    invoice_item_id = item_row[0]
                else:
                    invoice_item_id = metadata.get('invoice_item_id')
                
                rows_processed += 1
                # Group assignments
                if invoice_item_id not in item_assignments:
                    item_assignments[invoice_item_id] = {'warehouse': 0, 'company_cost': 0, 'project': None}
                
                if warehouse_mark == "✓":
                    item_assignments[invoice_item_id]['warehouse'] += qty
                elif company_cost_mark == "✓":
                    item_assignments[invoice_item_id]['company_cost'] += qty
                elif project_code:
                    item_assignments[invoice_item_id]['project'] = (project_code, qty)
            
            # Pass 3: Save grouped assignments
            for item_id, assignments in item_assignments.items():
                if assignments['warehouse'] > 0:
                    if save_assignment('warehouse_assignments', item_id, assignments['warehouse']):
                        saved_count += 1
                
                if assignments['company_cost'] > 0:
                    if save_assignment('company_cost_assignments', item_id, assignments['company_cost']):
                        saved_count += 1
                
                if assignments['project']:
                    project_code, qty = assignments['project']
                    c.execute("SELECT id FROM projects WHERE project_code = ?", (project_code,))
                    proj = c.fetchone()
                    if proj and save_assignment('project_assignments', item_id, qty, proj[0]):
                        saved_count += 1
            
            conn.commit()
            conn.close()
            
            if saved_count > 0 or deleted_count > 0:
                show_invoices(window)
        
        except Exception as e:
            conn.close()
            QMessageBox.critical(window, "Błąd", f"Błąd: {str(e)}")
    
    save_btn.clicked.connect(save_invoice_changes)
    save_btn.setFixedHeight(27)
    buttons_layout.addWidget(save_btn)
    
    # Pay button
    def add_to_payments():
        """Add invoice to payments."""
        try:
            # Check if already in payments
            existing = db_fetch_one("SELECT id FROM payments WHERE invoice_id = ?", (invoice['id'],))
            
            if existing:
                QMessageBox.information(window, "Info", "Ta faktura jest już na liście przelewów")
                return
            
            # Add to payments with amount=0 (unpaid by default)
            total_amount = invoice.get('total_brutto', 0)
            db_execute("INSERT INTO payments (invoice_id, amount) VALUES (?, ?)", (invoice['id'], 0))
            
            QMessageBox.information(window, "Sukces", f"Faktura {invoice['invoice_number']} dodana do przelewów\nKwota: {total_amount:.2f} PLN")
            show_invoices(window)
        except Exception as e:
            QMessageBox.critical(window, "Błąd", f"Błąd podczas dodawania do przelewów: {str(e)}")
    
    pay_btn = QPushButton("Dodaj do przelewów")
    pay_btn.clicked.connect(add_to_payments)
    pay_btn.setFixedHeight(27)
    buttons_layout.addWidget(pay_btn)
    
    # Materials button
    def assign_all_to_warehouse():
        """Assign all items to warehouse (override existing assignments)."""
        for row in range(items_table.rowCount()):
            # Clear project column (5)
            project_item = items_table.item(row, 5)
            if project_item:
                project_item.setText("")
            
            # Clear company cost column (7)
            cost_item = items_table.item(row, 7)
            if cost_item:
                cost_item.setText("")
            
            # Assign to warehouse column (6)
            warehouse_item = items_table.item(row, 6)
            if warehouse_item:
                warehouse_item.setText("✓")
    
    materials_btn = QPushButton("Dodaj wszystko do magazynu")
    materials_btn.clicked.connect(assign_all_to_warehouse)
    materials_btn.setFixedHeight(27)
    buttons_layout.addWidget(materials_btn)
    
    # Costs button
    def assign_all_to_company_cost():
        """Assign all items to company cost (override existing assignments)."""
        for row in range(items_table.rowCount()):
            # Clear project column (5)
            project_item = items_table.item(row, 5)
            if project_item:
                project_item.setText("")
            
            # Clear warehouse column (6)
            warehouse_item = items_table.item(row, 6)
            if warehouse_item:
                warehouse_item.setText("")
            
            # Assign to company cost column (7)
            cost_item = items_table.item(row, 7)
            if cost_item:
                cost_item.setText("✓")
    
    costs_btn = QPushButton("Dodaj wszystko do kosztów")
    costs_btn.clicked.connect(assign_all_to_company_cost)
    costs_btn.setFixedHeight(27)
    buttons_layout.addWidget(costs_btn)
    
    # Reset button
    def reset_all_assignments():
        """Clear all assignments (project, warehouse, company cost) for all items."""
        for row in range(items_table.rowCount()):
            # Clear project column (5)
            project_item = items_table.item(row, 5)
            if project_item:
                project_item.setText("")
            
            # Clear warehouse column (6)
            warehouse_item = items_table.item(row, 6)
            if warehouse_item:
                warehouse_item.setText("")
            
            # Clear company cost column (7)
            cost_item = items_table.item(row, 7)
            if cost_item:
                cost_item.setText("")
    
    reset_btn = QPushButton("Reset przypisanych pozycji")
    reset_btn.clicked.connect(reset_all_assignments)
    reset_btn.setFixedHeight(27)
    buttons_layout.addWidget(reset_btn)
    
    buttons_layout.addStretch()
    details_layout.addLayout(buttons_layout)
    main_h_layout.addWidget(details_frame)
    
    # RIGHT SIDE - Items Table
    right_layout = QVBoxLayout()
    
    # Items table
    columns = ["Nazwa pozycji", "Ilość", "Cena jednostkowa", "Netto", "Brutto", "Projekt", "Magazyn", "Koszt firmowy", "Wiersz pierwotny"]
    items_table = create_table_with_scrollbar(window, columns, True, "invoice_items")
    
    # Enable multi-select with Ctrl+click
    items_table.setSelectionMode(items_table.SelectionMode.ExtendedSelection)
    items_table.setSelectionBehavior(items_table.SelectionBehavior.SelectRows)
    
    # Helper function to make assignment columns editable only for unassigned items
    # Helper function to center-align assignment columns
    def center_align_assignment_columns():
        for row in range(items_table.rowCount()):
            for col in [5, 6, 7, 8]:
                item = items_table.item(row, col)
                if item:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
    
    # Helper to tag rows with assignment metadata
    def tag_row_with_assignment(row_num, assignment_type, assignment_id, invoice_item_id):
        """Store assignment metadata in cells of a row."""
        for col in range(9):
            item = items_table.item(row_num, col)
            if item:
                item.setData(Qt.ItemDataRole.UserRole, {
                    'assignment_type': assignment_type,
                    'assignment_id': assignment_id,
                    'invoice_item_id': invoice_item_id
                })
    
    # Calculate total assigned quantity per item across all assignment types
    assigned_qty_per_item = {}
    for item in warehouse_items:
        assigned_qty_per_item[item['id']] = assigned_qty_per_item.get(item['id'], 0) + item.get('quantity', 0)
    for item in project_items:
        assigned_qty_per_item[item['id']] = assigned_qty_per_item.get(item['id'], 0) + item.get('quantity', 0)
    for item in company_cost_items:
        assigned_qty_per_item[item['id']] = assigned_qty_per_item.get(item['id'], 0) + item.get('quantity', 0)
    
    # Helper to populate table with items
    def add_items_to_table(items, assignment_type=None, assignment_marks=None):
        """Add items to table. Calculate netto, vat, and brutto from invoice totals."""
        nonlocal row_num
        
        invoice_netto = invoice['total_netto']
        invoice_vat = invoice['total_vat']
        invoice_brutto = invoice['total_brutto']
        
        for item in items:
            # Calculate netto for this item
            netto = item['unit_price'] * item['quantity']
            
            # Calculate VAT proportionally from invoice VAT
            if invoice_netto > 0:
                item_vat = netto * (invoice_vat / invoice_netto)
            else:
                item_vat = 0
            
            # Brutto = Netto + VAT
            brutto = netto + item_vat
            
            # Replace newlines in description with space for better display
            description = item["item_description"].replace('\n', ' ')
            
            row_data = [
                description,
                f"{item['quantity']:.2f}".replace('.', ','),
                f"{item['unit_price']:.2f}".replace('.', ','),
                f"{netto:.2f}".replace('.', ','),
                f"{brutto:.2f}".replace('.', ','),
                item.get("project_code", "") if assignment_type == 'project' else "",
                "✓" if assignment_type == 'warehouse' else "",
                "✓" if assignment_type == 'company_cost' else "",
                "✓"  # Mark as original row
            ]
            
            add_row_to_table(items_table, row_data, numeric_columns=[1, 2, 3, 4])
            
            # Store VAT amount in metadata for split row calculations
            for col in range(items_table.columnCount()):
                cell_item = items_table.item(row_num, col)
                if cell_item:
                    cell_item.setData(Qt.ItemDataRole.UserRole + 1, item_vat)
            
            if assignment_type:
                tag_row_with_assignment(row_num, assignment_type, item['assignment_id'], item['id'])
            
            row_num += 1
            
            # If this is an assigned item but not fully assigned, also display the remainder as unassigned
            # Only add remainder once per unique item_id (track in processed_item_ids)
            if assignment_type and item.get('original_quantity', 0) > 0:
                if not hasattr(items_table, 'processed_item_ids'):
                    items_table.processed_item_ids = set()
                
                # Only add remainder once per unique item_id
                if item['id'] not in items_table.processed_item_ids:
                    items_table.processed_item_ids.add(item['id'])
                    
                    # Calculate total assigned quantity across ALL assignment types for this item
                    total_assigned = assigned_qty_per_item.get(item['id'], 0)
                    
                    # Check if there's any unassigned remainder
                    if total_assigned < item.get('original_quantity', 0):
                        remainder_qty = item['original_quantity'] - total_assigned
                        remainder_netto = item['unit_price'] * remainder_qty
                        
                        # Calculate VAT proportionally
                        if invoice_netto > 0:
                            remainder_vat = remainder_netto * (invoice_vat / invoice_netto)
                        else:
                            remainder_vat = 0
                        
                        remainder_brutto = remainder_netto + remainder_vat
                        
                        remainder_row_data = [
                            item["item_description"],
                            f"{remainder_qty:.2f}".replace('.', ','),
                            f"{item['unit_price']:.2f}".replace('.', ','),
                            f"{remainder_netto:.2f}".replace('.', ','),
                            f"{remainder_brutto:.2f}".replace('.', ','),
                            "",  # No project
                            "",  # No warehouse
                            "",  # No company cost
                            "✓"  # Mark as original row
                        ]
                        
                        add_row_to_table(items_table, remainder_row_data, numeric_columns=[1, 2, 3, 4])
                        
                        # Mark remainder metadata (not assigned)
                        for col in range(items_table.columnCount()):
                            cell_item = items_table.item(row_num, col)
                            if cell_item:
                                cell_item.setData(Qt.ItemDataRole.UserRole + 1, remainder_vat)
                                # Mark as remainder of an assigned item so we know to skip it on save
                                cell_item.setData(Qt.ItemDataRole.UserRole, {
                                    'is_remainder': True,
                                    'invoice_item_id': item['id']
                                })
                        
                        row_num += 1
    
    # Populate table
    row_num = 0
    add_items_to_table(invoice_items)  # Unassigned (no marks)
    add_items_to_table(warehouse_items, 'warehouse')
    add_items_to_table(project_items, 'project')
    add_items_to_table(company_cost_items, 'company_cost')
    
    # Make assignment columns read-only (no user typing allowed)
    for row in range(items_table.rowCount()):
        for col in [5, 6, 7]:
            item = items_table.item(row, col)
            if item:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    
    # Center-align all assignment columns
    center_align_assignment_columns()
    
    # Set column widths - make description column wider to display full text
    items_table.setColumnWidth(0, 400)  # Nazwa pozycji - wider for full descriptions
    items_table.setColumnWidth(1, 60)   # Ilość
    items_table.setColumnWidth(2, 150)  # Cena jednostkowa
    items_table.setColumnWidth(3, 70)   # Netto
    items_table.setColumnWidth(4, 70)   # Brutto
    items_table.setColumnWidth(5, 100)  # Projekt
    items_table.setColumnWidth(6, 100)  # Magazyn
    items_table.setColumnWidth(7, 100)  # Koszt firmowy
    items_table.setColumnWidth(8, 130)  # Wiersz pierwotny
    
    right_layout.addWidget(items_table)
    main_h_layout.addLayout(right_layout)
    
    # Context menu for splitting rows
    def show_context_menu(position):
        """Show context menu for table row(s). Supports multi-select."""
        index = items_table.indexAt(position)
        if not index.isValid():
            return
        
        # Get all selected rows
        selected_rows = set()
        for item in items_table.selectedItems():
            selected_rows.add(item.row())
        
        # If nothing selected, use the right-clicked row
        if not selected_rows:
            selected_rows.add(index.row())
        
        menu = QMenu(window)
        
        # Only show split/delete options if single row is selected
        if len(selected_rows) == 1:
            split_action = menu.addAction("Podziel rząd")
            delete_action_obj = None  # Will be added later
        else:
            split_action = None
            delete_action_obj = None
        
        # Add submenu for assignment (works for single or multiple rows)
        assign_menu = menu.addMenu("Przypisz do")
        projekt_action = assign_menu.addAction("Projekt")
        magazyn_action = assign_menu.addAction("Magazyn")
        koszt_action = assign_menu.addAction("Koszt firmowy")
        
        # Copy action
        copy_action = menu.addAction("Kopiuj")
        
        # Delete action (moved to end if single row selected)
        if len(selected_rows) == 1:
            delete_action = menu.addAction("Usuń rząd")
        else:
            delete_action = None
        
        action = menu.exec(items_table.mapToGlobal(position))
        
        if action == copy_action:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            row_data = []
            for row in sorted(selected_rows):
                row_values = []
                for col in range(items_table.columnCount()):
                    item = items_table.item(row, col)
                    if item:
                        row_values.append(item.text())
                row_data.append("\t".join(row_values))
            clipboard.setText("\n".join(row_data))
        elif split_action and action == split_action:
            split_row(items_table, list(selected_rows)[0], numeric_columns=[1, 2, 3, 4], editable_columns=[5, 6, 7], parent=window)
        elif action == projekt_action:
            # Show project selection dialog
            proj_list = projects.get_projects_from_db()
            # Filter to only active projects and sort alphabetically
            proj_list = sorted([proj for proj in proj_list if proj.get('status') == 'W trakcie'], 
                             key=lambda x: x.get('project_code', '').lower())
            if not proj_list:
                QMessageBox.information(window, "Info", "Brak aktywnych projektów w bazie danych")
                return
            
            # Create selection dialog
            dialog = QDialog(window)
            dialog.setWindowTitle("Wybierz projekt")
            dialog.setGeometry(100, 100, 450, 685)
            layout = QVBoxLayout(dialog)
            
            # Create table
            projects_table = QTableWidget()
            projects_table.setColumnCount(2)
            projects_table.setRowCount(20)
            projects_table.setHorizontalHeaderLabels(["Kod projektu", "Nazwa"])
            projects_table.setColumnWidth(0, 150)
            projects_table.setColumnWidth(1, 250)
            projects_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            projects_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            
            # Populate table with projects
            for idx, proj in enumerate(proj_list):
                if idx >= 20:  # Limit to 20 rows
                    break
                
                # Code column
                code_item = QTableWidgetItem(proj['project_code'])
                code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                code_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                projects_table.setItem(idx, 0, code_item)
                
                # Name column
                name_item = QTableWidgetItem(proj['name'])
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                projects_table.setItem(idx, 1, name_item)
                
                # Store project code for later retrieval
                code_item.project_code = proj['project_code']
                name_item.project_code = proj['project_code']
            
            layout.addWidget(projects_table)
            
            button_layout = QHBoxLayout()
            ok_btn = QPushButton("OK")
            ok_btn.clicked.connect(dialog.accept)
            button_layout.addWidget(ok_btn)
            layout.addLayout(button_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted and projects_table.currentRow() >= 0:
                selected_project = projects_table.item(projects_table.currentRow(), 0).project_code
                # Apply to all selected rows
                for row in sorted(selected_rows):
                    items_table.item(row, 5).setText(selected_project)
                    items_table.item(row, 5).setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                    items_table.item(row, 6).setText("")   # Clear Magazyn
                    items_table.item(row, 7).setText("")   # Clear Koszt firmowy
        elif action == magazyn_action:
            # Apply to all selected rows
            for row in sorted(selected_rows):
                items_table.item(row, 5).setText("")   # Clear Projekt
                item = items_table.item(row, 6)
                item.setText("✓")  # Magazyn column
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                items_table.item(row, 7).setText("")   # Clear Koszt firmowy
        elif action == koszt_action:
            # Apply to all selected rows
            for row in sorted(selected_rows):
                items_table.item(row, 5).setText("")   # Clear Projekt
                items_table.item(row, 6).setText("")   # Clear Magazyn
                item = items_table.item(row, 7)
                item.setText("✓")  # Koszt firmowy column
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
        elif delete_action and action == delete_action:
            # Delete the selected row
            delete_row(items_table, list(selected_rows)[0], numeric_columns=[1, 2, 3, 4], parent=window)
    
    items_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    items_table.customContextMenuRequested.connect(show_context_menu)
    
    # Add main layout to content
    window.content_layout.addLayout(main_h_layout)


# ===============================
# FUNCTIONS FROM invoices_import.py
# ===============================

def parse_xml_invoice(xml_file):
    """Parse invoice data from XML file."""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Define namespace
        ns = {'fa': 'http://crd.gov.pl/wzor/2025/06/25/13775/'}
        
        # Get seller info (Podmiot1)
        seller_nip = root.findtext('.//fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:NIP', namespaces=ns)
        seller_name = root.findtext('.//fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:Nazwa', namespaces=ns)
        
        # Get seller contact info
        seller_email = root.findtext('.//fa:Podmiot1/fa:DaneKontaktowe/fa:Email', namespaces=ns)
        seller_phone = root.findtext('.//fa:Podmiot1/fa:DaneKontaktowe/fa:Telefon', namespaces=ns)
        
        # Get seller address (combine AdresL1 and AdresL2)
        address_l1 = root.findtext('.//fa:Podmiot1/fa:Adres/fa:AdresL1', namespaces=ns)
        address_l2 = root.findtext('.//fa:Podmiot1/fa:Adres/fa:AdresL2', namespaces=ns)
        seller_address = ""
        if address_l1:
            seller_address = address_l1
        if address_l2:
            seller_address = f"{seller_address}, {address_l2}" if seller_address else address_l2
        
        # Get invoice data
        invoice_date = root.findtext('.//fa:Fa/fa:P_1', namespaces=ns)  # Invoice date
        invoice_number = root.findtext('.//fa:Fa/fa:P_2', namespaces=ns)  # Invoice number
        
        # Get amounts
        total_netto_str = root.findtext('.//fa:Fa/fa:P_13_1', namespaces=ns)
        # Fallback to P_13_7 if P_13_1 is not available
        if not total_netto_str:
            total_netto_str = root.findtext('.//fa:Fa/fa:P_13_7', namespaces=ns)
        total_vat_str = root.findtext('.//fa:Fa/fa:P_14_1', namespaces=ns)
        total_brutto_str = root.findtext('.//fa:Fa/fa:P_15', namespaces=ns)
        
        # Get due date (Termin Płatności)
        due_date = root.findtext('.//fa:Platnosc/fa:TerminPlatnosci/fa:Termin', namespaces=ns)
        
        # Get payment type code (FormaPlatnosci) - store as code, not converted name
        payment_type = root.findtext('.//fa:Platnosc/fa:FormaPlatnosci', namespaces=ns) or ''
        
        # Get invoice type (RodzajFaktury)
        invoice_type = root.findtext('.//fa:Fa/fa:RodzajFaktury', namespaces=ns) or ''
        
        # Parse amounts (replace comma with dot for float conversion)
        total_netto = float(total_netto_str.replace(',', '.')) if total_netto_str else 0
        total_vat = float(total_vat_str.replace(',', '.')) if total_vat_str else 0
        total_brutto = float(total_brutto_str.replace(',', '.')) if total_brutto_str else 0
        
        # Get line items - all items are in a single FaWiersz element grouped by NrWierszaFa
        line_items = []
        fa_wiersze = root.findall('.//fa:FaWiersz', namespaces=ns)
        
        for wiersz in fa_wiersze:
            # Get all direct children with tags
            items_dict = {}
            current_row = None
            
            for child in wiersz:
                tag = child.tag.split('}')[-1]  # Remove namespace
                text = child.text if child.text else ""
                
                if tag == 'NrWierszaFa':
                    current_row = text
                    if current_row not in items_dict:
                        items_dict[current_row] = {}
                elif current_row:
                    # For P_7 (description), concatenate multiple lines instead of overwriting
                    if tag == 'P_7':
                        if 'P_7' in items_dict[current_row]:
                            items_dict[current_row]['P_7'] += ' ' + text
                        else:
                            items_dict[current_row]['P_7'] = text
                    else:
                        items_dict[current_row][tag] = text
            
            # Parse each row's data
            for row_num in sorted(items_dict.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                row_data = items_dict[row_num]
                description = row_data.get('P_7', '')
                quantity_str = row_data.get('P_8B', '')
                
                # Try P_9A first, then P_9B (unit price can be in either field)
                unit_price_str = row_data.get('P_9A', '') or row_data.get('P_9B', '')
                
                # Try P_11 first, then P_11A (net total can be in either field)
                net_price_str = row_data.get('P_11A', '') or row_data.get('P_11', '')
                
                if description and quantity_str and unit_price_str:
                    try:
                        quantity = float(quantity_str.replace(',', '.'))
                        unit_price = float(unit_price_str.replace(',', '.'))
                        net_price = float(net_price_str.replace(',', '.')) if net_price_str else quantity * unit_price
                        
                        line_items.append({
                            'description': description,
                            'quantity': quantity,
                            'unit_price': unit_price,
                            'net_price': net_price
                        })
                    except ValueError:
                        continue
        
        return {
            'seller_nip': seller_nip,
            'seller_name': seller_name,
            'seller_address': seller_address,
            'seller_email': seller_email,
            'seller_phone': seller_phone,
            'invoice_date': invoice_date,
            'due_date': due_date,
            'payment_type': payment_type,
            'invoice_type': invoice_type,
            'invoice_number': invoice_number,
            'total_netto': total_netto,
            'total_vat': total_vat,
            'total_brutto': total_brutto,
            'line_items': line_items
        }
    except Exception as e:
        return None


def import_invoice_to_db(invoice_data, ksef_number=None):
    """Import parsed invoice data to database."""
    try:
        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        
        # Check if invoice already exists
        c.execute("SELECT id FROM invoices WHERE invoice_number = ?", 
                  (invoice_data['invoice_number'],))
        if c.fetchone():
            conn.close()
            return None
        
        # Insert invoice
        c.execute("""
            INSERT INTO invoices 
            (invoice_number, seller_name, seller_nip, invoice_date, due_date, payment_type, invoice_type,
             total_netto, total_vat, total_brutto, ksef_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            invoice_data['invoice_number'],
            invoice_data['seller_name'],
            invoice_data['seller_nip'],
            convert_date_to_standard(invoice_data['invoice_date']),
            convert_date_to_standard(invoice_data.get('due_date', '')),
            invoice_data.get('payment_type', ''),
            invoice_data.get('invoice_type', ''),
            invoice_data['total_netto'],
            invoice_data['total_vat'],
            invoice_data['total_brutto'],
            ksef_number
        ))
        
        invoice_id = c.lastrowid
        
        # Insert line items to invoice_items (unassigned)
        for item in invoice_data['line_items']:
            c.execute("""
                INSERT INTO invoice_items 
                (invoice_id, item_description, quantity, unit_price, total_price)
                VALUES (?, ?, ?, ?, ?)
            """, (
                invoice_id,
                item['description'],
                item['quantity'],
                item['unit_price'],
                item['net_price']
            ))
        
        # Import company info
        if invoice_data['seller_name']:
            try:
                # Check if company exists
                c.execute("SELECT id FROM company_details WHERE name = ?", 
                         (invoice_data['seller_name'],))
                company_exists = c.fetchone()
                
                if not company_exists:
                    # Add new company with seller details
                    c.execute("""
                        INSERT INTO company_details (name, nip_number, address, email, phone)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        invoice_data['seller_name'], 
                        invoice_data.get('seller_nip', ''),
                        invoice_data.get('seller_address', ''),
                        invoice_data.get('seller_email', ''),
                        invoice_data.get('seller_phone', '')
                    ))
                else:
                    # Update existing company with new data from invoice
                    c.execute("""
                        UPDATE company_details 
                        SET nip_number = COALESCE(NULLIF(?, ''), nip_number),
                            address = COALESCE(NULLIF(?, ''), address),
                            email = COALESCE(NULLIF(?, ''), email),
                            phone = COALESCE(NULLIF(?, ''), phone)
                        WHERE name = ?
                    """, (
                        invoice_data.get('seller_nip', ''),
                        invoice_data.get('seller_address', ''),
                        invoice_data.get('seller_email', ''),
                        invoice_data.get('seller_phone', ''),
                        invoice_data['seller_name']
                    ))
            except sqlite3.IntegrityError:
                pass
        
        conn.commit()
        conn.close()
        
        return invoice_id
    except Exception as e:
        return None


class _KSeFDownloadWorker(QThread):
    """Background worker for downloading invoices from KSeF."""
    invoice_downloaded = pyqtSignal(int)  # count of downloaded invoices
    finished_ok = pyqtSignal(str)   # tmp_dir path
    finished_err = pyqtSignal(str)  # error message

    def __init__(self, tmp_dir, key_password, existing_ksef):
        super().__init__()
        self.tmp_dir = tmp_dir
        self.key_password = key_password
        self.existing_ksef = existing_ksef

    def run(self):
        try:
            from scripts.ksef import download_all_invoices, KSeFError, USE_TOKEN_AUTH

            download_all_invoices(
                save_dir=self.tmp_dir,
                key_password=self.key_password,
                use_token_auth=USE_TOKEN_AUTH,
                skip_ksef_numbers=self.existing_ksef,
                progress_callback=lambda count: self.invoice_downloaded.emit(count),
            )
            self.finished_ok.emit(self.tmp_dir)
        except KSeFError as e:
            self.finished_err.emit(f"Błąd KSeF:\n{e.message}")
        except Exception as e:
            self.finished_err.emit(f"Błąd:\n{str(e)}")


def import_invoices(window):
    """Import invoices - download from KSeF, import XMLs to database, delete XMLs."""
    import os
    import shutil
    import tempfile
    from scripts.ksef import USE_TOKEN_AUTH, KEY_FILE, CERT_FILE

    # Check if key/cert files exist when using key auth
    if not USE_TOKEN_AUTH:
        missing = []
        if not KEY_FILE or not os.path.exists(KEY_FILE):
            missing.append(".key")
        if not CERT_FILE or not os.path.exists(CERT_FILE):
            missing.append(".crt")
        if missing:
            QMessageBox.warning(
                window, "Brak plików",
                f"Brak plików: {', '.join(missing)} w folderze data/keys/.\n"
                f"Umieść pliki klucza i certyfikatu przed importem faktur.\n"
                f"Zmodyfikuj także ksef_config.json, aby wskazywał na poprawne nazwy plików."
            )
            return

    # Get existing ksef_numbers from DB to skip already imported invoices
    existing_ksef = set(db_fetch_column("SELECT ksef_number FROM invoices WHERE ksef_number IS NOT NULL"))

    # Ask for KEY_PASSWORD only if using private key auth (not token auth)
    key_password = None
    if not USE_TOKEN_AUTH:
        pwd_dialog = QDialog(window)
        pwd_dialog.setWindowTitle("Hasło klucza")
        pwd_layout = QVBoxLayout()
        pwd_layout.addWidget(QLabel("Podaj hasło do klucza prywatnego (zostaw puste jeśli brak):"))
        pwd_input = QLineEdit()
        pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_layout.addWidget(pwd_input)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Zatwierdź")
        cancel_btn = QPushButton("Anuluj")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        pwd_layout.addLayout(btn_layout)
        pwd_dialog.setLayout(pwd_layout)
        ok_btn.clicked.connect(pwd_dialog.accept)
        cancel_btn.clicked.connect(pwd_dialog.reject)
        if pwd_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key_password = pwd_input.text().strip() if pwd_input.text() else None

    tmp_dir = tempfile.mkdtemp(prefix="ksef_")

    # Progress dialog (indeterminate)
    progress = QProgressDialog("Zaimportowane faktury: 0", None, 0, 0, window)
    progress.setWindowTitle("KSeF")
    progress.setMinimumDuration(0)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setCancelButton(None)  # no cancel
    progress.show()
    QApplication.processEvents()

    worker = _KSeFDownloadWorker(tmp_dir, key_password, existing_ksef)

    def on_invoice_downloaded(count):
        if count == -1:
            progress.setLabelText("Osiągnięto limit godzinowy KSeF. Oczekiwanie...")
        else:
            progress.setLabelText(f"Zaimportowane faktury: {count}")
        QApplication.processEvents()

    def on_error(err_msg):
        progress.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        QMessageBox.critical(window, "Błąd", err_msg)

    def on_success(result_dir):
        progress.setLabelText("Importowanie faktur do bazy...")
        QApplication.processEvents()

        xml_files = [f for f in os.listdir(result_dir) if f.endswith('.xml')]

        if not xml_files:
            progress.close()
            QMessageBox.information(window, "Info", "Brak nowych faktur do zaimportowania.")
            shutil.rmtree(result_dir, ignore_errors=True)
            show_invoices(window)
            return

        imported_count = 0
        for xml_file in xml_files:
            xml_path = os.path.join(result_dir, xml_file)
            ksef_number = xml_file[:-4]

            if ksef_number in existing_ksef:
                os.remove(xml_path)
                continue

            invoice_data = parse_xml_invoice(xml_path)
            if not invoice_data:
                os.remove(xml_path)
                continue

            invoice_id = import_invoice_to_db(invoice_data, ksef_number)
            if invoice_id:
                imported_count += 1

            os.remove(xml_path)

        shutil.rmtree(result_dir, ignore_errors=True)
        progress.close()

        summary_msg = f"Import zakończony!\n\nZaimportowano: {imported_count}/{len(xml_files)} faktur"
        QMessageBox.information(window, "Import Faktur", summary_msg)
        show_invoices(window)

    worker.invoice_downloaded.connect(on_invoice_downloaded)
    worker.finished_err.connect(on_error)
    worker.finished_ok.connect(on_success)

    # Keep reference so the worker isn't garbage-collected
    window._ksef_worker = worker
    worker.start()

