"""Payments view — payment list, status management, white list check."""
from PyQt6.QtWidgets import QPushButton, QComboBox, QVBoxLayout, QHBoxLayout, QMessageBox, QDialog, QApplication, QLineEdit, QMenu
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QAction
from datetime import datetime, date
from helpers import (clear_content, create_table_with_scrollbar, add_row_to_table, sort_table_by_column,
                     parse_date, BlankDateEdit, apply_saved_sort,
                     create_filter_panel, add_filter_row, create_input_table, add_input_row,
                     add_button_row, create_details_table_with_copy, is_date_in_range,
                     populate_table, db_fetch_all, db_fetch_column, db_execute, confirm_dialog)
import os
import config
import xml.etree.ElementTree as ET
import requests


def get_payments_from_db():
    """Get all payments joined with invoice data from the database."""
    return db_fetch_all("""
        SELECT p.*, i.seller_name, i.seller_nip, i.invoice_number, i.ksef_number, 
               i.invoice_date, i.due_date, i.total_netto, i.total_vat, i.total_brutto, i.seller_account_number
        FROM payments p
        JOIN invoices i ON p.invoice_id = i.id
        ORDER BY i.invoice_date DESC
    """)


def get_companies_from_payments_db():
    """Get distinct company names that have payments."""
    return db_fetch_column("""
        SELECT DISTINCT i.seller_name
        FROM payments p
        JOIN invoices i ON p.invoice_id = i.id
        ORDER BY i.seller_name
    """)


def get_account_number_from_xml(ksef_number):
    """Extract account number (NrRB) from XML file."""
    if not ksef_number:
        return ""
    
    xml_folder = os.path.join(os.path.dirname(config.DB_PATH), "xml_files")
    xml_file = os.path.join(xml_folder, f"{ksef_number}.xml")
    
    if not os.path.exists(xml_file):
        return ""
    
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Try with namespace
        ns = {'fa': 'http://crd.gov.pl/wzor/2025/06/25/13775/'}
        nr_rb_elem = root.find('.//fa:NrRB', ns)
        
        if nr_rb_elem is not None and nr_rb_elem.text:
            return nr_rb_elem.text
        
        # Try without namespace
        nr_rb_elem = root.find('.//NrRB')
        if nr_rb_elem is not None and nr_rb_elem.text:
            return nr_rb_elem.text
        
        return ""
    except Exception as e:
        return ""


def get_payment_status(payment):
    """Determine payment status based on amount."""
    amount = payment.get('amount') or 0
    total_brutto = payment.get('total_brutto', 0)
    
    if amount <= 0:
        return "Niezapłacone"
    elif amount >= total_brutto:
        return "Zapłacone"
    else:
        return "Częściowo zapłacone"


def get_remaining_brutto(payment):
    """Calculate remaining brutto amount."""
    amount = payment.get('amount') or 0
    total_brutto = payment.get('total_brutto', 0)
    return max(0, total_brutto - amount)


def _format_payment_row(payment):
    """Format a payment dict into a row of strings for the table."""
    due_date = parse_date(payment.get("due_date", ""), "%d-%m-%Y")
    days_overdue = (datetime.now().date() - due_date).days if due_date else 0
    return [
        get_payment_status(payment),
        payment["seller_name"],
        payment.get("seller_nip", ""),
        payment["invoice_number"],
        payment["invoice_date"],
        payment.get("due_date", ""),
        str(days_overdue),
        f"{payment['total_netto']:.2f}".replace('.', ','),
        f"{payment['total_vat']:.2f}".replace('.', ','),
        f"{payment['total_brutto']:.2f}".replace('.', ','),
        f"{get_remaining_brutto(payment):.2f}".replace('.', ',')
    ]


def _numeric_cols():
    return [6, 7, 8, 9, 10]


