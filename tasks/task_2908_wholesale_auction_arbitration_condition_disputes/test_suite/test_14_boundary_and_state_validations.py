"""Validations with a boundary or a stored state behind them: the per-family claim
bar, the shared licence namespace, the monotonic clock, the claim minimum, the fee
balance, the round deadline and the terminal-case evidence gate."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import MECHANICAL_POLICY
from test_helpers.factories import (
    build_arbitrator_review_world,
    build_case_world,
    build_negotiation_world,
    build_sale_world,
    buyer_payload,
    case_payload,
    create_seller,
    decide_case,
    evidence_payload,
    set_clock,
    withdraw_case,
)
from test_helpers.test_users import admin_headers, buyer_rep_headers

YELLOW_SALE = {"light_channel": "YELLOW"}
FIRST_CLAIM = {
    "defect_class": "MECHANICAL",
    "claim_amount_cents": 60000,
    "odometer_at_claim": 84100,
    "complaint_text": "Transmission slips under load",
}


def test_a_second_open_claim_for_the_same_family_on_one_sale_is_refused(api):
    """The bar is scoped to the sale and family pair, and the refusal leaves the
    counters reading exactly one open claim across all four aggregates.

    PRD: "No non-terminal case for the same sale and the same family may already
    exist, or `ERR_DUPLICATE_OPEN_CLAIM` — a sale may legitimately carry several
    concurrent cases, just not two for one defect family."

    Design: Corner/validations/a_second_open_claim_for_the_same_defect_class_is_rejected
    """
    world = build_case_world(
        api, [MECHANICAL_POLICY], sale_overrides=dict(YELLOW_SALE), case_overrides=dict(FIRST_CLAIM)
    )

    response = api.create_case(
        case_payload(
            world["sale"]["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=75000,
            odometer_at_claim=84120,
            complaint_text="Second look at the same transmission",
        ),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM.value)
    assert response.status_code == 409

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 1
    assert sale["version"] == 2

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["open_claim_count"] == 1
    assert buyer["lifetime_claim_count"] == 1

    seller = validate_success(api.get_seller(world["seller"]["id"], admin_headers()), 200)
    assert seller["open_claim_count"] == 1


def test_a_bidder_cannot_reuse_a_consignors_dealer_licence_number(api):
    """The licence namespace spans both dealer tables, so a per-table uniqueness
    check would have let this registration through.

    PRD: "License numbers are globally unique across the *whole* dealer population:
    a submitted `dealer_license_no` that is already held by any registered seller
    **or** by any registered buyer is refused with `ERR_DUPLICATE_DEALER_LICENSE`."

    Design: Corner/validations/a_buyer_cannot_reuse_a_sellers_dealer_license_number
    """
    seller = create_seller(api, dealer_license_no="SL-1001")

    response = api.create_buyer(
        buyer_payload(name="Ridgeline Retail", dealer_license_no="SL-1001"),
        admin_headers(),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_DEALER_LICENSE.value)
    assert response.status_code == 409

    stored = validate_success(api.get_seller(seller["id"], admin_headers()), 200)
    assert stored["dealer_license_no"] == "SL-1001"
    assert stored["version"] == 1


def test_the_clock_refuses_to_run_backwards_but_accepts_standing_still(api):
    """One second earlier is refused; the very same instant is accepted as a no-op,
    which is what makes the guard an at-or-after comparison rather than a strict one.

    PRD: "The clock is monotonic: the requested instant must be at or after the
    clock's current value, and an earlier instant is refused with
    `ERR_CLOCK_NOT_MONOTONIC` (HTTP 409). Setting the clock to exactly its current
    value is permitted and is a no-op."

    Design: Corner/validations/the_logical_clock_cannot_move_backwards_but_may_stand_still
    """
    now = "2026-08-02T00:00:00.000Z"
    advanced = set_clock(api, now)
    assert_instant_equals(advanced["current_utc"], now, "current_utc")

    backwards = api.set_clock("2026-08-01T23:59:59.000Z", admin_headers())
    validate_error(backwards, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)
    assert backwards.status_code == 409

    standing_still = validate_success(api.set_clock(now, admin_headers()), 200)
    assert_instant_equals(standing_still["current_utc"], now, "current_utc")


def test_one_cent_below_the_policy_minimum_fails_and_the_exact_minimum_passes(api):
    """59999 is refused and 60000 is admitted against the same 60000-cent minimum, so
    the comparison includes its endpoint, and the refused attempt leaves no row.

    PRD: "And `claim_amount_cents` must reach the policy's `min_claim_amount_cents`,
    or `ERR_CLAIM_BELOW_MINIMUM`."

    Design: Corner/validations/a_claim_one_cent_below_the_policy_minimum_is_rejected_and_the_exact_minimum_passes
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], **YELLOW_SALE)
    headers = buyer_rep_headers(world["buyer"]["id"])

    below = api.create_case(
        case_payload(
            world["sale"]["id"],
            claim_amount_cents=59999,
            odometer_at_claim=84100,
            complaint_text="Transmission slips under load",
        ),
        headers,
    )
    validate_error(below, ApiErrorId.ERR_CLAIM_BELOW_MINIMUM.value)
    assert below.status_code == 422

    exact = validate_success(
        api.create_case(
            case_payload(
                world["sale"]["id"],
                claim_amount_cents=60000,
                odometer_at_claim=84100,
                complaint_text="Transmission slips under load",
            ),
            headers,
        ),
        201,
    )
    assert exact["status"] == "SUBMITTED"
    assert exact["claim_amount_cents"] == 60000

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 1


