"""The charges a parcel earns on the road, and the ones it loses.

A package's price is not settled at induction. A window armed an hour later
adds a hundred and fifty cents to a parcel nobody touched; a consignee's
refusal mints two charges in a single request while an address correction mints
one and lets the parcel keep moving; a residential fee appears or vanishes on
the strength of a single contract flag; and a waiver leaves the row standing at
its historical amount while quietly repricing the open bill beneath it.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_ACCESSORIAL_NOT_WAIVABLE,
    accessorials_for_shipment,
    activate_rate_contract,
    assert_fields,
    assert_lbs,
    assert_money_equals,
    create_shipper_account,
    create_surcharge_window,
    draft_rate_contract,
    find_row,
    get_success_data,
    induct_shipment,
    open_invoice,
    raise_exception,
    refresh_invoice,
    refresh_shipment,
    shipment_payload,
    shipper_with_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

# 12 x 10 x 8 in rounds to a cube of 960 in3; over the 139 divisor that is a
# 7 lb dimensional weight, which beats the 6.0 lb scale weight, and 7 lb at the
# zone-2 rate of 380 cents per pound is a 2660-cent transportation charge.
SMALL_PARCEL = {
    "zone": 2,
    "residential_declared": False,
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}
TRANSPORTATION_CENTS = 2660

RESIDENTIAL_CENTS = 590
REFUSAL_CENTS = 1350
RETURN_UNDELIVERABLE_CENTS = 1800
ADDRESS_CORRECTION_CENTS = 2200
EXTENDED_AREA_CENTS = 650
DAS_AREA_CENTS = 425


def _acme(api, **contract_kwargs):
    """SH-2001 holding one ACTIVE EXPRESS-only contract."""
    return shipper_with_active_contract(
        api,
        account_number=ACME_ACCOUNT_NUMBER,
        name=ACME_NAME,
        with_ground=False,
        contract_kwargs=contract_kwargs or None,
    )


def _preview(api, shipment_id):
    """The billing desk's dry run of one parcel's price."""
    return get_success_data(api.get_billing_preview(shipment_id, BILLING_OPS_HEADERS))


def test_01_a_scheduled_window_prices_nothing_until_it_is_armed(api):
    """PRD §3.2: "A window opens at `status` `SCHEDULED`, which means it is on the calendar but invisible to pricing."
    PRD §3.2: "Arming it moves it `SCHEDULED` → `ACTIVE`, at which point it enters the surcharge candidate set consulted during line pricing, and its `version` increments by 1."
    PRD §3.6: "The candidate windows are every surcharge window whose `status` is `ACTIVE`, whose half-open range contains the shipment's `pickup_date` — meaning the date is on or after `start_date` and strictly before `end_date` — and whose scope matches, meaning either `service_level_id` is null or it equals the shipment's `service_level_id`."
    PRD §3.6: "Windows at `SCHEDULED` or `CANCELLED` never price anything."
    PRD §3.6: "The preview creates nothing and mutates nothing; it returns `shipment_id`, `contract_id`, `billable_weight_lbs`, `billable_weight_basis`, `rate_cents_per_lb`, `transportation_base_cents`, `surcharge_cents`, `accessorial_total_cents`, and `line_total_cents`, computed by exactly the line-pricing rules above."
    PRD §3.2: "Windows can be listed with optional filters on `kind`, on `service_level_id`, and on `status`."

    Design: Corner/state_machines/activating_a_scheduled_window_admits_it_to_the_pricing_set
    """
    shipper = _acme(api)
    window = create_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-15",
        per_package_cents=150,
    )
    assert window["status"] == "SCHEDULED", (
        f"a fresh window is only on the calendar, got {window['status']}"
    )
    parcel = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-W-0001", **SMALL_PARCEL
    )
    assert parcel.shipment["pickup_date"] == "2026-08-01", (
        "the parcel must sit inside the window's range for the comparison to be "
        f"about status alone, got {parcel.shipment['pickup_date']}"
    )

    before = _preview(api, parcel.shipment_id)
    assert_money_equals(
        before["line_total_cents"], TRANSPORTATION_CENTS, "line_total_cents before arming"
    )
    assert_money_equals(before["surcharge_cents"], 0, "surcharge_cents before arming")

    # Nothing about the parcel changes; only the window is armed.
    armed = validate_success(
        api.activate_surcharge_window(window["id"], CARRIER_ADMIN_HEADERS)
    )
    assert armed["status"] == "ACTIVE"
    assert armed["version"] == window["version"] + 1, (
        f"arming bumps the window's version, expected {window['version'] + 1}, "
        f"got {armed['version']}"
    )

    after = _preview(api, parcel.shipment_id)
    assert_money_equals(after["surcharge_cents"], 150, "surcharge_cents after arming")
    assert_money_equals(
        after["transportation_base_cents"],
        TRANSPORTATION_CENTS,
        "transportation_base_cents",
    )
    assert_money_equals(
        after["line_total_cents"],
        TRANSPORTATION_CENTS + 150,
        "line_total_cents after arming",
    )

    _, meta = validate_paginated(
        api.list_surcharge_windows(
            CARRIER_ADMIN_HEADERS, {"kind": "DEMAND", "status": "ACTIVE", "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one demand window is now armed, found {meta['total_count']}"
    )


def test_02_a_refusal_mints_both_the_refusal_and_the_return_leg(api):
    """PRD §3.5: "`kind` `REFUSED` drives the shipment `IN_TRANSIT → REFUSED` and creates **two** accessorial charges in the same request."
    PRD §3.5: "The first carries code `REFUSAL` at $13.50 or its contract override."
    PRD §3.5: "The second carries code `RETURN_UNDELIVERABLE` at $18.00 or its contract override, because a refused parcel must still travel back to the shipper."
    PRD §3.5: "Only the updated shipment is returned by the operation, so the second charge — and indeed both charges — are discoverable only by listing the shipment's accessorials."
    PRD §3.3: "The shipment's `accessorial_total_cents` is then the sum of `amount_cents` over its charges whose `status` is `ASSESSED` — charges sitting at `WAIVED` or `REVERSED` contribute nothing."
    PRD §3.5: "A `CarrierOps` operator drives the shipment `IN_TRANSIT → DELIVERED`, and the server stamps `delivered_at` from the logical clock and increments the shipment's `version` by 1."

    Design: Corner/state_machines/a_refusal_exception_creates_both_the_refusal_and_the_return_charge
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-X-0002", **SMALL_PARCEL
    )
    assert_money_equals(
        parcel.shipment["accessorial_total_cents"], 0, "accessorial_total_cents at induction"
    )

    refused = raise_exception(
        api, parcel.shipment_id, "REFUSED", reason="consignee refused delivery"
    )
    # The response body is the parcel, not either of the two charges it minted.
    assert refused["id"] == parcel.shipment_id, (
        "the exception returns the updated shipment, got a body with id "
        f"{refused['id']}"
    )
    assert refused["movement_status"] == "REFUSED"
    assert_money_equals(
        refused["accessorial_total_cents"],
        REFUSAL_CENTS + RETURN_UNDELIVERABLE_CENTS,
        "accessorial_total_cents",
    )

    charges = accessorials_for_shipment(api, parcel.shipment_id)
    assert len(charges) == 2, (
        "a refusal is the one outcome that mints two charges at once, found "
        f"{[row['code'] for row in charges]}"
    )
    refusal_row = find_row(charges, code="REFUSAL")
    return_row = find_row(charges, code="RETURN_UNDELIVERABLE")
    assert_money_equals(refusal_row["amount_cents"], REFUSAL_CENTS, "REFUSAL amount_cents")
    assert_money_equals(
        return_row["amount_cents"],
        RETURN_UNDELIVERABLE_CENTS,
        "RETURN_UNDELIVERABLE amount_cents",
    )
    for row in (refusal_row, return_row):
        assert row["status"] == "ASSESSED", (
            f"{row['code']} must contribute money immediately, got {row['status']}"
        )

    preview = _preview(api, parcel.shipment_id)
    assert_money_equals(preview["surcharge_cents"], 0, "surcharge_cents")
    assert_money_equals(
        preview["accessorial_total_cents"],
        REFUSAL_CENTS + RETURN_UNDELIVERABLE_CENTS,
        "preview accessorial_total_cents",
    )
    assert_money_equals(
        preview["line_total_cents"],
        TRANSPORTATION_CENTS + REFUSAL_CENTS + RETURN_UNDELIVERABLE_CENTS,
        "line_total_cents",
    )

    after = refresh_shipment(api, parcel.shipment_id)
    assert after["delivered_at"] is None, (
        "a refusal is not a delivery, so no delivery instant may be stamped, got "
        f"{after['delivered_at']}"
    )
    assert after["billing_status"] == "UNBILLED", (
        f"refusing a parcel never bills it, got {after['billing_status']}"
    )


