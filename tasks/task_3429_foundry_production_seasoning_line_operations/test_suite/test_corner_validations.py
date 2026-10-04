"""Corner queue (validations, plant-level): auth, pricing floors, product
discontinuation gates, sand-permit reading rejection, segregation of duties,
and the peak-window allocation freeze."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_breach,
    advance_clock,
    cancel_allocation,
    certify_melt,
    charge_melt,
    confirm_allocation,
    create_allocation,
    create_permit,
    create_product,
    create_product_payload,
    discontinue_product,
    get_allocation,
    get_inventory_record,
    get_melt,
    get_permit,
    get_product,
    make_foundry_manager_headers,
    make_quality_inspector_headers,
    qa_release,
    record_chemistry,
    record_reading,
    setup_baking_batch,
    setup_charging_melt,
    setup_confirmed_allocation,
    validate_error,
    validate_paginated,
)

_FM = TEST_USERS["foundry_manager_headers"]
_QI = TEST_USERS["quality_inspector_headers"]


def test_request_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role value
    outside the declared role set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    The rejection precedes any body evaluation and persists nothing.

    Design: Corner/validations/request_missing_auth_header_returns_unauthenticated
    """
    resp = api.create_product(create_product_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    _, meta = validate_paginated(api.list_products(_FM))
    assert meta["total_count"] == 0


def test_wholesale_below_brand_floor_rejected(api):
    """PRD §3.1: "The `wholesale_price_cents` charged to retail chains must be at
    least the import landed cost multiplied by 1.15 and rounded half-up — equality
    with that rounded floor is allowed — and a wholesale price below it is rejected
    with `ERR_PRICE_BELOW_BRAND_FLOOR` (HTTP 422)."
    Floor for import 2000 is round_half_up(2300.0) == 2300: 2300 accepted, 2299
    rejected.

    Design: Corner/validations/wholesale_below_brand_floor_rejected
    """
    product = create_product(sku_code="L8SK3", wholesale_price_cents=2300)
    assert product["wholesale_price_cents"] == 2300
    resp = api.create_product(
        create_product_payload(sku_code="L9SK3", wholesale_price_cents=2299), _FM)
    validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_BRAND_FLOOR)


def test_outlet_sale_below_floor_rejected(api):
    """PRD §3.8: "at the factory outlet the floor is the product's `msrp_cents`
    multiplied by 0.55 and rounded half-up, while at the museum store the floor is
    the full `msrp_cents`; a price below the applicable floor — equality is
    allowed — is rejected with `ERR_OUTLET_PRICE_BELOW_FLOOR` (HTTP 422)."
    Floor is round_half_up(4000 * 0.55) == 2200: 2199 fails the floor; exactly
    2200 passes it and fails only the later inventory check on empty stock.

    Design: Corner/validations/outlet_sale_below_floor_rejected
    """
    product = create_product()
    low = api.create_outlet_sale(
        {"product_id": product["id"], "channel": "FACTORY_OUTLET", "qty": 1,
         "unit_price_cents": 2199}, TEST_USERS["outlet_manager_headers"])
    validate_error(low, ApiErrorId.ERR_OUTLET_PRICE_BELOW_FLOOR)
    at_floor = api.create_outlet_sale(
        {"product_id": product["id"], "channel": "FACTORY_OUTLET", "qty": 1,
         "unit_price_cents": 2200}, TEST_USERS["outlet_manager_headers"])
    validate_error(at_floor, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_product_discontinue_blocks_new_order_rejected(api):
    """PRD §3.1: "Discontinuation blocks four operations with
    `ERR_PRODUCT_DISCONTINUED` (HTTP 422): creating a production order for the
    product, creating a retail allocation against its inventory, confirming a
    proposed allocation, and recording an outlet sale."

    Design: Corner/validations/product_discontinue_blocks_new_order_rejected
    """
    product = create_product()
    discontinue_product(product["id"])
    assert get_product(product["id"])["status"] == "DISCONTINUED"
    resp = api.create_production_order(
        {"product_id": product["id"], "planned_quantity": 10,
         "scheduled_week": 40}, _FM)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)


