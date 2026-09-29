"""Two occupancy rules on date intervals with deliberately opposite conventions."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PRACTICE_PERIOD_OVERLAP, ERR_REVIEW_WINDOW_CONFLICT
from test_helpers.assertions import assert_pagination_meta, field_sequence
from test_helpers.test_users import ADMIN, BASELINE_VERIFIER, make_producer_headers


def _tract_world(api):
    """T-101 held by a live COVER_CROP project; T-500 held by a revoked one.

    PP-Z is registered with `baseline_met` false and then driven to REVOKED by a
    BASELINE event with outcome FAIL, so its interval no longer occupies T-500.
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"])
    producer = fx.make_producer(api)
    producer_id = producer["id"]

    pp_a = fx.make_practice_project(
        api,
        producer_id,
        reaches["r_up"]["id"],
        "T-101",
        practice_type="COVER_CROP",
        enrolled_acres=100.00,
        effective_start_date="2026-01-01",
        effective_end_date="2027-01-01",
    )
    pp_z = fx.make_practice_project(
        api,
        producer_id,
        reaches["r_up"]["id"],
        "T-500",
        practice_type="COVER_CROP",
        enrolled_acres=50.00,
        baseline_met=False,
        pre_load_lbs_yr=500.00,
        post_load_lbs_yr=200.00,
        effective_start_date="2026-01-01",
        effective_end_date="2027-01-01",
    )
    failed = fx.file_verification_event(
        api,
        pp_z["id"],
        "BASELINE",
        "FAIL",
        BASELINE_VERIFIER,
        narrative="Tract T-500 does not meet the regulatory baseline.",
    )
    assert failed["resulting_project_status"] == "REVOKED", failed
    revoked = get_success_data(api.get_practice_project(pp_z["id"], ADMIN))
    assert revoked["status"] == "REVOKED", revoked

    return {
        "watershed": watershed,
        "reaches": reaches,
        "producer_id": producer_id,
        "pp_a": pp_a,
        "pp_z": pp_z,
    }


def test_a_practice_starting_on_the_incumbents_end_date_is_accepted(api):
    """The interval is half-open, so touching periods do not overlap.

    "Because the interval is half-open, touching periods do not overlap: a new
    project whose `effective_start_date` equals an existing project's
    `effective_end_date` is accepted."

    Design: Difficulty/resource_temporal_overlap/practice_period_half_open_adjacency_accepted_and_revoked_project_frees_the_tract
    """
    world = _tract_world(api)
    producer_id = world["producer_id"]
    headers = make_producer_headers(producer_id)

    adjacent = validate_success(
        api.create_practice_project(
            f.practice_project_payload(
                producer_id,
                world["reaches"]["r_up"]["id"],
                "T-101",
                practice_type="COVER_CROP",
                pre_load_lbs_yr=900.00,
                effective_start_date="2027-01-01",
                effective_end_date="2028-01-01",
                vintage_year=2027,
            ),
            headers,
        ),
        201,
    )

    assert adjacent["status"] == "REGISTERED", adjacent
    assert adjacent["effective_start_date"] == "2027-01-01", adjacent

    one_day_earlier = api.create_practice_project(
        f.practice_project_payload(
            producer_id,
            world["reaches"]["r_up"]["id"],
            "T-101",
            practice_type="COVER_CROP",
            pre_load_lbs_yr=900.00,
            effective_start_date="2026-12-31",
            effective_end_date="2027-06-30",
            vintage_year=2027,
        ),
        headers,
    )
    validate_error(one_day_earlier, ERR_PRACTICE_PERIOD_OVERLAP, 409)

    _, meta = validate_paginated(api.list_practice_projects(ADMIN, {"producer_id": producer_id}))
    assert_pagination_meta(meta, 10, 0, 3, False)


def test_a_different_practice_type_and_a_revoked_incumbent_leave_the_tract_free(api):
    """Occupancy is keyed on the pair, and only live statuses hold the key.

    "No other practice project sharing this project's `tract_code` and
    `practice_type` and sitting in any of the live statuses ... A revoked project
    no longer occupies its tract and never blocks a new registration."

    Design: Difficulty/resource_temporal_overlap/practice_period_half_open_adjacency_accepted_and_revoked_project_frees_the_tract
    """
    world = _tract_world(api)
    producer_id = world["producer_id"]

    other_practice = fx.make_practice_project(
        api,
        producer_id,
        world["reaches"]["r_up"]["id"],
        "T-101",
        practice_type="RIPARIAN_BUFFER",
        enrolled_acres=20.00,
        pre_load_lbs_yr=300.00,
        post_load_lbs_yr=100.00,
        effective_start_date="2026-06-01",
        effective_end_date="2026-09-01",
    )
    assert other_practice["practice_type"] == "RIPARIAN_BUFFER", other_practice
    assert other_practice["status"] == "REGISTERED", other_practice

    reuse = fx.make_practice_project(
        api,
        producer_id,
        world["reaches"]["r_up"]["id"],
        "T-500",
        practice_type="COVER_CROP",
        enrolled_acres=50.00,
        pre_load_lbs_yr=500.00,
        post_load_lbs_yr=200.00,
        effective_start_date="2026-03-01",
        effective_end_date="2026-12-01",
    )
    assert reuse["status"] == "REGISTERED", reuse
    assert reuse["effective_start_date"] == "2026-03-01", reuse

    _, meta = validate_paginated(api.list_practice_projects(ADMIN, {"producer_id": producer_id}))
    assert_pagination_meta(meta, 10, 0, 4, False)


