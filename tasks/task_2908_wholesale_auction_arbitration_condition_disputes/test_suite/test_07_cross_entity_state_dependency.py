"""Cross-entity dependencies: a settle gated by a third entity's tier, and one
inspection row that waives rights under one policy but not another."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import CLOCK_DEFAULT, FRAME_DAMAGE_POLICY, MECHANICAL_POLICY
from test_helpers.factories import (
    accept_round,
    case_payload,
    complete_inspection,
    create_buyer,
    create_case,
    create_evidence,
    create_inspection,
    create_policy,
    create_sale,
    create_seller,
    open_review,
    reinstate_seller,
    seller_response,
    set_clock,
)
from test_helpers.test_users import admin_headers, buyer_rep_headers

FRAME_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}
SIBLING_SALES = [
    {"sale_price_cents": 900000, "announced_odometer_miles": 61000, "light_channel": "GREEN"},
    {"sale_price_cents": 1100000, "announced_odometer_miles": 52000, "light_channel": "GREEN"},
    {"sale_price_cents": 780000, "announced_odometer_miles": 99000, "light_channel": "YELLOW"},
]


def _blocked_consignor_world(api):
    """One accepted allowance drives the consignor to BLOCKED, leaving holds on
    three sales that have no claim, no hold of their own making and no history."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, FRAME_DAMAGE_POLICY)
    sale1 = create_sale(api, seller["id"], buyer["id"], light_channel="RED")
    siblings = [
        create_sale(api, seller["id"], buyer["id"], **overrides)
        for overrides in SIBLING_SALES
    ]
    case = create_case(api, sale1["id"], buyer["id"], **FRAME_CASE)
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
    round_row = seller_response(
        api,
        case["id"],
        seller["id"],
        "OFFER_REPAIR_ALLOWANCE",
        200000,
        "Goodwill allowance offered",
    )
    accept_round(api, case["id"], round_row["id"], buyer["id"])
    return {
        "seller": seller,
        "buyer": buyer,
        "sale1": sale1,
        "siblings": siblings,
        "case": case,
    }


