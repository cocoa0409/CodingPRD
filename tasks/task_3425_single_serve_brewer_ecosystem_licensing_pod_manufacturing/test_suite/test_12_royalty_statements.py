"""Royalty statements: provisional vs final, tiers, multipliers, disputes."""
from test_helpers import (
    FINANCE,
    ApiErrorId,
    create_active_agreement,
    create_agreement,
    create_audit,
    create_brand,
    create_statement,
    get_success_data,
    issue_statement,
    transition_statement,
    validate_error,
    validate_success,
)

TIER_SCHEDULE = [
    {"up_to_units": 1000000, "millicents_per_pod": 750},
    {"up_to_units": 5000000, "millicents_per_pod": 900},
    {"up_to_units": None, "millicents_per_pod": 1100},
]


def _active_agreement(exclusive=False, brand_name="Royalty Co", tiers=None):
    brand = create_brand(kind="LICENSED", name=brand_name)
    agreement = create_active_agreement(
        brand["id"], royalty_tiers=tiers if tiers is not None else TIER_SCHEDULE,
        quality_min_cup_score=80, exclusive=exclusive)
    return brand, agreement


def _get_statement(api, agreement_id, statement_id):
    rows = get_success_data(api.list_royalty_statements(agreement_id, FINANCE))
    matches = [row for row in rows if row["id"] == statement_id]
    assert len(matches) == 1, f"statement {statement_id} not found in listing"
    return matches[0]


def test_provisional_uses_sell_in_without_multipliers(api):
    """PRD §3.8: "The walk is over the agreement's `royalty_tiers` as marginal
    brackets, applied to `sell_in_units` with the bracket position starting at
    zero"
    PRD §3.8: "The provisional figure applies **no** multipliers of any kind:
    not exclusivity, not quality, not the unlicensed-share response."
    PRD §2.5: "a royalty statement's `final_royalty_cents` is null until the
    statement is first issued"

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_divergence
    """
    _, agreement = _active_agreement(exclusive=True, brand_name="Lakeside Coffee")
    create_audit(agreement["id"], audited_at="2026-06-15T00:00:00Z",
                 cup_score=90, defect_rate_ppm=50)

    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=1200000,
        sell_through_units=1100000, unlicensed_share_pct=10)
    assert statement["status"] == "DRAFT"
    assert statement["dispute_count"] == 0
    assert statement["final_royalty_cents"] is None
    # 1000000*750/1000 + 200000*900/1000 == 750000 + 180000 == 930000
    assert statement["provisional_royalty_cents"] == 930000


def test_final_uses_sell_through_with_exclusive_discount(api):
    """PRD §3.8: "It runs the same marginal bracket walk, but over
    `sell_through_units` rather than `sell_in_units`."
    PRD §3.8: "First, exclusivity: when the agreement's `exclusive` flag is
    set, the base is reduced by 8 percent."
    PRD §3.8: "Identical inputs therefore produce different provisional and
    final figures — the variants are deliberately not interchangeable."

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_divergence
    """
    _, agreement = _active_agreement(exclusive=True, brand_name="Lakeside 2")
    create_audit(agreement["id"], audited_at="2026-06-15T00:00:00Z",
                 cup_score=90, defect_rate_ppm=50)
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=1200000,
        sell_through_units=1100000, unlicensed_share_pct=10)

    issued = issue_statement(statement["id"])
    # base 840000 (750000 + 100000*900/1000); exclusive *0.92 -> 772800;
    # defects 50 <= 200 so no penalty; unlicensed 10 < 15 so no discount.
    assert issued["final_royalty_cents"] == 772800
    assert issued["provisional_royalty_cents"] == 930000
    assert issued["final_royalty_cents"] != issued["provisional_royalty_cents"]


def test_provisional_ignores_penalty_band_and_unlicensed_share(api):
    """PRD §3.8: "The provisional figure applies **no** multipliers of any
    kind: not exclusivity, not quality, not the unlicensed-share response."

    Design: Difficulty/combinatorial_formula/royalty_tiered_multiplier_stacking
    """
    _, agreement = _active_agreement(exclusive=False, brand_name="Harbor Roast")
    create_audit(agreement["id"], audited_at="2026-07-01T00:00:00Z",
                 cup_score=90, defect_rate_ppm=300)

    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=500000,
        sell_through_units=600000, unlicensed_share_pct=20)
    # 500000 * 750/1000 == 375000 even though the penalty band and the
    # unlicensed threshold are both in play.
    assert statement["provisional_royalty_cents"] == 375000


