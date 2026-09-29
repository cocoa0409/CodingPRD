"""Telestroke consult routing: the decline loop, load conservation, video validity and the cooldown."""
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import ED, make_neurologist_headers


def _system_deviations(case_id, deviation_type):
    return [
        row
        for row in fx.list_case_deviations(case_id)
        if row["deviation_type"] == deviation_type and row["source"] == "SYSTEM_DETECTED"
    ]


def test_decline_loops_the_consult_back_through_requested_and_then_escalates():
    """The first decline re-routes inside the same request; the second finds an empty pool.

    PRD 3.3: "Otherwise `assigned_neurologist_id` is cleared, the consult returns
    to `REQUESTED`, `routing_attempt_count` rises by 1, and the selector runs
    again inside the same request: a non-empty pool puts the consult back into
    `ASSIGNED` with a new assignee, a fresh `assigned_at` and that neurologist's
    `active_consult_count` raised, while an empty pool lands it in
    `ESCALATED_UNFILLED` with the same deviation as above."

    Design: Difficulty/non_linear_state_machine/consult_decline_loops_assigned_back_to_requested_then_escalates
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at,
        neurologists=[{"roster_rank": 10}, {"roster_rank": 20}],
    )
    first, second = context["neurologists"]
    case = fx.activate_case(context["spoke"]["id"], door_at)
    consult = fx.request_consult(case["id"], context["agreement"]["id"], at="2026-09-01T08:05:00Z")
    assert consult["assigned_neurologist_id"] == first["id"], (
        "the roster_rank 10 neurologist is taken first, got "
        f"{consult['assigned_neurologist_id']}"
    )

    mid = validate_success(
        api_client.decline_consult(
            consult["id"], f.decline_consult_payload(), make_neurologist_headers(first["id"])
        )
    )

    assert mid["status"] == "ASSIGNED", (
        f"the first decline must re-route rather than terminate, got {mid['status']}"
    )
    assert mid["assigned_neurologist_id"] == second["id"], (
        "the decliner is excluded before the selector re-runs, got "
        f"{mid['assigned_neurologist_id']}"
    )
    assert mid["routing_attempt_count"] == 2, (
        f"the re-route is a second routing pass, got {mid['routing_attempt_count']}"
    )
    assert mid["decline_count"] == 1
    assert first["id"] in mid["excluded_neurologist_ids"]

    escalated = validate_success(
        api_client.decline_consult(
            consult["id"], f.decline_consult_payload(), make_neurologist_headers(second["id"])
        )
    )

    assert escalated["status"] == "ESCALATED_UNFILLED", (
        f"an empty pool lands the consult in ESCALATED_UNFILLED, got {escalated['status']}"
    )
    assert escalated["assigned_neurologist_id"] is None
    assert escalated["decline_count"] == 2
    assert escalated["routing_attempt_count"] == 3, (
        "the second decline raises the attempt count by 1 before running the selector, got "
        f"{escalated['routing_attempt_count']}"
    )
    assert set(escalated["excluded_neurologist_ids"]) == {first["id"], second["id"]}

    for neurologist in (first, second):
        live = fx.read_neurologist(neurologist["id"])
        assert live["active_consult_count"] == 0, (
            f"a decline releases the load, got {live['active_consult_count']}"
        )
        assert live["completed_consult_count"] == 0, (
            f"a decline is not a completion, got {live['completed_consult_count']}"
        )

    unfilled = _system_deviations(case["id"], "CONSULT_UNFILLED")
    assert len(unfilled) == 1, f"exactly one CONSULT_UNFILLED deviation, got {len(unfilled)}"
    assert unfilled[0]["severity"] == "MAJOR"
    case_after = fx.read_case(case["id"])
    assert case_after["deviation_count"] == 1
    assert case_after["status"] == "CONSULT_IN_PROGRESS", (
        f"the case does not rewind when its consult escalates, got {case_after['status']}"
    )


def test_third_decline_exits_the_loop_without_another_routing_pass():
    """The bounded loop terminates on the third decline even with a candidate still free.

    PRD 3.3: "if the decline just recorded is the third on this consult, the loop
    exits — `status` becomes `ESCALATED_UNFILLED`, `assigned_neurologist_id` is
    cleared to null, and a system-detected `CONSULT_UNFILLED` deviation of
    severity `MAJOR` is opened on the case with `deviation_count` raised by 1."

    Design: Difficulty/non_linear_state_machine/consult_decline_loops_assigned_back_to_requested_then_escalates
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at,
        neurologists=[{"roster_rank": 10}, {"roster_rank": 20}, {"roster_rank": 30}, {"roster_rank": 40}],
    )
    roster = context["neurologists"]
    case = fx.activate_case(context["spoke"]["id"], door_at)
    consult = fx.request_consult(case["id"], context["agreement"]["id"], at="2026-09-01T08:05:00Z")

    for index in range(2):
        state = validate_success(
            api_client.decline_consult(
                consult["id"], f.decline_consult_payload(),
                make_neurologist_headers(roster[index]["id"]),
            )
        )
        assert state["assigned_neurologist_id"] == roster[index + 1]["id"]

    assert state["routing_attempt_count"] == 3
    escalated = validate_success(
        api_client.decline_consult(
            consult["id"], f.decline_consult_payload(),
            make_neurologist_headers(roster[2]["id"]),
        )
    )

    assert escalated["status"] == "ESCALATED_UNFILLED", (
        f"the third decline exits the loop, got {escalated['status']}"
    )
    assert escalated["assigned_neurologist_id"] is None
    assert escalated["decline_count"] == 3
    assert escalated["routing_attempt_count"] == 3, (
        "the escalating decline runs no further routing pass, got "
        f"{escalated['routing_attempt_count']}"
    )
    assert roster[3]["id"] not in escalated["excluded_neurologist_ids"], (
        "the fourth, never-offered neurologist is not excluded"
    )
    assert fx.read_neurologist(roster[3]["id"])["active_consult_count"] == 0, (
        "the loop exited before the free candidate was offered the consult"
    )
    assert len(_system_deviations(case["id"], "CONSULT_UNFILLED")) == 1
    assert fx.read_case(case["id"])["deviation_count"] == 1


