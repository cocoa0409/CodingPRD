"""Holding and resuming therapy: reason-specific gates and the lab cascade.

Sources: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rules `non_linear_state_machine`
and `transitive_cascade`.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money_ledger,
    assert_monitoring_lab,
    assert_unit_ledger,
)
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.fixtures import (
    ADMIN,
    active_enrollment,
    active_episode,
    file_monitoring_lab,
    schedule_appointment,
    set_clock,
)


def _held_for_surgery():
    """An `ACTIVE`, `AUTHORIZED` Infliximab episode with a `CURRENT` CMP panel,
    six approved units and no appointment at all, held for `SURGERY` on
    2026-08-05 so the hold cascade has nothing to cancel."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = active_episode(requested_units=6)
    set_clock(instant(2026, 8, 5, 0, 0, 0), ADMIN)
    held = get_success_data(
        api_client.hold_therapy_episode(
            scenario.episode_id, {"hold_reason": "SURGERY"}, scenario.rheum_headers
        )
    )
    scenario.episode = held
    return scenario, held


def _resume(scenario, payload):
    return api_client.resume_therapy_episode(
        scenario.episode_id, payload, scenario.rheum_headers
    )


# ---------------------------------------------------------------------------
# non_linear_state_machine /
# therapy_episode_hold_resume_cycle_with_reason_specific_gates
# ---------------------------------------------------------------------------
def test_surgery_hold_of_a_tnfi_product_waits_two_weeks():
    """The washout comes from a reason-by-class matrix, not a single constant.

    PRD §3.9: "A `SURGERY` hold waits two weeks for a `TNFI` product, four weeks
    for an `IL6` product, one week for a `JAKI` product, six months — 180 days —
    for a `CD20` product, and four weeks for a `CTLA4` product."

    Design: Difficulty/non_linear_state_machine/therapy_episode_hold_resume_cycle_with_reason_specific_gates
    """
    scenario, held = _held_for_surgery()

    assert held["therapy_state"] == "HELD"
    assert held["hold_reason"] == "SURGERY"
    assert held["hold_count"] == 1
    assert_instant_equals(held["held_at"], instant(2026, 8, 5, 0, 0, 0), "held_at")
    assert_instant_equals(
        held["resume_not_before"], instant(2026, 8, 19, 0, 0, 0), "resume_not_before"
    )
    assert held["funding_state"] == "AUTHORIZED"
    assert scenario.refresh_patient()["active_episode_count"] == 0


def test_resumption_before_the_washout_instant_is_refused():
    """The washout gate is checked even when the obligation is already met.

    PRD §3.9: "And the logical clock must have reached `resume_not_before`, else
    `ERR_WASHOUT_PERIOD_NOT_ELAPSED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/therapy_episode_hold_resume_cycle_with_reason_specific_gates
    """
    scenario, _held = _held_for_surgery()

    response = _resume(scenario, {"wound_healed_attested": True})

    validate_error(response, ApiErrorId.ERR_WASHOUT_PERIOD_NOT_ELAPSED.value, 409)
    assert scenario.refresh_episode()["therapy_state"] == "HELD"


def test_surgery_resumption_demands_the_wound_attestation():
    """A `SURGERY` hold is cleared by `wound_healed_attested` and nothing else.

    PRD §3.9: "A `SURGERY` hold requires that the request supply
    `wound_healed_attested` set to true."

    Design: Difficulty/non_linear_state_machine/therapy_episode_hold_resume_cycle_with_reason_specific_gates
    """
    scenario, _held = _held_for_surgery()
    set_clock(instant(2026, 8, 19, 0, 0, 0), ADMIN)

    refused = _resume(scenario, {})
    validate_error(refused, ApiErrorId.ERR_RESUMPTION_PROTOCOL_INCOMPLETE.value, 422)
    assert scenario.refresh_episode()["therapy_state"] == "HELD"

    resumed = get_success_data(_resume(scenario, {"wound_healed_attested": True}))

    assert resumed["therapy_state"] == "ACTIVE"
    assert resumed["hold_reason"] is None
    assert resumed["held_at"] is None
    assert resumed["resume_not_before"] is None
    assert resumed["hold_count"] == 1
    assert resumed["funding_state"] == "AUTHORIZED"


