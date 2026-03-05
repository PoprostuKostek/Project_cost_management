"""Shared module for displaying assigned invoice items (warehouse and company costs).
Both views share ~90% identical structure — this module parameterizes the differences."""

from PyQt6.QtWidgets import QComboBox, QVBoxLayout, QHBoxLayout, QMenu
from PyQt6.QtCore import QDate, Qt
from helpers import (clear_content, create_table_with_scrollbar, sort_table_by_column,
                     parse_date, BlankDateEdit, apply_saved_sort, create_filter_panel, add_filter_row,
                     copy_table_row_to_clipboard, is_date_in_range,
                     populate_table, db_fetch_all, db_fetch_column)
from . import invoices


def show_assigned_items(window, *, assignment_table, columns, table_name, format_row_fn, get_items_sql,
                        get_companies_sql, numeric_columns):
    """Display assigned invoice items with filtering, sorting, and context menu.
    
    Args:
        window: Main application window
        assignment_table: DB table name (e.g. 'warehouse_assignments', 'company_cost_assignments')
        columns: List of column header strings
        table_name: Unique table name for sort preferences
        format_row_fn: Function(item) -> list of strings for each table row
        get_items_sql: SQL query to fetch all items (must return dicts via db_fetch_all)
        get_companies_sql: SQL query to fetch distinct company names (via db_fetch_column)
        numeric_columns: List of column indices that contain numeric data
    """
    clear_content(window)
    
    main_h_layout = QHBoxLayout()
    
    # Filter panel
    companies = db_fetch_column(get_companies_sql)
    filter_frame, filter_table, filter_layout, filter_btn, reset_btn = create_filter_panel(window, 3)
    
    from_date = BlankDateEdit()
    add_filter_row(filter_table, 0, "Data od:", from_date)
    
    until_date = BlankDateEdit()
    add_filter_row(filter_table, 1, "Data do:", until_date)
    
    company_combo = QComboBox()
    company_combo.addItems([""] + companies)
    company_combo.setEditable(True)
    add_filter_row(filter_table, 2, "Firma:", company_combo, widget_height=27)
    
    filter_layout.addStretch()
    main_h_layout.addWidget(filter_frame, 0, Qt.AlignmentFlag.AlignTop)
    
    # Table
    right_layout = QVBoxLayout()
    table = create_table_with_scrollbar(window, columns, True, table_name)
    
    # Context menu
    def show_context_menu(pos):
        index = table.indexAt(pos)
        if index.row() < 0:
            return
        invoice_number = table.item(index.row(), 2).text() if table.item(index.row(), 2) else ""
        menu = QMenu()
        open_action = menu.addAction("Otwórz")
        open_action.triggered.connect(lambda: invoices.show_invoice_details(window, invoice_number))
        copy_action = menu.addAction("Kopiuj")
        copy_action.triggered.connect(lambda: copy_table_row_to_clipboard(table, index.row()))
        menu.exec(table.mapToGlobal(pos))
    
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show_context_menu)
    
    table.sort_column = -1
    table.sort_ascending = True
    
    header = table.horizontalHeader()
    header.sectionClicked.connect(lambda col: sort_table_by_column(table, col, numeric_columns=numeric_columns, table_name=table_name))
    
    table.doubleClicked.connect(lambda index: invoices.show_invoice_details(
        window, table.item(index.row(), 2).text() if table.item(index.row(), 2) else ""))
    
    right_layout.addWidget(table)
    main_h_layout.addLayout(right_layout)
    window.content_layout.addLayout(main_h_layout)
    
    # Populate
    items = db_fetch_all(get_items_sql)
    populate_table(table, items, format_row_fn, numeric_columns=numeric_columns)
    apply_saved_sort(table, table_name, numeric_columns=numeric_columns)
    
    def filter_action():
        filtered = [
            item for item in items
            if (not company_combo.currentText() or item.get("seller_name") == company_combo.currentText())
            and (item_date := parse_date(item.get("invoice_date", ""), "%d-%m-%Y")) is not None
            and is_date_in_range(item_date, from_date, until_date)
        ]
        populate_table(table, filtered, format_row_fn, numeric_columns=numeric_columns)
        apply_saved_sort(table, table_name, numeric_columns=numeric_columns)
    
    def reset_action():
        from_date.setDate(QDate())
        until_date.setDate(QDate())
        company_combo.setCurrentIndex(0)
        populate_table(table, items, format_row_fn, numeric_columns=numeric_columns)
        apply_saved_sort(table, table_name, numeric_columns=numeric_columns)
    
    filter_btn.clicked.connect(filter_action)
    reset_btn.clicked.connect(reset_action)
