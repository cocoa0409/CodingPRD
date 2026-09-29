"""Derived numerics at their exact boundaries, and the layered gates that guard them.

The first ten tests walk the arithmetic the PRD fixes to the digit: whole-minute
floors that refuse to round up, a latency kept in seconds, the wake-up window at
120 versus 121 minutes, the two eligibility scores that never overwrite each
other, the open-case count, the report rates over an empty period and the
one-decimal publication rollup.  The last four drive the layered gates - the
stale-version rejections of PRD 2.7 sitting above the overlap and transition
checks of PRD 2.11, the eight-clause routing selector, and the inclusive
three-open-case divert threshold that counts accepted inbound transfers.
"""
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    INTERVAL_TARGETS,
    REPORTED_MEASURE_CODES,
    ROUTING_POSTURE,
    TIER_MULTIPLIER_BY_FACILITY_TYPE,
)
from test_helpers.test_users import (
    ABSTRACTOR,
    ATTESTER,
    COORD,
    ED,
    QUALITY_ABSTRACTOR_USER_ID,
    QUALITY_ATTESTER_USER_ID,
)


# ---------------------------------------------------------------------------
# Instance 1: floors on the minute clocks, seconds on the consult latency
# ---------------------------------------------------------------------------
def _second_resolution_case():
    """A case whose needle lands at :45 seconds past the minute, on a 20-minute onset."""
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    neuro_id = context["neurologist"]["id"]
    case = fx.activate_case(
        context["spoke"]["id"], "2026-09-01T08:00:00Z",
        last_known_well_at="2026-09-01T07:40:00Z",
    )
    fx.complete_imaging(case["id"], at="2026-09-01T08:22:00Z")
    consult = fx.request_consult(
        case["id"], context["agreement"]["id"], at="2026-09-01T08:25:00Z"
    )
    accepted = fx.accept_consult(consult["id"], neuro_id, at="2026-09-01T08:27:20Z")
    fx.append_video_session(
        consult["id"], neuro_id, "2026-09-01T08:27:20Z", "2026-09-01T08:30:25Z"
    )
    completed = fx.complete_consult(consult["id"], neuro_id, at="2026-09-01T08:31:00Z")
    checklist = fx.setup_documented_checklist(case["id"])
    checklist = fx.determine(checklist["id"], neuro_id, at="2026-09-01T08:35:00Z")
    fx.administer(case["id"], at="2026-09-01T08:58:45Z")
    return {
        "case": fx.read_case(case["id"]),
        "accepted": accepted,
        "consult": completed,
        "checklist": checklist,
    }


def test_clock_intervals_floor_to_minutes_while_the_consult_latency_stays_in_seconds():
    """3525 elapsed seconds is 58 minutes, 4725 is 78, and 140 seconds stays 140.

    PRD 2.6: "Zero elapsed seconds therefore yields 0 minutes rather than null; 59 seconds yields 0 minutes; 60 seconds yields 1 minute; 119 seconds yields 1 minute."
    PRD 2.6: "One elapsed quantity is deliberately not floored to minutes: a consult's `response_latency_seconds` is the elapsed count of whole seconds between the request and the acceptance, kept at second resolution."
    PRD 3.3: "`response_latency_seconds` is computed as the whole seconds elapsed from `requested_at` to `accepted_at`"

    Design: Corner/calculations/clock_interval_metrics_floors_minutes_but_keeps_latency_in_seconds
    """
    built = _second_resolution_case()
    case = built["case"]
    accepted = built["accepted"]

    assert a.instants_equal(case["needle_at"], "2026-09-01T08:58:45Z"), (
        f"the drug is given at 45 seconds past 08:58, got {case['needle_at']}"
    )
    assert case["door_to_imaging_minutes"] == 22, (
        f"08:00:00 to 08:22:00 is 22 whole minutes, got {case['door_to_imaging_minutes']}"
    )
    assert case["door_to_needle_minutes"] == 58, (
        "3525 elapsed seconds floors to 58 minutes and must not round up to 59, got "
        f"{case['door_to_needle_minutes']}"
    )
    assert case["lkw_to_needle_minutes"] == 78, (
        "4725 elapsed seconds floors to 78 minutes and must not round up to 79, got "
        f"{case['lkw_to_needle_minutes']}"
    )
    a.assert_case_clock_intervals(case)

    assert a.instants_equal(accepted["requested_at"], "2026-09-01T08:25:00Z"), (
        f"the request instant anchors the latency, got {accepted['requested_at']}"
    )
    assert a.instants_equal(accepted["accepted_at"], "2026-09-01T08:27:20Z"), (
        f"the acceptance instant closes it, got {accepted['accepted_at']}"
    )
    assert accepted["response_latency_seconds"] == 140, (
        "two minutes and twenty seconds is 140 seconds, never 2 minutes, got "
        f"{accepted['response_latency_seconds']}"
    )
    assert accepted["response_latency_seconds"] <= INTERVAL_TARGETS["TELESTROKE_RESPONSE_TARGET_SEC"]

    assert built["consult"]["status"] == "COMPLETED"
    assert built["checklist"]["determination_status"] == "ELIGIBLE", (
        f"four items and no contraindications inside 3 hours are eligible, got "
        f"{built['checklist']['determination_status']}"
    )
    assert case["thrombolytic_window_class"] == "WITHIN_3H", (
        "78 minutes from last known well is well inside the standard window, got "
        f"{case['thrombolytic_window_class']}"
    )
    assert case["status"] == "THROMBOLYSIS_ADMINISTERED"
    assert case["disposition"] == "TREATED_LOCAL"
    assert case["deviation_count"] == 0, (
        "a 22-minute scan and a 58-minute needle deviate from nothing, got "
        f"{case['deviation_count']}"
    )
    assert fx.list_case_deviations(case["id"]) == [], "no deviation of any type exists"


# ---------------------------------------------------------------------------
# Instance 2: roster rank first, then the concurrent-consult limit
# ---------------------------------------------------------------------------
def _three_rank_roster():
    """Hub roster of three board-certified, on-call neurologists at ranks 10, 20 and 30."""
    context = fx.setup_network(
        clock="2026-09-01T08:00:00Z",
        max_concurrent_consults=3,
        neurologists=[
            {"roster_rank": 10, "concurrent_consult_limit": 2},
            {"roster_rank": 20, "concurrent_consult_limit": 2},
            {"roster_rank": 30, "concurrent_consult_limit": 2},
        ],
    )
    spoke_id = context["spoke"]["id"]
    cases = [
        fx.activate_case(spoke_id, "2026-09-01T08:00:00Z"),
        fx.activate_case(spoke_id, "2026-09-01T08:01:00Z"),
        fx.activate_case(spoke_id, "2026-09-01T08:02:00Z"),
    ]
    for index, case in enumerate(cases):
        fx.complete_imaging(case["id"], at=f"2026-09-01T08:1{index}:00Z")
    context["cases"] = cases
    return context


def test_routing_takes_rank_ten_twice_then_drops_him_at_his_concurrent_limit():
    """Rank 10 wins the first two consults and is filtered out of the third.

    PRD 3.3: "Their `active_consult_count` is strictly less than their `concurrent_consult_limit`."
    PRD 3.3: "The surviving candidates are ordered by `roster_rank` ascending, then by `active_consult_count` ascending, then by `completed_consult_count` ascending, and finally by `created_at` ascending, and the first is taken."

    Design: Corner/calculations/routing_ranks_by_roster_then_drops_a_neurologist_at_his_limit
    """
    context = _three_rank_roster()
    rank10, rank20, rank30 = context["neurologists"]
    cases = context["cases"]
    agreement_id = context["agreement"]["id"]

    first = fx.request_consult(cases[0]["id"], agreement_id, at="2026-09-01T08:20:00Z")
    assert first["assigned_neurologist_id"] == rank10["id"], (
        "the lowest roster_rank is considered first, got "
        f"{first['assigned_neurologist_id']}"
    )
    assert first["status"] == "ASSIGNED"
    assert fx.read_neurologist(rank10["id"])["active_consult_count"] == 1

    second = fx.request_consult(cases[1]["id"], agreement_id, at="2026-09-01T08:21:00Z")
    assert second["assigned_neurologist_id"] == rank10["id"], (
        "rank 10 still holds one of his two slots, so rank wins again over an idle "
        f"rank 20, got {second['assigned_neurologist_id']}"
    )
    mid = fx.read_neurologist(rank10["id"])
    assert mid["active_consult_count"] == 2, (
        f"two ASSIGNED consults sit on rank 10, got {mid['active_consult_count']}"
    )
    assert mid["on_call_state"] == "ON_CALL", (
        f"assignment alone never moves the on-call state, got {mid['on_call_state']}"
    )

    third = fx.request_consult(cases[2]["id"], agreement_id, at="2026-09-01T08:22:00Z")
    assert third["status"] == "ASSIGNED", (
        f"the pool is not empty, so nothing escalates, got {third['status']}"
    )
    assert third["assigned_neurologist_id"] == rank20["id"], (
        "clause 3 drops rank 10 at 2 of 2, handing the consult to rank 20 rather than "
        f"rank 30, got {third['assigned_neurologist_id']}"
    )
    assert third["routing_attempt_count"] == 1, (
        f"one selector pass produced the assignment, got {third['routing_attempt_count']}"
    )

    assert fx.read_neurologist(rank10["id"])["active_consult_count"] == 2
    assert fx.read_neurologist(rank20["id"])["active_consult_count"] == 1
    assert fx.read_neurologist(rank30["id"])["active_consult_count"] == 0, (
        "rank 30 is never reached while a lower rank still has room"
    )
    assert fx.read_agreement(context["agreement"]["id"])["active_consult_count"] == 3, (
        "three live consults sit on the agreement, filling its ceiling exactly"
    )


