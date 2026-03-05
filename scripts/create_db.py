"""Database schema creation script."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3


def create_database(db_name=None):
    """
    Create database with reorganized schema:
    - invoice_items is the source of truth
    - Assignment tables track where each item is assigned (warehouse, project, or company cost)
    - No duplication of item data
    """
    # determine DB path: explicit, or environment/config, or fallback
    if db_name is None:
        try:
            import config
            db_name = getattr(config, "DB_PATH", "database.db")
        except Exception:
            db_name = "database.db"

    conn = sqlite3.connect(db_name)
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    # ------------------- INVOICES -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT NOT NULL UNIQUE,
        ksef_number TEXT,
        seller_name TEXT NOT NULL,
        seller_nip TEXT,
        seller_account_number TEXT,
        invoice_date TEXT NOT NULL,
        due_date TEXT,
        payment_type TEXT,
        invoice_type TEXT,
        total_netto REAL NOT NULL,
        total_vat REAL NOT NULL,
        total_brutto REAL NOT NULL
    )
    """)

    # ------------------- INVOICE ITEMS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        item_description TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        total_price REAL NOT NULL,
        FOREIGN KEY (invoice_id)
            REFERENCES invoices(id)
            ON DELETE CASCADE
    )
    """)

    # ------------------- COMPANY DETAILS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS company_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        address TEXT,
        nip_number TEXT,
        email TEXT,
        phone TEXT
    )
    """)


    # ------------------- PROJECTS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_code TEXT NOT NULL UNIQUE,
        name TEXT,
        start_date TEXT,
        end_date TEXT,
        status TEXT,
        estimated_income REAL
    )
    """)

    # ------------------- WAREHOUSE ASSIGNMENTS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS warehouse_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_item_id INTEGER NOT NULL UNIQUE,
        quantity_assigned REAL NOT NULL,
        assignment_date TEXT,
        FOREIGN KEY (invoice_item_id)
            REFERENCES invoice_items(id)
            ON DELETE CASCADE
    )
    """)

    # ------------------- PROJECT ASSIGNMENTS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS project_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_item_id INTEGER NOT NULL UNIQUE,
        project_id INTEGER NOT NULL,
        quantity_assigned REAL NOT NULL,
        assignment_date TEXT,
        FOREIGN KEY (invoice_item_id)
            REFERENCES invoice_items(id)
            ON DELETE CASCADE,
        FOREIGN KEY (project_id)
            REFERENCES projects(id)
            ON DELETE CASCADE
    )
    """)

    # ------------------- COMPANY COST ASSIGNMENTS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS company_cost_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_item_id INTEGER NOT NULL UNIQUE,
        quantity_assigned REAL NOT NULL,
        assignment_date TEXT,
        FOREIGN KEY (invoice_item_id)
            REFERENCES invoice_items(id)
            ON DELETE CASCADE
    )
    """)

    # ------------------- EMPLOYEES -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        hourly_rate REAL NOT NULL,
        hire_date TEXT,
        status TEXT DEFAULT 'active'
    )
    """)

    # ------------------- LABOR -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS labor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        employee_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        hours_worked REAL NOT NULL,
        hourly_rate REAL NOT NULL,
        total_cost REAL NOT NULL,
        FOREIGN KEY (project_id)
            REFERENCES projects(id)
            ON DELETE CASCADE,
        FOREIGN KEY (employee_id)
            REFERENCES employees(id)
            ON DELETE CASCADE
    )
    """)

    # ------------------- PAYMENTS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL UNIQUE,
        payment_date TEXT,
        amount REAL,
        FOREIGN KEY (invoice_id)
            REFERENCES invoices(id)
            ON DELETE CASCADE
    )
    """)

    # ------------------- MANUAL PROJECT COSTS -------------------
    c.execute("""
    CREATE TABLE IF NOT EXISTS manual_costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dokument TEXT,
        firma TEXT,
        data TEXT,
        opis_pozycji TEXT,
        ilosc REAL NOT NULL,
        cena_jednostkowa REAL NOT NULL,
        suma REAL NOT NULL,
        FOREIGN KEY (project_id)
            REFERENCES projects(id)
            ON DELETE CASCADE
    )
    """)

    # Indexes to improve common lookups
    c.execute("CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_id ON invoice_items(invoice_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_assignments_item_id ON warehouse_assignments(invoice_item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_assignments_item_id ON project_assignments(invoice_item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_assignments_project_id ON project_assignments(project_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_company_cost_assignments_item_id ON company_cost_assignments(invoice_item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice_id ON payments(invoice_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date)")

    conn.commit()
    conn.close()
    print(f"OK: Database '{db_name}' created successfully.")


if __name__ == "__main__":
    create_database()

