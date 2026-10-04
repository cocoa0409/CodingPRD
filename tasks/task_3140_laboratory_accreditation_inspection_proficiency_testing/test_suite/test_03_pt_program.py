"""Proficiency testing: grading, standing, shipments, deadlines."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_pt_subscription,
    create_shipment,
    get_success_data,
    list_investigations,
    make_director_headers,
    setup_lab_with_active_enrollment,
    setup_pt_active_enrollment,
    submit_result,
    submit_result_ok,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
PTC = TEST_USERS["pt_coordinator_headers"]


def test_pt_event_score_exactly_80_is_satisfactory(api):
    """PRD §3.2: "Both thresholds are inclusive in the passing direction — an
    `event_score` of exactly 80.0 with no critical failure is `SATISFACTORY`."
    PRD §3.2: "The `event_score` is one hundred times the passed count divided
    by the total count, rounded half-up to one decimal place."

    Design: Difficulty/boundary_precision_check/pt_event_score_exactly_80_is_satisfactory
    """
    analytes = [
        {"name": "glucose", "critical": True},
        {"name": "sodium", "critical": False},
        {"name": "potassium", "critical": False},
        {"name": "chloride", "critical": False},
        {"name": "calcium", "critical": False},
    ]
    ctx = setup_pt_active_enrollment(analytes=analytes)
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    scores = [
        {"name": "glucose", "score": 90},
        {"name": "sodium", "score": 85},
        {"name": "potassium", "score": 80},
        {"name": "chloride", "score": 80},
        {"name": "calcium", "score": 79},
    ]
    result = submit_result_ok(sh["id"], ctx["lab"]["id"], scores)
    assert result["status"] == "GRADED"
    assert result["event_score"] == 80.0
    assert result["event_evaluation"] == "SATISFACTORY"
    assert list_investigations(ctx["enrollment"]["id"]) == []


def test_pt_critical_analyte_failure_is_unsatisfactory_despite_passing_aggregate(api):
    """PRD §3.2: "The `event_evaluation` is `UNSATISFACTORY` when the
    `event_score` is below 80.0 or when any analyte flagged `critical` in the
    subscription received a `score` below 80; otherwise it is `SATISFACTORY`."

    Design: Difficulty/boundary_precision_check/pt_event_score_exactly_80_is_satisfactory
    """
    analytes = [
        {"name": "glucose", "critical": True},
        {"name": "sodium", "critical": False},
        {"name": "potassium", "critical": False},
        {"name": "chloride", "critical": False},
        {"name": "calcium", "critical": False},
    ]
    ctx = setup_pt_active_enrollment(analytes=analytes)
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    # 4 of 5 pass (aggregate 80.0) but the failing one is the critical analyte.
    scores = [
        {"name": "glucose", "score": 79},
        {"name": "sodium", "score": 90},
        {"name": "potassium", "score": 85},
        {"name": "chloride", "score": 80},
        {"name": "calcium", "score": 80},
    ]
    result = submit_result_ok(sh["id"], ctx["lab"]["id"], scores)
    assert result["event_score"] == 80.0
    assert result["event_evaluation"] == "UNSATISFACTORY"


def test_pt_subscription_requires_critical_analyte(api):
    """PRD §3.2: "Each analyte is an object with a `name` and a `critical`
    boolean; the array must be non-empty and at least one analyte must be
    flagged critical, otherwise the request is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/pt_subscription_requires_critical_analyte
    """
    ctx = setup_lab_with_active_enrollment()
    resp = api.create_pt_subscription(
        {"enrollment_id": ctx["enrollment"]["id"],
         "analytes": [{"name": "sodium", "critical": False}]},
        make_director_headers(ctx["lab"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_pt_result_collection_window_five_days(api):
    """PRD §3.2: "the `collected_at` must fall within the closed viability
    window from `shipped_at` through five calendar days after `shipped_at`
    (`ERR_PT_COLLECTION_WINDOW`)"

    Design: Corner/validations/pt_result_collection_window_five_days
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    assert sh["shipped_at"] == "2026-09-01T00:00:00Z"

    resp_late = submit_result(sh["id"], ctx["lab"]["id"],
                              [{"name": "glucose", "score": 95}],
                              collected_at="2026-09-06T00:00:01Z")
    validate_error(resp_late, ApiErrorId.ERR_PT_COLLECTION_WINDOW.value, 409)

    result = submit_result_ok(sh["id"], ctx["lab"]["id"],
                              [{"name": "glucose", "score": 95}],
                              collected_at="2026-09-06T00:00:00Z")
    assert result["status"] == "GRADED"
    assert result["event_score"] == 100.0


