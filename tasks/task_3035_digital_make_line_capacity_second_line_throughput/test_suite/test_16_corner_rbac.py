"""Breadth coverage of role authorization: exclusive lock, segregation of duties,
and the marketplace channel's own-identity order scope."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
    make_general_manager_headers,
    make_marketplace_channel_headers,
)


class TestLineWorkerCannotLockDeployment:
    def test_lock_refused_for_line_worker(self, api):
        """Locking is exclusive to GeneralManager; a LineWorker is refused 403.

        PRD §2.1: "A request whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.10: "Deployment authoring is deliberately split across two roles and two people. A `StoreManager` creates and publishes staffing deployments; only a `GeneralManager` may lock a published deployment, and the locking user's `X-User-ID` must differ from the publishing user's `X-User-ID`."
        Design: Corner/rbac/line_worker_cannot_lock_deployment
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="RB")
        deployment = fixtures.create_deployment(api, store["id"], store["version"])
        fixtures.publish_deployment(api, store["id"], deployment["id"], publisher_id="sm-pat")

        response = api.lock_deployment(
            store["id"], deployment["id"], fixtures.LINE_WORKER_HEADERS
        )
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE.value)

        current = get_success_data(
            api.get_deployment(deployment["id"], fixtures.STORE_MANAGER_HEADERS)
        )
        assert current["status"] == "PUBLISHED"


class TestSameUserCannotPublishAndLock:
    def test_publisher_cannot_lock_but_another_general_manager_can(self, api):
        """Segregation of duties: the locker's identity must differ from the publisher's.

        PRD §2.10: "Deployment authoring is deliberately split across two roles and two people. A `StoreManager` creates and publishes staffing deployments; only a `GeneralManager` may lock a published deployment, and the locking user's `X-User-ID` must differ from the publishing user's `X-User-ID`. A lock attempted by the same user who published the deployment is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        Design: Corner/rbac/same_user_cannot_publish_and_lock
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="SD")
        deployment = fixtures.create_deployment(api, store["id"], store["version"])
        fixtures.publish_deployment(api, store["id"], deployment["id"], publisher_id="gm-same")

        same_user = api.lock_deployment(
            store["id"], deployment["id"], make_general_manager_headers("gm-same")
        )
        validate_error(same_user, ApiErrorId.SEGREGATION_OF_DUTIES.value)

        other_user = api.lock_deployment(
            store["id"], deployment["id"], make_general_manager_headers("gm-other")
        )
        locked = validate_success(other_user, expected_status=200)
        assert locked["status"] == "LOCKED"


class TestMarketplaceChannelCannotPlaceInstoreOrder:
    def test_marketplace_role_on_in_store_channel_refused_403(self, api):
        """The marketplace identity may inject only MARKETPLACE orders.

        PRD §2.1: "A request whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.4: "A `LineWorker` or `StoreManager` may place an order (a `LineWorker` only on the in-store channel); a `MarketplaceChannel` injects marketplace orders under its own identity, so a marketplace order's `marketplace_channel_id` must equal the caller's `X-User-ID` — a `marketplace_channel_id` that does not resolve is `ERR_CHANNEL_NOT_FOUND`."
        Design: Corner/rbac/marketplace_channel_cannot_place_instore_order
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "MR"})
        channel = fixtures.create_marketplace_channel(api)

        response = api.create_order(
            world["store_id"],
            f.order_payload("IN_STORE", [f.order_line_payload(world["item_id"])]),
            make_marketplace_channel_headers(channel["id"]),
        )
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE.value)
