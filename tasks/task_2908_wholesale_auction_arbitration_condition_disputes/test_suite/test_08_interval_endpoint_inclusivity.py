"""Temporal intervals with opposite inclusivity: the half-open inspection window
and the closed negotiation cooldown, probed one second either side of their ends."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_instant_equals,
    assert_sweep_report,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import FRAME_DAMAGE_POLICY
from test_helpers.factories import (
    counter_round,
    create_buyer,
    create_case,
    create_evidence,
    create_inspection,
    create_policy,
    create_sale,
    create_seller,
    inspection_payload,
    open_review,
    run_sweep,
    seller_response,
    set_clock,
)
from test_helpers.test_users import admin_headers, buyer_rep_headers, seller_rep_headers

WINDOW_END = "2026-08-04T00:00:00.000Z"
ONE_SECOND_BEFORE_WINDOW_END = "2026-08-03T23:59:59.000Z"
SECOND_WINDOW_END = "2026-08-07T00:00:00.000Z"


def _incumbent_inspection_world(api):
    """One STANDARD inspection holding [2026-08-01T00:00:00Z, 2026-08-04T00:00:00Z)
    with the clock parked one second short of its endpoint."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    incumbent = create_inspection(api, sale["id"], buyer["id"], program_tier="STANDARD")
    set_clock(api, ONE_SECOND_BEFORE_WINDOW_END)
    return {"seller": seller, "buyer": buyer, "sale": sale, "incumbent": incumbent}


