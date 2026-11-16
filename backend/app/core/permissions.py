"""Roles and the permission matrix. Routers check permissions, never raw roles."""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    PLANNER = "planner"
    PURCHASER = "purchaser"
    ACCOUNTANT = "accountant"


class Permission(StrEnum):
    AUDIT_READ = "audit.read"
    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"
    USERS_MANAGE = "users.manage"
    # Sensitive data (bank account numbers, UPI, PAN): unmasked view.
    SENSITIVE_VIEW = "sensitive.view"
    # Module permissions used by later features.
    ORDERS_READ = "orders.read"
    ORDERS_WRITE = "orders.write"
    CUSTOMERS_READ = "customers.read"
    CUSTOMERS_WRITE = "customers.write"
    INVOICES_WRITE = "invoices.write"
    PLANNING_READ = "planning.read"
    PLANNING_WRITE = "planning.write"
    PLANNING_APPROVE = "planning.approve"
    PURCHASING_READ = "purchasing.read"
    PURCHASING_WRITE = "purchasing.write"
    PURCHASING_APPROVE = "purchasing.approve"
    FINANCE_READ = "finance.read"
    BILLING_READ = "billing.read"
    BILLING_WRITE = "billing.write"  # follow-ups, receipts, supplier invoices, verify, schedule, execute
    BILLING_ISSUE = "billing.issue"  # issue a sales invoice (owner, accountant)
    BILLING_APPROVE = "billing.approve"  # approve / hold / reject supplier payments (owner only)
    DASHBOARD_READ = "dashboard.read"  # Executive Dashboard (owner only: it shows cash and every module)


_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL,
    Role.PLANNER: frozenset(
        {
            Permission.SETTINGS_READ,
            Permission.ORDERS_READ,
            Permission.ORDERS_WRITE,
            Permission.CUSTOMERS_READ,
            Permission.PLANNING_READ,
            Permission.PLANNING_WRITE,
            Permission.PURCHASING_READ,
        }
    ),
    Role.PURCHASER: frozenset(
        {
            Permission.SETTINGS_READ,
            Permission.ORDERS_READ,
            Permission.CUSTOMERS_READ,
            Permission.PLANNING_READ,
            Permission.PURCHASING_READ,
            Permission.PURCHASING_WRITE,
            Permission.BILLING_READ,
        }
    ),
    Role.ACCOUNTANT: frozenset(
        {
            Permission.SETTINGS_READ,
            Permission.SENSITIVE_VIEW,
            Permission.ORDERS_READ,
            Permission.CUSTOMERS_READ,
            Permission.CUSTOMERS_WRITE,
            Permission.INVOICES_WRITE,
            Permission.FINANCE_READ,
            Permission.PURCHASING_READ,
            Permission.BILLING_READ,
            Permission.BILLING_WRITE,
            Permission.BILLING_ISSUE,
        }
    ),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