def test_final_stacks_quality_penalty_then_unlicensed_discount(api,
                                                               licensing_headers):
    """PRD §3.8: "Second, the quality penalty: if the agreement has a latest
    audit — ordered by `audited_at` descending, ties broken by `created_at`
    descending — and that audit's `defect_rate_ppm` exceeds 200 defective pods
    per million, the figure is increased by 10 percent. Third, the marketing
    response to unlicensed competition: when the statement's
    `unlicensed_share_pct` is at least 15, the figure is reduced by 5 percent."

    Design: Difficulty/combinatorial_formula/royalty_tiered_multiplier_stacking
    """
    _, agreement = _active_agreement(exclusive=False, brand_name="Harbor 2")
    audit = create_audit(agreement["id"], audited_at="2026-07-01T00:00:00Z",
                         cup_score=90, defect_rate_ppm=300)
    # defects 300 <= 500 hard max: the audit still PASSes, no suspension.
    assert audit["result"] == "PASS"
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=500000,
        sell_through_units=600000, unlicensed_share_pct=20)

    issued = issue_statement(statement["id"])
    # base 450000; non-exclusive skips step 1; *1.10 -> 495000; *0.95 -> 470250.
    assert issued["final_royalty_cents"] == 470250

    agreement_after = get_success_data(
        api.get_license_agreement(agreement["id"], licensing_headers))
    assert agreement_after["status"] == "ACTIVE"


def test_royalty_bracket_boundary_bills_millionth_unit_in_first_bracket(api):
    """PRD §3.8: "beginning at the first bracket, units up to each
    `up_to_units` boundary are billed at that bracket's `millicents_per_pod`
    rate, and whatever remains once every bounded bracket is exhausted falls
    into the open bracket whose `up_to_units` is null."
    PRD §3.1: "Brackets are **marginal**: only the units falling inside a
    bracket are billed at that bracket's rate, not the whole volume at the
    highest reached rate."

    Design: Difficulty/boundary_precision_check/royalty_tier_exact_boundary
    """
    _, agreement = _active_agreement(brand_name="Boundary Beans")
    create_audit(agreement["id"], audited_at="2026-05-01T00:00:00Z",
                 cup_score=90, defect_rate_ppm=50)
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=1,
        sell_through_units=1000000, unlicensed_share_pct=0)

    issued = issue_statement(statement["id"])
    # All 1000000 units land inside bracket 1: 1000000*750/1000 == 750000.
    assert issued["final_royalty_cents"] == 750000


def test_royalty_cumulative_position_carries_into_next_period(api):
    """PRD §3.8: "Its bracket position does not start at zero: it starts at
    the cumulative `sell_through_units` of this agreement's other statements
    already in `ISSUED` or `SETTLED` whose periods fall in the same calendar
    year as this statement's `period`, so the year's earlier volume pushes
    this statement deeper into the bracket schedule."
    PRD §2.6: "bracket arithmetic converts millicents into cents, rounding
    each bracket slice half-up to two decimal places as it accumulates, and
    every finalized royalty figure is rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/royalty_tier_exact_boundary
    """
    _, agreement = _active_agreement(brand_name="Boundary Beans 2")
    create_audit(agreement["id"], audited_at="2026-05-01T00:00:00Z",
                 cup_score=90, defect_rate_ppm=50)
    first = create_statement(
        agreement["id"], period="2026-08", sell_in_units=1,
        sell_through_units=1000000, unlicensed_share_pct=0)
    issue_statement(first["id"])

    second = create_statement(
        agreement["id"], period="2026-09", sell_in_units=1,
        sell_through_units=1, unlicensed_share_pct=0)
    issued_second = issue_statement(second["id"])
    # Cumulative position 1000000: bracket 1 is exhausted, so the single unit
    # is billed at 900 millicents: 1*900/1000 == 0.9 -> round half-up == 1.
    assert issued_second["final_royalty_cents"] == 1


