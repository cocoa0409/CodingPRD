"""Temporal overlap: half-open run windows vs aggregate reservation pools."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_accepted_lots, create_active_formula, create_committed_blend_run,
    create_line, schedule_run, get_line_version, production_run_payload,
    reservation_payload,
)

W44_START, W44_END = "2026-10-26T00:00:00Z", "2026-11-02T00:00:00Z"
W37_START, W37_END = "2026-09-07T00:00:00Z", "2026-09-14T00:00:00Z"


def _setup_line_with_committed_blend():
    supplier, lots = setup_accepted_lots(costs=(100, 200, 300))
    formula = create_active_formula("WIN-1")
    br = create_committed_blend_run(formula["id"], "COST_MIN", 10)
    line = create_line(name="Line-W")
    return {"formula": formula, "br": br, "line": line}


class TestLineWindowHalfOpenAdjacency:
    def test_back_to_back_windows_are_not_overlap(self, api):
        """PRD §3.5: "perfect adjacency — a neighbor whose `window_end` equals
        the new `window_start`, or whose `window_start` equals the new
        `window_end` — is allowed". PRD §3.5: "When there is no predecessor,
        the class is `NONE`."

        R1 [08:00,12:00) then R2 [12:00,16:00): touching at exactly
        end == start schedules fine; R2's predecessor is R1 and both classes
        are NONE (identical formula, brand, and allergen set).

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency
        """
        s = _setup_line_with_committed_blend()
        r1 = schedule_run(s["line"]["id"], s["formula"]["id"], s["br"]["id"],
                          10, "2026-09-07T08:00:00Z", "2026-09-07T12:00:00Z")
        assert r1["predecessor_run_id"] is None
        assert r1["changeover_class_required"] == "NONE"
        r2 = schedule_run(s["line"]["id"], s["formula"]["id"], s["br"]["id"],
                          10, "2026-09-07T12:00:00Z", "2026-09-07T16:00:00Z")
        assert r2["predecessor_run_id"] == r1["id"]
        assert r2["changeover_class_required"] == "NONE"

    def test_straddling_window_rejected(self, api):
        """PRD §3.5: "Windows on a line are exclusive under half-open
        semantics: the new window must not intersect any non-`CANCELLED` run
        on the same line ... a true overlap is rejected with
        `ERR_LINE_WINDOW_CONFLICT` (HTTP 409)."

        R3 [11:00,13:00) straddles R1's end at 12:00 and is rejected.

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency
        """
        s = _setup_line_with_committed_blend()
        schedule_run(s["line"]["id"], s["formula"]["id"], s["br"]["id"], 10,
                     "2026-09-07T08:00:00Z", "2026-09-07T12:00:00Z")
        schedule_run(s["line"]["id"], s["formula"]["id"], s["br"]["id"], 10,
                     "2026-09-07T12:00:00Z", "2026-09-07T16:00:00Z")
        payload = production_run_payload(
            s["line"]["id"], s["formula"]["id"], s["br"]["id"], 10,
            "2026-09-07T11:00:00Z", "2026-09-07T13:00:00Z",
            get_line_version(s["line"]["id"]))
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)


class TestReservationAggregatePool:
    def test_overlapping_reservations_share_the_week_pool(self, api):
        """PRD §3.8: "A reservation consumes `reserved_kg_per_week` from every
        ISO week its window intersects — not from a single week". PRD §3.8:
        "If honoring the reservation would push any intersected week's pool
        below zero, the create is rejected with `ERR_RESERVATION_OVER_COMMIT`
        (HTTP 409)".

        ISO week 44 surge pool is floor(1000*5*1.25) = 6250 kg: two fully
        overlapping 3000 kg reservations pass; a further 300 kg tips the
        aggregate over the pool and is rejected.

        Design: Difficulty/resource_temporal_overlap/reservation_aggregate_pool_semantics
        """
        line = create_line(name="Line-H")
        for _ in range(2):
            resp = api_client.create_reservation(
                reservation_payload(line["id"], W44_START, W44_END, 3000),
                TEST_USERS["production_scheduler_headers"])
            validate_success(resp, 201)
        resp = api_client.create_reservation(
            reservation_payload(line["id"], W44_START, W44_END, 300),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_RESERVATION_OVER_COMMIT)

    def test_pools_are_per_line_per_iso_week(self, api):
        """PRD §3.5: "A line's weekly pool is its `capacity_kg_per_shift`
        multiplied by 5 shifts per week, multiplied by the week's surge
        multiplier, and floored to a whole kilogram". PRD §3.8: a reservation
        consumes "from every ISO week its window intersects".

        3000 kg committed to surge week 44 leaves week 37's separate
        5000 kg pool untouched, so the same 3000 kg reservation succeeds there.

        Design: Difficulty/resource_temporal_overlap/reservation_aggregate_pool_semantics
        """
        line = create_line(name="Line-H")
        resp = api_client.create_reservation(
            reservation_payload(line["id"], W44_START, W44_END, 3000),
            TEST_USERS["production_scheduler_headers"])
        validate_success(resp, 201)
        resp = api_client.create_reservation(
            reservation_payload(line["id"], W37_START, W37_END, 3000),
            TEST_USERS["production_scheduler_headers"])
        validate_success(resp, 201)
