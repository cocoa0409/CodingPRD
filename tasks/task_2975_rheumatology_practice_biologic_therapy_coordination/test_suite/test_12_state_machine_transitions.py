"""Corner-case suite — section `state_machines`.

Visit, InfusionAppointment, TherapyEpisode and AssistanceEnrollment state
machines: initial states, valid transitions, precondition enforcement,
non-idempotent replays, terminal-state lockdown and the denormalized
side effects a single transition writes.

Every test in this module translates exactly one instance of the
`state_machines` section of SCAFFOLD_CORNER_DESIGN.yaml.
"""
import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_client, assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import COUNSELOR_BETA_USER_ID, make_benefits_counselor_headers


# ==========================================================================
# visit_initial_state_is_scheduled_on_creation
# ==========================================================================
def test_new_visit_is_born_scheduled_with_a_server_derived_end_instant():
    """A freshly booked `NEW` visit is `SCHEDULED` and its `visit_end_datetime`
    is the start advanced by the visit type's own slot length, never a client
    input.

    PRD: "A newly booked visit's `status` is `SCHEDULED`."
    PRD: "A `NEW` visit occupies a full hour, a `FOLLOW_UP` visit occupies half an hour, and an `URGENT` visit occupies three quarters of an hour; the server writes `visit_end_datetime` as the visit's start advanced by that many minutes."
    Design: Corner/state_machines/visit_initial_state_is_scheduled_on_creation
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()

    visit = validate_success(
        api_client.create_visit(
            factories.create_visit_payload(
                scenario.patient_id,
                scenario.rheumatologist_id,
                visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
                visit_type="NEW",
            ),
            scenario.rheum_headers,
        ),
        201,
    )

    assertions.assert_visit(visit)
    assert visit["status"] == "SCHEDULED", f"a new visit is SCHEDULED, got {visit['status']!r}"
    assertions.assert_instant_equals(
        visit["visit_end_datetime"],
        constants.instant(2026, 8, 3, 15, 0, 0),
        "visit_end_datetime",
    )
    assert visit["version"] == 1, "a freshly created resource carries version 1"


def test_new_visit_carries_no_score_and_projects_nothing_onto_the_patient():
    """Booking writes no scoring figures on the visit and leaves the patient's
    treat-to-target verdict at its floor.

    PRD: "All of these fields are null on a visit until it is scored."
    PRD: "`target_status` follows from the category: `AT_TARGET` when the winning category is `REMISSION` or `LOW`, `NOT_AT_TARGET` when it is `MODERATE` or `HIGH`, and `UNASSESSED` when the patient has no scored visit at all."
    Design: Corner/state_machines/visit_initial_state_is_scheduled_on_creation
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()

    visit = validate_success(
        api_client.create_visit(
            factories.create_visit_payload(
                scenario.patient_id,
                scenario.rheumatologist_id,
                visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
                visit_type="NEW",
            ),
            scenario.rheum_headers,
        ),
        201,
    )

    for field in ("activity_score", "activity_category", "escalation_recommendation", "scored_at"):
        assert visit[field] is None, f"{field} must be null on an unscored visit, got {visit[field]!r}"

    patient = scenario.refresh_patient()
    assert patient["target_status"] == "UNASSESSED", (
        f"scheduling a visit projects nothing onto the patient, got {patient['target_status']!r}"
    )
    assert patient["latest_activity_score"] is None
    assert patient["latest_activity_category"] is None


