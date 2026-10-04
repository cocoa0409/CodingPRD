"""The payout grid: provisional release, retroactive true-up and rounding order."""

from test_helpers import (
    api_client, get_success_data, refresh_advisor, validate_error, ApiErrorId,
    setup_funded_period, advance_period, true_up_period, make_advisor_ops_headers,
    BRANCH_MANAGER, PLATFORM_ADMIN,
)


def _post_period(ctx):
    """CLOSED then PAID — the posting leg that releases the draft line."""
    branch_code = ctx["branch"]["branch_code"]
    advance_period(ctx["period"]["id"], "CLOSED", branch_code)
    advance_period(ctx["period"]["id"], "PAID", branch_code)


def _line(period_id, headers=BRANCH_MANAGER):
    rows = get_success_data(api_client.list_period_payout_lines(period_id, headers))
    return rows[0]


CROSSING_ENTRIES = ((800_000, "2026-09-03", "EQUITY"),
                    (600_000, "2026-09-08", "MUTUAL_FUND"),
                    (400_000, "2026-09-12", "ADVISORY"),
                    (900_000, "2026-09-20", "EQUITY"),
                    (300_000, "2026-09-26", "BROKERAGE_TRAIL"))


# ─── dual_variant_calc ────────────────────────────────

def test_provisional_release_pays_every_entry_at_the_single_projected_rate():
    """PRD §3.4: "The provisional rate uses the line's `projected_annual_production_cents`
    as the tier basis and applies the entry's product delta and the advisor's affiliation
    offset; every entry of the period is paid at that single rate."
    PRD §3.4: "A line's `release_amount_cents` is not a rounded total; it is the sum of
    per-entry rounded amounts."

    Design: Difficulty/dual_variant_calc/grid_rate_provisional_vs_final_on_tier_crossing
    """
    ctx = setup_funded_period(
        advisor_code="A-3001", projected_annual_production_cents=120_000_000,
        entries=CROSSING_ENTRIES, release=True)
    _post_period(ctx)

    line = _line(ctx["period"]["id"])
    assert line["provisional_base_rate_bps"] == 8000, (
        "a projected basis of 120,000,000 sits inside the 8,000 tier")
    #  800000@8000 + 600000@7500 + 400000@8500 + 900000@8000 + 300000@7700
    assert line["release_amount_cents"] == 2_381_000, (
        f"provisional release expected 2381000, got {line['release_amount_cents']}")
    assert line["status"] == "RELEASED"

    period = get_success_data(api_client.get_payout_period(ctx["period"]["id"],
                                                          PLATFORM_ADMIN))
    assert period["period_payout_cents"] == 2_381_000
    assert period["period_gross_cents"] == 3_000_000


def test_true_up_recomputes_the_line_at_the_final_cumulative_rate():
    """PRD §3.4: "The true-up recomputes the period against the final grid and applies
    the signed difference."
    PRD §3.4: "The line's `true_up_amount_cents` is the final income minus the
    provisional income, and it is signed.

    Design: Difficulty/dual_variant_calc/grid_rate_provisional_vs_final_on_tier_crossing
    """
    ctx = setup_funded_period(
        advisor_code="A-3002", projected_annual_production_cents=120_000_000,
        entries=CROSSING_ENTRIES, release=True)
    _post_period(ctx)
    true_up_period(ctx["period"]["id"])

    line = _line(ctx["period"]["id"])
    #  final: 800000@7000 + 600000@6500 + 400000@7500 + 900000@7000 + 300000@6700
    assert line["release_amount_cents"] == 2_081_000
    assert line["true_up_amount_cents"] == -300_000
    assert line["status"] == "TRUE_UP_APPLIED"

    period = get_success_data(api_client.get_payout_period(ctx["period"]["id"],
                                                          PLATFORM_ADMIN))
    assert period["true_up_amount_cents"] == -300_000
    assert period["period_payout_cents"] == 2_081_000

    advisor = refresh_advisor(ctx["advisor"]["id"])
    assert advisor["ytd_payout_earned_cents"] == 2_081_000


