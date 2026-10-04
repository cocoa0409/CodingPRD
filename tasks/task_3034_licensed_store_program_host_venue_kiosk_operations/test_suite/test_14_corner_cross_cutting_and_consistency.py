"""Corner design — sections: cross_cutting_complexity_layers, consistency_model."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_campaign,
    create_product,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    activate_agreement,
    add_assortment_item,
    create_approved_distributor,
    create_draft_agreement,
    create_licensee,
    create_sales_report,
    create_supply_order,
    create_venue,
    drive_order_to_received,
)
from test_helpers.test_users import make_licensee_manager_headers


def test_version_increments_on_every_mutation():
    """PRD §2.4: "`version` (integer): a system-managed counter that increments
    by 1 on every mutation of the resource, including mutations caused by
    cascades triggered from other resources."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    licensee = create_licensee()
    venue = create_venue()
    draft = create_draft_agreement(licensee["id"], venue["id"])
    assert draft["version"] == 1
    submitted = validate_success(api_client.submit_license_agreement(draft["id"], ADMIN))
    assert submitted["version"] == 2
    from test_helpers.test_users import make_host_venue_manager_headers
    accepted = validate_success(api_client.accept_license_agreement(
        draft["id"], make_host_venue_manager_headers(venue["id"])))
    assert accepted["version"] == 3


def test_derived_on_hand_reconciles_after_receipt():
    """PRD §3.5: "Receipt sets each line's `quantity_received`, computes the
    order's `received_value_cents` as the sum over lines of each received
    quantity times its unit cost times the discount complement over 10000,
    rounded half-up per line, and — critically — increments the matching active
    assortment item's `on_hand` by each received quantity."

    Design: Corner/cross_cutting_complexity_layers/derived_on_hand_reconciles_after_receipt
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product()
    assortment = add_assortment_item(store_id, lic_id, product["id"], par_level=50)
    distributor = create_approved_distributor()
    order1 = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 6}])
    drive_order_to_received(
        order1, lic_id, [{"product_item_id": product["id"], "quantity_received": 6}])
    order2 = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 4}])
    drive_order_to_received(
        order2, lic_id, [{"product_item_id": product["id"], "quantity_received": 4}])
    refreshed = validate_success(api_client.get_assortment_item(
        assortment["id"], make_licensee_manager_headers(lic_id)))
    assert refreshed["on_hand"] == 10


def test_cascading_terminate_delicenses_store():
    """PRD §3.2: "In both cases every store of the agreement not already
    `DELICENSED` becomes `DELICENSED`, each delicensed store cancels its supply
    orders in `DRAFT`, `SUBMITTED`, or `APPROVED`, and its promotion campaigns
    in `PLANNED` or `ACTIVE` go directly to `CANCELLED` — the terminate path
    does not pass `ACTIVE` campaigns through `ENDED` first."

    Design: Corner/cross_cutting_complexity_layers/cascading_terminate_delicenses_store
    """
    set_clock()
    bundle = setup_operating_store()
    campaign = create_campaign(
        bundle["store"]["id"], start_date="2026-09-01", end_date="2026-09-30")
    validate_success(api_client.activate_promotion_campaign(campaign["id"], ADMIN))
    validate_success(api_client.terminate_license_agreement(bundle["agreement"]["id"], ADMIN))
    store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
    assert store["operating_status"] == "DELICENSED"
    campaign = validate_success(api_client.get_promotion_campaign(campaign["id"], ADMIN))
    assert campaign["status"] == "CANCELLED"
    resp = api_client.resume_store(store["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STORE_STATE.value)


def test_immediate_consistency_same_request_visibility():
    """PRD §3.7: "A report is born `DRAFT`; finalization computes
    `net_sales_cents` as gross minus returns minus loyalty redemptions,
    refusing with `ERR_INVALID_REQUEST` when that figure would go negative,
    stamps `finalized_at` from the logical clock, and moves the report to
    `FINALIZED`, terminal."

    Design: Corner/consistency_model/immediate_consistency_same_request_visibility
    """
    set_clock()
    bundle = setup_operating_store()
    report = create_sales_report(
        bundle["store"]["id"], bundle["licensee_id"],
        period_start_date="2026-09-01", period_end_date="2026-09-14",
        gross_sales_cents=1000, returns_cents=100, loyalty_redemption_cents=50)
    finalized = validate_success(api_client.finalize_sales_report(
        report["id"], make_licensee_manager_headers(bundle["licensee_id"])))
    assert finalized["status"] == "FINALIZED"
    assert finalized["net_sales_cents"] == 850
    reread = validate_success(api_client.get_sales_report(
        report["id"], make_licensee_manager_headers(bundle["licensee_id"])))
    assert reread["net_sales_cents"] == 850