# ==========================================================================
# visit_check_in_advances_scheduled_to_checked_in
# ==========================================================================
def test_nurse_check_in_advances_the_visit_and_bumps_only_the_visit_version():
    """The nurse's check-in is the `SCHEDULED -> CHECKED_IN` edge; it bumps the
    visit's own revision and nothing on the patient.

    PRD: "An `InfusionNurse` checks the patient in, which advances the visit `SCHEDULED → CHECKED_IN` and increments the visit's `version` by one."
    PRD: "The `version` counter is the substrate of the concurrency controls in §2.6, so its behaviour is exact rather than approximate: a resource's `version` advances only where this document says it advances."
    Design: Corner/state_machines/visit_check_in_advances_scheduled_to_checked_in
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()
    patient_version_before = scenario.refresh_patient()["version"]

    booked = fixtures.book_visit(
        scenario,
        visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
        visit_type="FOLLOW_UP",
    )
    visit_version_before = booked["version"]

    checked_in = validate_success(
        api_client.check_in_visit(booked["id"], scenario.nurse_headers)
    )

    assert checked_in["status"] == "CHECKED_IN", (
        f"check-in advances SCHEDULED -> CHECKED_IN, got {checked_in['status']!r}"
    )
    assert checked_in["version"] == visit_version_before + 1, (
        f"expected visit version {visit_version_before + 1}, got {checked_in['version']}"
    )
    assert scenario.refresh_patient()["version"] == patient_version_before, (
        "check-in has no patient side effect, so the patient's version must not move"
    )


# ==========================================================================
# visit_score_before_check_in_returns_visit_not_checked_in
# ==========================================================================
def test_scoring_a_still_scheduled_visit_is_refused_then_succeeds_after_check_in():
    """The very same scoring payload is refused with `ERR_VISIT_NOT_CHECKED_IN`
    before check-in and accepted after it, so the rejection is the state gate
    rather than a payload defect.

    PRD: "Check-in is a strict prerequisite for scoring, and the same error guards both ends of the sequence: a second check-in against a visit that has already left `SCHEDULED` is refused with `ERR_VISIT_NOT_CHECKED_IN` (HTTP 409), as is any attempt to score a visit that is not yet `CHECKED_IN`."
    Design: Corner/state_machines/visit_score_before_check_in_returns_visit_not_checked_in
    """
    fixtures.set_clock(constants.instant(2026, 8, 3, 14, 5, 0))
    scenario = fixtures.visit_ready_practice()
    booked = fixtures.book_visit(
        scenario,
        visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
        visit_type="FOLLOW_UP",
    )
    score_payload = factories.score_visit_cdai_payload()

    validate_error(
        api_client.score_visit(booked["id"], score_payload, scenario.rheum_headers),
        ApiErrorId.ERR_VISIT_NOT_CHECKED_IN.value,
        409,
    )

    untouched = validate_success(api_client.get_visit(booked["id"], scenario.rheum_headers))
    assert untouched["status"] == "SCHEDULED", "the rejected scoring left the visit SCHEDULED"
    assert untouched["activity_score"] is None, "the rejected scoring wrote no score"

    validate_success(api_client.check_in_visit(booked["id"], scenario.nurse_headers))
    scored = validate_success(
        api_client.score_visit(booked["id"], score_payload, scenario.rheum_headers)
    )

    assert scored["status"] == "SCORED", f"scoring advances to SCORED, got {scored['status']!r}"
    assert scored["activity_score"] == 9.00, (
        f"CDAI 2 + 1 + 3.0 + 3.0 is 9.00, got {scored['activity_score']!r}"
    )


# ==========================================================================
# visit_second_check_in_is_rejected_not_idempotent
# ==========================================================================
def test_replaying_check_in_on_a_checked_in_visit_is_rejected_and_bumps_nothing():
    """Check-in is not idempotent: the replay is a 409 and leaves the visit's
    revision exactly where the first check-in left it.

    PRD: "Check-in is a strict prerequisite for scoring, and the same error guards both ends of the sequence: a second check-in against a visit that has already left `SCHEDULED` is refused with `ERR_VISIT_NOT_CHECKED_IN` (HTTP 409), as is any attempt to score a visit that is not yet `CHECKED_IN`."
    Design: Corner/state_machines/visit_second_check_in_is_rejected_not_idempotent
    """
    fixtures.set_clock(constants.instant(2026, 8, 3, 14, 5, 0))
    scenario = fixtures.visit_ready_practice()
    booked = fixtures.book_visit(
        scenario,
        visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
        visit_type="FOLLOW_UP",
    )
    checked_in = validate_success(
        api_client.check_in_visit(booked["id"], scenario.nurse_headers)
    )
    version_after_first = checked_in["version"]

    validate_error(
        api_client.check_in_visit(booked["id"], scenario.nurse_headers),
        ApiErrorId.ERR_VISIT_NOT_CHECKED_IN.value,
        409,
    )

    after = validate_success(api_client.get_visit(booked["id"], scenario.rheum_headers))
    assert after["status"] == "CHECKED_IN", f"status must still be CHECKED_IN, got {after['status']!r}"
    assert after["version"] == version_after_first, (
        f"the rejected replay bumped nothing: expected version {version_after_first}, got {after['version']}"
    )


# ==========================================================================
# visit_scoring_bubbles_denormalized_fields_up_to_the_patient
# ==========================================================================
def test_scoring_writes_score_category_recommendation_and_scored_at_on_the_visit():
    """One scoring call settles all four derived visit fields at once.

    PRD: "Under `CDAI`, the score is the plain sum of four components: `tender_joint_count` plus `swollen_joint_count` plus `patient_global_assessment` plus `physician_global_assessment`, rounded half up to two decimal places."
    PRD: "The resulting `activity_category` is `REMISSION` when the score is at most 2.80, `LOW` when it is greater than 2.80 and at most 10.00, `MODERATE` when it is greater than 10.00 and at most 22.00, and `HIGH` when it exceeds 22.00."
    PRD: "Scoring also stamps `scored_at` with the logical clock and increments the visit's `version` by one."
    Design: Corner/state_machines/visit_scoring_bubbles_denormalized_fields_up_to_the_patient
    """
    scored_at = constants.instant(2026, 8, 3, 14, 5, 0)
    fixtures.set_clock(scored_at)
    scenario = fixtures.visit_ready_practice()
    fixtures.checked_in_visit(
        scenario,
        visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
        visit_type="FOLLOW_UP",
    )

    scored = validate_success(
        api_client.score_visit(
            scenario.visit_id, factories.score_visit_cdai_payload(), scenario.rheum_headers
        )
    )

    assert scored["status"] == "SCORED"
    assertions.assert_two_decimal_places(scored["activity_score"], "activity_score")
    assert scored["activity_score"] == 9.00, f"expected 9.00, got {scored['activity_score']!r}"
    assert scored["activity_category"] == "LOW", (
        f"9.00 is greater than 2.80 and at most 10.00, so LOW; got {scored['activity_category']!r}"
    )
    assert scored["escalation_recommendation"] == "CONTINUE", (
        f"a LOW category yields CONTINUE, got {scored['escalation_recommendation']!r}"
    )
    assertions.assert_instant_equals(scored["scored_at"], scored_at, "scored_at")


def test_scoring_bubbles_the_winning_figures_up_to_the_patient_in_one_version_bump():
    """The scored visit's figures are copied verbatim onto the patient, the
    target verdict follows the category, and the patient's revision advances by
    exactly one for the whole projection.

    PRD: "Among the patient's scored visits, the server picks the one with the greatest `visit_datetime`, breaking a tie by the greatest `created_at`, and copies that winner's figures verbatim — no rounding, no recomputation — into `latest_activity_score` and `latest_activity_category`."
    PRD: "The patient's `version` increments by one on every successful scoring."
    Design: Corner/state_machines/visit_scoring_bubbles_denormalized_fields_up_to_the_patient
    """
    fixtures.set_clock(constants.instant(2026, 8, 3, 14, 5, 0))
    scenario = fixtures.visit_ready_practice()
    fixtures.checked_in_visit(
        scenario,
        visit_datetime=constants.instant(2026, 8, 3, 14, 0, 0),
        visit_type="FOLLOW_UP",
    )
    patient_version_before = scenario.refresh_patient()["version"]

    validate_success(
        api_client.score_visit(
            scenario.visit_id, factories.score_visit_cdai_payload(), scenario.rheum_headers
        )
    )

    patient = scenario.refresh_patient()
    assert patient["latest_activity_score"] == 9.00, (
        f"expected latest_activity_score 9.00, got {patient['latest_activity_score']!r}"
    )
    assert patient["latest_activity_category"] == "LOW", (
        f"expected latest_activity_category LOW, got {patient['latest_activity_category']!r}"
    )
    assert patient["target_status"] == "AT_TARGET", (
        f"a LOW winning category is AT_TARGET, got {patient['target_status']!r}"
    )
    assert patient["version"] == patient_version_before + 1, (
        "one bubble-up write, not one per field: expected patient version "
        f"{patient_version_before + 1}, got {patient['version']}"
    )


# ==========================================================================
# cancelled_appointment_is_terminal_and_admits_no_further_transition
# ==========================================================================
def _cancelled_dose_scenario():
    """An ACTIVE, fully funded IV episode with one dose scheduled and then
    cancelled — the CANCELLED terminal state under test."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.scheduled_dose(
        scheduled_start=constants.instant(2026, 8, 10, 9, 0, 0),
        requested_units=6,
        determination_overrides={
            "approved_units": 6,
            "valid_from": constants.instant(2026, 8, 1),
            "valid_through": constants.instant(2027, 1, 28),
        },
    )
    cancelled = fixtures.cancel_appointment(scenario, cancellation_reason="PATIENT_REQUEST")
    return scenario, cancelled


