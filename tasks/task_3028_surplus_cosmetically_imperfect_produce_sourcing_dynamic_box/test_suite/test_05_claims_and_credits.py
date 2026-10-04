"""Quality claims: the credit ceiling, reason ranking, evidence and reopen."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    LINE_CAP_RATE,
    ApiErrorId,
    build_order,
    make_bid,
    make_center,
    make_lot,
    make_supplier,
    reset_clock,
    setup_box_scenario,
    setup_subscriber,
)
from test_helpers.fixtures import (
    advance_clock,
    award_lot,
    file_claim,
    line_plan,
    make_lot_ready,
    order_claims,
    order_items,
    pack_order,
    refresh_lot,
    refresh_order,
    review_claim,
)

# A FRUIT lot at 125 cents whose own-grade quote sets a display price of 200
# cents: one six-unit line bills at 120 grams and its line price is the frozen
# billing weight priced on a per-kilogram basis (120 * 200 / 1000 = 24 cents),
# so the 75 per cent line cap is 18.
LINE_CAP_LOT_COST_CENTS = 125
LINE_CAP_UNITS = 6
LINE_CAP_EXPECTED_CENTS = 18
LINE_CAP_DISPLAY_CENTS = 200
LINE_CAP_LINE_PRICE_CENTS = 24


def _claim_ready_order(api, *, unit_cost_cents=LINE_CAP_LOT_COST_CENTS, units=LINE_CAP_UNITS,
                       email="cred@example.com", **scenario_kwargs):
    """A packed order built from one quoted lot, with its line still INCLUDED."""
    scenario = setup_box_scenario(
        api, cycles=(2,), email=email,
        lot_overrides={"category": "FRUIT", "procurement_grade": "SURPLUS",
                       "unit_weight_grams": 100, "unit_cost_cents": unit_cost_cents,
                       "quantity_available": 600},
        **scenario_kwargs,
    )
    lot = scenario["lot"]
    quote = get_success_data(
        api.create_quote(
            {"supply_lot_id": lot["id"], "retailer_label": "Conventional Co",
             "source_url": "https://ref.example.com/credit",
             "captured_at": "2026-08-30T00:00:00Z",
             "conventional_unit_price_cents": 500,
             "barcode_gtin": "00012345678905", "grade_equivalent": True},
            ADMIN,
        )
    )
    validate_success(api.substantiate_quote(quote["id"], {}, ADMIN), 200)
    built = build_order(api, scenario["orders"][0], scenario["center"],
                        line_plan((lot["id"], units)))
    assert built["status"] == "BUILDING", "Setup failed: the order did not build"
    packed = pack_order(api, built, scenario["center"])
    items = [i for i in order_items(api, packed) if i["status"] == "INCLUDED"]
    assert items, "Setup failed: the packed order carries no INCLUDED line"
    scenario["order"] = packed
    scenario["items"] = items
    return scenario


# ---------------------------------------------------------------------------
# The credit ceiling: which cap binds
# ---------------------------------------------------------------------------
def test_credit_line_cap_binds_when_the_request_is_generous(api):
    """PRD §3.3: "The second is three quarters of the line's `line_price_cents`,
    rounded half-up to two decimal places."
    PRD §3.3: "The issued value, written to `credited_cents`, is the minimum of
    those three."
    PRD §3.3: "the implementation takes the seventy-five-per cent line cap first
    and the grace ceiling second, so whichever of the two ceilings is lower is
    the one that binds"

    Design: Difficulty/dual_variant_calc/quality_credit_cap_then_grace_vs_grace_then_cap
    """
    scenario = _claim_ready_order(api, email="capbinds@example.com")
    order, item = scenario["order"], scenario["items"][0]
    assert item["line_price_cents"] == LINE_CAP_LINE_PRICE_CENTS, (
        "Setup failed: the line must price at 144 cents for this cap table"
    )
    assert item["billed_unit_weight_grams"] == 120
    claim = file_claim(api, order, item["id"], reason_code="SPOILED",
                       requested_credit_cents=500)
    upheld = review_claim(api, claim, "UPHELD")

    assert upheld["status"] == "UPHELD"
    # The 75 per cent line cap of 18 is below the grace ceiling (700) and the
    # per-reason unit credit (1800), so it is the binding ceiling.
    assert upheld["credited_cents"] == LINE_CAP_EXPECTED_CENTS
    supplier = get_success_data(api.get_supplier(scenario["supplier"]["id"], ADMIN))
    assert supplier["claims_upheld_total"] == 1


def test_credit_grace_ceiling_binds_when_the_request_is_small(api):
    """PRD §3.3: "The third is the customer's request plus a grace allowance:
    `requested_credit_cents` plus whichever is smaller of
    `requested_credit_cents` and the 200-cent per-claim grace, which means a
    request of 100 cents can reach at most 200 cents"
    PRD §3.3: "The issued value, written to `credited_cents`, is the minimum of
    those three."

    Design: Difficulty/dual_variant_calc/quality_credit_cap_then_grace_vs_grace_then_cap
    """
    scenario = _claim_ready_order(api, email="gracebinds@example.com")
    order, item = scenario["order"], scenario["items"][0]
    claim = file_claim(api, order, item["id"], reason_code="SPOILED",
                       requested_credit_cents=5)
    upheld = review_claim(api, claim, "UPHELD")

    # 5 + min(5, 200) = 10, which is below the 18 cent line cap and the 1800
    # cent per-reason credit, so the grace ceiling is the binding one.
    assert upheld["credited_cents"] == 10


def test_a_zero_cent_claim_is_refused_as_not_credible(api):
    """PRD §3.3: "A claim cannot be credible if it asks for nothing: a
    `requested_credit_cents` of exactly zero is refused with
    `ERR_CLAIM_NOT_CREDIBLE` and HTTP status 422, and that check runs before any
    assessment of the cited lot's quality"
    PRD §3.9: "Seventh is claim credibility, and its position is deliberate: a
    quality claim whose `requested_credit_cents` is exactly zero is refused as
    not credible with `ERR_CLAIM_NOT_CREDIBLE` and HTTP status 422 *before* any
    assessment of the cited lot's quality"

    Design: Corner/calculations/quality_credit_boundary_at_the_floor_of_the_grace_window
    """
    scenario = _claim_ready_order(api, email="zerocredit@example.com")
    order, item = scenario["order"], scenario["items"][0]
    claim = file_claim(api, order, item["id"], reason_code="SPOILED",
                       requested_credit_cents=0)

    response = api.review_quality_claim(
        claim["id"], {"outcome": "UPHELD", "expected_claim_version": claim["version"]}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_CREDIBLE, 422)

    still = order_claims(api, order)
    assert len(still) == 1
    assert still[0]["status"] == "IN_REVIEW"
    assert still[0]["credited_cents"] == 0


def test_the_smallest_credible_request_is_upheld(api):
    """PRD §3.3: "The third is the customer's request plus a grace allowance:
    `requested_credit_cents` plus whichever is smaller of
    `requested_credit_cents` and the 200-cent per-claim grace"
    PRD §3.3: "a `requested_credit_cents` of exactly zero is refused with
    `ERR_CLAIM_NOT_CREDIBLE`"

    Design: Corner/calculations/quality_credit_boundary_at_the_floor_of_the_grace_window
    """
    scenario = _claim_ready_order(api, email="onecent@example.com")
    order, item = scenario["order"], scenario["items"][0]
    claim = file_claim(api, order, item["id"], reason_code="SPOILED",
                       requested_credit_cents=1)
    upheld = review_claim(api, claim, "UPHELD")

    # 1 + min(1, 200) = 2, the smallest credible credit the rule can issue.
    assert upheld["status"] == "UPHELD"
    assert upheld["credited_cents"] == 2


# ---------------------------------------------------------------------------
# Reason-code ranking
# ---------------------------------------------------------------------------
def test_credit_reason_code_multipliers_rank_the_four_reasons(api):
    """PRD §3.3: "The first is a per-reason unit credit: the flat figure for
    the claim's `reason_code` — 300 cents for `SPOILED`, 350 for `DAMAGED`, 300
    for `MISSING_ITEM` and 400 for `TEMPERATURE_ABUSE` — multiplied by the
    number of `units` on the cited build item and then by a grade multiplier"
    PRD §3.3: "The issued value, written to `credited_cents`, is the minimum of
    those three."

    Design: Corner/calculations/credit_reason_code_multipliers_rank_the_four_reasons
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=20)
    supplier = make_supplier(api, name="Reason Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="BEVERAGE",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=12000, quantity_available=2000, product_name="RC")
    quote = get_success_data(
        api.create_quote(
            {"supply_lot_id": lot["id"], "retailer_label": "Conventional Co",
             "source_url": "https://ref.example.com/rc",
             "captured_at": "2026-08-30T00:00:00Z",
             "conventional_unit_price_cents": 50000,
             "barcode_gtin": "00012345678905", "grade_equivalent": True},
            ADMIN,
        )
    )
    validate_success(api.substantiate_quote(quote["id"], {}, ADMIN), 200)
    make_bid(api, lot["id"], supplier["id"], cost=12000, quantity=2000)
    lot = make_lot_ready(api, award_lot(api, lot), "PASS")
    lot = refresh_lot(api, lot)
    # 19200 cents a unit, billed at the 300 gram BEVERAGE floor: the six-unit
    # line prices at 5760 cents per billed gram-kilogram basis, so the 75 per
    # cent line cap of 4320 clears every per-reason ceiling (2400 at most) and
    # the per-reason unit credit is the binding one for all four reasons.
    assert lot["display_price_cents"] == 19200

    expected = {
        "SPOILED": 300 * 6,
        "DAMAGED": 350 * 6,
        "MISSING_ITEM": 300 * 6,
        "TEMPERATURE_ABUSE": 400 * 6,
    }
    observed = {}
    for index, reason in enumerate(expected):
        # Each order is opened at the default clock: the previous iteration
        # walked the clock forward to build its box, and a cycle-2 order can
        # only meet its cutoff while the clock is still before its deadline.
        reset_clock(api)
        customer, subscription = setup_subscriber(
            api, region="NE", email=f"rc{index}@example.com"
        )
        order = get_success_data(
            api.create_box_order(
                {"customer_id": customer["id"], "subscription_id": subscription["id"],
                 "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
                ADMIN,
            )
        )
        built = build_order(api, order, center, line_plan((lot["id"], 6)))
        assert built["pricing_status"] == "PRICED", (
            f"Setup failed: the {reason} order did not price in one pass"
        )
        packed = pack_order(api, built, center)
        item = [i for i in order_items(api, packed) if i["status"] == "INCLUDED"][0]
        assert item["units"] == 6
        claim = file_claim(api, packed, item["id"], reason_code=reason,
                           requested_credit_cents=5000)
        observed[reason] = review_claim(api, claim, "UPHELD")["credited_cents"]

    assert observed == expected


# ---------------------------------------------------------------------------
# Claim evidence and the cited-lot snapshot
# ---------------------------------------------------------------------------
def test_claim_without_an_image_extension_is_refused(api):
    """PRD §3.3: "the `photo_url` path must end in one of the accepted image
    extensions `.jpg`, `.jpeg`, `.png`, `.webp` or `.heic`, and a claim whose
    evidence URL does not end in one of those is refused with
    `ERR_CLAIM_EVIDENCE_REQUIRED` and HTTP status 422."
    PRD §3.9: "Thirteenth is photo evidence: a quality claim must carry a
    `photo_url` whose path ends in one of the accepted image extensions"

    Design: Corner/validations/claim_photo_url_without_an_image_extension_is_refused
    """
    scenario = _claim_ready_order(api, email="pvevidence@example.com")
    order, item = scenario["order"], scenario["items"][0]

    response = api.create_quality_claim(
        order["id"],
        {"box_build_item_id": item["id"], "reason_code": "SPOILED",
         "photo_url": "https://cdn.example.com/evo/receipt.pdf",
         "requested_credit_cents": 300},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_EVIDENCE_REQUIRED, 422)

    assert len(order_claims(api, order)) == 0


def test_claim_create_derives_the_lot_and_snapshots_its_quality(api):
    """PRD §3.3: "a filed claim also carries a derived pointer back to the lot:
    `supply_lot_id` is derived from the claimed build item rather than supplied
    by the customer."
    PRD §3.3: "it freezes the lot's quality standing at the moment of filing
    into `cited_lot_quality_status`, so a later reviewer can see what the lot
    looked like when the customer complained rather than what it looks like at
    review time."

    Design: Corner/endpoints/claim_create_snapshots_the_cited_lots_quality_status
    """
    scenario = _claim_ready_order(api, email="snapshot@example.com")
    order, item = scenario["order"], scenario["items"][0]
    claim = file_claim(api, order, item["id"], reason_code="SPOILED",
                       requested_credit_cents=500)

    assert claim["supply_lot_id"] == item["supply_lot_id"]
    assert claim["supply_lot_id"] == scenario["lot"]["id"]
    assert claim["cited_lot_quality_status"] == "PASS"
    assert claim["status"] == "IN_REVIEW"
    assert claim["credited_cents"] == 0
    assert claim["outcome"] is None

    listed = order_claims(api, order)
    assert len(listed) == 1


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------
def test_reopen_of_an_upheld_claim_is_refused(api):
    """PRD §3.3: "A `REJECTED` claim is not necessarily finished: it may be
    reopened for a fresh review, which returns it to `IN_REVIEW`"
    PRD §3.3: "which along with `UPHELD` and `REJECTED` is one of the three
    outcomes that end a claim's life"

    Design: Corner/state_machines/quality_claim_reopen_after_upheld_returns_invalid_state
    """
    scenario = _claim_ready_order(api, email="reopenupheld@example.com")
    order, item = scenario["order"], scenario["items"][0]
    claim = file_claim(api, order, item["id"], reason_code="SPOILED",
                       requested_credit_cents=500)
    upheld = review_claim(api, claim, "UPHELD")
    assert upheld["status"] == "UPHELD"

    response = api.reopen_quality_claim(upheld["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    listed = order_claims(api, order)[0]
    assert listed["status"] == "UPHELD"
    assert listed["credited_cents"] == LINE_CAP_EXPECTED_CENTS


def test_reopen_of_a_rejected_claim_returns_it_to_in_review(api):
    """PRD §3.3: "A `REJECTED` claim is not necessarily finished: it may be
    reopened for a fresh review, which returns it to `IN_REVIEW` so that a new
    decision is required, but only while the cited lot's status is not
    `EXPIRED`"
    PRD §3.3: "Rejection also moves a claim to a plain close when the claim's
    `created_at` is at least the seven-day window ahead of the current logical
    clock — that is, when the claim is young enough that the escalation path did
    not open — leaving `credited_cents` at zero"

    Design: Corner/state_machines/quality_claim_reopen_from_rejected_returns_to_in_review
    """
    scenario = _claim_ready_order(api, email="reopenrejected@example.com")
    order, item = scenario["order"], scenario["items"][0]

    # A first upheld claim pushes the cited lot into INVESTIGATION, which is
    # the precondition an escalation needs, and clears the claim's age into the
    # window so a second rejection lands on UNDER_REVIEW rather than CLOSED.
    first = file_claim(api, order, item["id"], reason_code="SPOILED",
                       photo_url="https://cdn.example.com/evo/rr0.jpg",
                       requested_credit_cents=500)
    review_claim(api, first, "UPHELD")
    built_at = get_success_data(api.get_box_order(order["id"], ADMIN))["ready_deadline"]
    escalation_instant = (
        __import__("datetime").datetime.strptime(built_at[:19], "%Y-%m-%dT%H:%M:%S")
        + __import__("datetime").timedelta(days=8)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    advance_clock(api, escalation_instant)

    second = file_claim(api, order, item["id"], reason_code="SPOILED",
                        photo_url="https://cdn.example.com/evo/rr1.jpg",
                        requested_credit_cents=500)
    escalated = review_claim(api, second, "REJECTED")
    assert escalated["status"] == "UNDER_REVIEW"

    # The rejection from UNDER_REVIEW is terminal for the claim and drives the
    # cited lot to its terminal REJECTED quality outcome.
    rejected = review_claim(api, escalated, "REJECTED")
    assert rejected["status"] == "REJECTED"
    assert rejected["credited_cents"] == 0

    reopened = validate_success(
        api.reopen_quality_claim(rejected["id"], {}, ADMIN), 200
    )
    assert reopened["status"] == "IN_REVIEW"
    assert reopened["credited_cents"] == 0
    assert reopened["version"] > rejected["version"]