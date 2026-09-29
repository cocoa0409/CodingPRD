"""Rent-variant and screening-variant divergence over byte-identical inputs."""

from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_score_equals,
    assert_status,
)
from test_helpers.fixtures import (
    caprock_exercised_lease,
    caprock_qualified_parcel,
    caprock_recorded_lease,
    post_full_security,
    raise_curative,
    raise_invoice,
    read_invoice,
    read_lease,
    read_parcel,
    record_memo,
    rescreen,
    submit_memo,
    void_invoice,
)


def test_unrecorded_lease_bills_deeded_acres_and_suppresses_the_royalty():
    """
    An invoice raised while the memorandum is still unrecorded is provisional:
    it bills the deeded acreage and forces the royalty component to zero, so a
    royalty-hybrid structure still collects only its per-acre component.

    PRD: "Under `PROVISIONAL`, `acre_basis` is the parcel's deeded
    `gross_acres`, and `royalty_component_cents` is forced to 0 regardless of
    `production_mwh` and regardless of `royalty_rate_bps` — so
    `gross_rent_cents` equals `per_acre_component_cents` even under a
    `ROYALTY_HYBRID` structure."

    Design: Difficulty/dual_variant_calc/annual_rent_variant_divergence_on_recording
    """
    setup = caprock_exercised_lease(royalty_hybrid=True)
    lease = setup["lease"]
    assert lease["recording_status"] == "UNRECORDED"
    assert_acres_equals(lease["acre_basis_at_exercise"], 100.00, "acre_basis_at_exercise")
    assert_cents_equals(lease["total_security_required_cents"], 5225000, "total security")

    invoice = raise_invoice(lease["id"], period_year=1, production_mwh=90000)

    assert invoice["rent_variant"] == "PROVISIONAL"
    assert_acres_equals(invoice["acre_basis"], 125.00, "acre_basis")
    assert_cents_equals(invoice["per_acre_component_cents"], 15000000, "per-acre component")
    assert_cents_equals(invoice["royalty_component_cents"], 0, "royalty component")
    assert_cents_equals(invoice["gross_rent_cents"], 15000000, "gross rent")
    assert_status(invoice, "DRAFT", "invoice")


def test_recorded_lease_bills_as_built_acres_with_the_royalty_in_play():
    """
    Once the memorandum is recorded the same period, the same production and the
    same commercial terms produce a final as-built invoice on buildable acreage
    whose royalty component wins the greater-of comparison.

    PRD: "Under `FINAL_AS_BUILT`, `acre_basis` is the parcel's as-built
    `buildable_acres`, and `royalty_component_cents` is computed and does enter
    the greater-of comparison."

    Design: Difficulty/dual_variant_calc/annual_rent_variant_divergence_on_recording
    """
    setup = caprock_recorded_lease(royalty_hybrid=True)
    lease = setup["lease"]
    assert lease["recording_status"] == "RECORDED"

    invoice = raise_invoice(lease["id"], period_year=1, production_mwh=90000)

    assert invoice["rent_variant"] == "FINAL_AS_BUILT"
    assert_acres_equals(invoice["acre_basis"], 100.00, "acre_basis")
    assert_cents_equals(invoice["per_acre_component_cents"], 12000000, "per-acre component")
    assert_cents_equals(invoice["royalty_component_cents"], 13230000, "royalty component")
    assert_cents_equals(invoice["gross_rent_cents"], 13230000, "gross rent")


def test_void_and_replace_rebills_one_period_across_the_variant_boundary():
    """
    The void-and-replace path bills one period twice: once provisionally before
    recording and once as a final as-built figure afterwards. The two totals
    diverge by 1,770,000 cents on identical inputs, and the earlier invoice is
    left voided rather than restated.

    PRD: "A voided invoice frees its `period_year`, so a period first billed
    provisionally can be re-billed as a final as-built figure once the
    memorandum has been recorded — that is the intended use of the
    void-and-replace path."

    Design: Difficulty/dual_variant_calc/annual_rent_variant_divergence_on_recording
    """
    setup = caprock_exercised_lease(royalty_hybrid=True)
    lease_id = setup["lease"]["id"]

    provisional = raise_invoice(lease_id, period_year=1, production_mwh=90000)
    void_invoice(provisional["id"])

    post_full_security(lease_id)
    submit_memo(lease_id)
    record_memo(lease_id, "2026-0044821")
    assert read_lease(lease_id)["recording_status"] == "RECORDED"

    final = raise_invoice(lease_id, period_year=1, production_mwh=90000)

    assert provisional["rent_variant"] == "PROVISIONAL"
    assert final["rent_variant"] == "FINAL_AS_BUILT"
    assert_status(read_invoice(provisional["id"]), "VOID", "provisional invoice")
    delta = final["gross_rent_cents"] - provisional["gross_rent_cents"]
    assert delta == -1770000, f"variant delta: expected -1770000 cents, got {delta}"


