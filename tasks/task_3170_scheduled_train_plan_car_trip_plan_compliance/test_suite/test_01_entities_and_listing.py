"""Corner-queue tests: entity creation defaults, listing pagination, 404s,
and referential creation guards."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_train_plan,
    assert_yard,
    create_yard,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestYardCreate:
    def test_yard_create_applies_defaults_and_system_fields(self, api, np_headers):
        """PRD: "A yard begins life `OPEN` with zero overage."

        PRD §2.5: "At server startup the logical clock is exactly
        `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time."
        PRD §2.4: "`version` is a system-managed integer that increments by
        exactly one on every mutation to the resource."

        Design: Corner/entities/yard_create_applies_defaults_and_system_fields
        """
        resp = api.create_yard(
            {
                "yard_code": "EN-NPL",
                "dwell_benchmark_hours": 12,
                "classification_capacity_cars": 250,
            },
            np_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_yard(data)
        assert data["posture"] == "OPEN"
        assert data["current_dwell_overage_hours"] == 0
        assert data["version"] == 1
        assert data["yard_code"] == "EN-NPL"
        assert data["dwell_benchmark_hours"] == 12
        assert data["classification_capacity_cars"] == 250
        # Timestamps are stamped from the logical clock (server default).
        assert data["created_at"].startswith("2026-09-01T00:00:00")
        assert data["updated_at"] == data["created_at"]


class TestTrainPlanCreate:
    def test_train_plan_create_starts_in_draft(self, api, np_headers):
        """PRD §3.1: "A new plan is born in `DRAFT` status."

        Design: Corner/entities/train_plan_create_starts_in_draft
        """
        yA = create_yard(yard_code="EN2-A")
        yB = create_yard(yard_code="EN2-B")
        resp = api.create_train_plan(
            {
                "train_symbol": "EN2-MSGAL",
                "origin_yard_id": yA["id"],
                "destination_yard_id": yB["id"],
                "scheduled_departure_utc": "2026-09-02T08:00:00Z",
                "cutoff_minutes": 45,
                "frequency_mask": ["WED", "FRI"],
                "route_distance_miles": 412.5,
                "dwell_benchmark_hours": 10,
            },
            np_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_train_plan(data)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["cutoff_minutes"] == 45
        assert data["route_distance_miles"] == 412.5
        assert data["frequency_mask"] == ["WED", "FRI"]

    def test_train_plan_create_same_yard_rejected(self, api, np_headers, any_headers):
        """PRD §3.1: "Origin and destination must differ; a plan naming the
        same yard for both is rejected with `ERR_SAME_ORIGIN_DESTINATION`
        (HTTP 422)."

        Design: Corner/entities/train_plan_create_same_yard_rejected
        """
        yA = create_yard(yard_code="EN6-A")
        resp = api.create_train_plan(
            {
                "train_symbol": "EN6-LOOP",
                "origin_yard_id": yA["id"],
                "destination_yard_id": yA["id"],
                "scheduled_departure_utc": "2026-09-02T08:00:00Z",
                "cutoff_minutes": 30,
                "frequency_mask": ["WED"],
                "route_distance_miles": 100,
                "dwell_benchmark_hours": 10,
            },
            np_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_ORIGIN_DESTINATION.value)
        _data, meta = validate_paginated(api.list_train_plans(any_headers))
        assert meta["total_count"] == 0, "rejected plan must not persist"


class TestYardListing:
    def test_yards_list_paginates_with_total_count_and_has_more(self, api, np_headers, any_headers):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100. `offset` skips that
        many items from the front of the result set and defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/yards_list_paginates_with_total_count_and_has_more
        """
        for code in ("EN3-1", "EN3-2", "EN3-3"):
            create_yard(yard_code=code)

        page1, meta1 = validate_paginated(
            api.list_yards(any_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_yards(any_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        page_all, meta_all = validate_paginated(api.list_yards(any_headers))
        assert len(page_all) == 3, "default limit 10 returns all 3 rows"
        assert meta_all["total_count"] == 3


class TestNotFound:
    def test_get_nonexistent_yard_returns_404(self, api, any_headers):
        """PRD §2.9: "Existence failures surface as the resource-specific
        identifiers `ERR_YARD_NOT_FOUND` ... (each HTTP 404)."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/get_nonexistent_yard_returns_404
        """
        resp = api.get_yard("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", any_headers)
        err = validate_error(resp, ApiErrorId.ERR_YARD_NOT_FOUND.value)
        assert err["message"].strip(), "error message must be non-empty"

    def test_shipment_create_with_unknown_customer_returns_404(self, api, np_headers, sm_headers, any_headers):
        """PRD §2.9: "Existence failures surface as the resource-specific
        identifiers ... `ERR_CUSTOMER_NOT_FOUND` ... (each HTTP 404)."

        Design: Corner/entities/shipment_create_with_unknown_customer_returns_404
        """
        yA = create_yard(yard_code="EN5-A")
        yB = create_yard(yard_code="EN5-B")
        resp = api.create_shipment(
            {
                "customer_id": NON_EXISTENT_UUID,
                "origin_yard_id": yA["id"],
                "destination_yard_id": yB["id"],
                "car_count": 2,
                "first_mile_pickup_by": "2026-09-02T00:00:00Z",
                "last_mile_delivery_by": "2026-09-05T00:00:00Z",
                "committed_route_miles": 300,
            },
            sm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)
        _data, meta = validate_paginated(
            api.list_shipments(any_headers, params={"customer_id": NON_EXISTENT_UUID})
        )
        assert meta["total_count"] == 0
