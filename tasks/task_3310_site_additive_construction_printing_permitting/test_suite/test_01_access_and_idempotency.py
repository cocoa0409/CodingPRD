"""Access control, idempotency, and OCC tests (PRD §2.1, §2.8, §2.9)."""
from test_helpers import (
    ApiErrorId,
    PRINT_OP,
    SITE_MGR,
    create_approved_plan_revision,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_permit_application_payload,
    create_plan_revision_payload,
    create_printer_setup_payload,
    create_site,
    create_structural_plan_payload,
    current_site_version,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    assert_jurisdiction,
)
from test_helpers.test_users import make_engineer_headers


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing `X-User-Role`, or carrying a role string
    the server does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    headers = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
    resp = api.create_jurisdiction(create_jurisdiction_payload(code="JA7"), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_missing_idempotency_key_rejected(api, platform_admin_headers):
    """PRD §2.9: "A POST missing the header is rejected with
    `ERR_MISSING_IDEMPOTENCY_KEY` (HTTP 400)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(code="JA8"), platform_admin_headers, idem_key=False
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_IDEMPOTENCY_KEY)


def test_idempotency_replay_with_different_body_returns_mismatch(api, platform_admin_headers):
    """PRD §2.9: "Reusing a key with a request body different from the original
    submission is rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409)."

    Design: Corner/errors/idempotency_replay_with_different_body_returns_mismatch
    """
    set_clock("2026-09-01T00:00:00Z")
    key = "replay-key-0001"
    resp1 = api.create_jurisdiction(
        create_jurisdiction_payload(code="JG"), platform_admin_headers, idem_key=key
    )
    data = validate_success(resp1, 201)
    assert_jurisdiction(data)
    resp2 = api.create_jurisdiction(
        create_jurisdiction_payload(
            code="JG-DIFFERENT",
            name="J-G-DIFFERENT",
            permits_prescriptive_printed_path=False,
        ),
        platform_admin_headers,
        idem_key=key,
    )
    validate_error(resp2, ApiErrorId.ERR_IDEMPOTENCY_REPLAY_MISMATCH)


def test_idempotency_replay_identical_body_returns_original(api, platform_admin_headers):
    """PRD §2.9: "Reusing a key with an identical body returns the original
    response without re-executing the side effects."

    Design: Corner/errors/idempotency_replay_with_different_body_returns_mismatch
    """
    set_clock("2026-09-01T00:00:00Z")
    key = "replay-key-0002"
    payload = create_jurisdiction_payload(code="JG2")
    resp1 = api.create_jurisdiction(payload, platform_admin_headers, idem_key=key)
    data1 = validate_success(resp1, 201)
    resp2 = api.create_jurisdiction(payload, platform_admin_headers, idem_key=key)
    data2 = validate_success(resp2, 201)
    assert data2["id"] == data1["id"], (
        "Identical replay must return the original resource, not a new one"
    )


def test_print_operator_cannot_decide_permit(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists
    the permit-application action capability as authorized for PermitCoordinator
    and JurisdictionReviewer only.

    Design: Corner/validations/print_operator_cannot_decide_permit
    """
    from test_helpers import PERMIT_COORD

    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JN")
    _plan, revision = create_approved_plan_revision()
    site = create_site(jurisdiction["id"], address="15 J")
    app = get_success_data(
        api.create_permit_application(
            site["id"], create_permit_application_payload(revision["id"]), PERMIT_COORD
        )
    )
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    get_success_data(
        api.permit_application_action(
            site["id"], app["id"], {"action": "PAY_FEE", "amount_cents": 99999999}, PERMIT_COORD
        )
    )
    resp = api.permit_application_action(
        site["id"], app["id"], {"action": "DECIDE", "decision": "APPROVE"}, PRINT_OP
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_trade_contractor_cannot_create_permit_application(api, trade_contractor_headers):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists
    opening a permit application as a PermitCoordinator capability.

    Design: Corner/rbac/trade_contractor_cannot_create_permit_application
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JH")
    _plan, revision = create_approved_plan_revision()
    site = create_site(jurisdiction["id"], address="25 O")
    resp = api.create_permit_application(
        site["id"],
        create_permit_application_payload(revision["id"]),
        trade_contractor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_engineer_self_approval_violates_segregation_of_duties(api):
    """PRD §3.3: "the decider's `X-User-ID` must differ from
    `engineer_reviewer_id`, and a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/engineer_self_approval_violates_segregation_of_duties
    """
    set_clock("2026-09-01T00:00:00Z")
    alice = make_engineer_headers("eng-alice")
    plan = get_success_data(
        api.create_structural_plan(create_structural_plan_payload(), alice)
    )
    revision = get_success_data(
        api.create_plan_revision(plan["id"], create_plan_revision_payload(), alice)
    )
    get_success_data(
        api.plan_revision_action(plan["id"], revision["id"], {"action": "SUBMIT"}, alice)
    )
    resp = api.plan_revision_action(plan["id"], revision["id"], {"action": "APPROVE"}, alice)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    revisions, _meta = validate_paginated(api.list_plan_revisions(plan["id"], alice))
    current = next(r for r in revisions if r["id"] == revision["id"])
    assert current["status"] == "SUBMITTED", (
        "rejected decide must leave the revision SUBMITTED"
    )


def test_stale_version_occ_on_printer_setup_create(api, print_operator_headers):
    """PRD §2.8: "If `expected_site_version` does not match the site's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_version_occ_on_printer_setup_create
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JF")
    site = create_site(jurisdiction["id"], address="23 N")
    stale_version = site["version"]
    # The foundation pour increments the site's version (PRD §3.2), making the
    # captured version stale.
    get_success_data(api.site_action(site["id"], {"action": "POUR_FOUNDATION"}, SITE_MGR))
    resp = api.create_printer_setup(
        site["id"], create_printer_setup_payload(stale_version), print_operator_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_version_increments_on_every_mutation(api):
    """PRD §3.2: "it also increments the site's `version` by 1." PRD §3.4:
    "the creation itself increments the site's `version` by 1" and the advance
    "increments the site's `version` by 1".

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JK2")
    site = create_site(jurisdiction["id"], address="29 Q")
    v1 = site["version"]
    get_success_data(api.site_action(site["id"], {"action": "POUR_FOUNDATION"}, SITE_MGR))
    v2 = current_site_version(site["id"])
    setup = get_success_data(
        api.create_printer_setup(site["id"], create_printer_setup_payload(v2), PRINT_OP)
    )
    v3 = current_site_version(site["id"])
    get_success_data(
        api.advance_printer_setup(site["id"], setup["id"], {"to_state": "LEVELED"}, PRINT_OP)
    )
    v4 = current_site_version(site["id"])
    assert v1 == 1, f"new site version must be 1, got {v1}"
    assert v2 == v1 + 1, f"foundation pour must bump version: {v1} -> {v2}"
    assert v3 == v2 + 1, f"printer-setup create must bump version: {v2} -> {v3}"
    assert v4 == v3 + 1, f"printer-setup level must bump version: {v3} -> {v4}"
