"""Unwinding a ratified family decision, and the conservation of authorized
coverage hours across a suspend-then-reactivate lap.
"""
from test_helpers import (
    activate_service_authorization,
    assert_coverage_hours,
    authorize_service_authorization,
    convene_conference,
    propose_service_authorization,
    ratify_conference_decision,
    read_authorization,
    read_care_plan,
    read_client,
    read_decision,
    record_conference_decision,
    register_family_contact,
    rescind_conference_decision,
    schedule_conference,
    setup_active_authorization_scenario,
    setup_active_care_plan_scenario,
    suspend_service_authorization,
    uniform_domain_scores,
)

_RESCIND_NOTE = "Family reversed the engagement decision."


def _authorization_justified_by_a_ratified_decision():
    """A convened conference, a ratified vendor-engagement decision, and the
    AUTHORIZED coverage raised on the strength of it.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-09T09:00:00Z",
        client_overrides={
            "full_name": "Cornelia Achterberg",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "authorized_concurrent_caregivers": 2,
        },
        scores=uniform_domain_scores(1),
    )
    bystander = register_family_contact(
        scenario.client_id,
        full_name="Benedikt Achterberg",
        contact_role="INTERESTED_FAMILY",
    )
    conference = schedule_conference(
        scenario.client_id,
        [scenario.surrogate_id, bystander["id"]],
        scenario.care_manager_id,
    )
    conference = convene_conference(
        conference["id"], [scenario.surrogate_id], scenario.care_manager_id
    )
    assert conference["quorum_met"] is True
    assert conference["surrogate_present"] is True

    decision = record_conference_decision(
        conference["id"],
        scenario.surrogate_id,
        scenario.care_manager_id,
        decision_type="VENDOR_ENGAGEMENT",
    )
    decision = ratify_conference_decision(decision["id"], scenario.supervisor_id)
    assert decision["status"] == "RATIFIED"

    authorization = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
        authorizing_decision_id=decision["id"],
    )
    authorization = authorize_service_authorization(
        authorization["id"], scenario.supervisor_id
    )
    return scenario, decision, authorization


def test_01_coverage_raised_on_a_ratified_decision_stands_and_is_counted():
    """Before the compensating action: the engagement names the ratified decision,
    its hours are on the client, and the plan's coverage gap has closed.

    PRD: "Ratification matters beyond the conference record: only a `RATIFIED` decision may be named as the authorizing decision on a vendor engagement."

    Design: Difficulty/transitive_cascade/decision_rescind_four_hop_coverage_cascade
    """
    scenario, decision, authorization = _authorization_justified_by_a_ratified_decision()

    assert authorization["auth_status"] == "AUTHORIZED"
    assert authorization["authorizing_decision_id"] == decision["id"]
    assert authorization["coverage_hours"] == 8

    client = read_client(scenario.client_id)
    assert_coverage_hours(client, 8)
    assert client["risk_posture"] == "ROUTINE"
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False


def test_02_rescinding_records_the_reason_and_terminates_what_it_justified():
    """The first two hops: the decision is rescinded with the supplied note stored,
    and because of that the authorization it justified is terminated for that cause.

    PRD: "Rescission then unwinds what the decision authorized: every service authorization whose `authorizing_decision_id` names this decision and whose `auth_status` is `PROPOSED`, `AUTHORIZED`, `ACTIVE` or `SUSPENDED` moves to `TERMINATED` with `termination_reason` set to `DECISION_RESCINDED`."

    Design: Difficulty/transitive_cascade/decision_rescind_four_hop_coverage_cascade
    """
    scenario, decision, authorization = _authorization_justified_by_a_ratified_decision()
    rescinded = rescind_conference_decision(
        decision["id"], scenario.supervisor_id, note=_RESCIND_NOTE
    )

    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescinded_reason"] == _RESCIND_NOTE

    terminated = read_authorization(authorization["id"])
    assert terminated["auth_status"] == "TERMINATED"
    assert terminated["termination_reason"] == "DECISION_RESCINDED"


def test_03_the_terminated_coverage_leaves_the_authorized_set_and_reopens_the_gap():
    """The third hop: with the authorization outside the authorized set the client's
    coverage total falls to zero and the active plan's gap flag comes back.

    PRD: "Because those authorizations left the authorized set, the client's `authorized_coverage_hours` is recomputed downward and each affected care plan's `coverage_gap_flag` is recomputed."

    Design: Difficulty/transitive_cascade/decision_rescind_four_hop_coverage_cascade
    """
    scenario, decision, _authorization = _authorization_justified_by_a_ratified_decision()
    rescind_conference_decision(
        decision["id"], scenario.supervisor_id, note=_RESCIND_NOTE
    )

    assert_coverage_hours(read_client(scenario.client_id), 0)
    plan = read_care_plan(scenario.care_plan_id)
    assert plan["status"] == "ACTIVE"
    assert plan["coverage_gap_flag"] is True


def test_04_the_reopened_coverage_gap_elevates_the_clients_risk_posture():
    """The fourth hop: an activated plan with nobody authorized to deliver it is an
    elevated-risk client, and no escalation has been raised along the way.

    PRD: "Because a `coverage_gap_flag` may have flipped from false to true on a plan that is still `ACTIVE`, the client's `risk_posture` is recomputed to `ELEVATED`."

    Design: Difficulty/transitive_cascade/decision_rescind_four_hop_coverage_cascade
    """
    scenario, decision, _authorization = _authorization_justified_by_a_ratified_decision()
    rescind_conference_decision(
        decision["id"], scenario.supervisor_id, note=_RESCIND_NOTE
    )

    client = read_client(scenario.client_id)
    assert client["risk_posture"] == "ELEVATED"
    assert client["protective_escalation_status"] == "NONE"
    assert read_decision(decision["id"])["escalated_at"] is None


def _sixteen_hours_of_live_coverage():
    """An ACTIVE engagement staffing two caregivers across an eight-hour window,
    so sixteen caregiver-hours are standing on the client.
    """
    return setup_active_authorization_scenario(
        clock="2026-08-19T09:00:00Z",
        client_overrides={
            "full_name": "Priya Raghunathan",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "authorized_concurrent_caregivers": 2,
        },
        scores=uniform_domain_scores(2),
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=2,
        hourly_cost_cents=4_000,
    )


def test_05_live_coverage_puts_its_whole_caregiver_hour_total_on_the_client():
    """The opening checkpoint: an active row's sixteen caregiver-hours are inside
    the authorized set, so the plan has no gap and the client is routine.

    PRD: "The client's `authorized_coverage_hours` is at all times the sum of `coverage_hours` over that client's service authorizations whose `auth_status` is `AUTHORIZED` or `ACTIVE`; rows that are `PROPOSED`, `SUSPENDED` or `TERMINATED` are excluded from the sum entirely."

    Design: Difficulty/compensating_invariant/coverage_hours_conserved_across_suspend_and_reactivate
    """
    scenario = _sixteen_hours_of_live_coverage()

    assert scenario.authorization["auth_status"] == "ACTIVE"
    assert scenario.authorization["coverage_hours"] == 16
    assert scenario.authorization["suspension_reason"] == "NONE"

    client = read_client(scenario.client_id)
    assert_coverage_hours(client, 16)
    assert client["risk_posture"] == "ROUTINE"
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False


def test_06_suspending_withdraws_the_hours_while_the_row_keeps_its_own_figure():
    """Mid-lap: the client's total falls to zero because a suspended row is out of
    the authorized set, yet the row's own `coverage_hours` is untouched — which is
    what makes the figure restorable.

    PRD: "In every case the authorization's `coverage_hours` is subtracted from the client's `authorized_coverage_hours`, the parent plan's `coverage_gap_flag` is recomputed, the client's `risk_posture` is recomputed, and the authorization's `version` increases by 1."

    Design: Difficulty/compensating_invariant/coverage_hours_conserved_across_suspend_and_reactivate
    """
    scenario = _sixteen_hours_of_live_coverage()
    active_version = scenario.authorization["version"]

    suspended = suspend_service_authorization(
        scenario.authorization_id, scenario.care_manager_id
    )
    assert suspended["auth_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "FAMILY_REQUEST"
    assert suspended["coverage_hours"] == 16
    assert suspended["version"] > active_version

    client = read_client(scenario.client_id)
    assert_coverage_hours(client, 0)
    assert client["risk_posture"] == "ELEVATED"
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is True


def test_07_reactivating_restores_exactly_the_pre_lap_total():
    """The closing checkpoint: the lap leaves the client on sixteen hours exactly —
    not thirty-two from a double-add and not zero from a lost restore — and every
    transition advanced the authorization's version.

    PRD: "The loop between `ACTIVE` and `SUSPENDED` is unbounded, and each lap must leave the client's `authorized_coverage_hours` at exactly the value it held before the lap."

    Design: Difficulty/compensating_invariant/coverage_hours_conserved_across_suspend_and_reactivate
    """
    scenario = _sixteen_hours_of_live_coverage()
    active_version = scenario.authorization["version"]

    suspended = suspend_service_authorization(
        scenario.authorization_id, scenario.care_manager_id
    )
    reactivated = activate_service_authorization(
        scenario.authorization_id, scenario.care_manager_id
    )
    assert reactivated["auth_status"] == "ACTIVE"
    assert reactivated["suspension_reason"] == "NONE"
    assert reactivated["coverage_hours"] == 16
    assert reactivated["version"] > suspended["version"] > active_version

    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 16
    assert client["authorized_coverage_hours"] != 32
    assert client["risk_posture"] == "ROUTINE"
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False


def test_08_a_second_lap_lands_on_the_same_total_as_the_first():
    """The loop is unbounded, so a second suspend-then-reactivate pair over the
    same engagement must close on the identical sixteen-hour total.

    PRD: "Authorized caregiver-hours of coverage are conserved across authorization state changes: every suspend-then-reactivate lap and every terminate-then-re-authorize pair must leave the client's `authorized_coverage_hours` at exactly the value it held before the pair began."

    Design: Difficulty/compensating_invariant/coverage_hours_conserved_across_suspend_and_reactivate
    """
    scenario = _sixteen_hours_of_live_coverage()

    for _lap in range(2):
        suspend_service_authorization(
            scenario.authorization_id, scenario.care_manager_id
        )
        assert_coverage_hours(read_client(scenario.client_id), 0)
        activate_service_authorization(
            scenario.authorization_id, scenario.care_manager_id
        )
        assert_coverage_hours(read_client(scenario.client_id), 16)

    final = read_authorization(scenario.authorization_id)
    assert final["auth_status"] == "ACTIVE"
    assert final["suspension_reason"] == "NONE"
    assert final["coverage_hours"] == 16
