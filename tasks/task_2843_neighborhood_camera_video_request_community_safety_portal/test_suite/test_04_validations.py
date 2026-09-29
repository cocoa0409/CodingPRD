"""Boundary values and refusal identifiers on the portal's validation rules.

The rules exercised here all turn on a single value sitting on one side of a
declared boundary: the flag that comes from the wrong resident, the camera that
lands on a coordinate its owner already occupies, the canvass radius one metre
past the cap and the footage window that ends one second after the logical
clock. Each test pins both sides of the boundary where the contract declares one
— the accepted value and the rejected value — and names the exact error
identifier the rejection must carry.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_officer_headers, make_resident_headers

# The two instants the footage-window legs are measured against: the logical
# clock every scenario here is pinned to, and the instant one second past it.
CLOCK_INSTANT = "2026-08-12T00:00:00Z"
ONE_SECOND_PAST_CLOCK = "2026-08-12T00:00:01Z"


def _agency_areas(api: ApiClient, agency_id: str, officer_id: str) -> Dict[str, Any]:
    """Read the canvass-area collection for one agency and return its page block."""
    rows, meta = validate_paginated(
        api.list_request_areas(
            make_officer_headers(officer_id),
            f.page(limit=10, offset=0, agency_id=agency_id),
        )
    )
    return {"rows": rows, "meta": meta}


# ═══ Flagging one's own post ═══════════════════════════════════════════════

def test_author_flagging_own_post_is_refused_and_does_not_count(api: ApiClient) -> None:
    """An author's flag on their own post is refused and moves no counter.

    PRD: "An author may never flag their own post — `ERR_SELF_FLAG_NOT_ALLOWED` — and no resident may flag the same post twice, because their identifier already appears in `flagged_by_resident_ids` and the second attempt is refused with `ERR_DUPLICATE_FLAG`."
    PRD: "Each accepted flag increments `flag_count` by 1, appends the flagger, and advances the post's `version` by 1."

    Design: Corner/validations/post_flagged_by_its_own_author_rejected
    """
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    post = fixtures.create_post(
        api,
        author["id"],
        body="The alley gate has been left unlatched every evening this week.",
        category=k.CATEGORY_SAFETY_REPORT,
        post_x_m=0,
        post_y_m=0,
    )
    created_version = post["version"]
    assert post["state"] == k.POST_PUBLISHED
    assert post["flag_count"] == 0

    refused = api.flag_post(
        post["id"],
        f.flag_payload(flag_reason="Flagging my own post to test the guard."),
        make_resident_headers(author["id"]),
    )
    validate_error(refused, ApiErrorId.SELF_FLAG_NOT_ALLOWED.value, 409)

    unchanged = fixtures.read_post(api, post["id"])
    assert unchanged["flag_count"] == 0, "A refused self-flag must not be counted"
    assert unchanged["state"] == k.POST_PUBLISHED
    assert unchanged["flagged_by_resident_ids"] == []
    assert unchanged["auto_flag_reason"] is None
    assertions.assert_version_unchanged(unchanged, created_version)


def test_post_that_refused_a_self_flag_is_still_flaggable_by_a_neighbour(
    api: ApiClient,
) -> None:
    """After the author's own flag is refused, a genuine neighbour may still flag.

    PRD: "Each accepted flag increments `flag_count` by 1, appends the flagger, and advances the post's `version` by 1."
    PRD: "The post itself moves `PUBLISHED → FLAGGED` with `auto_flag_reason` set to `RESIDENT_FLAG_THRESHOLD` only once `flag_count` has reached the resident-flag threshold of 2; a first, solitary flag leaves the post in `PUBLISHED` while still bumping the counter and the version."

    Design: Corner/validations/post_flagged_by_its_own_author_rejected
    """
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    neighbour = fixtures.register_resident(
        api,
        display_name="Neighbour N",
        email="n@example.test",
        home_x_m=10,
        home_y_m=0,
        alert_radius_m=0,
    )
    post = fixtures.create_post(
        api,
        author["id"],
        body="The alley gate has been left unlatched every evening this week.",
        category=k.CATEGORY_SAFETY_REPORT,
        post_x_m=0,
        post_y_m=0,
    )
    created_version = post["version"]

    validate_error(
        api.flag_post(
            post["id"],
            f.flag_payload(flag_reason="Flagging my own post to test the guard."),
            make_resident_headers(author["id"]),
        ),
        ApiErrorId.SELF_FLAG_NOT_ALLOWED.value,
        409,
    )

    accepted = validate_success(
        api.flag_post(
            post["id"],
            f.flag_payload(flag_reason="Neighbour disputes the account."),
            make_resident_headers(neighbour["id"]),
        ),
        200,
    )
    assert accepted["flag_count"] == 1
    assert accepted["state"] == k.POST_PUBLISHED
    assert accepted["auto_flag_reason"] is None
    assert accepted["flagged_by_resident_ids"] == [neighbour["id"]]
    assertions.assert_version_advanced(accepted, created_version)


# ═══ Flagging the same post twice ══════════════════════════════════════════

def test_same_resident_flagging_twice_is_refused_and_flag_count_stays_at_one(
    api: ApiClient,
) -> None:
    """One resident's second flag on the same post is refused as a duplicate.

    PRD: "An author may never flag their own post — `ERR_SELF_FLAG_NOT_ALLOWED` — and no resident may flag the same post twice, because their identifier already appears in `flagged_by_resident_ids` and the second attempt is refused with `ERR_DUPLICATE_FLAG`."
    PRD: "The post itself moves `PUBLISHED → FLAGGED` with `auto_flag_reason` set to `RESIDENT_FLAG_THRESHOLD` only once `flag_count` has reached the resident-flag threshold of 2; a first, solitary flag leaves the post in `PUBLISHED` while still bumping the counter and the version."

    Design: Corner/validations/same_resident_flagging_twice_rejected
    """
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    flagger = fixtures.register_resident(
        api,
        display_name="Neighbour One",
        email="n1@example.test",
        home_x_m=10,
        home_y_m=0,
        alert_radius_m=0,
    )
    post = fixtures.create_post(
        api,
        author["id"],
        body="A stranger has been photographing parked cars on the block each morning.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
    )

    first = fixtures.flag_post(
        api, post["id"], flagger["id"], flag_reason="This description is inaccurate."
    )
    assert first["flag_count"] == 1
    assert first["state"] == k.POST_PUBLISHED
    version_after_first_flag = first["version"]

    repeat = api.flag_post(
        post["id"],
        f.flag_payload(flag_reason="Flagging again to be sure."),
        make_resident_headers(flagger["id"]),
    )
    validate_error(repeat, ApiErrorId.DUPLICATE_FLAG.value, 409)

    unchanged = fixtures.read_post(api, post["id"])
    assert unchanged["flag_count"] == 1, "A duplicate flag must not bump the counter"
    assert unchanged["state"] == k.POST_PUBLISHED
    assert unchanged["auto_flag_reason"] is None
    assert unchanged["flagged_by_resident_ids"].count(flagger["id"]) == 1
    assertions.assert_version_unchanged(unchanged, version_after_first_flag)


# ═══ A second camera on a coordinate its owner already occupies ════════════

def test_second_camera_at_an_occupied_coordinate_is_refused_per_owner(
    api: ApiClient,
) -> None:
    """The co-location refusal is keyed on the owner and on the exact coordinate.

    PRD: "A resident may not register a second camera at a grid position they already occupy: if any other camera owned by the same resident whose `status` is not `DECOMMISSIONED` already sits at exactly the submitted easting and northing, the registration is refused with `ERR_DUPLICATE_DEVICE_LOCATION`, because two co-located cameras would let a single household count twice toward a minimum-device threshold."

    Design: Corner/validations/second_device_at_identical_grid_point_rejected
    """
    first_owner = fixtures.register_resident(
        api,
        display_name="R1",
        email="r1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    second_owner = fixtures.register_resident(
        api,
        display_name="R2",
        email="r2@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    original = fixtures.register_device(
        api,
        first_owner["id"],
        label="Front door",
        grid_x_m=0,
        grid_y_m=10,
        retention_window_days=30,
    )
    assert original["status"] == k.DEVICE_STATUS_ACTIVE

    duplicate = api.create_device(
        f.device_payload(
            first_owner["id"],
            label="Front door spare",
            grid_x_m=0,
            grid_y_m=10,
            retention_window_days=30,
        ),
        make_resident_headers(first_owner["id"]),
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_DEVICE_LOCATION.value, 409)

    other_owner_camera = validate_success(
        api.create_device(
            f.device_payload(
                second_owner["id"],
                label="Neighbour front door",
                grid_x_m=0,
                grid_y_m=10,
                retention_window_days=30,
            ),
            make_resident_headers(second_owner["id"]),
        ),
        201,
    )
    assert other_owner_camera["owner_resident_id"] == second_owner["id"]
    assert (other_owner_camera["grid_x_m"], other_owner_camera["grid_y_m"]) == (0, 10)
    assert other_owner_camera["status"] == k.DEVICE_STATUS_ACTIVE

    one_metre_away = validate_success(
        api.create_device(
            f.device_payload(
                first_owner["id"],
                label="Side gate",
                grid_x_m=1,
                grid_y_m=10,
                retention_window_days=30,
            ),
            make_resident_headers(first_owner["id"]),
        ),
        201,
    )
    assert (one_metre_away["grid_x_m"], one_metre_away["grid_y_m"]) == (1, 10)
    assert one_metre_away["status"] == k.DEVICE_STATUS_ACTIVE

    owned = fixtures.list_rows(api, "list_devices", owner_resident_id=first_owner["id"])
    assert sorted((row["grid_x_m"], row["grid_y_m"]) for row in owned) == [(0, 10), (1, 10)]


def test_decommissioning_a_camera_frees_its_coordinate_for_a_replacement(
    api: ApiClient,
) -> None:
    """A decommissioned camera no longer occupies its coordinate for its owner.

    PRD: "A resident may not register a second camera at a grid position they already occupy: if any other camera owned by the same resident whose `status` is not `DECOMMISSIONED` already sits at exactly the submitted easting and northing, the registration is refused with `ERR_DUPLICATE_DEVICE_LOCATION`, because two co-located cameras would let a single household count twice toward a minimum-device threshold."
    PRD: "Updating a camera is a partial write over `label`, `retention_window_days`, `auto_decline_requests` and `status`, and omitted fields are left untouched."

    Design: Corner/validations/second_device_at_identical_grid_point_rejected
    """
    owner = fixtures.register_resident(
        api,
        display_name="R1",
        email="r1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    original = fixtures.register_device(
        api,
        owner["id"],
        label="Front door",
        grid_x_m=0,
        grid_y_m=10,
        retention_window_days=30,
    )

    validate_error(
        api.create_device(
            f.device_payload(
                owner["id"],
                label="Front door spare",
                grid_x_m=0,
                grid_y_m=10,
                retention_window_days=30,
            ),
            make_resident_headers(owner["id"]),
        ),
        ApiErrorId.DUPLICATE_DEVICE_LOCATION.value,
        409,
    )

    retired = fixtures.update_device(
        api, original["id"], owner["id"], status=k.DEVICE_STATUS_DECOMMISSIONED
    )
    assert retired["status"] == k.DEVICE_STATUS_DECOMMISSIONED
    assertions.assert_version_advanced(retired, original["version"])

    replacement = validate_success(
        api.create_device(
            f.device_payload(
                owner["id"],
                label="Front door replacement",
                grid_x_m=0,
                grid_y_m=10,
                retention_window_days=30,
            ),
            make_resident_headers(owner["id"]),
        ),
        201,
    )
    assert (replacement["grid_x_m"], replacement["grid_y_m"]) == (0, 10)
    assert replacement["status"] == k.DEVICE_STATUS_ACTIVE
    assert replacement["id"] != original["id"]

    owned = fixtures.list_rows(api, "list_devices", owner_resident_id=owner["id"])
    statuses = sorted(row["status"] for row in owned)
    assert statuses == [k.DEVICE_STATUS_ACTIVE, k.DEVICE_STATUS_DECOMMISSIONED]


# ═══ The canvass-radius cap ════════════════════════════════════════════════

def test_canvass_radius_one_metre_over_the_cap_is_refused_with_422(
    api: ApiClient, clock: str
) -> None:
    """A radius of 1501 metres is refused before any camera is consulted.

    PRD: "Next the radius: a `radius_m` greater than 1500 metres is refused with `ERR_AREA_RADIUS_EXCEEDS_LIMIT` regardless of how many cameras it would have found, because a wider disc sweeps in whole districts rather than a neighbourhood."

    Design: Corner/validations/area_radius_above_limit_returns_422
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    assert clock == CLOCK_INSTANT, "This scenario is built at a pinned logical clock"

    refused = api.create_request_area(
        f.request_area_payload(
            world["agency_id"],
            center_x_m=0,
            center_y_m=0,
            radius_m=1501,
            window_start_utc="2026-08-08T00:00:00Z",
            window_end_utc="2026-08-08T06:00:00Z",
            area_label="Whole district",
        ),
        world["officer_headers"],
    )
    validate_error(refused, ApiErrorId.AREA_RADIUS_EXCEEDS_LIMIT.value, 422)

    page = _agency_areas(api, world["agency_id"], world["officer_id"])
    assert page["meta"]["total_count"] == 0, "A refused creation must persist no area"
    assert page["rows"] == []


