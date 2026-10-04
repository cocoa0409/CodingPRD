"""Closeout workflow: markdown recovery, cascades, closeout cycle, retirement."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    create_commitment,
    fixtures,
    set_clock,
    setup_committed_line,
    setup_evergreen_line_with_sku,
    setup_retail_open_review,
    setup_tooled_line,
    validate_error,
    validate_success,
)


def _get_review(api, review_id):
    return validate_success(api.get_line_review(review_id, BRAND))


def _get_commitment(api, commitment_id):
    return validate_success(api.get_commitment(commitment_id, BRAND))


def test_markdown_recovery_damped_deep_discount_pinned_rounding_order(api):
    """PRD §3.7: "the average unit price is the sum of `committed_units` times
    `unit_price_cents` over those commitments, divided by the total committed
    units, rounded half-up to whole cents; the effective markdown is the supplied
    `markdown_pct` when it is below 50%, while at or above 50% a deep-discount
    damping halves the excess — the effective percentage is 50% plus half of the
    amount by which the supplied markdown exceeds 50%. The recovery is then the
    total committed units times the average price times the effective percentage,
    rounded half-up to whole cents".
    PRD §3.7: "Entering closeout stores the supplied markdown verbatim in
    `closeout_markdown_pct` for audit".

    Design: Difficulty/combinatorial_formula/markdown_recovery_damped_deep_discount_pinned_rounding_order
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer, review = setup_retail_open_review()
    create_commitment(review["id"], sku["id"], committed_units=3, unit_price_cents=333, shelf_slots=2)
    create_commitment(review["id"], sku["id"], committed_units=3, unit_price_cents=335, shelf_slots=2)
    line = fixtures.advance_line(line)  # TOOLED -> COMMITTED

    data = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.70}, BRAND))
    # avg = round_half_up((3*333 + 3*335)/6) = 334; eff = 0.50 + 0.20/2 = 0.60;
    # recovery = round_half_up(6 * 334 * 0.60) = 1202.
    assert data["closeout_recovery_cents"] == 1202
    assert data["closeout_markdown_pct"] == 0.70


def test_markdown_recovery_below_knee_uses_supplied_markdown(api):
    """PRD §3.7: "the effective markdown is the supplied `markdown_pct` when it is
    below 50%".

    Design: Difficulty/combinatorial_formula/markdown_recovery_damped_deep_discount_pinned_rounding_order
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer, review = setup_retail_open_review()
    create_commitment(review["id"], sku["id"], committed_units=10, unit_price_cents=500, shelf_slots=2)
    line = fixtures.advance_line(line)

    data = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.40}, BRAND))
    # avg 500; eff 0.40; recovery = 10 * 500 * 0.40 = 2000.
    assert data["closeout_recovery_cents"] == 2000
    assert data["closeout_markdown_pct"] == 0.40


def test_closeout_empty_commitment_set_yields_zero_recovery(api):
    """PRD §3.7: "The recovery is then the total committed units times the average
    price times the effective percentage, rounded half-up to whole cents; an empty
    commitment set yields a recovery of 0."

    Design: Difficulty/boundary_precision_check/closeout_empty_commitment_set_yields_zero_recovery
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, retailer, review, commitment, factory, order = setup_committed_line(
        commitment_overrides={"committed_units": 100, "unit_price_cents": 500, "shelf_slots": 4}
    )
    # Cancel the only commitment while the review is still OPEN, leaving an empty
    # COMMITTED/AT_RISK set for the recovery to work on.
    validate_success(api.cancel_commitment(commitment["id"], {}, BRAND))

    data = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.40}, BRAND))
    assert data["closeout_recovery_cents"] == 0
    assert data["status"] == "CLOSEOUT"