@pytest.mark.parametrize(
    "operation",
    ["administer", "cancel", "reverse_administration"],
)
def test_cancelled_appointment_admits_no_further_transition(operation):
    """`CANCELLED` is terminal: administration, a second cancellation and a
    reversal are all refused with the appointment state code.

    PRD: "`ERR_APPOINTMENT_STATE_INVALID` — administration or cancellation attempted on an appointment that is not `SCHEDULED`, or reversal attempted on an appointment that is not `ADMINISTERED`."
    Design: Corner/state_machines/cancelled_appointment_is_terminal_and_admits_no_further_transition
    """
    scenario, cancelled = _cancelled_dose_scenario()
    appointment_id = cancelled["id"]

    if operation == "administer":
        response = api_client.administer_appointment(appointment_id, scenario.nurse_headers)
    elif operation == "cancel":
        response = api_client.cancel_appointment(
            appointment_id, {"cancellation_reason": "PATIENT_REQUEST"}, scenario.nurse_headers
        )
    else:
        response = api_client.reverse_administration(
            appointment_id,
            {"reversal_reason": "documentation correction"},
            scenario.nurse_headers,
        )

    validate_error(response, ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value, 409)

    after = scenario.refresh_appointment(appointment_id)
    assert after["status"] == "CANCELLED", (
        f"the rejected {operation} left the appointment CANCELLED, got {after['status']!r}"
    )
    assert after["version"] == cancelled["version"], (
        f"the rejected {operation} bumped nothing: expected version {cancelled['version']}, "
        f"got {after['version']}"
    )