def test_pt_shipment_closed_interval_overlap_at_due_at(api):
    """PRD §3.2: "Shipments of one subscription may not overlap in time: the
    closed interval from `shipped_at` through `due_at`, inclusive at both ends,
    must not intersect the corresponding interval of any other `OPEN` shipment
    of the same subscription — including the boundary case where the new
    `shipped_at` equals the existing shipment's `due_at` — or the request is
    rejected with `ERR_SHIPMENT_WINDOW_OVERLAP`."
    PRD §3.2: "The server stamps `shipped_at` with the current logical time and
    computes `due_at` as exactly ten calendar days after `shipped_at`."

    Design: Difficulty/resource_temporal_overlap/pt_shipment_closed_interval_overlap_at_due_at
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    sh1 = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    assert sh1["due_at"] == "2026-09-11T00:00:00Z"

    # At exactly S1.due_at, S1 is still OPEN and the closed interval admits the
    # boundary — overlap is rejected.
    get_success_data(api.set_clock("2026-09-11T00:00:00Z", ADMIN))
    resp_overlap = api.create_pt_shipment(
        {"subscription_id": ctx["subscription"]["id"], "event_code": "C-2026-B"}, PTC)
    validate_error(resp_overlap, ApiErrorId.ERR_SHIPMENT_WINDOW_OVERLAP.value, 409)

    # Past due_at, the clock auto-closes S1 and a new shipment is admitted.
    get_success_data(api.set_clock("2026-09-12T00:00:00Z", ADMIN))
    sh1_after = get_success_data(api.get_pt_shipment(sh1["id"], OFFICER))
    assert sh1_after["status"] == "CLOSED"
    assert sh1_after["closure_reason"] == "DEADLINE_ELAPSED"

    sh2 = create_shipment(ctx["subscription"]["id"], event_code="C-2026-B")
    assert sh2["status"] == "OPEN"
    assert sh2["shipped_at"] == "2026-09-12T00:00:00Z"
    assert sh2["due_at"] == "2026-09-22T00:00:00Z"


def test_shipment_window_overlap_rejected_while_prior_open(api):
    """PRD §3.2: "Shipments of one subscription may not overlap in time: the
    closed interval from `shipped_at` through `due_at`, inclusive at both ends,
    must not intersect the corresponding interval of any other `OPEN` shipment
    of the same subscription — including the boundary case where the new
    `shipped_at` equals the existing shipment's `due_at` — or the request is
    rejected with `ERR_SHIPMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pt_shipment_closed_interval_overlap_at_due_at
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    # Clock still at default 2026-09-01: a second shipment overlaps the first.
    resp = api.create_pt_shipment(
        {"subscription_id": ctx["subscription"]["id"], "event_code": "C-2026-B"}, PTC)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_WINDOW_OVERLAP.value, 409)


def test_state_priority_beats_temporal_on_late_result_to_closed_shipment(api):
    """PRD §2.8: "(4) state-machine admissibility, including terminal-state
    lockdown (`ERR_INVALID_STATE` and its domain variants); ... (7) temporal
    windows such as deadlines and appeal periods"
    PRD §3.2: "The shipment must still be `OPEN` (`ERR_SHIPMENT_CLOSED`
    otherwise); the current logical time must not exceed the shipment's
    `due_at` (`ERR_SUBMISSION_DEADLINE_PASSED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_on_late_result_to_closed_shipment
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    get_success_data(api.set_clock("2026-09-03T00:00:00Z", ADMIN))
    closed = get_success_data(api.close_pt_shipment(sh["id"], PTC))
    assert closed["closure_reason"] == "ADMIN_CLOSED"
    # Past the due date as well, so both the state check and the temporal check
    # are violated; the state error must win.
    get_success_data(api.set_clock("2026-09-20T00:00:00Z", ADMIN))

    resp = submit_result(sh["id"], ctx["lab"]["id"],
                         [{"name": "glucose", "score": 95}],
                         collected_at="2026-09-02T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_CLOSED.value, 409)

    results = get_success_data(api.list_pt_results(
        OFFICER, params={"shipment_id": sh["id"]}))
    assert results == []


def test_clock_close_also_fires_shipment_closed_on_late_submission(api):
    """PRD §2.4: "Advancing the clock fires three families of automatic
    transitions: any `OPEN` shipment whose `due_at` the new clock value exceeds
    is closed with `closure_reason` set to `DEADLINE_ELAPSED`"
    PRD §3.2: "The shipment must still be `OPEN` (`ERR_SHIPMENT_CLOSED`
    otherwise); the current logical time must not exceed the shipment's
    `due_at` (`ERR_SUBMISSION_DEADLINE_PASSED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_on_late_result_to_closed_shipment
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    # Clock past due_at: deadline closure fires AND the deadline check is
    # violated; shipment is CLOSED, so the state error must win.
    get_success_data(api.set_clock("2026-09-20T00:00:00Z", ADMIN))
    sh_after = get_success_data(api.get_pt_shipment(sh["id"], OFFICER))
    assert sh_after["status"] == "CLOSED"
    assert sh_after["closure_reason"] == "DEADLINE_ELAPSED"

    resp = submit_result(sh["id"], ctx["lab"]["id"],
                         [{"name": "glucose", "score": 95}],
                         collected_at="2026-09-02T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_CLOSED.value, 409)


def test_pt_event_score_input_set_excludes_void_results(api):
    """PRD §3.2: "A `PTCoordinator` may void a result that is still `SUBMITTED`
    (a test-driving correction); attempting to void a `GRADED` result is
    rejected with `ERR_RESULT_ALREADY_GRADED`."

    Design: Corner/calculations/pt_event_score_input_set_excludes_void_results
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    result = submit_result_ok(sh["id"], ctx["lab"]["id"],
                              [{"name": "glucose", "score": 95}])
    assert result["status"] == "GRADED"

    resp = api.void_pt_result(result["id"], PTC)
    validate_error(resp, ApiErrorId.ERR_RESULT_ALREADY_GRADED.value, 409)

    after = get_success_data(api.get_pt_result(result["id"], OFFICER))
    assert after["status"] == "GRADED"
    enr = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr["standing_per_event"] == "SATISFACTORY"
    assert enr["standing_rolling"] == "SATISFACTORY"
    assert enr["unsuccessful_event_streak"] == 0


def test_clock_endpoint_sets_time_and_fires_automatic_transitions(api):
    """PRD §2.4: "Advancing the clock fires three families of automatic
    transitions: any `OPEN` shipment whose `due_at` the new clock value exceeds
    is closed with `closure_reason` set to `DEADLINE_ELAPSED`"

    Design: Corner/endpoints/clock_endpoint_sets_time_and_fires_automatic_transitions
    """
    ctx = setup_pt_active_enrollment(analytes=[{"name": "glucose", "critical": True}])
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")

    get_success_data(api.set_clock("2026-09-11T00:00:01Z", ADMIN))
    sh_after = get_success_data(api.get_pt_shipment(sh["id"], OFFICER))
    assert sh_after["status"] == "CLOSED"
    assert sh_after["closure_reason"] == "DEADLINE_ELAPSED"

    resp = submit_result(sh["id"], ctx["lab"]["id"],
                         [{"name": "glucose", "score": 95}],
                         collected_at="2026-09-02T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_CLOSED.value, 409)