def test_negative_true_up_is_added_back_to_the_loan_not_deducted_from_the_release():
    """PRD §3.2: "A negative true-up is a shortfall, and the whole signed amount is added
    back to the loan balance by posting a `LoanAmortizationEntry` whose
    `amortization_amount_cents` is negative, with `remaining_balance_cents` rising by the
    same magnitude."
    PRD §3.2: "the draw is the line's `release_amount_cents` multiplied by the loan's
    `amortization_rate_bps` and divided by 10000, rounded half up to whole cents, and
    then clipped to whatever balance remains."

    Design: Difficulty/dual_variant_calc/grid_rate_provisional_vs_final_on_tier_crossing
    """
    ctx = setup_funded_period(
        advisor_code="A-3003", projected_annual_production_cents=120_000_000,
        principal_cents=500_000, amortization_rate_bps=2000,
        entries=CROSSING_ENTRIES, release=True)
    _post_period(ctx)
    after_release = get_success_data(api_client.get_payout_loan(
        ctx["loan"]["id"], PLATFORM_ADMIN))
    assert after_release["remaining_balance_cents"] == 500_000 - 476_200

    true_up_period(ctx["period"]["id"])
    loan = get_success_data(api_client.get_payout_loan(ctx["loan"]["id"], PLATFORM_ADMIN))
    assert loan["remaining_balance_cents"] == 500_000 - 476_200 + 300_000


# ─── combinatorial_formula ────────────────────────────

def test_release_amount_rounds_each_entry_then_sums():
    """PRD §3.4: "Each entry's contribution is its `gross_commission_cents` multiplied by
    the applicable rate and divided by 10000, rounded half up to a whole cent, and the
    contributions are then added."

    Design: Difficulty/combinatorial_formula/per_entry_rounding_order_in_period_release
    """
    ctx = setup_funded_period(
        advisor_code="A-3004", projected_annual_production_cents=80_000_000,
        account_balance_cents=20_000_000,
        entries=((700_001, "2026-09-03", "EQUITY"),
                 (650_001, "2026-09-08", "MUTUAL_FUND"),
                 (450_001, "2026-09-12", "ADVISORY")), release=True)
    _post_period(ctx)

    line = _line(ctx["period"]["id"])
    #  490001 + 422501 + 337501; summing first and rounding once would give 1250002
    assert line["release_amount_cents"] == 1_250_003, (
        "per-entry rounding, not a single rounded total")
    assert line["provisional_base_rate_bps"] == 7000
    assert line["status"] == "RELEASED"


def test_period_gross_tracks_the_unrounded_entry_sum():
    """PRD §3.3: "The period's `period_gross_cents` is the sum of `gross_commission_cents`
    over released entries whose `production_date` falls in the period's calendar month."
    PRD §3.3: "its `provisional_base_rate_bps` is derived from that projected basis."

    Design: Difficulty/combinatorial_formula/per_entry_rounding_order_in_period_release
    """
    ctx = setup_funded_period(
        advisor_code="A-3005", projected_annual_production_cents=80_000_000,
        account_balance_cents=20_000_000,
        entries=((700_001, "2026-09-03", "EQUITY"),
                 (650_001, "2026-09-08", "MUTUAL_FUND"),
                 (450_001, "2026-09-12", "ADVISORY")), release=True)
    _post_period(ctx)

    period = get_success_data(api_client.get_payout_period(ctx["period"]["id"],
                                                          PLATFORM_ADMIN))
    assert period["period_gross_cents"] == 1_800_003
    assert period["period_payout_cents"] == 1_250_003
    assert period["period_payout_cents"] != 1_250_002


# ─── boundary_precision_check ─────────────────────────

def test_projected_basis_of_exactly_the_ceiling_lands_in_the_higher_tier():
    """PRD §3.4: "from 100,000,000 cents up to but not including 250,000,000 cents the
    base is 8,000".
    PRD §3.4: "a basis of exactly 100,000,000 cents lands in the 8,000 tier".

    Design: Difficulty/boundary_precision_check/tier_ceiling_boundary_at_two_hundred_fifty_million
    """
    ctx = setup_funded_period(
        advisor_code="A-3006", projected_annual_production_cents=100_000_000,
        entries=((50_000_000, "2026-09-05", "EQUITY"),
                 (200_000_000, "2026-09-15", "EQUITY")), release=True)
    _post_period(ctx)

    line = _line(ctx["period"]["id"])
    assert line["provisional_base_rate_bps"] == 8000
    assert line["release_amount_cents"] == 200_000_000, (
        "both entries pay at the single 8,000 bps provisional rate")
    assert line["status"] == "RELEASED"


