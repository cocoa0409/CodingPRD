"""Imagery task lifecycle: capture window, blur obligations, capacity, and
the region posture cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    capture_imagery_task,
    create_imagery_task_payload,
    get_region,
    make_imagery_task,
    make_operator_headers,
    make_region,
    schedule_imagery_task,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_capture_posture_cascade_to_clearance_pending(api):
    """PRD §3.8: "A successful capture moves the task through `CAPTURED`
    directly into `BLUR_PENDING` within the same request, increments the
    region's `privacy_pending_count` by one, and bubbles the region's posture
    to `CLEARANCE_PENDING` if it was previously `CLEAR` or `ACTIVE`."
    PRD §2.8: "The posture `posture` then follows a strict priority: a region
    whose frozen flag is set reports `FROZEN`; otherwise, a region with a
    `privacy_pending_count` greater than zero reports `CLEARANCE_PENDING`;
    otherwise, a region in which at least one imagery task has captured media
    reports `CLEAR`; otherwise the region reports `ACTIVE`."

    Design: Difficulty/transitive_cascade/imagery_capture_region_posture_cascade
    """
    region = make_region(name="R8")
    task = make_imagery_task(region["id"], collection_zone="zone-A",
                             operator_id="op-1",
                             window_start="2026-09-02T00:00:00Z",
                             window_end="2026-09-05T00:00:00Z",
                             blur_obligation="FACES_AND_PLATES")
    schedule_imagery_task(task["id"], "op-1")
    set_clock("2026-09-03T00:00:00Z")

    resp = api.capture_imagery_task(task["id"], {"capture_media_count": 10},
                                    make_operator_headers("op-1"))
    captured = validate_success(resp)
    assert captured["status"] == "BLUR_PENDING", (
        f"CAPTURED -> BLUR_PENDING within the same request, "
        f"got {captured['status']}"
    )

    region = get_region(region["id"])
    assert region["privacy_pending_count"] == 1
    assert region["posture"] == "CLEARANCE_PENDING"


def test_posture_bubble_up_recomputes_on_region_read(api):
    """PRD §2.8: "Every region maintains a privacy posture that summarizes the
    state of imagery work inside it, recomputed whenever an imagery task is
    captured, blur-completed, published, or cancelled, and also on every
    region read."
    PRD §2.8: "The posture `posture` then follows a strict priority: a region
    whose frozen flag is set reports `FROZEN`; otherwise, a region with a
    `privacy_pending_count` greater than zero reports `CLEARANCE_PENDING`;
    otherwise, a region in which at least one imagery task has captured media
    reports `CLEAR`; otherwise the region reports `ACTIVE`."

    Design: Difficulty/transitive_cascade/imagery_capture_region_posture_cascade
    """
    region = make_region(name="R8b")
    fresh = get_region(region["id"])
    assert fresh["posture"] == "ACTIVE"
    assert fresh["privacy_pending_count"] == 0

    task = make_imagery_task(region["id"], collection_zone="zone-A",
                             operator_id="op-1",
                             window_start="2026-09-02T00:00:00Z",
                             window_end="2026-09-05T00:00:00Z",
                             blur_obligation="FACES_ONLY")
    schedule_imagery_task(task["id"], "op-1")
    set_clock("2026-09-03T00:00:00Z")
    capture_imagery_task(task["id"], 4, "op-1")

    region = get_region(region["id"])
    assert region["privacy_pending_count"] == 1
    assert region["posture"] == "CLEARANCE_PENDING"


def test_schedule_allowed_in_clearance_pending_region(api):
    """PRD §3.8: "Scheduling a planned task is where the guards live, and the
    region's posture gates first — scheduling in a `FROZEN` region is refused
    with `ERR_REGION_FROZEN`, while `ACTIVE`, `CLEAR`, and `CLEARANCE_PENDING`
    admit it."
    PRD §2.8: "A region carries a computed `privacy_pending_count`: the number
    of its imagery tasks currently in `CAPTURED`, `BLUR_PENDING`, or
    `REPROCESS` status."

    Design: Difficulty/cross_entity_state_dependency/imagery_schedule_gated_on_region_posture_pair
    """
    region = make_region(name="R14")
    first = make_imagery_task(region["id"], collection_zone="zone-A",
                              operator_id="op-1",
                              window_start="2026-09-02T00:00:00Z",
                              window_end="2026-09-05T00:00:00Z",
                              blur_obligation="FACES_ONLY")
    schedule_imagery_task(first["id"], "op-1")
    set_clock("2026-09-03T00:00:00Z")
    capture_imagery_task(first["id"], 4, "op-1")

    second = make_imagery_task(region["id"], collection_zone="zone-B",
                               operator_id="op-2",
                               window_start="2026-09-03T00:00:00Z",
                               window_end="2026-09-04T00:00:00Z",
                               blur_obligation="FULL_PRIVACY")
    resp = api.schedule_imagery_task(second["id"], make_operator_headers("op-2"))
    scheduled = validate_success(resp)
    assert scheduled["status"] == "SCHEDULED", (
        f"CLEARANCE_PENDING admits scheduling, got {scheduled['status']}"
    )

    region = get_region(region["id"])
    assert region["posture"] == "CLEARANCE_PENDING", (
        "posture derived from the sibling task's pending state"
    )


def test_schedule_in_active_region_sets_scheduled(api):
    """PRD §3.8: "Scheduling a planned task is where the guards live, and the
    region's posture gates first — scheduling in a `FROZEN` region is refused
    with `ERR_REGION_FROZEN`, while `ACTIVE`, `CLEAR`, and `CLEARANCE_PENDING`
    admit it."
    PRD §3.8: "A task that passes all three becomes `SCHEDULED`; the region's
    privacy ledger is untouched at this point because nothing has been
    captured yet."

    Design: Difficulty/cross_entity_state_dependency/imagery_schedule_gated_on_region_posture_pair
    """
    region = make_region(name="R14b")
    task = make_imagery_task(region["id"], collection_zone="zone-A",
                             operator_id="op-1")
    scheduled = schedule_imagery_task(task["id"], "op-1")
    assert scheduled["status"] == "SCHEDULED"

    region = get_region(region["id"])
    assert region["posture"] == "ACTIVE", (
        f"nothing captured yet so the ledger is untouched, got {region['posture']}"
    )
    assert region["privacy_pending_count"] == 0


def test_half_open_adjacency_allowed_overlap_rejected(api):
    """PRD §3.8: "Second, no other non-terminal task in the same region and
    collection zone may hold an overlapping window; overlap is judged on the
    half-open intervals, so adjacency where one window's end equals the
    other's start is allowed, and a true overlap is refused with
    `ERR_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.8: "Capture windows use half-open semantics: the window runs from
    its start up to but not including its end, so two windows where one ends
    exactly when the other begins do not overlap."

    Design: Difficulty/resource_temporal_overlap/imagery_half_open_adjacency_allowed_overlap_rejected
    """
    region = make_region(name="R15")
    first = make_imagery_task(region["id"], collection_zone="zone-A",
                              operator_id="op-1",
                              window_start="2026-09-02T08:00:00Z",
                              window_end="2026-09-02T16:00:00Z",
                              blur_obligation="FACES_ONLY")
    schedule_imagery_task(first["id"], "op-1")

    adjacent = make_imagery_task(region["id"], collection_zone="zone-A",
                                 operator_id="op-1",
                                 window_start="2026-09-02T16:00:00Z",
                                 window_end="2026-09-03T00:00:00Z",
                                 blur_obligation="FACES_ONLY")
    overlapping = make_imagery_task(region["id"], collection_zone="zone-A",
                                    operator_id="op-1",
                                    window_start="2026-09-02T15:00:00Z",
                                    window_end="2026-09-02T17:00:00Z",
                                    blur_obligation="FACES_ONLY")

    resp = api.schedule_imagery_task(adjacent["id"], make_operator_headers("op-1"))
    scheduled = validate_success(resp)
    assert scheduled["status"] == "SCHEDULED", (
        "adjacency end == start is allowed under half-open semantics"
    )

    resp = api.schedule_imagery_task(overlapping["id"], make_operator_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_contained_window_overlap_rejected(api):
    """PRD §3.8: "Second, no other non-terminal task in the same region and
    collection zone may hold an overlapping window; overlap is judged on the
    half-open intervals, so adjacency where one window's end equals the
    other's start is allowed, and a true overlap is refused with
    `ERR_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/imagery_half_open_adjacency_allowed_overlap_rejected
    """
    region = make_region(name="R15b")
    first = make_imagery_task(region["id"], collection_zone="zone-A",
                              operator_id="op-1",
                              window_start="2026-09-02T08:00:00Z",
                              window_end="2026-09-02T16:00:00Z",
                              blur_obligation="FACES_ONLY")
    schedule_imagery_task(first["id"], "op-1")

    contained = make_imagery_task(region["id"], collection_zone="zone-A",
                                  operator_id="op-1",
                                  window_start="2026-09-02T10:00:00Z",
                                  window_end="2026-09-02T12:00:00Z",
                                  blur_obligation="FACES_ONLY")
    resp = api.schedule_imagery_task(contained["id"], make_operator_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_blur_incomplete_rejected_then_completed(api):
    """PRD §3.8: "When the obligation is `FACES_AND_PLATES` or `FULL_PRIVACY`,
    the operator must report a `blurred_media_count` at least equal to the
    `capture_media_count`; under `FACES_ONLY`, at least one blurred item
    suffices. Falling short is refused with `ERR_BLUR_INCOMPLETE` (HTTP 422)."
    PRD §3.8: "A complete blur moves the task to `BLURRED`."

    Design: Corner/state_machines/blur_incomplete_rejected_then_completed
    """
    region = make_region(name="RB")
    task = make_imagery_task(region["id"], collection_zone="zone-1",
                             operator_id="op-1",
                             window_start="2026-09-02T00:00:00Z",
                             window_end="2026-09-05T00:00:00Z",
                             blur_obligation="FACES_AND_PLATES")
    schedule_imagery_task(task["id"], "op-1")
    set_clock("2026-09-03T00:00:00Z")
    capture_imagery_task(task["id"], 10, "op-1")

    resp = api.blur_complete_imagery_task(
        task["id"], {"blurred_media_count": 7}, make_operator_headers("op-1")
    )
    validate_error(resp, ApiErrorId.ERR_BLUR_INCOMPLETE)

    resp = api.blur_complete_imagery_task(
        task["id"], {"blurred_media_count": 10}, make_operator_headers("op-1")
    )
    blurred = validate_success(resp)
    assert blurred["status"] == "BLURRED"


def test_capture_outside_window_rejected(api):
    """PRD §3.8: "Capture is time-boxed: the logical clock must sit within the
    task's window — before the start or at/after the end draws
    `ERR_OUTSIDE_WINDOW` (HTTP 409) — and the operator supplies a
    `capture_media_count` of at least one."

    Design: Corner/state_machines/capture_outside_window_rejected
    """
    region = make_region(name="ROW")
    task = make_imagery_task(region["id"], collection_zone="zone-2",
                             operator_id="op-1",
                             window_start="2026-09-10T00:00:00Z",
                             window_end="2026-09-12T00:00:00Z",
                             blur_obligation="FACES_ONLY")
    schedule_imagery_task(task["id"], "op-1")
    # Clock stays at the 2026-09-01 default: before the window opens.
    resp = api.capture_imagery_task(task["id"], {"capture_media_count": 5},
                                    make_operator_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)
    read = validate_success(api.get_imagery_task(task["id"], ADMIN))
    assert read["status"] == "SCHEDULED"


def test_imagery_capacity_cap_enforced(api):
    """PRD §2.8: "The input field `max_active_imagery_tasks`, defaulting to 5,
    caps the number of tasks in the region whose status is any of `PLANNED`,
    `SCHEDULED`, `CAPTURED`, `BLUR_PENDING`, `REPROCESS`, or `BLURRED`;
    scheduling a task that would meet or exceed the cap is rejected with
    `ERR_IMAGERY_CAPACITY` (HTTP 409)."
    PRD §3.8: "Third, the region's active-task count must remain below its
    `max_active_imagery_tasks` cap, otherwise `ERR_IMAGERY_CAPACITY`."

    Design: Corner/validations/imagery_capacity_cap_enforced
    """
    region = make_region(name="RCap", max_active_imagery_tasks=1)
    first = make_imagery_task(region["id"], collection_zone="z1",
                              operator_id="op-1",
                              window_start="2026-09-02T00:00:00Z",
                              window_end="2026-09-03T00:00:00Z",
                              blur_obligation="FACES_ONLY")
    schedule_imagery_task(first["id"], "op-1")
    second = make_imagery_task(region["id"], collection_zone="z2",
                               operator_id="op-1",
                               window_start="2026-09-02T00:00:00Z",
                               window_end="2026-09-03T00:00:00Z",
                               blur_obligation="FACES_ONLY")

    resp = api.schedule_imagery_task(second["id"], make_operator_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_IMAGERY_CAPACITY)
    read = validate_success(api.get_imagery_task(second["id"], ADMIN))
    assert read["status"] == "PLANNED"