def test_consult_load_moves_between_neurologists_without_being_double_counted():
    """A decline transfers the live load; the agreement's tally never doubles.

    PRD 3.3: "lowers that neurologist's `active_consult_count` back to its pre-assignment value"
    PRD 3.3: "a non-empty pool puts the consult back into `ASSIGNED` with a new assignee, a fresh `assigned_at` and that neurologist's `active_consult_count` raised"

    Design: Difficulty/compensating_invariant/consult_load_conserved_across_decline_reroute_and_completion
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at,
        neurologists=[{"roster_rank": 10}, {"roster_rank": 20}],
    )
    first, second = context["neurologists"]
    case = fx.activate_case(context["spoke"]["id"], door_at)

    consult = fx.request_consult(case["id"], context["agreement"]["id"], at="2026-09-01T08:04:00Z")

    assert consult["assigned_neurologist_id"] == first["id"]
    assert fx.read_neurologist(first["id"])["active_consult_count"] == 1, (
        "the assignment is the only live load on the roster"
    )
    assert fx.read_neurologist(second["id"])["active_consult_count"] == 0
    assert fx.read_agreement(context["agreement"]["id"])["active_consult_count"] == 1, (
        "one open consult on the agreement is counted once"
    )

    fx.set_clock("2026-09-01T08:06:00Z")
    rerouted = validate_success(
        api_client.decline_consult(
            consult["id"], f.decline_consult_payload(), make_neurologist_headers(first["id"])
        )
    )

    assert rerouted["assigned_neurologist_id"] == second["id"]
    assert fx.read_neurologist(first["id"])["active_consult_count"] == 0, (
        "the decliner is back to their pre-assignment load"
    )
    assert fx.read_neurologist(second["id"])["active_consult_count"] == 1, (
        "the new assignee carries the load instead"
    )
    assert fx.read_agreement(context["agreement"]["id"])["active_consult_count"] == 1, (
        "the same open consult is still counted exactly once after the re-route"
    )
    for neurologist in (first, second):
        live = fx.read_neurologist(neurologist["id"])
        assert live["completed_consult_count"] == 0
        assert live["last_consult_completed_at"] is None


def test_completion_credits_only_the_neurologist_who_ran_the_session():
    """The lifetime tally and the cooldown land on the accepter, never on the decliner.

    PRD 3.4: "`completed_consult_count` raised by 1, and `active_consult_count` recomputed. The agreement's `active_consult_count` is recomputed too."

    Design: Difficulty/compensating_invariant/consult_load_conserved_across_decline_reroute_and_completion
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at,
        neurologists=[{"roster_rank": 10}, {"roster_rank": 20}],
    )
    first, second = context["neurologists"]
    case = fx.activate_case(context["spoke"]["id"], door_at)
    consult = fx.request_consult(case["id"], context["agreement"]["id"], at="2026-09-01T08:04:00Z")
    fx.set_clock("2026-09-01T08:06:00Z")
    validate_success(
        api_client.decline_consult(
            consult["id"], f.decline_consult_payload(), make_neurologist_headers(first["id"])
        )
    )

    fx.accept_consult(consult["id"], second["id"], at="2026-09-01T08:08:00Z")
    fx.append_video_session(
        consult["id"], second["id"], "2026-09-01T08:08:00Z", "2026-09-01T08:14:00Z"
    )
    completed = fx.complete_consult(consult["id"], second["id"], at="2026-09-01T08:15:00Z")

    assert completed["status"] == "COMPLETED"

    accepter = fx.read_neurologist(second["id"])
    assert accepter["completed_consult_count"] == 1, (
        f"the accepter earns the completion, got {accepter['completed_consult_count']}"
    )
    assert accepter["active_consult_count"] == 0, (
        "the completed consult is no longer live load"
    )
    assert accepter["on_call_state"] == "ON_CALL"
    assert accepter["last_consult_completed_at"] == "2026-09-01T08:15:00Z", (
        f"the cooldown is armed from the logical clock, got {accepter['last_consult_completed_at']}"
    )

    decliner = fx.read_neurologist(first["id"])
    assert decliner["completed_consult_count"] == 0, (
        "declining is not completing, got "
        f"{decliner['completed_consult_count']}"
    )
    assert decliner["active_consult_count"] == 0
    assert decliner["last_consult_completed_at"] is None, (
        "no cooldown is armed on the neurologist who declined"
    )
    assert fx.read_agreement(context["agreement"]["id"])["active_consult_count"] == 0, (
        "the agreement releases the consult on completion"
    )


