"""
Dual-variant derived figures and the combinatorial scoring formulas.

Covers the two places where the same inputs legitimately yield two answers -- the
provisional versus final shelf life and the interview-only versus reconciled screening
risk -- and the two composed formulas whose intermediate rounding and tier selection are
pinned by the specification.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    FEE_OPTICAL_ALL_SURCHARGES_CENTS,
    FEE_OPTICAL_PROCEDURE_SURCHARGE_CENTS,
    FEE_OPTICAL_SHORT_NOTICE_SURCHARGE_CENTS,
    FEE_OPTICAL_URGENCY_SURCHARGE_CENTS,
    SHELF_LIFE_VARIANT_FINAL,
    SHELF_LIFE_VARIANT_PROVISIONAL,
    T_NOW,
    assert_dimensions,
    assert_instant_equals,
    assert_whole_cents,
    factories,
    fixtures,
    hours_between,
    validate_success,
)


def _uncooled_therapeutic_chain(pinned_api, classify_tissues=False):
    """A never-cooled donor whose single cornea grades to a 2100 cell count."""
    return fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-B",
        donor_kwargs={
            "referral_source": "HOSPITAL",
            "body_cooled_at": None,
            "age_years": 52,
        },
        endothelial_cell_count=2100,
        classify_tissues=classify_tissues,
    )


def test_provisional_shelf_life_charges_only_the_band_penalty(pinned_api):
    """
    At recovery the shelf life is the medium's base allowance, because neither the
    donor's cooling history nor the endothelial count may be charged yet.

    PRD 3.3: "The result is then raised to a floor of 24 hours if it fell below, and
    stored in `shelf_life_hours`, with `expires_at` set to `preserved_at` advanced by
    that many whole hours."

    Design: Difficulty/dual_variant_calc/tissue_shelf_life_provisional_vs_final_expiry
    """
    chain = _uncooled_therapeutic_chain(pinned_api)

    donor = chain["donor"]
    assert donor["recovery_window_minutes"] == 720
    assert_instant_equals(
        donor["recovery_deadline_at"],
        "2026-08-03T14:00:00.000Z",
        "recovery_deadline_at",
    )
    assert chain["recovery"]["time_limit_band"] == "WITHIN_STANDARD"

    tissue = chain["tissues"][0]
    assert tissue["shelf_life_variant"] == SHELF_LIFE_VARIANT_PROVISIONAL
    assert tissue["shelf_life_hours"] == 336
    assert_instant_equals(
        tissue["expires_at"], "2026-08-17T09:00:00.000Z", "provisional expires_at"
    )
    assert (
        hours_between(tissue["preserved_at"], tissue["expires_at"])
        == tissue["shelf_life_hours"]
    )


def test_final_shelf_life_charges_the_cooling_and_low_endothelium_penalties(pinned_api):
    """
    Classification recomputes the shelf life under the final variant, docking 72 hours
    for a body that was never cooled and 24 more for a low endothelial count.

    PRD 3.5: "A **cooling penalty of 72 hours** is charged when the donor's
    `body_cooled_at` is null, meaning the body was never refrigerated, **or** when the
    number of whole floored minutes from `death_at` to `body_cooled_at` is strictly
    greater than 480 — that is, cooling began more than eight hours after death."

    Design: Difficulty/dual_variant_calc/tissue_shelf_life_provisional_vs_final_expiry
    """
    chain = _uncooled_therapeutic_chain(pinned_api)
    tissue_id = chain["tissue_ids"][0]
    provisional = fixtures.read_tissue(pinned_api, tissue_id)

    classified = fixtures.classify(pinned_api, tissue_id)

    assert classified["tissue_quality_score"] == 66
    assert classified["classification"] == "TRANSPLANT_THERAPEUTIC"
    assert_dimensions(classified, "ELIGIBLE", "IN_HOUSE")
    assert classified["shelf_life_variant"] == SHELF_LIFE_VARIANT_FINAL
    assert classified["shelf_life_hours"] == 240
    assert_instant_equals(
        classified["expires_at"], "2026-08-13T09:00:00.000Z", "final expires_at"
    )
    assert (
        provisional["shelf_life_hours"] - classified["shelf_life_hours"] == 96
    ), "the final figure must be 96 hours shorter than the provisional figure"


def _mixed_answer_donor(pinned_api):
    """A screened donor carrying one YES answer and two UNKNOWN answers."""
    donor = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-C",
        referral_source="MEDICAL_EXAMINER",
        age_years=60,
    )
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "YES", "SPOUSE")
    fixtures.add_screening(
        pinned_api, donor["id"], "HEP_B_C_HISTORY", "UNKNOWN", "MEDICAL_RECORD"
    )
    fixtures.add_screening(pinned_api, donor["id"], "SEPSIS", "UNKNOWN", "MEDICAL_RECORD")
    return donor["id"]


def _screening_rows(pinned_api, donor_id):
    response = pinned_api.list_screening_records(donor_id, COORDINATOR_HEADERS)
    return {row["question_code"]: row for row in validate_success(response)}


def test_interview_only_variant_charges_the_yes_total_alone(pinned_api):
    """
    While no resulted panel exists the risk score counts only the YES answers, so two
    UNKNOWN answers worth 55 points between them contribute nothing.

    PRD 3.1: "While the donor's `serology_status` is still `PENDING` — that is, while no
    resulted, non-invalidated panel exists — the variant is `INTERVIEW_ONLY` and
    `screening_risk_score` is the `YES` total alone: the historian's uncertainty is
    deliberately not charged against the donor."

    Design: Difficulty/dual_variant_calc/donor_screening_risk_interview_vs_post_serology_reconciled
    """
    donor_id = _mixed_answer_donor(pinned_api)

    donor = fixtures.read_donor(pinned_api, donor_id)
    assert donor["screening_risk_variant"] == "INTERVIEW_ONLY"
    assert donor["screening_risk_score"] == 10
    assert donor["serology_status"] == "PENDING"
    assert donor["status"] == "SCREENING"

    rows = _screening_rows(pinned_api, donor_id)
    assert rows["TATTOO_12M"]["weight_applied"] == 10
    assert rows["HEP_B_C_HISTORY"]["weight_applied"] == 0
    assert rows["SEPSIS"]["weight_applied"] == 0


def test_reconciled_variant_adds_the_unknown_total_when_hemodilution_trips(pinned_api):
    """
    A panel too dilute to trust resolves INDETERMINATE, which flips the variant and
    charges every UNKNOWN answer at its full weight.

    PRD 3.1: "When the predicate holds, every `UNKNOWN` answer is charged at its full
    weight and `screening_risk_score` becomes the `YES` total plus the `UNKNOWN` total,
    which for the same rows is strictly larger than the interview-only figure whenever
    any `UNKNOWN` answer exists."

    Design: Difficulty/dual_variant_calc/donor_screening_risk_interview_vs_post_serology_reconciled
    """
    donor_id = _mixed_answer_donor(pinned_api)
    before = fixtures.read_donor(pinned_api, donor_id)

    panel = fixtures.draw_panel(pinned_api, donor_id, hemodilution_pct=55.00)
    resulted = fixtures.post_results(pinned_api, panel["id"])
    assert resulted["overall_result"] == "INDETERMINATE"

    donor = fixtures.read_donor(pinned_api, donor_id)
    assert donor["screening_risk_variant"] == "POST_SEROLOGY_RECONCILED"
    assert donor["screening_risk_score"] == 65
    assert donor["screening_risk_score"] > before["screening_risk_score"]
    assert donor["serology_status"] == "INDETERMINATE"
    assert donor["status"] == "SCREENING"

    rows = _screening_rows(pinned_api, donor_id)
    assert rows["TATTOO_12M"]["weight_applied"] == 10
    assert rows["HEP_B_C_HISTORY"]["weight_applied"] == 30
    assert rows["SEPSIS"]["weight_applied"] == 25


def _optical_tissue_with_dmek_request(pinned_api):
    """An optical-grade cornea and an urgent DMEK request two days out."""
    chain = fixtures.tissue_chain(pinned_api, donor_code="D-2846-A")
    tissue = chain["tissues"][0]
    assert tissue["classification"] == "TRANSPLANT_OPTICAL"
    surgeon = fixtures.create_surgeon(pinned_api, "Dr Anwar Reed", "CTR-01", "DMEK")
    request = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="DMEK",
        surgery_date="2026-08-05T00:00:00.000Z",
        urgency="URGENT",
        as_surgeon=True,
    )
    return tissue, surgeon, request


def test_each_fee_surcharge_is_rounded_before_the_components_are_summed(pinned_api):
    """
    All three surcharges apply to a 245000 cent base, and rounding each half up on its
    own gives 277464 rather than the 277463 a single final rounding would produce.

    PRD 3.6: "On a base of 245000 cents with all three surcharges applicable, the raw
    amounts are 17762.5, 10412.5 and 4287.5, which round to 17763, 10413 and 4288
    respectively, summing to 32464 for a `processing_fee_cents` of 277464."

    Design: Difficulty/combinatorial_formula/allocation_fee_rounds_each_surcharge_before_summing
    """
    tissue, _surgeon, request = _optical_tissue_with_dmek_request(pinned_api)

    allocation = fixtures.allocate(pinned_api, tissue["id"], request["id"])

    assert_whole_cents(
        allocation["processing_fee_cents"],
        FEE_OPTICAL_ALL_SURCHARGES_CENTS,
        "processing_fee_cents",
    )
    assert allocation["processing_fee_cents"] == 245000 + (
        FEE_OPTICAL_URGENCY_SURCHARGE_CENTS
        + FEE_OPTICAL_PROCEDURE_SURCHARGE_CENTS
        + FEE_OPTICAL_SHORT_NOTICE_SURCHARGE_CENTS
    )
    assert allocation["processing_fee_cents"] != 277463
    assert allocation["processing_fee_cents"] == factories.expected_fee_cents(
        "TRANSPLANT_OPTICAL", "URGENT", "DMEK", 1
    )


def test_the_fee_is_keyed_on_the_snapshots_frozen_at_reservation(pinned_api):
    """
    Reservation pins the classification and cell count the fee is keyed on, and leaves
    the reserved tissue and request in their new states.

    PRD 3.6: "On success the allocation is created with `allocated_at` set to the current
    logical instant, `status` `RESERVED` and `source` `MANUAL`; `reserved_ecd_snapshot`
    is pinned from the `endothelial_cell_count` of the tissue's `RECORDED` `SPECULAR`
    evaluation and `reserved_classification_snapshot` is pinned from the tissue's
    `classification`, which at this point is necessarily `TRANSPLANT_OPTICAL` or
    `TRANSPLANT_THERAPEUTIC`."

    Design: Difficulty/combinatorial_formula/allocation_fee_rounds_each_surcharge_before_summing
    """
    tissue, _surgeon, request = _optical_tissue_with_dmek_request(pinned_api)

    allocation = fixtures.allocate(pinned_api, tissue["id"], request["id"])

    assert allocation["status"] == "RESERVED"
    assert allocation["source"] == "MANUAL"
    assert allocation["reserved_classification_snapshot"] == "TRANSPLANT_OPTICAL"
    assert allocation["reserved_ecd_snapshot"] == 3100
    assert_instant_equals(allocation["allocated_at"], T_NOW, "allocated_at")
    assert allocation["cancel_reason"] is None
    assert allocation["expiry_margin_hours"] == hours_between(
        "2026-08-05T00:00:00.000Z", tissue["expires_at"]
    )

    reserved = fixtures.read_tissue(pinned_api, tissue["id"])
    assert_dimensions(reserved, "RESERVED", "IN_HOUSE")
    assert reserved["issue_count"] == 0
    assert fixtures.read_request(pinned_api, request["id"])["status"] == "ALLOCATED"


def test_priority_tier_is_selected_from_the_base_score_alone(pinned_api):
    """
    An urgent request four days out scores 55 before the bonus, which is a GOLD tier and
    not the PLATINUM tier the post-bonus total would suggest.

    PRD 3.6: "In step two, `priority_tier` is selected **from `base_score` alone**:
    `PLATINUM` when `base_score` is 60 or more, `GOLD` when it is at least 40 but less
    than 60, and `STANDARD` otherwise."

    Design: Difficulty/combinatorial_formula/request_priority_tier_derived_from_base_score_only
    """
    surgeon = fixtures.create_surgeon(pinned_api, "Dr Mira Vale", "CTR-02", "PK")

    request = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="PK",
        surgery_date="2026-08-08T00:00:00.000Z",
        urgency="URGENT",
    )

    assert request["base_score"] == 55
    assert request["priority_tier"] == "GOLD"
    assert request["status"] == "OPEN"


def test_the_tier_bonus_is_never_re_read_against_the_tier_bands(pinned_api):
    """
    The GOLD bonus of 8 lifts the stored priority_score to 63; re-deriving the tier from
    63 would wrongly award the PLATINUM bonus and report 70.

    PRD 3.6: "Consider an `URGENT` request whose surgery is four days away: the urgency
    weight is 30, the proximity points are 25, `base_score` is 55, the tier is therefore
    `GOLD`, the bonus is 8, and `priority_score` is 63."

    Design: Difficulty/combinatorial_formula/request_priority_tier_derived_from_base_score_only
    """
    surgeon = fixtures.create_surgeon(pinned_api, "Dr Mira Vale", "CTR-02", "PK")

    request = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="PK",
        surgery_date="2026-08-08T00:00:00.000Z",
        urgency="URGENT",
    )

    assert request["priority_score"] == 63
    assert request["priority_score"] != 70
    assert (request["base_score"], request["priority_tier"], request["priority_score"]) == (
        factories.expected_priority("URGENT", 4)
    )
    stored = fixtures.read_request(pinned_api, request["id"])
    assert stored["priority_tier"] == "GOLD"
    assert stored["priority_score"] == 63