def test_overpaying_a_fee_is_refused_and_the_exact_balance_clears_the_hold(api):
    """The refused overpayment does not bump the bidder's version, so the version
    captured before it still satisfies the optimistic check on the exact payment.

    PRD: "then `amount_cents` must not exceed the outstanding
    `frivolous_fee_balance_cents`, or the payment is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE` — the department does not hold buyer credit."

    Design: Corner/validations/a_fee_payment_above_the_outstanding_balance_is_rejected_then_the_exact_balance_clears_the_hold
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    decide_case(
        api,
        world["case"]["id"],
        "FRIVOLOUS_DENIED",
        fault_party="BUYER",
        rationale="Filed to reprice the unit rather than to report a defect",
    )
    buyer_id = world["buyer"]["id"]
    before = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert before["frivolous_fee_balance_cents"] == 25000
    assert before["claim_privilege_status"] == "FEE_HOLD"
    captured_version = before["version"]

    over = api.pay_buyer_fee(
        buyer_id,
        {"amount_cents": 25001, "expected_buyer_version": captured_version},
        buyer_rep_headers(buyer_id),
    )
    validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)
    assert over.status_code == 422

    paid = validate_success(
        api.pay_buyer_fee(
            buyer_id,
            {"amount_cents": 25000, "expected_buyer_version": captured_version},
            buyer_rep_headers(buyer_id),
        ),
        200,
    )

    assert paid["frivolous_fee_balance_cents"] == 0
    assert paid["claim_privilege_status"] == "ACTIVE"
    assert paid["frivolous_claim_count"] == 1
    assert paid["version"] == captured_version + 1


def test_accepting_an_offer_one_second_late_is_refused_though_no_sweep_has_run(api):
    """The deadline is evaluated against the clock at request time, so the round is
    still stored as OPEN when the accept is refused.

    PRD: "The current logical clock is at or before the round's response deadline —
    else `ERR_ROUND_EXPIRED` (HTTP 409). This guards countering and accepting."

    Design: Corner/validations/accepting_an_offer_after_its_response_deadline_is_rejected
    """
    world = build_negotiation_world(
        api, seller_offer_cents=100000, policy_presets=[MECHANICAL_POLICY]
    )
    assert_instant_equals(
        world["round"]["response_deadline_utc"],
        "2026-08-03T00:00:00.000Z",
        "response_deadline_utc",
    )
    set_clock(api, "2026-08-03T00:00:01.000Z")

    response = api.accept_round(
        world["case"]["id"],
        world["round"]["id"],
        {},
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROUND_EXPIRED.value)
    assert response.status_code == 409

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "OPEN"

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "NEGOTIATION"

    decisions, decisions_meta = validate_unpaginated(
        api.list_decision(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(decisions_meta, 0)
    assert decisions == []


def test_appending_evidence_to_a_withdrawn_claim_is_refused(api):
    """The append-only evidence route admits the five non-terminal statuses only, so
    the withdrawn case takes no further rows and its version does not move.

    PRD: "an attempt against a case that has already reached a terminal status is
    refused with `ERR_INVALID_CASE_STATE`."

    Design: Corner/validations/appending_evidence_to_a_withdrawn_case_is_rejected
    """
    world = build_case_world(
        api, [MECHANICAL_POLICY], sale_overrides=dict(YELLOW_SALE), case_overrides=dict(FIRST_CLAIM)
    )
    withdraw_case(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        reason="The buyer accepted the unit as it stands",
    )

    response = api.create_evidence(
        world["case"]["id"],
        evidence_payload(
            evidence_type="INSPECTION_REPORT",
            provider_name="Statewide Vehicle Inspection",
            document_reference="IR-77120",
            repair_estimate_cents=285000,
        ),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)
    assert response.status_code == 409

    rows, meta = validate_unpaginated(
        api.list_evidence(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert rows == []

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "WITHDRAWN"
    assert case["version"] == 2