def test_closeout_empty_recovery_from_on_shelf_line(api):
    """PRD §3.7: "a line already `ON_SHELF` may enter closeout unconditionally."
    PRD §3.7: "an empty commitment set yields a recovery of 0."

    Design: Difficulty/boundary_precision_check/closeout_empty_commitment_set_yields_zero_recovery
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, retailer, review, commitment, factory, order = setup_committed_line(
        commitment_overrides={"committed_units": 100, "unit_price_cents": 500, "shelf_slots": 4}
    )
    validate_success(api.cancel_commitment(commitment["id"], {}, BRAND))
    # Street date 2026-09-01 is already at/before the clock: a clock set fires the
    # COMMITTED -> ON_SHELF auto-advance.
    set_clock("2026-10-02T00:00:00Z")
    line_data = validate_success(api.get_toy_line(line["id"], BRAND))
    assert line_data["status"] == "ON_SHELF"

    data = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.40}, BRAND))
    assert data["closeout_recovery_cents"] == 0
    assert data["status"] == "CLOSEOUT"


def test_enter_closeout_cascades_to_commitments_and_reviews(api):
    """PRD §3.7: "Entering closeout stores the supplied markdown verbatim in
    `closeout_markdown_pct` for audit, computes `closeout_recovery_cents`, cancels
    every `COMMITTED` or `AT_RISK` commitment referencing the line's SKUs,
    recomputes each affected review's `shelf_slots_used` with the cancelled
    commitments' slots freed, and increments the line's `version`."

    Design: Difficulty/transitive_cascade/enter_closeout_cascades_to_commitments_and_reviews
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer_a, review_a = setup_retail_open_review(retailer_name="ToyBox")
    retailer_b, review_b = setup_retail_open_review(retailer_name="MegaMart")
    c_a = create_commitment(review_a["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=4)
    c_b = create_commitment(review_b["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=6)
    line = fixtures.advance_line(line)  # TOOLED -> COMMITTED (c_a satisfies the gate)

    data = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.30}, BRAND))
    assert data["status"] == "CLOSEOUT"
    assert _get_commitment(api, c_a["id"])["status"] == "CANCELLED"
    assert _get_commitment(api, c_b["id"])["status"] == "CANCELLED"
    assert _get_review(api, review_a["id"])["shelf_slots_used"] == 0
    assert _get_review(api, review_b["id"])["shelf_slots_used"] == 0


def test_enter_closeout_preserves_already_cancelled_commitments(api):
    """PRD §3.6: "The review's `shelf_slots_used` is always the sum of `shelf_slots`
    over its commitments in `COMMITTED` or `AT_RISK` status — an `AT_RISK`
    commitment still occupies its slots, since the retailer is holding the space
    pending the shifted release — and it is recomputed on every commitment create,
    cancel, or cascade-cancel."

    Design: Difficulty/transitive_cascade/enter_closeout_cascades_to_commitments_and_reviews
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer, review = setup_retail_open_review()
    c1 = create_commitment(review["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=4)
    c2 = create_commitment(review["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=6)
    line = fixtures.advance_line(line)

    # Cancel c2 first (frees its 6 slots); closeout cancels c1 only.
    validate_success(api.cancel_commitment(c2["id"], {}, BRAND))
    assert _get_review(api, review["id"])["shelf_slots_used"] == 4

    validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.30}, BRAND))
    assert _get_commitment(api, c1["id"])["status"] == "CANCELLED"
    assert _get_commitment(api, c2["id"])["status"] == "CANCELLED"
    assert _get_review(api, review["id"])["shelf_slots_used"] == 0


def test_toy_line_closeout_reopen_cycle_with_safety_regression(api):
    """PRD §3.7: "Closeout is reversible in one direction: a `BrandManager` may exit
    closeout, returning the line from `CLOSEOUT` to `COMMITTED` and re-opening it
    for fresh commitments — previously cancelled commitments stay `CANCELLED`".

    Design: Difficulty/non_linear_state_machine/toy_line_closeout_reopen_cycle_with_safety_regression
    """
    set_clock("2026-10-01T00:00:00Z")
    # Build the line manually so a second SKU can run its own independent
    # safety test cycle on the SAME line — §3.4 gates submissions to lines in
    # CONCEPT/IN_DEVELOPMENT, so the cycle must run before the line is tooled.
    line = fixtures.create_evergreen_line(name="Evergreen Blocks", street="2027-01-01T00:00:00Z")
    sku2 = fixtures.create_sku(
        line["id"],
        name="Block Bucket v2",
        age_grade_months=48,
        moq_units=100,
        unit_cost_cents=100,
        tooling_cost_cents=10000,
    )
    test2 = fixtures.submit_safety_test(sku2, test_type="CHEMICAL")
    fixtures.pass_safety_test(test2, sku2)
    sku2_data = validate_success(api.get_sku(sku2["id"], BRAND))
    assert sku2_data["safety_status"] == "PASSED"

    line = fixtures.advance_line(line)  # CONCEPT -> IN_DEVELOPMENT
    sku = fixtures.create_sku(line["id"], age_grade_months=48)
    sku = fixtures.certify_sku(sku)
    factory = fixtures.create_factory(capacity_units_per_month=100000)
    order = fixtures.create_tooling_order(
        line["id"], sku["id"], factory["id"], production_month="2026-11", units=100
    )
    line = fixtures.advance_line(line)  # IN_DEVELOPMENT -> TOOLED
    retailer, review = fixtures.setup_retail_open_review()
    commitment = fixtures.create_commitment(
        review["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=4
    )
    line = fixtures.advance_line(line)  # TOOLED -> COMMITTED

    closed = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.30}, BRAND))
    assert closed["status"] == "CLOSEOUT"
    reopened = validate_success(api.exit_closeout(line["id"], {}, BRAND))
    assert reopened["status"] == "COMMITTED"
    assert _get_commitment(api, commitment["id"])["status"] == "CANCELLED"

    # The regression side of the cycle: editing sku2's age grade invalidates
    # its certification even though the line is far past development.
    edited = validate_success(api.patch_sku(sku2["id"], {"age_grade_months": 60}, BRAND))
    assert edited["safety_status"] == "FAILED"
    assert edited["claims_validated"] is False


def test_toy_line_closeout_reopen_allows_fresh_commitment(api):
    """PRD §3.7: "a `BrandManager` may exit closeout, returning the line from
    `CLOSEOUT` to `COMMITTED` and re-opening it for fresh commitments — previously
    cancelled commitments stay `CANCELLED`, so an enter-then-exit cycle leaves each
    affected review's `shelf_slots_used` strictly lower by the cancelled
    commitments' slots until new commitments re-occupy them."

    Design: Difficulty/non_linear_state_machine/toy_line_closeout_reopen_cycle_with_safety_regression
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, retailer, review, commitment, factory, order = setup_committed_line(
        street="2027-01-01T00:00:00Z",
        line_name="Evergreen Blocks",
        commitment_overrides={"committed_units": 100, "unit_price_cents": 500, "shelf_slots": 4},
    )
    validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.30}, BRAND))
    assert _get_review(api, review["id"])["shelf_slots_used"] == 0
    validate_success(api.exit_closeout(line["id"], {}, BRAND))

    # Fresh commitments are accepted again on the re-opened line's SKU.
    c_new = create_commitment(review["id"], sku["id"], committed_units=50, unit_price_cents=400, shelf_slots=2)
    assert c_new["status"] == "COMMITTED"
    assert _get_commitment(api, commitment["id"])["status"] == "CANCELLED"