def test_a_second_inspection_one_second_before_the_endpoint_overlaps(api):
    """The incumbent's interval still contains 2026-08-03T23:59:59Z, so a second
    request there is refused as an overlap.

    PRD: "If that interval overlaps the interval of any inspection on the same
    sale whose `status` is still `REQUESTED`, the purchase is refused with
    `ERR_PSI_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/psi_window_half_open_rejects_at_minus_1s_and_admits_at_the_endpoint
    """
    world = _incumbent_inspection_world(api)

    inspections, meta = validate_unpaginated(
        api.list_sale_inspections(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert_instant_equals(
        inspections[0]["requested_at_utc"], "2026-08-01T00:00:00.000Z", "requested_at_utc"
    )
    assert_instant_equals(inspections[0]["window_end_utc"], WINDOW_END, "window_end_utc")
    assert inspections[0]["fee_cents"] == 12500

    response = api.create_inspection(
        inspection_payload(world["sale"]["id"], "PREMIUM"),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PSI_WINDOW_OVERLAP.value)
    assert response.status_code == 409


def test_a_request_exactly_at_the_endpoint_is_adjacent_and_admitted(api):
    """At the endpoint the interval is already closed, so a PREMIUM request is
    admitted with its own three-day window even though the incumbent row is still
    REQUESTED — expiry is the sweep's job, not the clock's.

    PRD: "Because both intervals exclude their right endpoint, a request arriving
    at exactly the incumbent inspection's `window_end_utc` touches but does not
    overlap, and is accepted."

    Design: Difficulty/resource_temporal_overlap/psi_window_half_open_rejects_at_minus_1s_and_admits_at_the_endpoint
    """
    world = _incumbent_inspection_world(api)
    sale_id = world["sale"]["id"]

    api.create_inspection(
        inspection_payload(sale_id, "PREMIUM"), buyer_rep_headers(world["buyer"]["id"])
    )
    set_clock(api, WINDOW_END)

    second = validate_success(
        api.create_inspection(
            inspection_payload(sale_id, "PREMIUM"),
            buyer_rep_headers(world["buyer"]["id"]),
        ),
        201,
    )

    assert_instant_equals(second["requested_at_utc"], WINDOW_END, "requested_at_utc")
    assert_instant_equals(
        second["window_end_utc"], SECOND_WINDOW_END, "window_end_utc"
    )
    assert second["fee_cents"] == 27500
    assert second["status"] == "REQUESTED"

    inspections, meta = validate_unpaginated(api.list_sale_inspections(sale_id, admin_headers()))
    assert_unpaginated_meta(meta, 2)
    incumbent = next(row for row in inspections if row["id"] == world["incumbent"]["id"])
    assert incumbent["status"] == "REQUESTED"


def test_the_sweep_expires_the_lapsed_inspection_and_a_repeat_sweep_is_idle(api):
    """The sweep is what moves the lapsed row to EXPIRED, reports exactly one
    expiry, and a second sweep at the same clock reports nothing at all.

    PRD: "Every `PostSaleInspection` whose `status` is `REQUESTED` and whose
    `window_end_utc` the clock has reached or passed moves `REQUESTED → EXPIRED`,
    incrementing its `version` by 1. This boundary is **inclusive**"

    Design: Difficulty/resource_temporal_overlap/psi_window_half_open_rejects_at_minus_1s_and_admits_at_the_endpoint
    """
    world = _incumbent_inspection_world(api)
    sale_id = world["sale"]["id"]
    set_clock(api, WINDOW_END)
    second = validate_success(
        api.create_inspection(
            inspection_payload(sale_id, "PREMIUM"),
            buyer_rep_headers(world["buyer"]["id"]),
        ),
        201,
    )

    report = run_sweep(api)
    assert_sweep_report(report, inspections_expired=1)

    inspections, meta = validate_unpaginated(api.list_sale_inspections(sale_id, admin_headers()))
    assert_unpaginated_meta(meta, 2)
    assert_created_at_ascending(inspections, "post-sale inspections")
    assert inspections[0]["id"] == world["incumbent"]["id"]
    assert inspections[0]["status"] == "EXPIRED"
    assert inspections[1]["id"] == second["id"]
    assert inspections[1]["status"] == "REQUESTED"

    assert_sweep_report(run_sweep(api))


# --- The closed cooldown interval ---------------------------------------------

FRAME_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}
COOLDOWN_END = "2026-08-01T02:00:00.000Z"
ONE_SECOND_AFTER_COOLDOWN = "2026-08-01T02:00:01.000Z"
SECOND_ROUND_DEADLINE = "2026-08-03T02:00:01.000Z"


def _countered_case_world(api):
    """Round 1 offered and countered at the default clock, so the cooldown ends at
    02:00:00Z, with the clock parked exactly on that endpoint."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, FRAME_DAMAGE_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="RED")
    case = create_case(api, sale["id"], buyer["id"], **FRAME_CASE)
    create_evidence(
        api,
        case["id"],
        buyer["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )
    create_evidence(
        api, case["id"], buyer["id"], evidence_type="THIRD_PARTY_VERIFICATION"
    )
    open_review(api, case["id"])
    round1 = seller_response(
        api, case["id"], seller["id"], "OFFER_REPAIR_ALLOWANCE", 100000, "First offer"
    )
    counter_round(api, case["id"], round1["id"], buyer["id"], 250000, "The estimate is 285000")
    set_clock(api, COOLDOWN_END)
    return {
        "seller": seller,
        "buyer": buyer,
        "sale": sale,
        "case": case,
        "round1": round1,
    }


def _re_offer(api, case_id, seller_id, note):
    return api.seller_response(
        case_id,
        {
            "response_type": "OFFER_REPAIR_ALLOWANCE",
            "response_note": note,
            "seller_offer_cents": 150000,
        },
        seller_rep_headers(seller_id),
    )


def test_a_re_offer_exactly_at_the_cooldown_endpoint_is_refused(api):
    """Unlike the inspection interval, the cooldown is closed at its endpoint: the
    guard needs the clock strictly past it, so the endpoint itself is still active.

    PRD: "A re-offer arriving at exactly `cooldown_until_utc` is therefore
    rejected; only strictly after it does the consignor get to speak again."

    Design: Difficulty/resource_temporal_overlap/round_cooldown_closed_interval_rejects_at_the_endpoint_and_admits_one_second_later
    """
    world = _countered_case_world(api)
    case_id = world["case"]["id"]

    response = _re_offer(
        api, case_id, world["seller"]["id"], "Second offer at the cooldown endpoint"
    )

    validate_error(response, ApiErrorId.ERR_ROUND_COOLDOWN_ACTIVE.value)
    assert response.status_code == 409

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "COUNTERED"
    assert case["current_round_index"] == 1

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(case_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "COUNTERED"


def test_one_second_past_the_cooldown_opens_round_two_and_supersedes_round_one(api):
    """A second past the endpoint the same request succeeds, opening round 2 with
    a 48-hour deadline and leaving exactly two rounds — the refused probe wrote
    nothing.

    PRD: "the round is written with `status` `OPEN`, a `response_deadline_utc` of
    48 hours (two days) after `opened_at_utc`"

    Design: Difficulty/resource_temporal_overlap/round_cooldown_closed_interval_rejects_at_the_endpoint_and_admits_one_second_later
    """
    world = _countered_case_world(api)
    case_id = world["case"]["id"]
    seller_id = world["seller"]["id"]

    _re_offer(api, case_id, seller_id, "Second offer at the cooldown endpoint")
    set_clock(api, ONE_SECOND_AFTER_COOLDOWN)
    round2 = validate_success(
        _re_offer(api, case_id, seller_id, "Second offer one second later"), 201
    )

    assert round2["round_index"] == 2
    assert round2["seller_offer_cents"] == 150000
    assert_instant_equals(
        round2["opened_at_utc"], ONE_SECOND_AFTER_COOLDOWN, "opened_at_utc"
    )
    assert_instant_equals(
        round2["response_deadline_utc"], SECOND_ROUND_DEADLINE, "response_deadline_utc"
    )

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "NEGOTIATION"
    assert case["current_round_index"] == 2

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(case_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert_created_at_ascending(rounds, "negotiation rounds")
    assert rounds[0]["status"] == "SUPERSEDED"
    assert_instant_equals(
        rounds[0]["cooldown_until_utc"], COOLDOWN_END, "cooldown_until_utc"
    )
    assert rounds[1]["status"] == "OPEN"
