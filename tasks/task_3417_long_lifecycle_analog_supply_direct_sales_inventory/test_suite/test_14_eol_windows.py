"""EOL window shape, closed-interval overlap, and rescinded-notice lockdown."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_eol_notice_payload,
    get_part,
    make_eol_notice,
    make_part,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestEolWindows:
    def test_rescind_rescinded_notice_returns_invalid_state(self, api):
        """PRD §3.7: "Rescission is legal only while the notice is `ANNOUNCED` and
        the part's `lifecycle_status` is still `EOL_ANNOUNCED` — otherwise
        `ERR_INVALID_STATE` (HTTP 409); once the sweep has moved the part onward,
        the decision is no longer reversible."

        Design: Corner/state_machines/rescind_rescinded_notice_returns_invalid_state
        """
        part = make_part(part_number="CD4013BE", process_technology="CMOS_180NM")
        notice = make_eol_notice(part["id"], reason="Premature notice")
        first = validate_success(api.rescind_eol_notice(notice["id"], PLANNER), 200)
        assert first["status"] == "RESCINDED"
        assert get_part(part["id"])["lifecycle_status"] == "ACTIVE"

        res = api.rescind_eol_notice(notice["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_part(part["id"])["lifecycle_status"] == "ACTIVE"

    def test_eol_window_too_short_rejected(self, api):
        """PRD §3.7: "`last_order_date` must be at least 180 days after
        `notice_date`, and `last_ship_date` must be at least 90 days after
        `last_order_date`; either violation is `ERR_EOL_WINDOW_INVALID` (HTTP 422)."

        Design: Corner/validations/eol_window_too_short_rejected
        """
        part = make_part(part_number="LF353N", process_technology="ANALOG_BIPOLAR")
        # 2026-09-01 + 179 days = 2027-02-27 (one day short of the 180-day floor);
        # 2027-02-27 + 90 days = 2027-05-28 (the last_ship leg is shape-valid).
        payload = create_eol_notice_payload(
            notice_date="2026-09-01T00:00:00Z",
            last_order_date="2027-02-27T00:00:00Z",
            last_ship_date="2027-05-28T00:00:00Z",
            reason="Too fast",
        )
        res = api.create_eol_notice(part["id"], payload, PLANNER)
        validate_error(res, ApiErrorId.ERR_EOL_WINDOW_INVALID)

        _, meta = validate_paginated(api.list_part_eol_notices(part["id"], PLANNER))
        assert meta["total_count"] == 0
        assert get_part(part["id"])["lifecycle_status"] == "ACTIVE"

    def test_eol_notice_window_closed_overlap_rejected(self, api):
        """PRD §3.7: "A part may not carry two overlapping live notices: if an
        `ANNOUNCED` notice already exists for the part and its closed window from
        `notice_date` through `last_ship_date` intersects the new notice's closed
        window — and because these are closed intervals, touching endpoints count as
        overlap, unlike the capacity-pool adjacency rule — the creation is rejected
        with `ERR_EOL_NOTICE_ACTIVE_EXISTS` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/eol_notice_window_closed_overlap_rejected
        """
        part = make_part(part_number="ULN2003AN", demand_rate_units_per_week=5)
        make_eol_notice(part["id"], reason="Package retirement")

        # Second window touches the first at exactly its last_ship_date endpoint;
        # its own shape is valid: 2027-05-29 + 180d = 2027-11-25, +90d = 2028-02-23.
        payload = create_eol_notice_payload(
            notice_date="2027-05-29T00:00:00Z",
            last_order_date="2027-11-25T00:00:00Z",
            last_ship_date="2028-02-23T00:00:00Z",
            reason="Successor program",
        )
        res = api.create_eol_notice(part["id"], payload, PLANNER)
        validate_error(res, ApiErrorId.ERR_EOL_NOTICE_ACTIVE_EXISTS)

        _, meta = validate_paginated(api.list_part_eol_notices(part["id"], PLANNER))
        assert meta["total_count"] == 1

    def test_eol_notice_interior_overlap_rejected(self, api):
        """PRD §3.7: "A part may not carry two overlapping live notices: if an
        `ANNOUNCED` notice already exists for the part and its closed window from
        `notice_date` through `last_ship_date` intersects the new notice's closed
        window — and because these are closed intervals, touching endpoints count as
        overlap, unlike the capacity-pool adjacency rule — the creation is rejected
        with `ERR_EOL_NOTICE_ACTIVE_EXISTS` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/eol_notice_window_closed_overlap_rejected
        """
        part = make_part(part_number="ULN2003B", demand_rate_units_per_week=5)
        make_eol_notice(part["id"], reason="Package retirement")

        # Second window starts strictly inside the first window's interior;
        # shape-valid: 2027-03-01 + 180d = 2027-08-28, +90d = 2027-11-26.
        payload = create_eol_notice_payload(
            notice_date="2027-03-01T00:00:00Z",
            last_order_date="2027-08-28T00:00:00Z",
            last_ship_date="2027-11-26T00:00:00Z",
            reason="Successor program",
        )
        res = api.create_eol_notice(part["id"], payload, PLANNER)
        validate_error(res, ApiErrorId.ERR_EOL_NOTICE_ACTIVE_EXISTS)
        assert get_part(part["id"])["lifecycle_status"] == "EOL_ANNOUNCED"
