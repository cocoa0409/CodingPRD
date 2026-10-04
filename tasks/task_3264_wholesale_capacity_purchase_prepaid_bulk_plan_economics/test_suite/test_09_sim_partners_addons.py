"""SIM media, retail partners, shipment and the add-on window rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_inventory_payload,
    create_partner_payload,
    make_partner_headers,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    activate_addon,
    create_addon,
    create_inventory,
    create_partner,
    create_subscriber,
    current_agreement_version,
    get_addon,
    get_inventory,
    get_summary,
    next_msisdn,
    set_clock,
    setup_activated_subscriber,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_retail_partner_defaults_its_shipment_sla_days(api):
    """PRD §3.8: "an optional
    `shipment_sla_days`, defaulting to 2 days when omitted. A partner opens with its `partner_status` set to `ACTIVE`."

    Design: Corner/entities/retail_partner_create_defaults_shipment_sla_days
    """
    set_clock()
    resp = api.create_partner(
        create_partner_payload(partner_state_codes=["CA", "NV"]),
        TEST_USERS["planner_headers"],
    )
    partner = validate_success(resp, expected_status=201)
    assert partner["shipment_sla_days"] == 2
    assert partner["partner_status"] == "ACTIVE"
    assert partner["partner_state_codes"] == ["CA", "NV"]

    read_back = api.get_partner(partner["id"], TEST_USERS["planner_headers"]).json()["data"]
    assert read_back["shipment_sla_days"] == 2

    duplicate = api.create_partner(
        create_partner_payload(partner_name=partner["partner_name"]),
        TEST_USERS["planner_headers"],
    )
    validate_error(duplicate, ApiErrorId.ERR_INVALID_REQUEST)


def test_new_inventory_block_opens_available_and_unreserved(api):
    """PRD §3.8: "A block opens in `AVAILABLE` with `reserved_count` at 0, `units_shipped` at 0, and no
    `shipment_channel`."

    Design: Corner/entities/retail_partner_create_defaults_shipment_sla_days
    """
    set_clock()
    block = create_inventory(state_code="CA", sim_media_type="PHYSICAL_SIM", unit_count=6)
    assert block["inventory_status"] == "AVAILABLE"
    assert block["reserved_count"] == 0
    assert block["units_shipped"] == 0
    assert block["shipment_channel"] is None
    assert block["unit_count"] == 6


def test_partner_suspend_and_reinstate_are_reachable_in_both_directions(api):
    """PRD §3.8: "A `CapacityPlanner` reinstates a deflected partner back to `ACTIVE`, which is admitted only once the partner has no block that is `SHIPPED` with an elapsed SLA window,
    and may also suspend a partner outright from `ACTIVE` or `DEFLECTED`, landing it in the terminal `SUSPENDED`
    state."

    Design: Corner/endpoints/retail_partner_suspend_and_reinstate_is_a_business_admin_surface
    """
    set_clock()
    partner = create_partner(partner_state_codes=["CA"])

    suspended = api.suspend_partner(
        partner["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    assert suspended["partner_status"] == "SUSPENDED"
    assert suspended["version"] == partner["version"] + 1
    assert api.get_partner(partner["id"], TEST_USERS["planner_headers"]).json()["data"][
        "partner_status"
    ] == "SUSPENDED"

    # Reinstate is only reachable from DEFLECTED.
    refused = api.reinstate_partner(partner["id"], TEST_USERS["planner_headers"])
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)


def test_registering_inventory_against_a_suspended_partner_is_refused(api):
    """PRD §3.8: "Registration against a partner in `DEFLECTED` or `SUSPENDED` is
    rejected with `ERR_PARTNER_SUSPENDED` (HTTP 422)".

    Design: Corner/validations/suspended_partner_blocks_new_retail_activations
    """
    set_clock()
    partner = create_partner(partner_state_codes=["CA"])
    api.suspend_partner(partner["id"], TEST_USERS["planner_headers"])

    resp = api.create_inventory(
        create_inventory_payload(retail_partner_id=partner["id"]),
        TEST_USERS["planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PARTNER_SUSPENDED)


def test_registration_naming_a_state_the_partner_does_not_list_is_refused(api):
    """PRD §3.8: "registration naming a state the partner does not list
    in its `partner_state_codes` is rejected with `ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE` (HTTP 422)."

    Design: Corner/validations/partner_not_authorized_for_state_returns_422
    """
    set_clock()
    partner = create_partner(partner_state_codes=["NV"])

    resp = api.create_inventory(
        create_inventory_payload(state_code="CA", retail_partner_id=partner["id"]),
        TEST_USERS["planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE)


def test_a_retail_partner_is_scoped_to_its_own_inventory(api):
    """PRD §2.1: "When `X-User-Role` is
    `RetailPartner`, `X-User-ID` is the `id` of the acting `RetailPartner`; ownership checks on a SIM inventory
    block compare the block's `retail_partner_id` to `X-User-ID`."

    Design: Corner/rbac/retail_partner_is_scoped_to_its_own_inventory
    """
    set_clock()
    mine = create_partner(partner_state_codes=["CA"])
    other = create_partner(partner_name="Sierra Retail Group", partner_state_codes=["NV"])

    resp = api.create_inventory(
        create_inventory_payload(state_code="NV", retail_partner_id=other["id"]),
        make_partner_headers(mine["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    own = api.create_inventory(
        create_inventory_payload(state_code="CA", retail_partner_id=mine["id"]),
        make_partner_headers(mine["id"]),
    )
    own_data = validate_success(own, expected_status=201)
    assert own_data["inventory_status"] == "AVAILABLE"
    assert own_data["retail_partner_id"] == mine["id"]


def test_returning_shipped_media_fails_the_waiting_activation(api):
    """PRD §3.8: "because the media can no longer serve the waiting activation, that activation is set to `FAILED`, which
    cascades its subscriber into `GRACE` and its term back to `PURCHASED`".

    Design: Corner/endpoints/activation_provision_reserves_exactly_one_unit_and_stamps_the_number
    """
    set_clock()
    from test_helpers.fixtures import create_plan, get_activation, offer_plan, purchase_term, quote_term, request_activation

    agreement = setup_active_agreement()
    block = create_inventory(state_code="CA", unit_count=1)
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    subscriber = create_subscriber(state_code="CA")
    term = quote_term(subscriber["id"], plan["id"], current_agreement_version(agreement["id"]))
    purchase_term(term["id"], subscriber["id"])
    activation = request_activation(subscriber["id"], term["id"])
    api.provision_activation(activation["id"], TEST_USERS["planner_headers"])

    returned = api.return_inventory(block["id"], TEST_USERS["fulfillment_headers"]).json()["data"]
    # PRD 3.8: "returning a block that is RESERVED_PREPAID, SHIPPED, or DELIVERED moves
    # it to RETURNED, reopens reserved_count by units_shipped, and zeroes units_shipped".
    assert returned["inventory_status"] == "RETURNED"
    assert returned["units_shipped"] == 0
    assert get_activation(activation["id"])["activation_status"] == "FAILED"
    assert get_summary(agreement["id"])["allocated_data_mb"] == 0


def test_add_on_window_and_allotment_constraints(api):
    """PRD §3.8: "The window must be one of 1, 7, or
    30 days, and the daily allotment must be 0 for an international long-distance add-on and at least 1 megabyte
    for a roaming add-on; a request that violates either is rejected with `ERR_INVALID_ADDON_WINDOW` (HTTP 422)."

    Design: Corner/entities/add_on_type_and_window_constraints
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    bad_ld = api.create_addon(
        {
            "subscriber_id": subscriber_id,
            "addon_type": "INTERNATIONAL_LD",
            "addon_days": 30,
            "per_day_allotment_mb": 100,
        },
        make_subscriber_headers(subscriber_id),
    )
    validate_error(bad_ld, ApiErrorId.ERR_INVALID_ADDON_WINDOW)

    bad_roaming = api.create_addon(
        {
            "subscriber_id": subscriber_id,
            "addon_type": "ROAMING",
            "addon_days": 7,
            "per_day_allotment_mb": 0,
        },
        make_subscriber_headers(subscriber_id),
    )
    validate_error(bad_roaming, ApiErrorId.ERR_INVALID_ADDON_WINDOW)

    bad_window = api.create_addon(
        {
            "subscriber_id": subscriber_id,
            "addon_type": "ROAMING",
            "addon_days": 14,
            "per_day_allotment_mb": 500,
        },
        make_subscriber_headers(subscriber_id),
    )
    validate_error(bad_window, ApiErrorId.ERR_INVALID_ADDON_WINDOW)

    good = create_addon(subscriber_id, addon_type="ROAMING", addon_days=1,
                        per_day_allotment_mb=500)
    assert good["addon_status"] == "REQUESTED"