def test_03_the_exception_kind_decides_whether_the_parcel_keeps_moving(api):
    """PRD §3.5: "`kind` `UNDELIVERABLE` drives the shipment `IN_TRANSIT → UNDELIVERABLE` and creates **one** accessorial charge, code `RETURN_UNDELIVERABLE`, `source` `AUTO`, `status` `ASSESSED`, covering the return leg at $18.00 or the contract's override for that code."
    PRD §3.5: "`kind` `ADDRESS_CORRECTED` creates **one** accessorial charge, code `ADDRESS_CORRECTION`, `source` `AUTO`, `status` `ASSESSED`, at $22.00 or its contract override, and leaves `movement_status` unchanged at `IN_TRANSIT` — the parcel keeps moving, so this is a self-loop on the movement axis rather than an outcome."
    PRD §3.5: "In all three cases the shipment's `accessorial_total_cents` rises by the sum of the newly assessed amounts, the shipment's `version` increments by 1, and the reconciliation branch of §2.9 runs."
    PRD §3.5: "A shipment's `movement_status` opens at `IN_TRANSIT` and every one of its outcomes is reachable only from there."
    PRD §3.5: "A `CarrierOps` operator drives the shipment `IN_TRANSIT → DELIVERED`, and the server stamps `delivered_at` from the logical clock and increments the shipment's `version` by 1."

    Design: Corner/state_machines/the_exception_kind_decides_whether_the_parcel_keeps_moving
    """
    shipper = _acme(api)
    corrected = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-K-0001", **SMALL_PARCEL
    )
    doomed = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-K-0002", **SMALL_PARCEL
    )

    # Same endpoint, same shaped parcel, two different kinds.
    after_correction = raise_exception(
        api,
        corrected.shipment_id,
        "ADDRESS_CORRECTED",
        reason="suite number corrected in transit",
    )
    assert after_correction["movement_status"] == "IN_TRANSIT", (
        "an address correction is a self-loop and does not end the movement, got "
        f"{after_correction['movement_status']}"
    )
    assert_money_equals(
        after_correction["accessorial_total_cents"],
        ADDRESS_CORRECTION_CENTS,
        "accessorial_total_cents",
    )

    after_failure = raise_exception(
        api, doomed.shipment_id, "UNDELIVERABLE", reason="no such address"
    )
    assert after_failure["movement_status"] == "UNDELIVERABLE", (
        f"an undeliverable parcel stops moving, got {after_failure['movement_status']}"
    )
    assert_money_equals(
        after_failure["accessorial_total_cents"],
        RETURN_UNDELIVERABLE_CENTS,
        "accessorial_total_cents",
    )

    # Because the corrected parcel never left IN_TRANSIT, delivery still works.
    delivered = validate_success(
        api.deliver_shipment(corrected.shipment_id, CARRIER_OPS_HEADERS)
    )
    assert delivered["movement_status"] == "DELIVERED"
    assert delivered["delivered_at"] is not None, (
        "delivery stamps its instant, got a null delivered_at"
    )

    correction_rows = accessorials_for_shipment(api, corrected.shipment_id)
    assert len(correction_rows) == 1, (
        f"one charge, not two, follows a correction, found {len(correction_rows)}"
    )
    assert_fields(
        correction_rows[0],
        {"code": "ADDRESS_CORRECTION", "source": "AUTO", "status": "ASSESSED"},
    )

    failure_rows = accessorials_for_shipment(api, doomed.shipment_id)
    assert len(failure_rows) == 1, (
        "an undeliverable parcel earns the return leg only, never the refusal fee, "
        f"found {[row['code'] for row in failure_rows]}"
    )
    assert_fields(
        failure_rows[0],
        {"code": "RETURN_UNDELIVERABLE", "source": "AUTO", "status": "ASSESSED"},
    )

    assert_money_equals(
        _preview(api, corrected.shipment_id)["line_total_cents"],
        TRANSPORTATION_CENTS + ADDRESS_CORRECTION_CENTS,
        "corrected parcel line_total_cents",
    )
    assert_money_equals(
        _preview(api, doomed.shipment_id)["line_total_cents"],
        TRANSPORTATION_CENTS + RETURN_UNDELIVERABLE_CENTS,
        "undeliverable parcel line_total_cents",
    )


