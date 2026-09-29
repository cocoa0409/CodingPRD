"""Machine orders: the two status dimensions and the tiered priced roll-up.

An order tracks the factory build and the money independently, and its price is
only cut when engineering releases it. These tests cover creation defaults, the
pinned four-step roll-up, the independence of the two tracks and who may push
each one.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    APP_ENGINEER,
    PLANNER,
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    assert_machine_order,
    create_machine_order_payload,
    make_customer_contact_headers,
    read_customer,
    read_order,
    read_trial,
    seed_customer,
    setup_draft_order,
    setup_engineered_order,
    setup_passed_trial,
    setup_reference_data,
)


def test_a_new_order_starts_draft_on_the_build_track_and_quoted_on_the_money_track():
    """"Initial state" is a pair of dimensions, and the read-back reports both
    together with an untouched roll-up.

    PRD: "A new order is created with `fulfillment_status` `DRAFT`,
    `commercial_status` `QUOTED` and `version` 1, with its derived commercial
    fields still empty — `discount_tier` at `NONE`, `commissioning_fee_cents` at 0
    and `order_total_cents` at 0 — and with `rework_days` and `fat_failure_count`
    both at 0, and the buying customer's `open_order_count` is re-derived."

    Design: Corner/state_machines/machine_order_initial_state_is_draft_and_quoted
    """
    env = setup_draft_order()

    data = validate_success(api_client.get_machine_order(env["order"]["id"], PLANNER))

    assert data["fulfillment_status"] == "DRAFT"
    assert data["commercial_status"] == "QUOTED"
    assert data["order_total_cents"] == 0
    assert data["discount_tier"] == "NONE"
    assert_machine_order(data)


def test_an_order_without_a_negotiated_equipment_price_is_malformed():
    """The equipment price has no default, so its absence is a shape failure
    raised before the trial reference is even considered and no order is stored.

    PRD: "The creating payload names the `customer_id` buying the machine, the
    `machine_model_id` being configured, the `product_trial_id` the order is
    engineered from, and the negotiated `equipment_price_cents` of at least 0 —
    which may legitimately differ from the model's catalog `base_price_cents`."

    Design: Corner/entities/machine_order_create_missing_equipment_price_returns_invalid_request
    """
    env = setup_passed_trial()
    payload = {
        "customer_id": env["customer"]["id"],
        "machine_model_id": env["model"]["id"],
        "product_trial_id": env["trial"]["id"],
    }

    response = api_client.create_machine_order(payload, APP_ENGINEER)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _, meta = validate_paginated(
        api_client.list_machine_orders(PLANNER, params={"customer_id": env["customer"]["id"]})
    )
    assert meta["total_count"] == 0


def test_omitting_the_optional_price_leg_and_guarantee_basis_applies_the_declared_defaults():
    """Both optional inputs carry declared defaults, so the change-parts leg lands
    at zero and the guarantee basis is pinned to nameplate rather than left null.

    PRD: "Two further inputs are optional: `change_parts_price_cents`, the price of
    change parts sold inside the original order, which defaults to 0 and may not be
    negative; and `guarantee_basis`, which defaults to `NAMEPLATE` and may instead
    be `PRODUCT_ADJUSTED`."

    Design: Corner/entities/machine_order_change_parts_and_guarantee_basis_defaults_applied
    """
    env = setup_passed_trial()
    payload = {
        "customer_id": env["customer"]["id"],
        "machine_model_id": env["model"]["id"],
        "product_trial_id": env["trial"]["id"],
        "equipment_price_cents": 40_000_000,
    }

    data = validate_success(api_client.create_machine_order(payload, APP_ENGINEER), 201)

    assert data["change_parts_price_cents"] == 0
    assert data["guarantee_basis"] == "NAMEPLATE"
    assert data["fulfillment_status"] == "DRAFT"
    assert data["commercial_status"] == "QUOTED"
    assert data["rework_days"] == 0
    assert data["fat_failure_count"] == 0


def test_a_suspended_plant_cannot_receive_a_new_order_even_after_a_passing_trial():
    """The customer's status is read at order-create time, so a suspension that
    lands after a successful trial still blocks the sale and leaves the passed
    trial intact.

    PRD: "A suspended customer cannot receive a new order
    (`ERR_CUSTOMER_SUSPENDED`)."

    Design: Corner/validations/machine_order_create_for_suspended_customer_returns_409
    """
    env = setup_passed_trial()
    validate_success(api_client.suspend_customer(env["customer"]["id"], ADMIN))

    response = api_client.create_machine_order(
        create_machine_order_payload(
            env["customer"]["id"], env["model"]["id"], env["trial"]["id"]
        ),
        APP_ENGINEER,
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value, 409)
    customer = read_customer(env["customer"]["id"])
    assert customer["status"] == "SUSPENDED"
    assert customer["open_order_count"] == 0
    assert read_trial(env["trial"]["id"])["status"] == "PASSED"


def test_the_roll_up_keys_the_discount_tier_on_the_pre_fee_subtotal():
    """A 73,000,000 subtotal is a T1 order, and the 5.00 percent fee pushes the
    total past the T2 floor without dragging the tier with it — keying the tier
    off the total instead would report T2 and a smaller fee.

    PRD: "**Step two** selects the `discount_tier` from that pre-fee subtotal
    alone: a subtotal of at least 150,000,000 cents is `T3`; a subtotal of at least
    75,000,000 cents but below 150,000,000 is `T2`; a subtotal of at least
    25,000,000 cents but below 75,000,000 is `T1`; anything below 25,000,000 cents
    is `NONE`."

    Design: Difficulty/combinatorial_formula/order_total_rollup_tier_keyed_on_pre_fee_subtotal
    """
    env = setup_draft_order(
        equipment_price_cents=70_000_000, change_parts_price_cents=3_000_000
    )

    data = validate_success(api_client.engineer_machine_order(env["order"]["id"], APP_ENGINEER))

    assert data["discount_tier"] == "T1"
    assert data["commissioning_fee_cents"] == 3_650_000
    assert data["order_total_cents"] == 76_650_000
    assert data["fulfillment_status"] == "ENGINEERED"
    assert data["commercial_status"] == "QUOTED"


def test_the_priced_roll_up_is_persisted_and_survives_a_separate_order_read():
    """The four steps run once at engineering and their results are stored, so a
    later read reports the same fee and total rather than recomputing a tier from
    the fee-inclusive figure.

    PRD: "**Step three** reads a commissioning percentage off the tier — 6.00
    percent for `NONE`, 5.00 percent for `T1`, 4.00 percent for `T2` and 3.00
    percent for `T3` — and sets `commissioning_fee_cents` to the pre-fee subtotal
    multiplied by that percentage divided by one hundred, rounded half up to a whole
    number of cents in that single multiplication."

    Design: Difficulty/combinatorial_formula/order_total_rollup_tier_keyed_on_pre_fee_subtotal
    """
    env = setup_engineered_order(
        equipment_price_cents=70_000_000, change_parts_price_cents=3_000_000
    )

    data = validate_success(api_client.get_machine_order(env["order"]["id"], PLANNER))

    assert data["discount_tier"] == "T1"
    assert data["commissioning_fee_cents"] == 3_650_000
    assert data["order_total_cents"] == 76_650_000
    assert data["order_total_cents"] > 75_000_000


def test_a_subtotal_below_the_first_tier_floor_prices_at_the_none_band():
    """A 24,000,000 subtotal sits below the T1 floor, so the 6.00 percent
    no-tier fee applies even though the resulting total climbs above that floor.

    PRD: "Deriving the tier from `order_total_cents` — which already contains the
    fee — is incorrect and will produce the wrong tier for subtotals near a
    boundary."

    Design: Corner/endpoints/machine_order_read_back_shows_none_tier_rollup
    """
    env = setup_reference_data(
        model={
            "model_code": "CP-200",
            "machine_family": "CAPPER",
            "nameplate_rate_cpm": 400,
            "guarantee_efficiency_pct": 92.00,
            "base_price_cents": 19_000_000,
            "min_container_diameter_mm": 40,
            "max_container_diameter_mm": 90,
        }
    )
    env = setup_engineered_order(
        setup_passed_trial(
            env,
            measured_rate_cpm=380,
            product_name="Cider Cap 28",
            container_family="PET_ROUND",
            container_diameter_mm=60,
        ),
        equipment_price_cents=20_000_000,
        change_parts_price_cents=4_000_000,
    )

    data = validate_success(api_client.get_machine_order(env["order"]["id"], SERVICE_MANAGER))

    assert data["discount_tier"] == "NONE"
    assert data["commissioning_fee_cents"] == 1_440_000
    assert data["order_total_cents"] == 25_440_000
    assert data["fulfillment_status"] == "ENGINEERED"


def test_releasing_an_already_engineered_order_a_second_time_is_refused():
    """Engineering is not idempotent, so the refused replay leaves the version and
    the customer's open-order tally exactly where the first release left them.

    PRD: "On success, the priced roll-up is computed, the buying customer's
    `open_order_count` is re-derived, and the order's `version` increments by 1."

    Design: Corner/state_machines/machine_order_engineer_twice_returns_invalid_order_state
    """
    env = setup_engineered_order()
    before = read_order(env["order"]["id"])

    response = api_client.engineer_machine_order(env["order"]["id"], APP_ENGINEER)

    validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE.value, 409)
    after = read_order(env["order"]["id"])
    assert after["fulfillment_status"] == "ENGINEERED"
    assert after["version"] == before["version"]
    assert read_customer(env["customer"]["id"])["open_order_count"] == 1


def test_booking_the_purchase_order_moves_only_the_money_track():
    """The money track advances independently: the build track stays where
    engineering left it and the priced roll-up is not recut.

    PRD: "Each of these four transitions increments the order's `version` by 1 and
    touches nothing on the fulfillment track."

    Design: Corner/state_machines/commercial_advance_leaves_fulfillment_dimension_untouched
    """
    env = setup_engineered_order(
        equipment_price_cents=70_000_000, change_parts_price_cents=3_000_000
    )
    total_after_engineer = env["order"]["order_total_cents"]

    data = validate_success(
        api_client.commercial_advance_machine_order(env["order"]["id"], "PO_RECEIVED", ADMIN)
    )

    assert data["commercial_status"] == "PO_RECEIVED"
    assert data["fulfillment_status"] == "ENGINEERED"
    assert data["order_total_cents"] == total_after_engineer
    assert data["rework_days"] == 0


def test_every_order_write_advances_the_version_token_by_exactly_one():
    """The version starts at one on create and each transition raises it by one,
    including a money-track move that never touches the build track.

    PRD: "Almost every entity additionally carries `updated_at`, refreshed to the
    current logical-clock instant on every mutation of that row, and `version`, an
    integer that begins at 1 when the row is created and increments by exactly 1 on
    every mutation of the row."

    Design: Corner/cross_cutting_complexity_layers/machine_order_version_increments_on_every_write
    """
    env = setup_draft_order(
        equipment_price_cents=70_000_000, change_parts_price_cents=3_000_000
    )
    assert env["order"]["version"] == 1
    engineered = validate_success(
        api_client.engineer_machine_order(env["order"]["id"], APP_ENGINEER)
    )

    data = validate_success(
        api_client.commercial_advance_machine_order(env["order"]["id"], "PO_RECEIVED", ADMIN)
    )

    assert data["version"] == engineered["version"] + 1
    assert data["fulfillment_status"] == "ENGINEERED"
    assert data["commercial_status"] == "PO_RECEIVED"
    assert data["order_total_cents"] == 76_650_000


def test_shipping_an_order_that_has_not_passed_its_factory_test_is_refused():
    """Shipment closes out the factory phase and its only legal source is a passed
    factory test, so a freshly engineered order cannot leave and no installation
    appears.

    PRD: "Shipment is a `ProductionPlanner` action and closes out the factory
    phase, advancing `fulfillment_status` from `FAT_PASSED` to `SHIPPED` and
    incrementing the order's `version` by 1."

    Design: Corner/endpoints/machine_order_ship_from_engineered_returns_invalid_order_state
    """
    env = setup_engineered_order()

    response = api_client.ship_machine_order(env["order"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE.value, 409)
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ENGINEERED"
    _, meta = validate_paginated(
        api_client.list_installed_machines(
            SERVICE_MANAGER, params={"machine_order_id": env["order"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_order_read_with_unknown_id_reports_the_order_not_found_code():
    """The order read reports the order's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/machine_order_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_machine_order(
        "33333333-3333-4333-8333-333333333333", PLANNER
    )

    validate_error(response, ApiErrorId.ERR_MACHINE_ORDER_NOT_FOUND.value, 404)


