"""Location creation defaults and posture fields."""
from test_helpers import (
    ApiErrorId,
    assert_location,
    create_location,
    validate_success,
)


class TestLocationCreateDefaults:
    def test_location_create_returns_defaults_and_posture(self, api, shift_manager_headers):
        """PRD: "A freshly created location starts calm: `weather_mode` is
        `NORMAL`, `rush_index` is 0, `stalls_available` equals `stall_capacity`,
        and `lane_posture` is `OPEN`."

        Design: Corner/entities/location_create_returns_defaults_and_posture
        """
        location = create_location(code="TST-001", name="Test", stall_capacity=5)
        assert_location(location)
        assert location["weather_mode"] == "NORMAL"
        assert location["rush_index"] == 0
        assert location["stalls_available"] == 5
        assert location["lane_posture"] == "OPEN"
        assert location["version"] == 1
        assert location["created_at"] is not None
        assert location["updated_at"] is not None

    def test_location_create_readback_carries_posture_fields(self, api, shift_manager_headers):
        """PRD: "Reading a location returns these computed posture fields
        alongside the configured ones."

        Design: Corner/entities/location_create_returns_defaults_and_posture
        """
        location = create_location(code="TST-002", name="Test Two", stall_capacity=7)
        resp = api.get_location(location["id"], shift_manager_headers)
        read = validate_success(resp, expected_status=200)
        assert_location(read)
        assert read["code"] == "TST-002"
        assert read["weather_mode"] == "NORMAL"
        assert read["rush_index"] == 0
        assert read["stalls_available"] == 7
        assert read["lane_posture"] == "OPEN"