def test_the_second_hold_cycle_enforces_a_different_obligation():
    """`ACTIVE → HELD → ACTIVE → HELD → ACTIVE` swaps the obligation each pass.

    PRD §3.9: "An `INFECTION` hold requires that the request supply
    `infection_resolved_attested` set to true."

    PRD §3.9: "An `INFECTION` hold waits one week for every molecule class without
    exception."

    Design: Difficulty/non_linear_state_machine/therapy_episode_hold_resume_cycle_with_reason_specific_gates
    """
    scenario, _held = _held_for_surgery()
    set_clock(instant(2026, 8, 19, 0, 0, 0), ADMIN)
    get_success_data(_resume(scenario, {"wound_healed_attested": True}))

    set_clock(instant(2026, 8, 20, 0, 0, 0), ADMIN)
    second_hold = get_success_data(
        api_client.hold_therapy_episode(
            scenario.episode_id, {"hold_reason": "INFECTION"}, scenario.rheum_headers
        )
    )
    assert second_hold["therapy_state"] == "HELD"
    assert second_hold["hold_reason"] == "INFECTION"
    assert second_hold["hold_count"] == 2
    assert_instant_equals(second_hold["held_at"], instant(2026, 8, 20, 0, 0, 0), "held_at")
    assert_instant_equals(
        second_hold["resume_not_before"], instant(2026, 8, 27, 0, 0, 0), "resume_not_before"
    )

    set_clock(instant(2026, 8, 27, 0, 0, 0), ADMIN)
    wrong_attestation = _resume(scenario, {"wound_healed_attested": True})
    validate_error(
        wrong_attestation, ApiErrorId.ERR_RESUMPTION_PROTOCOL_INCOMPLETE.value, 422
    )

    resumed = get_success_data(_resume(scenario, {"infection_resolved_attested": True}))

    assert resumed["therapy_state"] == "ACTIVE"
    assert resumed["hold_count"] == 2, "hold_count accumulates across every entry into HELD"
    assert resumed["funding_state"] == "AUTHORIZED", (
        "the cycle is confined to the clinical axis and never touched funding"
    )
    assert resumed["hold_reason"] is None
    assert scenario.refresh_patient()["active_episode_count"] == 1
    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=0, remaining=6)