def test_closeout_exit_cycle_frees_and_reoccupies_shelf_slots(api):
    """PRD §3.6: "The review's `shelf_slots_used` is always the sum of `shelf_slots`
    over its commitments in `COMMITTED` or `AT_RISK` status — an `AT_RISK`
    commitment still occupies its slots, since the retailer is holding the space
    pending the shifted release — and it is recomputed on every commitment create,
    cancel, or cascade-cancel."
    PRD §3.7: "an enter-then-exit cycle leaves each affected review's
    `shelf_slots_used` strictly lower by the cancelled commitments' slots until new
    commitments re-occupy them."

    Design: Difficulty/compensating_invariant/closeout_exit_cycle_frees_and_reoccupies_shelf_slots
    """
    set_clock("2026-10-01T00:00:00Z")
    # Line EL with sku SK1 (will be committed then closed out).
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    # A second evergreen line + SKU sharing the same review.
    line2 = fixtures.create_evergreen_line(name="Classic Plush", street="2026-09-01T00:00:00Z")
    sku2 = fixtures.create_sku(line2["id"], name="Plush Bear")

    retailer, review = setup_retail_open_review(shelf_slots_total=20)
    c1 = create_commitment(review["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=6)
    c2 = create_commitment(review["id"], sku2["id"], committed_units=100, unit_price_cents=500, shelf_slots=5)
    line = fixtures.advance_line(line)  # TOOLED -> COMMITTED

    assert _get_review(api, review["id"])["shelf_slots_used"] == 11  # 6 + 5

    validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.30}, BRAND))
    # Only c1 cancelled; c2 (other line) untouched.
    assert _get_review(api, review["id"])["shelf_slots_used"] == 5

    validate_success(api.exit_closeout(line["id"], {}, BRAND))
    c3 = create_commitment(review["id"], sku["id"], committed_units=50, unit_price_cents=400, shelf_slots=4)
    assert _get_review(api, review["id"])["shelf_slots_used"] == 9  # 5 + 4
    assert _get_commitment(api, c1["id"])["status"] == "CANCELLED"
    assert _get_commitment(api, c3["id"])["status"] == "COMMITTED"


def test_closeout_cycle_shelf_slots_invariant_holds_at_each_step(api):
    """PRD §3.6: "The review's `shelf_slots_used` is always the sum of `shelf_slots`
    over its commitments in `COMMITTED` or `AT_RISK` status".

    Design: Difficulty/compensating_invariant/closeout_exit_cycle_frees_and_reoccupies_shelf_slots
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer, review = setup_retail_open_review(shelf_slots_total=20)
    c1 = create_commitment(review["id"], sku["id"], committed_units=100, unit_price_cents=500, shelf_slots=6)
    line = fixtures.advance_line(line)

    assert _get_review(api, review["id"])["shelf_slots_used"] == 6
    validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.30}, BRAND))
    assert _get_review(api, review["id"])["shelf_slots_used"] == 0
    validate_success(api.exit_closeout(line["id"], {}, BRAND))
    # Exit alone does not resurrect the cancelled commitment.
    assert _get_review(api, review["id"])["shelf_slots_used"] == 0
    c2 = create_commitment(review["id"], sku["id"], committed_units=10, unit_price_cents=400, shelf_slots=6)
    assert _get_review(api, review["id"])["shelf_slots_used"] == 6


def test_retire_blocked_by_approved_tooling_order(api):
    """PRD §3.7: "From `CLOSEOUT` a line may instead be retired to `RETIRED`, its
    terminal state, but only when no shipment referencing the line's SKUs remains
    `PLANNED` and no tooling order of the line remains `APPROVED`; otherwise the
    retire is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retired_line_is_terminal_no_transitions
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, retailer, review, commitment, factory, order = setup_committed_line()
    validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.20}, BRAND))
    # Tooling order still APPROVED: retire rejected.
    resp = api.retire_toy_line(line["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
