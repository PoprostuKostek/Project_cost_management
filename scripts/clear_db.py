"""Script to clear all data from database tables."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
import config

def clear_all_tables():
    """Clear all data from database tables."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()
    
    # List of tables to attempt to clear (in dependency order)
    tables_to_try = [
        'manual_costs',
        'company_cost_assignments',
        'project_assignments',
        'warehouse_assignments',
        'payments',
        'labor',
        'employees',
        'invoice_items',
        'company_details',
        'projects',
        'invoices'
    ]
    
    # Get list of existing tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = set(row[0] for row in c.fetchall())
    
    for table in tables_to_try:
        if table in existing_tables:
            try:
                c.execute(f"DELETE FROM {table}")
                print(f"OK: Cleared {table}")
            except sqlite3.OperationalError as e:
                print(f"SKIP: {table} - {e}")
        else:
            print(f"SKIP: {table} (does not exist)")
    
    conn.commit()
    conn.close()
    print("\nOK: All database tables cleared successfully!")

if __name__ == "__main__":
    clear_all_tables()
