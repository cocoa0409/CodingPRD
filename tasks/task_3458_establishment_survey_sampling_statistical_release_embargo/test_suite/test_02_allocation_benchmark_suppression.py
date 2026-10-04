"""Depth tests: combinatorial formulas with pinned evaluation orders.

Neyman allocation clamps sub-minimum strata before fractional-remainder
distribution; benchmark realignment rounds each month independently;
suppression computes totals from the full cell set before complementary
selection iterates rows-then-columns to a fixed point.
"""
from test_helpers import (
    apply_benchmark_run,
    assert_same_instant,
    certify_cycle,
    collect_cycle,
    create_admin_cell_count,
    create_benchmark_run,
    create_frame,
    create_program,
    create_stratum,
    freeze_frame,
    get_single_cell,
    read_bulletin,
    set_clock,
    setup_certified_cycle,
    setup_embargoed_release,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
)


def _strata_out(frame, industry_code, size_class):
    for st in frame["strata"]:
        if st["industry_code"] == industry_code and st["size_class"] == size_class:
            return st
    raise AssertionError(f"stratum {industry_code}/{size_class} missing")


def test_neyman_min_clamp_before_fractional_remainder(api):
    """PRD §3.1: "The initial allocation is the whole-number floor of the raw share, raised to the minimum of 2 when the floor falls below it; a stratum raised this way is said to be clamped, and clamping consumes budget before any other adjustment."
    PRD §3.1: "On success, each stratum's `allocated_sample_size` is written, the frame's `total_sample_size` becomes their sum — always exactly equal to the `sample_budget` — and `frozen_at` records the current logical-clock reading."

    Design: Difficulty/combinatorial_formula/neyman_min_clamp_before_fractional_remainder
    """
    set_clock("2026-09-01T00:00:00Z")
    program = create_program(code="CES", sample_budget=10,
                             annual_burden_budget_minutes=500)
    frame = create_frame(
        program["code"], "2026-Q3",
        strata=[create_stratum("MANUFACTURING", "SMALL", 25),
                create_stratum("MANUFACTURING", "MEDIUM", 10),
                create_stratum("RETAIL", "LARGE", 11)])
    frozen = freeze_frame(frame["id"])

    # Dispersion proxies 4/15/50 give raw shares 1.25 / 1.875 / 6.875.
    assert _strata_out(frozen, "MANUFACTURING", "SMALL")[
        "allocated_sample_size"] == 2, "raw 1.25 clamped up to the 2-minimum"
    assert _strata_out(frozen, "MANUFACTURING", "MEDIUM")[
        "allocated_sample_size"] == 2, "raw 1.875 clamped up"
    assert _strata_out(frozen, "RETAIL", "LARGE")[
        "allocated_sample_size"] == 6, (
        "raw 6.875 floored; remainder exhausted by clamping")
    assert frozen["total_sample_size"] == 10 == program["sample_budget"]
    assert frozen["frame_status"] == "FROZEN"
    assert_same_instant(frozen["frozen_at"], "2026-09-01T00:00:00Z")