def _cooldown_scenario():
    """One neurologist, two consults; the first is completed at 08:20 to arm the cooldown."""
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    neurologist = context["neurologist"]
    spoke_id = context["spoke"]["id"]
    agreement_id = context["agreement"]["id"]
    case_one = fx.activate_case(spoke_id, door_at)
    case_two = fx.activate_case(spoke_id, "2026-09-01T08:01:00Z")
    first = fx.request_consult(case_one["id"], agreement_id, at="2026-09-01T08:01:30Z")
    second = fx.request_consult(case_two["id"], agreement_id, at="2026-09-01T08:02:00Z")
    assert first["assigned_neurologist_id"] == neurologist["id"]
    assert second["assigned_neurologist_id"] == neurologist["id"], (
        "both consults must land on the same neurologist for the cooldown to bite"
    )
    assert second["requested_at"] == "2026-09-01T08:02:00Z"
    fx.accept_consult(first["id"], neurologist["id"], at="2026-09-01T08:05:00Z")
    fx.append_video_session(
        first["id"], neurologist["id"], "2026-09-01T08:05:00Z", "2026-09-01T08:09:00Z"
    )
    completed = fx.complete_consult(first["id"], neurologist["id"], at="2026-09-01T08:20:00Z")
    assert completed["completed_at"] == "2026-09-01T08:20:00Z"
    assert fx.read_neurologist(neurologist["id"])["last_consult_completed_at"] == (
        "2026-09-01T08:20:00Z"
    )
    return {"context": context, "neurologist": neurologist, "consult": second}


