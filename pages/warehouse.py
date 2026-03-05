"""Warehouse (Magazyn) view — thin wrapper around shared assigned_items module."""

from .assigned_items import show_assigned_items


ITEMS_SQL = """
    SELECT ii.id, ii.invoice_id, ii.item_description, wa.quantity_assigned as quantity, 
           ii.unit_price, i.invoice_date, i.seller_name, i.invoice_number, wa.id as assignment_id
    FROM invoice_items ii
    JOIN warehouse_assignments wa ON ii.id = wa.invoice_item_id
    JOIN invoices i ON ii.invoice_id = i.id
    ORDER BY i.invoice_date DESC
"""

COMPANIES_SQL = """
    SELECT DISTINCT i.seller_name
    FROM invoice_items ii
    JOIN warehouse_assignments wa ON ii.id = wa.invoice_item_id
    JOIN invoices i ON ii.invoice_id = i.id
    ORDER BY i.seller_name
"""


def _format_warehouse_row(item):
    netto = item["unit_price"] * item["quantity"]
    return [
        item["invoice_date"],
        item["seller_name"],
        item["invoice_number"],
        item["item_description"],
        f"{item['quantity']:.2f}",
        f"{item['unit_price']:.2f}".replace('.', ','),
        f"{netto:.2f}".replace('.', ',')
    ]


def show_warehouse(window):
    show_assigned_items(
        window,
        assignment_table="warehouse_assignments",
        columns=["Data", "Firma", "Numer faktury", "Materiał", "Ilość", "Cena jednostkowa", "Suma"],
        table_name="warehouse_list",
        format_row_fn=_format_warehouse_row,
        get_items_sql=ITEMS_SQL,
        get_companies_sql=COMPANIES_SQL,
        numeric_columns=[4, 5, 6]
    )