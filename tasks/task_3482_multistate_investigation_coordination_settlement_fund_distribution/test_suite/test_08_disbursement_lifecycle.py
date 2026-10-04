"""Disbursement lifecycle: release cascade consistency, ownership scoping,
legislative certification windows, and list pagination.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    PAST_APPROPRIATION_WINDOW,
    api_client,
    deposit_funds,
    fund_world,
    get_allocation_line,
    make_lead_state_ag_headers,
    make_state_legislature_headers,
    release_disbursement,
    request_disbursement,
    set_clock,
    setup_executed_world,
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


def _line(world, code):
    return {l["state_code"]: l for l in world["lines"]}[code]


def test_immediate_read_after_release():
    """PRD section 3.5: "A release stamps `released_at` and cascades: the
    amount is added to the settlement's `released_cents`; the line's
    `disbursed_cents` grows by the amount and its `remaining_cents` is
    recomputed under the gross-share invariant."
    PRD section 2.9: "When a single operation mutates more than one entity,
    every cascade is applied atomically as part of that operation."

    Design: Corner/consistency_model/immediate_read_after_release
    """
    world = setup_executed_world()
    fund_world(world)
    ca_line = _line(world, "CA")
    disb = request_disbursement(
        ca_line, world["offices"]["CA"], True,
        amount_cents=1000000, use_code="PROGRAM",
    )
    assert disb["status"] == "CERTIFIED"  # PREAPPROPRIATED auto-certification
    released = release_disbursement(disb["id"])
    assert released["status"] == "RELEASED"
    assert _same_instant(released["released_at"], "2026-09-01T00:00:00Z")
    line = get_allocation_line(ca_line["id"])
    assert line["disbursed_cents"] == 1000000
    assert line["remaining_cents"] == 11937500
    assert line["status"] == "DISBURSING", (
        "1,000,000 of a 12,937,500 gross share leaves the line DISBURSING"
    )


def test_cross_state_disbursement_request_denied():
    """PRD section 3.5: "The caller is the office itself — a
    `ParticipatingStateAG` or `LeadStateAG` whose `X-User-ID` equals the
    line's `state_office_id`."
    PRD section 2.1: "A caller failing this check is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/cross_state_disbursement_request_denied
    """
    world = setup_executed_world()
    fund_world(world)
    ca_line = _line(world, "CA")
    resp = api_client.create_disbursement(
        ca_line["id"], {"amount_cents": 1000, "use_code": "PROGRAM"},
        make_lead_state_ag_headers(world["offices"]["TX"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_legislature_cannot_certify_other_state():
    """PRD section 2.1: "`StateLegislature` — the legislative appropriations
    authority of a state, which certifies disbursements for its own state
    only. ... ownership checks compare the target disbursement's office to
    it."
    PRD section 2.1: "A request whose role is not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 2.1: "A caller failing this check is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/legislature_cannot_certify_other_state
    """
    world = setup_executed_world()
    fund_world(world)
    ny_line = _line(world, "NY")
    disb = request_disbursement(
        ny_line, world["offices"]["NY"], False,
        amount_cents=1000000, use_code="PROGRAM",
    )
    assert disb["status"] == "REQUESTED"  # CERTIFICATION_REQUIRED waits
    resp_wrong_state = api_client.certify_disbursement(
        disb["id"], make_state_legislature_headers(world["offices"]["TX"]["id"]),
    )
    validate_error(resp_wrong_state, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    resp_wrong_role = api_client.certify_disbursement(disb["id"], CHAIR)
    validate_error(resp_wrong_role, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_certification_window_closed_blocks_certify():
    """PRD section 3.5: "a `StateLegislature` caller whose `X-User-ID` equals
    the line's office certifies the request, lawful only from `REQUESTED`
    (else `ERR_INVALID_STATE`) and only at or before the certification
    deadline, which is the settlement's `executed_at` plus 180 days.
    Certification attempted after that window is rejected with
    `ERR_CERTIFICATION_WINDOW_CLOSED` (HTTP 422) and mutates nothing."

    Design: Corner/errors/certification_window_closed_blocks_certify
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    ny_line = _line(world, "NY")
    deposit_funds(stl_id, 50000000)
    disb = request_disbursement(
        ny_line, world["offices"]["NY"], False,
        amount_cents=1000000, use_code="PROGRAM",
    )
    assert disb["status"] == "REQUESTED"
    set_clock(PAST_APPROPRIATION_WINDOW)  # executed_at + 181 days
    resp = api_client.certify_disbursement(
        disb["id"], make_state_legislature_headers(world["offices"]["NY"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_WINDOW_CLOSED)
    disbs, _ = validate_paginated(
        api_client.list_allocation_line_disbursements(ny_line["id"], CHAIR)
    )
    assert disbs[0]["status"] == "REQUESTED", (
        "the rejected certification mutates nothing"
    )


def test_list_pagination_envelope():
    """PRD section 2.3: "List responses carry four pagination fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`, where `total_count` reports the full size of the
    underlying collection and `has_more` indicates whether further items exist
    beyond the returned page."
    PRD section 2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100."

    Design: Corner/endpoints/list_pagination_envelope
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    page1, meta1 = validate_paginated(
        api_client.list_settlement_allocation_lines(
            stl_id, CHAIR, params={"limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api_client.list_settlement_allocation_lines(
            stl_id, CHAIR, params={"limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    ids = {l["id"] for l in page1} | {l["id"] for l in page2}
    assert len(ids) == 3, "pages tile the collection without overlap"
