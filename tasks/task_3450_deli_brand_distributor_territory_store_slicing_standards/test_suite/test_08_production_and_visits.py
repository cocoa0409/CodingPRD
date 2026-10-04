"""Plant production windows and service-visit spacing/workflow (PRD §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_plant,
    create_production_run,
    create_production_run_payload,
    create_product,
    create_service_visit_payload,
    create_visit,
    make_distributor_rep_headers,
    make_plant_scheduler_headers,
    review_visit,
    setup_approved_account,
    submit_visit,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def _plant_and_product():
    return create_plant(code="PL1", name="Plant 1"), create_product(code="P1", name="Item")


def test_planned_units_equal_to_capacity_allowed(api):
    """PRD §3.4: "The plan must fit the line: `planned_units` may not exceed
    `capacity_units`, though planning exactly to capacity is allowed; over-planning
    is rejected with `ERR_CAPACITY_EXCEEDED`."

    The integer-capacity boundary from below: planned == capacity schedules the run.

    Design: Difficulty/boundary_precision_check/capacity_equality_allowed_excess_rejected
    """
    plant, product = _plant_and_product()
    run = create_production_run(plant, product, capacity_units=100, planned_units=100)
    assert run["status"] == "SCHEDULED", "planning exactly to capacity is allowed"


def test_planned_units_above_capacity_rejected(api):
    """PRD §3.4: "The plan must fit the line: `planned_units` may not exceed
    `capacity_units`, though planning exactly to capacity is allowed; over-planning
    is rejected with `ERR_CAPACITY_EXCEEDED`."

    The boundary from above: planned == capacity + 1 is over-planning.

    Design: Difficulty/boundary_precision_check/capacity_equality_allowed_excess_rejected
    """
    plant, product = _plant_and_product()
    resp = api.create_production_run(
        create_production_run_payload(
            plant["id"], product["id"], capacity_units=100, planned_units=101),
        make_plant_scheduler_headers(plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_run_window_overlap_rejected(api):
    """PRD §3.4: "Runs on the same line are also kept apart temporally: considering
    runs at the same plant with the same `line_code`, ignoring any in `CANCELLED`,
    each window is a half-open interval that includes its start and excludes its end,
    and a new run is rejected with `ERR_RUN_OVERLAP` when its window begins before an
    existing window ends while that existing window begins before the new window
    ends."

    Starting at 11:59:59 falls inside the existing [08:00, 12:00) window.

    Design: Difficulty/resource_temporal_overlap/run_window_half_open_adjacency
    """
    plant, product = _plant_and_product()
    create_production_run(
        plant, product, window_start="2026-09-01T08:00:00Z",
        window_end="2026-09-01T12:00:00Z", planned_units=50)
    resp = api.create_production_run(
        create_production_run_payload(
            plant["id"], product["id"],
            window_start="2026-09-01T11:59:59Z", window_end="2026-09-01T13:00:00Z",
            planned_units=50),
        make_plant_scheduler_headers(plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RUN_OVERLAP)


def test_run_window_touching_boundary_allowed(api):
    """PRD §3.4: "Touching windows are expressly permitted — a run beginning exactly
    when another ends does not overlap."

    Starting at exactly 12:00:00 touches the half-open [08:00, 12:00) window without
    overlapping it.

    Design: Difficulty/resource_temporal_overlap/run_window_half_open_adjacency
    """
    plant, product = _plant_and_product()
    create_production_run(
        plant, product, window_start="2026-09-01T08:00:00Z",
        window_end="2026-09-01T12:00:00Z", planned_units=50)
    resp = api.create_production_run(
        create_production_run_payload(
            plant["id"], product["id"],
            window_start="2026-09-01T12:00:00Z", window_end="2026-09-01T16:00:00Z",
            planned_units=50),
        make_plant_scheduler_headers(plant["id"]),
    )
    run = validate_success(resp, expected_status=201)
    assert run["status"] == "SCHEDULED", "half-open adjacency is not an overlap"


def test_visit_twenty_nine_minute_gap_rejected(api):
    """PRD §3.6: "Visits at one account may not crowd each other: considering the
    account's visits in every status except `CANCELLED`, a new visit is rejected with
    `ERR_VISIT_TOO_CLOSE` when its window overlaps an existing window or when the gap
    separating the two windows is strictly less than 30 minutes — a gap of exactly 30
    minutes is permitted."

    A 29-minute gap after the 09:00-10:00 visit is strictly less than the buffer.

    Design: Difficulty/resource_temporal_overlap/visit_spacing_thirty_minute_buffer
    """
    ctx = setup_approved_account()
    create_visit(ctx["account"], ctx["distributor"],
                 "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    resp = api.create_service_visit(
        create_service_visit_payload(
            ctx["account"]["id"],
            window_start="2026-09-02T10:29:00Z", window_end="2026-09-02T11:00:00Z"),
        make_distributor_rep_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_TOO_CLOSE)


def test_visit_exactly_thirty_minute_gap_allowed(api):
    """PRD §3.6: "a new visit is rejected with `ERR_VISIT_TOO_CLOSE` when its window
    overlaps an existing window or when the gap separating the two windows is
    strictly less than 30 minutes — a gap of exactly 30 minutes is permitted."

    A 30-minute gap after the 09:00-10:00 visit is exactly the permitted boundary.

    Design: Difficulty/resource_temporal_overlap/visit_spacing_thirty_minute_buffer
    """
    ctx = setup_approved_account()
    create_visit(ctx["account"], ctx["distributor"],
                 "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    resp = api.create_service_visit(
        create_service_visit_payload(
            ctx["account"]["id"],
            window_start="2026-09-02T10:30:00Z", window_end="2026-09-02T11:30:00Z"),
        make_distributor_rep_headers(ctx["distributor"]["id"]),
    )
    visit = validate_success(resp, expected_status=201)
    assert visit["status"] == "SCHEDULED"


def test_inverted_run_window_is_validation_error(api):
    """PRD §2.8: "required fields are present, types match, enum values fall within
    their declared sets, integer quantities are positive, a window's start precedes
    its end, and a promo's `start_date` is on or before its `end_date`; failure is
    `ERR_VALIDATION`." and PRD §3.4: "a `window_start` and a `window_end` that must
    fall strictly after the start".

    A zero-length window (start == end) is a shape failure — 400, not a 409 overlap.

    Design: Corner/validations/run_window_inverted_rejected_as_validation
    """
    plant, product = _plant_and_product()
    resp = api.create_production_run(
        create_production_run_payload(
            plant["id"], product["id"],
            window_start="2026-09-01T06:00:00Z", window_end="2026-09-01T06:00:00Z",
            planned_units=50),
        make_plant_scheduler_headers(plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_service_visit_rework_resubmit_cycle(api):
    """PRD §3.6: "a visit sent back for rework resubmits along `REWORK` → `SUBMITTED`
    through the identical act." and "A verdict of `VERIFY` moves the visit to its
    terminal `VERIFIED`; a verdict of `REWORK` returns it to `REWORK`, from which the
    representative may submit again."

    The cyclic rework loop REWORK -> SUBMITTED -> VERIFIED succeeds, and the
    resubmission overwrites the report: score 85 replaces 70.

    Design: Corner/state_machines/service_visit_rework_resubmit_cycle
    """
    ctx = setup_approved_account()
    visit = create_visit(ctx["account"], ctx["distributor"],
                         "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    visit = submit_visit(visit, ctx["distributor"], score=70, rotation_compliant=False)
    visit = review_visit(visit, "REWORK")
    assert visit["status"] == "REWORK"

    resubmitted = submit_visit(visit, ctx["distributor"], score=85)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["score"] == 85, "the resubmission overwrites the prior score"

    verified = review_visit(resubmitted, "VERIFY")
    assert verified["status"] == "VERIFIED"
    assert verified["score"] == 85
