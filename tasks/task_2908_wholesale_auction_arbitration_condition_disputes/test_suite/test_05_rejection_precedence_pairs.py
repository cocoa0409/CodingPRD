"""Rejection precedence: three pairs where two rules are violated at once and
only the reported error id proves which one the ladder ranks higher."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import validate_unpaginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import FRAME_DAMAGE_POLICY, MECHANICAL_POLICY
from test_helpers.factories import (
    case_payload,
    create_buyer,
    create_case,
    create_evidence,
    create_policy,
    create_sale,
    create_seller,
    decide_case,
    decision_payload,
    open_review,
    seller_response,
    set_clock,
)
from test_helpers.test_users import (
    admin_headers,
    buyer_rep_headers,
    deciding_arbitrator_headers,
)

CLOCK_FOUR_DAYS_ON = "2026-08-05T00:00:00.000Z"
SUSPENSION_SALES = [
    {"sale_price_cents": 1450000, "announced_odometer_miles": 84000},
    {"sale_price_cents": 900000, "announced_odometer_miles": 61000},
    {"sale_price_cents": 1100000, "announced_odometer_miles": 52000},
    {"sale_price_cents": 780000, "announced_odometer_miles": 99000},
]


def _suspended_buyer_world(api):
    """Three frivolous denials suspend the buyer, then the clock moves 96 hours
    past every hammer time so the 48-hour window is also blown."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sales = [
        create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW", **overrides)
        for overrides in SUSPENSION_SALES
    ]
    for index in range(3):
        case = create_case(
            api,
            sales[index]["id"],
            buyer["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=SUSPENSION_SALES[index]["announced_odometer_miles"] + 100,
            complaint_text="Undisclosed mechanical fault",
        )
        create_evidence(
            api,
            case["id"],
            buyer["id"],
            evidence_type="INSPECTION_REPORT",
            repair_estimate_cents=100000,
        )
        open_review(api, case["id"])
        seller_response(
            api,
            case["id"],
            seller["id"],
            "DISPUTE",
            note="Announced as-is on a yellow light",
        )
        decide_case(
            api,
            case["id"],
            "FRIVOLOUS_DENIED",
            fault_party="BUYER",
            rationale="No defect found",
        )
    set_clock(api, CLOCK_FOUR_DAYS_ON)
    return {"seller": seller, "buyer": buyer, "sales": sales}


def test_a_suspended_buyer_outranks_an_expired_arbitration_window(api):
    """Filing 96 hours after the hammer under a 48-hour window while suspended
    reports the privilege gate, not the window arithmetic — both would answer
    409, so the error id is the only observable difference.

    PRD: "A suspended buyer filing a time-barred claim receives
    `ERR_BUYER_PRIVILEGE_SUSPENDED`, not `ERR_ARBITRATION_WINDOW_EXPIRED`"

    Design: Difficulty/priority_pair_validation_conflict/pair_a_suspended_buyer_beats_expired_window_rejected
    """
    world = _suspended_buyer_world(api)
    buyer_id = world["buyer"]["id"]

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["claim_privilege_status"] == "SUSPENDED"
    assert buyer["frivolous_claim_count"] == 3

    response = api.create_case(
        case_payload(
            world["sales"][3]["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=99100,
            complaint_text="Coolant loss noticed after four days",
        ),
        buyer_rep_headers(buyer_id),
    )

    error = validate_error(response, ApiErrorId.ERR_BUYER_PRIVILEGE_SUSPENDED.value)
    assert error["error_id"] != ApiErrorId.ERR_ARBITRATION_WINDOW_EXPIRED.value


def test_the_privilege_rejection_creates_no_case_and_moves_no_counters(api):
    """The refused filing leaves the target sale on the dispute dimension at
    NONE and the buyer's claim counters exactly where they stood.

    PRD: "`Buyer.open_claim_count` equals the number of cases whose
    `claimant_buyer_id` is that buyer and which are open"

    Design: Difficulty/priority_pair_validation_conflict/pair_a_suspended_buyer_beats_expired_window_rejected
    """
    world = _suspended_buyer_world(api)
    buyer_id = world["buyer"]["id"]
    sale_id = world["sales"][3]["id"]

    api.create_case(
        case_payload(
            sale_id,
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=99100,
        ),
        buyer_rep_headers(buyer_id),
    )

    cases, _ = validate_paginated(
        api.list_cases(admin_headers(), params={"sale_id": sale_id})
    )
    assert cases == []

    sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert sale["arbitration_status"] == "NONE"
    assert sale["open_case_count"] == 0

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["lifetime_claim_count"] == 3
    assert buyer["open_claim_count"] == 0


# --- Pair B: a conceded unwind against an over-cap allowance -------------------

FRAME_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}


def _conceded_frame_world(api):
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
    seller_response(
        api,
        case["id"],
        seller["id"],
        "ACCEPT_UNWIND",
        note="We will take the unit back",
    )
    return {"seller": seller, "buyer": buyer, "sale": sale, "case": case}


def test_a_mandatory_unwind_outranks_an_over_cap_allowance_request(api):
    """With seller_conceded true, an allowance request of 500000 against a 435000
    cap is refused as ERR_UNWIND_MANDATORY — a 409 — rather than as the 422 the
    cap violation would produce.

    PRD: "And a decision that both violates the mandatory-unwind rule and
    over-caps its allowance reports `ERR_UNWIND_MANDATORY`, not
    `ERR_ALLOWANCE_EXCEEDS_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/pair_b_mandatory_unwind_beats_over_cap_allowance_rejected
    """
    world = _conceded_frame_world(api)
    case_id = world["case"]["id"]

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["seller_conceded"] is True
    assert case["status"] == "ARBITRATOR_REVIEW"

    response = api.create_decision(
        case_id,
        decision_payload(
            "REPAIR_ALLOWANCE",
            fault_party="SELLER",
            requested_allowance_cents=500000,
            rationale="Allowance preferred over unwind",
        ),
        deciding_arbitrator_headers(),
    )

    error = validate_error(response, ApiErrorId.ERR_UNWIND_MANDATORY.value)
    assert error["error_id"] != ApiErrorId.ERR_ALLOWANCE_EXCEEDS_CAP.value
    assert response.status_code == 409


def test_the_refused_decision_leaves_the_case_and_the_money_untouched(api):
    """No decision row is written, the case stays in ARBITRATOR_REVIEW, and the
    consignor's scorecard never moves.

    PRD: "A decision row is immutable, carries no `updated_at` and no `version`,
    and a case is decided at most once, so the decision read on a case returns an
    array of either zero or one row."

    Design: Difficulty/priority_pair_validation_conflict/pair_b_mandatory_unwind_beats_over_cap_allowance_rejected
    """
    world = _conceded_frame_world(api)
    case_id = world["case"]["id"]

    api.create_decision(
        case_id,
        decision_payload(
            "REPAIR_ALLOWANCE", fault_party="SELLER", requested_allowance_cents=500000
        ),
        deciding_arbitrator_headers(),
    )

    decisions, _ = validate_unpaginated(api.list_decision(case_id, admin_headers()))
    assert decisions == []

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "ARBITRATOR_REVIEW"

    entries, _ = validate_unpaginated(
        api.list_case_ledger_entries(case_id, admin_headers())
    )
    assert entries == []

    seller = validate_success(api.get_seller(world["seller"]["id"], admin_headers()), 200)
    assert seller["lifetime_upheld_count"] == 0
    assert seller["policy_tier"] == "GOOD_STANDING"


# --- Pair C: an expired window against a below-minimum claim -------------------


def _blown_window_world(api):
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    set_clock(api, CLOCK_FOUR_DAYS_ON)
    return {"seller": seller, "buyer": buyer, "sale": sale}


def test_an_expired_window_outranks_a_below_minimum_claim(api):
    """96 elapsed hours against a 48-hour window with a 1000-cent claim under a
    60000-cent minimum reports the window, not the minimum.

    PRD: "A claim that is both time-barred and under the policy minimum reports
    `ERR_ARBITRATION_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/pair_c_expired_window_beats_below_minimum_claim_rejected
    """
    world = _blown_window_world(api)

    response = api.create_case(
        case_payload(
            world["sale"]["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=1000,
            odometer_at_claim=84100,
            complaint_text="Rattle from the dash",
        ),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    error = validate_error(response, ApiErrorId.ERR_ARBITRATION_WINDOW_EXPIRED.value)
    assert error["error_id"] != ApiErrorId.ERR_CLAIM_BELOW_MINIMUM.value
    assert response.status_code == 409


def test_the_window_rejection_leaves_the_sale_and_the_buyer_at_zero(api):
    """Nothing is written: no case, no counters, and the sale keeps both its
    dimensions at their opening values.

    PRD: "Filing also moves three other records in the same request. The sale's
    `arbitration_status` moves `NONE → ACTIVE`, its `open_case_count` rises by 1,
    and its `version` rises by 1."

    Design: Difficulty/priority_pair_validation_conflict/pair_c_expired_window_beats_below_minimum_claim_rejected
    """
    world = _blown_window_world(api)
    sale_id = world["sale"]["id"]

    api.create_case(
        case_payload(
            sale_id,
            defect_class="MECHANICAL",
            claim_amount_cents=1000,
            odometer_at_claim=84100,
        ),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    cases, _ = validate_paginated(
        api.list_cases(admin_headers(), params={"sale_id": sale_id})
    )
    assert cases == []

    sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert sale["arbitration_status"] == "NONE"
    assert sale["open_case_count"] == 0
    assert sale["settlement_status"] == "UNSETTLED"

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["lifetime_claim_count"] == 0
    assert buyer["open_claim_count"] == 0
