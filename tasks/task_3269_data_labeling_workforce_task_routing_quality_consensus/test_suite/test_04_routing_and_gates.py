"""Worker routing: selector eligibility, cold start, restricted access, lanes."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    attach_item,
    create_program,
    create_unit,
    dispatch_panel,
    enroll_qualification,
    get_program,
    make_pool,
    open_program,
    production_commits,
    register_worker,
    report_incident,
    verify_qualification,
)


def test_empty_pool_returns_no_eligible_worker_and_a_verified_peer_fixes_it(api):
    """PRD §3.3: "dispatch must produce a candidate: when the selector described
    in §3.4 returns an empty pool the request is refused with
    `ERR_NO_ELIGIBLE_WORKER` (422), a code reserved for that case alone."

    Design: Corner/validations/a_worker_absent_from_the_pool_succeeds_where_a_present_one_fails
    """
    program = create_program(language_code="es-MX")
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)

    wrong_language = register_worker("tomas-ibarra")
    enroll_qualification(wrong_language, "vi-VN", "PROFICIENT", training_required_count=0)
    verify_qualification(wrong_language, "vi-VN", "PROFICIENT")

    item = attach_item(unit, item_key="i-0001")
    validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_NO_ELIGIBLE_WORKER", 422)

    live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert live["consensus_status"] == "PENDING"
    assert production_commits(live) == []

    make_pool(1, "es-MX", "PROFICIENT")
    dispatched = dispatch_panel(live)
    assert len(production_commits(dispatched)) == 1


def test_worker_restricted_and_program_restricted_are_distinct_gates(api):
    """PRD §2.5: "On the worker, the mirror flag is `restricted`, true while any
    incident naming that worker has status `OPEN`. A restricted worker may not
    commit labels, may not be dispatched work, and may not be paid"

    PRD §2.5: "`operational_restricted` is true while any incident on that program
    has status `OPEN` *and* a severity that is `MAJOR` or `CATASTROPHIC`."

    Design: Corner/errors/worker_restriction_error_is_distinct_from_program_restriction
    """
    program, unit, pool, item, commits = setup_minimal(severity="MINOR")
    validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_NO_ELIGIBLE_WORKER", 422)

    program2 = create_program(program_code="AX-4411", sensitivity_class="SENSITIVE")
    unit2 = create_unit(program2, unit_code="U-1", panel_size=1)
    open_program(program2)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT", handles=["tomas-ibarra"])[0]
    item2 = attach_item(unit2, item_key="i-0001")
    report_incident(worker, severity="MAJOR", program_code="AX-4411")

    validate_error(
        api_client.dispatch_panel(item2["id"], ADMIN),
        "ERR_PROGRAM_OPERATIONALLY_RESTRICTED",
        409,
    )


def setup_minimal(severity="MINOR"):
    """Engagement + unit + one released piece with an incident on the only worker."""
    program = create_program(sensitivity_class="SENSITIVE")
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT")[0]
    item = attach_item(unit, item_key="i-0001")
    report_incident(worker, severity=severity, program_code="AX-4410")
    return program, unit, [worker], item, []


def test_restricted_engagement_requires_an_expert_qualified_worker(api):
    """PRD §2.5: "An engagement whose `sensitivity_class` is `RESTRICTED` may only
    be served by workers whose qualification carries `restricted_accessible` true,
    which is a condition that holds while the qualification's `tier` is `EXPERT`
    *and* its status is `QUALIFIED` simultaneously."

    Design: Corner/cross_cutting_complexity_layers/sensitive_program_withholds_the_payload_handle_and_restricted_class_requires_expert
    """
    program = create_program(sensitivity_class="RESTRICTED")
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    # A PROFICIENT enrollment that is left in training, so the ascent to EXPERT
    # is the act under test.
    worker = register_worker("rosa-diaz")
    enrollment = enroll_qualification(worker, "es-MX", "PROFICIENT", training_required_count=0)
    assert enrollment["status"] == "IN_TRAINING"
    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/secret/0001")

    read = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert read.get("payload_uri") in (None, ""), "a RESTRICTED engagement withholds the handle"

    validate_error(api_client.dispatch_panel(item["id"], ADMIN), "ERR_NO_ELIGIBLE_WORKER", 422)

    # PRD §2.6 pairs the VERIFY action with the tier being verified at, so the
    # PROFICIENT enrollment is lifted to EXPERT in one verification.
    verified = verify_qualification(worker, "es-MX", "EXPERT")
    assert verified["restricted_accessible"] is True
    assert verified["tier"] == "EXPERT"

    dispatched = dispatch_panel(item)
    assert len(production_commits(dispatched)) == 1


def test_sensitive_engagement_withholds_the_payload_handle(api):
    """PRD §3.1: "The `payload_uri` is additionally subject to the confidentiality
    class of the owning engagement: while the engagement's `sensitivity_class` is
    `SENSITIVE` or `RESTRICTED`, the field is omitted from every response that
    carries the piece, even though it remains a required input at creation."

    Design: Corner/cross_cutting_complexity_layers/sensitive_program_withholds_the_payload_handle_and_restricted_class_requires_expert
    """
    program = create_program(sensitivity_class="SENSITIVE")
    unit = create_unit(program, unit_code="U-1")
    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/secret/0001")

    created = api_client.create_item(
        unit["id"], {"item_key": "i-0002", "payload_uri": "s3://ax/secret/0002"}, ADMIN
    )
    assert created.status_code == 201, "the handle remains a required input at creation"

    read = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
    assert read.get("payload_uri") in (None, ""), "the handle is withheld on read"

    plain = create_program(program_code="AX-4419", sensitivity_class="STANDARD")
    plain_unit = create_unit(plain, unit_code="U-1")
    visible = attach_item(plain_unit, item_key="i-0001", payload_uri="s3://ax/plain/0001")
    assert visible["payload_uri"] == "s3://ax/plain/0001", "a STANDARD engagement exposes it"


def test_worker_lane_conflict_on_touching_closed_intervals(api):
    """PRD §3.4: "the candidate must hold no `DISPATCHED` commit on a different
    piece whose closed dispatch-to-deadline interval touches or overlaps this
    dispatch's interval. That last condition is a lane exclusion, and it is
    deliberately conservative about adjacency: because the intervals are treated as
    closed, an interval ending exactly when the next begins is a conflict, and the
    offending dispatch is reported as `ERR_WORKER_LANE_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/closed_worker_lane_intervals_versus_disjoint_slots
    """
    program = create_program(commit_deadline_seconds=3600)
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    make_pool(1, "es-MX", "PROFICIENT")
    first = attach_item(unit, item_key="i-0001")
    second = attach_item(unit, item_key="i-0002")

    dispatch_panel(first)
    validate_error(api_client.dispatch_panel(second["id"], ADMIN), "ERR_WORKER_LANE_CONFLICT", 409)

    # Advancing to the exact end of the first lane still leaves them touching.
    get_success_data(api_client.set_clock("2026-09-01T01:00:00Z", ADMIN), 200)
    validate_error(api_client.dispatch_panel(second["id"], ADMIN), "ERR_WORKER_LANE_CONFLICT", 409)

    # One second past the end clears the conflict.
    get_success_data(api_client.set_clock("2026-09-01T01:00:01Z", ADMIN), 200)
    dispatch_panel(second)


def test_second_pool_member_clears_the_lane_conflict(api):
    """PRD §3.4: "the candidate must hold no `DISPATCHED` commit on a different
    piece whose closed dispatch-to-deadline interval touches or overlaps this
    dispatch's interval."

    Design: Difficulty/resource_temporal_overlap/closed_worker_lane_intervals_versus_disjoint_slots
    """
    program = create_program(commit_deadline_seconds=3600)
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    make_pool(2, "es-MX", "PROFICIENT")
    first = attach_item(unit, item_key="i-0001")
    second = attach_item(unit, item_key="i-0002")

    dispatch_panel(first)
    dispatched = dispatch_panel(second)
    assert len(production_commits(dispatched)) == 1, "a second eligible member clears the overlap"


def test_half_open_coverage_window_admits_adjacency_and_rejects_overlap(api):
    """PRD §3.2: "when the failure is a positive-length overlap between the unit's
    coverage window and the engagement's blackout window it is
    `ERR_COVERAGE_WINDOW_OVERLAP` (409)"

    Design: Difficulty/resource_temporal_overlap/half_open_coverage_window_versus_blackout
    """
    program = create_program()
    adjacent = create_unit(
        program, unit_code="U-ADJ", max_items=5, coverage_end_utc="2026-09-20T00:00:00Z"
    )
    overlapping = create_unit(
        program,
        unit_code="U-OVER",
        max_items=5,
        coverage_start_utc="2026-09-19T23:00:00Z",
        coverage_end_utc="2026-09-20T01:00:00Z",
    )
    equal_start = create_unit(
        program,
        unit_code="U-EQ",
        max_items=5,
        coverage_start_utc="2026-09-20T00:00:00Z",
        coverage_end_utc="2026-09-21T00:00:00Z",
    )

    activated = get_success_data(
        api_client.advance_unit(adjacent["id"], {"unit_action": "ACTIVATE"}, ADMIN), 200
    )
    assert activated["status"] == "ACTIVE", "a zero-length adjacency is not an overlap"

    validate_error(
        api_client.advance_unit(overlapping["id"], {"unit_action": "ACTIVATE"}, ADMIN),
        "ERR_COVERAGE_WINDOW_OVERLAP",
        409,
    )
    validate_error(
        api_client.advance_unit(equal_start["id"], {"unit_action": "ACTIVATE"}, ADMIN),
        "ERR_COVERAGE_WINDOW_OVERLAP",
        409,
    )