# ═══ The footage window's clock leg ════════════════════════════════════════

def test_footage_window_ending_one_second_after_the_clock_is_refused(
    api: ApiClient, clock: str
) -> None:
    """A window that ends one second past the clock asks for unrecorded footage.

    PRD: "The window is checked first: `window_start_utc` must fall strictly before `window_end_utc`, `window_end_utc` must fall at or before the current logical clock instant — the portal does not canvass for footage that has not been recorded yet — and the span between the two must not exceed 168 hours."
    PRD: "Any of those three failures is `ERR_INVALID_WINDOW`."

    Design: Corner/validations/area_window_end_in_the_future_returns_422
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    assert clock == CLOCK_INSTANT, "This scenario is built at a pinned logical clock"

    refused = api.create_request_area(
        f.request_area_payload(
            world["agency_id"],
            center_x_m=0,
            center_y_m=0,
            radius_m=500,
            window_start_utc="2026-08-11T18:00:00Z",
            window_end_utc=ONE_SECOND_PAST_CLOCK,
            area_label="One second too far",
        ),
        world["officer_headers"],
    )
    validate_error(refused, ApiErrorId.INVALID_WINDOW.value, 422)

    page = _agency_areas(api, world["agency_id"], world["officer_id"])
    assert page["meta"]["total_count"] == 0, "A refused creation must persist no area"
    assert page["rows"] == []


def test_footage_window_ending_exactly_at_the_clock_is_accepted(
    api: ApiClient, clock: str
) -> None:
    """The clock leg is 'at or before', so a window ending exactly now is legal.

    PRD: "The window is checked first: `window_start_utc` must fall strictly before `window_end_utc`, `window_end_utc` must fall at or before the current logical clock instant — the portal does not canvass for footage that has not been recorded yet — and the span between the two must not exceed 168 hours."
    PRD: "The acting officer's identity is stamped onto the row as `created_by_officer_id`, and the area is created in `status` `DRAFT` with `version` 1, `eligible_device_count` 0, `effective_min_devices` null, `derived_request_count` 0, `locked_at` null and `invalidated_reason` null."

    Design: Corner/validations/area_window_end_in_the_future_returns_422
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)

    area = validate_success(
        api.create_request_area(
            f.request_area_payload(
                world["agency_id"],
                center_x_m=0,
                center_y_m=0,
                radius_m=500,
                window_start_utc="2026-08-11T18:00:00Z",
                window_end_utc=clock,
                area_label="Ends exactly at now",
            ),
            world["officer_headers"],
        ),
        201,
    )
    assert area["status"] == k.AREA_STATUS_DRAFT
    assert area["created_by_officer_id"] == world["officer_id"]
    assertions.assert_instant(area["window_end_utc"], CLOCK_INSTANT, "window_end_utc")
    assertions.assert_instant(
        area["window_start_utc"], "2026-08-11T18:00:00Z", "window_start_utc"
    )
    assertions.assert_mutable_common_fields(area, version=1)
    assertions.assert_zero_counters(area, "eligible_device_count", "derived_request_count")
    assertions.assert_nulls(area, "effective_min_devices", "locked_at", "invalidated_reason")