def test_dispute_reissue_recomputes_from_corrected_units(api):
    """PRD §3.8: "when the re-issue payload carries corrected
    `sell_through_units` or `unlicensed_share_pct` values, the stored values
    are replaced **before** the final royalty is recomputed, so the new figure
    reflects the corrections."
    PRD §3.8: "each such transition increments `dispute_count`."

    Design: Difficulty/non_linear_state_machine/statement_dispute_reissue_cycle
    """
    _, agreement = _active_agreement(brand_name="Dispute Roasters")
    create_audit(agreement["id"], audited_at="2026-05-01T00:00:00Z",
                 cup_score=88, defect_rate_ppm=50)
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=100000,
        sell_through_units=100000, unlicensed_share_pct=0)

    issued = issue_statement(statement["id"])
    # 100000 * 750/1000 == 75000
    assert issued["final_royalty_cents"] == 75000

    disputed = get_success_data(transition_statement(
        statement["id"], "DISPUTED",
        dispute_reason="retailer underreported sell-through"))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1

    reissued = get_success_data(transition_statement(
        statement["id"], "ISSUED", sell_through_units=120000))
    # 120000 * 750/1000 == 90000; the statement itself left ISSUED so it does
    # not advance its own cumulative bracket position.
    assert reissued["final_royalty_cents"] == 90000
    assert reissued["sell_through_units"] == 120000


def test_dispute_count_accumulates_then_settles(api):
    """PRD §3.8: "A `FinanceAnalyst` moves `ISSUED → DISPUTED` with a required
    `dispute_reason`, and each such transition increments `dispute_count`."
    PRD §3.8: "When the parties are done, `ISSUED → SETTLED` closes the
    statement; `SETTLED` is terminal."

    Design: Difficulty/non_linear_state_machine/statement_dispute_reissue_cycle
    """
    _, agreement = _active_agreement(brand_name="Dispute Roasters 2")
    create_audit(agreement["id"], audited_at="2026-05-01T00:00:00Z",
                 cup_score=88, defect_rate_ppm=50)
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=100000,
        sell_through_units=100000, unlicensed_share_pct=0)

    issue_statement(statement["id"])
    get_success_data(transition_statement(
        statement["id"], "DISPUTED", dispute_reason="first"))
    get_success_data(transition_statement(
        statement["id"], "ISSUED", sell_through_units=120000))
    second_dispute = get_success_data(transition_statement(
        statement["id"], "DISPUTED", dispute_reason="second"))
    assert second_dispute["dispute_count"] == 2

    get_success_data(transition_statement(
        statement["id"], "ISSUED", sell_through_units=120000))
    settled = get_success_data(transition_statement(statement["id"], "SETTLED"))
    assert settled["status"] == "SETTLED"
    assert settled["dispute_count"] == 2


def test_quality_penalty_follows_only_the_latest_audit(api):
    """PRD §3.8: "if the agreement has a latest audit — ordered by `audited_at`
    descending, ties broken by `created_at` descending — and that audit's
    `defect_rate_ppm` exceeds 200 defective pods per million, the figure is
    increased by 10 percent."

    Design: Corner/calculations/quality_penalty_follows_only_the_latest_audit
    """
    brand = create_brand(kind="LICENSED", name="Latest Audit Co")
    agreement = create_active_agreement(
        brand["id"],
        royalty_tiers=[{"up_to_units": None, "millicents_per_pod": 750}],
        quality_min_cup_score=80, exclusive=False)
    create_audit(agreement["id"], audited_at="2026-06-01T00:00:00Z",
                 cup_score=90, defect_rate_ppm=300)
    create_audit(agreement["id"], audited_at="2026-08-01T00:00:00Z",
                 cup_score=90, defect_rate_ppm=50)

    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=500000,
        sell_through_units=500000, unlicensed_share_pct=0)
    issued = issue_statement(statement["id"])
    # Latest audit defects 50 <= 200: no penalty. 500000*750/1000 == 375000.
    assert issued["final_royalty_cents"] == 375000


def test_duplicate_statement_period_rejected(api):
    """PRD §3.8: "each agreement holds at most one statement per period — a
    repeat is `ERR_DUPLICATE_STATEMENT_PERIOD`."

    Design: Corner/validations/duplicate_statement_period_rejected
    """
    _, agreement = _active_agreement(brand_name="Dup Period Co")
    create_statement(agreement["id"], period="2026-08", sell_in_units=10,
                     sell_through_units=10, unlicensed_share_pct=0)

    resp = api.create_royalty_statement(
        agreement["id"],
        {"period": "2026-08", "sell_in_units": 20, "sell_through_units": 20,
         "unlicensed_share_pct": 0},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATEMENT_PERIOD)