# ---------------------------------------------------------------------------
# transitive_cascade /
# lab_grade_hold_cascade_releases_units_and_reactivates_enrollment
# ---------------------------------------------------------------------------
def _exhausted_practice():
    """An `ACTIVE` Infliximab episode with six approved units, one scheduled dose
    at 2026-08-12T09:00:00Z and a copay card of exactly 111007 cents, which that
    dose's assistance drives to `EXHAUSTED`."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = active_episode(requested_units=6)
    active_enrollment(scenario, annual_benefit_cents=111_007)
    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))
    return scenario


def _file_grade_four_panel(scenario):
    return file_monitoring_lab(
        scenario,
        panel_type="CMP",
        collected_at=instant(2026, 8, 13, 0, 0, 0),
        alt_u_l=450.0,
        neutrophil_k_ul=3.20,
    )


def test_a_grade_four_panel_holds_the_episode_with_no_clinician_in_the_loop():
    """An ALT above 400 grades 4 and forces the hold on the server's own authority.

    PRD §3.6: "`alt_grade` is 0 when `alt_u_l` is absent or is at most 40, 1 when
    it is greater than 40 and at most 120, 2 when it is greater than 120 and at
    most 200, 3 when it is greater than 200 and at most 400, and 4 when it exceeds
    400 — the upper bounds are inclusive, so a value of exactly 200.0 grades 2
    while 200.1 grades 3."

    PRD §3.6: "The episode moves `ACTIVE → HELD` with `hold_reason`
    `LAB_ABNORMALITY`, `held_at` stamped from the logical clock, and `hold_count`
    incremented by one."

    Design: Difficulty/transitive_cascade/lab_grade_hold_cascade_releases_units_and_reactivates_enrollment
    """
    scenario = _exhausted_practice()
    set_clock(instant(2026, 8, 13, 0, 0, 0), ADMIN)

    lab = _file_grade_four_panel(scenario)

    assert_monitoring_lab(lab)
    assert lab["alt_grade"] == 4
    assert lab["anc_grade"] == 0
    assert lab["abnormal_grade"] == 4
    assert lab["triggers_hold"] is True

    episode = scenario.refresh_episode()
    assert episode["therapy_state"] == "HELD"
    assert episode["hold_reason"] == "LAB_ABNORMALITY"
    assert episode["hold_count"] == 1
    assert_instant_equals(episode["held_at"], instant(2026, 8, 13, 0, 0, 0), "held_at")
    assert_instant_equals(
        episode["resume_not_before"], instant(2026, 8, 13, 0, 0, 0), "resume_not_before"
    )
    assert episode["resume_not_before"] == episode["held_at"], (
        "the washout for a lab abnormality is zero days"
    )
    assert episode["funding_state"] == "AUTHORIZED"
    assert scenario.refresh_patient()["active_episode_count"] == 0


def test_the_lab_hold_cancels_the_scheduled_dose_and_releases_its_unit():
    """The cascade cancels the dose and refunds the authorization unit.

    PRD §3.6: "The same tail then runs as for a clinician-ordered hold: every one
    of the episode's appointments still in `SCHEDULED` is cancelled with
    `cancellation_reason` `THERAPY_HELD`, each cancellation releases one unit from
    the reserving authorization's `units_reserved` into its `units_remaining` and
    releases that appointment's `assistance_applied_cents` from the reserving
    enrollment's `benefit_reserved_cents` into its `benefit_remaining_cents`, and
    any enrollment sitting in `EXHAUSTED` whose `benefit_remaining_cents` becomes
    greater than zero as a result moves `EXHAUSTED → ACTIVE`."

    Design: Difficulty/transitive_cascade/lab_grade_hold_cascade_releases_units_and_reactivates_enrollment
    """
    scenario = _exhausted_practice()
    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=5)

    set_clock(instant(2026, 8, 13, 0, 0, 0), ADMIN)
    _file_grade_four_panel(scenario)

    appointment = scenario.refresh_appointment()
    assert appointment["status"] == "CANCELLED"
    assert appointment["cancellation_reason"] == "THERAPY_HELD"
    assert appointment["administered_at"] is None

    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=0, remaining=6)


def test_the_lab_hold_lifts_the_exhausted_enrollment_back_to_active():
    """Exhaustion is recoverable: the release reactivates the enrollment.

    PRD §3.8: "An active enrollment moves between `ACTIVE` and `EXHAUSTED` purely
    as a consequence of money."

    PRD §3.8: "Any reservation or administration that drives
    `benefit_remaining_cents` to exactly zero moves it `ACTIVE → EXHAUSTED`, and
    any release that lifts `benefit_remaining_cents` back above zero — an
    appointment cancellation, or the unwinding tail of a hold or a discontinuation
    — moves it `EXHAUSTED → ACTIVE`."

    Design: Difficulty/transitive_cascade/lab_grade_hold_cascade_releases_units_and_reactivates_enrollment
    """
    scenario = _exhausted_practice()
    before = scenario.refresh_enrollment()
    assert before["status"] == "EXHAUSTED"
    assert_money_ledger(before, used=0, reserved=111_007, remaining=0)

    set_clock(instant(2026, 8, 13, 0, 0, 0), ADMIN)
    _file_grade_four_panel(scenario)

    after = scenario.refresh_enrollment()
    assert_money_ledger(after, used=0, reserved=0, remaining=111_007)
    assert after["status"] == "ACTIVE"
    assert after["benefit_used_cents"] == 0, "the dose was never administered"
