"""Warranty claims: the registration gate, the adjudication loop (review,
info-request, deny, reopen, escalate), coverage determination boundaries, the
goodwill cap, and the provisional/final settlement duality.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_claim,
    adjudicate_claim_payload,
    create_claim,
    create_part,
    create_warranty_claim_payload,
    set_logical_clock,
    setup_in_season_with_sale,
    transition_sale,
    validate_error,
    validate_success,
    walk_claim_to_state,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]


def _adjudicate(api, claim_id, action, **kwargs):
    return api.adjudicate_claim(claim_id, adjudicate_claim_payload(action, **kwargs), headers=AGENT)


def test_claim_on_unregistered_sale_rejected(api):
    """PRD 3.7: "registration is the gate: filing against a sale still `SOLD` is
    rejected with `ERR_SALE_NOT_REGISTERED`, and filing against a `RETURNED` sale with
    `ERR_SALE_RETURNED`."
    PRD 2.8: "Identifiers carried in a request body are resolved with the same
    discipline: a `channel_account_id` that names no existing channel yields
    `ERR_CHANNEL_NOT_FOUND`, and likewise for any other body-carried reference."

    Design: Corner/validations/claim_on_unregistered_sale_rejected
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    ghost = api.create_warranty_claim(
        create_warranty_claim_payload("00000000-0000-4000-8000-0000000000dd", "BURNER", "ghost sale"),
        headers=AGENT)
    validate_error(ghost, ApiErrorId.ERR_SALE_NOT_FOUND)
    unregistered = api.create_warranty_claim(
        create_warranty_claim_payload(bundle["sale"]["id"], "BURNER", "Burner issue"), headers=AGENT)
    validate_error(unregistered, ApiErrorId.ERR_SALE_NOT_REGISTERED)


def test_claim_on_returned_sale_rejected(api):
    """PRD 3.7: "registration is the gate: filing against a sale still `SOLD` is
    rejected with `ERR_SALE_NOT_REGISTERED`, and filing against a `RETURNED` sale with
    `ERR_SALE_RETURNED`."

    Design: Corner/validations/claim_on_returned_sale_rejected
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")  # REGISTERED at creation
    transition_sale(bundle["sale"], "RETURN")
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(bundle["sale"]["id"], "GRATE", "Grate warped"), headers=AGENT)
    validate_error(resp, ApiErrorId.ERR_SALE_RETURNED)


def test_claim_info_request_round_trip(api):
    """PRD 3.7: "Requesting information moves `UNDER_REVIEW → INFO_REQUESTED`, and
    submitting it returns `INFO_REQUESTED → UNDER_REVIEW`."
    PRD 3.7: "a burner claim schedules 3200 cents of parts and 4500 cents of labor"

    Design: Corner/state_machines/claim_info_request_round_trip
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")
    claim = create_claim(bundle["sale"]["id"], component="BURNER", failure_description="Burner flame uneven")
    adjudicate_claim(claim["id"], "REVIEW")
    asking = validate_success(_adjudicate(api, claim["id"], "REQUEST_INFO"), 200)
    assert asking["status"] == "INFO_REQUESTED"
    supplied = validate_success(_adjudicate(api, claim["id"], "SUBMIT_INFO"), 200)
    assert supplied["status"] == "UNDER_REVIEW"
    approved = validate_success(_adjudicate(api, claim["id"], "APPROVE"), 200)
    assert approved["status"] == "APPROVED"
    assert approved["provisional_settlement_cents"] == 7700, "3200 part + 4500 labor, computed once at approval"