def test_statement_period_after_clock_month_rejected(api):
    """PRD §3.8: "The period must fall within the agreement's effective window
    and not after the logical clock's current month"
    PRD §2.10: "period strings are well-formed `YYYY-MM` and not after the
    current clock month"

    Design: Corner/entities/statement_period_after_clock_month_rejected
    """
    _, agreement = _active_agreement(brand_name="Future Period Co")

    resp = api.create_royalty_statement(
        agreement["id"],
        {"period": "2026-10", "sell_in_units": 10, "sell_through_units": 10,
         "unlicensed_share_pct": 0},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_statement_creation_blocked_while_suspended(api):
    """PRD §3.8: "a `SUSPENDED` agreement refuses statement work with
    `ERR_LICENSE_SUSPENDED` (HTTP 409), and an agreement in any other
    non-`ACTIVE` state is `ERR_INVALID_STATE`."

    Design: Corner/validations/statement_creation_blocked_while_suspended
    """
    _, agreement = _active_agreement(brand_name="Draft Block Co")
    audit = create_audit(agreement["id"], audited_at="2026-09-01T00:00:00Z",
                         cup_score=60, defect_rate_ppm=50)
    assert audit["result"] == "FAIL"  # suspends the agreement

    resp = api.create_royalty_statement(
        agreement["id"],
        {"period": "2026-08", "sell_in_units": 10, "sell_through_units": 10,
         "unlicensed_share_pct": 0},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_LICENSE_SUSPENDED)


def test_issue_blocked_after_agreement_suspension(api):
    """PRD §3.8: "Issuance — `DRAFT → ISSUED` at a `FinanceAnalyst`'s hand,
    gated on the same agreement-state split as creation (expiry first as
    `ERR_AGREEMENT_EXPIRED`, then `ERR_LICENSE_SUSPENDED` for `SUSPENDED`,
    then `ERR_INVALID_STATE` for anything else not `ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/issue_requires_agreement_not_suspended
    """
    _, agreement = _active_agreement(brand_name="Suspenders Coffee")
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=1000,
        sell_through_units=1000, unlicensed_share_pct=0)

    audit = create_audit(agreement["id"], audited_at="2026-09-01T00:00:00Z",
                         cup_score=65, defect_rate_ppm=50)
    assert audit["result"] == "FAIL"  # agreement now SUSPENDED

    resp = transition_statement(statement["id"], "ISSUED")
    validate_error(resp, ApiErrorId.ERR_LICENSE_SUSPENDED)

    stayed = _get_statement(api, agreement["id"], statement["id"])
    assert stayed["status"] == "DRAFT"
    assert stayed["final_royalty_cents"] is None


def test_statement_create_on_draft_agreement_rejected(api):
    """PRD §3.8: "an agreement in any other non-`ACTIVE` state is
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_agreement_not_suspended
    """
    brand = create_brand(kind="LICENSED", name="Draft Gate Co")
    agreement = create_agreement(brand["id"])  # stays DRAFT

    resp = api.create_royalty_statement(
        agreement["id"],
        {"period": "2026-08", "sell_in_units": 10, "sell_through_units": 10,
         "unlicensed_share_pct": 0},
        FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_settled_statement_is_terminal(api):
    """PRD §3.8: "When the parties are done, `ISSUED → SETTLED` closes the
    statement; `SETTLED` is terminal."
    PRD §2.9: "Terminal states are absorbing — a resource in a terminal state
    accepts no further transitions, and any attempt to drive one is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/settled_statement_is_terminal
    """
    _, agreement = _active_agreement(brand_name="Settle Co")
    statement = create_statement(
        agreement["id"], period="2026-08", sell_in_units=10,
        sell_through_units=10, unlicensed_share_pct=0)
    issue_statement(statement["id"])
    get_success_data(transition_statement(statement["id"], "SETTLED"))

    resp = transition_statement(statement["id"], "DISPUTED",
                                dispute_reason="too late")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stayed = _get_statement(api, agreement["id"], statement["id"])
    assert stayed["status"] == "SETTLED"
    assert stayed["dispute_count"] == 0
