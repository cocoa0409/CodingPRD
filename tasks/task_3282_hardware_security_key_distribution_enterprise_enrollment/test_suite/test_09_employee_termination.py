"""Employee lifecycle: atomic account creation, lock routes, termination
cascade with derived-field reconciliation."""
from test_helpers import (
    HD,
    SA,
    ApiErrorId,
    api_client,
    create_employee,
    create_org,
    setup_account_with_active_enrollments,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_employee_creation_creates_identity_account_atomically():
    """PRD §3.3: "Creating an employee atomically creates exactly one identity
    account bound to that employee; the account's id is returned on the
    employee record as `identity_account_id`. The account copies
    `directory_user_id` and `employee_ref` from the employee at creation and
    never changes them, and it inherits the employee's `organization_id`. The
    account begins `UNENROLLED`, with `registered_key_count` at 0 and
    `backup_compliant` false."

    Design: Corner/entities/employee_creation_creates_identity_account_atomically
    """
    org = create_org(legal_name="Atomic Org")
    emp = validate_success(api_client.create_employee(
        org["id"],
        {"employee_ref": "E-A1", "location": "HQ", "directory_user_id": "u-a1"},
        SA,
    ), expected_status=201)
    assert emp["identity_account_id"]
    account = validate_success(
        api_client.get_identity_account(emp["identity_account_id"], SA))
    assert account["status"] == "UNENROLLED"
    assert account["registered_key_count"] == 0
    assert account["backup_compliant"] is False
    assert account["directory_user_id"] == "u-a1"
    assert account["employee_ref"] == "E-A1"
    assert account["organization_id"] == org["id"]


def test_derived_counters_reconcile_after_termination_cascade():
    """PRD §3.3: "Every security key assigned to the employee's account with
    `hardware_status` in `ASSIGNED` or `DISTRIBUTED` is revoked, carrying the
    enrollment-and-account cascade described in §3.6. Every enrollment
    ceremony of the account in `PENDING`, `ACTIVE`, or `EXPIRING` is revoked.
    Every `ACTIVE` temporary access grant of the account is voided. Finally
    the identity account itself is `LOCKED`."

    Design: Corner/cross_cutting_layers/derived_counters_reconcile_after_termination_cascade
    """
    env = setup_account_with_active_enrollments(
        2, org_overrides={"legal_name": "Term Org", "backup_key_minimum": 2},
        serial_prefix="O-2")
    org, emp, acct = env["org"], env["employee"], env["account_id"]
    grant = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 4}, HD), expected_status=201)
    terminated = validate_success(
        api_client.terminate_employee(org["id"], emp["id"], SA))
    assert terminated["employment_status"] == "TERMINATED"
    account = validate_success(api_client.get_identity_account(acct, SA))
    assert account["status"] == "LOCKED"
    assert account["registered_key_count"] == 0
    assert account["backup_compliant"] is False
    grants, _ = validate_paginated(api_client.list_temporary_access(acct, SA))
    assert grants[0]["status"] == "VOIDED"
    keys, _ = validate_paginated(api_client.list_security_keys(
        org["id"], SA, params={"purchase_order_id": env["order"]["id"]}))
    assert all(k["hardware_status"] == "REVOKED" for k in keys)


def test_termination_is_terminal_and_cannot_repeat():
    """PRD §3.3: "Terminating an employee — a `SecurityAdmin` action on an
    `ACTIVE` employee, moving `employment_status` to the terminal
    `TERMINATED` — triggers the widest cascade in the system."

    Design: Corner/cross_cutting_layers/derived_counters_reconcile_after_termination_cascade
    """
    org = create_org()
    emp = create_employee(org["id"])
    terminated = validate_success(
        api_client.terminate_employee(org["id"], emp["id"], SA))
    assert terminated["employment_status"] == "TERMINATED"
    account = validate_success(
        api_client.get_identity_account(emp["identity_account_id"], SA))
    assert account["status"] == "LOCKED"
    resp = api_client.terminate_employee(org["id"], emp["id"], SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_account_lock_voids_active_grants():
    """PRD §3.3: "A `SecurityAdmin` may lock an `ENROLLED` account — and, as
    an administrative pre-enrollment lockout, an `UNENROLLED` account — moving
    it to `LOCKED`; locking voids every `ACTIVE` temporary access grant on the
    account."

    Design: Corner/cross_cutting_layers/derived_counters_reconcile_after_termination_cascade
    """
    org = create_org()
    emp = create_employee(org["id"])
    acct = emp["identity_account_id"]
    validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 4}, HD), expected_status=201)
    locked = validate_success(api_client.lock_identity_account(acct, SA))
    assert locked["status"] == "LOCKED"
    grants, _ = validate_paginated(api_client.list_temporary_access(acct, SA))
    assert grants[0]["status"] == "VOIDED"
