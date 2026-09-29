"""Two rules broken at once, and which of the two the ladder reports.

Source: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rule
`priority_pair_validation_conflict`.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals, assert_unit_ledger, validate_list
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.factories import create_appointment_payload
from test_helpers.fixtures import (
    ADMIN,
    approved_authorization,
    bootstrap_reference,
    file_screen,
    make_monitoring_current,
    open_planned_episode,
    register_patient,
    scheduled_dose,
    set_clock,
)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict /
# discontinued_episode_state_check_outranks_missing_tb_screen_on_activate
# ---------------------------------------------------------------------------
def _tb_missing_practice():
    """Infliximab on Meridian PPO with a patient whose hepatitis B panel is
    complete and negative but who has no tuberculosis record at all, a `CURRENT`
    CMP panel and an `APPROVED` six-unit authorization — so priorities 26, 30, 31
    and 32 are all satisfied and only the tuberculosis rule is live."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = bootstrap_reference()
    register_patient(scenario)
    file_screen(scenario, "HBV_SURFACE_AG", "NEGATIVE")
    file_screen(scenario, "HBV_CORE_AB", "NEGATIVE")
    open_planned_episode(scenario)
    make_monitoring_current(scenario)
    approved_authorization(scenario, requested_units=6)
    return scenario


def _activate(scenario):
    return api_client.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers)


def _discontinue(scenario, reason="PATIENT_REQUEST"):
    return get_success_data(
        api_client.discontinue_therapy_episode(
            scenario.episode_id, {"discontinuation_reason": reason}, scenario.rheum_headers
        )
    )


def test_the_missing_tuberculosis_record_alone_refuses_activation():
    """With the episode still `PLANNED` only the screening rule can fire.

    PRD §3.4: "If the drug has `tb_screen_required` set, the patient's
    `tb_screen_status` must be `CLEARED` or `CLEARED_AFTER_TREATMENT`; a posture of
    `MISSING`, `EXPIRED`, `INDETERMINATE` or `POSITIVE_UNTREATED` is refused with
    `ERR_TB_SCREEN_NOT_CLEARED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/discontinued_episode_state_check_outranks_missing_tb_screen_on_activate
    """
    scenario = _tb_missing_practice()
    patient = scenario.refresh_patient()
    assert patient["tb_screen_status"] == "MISSING"
    assert patient["hbv_screen_status"] == "CLEARED"
    episode = scenario.refresh_episode()
    assert episode["therapy_state"] == "PLANNED"
    assert episode["funding_state"] == "AUTHORIZED"
    assert episode["monitoring_status"] == "CURRENT"

    response = _activate(scenario)

    validate_error(response, ApiErrorId.ERR_TB_SCREEN_NOT_CLEARED.value, 422)
    assert scenario.refresh_episode()["therapy_state"] == "PLANNED"


def test_discontinuation_straight_out_of_planned_freezes_the_exposure_at_zero():
    """The episode leaves `PLANNED` without ever having been active.

    PRD §3.9: "`discontinued_at` is stamped from the logical clock and
    `therapy_exposure_weeks` is frozen at that moment: for an episode that had
    reached `ACTIVE` or `HELD` it is the elapsed time from `therapy_start_at` to
    `discontinued_at` divided by seven days with any remainder discarded, and for an
    episode discontinued straight out of `PLANNED` — which never activated — it is
    0."

    Design: Difficulty/priority_pair_validation_conflict/discontinued_episode_state_check_outranks_missing_tb_screen_on_activate
    """
    scenario = _tb_missing_practice()

    discontinued = _discontinue(scenario)

    assert discontinued["therapy_state"] == "DISCONTINUED"
    assert discontinued["discontinuation_reason"] == "PATIENT_REQUEST"
    assert discontinued["therapy_exposure_weeks"] == 0
    assert_instant_equals(
        discontinued["discontinued_at"], instant(2026, 8, 1, 0, 0, 0), "discontinued_at"
    )
    assert scenario.refresh_patient()["active_episode_count"] == 0


