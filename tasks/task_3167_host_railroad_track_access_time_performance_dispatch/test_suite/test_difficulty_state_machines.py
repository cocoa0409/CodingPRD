"""Cyclic and fork-join state machines: the timetable review loop and dispute resolution."""

from prd_bench_local_runner.testing import validate_success as get_success

from test_helpers import PASSENGER_OPERATOR_HEADERS, fixtures


def test_revision_loop_increments_revision_no_each_round(api):
    """Returning an under-review timetable to PROPOSED increments revision_no.

    One UNDER_REVIEW -> PROPOSED loop takes revision_no from 0 to 1, after
    which the same timetable can be reviewed and ratified normally.

    PRD: "The operator may return an under-review timetable to `PROPOSED` for another negotiation round, incrementing `revision_no` each time."
    Design: Difficulty/non_linear_state_machine/timetable_review_revision_cycle
    """
    net = fixtures.setup_active_agreement(api)
    timetable = fixtures.create_timetable(api, net)
    assert timetable["revision_no"] == 0
    fixtures.propose_timetable(api, timetable["id"])
    fixtures.review_timetable(api, net, timetable["id"])

    revised = get_success(api.revise_timetable(timetable["id"], PASSENGER_OPERATOR_HEADERS))
    assert revised["status"] == "PROPOSED"
    assert revised["revision_no"] == 1

    fixtures.review_timetable(api, net, timetable["id"])
    ratified = fixtures.ratify_timetable(api, net, timetable["id"])
    assert ratified["status"] == "RATIFIED"
    assert ratified["revision_no"] == 1


def test_review_loop_is_cyclic_not_terminal(api):
    """After one loop, the timetable is again eligible for review and ratification.

    PRD: "A `HostRailroadRep` who owns the corridor's host railroad opens review, moving `PROPOSED` → `UNDER_REVIEW`. The operator may return an under-review timetable to `PROPOSED` for another negotiation round, incrementing `revision_no` each time. Ratification by the owning `HostRailroadRep` moves `UNDER_REVIEW` → `RATIFIED` and requires the operating agreement to be `ACTIVE` — otherwise the request fails with `ERR_AGREEMENT_NOT_ACTIVE`."
    Design: Difficulty/non_linear_state_machine/timetable_review_revision_cycle
    """
    net = fixtures.setup_active_agreement(api)
    timetable = fixtures.create_timetable(api, net)
    fixtures.propose_timetable(api, timetable["id"])
    fixtures.review_timetable(api, net, timetable["id"])
    get_success(api.revise_timetable(timetable["id"], PASSENGER_OPERATOR_HEADERS))

    second_review = fixtures.review_timetable(api, net, timetable["id"])
    assert second_review["status"] == "UNDER_REVIEW"

    ratified = fixtures.ratify_timetable(api, net, timetable["id"])
    assert ratified["status"] == "RATIFIED"
    assert ratified["revision_no"] == 1


def test_escalated_overturn_reverses_incident_and_recomputes_attributed_minutes(api):
    """The escalated branch of the dispute fork overturns the incident.

    Two OPEN host incidents (20 and 5 minutes); the 20-minute incident is
    disputed, escalated and resolved OVERTURNED, so it flips to REVERSED and
    the run's attributed host minutes drop to zero, because the other
    incident is still DISPUTED and only CONFIRMED host incidents count.

    PRD: "From `UNDER_REVIEW`, only `UPHELD` is accepted — attempting `OVERTURNED` without prior escalation is rejected with `ERR_INVALID_STATE` — while from `ESCALATED` either outcome is accepted."
    PRD: "an `UPHELD` resolution returns the incident `DISPUTED` → `CONFIRMED`, and an `OVERTURNED` resolution moves it `DISPUTED` → `REVERSED`; both outcomes recompute the owning run's `attributed_host_delay_minutes`"
    Design: Difficulty/non_linear_state_machine/dispute_escalation_fork_divergent_resolution
    """
    net = fixtures.run_0902_completed_20_late(api)
    inc_big = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )
    inc_small = fixtures.code_incident(api, net, net["run"]["id"], "HOST_TRACK", 5)
    dispute_a = fixtures.dispute_incident(
        api, inc_big["id"], reason="freight hold mis-coded", headers=net["host_headers"]
    )
    dispute_b = fixtures.dispute_incident(api, inc_small["id"], reason="challenged")
    fixtures.escalate_dispute(api, dispute_a["id"])

    resolved_a = fixtures.resolve_dispute(api, dispute_a["id"], "OVERTURNED")

    assert resolved_a["status"] == "RESOLVED"
    assert resolved_a["resolution"] == "OVERTURNED"
    assert fixtures.read_incident(api, inc_big["id"])["status"] == "REVERSED"
    assert fixtures.read_run(api, net["run"]["id"])["attributed_host_delay_minutes"] == 0
    assert fixtures.read_incident(api, inc_small["id"])["status"] == "DISPUTED"
    assert fixtures.read_dispute(api, dispute_b["id"])["status"] == "UNDER_REVIEW"


def test_direct_uphold_from_under_review_confirms_incident(api):
    """The non-escalated branch of the dispute fork confirms the incident.

    PRD: "Resolution stamps `resolved_at`, moves the dispute to `RESOLVED`, and feeds back into the incident: an `UPHELD` resolution returns the incident `DISPUTED` → `CONFIRMED`, and an `OVERTURNED` resolution moves it `DISPUTED` → `REVERSED`; both outcomes recompute the owning run's `attributed_host_delay_minutes`."
    Design: Difficulty/non_linear_state_machine/dispute_escalation_fork_divergent_resolution
    """
    net = fixtures.run_0902_completed_20_late(api)
    inc_big = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )
    inc_small = fixtures.code_incident(api, net, net["run"]["id"], "HOST_TRACK", 5)
    dispute_a = fixtures.dispute_incident(
        api, inc_big["id"], reason="freight hold mis-coded", headers=net["host_headers"]
    )
    dispute_b = fixtures.dispute_incident(api, inc_small["id"], reason="challenged")

    resolved_b = fixtures.resolve_dispute(api, dispute_b["id"], "UPHELD")

    assert resolved_b["status"] == "RESOLVED"
    assert resolved_b["resolution"] == "UPHELD"
    assert fixtures.read_incident(api, inc_small["id"])["status"] == "CONFIRMED"
    assert fixtures.read_run(api, net["run"]["id"])["attributed_host_delay_minutes"] == 5
    assert fixtures.read_dispute(api, dispute_a["id"])["status"] == "UNDER_REVIEW"