def test_reading_to_sand_permit_rejected(api):
    """PRD §3.7: "Emissions readings are taken against `AIR_EMISSIONS` and
    `DUST_CONTROL` permits only; posting a reading to a `SAND_RECLAMATION`
    permit — which is rate-driven through mold reclamation instead — is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/reading_to_sand_permit_rejected
    """
    permit = create_permit("SAND_RECLAMATION", limit_value=0.90)
    resp = api.record_emissions_reading(
        permit["id"], {"reading_value": 0.5, "source": "SAND_PLANT"},
        TEST_USERS["environmental_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert get_permit(permit["id"])["status"] == "ACTIVE"
    _, meta = validate_paginated(api.list_emissions_readings(
        permit["id"], TEST_USERS["environmental_officer_headers"]))
    assert meta["total_count"] == 0


def test_certify_chemistry_same_user_segregation_rejected(api):
    """PRD §2.1: "chemistry certification requires the caller to differ from the
    batch's `chemistry_recorded_by`"
    PRD §2.1: "A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."
    An inspector call carrying the recording operator's X-User-ID (op-1) is
    rejected; a different inspector (qi-1) certifies.

    Design: Corner/validations/certify_chemistry_same_user_segregation_rejected
    """
    ctx = setup_charging_melt()
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    record_chemistry(batch_id)
    resp = api.certify_chemistry(batch_id, {"decision": "CERTIFY"},
                                 make_quality_inspector_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_melt(batch_id)["chemistry_recorded_by"] == "op-1"
    melt = certify_melt(batch_id, decision="CERTIFY")
    assert melt["state"] == "CERTIFIED"
    assert melt["certified_by"] == "qi-1"


def test_qa_release_same_user_segregation_rejected(api):
    """PRD §3.6: "Quality release belongs to the `QualityInspector`, whose
    `X-User-ID` must differ from `bake_recorded_by`, else
    `ERR_SEGREGATION_OF_DUTIES`."
    The bake starter (sl-1) may not release their own batch even with a passing
    cure profile; a different inspector releases successfully.

    Design: Corner/validations/qa_release_same_user_segregation_rejected
    """
    ctx = setup_baking_batch(num_units=1, order_overrides={"planned_quantity": 5})
    batch_id = ctx["seasoning_batch"]["id"]
    resp = api.qa_release_seasoning_batch(
        batch_id, {"bake_duration_min": 60, "food_safety_verified": True,
                   "decision": "RELEASE"}, make_quality_inspector_headers("sl-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    batch = qa_release(batch_id, bake_duration_min=60, food_safety_verified=True,
                       decision="RELEASE")
    assert batch["state"] == "RELEASED"
    assert batch["released_by"] == "qi-1"


def test_acknowledge_breach_same_user_segregation_rejected(api):
    """PRD §3.7: "A `FoundryManager` acknowledges the breach, moving the permit
    from `BREACH` to `REMEDIATION`, and the acknowledging manager's `X-User-ID`
    must differ from `last_breach_reading_recorded_by`, otherwise the call is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."
    The breaching officer (eo-1) may not acknowledge; manager fm-1 may.

    Design: Corner/validations/acknowledge_breach_same_user_segregation_rejected
    """
    permit = create_permit("AIR_EMISSIONS", limit_value=100.0)
    record_reading(permit["id"], 120.0)
    record_reading(permit["id"], 130.0)
    assert get_permit(permit["id"])["status"] == "BREACH"
    resp = api.acknowledge_breach(permit["id"],
                                  make_foundry_manager_headers("eo-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    permit = acknowledge_breach(permit["id"])  # fm-1
    assert permit["status"] == "REMEDIATION"


def test_allocation_freeze_window_blocks_cancel_at_boundary(api):
    """PRD §3.8: "when the ISO week of the `ship_week` falls within the product's
    inclusive window from `peak_season_start_week` to `peak_season_end_week`, the
    cancellation is permitted only while the current logical date is strictly
    before the date 42 days before the `ship_week` — the freeze boundary itself is
    already frozen — and otherwise the cancel is rejected with
    `ERR_ALLOCATION_FROZEN` (HTTP 409)"
    ship_week 2026-11-16 (ISO week 47, inside the 44-52 peak window) freezes on
    2026-10-05: a cancel on 2026-10-04 succeeds; the same cancel on the boundary
    date fails.

    Design: Corner/validations/allocation_freeze_window_blocks_cancel_at_boundary
    """
    ctx = setup_confirmed_allocation(num_units=3, allocated_qty=2,
                                     ship_week="2026-11-16")
    record_id = ctx["inventory_record"]["id"]
    a1 = ctx["allocation"]
    a2 = create_allocation(record_id, allocated_qty=1, ship_week="2026-11-16",
                           channel="ECOMMERCE")
    confirm_allocation(a2["id"])
    advance_clock("2026-10-04T00:00:00Z")
    cancel_allocation(a2["id"])
    assert get_allocation(a2["id"])["status"] == "CANCELLED"
    advance_clock("2026-10-05T00:00:00Z")
    resp = api.cancel_retail_allocation(a1["id"],
                                        TEST_USERS["retail_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_FROZEN)
    assert get_allocation(a1["id"])["status"] == "CONFIRMED"
    record = get_inventory_record(record_id)
    assert record["reserved_units"] == 2
    assert record["on_hand_units"] == 3