def test_acceptance_nine_minutes_after_a_completion_is_refused():
    """Nine whole minutes past `last_consult_completed_at` is inside the buffer.

    PRD 3.3: "That buffer rejects adjacency: accepting exactly 9 minutes after completing another consult fails with `ERR_NEUROLOGIST_COOLDOWN_ACTIVE`, and exactly 10 minutes after succeeds."

    Design: Difficulty/resource_temporal_overlap/neurologist_cooldown_buffer_excludes_nine_minutes_and_admits_ten
    """
    scenario = _cooldown_scenario()
    consult = scenario["consult"]
    neurologist = scenario["neurologist"]

    fx.set_clock("2026-09-01T08:29:00Z")
    response = api_client.accept_consult(
        consult["id"], make_neurologist_headers(neurologist["id"])
    )

    validate_error(response, ApiErrorId.ERR_NEUROLOGIST_COOLDOWN_ACTIVE.value, 409)

    unchanged = fx.read_consult(consult["id"])
    assert unchanged["status"] == "ASSIGNED", (
        f"the refused acceptance leaves the consult ASSIGNED, got {unchanged['status']}"
    )
    assert unchanged["accepted_at"] is None
    assert unchanged["response_latency_seconds"] is None
    assert fx.read_neurologist(neurologist["id"])["on_call_state"] == "ON_CALL", (
        "a refused acceptance does not put the neurologist into consult"
    )


def test_acceptance_exactly_ten_minutes_after_a_completion_is_admitted():
    """Ten whole minutes clears the buffer and the latency runs from this consult's own request.

    PRD 3.3: "On acceptance the consult's `status` becomes `IN_SESSION`, `accepted_at` is stamped from the logical clock, `response_latency_seconds` is computed as the whole seconds elapsed from `requested_at` to `accepted_at`"

    Design: Difficulty/resource_temporal_overlap/neurologist_cooldown_buffer_excludes_nine_minutes_and_admits_ten
    """
    scenario = _cooldown_scenario()
    consult = scenario["consult"]
    neurologist = scenario["neurologist"]

    accepted = fx.accept_consult(consult["id"], neurologist["id"], at="2026-09-01T08:30:00Z")

    assert accepted["status"] == "IN_SESSION", (
        f"exactly ten minutes after a completion succeeds, got {accepted['status']}"
    )
    assert accepted["accepted_at"] == "2026-09-01T08:30:00Z"
    assert accepted["response_latency_seconds"] == 1680, (
        "the latency spans 08:02:00 to 08:30:00 in whole seconds, got "
        f"{accepted['response_latency_seconds']}"
    )
    live = fx.read_neurologist(neurologist["id"])
    assert live["on_call_state"] == "IN_CONSULT"
    assert live["last_consult_completed_at"] == "2026-09-01T08:20:00Z", (
        "accepting does not move the previous completion instant"
    )


def _consult_in_session(*, requested_at="2026-09-01T08:16:00Z", accepted_at="2026-09-01T08:20:00Z"):
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    case = fx.activate_case(context["spoke"]["id"], door_at)
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    consult = fx.request_consult(case["id"], context["agreement"]["id"], at=requested_at)
    fx.accept_consult(consult["id"], context["neurologist"]["id"], at=accepted_at)
    return {"context": context, "case": case, "consult": consult,
            "neurologist": context["neurologist"]}


