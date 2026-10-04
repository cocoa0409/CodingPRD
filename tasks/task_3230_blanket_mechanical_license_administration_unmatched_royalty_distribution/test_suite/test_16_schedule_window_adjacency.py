"""Rate-schedule window semantics: overlap rejected, adjacency legal."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_schedule_pending, create_active_schedule,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_active_schedule_and_candidates():
    set_clock("2026-09-01T00:00:00Z")
    rs1 = create_active_schedule(
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    rs2 = create_schedule_pending(
        under=135, over=260,
        effective_from="2026-06-01T00:00:00Z", effective_to="2028-01-01T00:00:00Z")
    rs3 = create_schedule_pending(
        under=135, over=260, effective_from="2027-01-01T00:00:00Z")
    return rs1, rs2, rs3


def test_overlapping_window_rejected_on_activation(api):
    """PRD §3.1: "Activating a schedule requires that its `effective_from` is
    not in the future (`ERR_RATE_SCHEDULE_NOT_YET_EFFECTIVE`) and that its
    half-open effectiveness window does not overlap the window of the currently
    `ACTIVE` schedule (`ERR_RATE_SCHEDULE_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_window_adjacency
    """
    _rs1, rs2, _rs3 = _setup_active_schedule_and_candidates()
    validate_error(api_client.activate_rate_schedule(rs2["id"], ADMIN),
                   ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP)


def test_adjacent_window_passes_overlap_check(api):
    """PRD §3.1: "Overlap is judged with half-open interval semantics — each
    window spans from its inclusive `effective_from` to its exclusive
    `effective_to` — so adjacent windows, where one schedule's `effective_to`
    equals the other's `effective_from`, are permitted."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_window_adjacency
    """
    rs1, _rs2, rs3 = _setup_active_schedule_and_candidates()
    # RS3 [2027-01-01, null) touches RS1 [2026-01-01, 2027-01-01) — geometrically
    # legal. At clock 2026-09-01 its effective_from lies in the future, so the
    # rejection is the temporal gate, proving the overlap check passed.
    validate_error(api_client.activate_rate_schedule(rs3["id"], ADMIN),
                   ApiErrorId.ERR_RATE_SCHEDULE_NOT_YET_EFFECTIVE)
    rs1_after = validate_success(api_client.get_rate_schedule(rs1["id"], ADMIN))
    assert rs1_after["status"] == "ACTIVE", (
        f"both failed activations leave the ACTIVE schedule untouched; "
        f"got {rs1_after['status']}")