def test_a_plant_contact_cannot_read_another_plants_order():
    """The same role on the same endpoint succeeds or fails purely on whether the
    caller is the buying plant, and the outsider is told it is not the owner rather
    than that the order is missing.

    PRD: "Orders can be listed with optional `customer_id`, `machine_model_id`,
    `product_trial_id`, `fulfillment_status` and `commercial_status` filters; a
    single order read exposes both status dimensions, the priced roll-up and the
    current `version`, and when the reader is a `CustomerContact` it must be their
    own order."

    Design: Corner/rbac/customer_contact_reading_another_customers_order_returns_403_not_owner
    """
    env = setup_engineered_order()
    other = seed_customer(
        legal_name="Contoso Foods", region_code="EU", product_variation_pct=6.00
    )

    response = api_client.get_machine_order(
        env["order"]["id"], make_customer_contact_headers(other["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    owner_view = validate_success(
        api_client.get_machine_order(
            env["order"]["id"], make_customer_contact_headers(env["customer"]["id"])
        )
    )
    assert owner_view["id"] == env["order"]["id"]


def test_the_service_manager_cannot_push_an_order_through_engineering():
    """Aftermarket ownership does not extend to the engineering gate, and the
    denial leaves the order untouched at its first version.

    PRD: "An `ApplicationEngineer` converts a trial into a build-to-order
    commitment."

    Design: Corner/rbac/service_manager_cannot_engineer_machine_order
    """
    env = setup_draft_order()

    response = api_client.engineer_machine_order(env["order"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)
    after = read_order(env["order"]["id"])
    assert after["fulfillment_status"] == "DRAFT"
    assert after["version"] == 1
