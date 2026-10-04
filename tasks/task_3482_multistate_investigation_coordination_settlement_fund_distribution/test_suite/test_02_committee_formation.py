"""Committee formation: invitation defaults, duplicate participation, lead
designation gates, activation quorum, and role/ownership checks on
designation and CIA execution.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_participation,
    advance_payload,
    create_investigation,
    create_participation_payload,
    create_state_office,
    designate_lead,
    execute_cia,
    execute_cia_payload,
    get_investigation,
    invite_participation,
    make_participating_state_ag_headers,
    setup_offices,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]


def _same_instant(actual: str, expected: str) -> bool:
    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == (
        datetime.fromisoformat(expected.replace("Z", "+00:00"))
    )


def test_participation_invite_initial_parallel_dimensions():
    """PRD section 3.1: "each invitation names a `state_office_id` and creates
    a participation row in `INVITED` status with `invited_at` set to the
    current logical time, its `investigation_id` pointing at the matter, its
    `cia_status` at `NOT_EXECUTED`, its `cia_tier` null, and its
    `committee_role` at `MEMBER`."

    Design: Corner/entities/participation_invite_initial_parallel_dimensions
    """
    ca = create_state_office(state_code="CA")
    inv = create_investigation()
    resp = api_client.create_participation(
        inv["id"], create_participation_payload(ca["id"]), CHAIR,
    )
    data = validate_success(resp, 201)
    assert_participation(data)
    assert data["status"] == "INVITED"
    assert data["cia_status"] == "NOT_EXECUTED"
    assert data["committee_role"] == "MEMBER"
    assert data["cia_tier"] is None
    assert data["investigation_id"] == inv["id"]
    assert _same_instant(data["invited_at"], "2026-09-01T00:00:00Z"), (
        f"invited_at must be the logical clock value, got {data['invited_at']}"
    )


def test_duplicate_participation_rejected():
    """PRD section 3.1: "One office may hold only one non-`WITHDRAWN`
    participation per investigation; a second live invitation for the same
    office is rejected with `ERR_DUPLICATE_PARTICIPATION` (HTTP 409)."

    Design: Corner/errors/duplicate_participation_rejected
    """
    ca = create_state_office(state_code="CA")
    inv = create_investigation()
    invite_participation(inv["id"], ca["id"])
    resp = api_client.create_participation(
        inv["id"], create_participation_payload(ca["id"]), CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARTICIPATION)
    lst, meta = validate_paginated(
        api_client.list_investigation_participations(inv["id"], CHAIR)
    )
    assert meta["total_count"] == 1 and len(lst) == 1, (
        "exactly one Participation may exist for CA in this investigation"
    )


def test_designate_lead_gates_rejected():
    """PRD section 3.1: "Designation requires the participation to be `ACTIVE`
    (else `ERR_PARTICIPATION_INACTIVE`), its `cia_tier` to be `RESTRICTED` or
    `LEAD_ONLY` — a `STANDARD`-tier office cannot lead, and the attempt is
    rejected with `ERR_CIA_TIER_INSUFFICIENT` (HTTP 422) — and the
    investigation's phase to be `DRAFT` or `OPEN` (else `ERR_INVALID_PHASE`)."

    Design: Corner/state_machines/designate_lead_gates_rejected
    """
    offices = setup_offices(("NY", "FL"))
    inv = create_investigation()
    p_ny = invite_participation(inv["id"], offices["NY"]["id"])
    p_fl = invite_participation(inv["id"], offices["FL"]["id"])
    execute_cia(p_ny, "STANDARD")
    resp_invited = api_client.designate_lead(p_fl["id"], CHAIR)
    validate_error(resp_invited, ApiErrorId.ERR_PARTICIPATION_INACTIVE)
    resp_standard = api_client.designate_lead(p_ny["id"], CHAIR)
    validate_error(resp_standard, ApiErrorId.ERR_CIA_TIER_INSUFFICIENT)


def test_activation_quorum_missing():
    """PRD section 3.1: "the matter must field at least 2 `ACTIVE`
    participations whose `committee_role` is `LEAD`, and at least 3 `ACTIVE`
    participations in total, with withdrawn offices excluded from both counts;
    falling short on either leg is rejected with
    `ERR_ACTIVATION_QUORUM_MISSING` (HTTP 422)."

    Design: Corner/errors/activation_quorum_missing
    """
    offices = setup_offices(("CA", "TX", "NY"))
    inv = create_investigation()
    tiers = {"CA": "LEAD_ONLY", "TX": "RESTRICTED", "NY": "STANDARD"}
    parts = {}
    for code in ("CA", "TX", "NY"):
        part = invite_participation(inv["id"], offices[code]["id"])
        parts[code] = execute_cia(part, tiers[code])
    designate_lead(parts["CA"]["id"])
    resp = api_client.advance_investigation(inv["id"], advance_payload("OPEN"), CHAIR)
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_QUORUM_MISSING)
    assert get_investigation(inv["id"])["phase"] == "DRAFT", (
        "a failed activation leaves the investigation in DRAFT"
    )


def test_member_state_cannot_designate_lead():
    """PRD section 4: the designate-lead endpoint is authorized for
    CommitteeChair only.
    PRD section 2.1: "A request whose role is not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/member_state_cannot_designate_lead
    """
    offices = setup_offices(("CA", "TX"))
    inv = create_investigation()
    p_ca = invite_participation(inv["id"], offices["CA"]["id"])
    p_ca = execute_cia(p_ca, "LEAD_ONLY")
    resp = api_client.designate_lead(
        p_ca["id"], make_participating_state_ag_headers(offices["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    fresh = validate_success(api_client.get_participation(p_ca["id"], CHAIR))
    assert fresh["committee_role"] == "MEMBER"


def test_ownership_check_blocks_cross_office_cia():
    """PRD section 3.1: "The caller must be a `ParticipatingStateAG` or
    `LeadStateAG` whose `X-User-ID` equals the participation's
    `state_office_id`."
    PRD section 2.1: "A caller failing this check is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/ownership_check_blocks_cross_office_cia
    """
    offices = setup_offices(("CA", "TX"))
    inv = create_investigation()
    p_ca = invite_participation(inv["id"], offices["CA"]["id"])
    resp = api_client.execute_cia(
        p_ca["id"], execute_cia_payload(confidentiality_tier="STANDARD"),
        make_participating_state_ag_headers(offices["TX"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
