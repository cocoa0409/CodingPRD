"""Plant creation defaults, not-found envelope, server-minted fields, and
nested-path existence (PRD §2.5, §2.6, §3.1)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    set_clock, create_plant_payload, create_line_payload,
    admin, manager,
)


class TestPlantCreateDefaults:
    def test_plant_create_returns_computed_defaults_and_open_posture(self, api):
        """PRD §3.1: "A new plant starts with `warehouse_on_hand_units` and
        `projected_warehouse_units` at 0, `posture` of `OPEN`, an
        `ops_run_index` of 0, and its year-to-date accumulators
        `scrap_credit_lbs_ytd` and `metal_consumed_lbs_ytd` at 0, which leaves
        the derived `recycled_content_pct` at 0 as well."

        Design: Corner/entities/plant_create_returns_computed_defaults_and_open_posture
        """
        set_clock()
        resp = api.create_plant(create_plant_payload(
            name="Phoenix Can Plant", region="US-SW",
            warehouse_capacity_units=1_000_000), admin())
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"])
        assert data["warehouse_on_hand_units"] == 0
        assert data["projected_warehouse_units"] == 0
        assert data["posture"] == "OPEN"
        assert data["ops_run_index"] == 0
        assert data["scrap_credit_lbs_ytd"] == 0
        assert data["metal_consumed_lbs_ytd"] == 0
        assert data["recycled_content_pct"] == 0
        assert data["version"] == 1
        assert "created_at" in data and "updated_at" in data

    def test_plant_create_ignores_client_supplied_id_extra_field(self, api):
        """PRD §2.5: "`id` (string): a server-minted unique identifier formatted
        as a UUID, with no type prefix." and "`version` (integer): a
        system-managed integer that increments by 1 on every modification".

        Design: Corner/entities/plant_create_ignores_client_supplied_id_extra_field
        """
        set_clock()
        supplied_id = "00000000-0000-4000-8000-0000000000ff"
        payload = create_plant_payload()
        payload["id"] = supplied_id
        payload["version"] = 99
        resp = api.create_plant(payload, admin())
        data = validate_success(resp, 201)
        assert data["version"] == 1, "server-managed version starts at 1"
        assert data["id"] != supplied_id, "id is server-minted, not client-supplied"


class TestPlantNotFound:
    def test_plant_get_unknown_id_returns_not_found_with_error_envelope(self, api):
        """PRD §2.6: "the first path-segment identifier that does not correspond
        to an existing resource rejects the request with `ERR_NOT_FOUND`
        (HTTP 404), and later segments are never consulted."

        Design: Corner/entities/plant_get_unknown_id_returns_not_found_with_error_envelope
        """
        set_clock()
        resp = api.get_plant(NON_EXISTENT_UUID, manager())
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["message"].strip(), "error envelope carries a message"

    def test_line_create_under_unknown_plant_returns_not_found(self, api):
        """PRD §2.6: "the first path-segment identifier that does not correspond
        to an existing resource rejects the request with `ERR_NOT_FOUND`
        (HTTP 404), and later segments are never consulted."

        Design: Corner/entities/line_create_under_unknown_plant_returns_not_found
        """
        set_clock()
        resp = api.create_line(NON_EXISTENT_UUID, create_line_payload(), manager())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
