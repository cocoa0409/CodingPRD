"""Validation corners: one refusal code per rule, plus the pairs that are ordered.

Every test drives exactly one gate on the refusal ladder and then shows that the
rejected request left no trace behind it.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    NON_EXISTENT_UUID,
    constants as C,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_second_product_presenting_a_taken_sku_is_a_conflict(api):
    """The item number is unique system-wide, so the second product is 409 and unwritten.

    PRD 3.4: "A product record carries a `sku` — the worldwide item number, between 3
    and 32 characters, which must be unique across every product in the system; a
    second product presenting an existing `sku` is rejected with `ERR_DUPLICATE_SKU`
    (HTTP 409)."

    Design: Corner/validations/corner_duplicate_sku_returns_conflict
    """
    first = fx.create_product(
        api,
        sku="SKU-DUP-001",
        name="Ground Coffee 2lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=899,
    )

    validate_error(
        api.create_product(
            factories.product_payload(
                sku="SKU-DUP-001",
                name="Beach Towel",
                category="GENERAL_MERCHANDISE",
                unit_cost_cents=1299,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        "ERR_DUPLICATE_SKU",
        409,
    )

    _rows, meta = validate_paginated(
        api.list_products({"category": "GENERAL_MERCHANDISE"}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 0

    read_first = validate_success(api.get_product(first["id"], HEADERS_ASSORTMENT_PLANNER))
    assert read_first["name"] == "Ground Coffee 2lb"
    assert read_first["unit_cost_cents"] == 899


def test_the_same_markup_is_legal_at_an_exchange_and_forbidden_at_a_commissary(api):
    """300 basis points registers fine on the exchange and is refused on the commissary.

    PRD 3.1: "The no-markup grocery rule is absolute and it is enforced at
    registration time. A store whose `channel` is `COMMISSARY` must have
    `exchange_markup_bp` of 0, whether by omitting the field or by supplying zero
    explicitly; supplying any positive markup for a commissary is rejected with
    `ERR_MARKUP_FORBIDDEN_IN_COMMISSARY` (HTTP 422)."

    Design: Corner/validations/corner_markup_on_commissary_store_returns_forbidden
    """
    exchange = fx.create_store(
        api,
        name="Camp Zama Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        exchange_markup_bp=300,
    )
    assert exchange["exchange_markup_bp"] == 300

    validate_error(
        api.create_store(
            factories.store_payload(
                name="Camp Zama Commissary",
                channel="COMMISSARY",
                region="CONUS",
                surcharge_rate_bp=500,
                exchange_markup_bp=300,
            ),
            HEADERS_FUND_CONTROLLER,
        ),
        "ERR_MARKUP_FORBIDDEN_IN_COMMISSARY",
        422,
    )

    _rows, meta = validate_paginated(
        api.list_stores({"channel": "COMMISSARY"}, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0


def test_a_vendor_is_required_only_once_the_supply_mode_is_direct_store_delivery(api):
    """The same bare payload passes as WAREHOUSE and fails as DSD.

    PRD 3.4: "When `supply_mode` is `DSD`, `vendor_name` must be present."
    PRD 3.4: "The direct-store-delivery terms are a tightly coupled group of four
    fields, and the system refuses any inconsistent combination with
    `ERR_VENDOR_REQUIRED_FOR_DSD` (HTTP 422)."
    PRD 3.4: "When `supply_mode` is `WAREHOUSE`, `vendor_name` must be null and
    `promo_allowance_bp` must be 0 — a warehouse line has no vendor to offer an
    allowance."

    Design: Corner/validations/corner_dsd_assortment_without_vendor_name_returns_error
    """
    store = fx.create_store(
        api,
        name="Yokota Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=500,
        shelf_block_capacity_facings=24,
    )
    product = fx.create_product(
        api,
        sku="SKU-DSD-500",
        name="Sports Drink 12pk",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=500,
    )
    warehouse = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="U1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    assert warehouse["supply_mode"] == "WAREHOUSE"
    assert warehouse["vendor_name"] is None
    assert warehouse["promo_allowance_bp"] == 0
    store_before = fx.read_store(api, store["id"])

    validate_error(
        api.create_assortment(
            factories.assortment_payload(
                store_id=store["id"],
                product_id=product["id"],
                expected_store_version=store_before["version"],
                shelf_block="U2",
                facings=4,
                supply_mode="DSD",
                effective_from=C.AUG_01,
                effective_to=C.AUG_31,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        "ERR_VENDOR_REQUIRED_FOR_DSD",
        422,
    )

    _rows, meta = validate_paginated(
        api.list_assortments({"shelf_block": "U2"}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 0
    assert fx.read_store(api, store["id"])["version"] == store_before["version"]


def test_declaring_any_collected_tax_at_tender_is_refused(api):
    """Resale sales are tax-free, so a declared 25 cents of tax is a 422.

    PRD 3.6: "And `collected_tax_cents`, when supplied at all, must be exactly 0, or
    the attempt is refused with `ERR_TAX_COLLECTION_FORBIDDEN` (HTTP 422)."
    PRD 3.5: "`tax_cents` is always 0 — commissary and exchange sales are tax-free and
    there is no configuration in which they are not."

    Design: Corner/validations/corner_tender_with_nonzero_collected_tax_returns_forbidden
    """
    store = fx.create_store(
        api,
        name="Fort Riley Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api, sku="SKU-TAX-500", name="Rice 10lb", category="GROCERY_STAPLE", unit_cost_cents=500
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="V1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT H Brannigan", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 1)

    validate_error(
        api.tender_sale(sale["id"], factories.tender_payload(25), HEADERS_STORE_CASHIER),
        "ERR_TAX_COLLECTION_FORBIDDEN",
        422,
    )

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["tender_state"] == "OPEN"
    assert read_sale["tax_cents"] == 0
    assert read_sale["total_due_cents"] == 525

    assert fx.read_store(api, store["id"])["surcharge_fund_balance_cents"] == 0
    _entries, meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0


def test_the_spend_cap_is_tested_against_the_total_due_including_surcharge(api):
    """1200 of merchandise plus 60 of surcharge breaches a 1000-cent cap at tender.

    PRD 3.6: "The visit's `total_due_cents` must be no greater than the acting
    delegation's `per_sale_spend_cap_cents`, or the attempt is refused with
    `ERR_DELEGATION_SPEND_CAP_EXCEEDED` (HTTP 402) — a total exactly equal to the cap
    passes."
    PRD 3.3: "The fiscal ceiling is `per_sale_spend_cap_cents`, which must be at least
    1 and which limits the total a single visit rung under this delegation may reach —
    §3.6 explains where that ceiling bites."

    Design: Corner/validations/corner_tender_above_delegation_spend_cap_returns_payment_required
    """
    store = fx.create_store(
        api,
        name="Fort Bliss Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-CAP-600",
        name="Detergent 100oz",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=600,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="W1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    sponsor = fx.create_patron(api, full_name="MSG (Ret) I Nakagawa", id_card_class="RETIREE")
    delegate = fx.create_patron(api, full_name="SPC J Ferreira", id_card_class="ACTIVE_DUTY")
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=1000,
        expected_delegate_patron_version=delegate["version"],
    )
    sale = fx.open_sale(api, store["id"], delegate["id"], acting_delegation_id=delegation["id"])
    fx.add_line(api, sale["id"], product["id"], 2)

    validate_error(
        api.tender_sale(sale["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        "ERR_DELEGATION_SPEND_CAP_EXCEEDED",
        402,
    )

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["merchandise_cents"] == 1200
    assert read_sale["surcharge_total_cents"] == 60
    assert read_sale["total_due_cents"] == 1260
    assert read_sale["tender_state"] == "OPEN"
    assert read_sale["compliance_state"] == "CLEARED"

    assert fx.read_delegation(api, delegation["id"])["status"] == "ACTIVE"
    assert fx.read_store(api, store["id"])["surcharge_fund_balance_cents"] == 0


def test_an_empty_basket_cannot_be_tendered_and_stays_open(api):
    """line_count 0 is refused with 409 and the visit remains re-tenderable.

    PRD 3.6: "The visit must have at least one line — `line_count` of at least 1 — or
    it is refused with `ERR_SALE_HAS_NO_LINES` (HTTP 409)."
    PRD 3.5: "A newly opened visit sits at `tender_state` of `OPEN` on the money axis
    and `compliance_state` of `CLEARED` on the compliance axis, with `line_count` of 0
    and every money figure — `merchandise_cents`, `markup_total_cents`,
    `surcharge_total_cents`, `tax_cents`, `total_due_cents`,
    `provisional_allowance_cents` and `subsidized_shipping_cents` — at 0."

    Design: Corner/validations/corner_tender_of_empty_sale_returns_sale_has_no_lines
    """
    store = fx.create_store(
        api,
        name="Fort Carson Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(api, full_name="PFC K Salvatierra", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])

    validate_error(
        api.tender_sale(sale["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        "ERR_SALE_HAS_NO_LINES",
        409,
    )

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["line_count"] == 0
    assert read_sale["tender_state"] == "OPEN"
    assert read_sale["total_due_cents"] == 0

    read_store = fx.read_store(api, store["id"])
    assert read_store["period_close_index"] == 0
    assert read_store["surcharge_fund_balance_cents"] == 0


def test_a_basket_flagged_by_a_manual_strike_cannot_be_tendered(api):
    """The strike path flags the basket with no delegation in sight, so tender is 409.

    PRD 3.6: "The visit's `compliance_state` must be `CLEARED`, or it is refused with
    `ERR_SALE_COMPLIANCE_FLAGGED` (HTTP 409)."
    PRD 3.7: "It also flags the patron's baskets directly: every sale whose
    `patron_id` names this patron and whose `tender_state` is `OPEN` has its compliance
    axis moved `CLEARED → FLAGGED` with its `version` incremented, regardless of whether
    it carries an acting delegation."

    Design: Corner/validations/corner_tender_of_flagged_sale_returns_compliance_flagged
    """
    store = fx.create_store(
        api,
        name="Fort Drum Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-FLG-500",
        name="Cooking Oil 48oz",
        category="GROCERY_STAPLE",
        unit_cost_cents=500,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="X1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SSG L Okonjo", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 1)
    fx.record_compliance_review(api, patron["id"], "CONFIRM_STRIKE")

    validate_error(
        api.tender_sale(sale["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        "ERR_SALE_COMPLIANCE_FLAGGED",
        409,
    )

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["compliance_state"] == "FLAGGED"
    assert read_sale["tender_state"] == "OPEN"
    assert read_sale["acting_delegation_id"] is None

    read_patron = fx.read_patron(api, patron["id"])
    assert read_patron["card_status"] == "VALID"
    assert read_patron["resale_risk_score"] == 25
    assert read_patron["resale_watch_status"] == "CLEAR"

    _rows, meta = validate_paginated(
        api.list_delegations({"delegate_patron_id": patron["id"]}, HEADERS_COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 0
    assert fx.read_store(api, store["id"])["surcharge_fund_balance_cents"] == 0


def test_a_visit_stamped_before_the_grant_opens_is_not_covered_by_it(api):
    """business_date 08-05 against a window opening 08-10 is refused with 409.

    PRD 3.5: "That last question needs the visit's own instant, and the visit gets one
    at creation: `business_date` is stamped from the logical clock's current position
    and is the date the sale is booked to for every purpose afterwards — allocation
    resolution, promotional-window evaluation, delegation coverage and the rolling risk
    window all read it."
    PRD 3.5: "Coverage means `valid_from` at or before `business_date` and `valid_to`
    strictly after it, with a `business_date` exactly equal to `valid_to` therefore
    falling outside the grant."

    Design: Corner/validations/corner_sale_outside_delegation_window_returns_not_covering
    """
    store = fx.create_store(
        api,
        name="Fort Stewart Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    sponsor = fx.create_patron(api, full_name="SFC (Ret) M Delacroix", id_card_class="RETIREE")
    delegate = fx.create_patron(api, full_name="SPC N Achterberg", id_card_class="ACTIVE_DUTY")
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_10,
        valid_to=C.AUG_20,
        per_sale_spend_cap_cents=50000,
        expected_delegate_patron_version=delegate["version"],
    )
    fx.set_clock(api, C.AUG_05)

    validate_error(
        api.open_sale(
            factories.sale_payload(store["id"], delegate["id"], acting_delegation_id=delegation["id"]),
            HEADERS_STORE_CASHIER,
        ),
        "ERR_DELEGATION_WINDOW_NOT_COVERING",
        409,
    )

    assert fx.read_delegation(api, delegation["id"])["status"] == "ACTIVE"
    assert fx.read_patron(api, delegate["id"])["card_status"] == "VALID"

    _rows, meta = validate_paginated(
        api.list_sales({"store_id": store["id"]}, HEADERS_STORE_CASHIER)
    )
    assert meta["total_count"] == 0


def test_the_grants_status_is_consulted_before_its_window(api):
    """With both gates violated the caller hears about the revocation, not the window.

    PRD 3.5: "After the payload has been schema-checked and after every identifier in
    it has been resolved, the system asks in sequence: is the acting delegation, if one
    was named, currently `ACTIVE` (`ERR_DELEGATION_NOT_ACTIVE`); is the patron's own
    `card_status` `VALID` (`ERR_PATRON_CARD_NOT_VALID`); if the patron is a `DEPENDENT`,
    is their sponsor's `card_status` `VALID` (`ERR_SPONSOR_CARD_NOT_VALID`); is the
    patron's `id_card_class` authorised for this store's `channel`
    (`ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL`); is it authorised for this store's `region`
    (`ERR_PATRON_NOT_ELIGIBLE_IN_REGION`); and finally, does the acting delegation's
    half-open window actually cover this visit (`ERR_DELEGATION_WINDOW_NOT_COVERING`,
    HTTP 409)?"
    PRD 2.8: "The system therefore evaluates checks in a fixed doctrinal order and
    returns the first failure it finds; later checks are never reached once an earlier
    one has failed."

    Design: Corner/validations/corner_delegation_status_check_precedes_window_check
    """
    store = fx.create_store(
        api,
        name="Fort Gordon Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    sponsor = fx.create_patron(api, full_name="CW3 (Ret) O Bergqvist", id_card_class="RETIREE")
    delegate = fx.create_patron(api, full_name="PFC P Sundaresan", id_card_class="ACTIVE_DUTY")
    delegation = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_10,
        valid_to=C.AUG_20,
        per_sale_spend_cap_cents=50000,
        expected_delegate_patron_version=delegate["version"],
    )
    fx.revoke_delegation(api, delegation["id"], reason="SPONSOR_REQUEST")
    fx.set_clock(api, C.AUG_05)

    error = validate_error(
        api.open_sale(
            factories.sale_payload(store["id"], delegate["id"], acting_delegation_id=delegation["id"]),
            HEADERS_STORE_CASHIER,
        ),
        "ERR_DELEGATION_NOT_ACTIVE",
        409,
    )
    assert error["error_id"] != "ERR_DELEGATION_WINDOW_NOT_COVERING"

    assert fx.read_delegation(api, delegation["id"])["status"] == "REVOKED"

    _rows, meta = validate_paginated(
        api.list_sales({"store_id": store["id"]}, HEADERS_STORE_CASHIER)
    )
    assert meta["total_count"] == 0


def test_an_aggregate_landing_exactly_on_the_per_visit_limit_is_accepted(api):
    """4 units then 2 units against a limit of 6 both ring, for 1500 and 75.

    PRD 3.5: "When the product's `quantity_limit_per_visit` is not null, the system
    adds the `quantity` of every existing line of this visit for that same product to
    the `quantity` now being requested, and requires the total to be no greater than the
    limit."
    PRD 3.5: "A total exactly equal to the limit passes; a total above it is refused
    with `ERR_QUANTITY_LIMIT_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/corner_quantity_limit_satisfied_at_exact_limit_succeeds
    """
    store = fx.create_store(
        api,
        name="Fort Sill Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-QTY-250",
        name="Infant Formula 12oz",
        category="GROCERY_STAPLE",
        unit_cost_cents=250,
        quantity_limit_per_visit=6,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="Y1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT Q Halvorsen", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    first_line = fx.add_line(api, sale["id"], product["id"], 4)

    second_line = validate_success(
        api.add_sale_line(
            sale["id"], factories.sale_line_payload(product["id"], 2), HEADERS_STORE_CASHIER
        ),
        201,
    )

    assert first_line["extended_cents"] == 1000
    assert first_line["line_surcharge_cents"] == 50
    assert second_line["extended_cents"] == 500
    assert second_line["line_surcharge_cents"] == 25

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["line_count"] == 2
    assert read_sale["merchandise_cents"] == 1500
    assert read_sale["surcharge_total_cents"] == 75
    assert read_sale["total_due_cents"] == 1575


def test_a_restricted_watch_blocks_the_controlled_item_while_the_card_stays_valid(api):
    """Eight single-unit baskets drive the rolling score to 96 and the ninth line is 403.

    PRD 3.5: "The **resale watch** gate is blunt: when the patron's
    `resale_watch_status` is `RESTRICTED`, no line of any product whose
    `resale_restricted` is true may be added, and the attempt is refused with
    `ERR_RESTRICTED_ITEM_BLOCKED_BY_WATCH` (HTTP 403)."
    PRD 3.7: "The first term is 12 points for every unit of resale-restricted
    merchandise in the set — that is, 12 multiplied by the total of `restricted_units`
    across all sale lines of all sales in the set."
    PRD 3.7: "The **last-five-sales** variant writes `recent_sales_risk_score` and
    drives the card axis."

    Design: Corner/validations/corner_restricted_item_blocked_for_restricted_watch_patron
    """
    store = fx.create_store(
        api,
        name="Fort Campbell Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
        shelf_block_capacity_facings=24,
    )
    product = fx.create_product(
        api,
        sku="SKU-RST-1000",
        name="Infant Formula Case",
        category="GROCERY_STAPLE",
        unit_cost_cents=1000,
        resale_restricted=True,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="Z1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SPC R Tchividjian", id_card_class="ACTIVE_DUTY")
    eighth_sale = None
    for _ in range(8):
        eighth_sale = fx.open_sale(api, store["id"], patron["id"])
        fx.add_line(api, eighth_sale["id"], product["id"], 1)
    ninth_sale = fx.open_sale(api, store["id"], patron["id"])

    validate_error(
        api.add_sale_line(
            ninth_sale["id"], factories.sale_line_payload(product["id"], 1), HEADERS_STORE_CASHIER
        ),
        "ERR_RESTRICTED_ITEM_BLOCKED_BY_WATCH",
        403,
    )

    read_patron = fx.read_patron(api, patron["id"])
    assert read_patron["restricted_units_30d"] == 8
    assert read_patron["resale_risk_score"] == 96
    assert read_patron["resale_watch_status"] == "RESTRICTED"
    assert read_patron["recent_sales_risk_score"] == 60
    assert read_patron["card_status"] == "VALID"
    assert read_patron["suspension_reason"] is None

    read_ninth = fx.read_sale(api, ninth_sale["id"])
    assert read_ninth["line_count"] == 0
    assert read_ninth["total_due_cents"] == 0
    assert fx.read_sale(api, eighth_sale["id"])["line_count"] == 1


def test_overseas_shipment_cannot_be_routed_out_of_a_conus_store(api):
    """The allocation exists, so the region gate is the one that speaks: 409.

    PRD 3.8: "Second, and only after that, a `route` of `OVERSEAS_SHIP` requires the
    store's `region` to be `OVERSEAS` or `DEPLOYED`; requesting overseas shipment from a
    `CONUS` store is refused with `ERR_ROUTE_NOT_AVAILABLE_IN_REGION` (HTTP 409)."
    PRD 3.8: "A newly placed order sits at `state` of `SUBMITTED` with `route` still
    null, and every shipping figure — `billable_weight_kg`, `gross_ship_cents`,
    `patron_share_cents` and `shipping_allowance_cents` — at 0, with `cancelled_reason`
    null."

    Design: Corner/validations/corner_overseas_route_at_conus_store_returns_route_not_available
    """
    store = fx.create_store(
        api,
        name="Fort Knox Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        exchange_markup_bp=750,
    )
    product = fx.create_product(
        api,
        sku="SKU-RTE-4000",
        name="Portable Generator",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=4000,
        unit_weight_grams=900,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AA1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SSG S Marchetti", id_card_class="ACTIVE_DUTY")
    order = fx.create_special_order(api, store["id"], patron["id"], product["id"], 2)

    validate_error(
        api.route_special_order(
            order["id"], factories.route_payload("OVERSEAS_SHIP"), HEADERS_STORE_CASHIER
        ),
        "ERR_ROUTE_NOT_AVAILABLE_IN_REGION",
        409,
    )

    read_order = fx.read_special_order(api, order["id"])
    assert read_order["state"] == "SUBMITTED"
    assert read_order["route"] is None
    assert read_order["shipping_allowance_cents"] == 0
    assert fx.read_store(api, store["id"])["shipping_allowance_committed_cents"] == 0


def test_an_overseas_civilian_shops_the_exchange_but_not_the_commissary(api):
    """One card class, two channels in the same region: 201 then 403.

    PRD 3.2: "The **channel** half asks whether the card class may shop that kind of
    store at all: `ACTIVE_DUTY`, `GUARD_RESERVE`, `RETIREE`, `DEPENDENT` and
    `DISABLED_VETERAN` are all authorised at both `COMMISSARY` and `EXCHANGE` stores,
    while `DOD_CIVILIAN_OVERSEAS` is authorised at `EXCHANGE` stores only — an overseas
    civilian employee has exchange privileges but no commissary privileges."
    PRD 3.2: "A channel failure is reported as `ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL`
    (HTTP 403)."

    Design: Corner/validations/corner_dod_civilian_overseas_blocked_at_commissary_channel
    """
    exchange = fx.create_store(
        api,
        name="Vicenza Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=500,
        exchange_markup_bp=750,
    )
    commissary = fx.create_store(
        api,
        name="Vicenza Commissary",
        channel="COMMISSARY",
        region="OVERSEAS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(
        api, full_name="U Kirchhoff (GS-11)", id_card_class="DOD_CIVILIAN_OVERSEAS"
    )
    exchange_sale = fx.open_sale(api, exchange["id"], patron["id"])

    validate_error(
        api.open_sale(
            factories.sale_payload(commissary["id"], patron["id"]), HEADERS_STORE_CASHIER
        ),
        "ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL",
        403,
    )

    assert fx.read_sale(api, exchange_sale["id"])["tender_state"] == "OPEN"
    assert fx.read_patron(api, patron["id"])["card_status"] == "VALID"

    _rows, meta = validate_paginated(
        api.list_sales({"store_id": commissary["id"]}, HEADERS_STORE_CASHIER)
    )
    assert meta["total_count"] == 0


def test_a_disabled_veteran_may_shop_only_inside_the_continental_united_states(api):
    """The same exchange channel passes at CONUS and fails at OVERSEAS.

    PRD 3.2: "A `DISABLED_VETERAN` is authorised in `CONUS` only."
    PRD 3.2: "A region failure is reported as `ERR_PATRON_NOT_ELIGIBLE_IN_REGION`
    (HTTP 403), and because the channel half is evaluated first, a
    `DOD_CIVILIAN_OVERSEAS` patron attempting a `CONUS` commissary is told about the
    channel, not the region."

    Design: Corner/validations/corner_disabled_veteran_blocked_outside_conus_region
    """
    conus = fx.create_store(
        api,
        name="Fort Belvoir Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        exchange_markup_bp=750,
    )
    overseas = fx.create_store(
        api,
        name="Kaiserslautern Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=500,
        exchange_markup_bp=750,
    )
    patron = fx.create_patron(
        api, full_name="V Ostrowski (100% SC)", id_card_class="DISABLED_VETERAN"
    )
    conus_sale = fx.open_sale(api, conus["id"], patron["id"])

    validate_error(
        api.open_sale(factories.sale_payload(overseas["id"], patron["id"]), HEADERS_STORE_CASHIER),
        "ERR_PATRON_NOT_ELIGIBLE_IN_REGION",
        403,
    )

    assert fx.read_sale(api, conus_sale["id"])["tender_state"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_sales({"store_id": overseas["id"]}, HEADERS_STORE_CASHIER)
    )
    assert meta["total_count"] == 0


def test_a_suspended_card_cannot_open_a_visit_at_all(api):
    """An administratively suspended patron is turned away at the door with 403.

    PRD 3.2: "The transacting patron's own `card_status` must be `VALID`; a `SUSPENDED`
    or `REVOKED` card is refused with `ERR_PATRON_CARD_NOT_VALID` (HTTP 403), and that
    gate guards four operations — opening a visit, ringing a line onto a visit, tendering
    a visit, and placing a special order."
    PRD 3.7: "A `ComplianceOfficer` also moves the card axis by hand, supplying an
    `action` of `SUSPEND`, `REINSTATE` or `REVOKE` together with an optional `reason`."

    Design: Corner/validations/corner_suspended_card_blocks_sale_open
    """
    store = fx.create_store(
        api,
        name="Fort Polk Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(api, full_name="SPC W Adeyemi", id_card_class="ACTIVE_DUTY")
    fx.set_card_status(api, patron["id"], "SUSPEND", reason="ADMIN_ACTION")

    validate_error(
        api.open_sale(factories.sale_payload(store["id"], patron["id"]), HEADERS_STORE_CASHIER),
        "ERR_PATRON_CARD_NOT_VALID",
        403,
    )

    read_patron = fx.read_patron(api, patron["id"])
    assert read_patron["card_status"] == "SUSPENDED"
    assert read_patron["suspension_reason"] == "ADMIN_ACTION"

    _rows, meta = validate_paginated(
        api.list_sales({"patron_id": patron["id"]}, HEADERS_STORE_CASHIER)
    )
    assert meta["total_count"] == 0


def test_a_dependents_own_valid_card_does_not_survive_a_suspended_sponsor(api):
    """The dependent's card is VALID, so the sponsor gate is the one that fires.

    PRD 3.2: "Immediately after it, and only when the transacting patron's
    `id_card_class` is `DEPENDENT`, the sponsor named by `sponsor_patron_id` must itself
    have `card_status` of `VALID`; a dependent shopping behind a suspended or revoked
    sponsor is refused with `ERR_SPONSOR_CARD_NOT_VALID` (HTTP 403)."
    PRD 3.2: "The sponsor gate guards two operations — opening a visit and placing a
    special order — and is not re-evaluated at line-add or tender time."

    Design: Corner/validations/corner_dependent_with_suspended_sponsor_blocked_at_sale_open
    """
    store = fx.create_store(
        api,
        name="Fort Meade Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    sponsor = fx.create_patron(api, full_name="SSG X Ravensworth", id_card_class="ACTIVE_DUTY")
    fx.set_card_status(api, sponsor["id"], "SUSPEND", reason="ADMIN_ACTION")
    dependent = fx.create_patron(
        api,
        full_name="Y Ravensworth",
        id_card_class="DEPENDENT",
        sponsor_patron_id=sponsor["id"],
    )
    assert dependent["card_status"] == "VALID"

    error = validate_error(
        api.open_sale(factories.sale_payload(store["id"], dependent["id"]), HEADERS_STORE_CASHIER),
        "ERR_SPONSOR_CARD_NOT_VALID",
        403,
    )
    assert error["error_id"] != "ERR_PATRON_CARD_NOT_VALID"

    read_dependent = fx.read_patron(api, dependent["id"])
    assert read_dependent["card_status"] == "VALID"
    assert read_dependent["suspension_reason"] is None
    assert fx.read_patron(api, sponsor["id"])["card_status"] == "SUSPENDED"

    _rows, meta = validate_paginated(
        api.list_sales({"store_id": store["id"]}, HEADERS_STORE_CASHIER)
    )
    assert meta["total_count"] == 0


def test_the_wrong_role_is_told_about_the_role_not_about_the_missing_visit(api):
    """A cashier voiding an unknown identifier hears 403, because step 2 precedes step 3.

    PRD 2.8: "The system therefore evaluates checks in a fixed doctrinal order and
    returns the first failure it finds; later checks are never reached once an earlier
    one has failed."
    PRD 2.8: "3. **Path existence** — every identifier embedded in the URL path
    resolves, checked from left to right."
    PRD 2.1: "A request whose role is well-formed but is not among the roles authorised
    for the endpoint being called is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/corner_role_denial_outranks_path_existence_check
    """
    store = fx.create_store(
        api,
        name="Fort Hood Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(api, full_name="SGT Z Ferraro", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])

    validate_error(
        api.void_sale(
            NON_EXISTENT_UUID, factories.void_payload("OPERATOR_ERROR"), HEADERS_STORE_CASHIER
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    assert fx.read_sale(api, sale["id"])["tender_state"] == "OPEN"
