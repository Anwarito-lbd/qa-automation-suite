"""Android Page Object Model (POM) for AegisPay Mobile."""

from qa_framework.mobile.pages.dashboard_page import WalletDashboardPage
from qa_framework.mobile.pages.login_page import LoginPage
from qa_framework.mobile.pages.transfer_page import TransferOrderPage

__all__ = ["LoginPage", "TransferOrderPage", "WalletDashboardPage"]
