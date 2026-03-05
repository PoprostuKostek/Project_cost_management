"""Program — main application entry point."""
import sys
import time
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtGui import QAction
from pages import invoices, projects, warehouse, labor, payments, company_cost, contacts
from helpers import load_window_geometry, save_window_geometry


class ProgramApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Program")
        self.setGeometry(100, 100, 1920, 1080)
        
        # Try to load saved window geometry
        if not load_window_geometry(self):
            # If no saved geometry, use default size but center on screen
            screen = self.screen()
            if screen:
                screen_geom = screen.availableGeometry()
                self.move((screen_geom.width() - 1920) // 2, (screen_geom.height() - 1080) // 2)
        
        # Central widget with content frame
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget.setLayout(self.content_layout)
        self.setCentralWidget(self.content_widget)
        
        # Cooldown tracking for menu commands
        self.last_menu_click = {}
        
        self.create_menubar()
    
    def with_menu_cooldown(self, key, func, delay_ms=1000):
        """Wrapper to add cooldown to menu commands."""
        def wrapper():
            now = time.time() * 1000
            if key not in self.last_menu_click or now - self.last_menu_click[key] >= delay_ms:
                self.last_menu_click[key] = now
                func()
        return wrapper
    
    def closeEvent(self, event):
        """Save window geometry when closing."""
        save_window_geometry(self)
        event.accept()
    
    def create_menubar(self):
        """Build the application menu bar with page navigation actions."""
        menubar = self.menuBar()

        # Invoices
        invoices_action = QAction("Faktury", self)
        invoices_action.triggered.connect(
            self.with_menu_cooldown("ksef_invoices", lambda: invoices.show_invoices(self))
        )
        menubar.addAction(invoices_action)
        
        # Projects
        projects_action = QAction("Projekty", self)
        projects_action.triggered.connect(
            self.with_menu_cooldown("projects_list", lambda: projects.show_projects(self))
        )
        menubar.addAction(projects_action)
        
        # Warehouse
        warehouse_action = QAction("Magazyn", self)
        warehouse_action.triggered.connect(
            self.with_menu_cooldown("warehouse", lambda: warehouse.show_warehouse(self))
        )
        menubar.addAction(warehouse_action)
        
        # Company costs
        company_costs_action = QAction("Koszty firmowe", self)
        company_costs_action.triggered.connect(
            self.with_menu_cooldown("company_costs", lambda: company_cost.show_company_costs(self))
        )
        menubar.addAction(company_costs_action)
        
        # Labor
        labor_action = QAction("Robocizna", self)
        labor_action.triggered.connect(
            self.with_menu_cooldown("labor", lambda: labor.show_labor(self))
        )
        menubar.addAction(labor_action)
        
        # Payments
        payments_action = QAction("Płatności", self)
        payments_action.triggered.connect(
            self.with_menu_cooldown("payments", lambda: payments.show_payments(self))
        )
        menubar.addAction(payments_action)

        # Contacts
        contacts_action = QAction("Kontakty", self)
        contacts_action.triggered.connect(
            self.with_menu_cooldown("contacts", lambda: contacts.show_company_contacts(self))
        )
        menubar.addAction(contacts_action)

        
if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = ProgramApp()
    window.show()

    invoices.show_invoices(window)
    sys.exit(app.exec())
