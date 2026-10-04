"""Routing update validation: the 24-hour buffer window conflict rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_routing_update_payload,
    get_region,
    make_region,
    make_routing_update,
    validate_error,
    validate_success,
)

RE1 = TEST_USERS["routing_engineer_headers"]


def _update(api, region, segment_ref, start, end, kind="CLOSURE"):
    fresh = get_region(region["id"])
    resp = api.create_routing_update(
        create_routing_update_payload(
            region_id=region["id"], segment_ref=segment_ref, kind=kind,
            effective_start=start, effective_end=end,
            expected_region_version=fresh["version"],
        ),
        RE1,
    )
    return validate_success(resp, expected_status=201)


def test_routing_buffer_exactly_24h_allowed_23h_rejected(api):
    """PRD §3.9: "For closures and construction, a 24-hour buffer rule
    protects the segment: no other update on the same `segment_ref` in
    `VALIDATED`, `SCHEDULED`, or `ACTIVE` status may have an effect window
    within 24 hours of this window on either side. The buffer is inclusive of
    exactly 24 hours — a gap of precisely 24 hours is allowed — and any
    tighter spacing is refused with `ERR_ROUTING_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/routing_24h_buffer_exactly_allowed_23h_rejected
    """
    region = make_region(name="R16")
    first = _update(api, region, "S1", "2026-09-10T00:00:00Z",
                    "2026-09-12T00:00:00Z")
    validated = validate_success(api.validate_routing_update(first["id"], RE1))
    assert validated["status"] in ("SCHEDULED", "ACTIVE")

    exact = _update(api, region, "S1", "2026-09-13T00:00:00Z",
                    "2026-09-14T00:00:00Z")
    tight = _update(api, region, "S1", "2026-09-12T23:00:00Z",
                    "2026-09-13T23:00:00Z")

    resp = api.validate_routing_update(exact["id"], RE1)
    ok = validate_success(resp)
    assert ok["status"] in ("SCHEDULED", "ACTIVE"), (
        f"exactly 24h gap allowed, got {ok['status']}"
    )

    resp = api.validate_routing_update(tight["id"], RE1)
    validate_error(resp, ApiErrorId.ERR_ROUTING_WINDOW_CONFLICT)


def test_routing_buffer_gap_below_24h_on_either_side_rejected(api):
    """PRD §3.9: "For closures and construction, a 24-hour buffer rule
    protects the segment: no other update on the same `segment_ref` in
    `VALIDATED`, `SCHEDULED`, or `ACTIVE` status may have an effect window
    within 24 hours of this window on either side. The buffer is inclusive of
    exactly 24 hours — a gap of precisely 24 hours is allowed — and any
    tighter spacing is refused with `ERR_ROUTING_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/routing_24h_buffer_exactly_allowed_23h_rejected
    """
    region = make_region(name="R16b")
    first = _update(api, region, "S2", "2026-09-10T00:00:00Z",
                    "2026-09-12T00:00:00Z")
    validate_success(api.validate_routing_update(first["id"], RE1))

    # New window ENDS 23h before the existing window starts (other side).
    before = _update(api, region, "S2", "2026-09-08T01:00:00Z",
                     "2026-09-09T01:00:00Z")
    resp = api.validate_routing_update(before["id"], RE1)
    validate_error(resp, ApiErrorId.ERR_ROUTING_WINDOW_CONFLICT)
