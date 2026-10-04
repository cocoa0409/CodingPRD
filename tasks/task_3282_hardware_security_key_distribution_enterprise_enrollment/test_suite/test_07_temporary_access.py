"""Temporary access grants: window bounds, occupancy, expiry boundary,
ownership, TOTP policy, idempotency."""
from test_helpers import (
    HD,
    ApiErrorId,
    api_client,
    create_employee,
    create_org,
    make_employee_headers,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _org_with_account(legal_name, **org_overrides):
    org = create_org(legal_name=legal_name, **org_overrides)
    emp = create_employee(org["id"])
    return org, emp, emp["identity_account_id"]


def test_grant_expiry_now_equals_expires_at_boundary():
    """PRD §3.9: "The boundary is exclusive: the grant is usable while the
    current time is strictly before `expires_at`."
    PRD §3.9: "use requires the grant to be `ACTIVE` and unexpired — a use at
    or after expiry is `ERR_GRANT_WINDOW`."

    Design: Difficulty/boundary_precision_check/grant_expiry_now_equals_expires_at_boundary
    """
    org, emp, acct = _org_with_account("Grant Org")
    grant = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 24}, HD), expected_status=201)
    # created at 2026-09-01T00:00:00Z -> expires 2026-09-02T00:00:00Z
    set_clock("2026-09-01T23:59:59Z")
    used = validate_success(
        api_client.use_temporary_access(acct, grant["id"], make_employee_headers(emp["id"])))
    assert used["status"] == "USED"
    set_clock("2026-09-02T00:00:00Z")
    grant_b = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 24}, HD), expected_status=201)
    set_clock("2026-09-03T00:00:00Z")
    resp = api_client.use_temporary_access(
        acct, grant_b["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW)


def test_grant_use_rejected_exactly_at_expiry():
    """PRD §3.9: "use requires the grant to be `ACTIVE` and unexpired — a use
    at or after expiry is `ERR_GRANT_WINDOW`."

    Design: Difficulty/boundary_precision_check/grant_expiry_now_equals_expires_at_boundary
    """
    org, emp, acct = _org_with_account("Grant Org 2")
    grant = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 1}, HD), expected_status=201)
    # expires exactly at 2026-09-01T01:00:00Z
    set_clock("2026-09-01T01:00:00Z")
    resp = api_client.use_temporary_access(
        acct, grant["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW)


def test_overlapping_active_temporary_access_grants_rejected():
    """PRD §3.9: "At most one grant per account may be `ACTIVE` at any moment;
    issuing a second while one is live is `ERR_GRANT_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/overlapping_active_temporary_access_grants_rejected
    """
    org, emp, acct = _org_with_account("Overlap Org")
    grant_a = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 1}, HD), expected_status=201)
    resp = api_client.create_temporary_access(
        acct, {"method": "SERVICE_DESK_TOKEN", "duration_hours": 1}, HD)
    validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW)
    validate_success(api_client.void_temporary_access(acct, grant_a["id"], HD))
    grant_b = validate_success(api_client.create_temporary_access(
        acct, {"method": "SERVICE_DESK_TOKEN", "duration_hours": 1}, HD),
        expected_status=201)
    assert grant_b["status"] == "ACTIVE"


def test_second_grant_rejected_regardless_of_duration():
    """PRD §3.9: "At most one grant per account may be `ACTIVE` at any moment;
    issuing a second while one is live is `ERR_GRANT_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/overlapping_active_temporary_access_grants_rejected
    """
    org, emp, acct = _org_with_account("Overlap Org 2")
    validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 72}, HD), expected_status=201)
    resp = api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 1}, HD)
    validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW)


def test_grant_duration_outside_window_rejected():
    """PRD §3.9: "A `HelpDeskAgent` issues a grant to an identity account by
    naming a `method` — `TOTP`, `SMART_CARD`, or `SERVICE_DESK_TOKEN` — and a
    `duration_hours` between 1 and 72 inclusive; a duration outside that window
    is `ERR_GRANT_WINDOW`."

    Design: Corner/validations/grant_duration_outside_window_rejected
    """
    org, emp, acct = _org_with_account("Window2 Org")
    resp0 = api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 0}, HD)
    validate_error(resp0, ApiErrorId.ERR_GRANT_WINDOW)
    resp73 = api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 73}, HD)
    validate_error(resp73, ApiErrorId.ERR_GRANT_WINDOW)
    grant72 = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 72}, HD), expected_status=201)
    assert grant72["status"] == "ACTIVE"


def test_use_of_used_grant_idempotency_rejection():
    """PRD §3.9: "Successful use moves the grant to `USED`." and "`USED`,
    `VOIDED`, and `EXPIRED` are all terminal."

    Design: Corner/state_machines/use_of_used_grant_idempotency_rejection
    """
    org, emp, acct = _org_with_account("Twice Org")
    grant = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 24}, HD), expected_status=201)
    used = validate_success(
        api_client.use_temporary_access(acct, grant["id"], make_employee_headers(emp["id"])))
    assert used["status"] == "USED"
    resp = api_client.use_temporary_access(
        acct, grant["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_employee_cannot_use_another_employees_grant():
    """PRD §3.9: "Only the owning employee consumes a grant: the acting
    employee's identity account must be the account the grant was issued to".

    Design: Corner/rbac/employee_cannot_use_another_employees_grant
    """
    org = create_org(legal_name="Own Org")
    emp_a = create_employee(org["id"], employee_ref="E-B2a", directory_user_id="u-b2a")
    emp_b = create_employee(org["id"], employee_ref="E-B2b", directory_user_id="u-b2b")
    grant = validate_success(api_client.create_temporary_access(
        emp_a["identity_account_id"],
        {"method": "SMART_CARD", "duration_hours": 4}, HD), expected_status=201)
    resp = api_client.use_temporary_access(
        emp_a["identity_account_id"], grant["id"],
        make_employee_headers(emp_b["id"]))
    # PRD requires the ownership rejection but does not name its error_id; both
    # an authorization denial and a scope-style not-found satisfy the rule.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_UNAUTHORIZED, ApiErrorId.ERR_NOT_FOUND])


def test_totp_grant_forbidden_under_phishing_resistant_policy():
    """PRD §3.9: "Under a `PHISHING_RESISTANT` policy the `TOTP` method is
    forbidden — requesting it is `ERR_PHISHABLE_PATH_FORBIDDEN`, because the
    whole point of the policy is that help-desk flows never reintroduce
    phishable recovery."

    Design: Corner/errors/totp_grant_forbidden_under_phishing_resistant_policy
    """
    org_hp, emp_hp, acct_hp = _org_with_account(
        "HP Org", authentication_policy="PHISHING_RESISTANT")
    org_hs, emp_hs, acct_hs = _org_with_account("HS Org")
    resp = api_client.create_temporary_access(
        acct_hp, {"method": "TOTP", "duration_hours": 4}, HD)
    validate_error(resp, ApiErrorId.ERR_PHISHABLE_PATH_FORBIDDEN)
    grant = validate_success(api_client.create_temporary_access(
        acct_hs, {"method": "TOTP", "duration_hours": 4}, HD), expected_status=201)
    assert grant["status"] == "ACTIVE"
