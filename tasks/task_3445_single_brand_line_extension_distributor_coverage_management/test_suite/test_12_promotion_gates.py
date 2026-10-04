"""Promotion approve-time gates (depth cap, MAP floor, cadence) and redemption
arithmetic (unit/case pricing, provisional-vs-actual funding, the budget)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assert_redemption,
    validate_error, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
MM = TEST_USERS["marketing_manager_headers"]
PA = TEST_USERS["pricing_analyst_headers"]
SP = TEST_USERS["supply_planner_headers"]


def test_promo_case_price_rounds_per_unit_before_case_multiply():
    """PRD §3.8: "The promotional unit price is the list price minus the unit funding, and the promotional case price multiplies that unit price by the pack's `case_pack_qty` — rounding happens **once**, at the unit level, before the multiplication; discounting the case gross and rounding at case level is non-conformant (a 499-cent list at 15.00 percent with a case of 12 must yield 5088 cents, not 5090)."
    PRD §3.8: "The redemption's total funding is the unit funding times the redeemed units, and it must fit the purse: the accrued funding plus this total may not exceed `funding_budget_cents` (`ERR_PROMO_BUDGET_EXCEEDED`, HTTP 409)."

    Design: Difficulty/combinatorial_formula/promo_case_price_rounds_per_unit_before_case_multiply
    """
    sc = fx.setup_launched_line()  # list 499/300 EFFECTIVE, case_pack_qty 12
    sc = fx.setup_live_promotion(
        scenario=sc,
        promo_overrides={"discount_pct": 15.00, "funding_budget_cents": 100000})
    promo_id = sc["promotion"]["id"]

    redemption = validate_success(api_client.create_redemption(
        promo_id, sc["pack"]["id"], 12, CM))
    assert_redemption(redemption)
    assert redemption["unit_funding_cents"] == 75, \
        "round_half_up(499 * 15.00 / 100) = round_half_up(74.85)"
    assert redemption["promo_unit_price_cents"] == 424, "499 - 75"
    assert redemption["promo_case_price_cents"] == 5088, \
        "424 * 12 — the case-level order would wrongly give 5090"
    assert redemption["total_funding_cents"] == 900, "75 * 12"
    assert redemption["accrued_funding_cents"] == 900
    assert redemption["remaining_budget_cents"] == 99100


def test_promo_depth_exactly_at_posture_cap():
    """PRD §3.8: "The depth cap tracks the brand's protection posture: `discount_pct` may not exceed 25.00 under `NORMAL`, 15.00 under `ELEVATED`, or 5.00 under `CRITICAL` (`ERR_PROMO_DEPTH_EXCEEDS_CAP`, HTTP 422)."
    PRD §3.8: "the provisional funding is that list's `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/promo_depth_exactly_at_posture_cap
    """
    sc = fx.setup_launched_line()  # posture NORMAL; list 499/300 EFFECTIVE
    line_id = sc["line"]["id"]

    promo_a = fx.create_promotion_record(
        line_id, discount_pct=25.00, starts_on="2026-10-01",
        ends_on="2026-10-31", funding_budget_cents=100000)
    validate_success(api_client.submit_promotion(promo_a["id"], PA))
    approved_a = validate_success(api_client.approve_promotion(promo_a["id"], MM))
    assert approved_a["status"] == "APPROVED", \
        "depth 25.00 equals the NORMAL cap of 25.00 and passes"
    assert approved_a["unit_funding_provisional_cents"] == 125, \
        "round_half_up(499 * 25.00 / 100) = round_half_up(124.75)"

    promo_b = fx.create_promotion_record(
        line_id, discount_pct=25.01, starts_on="2026-12-01",
        ends_on="2026-12-31", funding_budget_cents=100000)
    validate_success(api_client.submit_promotion(promo_b["id"], PA))
    resp = api_client.approve_promotion(promo_b["id"], MM)
    validate_error(resp, ApiErrorId.ERR_PROMO_DEPTH_EXCEEDS_CAP)

    after = validate_success(api_client.get_promotion(promo_b["id"], MM))
    assert after["status"] == "PENDING_APPROVAL"


def test_promo_funding_provisional_vs_actual_diverge():
    """PRD §3.8: "the provisional unit funding `unit_funding_provisional_cents` is computed once and never updated afterwards: among the line's packs that hold a non-`SUPERSEDED` list for the channel covering `starts_on`, the reference pack is the smallest by `size_ml` with ties broken by earliest `created_at`, and the provisional funding is that list's `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents."
    PRD §3.8: "The actual unit funding is priced fresh at redemption time: the price list `EFFECTIVE` right now for the redeemed pack and the promotion's channel is resolved exactly as in §3.7, and the per-unit funding is that list's `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents — this ACTUAL figure can diverge from the provisional one when the price list changed between `starts_on` and redemption."
    PRD §3.8: "If the approval lands while the current date already lies inside the promotion window, the promotion skips `APPROVED` and enters `LIVE` immediately." — here starts_on is in the future at approval, so it waits in APPROVED until the sweep.

    Design: Difficulty/dual_variant_calc/promo_funding_provisional_vs_actual_diverge
    """
    sc = fx.setup_launched_line(
        price_overrides={"effective_to": "2026-12-31T00:00:00Z"})
    promo = fx.create_promotion_record(
        sc["line"]["id"], discount_pct=15.00, starts_on="2026-10-01",
        ends_on="2026-10-31", funding_budget_cents=100000)
    validate_success(api_client.submit_promotion(promo["id"], PA))
    approved = validate_success(api_client.approve_promotion(promo["id"], MM))
    assert approved["status"] == "APPROVED", \
        "starts_on 2026-10-01 was in the future at approval"
    assert approved["unit_funding_provisional_cents"] == 75, \
        "round_half_up(499 * 15.00 / 100) frozen at approve"

    fx.advance_clock("2026-10-10T00:00:00Z")
    fx.create_price_list_record(
        sc["pack"]["id"], list_price_cents=599,
        effective_from="2026-10-15T00:00:00Z",
        effective_to="2027-03-01T00:00:00Z")
    fx.advance_clock("2026-10-20T00:00:00Z")

    redemption = validate_success(api_client.create_redemption(
        promo["id"], sc["pack"]["id"], 1, CM))
    assert_redemption(redemption)
    assert redemption["unit_funding_cents"] == 90, \
        "round_half_up(599 * 15.00 / 100) from the list EFFECTIVE at 2026-10-20"
    assert redemption["unit_funding_cents"] != 75, \
        "the variants diverge after the mid-window price change"
    assert redemption["accrued_funding_cents"] == 90
    assert redemption["remaining_budget_cents"] == 99910

    live = validate_success(api_client.get_promotion(promo["id"], MM))
    assert live["status"] == "LIVE", "the 2026-10-10 sweep opened the window"


def test_promo_selling_price_below_map_rejected_at_approve():
    """PRD §3.8: "The advertised-price floor must hold for **every** such pack and covering list: the list price minus the per-unit discount — the discount being `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents — must stay at or above that list's `map_price_cents` (`ERR_BELOW_MAP_PRICE`, HTTP 422)."

    Design: Corner/validations/promo_selling_price_below_map_rejected_at_approve
    """
    sc = fx.setup_launched_line(price_overrides={"map_price_cents": 449})
    promo = fx.create_promotion_record(
        sc["line"]["id"], discount_pct=20.00, starts_on="2026-10-01",
        ends_on="2026-10-31", funding_budget_cents=100000)
    validate_success(api_client.submit_promotion(promo["id"], PA))

    resp = api_client.approve_promotion(promo["id"], MM)
    validate_error(resp, ApiErrorId.ERR_BELOW_MAP_PRICE)

    after = validate_success(api_client.get_promotion(promo["id"], MM))
    assert after["status"] == "PENDING_APPROVAL"


def test_promo_gap_violation_under_fourteen_days():
    """PRD §3.8: "Then cadence, frequency before gap: among the promotion's peers — the other promotions of the same line and channel in `APPROVED`, `LIVE`, `SUSPENDED` or `ENDED` — those whose `starts_on` falls within 90 days before or after the candidate's `starts_on` must number fewer than 2 (`ERR_PROMO_TOO_FREQUENT`, HTTP 422); and every peer's `starts_on` must sit at least 14 days away in absolute terms (`ERR_PROMO_GAP_VIOLATION`, HTTP 422)."

    Design: Corner/validations/promo_gap_violation_under_fourteen_days
    """
    sc = fx.setup_approved_promotion(
        promo_overrides={"discount_pct": 10.00, "starts_on": "2026-10-01",
                         "ends_on": "2026-10-07"})
    line_id = sc["line"]["id"]

    promo2 = fx.create_promotion_record(
        line_id, discount_pct=10.00, starts_on="2026-10-10",
        ends_on="2026-10-17", funding_budget_cents=100000)
    validate_success(api_client.submit_promotion(promo2["id"], PA))
    resp = api_client.approve_promotion(promo2["id"], MM)
    validate_error(resp, ApiErrorId.ERR_PROMO_GAP_VIOLATION)


def test_promo_frequency_third_in_window_rejected():
    """PRD §3.8: "Then cadence, frequency before gap: among the promotion's peers — the other promotions of the same line and channel in `APPROVED`, `LIVE`, `SUSPENDED` or `ENDED` — those whose `starts_on` falls within 90 days before or after the candidate's `starts_on` must number fewer than 2 (`ERR_PROMO_TOO_FREQUENT`, HTTP 422); and every peer's `starts_on` must sit at least 14 days away in absolute terms (`ERR_PROMO_GAP_VIOLATION`, HTTP 422)."

    Design: Corner/validations/promo_frequency_third_in_window_rejected
    """
    sc = fx.setup_approved_promotion(
        promo_overrides={"discount_pct": 10.00, "starts_on": "2026-10-01",
                         "ends_on": "2026-10-20"})
    line_id = sc["line"]["id"]
    sc = fx.setup_approved_promotion(
        scenario=sc,
        promo_overrides={"discount_pct": 10.00, "starts_on": "2026-11-15",
                         "ends_on": "2026-11-30"})

    promo3 = fx.create_promotion_record(
        line_id, discount_pct=10.00, starts_on="2026-12-30",
        ends_on="2027-01-10", funding_budget_cents=100000)
    validate_success(api_client.submit_promotion(promo3["id"], PA))
    resp = api_client.approve_promotion(promo3["id"], MM)
    validate_error(resp, ApiErrorId.ERR_PROMO_TOO_FREQUENT)


def test_promo_budget_boundary_exact_and_over():
    """PRD §3.8: "The redemption's total funding is the unit funding times the redeemed units, and it must fit the purse: the accrued funding plus this total may not exceed `funding_budget_cents` (`ERR_PROMO_BUDGET_EXCEEDED`, HTTP 409). On success `accrued_funding_cents` grows by the total and `redemptions_count` increments by one."

    Design: Corner/validations/promo_budget_boundary_exact_and_over
    """
    sc = fx.setup_launched_line(price_overrides={"list_price_cents": 3000})
    sc = fx.setup_live_promotion(
        scenario=sc,
        promo_overrides={"discount_pct": 15.00, "funding_budget_cents": 9000})
    promo_id = sc["promotion"]["id"]
    pack_id = sc["pack"]["id"]

    over = api_client.create_redemption(promo_id, pack_id, 21, CM)
    validate_error(over, ApiErrorId.ERR_PROMO_BUDGET_EXCEEDED)
    assert validate_success(api_client.get_promotion(promo_id, MM))[
        "accrued_funding_cents"] == 0, "the over-budget redemption is atomic"

    exact = validate_success(api_client.create_redemption(promo_id, pack_id, 20, CM))
    assert exact["accrued_funding_cents"] == 9000, "exact exhaustion is allowed"
    assert exact["remaining_budget_cents"] == 0

    one_more = api_client.create_redemption(promo_id, pack_id, 1, CM)
    validate_error(one_more, ApiErrorId.ERR_PROMO_BUDGET_EXCEEDED)


def test_redemption_pack_must_belong_to_promotion_line():
    """PRD §3.8: "The pack must belong to the promotion's line (`ERR_PACK_LINE_MISMATCH`, HTTP 422)."

    Design: Corner/errors/redemption_pack_must_belong_to_promotion_line
    """
    sc = fx.setup_launched_line(
        line_overrides={"line_code": "EXT-1", "name": "Extension One",
                        "is_core": False})
    brand_id = sc["brand"]["id"]

    line2 = fx.create_product_line(brand_id, line_code="EXT-2",
                                   name="Extension Two", is_core=False)
    form2 = fx.create_and_seal_formulation(line2["id"])
    fx.approve_line_to_pilot(line2["id"])
    fx.create_active_grant(sc["mfr1"]["id"], form2["id"],
                           component_scope=["C1", "C2"])
    fx.create_active_grant(sc["mfr2"]["id"], form2["id"],
                           component_scope=["C3", "C4"])
    pack2 = fx.create_tooled_pack(line2["id"], size_ml=59,
                                  delivery_system="TRIGGER_SPRAY",
                                  channel_restrictions=["HARDWARE"],
                                  case_pack_qty=24)
    fx.create_price_list_record(pack2["id"], list_price_cents=399,
                                map_price_cents=250)
    validate_success(api_client.enter_production_pack_format(pack2["id"], SP))
    validate_success(api_client.launch_product_line(line2["id"], BM))

    sc = fx.setup_live_promotion(scenario=sc)  # LIVE promotion on EXT-1
    promo_id = sc["promotion"]["id"]

    resp = api_client.create_redemption(promo_id, pack2["id"], 5, CM)
    validate_error(resp, ApiErrorId.ERR_PACK_LINE_MISMATCH)

    after = validate_success(api_client.get_promotion(promo_id, MM))
    assert after["accrued_funding_cents"] == 0