def test_add_on_window_half_open_adjacency_is_admitted(api):
    """PRD §3.8: "Activating an add-on whose window intersects a window
    already `ACTIVE` for that subscriber is rejected with `ERR_ADDON_WINDOW_OVERLAP` (HTTP 409), and the windows
    are compared as half-open intervals: a new add-on that starts exactly at an existing window's `end_at` is
    admitted, while one starting a second earlier is rejected."

    Design: Difficulty/boundary_precision_check/add_on_window_half_open_adjacency_boundary
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    week = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                        per_day_allotment_mb=500)
    first = activate_addon(week["id"])
    assert first["start_at"].startswith("2026-10-01T00:00:00")
    assert first["end_at"].startswith("2026-10-08T00:00:00")

    set_clock("2026-10-08T00:00:00Z")
    adjacent = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                            per_day_allotment_mb=500)
    accepted = activate_addon(adjacent["id"])
    assert accepted["start_at"].startswith("2026-10-08T00:00:00")
    assert accepted["addon_price_cents"] == 273


def test_add_on_window_one_second_early_overlaps(api):
    """PRD §2.10: "(27) add-on window
    overlap, yielding `ERR_ADDON_WINDOW_OVERLAP`."

    Design: Difficulty/boundary_precision_check/add_on_window_half_open_adjacency_boundary
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    week = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                        per_day_allotment_mb=500)
    activate_addon(week["id"])

    set_clock("2026-10-07T23:59:59Z")
    early = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                         per_day_allotment_mb=500)
    resp = api.activate_addon(early["id"], TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_ADDON_WINDOW_OVERLAP)