def test_cumulative_two_hundred_fifty_million_is_inclusive_on_the_lower_side():
    """PRD §3.4: "a basis of exactly 250,000,000 cents lands in the 9,000 tier, while
    249,999,999 cents remains in the 8,000 tier."
    PRD §3.4: "Cumulative production sums `gross_commission_cents` over the advisor's
    entries in calendar-year order by `production_date` ascending".

    Design: Difficulty/boundary_precision_check/tier_ceiling_boundary_at_two_hundred_fifty_million
    """
    ctx = setup_funded_period(
        advisor_code="A-3007", projected_annual_production_cents=100_000_000,
        entries=((50_000_000, "2026-09-05", "EQUITY"),
                 (200_000_000, "2026-09-15", "EQUITY")), release=True)
    _post_period(ctx)
    true_up_period(ctx["period"]["id"])

    line = _line(ctx["period"]["id"])
    #  50,000,000 at 7,000 plus 200,000,000 at 9,000
    assert line["release_amount_cents"] == 215_000_000
    assert line["true_up_amount_cents"] == 15_000_000, (
        "the boundary entry reaches cumulative 250,000,000 and pays 9,000 bps")
    assert line["status"] == "TRUE_UP_APPLIED"


# ─── corner: calculations ─────────────────────────────

def test_institutional_offset_clamps_the_applied_rate_to_the_floor():
    """PRD §3.4: "A product delta is added according to `product_type`: `EQUITY` adds 0,
    `MUTUAL_FUND` subtracts 500, `ANNUITY` subtracts 700, `BROKERAGE_TRAIL` subtracts 300,
    and `ADVISORY` adds 500. An affiliation offset is then subtracted according to
    `affiliation_model`: `IC` subtracts 0, `EMPLOYEE` subtracts 500, `HYBRID` subtracts
    250, and `INSTITUTIONAL` subtracts 6,500. The result is finally clamped into the band
    from 500 basis points to 9,000 basis points inclusive."

    Design: Corner/calculations/institutional_floor_clamps_the_grid_rate
    """
    ctx = setup_funded_period(
        advisor_code="A-3008", affiliation_model="INSTITUTIONAL",
        projected_annual_production_cents=50_000_000,
        entries=((10_000_000, "2026-09-03", "ANNUITY"),), release=True)
    _post_period(ctx)

    line = _line(ctx["period"]["id"])
    assert line["provisional_base_rate_bps"] == 7000, (
        "the provisional base rate is the grid base for the 50,000,000 projected basis")
    assert line["release_amount_cents"] == 500_000, (
        "10,000,000 at the applied rate, which the 6,500 offset and the 700 delta clamp to "
        "the 500-basis-point floor")


def test_employer_offset_moves_the_rate_off_the_tier_base_at_release():
    """PRD §3.4: "An affiliation offset is then subtracted according to `affiliation_model`:
    `IC` subtracts 0, `EMPLOYEE` subtracts 500".

    Design: Corner/calculations/dual_grid_readings_diverge_on_identical_employer_rows
    """
    ctx = setup_funded_period(
        advisor_code="A-3010", affiliation_model="EMPLOYEE",
        projected_annual_production_cents=50_000_000,
        entries=((10_000_000, "2026-09-03", "EQUITY"),), release=True)
    _post_period(ctx)

    line = _line(ctx["period"]["id"])
    assert line["provisional_base_rate_bps"] == 7000
    assert line["release_amount_cents"] == 6_500_000, (
        "10,000,000 at the 6,500 bps the 500-point employee offset leaves")
    assert line["release_amount_cents"] != 7_000_000, (
        "the same entry for an IC advisor would apply 7,000 basis points")


# ─── corner: endpoints ────────────────────────────────

def test_releasing_a_revenue_entry_twice_is_rejected():
    """PRD §3.3: "An entry may only be released while its owning account is `OPEN` or
    `FROZEN`".
    PRD §3.3: "Entries are created at `status` `DRAFT` and contribute to no basis until
    released."

    Design: Corner/endpoints/revenue_entry_release_twice_returns_invalid_state
    """
    ctx = setup_funded_period(advisor_code="A-3011", release=False,
                              entries=((1_000_000, "2026-09-03", "EQUITY"),))
    advisor = ctx["advisor"]
    entry = ctx["entries"][0]

    first = get_success_data(api_client.release_revenue_entry(
        entry["id"], make_advisor_ops_headers(advisor["id"])))
    assert first["status"] == "RELEASED"

    second = api_client.release_revenue_entry(entry["id"],
                                              make_advisor_ops_headers(advisor["id"]))
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    reread = get_success_data(api_client.get_revenue_entry(entry["id"], PLATFORM_ADMIN))
    assert reread["status"] == "RELEASED"
    # The trailing-twelve-month window reads the logical clock, and the fixture
    # books its production inside that window, so the released entry counts.
    assert refresh_advisor(advisor["id"])["t12_production_cents"] == 1_000_000