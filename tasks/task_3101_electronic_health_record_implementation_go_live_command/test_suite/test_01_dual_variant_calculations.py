"""Dual-variant calculation: one datum, two published readings.

Covers the readiness posture score and its optimistic variant, the provisional
versus final charge capture, and the strict-versus-inclusive conversion variance
threshold.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    assert_cost_precision,
    ApiErrorId,
    NON_EXISTENT_UUID,
    setup_program,
    setup_program_and_facility,
    create_department,
    create_build_item_payload,
    create_test_scenario_payload,
    create_defect_payload,
    create_conversion_batch_payload,
    create_patient_order_payload,
    get_success_data,
    get_facility,
    get_program,
    BUILD_ANALYST,
    TEST_LEAD,
    CONVERSION,
    RECONCILER,
    ANALYST,
)


# ===========================================================================
# r1_empty_program_readiness_metric_variants_agree
# ===========================================================================

def test_empty_program_publishes_both_readiness_variants_at_the_perfect_score(api, director_headers):
    """PRD §3.1: "A newly created program is in `PLANNING` status, its
    `current_epoch_index` is 0, and its `readiness_posture` is `OPEN`."
    PRD §3.1: "It is surfaced when a caller reads a single program with the
    `posture_view` query parameter set to `OPTIMISTIC`; the field is present on
    the program resource in every case, and the base `readiness_score` remains
    the value the cutover gate consults."
    PRD §2.5: "Its companion `readiness_score` is a number between 0.00 and
    100.00 inclusive."

    A program with no defect load scores a perfect 100.00 on both readings,
    because the optimistic variant returns a strictly higher figure only
    "whenever any build item of the program is in `BUILD_REJECTED`".

    Design: Difficulty/dual_variant_calc/r1_empty_program_readiness_metric_variants_agree
    """
    prog = setup_program()

    read = validate_success(api.get_ehr_implementation(prog["id"], director_headers), 200)
    assert read["readiness_score"] == pytest.approx(100.00, abs=0.01), (
        f"empty program must score a perfect readiness; got {read['readiness_score']}"
    )
    assert read["optimistic_readiness_score"] == pytest.approx(100.00, abs=0.01), (
        "with no build item mid-remediation the two variants agree"
    )
    assert read["readiness_posture"] == "OPEN"


def test_empty_program_baseline_read_is_numeric_and_object_shaped(api, director_headers):
    """PRD §3.1: "A newly created program is in `PLANNING` status, its
    `current_epoch_index` is 0, and its `readiness_posture` is `OPEN`."
    PRD §3.1: "The result is clamped into the range 0.00 to 100.00 inclusive
    and published to two decimal places."

    The base reading is the one the cutover gate consults, so it must always be
    a two-decimal number inside the clamped range rather than an absent field.

    Design: Difficulty/dual_variant_calc/r1_empty_program_readiness_metric_variants_agree
    """
    prog = setup_program()

    read = validate_success(api.get_ehr_implementation(prog["id"], director_headers), 200)
    assert isinstance(read["readiness_score"], (int, float))
    assert 0.00 <= read["readiness_score"] <= 100.00
    assert_cost_precision(read["readiness_score"])
    assert read["current_epoch_index"] == 0
    assert read["status"] == "PLANNING"


# ===========================================================================
# r1_optimistic_variant_discounts_remediation_capped_defect
# ===========================================================================

def _program_with_rejected_build_item():
    """One SEV1 defect on a BUILD_REJECTED build item, department and facility
    carried backwards by it."""
    from test_helpers import setup_rejected_build_item_with_sev1_defect

    return setup_rejected_build_item_with_sev1_defect(defect_code="LBL-9001", severity="SEV1")


def test_optimistic_variant_caps_a_rejected_items_defect_penalty(api, director_headers):
    """PRD §3.1: "a defect whose owning build item is sitting in `BUILD_REJECTED`
    mid-remediation contributes the smaller of its severity penalty and 5 points
    rather than its full severity penalty, while a defect whose build item is in
    any other status contributes the full penalty as usual."
    PRD §3.1: "The severity penalties are 40 points for `SEV1`, 25 for `SEV2`,
    10 for `SEV3` and 3 for `SEV4`, and a department with no open defect
    contributes 0."

    One SEV1 defect on a rejected item therefore reads 100.00 - 5.00 = 95.00 on
    the optimistic variant, while the base reading charges the full 40 points.

    Design: Difficulty/dual_variant_calc/r1_optimistic_variant_discounts_remediation_capped_defect
    """
    ctx = _program_with_rejected_build_item()

    read = validate_success(
        api.get_ehr_implementation(ctx["prog"]["id"], director_headers,
                                   params={"posture_view": "OPTIMISTIC"}),
        200,
    )
    assert read["optimistic_readiness_score"] == pytest.approx(95.00, abs=0.01), (
        f"a SEV1 defect on a BUILD_REJECTED item is capped at 5 points; "
        f"got {read['optimistic_readiness_score']}"
    )


def test_base_score_charges_the_full_penalty_while_the_optimistic_variant_does_not(api, director_headers):
    """PRD §3.1: "Open defects are grouped by the department that owns the build
    item they were raised against, and each department contributes a single
    penalty equal to the *largest* severity penalty among its open defects, not
    the sum of them".
    PRD §3.1: "This variant therefore returns a strictly higher figure than the
    base score whenever any build item of the program is in `BUILD_REJECTED`."

    The identical defect load reads 60.00 on the base (100 - 40) and 95.00 on
    the optimistic variant (100 - 5), so the two differ by exactly 35.00 and the
    ordering base < optimistic holds.

    Design: Difficulty/dual_variant_calc/r1_optimistic_variant_discounts_remediation_capped_defect
    """
    ctx = _program_with_rejected_build_item()

    read = validate_success(
        api.get_ehr_implementation(ctx["prog"]["id"], director_headers,
                                   params={"posture_view": "OPTIMISTIC"}),
        200,
    )
    assert read["readiness_score"] == pytest.approx(60.00, abs=0.01), (
        f"the base reading charges the full 40-point SEV1 penalty; got {read['readiness_score']}"
    )
    assert read["optimistic_readiness_score"] > read["readiness_score"], (
        "the optimistic variant must exceed the base while an item is BUILD_REJECTED"
    )
    assert read["optimistic_readiness_score"] - read["readiness_score"] == pytest.approx(35.00, abs=0.01)
    assert read["readiness_posture"] == "OPEN", "60.00 is the inclusive lower bound of OPEN"


# ===========================================================================
# r1_charge_capture_provisional_final_diverge_on_procedure
# ===========================================================================

def test_procedure_order_provisional_charge_omits_the_reconciled_gap(api, director_headers, conversion_headers):
    """PRD §3.7: "a procedure order carries an operating-room line of 20.0 percent
    and an anesthesia line of 5.0 percent."
    PRD §3.7: "For a procedure order only, a charge-capture gap line is added,
    computed as 3.0 percent of the unrounded sum of all the order's line items,
    rounded once to two decimal places, and this gap line is a
    final-variant-only construct."

    The provisional reading of a 10000-cent procedure order is the sum of its
    rounded lines only; the gap line does not participate before reconciliation.

    Design: Difficulty/dual_variant_calc/r1_charge_capture_provisional_final_diverge_on_procedure
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-4001", order_type="PROCEDURE",
            encounter_utc="2026-08-20T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))

    assert order["provisional_charge_cents"] == pytest.approx(12500.00, abs=0.01), (
        f"10000 base + 20% OR + 5% anesthesia = 12500.00; got {order['provisional_charge_cents']}"
    )
    assert order["clinical_state"] == "CONVERTED", (
        "the final variant attaches to the reconciled reading of the order"
    )