def test_add_on_adjacency_across_a_thirty_day_window(api):
    """PRD §3.8: "The thirty-day tier is `BASE_ROAMING_30D_CENTS` itself, 900 cents."

    Design: Difficulty/resource_temporal_overlap/roaming_addon_half_open_window_overlap_on_a_subscriber
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    month = create_addon(subscriber_id, addon_type="ROAMING", addon_days=30,
                         per_day_allotment_mb=1000)
    activated = activate_addon(month["id"])
    assert activated["addon_price_cents"] == 900
    assert activated["end_at"].startswith("2026-10-31T00:00:00")

    set_clock("2026-10-31T00:00:00Z")
    exact = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                         per_day_allotment_mb=500)
    accepted = activate_addon(exact["id"])
    assert accepted["addon_price_cents"] == 273

    set_clock("2026-10-30T00:00:00Z")
    overlapping = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                               per_day_allotment_mb=500)
    resp = api.activate_addon(overlapping["id"], TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_ADDON_WINDOW_OVERLAP)


def test_roaming_rate_card_resolves_each_tier(api):
    """PRD §3.8: "The seven-day
    tier is the base day rate multiplied by 7, then multiplied by `SHORT_TERM_MULT_NUM` and divided by
    `SHORT_TERM_MULT_DEN` — a 30 percent uplift — rounded up to the next whole cent; the one-day tier is the base
    day rate multiplied by 1 and uplifted the same way, also rounded up."

    Design: Corner/calculations/roaming_rate_card_tier_ladder
    """
    set_clock()
    setup = setup_activated_subscriber(data_allotment_mb=3000)
    subscriber_id = setup["subscriber"]["id"]

    month = activate_addon(
        create_addon(subscriber_id, addon_type="ROAMING", addon_days=30,
                     per_day_allotment_mb=1000)["id"]
    )
    assert month["addon_price_cents"] == 900
    assert month["end_at"].startswith("2026-10-31T00:00:00")

    set_clock("2026-10-31T00:00:00Z")
    week = activate_addon(
        create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                     per_day_allotment_mb=500)["id"]
    )
    assert week["addon_price_cents"] == 273

    set_clock("2026-11-07T00:00:00Z")
    day = activate_addon(
        create_addon(subscriber_id, addon_type="ROAMING", addon_days=1,
                     per_day_allotment_mb=500)["id"]
    )
    assert day["addon_price_cents"] == 39


def test_international_long_distance_add_on_takes_the_flat_price(api):
    """PRD §3.8: "An add-on of type `INTERNATIONAL_LD` ignores the ladder entirely and takes the flat
    `INTL_LD_FLAT_CENTS` price of 500 cents."

    Design: Corner/calculations/roaming_rate_card_tier_ladder
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    ld = create_addon(subscriber_id, addon_type="INTERNATIONAL_LD", addon_days=30,
                      per_day_allotment_mb=0)
    activated = activate_addon(ld["id"])
    assert activated["addon_price_cents"] == 500


