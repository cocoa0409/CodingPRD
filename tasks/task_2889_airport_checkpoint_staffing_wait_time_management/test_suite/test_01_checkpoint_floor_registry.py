"""Checkpoint, lane, officer, time-band and show-up-curve registration.

Covers the resource contract of PRD sections 2.3, 2.4, 3.1 and 3.2: the fields a
create seeds, the fields a read must leave alone, the declared ordering of the
lane collection, and the shape and reference checks that reject a malformed
create.
"""

from decimal import Decimal

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_common_fields,
    assert_field_sequence,
    assert_instant,
    assert_list_meta,
    assert_new_checkpoint_defaults,
    assert_nulls,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CLOCK_0800, Scenario

FORECAST_FIELDS = [
    "forecast_variant",
    "forecast_pax_count",
    "forecast_computed_at_utc",
    "required_standard_lanes",
    "required_expedited_lanes",
    "unmet_standard_demand",
    "unmet_expedited_demand",
]


def as_decimal(value) -> Decimal:
    """A client-supplied two-decimal percentage, however it is serialized."""
    return Decimal(str(value))


class TestCheckpointRegistration:
    """PRD 3.1 - what a newly created checkpoint reports."""

    def test_create_seeds_every_counter_from_its_own_inputs(self, scenario: Scenario):
        """A create returns 201 with the counters of PRD 3.1 seeded, not zeroed.

        Design: Corner/entities/checkpoint_create_returns_201_with_computed_and_system_fields
        """
        scenario.set_clock(CLOCK_0800)
        response = scenario.api.create_checkpoint(
            f.checkpoint_payload(name="T1 Main", terminal_code="T1", total_lane_positions=6),
            ADMIN_HEADERS,
        )
        checkpoint = validate_success(response, 201)

        assert_common_fields(checkpoint)
        assert checkpoint["version"] == 1
        assert_instant(checkpoint["updated_at"], checkpoint["created_at"], "updated_at")
        assert checkpoint["suspended"] is False
        assert_new_checkpoint_defaults(checkpoint, total_lane_positions=6)

        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert envelope["meta"]["api_request_timestamp"]

    def test_read_is_side_effect_free(self, scenario: Scenario):
        """A GET returns the stored row and never bumps version or updated_at.

        Design: Corner/entities/checkpoint_get_by_id_returns_stored_entity_unchanged
        """
        scenario.set_clock(CLOCK_0800)
        created = validate_success(
            scenario.api.create_checkpoint(f.checkpoint_payload(), ADMIN_HEADERS), 201
        )
        scenario.set_clock("2026-09-10T09:00:00Z")

        read = validate_success(scenario.api.get_checkpoint(created["id"], PLANNER_HEADERS))

        assert read["name"] == "T1 Main"
        assert read["terminal_code"] == "T1"
        assert read["version"] == 1
        assert_instant(read["updated_at"], created["updated_at"], "updated_at")
        assert read["wait_threshold_minutes_standard"] == 15
        assert read["wait_threshold_minutes_expedited"] == 8
        assert read["secondary_slot_capacity"] == 2
        assert read["plan_cost_cap_cents"] == 10000000


