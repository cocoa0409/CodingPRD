"""Breadth coverage of the lifecycle rules: initial states, terminal lockdown,
publish supersession, cancellation compensation, the accuracy gate and line mapping."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_instant,
    factories as f,
    fixtures,
    make_marketplace_channel_headers,
)


class TestOrderInitialStateIsAccepted:
    def test_successful_place_reports_accepted_authorized_unverified(self, api):
        """Acceptance is atomic with creation: the order never rests in PLACED.

        PRD §3.4: "On acceptance the order's `fulfillment_status` moves from the transient `PLACED` straight to `ACCEPTED`, `payment_status` is `AUTHORIZED`, and `accuracy_status` begins `UNVERIFIED`."
        PRD §3.4: "The order's `placed_at` is stamped from the logical clock, its `line` is assigned at acceptance — `DIGITAL` for first-party digital and marketplace orders, `IN_STORE` for in-store orders — and each line is minted a `lid_label_code`, the short code printed on the bowl's lid for later accuracy verification, and each line's `accuracy_check` begins `PENDING`."
        Design: Corner/state_machines/order_initial_state_is_accepted_on_successful_place
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "IS"})
        order = fixtures.place_order(api, world["store_id"], world["item_id"])
        assert order["fulfillment_status"] == "ACCEPTED"
        assert order["payment_status"] == "AUTHORIZED"
        assert order["accuracy_status"] == "UNVERIFIED"
        assert order["line"] == "IN_STORE"


class TestPickupFromTerminalPickedUpRejected:
    def test_second_pickup_returns_already_terminal(self, api):
        """From terminal PICKED_UP no further transition is possible.

        PRD §3.5: "Pickup, performed by a `LineWorker`, moves a `READY` order to `PICKED_UP`."
        PRD §3.5: "Two preconditions gate the start: the order must currently be `ACCEPTED` (any other state is `ERR_INVALID_STATE`, and any terminal state is `ERR_ALREADY_TERMINAL`), and a staffing deployment covering the order's line must exist in `PUBLISHED` or `LOCKED` status for a `shift_date` equal to the store's `current_business_day` — without one the start is refused with `ERR_DEPLOYMENT_MISSING`."
        Design: Corner/state_machines/pickup_from_terminal_picked_up_is_rejected
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "TL"})
        order = fixtures.order_picked_up(api, world)
        assert order["fulfillment_status"] == "PICKED_UP"

        response = api.pickup_order(
            world["store_id"], order["id"], fixtures.LINE_WORKER_HEADERS
        )
        validate_error(response, ApiErrorId.ALREADY_TERMINAL.value)

        current = fixtures.read_order(api, order["id"])
        assert current["fulfillment_status"] == "PICKED_UP"


class TestDeploymentPublishSupersedesExistingPublished:
    def test_second_publish_supersedes_the_first(self, api):
        """Publishing a new deployment for a covered shift_date supersedes the older one.

        PRD §3.8: "Publishing also supersedes whatever deployment was previously `PUBLISHED` for the same `shift_date`, moving it to `SUPERSEDED`."
        PRD §3.8: "Publishing, also by a `StoreManager`, moves a deployment from `DRAFT` to `PUBLISHED` under the same consistency rules — the mix fractions summing to one and a headcount of at least two — and computes the line split: `digital_headcount` is the `headcount` multiplied by `predicted_digital_mix_pct` rounded half-up to a whole person, and `instore_headcount` is the remainder of `headcount` once the digital share is removed, so the two always sum exactly to the scheduled total."
        Design: Corner/state_machines/deployment_publish_supersedes_existing_published
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="DS")

        first = fixtures.create_deployment(api, store["id"], store["version"])
        fixtures.publish_deployment(api, store["id"], first["id"], publisher_id="sm-pat")
        assert (
            get_success_data(api.get_deployment(first["id"], fixtures.STORE_MANAGER_HEADERS))[
                "status"
            ]
            == "PUBLISHED"
        )

        version_now = fixtures.read_store(api, store["id"])["version"]
        second = fixtures.create_deployment(
            api,
            store["id"],
            version_now,
            predicted_digital_mix_pct=0.6,
            predicted_instore_mix_pct=0.4,
            headcount=6,
        )
        fixtures.publish_deployment(api, store["id"], second["id"], publisher_id="sm-pat")

        first_now = get_success_data(
            api.get_deployment(first["id"], fixtures.STORE_MANAGER_HEADERS)
        )
        second_now = get_success_data(
            api.get_deployment(second["id"], fixtures.STORE_MANAGER_HEADERS)
        )
        assert first_now["status"] == "SUPERSEDED"
        assert second_now["status"] == "PUBLISHED"
        # round_half_up(6 * 0.6) = 4 digital, remainder 2 in-store.
        assert second_now["digital_headcount"] == 4
        assert second_now["instore_headcount"] == 2