def test_04_the_residential_fee_falls_only_when_the_contract_waives_it(api):
    """PRD §3.3: "`RESIDENTIAL` is assessed when the shipment's `residential_declared` is true *and* the governing contract's `residential_waived` is false."
    PRD §3.1: "Two optional levers refine the contract: `accessorial_rate_overrides` is a map from accessorial code to a cents amount that displaces the carrier default rate for that code, defaulting to an empty map; and `residential_waived`, defaulting to false, suppresses automatic residential assessment for this shipper entirely when set true."
    PRD §3.3: "Otherwise the carrier default applies: $5.90 for `RESIDENTIAL`, $125.00 for `OVERSIZE`, $24.50 for `ADDITIONAL_HANDLING`, $22.00 for `ADDRESS_CORRECTION`, $18.00 for `RETURN_UNDELIVERABLE`, and $13.50 for `REFUSAL`."
    PRD §3.3: "Each assessed code produces one `AccessorialCharge` record whose `shipment_id` points at the parcel, whose `source` is `AUTO`, whose `status` is `ASSESSED`, and whose `assessed_basis` records a short machine-readable trigger note explaining why it fired — for instance `longest_in=100>96` for an oversize charge, or `residential_declared=true` for a residential one."
    PRD §3.6: "The line's `accessorial_total_cents` is the sum of `amount_cents` over the shipment's accessorial charges whose `status` is `ASSESSED` at the moment the line is computed — `WAIVED` and `REVERSED` rows are excluded."

    Design: Corner/validations/the_residential_charge_is_suppressed_only_when_the_contract_waives_it
    """
    charging = _acme(api, residential_waived=False)
    express_id = charging.service_level_ids["EXPRESS"]

    # A second shipper on the same catalogue, differing only in the waiver flag.
    waiving_account = create_shipper_account(
        api, account_number="SH-2002", name="Borealis Freight"
    )
    waiving_contract = draft_rate_contract(
        api, waiving_account["id"], residential_waived=True
    )
    activate_rate_contract(
        api, waiving_contract["id"], waiving_account["version"]
    )

    residential_parcel = {**SMALL_PARCEL, "residential_declared": True}
    charged = validate_success(
        api.create_shipment(
            shipment_payload(
                charging.shipper_id,
                express_id,
                tracking_number="1Z-C-7001",
                **residential_parcel,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    spared = validate_success(
        api.create_shipment(
            shipment_payload(
                waiving_account["id"],
                express_id,
                tracking_number="1Z-C-7002",
                **residential_parcel,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )

    assert_money_equals(
        charged["accessorial_total_cents"], RESIDENTIAL_CENTS, "accessorial_total_cents"
    )
    charged_rows = accessorials_for_shipment(api, charged["id"])
    assert len(charged_rows) == 1, (
        f"exactly the residential fee is earned, found {[r['code'] for r in charged_rows]}"
    )
    assert_fields(
        charged_rows[0],
        {"code": "RESIDENTIAL", "source": "AUTO", "status": "ASSESSED"},
    )
    assert_money_equals(
        charged_rows[0]["amount_cents"], RESIDENTIAL_CENTS, "RESIDENTIAL amount_cents"
    )
    assert charged_rows[0]["assessed_basis"], (
        "an automatic charge records why it fired, got "
        f"{charged_rows[0]['assessed_basis']!r}"
    )

    assert_money_equals(
        spared["accessorial_total_cents"], 0, "accessorial_total_cents under a waiver"
    )
    assert accessorials_for_shipment(api, spared["id"]) == [], (
        "the waiver suppresses the assessment entirely rather than pricing it at 0"
    )

    charged_preview = _preview(api, charged["id"])
    spared_preview = _preview(api, spared["id"])
    assert_money_equals(
        charged_preview["line_total_cents"],
        TRANSPORTATION_CENTS + RESIDENTIAL_CENTS,
        "line_total_cents with the fee",
    )
    assert_money_equals(
        spared_preview["line_total_cents"],
        TRANSPORTATION_CENTS,
        "line_total_cents under the waiver",
    )
    for label, parcel, preview in (
        ("charged", charged, charged_preview),
        ("spared", spared, spared_preview),
    ):
        assert parcel["residential_declared"] is True, (
            f"the {label} parcel declares a residential destination"
        )
        assert_lbs(preview["billable_weight_lbs"], 7.0, f"{label} billable_weight_lbs")
        assert_money_equals(
            preview["transportation_base_cents"],
            TRANSPORTATION_CENTS,
            f"{label} transportation_base_cents",
        )


def test_05_waiving_a_charge_keeps_the_row_and_reprices_the_open_bill(api):
    """PRD §3.5: "A `BillingOps` operator may waive an accessorial as a service gesture, optionally recording a `reason`."
    PRD §3.5: "The charge moves `ASSESSED` → `WAIVED`: the row survives for audit and simply stops contributing money."
    PRD §3.5: "A successful waiver recomputes the shipment's `accessorial_total_cents` and the account's `open_charges_cents`, increments the charge's `version` by 1, and — when the package's line belongs to an `OPEN` invoice — reprices that line and re-runs the invoice roll-up."
    PRD §3.5: "Only an `ASSESSED` charge is waivable; a charge already at `WAIVED` or `REVERSED` is rejected with `ERR_ACCESSORIAL_NOT_WAIVABLE` (HTTP 409), and that state check precedes the freeze check."
    PRD §3.6: "`accessorial_subtotal_cents` is the sum, over those lines, of `accessorial_total_cents`."
    PRD §3.5: "Every accessorial ever attached to a package remains readable, including `WAIVED` and `REVERSED` history rows, through a per-shipment listing that accepts optional filters on `status` and on `code`."

    Design: Corner/endpoints/waiving_an_accessorial_is_an_action_endpoint_that_moves_money
    """
    shipper = _acme(api, residential_waived=False)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-E-2001",
        **{**SMALL_PARCEL, "residential_declared": True},
    )
    validate_success(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    assert_money_equals(
        invoice.invoice["net_amount_cents"],
        TRANSPORTATION_CENTS + RESIDENTIAL_CENTS,
        "net_amount_cents before the waiver",
    )

    charge = accessorials_for_shipment(api, parcel.shipment_id)[0]
    assert_money_equals(
        charge["amount_cents"], RESIDENTIAL_CENTS, "RESIDENTIAL amount_cents"
    )

    # There is no edit on a charge; the waive action is the only way to stop it.
    waived = validate_success(
        api.waive_accessorial(
            charge["id"],
            BILLING_OPS_HEADERS,
            reason="goodwill: commercial dock confirmed",
        )
    )
    assert waived["status"] == "WAIVED"
    assert_money_equals(
        waived["amount_cents"],
        RESIDENTIAL_CENTS,
        "the waived row keeps its historical amount_cents",
    )
    assert waived["version"] == charge["version"] + 1, (
        f"the waiver bumps the charge, expected {charge['version'] + 1}, "
        f"got {waived['version']}"
    )

    after_shipment = refresh_shipment(api, parcel.shipment_id)
    assert_money_equals(
        after_shipment["accessorial_total_cents"],
        0,
        "a WAIVED charge no longer contributes to accessorial_total_cents",
    )

    after_invoice = refresh_invoice(api, invoice.invoice_id)
    assert_money_equals(
        after_invoice["net_amount_cents"],
        TRANSPORTATION_CENTS,
        "net_amount_cents after the waiver",
    )
    assert_money_equals(
        after_invoice["accessorial_subtotal_cents"], 0, "accessorial_subtotal_cents"
    )
    assert after_invoice["status"] == "OPEN", (
        f"the bill was never published, so it stays open, got {after_invoice['status']}"
    )

    # An OPEN invoice is repriced in place, so no adjustment row is needed.
    _, adjustment_meta = validate_paginated(
        api.list_billing_adjustments(BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert adjustment_meta["total_count"] == 0, (
        "an unpublished line is edited in place rather than adjusted, found "
        f"{adjustment_meta['total_count']}"
    )

    # The action is not idempotent: the row is no longer waivable.
    validate_error(
        api.waive_accessorial(charge["id"], BILLING_OPS_HEADERS, reason="second attempt"),
        ERR_ACCESSORIAL_NOT_WAIVABLE,
        409,
    )
    unchanged = get_success_data(
        api.get_accessorial(charge["id"], BILLING_OPS_HEADERS)
    )
    assert unchanged["version"] == waived["version"], (
        f"the refused second waiver must not bump the row, got {unchanged['version']}"
    )
    history = accessorials_for_shipment(api, parcel.shipment_id, status="WAIVED")
    assert len(history) == 1, (
        f"the waived row survives for audit, found {len(history)} rows"
    )


def test_06_an_extended_delivery_area_prices_at_its_own_class_rate(api):
    """PRD §3.3: "The delivery-area charge is the exception to the single-default pattern: its amount is keyed by the shipment's `delivery_area_class`, at $0.00 for `NONE`, $4.25 for `DAS`, and $6.50 for `EXTENDED`."
    PRD §3.3: "`DELIVERY_AREA` is assessed whenever `delivery_area_class` is anything other than `NONE`."
    PRD §3.3: "The billable weight is the greatest of those three quantities — the actual billable pound count, the dimensional pound count, and the oversize floor — and is written to `preliminary_billable_weight_lbs`."
    PRD §3.6: "That row's `cents_per_lb` is recorded on the line as `rate_cents_per_lb`, and the uncapped charge is the billable pound count multiplied by that per-pound rate."
    PRD §3.5: "Every accessorial ever attached to a package remains readable, including `WAIVED` and `REVERSED` history rows, through a per-shipment listing that accepts optional filters on `status` and on `code`."

    Design: Corner/calculations/an_extended_delivery_area_prices_at_its_own_class_rate
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-A-0001",
        delivery_area_class="EXTENDED",
        **SMALL_PARCEL,
    )
    assert_money_equals(
        parcel.shipment["accessorial_total_cents"],
        EXTENDED_AREA_CENTS,
        "accessorial_total_cents",
    )

    area_rows = accessorials_for_shipment(api, parcel.shipment_id, code="DELIVERY_AREA")
    assert len(area_rows) == 1, (
        f"one delivery-area charge is earned, found {len(area_rows)}"
    )
    area = find_row(area_rows, code="DELIVERY_AREA")
    assert_money_equals(
        area["amount_cents"],
        EXTENDED_AREA_CENTS,
        f"the EXTENDED class rate, not the DAS {DAS_AREA_CENTS}",
    )
    assert_fields(area, {"source": "AUTO", "status": "ASSESSED"})

    every_charge = accessorials_for_shipment(api, parcel.shipment_id)
    assert len(every_charge) == 1, (
        "a commercial, in-tolerance, conveyable parcel earns nothing else, found "
        f"{[row['code'] for row in every_charge]}"
    )

    preview = _preview(api, parcel.shipment_id)
    assert_money_equals(
        preview["transportation_base_cents"],
        TRANSPORTATION_CENTS,
        "transportation_base_cents",
    )
    assert_money_equals(preview["surcharge_cents"], 0, "surcharge_cents")
    assert_money_equals(
        preview["line_total_cents"],
        TRANSPORTATION_CENTS + EXTENDED_AREA_CENTS,
        "line_total_cents",
    )
    assert_lbs(preview["billable_weight_lbs"], 7.0, "billable_weight_lbs")
    assert preview["billable_weight_basis"] == "DIMENSIONAL", (
        "the cube beats the scale weight on this parcel, got "
        f"{preview['billable_weight_basis']}"
    )
    assert_money_equals(preview["rate_cents_per_lb"], 380, "rate_cents_per_lb")
