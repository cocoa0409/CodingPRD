"""Difficulty tests: temporal interval overlap — scope versions and blackout windows."""
from test_helpers import ApiErrorId, get_success_data, validate_error, validate_success
from test_helpers.factories import create_program_payload
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    create_asset,
    create_program,
    get_program,
    set_clock,
)


def test_scope_version_half_open_adjacency_allowed(api):
    """PRD §3.2: "Within one program, these windows must not intersect;
    adjacency, where one window's `effective_to` equals the next window's
    `effective_from`, is allowed."

    Design: Difficulty/resource_temporal_overlap/scope_version_half_open_adjacency_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    program = create_program()
    asset = create_asset(program["id"])
    first = get_success_data(api.create_scope_version({
        "program_id": program["id"],
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2026-06-01T00:00:00Z",
        "in_scope_asset_ids": [asset["id"]],
    }, PROGRAM_ADMIN))
    resp = api.create_scope_version({
        "program_id": program["id"],
        "effective_from": "2026-06-01T00:00:00Z",
        "in_scope_asset_ids": [asset["id"]],
    }, PROGRAM_ADMIN)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


def test_scope_version_true_intersection_rejected(api):
    """PRD §3.2: "Overlapping windows are rejected with
    `ERR_SCOPE_WINDOW_OVERLAP`."
    PRD §3.2: "Each version's window is a half-open interval that includes
    `effective_from` and excludes `effective_to`."

    Design: Difficulty/resource_temporal_overlap/scope_version_half_open_adjacency_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    program = create_program()
    asset = create_asset(program["id"])
    get_success_data(api.create_scope_version({
        "program_id": program["id"],
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2026-06-01T00:00:00Z",
        "in_scope_asset_ids": [asset["id"]],
    }, PROGRAM_ADMIN))
    resp = api.create_scope_version({
        "program_id": program["id"],
        "effective_from": "2026-03-01T00:00:00Z",
        "effective_to": "2026-04-01T00:00:00Z",
        "in_scope_asset_ids": [asset["id"]],
    }, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_SCOPE_WINDOW_OVERLAP)


def test_blackout_gap_below_3600_seconds_rejected(api):
    """PRD §3.1: "Blackout windows are an array of `{starts_at, ends_at}` pairs
    interpreted as closed intervals during which disclosure publication is
    forbidden; any two windows must not overlap and must be separated by at least
    3600 seconds, with violations rejected as `ERR_BLACKOUT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_gap_buffer
    """
    set_clock("2026-09-01T00:00:00Z")
    program = create_program()
    v1 = program["version"]
    patched = get_success_data(api.patch_program(program["id"], {
        "expected_program_version": v1,
        "blackout_windows": [
            {"starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-10-10T00:00:00Z"},
        ],
    }, PROGRAM_ADMIN))
    v2 = patched["version"]
    resp = api.patch_program(program["id"], {
        "expected_program_version": v2,
        "blackout_windows": [
            {"starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-10-10T00:00:00Z"},
            {"starts_at": "2026-10-10T00:30:00Z", "ends_at": "2026-10-20T00:00:00Z"},
        ],
    }, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_OVERLAP)
    # A failed validation leaves the program's version untouched
    assert get_program(program["id"])["version"] == v2


def test_blackout_gap_exactly_3600_seconds_allowed(api):
    """PRD §3.1: "Blackout windows are an array of `{starts_at, ends_at}` pairs
    interpreted as closed intervals during which disclosure publication is
    forbidden; any two windows must not overlap and must be separated by at least
    3600 seconds, with violations rejected as `ERR_BLACKOUT_OVERLAP`."
    PRD §3.1: "A failed validation leaves the program's `version` untouched; a
    successful update increments it by one."

    Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_gap_buffer
    """
    set_clock("2026-09-01T00:00:00Z")
    program = create_program()
    v1 = program["version"]
    patched = get_success_data(api.patch_program(program["id"], {
        "expected_program_version": v1,
        "blackout_windows": [
            {"starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-10-10T00:00:00Z"},
        ],
    }, PROGRAM_ADMIN))
    v2 = patched["version"]
    # 1800-second gap: rejected
    bad = api.patch_program(program["id"], {
        "expected_program_version": v2,
        "blackout_windows": [
            {"starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-10-10T00:00:00Z"},
            {"starts_at": "2026-10-10T00:30:00Z", "ends_at": "2026-10-20T00:00:00Z"},
        ],
    }, PROGRAM_ADMIN)
    validate_error(bad, ApiErrorId.ERR_BLACKOUT_OVERLAP)
    # Exactly 3600-second gap: allowed; the rejected PATCH did not bump the version
    good = api.patch_program(program["id"], {
        "expected_program_version": v2,
        "blackout_windows": [
            {"starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-10-10T00:00:00Z"},
            {"starts_at": "2026-10-10T01:00:00Z", "ends_at": "2026-10-20T00:00:00Z"},
        ],
    }, PROGRAM_ADMIN)
    assert good.status_code == 200, f"Expected 200, got {good.status_code}: {good.text}"
    assert get_program(program["id"])["version"] == v2 + 1