def test_desktop_screening_ignores_a_newly_raised_blocking_defect():
    """
    A blocking title defect raised against a parcel screened under the desktop
    variant demotes it out of qualification through the counter alone, while its
    score and tier stay exactly where the desktop title report put them.

    PRD: "Under `DESKTOP` the effective grade is the `title_condition_grade`
    exactly as the desktop title report gave it, and open curative work is
    ignored entirely."

    Design: Difficulty/dual_variant_calc/parcel_screening_variant_divergence_on_field_verification
    """
    setup = caprock_qualified_parcel()
    parcel_id = setup["parcel"]["id"]
    assert setup["parcel"]["screen_mode"] == "DESKTOP"
    assert_status(setup["parcel"], "QUALIFIED", "parcel")

    raise_curative(
        parcel_id,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=450000,
    )

    parcel = read_parcel(parcel_id)
    assert parcel["blocking_curative_open_count"] == 1
    assert_status(parcel, "SCREENING", "parcel")
    assert parcel["screen_mode"] == "DESKTOP"
    assert_score_equals(parcel["screening_score"], 82.15, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY"
    assert_cents_equals(parcel["curative_cost_cents"], 0, "curative_cost_cents")


def test_field_verified_screening_steps_the_grade_down_and_changes_the_tier():
    """
    Re-screening the same parcel under the field-verified variant walks the title
    grade one rung down for the single open blocking defect, which drops the
    score into a different tier while every acreage figure stays put.

    PRD: "The two variants therefore return different scores, and can land in
    different tiers, for byte-identical parcel input."

    Design: Difficulty/dual_variant_calc/parcel_screening_variant_divergence_on_field_verification
    """
    setup = caprock_qualified_parcel()
    parcel_id = setup["parcel"]["id"]
    raise_curative(
        parcel_id,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=450000,
    )
    desktop = read_parcel(parcel_id)
    assert_score_equals(desktop["screening_score"], 82.15, "desktop screening_score")

    rescreen(parcel_id, "FIELD_VERIFIED")

    parcel = read_parcel(parcel_id)
    assert parcel["screen_mode"] == "FIELD_VERIFIED"
    assert_score_equals(parcel["screening_score"], 75.90, "screening_score")
    assert parcel["screening_tier"] == "STANDARD"
    assert_acres_equals(parcel["buildable_acres"], 100.00, "buildable_acres")
    assert_acres_equals(parcel["slope_excluded_acres"], 0.00, "slope_excluded_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 25.00, "setback_encumbered_acres"
    )
    assert_cents_equals(parcel["curative_cost_cents"], 0, "curative_cost_cents")
    assert parcel["blocking_curative_open_count"] == 1


def test_raising_a_defect_capitalises_nothing_under_either_variant():
    """
    Raising a blocking defect never capitalises its budgeted cost, whichever
    variant the parcel is screened under, because nothing has been cured yet.

    PRD: "Note what raising an item does **not** do: the parcel's
    `curative_cost_cents` is not touched at creation, because cost is
    capitalised only when the work is actually done."

    Design: Difficulty/dual_variant_calc/parcel_screening_variant_divergence_on_field_verification
    """
    setup = caprock_qualified_parcel()
    parcel_id = setup["parcel"]["id"]

    raise_curative(
        parcel_id,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=450000,
    )
    assert_cents_equals(
        read_parcel(parcel_id)["curative_cost_cents"], 0, "curative_cost_cents"
    )

    rescreen(parcel_id, "FIELD_VERIFIED")

    assert_cents_equals(
        read_parcel(parcel_id)["curative_cost_cents"], 0, "curative_cost_cents"
    )
