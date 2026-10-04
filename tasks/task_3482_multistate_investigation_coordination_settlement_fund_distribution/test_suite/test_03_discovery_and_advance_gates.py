"""Phase advancement gates, demand issuance preconditions, and consolidated
response lifecycle (accept/fulfill validity and the consolidation cascade).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    accept_response,
    advance_investigation,
    advance_payload,
    create_investigation,
    create_participation_payload,
    create_response_payload,
    designate_lead,
    execute_cia,
    get_investigation,
    invite_participation,
    issue_demand,
    make_lead_state_ag_headers,
    make_participating_state_ag_headers,
    propose_settlement,
    setup_offices,
    setup_open_world,
    setup_negotiation_world,
    submit_response,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
COUNSEL = TEST_USERS["defendant_counsel_headers"]


def test_advance_skip_phase_returns_invalid_phase():
    """PRD section 3.2: "Every manual advance names its target in `to_phase`
    and moves exactly one step along the declared chain — `OPEN`, `DISCOVERY`,
    `NEGOTIATION`, `SETTLEMENT_PENDING`, `SETTLED`, `MONITORING` are the
    settable targets; `CLOSED` is reached only automatically — and an advance
    that skips steps, names an unreachable target, or is attempted from a
    phase the chain does not connect is rejected with `ERR_INVALID_PHASE`."

    Design: Corner/state_machines/advance_skip_phase_returns_invalid_phase
    """
    inv = create_investigation()
    resp_skip = api_client.advance_investigation(
        inv["id"], advance_payload("DISCOVERY"), CHAIR,
    )
    validate_error(resp_skip, ApiErrorId.ERR_INVALID_PHASE)
    resp_auto = api_client.advance_investigation(
        inv["id"], advance_payload("CLOSED"), CHAIR,
    )
    validate_error(resp_auto, ApiErrorId.ERR_INVALID_PHASE)
    assert get_investigation(inv["id"])["phase"] == "DRAFT"


def test_advance_gates_require_prerequisites():
    """PRD section 3.2: "Advancing the investigation from `DISCOVERY` to
    `NEGOTIATION` requires that at least one consolidated response of the
    investigation have status `ACCEPTED` or `FULFILLED`; without one the
    advance is rejected with `ERR_NO_ACCEPTED_RESPONSE` (HTTP 422)."
    PRD section 3.3: "Once the active settlement's `term_status` is
    `TERMS_AGREED` (or later `SIGN_ON_OPEN`), the chair may advance the
    investigation `NEGOTIATION` → `SETTLEMENT_PENDING`; attempting that
    advance without such a settlement is rejected with
    `ERR_NO_AGREED_SETTLEMENT` (HTTP 422)."

    Design: Corner/errors/advance_gates_require_prerequisites
    """
    world = setup_open_world(office_codes=("CA", "TX", "NY"))
    inv_id = world["investigation"]["id"]
    advance_investigation(inv_id, "DISCOVERY")
    resp_early = api_client.advance_investigation(
        inv_id, advance_payload("NEGOTIATION"), CHAIR,
    )
    validate_error(resp_early, ApiErrorId.ERR_NO_ACCEPTED_RESPONSE)
    demand = issue_demand(world["participations"]["CA"])
    response = submit_response(inv_id, [demand["id"]])
    accept_response(response["id"], world["offices"]["CA"])
    advance_investigation(inv_id, "NEGOTIATION")
    propose_settlement(inv_id, world["offices"]["CA"])
    resp_no_agreement = api_client.advance_investigation(
        inv_id, advance_payload("SETTLEMENT_PENDING"), CHAIR,
    )
    validate_error(resp_no_agreement, ApiErrorId.ERR_NO_AGREED_SETTLEMENT)
    assert get_investigation(inv_id)["phase"] == "NEGOTIATION"


def test_demand_issuance_requires_active_participation():
    """PRD section 3.2: "Issuance from a participation that is not `ACTIVE` —
    the common interest agreement must be executed first — is rejected with
    `ERR_PARTICIPATION_INACTIVE` (HTTP 409), and issuance is lawful only while
    the investigation is in `OPEN` or `DISCOVERY` phase."

    Design: Difficulty/cross_entity_state_dependency/demand_issuance_requires_active_participation
    """
    offices = setup_offices()
    inv = create_investigation()
    parts = {}
    for code in ("CA", "TX", "NY", "FL"):
        parts[code] = invite_participation(inv["id"], offices[code]["id"])
    for code, tier in (("CA", "LEAD_ONLY"), ("TX", "RESTRICTED"), ("NY", "STANDARD")):
        parts[code] = execute_cia(parts[code], tier)
    designate_lead(parts["CA"]["id"])
    designate_lead(parts["TX"]["id"])
    advance_investigation(inv["id"], "OPEN")
    resp = api_client.create_demand(
        parts["FL"]["id"], {"scope_text": "FL sales records"},
        make_participating_state_ag_headers(offices["FL"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPATION_INACTIVE)
    demands, meta = validate_paginated(
        api_client.list_participation_demands(parts["FL"]["id"], CHAIR)
    )
    assert demands == [] and meta["total_count"] == 0, (
        "no demand may be persisted for an INVITED participation"
    )


def test_fulfill_unaccepted_response_returns_invalid_state():
    """PRD section 3.2: "When the defendant has produced everything promised,
    the `DefendantCounsel` marks the response fulfilled, moving `ACCEPTED` →
    `FULFILLED` and stamping `fulfilled_at`."
    PRD section 2.8: "the target resource's own state machine must admit the
    trigger (`ERR_INVALID_STATE`, ...)."

    Design: Corner/state_machines/fulfill_unaccepted_response_returns_invalid_state
    """
    world = setup_open_world(office_codes=("CA", "TX", "NY"))
    inv_id = world["investigation"]["id"]
    advance_investigation(inv_id, "DISCOVERY")
    demand = issue_demand(world["participations"]["CA"])
    response = submit_response(inv_id, [demand["id"]])
    resp = api_client.fulfill_response(response["id"], COUNSEL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_accept_response_twice_returns_invalid_state():
    """PRD section 3.2: "acceptance by a `LeadStateAG` whose office holds a
    `LEAD`, `ACTIVE` participation in this investigation moves the response
    `SUBMITTED` → `ACCEPTED` (from any other status the attempt fails with
    `ERR_INVALID_STATE`), stamps `accepted_at`, and — as one atomic cascade —
    folds every listed demand from `ISSUED` to `CONSOLIDATED`, stamping each
    demand's `consolidated_at` and writing the accepted response's id into its
    `consolidated_response_id`."

    Design: Corner/state_machines/accept_response_twice_returns_invalid_state
    """
    world = setup_open_world(office_codes=("CA", "TX", "NY"))
    inv_id = world["investigation"]["id"]
    advance_investigation(inv_id, "DISCOVERY")
    demand = issue_demand(world["participations"]["CA"])
    response = submit_response(inv_id, [demand["id"]])
    accept_response(response["id"], world["offices"]["CA"])
    resp = api_client.accept_response(
        response["id"], make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    demands, _ = validate_paginated(
        api_client.list_participation_demands(
            world["participations"]["CA"]["id"], CHAIR,
        )
    )
    assert demands[0]["status"] == "CONSOLIDATED"
    assert demands[0]["consolidated_response_id"] == response["id"]


def test_accept_response_consolidates_demands_side_effect():
    """PRD section 3.2: "acceptance by a `LeadStateAG` whose office holds a
    `LEAD`, `ACTIVE` participation in this investigation moves the response
    `SUBMITTED` → `ACCEPTED` ... and — as one atomic cascade — folds every
    listed demand from `ISSUED` to `CONSOLIDATED`, stamping each demand's
    `consolidated_at` and writing the accepted response's id into its
    `consolidated_response_id`."

    Design: Corner/endpoints/accept_response_consolidates_demands_side_effect
    """
    world = setup_open_world(office_codes=("CA", "TX", "NY"))
    inv_id = world["investigation"]["id"]
    advance_investigation(inv_id, "DISCOVERY")
    d_ca = issue_demand(world["participations"]["CA"], "CA pricing documents")
    d_tx = issue_demand(world["participations"]["TX"], "TX sales records")
    response = submit_response(
        inv_id, [d_ca["id"], d_tx["id"]], coverage_summary="Joint production",
    )
    accept_response(response["id"], world["offices"]["CA"])
    for code, demand in (("CA", d_ca), ("TX", d_tx)):
        demands, _ = validate_paginated(
            api_client.list_participation_demands(
                world["participations"][code]["id"], CHAIR,
            )
        )
        assert demands[0]["id"] == demand["id"]
        assert demands[0]["status"] == "CONSOLIDATED", (
            f"demand of {code} must be CONSOLIDATED after acceptance"
        )
        assert demands[0]["consolidated_response_id"] == response["id"]
        assert demands[0]["consolidated_at"] is not None


def test_response_covering_consolidated_demand_rejected():
    """PRD section 3.2: "Submission carries `demand_ids` — a non-empty array
    in which every id must resolve to a demand of this same investigation
    whose status is still `ISSUED`; an empty list, a demand from another
    investigation, or a demand already consolidated is rejected with
    `ERR_RESPONSE_DEMANDS_INVALID` (HTTP 422)."

    Design: Corner/errors/response_covering_consolidated_demand_rejected
    """
    world = setup_negotiation_world()
    inv_id = world["investigation"]["id"]
    consolidated_demand_id = world["demands"]["CA"]["id"]
    resp = api_client.create_response(
        inv_id,
        create_response_payload([consolidated_demand_id],
                                coverage_summary="Second pass"),
        COUNSEL,
    )
    validate_error(resp, ApiErrorId.ERR_RESPONSE_DEMANDS_INVALID)


def test_lead_window_capacity_conflict_on_second_investigation():
    """PRD section 3.1: "no office holding `LEAD` on this investigation may
    simultaneously hold `committee_role` `LEAD` on another investigation whose
    phase is `OPEN`, `DISCOVERY`, `NEGOTIATION`, or `SETTLEMENT_PENDING`" and
    "A conflict is rejected with `ERR_LEAD_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lead_window_capacity_conflict_on_second_investigation
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
    for code, tier in (("CA", "LEAD_ONLY"), ("NY", "RESTRICTED"), ("FL", "STANDARD")):
        p2[code] = execute_cia(p2[code], tier)
    designate_lead(p2["CA"]["id"])
    designate_lead(p2["NY"]["id"])
    resp = api_client.advance_investigation(inv2["id"], advance_payload("OPEN"), CHAIR)
    validate_error(resp, ApiErrorId.ERR_LEAD_WINDOW_OVERLAP)
    assert get_investigation(inv2["id"])["phase"] == "DRAFT", (
        "inv2 must remain DRAFT after the rejected activation"
    )
