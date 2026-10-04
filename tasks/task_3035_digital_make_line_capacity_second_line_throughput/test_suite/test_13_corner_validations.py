"""Breadth coverage of the validation ladder: auth headers, existence order,
deployment consistency, marketplace references, ingredient sufficiency, EXTRA doubling."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
    headers_without_role,
    make_marketplace_channel_headers,
)


class TestMissingAuthHeader:
    def test_request_without_role_header_is_rejected_400(self, api):
        """A request missing X-User-Role fails the first check in the ladder.

        PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the operational capacity in which they act. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        Design: Corner/validations/missing_auth_header_returns_400
        """
        fixtures.set_clock(api, fixtures.MORNING)
        response = api.list_stores(headers_without_role("user-1"))
        validate_error(response, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


class TestExistenceBeatsStateCheck:
    def test_unknown_store_on_nested_order_route_returns_store_404(self, api):
        """Path existence resolves before any business rule on the nested route.

        PRD §2.7: "When a path contains multiple resource identifiers (for example, a store followed by an order), the server resolves each identifier in order and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve — `ERR_STORE_NOT_FOUND` for a store segment, then `ERR_ORDER_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_SUPPRESSION_EVENT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, or `ERR_INGREDIENT_NOT_FOUND` as appropriate — before any business rule is evaluated."
        Design: Corner/validations/existence_check_beats_state_check
        """
        fixtures.set_clock(api, fixtures.MORNING)
        response = api.create_order(
            NON_EXISTENT_UUID,
            f.order_payload("IN_STORE", []),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(response, ApiErrorId.STORE_NOT_FOUND.value)


class TestInvalidDeploymentMix:
    def test_mix_not_summing_to_one_rejected_422(self, api):
        """A deployment whose mix fractions do not sum to one is refused.

        PRD §3.8: "The two mix fractions must sum to one (within a tolerance of one part in a billion), the headcount must be at least two, and the `shift_date` must not be in the past; a violation is rejected with `ERR_INVALID_DEPLOYMENT`."
        Design: Corner/validations/invalid_deployment_mix_returns_422
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="DV")
        response = api.create_deployment(
            store["id"],
            f.deployment_payload(
                fixtures.BUSINESS_DAY,
                store["version"],
                predicted_digital_mix_pct=0.5,
                predicted_instore_mix_pct=0.6,
            ),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_DEPLOYMENT.value)


class TestMarketplaceDuplicateExternalRef:
    def test_reused_external_ref_within_channel_rejected_422(self, api):
        """An external_order_ref already seen on the channel cannot be reused.

        PRD §3.4: "Marketplace orders must additionally carry an `external_order_ref`, the marketplace-provided reference, and both fields are required if and only if the channel is `MARKETPLACE`. The referenced channel must be `active`, and the `external_order_ref` must be unique within that channel; a violation is rejected with `ERR_MARKETPLACE_REFERENCE_INVALID`."
        Design: Corner/validations/marketplace_duplicate_external_ref_returns_422
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "DR"})
        channel = fixtures.create_marketplace_channel(api)
        headers = make_marketplace_channel_headers(channel["id"])

        first = api.create_order(
            world["store_id"],
            f.order_payload(
                "MARKETPLACE",
                [f.order_line_payload(world["item_id"])],
                marketplace_channel_id=channel["id"],
                external_order_ref="DASH-1",
            ),
            headers,
        )
        validate_success(first, expected_status=201)

        duplicate = api.create_order(
            world["store_id"],
            f.order_payload(
                "MARKETPLACE",
                [f.order_line_payload(world["item_id"])],
                marketplace_channel_id=channel["id"],
                external_order_ref="DASH-1",
            ),
            headers,
        )
        validate_error(duplicate, ApiErrorId.MARKETPLACE_REFERENCE_INVALID.value)


class TestInsufficientIngredient:
    def test_required_grams_beyond_stock_rejected_409(self, api):
        """A line needing more grams than the FIFO stock holds is refused.

        PRD §3.4: "Then, for every component of every line, the grams available across the ingredient's `ACTIVE` batches must cover the requirement, with an `EXTRA` customization doubling the standard grams for that component; a shortfall is rejected with `ERR_INSUFFICIENT_INGREDIENT`."
        Design: Corner/validations/insufficient_ingredient_returns_409
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api, chicken_grams=100, store_overrides={"store_code": "II"}
        )
        response = api.create_order(
            world["store_id"],
            f.order_payload("IN_STORE", [f.order_line_payload(world["item_id"])]),
            fixtures.LINE_WORKER_HEADERS,
        )
        validate_error(response, ApiErrorId.INSUFFICIENT_INGREDIENT.value)

        orders, meta = validate_paginated(
            api.list_orders_for_store(world["store_id"], fixtures.STORE_MANAGER_HEADERS)
        )
        assert meta["total_count"] == 0, "a rejected order must not be persisted"
        assert orders == []


class TestExtraCustomizationDoublesRequirement:
    def test_extra_against_borderline_stock_fails_where_plain_passes(self, api):
        """EXTRA doubles the component's grams: 240 required against 200 on hand fails.

        PRD §3.4: "Then, for every component of every line, the grams available across the ingredient's `ACTIVE` batches must cover the requirement, with an `EXTRA` customization doubling the standard grams for that component; a shortfall is rejected with `ERR_INSUFFICIENT_INGREDIENT`."
        Design: Corner/validations/extra_customization_doubles_ingredient_requirement
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api, chicken_grams=200, store_overrides={"store_code": "EX"}
        )
        extra = api.create_order(
            world["store_id"],
            f.order_payload(
                "IN_STORE",
                [
                    f.order_line_payload(
                        world["item_id"],
                        customizations=[
                            {"ingredient_id": world["ingredient_id"], "action": "EXTRA"}
                        ],
                    )
                ],
            ),
            fixtures.LINE_WORKER_HEADERS,
        )
        validate_error(extra, ApiErrorId.INSUFFICIENT_INGREDIENT.value)

        plain = fixtures.place_order(api, world["store_id"], world["item_id"])
        assert plain["fulfillment_status"] == "ACCEPTED", (
            "the plain 120g order fits the 200g stock that the EXTRA 240g order cannot"
        )
