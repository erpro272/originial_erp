from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission


def test_owner_has_everything() -> None:
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)


def test_only_owner_reads_audit_and_writes_settings() -> None:
    for role in Role:
        assert has_permission(role, Permission.AUDIT_READ) == (role is Role.OWNER)
        assert has_permission(role, Permission.SETTINGS_WRITE) == (role is Role.OWNER)


def test_sensitive_view_owner_and_accountant_only() -> None:
    allowed = {r for r in Role if has_permission(r, Permission.SENSITIVE_VIEW)}
    assert allowed == {Role.OWNER, Role.ACCOUNTANT}


def test_every_role_can_read_settings() -> None:
    assert all(has_permission(r, Permission.SETTINGS_READ) for r in Role)


def test_prod_refuses_dev_secrets() -> None:
    import pytest
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="ERP_JWT_SECRET"):
        Settings(env="prod", cookie_secure=True)
