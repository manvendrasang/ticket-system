"""Unit tests: RBAC matrix, validation, metrics, privacy-free utils."""

from crm import rbac


def test_owner_has_everything():
    for perm in ("contacts.delete", "organization.update", "audit.read", "users.remove"):
        assert rbac.can("owner", perm)


def test_viewer_is_read_only():
    assert rbac.can("viewer", "contacts.read")
    assert not rbac.can("viewer", "contacts.create")
    assert not rbac.can("viewer", "organization.update")


def test_sales_cannot_delete_or_administer():
    assert rbac.can("sales", "deals.create")
    assert not rbac.can("sales", "deals.delete")
    assert not rbac.can("sales", "users.invite")


def test_manager_scope():
    assert rbac.can("manager", "contacts.assign")
    assert not rbac.can("manager", "organization.update")
    assert rbac.can("manager", "pipelines.read")
    assert not rbac.can("manager", "pipelines.create")


def test_unknown_role_has_nothing():
    assert not rbac.can("nobody", "contacts.read")


def test_require_raises():
    import pytest

    with pytest.raises(rbac.PermissionDenied):
        rbac.require("viewer", "contacts.delete")


def test_password_strength_rules():
    from crm.security import check_strength, hash_password, verify_password

    assert check_strength("short") is not None
    assert check_strength("alllowercase123") is not None
    assert check_strength("ValidPass123") is None
    hashed = hash_password("ValidPass123")
    assert verify_password("ValidPass123", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("x", None)