def test_a_blocked_consignor_refuses_a_settle_on_an_untouched_sibling_sale(api):
    """Sale 2 is UNSETTLED, carries no case of its own and never changed, yet its
    settle is refused because the blocking condition lives on the consignor.

    PRD: "a sale is refused with `ERR_SELLER_BLOCKED` when its consignor's
    `policy_tier` is `BLOCKED` or when the sale itself carries `settlement_hold`
    true"

    Design: Difficulty/cross_entity_state_dependency/settle_gated_by_seller_policy_tier_then_released_by_reinstate
    """
    world = _blocked_consignor_world(api)
    sale2_id = world["siblings"][0]["id"]

    seller = validate_success(api.get_seller(world["seller"]["id"], admin_headers()), 200)
    assert seller["policy_tier"] == "BLOCKED"

    response = api.settle_sale(sale2_id, {}, admin_headers())
    validate_error(response, ApiErrorId.ERR_SELLER_BLOCKED.value)
    assert response.status_code == 409

    sale2 = validate_success(api.get_sale(sale2_id, admin_headers()), 200)
    assert sale2["settlement_status"] == "UNSETTLED"
    assert sale2["arbitration_status"] == "NONE"
    assert sale2["open_case_count"] == 0

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(sale2_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert entries == []


def test_reinstating_the_consignor_clears_every_hold_and_appends_a_second_action(api):
    """The reinstate on the consignor's own route moves BLOCKED to PROBATION,
    clears the blocked timestamp, counts the reinstatement and lifts the holds
    from all three sibling sales.

    PRD: "Reinstatement moves the tier `BLOCKED → PROBATION` rather than all the
    way back to `GOOD_STANDING`, clears `blocked_at_utc` to null, increments
    `reinstated_count` by 1, appends a `SellerPolicyAction` with `action_type`
    `REINSTATE`, a null `triggered_by_case_id` — no case caused it"

    Design: Difficulty/cross_entity_state_dependency/settle_gated_by_seller_policy_tier_then_released_by_reinstate
    """
    world = _blocked_consignor_world(api)
    seller_id = world["seller"]["id"]

    reinstated = reinstate_seller(
        api, seller_id, note="Corrective action plan accepted; released to probation"
    )

    assert reinstated["policy_tier"] == "PROBATION"
    assert reinstated["blocked_at_utc"] is None
    assert reinstated["reinstated_count"] == 1

    actions, meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert_created_at_ascending(actions, "seller policy actions")
    assert actions[0]["action_type"] == "BLOCK"
    assert actions[0]["from_tier"] == "GOOD_STANDING"
    assert actions[0]["to_tier"] == "BLOCKED"
    assert actions[0]["triggered_by_case_id"] == world["case"]["id"]
    assert actions[1]["action_type"] == "REINSTATE"
    assert actions[1]["from_tier"] == "BLOCKED"
    assert actions[1]["to_tier"] == "PROBATION"
    assert actions[1]["triggered_by_case_id"] is None

    for sibling in world["siblings"]:
        sale = validate_success(api.get_sale(sibling["id"], admin_headers()), 200)
        assert sale["settlement_hold"] is False


def test_the_same_settle_succeeds_after_reinstatement_and_the_rate_stays_put(api):
    """Nothing about sale 2 changed, only the consignor's tier, and the second
    attempt releases the proceeds; the scorecard still reads 2500 bps and the read
    leaves the reinstated `PROBATION` on the consignor row untouched.

    PRD: "It posts a balanced `SALE_PROCEEDS` pair — the seller credited the full
    `sale_price_cents`, the buyer debited the same figure, both rows with a null
    `case_id` since no dispute caused them"

    PRD: "That read recomputes both variants against the current logical clock and
    answers with an object carrying ... the `policy_tier` those figures produce ...
    It never mutates the consignor row — a read must not bump a `version` or move
    a tier"

    Design: Difficulty/cross_entity_state_dependency/settle_gated_by_seller_policy_tier_then_released_by_reinstate
    """
    world = _blocked_consignor_world(api)
    seller_id = world["seller"]["id"]
    sale2_id = world["siblings"][0]["id"]

    api.settle_sale(sale2_id, {}, admin_headers())
    reinstated = reinstate_seller(api, seller_id)
    settled = validate_success(api.settle_sale(sale2_id, {}, admin_headers()), 200)

    assert settled["settlement_status"] == "SETTLED"
    assert_instant_equals(settled["settled_at_utc"], CLOCK_DEFAULT, "settled_at_utc")

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(sale2_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert_ledger_batch_balanced(entries, "the released proceeds pair")
    assert_ledger_rows(
        entries,
        [
            {"party": "SELLER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": 900000},
            {"party": "BUYER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": -900000},
        ],
    )

    scorecard = validate_success(api.get_seller_scorecard(seller_id, admin_headers()), 200)
    assert scorecard["rolling_window_sales_count"] == 4
    assert scorecard["rolling_arbitration_rate_bps"] == 2500
    # The read reports the tier those figures produce: 4 in-window sales at
    # 2500 bps, evaluated from a stored PROBATION that stickiness does not pin.
    assert scorecard["policy_tier"] == "BLOCKED"

    # ...but a read moves nothing, so the consignor row still carries the tier
    # and the version the reinstatement left behind.
    seller = validate_success(api.get_seller(seller_id, admin_headers()), 200)
    assert seller["policy_tier"] == "PROBATION"
    assert seller["blocked_at_utc"] is None
    assert seller["version"] == reinstated["version"]


# --- One inspection, two opposite answers -------------------------------------


def _clean_inspection_world(api):
    """A clean STANDARD inspection completed an hour after the hammer, against a
    policy pair that disagrees about what a clean inspection means."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    create_policy(api, FRAME_DAMAGE_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    inspection = create_inspection(api, sale["id"], buyer["id"], program_tier="STANDARD")
    set_clock(api, "2026-08-01T01:00:00.000Z")
    completed = complete_inspection(api, inspection["id"], [])
    return {
        "seller": seller,
        "buyer": buyer,
        "sale": sale,
        "inspection": completed,
    }


def test_a_clean_inspection_waives_rights_only_under_the_policy_that_says_so(api):
    """The MECHANICAL probe is refused as waived while the FRAME_DAMAGE probe on
    the same sale, the same buyer and the same inspection row is admitted.

    PRD: "If the `findings` **omit** the claimed family — including the case of a
    completely clean inspection with an empty array — and the governing policy
    sets `psi_clean_waives_rights` to true, then the buyer paid a professional to
    look for this defect, the professional did not find it, and the right to
    arbitrate that family on this sale is gone: the claim is refused with
    `ERR_PSI_WAIVED_RIGHTS`."

    Design: Difficulty/cross_entity_state_dependency/psi_findings_waive_one_defect_class_but_not_another
    """
    world = _clean_inspection_world(api)
    buyer_id = world["buyer"]["id"]
    sale_id = world["sale"]["id"]

    assert world["inspection"]["status"] == "COMPLETED"
    assert world["inspection"]["findings"] == []
    assert world["inspection"]["fee_cents"] == 12500
    assert_instant_equals(
        world["inspection"]["completed_at_utc"],
        "2026-08-01T01:00:00.000Z",
        "completed_at_utc",
    )

    waived = api.create_case(
        case_payload(
            sale_id,
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=84010,
            complaint_text="Transmission slips despite the clean inspection",
        ),
        buyer_rep_headers(buyer_id),
    )
    validate_error(waived, ApiErrorId.ERR_PSI_WAIVED_RIGHTS.value)
    assert waived.status_code == 409

    admitted = validate_success(
        api.create_case(
            case_payload(
                sale_id,
                defect_class="FRAME_DAMAGE",
                claim_amount_cents=285000,
                odometer_at_claim=84010,
                complaint_text="Frame rail repair the inspection did not cover",
            ),
            buyer_rep_headers(buyer_id),
        ),
        201,
    )
    assert admitted["defect_class"] == "FRAME_DAMAGE"


def test_an_empty_findings_array_extends_no_window_and_leaves_one_case_standing(api):
    """The admitted claim applies no extension, because empty findings cannot
    name FRAME_DAMAGE, and the refused probe left nothing behind.

    PRD: "If `psi_clean_waives_rights` is false, a clean inspection is simply
    neutral and adds no extension."

    Design: Difficulty/cross_entity_state_dependency/psi_findings_waive_one_defect_class_but_not_another
    """
    world = _clean_inspection_world(api)
    buyer_id = world["buyer"]["id"]
    sale_id = world["sale"]["id"]

    api.create_case(
        case_payload(
            sale_id,
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=84010,
        ),
        buyer_rep_headers(buyer_id),
    )
    frame_case = create_case(
        api,
        sale_id,
        buyer_id,
        defect_class="FRAME_DAMAGE",
        claim_amount_cents=285000,
        odometer_at_claim=84010,
        complaint_text="Frame rail repair the inspection did not cover",
    )

    observed = validate_success(api.get_case(frame_case["id"], admin_headers()), 200)
    assert observed["psi_extension_applied_hours"] == 0
    assert observed["effective_window_hours"] == 168
    assert observed["hours_elapsed_at_claim"] == 1.0
    assert observed["window_eligible"] is True

    sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert sale["arbitration_status"] == "ACTIVE"
    assert sale["open_case_count"] == 1

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["lifetime_claim_count"] == 1
    assert buyer["open_claim_count"] == 1

    cases, meta = validate_paginated(
        api.list_cases(admin_headers(), params={"sale_id": sale_id})
    )
    assert meta["total_count"] == 1
    assert len(cases) == 1
    assert cases[0]["defect_class"] == "FRAME_DAMAGE"