def test_one_hundred_seventy_nine_second_session_is_invalid_and_blocks_completion():
    """A session one second under the floor is recorded, deviates, and cannot carry a completion.

    PRD 3.4: "A three-minute `HD` session with no disconnects, at exactly 180 seconds, is valid; the same session one second shorter, at 179 seconds, is not."
    PRD 3.4: "the consult's `valid_video_session_count` must be 1 or more (`ERR_NO_VALID_VIDEO_SESSION`)"

    Design: Difficulty/boundary_precision_check/video_session_validity_boundary_at_one_eighty_and_one_seventy_nine_seconds
    """
    scenario = _consult_in_session()
    consult_id = scenario["consult"]["id"]
    case_id = scenario["case"]["id"]
    neurologist_id = scenario["neurologist"]["id"]

    fx.set_clock("2026-09-01T08:24:00Z")
    fx.append_video_session(
        consult_id, neurologist_id, "2026-09-01T08:20:00Z", "2026-09-01T08:22:59Z"
    )

    stored = fx.read_consult(consult_id)
    session = stored["video_sessions"][-1]
    assert session["duration_seconds"] == 179, (
        f"179 whole seconds elapse between the two instants, got {session['duration_seconds']}"
    )
    assert session["session_valid"] is False, "179 seconds is below the inclusive 180-second floor"
    assert stored["valid_video_session_count"] == 0, (
        f"an invalid session raises no tally, got {stored['valid_video_session_count']}"
    )
    assert stored["status"] == "IN_SESSION", "an invalid session is recorded, not rejected"

    invalid_deviations = _system_deviations(case_id, "INVALID_VIDEO_SESSION")
    assert len(invalid_deviations) == 1, (
        f"the invalid session opens exactly one deviation, got {len(invalid_deviations)}"
    )
    assert invalid_deviations[0]["severity"] == "MINOR"
    assert fx.read_case(case_id)["deviation_count"] == 1

    response = api_client.complete_consult(
        consult_id, f.complete_consult_payload(), make_neurologist_headers(neurologist_id)
    )

    validate_error(response, ApiErrorId.ERR_NO_VALID_VIDEO_SESSION.value, 409)
    after = fx.read_consult(consult_id)
    assert after["status"] == "IN_SESSION", (
        f"the refused completion leaves the consult IN_SESSION, got {after['status']}"
    )
    assert after["completed_at"] is None
    assert after["recommendation"] is None
    assert after["nihss_score"] is None
    blocked = fx.read_neurologist(neurologist_id)
    assert blocked["on_call_state"] == "IN_CONSULT", "the neurologist is not unwound"
    assert blocked["completed_consult_count"] == 0
    assert blocked["last_consult_completed_at"] is None


def test_one_hundred_eighty_second_session_is_valid_and_carries_the_completion():
    """The 180-second session passes on the inclusive edge and completes alongside the invalid one.

    PRD 3.4: "A three-minute `HD` session with no disconnects, at exactly 180 seconds, is valid; the same session one second shorter, at 179 seconds, is not."
    PRD 3.4: "A consult can therefore accumulate a valid session, an invalid session and a deviation all at once, and still be completable."

    Design: Difficulty/boundary_precision_check/video_session_validity_boundary_at_one_eighty_and_one_seventy_nine_seconds
    """
    scenario = _consult_in_session()
    consult_id = scenario["consult"]["id"]
    case_id = scenario["case"]["id"]
    neurologist_id = scenario["neurologist"]["id"]

    fx.set_clock("2026-09-01T08:24:00Z")
    fx.append_video_session(
        consult_id, neurologist_id, "2026-09-01T08:20:00Z", "2026-09-01T08:22:59Z"
    )
    fx.append_video_session(
        consult_id, neurologist_id, "2026-09-01T08:23:00Z", "2026-09-01T08:26:00Z"
    )

    stored = fx.read_consult(consult_id)
    assert len(stored["video_sessions"]) == 2, (
        f"both link attempts are retained, got {len(stored['video_sessions'])}"
    )
    valid_session = stored["video_sessions"][-1]
    assert valid_session["duration_seconds"] == 180
    assert valid_session["session_valid"] is True, "exactly 180 seconds passes the floor"
    assert stored["valid_video_session_count"] == 1, (
        f"only the valid session is tallied, got {stored['valid_video_session_count']}"
    )
    assert stored["video_sessions"][0]["session_valid"] is False, (
        "the earlier 179-second session keeps its verdict"
    )

    completed = fx.complete_consult(
        consult_id, neurologist_id, at="2026-09-01T08:27:00Z", nihss_score=14
    )

    assert completed["status"] == "COMPLETED", (
        f"one valid session is enough to complete, got {completed['status']}"
    )
    assert completed["completed_at"] == "2026-09-01T08:27:00Z"
    assert completed["nihss_score"] == 14
    assert completed["valid_video_session_count"] == 1
    assert fx.read_case(case_id)["deviation_count"] == 1, (
        "the single invalid-session deviation stands and completion adds none"
    )
    assert fx.read_case(case_id)["status"] == "CONSULT_IN_PROGRESS", (
        "completion does not advance the case"
    )


