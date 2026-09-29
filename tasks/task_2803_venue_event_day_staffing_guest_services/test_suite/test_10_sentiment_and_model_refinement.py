"""Guest sentiment aggregation and the end-of-season model refinement read."""

from test_helpers import (
    DIRECTOR_HEADERS,
    ERR_EVENT_STATE_INVALID,
    SUPERVISOR_HEADERS,
    advance_event,
    assert_absent,
    assert_average,
    assert_fields,
    assert_ratio,
    assert_slot_fill,
    assert_version_unchanged,
    attendance,
    create_assignment,
    create_event,
    create_member,
    create_satisfaction_response,
    err,
    event_in_progress_with_slot,
    ok,
    read_event,
    read_slot,
    set_clock,
)
from test_helpers.factories import ticket_taker_payload


def _survey_fixture(client):
    """Eight responses whose scores sum to 35 across two zones."""
    set_clock(client, "2026-09-13T09:00:00Z")
    event = create_event(
        client,
        name="Satisfaction Precision Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )
    first = create_satisfaction_response(client, event["id"], "Z701", 5)
    for _ in range(3):
        create_satisfaction_response(client, event["id"], "Z701", 5)
    create_satisfaction_response(client, event["id"], "Z702", 4)
    create_satisfaction_response(client, event["id"], "Z702", 4)
    create_satisfaction_response(
        client, event["id"], "Z702", 4, comment="Long queue at the elevator"
    )
    create_satisfaction_response(client, event["id"], "Z702", 3)
    return event, first


def _summary(client, event_id, headers=None, **params):
    return ok(
        client.get_satisfaction_summary(event_id, headers or DIRECTOR_HEADERS, params or None)
    )


def test_sentiment_average_quantizes_half_up_on_the_exact_tie(client):
    """Eight scores summing to 35 average to 4.375 and must be reported as 4.38.

    "When there is at least one, `average_score` is the sum of the scores divided
    by the count, quantized to two decimal places by rounding half up — eight
    responses summing to 35 give exactly 4.375, which is reported as 4.38 and not
    4.37 — and `promoter_share_bp` is the count of responses scoring 4 or better,
    multiplied by 10000, divided by the total count, and rounded half up to a
    whole number of basis points."

    Design: Difficulty/boundary_precision_check/satisfaction_average_half_up_at_4_375
    """
    event, _first = _survey_fixture(client)

    summary = _summary(client, event["id"])

    assert_fields(summary, response_count=8, promoter_share_bp=8750)
    assert_average(summary["average_score"], 4.38, "average_score")
    assert summary["average_score"] != 4.37, (
        "4.375 must round half up to 4.38, never down to 4.37"
    )
    assert_fields(summary, resolved_issue_count=0, sla_breached_issue_count=0)

    breakdown = summary["zone_breakdown"]
    assert [entry["zone_code"] for entry in breakdown] == ["Z701", "Z702"], (
        "zone_breakdown is ordered by zone_code ascending"
    )
    assert_fields(breakdown[0], zone_code="Z701", response_count=4)
    assert_average(breakdown[0]["average_score"], 5.00, "Z701 average")
    assert_fields(breakdown[1], zone_code="Z702", response_count=4)
    assert_average(breakdown[1]["average_score"], 3.75, "Z702 average")


def test_zone_filtered_sentiment_summary_recomputes_every_headline_figure(client):
    """Narrowing the read to one zone recomputes the count, the mean and the promoter share.

    "Responses may be listed for an event, optionally narrowed to a single
    `zone_code`."

    Design: Difficulty/boundary_precision_check/satisfaction_average_half_up_at_4_375
    """
    event, _first = _survey_fixture(client)

    filtered = _summary(client, event["id"], SUPERVISOR_HEADERS, zone_code="Z702")

    assert_fields(filtered, response_count=4, promoter_share_bp=7500)
    assert_average(filtered["average_score"], 3.75, "filtered average_score")
    assert len(filtered["zone_breakdown"]) == 1, "only the requested zone is broken out"
    assert_fields(filtered["zone_breakdown"][0], zone_code="Z702", response_count=4)


def test_sentiment_responses_are_append_only_and_the_summary_is_pure(client):
    """A filed response carries no version, and reading the summary stores nothing.

    "A response is the one resource in this system that carries no `updated_at`
    and no `version` at all — only its `id` and its `created_at` — because it can
    never be edited, withdrawn or corrected once filed."

    Design: Difficulty/boundary_precision_check/satisfaction_average_half_up_at_4_375
    """
    event, first = _survey_fixture(client)

    assert_absent(first, "updated_at", "version")

    before_event = read_event(client, event["id"])
    first_read = _summary(client, event["id"])
    second_read = _summary(client, event["id"])
    after_event = read_event(client, event["id"])

    assert first_read == second_read, "the summary read is pure and repeatable"
    assert_version_unchanged(before_event, after_event)


def _four_of_five_worked(client):
    """A closed event whose only block planned five heads and worked four."""
    set_clock(client, "2026-09-12T17:00:00Z")
    context = event_in_progress_with_slot(
        client,
        position_type_payload=ticket_taker_payload(required_certifications=[]),
        slot_overrides={
            "zone_code": "Z901",
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
        },
        name="Fill Rate Boundary Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
    )
    slot_id = context["slot"]["id"]
    for index, name in enumerate(["Wes Iyer", "Xia Nolan", "Yao Pike", "Zed Quill"]):
        member = create_member(
            client,
            full_name=name,
            employment_type="PART_TIME_EMPLOYEE",
            seniority_date=f"2024-0{index + 1}-01T00:00:00Z",
            hourly_rate_cents=2000,
        )
        assignment = create_assignment(client, slot_id, member["id"])
        attendance(client, assignment["id"], "CHECK_IN", at="2026-09-12T18:00:00Z")
        attendance(client, assignment["id"], "CHECK_OUT", at="2026-09-12T22:00:00Z")
    return context


def test_fill_rate_of_exactly_8000_bp_is_not_uplifted(client):
    """Four heads worked of five planned is exactly 8000 bp, which the strict test holds.

    "Because the first test is strict, a group that worked 4 of 5 planned heads
    lands on exactly 8000 basis points and is *not* uplifted."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_8000_bp_holds_the_ratio
    """
    context = _four_of_five_worked(client)
    event_id = context["event"]["id"]

    assert_slot_fill(
        read_slot(client, context["slot"]["id"]),
        filled=4,
        required=5,
        status="PARTIALLY_FILLED",
    )
    advance_event(client, event_id, "CLOSED")

    answer = ok(client.get_staffing_model_recommendation(event_id, DIRECTOR_HEADERS))
    groups = answer["position_recommendations"]
    assert len(groups) == 1, "one position family was staffed, so one group is reported"
    group = groups[0]
    assert_fields(
        group,
        planned_headcount=5,
        worked_headcount=4,
        no_show_count=0,
        fill_rate_bp=8000,
        direction="HOLD",
    )
    assert_ratio(group["recommended_ratio_per_1000"], 0.80, "recommended_ratio_per_1000")
    assert group["recommended_ratio_per_1000"] != 0.88, (
        "8000 is not strictly below 8000, so the 1.10 uplift must not fire"
    )


def test_absent_sentiment_average_never_satisfies_the_trim_floor(client):
    """With no responses at all the 0.95 trim branch is skipped, not taken.

    "Otherwise, when the group had no no-shows at all, the whole plan had no
    escalated blocks at all, and the event's sentiment average exists and stands
    at 4.5 or better, the factor is 0.95 and the direction is `DECREASE`."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_8000_bp_holds_the_ratio
    """
    context = _four_of_five_worked(client)
    event_id = context["event"]["id"]
    advance_event(client, event_id, "CLOSED")

    answer = ok(client.get_staffing_model_recommendation(event_id, DIRECTOR_HEADERS))

    assert_fields(answer, event_id=event_id, understaffed_slot_count=0)
    assert answer["average_score"] is None, (
        "an unsurveyed event reports an absent sentiment average"
    )
    group = answer["position_recommendations"][0]
    assert_fields(group, direction="HOLD", no_show_count=0)
    assert_ratio(group["recommended_ratio_per_1000"], 0.80, "recommended_ratio_per_1000")
    assert group["recommended_ratio_per_1000"] != 0.76, (
        "a null average must not be treated as passing the 4.5 trim floor"
    )


def test_model_refinement_read_requires_a_closed_event(client):
    """The refinement read is refused while the event is still running.

    "It is available to a `GuestExperienceDirector` or a `StaffingCoordinator`,
    requires the event's `status` to be `CLOSED` — otherwise it is refused with
    `ERR_EVENT_STATE_INVALID` — and works from the event's `LOCKED` plan,
    considering that plan's shift blocks other than the `CLOSED` ones."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_8000_bp_holds_the_ratio
    """
    context = _four_of_five_worked(client)
    event_id = context["event"]["id"]

    err(
        client.get_staffing_model_recommendation(event_id, DIRECTOR_HEADERS),
        ERR_EVENT_STATE_INVALID,
    )

    advance_event(client, event_id, "CLOSED")
    answer = ok(client.get_staffing_model_recommendation(event_id, DIRECTOR_HEADERS))
    assert_fields(answer["position_recommendations"][0], fill_rate_bp=8000)