def test_cancelled_appointment_releases_its_unit_exactly_once():
    """The first cancellation returned the reserved unit; three rejected
    follow-up transitions release nothing further, so the ledger still reads
    the single release.

    PRD: "The appointment moves `SCHEDULED → CANCELLED`, which is terminal, one unit moves from the authorization's `units_reserved` back into `units_remaining`, and the appointment's `assistance_applied_cents` moves from the enrollment's `benefit_reserved_cents` back into `benefit_remaining_cents`."
    Design: Corner/state_machines/cancelled_appointment_is_terminal_and_admits_no_further_transition
    """
    scenario, cancelled = _cancelled_dose_scenario()
    appointment_id = cancelled["id"]

    validate_error(
        api_client.administer_appointment(appointment_id, scenario.nurse_headers),
        ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value,
        409,
    )
    validate_error(
        api_client.cancel_appointment(
            appointment_id, {"cancellation_reason": "PATIENT_REQUEST"}, scenario.nurse_headers
        ),
        ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value,
        409,
    )
    validate_error(
        api_client.reverse_administration(
            appointment_id,
            {"reversal_reason": "documentation correction"},
            scenario.nurse_headers,
        ),
        ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value,
        409,
    )

    authorization = scenario.refresh_authorization()
    assertions.assert_unit_ledger(authorization, reserved=0, consumed=0, remaining=6)
    assert scenario.refresh_episode()["doses_administered"] == 0
    assert scenario.refresh_patient()["administered_dose_total"] == 0


