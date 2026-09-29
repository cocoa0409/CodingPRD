"""Gates that read the state of a neighbouring entity rather than their own.

Source: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rule `cross_entity_state_dependency`.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals, assert_unit_ledger
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.factories import update_infusion_chair_payload
from test_helpers.fixtures import (
    ADMIN,
    REVIEWER,
    administer_appointment,
    make_monitoring_current,
    open_authorization,
    planned_episode,
    scheduled_dose,
    set_clock,
    submit_authorization,
)

APPROVAL = {
    "decision": "APPROVED",
    "approved_units": 6,
    "valid_from": instant(2026, 8, 1, 0, 0, 0),
    "valid_through": instant(2027, 1, 28, 0, 0, 0),
}


# ---------------------------------------------------------------------------
# cross_entity_state_dependency /
# episode_activation_gated_on_authorization_status_of_a_separate_entity
# ---------------------------------------------------------------------------
def _submitted_practice():
    """Infliximab on Meridian PPO; a patient cleared for TB and hepatitis B, a
    `CURRENT` CMP panel, one `PLANNED` episode and a `SUBMITTED` six-unit
    authorization — so every gate the episode owns is satisfied and only the
    neighbouring authorization stands in the way."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = planned_episode()
    make_monitoring_current(scenario)
    open_authorization(scenario, requested_units=6)
    submit_authorization(scenario)
    return scenario


def _activate(scenario):
    return api_client.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers)


def test_activation_is_refused_while_the_authorization_is_only_submitted():
    """The refusal comes from the authorization, not from the episode.

    PRD §3.4: "Its `funding_state` must be `AUTHORIZED`, or
    `ERR_FUNDING_NOT_AUTHORIZED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/episode_activation_gated_on_authorization_status_of_a_separate_entity
    """
    scenario = _submitted_practice()
    assert scenario.refresh_authorization()["status"] == "SUBMITTED"
    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "PENDING_AUTH"
    assert episode["therapy_state"] == "PLANNED"
    assert episode["monitoring_status"] == "CURRENT"

    response = _activate(scenario)

    validate_error(response, ApiErrorId.ERR_FUNDING_NOT_AUTHORIZED.value, 409)
    assert scenario.refresh_episode()["therapy_state"] == "PLANNED"
    assert scenario.refresh_patient()["active_episode_count"] == 0


def test_the_approval_flips_the_funding_gate_on_the_episode():
    """Approving the separate entity is what moves the episode's funding.

    PRD §3.5: "In the same operation the episode's `funding_state` advances
    `PENDING_AUTH → AUTHORIZED` and the episode's `version` increments by one; the
    authorization's own `version` increments by one as well."

    Design: Difficulty/cross_entity_state_dependency/episode_activation_gated_on_authorization_status_of_a_separate_entity
    """
    scenario = _submitted_practice()

    approved = get_success_data(
        api_client.determine_authorization(scenario.authorization_id, APPROVAL, REVIEWER)
    )

    assert approved["status"] == "APPROVED"
    assert approved["approved_units"] == 6
    assert_unit_ledger(approved, reserved=0, consumed=0, remaining=6)
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"


def test_the_identical_activation_succeeds_once_the_authorization_is_approved():
    """Nothing about the episode changed between the refusal and the success.

    PRD §3.4: "A successful activation increments the patient's
    `active_episode_count` by one, increments the patient's `version` by one, and
    increments the episode's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/episode_activation_gated_on_authorization_status_of_a_separate_entity
    """
    scenario = _submitted_practice()
    patient_before = scenario.refresh_patient()

    refused = _activate(scenario)
    validate_error(refused, ApiErrorId.ERR_FUNDING_NOT_AUTHORIZED.value, 409)

    get_success_data(
        api_client.determine_authorization(scenario.authorization_id, APPROVAL, REVIEWER)
    )

    activated = get_success_data(_activate(scenario))

    assert activated["therapy_state"] == "ACTIVE"
    assert activated["funding_state"] == "AUTHORIZED"
    assert activated["monitoring_status"] == "CURRENT", (
        "the episode's own preconditions were satisfied the whole time"
    )

    patient_after = scenario.refresh_patient()
    assert patient_after["active_episode_count"] == 1
    assert patient_after["tb_screen_status"] == patient_before["tb_screen_status"]
    assert patient_after["hbv_screen_status"] == patient_before["hbv_screen_status"]


