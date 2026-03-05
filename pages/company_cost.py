"""Company costs (Koszty firmowe) view — thin wrapper around shared assigned_items module."""

from .assigned_items import show_assigned_items


ITEMS_SQL = """
    SELECT ii.id, ii.invoice_id, ii.item_description, cca.quantity_assigned as quantity, 
           ii.unit_price, i.invoice_date, i.seller_name, i.invoice_number, cca.id as assignment_id
    FROM invoice_items ii
    JOIN company_cost_assignments cca ON ii.id = cca.invoice_item_id
    JOIN invoices i ON ii.invoice_id = i.id
    ORDER BY i.invoice_date DESC
"""

COMPANIES_SQL = """
    SELECT DISTINCT i.seller_name
    FROM invoice_items ii
    JOIN company_cost_assignments cca ON ii.id = cca.invoice_item_id
    JOIN invoices i ON ii.invoice_id = i.id
    WHERE i.seller_name IS NOT NULL
    ORDER BY i.seller_name
"""


def _format_company_cost_row(item):
    netto = item.get("unit_price", 0) * item.get("quantity", 0)
    brutto = netto * 1.23
    vat = brutto - netto
    return [
        item.get("invoice_date", ""),
        item.get("seller_name", ""),
        item.get("invoice_number", ""),
        item.get("item_description", ""),
        f"{netto:.2f}".replace('.', ','),
        f"{vat:.2f}".replace('.', ','),
        f"{brutto:.2f}".replace('.', ',')
    ]


def show_company_costs(window):
    show_assigned_items(
        window,
        assignment_table="company_cost_assignments",
        columns=["Data", "Firma", "Numer faktury", "Opis", "Netto", "VAT", "Brutto"],
        table_name="company_cost_list",
        format_row_fn=_format_company_cost_row,
        get_items_sql=ITEMS_SQL,
        get_companies_sql=COMPANIES_SQL,
        numeric_columns=[4, 5, 6]
    )