def test_warranty_claim_denied_reopened_cycle(api):
    """PRD 3.7: "Reviewing moves `SUBMITTED → UNDER_REVIEW`, and likewise `REOPENED →
    UNDER_REVIEW`."
    PRD 3.7: "Denying moves either `UNDER_REVIEW` or `ESCALATED → DENIED`, stamping
    `denied_at` from the logical clock"
    PRD 3.7: "A denied claim may be reopened — `DENIED → REOPENED` — only while the
    logical clock remains within 30 days of `denied_at`"

    Design: Difficulty/non_linear_state_machine/warranty_claim_denied_reopened_cycle
    """
    bundle = setup_in_season_with_sale()  # logical clock parked at 2026-04-01
    claim = create_claim(bundle["sale"]["id"], component="BURNER", failure_description="Burner tube rusted through")
    st1 = validate_success(_adjudicate(api, claim["id"], "REVIEW"), 200)
    assert st1["status"] == "UNDER_REVIEW"
    st2 = validate_success(_adjudicate(api, claim["id"], "DENY"), 200)
    assert st2["status"] == "DENIED"
    assert st2["denied_at"] == "2026-04-01T00:00:00Z", "denied_at is stamped from the logical clock"
    st3 = validate_success(_adjudicate(api, claim["id"], "REOPEN"), 200)
    assert st3["status"] == "REOPENED", "denied one minute ago: the 30-day window is wide open"
    st4 = validate_success(_adjudicate(api, claim["id"], "REVIEW"), 200)
    assert st4["status"] == "UNDER_REVIEW", "the loop re-enters review"
    st5 = validate_success(_adjudicate(api, claim["id"], "APPROVE"), 200)
    assert st5["status"] == "APPROVED"
    assert st5["provisional_settlement_cents"] == 7700


def test_reopen_after_thirty_day_window_rejected(api):
    """PRD 3.7: "A denied claim may be reopened — `DENIED → REOPENED` — only while the
    logical clock remains within 30 days of `denied_at`; once that reopen window has
    elapsed the attempt is `ERR_REOPEN_WINDOW_EXPIRED`."
    PRD 2.8: "the system validates the existence of each identifier in strict
    left-to-right order and rejects the request immediately with the 404 code of the
    first identifier that does not resolve"

    Design: Corner/validations/reopen_after_thirty_day_window_rejected
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")  # clock 2026-04-01
    claim = create_claim(bundle["sale"]["id"], component="BURNER", failure_description="Burner issue")
    denied = walk_claim_to_state(claim, "DENIED")
    assert denied["denied_at"] == "2026-04-01T00:00:00Z"
    set_logical_clock("2026-05-02T00:00:00Z")  # past denied_at + 30 days (2026-05-01)
    ghost = _adjudicate(api, "00000000-0000-4000-8000-0000000000ee", "REOPEN")
    validate_error(ghost, ApiErrorId.ERR_CLAIM_NOT_FOUND)
    expired = _adjudicate(api, claim["id"], "REOPEN")
    validate_error(expired, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)


def test_goodwill_cap_forces_escalation_before_approve(api):
    """PRD 3.7: "From `UNDER_REVIEW`, that provisional figure must not exceed the
    goodwill cap of 10000 cents, else the approval is rejected with
    `ERR_GOODWILL_CAP_EXCEEDED` and the claim must be escalated first; note that an
    electronics claim's provisional settlement is 12300 cents, which sits above the
    cap, so electronics claims can never be approved directly from review. Approving
    from `ESCALATED` bypasses the cap entirely."

    Design: Corner/validations/goodwill_cap_forces_escalation_before_approve
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")
    claim = create_claim(bundle["sale"]["id"], component="ELECTRONICS", failure_description="Controller dead")
    adjudicate_claim(claim["id"], "REVIEW")
    capped = _adjudicate(api, claim["id"], "APPROVE")
    validate_error(capped, ApiErrorId.ERR_GOODWILL_CAP_EXCEEDED)  # 12300 > 10000 from UNDER_REVIEW
    adjudicate_claim(claim["id"], "ESCALATE")
    approved = validate_success(_adjudicate(api, claim["id"], "APPROVE"), 200)
    assert approved["status"] == "APPROVED"
    assert approved["provisional_settlement_cents"] == 12300, "ESCALATED bypasses the cap; 4800 + 7500 = 12300"


def test_coverage_expiry_day_is_inclusive(api):
    """PRD 3.7: "A claim whose `claim_date` falls on or before the expiry day is
    `IN_COVERAGE` — the exact expiry day still counts. A claim falling after expiry
    but on or before 90 days past it is `GOODWILL_ELIGIBLE`. Anything later is
    `OUT_OF_COVERAGE`. Comparisons are at day granularity."

    Design: Difficulty/boundary_precision_check/coverage_expiry_day_is_inclusive
    """
    bundle = setup_in_season_with_sale()  # sold_at 2026-04-01; burner coverage 10 years
    set_logical_clock("2036-04-01T00:00:00Z")  # exactly sold_at + 10 years
    on_expiry = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(bundle["sale"]["id"], "BURNER", "Burner cracked on boundary day"),
        headers=AGENT), 201)
    assert on_expiry["coverage_determination"] == "IN_COVERAGE", "the exact expiry day still counts"
    set_logical_clock("2036-04-02T00:00:00Z")  # one day past expiry, inside the 90-day extension
    day_after = validate_success(api.create_warranty_claim(
        create_warranty_claim_payload(bundle["sale"]["id"], "BURNER", "Second burner issue one day later"),
        headers=AGENT), 201)
    assert day_after["coverage_determination"] == "GOODWILL_ELIGIBLE"


