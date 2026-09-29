"""Validations that decide who may act and what may be claimed: the three ownership
bindings, segregation of duties, round state, the fee hold, and the announcement bar."""
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
from test_helpers.constants import (
    ARB_INTAKE_USER_ID,
    MECHANICAL_POLICY,
    TITLE_MISSING_POLICY,
)
from test_helpers.factories import (
    build_arbitrator_review_world,
    build_negotiation_world,
    build_sale_world,
    build_under_review_world,
    case_payload,
    counter_round,
    create_announcement,
    create_buyer,
    create_policy,
    create_sale,
    create_seller,
    decide_case,
    decision_payload,
    inspection_payload,
    seller_response,
    set_clock,
)
from test_helpers.test_users import (
    admin_headers,
    buyer_rep_headers,
    intake_arbitrator_headers,
    seller_rep_headers,
)


def test_filing_a_claim_on_another_dealers_sale_is_refused_as_a_non_buyer(api):
    """The BuyerRep role is welcome on the intake route, so the refusal names the
    ownership failure rather than an authorisation or lookup failure.

    PRD: "The caller's `X-User-ID` must equal the sale's `buyer_id`, or
    `ERR_NOT_SALE_BUYER`."

    Design: Corner/validations/filing_a_claim_on_another_dealers_sale_is_rejected
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], light_channel="YELLOW")
    other_buyer = create_buyer(api)

    response = api.create_case(
        case_payload(
            world["sale"]["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=60000,
            odometer_at_claim=84100,
            complaint_text="Transmission slips under load",
        ),
        buyer_rep_headers(other_buyer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_SALE_BUYER.value)
    assert response.status_code == 403

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 0
    assert sale["arbitration_status"] == "NONE"

    observed = validate_success(api.get_buyer(other_buyer["id"], admin_headers()), 200)
    assert observed["lifetime_claim_count"] == 0
    assert observed["open_claim_count"] == 0


def test_countering_a_round_on_another_buyers_case_leaves_the_offer_open(api):
    """The counter route resolves ownership through the case's claimant, so an
    unrelated bidder cannot move the round and none of its counter fields are set.

    PRD: "A `BuyerRep` acting on a case presents an `X-User-ID` equal to the case's
    `claimant_buyer_id` — else `ERR_NOT_CASE_OWNER`. This guards evidence filing,
    withdrawal, countering and accepting."

    Design: Corner/validations/countering_a_round_on_another_buyers_case_is_rejected
    """
    world = build_negotiation_world(
        api, seller_offer_cents=100000, policy_presets=[MECHANICAL_POLICY]
    )
    other_buyer = create_buyer(api)

    response = api.counter_round(
        world["case"]["id"],
        world["round"]["id"],
        {
            "buyer_demand_cents": 200000,
            "counter_note": "Estimate is higher than the offer",
        },
        buyer_rep_headers(other_buyer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_CASE_OWNER.value)
    assert response.status_code == 403

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "OPEN"
    assert rounds[0]["buyer_demand_cents"] is None
    assert rounds[0]["cooldown_until_utc"] is None

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "NEGOTIATION"
    assert case["current_round_index"] == 1


def test_a_seller_rep_from_another_dealership_cannot_answer_the_claim(api):
    """The seller-response route binds the acting identity to the consignor of the
    disputed sale, so no round is minted for a stranger's answer.

    PRD: "A `SellerRep` acting on a case presents an `X-User-ID` equal to the
    `seller_id` of the case's sale — else `ERR_NOT_SALE_SELLER`. This guards the
    seller response."

    Design: Corner/validations/a_seller_rep_from_another_dealership_cannot_respond_to_the_case
    """
    world = build_under_review_world(api, [MECHANICAL_POLICY])
    other_seller = create_seller(api)

    response = api.seller_response(
        world["case"]["id"],
        {
            "response_type": "OFFER_REPAIR_ALLOWANCE",
            "response_note": "We will cover half",
            "seller_offer_cents": 100000,
        },
        seller_rep_headers(other_seller["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_SALE_SELLER.value)
    assert response.status_code == 403

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "UNDER_REVIEW"
    assert case["current_round_index"] == 0

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert rounds == []


def test_the_officer_who_opened_intake_cannot_render_the_decision(api):
    """The Arbitrator role is permitted on the decision route, so the bar is the
    identity stamped at intake rather than the role, and no decision row appears.

    PRD: "An `Arbitrator` other than the one who opened intake review — otherwise
    `ERR_SEGREGATION_OF_DUTIES` — renders the decision on a case in
    `ARBITRATOR_REVIEW`"

    Design: Corner/validations/the_intake_arbitrator_cannot_issue_the_decision
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    assert world["case"]["intake_arbitrator_user_id"] == ARB_INTAKE_USER_ID

    response = api.create_decision(
        world["case"]["id"],
        decision_payload(
            "CLAIM_DENIED",
            fault_party="BUYER",
            rationale="No mechanical defect substantiated",
        ),
        intake_arbitrator_headers(),
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert response.status_code == 403

    decisions, meta = validate_unpaginated(
        api.list_decision(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert decisions == []

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "ARBITRATOR_REVIEW"


COOLDOWN_END = "2026-08-01T02:00:00.000Z"
PAST_COOLDOWN = "2026-08-01T02:00:01.000Z"


def test_accepting_a_round_that_was_superseded_is_refused_on_round_state(api):
    """The case is back in NEGOTIATION with a live offer, so the case-state gate
    passes and the refusal comes from the addressed round's own status.

    PRD: "The `NegotiationRound` status is `OPEN` — else `ERR_INVALID_ROUND_STATE`
    (HTTP 409). This guards countering and accepting."

    Design: Corner/validations/accepting_a_superseded_round_is_rejected
    """
    world = build_negotiation_world(
        api, seller_offer_cents=100000, policy_presets=[MECHANICAL_POLICY]
    )
    case_id = world["case"]["id"]
    round_one_id = world["round"]["id"]

    countered = counter_round(
        api, case_id, round_one_id, world["buyer"]["id"], 200000, "Estimate is 285000"
    )
    assert_instant_equals(
        countered["cooldown_until_utc"], COOLDOWN_END, "cooldown_until_utc"
    )

    set_clock(api, PAST_COOLDOWN)
    seller_response(
        api,
        case_id,
        world["seller"]["id"],
        "OFFER_REPAIR_ALLOWANCE",
        150000,
        "Revised offer after the cooldown",
    )

    response = api.accept_round(
        case_id, round_one_id, {}, buyer_rep_headers(world["buyer"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ROUND_STATE.value)
    assert response.status_code == 409

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(case_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert rounds[0]["round_index"] == 1
    assert rounds[0]["status"] == "SUPERSEDED"
    assert rounds[1]["round_index"] == 2
    assert rounds[1]["status"] == "OPEN"
    assert rounds[1]["seller_offer_cents"] == 150000

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "NEGOTIATION"
    assert case["current_round_index"] == 2

    decisions, decisions_meta = validate_unpaginated(
        api.list_decision(case_id, admin_headers())
    )
    assert_unpaginated_meta(decisions_meta, 0)
    assert decisions == []


def test_a_bidder_on_a_fee_hold_may_not_buy_an_inspection_on_another_sale(api):
    """The hold is a property of the bidder, not of the sale, so a second entirely
    clean sale is closed to it as well.

    PRD: "The acting buyer's `claim_privilege_status` is `ACTIVE` — else
    `ERR_BUYER_FEE_HOLD` (HTTP 409). This guards inspection purchase, which is
    stricter than claim intake because an inspection is a paid privilege: a
    `FEE_HOLD` buyer may still file a claim but may not buy an inspection."

    Design: Corner/validations/requesting_an_inspection_while_on_a_fee_hold_is_rejected
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    decide_case(
        api,
        world["case"]["id"],
        "FRIVOLOUS_DENIED",
        fault_party="BUYER",
        rationale="Filed to reprice the unit rather than to report a defect",
    )
    sale_b = create_sale(
        api,
        world["seller"]["id"],
        world["buyer"]["id"],
        sale_price_cents=900000,
        announced_odometer_miles=61000,
    )

    response = api.create_inspection(
        inspection_payload(sale_b["id"], "STANDARD"),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_BUYER_FEE_HOLD.value)
    assert response.status_code == 409

    inspections, meta = validate_unpaginated(
        api.list_sale_inspections(sale_b["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert inspections == []

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["claim_privilege_status"] == "FEE_HOLD"
    assert buyer["frivolous_fee_balance_cents"] == 25000
    assert buyer["frivolous_claim_count"] == 1


def test_a_defect_announced_at_the_block_bars_the_claim_outright(api):
    """The claim is inside the window, over the minimum and under the mileage limit,
    and is still barred because the very family was disclosed at the block.

    PRD: "No announcement of the same family may exist on the sale unless the family
    is `TITLE_MISSING`, or `ERR_DEFECT_ANNOUNCED`."

    Design: Corner/validations/claiming_a_defect_that_was_announced_at_the_block_is_rejected
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], light_channel="YELLOW")
    create_announcement(api, world["sale"]["id"], "MECHANICAL")

    response = api.create_case(
        case_payload(
            world["sale"]["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=60000,
            odometer_at_claim=84100,
            complaint_text="Transmission slips under load",
        ),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DEFECT_ANNOUNCED.value)
    assert response.status_code == 409

    announcements, meta = validate_unpaginated(
        api.list_announcements(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert announcements[0]["defect_class"] == "MECHANICAL"

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 0
    assert sale["arbitration_status"] == "NONE"


def test_a_missing_title_claim_survives_its_announcement_and_an_open_window(api):
    """The one announcement-exempt family, filed 31 days and 6000 miles after the
    hammer under a policy with no window and no mileage limit, is still admitted.

    PRD: "The time axis passes when the policy's `window_hours` is null, and
    otherwise when `hours_elapsed_at_claim` is less than or equal to
    `effective_window_hours`"

    Design: Corner/validations/a_title_missing_claim_survives_both_its_announcement_and_an_unlimited_window
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    policy = create_policy(api, TITLE_MISSING_POLICY)
    assert policy["window_hours"] is None
    assert policy["mileage_limit"] is None
    sale = create_sale(api, seller["id"], buyer["id"], title_status="MISSING")
    create_announcement(api, sale["id"], "TITLE_MISSING")
    set_clock(api, "2026-09-01T00:00:00.000Z")

    case = validate_success(
        api.create_case(
            case_payload(
                sale["id"],
                defect_class="TITLE_MISSING",
                claim_amount_cents=60000,
                odometer_at_claim=90000,
                complaint_text="Title never arrived from the consignor",
            ),
            buyer_rep_headers(buyer["id"]),
        ),
        201,
    )

    assert case["status"] == "SUBMITTED"
    assert case["window_eligible"] is True
    assert case["effective_window_hours"] is None
    assert case["hours_elapsed_at_claim"] == 744.0
    assert case["miles_driven_at_claim"] == 6000
    assert case["psi_extension_applied_hours"] == 0

    stored = validate_success(api.get_sale(sale["id"], admin_headers()), 200)
    assert stored["arbitration_status"] == "ACTIVE"
    assert stored["open_case_count"] == 1
