"""Company contacts/details management module."""
import sqlite3
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                             QMessageBox, QDialog, QLineEdit, QMenu, QApplication, QWidget)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
import config
from helpers import (clear_content, create_table_with_scrollbar, add_row_to_table, sort_table_by_column,
                     apply_saved_sort, create_filter_panel, add_filter_row,
                     create_input_table, add_input_row, add_button_row, create_details_table_with_copy,
                     populate_table, db_fetch_all, db_execute, confirm_dialog)


def get_companies_from_db():
    """Get all companies from the database."""
    rows = db_fetch_all("""
        SELECT id, name, address, phone, email, nip_number
        FROM company_details
        ORDER BY name
    """)
    for row in rows:
        row["name"] = row["name"] or ""
        row["address"] = row["address"] or ""
        row["phone"] = row["phone"] or ""
        row["email"] = row["email"] or ""
        row["nip_number"] = row["nip_number"] or ""
    return rows


def _format_company_row(company):
    """Format a company dict into a row of strings for the table."""
    return [
        company["name"],
        company["address"],
        company["phone"],
        company["email"],
        company["nip_number"]
    ]


def company_dialog(window, company=None):
    """Show dialog to add or edit a company.
    
    Args:
        window: Parent window
        company: If provided, edit this company. If None, add new company.
    """
    edit_mode = company is not None
    
    dialog = QDialog(window)
    dialog.setWindowTitle("Edytuj firmę" if edit_mode else "Dodaj firmę")
    dialog.setGeometry(200, 200, 530, 247)
    
    layout = QVBoxLayout()
    
    # Create table for inputs
    input_table = create_input_table(6)
    
    # Row 0: Company name
    name_input = QLineEdit()
    if edit_mode:
        name_input.setText(company["name"])
    add_input_row(input_table, 0, "Nazwa firmy:", name_input)
    
    # Row 1: Address
    address_input = QLineEdit()
    if edit_mode:
        address_input.setText(company["address"])
    add_input_row(input_table, 1, "Adres:", address_input)
    
    # Row 2: Phone
    phone_input = QLineEdit()
    if edit_mode:
        phone_input.setText(company["phone"])
    add_input_row(input_table, 2, "Telefon:", phone_input)
    
    # Row 3: Email
    email_input = QLineEdit()
    if edit_mode:
        email_input.setText(company["email"])
    add_input_row(input_table, 3, "Email:", email_input)
    
    # Row 4: NIP
    nip_input = QLineEdit()
    if edit_mode:
        nip_input.setText(company["nip_number"])
    add_input_row(input_table, 4, "NIP:", nip_input)
    
    # Row 5: Buttons
    save_btn = QPushButton("Zapisz")
    add_button_row(input_table, 5, save_btn)
    
    layout.addWidget(input_table)
    dialog.setLayout(layout)
    
    def save_company():
        name = name_input.text().strip()
        if not name:
            QMessageBox.warning(dialog, "Błąd", "Podaj nazwę firmy")
            return
        
        try:
            if edit_mode:
                db_execute("""
                    UPDATE company_details 
                    SET name = ?, address = ?, phone = ?, email = ?, nip_number = ?
                    WHERE id = ?
                """, (
                    name,
                    address_input.text().strip(),
                    phone_input.text().strip(),
                    email_input.text().strip(),
                    nip_input.text().strip(),
                    company["id"]
                ))
                QMessageBox.information(dialog, "Sukces", "Firma zaktualizowana pomyślnie")
            else:
                db_execute("""
                    INSERT INTO company_details (name, address, phone, email, nip_number)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    name,
                    address_input.text().strip(),
                    phone_input.text().strip(),
                    email_input.text().strip(),
                    nip_input.text().strip()
                ))
                QMessageBox.information(dialog, "Sukces", "Firma dodana pomyślnie")
            
            dialog.accept()
            show_company_contacts(window)
        except sqlite3.IntegrityError:
            QMessageBox.warning(dialog, "Błąd", "Firma o tej nazwie już istnieje")
        except Exception as e:
            QMessageBox.critical(dialog, "Błąd", f"Błąd: {str(e)}")
    
    save_btn.clicked.connect(save_company)
    
    dialog.exec()


def delete_company(window, company):
    """Delete a company from the database after confirmation."""
    if confirm_dialog(window, "Potwierdzenie", f"Czy na pewno chcesz usunąć firmę '{company['name']}'?"):
        try:
            db_execute("DELETE FROM company_details WHERE id = ?", (company["id"],))
            QMessageBox.information(window, "Sukces", "Firma usunięta pomyślnie")
            show_company_contacts(window)
        except Exception as e:
            QMessageBox.critical(window, "Błąd", f"Nie można usunąć firmy: {str(e)}")


def show_company_contacts(window):
    """Show company contacts/details in a table with filters."""
    clear_content(window)
    
    # Main horizontal layout for filters (left) and table (right)
    main_h_layout = QHBoxLayout()
    
    # LEFT SIDE - Filter panel
    filter_frame, filter_table, filter_layout, filter_btn, reset_btn = create_filter_panel(window, 2)
    
    name_search = QLineEdit()
    add_filter_row(filter_table, 0, "Nazwa:", name_search, widget_height=27)
    
    nip_search = QLineEdit()
    add_filter_row(filter_table, 1, "NIP:", nip_search, widget_height=27)
    
    # Add button
    add_btn = QPushButton("Dodaj kontakt")
    filter_layout.addWidget(add_btn)
    
    filter_layout.addStretch()
    
    main_h_layout.addWidget(filter_frame, 0, Qt.AlignmentFlag.AlignTop)
    
    # RIGHT SIDE - Content frame
    right_layout = QVBoxLayout()
    
    # Create table
    columns = ["Nazwa firmy", "Adres", "Telefon", "Email", "NIP"]
    table = create_table_with_scrollbar(window, columns, True, "contacts_list")
    
    # Initialize sort attributes
    table.sort_column = -1
    table.sort_ascending = True
    
    # Make table sortable
    def make_headers_clickable():
        header = table.horizontalHeader()
        header.sectionClicked.connect(lambda col: sort_table_by_column(table, col, table_name="contacts_list"))
    
    # Get companies and populate table
    companies = get_companies_from_db()
    
    # Details dialog to show current info
    def show_details_dialog(company):
        """Show details dialog with company info."""
        dialog = QDialog(window)
        dialog.setWindowTitle(f"Szczegóły: {company['name']}")
        dialog.setGeometry(200, 200, 607, 187)
        
        layout = QVBoxLayout(dialog)
        
        # Prepare current data
        current_data = [
            ("Nazwa", company["name"]),
            ("Adres", company["address"] or "(brak)"),
            ("Telefon", company["phone"] or "(brak)"),
            ("Email", company["email"] or "(brak)"),
            ("NIP", company["nip_number"] or "(brak)"),
        ]
        
        details_table = create_details_table_with_copy(current_data)
        layout.addWidget(details_table)
        
        layout.addStretch()
        
        dialog.exec()
    
    # Double-click handler for table
    def on_table_double_click(index):
        """Show details when row is double-clicked."""
        row = index.row()
        company = table.item(row, 0).data(Qt.ItemDataRole.UserRole) if table.item(row, 0) else None
        if company:
            show_details_dialog(company)
    
    table.doubleClicked.connect(on_table_double_click)
    
    # Initial population
    populate_table(table, companies, _format_company_row)
    make_headers_clickable()
    apply_saved_sort(table, "contacts_list")
    
    right_layout.addWidget(table)
    
    # Context menu for table
    def show_context_menu(position):
        """Show context menu with Open, Copy, Edit, and Delete options."""
        index = table.indexAt(position)
        if not index.isValid():
            return
        
        menu = QMenu()
        row = index.row()
        col = index.column()
        
        # Get the company data stored in the first cell's UserRole
        company = table.item(row, 0).data(Qt.ItemDataRole.UserRole) if table.item(row, 0) else None
        
        # Only show menu if we have valid company data
        if company:
            # Open action
            open_action = QAction("Otwórz", table)
            open_action.triggered.connect(lambda _, c=company: show_details_dialog(c))
            menu.addAction(open_action)
            
            # Edit action
            edit_action = QAction("Edytuj", table)
            edit_action.triggered.connect(lambda _, c=company: company_dialog(window, c))
            menu.addAction(edit_action)
            
            # Delete action
            delete_action = QAction("Usuń", table)
            delete_action.triggered.connect(lambda _, c=company: delete_company(window, c))
            menu.addAction(delete_action)
        
        # Copy action with multi-selection support
        copy_action = QAction("Kopiuj", table)
        def copy_cell():
            selected_ranges = table.selectedRanges()
            clipboard = QApplication.clipboard()
            
            if selected_ranges:
                # Multi-cell copy
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
                # Single cell copy
                cell_text = table.item(row, col).text() if table.item(row, col) else ""
                clipboard.setText(cell_text)
        copy_action.triggered.connect(copy_cell)
        menu.addAction(copy_action)
        
        menu.exec(table.mapToGlobal(position))
    
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show_context_menu)
    
    # Filter action
    def filter_action():
        """Filter companies based on search criteria."""
        name_filter = name_search.text().lower().strip()
        nip_filter = nip_search.text().strip()
        
        filtered_companies = [
            company for company in companies
            if (not name_filter or name_filter in company["name"].lower())
            and (not nip_filter or nip_filter in company["nip_number"])
        ]
        
        populate_table(table, filtered_companies, _format_company_row)
        make_headers_clickable()
        apply_saved_sort(table, "contacts_list")
    
    # Reset action
    def reset_action():
        name_search.clear()
        nip_search.clear()
        populate_table(table, companies, _format_company_row)
        make_headers_clickable()
        apply_saved_sort(table, "contacts_list")
    
    filter_btn.clicked.connect(filter_action)
    reset_btn.clicked.connect(reset_action)
    add_btn.clicked.connect(lambda: company_dialog(window))
    
    main_h_layout.addLayout(right_layout)
    
    # Add to window
    window.content_layout.addLayout(main_h_layout)