# ---------------------------------------------------------------------------
# Instance 3: the wake-up window at 120 and at 121 minutes
# ---------------------------------------------------------------------------
def _wake_up_pair():
    """Two wake-up cases whose determinations land at door+120 and door+121 minutes."""
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    neuro_id = context["neurologist"]["id"]
    spoke_id = context["spoke"]["id"]

    early = fx.activate_case(spoke_id, "2026-09-01T08:00:00Z", lkw_precision="UNKNOWN_WAKE_UP")
    fx.run_consult_to_completed(
        early["id"], context["agreement"]["id"], neuro_id,
        requested_at="2026-09-01T08:00:00Z",
    )
    early_checklist = fx.setup_documented_checklist(early["id"])

    late = fx.activate_case(spoke_id, "2026-09-01T09:00:00Z", lkw_precision="UNKNOWN_WAKE_UP")
    fx.run_consult_to_completed(
        late["id"], context["agreement"]["id"], neuro_id,
        requested_at="2026-09-01T09:00:00Z",
    )
    late_checklist = fx.setup_documented_checklist(late["id"])

    early_checklist = fx.determine(early_checklist["id"], neuro_id, at="2026-09-01T10:00:00Z")
    late_checklist = fx.determine(late_checklist["id"], neuro_id, at="2026-09-01T11:01:00Z")
    return {
        "context": context,
        "early_case": fx.read_case(early["id"]),
        "late_case": fx.read_case(late["id"]),
        "early_checklist": early_checklist,
        "late_checklist": late_checklist,
    }


def test_wake_up_window_flips_between_one_hundred_twenty_and_one_hundred_twenty_one_minutes():
    """Door+120 penalises 15 points; door+121 penalises 100 and clamps the score to zero.

    PRD 3.2: "Exactly 120 minutes yields `EXTENDED_UNKNOWN` and exactly 121 yields `OUT_OF_WINDOW`. A wake-up case never yields `WITHIN_3H` or `WITHIN_4_5H`, no matter how recently the patient arrived."
    PRD 3.2: "For a case whose `lkw_precision` is `UNKNOWN_WAKE_UP`, the last-known-well axis is abandoned entirely and the classification is made on door elapsed time instead."
    PRD 3.5: "it subtracts a window penalty read off the case's `thrombolytic_window_class` — 0.0 for `WITHIN_3H`, 8.0 for `WITHIN_4_5H`, 15.0 for `EXTENDED_UNKNOWN`, 100.0 for `OUT_OF_WINDOW`"

    Design: Corner/calculations/wake_up_stroke_window_flips_at_exactly_one_hundred_twenty_minutes
    """
    built = _wake_up_pair()
    early_case, late_case = built["early_case"], built["late_case"]
    early, late = built["early_checklist"], built["late_checklist"]

    assert early_case["last_known_well_at"] is None, (
        "a wake-up onset is never witnessed, so the field stays null, got "
        f"{early_case['last_known_well_at']}"
    )
    assert early_case["thrombolytic_window_class"] == "EXTENDED_UNKNOWN", (
        "exactly 120 whole minutes of door elapsed time is still extended, got "
        f"{early_case['thrombolytic_window_class']}"
    )
    assert early["screening_eligibility_score"] == 60.00, (
        f"four inclusion items screen at 60.00, got {early['screening_eligibility_score']}"
    )
    assert early["attested_eligibility_score"] == 51.00, (
        "60.00 minus the 15.00 extended-window penalty plus 6.00 of board credit is "
        f"51.00, got {early['attested_eligibility_score']}"
    )
    assert early["attested_eligibility_score"] == a.expected_attested_score(
        4, 0, 0, "EXTENDED_UNKNOWN", True
    )
    a.assert_two_decimal_places(early["attested_eligibility_score"], "attested_eligibility_score")
    assert early["determination_status"] == "INELIGIBLE", (
        "51.00 is under the 55.0 eligible floor with no relative override available, got "
        f"{early['determination_status']}"
    )
    assert early_case["disposition"] == "NO_TREATMENT", (
        f"an ineligible verdict dispositions the case, got {early_case['disposition']}"
    )

    assert late_case["thrombolytic_window_class"] == "OUT_OF_WINDOW", (
        "one minute past 120 abandons the window entirely, got "
        f"{late_case['thrombolytic_window_class']}"
    )
    assert late["screening_eligibility_score"] == 60.00, (
        "the screening figure knows nothing of the window, got "
        f"{late['screening_eligibility_score']}"
    )
    assert late["attested_eligibility_score"] == 0.00, (
        "60.00 − 100.00 + 6.00 is −34.0 raw and clamps to 0.00 before rounding, got "
        f"{late['attested_eligibility_score']}"
    )
    assert late["attested_eligibility_score"] == a.expected_attested_score(
        4, 0, 0, "OUT_OF_WINDOW", True
    )
    assert late["determination_status"] == "INELIGIBLE"
    for checklist in (early, late):
        assert checklist["overridden_by_neurologist_id"] is None, (
            "no override was involved on either verdict"
        )