def test_reconciling_a_procedure_order_publishes_the_gap_and_the_variance(api, director_headers, conversion_headers, reconciler_headers, analyst_headers):
    """PRD §3.7: "The final charge is the provisional charge plus that gap,
    rounded half-up to two decimals, and the order's `charge_variance_cents`
    reports the final charge minus the provisional charge."
    PRD §3.7: "The frozen final figure is published at reconciliation, and it is
    recomputed and republished when the order's charge is posted."

    The gap on a 10000-cent procedure order is 3.0 percent of the unrounded line
    sum (12500.00), so the final charge is 12875.00 and the variance 375.00.

    Design: Difficulty/dual_variant_calc/r1_charge_capture_provisional_final_diverge_on_procedure
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-4001", order_type="PROCEDURE",
            encounter_utc="2026-08-20T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))

    reconciled = validate_success(api.reconcile_order(order["id"], reconciler_headers), 200)
    assert reconciled["clinical_state"] == "RECONCILED"
    assert reconciled["final_charge_cents"] == pytest.approx(12875.00, abs=0.01), (
        f"12500.00 + 3% gap of 375.00 = 12875.00; got {reconciled['final_charge_cents']}"
    )
    assert reconciled["charge_variance_cents"] == pytest.approx(375.00, abs=0.01)

    read = validate_success(api.get_patient_order(order["id"], analyst_headers), 200)
    assert read["final_charge_cents"] == pytest.approx(12875.00, abs=0.01)
    assert read["charge_variance_cents"] == pytest.approx(375.00, abs=0.01)


# ===========================================================================
# r1_conversion_variance_strict_threshold_vs_inclusive
# ===========================================================================

def test_batch_sitting_exactly_on_its_classification_cap_still_loads(api, director_headers, conversion_headers, analyst_headers):
    """PRD §3.2: "The variance measure itself is `variance_penalty_points`, the
    absolute count difference expressed as a percentage of the source count,
    rounded half-up to two decimal places."
    PRD §3.2: "Each payload class carries its own ceiling: 1.00 for
    `PATIENT_DEMOGRAPHICS`, 1.50 for `APPOINTMENTS`, 2.00 for `ORDERS` and 0.50
    for `BALANCES`. The load gate compares the batch's penalty against its
    ceiling with a strict *greater than*, so a batch sitting exactly on its
    ceiling loads successfully."

    1000 read with 990 reconciled is a 1.00 percent variance — exactly the
    PATIENT_DEMOGRAPHICS ceiling — and must load.

    Design: Difficulty/dual_variant_calc/r1_conversion_variance_strict_threshold_vs_inclusive
    """
    prog, fac = setup_program_and_facility()
    at_cap = get_success_data(api_client.create_conversion_batch(
        fac["id"],
        create_conversion_batch_payload(
            fac["version"], payload_class="PATIENT_DEMOGRAPHICS", attempt_epoch=0,
            source_count=1000, reconciled_count=990,
        ),
        conversion_headers,
    ))

    validating = validate_success(api.begin_batch_validation(at_cap["id"], conversion_headers), 200)
    assert validating["variance_penalty_points"] == pytest.approx(1.00, abs=0.01)

    loaded = validate_success(api.load_batch(at_cap["id"], conversion_headers), 200)
    assert loaded["status"] == "LOADED", (
        "a batch exactly on its ceiling loads because the gate is a strict greater-than"
    )
    facility = get_facility(fac["id"], analyst_headers)
    assert facility["converted_patient_count"] == 990


def test_batch_over_its_classification_cap_is_refused_on_load(api, director_headers, conversion_headers):
    """PRD §3.2: "A batch whose penalty exceeds its ceiling is refused with
    `ERR_BALANCE_VARIANCE_EXCEEDED` (HTTP 422), and if it is instead allowed to
    fail on its own the batch moves to `FAILED`."

    1000 read with 980 reconciled is a 2.00 percent variance, twice the
    PATIENT_DEMOGRAPHICS ceiling, so the load is refused and the batch is left
    untouched in VALIDATING.

    Design: Difficulty/dual_variant_calc/r1_conversion_variance_strict_threshold_vs_inclusive
    """
    prog, fac = setup_program_and_facility()
    over_cap = get_success_data(api_client.create_conversion_batch(
        fac["id"],
        create_conversion_batch_payload(
            fac["version"], payload_class="PATIENT_DEMOGRAPHICS", attempt_epoch=0,
            source_count=1000, reconciled_count=980,
        ),
        conversion_headers,
    ))
    get_success_data(api.begin_batch_validation(over_cap["id"], conversion_headers))

    refused = api.load_batch(over_cap["id"], conversion_headers)
    validate_error(refused, ApiErrorId.ERR_BALANCE_VARIANCE_EXCEEDED)

    read = validate_success(api.get_conversion_batch(over_cap["id"], conversion_headers), 200)
    assert read["variance_penalty_points"] == pytest.approx(2.00, abs=0.01)
    assert read["status"] == "VALIDATING", "the refused load must not move the batch on"