"""Composite setup helpers.

Every helper here builds its entities through declared endpoints only -- nothing
in the suite assumes a pre-seeded database. Helpers are deliberately phased: a
helper performs one recognisable step of a workflow and returns the resource it
produced, so that reusing it never undoes a precondition an earlier call
established. Where a whole workflow shortcut is offered (an authorized case, an
interpreted study, a verified vial) the docstring names every side effect it
leaves behind.

Success-path setup goes through ``get_success_data``, which accepts any 2xx and
raises a readable ``Setup step failed`` message otherwise. Tests that assert a
rejection call the client directly instead of using these helpers.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories, test_users
from .constants import (
    CLOCK_DEFAULT,
    CRITERION_CT_OPACIFICATION,
    CRITERION_FAILED_INCS,
    CRITERION_SNOT22_GE_20,
    DECISION_APPROVED,
    DEVICE_TYPE_HEARING_AID,
    DILUTION_BLUE,
    EAR_LEFT,
    ITEM_TYPE_ALLERGEN_CONCENTRATE,
    ITEM_TYPE_HEARING_AID,
    LATERALITY_LEFT,
    METHOD_SKIN_PRICK,
    PANEL_MOLD_12,
    PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
    SINUS_MAXILLARY,
    STUDY_AUDIOMETRY,
    STUDY_SLEEP_HSAT,
    THERAPY_INCS,
    USER_ENT_1,
    VENUE_IN_OFFICE_SUITE,
    device_serial as build_device_serial,
    lot_number as build_lot_number,
    mrn as build_mrn,
    scope_serial as build_scope_serial,
)

# Default expiry instants, chosen to sit comfortably after the logical clock of
# 2026-08-01T00:00:00Z and inside the three-hundred-and-sixty-five-day ceiling
# that PRD 3.5 places on a compounded vial.
VIAL_EXPIRY_DEFAULT = "2026-12-01T00:00:00Z"
LOT_EXPIRY_DEFAULT = "2027-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def set_clock(api, current_utc: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Move the logical clock and return the instant the service echoes."""
    response = api.set_clock(current_utc, headers or test_users.ADMIN_1)
    data = get_success_data(response)
    return data["current_utc"]


def reset_clock(api, headers: Optional[Dict[str, str]] = None) -> str:
    """Park the logical clock back on its unset reading of PRD 2.5."""
    return set_clock(api, CLOCK_DEFAULT, headers)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def read_policy(api, policy_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_payer_policy(policy_id, headers or test_users.ADMIN_1))


def read_patient(api, patient_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_patient(patient_id, headers or test_users.ADMIN_1))


def read_order(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_allergy_test_order(order_id, headers or test_users.ADMIN_1)
    )


def read_vial(api, vial_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_immunotherapy_vial(vial_id, headers or test_users.ADMIN_1)
    )


def read_dose(api, dose_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_immunotherapy_dose(dose_id, headers or test_users.ADMIN_1)
    )


def read_case(api, case_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_sinuplasty_case(case_id, headers or test_users.ADMIN_1))


def read_study(api, study_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_diagnostic_study(study_id, headers or test_users.ADMIN_1)
    )


def read_dispense(api, dispense_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_device_dispense(dispense_id, headers or test_users.ADMIN_1)
    )


def read_scope(api, scope_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_endoscope(scope_id, headers or test_users.ADMIN_1))


def read_lot(api, lot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_supply_lot(lot_id, headers or test_users.ADMIN_1))


def read_block(api, block_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_surgery_center_block(block_id, headers or test_users.ADMIN_1)
    )


def read_booking(api, booking_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_procedure_booking(booking_id, headers or test_users.ADMIN_1)
    )


def patient_version(api, patient_id: str) -> int:
    """Re-read a patient's ``version`` immediately before pinning it.

    PRD 2.7 makes ``expected_patient_version`` mandatory on compounding, so a
    helper that pins a remembered value would go stale the moment any cascade
    touched the chart. Every pin in the suite is read fresh through here.
    """
    return read_patient(api, patient_id)["version"]


def study_version(api, study_id: str) -> int:
    """Re-read a study's ``version`` immediately before pinning it (PRD 2.7)."""
    return read_study(api, study_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: payer plans and patient charts
# ---------------------------------------------------------------------------
def create_policy(
    api,
    plan_code: str = "PLAN-2999",
    payer_name: str = "Northshore Health Plan",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Register a payer plan. Omitted terms take the defaults of PRD 3.1."""
    payload = factories.payer_policy_payload(
        plan_code=plan_code, payer_name=payer_name, **overrides
    )
    return get_success_data(
        api.create_payer_policy(payload, headers or test_users.ADMIN_1), 201
    )


def create_patient(
    api,
    policy_id: str,
    patient_mrn: Optional[str] = None,
    full_name: str = "Rowan Ellery Castellane",
    date_of_birth: str = "1990-05-20",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Register a patient chart under a plan."""
    payload = factories.patient_payload(
        policy_id,
        mrn=patient_mrn if patient_mrn is not None else build_mrn(10001),
        full_name=full_name,
        date_of_birth=date_of_birth,
        **overrides
    )
    return get_success_data(api.create_patient(payload, headers or test_users.ADMIN_1), 201)


def policy_with_patient(
    api,
    plan_code: str = "PLAN-2999",
    patient_mrn: Optional[str] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    patient_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register one plan and one patient under it.

    Returns ``{"policy": ..., "patient": ...}`` with both resources exactly as
    the service minted them.
    """
    policy = create_policy(api, plan_code=plan_code, **(policy_overrides or {}))
    patient = create_patient(
        api, policy["id"], patient_mrn=patient_mrn, **(patient_overrides or {})
    )
    return {"policy": policy, "patient": patient}


def patch_patient(
    api, patient_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Update a patient's mutable chart fields, re-deriving risk and tier."""
    payload = factories.patient_patch_payload(**overrides)
    return get_success_data(
        api.patch_patient(patient_id, payload, headers or test_users.ADMIN_1)
    )


def patch_policy(
    api, policy_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Amend a payer plan, which bumps its ``version`` by one."""
    payload = factories.payer_policy_patch_payload(**overrides)
    return get_success_data(
        api.patch_payer_policy(policy_id, payload, headers or test_users.ADMIN_1)
    )


# ---------------------------------------------------------------------------
# Tier 2: allergy panels
# ---------------------------------------------------------------------------
def create_order(
    api,
    patient_id: str,
    panel_code: str = PANEL_MOLD_12,
    method: str = METHOD_SKIN_PRICK,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Order an allergy panel. The order starts in ORDERED with zero billing."""
    payload = factories.allergy_test_order_payload(
        patient_id, panel_code=panel_code, method=method
    )
    return get_success_data(
        api.create_allergy_test_order(payload, headers or test_users.NURSE_1), 201
    )


def administer_order(
    api, order_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Administer a skin panel, stamping ``administered_at`` from the clock."""
    return get_success_data(
        api.administer_allergy_test_order(order_id, headers or test_users.NURSE_1)
    )


def convert_order_to_serum(
    api, order_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Move an order onto the serum arm, rewriting its method and billing."""
    return get_success_data(
        api.convert_allergy_test_order_to_serum(order_id, headers or test_users.NURSE_1)
    )


def record_reading(
    api,
    order_id: str,
    positive_antigen_count: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Record a panel reading, billing the panel or aborting it."""
    payload = factories.allergy_reading_payload(positive_antigen_count, **overrides)
    return get_success_data(
        api.record_allergy_test_reading(order_id, payload, headers or test_users.NURSE_1)
    )


def administered_order(
    api,
    patient_id: str,
    panel_code: str = PANEL_MOLD_12,
    method: str = METHOD_SKIN_PRICK,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Order a skin panel and administer it in one step.

    Side effects left behind: the order sits in ADMINISTERED with
    ``administered_at`` stamped from the clock as it stood at the second call.
    """
    order = create_order(api, patient_id, panel_code=panel_code, method=method, headers=headers)
    return administer_order(api, order["id"], headers=headers)


def read_panel(
    api,
    patient_id: str,
    panel_code: str = PANEL_MOLD_12,
    method: str = METHOD_SKIN_PRICK,
    positive_antigen_count: int = 0,
    observation_minutes: int = 30,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Carry a skin panel from ORDERED all the way to READ.

    The caller must have advanced the clock by at least the order's observation
    requirement before the reading, which is why ``observation_minutes`` is a
    parameter rather than an assumption: pass the value the order reports and
    move the clock yourself, or use the two phases separately.
    """
    order = administered_order(
        api, patient_id, panel_code=panel_code, method=method, headers=headers
    )
    assert order["observation_required_minutes"] == observation_minutes, (
        "this shortcut expects an observation requirement of {0} minutes, but the "
        "order reports {1}".format(observation_minutes, order["observation_required_minutes"])
    )
    return record_reading(
        api, order["id"], positive_antigen_count, headers=headers
    )


def record_reaction(
    api,
    systemic_grade: int,
    onset_minutes: int,
    order_id: Optional[str] = None,
    dose_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Record a reaction event against exactly one parent (PRD 3.4)."""
    assert (order_id is None) != (dose_id is None), (
        "a reaction event carries exactly one parent reference"
    )
    if order_id is not None:
        overrides["allergy_test_order_id"] = order_id
    else:
        overrides["immunotherapy_dose_id"] = dose_id
    payload = factories.reaction_event_payload(systemic_grade, onset_minutes, **overrides)
    return get_success_data(
        api.create_reaction_event(payload, headers or test_users.NURSE_1), 201
    )


# ---------------------------------------------------------------------------
# Tier 2: supply lots and endoscopes
# ---------------------------------------------------------------------------
def create_lot(
    api,
    item_type: str = ITEM_TYPE_ALLERGEN_CONCENTRATE,
    lot_no: Optional[str] = None,
    quantity_received: int = 10,
    expires_at: str = LOT_EXPIRY_DEFAULT,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Receive a lot into inventory with every bucket at its opening value."""
    payload = factories.supply_lot_payload(
        expires_at,
        item_type=item_type,
        lot_number=lot_no if lot_no is not None else build_lot_number(1),
        quantity_received=quantity_received,
        **overrides
    )
    return get_success_data(api.create_supply_lot(payload, headers or test_users.ADMIN_1), 201)


def adjust_lot(
    api,
    lot_id: str,
    reason: str,
    quantity: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Receive extra units, write units off, or quarantine the remainder.

    ``quantity`` is required for RECEIVE and WRITE_OFF and is omitted entirely
    for QUARANTINE, which moves the whole available remainder.
    """
    if quantity is None:
        payload: Dict[str, Any] = {"reason": reason}
    else:
        payload = factories.lot_adjustment_payload(reason=reason, quantity=quantity)
    return get_success_data(
        api.adjust_supply_lot(lot_id, payload, headers or test_users.ADMIN_1)
    )


def register_scope(
    api,
    serial: Optional[str] = None,
    model: str = "Olympus ENF-VH",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register an endoscope. It starts READY with no reprocessing history."""
    payload = factories.endoscope_payload(
        serial_number=serial if serial is not None else build_scope_serial(1), model=model
    )
    return get_success_data(api.create_endoscope(payload, headers or test_users.ADMIN_1), 201)


def start_reprocessing(
    api, scope_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Open a disinfection run, recording the technician who owns it."""
    return get_success_data(
        api.start_reprocessing(scope_id, headers or test_users.TECH_1)
    )


def complete_reprocessing(
    api,
    scope_id: str,
    leak_test_passed: bool = True,
    mec_test_passed: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Close a disinfection run. The same technician who started it must submit."""
    payload = factories.reprocessing_completion_payload(leak_test_passed)
    if mec_test_passed is not None:
        payload["mec_test_passed"] = mec_test_passed
    return get_success_data(
        api.complete_reprocessing(scope_id, payload, headers or test_users.TECH_1)
    )


def reprocess_scope(
    api,
    scope_id: str,
    leak_test_passed: bool = True,
    mec_test_passed: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run one disinfection cycle from start to completion.

    Side effects left behind on a passing run: the scope is READY, its
    ``cycle_count`` has risen by one, ``last_reprocessed_at`` is stamped from the
    clock and ``hld_expires_at`` sits one hundred sixty-eight hours later.
    """
    tech = headers or test_users.TECH_1
    start_reprocessing(api, scope_id, headers=tech)
    return complete_reprocessing(
        api,
        scope_id,
        leak_test_passed=leak_test_passed,
        mec_test_passed=mec_test_passed,
        headers=tech,
    )


# ---------------------------------------------------------------------------
# Tier 3: immunotherapy vials and doses
# ---------------------------------------------------------------------------
def mix_vial(
    api,
    patient: Dict[str, Any],
    lot_id: str,
    dilution_code: str = DILUTION_BLUE,
    expires_at: str = VIAL_EXPIRY_DEFAULT,
    volume_ml_initial: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Compound a vial for a patient.

    The patient's ``version`` is re-read at call time unless the caller pins one
    deliberately, and ``label_text`` is derived from the patient's ``mrn``, the
    dilution code and the expiry date. Compounding supersedes any vial of the
    same patient already sitting in LABEL_VERIFIED or IN_USE, so calling this
    twice for one patient discards the first vial by design.
    """
    version = (
        expected_version
        if expected_version is not None
        else patient_version(api, patient["id"])
    )
    overrides: Dict[str, Any] = {"dilution_code": dilution_code}
    if volume_ml_initial is not None:
        overrides["volume_ml_initial"] = volume_ml_initial
    payload = factories.immunotherapy_vial_payload(
        patient["id"], lot_id, patient["mrn"], version, expires_at, **overrides
    )
    return get_success_data(
        api.create_immunotherapy_vial(payload, headers or test_users.NURSE_1), 201
    )


def verify_vial(
    api, vial: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Verify a vial label with a second nurse, activating it for dosing.

    The default actor is the second nurse precisely because PRD 2.9 forbids the
    nurse who compounded the vial from verifying it.
    """
    payload = factories.label_verification_payload(vial["label_text"])
    return get_success_data(
        api.verify_immunotherapy_vial_label(
            vial["id"], payload, headers or test_users.NURSE_2
        )
    )


def verified_vial(
    api,
    patient: Dict[str, Any],
    lot_id: str,
    dilution_code: str = DILUTION_BLUE,
    expires_at: str = VIAL_EXPIRY_DEFAULT,
    volume_ml_initial: Optional[float] = None,
    mixer: Optional[Dict[str, str]] = None,
    verifier: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compound a vial and verify its label.

    Side effects left behind: the vial is LABEL_VERIFIED with its full initial
    volume remaining, and the patient's ``immunotherapy_status`` has moved to
    BUILD_UP or MAINTENANCE according to the escalation step.
    """
    vial = mix_vial(
        api,
        patient,
        lot_id,
        dilution_code=dilution_code,
        expires_at=expires_at,
        volume_ml_initial=volume_ml_initial,
        headers=mixer or test_users.NURSE_1,
    )
    return verify_vial(api, vial, headers=verifier or test_users.NURSE_2)


def administer_dose(
    api,
    vial_id: str,
    supervising_user_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draw the scheduled volume from a verified vial."""
    overrides: Dict[str, Any] = {}
    if supervising_user_id is not None:
        overrides["supervising_user_id"] = supervising_user_id
    payload = factories.immunotherapy_dose_payload(vial_id, **overrides)
    return get_success_data(
        api.create_immunotherapy_dose(payload, headers or test_users.NURSE_1), 201
    )


def clear_dose(api, dose_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Clear a dose's observation window, advancing the patient's step."""
    return get_success_data(
        api.clear_dose_observation(dose_id, headers or test_users.NURSE_1)
    )


def void_dose(
    api, dose_id: str, void_reason: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Void a dose inside its window, returning the volume to the vial."""
    payload = factories.dose_void_payload(void_reason=void_reason)
    return get_success_data(
        api.void_immunotherapy_dose(dose_id, payload, headers or test_users.NURSE_1)
    )


def discard_vial(
    api, vial_id: str, discard_reason: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Discard a vial, writing its remaining volume off to waste."""
    payload = factories.vial_discard_payload(discard_reason=discard_reason)
    return get_success_data(
        api.discard_immunotherapy_vial(vial_id, payload, headers or test_users.NURSE_1)
    )


def immunotherapy_ready_patient(
    api,
    plan_code: str = "PLAN-2999",
    patient_mrn: Optional[str] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    patient_overrides: Optional[Dict[str, Any]] = None,
    dilution_code: str = DILUTION_BLUE,
    volume_ml_initial: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a plan, a patient, an allergen-concentrate lot and a verified vial.

    Returns ``{"policy", "patient", "lot", "vial"}``. The patient is left at
    escalation step 1 with ``immunotherapy_status`` BUILD_UP, so the next dose
    draws 0.05 mL from a BLUE_1_100 vial.
    """
    base = policy_with_patient(
        api,
        plan_code=plan_code,
        patient_mrn=patient_mrn,
        policy_overrides=policy_overrides,
        patient_overrides=patient_overrides,
    )
    lot = create_lot(api, item_type=ITEM_TYPE_ALLERGEN_CONCENTRATE)
    vial = verified_vial(
        api,
        base["patient"],
        lot["id"],
        dilution_code=dilution_code,
        volume_ml_initial=volume_ml_initial,
    )
    base["lot"] = lot
    base["vial"] = vial
    # Label verification is a mutation of the patient row (PRD 3.5: "the
    # patient's `immunotherapy_status` leaves `NONE` for the first time"), so the
    # chart snapshot taken at registration is stale by now. Re-read it, otherwise
    # callers see the pre-verification `NONE` and a pre-compounding `version`.
    base["patient"] = read_patient(api, base["patient"]["id"])
    return base


# ---------------------------------------------------------------------------
# Tier 3: sinuplasty cases
# ---------------------------------------------------------------------------
def create_case(
    api,
    patient_id: str,
    laterality: str = LATERALITY_LEFT,
    sinuses: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a case. Its evaluation variant is fixed by the plan at this instant."""
    payload = factories.sinuplasty_case_payload(
        patient_id,
        laterality=laterality,
        sinuses=sinuses if sinuses is not None else [SINUS_MAXILLARY],
    )
    return get_success_data(
        api.create_sinuplasty_case(payload, headers or test_users.ENT_1), 201
    )


def document_case(
    api,
    case_id: str,
    therapies: Optional[List[Dict[str, str]]] = None,
    criteria: Optional[List[str]] = None,
    ct_study_date: Optional[str] = "2026-07-01",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Attach the management history and evaluate candidacy in one call."""
    payload = factories.documentation_payload(
        documented_therapies=therapies,
        documented_criteria_codes=criteria,
        ct_study_date=ct_study_date,
    )
    return get_success_data(
        api.document_sinuplasty_case(case_id, payload, headers or test_users.ENT_1)
    )


def submit_case(
    api, case_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Submit or resubmit a case, pinning the plan version at this instant."""
    return get_success_data(
        api.submit_authorization(case_id, headers or test_users.LIAISON_1)
    )


def decide_case(
    api,
    case_id: str,
    decision: str,
    payer_reference: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record the payer's decision. The decider must differ from the submitter,
    which is why the default actor is the second payer liaison."""
    payload = factories.payer_decision_payload(payer_reference, decision=decision)
    return get_success_data(
        api.record_payer_decision(case_id, payload, headers or test_users.LIAISON_2)
    )


# A pair of adjacent courses spanning twenty-eight contiguous days: the first
# runs from the first to the fourteenth of June inclusive and the second picks up
# the very next day, so the two merge into a single interval under PRD 3.6.
ADJACENT_TWENTY_EIGHT_DAY_COURSES = [
    factories.therapy_course(THERAPY_INCS, "2026-06-01", "2026-06-14"),
    factories.therapy_course(THERAPY_INCS, "2026-06-15", "2026-06-28"),
]

# The three criteria that a strict plan admits without needing a therapy of a
# particular code: an endoscopy finding, a SNOT-22 score, and a failed course of
# intranasal corticosteroids backed by the INCS therapies above.
STRICT_ADMISSIBLE_CRITERIA = [
    CRITERION_SNOT22_GE_20,
    CRITERION_CT_OPACIFICATION,
    CRITERION_FAILED_INCS,
]


def eligible_documented_case(
    api,
    patient_id: str,
    laterality: str = LATERALITY_LEFT,
    sinuses: Optional[List[str]] = None,
    ct_study_date: str = "2026-07-01",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a case and document it so that candidacy lands on ELIGIBLE.

    The documentation supplies twenty-eight contiguous management days and three
    admissible criteria, which clears the default thresholds of PRD 3.1 under
    either evaluation variant.
    """
    case = create_case(
        api, patient_id, laterality=laterality, sinuses=sinuses, headers=headers
    )
    return document_case(
        api,
        case["id"],
        therapies=list(ADJACENT_TWENTY_EIGHT_DAY_COURSES),
        criteria=list(STRICT_ADMISSIBLE_CRITERIA),
        ct_study_date=ct_study_date,
        headers=headers,
    )


def authorized_case(
    api,
    patient_id: str,
    laterality: str = LATERALITY_LEFT,
    sinuses: Optional[List[str]] = None,
    payer_reference: str = "PA-77001",
    ct_study_date: str = "2026-07-01",
) -> Dict[str, Any]:
    """Carry a case from DRAFT to AUTHORIZED.

    Side effects left behind: ``submitted_by_user_id`` names the first payer
    liaison, ``pinned_policy_version`` holds the plan version as it stood at
    submission, ``authorized_device_count`` is the planned count capped by the
    plan's balloon ceiling, and ``auth_expires_at`` sits the plan's validity
    window after the clock as it stood at the decision.
    """
    documented = eligible_documented_case(
        api, patient_id, laterality=laterality, sinuses=sinuses, ct_study_date=ct_study_date
    )
    submit_case(api, documented["id"])
    return decide_case(api, documented["id"], DECISION_APPROVED, payer_reference)


# ---------------------------------------------------------------------------
# Tier 3: diagnostic studies and device dispenses
# ---------------------------------------------------------------------------
def create_study(
    api,
    patient_id: str,
    study_type: str = STUDY_AUDIOMETRY,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Order a study. It starts ORDERED with every metric null."""
    payload = factories.diagnostic_study_payload(patient_id, study_type=study_type)
    return get_success_data(
        api.create_diagnostic_study(payload, headers or test_users.ENT_1), 201
    )


def record_audiometry_results(
    api,
    study_id: str,
    pta_db_hl: float,
    word_recognition_pct: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record the metric set an audiometry demands, and nothing else."""
    payload = factories.audiometry_results_payload(pta_db_hl, word_recognition_pct)
    return get_success_data(
        api.record_study_results(study_id, payload, headers or test_users.AUD_1)
    )


def record_sleep_results(
    api, study_id: str, ahi: float, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Record the metric set a sleep study demands, and nothing else."""
    payload = factories.sleep_results_payload(ahi)
    return get_success_data(
        api.record_study_results(study_id, payload, headers or test_users.AUD_1)
    )


def interpret_study(
    api, study_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Interpret a performed study, emitting its recommendation.

    The default actor is the second audiologist because PRD 2.9 forbids the
    audiologist who performed the study from interpreting it.
    """
    return get_success_data(
        api.interpret_diagnostic_study(study_id, headers or test_users.AUD_2)
    )


def interpreted_audiometry(
    api,
    patient_id: str,
    pta_db_hl: float = 62.0,
    word_recognition_pct: float = 74.0,
    performer: Optional[Dict[str, str]] = None,
    interpreter: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Carry an audiometry from ORDERED to INTERPRETED.

    Side effects left behind: ``version`` has reached 3, ``performed_at`` and
    ``performed_by_user_id`` name the first audiologist, and the recommendation
    follows from the pure-tone average.
    """
    study = create_study(api, patient_id, study_type=STUDY_AUDIOMETRY)
    record_audiometry_results(
        api,
        study["id"],
        pta_db_hl,
        word_recognition_pct,
        headers=performer or test_users.AUD_1,
    )
    return interpret_study(api, study["id"], headers=interpreter or test_users.AUD_2)


def interpreted_sleep_study(
    api,
    patient_id: str,
    ahi: float,
    study_type: str = STUDY_SLEEP_HSAT,
    performer: Optional[Dict[str, str]] = None,
    interpreter: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Carry a sleep study from ORDERED to INTERPRETED."""
    study = create_study(api, patient_id, study_type=study_type)
    record_sleep_results(api, study["id"], ahi, headers=performer or test_users.AUD_1)
    return interpret_study(api, study["id"], headers=interpreter or test_users.AUD_2)


def create_dispense(
    api,
    study_id: str,
    lot_id: str,
    device_type: str = DEVICE_TYPE_HEARING_AID,
    serial: Optional[str] = None,
    price_cents: int = 289000,
    ear: str = EAR_LEFT,
    headers: Optional[Dict[str, str]] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Dispense a device against an interpreted study.

    The study's ``version`` is re-read at call time unless the caller pins one
    deliberately, because PRD 2.7 makes ``expected_study_version`` mandatory.
    """
    version = (
        expected_version if expected_version is not None else study_version(api, study_id)
    )
    payload = factories.device_dispense_payload(
        study_id,
        lot_id,
        version,
        device_type=device_type,
        device_serial=serial if serial is not None else build_device_serial("HA", 100001),
        price_cents=price_cents,
        ear=ear,
    )
    return get_success_data(
        api.create_device_dispense(payload, headers or test_users.AUD_1), 201
    )


def adjust_dispense(
    api,
    dispense_id: str,
    adjustment_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record one fitting adjustment during the trial."""
    overrides: Dict[str, Any] = {}
    if adjustment_note is not None:
        overrides["adjustment_note"] = adjustment_note
    payload = factories.adjustment_payload(**overrides)
    return get_success_data(
        api.adjust_device_dispense(dispense_id, headers or test_users.AUD_1, payload)
    )


def return_dispense(
    api, dispense_id: str, return_reason: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Accept a device back, computing the refund under the applicable variant."""
    payload = factories.trial_return_payload(return_reason=return_reason)
    return get_success_data(
        api.return_device_dispense(dispense_id, payload, headers or test_users.AUD_1)
    )


def settle_refund(
    api, dispense_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Settle a pending refund. The settler must differ from the dispenser, so
    the default actor is a practice administrator distinct from the audiologist."""
    return get_success_data(
        api.settle_device_refund(dispense_id, headers or test_users.ADMIN_1)
    )


def fitted_hearing_aid(
    api,
    plan_code: str = "PLAN-2999",
    patient_mrn: Optional[str] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    price_cents: int = 289000,
    quantity_received: int = 5,
    pta_db_hl: float = 62.0,
) -> Dict[str, Any]:
    """Build a plan, a patient, a hearing-aid lot, an interpreted audiometry and
    a fitted dispense.

    Returns ``{"policy", "patient", "lot", "study", "dispense"}``. The dispense
    sits in FITTED and INVOICED with its trial window frozen at creation, and the
    lot has given up one unit to ``quantity_consumed``.
    """
    base = policy_with_patient(
        api, plan_code=plan_code, patient_mrn=patient_mrn, policy_overrides=policy_overrides
    )
    lot = create_lot(
        api,
        item_type=ITEM_TYPE_HEARING_AID,
        lot_no=build_lot_number(2),
        quantity_received=quantity_received,
    )
    study = interpreted_audiometry(api, base["patient"]["id"], pta_db_hl=pta_db_hl)
    dispense = create_dispense(
        api, study["id"], lot["id"], price_cents=price_cents
    )
    base["lot"] = lot
    base["study"] = study
    base["dispense"] = dispense
    return base


# ---------------------------------------------------------------------------
# Tier 4: surgery-center blocks and procedure bookings
# ---------------------------------------------------------------------------
def publish_block(
    api,
    block_start_at: str,
    block_end_at: str,
    max_concurrent_cases: Optional[int] = None,
    overnight_capable: Optional[bool] = None,
    center_name: str = "Lakeside Surgery Center",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Publish a block over a half-open window with a concurrency ceiling."""
    overrides: Dict[str, Any] = {"center_name": center_name}
    if max_concurrent_cases is not None:
        overrides["max_concurrent_cases"] = max_concurrent_cases
    if overnight_capable is not None:
        overrides["overnight_capable"] = overnight_capable
    payload = factories.surgery_center_block_payload(
        block_start_at, block_end_at, **overrides
    )
    return get_success_data(
        api.create_surgery_center_block(payload, headers or test_users.ADMIN_1), 201
    )


def close_block(
    api, block_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Close a block to further bookings. Scheduled cases keep their slots."""
    return get_success_data(
        api.close_surgery_center_block(block_id, headers or test_users.ADMIN_1)
    )


def booking_payload(
    patient_id: str,
    start_at: str,
    end_at: str,
    physician_user_id: str = USER_ENT_1,
    procedure_type: str = PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
    venue: str = VENUE_IN_OFFICE_SUITE,
    **overrides: Any
) -> Dict[str, Any]:
    """Assemble a booking body without sending it.

    Tests that expect a rejection use this and call the client directly, so that
    the failing request is visible at the call site rather than buried in a
    helper.
    """
    return factories.procedure_booking_payload(
        patient_id,
        start_at,
        end_at,
        physician_user_id,
        procedure_type=procedure_type,
        venue=venue,
        **overrides
    )


def create_booking(
    api,
    patient_id: str,
    start_at: str,
    end_at: str,
    physician_user_id: str = USER_ENT_1,
    procedure_type: str = PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
    venue: str = VENUE_IN_OFFICE_SUITE,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Schedule a procedure, reserving every resource the booking claims."""
    payload = booking_payload(
        patient_id,
        start_at,
        end_at,
        physician_user_id=physician_user_id,
        procedure_type=procedure_type,
        venue=venue,
        **overrides
    )
    return get_success_data(
        api.create_procedure_booking(payload, headers or test_users.ADMIN_1), 201
    )


def start_booking(
    api,
    booking_id: str,
    attending_physician_user_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Start a booking. The actor must be the booking's own physician, so the
    caller passes the headers of whoever was named ``physician_user_id``."""
    overrides: Dict[str, Any] = {}
    if attending_physician_user_id is not None:
        overrides["attending_physician_user_id"] = attending_physician_user_id
    payload = factories.booking_start_payload(**overrides)
    return get_success_data(
        api.start_procedure_booking(booking_id, headers or test_users.ENT_1, payload)
    )


def complete_booking(
    api,
    booking_id: str,
    devices_used_count: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Complete a booking, converting reserved units into consumed units."""
    payload = factories.booking_completion_payload(devices_used_count)
    return get_success_data(
        api.complete_procedure_booking(booking_id, payload, headers or test_users.ENT_1)
    )


def cancel_booking(
    api, booking_id: str, cancel_reason: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Cancel a scheduled booking, releasing every resource it held."""
    payload = factories.booking_cancel_payload(cancel_reason=cancel_reason)
    return get_success_data(
        api.cancel_procedure_booking(booking_id, payload, headers or test_users.ADMIN_1)
    )


def soil_scope(
    api,
    scope_id: str,
    patient_id: str,
    start_at: str = "2026-08-01T00:00:00Z",
    end_at: str = "2026-08-01T00:30:00Z",
    physician_headers: Optional[Dict[str, str]] = None,
    physician_user_id: str = USER_ENT_1,
) -> Dict[str, Any]:
    """Drive a scope from READY to SOILED through one diagnostic endoscopy.

    Side effects left behind: a completed booking exists over the interval given,
    the scope's ``last_used_by_user_id`` names the booking's physician and its
    ``hld_expires_at`` has been cleared. Returns the scope as it stands after
    completion.
    """
    booking = create_booking(
        api,
        patient_id,
        start_at,
        end_at,
        physician_user_id=physician_user_id,
        procedure_type=PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
        venue=VENUE_IN_OFFICE_SUITE,
        endoscope_asset_id=scope_id,
    )
    start_booking(api, booking["id"], headers=physician_headers or test_users.ENT_1)
    complete_booking(
        api, booking["id"], devices_used_count=0, headers=physician_headers or test_users.ENT_1
    )
    return read_scope(api, scope_id)
