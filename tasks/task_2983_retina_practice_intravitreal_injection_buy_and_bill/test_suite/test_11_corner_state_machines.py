"""
State-machine breadth: initial states, one valid edge each, the side effects an
edge is declared to fire, refused edges, non-idempotent triggers and terminal
lockdown.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_instant_equals, assert_vial_counters
from test_helpers import factories as f
from test_helpers.test_users import (
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_2,
    compliance_headers,
    specialist_headers,
    tech_headers,
)


def test_activation_moves_a_draft_plan_into_loading_with_the_cadence_seeded(breadth):
    """
    A draft plan activated against an active same-eye baseline enters loading with
    the 28-day cadence, a due date 28 days out and a second version.

    The PRD names the edge — "Activation is the decision that treatment is justified,
    and it moves the plan `DRAFT → LOADING`" — and pins everything it writes: "A
    successful activation writes `baseline_imaging_study_id` onto the plan, sets
    `current_interval_days` to 28 — four weeks, the loading cadence — sets
    `next_due_date` to the logical clock advanced by those 28 days, and advances the
    plan's `version` by 1."  The starting point is equally fixed: "A new plan is born
    in `DRAFT` with `version` 1", and "`injections_administered` and
    `consecutive_quiescent_visits` both start at 0".

    Design: Corner/state_machines/corner_plan_activate_from_draft_enters_loading_with_seeded_schedule
    """
    breadth.pol_np_ref
    study = breadth.img_np
    plan = breadth.plan_np

    assert plan["status"] == "DRAFT"
    assert plan["version"] == 1

    response = breadth.api.activate_treatment_plan(
        plan["id"],
        f.plan_activate_payload(baseline_imaging_study_id=study["id"]),
        specialist_headers(breadth.cl1["id"]),
    )
    activated = validate_success(response, 200)

    assert activated["status"] == "LOADING"
    assert activated["version"] == 2
    assert activated["current_interval_days"] == 28
    assert_instant_equals(activated["next_due_date"], "2026-08-29T00:00:00Z", "next_due_date")
    assert activated["baseline_imaging_study_id"] == study["id"]
    assert activated["injections_administered"] == 0
    assert activated["consecutive_quiescent_visits"] == 0


def test_a_baseline_study_on_the_other_eye_leaves_the_plan_in_draft(breadth):
    """
    An active study of the same patient's other eye cannot justify this plan, and the
    refusal leaves the plan unactivated.

    The activate precondition names the eye explicitly: "the nominated study belongs
    to the plan's patient and its `eye` equals the plan's `eye` ... A study whose
    patient or eye disagrees with the plan is rejected with `ERR_IMAGING_EYE_MISMATCH`
    (HTTP 422)."  Nothing is written on the way out, so the plan is still at its
    birth state, where "Before activation, `current_interval_days` and `next_due_date`
    are both null, as are `baseline_imaging_study_id` and `last_encounter_id`" and "A
    new plan is born in `DRAFT` with `version` 1".

    Design: Corner/state_machines/corner_plan_activate_with_wrong_eye_baseline_study_rejected
    """
    breadth.pol_np_ref
    breadth.img_np
    plan = breadth.plan_np

    other_eye = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=breadth.pt_np["id"],
        eye="OS",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=410,
        intraretinal_fluid=True,
        va_letter_score=57,
    )
    assert other_eye["disease_activity"] == "ACTIVE"

    response = breadth.api.activate_treatment_plan(
        plan["id"],
        f.plan_activate_payload(baseline_imaging_study_id=other_eye["id"]),
        specialist_headers(breadth.cl1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_IMAGING_EYE_MISMATCH, 422)

    unchanged = breadth.read_plan(plan["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1
    assert unchanged["baseline_imaging_study_id"] is None
    assert unchanged["next_due_date"] is None


def test_one_documentation_fires_the_split_the_modifiers_the_vial_and_the_plan(breadth):
    """
    A single document call splits the vial into billing units, assembles the
    modifiers, consumes the reserved vial and advances the plan's schedule.

    The PRD works the arithmetic out for exactly this product: "Consider a product
    supplied at 0.27 ml per vial with a concentration of 40 mg per ml and a billing
    unit of 1 mg, from which 0.06 ml is injected. The administered milligrams are 2.4,
    which rounds to 2 units; the wasted volume is 0.21 ml, or 8.4 mg, which rounds to
    8 units; the total billed is therefore 10 units."  The modifiers follow the pinned
    order: "Position zero is always laterality: `RT` when the encounter's `eye` is
    `OD`", and "For a `SINGLE_DOSE` effective product a wastage modifier is appended
    second — `JW` when `wasted_billing_units` is greater than zero".  The vial and the
    plan move together: "The reserved vial moves `RESERVED → ADMINISTERED` and has
    `administered_at` stamped with the encounter's `encounter_datetime`", while the
    loading branch pins the cadence — "`current_interval_days` is pinned to 28 days
    regardless of what the imaging showed" — and "`next_due_date` becomes the
    encounter's `encounter_datetime` advanced by the new interval in whole days while
    keeping the encounter's time of day".  The driving study is `ACTIVE`, so the run
    "is reset to 0", and a plan's first encounter has "`interval_days_from_previous`
    ... likewise null".

    Design: Corner/state_machines/corner_document_fires_every_declared_side_effect_once
    """
    encounter = breadth.enc_np
    assert encounter["status"] == "DRAFT"

    response = breadth.api.document_injection_encounter(
        encounter["id"],
        f.document_payload(administered_dose_ml=0.06, post_injection_iop_mmhg=17),
        specialist_headers(breadth.cl1["id"]),
    )
    documented = validate_success(response, 200)

    assert round(documented["wasted_ml"], 3) == 0.21
    assert documented["modifiers"] == ["RT", "JW"]
    assert documented["administered_billing_units"] == 2
    assert documented["wasted_billing_units"] == 8
    assert documented["total_billed_billing_units"] == 10
    assert documented["status"] == "DOCUMENTED"
    assert documented["interval_days_from_previous"] is None

    vial = breadth.read_vial(encounter["vial_id"])
    assert vial["status"] == "ADMINISTERED"
    assert_instant_equals(vial["administered_at"], breadth.ENCOUNTER_AT, "administered_at")

    lot = breadth.read_lot(breadth.lot_ref["id"])
    assert_vial_counters(lot, vials_on_hand=4, vials_reserved=0, vials_administered=1)

    plan = breadth.read_plan(breadth.plan_np["id"])
    assert plan["injections_administered"] == 1
    assert plan["current_interval_days"] == 28
    assert_instant_equals(plan["next_due_date"], "2026-08-29T09:00:00Z", "next_due_date")
    assert plan["status"] == "LOADING"
    assert plan["last_encounter_id"] == encounter["id"]
    assert plan["consecutive_quiescent_visits"] == 0


def test_a_newly_booked_encounter_is_a_draft_holding_a_reserved_vial(breadth):
    """
    Creation alone produces a draft with no clinical documentation on it, a stamped
    injector and a vial already off the shelf.

    The PRD fixes the birth state — "A new encounter is born in `DRAFT`" — and the
    empty fields: "While the encounter remains in `DRAFT`, `administered_dose_ml`,
    `wasted_ml`, `administered_billing_units`, `wasted_billing_units`,
    `total_billed_billing_units`, `modifiers`, `injection_site_prep_confirmed`,
    `post_injection_iop_mmhg`, `attested_by_clinician_id` and `void_reason` are all
    null."  Identity is not the client's to give: "The acting specialist's identifier
    is stamped as `clinician_id`, and `patient_id` and `eye` are copied from the plan;
    none of the three may be supplied by the client."  This payer needs no
    authorization — "When `pa_required` is false, no authorization is consulted and the
    encounter's `prior_authorization_id` stays null" — while the vial is taken at once:
    "the vial moves `IN_STOCK → RESERVED` with `reserved_for_encounter_id` naming this
    encounter and `reserved_at` set to the logical clock".

    Design: Corner/state_machines/corner_new_injection_encounter_starts_in_draft
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

    assert booked["status"] == "DRAFT"
    assert booked["version"] == 1
    assert booked["administered_dose_ml"] is None
    assert booked["wasted_ml"] is None
    assert booked["modifiers"] is None
    assert booked["attested_by_clinician_id"] is None
    assert booked["void_reason"] is None
    assert booked["clinician_id"] == breadth.cl1["id"]
    assert booked["eye"] == "OD"
    assert booked["prior_authorization_id"] is None

    vial = breadth.read_vial(booked["vial_id"])
    assert vial["status"] == "RESERVED"
    assert_instant_equals(vial["reserved_at"], breadth.CLOCK, "reserved_at")


