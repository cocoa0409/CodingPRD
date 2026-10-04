"""Metrics rollup empty set, order listing/pagination, and 404 reads."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    create_location,
    create_stall,
    intercom_checkin,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


class TestMetricsRollupEmptySet:
    def test_metrics_rollup_empty_set_returns_nulls(self, api, shift_manager_headers):
        """PRD: "Over an empty set the rollup reports `count_delivered` of 0
        with both means and the on-time rate null."

        Design: Corner/calculations/metrics_rollup_empty_set_returns_nulls
        """
        location = create_location(code="CRN-MET1")
        metrics = validate_success(
            api.get_metrics(location["id"], shift_manager_headers), 200
        )
        assert metrics["count_delivered"] == 0
        assert metrics["count_late"] == 0
        assert metrics["avg_checkout_to_ready_seconds"] is None
        assert metrics["avg_ready_to_delivered_seconds"] is None
        assert metrics["on_time_rate"] is None

    def test_metrics_rollup_empty_set_with_channel_filter_returns_nulls(
        self, api, shift_manager_headers
    ):
        """PRD: "Over an empty set the rollup reports `count_delivered` of 0
        with both means and the on-time rate null."

        A channel filter over a location with no delivered orders matches the
        empty set and reports the same null means.

        Design: Corner/calculations/metrics_rollup_empty_set_returns_nulls
        """
        location = create_location(code="CRN-MET2")
        metrics = validate_success(
            api.get_metrics(
                location["id"], shift_manager_headers, params={"channel": "DRIVE_THRU"}
            ),
            200,
        )
        assert metrics["count_delivered"] == 0
        assert metrics["avg_checkout_to_ready_seconds"] is None
        assert metrics["avg_ready_to_delivered_seconds"] is None
        assert metrics["on_time_rate"] is None


class TestOrderListFilteringAndPagination:
    def test_order_list_filters_by_status_and_paginates(self, api, shift_manager_headers):
        """PRD: "List responses include `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."
        PRD: "Orders are listed with filters for `status`, `channel`,
        `payment_status`, `location_id`, `stall_id`, `customer_id`, and
        `delivery_run_id`."

        Three DRAFT orders from three stall check-ins: a status=DRAFT filter
        with limit 2 returns two rows, total_count 3, and has_more true.

        Design: Corner/endpoints/order_list_filters_by_status_and_paginates
        """
        location = create_location(code="CRN-LIST1", stall_capacity=3)
        for stall_number in (1, 2, 3):
            stall = create_stall(location["id"], stall_number=stall_number)
            intercom_checkin(location["id"], stall["id"])

        resp = api.list_orders(
            location["id"], shift_manager_headers,
            params={"status": "DRAFT", "limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert all(order["status"] == "DRAFT" for order in data)

    def test_order_list_second_page_completes_filtered_set(self, api, shift_manager_headers):
        """PRD: "List responses include `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        The second page of the same filtered listing carries the remaining
        row and has_more false.

        Design: Corner/endpoints/order_list_filters_by_status_and_paginates
        """
        location = create_location(code="CRN-LIST2", stall_capacity=3)
        for stall_number in (1, 2, 3):
            stall = create_stall(location["id"], stall_number=stall_number)
            intercom_checkin(location["id"], stall["id"])

        resp = api.list_orders(
            location["id"], shift_manager_headers,
            params={"status": "DRAFT", "limit": 2, "offset": 2},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestNotFoundReads:
    def test_get_nonexistent_order_returns_404(self, api, shift_manager_headers):
        """PRD: "the location is resolved first, then the stall, then the
        fault, order, run, or tip record beneath it, and each identifier must
        not only exist but belong to the enclosing resource named earlier in
        the path. The first identifier that fails existence or nesting yields
        `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/endpoints/get_nonexistent_order_returns_404
        """
        location = create_location(code="CRN-404A")
        resp = api.get_order(location["id"], NON_EXISTENT_UUID, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_nonexistent_stall_returns_404(self, api, shift_manager_headers):
        """PRD: "the location is resolved first, then the stall, then the
        fault, order, run, or tip record beneath it, and each identifier must
        not only exist but belong to the enclosing resource named earlier in
        the path. The first identifier that fails existence or nesting yields
        `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/endpoints/get_nonexistent_order_returns_404
        """
        location = create_location(code="CRN-404B")
        resp = api.get_stall(location["id"], NON_EXISTENT_UUID, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