def show_payments(window, status_filter=None, due_date_filter=None):
    """Show payments view.
    
    Args:
        window: Main window
        status_filter: Optional status to filter ("Niezapłacone", "Częściowo zapłacone", "Zapłacone")
        due_date_filter: Optional due date filter ("close" for less than 7 days)
    """
    clear_content(window)
    
    # Main horizontal layout for filters (left) and table (right)
    main_h_layout = QHBoxLayout()
    
    # Filter panel (LEFT SIDE)
    companies = get_companies_from_payments_db()
    filter_frame, filter_table, filter_layout, filter_btn, reset_btn = create_filter_panel(window, 4)
    
    from_date = BlankDateEdit()
    add_filter_row(filter_table, 0, "Data od:", from_date)
    
    until_date = BlankDateEdit()
    add_filter_row(filter_table, 1, "Data do:", until_date)
    
    company_combo = QComboBox()
    company_combo.addItems([""] + companies)
    company_combo.setEditable(True)
    add_filter_row(filter_table, 2, "Firma:", company_combo, widget_height=27)
    
    status_combo = QComboBox()
    status_combo.addItems(["", "Niezapłacone", "Częściowo zapłacone", "Zapłacone"])
    add_filter_row(filter_table, 3, "Status:", status_combo, widget_height=27)
    
    filter_layout.addStretch()
    
    main_h_layout.addWidget(filter_frame, 0, Qt.AlignmentFlag.AlignTop)
    
    # Right side layout (RIGHT SIDE) - containing table
    right_layout = QVBoxLayout()
    
    # Table (RIGHT SIDE)
    columns = ["Status", "Firma", "NIP", "Numer faktury", "Data faktury", "Data płatności", "Dni zaległości", "Netto", "VAT", "Brutto", "Pozostało brutto"]
    table = create_table_with_scrollbar(window, columns, True, "payments_list")
    
    # Set up context menu for payments table
    def show_payments_context_menu(position):
        """Show context menu with Open, Copy, Edit Status, and Delete options."""
        index = table.indexAt(position)
        if not index.isValid():
            return
        
        menu = QMenu()
        row = index.row()
        col = index.column()
        
        # Open action
        open_action = QAction("Otwórz", table)
        open_action.triggered.connect(lambda: show_wire_transfer_details(row, col))
        menu.addAction(open_action)
        
        # Copy action
        copy_action = QAction("Kopiuj", table)
        def copy_cell():
            selected_ranges = table.selectedRanges()
            clipboard = QApplication.clipboard()
            
            if selected_ranges:
                copy_text = ""
                for range_obj in selected_ranges:
                    for r in range(range_obj.topRow(), range_obj.bottomRow() + 1):
                        row_data = []
                        for c in range(range_obj.leftColumn(), range_obj.rightColumn() + 1):
                            item = table.item(r, c)
                            row_data.append(item.text() if item else "")
                        copy_text += "\t".join(row_data) + "\n"
                clipboard.setText(copy_text.rstrip())
            else:
                cell_text = table.item(row, col).text() if table.item(row, col) else ""
                clipboard.setText(cell_text)
        copy_action.triggered.connect(copy_cell)
        menu.addAction(copy_action)
        
        # Edit Status action with submenu
        edit_action = QAction("Zmień status", table)
        status_submenu = QMenu(table)
        
        status_options = ["Niezapłacone", "Częściowo zapłacone", "Zapłacone"]
        for status_option in status_options:
            status_action = status_submenu.addAction(status_option)
            def handle_status_change(checked, status=status_option):
                if row >= 0 and row < table.rowCount():
                    invoice_number_item = table.item(row, 3)
                    if invoice_number_item:
                        invoice_number = invoice_number_item.text()
                        for p in payments:
                            if p.get('invoice_number') == invoice_number:
                                payment_id = p.get('id')
                                try:
                                    change_payment_status(payment_id, status)
                                except Exception as e:
                                    QMessageBox.critical(window, "Błąd", f"Błąd przy zmianie statusu: {str(e)}")
                                break
            status_action.triggered.connect(handle_status_change)
        
        edit_action.setMenu(status_submenu)
        menu.addAction(edit_action)
        
        # Delete action
        delete_action = QAction("Usuń", table)
        delete_action.triggered.connect(lambda: delete_payment(row))
        menu.addAction(delete_action)
        
        menu.exec(table.mapToGlobal(position))
    
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show_payments_context_menu)
    
    # Initialize sort attributes
    table.sort_column = -1
    table.sort_ascending = True
    
    # Make headers clickable for sorting
    header = table.horizontalHeader()
    header.sectionClicked.connect(lambda col: sort_table_by_column(table, col, numeric_columns=_numeric_cols(), table_name="payments_list"))
    
    right_layout.addWidget(table)
    main_h_layout.addLayout(right_layout)
    
    # Add the main horizontal layout to content
    window.content_layout.addLayout(main_h_layout)
    
    payments = get_payments_from_db()
    
    def filter_action():
        # Get UI filter values, with parameter-based defaults
        combo_status = status_combo.currentText()
        filter_status = combo_status if combo_status else status_filter
        filter_company = company_combo.currentText()
        
        filtered = [
            p for p in payments
            if (not filter_status or get_payment_status(p) == filter_status)
            and (not filter_company or p["seller_name"] == filter_company)
            and (invoice_date := parse_date(p["invoice_date"], "%d-%m-%Y")) is not None
            and is_date_in_range(invoice_date, from_date, until_date)
        ]
        populate_table(table, filtered, _format_payment_row, numeric_columns=_numeric_cols())
        apply_saved_sort(table, "payments_list", numeric_columns=_numeric_cols())
    
    def reset_action():
        from_date.setDate(QDate())
        until_date.setDate(QDate())
        company_combo.setCurrentIndex(0)
        status_combo.setCurrentIndex(0)
        populate_table(table, payments, _format_payment_row, numeric_columns=_numeric_cols())
        apply_saved_sort(table, "payments_list", numeric_columns=_numeric_cols())
    
    def show_wire_transfer_details(row, col):
        """Show popup with wire transfer details for the selected payment."""
        try:
            if row < 0 or row >= table.rowCount():
                return
            
            # Get invoice number from column 3 of the table (Status=0, Firma=1, NIP=2, Invoice#=3)
            invoice_number_item = table.item(row, 3)
            if not invoice_number_item:
                return
            
            invoice_number = invoice_number_item.text()
            
            # Find the payment with this invoice number
            payment = None
            for p in payments:
                if p.get('invoice_number') == invoice_number:
                    payment = p
                    break
            
            if not payment:
                return
            
            # Create dialog
            dialog = QDialog(window)
            dialog.setWindowTitle(f"Dane do przelewu - {payment['invoice_number']}")
            dialog.setGeometry(200, 200, 607, 297)
            
            # Create layout
            layout = QVBoxLayout()
            
            # Prepare details data
            account_number = get_account_number_from_xml(payment.get('ksef_number', ''))
            
            # Calculate amounts based on payment status
            status = get_payment_status(payment)
            if status == "Częściowo zapłacone":
                # Calculate remaining amounts proportionally
                total_brutto = payment.get('total_brutto', 0)
                amount_paid = payment.get('amount') or 0
                remaining_brutto = total_brutto - amount_paid
                
                # Calculate remaining netto and vat proportionally
                if total_brutto > 0:
                    total_netto = payment.get('total_netto', 0)
                    total_vat = payment.get('total_vat', 0)
                    remaining_netto = (total_netto / total_brutto) * remaining_brutto
                    remaining_vat = (total_vat / total_brutto) * remaining_brutto
                else:
                    remaining_netto = 0
                    remaining_vat = 0
                
                details_data = [
                    ("Numer faktury", payment.get('invoice_number', '')),
                    ("NIP", payment.get('seller_nip', '')),
                    ("Numer konta", account_number),
                    ("Data płatności", payment.get('due_date', '')),
                    ("Numer KSeF", payment.get('ksef_number', '')),
                    ("Netto do zapłaty", f"{remaining_netto:.2f}".replace('.', ',')),
                    ("VAT do zapłaty", f"{remaining_vat:.2f}".replace('.', ',')),
                    ("Brutto do zapłaty", f"{remaining_brutto:.2f}".replace('.', ',')),
                ]
            else:
                # Show full amounts for unpaid invoices
                details_data = [
                    ("Numer faktury", payment.get('invoice_number', '')),
                    ("NIP", payment.get('seller_nip', '')),
                    ("Numer konta", account_number),
                    ("Data płatności", payment.get('due_date', '')),
                    ("Numer KSeF", payment.get('ksef_number', '')),
                    ("Netto", f"{payment['total_netto']:.2f}".replace('.', ',')),
                    ("VAT", f"{payment['total_vat']:.2f}".replace('.', ',')),
                    ("Brutto", f"{payment['total_brutto']:.2f}".replace('.', ',')),
                ]
            
            # Create details table with copy buttons
            details_table = create_details_table_with_copy(details_data)
            
            # Add button row with Sprawdź na białej liście button spanning 3 columns
            button_row_idx = len(details_data)
            details_table.insertRow(button_row_idx)
            
            def check_whitelist():
                """Check NIP on Biała Lista VAT and show results."""
                nip = payment.get('seller_nip', '')
                company_name = payment.get('seller_name', '')
                if not nip:
                    QMessageBox.warning(dialog, "Brak NIP", "Brak NIP sprzedawcy.")
                    return
                
                check_date = date.today().strftime("%Y-%m-%d")
                url = f"https://wl-api.mf.gov.pl/api/search/nip/{nip}?date={check_date}"
                
                try:
                    response = requests.get(url, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                except requests.exceptions.RequestException as e:
                    QMessageBox.critical(dialog, "Błąd", f"Błąd podczas sprawdzania:\n{e}")
                    return
                
                subject = data.get("result", {}).get("subject")
                if subject:
                    msg = f"Kontrahent {company_name}, o NIPie: {nip} jest na białej liście"
                    QMessageBox.information(dialog, "Biała Lista", msg)
                else:
                    msg = f"Kontrahent {company_name}, o NIPie: {nip} nie jest na białej liście"
                    QMessageBox.warning(dialog, "Biała Lista", msg)
            
            whitelist_btn = QPushButton("Sprawdź na białej liście")
            whitelist_btn.setDefault(True)
            whitelist_btn.clicked.connect(check_whitelist)
            details_table.setCellWidget(button_row_idx, 0, whitelist_btn)
            details_table.setSpan(button_row_idx, 0, 1, 3)  # Span across all 3 columns
            details_table.setRowHeight(button_row_idx, 27)
            
            layout.addWidget(details_table)
            
            dialog.setLayout(layout)
            dialog.exec()
        except Exception:
            pass  # Dialog display failed silently
    
    def delete_payment(row):
        """Delete payment from database and refresh table."""
        try:
            if row < 0 or row >= table.rowCount():
                return
            
            # Get invoice number from column 3
            invoice_number_item = table.item(row, 3)
            if not invoice_number_item:
                return
            
            invoice_number = invoice_number_item.text()
            
            # Find payment with this invoice number and delete it
            payment_id = None
            for p in payments:
                if p.get('invoice_number') == invoice_number:
                    payment_id = p.get('id')
                    break
            
            if payment_id is None:
                QMessageBox.warning(window, "Błąd", "Nie znaleziono płatności.")
                return
            
            # Confirm deletion
            if not confirm_dialog(window, "Potwierdzenie", f"Czy na pewno chcesz usunąć płatność dla faktury {invoice_number}?"):
                return
            
            # Delete from database
            db_execute("DELETE FROM payments WHERE id = ?", (payment_id,))
            
            # Remove from payments list
            payments[:] = [p for p in payments if p.get('id') != payment_id]
            
            # Refresh table
            filter_action()
            
            QMessageBox.information(window, "Sukces", "Płatność została usunięta.")
        except Exception as e:
            QMessageBox.warning(window, "Błąd", f"Nie udało się usunąć płatności: {str(e)}")
    
    # Set up right-click context menu (already configured above with show_payments_context_menu)
    
    def show_partial_payment_dialog(payment):
        """Show dialog for entering partial payment amounts."""
        dialog = QDialog(window)
        dialog.setWindowTitle("Wprowadź kwotę płatności")
        dialog.setGeometry(200, 200, 500, 177)
        
        layout = QVBoxLayout(dialog)
        
        # Create table for inputs
        input_table = create_input_table(4)
        
        # Row 0: Netto
        netto_input = QLineEdit()
        netto_input.setText("0,00")
        add_input_row(input_table, 0, "Netto:", netto_input)
        
        # Row 1: VAT
        vat_input = QLineEdit()
        vat_input.setText("0,00")
        add_input_row(input_table, 1, "VAT:", vat_input)
        
        # Row 2: Brutto (read-only)
        brutto_input = QLineEdit()
        brutto_input.setText("0,00")
        brutto_input.setReadOnly(True)
        add_input_row(input_table, 2, "Brutto:", brutto_input)
        
        # Function to update brutto when netto or vat changes
        def update_brutto():
            try:
                netto_str = netto_input.text().strip().replace(',', '.')
                vat_str = vat_input.text().strip().replace(',', '.')
                netto = float(netto_str) if netto_str else 0
                vat = float(vat_str) if vat_str else 0
                brutto = netto + vat
                brutto_input.setText(f"{brutto:.2f}".replace('.', ','))
            except ValueError:
                brutto_input.setText("0,00")
        
        # Connect signals to update brutto
        netto_input.textChanged.connect(update_brutto)
        vat_input.textChanged.connect(update_brutto)
        
        # Row 3: Buttons
        ok_btn = QPushButton("Zapisz")
        ok_btn.setDefault(True)
        add_button_row(input_table, 3, ok_btn)
        
        # Set column widths
        input_table.setColumnWidth(0, 150)
        input_table.setColumnWidth(1, 320)
        
        layout.addWidget(input_table)
        dialog.setLayout(layout)
        
        ok_btn.clicked.connect(dialog.accept)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                # Parse brutto value from input
                brutto_str = brutto_input.text().strip().replace(',', '.')
                amount = float(brutto_str) if brutto_str else 0
                return amount
            except ValueError:
                QMessageBox.warning(window, "Błąd", "Niepoprawna kwota.")
                return None
        return None
    
    def change_payment_status(payment_id, new_status):
        """Change payment status in database."""
        try:
            # Get payment from payments list
            payment = None
            for p in payments:
                if p.get('id') == payment_id:
                    payment = p
                    break
            
            if not payment:
                QMessageBox.warning(window, "Błąd", "Nie znaleziono płatności.")
                return
            
            # Determine amount based on status
            total_brutto = payment.get('total_brutto', 0)
            if new_status == "Niezapłacone":
                amount = 0
            elif new_status == "Zapłacone":
                amount = total_brutto
            else:  # Częściowo zapłacone
                # Show dialog for partial payment input
                amount = show_partial_payment_dialog(payment)
                if amount is None:
                    return  # User cancelled
            
            # Update in database
            db_execute("UPDATE payments SET amount = ? WHERE id = ?", (amount, payment_id))
            
            # Update in payments list
            for p in payments:
                if p.get('id') == payment_id:
                    p['amount'] = amount
                    break
            
            # Refresh table with all filters cleared
            reset_action()
            
        except Exception as e:
            QMessageBox.warning(window, "Błąd", f"Nie udało się zmienić statusu: {str(e)}")
    
    # Connect double-click to show wire transfer details
    def on_table_double_click(row, col):
        show_wire_transfer_details(row, col)
    
    table.cellDoubleClicked.connect(on_table_double_click)
    
    filter_btn.clicked.connect(filter_action)
    reset_btn.clicked.connect(reset_action)
    
    # Always populate table with data
    if status_filter:
        status_combo.setCurrentText(status_filter)
        filtered = [p for p in payments if get_payment_status(p) == status_filter]
        populate_table(table, filtered, _format_payment_row, numeric_columns=_numeric_cols())
    else:
        populate_table(table, payments, _format_payment_row, numeric_columns=_numeric_cols())
    
    # Apply saved sort preference (or do nothing if no preference saved)
    apply_saved_sort(table, "payments_list", numeric_columns=_numeric_cols())
    
    # If no sorting was applied (no saved preference), default to sorting by days overdue
    if table.sort_column == -1:
        sort_table_by_column(table, 6, numeric_columns=_numeric_cols(), table_name="payments_list")

