"""The alert cycle: promotion, planning, escalation and re-planning."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_instant,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
)
from test_helpers import factories, fixtures


def world_with_escalated_alert(api):
    """A first plan that keeps one check-in, misses the other and closes ESCALATED."""
    world = fixtures.world_with_active_plan(
        api,
        required_checkin_count=2,
        duration_days=30,
        interventions=["RETRAINING", "COUNSELING"],
    )
    first_check_in, second_check_in = world["check_ins"]
    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    kept = fixtures.complete_check_in(api, world, first_check_in["id"])
    fixtures.set_clock(api, "2026-08-25T00:00:00Z")
    sweep = fixtures.run_sweep(api, world)
    closed = get_success_data(
        api.close_intervention_plan(world["p1_id"], {}, world["sup_headers"])
    )
    world.update(
        {
            "ci1": first_check_in,
            "ci2": second_check_in,
            "kept": kept,
            "sweep2": sweep,
            "closed_plan": closed,
        }
    )
    return world


def test_a_failed_plan_escalates_both_itself_and_its_alert(api):
    """One missed check-in of two scores 50.00, which is below the 80 success floor.

    PRD: The plan moves `ACTIVE → ESCALATED` when `compliance_score` is below 80, **or** when another alert was created for the officer inside that window.
    Design: Difficulty/non_linear_state_machine/alert_escalation_cycle_returns_to_plan_required
    """
    world = fixtures.world_with_active_plan(
        api,
        required_checkin_count=2,
        duration_days=30,
        interventions=["RETRAINING", "COUNSELING"],
    )
    assert world["alert"]["status"] == "PLAN_REQUIRED"
    assert_two_dp(world["alert"]["composite_score"], 63.75, label="composite_score")
    first_check_in, second_check_in = world["check_ins"]
    assert_instant(first_check_in["due_at"], "2026-08-11T00:00:00Z")
    assert_instant(second_check_in["due_at"], "2026-08-21T00:00:00Z")
    assert_instant(world["plan"]["end_date"], "2026-08-31T00:00:00Z")

    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    kept = fixtures.complete_check_in(api, world, first_check_in["id"])
    assert kept["on_time"] is True
    fixtures.set_clock(api, "2026-08-25T00:00:00Z")
    sweep = fixtures.run_sweep(api, world)
    assert sweep["checkins_missed"] == 1

    closed = get_success_data(
        api.close_intervention_plan(world["p1_id"], {}, world["sup_headers"])
    )

    assert closed["status"] == "ESCALATED"
    assert_two_dp(closed["compliance_score"], 50.00, label="compliance_score")
    assert closed["completed_checkin_count"] == 1
    assert closed["on_time_checkin_count"] == 1
    assert closed["concern_count"] == 0
    alert = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert alert["status"] == "ESCALATED"
    rows_, _ = fixtures.rows(api.list_plan_check_ins(world["p1_id"], world["sup_headers"]))
    assert rows_[1]["status"] == "MISSED"
    assert rows_[1]["on_time"] is None
    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(officer, open_alert_count=1, intervention_escalation_count=1)
    assert_officer_risk(officer, eis_score=63.75, eis_alert_level="CRITICAL")


def test_a_replacement_plan_returns_the_alert_to_plan_required(api):
    """A second plan drives the alert around the cycle and lifts plan_count to 2.

    PRD: When the alert was `ESCALATED`, it moves `ESCALATED → PLAN_REQUIRED`, which is the cycle in this system: `PLAN_REQUIRED → PLAN_ACTIVE → ESCALATED → PLAN_REQUIRED`, one revolution for every plan that fails.
    Design: Difficulty/non_linear_state_machine/alert_escalation_cycle_returns_to_plan_required
    """
    world = world_with_escalated_alert(api)
    escalated = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert escalated["status"] == "ESCALATED"
    assert escalated["plan_count"] == 1

    replacement = get_success_data(
        api.create_intervention_plan(
            world["al_id"],
            factories.intervention_plan_payload(
                escalated["version"],
                world["sup_id"],
                required_checkin_count=3,
                duration_days=60,
                interventions=["PEER_REVIEW", "EAP_REFERRAL"],
            ),
            world["sup_headers"],
        )
    )

    assert replacement["status"] == "DRAFT"
    assert replacement["completed_checkin_count"] == 0
    assert replacement["on_time_checkin_count"] == 0
    assert replacement["concern_count"] == 0
    reopened = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert reopened["status"] == "PLAN_REQUIRED"
    assert reopened["plan_count"] == 2
    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(officer, open_alert_count=1, intervention_escalation_count=1)
    first_plan = fixtures.read_plan(api, world["p1_id"], world["sup_headers"])
    assert first_plan["status"] == "ESCALATED"


WATCH_PREFIX = (
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-01T12:00:00Z", "UOF-1"),
    ("USE_OF_FORCE", "LEVEL_2", "2026-07-10T12:00:00Z", "UOF-2"),
    ("PURSUIT", "NA", "2026-07-15T12:00:00Z", "PUR-1"),
)

ALERT_SUFFIX = (
    ("PURSUIT", "NA", "2026-07-20T12:00:00Z", "PUR-2"),
    ("USE_OF_FORCE", "LEVEL_1", "2026-07-25T12:00:00Z", "UOF-3"),
)


def world_with_stale_watch_alert(api):
    """An alert opened in the WATCH band whose snapshot two later events left behind."""
    world = fixtures.seed_reference_data(api)
    fixtures.ingest_event_pattern(api, world["subj_id"], WATCH_PREFIX)
    alert = fixtures.alert_for_officer(api, world, world["subj_id"])
    fixtures.ingest_event_pattern(api, world["subj_id"], ALERT_SUFFIX)
    world.update({"al_id": alert["id"], "al_v0": alert["version"], "alert": alert})
    return world


def test_a_plan_is_refused_while_the_alert_carries_its_stale_open_snapshot(api):
    """The officer is in the ALERT band, but the alert row is still OPEN at 31.25.

    PRD: The alert must be in `PLAN_REQUIRED` or `ESCALATED`, otherwise `ERR_ALERT_STATE_INVALID`.
    Design: Difficulty/cross_entity_state_dependency/plan_creation_depends_on_the_alert_status_the_sweep_promotes
    """
    world = world_with_stale_watch_alert(api)
    assert world["alert"]["status"] == "OPEN"
    assert_two_dp(world["alert"]["composite_score"], 31.25, label="composite_score")
    assert world["alert"]["alert_level"] == "WATCH"
    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_risk(officer, eis_score=63.75, eis_alert_level="ALERT")
    assert_officer_ledgers(officer, open_alert_count=1)

    refused = api.create_intervention_plan(
        world["al_id"],
        factories.intervention_plan_payload(
            world["al_v0"], world["sup_id"], interventions=["RETRAINING", "COUNSELING"]
        ),
        world["sup_headers"],
    )

    validate_error(refused, "ERR_ALERT_STATE_INVALID", 409)
    unchanged = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert unchanged["status"] == "OPEN"
    assert unchanged["plan_count"] == 0
    assert unchanged["version"] == world["al_v0"]


def test_the_sweep_promotion_admits_the_same_plan_payload(api):
    """One targeted run refreshes the alert to 63.75 and promotes it to PLAN_REQUIRED.

    PRD: It promotes an alert `OPEN → PLAN_REQUIRED` when the recomputed band reaches `ALERT` or `CRITICAL`, setting `review_due_at` to the promotion instant plus 30 whole days — the same 30-day rule that sets `review_due_at` at creation.
    Design: Difficulty/cross_entity_state_dependency/plan_creation_depends_on_the_alert_status_the_sweep_promotes
    """
    world = world_with_stale_watch_alert(api)

    run = fixtures.run_sweep(api, world, officer_id=world["subj_id"], headers=world["cmdr_headers"])

    assert run["run_sequence"] == 1
    assert run["evaluated_officer_count"] == 1
    assert run["alerts_created"] == 0
    assert run["alerts_promoted"] == 1
    assert run["checkins_missed"] == 0
    assert run["disclosures_expired"] == 0

    promoted = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert promoted["status"] == "PLAN_REQUIRED"
    assert_two_dp(promoted["composite_score"], 63.75, label="composite_score")
    assert promoted["alert_level"] == "ALERT"
    assert promoted["breached_indicators"] == ["FORCE_COUNT", "PURSUIT_COUNT"]
    assert promoted["run_sequence"] == 1
    assert_instant(promoted["review_due_at"], "2026-08-31T00:00:00Z")
    assert promoted["version"] > world["al_v0"]

    plan = get_success_data(
        api.create_intervention_plan(
            world["al_id"],
            factories.intervention_plan_payload(
                promoted["version"], world["sup_id"], interventions=["RETRAINING", "COUNSELING"]
            ),
            world["sup_headers"],
        )
    )
    assert plan["status"] == "DRAFT"

    activated = get_success_data(
        api.activate_intervention_plan(plan["id"], {}, world["sup_headers"])
    )
    assert activated["status"] == "ACTIVE"
    assert_instant(activated["activated_at"], "2026-08-01T00:00:00Z")
    assert_instant(activated["end_date"], "2026-08-31T00:00:00Z")

    check_ins, _ = fixtures.rows(api.list_plan_check_ins(plan["id"], world["sup_headers"]))
    assert [row["status"] for row in check_ins] == ["PENDING", "PENDING"]
    assert_instant(check_ins[0]["due_at"], "2026-08-11T00:00:00Z")
    assert_instant(check_ins[1]["due_at"], "2026-08-21T00:00:00Z")

    working = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert working["status"] == "PLAN_ACTIVE"
    assert working["plan_count"] == 1
