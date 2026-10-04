"""Breadth coverage of the error catalogue: capacity exhaustion and stale versions."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
)


class TestLineCapacityExceeded:
    def test_full_store_with_no_open_window_rejects_digital_order(self, api):
        """When no open window has room, the digital order is refused outright.

        PRD §3.3: "If no open window is eligible, placement is rejected with `ERR_LINE_CAPACITY_EXCEEDED`."
        PRD §2.9: "When the current window's `digital_committed` is at or above the store's `digital_line_capacity_per_interval`, the state is `CLOSED`."
        Design: Corner/errors/err_line_capacity_exceeded_triggerable
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api,
            store_overrides={
                "store_code": "LC",
                "digital_line_capacity_per_interval": 1,
                "instore_line_capacity_per_interval": 10,
                "overage_threshold_pct": 1.0,
            },
        )
        # The single window absorbs exactly one digital entree.
        fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL"
        )
        store = fixtures.read_store(api, world["store_id"])
        assert store["throttle_state"] == "CLOSED"

        response = api.create_order(
            world["store_id"],
            f.order_payload(
                "FIRST_PARTY_DIGITAL", [f.order_line_payload(world["item_id"])]
            ),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(response, ApiErrorId.LINE_CAPACITY_EXCEEDED.value)


class TestStaleVersionOnDeploymentCreate:
    def test_second_create_with_stale_version_rejected_412(self, api):
        """A create carrying the pre-bump store version loses to the OCC guard.

        PRD §2.8: "Creating a staffing deployment for a store requires a non-optional `expected_store_version` field in the request body carrying the client's last observed `version` of that store; if the store's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "Both guarded operations increment the store's `version` by one on success."
        Design: Corner/errors/err_stale_version_on_deployment_create
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="SV")
        base_version = store["version"]

        first = validate_success(
            api.create_deployment(
                store["id"],
                f.deployment_payload("2026-09-02", base_version),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert first["id"]

        # The first create bumped the store version, so the same version is now stale.
        stale = api.create_deployment(
            store["id"],
            f.deployment_payload("2026-09-03", base_version),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(stale, ApiErrorId.STALE_VERSION.value)
