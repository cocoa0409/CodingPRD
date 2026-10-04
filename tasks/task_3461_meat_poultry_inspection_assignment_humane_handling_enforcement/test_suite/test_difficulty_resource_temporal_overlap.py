"""Depth tests: resource temporal overlap geometry.

Two different overlap regimes: the half-open same-(window, line) rule where
any positive overlap violates but end == start adjacency is legal, and the
buffer-expanded cross-establishment travel rule where one inspector's
assignments at different establishments must sit at least 30 minutes apart.
"""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

W_START = "2026-09-02T06:00:00Z"
W_END = "2026-09-02T14:00:00Z"


def _assignment_attempt(api, window_id, inspector_id, line_index, start, end):
    """POST one assignment against the window's CURRENT version."""
    version = fx.get_shift_window(api, window_id)["version"]
    return api.create_assignment(
        window_id,
        f.assignment_payload(inspector_id, line_index, start, end, version),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )


def _assignment_count(api):
    rows, _meta = validate_paginated(api.list_shift_assignments(DISTRICT_MANAGER_HEADERS))
    return len(rows), rows


class TestSameLineHalfOpenOverlap:
    def _window_with_line1_morning(self, api):
        """Granted establishment; one SLAUGHTER window (2 lines); inspector
        SCHEDULED 06:00-10:00 on line 1."""
        base = fx.setup_granted_with_window(
            api, species_classes=["CATTLE"], name="D16 Beef Plant", planned_line_count=2,
            start_utc=W_START, end_utc=W_END,
        )
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        fx.add_assignment(
            api, base["window"]["id"], inspector["id"],
            line_index=1, start_utc=W_START, end_utc="2026-09-02T10:00:00Z",
        )
        return base, inspector

    def test_positive_overlap_rejected_but_exact_adjacency_accepted(self, api):
        """PRD §3.2: "On the same window and the same `line_index`, the new
        interval must not overlap any existing non-`CANCELLED` assignment's
        interval — intervals are half-open, so one assignment ending exactly
        when another begins is continuous, legal coverage — and a violation is
        rejected with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/same_line_half_open_overlap
        """
        base, inspector = self._window_with_line1_morning(api)
        window_id = base["window"]["id"]

        # 09:30-11:00 overlaps the existing 06:00-10:00 by 30 minutes.
        overlap = _assignment_attempt(
            api, window_id, inspector["id"], 1, "2026-09-02T09:30:00Z", "2026-09-02T11:00:00Z"
        )
        validate_error(overlap, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)

        # 10:00-12:00 starts exactly when the existing assignment ends: legal.
        adjacent = _assignment_attempt(
            api, window_id, inspector["id"], 1, "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z"
        )
        adj_data = validate_success(adjacent, 201)
        assert adj_data["status"] == "SCHEDULED"
        assert adj_data["line_index"] == 1

    def test_overlap_rule_is_scoped_to_window_and_line(self, api):
        """PRD §3.2: "Assignments on different lines of the same window may
        overlap freely."

        Design: Difficulty/resource_temporal_overlap/same_line_half_open_overlap
        """
        base, inspector = self._window_with_line1_morning(api)
        window_id = base["window"]["id"]

        # The exact interval rejected on line 1 is legal on line 2.
        other_line = _assignment_attempt(
            api, window_id, inspector["id"], 2, "2026-09-02T09:30:00Z", "2026-09-02T11:00:00Z"
        )
        line2_data = validate_success(other_line, 201)
        assert line2_data["line_index"] == 2

        count, rows = _assignment_count(api)
        assert count == 2, f"expected the line-1 row plus the line-2 row, got {count}"
        assert {row["line_index"] for row in rows} == {1, 2}


class TestCrossEstablishmentTravelBuffer:
    def _two_establishments_one_shared_inspector(self, api):
        """Plants A and B granted, each with a 06:00-14:00 window; one
        CATTLE-qualified inspector SCHEDULED 06:00-10:00 on window A."""
        base_a = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="D17 Plant A")
        base_b = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="D17 Plant B")
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        window_a = fx.create_shift_window(api, base_a["establishment"]["id"], start_utc=W_START, end_utc=W_END)
        window_b = fx.create_shift_window(api, base_b["establishment"]["id"], start_utc=W_START, end_utc=W_END)
        fx.add_assignment(
            api, window_a["id"], inspector["id"],
            line_index=1, start_utc=W_START, end_utc="2026-09-02T10:00:00Z",
        )
        return base_a, base_b, inspector, window_a, window_b

    def test_twenty_minute_gap_rejected_thirty_minute_gap_accepted(self, api):
        """PRD §3.2: "Finally, an inspector may not be scheduled at two
        different establishments within 30 minutes of one another: if the named
        inspector holds a non-`CANCELLED` assignment at a different
        establishment whose interval falls within 30 minutes of the requested
        interval, the creation is rejected with `ERR_TRAVEL_BUFFER_VIOLATION`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cross_establishment_travel_buffer
        """
        _a, _b, inspector, _window_a, window_b = self._two_establishments_one_shared_inspector(api)

        # The inspector leaves plant A at 10:00; a 10:20 start at plant B
        # leaves only a 20-minute gap (< 30).
        too_soon = _assignment_attempt(
            api, window_b["id"], inspector["id"], 1, "2026-09-02T10:20:00Z", "2026-09-02T12:00:00Z"
        )
        validate_error(too_soon, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION)

        # A 10:30 start leaves exactly 30 minutes: satisfies the buffer.
        exactly = _assignment_attempt(
            api, window_b["id"], inspector["id"], 1, "2026-09-02T10:30:00Z", "2026-09-02T12:00:00Z"
        )
        data = validate_success(exactly, 201)
        assert data["status"] == "SCHEDULED"
        assert data["establishment_id"] == _b["establishment"]["id"]

    def test_same_establishment_adjacency_needs_no_buffer(self, api):
        """PRD §3.2: "Same-establishment assignments are exempt from the travel
        buffer."
        PRD §3.2: "On the same window and the same `line_index`, the new
        interval must not overlap any existing non-`CANCELLED` assignment's
        interval — intervals are half-open, so one assignment ending exactly
        when another begins is continuous, legal coverage — and a violation is
        rejected with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cross_establishment_travel_buffer
        """
        _a, _b, inspector, window_a, _window_b = self._two_establishments_one_shared_inspector(api)

        # 10:00-12:00 at plant A starts the minute the inspector's existing
        # plant-A assignment ends: adjacent on line 1, no travel required.
        adjacent = _assignment_attempt(
            api, window_a["id"], inspector["id"], 1, "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z"
        )
        data = validate_success(adjacent, 201)
        assert data["status"] == "SCHEDULED"
        count, _rows = _assignment_count(api)
        assert count == 2