class TestCancelReleasesCapacityAndVoidsPayment:
    def test_cancel_compensates_window_load_and_voids_payment(self, api):
        """Cancelling an accepted digital order releases its committed capacity.

        PRD §3.6: "A `StoreManager` may cancel an order while its `fulfillment_status` is `PLACED` or `ACCEPTED`, moving it to the terminal `CANCELLED` state; from any other state the request is rejected with `ERR_INVALID_STATE`, and from a terminal state (`PICKED_UP`, `CANCELLED`, or `EXPIRED`) with `ERR_ALREADY_TERMINAL`. Cancellation is fully compensating: the committed entrees are released back to the production window's committed counter and to the store's interval load, the throttle band is re-evaluated, the grams the order consumed are restored to the newest `ACTIVE` batch of each ingredient (ties on `created_at` broken by the latest `cooked_at`), suppression states are re-evaluated against the restored stock, and `payment_status` moves to `VOIDED`."
        Design: Corner/state_machines/cancel_releases_capacity_and_voids_payment
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api,
            store_overrides={"store_code": "CX", "digital_line_capacity_per_interval": 5},
        )
        order = fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL", quantity=2
        )
        assert fixtures.read_store(api, world["store_id"])["digital_interval_load"] == 2

        cancelled = fixtures.cancel(api, world["store_id"], order["id"])
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "VOIDED"
        assert fixtures.read_store(api, world["store_id"])["digital_interval_load"] == 0
        window = fixtures.read_window(api, world["window_id"])
        assert window["digital_committed"] == 0


class TestMarkReadyWithoutVerification:
    def test_in_production_without_pass_verification_is_refused(self, api):
        """The accuracy gate refuses mark-ready before any PASS verification.

        PRD §3.5: "A `LineWorker` may then mark the order ready, moving it from `IN_PRODUCTION` to `READY`, only when every line's `accuracy_check` is `MATCHED` following at least one `PASS` verification; otherwise the transition is rejected with `ERR_ACCURACY_UNVERIFIED`."
        Design: Corner/state_machines/mark_ready_without_verification_returns_accuracy_unverified
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "AV"})
        order = fixtures.order_in_production(api, world)

        response = api.mark_ready(
            world["store_id"], order["id"], fixtures.LINE_WORKER_HEADERS
        )
        validate_error(response, ApiErrorId.ACCURACY_UNVERIFIED.value)

        current = fixtures.read_order(api, order["id"])
        assert current["fulfillment_status"] == "IN_PRODUCTION"


class TestMarketplaceMapsToDigitalLine:
    def test_marketplace_order_lands_on_digital_line_with_waterfall_promise(self, api):
        """A marketplace order is a digital-line order promised at the window's end.

        PRD §3.4: "The order's `placed_at` is stamped from the logical clock, its `line` is assigned at acceptance — `DIGITAL` for first-party digital and marketplace orders, `IN_STORE` for in-store orders — and each line is minted a `lid_label_code`, the short code printed on the bowl's lid for later accuracy verification, and each line's `accuracy_check` begins `PENDING`."
        PRD §3.3: "The first eligible window in start order wins, and the order's `promised_at` is stamped as that window's `interval_end`."
        Design: Corner/state_machines/order_marketplace_maps_to_digital_line
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "MM"})
        channel = fixtures.create_marketplace_channel(
            api, channel_code="DASH", markup_pct=0.18, commission_pct=0.22, active=True
        )
        order = validate_success(
            api.create_order(
                world["store_id"],
                f.order_payload(
                    "MARKETPLACE",
                    [f.order_line_payload(world["item_id"])],
                    marketplace_channel_id=channel["id"],
                    external_order_ref="DASH-9001",
                ),
                make_marketplace_channel_headers(channel["id"]),
            ),
            expected_status=201,
        )
        assert order["line"] == "DIGITAL"
        assert_instant(order["promised_at"], "2026-09-01T10:30:00Z", "promised_at")
        assert order["entree_count"] == 1
