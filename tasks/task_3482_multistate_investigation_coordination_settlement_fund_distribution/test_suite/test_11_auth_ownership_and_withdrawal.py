"""Authentication, authorization ordering, office optimistic concurrency,
withdrawal gating and side effects, and cross-investigation lead scoping.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    advance_investigation,
    advance_payload,
    create_investigation,
    create_state_office,
    designate_lead,
    execute_cia,
    invite_participation,
    issue_demand,
    make_lead_state_ag_headers,
    patch_state_office_payload,
    record_sign_ons,
    setup_offices,
    setup_open_world,
    setup_sign_on_open_world,
    submit_response,
    validate_error,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
FUND_ADMIN = TEST_USERS["fund_administrator_headers"]


def _same_instant(actual: str, expected: str) -> bool:
    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == (
        datetime.fromisoformat(expected.replace("Z", "+00:00"))
    )


def test_role_check_precedes_existence():
    """PRD section 2.8: "2. **Role authorization** — the caller's role must be
    permitted on the endpoint (`ERR_UNAUTHORIZED_ROLE`)." comes before
    "4. **Path existence** — path identifiers are resolved left to right along
    the URL hierarchy."
    PRD section 2.8: "Every request is evaluated against a fixed ladder of
    checks, and the first failure wins — no later check runs once an earlier
    one has rejected the request."

    Design: Corner/validations/role_check_precedes_existence
    """
    create_investigation()
    resp = api_client.advance_investigation(
        NON_EXISTENT_UUID, advance_payload("OPEN"), FUND_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_missing_auth_header_returns_unauthenticated():
    """PRD section 2.1: "A request whose `X-User-Role` header is missing or
    names no declared role, or whose `X-User-ID` is missing although the named
    role is entity-backed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    inv = create_investigation()
    resp = api_client.get_investigation(inv["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_office_patch_stale_version_returns_412():
    """PRD section 2.5: "Updating a state office requires
    `expected_state_office_version` in the same fashion: a mismatch with the
    office's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412), since allocation-relevant fields such as `population` and
    `harm_measure_cents` may have changed underneath the caller."
    PRD section 2.5: "The `version` is an integer that starts at its initial
    value on creation and increments by exactly 1 on every mutation of the
    resource."

    Design: Corner/complexity_layers/office_patch_stale_version_returns_412
    """
    ca = create_state_office(state_code="CA")
    v0 = ca["version"]
    first = api_client.patch_state_office(
        ca["id"], patch_state_office_payload(v0, population=150), CHAIR,
    )
    patched = validate_success(first)
    assert patched["population"] == 150
    assert patched["version"] == v0 + 1
    resp = api_client.patch_state_office(
        ca["id"], patch_state_office_payload(v0, population=999), CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    fresh = validate_success(api_client.get_state_office(ca["id"], CHAIR))
    assert fresh["population"] == 150, "the stale replay changes nothing"
    assert fresh["version"] == v0 + 1


def test_withdraw_after_sign_on_blocked():
    """PRD section 3.1: "Withdrawal is refused with
    `ERR_SIGNED_STATE_CANNOT_WITHDRAW` (HTTP 409) while the office holds a
    sign-on entry in `SIGNED` or `LOCKED` status on any settlement of this
    investigation whose `term_status` is neither `COLLAPSED` nor
    `CLOSED_OUT`."

    Design: Corner/state_machines/withdraw_after_sign_on_blocked
    """
    world = setup_sign_on_open_world()
    record_sign_ons(world, {"CA": "SIGNED"})
    p_ca = world["participations"]["CA"]
    resp = api_client.withdraw_participation(
        p_ca["id"], make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SIGNED_STATE_CANNOT_WITHDRAW)
    fresh = validate_success(api_client.get_participation(p_ca["id"], CHAIR))
    assert fresh["status"] == "ACTIVE"
    assert fresh["committee_role"] == "LEAD"


def test_withdraw_lead_resets_committee_role():
    """PRD section 3.1: "An office leaves a matter by withdrawing, moving its
    participation `ACTIVE` → `WITHDRAWN`; the office itself (either AG role,
    matched by `X-User-ID`) or the `CommitteeChair` may perform the
    withdrawal." and "A completed withdrawal resets `committee_role` to
    `MEMBER` and stamps `withdrawn_at`."

    Design: Corner/state_machines/withdraw_lead_resets_committee_role
    """
    world = setup_open_world()
    p_tx = world["participations"]["TX"]
    resp = api_client.withdraw_participation(
        p_tx["id"], make_lead_state_ag_headers(world["offices"]["TX"]["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "WITHDRAWN"
    assert data["committee_role"] == "MEMBER", "the lead seat is forfeited"
    assert _same_instant(data["withdrawn_at"], "2026-09-01T00:00:00Z")


def test_lead_of_other_investigation_cannot_accept_response():
    """PRD section 2.1: "lead-gated operations (proposing or revising a
    settlement, accepting a consolidated response) additionally require that
    the caller's office hold a `LEAD` and `ACTIVE` participation in the
    relevant investigation. A caller failing this check is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/lead_of_other_investigation_cannot_accept_response
    """
    offices = setup_offices()
    inv1 = create_investigation(title="Probe one", summary="First matter")
    p1 = {}
    for code in ("CA", "TX", "NY"):
        p1[code] = invite_participation(inv1["id"], offices[code]["id"])
    for code, tier in (("CA", "LEAD_ONLY"), ("TX", "RESTRICTED"), ("NY", "STANDARD")):
        p1[code] = execute_cia(p1[code], tier)
    designate_lead(p1["CA"]["id"])
    designate_lead(p1["TX"]["id"])
    advance_investigation(inv1["id"], "OPEN")
    inv2 = create_investigation(
        title="Probe two", target_name="Beta LLC", summary="Second matter",
    )
    p2 = {}
    for code in ("CA", "NY", "FL"):
        p2[code] = invite_participation(inv2["id"], offices[code]["id"])
    for code, tier in (("CA", "STANDARD"), ("NY", "LEAD_ONLY"), ("FL", "RESTRICTED")):
        p2[code] = execute_cia(p2[code], tier)
    designate_lead(p2["NY"]["id"])
    designate_lead(p2["FL"]["id"])
    advance_investigation(inv2["id"], "OPEN")
    advance_investigation(inv2["id"], "DISCOVERY")
    demand = issue_demand(p2["NY"], "NY records")
    response = submit_response(inv2["id"], [demand["id"]])
    # CA leads inv1 but is a STANDARD-tier MEMBER of inv2.
    resp = api_client.accept_response(
        response["id"], make_lead_state_ag_headers(offices["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