def test_the_second_documentation_of_the_same_encounter_is_refused(breadth):
    """
    Repeating the document call neither doubles the billing units nor consumes a
    second vial nor bumps the plan again.

    The PRD forbids the repeat outright: "Only the injecting clinician may do it: the
    acting `X-User-ID` must equal the encounter's `clinician_id`, and a different
    specialist attempting it is refused with `ERR_ENCOUNTER_STATE_INVALID` (HTTP 409),
    as is any attempt to document an encounter that is not in `DRAFT` — documenting
    twice is impossible."  The first pass already reached its terminal figures — "the
    total billed is therefore 10 units" — and the lot counter is a recomputation, not
    an increment: "The vial's lot has `vials_reserved` and `vials_administered`
    recomputed."

    Design: Corner/state_machines/corner_documenting_an_already_documented_encounter_is_rejected
    """
    documented = breadth.enc_np_documented
    assert documented["total_billed_billing_units"] == 10

    response = breadth.api.document_injection_encounter(
        documented["id"],
        f.document_payload(administered_dose_ml=0.06, post_injection_iop_mmhg=17),
        specialist_headers(breadth.cl1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ENCOUNTER_STATE_INVALID, 409)

    settled = breadth.read_encounter(documented["id"])
    assert settled["status"] == "DOCUMENTED"
    assert settled["total_billed_billing_units"] == 10

    lot = breadth.read_lot(breadth.lot_ref["id"])
    assert_vial_counters(lot, vials_administered=1, vials_on_hand=4)

    assert breadth.read_plan(breadth.plan_np["id"])["injections_administered"] == 1


def test_the_recall_ladder_cannot_be_entered_at_any_step_but_the_first(breadth, billing):
    """
    Closure, return shipment and credit reconciliation are all refused on a recall
    still sitting at its first rung, and the recall keeps its opening figures.

    The PRD makes the order mandatory: "The recall's steps must be walked in order,
    and any attempt to take one out of turn is `ERR_RECALL_STATE_INVALID` (HTTP 409);
    each step also belongs to a different role, so no single person can walk the whole
    ladder."  Closure's own edge starts elsewhere — "Closure is a `ComplianceOfficer`
    action carrying `closure_note`, moving the recall `CREDIT_RECONCILED → CLOSED`,
    which is terminal" — and it is attempted here by a second officer because "the
    closer must not be the initiator: an acting `X-User-ID` equal to
    `initiated_by_user_id` is refused with `ERR_RECALL_CLOSER_CONFLICT` (HTTP 403)".
    The opening figures are pinned: "`notification_deadline_date` is computed as the
    logical clock plus the class notice period: three days for `CLASS_I`, ten for
    `CLASS_II`, thirty for `CLASS_III`", "both its `IN_STOCK` and its `RESERVED` vials
    move to `QUARANTINED`", and "`notifications_acknowledged`,
    `notifications_unreachable` and `vials_returned_count` all start at 0,
    `credit_expected_cents` starts at 0, and `credit_received_cents`,
    `carrier_reference`, `closed_by_user_id` and `closure_note` all start null".

    Design: Corner/state_machines/corner_closing_a_recall_from_initiated_cannot_skip_states
    """
    breadth.enc_np_documented
    recall = breadth.recall(
        drug_lot_id=breadth.lot_ref["id"],
        recall_class="CLASS_III",
        reason="Labelling defect on the carton",
        user_id=COMPLIANCE_USER_ID,
    )

    assert recall["status"] == "INITIATED"
    assert_instant_equals(
        recall["notification_deadline_date"],
        "2026-08-31T00:00:00Z",
        "notification_deadline_date",
    )

    validate_error(
        breadth.api.close_lot_recall(
            recall["id"],
            f.recall_close_payload(closure_note="Trying to close before anything happened"),
            compliance_headers(COMPLIANCE_USER_ID_2),
        ),
        ApiErrorId.ERR_RECALL_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.ship_recall_return(
            recall["id"],
            f.ship_return_payload(carrier_reference="UPS-TOO-EARLY"),
            tech_headers(),
        ),
        ApiErrorId.ERR_RECALL_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.reconcile_recall_credit(
            recall["id"], f.reconcile_credit_payload(credit_received_cents=1), billing
        ),
        ApiErrorId.ERR_RECALL_STATE_INVALID,
        409,
    )

    settled = breadth.read_recall(recall["id"])
    assert settled["status"] == "INITIATED"
    assert settled["credit_expected_cents"] == 0
    assert settled["vials_returned_count"] == 0
    assert settled["closed_by_user_id"] is None

    lot = breadth.read_lot(breadth.lot_ref["id"])
    assert lot["vials_quarantined"] == 4
    assert lot["vials_returned"] == 0


def test_a_voided_encounter_refuses_every_further_move(breadth, billing):
    """
    Once voided, the encounter accepts neither documentation, attestation, a second
    void nor a claim, and the vial it was holding is back on the shelf.

    `VOIDED` is one of the two dead ends: "`CLOSED` and `VOIDED` are the encounter's
    two terminal statuses."  Each refused move names the same code from its own
    paragraph — documentation refuses "any attempt to document an encounter that is
    not in `DRAFT`", attestation refuses anything "that is not `DOCUMENTED`", the void
    endpoint only accepts "an encounter that is in `DRAFT` or `DOCUMENTED`", and a
    claim requires that "the encounter must be `ATTESTED` — an unattested encounter
    cannot be billed, and the attempt is `ERR_ENCOUNTER_STATE_INVALID` (HTTP 409)".
    The release happened at the void: "Voiding from `DRAFT` releases the reservation.
    The vial moves `RESERVED → IN_STOCK`, both `reserved_for_encounter_id` and
    `reserved_at` are cleared to null, and the lot's counters are recomputed. Because
    the encounter never consumed a dose, the plan's dose counters were never bumped and
    need no adjustment".

    Design: Corner/state_machines/corner_voided_encounter_is_terminal_and_locked_down
    """
    encounter = breadth.enc_np
    injector = specialist_headers(breadth.cl1["id"])
    witness = specialist_headers(breadth.cl2["id"])

    voided = validate_success(
        breadth.api.void_injection_encounter(
            encounter["id"],
            f.void_payload(void_reason="Patient declined at the chair"),
            injector,
        ),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "Patient declined at the chair"

    validate_error(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0.06, post_injection_iop_mmhg=17),
            injector,
        ),
        ApiErrorId.ERR_ENCOUNTER_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.attest_wastage(
            encounter["id"], f.attest_payload(attested_wasted_ml=0.21), witness
        ),
        ApiErrorId.ERR_ENCOUNTER_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.void_injection_encounter(
            encounter["id"], f.void_payload(void_reason="Voiding twice"), injector
        ),
        ApiErrorId.ERR_ENCOUNTER_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=encounter["id"]), billing
        ),
        ApiErrorId.ERR_ENCOUNTER_STATE_INVALID,
        409,
    )

    vial = breadth.read_vial(encounter["vial_id"])
    assert vial["status"] == "IN_STOCK"
    assert vial["reserved_for_encounter_id"] is None

    lot = breadth.read_lot(breadth.lot_ref["id"])
    assert_vial_counters(lot, vials_on_hand=5, vials_reserved=0, vials_administered=0)

    assert breadth.read_plan(breadth.plan_np["id"])["injections_administered"] == 0