def test_warranty_settlement_provisional_diverges_from_final(api):
    """PRD 3.7: "a burner claim schedules 3200 cents of parts and 4500 cents of labor,
    a grate claim 2400 and 4500, an electronics claim 4800 and 7500, and any other
    component 1500 and 2500."
    PRD 3.7: "First, it auto-creates a parts order for the claim: quantity 1, with
    `fulfillment_type` `WARRANTY` when the claim is `IN_COVERAGE` and `GOODWILL`
    otherwise"
    PRD 3.7: "`final_settlement_cents` is that actual part cost plus the supplied
    `actual_labor_cents`, and `settlement_delta_cents` is the final figure minus the
    stored provisional"

    Design: Difficulty/dual_variant_calc/warranty_settlement_provisional_diverges_from_final
    """
    bundle = setup_in_season_with_sale()  # REGISTERED sale; claim at sold_at is IN_COVERAGE
    part = create_part(part_number="IGN-9", component="ELECTRONICS",
                       compatible_model_codes=["GX-100"], supersession_chain_id="CH-IGN",
                       chain_position=1, unit_cost_cents=4800, stock_quantity=5)
    claim = create_claim(bundle["sale"]["id"], component="ELECTRONICS",
                         failure_description="Igniter sparks but no flame")
    adjudicate_claim(claim["id"], "REVIEW")
    adjudicate_claim(claim["id"], "ESCALATE")  # provisional 12300 exceeds the 10000 cap from UNDER_REVIEW
    approved = validate_success(_adjudicate(api, claim["id"], "APPROVE"), 200)
    assert approved["provisional_settlement_cents"] == 12300, "catalog schedule: 4800 part + 7500 labor"
    settled = validate_success(_adjudicate(api, claim["id"], "SETTLE", actual_labor_cents=9000), 200)
    assert settled["final_settlement_cents"] == 13800, "actual part 4800 + actual labor 9000"
    assert settled["settlement_delta_cents"] == 1500, "final minus provisional"
    assert settled["provisional_settlement_cents"] != settled["final_settlement_cents"], (
        "the two variants price identical claim data differently"
    )
    order_id = settled["settlement_parts_order_id"]
    assert order_id is not None, "the selector finds IGN-9 (compatible, stocked)"
    order = validate_success(api.get_parts_order(order_id, headers=AGENT), 200)
    assert order["total_cost_cents"] == 4800, "resolved part cost x quantity 1"
    assert order["free_of_charge"] is True, "IN_COVERAGE claim settles as WARRANTY (free of charge)"


def test_settled_claim_rejects_further_adjudication(api):
    """PRD 3.7: "Any adjudication action attempted from a state that does not offer it
    — settling before approval, reopening a settled claim — is
    `ERR_CLAIM_NOT_ADJUDICATABLE`."
    PRD 3.7: "When the eligible pool is empty, no order is created,
    `settlement_parts_order_id` stays null, and the schedule's catalog part cost
    stands in as the actual part cost"

    Design: Corner/state_machines/settled_claim_rejects_further_adjudication
    """
    bundle = setup_in_season_with_sale()  # no parts in the catalog at all
    claim = create_claim(bundle["sale"]["id"], component="BURNER", failure_description="Burner corroded")
    settled = walk_claim_to_state(claim, "SETTLED", actual_labor_cents=4000)
    assert settled["status"] == "SETTLED"
    assert settled["final_settlement_cents"] == 7200, "schedule part 3200 + actual labor 4000"
    assert settled["settlement_parts_order_id"] is None, "empty selector pool creates no order"
    resp = _adjudicate(api, claim["id"], "DENY")
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATABLE)