def _consults_for_case(case_id):
    data, _meta = validate_paginated(
        api_client.list_consults(ED, {"case_id": case_id, "limit": 100, "offset": 0})
    )
    return [row for row in data if row["case_id"] == case_id]


def _future_window_offline_spoke():
    """An ACTIVE agreement that is not yet in effect, plus an OFFLINE spoke."""
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at,
        effective_from="2026-10-01T00:00:00Z",
        effective_until="2027-10-01T00:00:00Z",
    )
    assert fx.read_agreement(context["agreement"]["id"])["status"] == "ACTIVE", (
        "activation only requires the clock to be before effective_until"
    )
    case = fx.activate_case(context["spoke"]["id"], door_at)
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    case = fx.read_case(case["id"])
    fx.set_clock("2026-09-01T08:15:00Z")
    fx.take_center_offline(context["spoke"]["id"])
    spoke = fx.read_center(context["spoke"]["id"])
    assert spoke["equipment_readiness_posture"] == "OFFLINE"
    assert spoke["ems_routing_posture"] == "BYPASS"
    return {"context": context, "case": case}


def test_offline_equipment_beats_a_not_yet_effective_agreement_on_a_consult_request():
    """Both candidates answer 409, so only the error_id shows which rung was evaluated first.

    PRD 2.11: "so an offline facility with a not-yet-effective agreement returns the equipment code"

    Design: Difficulty/priority_pair_validation_conflict/equipment_offline_outranks_agreement_window_on_consult_request
    """
    scenario = _future_window_offline_spoke()
    case = scenario["case"]
    context = scenario["context"]

    fx.set_clock("2026-09-01T08:20:00Z")
    response = api_client.request_consult(
        f.consult_request_payload(case["id"], context["agreement"]["id"], case["version"]), ED
    )

    error = validate_error(response, ApiErrorId.ERR_CENTER_EQUIPMENT_OFFLINE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_AGREEMENT_WINDOW_CLOSED.value, (
        "the equipment gate outranks the agreement window, got " f"{error['error_id']}"
    )

    assert _consults_for_case(case["id"]) == [], "no consult row is written by the rejection"
    after = fx.read_case(case["id"])
    assert after["status"] == "IMAGING_COMPLETE", (
        f"the case does not move on a rejected request, got {after['status']}"
    )
    assert after["version"] == case["version"], "the OCC version does not move on a rejection"
    agreement = fx.read_agreement(context["agreement"]["id"])
    assert agreement["status"] == "ACTIVE", (
        "the rejected request did not run the expiry check either"
    )
    assert agreement["active_consult_count"] == 0


def test_repairing_the_equipment_exposes_the_agreement_window_error():
    """With the higher rung cleared the losing candidate becomes reachable and answers instead.

    PRD 3.3: "A request made before the agreement's `effective_from` has arrived is rejected earlier and differently, with `ERR_AGREEMENT_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/equipment_offline_outranks_agreement_window_on_consult_request
    """
    scenario = _future_window_offline_spoke()
    case = scenario["case"]
    context = scenario["context"]
    spoke_id = context["spoke"]["id"]

    fx.set_clock("2026-09-01T08:20:00Z")
    fx.attest_readiness(spoke_id, "CT_SCANNER", "PASS")
    repaired = fx.attest_readiness(spoke_id, "VIDEO_CART", "PASS")
    assert repaired["equipment_readiness_posture"] == "READY", (
        f"two PASS attestations clear the posture, got {repaired['equipment_readiness_posture']}"
    )

    response = api_client.request_consult(
        f.consult_request_payload(case["id"], context["agreement"]["id"], case["version"]), ED
    )

    error = validate_error(response, ApiErrorId.ERR_AGREEMENT_WINDOW_CLOSED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_CENTER_EQUIPMENT_OFFLINE.value
    assert _consults_for_case(case["id"]) == [], "the window rejection writes no consult either"
    assert fx.read_case(case["id"])["version"] == case["version"]
    assert fx.read_neurologist(context["neurologist"]["id"])["active_consult_count"] == 0, (
        "routing never ran, so no load was taken"
    )


def _draft_agreement_case():
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at, activate=False)
    assert fx.read_agreement(context["agreement"]["id"])["status"] == "DRAFT", (
        "the agreement is deliberately left unactivated"
    )
    case = fx.activate_case(context["spoke"]["id"], door_at)
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    return {"context": context, "case": fx.read_case(case["id"])}


def test_consult_request_is_refused_while_its_agreement_is_still_draft():
    """Every other precondition holds; the referenced agreement's state alone refuses the request.

    PRD 3.3: "the agreement must be `ACTIVE`, evaluated after the automatic expiry check (`ERR_AGREEMENT_NOT_ACTIVE`, 409)"

    Design: Difficulty/cross_entity_state_dependency/consult_request_depends_on_spoke_agreement_active_state
    """
    scenario = _draft_agreement_case()
    context = scenario["context"]
    case = scenario["case"]
    neurologist = context["neurologist"]
    assert fx.read_neurologist(neurologist["id"])["on_call_state"] == "ON_CALL"

    fx.set_clock("2026-09-01T08:15:00Z")
    response = api_client.request_consult(
        f.consult_request_payload(case["id"], context["agreement"]["id"], case["version"]), ED
    )

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)

    assert _consults_for_case(case["id"]) == [], "the rejected request creates no consult"
    after = fx.read_case(case["id"])
    assert after["status"] == "IMAGING_COMPLETE"
    assert after["version"] == case["version"], (
        "the case version does not move, so a held expected_case_version stays usable"
    )
    assert after["deviation_count"] == 0, (
        "a rejected precondition is not an empty routing pool"
    )
    assert fx.read_neurologist(neurologist["id"])["active_consult_count"] == 0


