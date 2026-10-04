"""Temporal intervals: the station service window's strict ordering
constraint."""

from test_helpers import (
    TEST_USERS,
    create_event_site_locked,
    create_station_payload,
    validate_error,
)

LC = TEST_USERS["logistics_coordinator_headers"]


class TestStationWindowInverted:
    def test_zero_length_window_rejected(self, api):
        """PRD §3.5: "The close must be strictly after the open; an inverted
        or zero-length window is rejected with `ERR_TEMPORAL_WINDOW_INVALID`."

        Design: Difficulty/resource_temporal_overlap/station_window_inverted_rejected
        """
        event = create_event_site_locked(
            event_overrides={
                "host_state_code": "VA",
                "service_date": "2026-10-17",
                "doors_open_utc": "2026-10-17T10:00:00Z",
            },
            site_overrides={"state_code": "VA"},
        )
        response = api.create_station(
            event["id"],
            create_station_payload(
                station_label="V-16",
                station_type="VISION",
                service_window_open_utc="2026-10-17T11:00:00Z",
                service_window_close_utc="2026-10-17T11:00:00Z",
            ),
            LC,
        )
        validate_error(response, "ERR_TEMPORAL_WINDOW_INVALID")

    def test_inverted_window_rejected(self, api):
        """PRD §3.5: "The close must be strictly after the open; an inverted
        or zero-length window is rejected with `ERR_TEMPORAL_WINDOW_INVALID`."

        Design: Difficulty/resource_temporal_overlap/station_window_inverted_rejected
        """
        event = create_event_site_locked(
            event_overrides={
                "host_state_code": "VA",
                "service_date": "2026-10-17",
                "doors_open_utc": "2026-10-17T10:00:00Z",
            },
            site_overrides={"state_code": "VA"},
        )
        response = api.create_station(
            event["id"],
            create_station_payload(
                station_label="V-16",
                station_type="VISION",
                service_window_open_utc="2026-10-17T19:00:00Z",
                service_window_close_utc="2026-10-17T11:00:00Z",
            ),
            LC,
        )
        validate_error(response, "ERR_TEMPORAL_WINDOW_INVALID")