def test_an_expired_add_on_cannot_gate_a_later_window(api):
    """PRD §3.8: "An add-on expires on its own at the first cycle
    roll whose `closed_at` is at or after its `end_at`, moving from `ACTIVE` to `EXPIRED`, setting its resolved
    price to 0 and leaving `end_at` unchanged."

    Design: Difficulty/resource_temporal_overlap/roaming_addon_half_open_window_overlap_on_a_subscriber
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    month = create_addon(subscriber_id, addon_type="ROAMING", addon_days=30,
                         per_day_allotment_mb=1000)
    activate_addon(month["id"])

    set_clock("2026-11-15T00:00:00Z")
    api.run_cycle(subscriber_id, TEST_USERS["planner_headers"])
    expired = get_addon(month["id"])
    assert expired["addon_status"] == "EXPIRED"
    assert expired["addon_price_cents"] == 0
    assert expired["end_at"].startswith("2026-10-31T00:00:00")


def test_inventory_read_with_unknown_id_returns_sim_inventory_not_found(api):
    """PRD §2.9: "a missing SIM inventory block
    `ERR_SIM_INVENTORY_NOT_FOUND`".

    Design: Corner/validations/fulfillment_lookup_of_an_unknown_shipment_shape_returns_not_found
    """
    set_clock()
    resp = api.get_inventory(MISSING_ID, TEST_USERS["fulfillment_headers"])
    validate_error(resp, ApiErrorId.ERR_SIM_INVENTORY_NOT_FOUND)


def test_add_on_read_with_unknown_id_returns_addon_not_found(api):
    """PRD §2.9: "a missing add-on `ERR_ADDON_NOT_FOUND`".

    Design: Corner/validations/fulfillment_lookup_of_an_unknown_shipment_shape_returns_not_found
    """
    set_clock()
    resp = api.get_addon(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_ADDON_NOT_FOUND)


def test_cycle_read_with_unknown_id_returns_cycle_not_found(api):
    """PRD §2.9: "a missing cycle
    `ERR_CYCLE_NOT_FOUND`".

    Design: Corner/validations/fulfillment_lookup_of_an_unknown_shipment_shape_returns_not_found
    """
    set_clock()
    resp = api.get_cycle(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND)