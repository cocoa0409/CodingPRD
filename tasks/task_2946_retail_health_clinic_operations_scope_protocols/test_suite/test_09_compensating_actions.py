"""Compensating actions must restore the quantity they disturbed, exactly."""
from test_helpers import (
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_CANCELLED,
    ASSIGNMENT_SCHEDULED,
    BILLING_INVOICED,
    BILLING_VOIDED,
    CLINIC_CLOSED,
    SERVICE_RAPID_STREP_TEST,
    SERVICE_URINALYSIS,
    ApiErrorId,
    closed_insured_visit,
    create_insured_patient,
    error_id,
    read_clinic,
    read_clinician,
    read_patient,
    read_physician,
    read_visit,
    staffed_clinic,
    staffing_assignment_payload,
    validate_error,
    validate_success,
)

VOID_SERVICES = [SERVICE_RAPID_STREP_TEST, SERVICE_URINALYSIS]


def _invoiced_visit_for_a_patient_who_started_at_zero(api):
    """Vera Void owes nothing, is seen, and is invoiced for 4526 cents of her own."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Vera Void", date_of_birth="1972-12-12",
        payer_name="BlueCo", member_id="M-8008", pcp_consent_on_file=False)
    env["patient"] = patient
    env["balance_before"] = read_patient(api, patient["id"])["outstanding_balance_cents"]
    env["bundle"] = closed_insured_visit(
        api, env, patient["id"], services_rendered=VOID_SERVICES,
        vitals={"temp_c": 37.2, "heart_rate_bpm": 84, "spo2_pct": 98})
    env["visit_id"] = env["bundle"]["visit_id"]
    env["balance_peak"] = read_patient(api, patient["id"])["outstanding_balance_cents"]
    return env


def test_checkout_lifts_the_balance_from_zero_to_the_patient_share(api):
    """A registered patient starts at 0 and the invoice puts 4526 cents on her.

    PRD: "A patient's `outstanding_balance_cents` is the sum of
    `patient_responsibility_cents` across that patient's visits whose `billing_status`
    is `INVOICED`, and it is recomputed from scratch on every billing transition that
    touches the patient."

    Design: Difficulty/compensating_invariant/charge_void_restores_patient_outstanding_balance_to_zero
    """
    env = _invoiced_visit_for_a_patient_who_started_at_zero(api)

    assert env["balance_before"] == 0
    assert env["bundle"]["visit"]["patient_responsibility_cents"] == 4526
    assert env["balance_peak"] == 4526
    assert env["bundle"]["visit"]["billing_status"] == BILLING_INVOICED


def test_the_void_returns_the_balance_to_exactly_its_pre_checkout_value(api):
    """4526 goes back to 0 with no rounding drift in either direction.

    PRD: "The patient's `outstanding_balance_cents` is therefore recomputed and returns
    to exactly its pre-checkout value, and the visit's `version` is incremented."

    Design: Difficulty/compensating_invariant/charge_void_restores_patient_outstanding_balance_to_zero
    """
    env = _invoiced_visit_for_a_patient_who_started_at_zero(api)

    voided = validate_success(
        api.charge_void(env["visit_id"], "Billed in error", env["admin"]))

    assert voided["billing_status"] == BILLING_VOIDED
    assert read_patient(api, env["patient"]["id"])["outstanding_balance_cents"] == 0


def test_the_voided_visit_keeps_its_priced_amounts_for_audit(api):
    """The invariant is restored by excluding the visit, not by zeroing its money.

    PRD: "The transition `INVOICED → VOIDED` deliberately **retains**
    `final_price_cents`, `patient_responsibility_cents` and `payer_responsibility_cents`
    on the visit for audit rather than clearing them; what changes is that a `VOIDED`
    visit no longer contributes to the patient's balance."

    Design: Difficulty/compensating_invariant/charge_void_restores_patient_outstanding_balance_to_zero
    """
    env = _invoiced_visit_for_a_patient_who_started_at_zero(api)
    validate_success(api.charge_void(env["visit_id"], "Billed in error", env["admin"]))

    visit = read_visit(api, env["visit_id"])

    assert visit["final_price_cents"] == 16200
    assert visit["patient_responsibility_cents"] == 4526
    assert visit["payer_responsibility_cents"] == 11674


def test_a_second_void_of_the_same_charge_is_refused(api):
    """VOIDED is the end of the billing dimension, so the void is not repeatable.

    PRD: "The visit's `billing_status` must be `INVOICED`, else
    `ERR_CHARGE_NOT_VOIDABLE`."

    Design: Difficulty/compensating_invariant/charge_void_restores_patient_outstanding_balance_to_zero
    """
    env = _invoiced_visit_for_a_patient_who_started_at_zero(api)
    validate_success(api.charge_void(env["visit_id"], "Billed in error", env["admin"]))

    response = api.charge_void(env["visit_id"], "Duplicate void attempt", env["admin"])

    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_VOIDABLE, 409)
    assert error_id(response) == "ERR_CHARGE_NOT_VOIDABLE"
    assert read_patient(api, env["patient"]["id"])["outstanding_balance_cents"] == 0


def _one_clinician_holding_two_shifts_under_one_physician(api):
    """Dr Rain supervises NP R One, who works a morning and an evening shift."""
    env = staffed_clinic(
        api, with_protocol=False, physician={"full_name": "Dr Rain"},
        clinician={"full_name": "NP R One"},
        assignment={"starts_at": "2026-08-01T00:00:00Z",
                    "ends_at": "2026-08-01T12:00:00Z"})
    env["load_zero"] = 0
    env["morning"] = env["assignment"]
    env["evening"] = validate_success(api.create_staffing_assignment(
        staffing_assignment_payload(
            env["clinic_id"], env["clinician_id"],
            starts_at="2026-08-01T12:00:00Z", ends_at="2026-08-01T20:00:00Z",
            pinned_supervising_physician_id=env["physician_id"]),
        env["admin"]), 201)
    return env


def test_two_shifts_for_one_clinician_count_once_in_the_supervision_headcount(api):
    """The physician's load is 1 while the clinician's assignment count is 2.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor
    and sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under
    the same physician count once, and `CANCELLED` or `COMPLETED` assignments are
    excluded entirely."

    Design: Difficulty/compensating_invariant/assignment_cancel_restores_physician_supervision_count
    """
    env = _one_clinician_holding_two_shifts_under_one_physician(api)

    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 1
    assert read_clinician(api, env["clinician_id"])["active_assignment_count"] == 2
    assert env["morning"]["status"] == ASSIGNMENT_ACTIVE
    assert env["evening"]["status"] == ASSIGNMENT_SCHEDULED


def test_cancelling_the_scheduled_shift_is_quiet_and_leaves_the_headcount_alone(api):
    """One of the two shifts goes, so the per-clinician counter drops but the load holds.

    PRD: "Cancelling a `SCHEDULED` assignment is quiet: the row moves
    `SCHEDULED → CANCELLED`, the pinned physician's `current_supervised_count` is
    recomputed — dropping by 1 when that was the physician's only assignment for that
    clinician — and the clinician's `active_assignment_count` is recomputed."

    Design: Difficulty/compensating_invariant/assignment_cancel_restores_physician_supervision_count
    """
    env = _one_clinician_holding_two_shifts_under_one_physician(api)

    cancelled = validate_success(api.cancel_staffing_assignment(
        env["evening"]["id"], env["admin"], cancel_reason="Shift dropped"))

    assert cancelled["status"] == ASSIGNMENT_CANCELLED
    assert read_clinician(api, env["clinician_id"])["active_assignment_count"] == 1
    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 1


def test_cancelling_the_last_shift_restores_the_headcount_to_zero(api):
    """With both rows CANCELLED the physician supervises nobody and the counters unwind.

    PRD: "This counting rule is what makes a schedule-then-cancel pair conserve the
    number exactly."

    Design: Difficulty/compensating_invariant/assignment_cancel_restores_physician_supervision_count
    """
    env = _one_clinician_holding_two_shifts_under_one_physician(api)
    validate_success(api.cancel_staffing_assignment(
        env["evening"]["id"], env["admin"], cancel_reason="Shift dropped"))

    morning = validate_success(api.cancel_staffing_assignment(
        env["morning"]["id"], env["admin"], cancel_reason="Site closed early"))

    assert morning["status"] == ASSIGNMENT_CANCELLED
    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 0
    assert read_clinician(api, env["clinician_id"])["active_assignment_count"] == 0


def test_cancelling_the_active_shift_empties_the_floor_and_closes_the_clinic(api):
    """Losing the only ACTIVE assignment drives the on-duty count to 0 and shuts the site.

    PRD: "Hop one lowers the clinic's `on_duty_clinician_count` by 1. Hop two re-derives
    `open_status` from the new count, moving `OPEN → LIMITED` when the count is above 0
    but below `min_clinicians_required`, and `OPEN → CLOSED` or `LIMITED → CLOSED` when
    it reaches 0."

    Design: Difficulty/compensating_invariant/assignment_cancel_restores_physician_supervision_count
    """
    env = _one_clinician_holding_two_shifts_under_one_physician(api)
    validate_success(api.cancel_staffing_assignment(
        env["evening"]["id"], env["admin"], cancel_reason="Shift dropped"))

    validate_success(api.cancel_staffing_assignment(
        env["morning"]["id"], env["admin"], cancel_reason="Site closed early"))

    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["on_duty_clinician_count"] == 0
    assert clinic["open_status"] == CLINIC_CLOSED
