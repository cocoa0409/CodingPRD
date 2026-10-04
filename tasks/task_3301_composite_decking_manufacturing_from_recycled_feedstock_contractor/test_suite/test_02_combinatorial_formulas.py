"""Combinatorial formulas: changeover-minute branch summation and PCR decay
nested per-day rounding."""
from test_helpers import (
    create_run,
    get_success_data,
    make_active_formulation,
    make_plant,
    make_product_line,
    make_released_lot,
    make_supplier,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def _two_line_plant(api):
    """Plant (1 line) + activated formulation + two contrasting product lines."""
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    form = make_active_formulation()
    line1 = make_product_line(form["id"], name="L1", color="Grey", capped=False,
                              profile="GROOVED", emboss="WOODGRAIN")
    line2 = make_product_line(form["id"], name="L2", color="Brown", capped=True,
                              profile="SQUARE", emboss="SMOOTH")
    return plant, line1, line2


def test_changeover_initial_setup_and_full_branch_sum(api):
    """PRD §3.4: "With no predecessor, the changeover is 60 minutes of initial
    setup. With a predecessor, the changeover starts at a 15-minute base and
    accrues additive penalties for each physical difference between the two
    runs' product lines: 45 minutes when the `color` differs, 60 minutes when
    the `profile` differs, 30 minutes when the `emboss` differs, and 25
    minutes when the `capped` flag differs."

    Design: Difficulty/combinatorial_formula/changeover_minutes_mode_a
    """
    plant, line1, line2 = _two_line_plant(api)
    run1 = create_run(plant["id"], line1["id"], 500, "2026-03-02", run_kind="NULL_SLOT")
    assert run1["changeover_minutes"] == 60, (
        f"initial setup must be 60, got {run1['changeover_minutes']}"
    )
    assert run1["total_minutes"] == 60 + 72, (
        f"run_minutes ceil(500/10000*1440) = 72; total must be 132, got {run1['total_minutes']}"
    )
    run2 = create_run(plant["id"], line2["id"], 500, "2026-03-03", run_kind="NULL_SLOT")
    assert run2["changeover_minutes"] == 15 + 45 + 60 + 30 + 25, (
        f"all four attributes differ -> 175, got {run2['changeover_minutes']}"
    )
    assert run2["total_minutes"] == 175 + 72


def test_changeover_single_branch_color_only(api):
    """PRD §3.4: "45 minutes when the `color` differs, 60 minutes when the
    `profile` differs, 30 minutes when the `emboss` differs, and 25 minutes
    when the `capped` flag differs."

    Design: Difficulty/combinatorial_formula/changeover_minutes_mode_a
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    form = make_active_formulation()
    line1 = make_product_line(form["id"], name="L1", color="Grey", capped=False,
                              profile="GROOVED", emboss="WOODGRAIN")
    line2 = make_product_line(form["id"], name="L2", color="Brown", capped=False,
                              profile="GROOVED", emboss="WOODGRAIN")
    run1 = create_run(plant["id"], line1["id"], 500, "2026-03-02", run_kind="NULL_SLOT")
    run2 = create_run(plant["id"], line2["id"], 500, "2026-03-03", run_kind="NULL_SLOT")
    assert run2["changeover_minutes"] == 15 + 45, (
        f"color-only diff -> 60, got {run2['changeover_minutes']}"
    )


def test_pcr_decay_per_day_truncation_over_30_days(api):
    """PRD §3.12: "The `PCR_FILM` balance in `resin_store` decays at half a
    percent per elapsed calendar day since the previous review — or since
    plant creation for the first review. The decay is applied day by day in
    chronological order, truncating each day's result down to a whole pound
    before the next day is computed; equivalently, each day retains 99.5
    percent of the prior day's balance, floored daily rather than once on the
    compounded total."

    Design: Difficulty/combinatorial_formula/pcr_decay_nested_rounding_mode_b
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    supplier = make_supplier(kind="COLLECTION_PROGRAM")
    make_released_lot(supplier["id"], "PCR_FILM", 1000, received_date="2026-03-01")
    set_clock("2026-03-31T00:00:00Z")
    before = get_success_data(api.get_plant(plant["id"], OPS))
    reviewed = get_success_data(api.run_capacity_review(plant["id"], OPS))
    # Per-day floor over 30 days: iterating x = floor(x*0.995) from 1000 -> 850.
    # (Round-once floor(1000 * 0.995**30) would give 860.)
    expected = 1000
    for _ in range(30):
        expected = int(expected * 0.995)
    assert expected == 850  # sanity on the reference iteration
    assert reviewed["resin_store"]["PCR_FILM"] == expected, (
        f"per-day truncation must give {expected}, got {reviewed['resin_store']['PCR_FILM']}"
    )
    assert reviewed["season_posture"] == "SELLING"
    assert reviewed["version"] == before["version"] + 1


def test_pcr_decay_zero_elapsed_days_no_change(api):
    """PRD §3.12: "The `PCR_FILM` balance in `resin_store` decays at half a
    percent per elapsed calendar day since the previous review — or since
    plant creation for the first review."

    Design: Difficulty/combinatorial_formula/pcr_decay_nested_rounding_mode_b
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    supplier = make_supplier(kind="COLLECTION_PROGRAM")
    make_released_lot(supplier["id"], "PCR_FILM", 1000, received_date="2026-03-01")
    # Same-day review: zero elapsed days -> no decay applied.
    reviewed = get_success_data(api.run_capacity_review(plant["id"], OPS))
    assert reviewed["resin_store"]["PCR_FILM"] == 1000