def test_activating_the_agreement_lets_the_identical_request_route():
    """The byte-identical request flips to 201 once the third entity reaches ACTIVE.

    PRD 3.3: "The winner is written to `assigned_neurologist_id`, `assigned_at` is stamped from the logical clock, the consult's `status` becomes `ASSIGNED`, `routing_attempt_count` reflects the pass just executed"

    Design: Difficulty/cross_entity_state_dependency/consult_request_depends_on_spoke_agreement_active_state
    """
    scenario = _draft_agreement_case()
    context = scenario["context"]
    case = scenario["case"]
    neurologist = context["neurologist"]
    agreement_id = context["agreement"]["id"]
    payload = f.consult_request_payload(case["id"], agreement_id, case["version"])

    fx.set_clock("2026-09-01T08:15:00Z")
    validate_error(
        api_client.request_consult(dict(payload), ED),
        ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
        409,
    )
    activated = fx.activate_agreement(agreement_id)
    assert activated["status"] == "ACTIVE"
    assert activated["active_consult_count"] == 0

    consult = validate_success(api_client.request_consult(dict(payload), ED), 201)

    assert consult["status"] == "ASSIGNED", (
        f"the same request now routes, got {consult['status']}"
    )
    assert consult["assigned_neurologist_id"] == neurologist["id"]
    assert consult["routing_attempt_count"] == 1, (
        f"this is the first routing pass on the consult, got {consult['routing_attempt_count']}"
    )
    assert consult["assigned_at"] == "2026-09-01T08:15:00Z"
    assert consult["decline_count"] == 0
    assert consult["excluded_neurologist_ids"] == []

    assert fx.read_case(case["id"])["status"] == "CONSULT_IN_PROGRESS"
    live = fx.read_neurologist(neurologist["id"])
    assert live["active_consult_count"] == 1
    assert live["on_call_state"] == "ON_CALL", (
        "assignment does not open the session; only acceptance moves the neurologist"
    )
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 1
    assert fx.read_case(case["id"])["deviation_count"] == 0