# ==========================================================================
# discontinued_episode_locks_out_activate_hold_resume_and_discontinue
# ==========================================================================
def _discontinued_episode_scenario():
    """A PLANNED episode discontinued for INADEQUATE_RESPONSE at the default
    clock, so its frozen exposure is 0 weeks."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    discontinued = validate_success(
        api_client.discontinue_therapy_episode(
            scenario.episode_id,
            {"discontinuation_reason": "INADEQUATE_RESPONSE"},
            scenario.rheum_headers,
        )
    )
    return scenario, discontinued


@pytest.mark.parametrize(
    "operation,expected_error",
    [
        ("activate", ApiErrorId.ERR_EPISODE_NOT_PLANNED.value),
        ("hold", ApiErrorId.ERR_EPISODE_NOT_ACTIVE.value),
        ("resume", ApiErrorId.ERR_EPISODE_NOT_HELD.value),
        ("discontinue", ApiErrorId.ERR_EPISODE_NOT_ACTIVE.value),
    ],
)
def test_discontinued_episode_locks_out_every_clinical_transition(operation, expected_error):
    """`DISCONTINUED` is terminal on the clinical axis, and each locked-out
    action reports its own precondition code rather than a generic one.

    PRD: "`ERR_EPISODE_NOT_PLANNED` — activation attempted on an episode that is not `PLANNED`."
    PRD: "`ERR_EPISODE_NOT_ACTIVE` — hold, dose scheduling or administration attempted on an episode that is not `ACTIVE`; for discontinuation, the check is that the episode is not already `DISCONTINUED`."
    PRD: "`ERR_EPISODE_NOT_HELD` — resumption attempted on an episode that is not `HELD`."
    Design: Corner/state_machines/discontinued_episode_locks_out_activate_hold_resume_and_discontinue
    """
    scenario, discontinued = _discontinued_episode_scenario()
    episode_id = discontinued["id"]

    if operation == "activate":
        response = api_client.activate_therapy_episode(episode_id, scenario.rheum_headers)
    elif operation == "hold":
        response = api_client.hold_therapy_episode(
            episode_id, {"hold_reason": "INFECTION"}, scenario.rheum_headers
        )
    elif operation == "resume":
        response = api_client.resume_therapy_episode(
            episode_id, {"infection_resolved_attested": True}, scenario.rheum_headers
        )
    else:
        response = api_client.discontinue_therapy_episode(
            episode_id, {"discontinuation_reason": "PATIENT_REQUEST"}, scenario.rheum_headers
        )

    validate_error(response, expected_error, 409)

    after = scenario.refresh_episode()
    assert after["therapy_state"] == "DISCONTINUED"
    assert after["version"] == discontinued["version"], (
        f"the rejected {operation} bumped nothing: expected version "
        f"{discontinued['version']}, got {after['version']}"
    )


def test_discontinuation_out_of_planned_freezes_exposure_at_zero_weeks():
    """An episode that never activated freezes at zero exposure weeks, keeps
    the reason it was stopped for, and was never in the patient's active count.

    PRD: "`discontinued_at` is stamped from the logical clock and `therapy_exposure_weeks` is frozen at that moment: for an episode that had reached `ACTIVE` or `HELD` it is the elapsed time from `therapy_start_at` to `discontinued_at` divided by seven days with any remainder discarded, and for an episode discontinued straight out of `PLANNED` — which never activated — it is 0."
    PRD: "The patient's `active_episode_count` is decremented by one **only** when the episode was `ACTIVE` at the moment of discontinuation; an episode discontinued from `HELD` was already removed from the active count when it was held, and an episode discontinued from `PLANNED` was never in it."
    Design: Corner/state_machines/discontinued_episode_locks_out_activate_hold_resume_and_discontinue
    """
    scenario, discontinued = _discontinued_episode_scenario()

    assert discontinued["therapy_state"] == "DISCONTINUED"
    assert discontinued["discontinuation_reason"] == "INADEQUATE_RESPONSE"
    assert discontinued["therapy_exposure_weeks"] == 0, (
        f"an episode discontinued out of PLANNED freezes at 0 weeks, "
        f"got {discontinued['therapy_exposure_weeks']!r}"
    )
    assertions.assert_instant_equals(
        discontinued["discontinued_at"], constants.CLOCK_DEFAULT, "discontinued_at"
    )
    assert scenario.refresh_patient()["active_episode_count"] == 0


# ==========================================================================
# enrollment_attest_and_reauthorize_from_active_are_invalid_transitions
# ==========================================================================
COUNSELOR_GAMMA = make_benefits_counselor_headers("ops-counselor-gamma")


def _active_enrollment_scenario():
    """A PLANNED episode carrying one MANUFACTURER_COPAY_CARD enrollment
    submitted by counselor alpha and attested by counselor beta, so it is
    ACTIVE at the default clock."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    enrollment = fixtures.active_enrollment(scenario)
    return scenario, enrollment


