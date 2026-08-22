"""The two stale-version guards protecting shared inventory and pricing."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_entitlement,
    add_rate_card_line,
    asset_version,
    book_asset,
    create_contract,
    create_rate_card,
    create_sponsor,
    publish_rate_card,
    read_contract,
    read_entitlement,
    read_inventory_asset,
    read_property,
    setup_contract_scenario,
    setup_property_estate,
    submit_contract,
    validate_error,
    validate_success,
)

ACTIVATION = TEST_USERS["activation_headers"]
APPROVER = TEST_USERS["approver_headers"]


def test_stale_asset_version_is_refused_even_when_capacity_remains(api):
    """PRD §2.7: "Scheduling an occupation of an inventory asset — the create
    operation mounted at `POST /asset-bookings` — requires
    `expected_inventory_asset_version` in the request body."
    PRD §2.7: "If that number differs from the asset's current `version`, the
    request is refused with `ERR_ASSET_VERSION_STALE` (412) and nothing is
    written. This holds even when the residual capacity would still admit the
    requested units, because a stale version means the caller's picture of
    `reserved_units_total`, of the surrounding buffer neighbourhood and of the
    asset's occupied windows predates an earlier accepted booking, cancellation,
    delivery or preemption on that same asset."

    Design: Corner/cross_cutting_layers/booking_create_with_stale_asset_version_returns_412
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    asset_id = scenario["asset"]["id"]
    stale_version = asset_version(asset_id)

    book_asset(
        scenario["entitlement"]["id"], asset_id,
        expected_inventory_asset_version=stale_version,
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=2,
    )

    second_payload = {
        "entitlement_id": scenario["entitlement"]["id"],
        "inventory_asset_id": asset_id,
        "window_start": "2026-09-11T18:00:00Z",
        "window_end": "2026-09-11T21:00:00Z",
        "units_booked": 2,
        "expected_inventory_asset_version": stale_version,
    }
    refused = api.create_asset_booking(second_payload, ACTIVATION)
    validate_error(refused, ApiErrorId.ERR_ASSET_VERSION_STALE.value)
    assert refused.status_code == 412, (
        "2 more units would still fit under capacity 6, yet the stale version "
        "alone refuses the write"
    )

    mid = read_inventory_asset(asset_id)
    assert mid["reserved_units_total"] == 2

    second_payload["expected_inventory_asset_version"] = mid["version"]
    accepted = validate_success(
        api.create_asset_booking(second_payload, ACTIVATION), 201
    )
    assert accepted["status"] == "SCHEDULED"
    assert read_inventory_asset(asset_id)["reserved_units_total"] == 4


def test_stale_property_version_is_refused_and_the_retry_pins_the_new_card(api):
    """PRD §2.7: "Countersigning a contract — the action mounted at
    `POST /contracts/{id}/countersign` — requires `expected_property_version` in
    the request body, again mandatory and again carrying the `version` of the
    owning `Property` as the approver last observed it."
    PRD §2.7: "If it differs from the property's current `version`, the
    countersign is refused with `ERR_PROPERTY_VERSION_STALE` (412). A property's
    version advances whenever a newer rate card is published — which supersedes
    the very card this countersign would pin — and whenever another countersign,
    termination, close or delivery moves `committed_gross_value_cents` or
    `delivered_media_value_cents`, so a stale property version means the approver
    is pricing the deal against a superseded card or against an inventory position
    that has already been sold into."

    Design: Corner/cross_cutting_layers/countersign_with_stale_property_version_returns_412
    """
    estate = setup_property_estate(
        line_specs=[
            {
                "asset_class": "DIGITAL_BOARD",
                "base_unit_price_cents": 250_000,
                "tier_breaks": [],
                "exclusivity_multiplier": 1.00,
            }
        ],
        asset_specs=[
            {
                "name": "North LED Ribbon",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 6,
                "changeover_buffer_minutes": 0,
            }
        ],
        rate_card_label="Card A",
    )
    prop = estate["property"]
    sponsor = create_sponsor()
    contract = create_contract(
        sponsor["id"], prop["id"], exclusivity_scope="NONE"
    )
    entitlement = add_entitlement(
        contract["id"], estate["assets"][0]["id"],
        clause_ref="4.2(a)", promised_units=10,
    )
    submit_contract(contract["id"])

    stale_version = read_property(prop["id"])["version"]

    card_b = create_rate_card(prop["id"], label="Card B")
    add_rate_card_line(
        card_b["id"],
        asset_class="DIGITAL_BOARD",
        base_unit_price_cents=300_000,
        # Both cards price the class off their base alone, so the money below
        # can only come out right if Card B -- and not the superseded Card A --
        # was the card the countersign pinned.
        tier_breaks=[],
        exclusivity_multiplier=1.00,
    )
    publish_rate_card(card_b["id"])

    refused = api.countersign_contract(
        contract["id"], {"expected_property_version": stale_version}, APPROVER
    )
    validate_error(refused, ApiErrorId.ERR_PROPERTY_VERSION_STALE.value)
    assert refused.status_code == 412

    fresh_version = read_property(prop["id"])["version"]
    accepted = validate_success(
        api.countersign_contract(
            contract["id"],
            {"expected_property_version": fresh_version},
            APPROVER,
        )
    )
    assert accepted["rate_card_id"] == card_b["id"], (
        "the countersign pins the newly published card, not the superseded one"
    )
    assert accepted["cash_value_cents"] == 3_312_000
    assert read_entitlement(entitlement["id"])["unit_value_cents"] == 360_000
    assert read_contract(contract["id"])["total_recognized_value_cents"] == 3_312_000