# ---------------------------------------------------------------------------
# Instance 4: the imaging deviation at 45 and at 46 minutes
# ---------------------------------------------------------------------------
def test_door_to_imaging_deviation_fires_at_forty_six_but_not_at_forty_five():
    """Forty-five minutes is on target; the forty-sixth minute opens a minor deviation.

    PRD 3.6: "Whenever `door_to_imaging_minutes` comes out greater than 45, a system-detected `ProtocolDeviation` of type `DTI_EXCEEDED` and severity `MINOR` is opened on the case and its `deviation_count` rises by 1. Exactly 45 minutes raises nothing; 46 does."
    PRD 3.8: "Deviations synthesised by the cascades described throughout §3 are identical rows except that their `source` is `SYSTEM_DETECTED` and their `opened_by_user_id` is the literal string `system`."

    Design: Corner/calculations/door_to_imaging_deviation_fires_at_forty_six_but_not_at_forty_five
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    spoke_id = context["spoke"]["id"]

    on_target = fx.activate_case(spoke_id, "2026-09-01T08:00:00Z")
    on_target = fx.complete_imaging(on_target["id"], at="2026-09-01T08:45:00Z")
    late = fx.activate_case(spoke_id, "2026-09-01T09:00:00Z")
    late = fx.complete_imaging(late["id"], at="2026-09-01T09:46:00Z")

    assert on_target["door_to_imaging_minutes"] == 45, (
        f"08:00 to 08:45 is exactly the target, got {on_target['door_to_imaging_minutes']}"
    )
    assert on_target["door_to_imaging_minutes"] == INTERVAL_TARGETS["DTI_TARGET_MIN"]
    assert on_target["deviation_count"] == 0, (
        "the comparison is strictly greater than 45, so 45 raises nothing, got "
        f"{on_target['deviation_count']}"
    )
    assert fx.list_case_deviations(on_target["id"]) == [], (
        "no deviation row exists on the on-target case"
    )
    on_target_page, on_target_meta = validate_paginated(
        api_client.list_deviations(ED, {"case_id": on_target["id"], "limit": 100, "offset": 0})
    )
    assert on_target_meta["total_count"] == 0, (
        f"the filtered result set is empty, got {on_target_meta['total_count']}"
    )
    assert on_target_page == []

    assert late["door_to_imaging_minutes"] == 46, (
        f"09:00 to 09:46 is one minute over target, got {late['door_to_imaging_minutes']}"
    )
    assert late["deviation_count"] == 1, (
        f"the forty-sixth minute raises exactly one deviation, got {late['deviation_count']}"
    )
    late_page, late_meta = validate_paginated(
        api_client.list_deviations(ED, {"case_id": late["id"], "limit": 100, "offset": 0})
    )
    assert late_meta["total_count"] == 1, (
        f"exactly one deviation row is discoverable, got {late_meta['total_count']}"
    )
    deviation = late_page[0]
    a.assert_system_detected_deviation(deviation, "DTI_EXCEEDED", "MINOR")
    assert deviation["opened_by_user_id"] == "system", (
        f"a synthesised row is opened by the literal 'system', got {deviation['opened_by_user_id']}"
    )
    assert deviation["status"] == "OPEN", (
        f"the row starts its review loop unopened, got {deviation['status']}"
    )
    assert deviation["case_id"] == late["id"]


# ---------------------------------------------------------------------------
# Instance 5: the two eligibility scores live side by side
# ---------------------------------------------------------------------------
_OVERRIDE_NOTE = "relative risk accepted after attending discussion with family"


def test_the_determination_writes_the_attested_score_without_touching_the_screening_one():
    """Screening stays 48.00 while the determination writes an attested 54.00.

    PRD 3.5: "The two fields never overwrite each other: a determination writes `attested_eligibility_score` and leaves `screening_eligibility_score` exactly as the last documentation write left it"
    PRD 3.5: "otherwise if `relative_contraindication_count` is 1 or more, the attested score is 40.0 or higher and an `override_justification` was supplied, the verdict is `ELIGIBLE_WITH_RELATIVE_OVERRIDE`"
    PRD 3.5: "A successful determination sets `documentation_status` to `DOCUMENTED`, writes the verdict into `determination_status`, stamps `determined_at` from the logical clock"

    Design: Corner/calculations/eligibility_scores_are_stored_to_two_decimals_and_never_overwrite_each_other
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    neuro_id = context["neurologist"]["id"]
    built = fx.setup_case_with_completed_consult(context, "2026-09-01T08:00:00Z")
    checklist = fx.setup_documented_checklist(
        built["case"]["id"], relative_contraindications=1
    )

    assert checklist["relative_contraindication_count"] == 1
    assert checklist["absolute_contraindication_count"] == 0
    assert checklist["confirmed_inclusion_item_count"] == 4
    assert checklist["screening_eligibility_score"] == 48.00, (
        "four items at 15.0 less one relative at 12.0 is 48.00, got "
        f"{checklist['screening_eligibility_score']}"
    )
    assert checklist["screening_eligibility_score"] == a.expected_screening_score(4, 1, 0)
    a.assert_two_decimal_places(checklist["screening_eligibility_score"], "screening_eligibility_score")
    assert checklist["attested_eligibility_score"] is None, (
        "the attested figure exists only from the determination onward, got "
        f"{checklist['attested_eligibility_score']}"
    )
    assert checklist["determination_status"] == "PENDING"

    determined = fx.determine(
        checklist["id"], neuro_id,
        at="2026-09-01T08:30:00Z", override_justification=_OVERRIDE_NOTE,
    )

    assert determined["attested_eligibility_score"] == 54.00, (
        "48.00 with no window penalty plus 6.00 of board credit is 54.00, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["attested_eligibility_score"] == a.expected_attested_score(
        4, 1, 0, "WITHIN_3H", True
    )
    a.assert_two_decimal_places(determined["attested_eligibility_score"], "attested_eligibility_score")
    assert determined["screening_eligibility_score"] == 48.00, (
        "the determination must not overwrite the bedside screening figure, got "
        f"{determined['screening_eligibility_score']}"
    )
    assert determined["determination_status"] == "ELIGIBLE_WITH_RELATIVE_OVERRIDE", (
        "54.00 is under 55.0 but at or over 40.0 with one relative and a justification, "
        f"got {determined['determination_status']}"
    )
    assert determined["documentation_status"] == "DOCUMENTED"
    assert determined["overridden_by_neurologist_id"] == neuro_id, (
        "the override records the attesting neurologist, got "
        f"{determined['overridden_by_neurologist_id']}"
    )
    assert determined["override_justification"] == _OVERRIDE_NOTE
    assert a.instants_equal(determined["determined_at"], "2026-09-01T08:30:00Z"), (
        f"the determination is stamped from the logical clock, got {determined['determined_at']}"
    )
    a.assert_thrombolytic_checklist(determined)

    case = fx.read_case(built["case"]["id"])
    assert case["status"] == "ELIGIBILITY_DETERMINED"
    assert case["disposition"] == "PENDING", (
        f"an override verdict is not a no-treatment verdict, got {case['disposition']}"
    )