# ---------------------------------------------------------------------------
# cross_entity_state_dependency /
# dose_administration_gated_on_infusion_chair_status
# ---------------------------------------------------------------------------
def _closed_chair_dose():
    """An `ACTIVE` Infliximab episode with a `CURRENT` panel, six approved units
    and one dose scheduled at 2026-08-12T09:00:00Z on chair AIC-1, which is then
    closed; the clock stands at the dose's own start instant."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = scheduled_dose(instant(2026, 8, 12, 9, 0, 0), requested_units=6)
    closed = get_success_data(
        api_client.update_infusion_chair(
            scenario.chair_id, update_infusion_chair_payload(status="CLOSED"), ADMIN
        )
    )
    assert closed["status"] == "CLOSED"
    set_clock(instant(2026, 8, 12, 9, 0, 0), ADMIN)
    return scenario


def _reopen(scenario):
    return get_success_data(
        api_client.update_infusion_chair(
            scenario.chair_id, update_infusion_chair_payload(status="OPEN"), ADMIN
        )
    )


def test_administration_against_a_closed_chair_is_refused():
    """Three of the four administration conditions hold; the chair fails the fourth.

    PRD §3.7: "Four conditions are checked: the appointment must be `SCHEDULED`,
    else `ERR_APPOINTMENT_STATE_INVALID` (HTTP 409); the episode must be `ACTIVE`,
    else `ERR_EPISODE_NOT_ACTIVE`; the chair must be `OPEN`, else
    `ERR_CHAIR_CLOSED`; and the episode's `monitoring_status` must be `CURRENT`,
    else `ERR_MONITORING_LAB_OVERDUE`."

    Design: Difficulty/cross_entity_state_dependency/dose_administration_gated_on_infusion_chair_status
    """
    scenario = _closed_chair_dose()
    assert scenario.refresh_appointment()["status"] == "SCHEDULED"
    episode = scenario.refresh_episode()
    assert episode["therapy_state"] == "ACTIVE"
    assert episode["monitoring_status"] == "CURRENT"

    response = api_client.administer_appointment(
        scenario.appointment_id, scenario.nurse_headers
    )

    validate_error(response, ApiErrorId.ERR_CHAIR_CLOSED.value, 409)


def test_the_refused_administration_stamps_nothing_and_consumes_no_unit():
    """A closed chair leaves the appointment and the unit ledger exactly as they were.

    PRD §2.10: "`ERR_CHAIR_CLOSED` — dose scheduling or administration against a
    chair whose `status` is `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/dose_administration_gated_on_infusion_chair_status
    """
    scenario = _closed_chair_dose()

    refused = api_client.administer_appointment(
        scenario.appointment_id, scenario.nurse_headers
    )
    validate_error(refused, ApiErrorId.ERR_CHAIR_CLOSED.value, 409)

    appointment = scenario.refresh_appointment()
    assert appointment["status"] == "SCHEDULED"
    assert appointment["administered_at"] is None
    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=5)
    assert scenario.refresh_episode()["doses_administered"] == 0


def test_reopening_the_chair_lets_the_identical_request_succeed():
    """A write to the chair aggregate alone unblocks the appointment.

    PRD §3.7: "Administration stamps `administered_at` from the logical clock,
    moves one unit from the reserving authorization's `units_reserved` into its
    `units_consumed` while leaving `units_remaining` untouched, moves the
    appointment's `assistance_applied_cents` from the reserving enrollment's
    `benefit_reserved_cents` into its `benefit_used_cents` while leaving
    `benefit_remaining_cents` untouched, increments the episode's
    `doses_administered` and the patient's `administered_dose_total` by one each,
    and increments the `version` of the appointment, the episode and the patient by
    one each."

    Design: Difficulty/cross_entity_state_dependency/dose_administration_gated_on_infusion_chair_status
    """
    scenario = _closed_chair_dose()

    refused = api_client.administer_appointment(
        scenario.appointment_id, scenario.nurse_headers
    )
    validate_error(refused, ApiErrorId.ERR_CHAIR_CLOSED.value, 409)

    assert _reopen(scenario)["status"] == "OPEN"

    administered = administer_appointment(scenario)

    assert administered["status"] == "ADMINISTERED"
    assert_instant_equals(
        administered["administered_at"], instant(2026, 8, 12, 9, 0, 0), "administered_at"
    )
    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=1, remaining=5)
    assert scenario.refresh_episode()["doses_administered"] == 1
    assert scenario.refresh_patient()["administered_dose_total"] == 1