@pytest.mark.parametrize("operation", ["attest", "reauthorize"])
def test_active_enrollment_refuses_attest_and_reauthorize(operation):
    """No operator edge leaves `ACTIVE`: a replayed attestation and a renewal
    are both refused with the enrollment state code.

    PRD: "The enrollment must also still be in `SUBMITTED`, or the attempt is refused with `ERR_ENROLLMENT_STATE_INVALID` (HTTP 409); the state check precedes the duties check, so attesting an already-active enrollment reports the state error even when the caller is also the original submitter."
    PRD: "Renewal is a counselor action against an enrollment in `REAUTH_PENDING` — any other status is refused with `ERR_ENROLLMENT_STATE_INVALID` — and it may optionally carry a fresh `annual_benefit_cents`, which replaces the stored figure; when the field is omitted the existing figure stands."
    Design: Corner/state_machines/enrollment_attest_and_reauthorize_from_active_are_invalid_transitions
    """
    scenario, enrollment = _active_enrollment_scenario()

    if operation == "attest":
        # A third, distinct counselor identity, so the state check is what bites
        # rather than the segregation-of-duties comparison.
        response = api_client.attest_enrollment(enrollment["id"], COUNSELOR_GAMMA)
    else:
        response = api_client.reauthorize_enrollment(
            enrollment["id"], {"annual_benefit_cents": 900_000}, scenario.counselor_headers
        )

    validate_error(response, ApiErrorId.ERR_ENROLLMENT_STATE_INVALID.value, 409)

    after = scenario.refresh_enrollment(enrollment["id"])
    assert after["status"] == "ACTIVE", (
        f"the rejected {operation} left the enrollment ACTIVE, got {after['status']!r}"
    )
    assert after["version"] == enrollment["version"], (
        f"the rejected {operation} bumped nothing: expected version "
        f"{enrollment['version']}, got {after['version']}"
    )


def test_rejected_attest_and_reauthorize_touch_no_enrollment_field():
    """Neither rejection rewrites the attestation audit fields, the coverage
    window or the money ledger.

    PRD: "A successful attestation advances `SUBMITTED → ACTIVE`, writes `attested_by_user_id` from the attesting caller's `X-User-ID` and `attested_at` from the logical clock, and increments the enrollment's `version` by one."
    PRD: "A manufacturer copay card runs a full year of 365 days from `coverage_start`; a foundation grant runs 180 days; a patient assistance program runs 90 days."
    Design: Corner/state_machines/enrollment_attest_and_reauthorize_from_active_are_invalid_transitions
    """
    scenario, enrollment = _active_enrollment_scenario()

    validate_error(
        api_client.attest_enrollment(enrollment["id"], COUNSELOR_GAMMA),
        ApiErrorId.ERR_ENROLLMENT_STATE_INVALID.value,
        409,
    )
    validate_error(
        api_client.reauthorize_enrollment(
            enrollment["id"], {"annual_benefit_cents": 900_000}, scenario.counselor_headers
        ),
        ApiErrorId.ERR_ENROLLMENT_STATE_INVALID.value,
        409,
    )

    after = scenario.refresh_enrollment(enrollment["id"])
    assertions.assert_assistance_enrollment(after)
    assert after["attested_by_user_id"] == COUNSELOR_BETA_USER_ID, (
        f"attested_by_user_id must still be the original attester, got "
        f"{after['attested_by_user_id']!r}"
    )
    assertions.assert_instant_equals(
        after["attested_at"], constants.CLOCK_DEFAULT, "attested_at"
    )
    assert after["annual_benefit_cents"] == 500_000, (
        f"the rejected renewal must not replace annual_benefit_cents, got "
        f"{after['annual_benefit_cents']!r}"
    )
    assertions.assert_money_ledger(after, used=0, reserved=0, remaining=500_000)
    assertions.assert_instant_equals(
        after["coverage_start"], constants.CLOCK_DEFAULT, "coverage_start"
    )
    assertions.assert_instant_equals(
        after["coverage_end"], constants.instant(2027, 8, 1), "coverage_end"
    )