class TestLaneRegistry:
    """PRD 2.5 and 3.1 - the lane collection and the lane create contract."""

    def test_list_orders_by_position_index_and_paginates(self, base: Scenario):
        """Lanes come back in ascending position_index, not in creation order.

        Design: Corner/entities/lanes_filtered_list_orders_by_position_index_and_paginates
        """
        lane_p3 = base.create_lane(position_index=3)
        lane_p1 = base.create_lane(position_index=1)
        lane_p2 = base.create_lane(position_index=2, lane_type="EXPEDITED")

        rows, meta = validate_paginated(
            base.api.list_lanes(PLANNER_HEADERS, {"checkpoint_id": base.checkpoint_id})
        )
        assert_list_meta(meta, total_count=3, has_more=False)
        assert_field_sequence(rows, "position_index", [1, 2, 3])
        assert rows[0]["id"] == lane_p1["id"]
        assert base.api.list_lanes(PLANNER_HEADERS).json()["response_type"] == "array"

        page, page_meta = validate_paginated(
            base.api.list_lanes(
                PLANNER_HEADERS,
                {"checkpoint_id": base.checkpoint_id, "limit": 2, "offset": 1},
            )
        )
        assert_list_meta(page_meta, total_count=3, limit=2, offset=1, has_more=False)
        assert_field_sequence(page, "position_index", [2, 3])
        assert page[1]["id"] == lane_p3["id"]

        filtered, filtered_meta = validate_paginated(
            base.api.list_lanes(
                PLANNER_HEADERS,
                {"checkpoint_id": base.checkpoint_id, "lane_type": "EXPEDITED"},
            )
        )
        assert_list_meta(filtered_meta, total_count=1)
        assert filtered[0]["id"] == lane_p2["id"]

    def test_missing_required_field_is_rejected_before_anything_persists(
        self, base: Scenario
    ):
        """Every lane input is required, so an omission is a shape failure.

        Design: Corner/entities/lane_create_missing_required_field_returns_invalid_request
        """
        payload = f.lane_payload(base.checkpoint_id, secondary_positions=0)
        payload.pop("max_concurrent_officers")

        validate_error(
            base.api.create_lane(payload, MANAGER_HEADERS), ApiErrorId.INVALID_REQUEST, 400
        )

        rows, meta = validate_paginated(
            base.api.list_lanes(MANAGER_HEADERS, {"checkpoint_id": base.checkpoint_id})
        )
        assert rows == []
        assert_list_meta(meta, total_count=0)
        assert base.checkpoint_version() == 1

    def test_body_foreign_key_is_resolved_against_its_own_collection(self, base: Scenario):
        """A body-borne parent link is validated, per collection, before the write.

        Design: Corner/entities/lane_create_with_unknown_checkpoint_returns_checkpoint_not_found
        """
        validate_error(
            base.api.create_lane(f.lane_payload(UNKNOWN_UUID), MANAGER_HEADERS),
            ApiErrorId.CHECKPOINT_NOT_FOUND,
            404,
        )
        validate_error(
            base.api.create_flight_schedule_entry(
                f.flight_payload(base.checkpoint_id, UNKNOWN_UUID, "2026-09-10T10:30:00Z"),
                PLANNER_HEADERS,
            ),
            ApiErrorId.SHOW_UP_CURVE_NOT_FOUND,
            404,
        )
        validate_error(
            base.api.create_flight_schedule_entry(
                f.flight_payload(
                    base.checkpoint_id, base.checkpoint_id, "2026-09-10T10:30:00Z"
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.SHOW_UP_CURVE_NOT_FOUND,
            404,
        )

        rows, _ = validate_paginated(
            base.api.list_flight_schedule_entries(
                PLANNER_HEADERS, {"checkpoint_id": base.checkpoint_id}
            )
        )
        assert rows == []


class TestTimeBandRegistry:
    """PRD 3.2 - band defaults, the computed band end, and the input ranges."""

    def test_omitted_seasonal_multiplier_falls_back_to_one(self, base: Scenario):
        """seasonal_multiplier is optional and defaults to 1.00, not to null or 0.

        Design: Corner/entities/time_band_omitting_seasonal_multiplier_applies_default_one
        """
        band = validate_success(
            base.api.create_time_band(
                f.time_band_payload(
                    base.checkpoint_id,
                    "2026-09-10T10:00:00Z",
                    expedited_share_pct=0,
                    seasonal_multiplier=None,
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        assert band["seasonal_multiplier"] is not None
        assert as_decimal(band["seasonal_multiplier"]) == Decimal("1.00")
        assert_instant(band["band_end_utc"], "2026-09-10T10:30:00Z", "band_end_utc")
        assert_nulls(band, FORECAST_FIELDS)

    def test_band_end_is_computed_thirty_minutes_after_the_start(self, base: Scenario):
        """band_end_utc is always the start plus the fixed thirty-minute band.

        Design: Corner/entities/time_band_end_utc_is_computed_and_client_value_is_ignored
        """
        band = validate_success(
            base.api.create_time_band(
                f.time_band_payload(
                    base.checkpoint_id,
                    "2026-09-10T10:30:00Z",
                    expedited_share_pct=40,
                    seasonal_multiplier=1.25,
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        assert_instant(band["band_end_utc"], "2026-09-10T11:00:00Z", "band_end_utc")
        assert band["expedited_share_pct"] == 40
        assert as_decimal(band["seasonal_multiplier"]) == Decimal("1.25")

        read = validate_success(base.api.get_time_band(band["id"], PLANNER_HEADERS))
        assert_instant(read["band_end_utc"], "2026-09-10T11:00:00Z", "band_end_utc")

    @pytest.mark.parametrize(
        "band_start_utc,expedited_share_pct,seasonal_multiplier",
        [
            ("2026-09-10T10:15:00Z", 0, 1.00),
            ("2026-09-10T10:00:30Z", 0, 1.00),
            ("2026-09-10T10:00:00Z", 140, 1.00),
            ("2026-09-10T10:00:00Z", 0, 4.00),
        ],
    )
    def test_band_inputs_outside_their_declared_range_are_rejected(
        self,
        base: Scenario,
        band_start_utc: str,
        expedited_share_pct: int,
        seasonal_multiplier: float,
    ):
        """A misaligned start, a stray second, or an out-of-range number is a 400.

        Design: Corner/entities/time_band_start_off_the_half_hour_returns_invalid_request
        """
        validate_error(
            base.api.create_time_band(
                f.time_band_payload(
                    base.checkpoint_id,
                    band_start_utc,
                    expedited_share_pct=expedited_share_pct,
                    seasonal_multiplier=seasonal_multiplier,
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        rows, _ = validate_paginated(
            base.api.list_time_bands(PLANNER_HEADERS, {"checkpoint_id": base.checkpoint_id})
        )
        assert rows == []


class TestOfficerRegistry:
    """PRD 3.1 and 2.5 - server-owned officer fields and the officer 404."""

    def test_officer_system_fields_are_server_generated(self, scenario: Scenario):
        """duty_status, both ledgers and the identity fields are seeded by the server.

        Design: Corner/entities/officer_system_fields_are_server_generated
        """
        scenario.set_clock(CLOCK_0800)
        officer = validate_success(
            scenario.api.create_officer(
                f.officer_payload(
                    badge_number="B-1001",
                    full_name="Ada Lane",
                    certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
                    base_rate_cents_per_minute=100,
                    weekly_regular_minutes_cap=45,
                    weekly_overtime_minutes_cap=600,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_common_fields(officer)
        assert officer["duty_status"] == "OFF_DUTY"
        assert officer["committed_duty_minutes"] == 0
        assert officer["approved_detail_minutes"] == 0
        assert officer["version"] == 1
        assert officer["id"] != officer["badge_number"]
        assert officer["certifications"] == ["STANDARD_LANE", "ADVANCED_IMAGING"]

    def test_unknown_officer_id_returns_the_officer_not_found_code(self, scenario: Scenario):
        """A well-formed but unknown identifier is the entity's own 404, not a 400.

        Design: Corner/entities/officer_get_with_unknown_id_returns_officer_not_found
        """
        scenario.set_clock(CLOCK_0800)
        response = scenario.api.get_officer(UNKNOWN_UUID, PLANNER_HEADERS)

        validate_error(response, ApiErrorId.OFFICER_NOT_FOUND, 404)
        envelope = response.json()
        assert envelope["response_type"] == "error"
        assert isinstance(envelope["data"]["message"], str)
        assert envelope["data"]["message"] != ""


class TestImmutableReferenceData:
    """PRD 2.4 - the two resources that carry only id and created_at."""

    def test_curve_and_observation_carry_no_version_or_updated_at(self, base: Scenario):
        """A show-up curve and a wait sample are immutable and unversioned.

        Design: Corner/entities/show_up_curve_is_immutable_with_no_update_endpoint
        """
        curve = validate_success(
            base.api.get_show_up_curve(base.curve["id"], PLANNER_HEADERS)
        )
        assert_common_fields(curve, versioned=False)
        assert curve["name"] == base.curve["name"]
        assert curve["window_start_minutes_before"] == 30
        assert curve["window_end_minutes_before"] == 0

        observation = base.post_observation()
        assert_common_fields(observation, versioned=False)
        read_back = validate_success(
            base.api.get_wait_observation(observation["id"], PLANNER_HEADERS)
        )
        assert_common_fields(read_back, versioned=False)