def test_the_episode_state_rule_outranks_the_still_broken_screening_rule():
    """Both rules are broken; the ladder reports the lower-numbered one.

    PRD §2.10: "When a request violates more than one rule, exactly one error is
    returned, and which one is fixed rather than incidental. The server evaluates in
    the following order and stops at the first failure."

    PRD §3.4: "The episode must still be `PLANNED`, or the request is refused with
    `ERR_EPISODE_NOT_PLANNED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/discontinued_episode_state_check_outranks_missing_tb_screen_on_activate
    """
    scenario = _tb_missing_practice()

    tb_only = _activate(scenario)
    validate_error(tb_only, ApiErrorId.ERR_TB_SCREEN_NOT_CLEARED.value, 422)

    _discontinue(scenario)
    assert scenario.refresh_patient()["tb_screen_status"] == "MISSING", (
        "the screening rule is still violated when the paired request is made"
    )

    paired = _activate(scenario)

    body = validate_error(paired, ApiErrorId.ERR_EPISODE_NOT_PLANNED.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_TB_SCREEN_NOT_CLEARED.value, (
        "priority 21 outranks priority 29, so the state error must be the one reported"
    )
    assert scenario.refresh_episode()["therapy_state"] == "DISCONTINUED"
    assert scenario.refresh_patient()["active_episode_count"] == 0


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict /
# chair_time_conflict_outranks_exhausted_authorization_units_on_scheduling
# ---------------------------------------------------------------------------
def _single_unit_practice():
    """An `ACTIVE` Infliximab episode whose authorization was approved for exactly
    one unit, that unit already reserved by a dose at 2026-08-12T09:00:00Z which
    blocks chair AIC-1 through 12:00 — so an 11:45 request breaks the chair rule and
    the unit rule at the same time."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = scheduled_dose(instant(2026, 8, 12, 9, 0, 0), requested_units=1)
    return scenario


def _schedule(scenario, scheduled_start):
    return api_client.create_infusion_appointment(
        create_appointment_payload(
            scenario.episode_id, scenario.chair_id, scheduled_start=scheduled_start
        ),
        scenario.nurse_headers,
    )


def test_the_chair_conflict_outranks_the_exhausted_unit_pool():
    """Priority 45 beats priority 48 when a request violates both.

    PRD §2.10: "45. `ERR_CHAIR_TIME_CONFLICT` — the requested chair occupancy
    overlaps an existing occupancy including its turnover buffer."

    PRD §2.10: "Second, when dose scheduling reaches the authorization-selection
    step, that calculation has its own internal ordering — described in §3.7 — and
    that internal ordering governs which of `ERR_AUTHORIZATION_UNITS_EXHAUSTED` and
    `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` is reported, overriding the relative
    positions those two occupy in the general ladder."

    Design: Difficulty/priority_pair_validation_conflict/chair_time_conflict_outranks_exhausted_authorization_units_on_scheduling
    """
    scenario = _single_unit_practice()
    first = scenario.refresh_appointment()
    assert_instant_equals(first["scheduled_start"], instant(2026, 8, 12, 9, 0, 0))
    assert_instant_equals(first["scheduled_end"], instant(2026, 8, 12, 11, 30, 0))
    authorization = scenario.refresh_authorization()
    assert authorization["approved_units"] == 1
    assert_unit_ledger(authorization, reserved=1, consumed=0, remaining=0)

    response = _schedule(scenario, instant(2026, 8, 12, 11, 45, 0))

    body = validate_error(response, ApiErrorId.ERR_CHAIR_TIME_CONFLICT.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_AUTHORIZATION_UNITS_EXHAUSTED.value, (
        "the exhausted pool is the incidental violation here, not the reported one"
    )


def test_a_start_clear_of_the_buffer_isolates_the_unit_rule():
    """The fiscal rule is live: alone, it is exactly what a 12:00 start reports.

    PRD §3.7: "First, the pool of the episode's authorizations in `status`
    `APPROVED` is assembled; if that pool is empty, or if every member of it has
    `units_remaining` of zero, the request is refused with
    `ERR_AUTHORIZATION_UNITS_EXHAUSTED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/chair_time_conflict_outranks_exhausted_authorization_units_on_scheduling
    """
    scenario = _single_unit_practice()

    response = _schedule(scenario, instant(2026, 8, 12, 12, 0, 0))

    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_UNITS_EXHAUSTED.value, 409)


def test_neither_rejected_request_booked_a_chair_or_moved_a_unit():
    """Both refusals are total: one appointment stands and the ledger is unchanged.

    PRD §2.8: "Exactly one unit is moved per dose in every direction; there is no
    partial unit anywhere in the system."

    Design: Difficulty/priority_pair_validation_conflict/chair_time_conflict_outranks_exhausted_authorization_units_on_scheduling
    """
    scenario = _single_unit_practice()

    paired = _schedule(scenario, instant(2026, 8, 12, 11, 45, 0))
    validate_error(paired, ApiErrorId.ERR_CHAIR_TIME_CONFLICT.value, 409)

    units_only = _schedule(scenario, instant(2026, 8, 12, 12, 0, 0))
    validate_error(units_only, ApiErrorId.ERR_AUTHORIZATION_UNITS_EXHAUSTED.value, 409)

    rows, meta = validate_list(
        api_client.list_infusion_appointments(ADMIN, {"episode_id": scenario.episode_id})
    )
    assert meta["total_count"] == 1, (
        f"neither rejected request may persist an appointment, got {meta['total_count']}"
    )
    assert len(rows) == 1

    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=0)
