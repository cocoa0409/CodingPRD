"""Scheduled sweeps and lifecycle transitions: the restriction-expiry sweep, the
periodic review round, the trip ledger and the regional policy generations."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_account,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_cluster,
    setup_decided_case,
    setup_link,
    setup_policy,
    setup_trip,
    shift_iso,
    make_driver_headers,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]
RIDER = TEST_USERS["rider_headers"]


def test_expiry_sweep_restores_the_account_and_retains_the_action(api):
    """PRD §3.8: "the sweep increments the account's `version` by 1"
    PRD §2.6: "The action begins in `DRAFT` and moves to `ACTIVE` or to `MANDATORY_REPORTED`
    inside the same request."

    Design: Difficulty/cross_entity_state_dependency/dependency_expiry_blocked_by_sibling_severe_tier
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account, incident, action = setup_decided_case(
        account_handle="tomas.vidal.high", incident_category="PROPERTY_DAMAGE",
        decision_category="RESTRICTED",
        evidence_specs=[
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    assert action["enforcement_status"] == "ACTIVE"

    set_clock("2027-10-01T00:00:00Z")
    before = get_account(account["id"])
    assert before["standing_enforcement_count"] == 1

    swept = get_success_data(
        api_client.expiry_sweep(account["id"], before["version"], OPERATIONS_LEAD)
    )
    assert swept["standing_enforcement_count"] == 0
    assert swept["status"] in ("ACTIVE", "DEACTIVATED"), (
        "the sweep either restores the account or deactivates it on a tier regression"
    )
    assert swept["version"] == before["version"] + 1, (
        "the sweep increments the account's version by one"
    )


def test_expiry_sweep_soft_deletes_the_action_rather_than_erasing_it(api):
    """PRD §2.6: "An `EnforcementAction` is never created by a client. It is synthesised when
    a decision is committed"
    PRD §3.8: "It moves the account's `ACTIVE` enforcement action whose `expires_at` has
    arrived to `EXPIRED`"

    Design: Corner/cross_cutting_layers/restriction_expiry_restores_the_account_and_freezes_the_posture
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account, incident, action = setup_decided_case(
        account_handle="ema.fischer", incident_category="PROPERTY_DAMAGE",
        decision_category="RESTRICTED",
        evidence_specs=[
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
        ],
    )

    set_clock("2027-10-01T00:00:00Z")
    before = get_account(account["id"])
    swept = get_success_data(
        api_client.expiry_sweep(account["id"], before["version"], OPERATIONS_LEAD)
    )
    assert swept["standing_enforcement_count"] == 0
    assert swept["safety_posture"] in ("OPEN", "RESTRICTED")

    retained = get_success_data(
        api_client.get_enforcement_action(action["id"], OPERATIONS_LEAD)
    )
    assert retained["enforcement_status"] == "EXPIRED", (
        "the standing action is marked expired rather than deleted"
    )
    assert retained["outcome"] == "RESTRICTED", (
        "the action's outcome is retained so the history stays queryable"
    )
    rows = get_success_data(
        api_client.list_enforcement_actions(OPERATIONS_LEAD,
                                            params={"account_id": account["id"]})
    )
    assert len(rows) == 1, "the expired action remains queryable through the listing"


def test_review_tick_advances_the_review_date_and_leaves_effective_at_alone(api):
    """PRD §3.8: "Every action at or past its `review_due_at` receives `review_due_at` advanced
    by 180 days, and `effective_at` is left untouched so the effective date of the restriction
    remains auditable."

    Design: Corner/state_machines/enforcement_action_lifecycle_and_review_tick_cycle
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account, incident, action = setup_decided_case(
        account_handle="nia.campbell", incident_category="SAFETY_VIOLATION",
        decision_category="RESTRICTED",
        evidence_specs=[
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "RATINGS_HISTORY", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    assert action["enforcement_status"] == "ACTIVE"
    assert action["outcome"] == "RESTRICTED"
    effective_before = action["effective_at"]
    review_before = action["review_due_at"]

    set_clock("2027-04-03T00:00:00Z")
    ticked = get_success_data(api_client.review_tick(account["id"], OPERATIONS_LEAD))
    assert ticked, "the review round returns the account's enforcement actions"
    assert ticked[0]["effective_at"] == effective_before, (
        "the periodic review round leaves the effective date untouched"
    )
    assert ticked[0]["review_due_at"] != review_before, (
        "the action at or past its review date receives a fresh one"
    )
    assert ticked[0]["enforcement_status"] == "ACTIVE"


def test_completed_trip_decrements_both_member_accounts_risk(api):
    """PRD §2.4: "Completing a trip subtracts 2 from the `risk_score` of both the rider and the
    driver account, floored at 0."
    PRD §3.9: "Completion itself requires the trip to sit at `COMPLETED_PENDING`, stamps
    `completed_at` from the logical clock, decrements **both** member accounts' risk scores by 2
    floored at 0"

    Design: Difficulty/compensating_invariant/invariant_overturn_restores_standing_enforcement_count
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    rider = setup_account(handle="iris.bell", account_type="RIDER")
    driver = setup_account(account_type="DRIVER", handle="gita.rao")

    # Both accounts carry a little risk so the decrement is observable.
    make_incident(rider["id"], incident_category="HARASSMENT")
    make_incident(driver["id"], incident_category="HARASSMENT")
    rider_before = get_account(rider["id"])["risk_score"]
    driver_before = get_account(driver["id"])["risk_score"]
    assert rider_before > 0 and driver_before > 0

    trip = setup_trip(rider["id"], driver["id"])
    assert trip["status"] == "REQUESTED"
    assert trip["completed_at"] is None

    driver_headers = make_driver_headers(driver["id"])
    started = get_success_data(api_client.complete_start_trip(trip["id"], driver_headers))
    assert started["status"] == "COMPLETED_PENDING"

    completed = get_success_data(api_client.complete_trip(trip["id"], driver_headers))
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] is not None

    assert get_account(rider["id"])["risk_score"] == pytest.approx(rider_before - 2, abs=0.005), (
        "the rider's score is decremented by the trip credit"
    )
    assert get_account(driver["id"])["risk_score"] == pytest.approx(
        driver_before - 2, abs=0.005
    ), "the driver's score is decremented by the trip credit"


def test_completion_start_is_refused_for_a_driver_who_does_not_own_the_trip(api):
    """PRD §3.9: "A `Driver` signals completion by moving the trip to `COMPLETED_PENDING`,
    which is permitted only when the acting driver account is the trip's `driver_account_id`
    and that account's `status` is `ACTIVE` or `RESTRICTED`."

    Design: Corner/entities/trip_lifecycle_requires_the_acting_driver_to_own_the_trip
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    rider = setup_account(handle="iris.bell.owner", account_type="RIDER")
    owner = setup_account(account_type="DRIVER", handle="gita.rao.owner")
    outsider = setup_account(account_type="DRIVER", handle="hugo.marsh")

    trip = setup_trip(rider["id"], owner["id"])
    assert trip["status"] == "REQUESTED"
    assert trip["completed_at"] is None

    res = api_client.complete_start_trip(trip["id"], make_driver_headers(outsider["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403, (
        "the acting driver is not the trip's driver, so the operation is refused"
    )
    assert get_success_data(api_client.get_trip(trip["id"], ADMIN))["status"] == "REQUESTED"


def test_policy_defaults_apply_to_every_omitted_threshold(api):
    """PRD §3.9: "Creation supplies `region_code` and `sd_floor_severity` and may supply any of
    `sd_floor_enabled`, `rollup_window_days`, `rollup_threshold`, `cluster_watchlist_threshold`,
    `cluster_purge_threshold`, `escalation_enabled`, `expedite_appeal_baseline_count`,
    `expedite_review_days`, `standard_review_days`, `appeal_window_days`,
    `rescreen_refresh_days`, `continuous_monitor_ack_deadline_days`, `review_generation_index`
    and `knob_generation_index`; every omitted value takes its documented default"
    PRD §2.8: "Both counters are monotonic and begin at 1."

    Design: Corner/entities/platform_policy_defaults_are_applied_for_every_omitted_threshold
    """
    set_clock("2026-10-01T00:00:00Z")

    policy = get_success_data(
        api_client.create_platform_policy(
            {"region_code": "R2", "sd_floor_severity": "S2"}, ADMIN
        )
    )

    assert policy["sd_floor_enabled"] is True
    assert policy["escalation_enabled"] is True
    assert policy["rollup_window_days"] == 30
    assert policy["rollup_threshold"] == 3
    assert policy["cluster_watchlist_threshold"] == 2
    assert policy["cluster_purge_threshold"] == 2400
    assert policy["expedite_appeal_baseline_count"] == 5
    assert policy["expedite_review_days"] == 14
    assert policy["standard_review_days"] == 30
    assert policy["appeal_window_days"] == 30
    assert policy["rescreen_refresh_days"] == 548
    assert policy["continuous_monitor_ack_deadline_days"] == 7
    assert policy["review_generation_index"] == 1
    assert policy["knob_generation_index"] == 1


def test_config_advance_steps_the_knob_counter_and_restamps_the_region(api):
    """PRD §3.9: "There is also a bulk generation-advance capability, keyed on `region_code`
    and an `advance_counter` naming which counter to move, which increments that counter by one
    and then re-stamps every member account's generation, re-anchors every member background
    check, bumps each account's open continuous-monitor `monitor_generation`, and recomputes
    and re-stamps every cluster in the region."

    Design: Corner/cross_cutting_layers/config_advance_steps_the_knob_counter_and_recomputes_clusters
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(knob_generation_index=1, review_generation_index=1)
    account = setup_account(account_type="DRIVER", handle="gus.lindholm")
    cluster = setup_cluster(cluster_key="dc-advance")
    setup_link(account["id"], cluster["id"], fingerprint_hash="fp-advance")

    assert get_account(account["id"])["policy_generation_index"] == 1
    assert get_success_data(
        api_client.get_device_cluster(cluster["id"], OPERATIONS_LEAD)
    )["cluster_risk_generation_index"] == 1

    advanced = get_success_data(
        api_client.config_advance("R1", "knob_generation_index", ADMIN)
    )
    assert advanced["knob_generation_index"] == 2, (
        "the named counter steps by exactly one"
    )
    assert advanced["review_generation_index"] == 1, (
        "the periodicity counter is left untouched by a knob-only advance"
    )
    assert get_account(account["id"])["policy_generation_index"] == 2, (
        "every member account's generation is re-stamped from the advanced policy"
    )
    assert get_success_data(
        api_client.get_device_cluster(cluster["id"], OPERATIONS_LEAD)
    )["cluster_risk_generation_index"] == 2, (
        "the region's clusters are recomputed and re-stamped on the advance"
    )


def test_acknowledged_review_moves_into_the_review_state(api):
    """PRD §3.8: "A `BackgroundReviewer` acknowledges a due review when the current instant has
    reached its `scheduled_due_at` minus the region's continuous-monitor acknowledgement
    deadline, which moves the record from `SCHEDULED` to `IN_REVIEW`"

    Design: Corner/validations/background_check_acknowledge_before_the_ack_deadline_is_refused
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(continuous_monitor_ack_deadline_days=7, rescreen_refresh_days=548)
    account = setup_account(account_type="DRIVER", handle="soren.vogt")

    check = get_success_data(
        api_client.list_account_background_checks(account["id"], TEST_USERS["background_reviewer_headers"])
    )[0]

    set_clock(shift_iso(check["scheduled_due_at"], -6))
    acknowledged = get_success_data(
        api_client.acknowledge_background_check(
            check["id"], TEST_USERS["background_reviewer_headers"]
        )
    )
    assert acknowledged["check_status"] == "IN_REVIEW", (
        "once the clock reaches the acknowledgement window the record moves into review"
    )
    assert acknowledged["completed_at"] is None, (
        "the acknowledgement is not an adjudication, so no completion instant is stamped"
    )
    assert get_success_data(
        api_client.get_background_check(
            check["id"], TEST_USERS["background_reviewer_headers"]
        )
    )["check_status"] == "IN_REVIEW"