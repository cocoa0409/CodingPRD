"""Screen-time windows and access grants: intervals, overlap, conflicts."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_grant,
    make_parent_headers,
    setup_monitoring_pipeline,
    validate_error,
    validate_success,
)


def test_screen_time_window_half_open_adjacency(api):
    """PRD §3.10: "Two `BLOCKED` windows on the same device and weekday must
    never overlap: creating a `BLOCKED` window whose half-open interval
    intersects an existing `ACTIVE` `BLOCKED` window for the same device and
    weekday is rejected with `ERR_WINDOW_OVERLAP`. Because the intervals are
    half-open, adjacency is allowed — a window ending at minute 480 and another
    beginning at minute 480 do not overlap."

    Design: Difficulty/resource_temporal_overlap/screen_time_window_half_open_adjacency
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 480, "end_minute": 720,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_success(resp, expected_status=201)

    # Adjacent: [720, 900) touches but does not intersect [480, 720).
    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 720, "end_minute": 900,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_success(resp, expected_status=201)

    # Different weekday, same minutes: no overlap.
    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "TUE", "start_minute": 600, "end_minute": 800,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_success(resp, expected_status=201)

    # Overlapping same weekday: [600, 800) intersects [480, 720).
    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 600, "end_minute": 800,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_allowed_windows_may_overlap_blocked(api):
    """PRD §3.10: "Two `BLOCKED` windows on the same device and weekday must
    never overlap: creating a `BLOCKED` window whose half-open interval
    intersects an existing `ACTIVE` `BLOCKED` window for the same device and
    weekday is rejected with `ERR_WINDOW_OVERLAP`. Because the intervals are
    half-open, adjacency is allowed — a window ending at minute 480 and another
    beginning at minute 480 do not overlap."

    Design: Difficulty/resource_temporal_overlap/screen_time_window_half_open_adjacency
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 480, "end_minute": 720,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_success(resp, expected_status=201)

    # An ALLOWED window overlapping the BLOCKED one: the rule constrains pairs
    # of BLOCKED windows only.
    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 600, "end_minute": 800,
         "window_kind": "ALLOWED"},
        headers,
    )
    validate_success(resp, expected_status=201)


def test_window_inverted_range_returns_400(api):
    """PRD §3.10: "Parents schedule device availability with screen-time
    windows, each defined by a `weekday` (one of `MON`, `TUE`, `WED`, `THU`,
    `FRI`, `SAT`, `SUN`), a `start_minute` from 0 to 1439, an `end_minute` from
    1 to 1440 that must be strictly greater than `start_minute`, and a
    `window_kind` of `BLOCKED` or `ALLOWED`."
    PRD §3.10: "Bounds violations — a start minute outside 0 to 1439, an end
    minute outside 1 to 1440, or an end minute not greater than the start — are
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/window_inverted_range_returns_400
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 720, "end_minute": 480,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_unpaired_device_beats_window_overlap_rejected(api):
    """PRD §3.10: "Windows may be disabled and later re-enabled through the
    window state operation. Disabling moves `ACTIVE` to `DISABLED` freely.
    Re-enabling moves `DISABLED` back to `ACTIVE` under two preconditions: the
    device must currently be `PAIRED` (otherwise `ERR_DEVICE_NOT_PAIRED`), and
    re-enabling a `BLOCKED` window must not recreate an overlap with another
    `ACTIVE` `BLOCKED` window on the same device and weekday (otherwise
    `ERR_WINDOW_OVERLAP`)."
    PRD §3.3: "Certain operations also require the device to be `PAIRED` in the
    first place — re-enabling a screen-time window on an unpaired device, or
    reporting a bypass event for one, is rejected with `ERR_DEVICE_NOT_PAIRED`."

    Design: Difficulty/priority_pair_validation_conflict/unpaired_device_beats_window_overlap_rejected
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2013)
    headers = make_parent_headers(parent["id"])

    validate_success(
        api.create_screen_time_window(
            dev["id"],
            {"weekday": "MON", "start_minute": 480, "end_minute": 720,
             "window_kind": "BLOCKED"},
            headers,
        ),
        expected_status=201,
    )
    validate_success(api.unpair_device(dev["id"], headers))

    # Overlapping interval on an unpaired device: NOT_PAIRED surfaces, never
    # WINDOW_OVERLAP.
    resp = api.create_screen_time_window(
        dev["id"],
        {"weekday": "MON", "start_minute": 600, "end_minute": 800,
         "window_kind": "BLOCKED"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_PAIRED)


def test_unpaired_device_reenable_window_rejected(api):
    """PRD §3.10: "Windows may be disabled and later re-enabled through the
    window state operation. Disabling moves `ACTIVE` to `DISABLED` freely.
    Re-enabling moves `DISABLED` back to `ACTIVE` under two preconditions: the
    device must currently be `PAIRED` (otherwise `ERR_DEVICE_NOT_PAIRED`), and
    re-enabling a `BLOCKED` window must not recreate an overlap with another
    `ACTIVE` `BLOCKED` window on the same device and weekday (otherwise
    `ERR_WINDOW_OVERLAP`)."

    Design: Difficulty/priority_pair_validation_conflict/unpaired_device_beats_window_overlap_rejected
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2013)
    headers = make_parent_headers(parent["id"])

    window = validate_success(
        api.create_screen_time_window(
            dev["id"],
            {"weekday": "MON", "start_minute": 480, "end_minute": 720,
             "window_kind": "BLOCKED"},
            headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.set_screen_time_window_state(
            window["id"], {"to_status": "DISABLED"}, headers
        )
    )
    validate_success(api.unpair_device(dev["id"], headers))

    resp = api.set_screen_time_window_state(
        window["id"], {"to_status": "ACTIVE"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_PAIRED)


def test_access_grant_padded_closed_interval_conflict(api):
    """PRD §3.12: "Grants on the same device must not collide. A new grant is
    rejected with `ERR_GRANT_CONFLICT` when its closed interval conflicts with
    an existing `SCHEDULED` or `ACTIVE` grant under padded closed-interval
    semantics: each existing grant is treated as though extended by a
    five-minute buffer on both sides, and any intersection between the new
    interval and a padded existing interval is a conflict."

    Design: Difficulty/resource_temporal_overlap/access_grant_padded_closed_interval_conflict
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    resp = api.create_access_grant(
        dev["id"],
        {"start_at": "2026-09-01T01:00:00Z", "end_at": "2026-09-01T02:00:00Z"},
        headers,
    )
    validate_success(resp, expected_status=201)

    # Existing grant padded to [00:55, 02:05]. A new grant at 02:03 intersects.
    resp = api.create_access_grant(
        dev["id"],
        {"start_at": "2026-09-01T02:03:00Z", "end_at": "2026-09-01T03:00:00Z"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_CONFLICT)

    # 02:06 clears the padded edge at 02:05.
    resp = api.create_access_grant(
        dev["id"],
        {"start_at": "2026-09-01T02:06:00Z", "end_at": "2026-09-01T03:00:00Z"},
        headers,
    )
    validate_success(resp, expected_status=201)


def test_access_grant_touching_inside_buffer_rejected(api):
    """PRD §3.12: "Grants on the same device must not collide. A new grant is
    rejected with `ERR_GRANT_CONFLICT` when its closed interval conflicts with
    an existing `SCHEDULED` or `ACTIVE` grant under padded closed-interval
    semantics: each existing grant is treated as though extended by a
    five-minute buffer on both sides, and any intersection between the new
    interval and a padded existing interval is a conflict."

    Design: Difficulty/resource_temporal_overlap/access_grant_padded_closed_interval_conflict
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    validate_success(
        api.create_access_grant(
            dev["id"],
            {"start_at": "2026-09-01T01:00:00Z",
             "end_at": "2026-09-01T02:00:00Z"},
            headers,
        ),
        expected_status=201,
    )

    # A new grant ending at 00:58 falls inside the leading pad [00:55, 01:00].
    resp = api.create_access_grant(
        dev["id"],
        {"start_at": "2026-09-01T00:30:00Z",
         "end_at": "2026-09-01T00:58:00Z"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_CONFLICT)