def test_benchmark_wedge_rounds_per_month_not_annual(api):
    """PRD §3.7: "The realignment itself computes, for each administrative cell, a wedge factor: the entry's `admin_employment` divided by the benchmark-month cell's `employment_estimate`, rounded half up to 6 decimal places."
    PRD §3.7: "each month is rounded independently after multiplication, and no annual reconciliation pass is applied, so the sum of the realigned monthly values may differ by a unit from a rounded annual product — this is accepted and expected."
    PRD §3.7: "The benchmark-month cell is anchored outright — its `employment_estimate` is set to the administrative count, it moves to `FINAL`, its `wedge_factor` records the wedge, and its `revision_no` increments by 1."

    Design: Difficulty/combinatorial_formula/benchmark_wedge_rounds_per_month_not_annual
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=4,
        strata=[create_stratum("MANUFACTURING", "SMALL", 40)],
        annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=4)
    ids = [en["id"] for en in panel["enrollments"]]

    # weight 10.0; Oct 20/20/25/25 -> 900, Nov 20/23/25/25 -> 930,
    # Dec 25x4 -> 1000 (benchmark month, certified).
    cyc_oct = collect_cycle("CES", "2026-10", panel["enrollments"],
                            dict(zip(ids, [20, 20, 25, 25])))
    cyc_nov = collect_cycle("CES", "2026-11", panel["enrollments"],
                            dict(zip(ids, [20, 23, 25, 25])))
    cyc_dec = setup_certified_cycle("CES", "2026-12", panel["enrollments"],
                                    dict(zip(ids, [25, 25, 25, 25])))

    run = create_benchmark_run("CES", "2026-12", [create_admin_cell_count(
        "MANUFACTURING", "SMALL", 1045)])
    applied = apply_benchmark_run(run["id"])
    assert applied["run_status"] == "APPLIED"
    assert_same_instant(applied["applied_at"], "2026-12-21T00:00:00Z")

    dec = get_single_cell(cyc_dec["id"], "MANUFACTURING", "SMALL")
    assert dec["employment_estimate"] == 1045
    assert dec["estimate_status"] == "FINAL"
    assert dec["revision_no"] == 2

    oct_cell = get_single_cell(cyc_oct["id"], "MANUFACTURING", "SMALL")
    assert oct_cell["employment_estimate"] == 941, (
        f"round_half_up(900 x 1.045) = round_half_up(940.5) = 941, got "
        f"{oct_cell['employment_estimate']}")
    assert oct_cell["estimate_status"] == "FINAL"
    assert oct_cell["revision_no"] == 2
    assert oct_cell["wedge_factor"] == 1.045000

    nov_cell = get_single_cell(cyc_nov["id"], "MANUFACTURING", "SMALL")
    assert nov_cell["employment_estimate"] == 972, (
        f"round_half_up(930 x 1.045) = round_half_up(971.85) = 972, got "
        f"{nov_cell['employment_estimate']}")
    assert nov_cell["estimate_status"] == "FINAL"

    assert oct_cell["employment_estimate"] + nov_cell["employment_estimate"] == 1913, (
        "per-month rounding is pinned; a sum-then-round implementation "
        "yields round_half_up(1830 x 1.045) == 1912")


def test_suppression_fixed_point_row_column_iteration_order(api):
    """PRD §3.5: "a cell is marked `PRIMARY` if and only if its `respondent_count` is below 3 — the minimum cell size — or its `dominance_flag` is true."
    PRD §3.5: "the industry row totals and size column totals are always computed from the full cell set including suppressed cells — suppression never changes a total."
    PRD §3.5: "A row holding exactly one suppressed cell causes the publishable cell in that row with the smallest `employment_estimate` to be marked `COMPLEMENTARY`, ties broken by `size_class` in the same order; a column holding exactly one suppressed cell likewise suppresses that column's smallest publishable cell, ties broken by ascending `industry_code` and then `size_class`."

    Design: Difficulty/combinatorial_formula/suppression_fixed_point_row_column_iteration_order
    """
    set_clock("2026-09-01T00:00:00Z")
    # Budget 38 over these strata yields raw shares of exactly 4/15/4/15 —
    # whole numbers, so no clamping or fractional-remainder reconciliation is
    # invoked and the allocation is identical under any reading of the
    # reconciliation rule. Weights: 7.5 / 2.0 / 7.5 / 2.0.
    setup_program_with_frozen_frame(
        code="CES", sample_budget=38,
        strata=[create_stratum("MANUFACTURING", "SMALL", 30),
                create_stratum("MANUFACTURING", "MEDIUM", 30),
                create_stratum("RETAIL", "SMALL", 30),
                create_stratum("RETAIL", "MEDIUM", 30)],
        annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel(
        "CES", specs=[("RETAIL", "SMALL", 2), ("RETAIL", "MEDIUM", 3),
                      ("MANUFACTURING", "SMALL", 3),
                      ("MANUFACTURING", "MEDIUM", 3)])
    en_r1, en_r2, en_r3, en_r4, en_r5, en_m1, en_m2, en_m3, en_m4, en_m5, \
        en_m6 = panel["enrollments"]

    cycle = collect_cycle("CES", "2026-09", panel["enrollments"], {
        en_r1["id"]: 5, en_r2["id"]: 5,
        en_r3["id"]: 8, en_r4["id"]: 10, en_r5["id"]: 12,
        en_m1["id"]: 2, en_m2["id"]: 4, en_m3["id"]: 6,
        en_m4["id"]: 10, en_m5["id"]: 14, en_m6["id"]: 16,
    })

    rs = get_single_cell(cycle["id"], "RETAIL", "SMALL")
    assert rs["employment_estimate"] == 75 and rs["respondent_count"] == 2
    assert rs["suppression_status"] == "PRIMARY", (
        "respondent_count 2 < 3 (the minimum cell size)")

    rm = get_single_cell(cycle["id"], "RETAIL", "MEDIUM")
    assert rm["employment_estimate"] == 60
    assert rm["suppression_status"] == "COMPLEMENTARY", (
        "RETAIL row held exactly one suppressed cell")

    ms = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert ms["employment_estimate"] == 90
    assert ms["suppression_status"] == "COMPLEMENTARY", (
        "SMALL column held exactly one suppressed cell")

    mm = get_single_cell(cycle["id"], "MANUFACTURING", "MEDIUM")
    assert mm["employment_estimate"] == 80
    assert mm["suppression_status"] == "COMPLEMENTARY", (
        "MEDIUM column held exactly one suppressed cell once RM was marked")

    # Totals come from the full cell set: read them through the bulletin.
    certify_cycle(cycle["id"])
    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z")
    grant = staged["grants"][0]
    outlet = staged["outlets"][0]
    bulletin = read_bulletin(grant["id"], outlet["id"])
    totals = bulletin["industry_totals"]
    assert len(totals) == 2
    # The PRD pins the figures ("industry row totals ... computed from the
    # complete cell set") but does not name the per-entry value field, so the
    # row and its figure are located by value rather than by key.
    retail_rows = [t for t in totals if "RETAIL" in t.values()]
    mfg_rows = [t for t in totals if "MANUFACTURING" in t.values()]
    assert len(retail_rows) == 1 and len(mfg_rows) == 1
    assert 135 in retail_rows[0].values(), "75 + 60 from the full cell set"
    assert 170 in mfg_rows[0].values(), "90 + 80 from the full cell set"
    for cell in bulletin["cells"]:
        assert cell["employment_estimate"] is None, (
            "all four cells suppressed at the fixed point; bulletins mask them")