# ═══ Which of two broken area rules is reported ════════════════════════════

def test_future_window_is_reported_before_an_oversized_radius(
    api: ApiClient, clock: str
) -> None:
    """A creation breaking both the window and the radius rule reports the window.

    PRD: "Three refusals guard area creation, and their relative order matters."
    PRD: "The window is checked first: `window_start_utc` must fall strictly before `window_end_utc`, `window_end_utc` must fall at or before the current logical clock instant — the portal does not canvass for footage that has not been recorded yet — and the span between the two must not exceed 168 hours."
    PRD: "Next the radius: a `radius_m` greater than 1500 metres is refused with `ERR_AREA_RADIUS_EXCEEDS_LIMIT` regardless of how many cameras it would have found, because a wider disc sweeps in whole districts rather than a neighbourhood."

    Design: Corner/validations/invalid_window_rule_34_beats_radius_rule_37
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    assert clock == CLOCK_INSTANT, "This scenario is built at a pinned logical clock"

    both_broken = api.create_request_area(
        f.request_area_payload(
            world["agency_id"],
            center_x_m=0,
            center_y_m=0,
            radius_m=1600,
            window_start_utc="2026-08-11T18:00:00Z",
            window_end_utc="2026-08-13T00:00:00Z",
            area_label="Both rules broken",
        ),
        world["officer_headers"],
    )
    reported = validate_error(both_broken, ApiErrorId.INVALID_WINDOW.value, 422)
    assert reported["error_id"] != ApiErrorId.AREA_RADIUS_EXCEEDS_LIMIT.value, (
        "The window rule outranks the radius rule and must decide the response"
    )

    window_repaired = api.create_request_area(
        f.request_area_payload(
            world["agency_id"],
            center_x_m=0,
            center_y_m=0,
            radius_m=1600,
            window_start_utc="2026-08-11T18:00:00Z",
            window_end_utc=CLOCK_INSTANT,
            area_label="Radius still too wide",
        ),
        world["officer_headers"],
    )
    validate_error(window_repaired, ApiErrorId.AREA_RADIUS_EXCEEDS_LIMIT.value, 422)

    page = _agency_areas(api, world["agency_id"], world["officer_id"])
    assert page["meta"]["total_count"] == 0, "Neither refused attempt may persist an area"
    assert page["rows"] == []


# ═══ Both caps at their inclusive limit ════════════════════════════════════

def test_area_at_the_maximum_radius_and_maximum_window_locks_at_eleven(
    api: ApiClient, clock: str
) -> None:
    """Radius 1500 over a 168-hour window is accepted and locks at eleven devices.

    PRD: "Creating one names the `agency_id` doing the canvassing, the disc centre as `center_x_m` and `center_y_m`, the `radius_m` of the disc in whole metres — at least 50 and at most 1500 — and the footage window being sought as `window_start_utc` and `window_end_utc`, both ISO 8601 UTC instants with three fractional digits."
    PRD: "The base is the owning agency's own `min_device_threshold`."
    PRD: "To that is added a radius bump, a step function over the disc: a `radius_m` of 500 metres or less adds nothing, a `radius_m` above 500 metres and up to and including 1000 metres adds 2, and a `radius_m` above 1000 metres adds 5."
    PRD: "To that is added a window bump: take the elapsed time between `window_start_utc` and `window_end_utc`, round it **up** to a whole number of hours, divide that by 12, round the quotient **up** to a whole number, subtract 1, and take the smaller of the result and 3."
    PRD: "Finally, and only after the three terms have been summed, the larger of that sum and the global floor of 3 is taken."
    PRD: "Locking deliberately does **not** check the roster against the threshold."

    Design: Corner/validations/area_at_maximum_radius_and_maximum_window_passes
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)

    area = validate_success(
        api.create_request_area(
            f.request_area_payload(
                world["agency_id"],
                center_x_m=0,
                center_y_m=0,
                radius_m=1500,
                window_start_utc="2026-08-05T00:00:00Z",
                window_end_utc=clock,
                area_label="Both caps at their limit",
            ),
            world["officer_headers"],
        ),
        201,
    )
    assert area["radius_m"] == 1500
    assert area["status"] == k.AREA_STATUS_DRAFT
    assertions.assert_mutable_common_fields(area, version=1)
    assertions.assert_nulls(area, "effective_min_devices", "locked_at")

    locked = fixtures.lock_area(api, area["id"], world["officer_id"])
    assert locked["status"] == k.AREA_STATUS_LOCKED
    assert locked["effective_min_devices"] == 11, (
        "min_device_threshold 3 plus a radius bump of 5 plus a window bump capped "
        "at 3, floored at 3, is 11"
    )
    assert locked["eligible_device_count"] == 0, "An empty roster is legal at lock time"
    assert locked["derived_request_count"] == 0
    assert locked["invalidated_reason"] is None
    assertions.assert_instant(locked["locked_at"], CLOCK_INSTANT, "locked_at")
    assertions.assert_version_advanced(locked, area["version"])


def test_footage_window_one_hour_over_the_span_cap_is_refused(
    api: ApiClient, clock: str
) -> None:
    """A 169-hour footage window breaches the span cap even at a legal radius.

    PRD: "The window is checked first: `window_start_utc` must fall strictly before `window_end_utc`, `window_end_utc` must fall at or before the current logical clock instant — the portal does not canvass for footage that has not been recorded yet — and the span between the two must not exceed 168 hours."
    PRD: "Any of those three failures is `ERR_INVALID_WINDOW`."

    Design: Corner/validations/area_at_maximum_radius_and_maximum_window_passes
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)

    refused = api.create_request_area(
        f.request_area_payload(
            world["agency_id"],
            center_x_m=0,
            center_y_m=0,
            radius_m=1500,
            window_start_utc="2026-08-04T23:00:00Z",
            window_end_utc=clock,
            area_label="One hour over the span cap",
        ),
        world["officer_headers"],
    )
    validate_error(refused, ApiErrorId.INVALID_WINDOW.value, 422)

    page = _agency_areas(api, world["agency_id"], world["officer_id"])
    assert page["meta"]["total_count"] == 0, "A refused creation must persist no area"
    assert page["rows"] == []