def test_a_third_clinician_cannot_re_attest_an_attested_encounter(breadth, admin):
    """
    The witness signature is written once: a second, differently-identified attester
    is refused and the first attester's name stands.

    The PRD allows the edge only from one state: "Attestation moves the encounter
    `DOCUMENTED → ATTESTED` and carries a single input, `attested_wasted_ml` ... On
    success the acting clinician's identifier is written to
    `attested_by_clinician_id`. Attesting anything that is not `DOCUMENTED` — a `DRAFT`
    encounter, or one already attested — is `ERR_ENCOUNTER_STATE_INVALID` (HTTP 409)."
    The third clinician is not the injector, so the separation rule — "The attester
    must be a different clinician from the injector: an acting `X-User-ID` equal to the
    encounter's `clinician_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)"
    — is not what refuses this call.

    Design: Corner/state_machines/corner_attest_wastage_twice_is_rejected_on_the_second_call
    """
    attested = breadth.enc_np_attested
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_clinician_id"] == breadth.cl2["id"]

    third = validate_success(
        breadth.api.create_clinician(
            f.clinician_payload(
                full_name="Dr Priya Venkat",
                npi="2000000004",
                credential="MD",
                injection_privilege=True,
                max_injections_per_day=12,
            ),
            admin,
        ),
        201,
    )

    response = breadth.api.attest_wastage(
        attested["id"],
        f.attest_payload(attested_wasted_ml=0.21),
        specialist_headers(third["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ENCOUNTER_STATE_INVALID, 409)

    settled = breadth.read_encounter(attested["id"])
    assert settled["attested_by_clinician_id"] == breadth.cl2["id"]
