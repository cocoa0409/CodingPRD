"""Year-end reconciliation: the sum-then-round true-up, the gates that refuse
to reconcile, the kick-out evaluation and ownership's comparable-store trend.
"""
from test_helpers import (
    ApiErrorId, assert_sales_trend,
    attach_kick_out_clause, charges_for_year, close_period, file_and_accept,
    LEASE_ADMIN, open_audit, open_lease_year, OWNERSHIP_ANALYST, read_kick_out,
    read_lease_year, read_report, reconcile, rescind_audit,
    schedule_monthly_report, schedule_quarterly_report, schedule_report,
    setup_active_lease, setup_lease_year, setup_year_with_accepted_reports,
    setup_year_with_pending_reports, TEST_DEFAULTS, validate_error,
    validate_success,
)

UNREACHABLE_BREAKPOINT = TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"]
ARTIFICIAL_BREAKPOINT = TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"]


def _quarterly_year_billed_per_period():
    """Four quarters of 15,000,005 net sales, each billed on its own rounding."""
    scene = setup_lease_year(
        suite_code="301", billing_mode="PERIOD_STANDALONE",
        reporting_frequency="QUARTERLY", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    for index in range(1, 5):
        report = schedule_quarterly_report(scene["lease_year"]["id"], index)
        file_and_accept(report["id"], scene["tenant"]["id"], 15_000_005)
    close_period(scene["lease_year"]["id"])
    return scene


def test_annual_true_up_materialises_the_rounding_order_disagreement(api):
    """PRD §3.10: "The annual recompute sums first and rounds once: the service
    sums `net_sales_cents` across every report of the year in the counted set
    as exact integer cents, subtracts the year's `breakpoint_cents`, takes the
    result if positive or zero if not, multiplies that annual excess by the
    year's `percentage_rate_bps_snapshot`, divides by 10000, and rounds half up
    to whole cents exactly once — this is the annual amount due. Periodic
    billing, by contrast, rounded each period separately and then summed those
    rounded figures. The service therefore subtracts from the annual amount due
    the sum of `amount_cents` over every charge of the year whose
    `billing_status` is `ISSUED` — draft and voided charges are excluded from
    that sum — and writes the difference into the year's
    `true_up_delta_cents`."

    Design: Difficulty/combinatorial_formula/annual_true_up_sum_then_round_versus_round_per_period_mode_b
    """
    scene = _quarterly_year_billed_per_period()

    reconciled = reconcile(scene["lease_year"]["id"])

    assert reconciled["status"] == "RECONCILED"
    assert reconciled["cumulative_net_sales_cents"] == 60_000_020
    assert reconciled["cumulative_billed_cents"] == 1_200_000, (
        "four quarters each rounded to 300,000")
    assert reconciled["true_up_delta_cents"] == 1, (
        "the annual recompute rounds 1,200,001.2 once, one cent above the sum "
        "of the per-period roundings")


def test_positive_true_up_delta_creates_a_draft_true_up_charge(api):
    """PRD §3.10: "When `true_up_delta_cents` is greater than zero,
    reconciliation creates a charge with `charge_type` of `TRUE_UP`,
    `billing_status` of `DRAFT`, `collection_status` of `UNPAID`,
    `amount_cents` equal to the delta and `sales_report_id` null."
    PRD §3.10: "In a year whose snapshot is `PERIOD_STANDALONE`, the
    already-issued figure is the sum of per-period amounts each rounded against
    its own pro-rated breakpoint, so the delta captures both the difference
    between pro-rata and annual breakpoint treatment and the accumulated
    per-period rounding residue."

    Design: Difficulty/combinatorial_formula/annual_true_up_sum_then_round_versus_round_per_period_mode_b
    """
    scene = _quarterly_year_billed_per_period()

    reconcile(scene["lease_year"]["id"])

    true_ups = charges_for_year(scene["lease_year"]["id"], charge_type="TRUE_UP")
    assert len(true_ups) == 1
    assert true_ups[0]["amount_cents"] == 1
    assert true_ups[0]["billing_status"] == "DRAFT"
    assert true_ups[0]["collection_status"] == "UNPAID"
    assert true_ups[0]["sales_report_id"] is None

    periodic = charges_for_year(scene["lease_year"]["id"], charge_type="PERIODIC")
    assert len(periodic) == 4
    for charge in periodic:
        assert charge["amount_cents"] == 300_000
        assert charge["billing_status"] == "ISSUED"


def test_reconciliation_is_refused_while_an_audit_is_still_open(api):
    """PRD §3.10: "Reconciliation refuses to run while any audit on the year's
    reports is still `OPEN` or `FINDINGS_ISSUED` — that is, while
    `open_audit_count` is greater than zero — with
    `ERR_OPEN_AUDIT_BLOCKS_RECONCILE`, and it refuses to run while any sales
    report of the year is still in `PENDING`, `SUBMITTED`, `UNDER_AUDIT`,
    `DISPUTED` or `AMENDED`, with `ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE`."

    Design: Difficulty/cross_entity_state_dependency/reconcile_gated_by_lease_year_open_audit_count
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="2001", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    report = scene["reports"][0]
    open_audit(report["id"], "2026-10-05T00:00:00Z", "2026-10-20T00:00:00Z")
    close_period(scene["lease_year"]["id"])

    validate_error(
        api.reconcile_lease_year(scene["lease_year"]["id"], LEASE_ADMIN),
        ApiErrorId.ERR_OPEN_AUDIT_BLOCKS_RECONCILE.value, 409)

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["status"] == "RECONCILING"
    assert year["true_up_delta_cents"] is None
    assert year["open_audit_count"] == 1


def test_reconciliation_succeeds_once_the_blocking_audit_is_rescinded(api):
    """PRD §3.7: "From `OPEN`, rescinding simply abandons the examination: the
    audit becomes `RESCINDED`, the report returns `UNDER_AUDIT → ACCEPTED`, the
    year's `open_audit_count` decreases by 1, and no sales or billing figure
    moves."
    PRD §3.10: "Reconciliation refuses to run while any audit on the year's
    reports is still `OPEN` or `FINDINGS_ISSUED` — that is, while
    `open_audit_count` is greater than zero — with
    `ERR_OPEN_AUDIT_BLOCKS_RECONCILE`, and it refuses to run while any sales
    report of the year is still in `PENDING`, `SUBMITTED`, `UNDER_AUDIT`,
    `DISPUTED` or `AMENDED`, with `ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE`."

    Design: Difficulty/cross_entity_state_dependency/reconcile_gated_by_lease_year_open_audit_count
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="2001", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    report = scene["reports"][0]
    audit = open_audit(report["id"], "2026-10-05T00:00:00Z",
                       "2026-10-20T00:00:00Z")
    close_period(scene["lease_year"]["id"])

    rescinded = rescind_audit(audit["id"],
                              reason="Audit scope withdrawn by ownership")
    assert rescinded["status"] == "RESCINDED"
    assert read_report(report["id"])["status"] == "ACCEPTED"

    reconciled = reconcile(scene["lease_year"]["id"])

    assert reconciled["status"] == "RECONCILED"
    assert reconciled["open_audit_count"] == 0
    assert reconciled["cumulative_net_sales_cents"] == 30_000_000
    assert reconciled["true_up_delta_cents"] == 0, (
        "30,000,000 is below the 40,000,000 breakpoint, so nothing is due")
    assert charges_for_year(scene["lease_year"]["id"]) == []


def test_reconciliation_is_refused_while_a_period_is_still_pending(api):
    """PRD §3.10: "Reconciliation refuses to run while any audit on the year's
    reports is still `OPEN` or `FINDINGS_ISSUED` — that is, while
    `open_audit_count` is greater than zero — with
    `ERR_OPEN_AUDIT_BLOCKS_RECONCILE`, and it refuses to run while any sales
    report of the year is still in `PENDING`, `SUBMITTED`, `UNDER_AUDIT`,
    `DISPUTED` or `AMENDED`, with `ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE`."

    Design: Corner/validations/reconcile_with_pending_report_returns_unaccepted_reports_block
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="6601", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)
    september, _october = scene["reports"]
    file_and_accept(september["id"], scene["tenant"]["id"], 30_000_000)
    close_period(scene["lease_year"]["id"])

    validate_error(
        api.reconcile_lease_year(scene["lease_year"]["id"], LEASE_ADMIN),
        ApiErrorId.ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE.value, 409)

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["status"] == "RECONCILING"
    assert year["true_up_delta_cents"] is None
    assert year["open_audit_count"] == 0


def test_sales_exactly_on_the_kick_out_threshold_expire_the_right(api):
    """PRD §3.9: "Otherwise the clause moves `ARMED → EXPIRED` with
    `triggered_at` and `election_deadline_at` left null and the tenant never
    gaining an election. Sales landing exactly on the threshold therefore
    expire the right rather than trigger it."
    PRD §3.10: "Reconciliation also runs the kick-out evaluation of Section 3.9
    over every `ARMED` kick-out clause of that lease whose
    `measurement_year_index` matches the year's `year_index`."

    Design: Corner/calculations/kick_out_threshold_equal_to_sales_expires_instead_of_triggering
    """
    scene = setup_active_lease(
        suite_code="5801", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)
    kick_out = attach_kick_out_clause(scene["lease"]["id"],
                                      threshold_sales_cents=30_000_000,
                                      election_window_days=30)
    lease_year = open_lease_year(scene["lease"]["id"])
    report = schedule_monthly_report(lease_year["id"], 1)
    file_and_accept(report["id"], scene["tenant"]["id"], 30_000_000)
    close_period(lease_year["id"])

    reconciled = reconcile(lease_year["id"])

    assert reconciled["status"] == "RECONCILED"
    assert reconciled["cumulative_net_sales_cents"] == 30_000_000

    clause_now = read_kick_out(kick_out["id"])
    assert clause_now["status"] == "EXPIRED", (
        "the comparison is strictly less than, so equality expires the right")
    assert clause_now["triggered_at"] is None
    assert clause_now["election_deadline_at"] is None


# ─── Ownership's comparable-store trend ───────────────────────────────────

def test_trend_report_with_no_comparable_lease_returns_a_zeroed_report(api):
    """PRD §3.10: "A center with no comparable lease at all is not an error:
    the report returns HTTP 200 with `tenant_count` of 0 and every other metric
    at 0."

    Design: Difficulty/boundary_precision_check/sales_trend_with_empty_comparable_set_returns_zeros
    """
    scene = setup_lease_year(suite_code="1701")

    data = validate_success(
        api.get_center_sales_trend(scene["center"]["id"], OWNERSHIP_ANALYST,
                                   params={"year_index": 2}))

    assert_sales_trend(data)
    assert data["tenant_count"] == 0
    assert data["comp_sqft"] == 0
    assert data["current_net_sales_cents"] == 0
    assert data["prior_net_sales_cents"] == 0


def test_trend_report_guards_every_ratio_when_the_comparable_set_is_empty(api):
    """PRD §3.10: "`comp_growth_bps` is the current net less the prior net,
    multiplied by 10000, divided by the prior net and rounded half up — and it
    is defined as 0 when the prior net is zero; it may be negative, in which
    case a value exactly halfway between two basis points rounds away from
    zero. `sales_psf_cents` is the current net divided by `comp_sqft`, floored
    to whole cents, and is defined as 0 when `comp_sqft` is zero."
    PRD §3.10: "The comparable set consists of every lease of that center whose
    status is `ACTIVE`, `RELIEF_ACTIVE` or `TERMINATION_PENDING` that has
    **both** a reporting year at index N and a reporting year at index N minus
    1, each of which must be `RECONCILED`; leases missing either year, or
    holding either year in any other status, are excluded."

    Design: Difficulty/boundary_precision_check/sales_trend_with_empty_comparable_set_returns_zeros
    """
    scene = setup_lease_year(suite_code="1701")

    data = validate_success(
        api.get_center_sales_trend(scene["center"]["id"], OWNERSHIP_ANALYST,
                                   params={"year_index": 2}))

    assert data["comp_growth_bps"] == 0, (
        "the prior-net guard keeps the growth figure at zero")
    assert data["percentage_rent_cents"] == 0
    assert data["sales_psf_cents"] == 0
    assert data["occupancy_cost_ratio_bps"] == 0
    assert read_lease_year(scene["lease_year"]["id"])["status"] == "OPEN", (
        "the single reporting year was never reconciled, so nothing compares")


def test_trend_report_compares_two_reconciled_reporting_years(api):
    """PRD §3.10: "Eight figures are returned. `tenant_count` is the number of
    leases in the comparable set. `comp_sqft` is the sum of their
    `leased_sqft`. `current_net_sales_cents` is the sum of the year-N
    `cumulative_net_sales_cents` across the set, and `prior_net_sales_cents`
    the same sum taken over year N minus 1."
    PRD §3.10: "`occupancy_cost_ratio_bps` here is a center-level figure: the
    sum of each comparable lease's `annual_base_rent_cents` plus the
    `percentage_rent_cents` total, multiplied by 10000, divided by the current
    net and floored to whole basis points, defined as 0 when the current net is
    zero."

    Design: Corner/calculations/sales_trend_reports_comp_growth_between_two_reconciled_years
    """
    scene = setup_lease_year(
        suite_code="5701", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)
    first_report = schedule_monthly_report(scene["lease_year"]["id"], 1)
    file_and_accept(first_report["id"], scene["tenant"]["id"], 40_000_000)
    close_period(scene["lease_year"]["id"])
    reconcile(scene["lease_year"]["id"])

    second_year = open_lease_year(scene["lease"]["id"], year_index=2,
                                  period_start="2027-09-01T00:00:00Z",
                                  period_end="2028-09-01T00:00:00Z")
    second_report = schedule_report(second_year["id"], "2027-09-01T00:00:00Z",
                                    "2027-10-01T00:00:00Z")
    file_and_accept(second_report["id"], scene["tenant"]["id"], 50_000_000)
    close_period(second_year["id"])
    reconcile(second_year["id"])

    data = validate_success(
        api.get_center_sales_trend(scene["center"]["id"], OWNERSHIP_ANALYST,
                                   params={"year_index": 2}))

    assert_sales_trend(data)
    assert data["tenant_count"] == 1
    assert data["comp_sqft"] == 4_000
    assert data["current_net_sales_cents"] == 50_000_000
    assert data["prior_net_sales_cents"] == 40_000_000
    assert data["comp_growth_bps"] == 2500
    assert data["percentage_rent_cents"] == 0
    assert data["sales_psf_cents"] == 12_500
    assert data["occupancy_cost_ratio_bps"] == 2400