# ---------------------------------------------------------------------------
# Instance 6: the open-case count counts only the non-terminal cases
# ---------------------------------------------------------------------------
def test_aborting_the_middle_case_lowers_the_open_count_and_brings_the_posture_back():
    """Three open cases divert; aborting one recomputes the count and the posture downward.

    PRD 2.8: "A facility's `open_case_count` is the number of `CodeStrokeCase` records whose `center_id` names that facility and whose `status` is anything other than `CLOSED` or `ABORTED`, plus the number of `TransferDecision` records whose `destination_center_id` names that facility and whose `status` is `ACCEPTED`."
    PRD 2.9: "Because the open-case threshold is inclusive at 3, a certified and fully ready facility holding exactly 2 open cases is `ROUTINE` and the same facility holding exactly 3 is `DIVERT_ADVISORY`; closing the third case drops the count back to 2 and returns the posture to `ROUTINE` inside the very same request."
    PRD 3.8: "The case's `status` becomes `ABORTED` and its `disposition` `NO_TREATMENT`"

    Design: Corner/calculations/open_case_count_counts_only_non_terminal_cases
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    spoke = fx.register_spoke()
    assert spoke["open_case_count"] == 0
    assert spoke["ems_routing_posture"] == "ROUTINE"

    first = fx.activate_case(spoke["id"], "2026-09-01T08:00:00Z")
    middle = fx.activate_case(spoke["id"], "2026-09-01T08:05:00Z")
    last = fx.activate_case(spoke["id"], "2026-09-01T08:10:00Z")

    crowded = fx.read_center(spoke["id"])
    assert crowded["open_case_count"] == 3, (
        f"three ACTIVATED cases are three open cases, got {crowded['open_case_count']}"
    )
    assert crowded["open_case_count"] == ROUTING_POSTURE["OPEN_CASE_DIVERT_THRESHOLD"]
    assert crowded["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "the threshold is inclusive at three, got "
        f"{crowded['ems_routing_posture']}"
    )
    a.assert_ems_routing_posture(crowded)

    aborted = fx.abort_case(middle["id"], at="2026-09-01T08:20:00Z")
    assert aborted["status"] == "ABORTED"
    assert aborted["disposition"] == "NO_TREATMENT", (
        f"an aborted case treats nobody, got {aborted['disposition']}"
    )

    relieved = fx.read_center(spoke["id"])
    assert relieved["open_case_count"] == 2, (
        "the aborted row leaves the count because ABORTED is terminal, got "
        f"{relieved['open_case_count']}"
    )
    assert relieved["ems_routing_posture"] == "ROUTINE", (
        "the posture is derived rather than latched, so it comes back down, got "
        f"{relieved['ems_routing_posture']}"
    )
    a.assert_ems_routing_posture(relieved)

    still_open = fx.read_case(first["id"])
    assert still_open["status"] == "ACTIVATED", "the untouched cases stay open"
    assert fx.read_case(last["id"])["status"] == "ACTIVATED"
    assert fx.read_case(middle["id"])["status"] == "ABORTED", (
        "the terminal row is still readable, it is only no longer counted"
    )

    all_rows, all_meta = validate_paginated(
        api_client.list_code_strokes(ED, {"center_id": spoke["id"], "limit": 100, "offset": 0})
    )
    assert all_meta["total_count"] == 3, (
        f"all three case records survive the abort, got {all_meta['total_count']}"
    )
    assert len(all_rows) == 3
    terminal_rows, terminal_meta = validate_paginated(
        api_client.list_code_strokes(
            ED, {"center_id": spoke["id"], "status": "ABORTED", "limit": 100, "offset": 0}
        )
    )
    assert terminal_meta["total_count"] == 1, (
        "the two filters combine conjunctively down to the one aborted row, got "
        f"{terminal_meta['total_count']}"
    )
    assert [row["id"] for row in terminal_rows] == [middle["id"]]


# ---------------------------------------------------------------------------
# Instance 7: the telestroke numerator at 300 and at 301 seconds
# ---------------------------------------------------------------------------
def _latency_pair():
    """Two completed consults answered in exactly 300 and in 301 seconds."""
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    neuro_id = context["neurologist"]["id"]
    spoke_id = context["spoke"]["id"]

    on_target = fx.activate_case(spoke_id, "2026-09-01T08:14:00Z")
    on_target_consult = fx.run_consult_to_completed(
        on_target["id"], context["agreement"]["id"], neuro_id,
        requested_at="2026-09-01T08:14:00Z", accept_after_seconds=300, session_seconds=240,
    )
    late = fx.activate_case(spoke_id, "2026-09-01T09:14:00Z")
    late_consult = fx.run_consult_to_completed(
        late["id"], context["agreement"]["id"], neuro_id,
        requested_at="2026-09-01T09:14:00Z", accept_after_seconds=301, session_seconds=240,
    )

    fx.set_clock("2026-09-01T09:40:00Z")
    return {
        "on_target_case": on_target,
        "late_case": late,
        "on_target_consult": on_target_consult,
        "late_consult": late_consult,
        "on_target_abstraction": fx.create_abstraction(
            on_target["id"], "STK_TELESTROKE_RESPONSE"
        ),
        "late_abstraction": fx.create_abstraction(late["id"], "STK_TELESTROKE_RESPONSE"),
    }


def test_telestroke_numerator_flips_between_three_hundred_and_three_hundred_one_seconds():
    """One second past the target loses the numerator without losing the denominator.

    PRD 3.9: "Exactly 300 seconds with a valid session passes; 301 fails."
    PRD 3.9: "`STK_TELESTROKE_RESPONSE` requires some consult on the case whose `status` is `COMPLETED`, whose `response_latency_seconds` is non-null and 300 or less, and whose `valid_video_session_count` is 1 or more."
    PRD 3.9: "is created with `status` `DRAFT`, `variant` `PROVISIONAL`, `abstracted_by_user_id` from the caller's identity header, and a null `attested_by_user_id`, `attestation_note` and `retraction_reason`."

    Design: Corner/calculations/telestroke_response_numerator_flips_between_three_hundred_and_three_oh_one_seconds
    """
    built = _latency_pair()
    on_target_consult = built["on_target_consult"]
    late_consult = built["late_consult"]

    assert on_target_consult["response_latency_seconds"] == 300, (
        "08:14:00 to 08:19:00 is exactly 300 seconds, got "
        f"{on_target_consult['response_latency_seconds']}"
    )
    assert late_consult["response_latency_seconds"] == 301, (
        "09:14:00 to 09:19:01 is 301 seconds, and the extra second is not floored away, "
        f"got {late_consult['response_latency_seconds']}"
    )
    for consult in (on_target_consult, late_consult):
        assert consult["status"] == "COMPLETED"
        assert consult["valid_video_session_count"] == 1, (
            "the video gate is part of the numerator, so each consult carries one valid "
            f"session, got {consult['valid_video_session_count']}"
        )

    on_target = built["on_target_abstraction"]
    late = built["late_abstraction"]
    assert on_target["numerator_flag"] is True, (
        "300 is on the inclusive side of the 300-second target"
    )
    assert late["numerator_flag"] is False, (
        "301 fails the measure even though the session was valid"
    )
    for abstraction in (on_target, late):
        assert abstraction["measure_code"] == "STK_TELESTROKE_RESPONSE"
        assert abstraction["status"] == "DRAFT"
        assert abstraction["variant"] == "PROVISIONAL", (
            f"a fresh draft is provisional, got {abstraction['variant']}"
        )
        assert abstraction["exclusion_reason"] == "NONE", (
            "neither case is aborted, out of window or transfer-only, got "
            f"{abstraction['exclusion_reason']}"
        )
        assert abstraction["denominator_included"] is True, (
            "a late answer is a denominator member that misses the numerator"
        )
        assert abstraction["abstracted_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID
        assert abstraction["attested_by_user_id"] is None
        assert abstraction["attestation_note"] is None
        assert abstraction["report_id"] is None, (
            f"no report exists to attach to, got {abstraction['report_id']}"
        )
        a.assert_quality_measure_abstraction(abstraction)

    rows, meta = validate_paginated(
        api_client.list_abstractions(
            ABSTRACTOR,
            {"measure_code": "STK_TELESTROKE_RESPONSE", "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 2, (
        f"both rows are discoverable by measure, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {on_target["id"], late["id"]}
    for case_id in (built["on_target_case"]["id"], built["late_case"]["id"]):
        assert fx.read_case(case_id)["status"] == "CONSULT_IN_PROGRESS", (
            "abstraction begins while the case is still live"
        )


# ---------------------------------------------------------------------------
# Instance 8: an empty reporting period
# ---------------------------------------------------------------------------
def test_an_empty_reporting_period_yields_zero_rates_and_a_null_excess_mean():
    """Zero denominators give 0.00 rates, but an empty excess population gives null.

    PRD 3.9: "When the denominator is 0 the rate is **0.00** — never null, and never 100.00 on the reasoning that nothing failed."
    PRD 2.6: "a report whose `mean_dtn_excess_pct` is null had no eligible cases at all, which is a different fact from a report whose mean excess was `0.00`"
    PRD 3.9: "The create returns 201 with `status` `DRAFT`, `rate_variant` `PROVISIONAL`, `decision` `PENDING`, and null `submitted_by_user_id`, `decided_by_user_id`, `superseded_by_report_id`, `submitted_at`, `decided_at` and `published_at`."
    PRD 3.9: "leaves `composite_certification_score` at 0.00 — the composite is produced at submission and nowhere else"

    Design: Corner/calculations/an_empty_reporting_period_yields_zero_rates_and_a_null_excess_mean
    """
    fx.set_clock("2026-10-01T09:00:00Z")
    spoke = fx.register_spoke()
    assert spoke["version"] == 1, (
        f"a freshly registered facility is at version 1, got {spoke['version']}"
    )

    report = fx.create_report(
        spoke["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        expected_center_version=1,
    )

    assert report["status"] == "DRAFT"
    assert report["rate_variant"] == "PROVISIONAL"
    assert report["decision"] == "PENDING"
    assert report["included_abstraction_count"] == 0, (
        f"nothing was ever abstracted here, got {report['included_abstraction_count']}"
    )
    assert report["closed_case_count_in_period"] == 0, (
        f"no case ever closed here, got {report['closed_case_count_in_period']}"
    )
    for field in (
        "dtn_60_compliance_pct", "dti_45_compliance_pct", "telestroke_response_compliance_pct"
    ):
        assert report[field] == 0.00, (
            f"an empty denominator stores 0.00 rather than null or 100.00 for {field}, "
            f"got {report[field]}"
        )
        assert report[field] == a.expected_rate(0, 0)
        a.assert_two_decimal_places(report[field], field)
    assert report["mean_dtn_excess_pct"] is None, (
        "an empty excess population is null, which is a different fact from 0.00, got "
        f"{report['mean_dtn_excess_pct']}"
    )
    assert a.expected_mean_dtn_excess_pct([]) is None
    assert report["substantiated_major_count"] == 0
    assert report["substantiated_sentinel_count"] == 0
    assert report["composite_certification_score"] == 0.00, (
        "the composite is produced at submission and nowhere else, got "
        f"{report['composite_certification_score']}"
    )
    for field in (
        "submitted_by_user_id", "decided_by_user_id", "superseded_by_report_id",
        "submitted_at", "decided_at", "published_at",
    ):
        assert report[field] is None, f"{field} is null on a fresh draft, got {report[field]}"
    a.assert_certification_report(report)

    after = fx.read_center(spoke["id"])
    assert after["version"] == 2, (
        f"the create raises the facility's version by exactly 1, got {after['version']}"
    )
    assert after["public_dtn_compliance_pct"] is None, (
        "creating a report publishes nothing"
    )


# ---------------------------------------------------------------------------
# Instance 9: the variant switch at finalisation
# ---------------------------------------------------------------------------
def _transfer_only_abstraction():
    """A transfer-only case carrying a DRAFT STK_DTI_45 abstraction opened while it was live."""
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    destination = fx.register_thrombectomy_center()
    built = fx.setup_eligible_case(context, "2026-09-01T08:00:00Z", dti_minutes=10)
    case_id = built["case"]["id"]
    transfer = fx.propose_transfer(
        case_id, destination["id"],
        mode="TRANSFER_ONLY", transport_eta_minutes=30, at="2026-09-01T08:30:00Z",
    )
    fx.set_clock("2026-09-01T08:35:00Z")
    abstraction = fx.create_abstraction(case_id, "STK_DTI_45")
    return {
        "context": context,
        "case": fx.read_case(case_id),
        "checklist": built["checklist"],
        "transfer": transfer,
        "abstraction": abstraction,
        "destination": destination,
    }


def test_finalisation_switches_the_variant_and_applies_the_recorded_transfer_only_exclusion():
    """The draft records TRANSFER_ONLY while still counting; finalisation applies it.

    PRD 3.9: "Under the `PROVISIONAL` variant — which applies at create and for as long as the row stays `DRAFT` — `numerator_flag` and `exclusion_reason` are computed as above, but `denominator_included` is set true **unconditionally**."
    PRD 3.9: "Finalising that same transfer-only row flips `denominator_included` to false without changing `exclusion_reason`."
    PRD 3.9: "It sets `status` `FINALIZED`, `variant` `CERTIFIED` and `attested_by_user_id`, re-evaluates the numerator, exclusion and denominator under the certified variant"

    Design: Corner/calculations/abstraction_variant_switches_at_finalisation_and_drops_the_excluded_denominator
    """
    built = _transfer_only_abstraction()
    draft = built["abstraction"]
    case_id = built["case"]["id"]

    assert built["checklist"]["determination_status"] == "ELIGIBLE"
    assert built["case"]["status"] == "TRANSFER_INITIATED"
    assert built["case"]["disposition"] == "TRANSFER_ONLY", (
        f"the unlysed patient is shipped, got {built['case']['disposition']}"
    )
    assert built["case"]["needle_at"] is None, "a transfer-only mode requires a null needle"
    assert built["case"]["door_to_imaging_minutes"] == 10

    assert draft["status"] == "DRAFT"
    assert draft["variant"] == "PROVISIONAL"
    assert draft["numerator_flag"] is True, (
        "a 10-minute scan scores the STK_DTI_45 numerator regardless of the exclusion"
    )
    assert draft["exclusion_reason"] == "TRANSFER_ONLY", (
        f"the disposition fires clause 4 of the exclusion ladder, got {draft['exclusion_reason']}"
    )
    assert draft["denominator_included"] is True, (
        "the provisional variant records the exclusion without applying it, got "
        f"{draft['denominator_included']}"
    )
    assert draft["abstracted_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID
    assert draft["attested_by_user_id"] is None
    assert draft["case_id"] == case_id

    fx.accept_transfer(built["transfer"]["id"], at="2026-09-01T08:40:00Z")
    settled = fx.complete_handoff(
        built["transfer"]["id"], mode="TRANSFER_ONLY", at="2026-09-01T09:00:00Z"
    )
    assert settled["status"] == "HANDOFF_COMPLETE"
    closed = fx.read_case(case_id)
    assert closed["status"] == "CLOSED"
    assert closed["disposition"] == "TRANSFER_ONLY", (
        f"the closed case keeps the disposition its mode gave it, got {closed['disposition']}"
    )

    fx.set_clock("2026-09-01T09:05:00Z")
    finalized = fx.finalize_abstraction(draft["id"], headers=ATTESTER)

    assert finalized["status"] == "FINALIZED"
    assert finalized["variant"] == "CERTIFIED", (
        f"finalisation switches the variant, got {finalized['variant']}"
    )
    assert finalized["exclusion_reason"] == "TRANSFER_ONLY", (
        "the exclusion reason is unchanged by the flip, got "
        f"{finalized['exclusion_reason']}"
    )
    assert finalized["denominator_included"] is False, (
        "the certified variant includes the row only when the exclusion is NONE, got "
        f"{finalized['denominator_included']}"
    )
    assert finalized["numerator_flag"] is True, (
        "the numerator is re-evaluated to the same answer, got "
        f"{finalized['numerator_flag']}"
    )
    assert finalized["attested_by_user_id"] == QUALITY_ATTESTER_USER_ID, (
        "the attester is a second identity, per the segregation barrier, got "
        f"{finalized['attested_by_user_id']}"
    )
    assert finalized["attested_by_user_id"] != finalized["abstracted_by_user_id"]
    assert finalized["attestation_note"] is not None, (
        "finalisation supplies an attestation note"
    )
    assert finalized["report_id"] is None, "no report was ever opened at this facility"
    a.assert_quality_measure_abstraction(finalized)


# ---------------------------------------------------------------------------
# Instance 10: 66.67 stored, 66.7 published
# ---------------------------------------------------------------------------
def _three_case_spoke_report():
    """A SPOKE with three closed cases at 50, 55 and 70 minutes to the needle."""
    return fx.setup_report_scenario(
        period_start="2026-09-01T00:00:00Z",
        period_days=30,
        cases=[
            {
                "dtn_minutes": dtn, "dti_minutes": 10,
                "measures": REPORTED_MEASURE_CODES, "accept_after_seconds": 120,
            }
            for dtn in (50, 55, 70)
        ],
    )


def test_publication_rounds_the_stored_two_decimal_rate_to_one_decimal():
    """Two of three needles on target store 66.67 and publish 66.7.

    PRD 3.9: "so 100.00 publishes as 100.0, 66.67 as 66.7, and 33.33 as 33.3"
    PRD 3.9: "`public_dtn_compliance_pct` is set to this report's stored `dtn_60_compliance_pct` rounded to **one** decimal place half up, and `public_report_published_at` is set to the logical clock."
    PRD 2.6: "The single exception in the whole system is a facility's `public_dtn_compliance_pct`, which is published at 1 decimal place, rounded half up, and derived from an already-rounded 2-decimal input."
    PRD 3.9: "Then average those whole percents and round the average to two decimals half up."

    Design: Corner/calculations/publication_rounds_the_stored_two_decimal_rate_to_one_decimal
    """
    scenario = _three_case_spoke_report()
    center_id = scenario["center"]["id"]
    draft = scenario["report"]

    assert draft["status"] == "DRAFT"
    assert draft["rate_variant"] == "PROVISIONAL"
    assert draft["included_abstraction_count"] == 9, (
        "three measures on each of three closed cases, got "
        f"{draft['included_abstraction_count']}"
    )
    assert draft["closed_case_count_in_period"] == 3
    assert draft["dtn_60_compliance_pct"] == 66.67, (
        f"2 of 3 needles inside 60 minutes is 66.67, got {draft['dtn_60_compliance_pct']}"
    )
    assert draft["dtn_60_compliance_pct"] == a.expected_rate(2, 3)
    assert draft["dti_45_compliance_pct"] == 100.00, (
        f"every scan landed in 10 minutes, got {draft['dti_45_compliance_pct']}"
    )
    assert draft["telestroke_response_compliance_pct"] == 100.00, (
        "every consult was answered in 120 seconds with a valid session, got "
        f"{draft['telestroke_response_compliance_pct']}"
    )
    assert draft["mean_dtn_excess_pct"] == 5.67, (
        "per-case excesses of 0, 0 and 17 average to 5.6667 and store as 5.67, got "
        f"{draft['mean_dtn_excess_pct']}"
    )
    assert draft["mean_dtn_excess_pct"] == a.expected_mean_dtn_excess_pct([50, 55, 70])
    a.assert_two_decimal_places(draft["mean_dtn_excess_pct"], "mean_dtn_excess_pct")
    assert draft["composite_certification_score"] == 0.00

    slow_case = scenario["cases"][2]["case"]
    assert slow_case["door_to_needle_minutes"] == 70
    slow_deviations = fx.list_case_deviations(slow_case["id"])
    assert len(slow_deviations) == 1, (
        f"the 70-minute needle opened exactly one deviation, got {len(slow_deviations)}"
    )
    a.assert_system_detected_deviation(slow_deviations[0], "DTN_EXCEEDED", "MAJOR")
    assert slow_deviations[0]["status"] == "OPEN", (
        "the row was never reviewed, so it cannot be substantiated, got "
        f"{slow_deviations[0]['status']}"
    )

    submitted = fx.submit_report(draft["id"], at="2026-09-01T11:40:00Z")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["rate_variant"] == "CERTIFIED", (
        f"the variant flips from submission onward, got {submitted['rate_variant']}"
    )
    assert submitted["included_abstraction_count"] == 9, (
        "every attached row was already finalised, so nothing is detached, got "
        f"{submitted['included_abstraction_count']}"
    )
    assert submitted["dtn_60_compliance_pct"] == 66.67
    assert submitted["substantiated_major_count"] == 0, (
        "an OPEN deviation is not a substantiated one, got "
        f"{submitted['substantiated_major_count']}"
    )
    assert submitted["composite_certification_score"] == 82.33, (
        "(0.40x66.67 + 0.35x100 + 0.25x100) x 0.95 is 82.3346 and stores as 82.33, got "
        f"{submitted['composite_certification_score']}"
    )
    assert submitted["composite_certification_score"] == a.expected_composite_score(
        66.67, 100.00, 100.00, 0, 0, 9, "SPOKE"
    )
    assert TIER_MULTIPLIER_BY_FACILITY_TYPE["SPOKE"] == 0.95
    a.assert_two_decimal_places(submitted["composite_certification_score"], "composite_certification_score")

    decided = fx.decide_report(submitted["id"], at="2026-09-01T11:45:00Z")
    assert decided["decision"] == "CONDITIONAL", (
        f"82.33 sits between 70.00 and 85.00, got {decided['decision']}"
    )
    assert decided["decision"] == a.expected_decision_for_score(82.33)
    assert decided["status"] == "ACCEPTED"
    assert decided["composite_certification_score"] == 82.33, (
        "the decision re-reads the score rather than recomputing it"
    )
    conditional = fx.read_center(center_id)
    assert conditional["certification_status"] == "CONDITIONAL"
    assert conditional["public_dtn_compliance_pct"] is None, (
        "accepting a report publishes nothing, got "
        f"{conditional['public_dtn_compliance_pct']}"
    )

    published = fx.publish_report(decided["id"], at="2026-09-01T11:50:00Z")
    assert published["status"] == "PUBLISHED"
    assert a.instants_equal(published["published_at"], "2026-09-01T11:50:00Z"), (
        f"publication is stamped from the logical clock, got {published['published_at']}"
    )
    assert published["dtn_60_compliance_pct"] == 66.67, (
        "the report keeps its two-decimal figure, got "
        f"{published['dtn_60_compliance_pct']}"
    )

    rolled_up = fx.read_center(center_id)
    assert rolled_up["public_dtn_compliance_pct"] == 66.7, (
        f"66.67 publishes as one-decimal 66.7, got {rolled_up['public_dtn_compliance_pct']}"
    )
    assert rolled_up["public_dtn_compliance_pct"] == a.expected_public_dtn_compliance_pct(66.67)
    a.assert_one_decimal_place(rolled_up["public_dtn_compliance_pct"], "public_dtn_compliance_pct")
    assert a.instants_equal(rolled_up["public_report_published_at"], "2026-09-01T11:50:00Z")
    assert rolled_up["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "a CONDITIONAL facility is at best on divert advisory however quiet it is, got "
        f"{rolled_up['ems_routing_posture']}"
    )
    assert rolled_up["open_case_count"] == 0, "all three cases closed before the report"
    a.assert_ems_routing_posture(rolled_up)


# ---------------------------------------------------------------------------
# Instance 11: the stale case version the requester's own cascade produced
# ---------------------------------------------------------------------------
def test_the_consult_request_rejects_a_case_version_the_requester_itself_invalidated():
    """Version 1 is stale after imaging, and version 2 is stale after the first consult.

    PRD 2.7: "If that value does not equal the case's current `version`, the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is written."
    PRD 2.5: "`version` (integer): a monotonically increasing counter that begins at 1 on creation and increments by exactly 1 on every mutation of that record."
    PRD 3.3: "A case sitting in `ACTIVATED` or in `IMAGING_COMPLETE` transitions to `CONSULT_IN_PROGRESS`, and that transition increments the case's `version`"

    Design: Corner/cross_cutting_complexity_layers/the_consult_request_rejects_a_case_version_the_requester_itself_invalidated
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    agreement_id = context["agreement"]["id"]
    neuro_id = context["neurologist"]["id"]

    case = fx.activate_case(context["spoke"]["id"], "2026-09-01T08:00:00Z")
    assert case["version"] == 1, (
        f"a freshly activated case is at version 1, got {case['version']}"
    )
    imaged = fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    assert imaged["version"] == 2, (
        f"the imaging write is one mutation, so the version is 2, got {imaged['version']}"
    )
    assert imaged["status"] == "IMAGING_COMPLETE"

    first_refusal = validate_error(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement_id, 1), ED
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
        412,
    )
    assert first_refusal["error_id"] == "ERR_STALE_CASE_VERSION", (
        f"412 rather than a conflict or a shape failure, got {first_refusal['error_id']}"
    )
    inert = fx.read_case(case["id"])
    assert inert["status"] == "IMAGING_COMPLETE", (
        f"nothing is written on a stale-version refusal, got {inert['status']}"
    )
    assert inert["version"] == 2, (
        f"the refusal is not itself a mutation, got {inert['version']}"
    )
    _, empty_meta = validate_paginated(
        api_client.list_consults(ED, {"case_id": case["id"], "limit": 100, "offset": 0})
    )
    assert empty_meta["total_count"] == 0, (
        f"no consult record was created, got {empty_meta['total_count']}"
    )

    consult = validate_success(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement_id, 2), ED
        ),
        201,
    )
    assert consult["status"] == "ASSIGNED"
    assert consult["assigned_neurologist_id"] == neuro_id
    routed = fx.read_case(case["id"])
    assert routed["status"] == "CONSULT_IN_PROGRESS"
    assert routed["version"] == 3, (
        "the routing transition is the bump the next stale requester trips over, got "
        f"{routed['version']}"
    )

    second_refusal = validate_error(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement_id, 2), ED
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
        412,
    )
    assert second_refusal["error_id"] == "ERR_STALE_CASE_VERSION"
    settled = fx.read_case(case["id"])
    assert settled["version"] == 3, (
        f"the second refusal writes nothing either, got {settled['version']}"
    )
    assert fx.read_neurologist(neuro_id)["active_consult_count"] == 1, (
        "the refused request never produced a second assignment, got "
        f"{fx.read_neurologist(neuro_id)['active_consult_count']}"
    )
    rows, meta = validate_paginated(
        api_client.list_consults(ED, {"case_id": case["id"], "limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1, (
        f"exactly one consult exists on the case, got {meta['total_count']}"
    )
    assert rows[0]["id"] == consult["id"]


# ---------------------------------------------------------------------------
# Instance 12: the stale center version outranks the period-overlap check
# ---------------------------------------------------------------------------
_SEPTEMBER_START = "2026-09-01T00:00:00Z"
_SEPTEMBER_END = "2026-10-01T00:00:00Z"
_OCTOBER_END = "2026-11-01T00:00:00Z"


def _two_closed_september_cases():
    """A spoke with two closed, ineligible September cases, each with one finalised row."""
    context = fx.setup_network(clock=_SEPTEMBER_START)
    built = [
        fx.setup_reportable_case(
            context, fx.shift(_SEPTEMBER_START, hours=1 + 2 * index),
            dtn_minutes=None, dti_minutes=20,
        )
        for index in range(2)
    ]
    context["built"] = built
    return context


def test_the_report_create_rejects_a_stale_center_version_ahead_of_the_period_overlap_check():
    """A rename invalidates the cached version, and rule 11 outranks the overlap rule.

    PRD 2.11: "**Stale center version.** `expected_center_version` must equal the referenced facility's current `version` — `ERR_STALE_CENTER_VERSION` (412)."
    PRD 2.11: "the response is determined by the highest-precedence rule violated, not by the order in which an implementation happens to run its checks"
    PRD 2.7: "Note that a successful report create itself increments the center's `version`, which is what makes a second create carrying the same `expected_center_version` fail"
    PRD 3.9: "Any existing `DRAFT` report for the same facility moves to `SUPERSEDED` with its `superseded_by_report_id` pointing at the new report, and every abstraction attached to it is detached by having `report_id` cleared to null."

    Design: Corner/cross_cutting_complexity_layers/the_report_create_rejects_a_stale_center_version_ahead_of_the_period_overlap_check
    """
    context = _two_closed_september_cases()
    center_id = context["spoke"]["id"]
    abstraction_id = context["built"][0]["abstractions"]["STK_DTN_60"]["id"]

    cached_version = fx.read_center(center_id)["version"]
    renamed = validate_success(
        api_client.update_stroke_center(center_id, f.update_center_payload(), COORD)
    )
    assert renamed["version"] == cached_version + 1, (
        "an unrelated rename bumps the facility version by exactly 1, got "
        f"{renamed['version']} against a cached {cached_version}"
    )
    live_version = renamed["version"]

    stale_refusal = validate_error(
        api_client.create_certification_report(
            f.certification_report_payload(
                center_id, _SEPTEMBER_START, _SEPTEMBER_END, cached_version
            ),
            COORD,
        ),
        ApiErrorId.ERR_STALE_CENTER_VERSION.value,
        412,
    )
    assert stale_refusal["error_id"] == "ERR_STALE_CENTER_VERSION"
    assert fx.read_center(center_id)["version"] == live_version, (
        "the refused create is inert, so the version does not move"
    )

    september = validate_success(
        api_client.create_certification_report(
            f.certification_report_payload(
                center_id, _SEPTEMBER_START, _SEPTEMBER_END, live_version
            ),
            COORD,
        ),
        201,
    )
    assert september["status"] == "DRAFT"
    assert september["included_abstraction_count"] == 2, (
        f"one finalised row per closed case, got {september['included_abstraction_count']}"
    )
    assert september["closed_case_count_in_period"] == 2, (
        f"both September doors fall inside the period, got {september['closed_case_count_in_period']}"
    )
    assert fx.read_abstraction(abstraction_id)["report_id"] == september["id"], (
        "the create gathers the finalised rows onto itself"
    )
    bumped_version = fx.read_center(center_id)["version"]
    assert bumped_version == live_version + 1, (
        f"the successful create raises the version by 1, got {bumped_version}"
    )

    layered_refusal = validate_error(
        api_client.create_certification_report(
            f.certification_report_payload(
                center_id, _SEPTEMBER_START, _SEPTEMBER_END, live_version
            ),
            COORD,
        ),
        ApiErrorId.ERR_STALE_CENTER_VERSION.value,
        412,
    )
    assert layered_refusal["error_id"] != ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value, (
        "the identical period also overlaps, but the stale-version rule has the higher "
        f"precedence, got {layered_refusal['error_id']}"
    )
    assert fx.read_report(september["id"])["status"] == "DRAFT", (
        "the refused second create supersedes nothing"
    )

    october = validate_success(
        api_client.create_certification_report(
            f.certification_report_payload(
                center_id, _SEPTEMBER_END, _OCTOBER_END, bumped_version
            ),
            COORD,
        ),
        201,
    )
    assert october["status"] == "DRAFT"
    assert october["included_abstraction_count"] == 0, (
        "an adjacent, empty period gathers nothing, got "
        f"{october['included_abstraction_count']}"
    )
    assert october["closed_case_count_in_period"] == 0

    superseded = fx.read_report(september["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the earlier draft is superseded, not deleted, got {superseded['status']}"
    )
    assert superseded["superseded_by_report_id"] == october["id"], (
        "the superseded report points at its successor, got "
        f"{superseded['superseded_by_report_id']}"
    )
    detached = fx.read_abstraction(abstraction_id)
    assert detached["report_id"] is None, (
        f"the abstraction is detached rather than destroyed, got {detached['report_id']}"
    )
    assert detached["status"] == "FINALIZED", (
        f"detaching never rewinds the abstraction's own lifecycle, got {detached['status']}"
    )


# ---------------------------------------------------------------------------
# Instance 13: five ineligible candidates skipped, then a rank tie on load
# ---------------------------------------------------------------------------
def _seven_candidate_roster():
    """A hub roster of seven, of which five are individually ineligible at 08:14.

    Index order is deliberate: the two rank-20 candidates are registered with the
    busy one FIRST, so `created_at` would pick him and only the live-load
    tie-break can pick the other.
    """
    context = fx.setup_network(
        clock="2026-09-01T08:00:00Z",
        state_code="CA",
        spoke_state_code="CA",
        coverage_tier="TIER_1_FULL",
        max_concurrent_consults=3,
        neurologists=[
            {"roster_rank": 5, "on_call": False,
             "credential_expires_at": "2026-09-01T08:14:00Z"},
            {"roster_rank": 10, "on_call": False, "privilege_scope": "CONSULT_ONLY"},
            {"roster_rank": 12, "on_call": False},
            {"roster_rank": 14, "on_call": False, "licensed_state_codes": ["OR"]},
            {"roster_rank": 16, "on_call": False, "board_certified": False},
            {"roster_rank": 20, "on_call": True},
            {"roster_rank": 20, "on_call": False},
        ],
    )
    roster = context["neurologists"]
    context["expiring"] = roster[0]
    context["consult_only"] = roster[1]
    context["off_duty"] = roster[2]
    context["out_of_state"] = roster[3]
    context["not_board_certified"] = roster[4]
    context["busy_rank_twenty"] = roster[5]
    context["idle_rank_twenty"] = roster[6]
    return context


def test_the_routing_selector_skips_five_ineligible_candidates_and_breaks_a_rank_tie_by_load():
    """Expiry, scope, duty state, licensure and board status each remove one, then load decides.

    PRD 3.3: "The surviving candidates are ordered by `roster_rank` ascending, then by `active_consult_count` ascending, then by `completed_consult_count` ascending, and finally by `created_at` ascending, and the first is taken."
    PRD 3.3: "Two candidates sharing a `roster_rank` are separated by the lighter live load; if load and lifetime completions also tie, the earlier-registered neurologist wins."
    PRD 3.3: "A grant expiring at exactly the current instant is not eligible, because the comparison is strict."
    PRD 3.3: "A `CONSULT_ONLY` grant therefore cannot satisfy a `CONSULT_AND_THROMBOLYSIS` request, while a `CONSULT_AND_THROMBOLYSIS` grant satisfies a `CONSULT_ONLY` request."
    PRD 3.3: "The `state_code` of the facility named by the case's `center_id` appears in their `licensed_state_codes`."
    PRD 3.3: "All else equal, a neurologist who is not board certified is eligible on a consult-only-tier agreement and ineligible on a `TIER_1_FULL` one."

    Design: Corner/cross_cutting_complexity_layers/the_routing_selector_skips_five_ineligible_candidates_and_breaks_a_rank_tie_by_load
    """
    context = _seven_candidate_roster()
    spoke_id = context["spoke"]["id"]
    agreement_id = context["agreement"]["id"]
    busy = context["busy_rank_twenty"]
    idle = context["idle_rank_twenty"]

    first_case = fx.activate_case(spoke_id, "2026-09-01T08:05:00Z")
    first_consult = fx.request_consult(first_case["id"], agreement_id)
    assert first_consult["assigned_neurologist_id"] == busy["id"], (
        "only the one on-call candidate can take the first case, got "
        f"{first_consult['assigned_neurologist_id']}"
    )
    assert fx.read_neurologist(busy["id"])["active_consult_count"] == 1
    assert fx.read_neurologist(idle["id"])["active_consult_count"] == 0

    for key in ("expiring", "consult_only", "out_of_state", "not_board_certified",
                "idle_rank_twenty"):
        promoted = fx.set_on_call(context[key]["id"], "ON_CALL")
        assert promoted["on_call_state"] == "ON_CALL", (
            f"{key} must be on call before the decisive pass, got {promoted['on_call_state']}"
        )
    assert fx.read_neurologist(context["off_duty"]["id"])["on_call_state"] == "OFF_DUTY", (
        "the rank-12 candidate is deliberately left off duty"
    )

    second_case = fx.activate_case(spoke_id, "2026-09-01T08:14:00Z")
    second_consult = fx.request_consult(
        second_case["id"], agreement_id,
        requested_privilege_scope="CONSULT_AND_THROMBOLYSIS",
    )
    assert second_consult["status"] == "ASSIGNED", (
        f"the pool is non-empty, so nothing escalates, got {second_consult['status']}"
    )
    assert second_consult["assigned_neurologist_id"] == idle["id"], (
        "rank 5 expired at exactly this instant, rank 10 lacks thrombolysis scope, rank 12 "
        "is off duty, rank 14 is licensed elsewhere and rank 16 is not board certified, so "
        "the rank-20 tie falls to the lighter load, got "
        f"{second_consult['assigned_neurologist_id']}"
    )
    assert second_consult["routing_attempt_count"] == 1, (
        f"one pass over the roster fills it, got {second_consult['routing_attempt_count']}"
    )
    assert second_consult["response_latency_seconds"] is None, (
        "latency is only stamped on acceptance, got "
        f"{second_consult['response_latency_seconds']}"
    )
    assert second_consult["assigned_at"] is not None
    assert a.instants_equal(second_consult["assigned_at"], "2026-09-01T08:14:00Z"), (
        f"the assignment is stamped from the logical clock, got {second_consult['assigned_at']}"
    )

    third_case = fx.activate_case(spoke_id, "2026-09-01T08:15:00Z")
    third_consult = fx.request_consult(
        third_case["id"], agreement_id, requested_privilege_scope="CONSULT_ONLY",
    )
    assert third_consult["assigned_neurologist_id"] == context["consult_only"]["id"], (
        "a consult-only request lets the rank-10 grant back into the pool, and it "
        f"outranks both rank-20 candidates, got {third_consult['assigned_neurologist_id']}"
    )
    assert third_consult["status"] == "ASSIGNED"

    for key, expected in (
        ("expiring", 0), ("off_duty", 0), ("out_of_state", 0),
        ("not_board_certified", 0), ("busy_rank_twenty", 1),
        ("idle_rank_twenty", 1), ("consult_only", 1),
    ):
        observed = fx.read_neurologist(context[key]["id"])["active_consult_count"]
        assert observed == expected, (
            f"{key} should hold {expected} live consults, got {observed}"
        )

    agreement = fx.read_agreement(agreement_id)
    assert agreement["active_consult_count"] == 3, (
        f"three live consults on the agreement, got {agreement['active_consult_count']}"
    )
    assert agreement["max_concurrent_consults"] == 3, (
        "the agreement is now exactly at its ceiling"
    )


# ---------------------------------------------------------------------------
# Instance 14: the divert threshold at exactly three, and the double-counted
# patient between transfer acceptance and handoff
# ---------------------------------------------------------------------------
def test_the_divert_threshold_fires_at_exactly_three_open_cases_and_counts_accepted_transfers():
    """Two is routine, three diverts, an abort walks it back, and an accepted transfer counts twice.

    PRD 2.8: "A facility's `open_case_count` is the number of `CodeStrokeCase` records whose `center_id` names that facility and whose `status` is anything other than `CLOSED` or `ABORTED`, plus the number of `TransferDecision` records whose `destination_center_id` names that facility and whose `status` is `ACCEPTED`."
    PRD 2.9: "Otherwise the posture is `DIVERT_ADVISORY` if its `equipment_readiness_posture` is `DEGRADED`, or its `open_case_count` is 3 or greater, or its `certification_status` is `CONDITIONAL`."
    PRD 3.8: "the origin facility's `open_case_count` drops by 1 — exactly compensating the increment the activation made"
    PRD 3.7: "No `open_case_count` moves at proposal time; a proposal is not yet a commitment."
    PRD 3.7: "Acceptance is the moment the destination starts carrying the patient: it stamps `accepted_at`, raises the destination's `open_case_count` by 1 and recomputes that facility's `ems_routing_posture`"

    Design: Corner/cross_cutting_complexity_layers/the_divert_threshold_fires_at_exactly_three_open_cases_and_counts_accepted_transfers
    """
    assert ROUTING_POSTURE["OPEN_CASE_DIVERT_THRESHOLD"] == 3, (
        "the advisory threshold under test is three open cases, got "
        f"{ROUTING_POSTURE['OPEN_CASE_DIVERT_THRESHOLD']}"
    )
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    spoke_id = context["spoke"]["id"]
    travelling = fx.setup_eligible_case(context, "2026-09-01T08:00:00Z", dti_minutes=20)
    travelling_case = travelling["case"]
    assert travelling_case["status"] == "ELIGIBILITY_DETERMINED"
    assert travelling_case["needle_at"] is None, (
        "the patient is shipped unlysed, which is what a transfer-only proposal requires"
    )

    destination = fx.register_thrombectomy_center()
    destination_id = destination["id"]
    assert destination["open_case_count"] == 0
    assert destination["ems_routing_posture"] == "ROUTINE", (
        f"a fresh thrombectomy centre starts routine, got {destination['ems_routing_posture']}"
    )

    one_open = fx.read_center(spoke_id)
    assert one_open["open_case_count"] == 1, (
        f"only the travelling case is open so far, got {one_open['open_case_count']}"
    )
    assert one_open["ems_routing_posture"] == "ROUTINE"
    a.assert_ems_routing_posture(one_open)

    second_case = fx.activate_case(spoke_id, "2026-09-01T08:30:00Z")
    two_open = fx.read_center(spoke_id)
    assert two_open["open_case_count"] == 2, (
        f"two live cases at the spoke, got {two_open['open_case_count']}"
    )
    assert two_open["ems_routing_posture"] == "ROUTINE", (
        "two is strictly below the threshold, so the spoke still takes ambulances, got "
        f"{two_open['ems_routing_posture']}"
    )
    a.assert_ems_routing_posture(two_open)

    third_case = fx.activate_case(spoke_id, "2026-09-01T08:31:00Z")
    three_open = fx.read_center(spoke_id)
    assert three_open["open_case_count"] == 3, (
        f"the third activation reaches the threshold, got {three_open['open_case_count']}"
    )
    assert three_open["ems_routing_posture"] == "DIVERT_ADVISORY", (
        "three or greater diverts, and this facility is otherwise ready and provisional, got "
        f"{three_open['ems_routing_posture']}"
    )
    assert three_open["equipment_readiness_posture"] == "READY", (
        "the divert is driven by load alone, not by equipment"
    )
    assert three_open["certification_status"] == "PROVISIONAL", (
        "nor by a conditional certification"
    )
    a.assert_ems_routing_posture(three_open)

    aborted = fx.abort_case(third_case["id"], at="2026-09-01T08:40:00Z")
    assert aborted["status"] == "ABORTED"
    assert aborted["disposition"] == "NO_TREATMENT"
    back_to_two = fx.read_center(spoke_id)
    assert back_to_two["open_case_count"] == 2, (
        f"the abort gives the increment back, got {back_to_two['open_case_count']}"
    )
    assert back_to_two["ems_routing_posture"] == "ROUTINE", (
        "the posture is re-derived rather than latched, so dropping below three restores "
        f"routine in the same request, got {back_to_two['ems_routing_posture']}"
    )
    a.assert_ems_routing_posture(back_to_two)

    transfer = fx.propose_transfer(
        travelling_case["id"], destination_id,
        mode="TRANSFER_ONLY", transport_eta_minutes=30, at="2026-09-01T09:00:00Z",
    )
    assert transfer["status"] == "PROPOSED"
    assert transfer["destination_posture_at_proposal"] == "ROUTINE", (
        "the uncongested destination is frozen into the proposal, got "
        f"{transfer['destination_posture_at_proposal']}"
    )
    assert fx.read_center(destination_id)["open_case_count"] == 0, (
        "a proposal is not a commitment, so the destination count has not moved"
    )
    assert fx.read_center(destination_id)["ems_routing_posture"] == "ROUTINE"
    assert fx.read_center(spoke_id)["open_case_count"] == 2, (
        "the origin still holds the patient while the proposal is outstanding"
    )
    assert fx.read_case(travelling_case["id"])["status"] == "TRANSFER_INITIATED"

    accepted = fx.accept_transfer(transfer["id"], at="2026-09-01T09:05:00Z")
    assert accepted["status"] == "ACCEPTED"
    assert a.instants_equal(accepted["accepted_at"], "2026-09-01T09:05:00Z")

    receiving = fx.read_center(destination_id)
    assert receiving["open_case_count"] == 1, (
        "an accepted transfer decision counts at its destination even though no case "
        f"record lives there, got {receiving['open_case_count']}"
    )
    assert receiving["ems_routing_posture"] == "ROUTINE", (
        f"one is far below the threshold, got {receiving['ems_routing_posture']}"
    )
    a.assert_ems_routing_posture(receiving)

    origin = fx.read_center(spoke_id)
    assert origin["open_case_count"] == 2, (
        "TRANSFER_INITIATED is not terminal, so the origin keeps counting the same patient "
        f"the destination has just started counting, got {origin['open_case_count']}"
    )
    assert origin["ems_routing_posture"] == "ROUTINE", (
        f"two open cases keep the origin routine, got {origin['ems_routing_posture']}"
    )
    a.assert_ems_routing_posture(origin)
    assert fx.read_case(second_case["id"])["status"] == "ACTIVATED", (
        "the untouched second case is the other half of the origin's count"
    )