def _review_world(api):
    """One OPEN review holding the closed window 2026-01-01..2026-06-30."""
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    ar_1 = fx.make_adaptive_review(
        api, watershed["id"], "AR-1", "2026-01-01", "2026-06-30"
    )
    assert ar_1["status"] == "OPEN", ar_1
    return {"watershed_id": watershed["id"], "ar_1": ar_1}


def test_review_windows_that_merely_abut_are_rejected_on_both_sides(api):
    """One clear calendar day is demanded, so back-to-back windows crowd.

    "the new window is acceptable only if its start falls more than one day after
    the existing window's end, or its end falls more than one day before the
    existing window's start; anything closer, including windows that merely abut,
    is rejected with `ERR_REVIEW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/adaptive_review_windows_require_one_clear_day_and_adjacency_is_rejected
    """
    world = _review_world(api)
    watershed_id = world["watershed_id"]

    touch_after = api.create_adaptive_review(
        watershed_id, f.adaptive_review_payload("AR-TOUCH-AFTER", "2026-07-01", "2026-12-31"), ADMIN
    )
    validate_error(touch_after, ERR_REVIEW_WINDOW_CONFLICT, 409)

    touch_before = api.create_adaptive_review(
        watershed_id,
        f.adaptive_review_payload("AR-TOUCH-BEFORE", "2025-07-01", "2025-12-31"),
        ADMIN,
    )
    validate_error(touch_before, ERR_REVIEW_WINDOW_CONFLICT, 409)

    incumbent = get_success_data(api.get_adaptive_review(world["ar_1"]["id"], ADMIN))
    assert incumbent["status"] == "OPEN", incumbent
    assert incumbent["period_start_date"] == "2026-01-01", incumbent

    _, meta = validate_paginated(api.list_adaptive_reviews(ADMIN, {"watershed_id": watershed_id}))
    assert_pagination_meta(meta, 10, 0, 1, False)


def test_one_clear_day_is_enough_and_the_gap_is_rechecked_against_new_windows(api):
    """The separation is re-evaluated against every existing window, including fresh ones.

    "the new closed window must be separated from every existing review window on
    that watershed — whether that review is `OPEN` or `FINALIZED` — by at least one
    clear calendar day on both sides."

    Design: Difficulty/resource_temporal_overlap/adaptive_review_windows_require_one_clear_day_and_adjacency_is_rejected
    """
    world = _review_world(api)
    watershed_id = world["watershed_id"]

    before_ok = validate_success(
        api.create_adaptive_review(
            watershed_id,
            f.adaptive_review_payload("AR-BEFORE-OK", "2025-07-01", "2025-12-30"),
            ADMIN,
        ),
        201,
    )
    assert before_ok["period_end_date"] == "2025-12-30", before_ok
    assert before_ok["status"] == "OPEN", before_ok

    after_ok = validate_success(
        api.create_adaptive_review(
            watershed_id,
            f.adaptive_review_payload("AR-AFTER-OK", "2026-07-02", "2026-12-31"),
            ADMIN,
        ),
        201,
    )
    assert after_ok["period_start_date"] == "2026-07-02", after_ok
    assert after_ok["status"] == "OPEN", after_ok

    touching_the_new_window = api.create_adaptive_review(
        watershed_id, f.adaptive_review_payload("AR-TOUCH-NEW", "2027-01-01", "2027-06-30"), ADMIN
    )
    validate_error(touching_the_new_window, ERR_REVIEW_WINDOW_CONFLICT, 409)

    rows, meta = validate_paginated(
        api.list_adaptive_reviews(ADMIN, {"watershed_id": watershed_id})
    )
    assert_pagination_meta(meta, 10, 0, 3, False)
    assert field_sequence(rows, "period_start_date") == [
        "2025-07-01",
        "2026-01-01",
        "2026-07-02",
    ], rows
