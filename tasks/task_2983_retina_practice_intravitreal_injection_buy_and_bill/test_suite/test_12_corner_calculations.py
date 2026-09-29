"""
Calculation breadth: one scenario per formula, variant, selector ranking,
threshold constant and degenerate input set.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_vial_counters,
    validate_list,
)
from test_helpers import factories as f
from test_helpers.test_users import specialist_headers, tech_headers

QUIET_PATIENT_MRN = "MRN-2009"


# --------------------------------------------------------------------------
# shared scenario builders
# --------------------------------------------------------------------------


def _quiet_course_after_the_first_visit(breadth):
    """
    Stand up a one-dose loading course for a fresh open-access patient and put its
    first, quiescent, visit through documentation.  Returns the patient and plan.
    """
    breadth.pol_np_ref
    breadth.lot_ref
    clinician = breadth.cl1["id"]
    patient = breadth.patient(
        mrn=QUIET_PATIENT_MRN,
        full_name="Quentin Alder",
        payer_id=breadth.pay_np["id"],
        member_id="FOA-90009",
        contact_point="quentin.alder@example.test",
        notification_channel="EMAIL",
    )
    baseline = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=420,
        intraretinal_fluid=True,
        subretinal_fluid=True,
        va_letter_score=55,
    )
    plan = breadth.plan(
        clinician_id=clinician,
        patient_id=patient["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OD",
        loading_doses_required=1,
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=clinician, baseline_imaging_study_id=baseline["id"]
    )
    quiet = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime="2026-08-01T08:00:00Z",
        central_subfield_thickness_um=250,
        intraretinal_fluid=False,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=78,
    )
    assert quiet["disease_activity"] == "QUIESCENT"
    encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=quiet["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )
    breadth.document(
        encounter["id"],
        clinician_id=clinician,
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=16,
    )
    return patient, plan


def _quiet_visit(breadth, plan_id, patient_id, *, day, thickness, iop, va_letter_score):
    """Advance the clock to `day` and drive one more quiescent visit through the plan."""
    clinician = breadth.cl1["id"]
    breadth.set_clock(day + "T00:00:00Z")
    study = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient_id,
        eye="OD",
        study_datetime=day + "T08:00:00Z",
        central_subfield_thickness_um=thickness,
        intraretinal_fluid=False,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=va_letter_score,
    )
    current = breadth.read_plan(plan_id)
    encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan_id,
        imaging_study_id=study["id"],
        encounter_datetime=day + "T09:00:00Z",
        expected_treatment_plan_version=current["version"],
    )
    breadth.document(
        encounter["id"],
        clinician_id=clinician,
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=iop,
    )
    return breadth.read_plan(plan_id)


def _mandatory_payer_plan(breadth):
    """
    Put the Medicare Part B patient on an activated reference-product plan with both
    preferred biosimilars and a biosimilar lot on file.  Returns the plan and study.
    """
    breadth.pol_mcr_ref
    breadth.pol_mcr_bio_a
    breadth.pol_mcr_bio_b
    breadth.lot_ref
    breadth.lot_bio_a
    clinician = breadth.cl1["id"]
    study = breadth.imaging(
        clinician_id=clinician,
        patient_id=breadth.pt_mcr["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=460,
        intraretinal_fluid=True,
        subretinal_fluid=True,
        va_letter_score=48,
    )
    plan = breadth.plan(
        clinician_id=clinician,
        patient_id=breadth.pt_mcr["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=clinician, baseline_imaging_study_id=study["id"]
    )
    return activated, study


# --------------------------------------------------------------------------
# disease activity
# --------------------------------------------------------------------------


def test_a_single_fluid_flag_makes_a_thin_scan_active(breadth):
    """
    At 180 micrometres — far under the thickness threshold — a dry scan is quiescent
    while either fluid or a fresh haemorrhage alone flips the verdict to active.

    The PRD states the classifier as a disjunction, not a measurement: "The verdict is
    `ACTIVE` when the central subfield thickness is at least 300 micrometres, or
    intraretinal fluid is present, or subretinal fluid is present, or a new haemorrhage
    is present — any one of those four conditions suffices. When none of the four
    holds, the verdict is `QUIESCENT`."  Each study is judged alone: "Nothing outside
    the study being created participates in the verdict — no prior study, no plan
    history, no drug attribute."

    Design: Corner/calculations/corner_any_fluid_flag_forces_active_below_the_thickness_threshold
    """
    clinician = breadth.cl1["id"]
    patient = breadth.pt_np["id"]

    def read(**flags):
        base = dict(
            patient_id=patient,
            eye="OD",
            central_subfield_thickness_um=180,
            va_letter_score=80,
            intraretinal_fluid=False,
            subretinal_fluid=False,
            new_hemorrhage=False,
        )
        base.update(flags)
        return breadth.imaging(clinician_id=clinician, **base)

    dry = read(study_datetime="2026-08-01T00:00:00Z")
    wet = read(study_datetime="2026-08-01T01:00:00Z", subretinal_fluid=True)
    bleeding = read(study_datetime="2026-08-01T02:00:00Z", new_hemorrhage=True)

    assert dry["disease_activity"] == "QUIESCENT"
    assert wet["disease_activity"] == "ACTIVE"
    assert bleeding["disease_activity"] == "ACTIVE"


# --------------------------------------------------------------------------
# treat-and-extend steering
# --------------------------------------------------------------------------


def test_the_interval_extends_on_a_quiet_visit_and_contracts_on_an_active_one(breadth):
    """
    The first quiescent visit stretches the cadence from 28 to 42 days, and the next
    visit, on an active scan, pulls it back to 28 while intensifying the plan.

    The extension branch is stated as "if the driving study was `QUIESCENT`, the
    interval extends. The extension step is 14 days — two weeks — but it doubles to 28
    days when the prior quiescent run was already at least 3 ... The new
    `current_interval_days` is the smaller of the prior interval plus that step and the
    effective drug's `max_interval_days` ... `consecutive_quiescent_visits` becomes the
    prior run increased by one."  The contraction branch mirrors it: "Otherwise the
    driving study was `ACTIVE` and the interval contracts. The new
    `current_interval_days` is the larger of the prior interval less 14 days and the
    effective drug's `min_interval_days` ... `consecutive_quiescent_visits` resets to
    0."  Both due dates are clinical, not clock-based: "`next_due_date` becomes the
    encounter's `encounter_datetime` advanced by the new interval in whole days while
    keeping the encounter's time of day."  The status follows: the graduating dose moves
    the plan "`LOADING → MAINTENANCE` on the documentation whose incremented dose count
    exactly equals `loading_doses_required`", and afterwards "an `ACTIVE` study drives
    `MAINTENANCE → INTENSIFIED` with the reduction branch".

    Design: Corner/calculations/corner_interval_extends_on_a_quiescent_visit_then_reduces_on_an_active_one
    """
    patient, plan = _quiet_course_after_the_first_visit(breadth)

    after_first = breadth.read_plan(plan["id"])
    assert after_first["status"] == "MAINTENANCE"
    assert after_first["current_interval_days"] == 42
    assert after_first["consecutive_quiescent_visits"] == 1
    assert_instant_equals(
        after_first["next_due_date"], "2026-09-12T09:00:00Z", "next_due_date"
    )

    clinician = breadth.cl1["id"]
    breadth.set_clock("2026-08-29T00:00:00Z")
    active = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime="2026-08-29T08:00:00Z",
        central_subfield_thickness_um=430,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=52,
    )
    assert active["disease_activity"] == "ACTIVE"

    second = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=active["id"],
        encounter_datetime="2026-08-29T09:00:00Z",
        expected_treatment_plan_version=after_first["version"],
    )
    assert second["interval_days_from_previous"] == 28
    breadth.document(
        second["id"],
        clinician_id=clinician,
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=18,
    )

    after_second = breadth.read_plan(plan["id"])
    assert after_second["status"] == "INTENSIFIED"
    assert after_second["current_interval_days"] == 28
    assert after_second["consecutive_quiescent_visits"] == 0
    assert_instant_equals(
        after_second["next_due_date"], "2026-09-26T09:00:00Z", "next_due_date"
    )


def test_a_three_visit_quiet_run_doubles_the_step_until_the_products_ceiling_clamps(breadth):
    """
    Five consecutive quiet visits walk the cadence 28 → 42 → 56 → 70 → 98 → 112: the
    step doubles once the incoming run reaches three, and the drug's ceiling takes the
    last step.

    The PRD names both constants inside the extension branch: "The extension step is 14
    days — two weeks — but it doubles to 28 days when the prior quiescent run was
    already at least 3, rewarding a patient who has held quiet for three consecutive
    visits with a full extra month of freedom. The new `current_interval_days` is the
    smaller of the prior interval plus that step and the effective drug's
    `max_interval_days`, so the product's labelled ceiling always wins."  The run is read
    as it stood before the visit — "the plan's `consecutive_quiescent_visits` *as it
    stood before this visit*" — and a quiet visit on a maintenance plan stays there: "a
    `QUIESCENT` study on a plan already in `MAINTENANCE` re-enters `MAINTENANCE` with the
    same extension branch and the same increment."

    Design: Corner/calculations/corner_a_quiescent_run_of_three_doubles_the_step_and_then_the_max_interval_clamps
    """
    patient, plan = _quiet_course_after_the_first_visit(breadth)

    second = _quiet_visit(
        breadth, plan["id"], patient["id"], day="2026-08-29", thickness=250, iop=16, va_letter_score=79
    )
    assert second["current_interval_days"] == 56
    assert second["consecutive_quiescent_visits"] == 2

    third = _quiet_visit(
        breadth, plan["id"], patient["id"], day="2026-09-26", thickness=245, iop=15, va_letter_score=80
    )
    assert third["current_interval_days"] == 70
    assert third["consecutive_quiescent_visits"] == 3

    fourth = _quiet_visit(
        breadth, plan["id"], patient["id"], day="2026-10-24", thickness=240, iop=15, va_letter_score=81
    )
    assert fourth["current_interval_days"] == 98
    assert fourth["consecutive_quiescent_visits"] == 4
    assert_instant_equals(fourth["next_due_date"], "2027-01-30T09:00:00Z", "next_due_date")

    fifth = _quiet_visit(
        breadth, plan["id"], patient["id"], day="2026-11-21", thickness=238, iop=14, va_letter_score=82
    )
    assert fifth["current_interval_days"] == 112
    assert fifth["consecutive_quiescent_visits"] == 5
    assert_instant_equals(fifth["next_due_date"], "2027-03-13T09:00:00Z", "next_due_date")
    assert fifth["status"] == "MAINTENANCE"
    assert fifth["injections_administered"] == 5

    assert breadth.read_lot(breadth.lot_ref["id"])["vials_on_hand"] == 0


# --------------------------------------------------------------------------
# biosimilar substitution
# --------------------------------------------------------------------------


def test_a_payer_with_no_biosimilar_preference_dispenses_the_planned_product(breadth):
    """
    With an empty candidate pool and a payer expressing no preference, the encounter
    is written against the plan's own product and records no substitution.

    Two of the cascade's arms say so.  The pool falls through first — "when the plan's
    product is itself a biosimilar (its `is_biosimilar` is true) or the candidate pool
    came back empty, the plan's product is kept and `substituted_from_drug_id` stays
    null" — and the preference arm would not have fired anyway: "a payer whose
    preference is `NONE` never triggers one".  This payer's policy also
    needs no approval: "When `pa_required` is false, no authorization is consulted and
    the encounter's `prior_authorization_id` stays null."

    Design: Corner/calculations/corner_no_substitution_when_the_payer_has_no_biosimilar_preference
    """
    breadth.pol_np_ref
    breadth.lot_ref
    plan = breadth.plan_np_active

    response = breadth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=breadth.img_np["id"],
            encounter_datetime=breadth.ENCOUNTER_AT,
            expected_treatment_plan_version=plan["version"],
        ),
        specialist_headers(breadth.cl1["id"]),
    )
    booked = validate_success(response, 201)

    assert booked["effective_drug_id"] == breadth.drug_ref["id"]
    assert booked["substituted_from_drug_id"] is None
    assert booked["prior_authorization_id"] is None


def test_a_mandatory_payer_forces_the_cheapest_preferred_biosimilar(breadth):
    """
    Between two preferred biosimilars the mandatory payer takes the one with the lower
    contracted allowable, and the vial is drawn from that product's lot.

    The pool and its ranking are pinned: "The candidate pool is built first: every drug
    whose `reference_drug_id` names the plan's product, whose own `status` is `ACTIVE`,
    and for which a coverage policy exists on this patient's payer with `coverage_tier`
    of `PREFERRED`. Candidates are ranked by that policy's
    `drug_allowed_cents_per_billing_unit` ascending — cheapest contracted allowable
    first — with the candidate drug's own `created_at` ascending breaking any tie."  The
    third arm then fires: "when the payer's `biosimilar_preference` is `MANDATORY`, the
    chosen candidate becomes `effective_drug_id` and the displaced plan product is
    recorded in `substituted_from_drug_id`."  The vial follows the swap because the pool
    is keyed on the outcome — "whose lot's `drug_id` is the encounter's
    `effective_drug_id`".

    Design: Corner/calculations/corner_mandatory_preference_substitutes_the_cheapest_preferred_biosimilar
    """
    plan, study = _mandatory_payer_plan(breadth)

    response = breadth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=study["id"],
            encounter_datetime=breadth.ENCOUNTER_AT,
            expected_treatment_plan_version=plan["version"],
        ),
        specialist_headers(breadth.cl1["id"]),
    )
    booked = validate_success(response, 201)

    assert booked["effective_drug_id"] == breadth.drug_bio_a["id"]
    assert booked["substituted_from_drug_id"] == breadth.drug_ref["id"]

    vial = breadth.read_vial(booked["vial_id"])
    assert vial["drug_lot_id"] == breadth.lot_bio_a["id"]
    assert vial["status"] == "RESERVED"

    assert breadth.read_lot(breadth.lot_bio_a["id"])["vials_reserved"] == 1
    assert breadth.read_lot(breadth.lot_ref["id"])["vials_reserved"] == 0

    assert breadth.read_plan(plan["id"])["drug_id"] == breadth.drug_ref["id"]


def test_a_documented_medical_necessity_override_outranks_the_mandatory_preference(breadth):
    """
    The clinician's override is the first arm of the cascade, so the reference product
    is dispensed from the reference lot despite the payer's mandate.

    The PRD orders the arms and gives the override the first one: "exactly one of its
    five arms fires, tested in this order. 1. When `medical_necessity_override` is true,
    the plan's product is kept: `effective_drug_id` is the plan's `drug_id` and
    `substituted_from_drug_id` is null. A clinician's documented medical-necessity claim
    overrides even a mandatory payer preference — but `override_reason` must then be
    present and non-empty, or the request is rejected with
    `ERR_OVERRIDE_REASON_REQUIRED` (HTTP 422)."  The vial pool again keys on the outcome,
    "whose lot's `drug_id` is the encounter's `effective_drug_id`".

    Design: Corner/calculations/corner_medical_necessity_override_pins_the_plan_drug_against_a_mandatory_payer
    """
    plan, study = _mandatory_payer_plan(breadth)
    reason = "Documented hypersensitivity to the biosimilar excipient"

    response = breadth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=study["id"],
            encounter_datetime=breadth.ENCOUNTER_AT,
            expected_treatment_plan_version=plan["version"],
            medical_necessity_override=True,
            override_reason=reason,
        ),
        specialist_headers(breadth.cl1["id"]),
    )
    booked = validate_success(response, 201)

    assert booked["effective_drug_id"] == breadth.drug_ref["id"]
    assert booked["substituted_from_drug_id"] is None
    assert booked["medical_necessity_override"] is True
    assert booked["override_reason"] == reason

    vial = breadth.read_vial(booked["vial_id"])
    assert vial["drug_lot_id"] == breadth.lot_ref["id"]

    assert breadth.read_lot(breadth.lot_bio_a["id"])["vials_reserved"] == 0


def test_an_override_without_its_reason_reserves_nothing(breadth):
    """
    Raising the override flag with no justification is refused, and the refusal leaves
    no encounter, no reservation and no version bump behind.

    The requirement is conditional on the flag alone: "`override_reason` must then be
    present and non-empty, or the request is rejected with
    `ERR_OVERRIDE_REASON_REQUIRED` (HTTP 422)."  Nothing partial survives, because the
    vial is taken "Last of all, and only once every preceding gate has passed" and "no
    vial is ever reserved by a request that goes on to fail"; the plan's counter only
    moves on success, where "The plan's `version` advances by 1."

    Design: Corner/calculations/corner_override_without_a_reason_is_rejected
    """
    plan, study = _mandatory_payer_plan(breadth)

    response = breadth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=study["id"],
            encounter_datetime=breadth.ENCOUNTER_AT,
            expected_treatment_plan_version=plan["version"],
            medical_necessity_override=True,
        ),
        specialist_headers(breadth.cl1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_OVERRIDE_REASON_REQUIRED, 422)

    _, meta = validate_list(
        breadth.api.list_injection_encounters(
            specialist_headers(breadth.cl1["id"]), f.page_params(treatment_plan_id=plan["id"])
        )
    )
    assert meta["total_count"] == 0

    assert breadth.read_lot(breadth.lot_ref["id"])["vials_reserved"] == 0
    assert breadth.read_plan(plan["id"])["version"] == plan["version"]


# --------------------------------------------------------------------------
# vial selection
# --------------------------------------------------------------------------


def test_vial_selection_burns_the_earliest_expiry_then_the_dearest_lot(breadth):
    """
    The first booking takes the short-dated lot outright; the second breaks a tied
    expiry in favour of the more expensive lot rather than the cheaper one.

    The ranking is stated in full: "The pool is ranked first-expiring-first-out, by the
    lot's `expiration_date` ascending; ties are broken by the lot's
    `unit_acquisition_cost_cents` **descending**, burning the dearest capital first; and
    any remaining tie is broken by the vial's `created_at` ascending, never by the
    vial's identifier."  Each booking also records its lineage: "`previous_encounter_id`
    is set to whatever the plan's `last_encounter_id` was at the moment of creation" and
    "`interval_days_from_previous` records the whole days between that previous
    encounter's `encounter_datetime` and this one's".

    Design: Corner/calculations/corner_vial_selection_takes_the_earliest_expiry_then_the_dearest_lot
    """
    breadth.pol_np_ref
    reference = breadth.lot_ref
    early = breadth.lot(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9010",
        expiration_date="2026-12-31T00:00:00Z",
        received_date="2026-07-02T00:00:00Z",
        unit_acquisition_cost_cents=100000,
        vials_received=1,
    )
    dear = breadth.lot(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9011",
        expiration_date="2027-06-30T00:00:00Z",
        received_date="2026-07-03T00:00:00Z",
        unit_acquisition_cost_cents=140000,
        vials_received=1,
    )
    plan = breadth.plan_np_active
    clinician = breadth.cl1["id"]

    first = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=breadth.img_np["id"],
        encounter_datetime=breadth.ENCOUNTER_AT,
        expected_treatment_plan_version=plan["version"],
    )
    assert breadth.read_vial(first["vial_id"])["drug_lot_id"] == early["id"]

    later_study = breadth.imaging(
        clinician_id=clinician,
        patient_id=breadth.pt_np["id"],
        eye="OD",
        study_datetime="2026-08-29T08:00:00Z",
        central_subfield_thickness_um=415,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=56,
    )
    current = breadth.read_plan(plan["id"])
    second = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=later_study["id"],
        encounter_datetime="2026-08-29T09:00:00Z",
        expected_treatment_plan_version=current["version"],
    )

    assert breadth.read_vial(second["vial_id"])["drug_lot_id"] == dear["id"]
    assert breadth.read_vial(first["vial_id"])["status"] == "RESERVED"
    assert breadth.read_vial(second["vial_id"])["status"] == "RESERVED"
    assert breadth.read_lot(reference["id"])["vials_reserved"] == 0

    assert second["previous_encounter_id"] == first["id"]
    assert second["interval_days_from_previous"] == 28


# --------------------------------------------------------------------------
# billing-unit split and modifier assembly
# --------------------------------------------------------------------------


def test_emptying_the_vial_into_a_left_eye_bills_no_wastage_and_carries_jz(breadth):
    """
    A left-eye dose equal to the whole vial fill leaves nothing to discard, so eleven
    units are billed as administered and the wastage modifier is the zero-discard one.

    The split is arithmetic on the effective product: "Each volume is then converted to
    milligrams by multiplying by the drug's `mg_per_ml` — the administered volume giving
    the administered milligrams, the wasted volume giving the wasted milligrams."  The
    discard comes first — "for a `SINGLE_DOSE` product, `wasted_ml` is the effective
    drug's `vial_fill_ml` less `administered_dose_ml`, rounded half up to three decimal
    places" — and each line rounds alone: "Each of those two milligram figures is then
    divided by the drug's `billing_unit_mg` and rounded half up to a whole number
    **independently**, producing `administered_billing_units` and
    `wasted_billing_units`. Only after both lines have been rounded are they added
    together to give `total_billed_billing_units`."  The modifier list is positional:
    "Position zero is always laterality: `RT` when the encounter's `eye` is `OD`, `LT`
    when it is `OS`", and the second slot chooses between the two wastage codes — "`JW`
    when `wasted_billing_units` is greater than zero, and `JZ` when it is exactly zero,
    `JZ` being the attestation that nothing was discarded."

    Design: Corner/calculations/corner_zero_wastage_left_eye_injection_carries_lt_and_jz
    """
    breadth.pol_np_ref
    breadth.lot_ref
    clinician = breadth.cl1["id"]

    study = breadth.imaging(
        clinician_id=clinician,
        patient_id=breadth.pt_np["id"],
        eye="OS",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=470,
        intraretinal_fluid=True,
        subretinal_fluid=True,
        new_hemorrhage=True,
        va_letter_score=44,
    )
    plan = breadth.plan(
        clinician_id=clinician,
        patient_id=breadth.pt_np["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OS",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=clinician, baseline_imaging_study_id=study["id"]
    )
    encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=study["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )

    documented = validate_success(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0.27, post_injection_iop_mmhg=19),
            specialist_headers(clinician),
        ),
        200,
    )

    assert round(documented["wasted_ml"], 3) == 0.0
    assert documented["administered_billing_units"] == 11
    assert documented["wasted_billing_units"] == 0
    assert documented["total_billed_billing_units"] == 11
    assert documented["modifiers"] == ["LT", "JZ"]
    assert "JW" not in documented["modifiers"]


def test_a_compounded_multi_dose_vial_bills_no_wastage_line_at_all(breadth):
    """
    Injecting 0.05 ml from a 1.0 ml compounded vial produces a zero discard and a
    single-element modifier list — neither wastage code is appended.

    The wastage arm is conditional on the vial type: "Wastage volume comes first: for a
    `SINGLE_DOSE` product, `wasted_ml` is the effective drug's `vial_fill_ml` less
    `administered_dose_ml`, rounded half up to three decimal places; for a
    `MULTI_DOSE_COMPOUNDED` product, `wasted_ml` is exactly 0, because compounded
    multi-dose stock produces no billable discard."  The modifier rule keeps the second
    slot for single-dose products alone: "For a `SINGLE_DOSE` effective product a
    wastage modifier is appended second — `JW` when `wasted_billing_units` is greater
    than zero, and `JZ` when it is exactly zero, `JZ` being the attestation that nothing
    was discarded. A `MULTI_DOSE_COMPOUNDED` product carries neither `JW` nor `JZ`, so
    its `modifiers` array holds the laterality modifier alone."

    Design: Corner/calculations/corner_compounded_multi_dose_product_carries_no_wastage_modifier
    """
    breadth.pol_np_cmp
    breadth.lot_cmp
    clinician = breadth.cl1["id"]

    patient = breadth.patient(
        mrn="MRN-2013",
        full_name="Carol Nunez",
        payer_id=breadth.pay_np["id"],
        member_id="FOA-90013",
        contact_point="carol.nunez@example.test",
        notification_channel="EMAIL",
    )
    study = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=380,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=60,
    )
    plan = breadth.plan(
        clinician_id=clinician,
        patient_id=patient["id"],
        drug_id=breadth.drug_cmp["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=clinician, baseline_imaging_study_id=study["id"]
    )
    encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=study["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )

    documented = validate_success(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0.05, post_injection_iop_mmhg=15),
            specialist_headers(clinician),
        ),
        200,
    )

    assert round(documented["wasted_ml"], 3) == 0
    assert documented["modifiers"] == ["RT"]
    assert len(documented["modifiers"]) == 1
    assert documented["administered_billing_units"] == 2
    assert documented["wasted_billing_units"] == 0
    assert documented["total_billed_billing_units"] == 2


# --------------------------------------------------------------------------
# the patient-responsibility waterfall
# --------------------------------------------------------------------------


def test_with_no_enrollment_the_whole_coinsurance_stays_with_the_patient(breadth, billing):
    """
    A claim cut with no assistance on file prices three lines to 38000 cents, leaves
    the 3800 coinsurance on the patient, and reports a negative provisional margin
    because eight of the ten billed units are unreimbursed discard.

    The three lines are read off the policy: "`drug_billed_cents` is the encounter's
    `administered_billing_units` multiplied by the policy's
    `drug_allowed_cents_per_billing_unit`. `wastage_billed_cents` is the encounter's
    `wasted_billing_units` multiplied by that same rate — the discard is *always*
    billed, whether or not this payer reimburses it ... `wastage_allowed_cents` equal to
    `wastage_billed_cents` when the policy's `wastage_reimbursed` is true and exactly 0
    when it is false."  The waterfall then runs its first two steps —
    "`total_allowed_cents` is `drug_allowed_cents` plus `wastage_allowed_cents` plus
    `admin_allowed_cents`" and "`coinsurance_cents` is `total_allowed_cents` multiplied
    by the payer's `coinsurance_rate`, rounded half up to whole cents" — finds nothing to
    apply, since "an empty pool leaves that field null" and "With no enrollment the cap
    is 0", and lands above the relief threshold: "above that threshold the write-off is 0
    and `patient_responsibility_cents` is the full pre-relief balance".  The margin is
    benchmark-costed: "`standard_drug_cost_cents` is written as the encounter's
    `administered_billing_units` plus its `wasted_billing_units`, multiplied by the
    effective drug's `asp_cents_per_billing_unit` ... `provisional_margin_cents` is then
    the sum of `drug_allowed_cents`, `wastage_allowed_cents` and `admin_allowed_cents`,
    less `standard_drug_cost_cents`. Both `actual_acquisition_cost_cents` and
    `realized_margin_cents` remain null at this stage".

    Design: Corner/calculations/corner_waterfall_with_no_enrollment_leaves_the_whole_coinsurance_on_the_patient
    """
    encounter = breadth.enc_np_attested

    claim = validate_success(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=encounter["id"]), billing
        ),
        201,
    )

    assert claim["total_allowed_cents"] == 38000
    assert claim["coinsurance_cents"] == 3800
    assert claim["foundation_applied_cents"] == 0
    assert claim["assistance_enrollment_id"] is None
    assert claim["patient_responsibility_cents"] == 3800
    assert claim["practice_writeoff_cents"] == 0
    assert claim["provisional_margin_cents"] == -112000
    assert claim["realized_margin_cents"] is None
    assert claim["actual_acquisition_cost_cents"] is None
    assert claim["wastage_allowed_cents"] == 0
    assert claim["wastage_billed_cents"] == 112000
    assert claim["hcpcs_code"] == "J2778"
    assert claim["modifiers"] == ["RT", "JW"]

    assert breadth.read_encounter(encounter["id"])["status"] == "BILLED"


def test_a_balance_landing_exactly_on_the_relief_threshold_is_written_off_whole(
    breadth, billing, admin
):
    """
    A 2.5 percent coinsurance against a 40000 cent allowed total is exactly 1000 cents,
    and the inclusive comparison writes the entire balance off.

    The threshold sentence is inclusive on both the constant and the outcome: "When that
    pre-relief balance is less than or equal to 1000 cents, the whole of it becomes a
    small-balance write-off and `patient_responsibility_cents` becomes 0 ...
    `practice_writeoff_cents` is the small-balance write-off plus that payer shortfall."
    The provisional pass contributes no shortfall — "the payer is assumed to pay exactly
    its share, so the paid total is treated as `total_allowed_cents` less
    `coinsurance_cents` and the payer shortfall is therefore 0" — and the margin is again
    the benchmark comparison, "`provisional_margin_cents` ... less
    `standard_drug_cost_cents`".

    Design: Corner/calculations/corner_small_balance_writeoff_fires_at_exactly_the_threshold
    """
    breadth.lot_ref
    clinician = breadth.cl1["id"]

    payer = validate_success(
        breadth.api.create_payer(
            f.payer_payload(
                name="Threshold Mutual",
                payer_type="COMMERCIAL",
                coinsurance_rate=0.025,
                pa_required=False,
                biosimilar_preference="NONE",
                appeal_window_days=45,
            ),
            admin,
        ),
        201,
    )
    breadth.policy(
        payer_id=payer["id"],
        drug_id=breadth.drug_ref["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=15000,
        admin_allowed_cents=10000,
        wastage_reimbursed=False,
        pa_required=False,
    )
    patient = breadth.patient(
        mrn="MRN-2015",
        full_name="Wanda Osei",
        payer_id=payer["id"],
        member_id="TM-40015",
        contact_point="wanda.osei@example.test",
        notification_channel="EMAIL",
    )
    study = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=405,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=58,
    )
    plan = breadth.plan(
        clinician_id=clinician,
        patient_id=patient["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=clinician, baseline_imaging_study_id=study["id"]
    )
    encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=plan["id"],
        imaging_study_id=study["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )
    breadth.document(
        encounter["id"],
        clinician_id=clinician,
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=16,
    )
    breadth.attest(encounter["id"], clinician_id=breadth.cl2["id"], attested_wasted_ml=0.21)

    claim = validate_success(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=encounter["id"]), billing
        ),
        201,
    )

    assert claim["total_allowed_cents"] == 40000
    assert claim["coinsurance_cents"] == 1000
    assert claim["foundation_applied_cents"] == 0
    assert claim["patient_responsibility_cents"] == 0
    assert claim["practice_writeoff_cents"] == 1000
    assert claim["provisional_margin_cents"] == -110000


# --------------------------------------------------------------------------
# lot exposure
# --------------------------------------------------------------------------


def test_expiration_exposure_writes_off_every_vial_when_nothing_has_been_burned(breadth):
    """
    With no administered vial of the product anywhere, the burn rate is zero, so the
    expiration basis writes off all five vials — and the read leaves the lot untouched.

    The PRD makes the projection a pure function of recent consumption: "Inside that
    window the server counts vials whose status is `ADMINISTERED` and whose
    `administered_at` falls in the window, across every lot of the **same** product ...
    Dividing that count by thirty gives a per-day burn rate ... Multiplying the burn rate
    by the days remaining and taking the floor gives the projected consumable count,
    reported as `projected_burn_vials`. The vials at stake are those in `IN_STOCK` plus
    those in `RESERVED` — reported here as `unconsumed_vials` ... and the shortfall
    between that population and the projected consumable count, floored at 0, is the
    unusable count reported as `at_risk_vials`. Multiplying the unusable count by
    `unit_acquisition_cost_cents` gives `exposure_cents` on this basis. `days_held` is
    reported on this basis too, with the same meaning as before" — that meaning being
    "the whole number of days from the lot's `received_date` to the logical clock,
    truncated downward."  The read is a pure read: "The read persists nothing", and only
    the sweep may touch the accrual, "this endpoint is the only writer of that field".

    Design: Corner/calculations/corner_expiration_exposure_with_no_burn_history_writes_off_every_unconsumed_vial
    """
    breadth.pol_np_ref
    lot = breadth.lot_ref

    response = breadth.api.get_drug_lot_exposure(
        lot["id"], tech_headers(), f.exposure_params(basis="EXPIRATION")
    )
    exposure = validate_success(response, 200)

    assert exposure["basis"] == "EXPIRATION"
    assert exposure["drug_lot_id"] == lot["id"]
    assert exposure["projected_burn_vials"] == 0
    assert exposure["at_risk_vials"] == 5
    assert exposure["unconsumed_vials"] == 5
    assert exposure["exposure_cents"] == 660000
    assert exposure["days_held"] == 31

    settled = breadth.read_lot(lot["id"])
    assert settled["carrying_cost_accrued_cents"] == 0
    assert settled["version"] == lot["version"]
    assert settled["last_swept_at"] is None


# --------------------------------------------------------------------------
# step-therapy failure counting
# --------------------------------------------------------------------------


def test_the_step_therapy_count_ignores_a_draft_prerequisite_encounter(breadth, billing, admin):
    """
    One documented and one still-draft injection of the prerequisite product count as a
    single documented failure, which is exactly what the policy demands.

    The population is stated by status and by effective product: the server "counts this
    patient's injection encounters — across every plan the patient has ever had, with no
    time window at all, so the whole treatment history counts — restricted to encounters
    whose status is `DOCUMENTED`, `ATTESTED`, `BILLED` or `CLOSED`, whose
    `effective_drug_id` is the prerequisite product (the product actually injected, not
    whatever the plan nominated), and whose driving imaging study carried a
    `disease_activity` verdict of `ACTIVE`. That count ... is written to
    `step_therapy_failures_documented`. The gate then requires the count to be at least
    the policy's `required_prior_failures`".  A clearing first submission does three
    things: "A first submission out of `DRAFT` stores the `clinical_justification`,
    writes `step_therapy_failures_documented`, and increases `submission_count` by 1."
    The authorization's own reference data was frozen at creation — "`drug_id` is copied
    from the plan's planned product and is never re-derived afterwards, and `payer_id` is
    copied from the patient's current payer".

    Design: Corner/calculations/corner_step_therapy_count_ignores_draft_history_and_clears_the_gate
    """
    breadth.lot_ref
    clinician = breadth.cl1["id"]

    payer = validate_success(
        breadth.api.create_payer(
            f.payer_payload(
                name="Summit Step Health",
                payer_type="COMMERCIAL",
                coinsurance_rate=0.2,
                pa_required=True,
                biosimilar_preference="NONE",
                appeal_window_days=60,
            ),
            admin,
        ),
        201,
    )
    target = validate_success(
        breadth.api.create_drug(
            f.drug_payload(
                brand_name="Zaltruvex",
                hcpcs_code="J2779",
                vial_type="SINGLE_DOSE",
                vial_fill_ml=0.5,
                label_dose_ml=0.05,
                mg_per_ml=100,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=20000,
                min_interval_days=28,
                max_interval_days=112,
            ),
            admin,
        ),
        201,
    )
    breadth.policy(
        payer_id=payer["id"],
        drug_id=breadth.drug_ref["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=14000,
        admin_allowed_cents=10000,
        wastage_reimbursed=True,
        pa_required=False,
    )
    breadth.policy(
        payer_id=payer["id"],
        drug_id=target["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=20000,
        admin_allowed_cents=10000,
        wastage_reimbursed=True,
        pa_required=True,
        step_therapy_prerequisite_drug_id=breadth.drug_ref["id"],
        required_prior_failures=1,
    )
    patient = breadth.patient(
        mrn="MRN-2017",
        full_name="Sofia Vance",
        payer_id=payer["id"],
        member_id="SSH-30017",
        contact_point="sofia.vance@example.test",
        notification_channel="EMAIL",
    )

    first_study = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=440,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=54,
    )
    prerequisite_plan = breadth.plan(
        clinician_id=clinician,
        patient_id=patient["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        prerequisite_plan["id"],
        clinician_id=clinician,
        baseline_imaging_study_id=first_study["id"],
    )
    documented_encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=prerequisite_plan["id"],
        imaging_study_id=first_study["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )
    breadth.document(
        documented_encounter["id"],
        clinician_id=clinician,
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=17,
    )

    second_study = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OD",
        study_datetime="2026-08-29T08:00:00Z",
        central_subfield_thickness_um=435,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=53,
    )
    draft_encounter = breadth.encounter(
        clinician_id=clinician,
        treatment_plan_id=prerequisite_plan["id"],
        imaging_study_id=second_study["id"],
        encounter_datetime="2026-08-29T09:00:00Z",
        expected_treatment_plan_version=breadth.read_plan(prerequisite_plan["id"])["version"],
    )
    assert draft_encounter["status"] == "DRAFT"

    target_study = breadth.imaging(
        clinician_id=clinician,
        patient_id=patient["id"],
        eye="OS",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=450,
        intraretinal_fluid=True,
        subretinal_fluid=True,
        new_hemorrhage=False,
        va_letter_score=50,
    )
    target_plan = breadth.plan(
        clinician_id=clinician, patient_id=patient["id"], drug_id=target["id"], eye="OS"
    )
    target_activated = breadth.activate_plan(
        target_plan["id"], clinician_id=clinician, baseline_imaging_study_id=target_study["id"]
    )
    authorization = breadth.authorization(
        treatment_plan_id=target_plan["id"],
        expected_treatment_plan_version=target_activated["version"],
    )
    assert authorization["status"] == "DRAFT"

    submitted = validate_success(
        breadth.api.submit_prior_authorization(
            authorization["id"],
            f.authorization_submit_payload(
                clinical_justification=(
                    "Persistent exudation after a documented anti-VEGF failure on the "
                    "preferred product"
                )
            ),
            billing,
        ),
        200,
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["step_therapy_failures_documented"] == 1
    assert submitted["submission_count"] == 1
    assert submitted["drug_id"] == target["id"]
    assert submitted["payer_id"] == payer["id"]


# --------------------------------------------------------------------------
# adverse-event reportability
# --------------------------------------------------------------------------


def test_endophthalmitis_twenty_days_out_is_reportable_on_the_routine_deadline(breadth):
    """
    An infection twenty days after the injection is reportable on the event-type arm
    alone, with a deadline thirty days after symptom onset rather than after filing.

    The elapsed figure is measured from the injection: "`days_post_injection` is written
    as the whole days from the encounter's `encounter_datetime` to `onset_datetime`,
    truncated downward."  One arm suffices: "An event is `reportable` when any one of
    three conditions holds: its `event_type` is `ENDOPHTHALMITIS` and its
    `days_post_injection` is no more than thirty; or its `severity` is `SEVERE`; or its
    `culture_result` is `POSITIVE`. When reportable, `fda_report_due_date` is
    `onset_datetime` plus fifteen days for a `SEVERE` event and plus thirty days for any
    other severity — the deadline runs from symptom onset, not from the filing instant".
    The surveillance joins are server-side: "The server stamps `reported_by_clinician_id`
    from the acting `X-User-ID`, copies `patient_id` from the encounter, and resolves
    `source_drug_lot_id` by following the encounter's administered vial to its lot ... The
    event is born `REPORTED`".

    Design: Corner/calculations/corner_endophthalmitis_inside_the_window_is_reportable_on_the_routine_clock
    """
    encounter = breadth.enc_np_documented
    witness = breadth.cl2["id"]

    breadth.set_clock("2026-08-21T00:00:00Z")
    response = breadth.api.create_adverse_event(
        f.adverse_event_payload(
            injection_encounter_id=encounter["id"],
            event_type="ENDOPHTHALMITIS",
            onset_datetime="2026-08-21T09:00:00Z",
            severity="MODERATE",
            culture_result="PENDING",
        ),
        specialist_headers(witness),
    )
    event = validate_success(response, 201)

    assert event["days_post_injection"] == 20
    assert event["reportable"] is True
    assert_instant_equals(
        event["fda_report_due_date"], "2026-09-20T09:00:00Z", "fda_report_due_date"
    )
    assert event["status"] == "REPORTED"
    assert event["source_drug_lot_id"] == breadth.lot_ref["id"]
    assert event["patient_id"] == breadth.pt_np["id"]
    assert event["reported_by_clinician_id"] == witness


def test_endophthalmitis_one_day_past_the_window_carries_no_deadline(breadth):
    """
    An onset thirty-one days and an hour after the injection floors to thirty-one, which
    fails the window, and with no other arm firing the event is filed without a deadline.

    The window is an inclusive ceiling on a floored count — "`days_post_injection` is
    written as the whole days from the encounter's `encounter_datetime` to
    `onset_datetime`, truncated downward" and the arm requires that it "is no more than
    thirty" — and the other two arms are the severity and the culture, neither of which
    fires on a `MILD` event with a negative culture: "or its `severity` is `SEVERE`; or
    its `culture_result` is `POSITIVE`. ... When not reportable, `fda_report_due_date`
    is null and `reportable` is false."  The workflow state is independent of all of it:
    "The event is born `REPORTED`, with `adjudicated_by_clinician_id` and
    `adjudication_note` null."

    Design: Corner/calculations/corner_endophthalmitis_one_day_outside_the_window_is_not_reportable
    """
    encounter = breadth.enc_np_documented
    witness = breadth.cl2["id"]

    breadth.set_clock("2026-09-01T00:00:00Z")
    response = breadth.api.create_adverse_event(
        f.adverse_event_payload(
            injection_encounter_id=encounter["id"],
            event_type="ENDOPHTHALMITIS",
            onset_datetime="2026-09-01T10:00:00Z",
            severity="MILD",
            culture_result="NEGATIVE",
        ),
        specialist_headers(witness),
    )
    event = validate_success(response, 201)

    assert event["days_post_injection"] == 31
    assert event["reportable"] is False
    assert event["fda_report_due_date"] is None
    assert event["status"] == "REPORTED"


# --------------------------------------------------------------------------
# the recall notice table
# --------------------------------------------------------------------------


def test_the_notification_deadline_comes_from_the_recall_class_table(breadth):
    """
    Two recalls opened at the same clock get deadlines three and ten days out
    respectively, and neither generates a notification because no drug ever reached a
    patient.

    The deadline reads the clock and the class alone: "`notification_deadline_date` is
    computed as the logical clock plus the class notice period: three days for `CLASS_I`,
    ten for `CLASS_II`, thirty for `CLASS_III`."  The same call moves the lot — "the lot
    moves to `RECALLED`, which is terminal; both its `IN_STOCK` and its `RESERVED` vials
    move to `QUARANTINED`" — while the notification set is drawn from injected doses
    only: "The exposed population is every injection encounter whose administered vial
    belongs to the recalled lot and whose `status` is `DOCUMENTED`, `ATTESTED`, `BILLED`
    or `CLOSED` ... The recall's `notifications_required` is set to the size of that
    exposed set".

    Design: Corner/calculations/corner_recall_notification_deadline_follows_the_recall_class_table
    """
    breadth.pol_np_ref
    first_lot = breadth.lot_ref
    second_lot = breadth.lot(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9002",
        expiration_date="2027-07-31T00:00:00Z",
        received_date="2026-07-05T00:00:00Z",
        unit_acquisition_cost_cents=131000,
        vials_received=2,
    )

    class_one = breadth.recall(
        drug_lot_id=first_lot["id"],
        recall_class="CLASS_I",
        reason="Sterility failure in the filling line",
    )
    class_two = breadth.recall(
        drug_lot_id=second_lot["id"],
        recall_class="CLASS_II",
        reason="Carton mislabelling",
    )

    assert_instant_equals(
        class_one["notification_deadline_date"],
        "2026-08-04T00:00:00Z",
        "notification_deadline_date",
    )
    assert_instant_equals(
        class_two["notification_deadline_date"],
        "2026-08-11T00:00:00Z",
        "notification_deadline_date",
    )
    assert class_one["notifications_required"] == 0
    assert class_two["notifications_required"] == 0

    _, meta = validate_list(
        breadth.api.list_recall_notifications(
            tech_headers(), f.page_params(lot_recall_id=class_one["id"])
        )
    )
    assert meta["total_count"] == 0

    recalled = breadth.read_lot(first_lot["id"])
    assert recalled["status"] == "RECALLED"
    assert_vial_counters(recalled, vials_quarantined=5, vials_on_hand=0)
    assert breadth.read_lot(second_lot["id"])["vials_quarantined"] == 2
