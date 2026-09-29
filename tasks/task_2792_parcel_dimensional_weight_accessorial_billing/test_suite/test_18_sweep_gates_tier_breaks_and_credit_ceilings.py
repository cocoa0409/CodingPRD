"""Which parcels a sweep may bill, and how far the money may be pushed.

The sweep is the one operation in this domain that reads four gates at once,
and this file walks each of them: a parcel still moving, a parcel whose scanner
verdict is unresolved and a parcel picked up on the wrong day are all left
behind, while naming a parcel outright lifts the date gate and the movement
gate but never the already-billed one. A contract with a hole in its rate table
takes the whole run down rather than half-billing a period, and a suspended
account stops new inductions without disturbing the packages already in the
air.

The second half of the file is arithmetic at the break points. A transportation
subtotal landing exactly on a tier threshold earns the tier while one cent
below it earns nothing at all, a discount whose exact value is a half cent
rounds up once on the summed subtotal, and the ceiling that stops a credit is
the invoice net — not the line it targets — so the tier discount itself becomes
the headroom a third full-line credit is missing.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_ADJUSTMENT_EXCEEDS_LINE,
    ERR_CREDIT_EXCEEDS_INVOICE_NET,
    ERR_NO_BILLABLE_SHIPMENTS,
    ERR_RATE_ROW_MISSING,
    ERR_SHIPMENT_ALREADY_BILLED,
    ERR_SHIPPER_SUSPENDED,
    FULL_TIER_TABLE,
    active_surcharge_window,
    add_scan,
    apply_adjustment,
    assert_fields,
    assert_lbs,
    assert_ledger,
    assert_money_equals,
    assert_pct,
    billing_adjustment_payload,
    delivered_shipment,
    get_success_data,
    ids_of,
    induct_shipment,
    invoice_sweep_payload,
    issued_invoice,
    open_invoice,
    propose_adjustment,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipment,
    refresh_shipper_account,
    set_clock,
    shipment_payload,
    shipper_with_active_contract,
    suspend_shipper_account,
    validate_error,
    validate_paginated,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"
BOREALIS_ACCOUNT_NUMBER = "SH-2002"
BOREALIS_NAME = "Borealis Freight"

# 12 x 10 x 8 in at 6.0 lb: cube 960, dimensional 7 lb, priced at 380.
SMALL_PARCEL = {
    "zone": 2,
    "residential_declared": False,
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}
TRANSPORTATION_CENTS = 2660

# 47 x 24 x 20 in at 45.0 lb: cube 22560, dimensional 163 lb, oversize on
# length-plus-girth, priced at 305.
BIG_PARCEL = {
    "zone": 2,
    "residential_declared": False,
    "declared_length_in": 47,
    "declared_width_in": 24,
    "declared_height_in": 20,
    "declared_weight_lbs": 45.0,
}
BIG_TRANSPORTATION_CENTS = 49715
OVERSIZE_CENTS = 12500

SECOND_DAY_INSTANT = "2026-08-02T00:00:00Z"
FIFTH_DAY_INSTANT = "2026-08-05T00:00:00Z"


def _acme(api, **contract_kwargs):
    """SH-2001 holding one ACTIVE EXPRESS-only contract."""
    return shipper_with_active_contract(
        api,
        account_number=ACME_ACCOUNT_NUMBER,
        name=ACME_NAME,
        with_ground=False,
        contract_kwargs=contract_kwargs or None,
    )


def _borealis(api, **contract_kwargs):
    """SH-2002 holding one ACTIVE GROUND-only contract of the same shape."""
    return shipper_with_active_contract(
        api,
        account_number=BOREALIS_ACCOUNT_NUMBER,
        name=BOREALIS_NAME,
        with_express=False,
        contract_kwargs=contract_kwargs or None,
    )


def _sweep_error(api, shipper_id, error_id, status, **params):
    """Run a sweep that must be refused, and return the error payload."""
    return validate_error(
        api.create_invoice(
            invoice_sweep_payload(shipper_id, **params), BILLING_OPS_HEADERS
        ),
        error_id,
        status,
    )


def _lines(api, **params):
    """Page invoice lines through the billing desk's own view."""
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(api.list_invoice_lines(BILLING_OPS_HEADERS, query))


def test_01_the_sweep_leaves_behind_the_moving_the_flagged_and_the_wrong_day(api):
    """Four identical-priced parcels, and only two of them ever reach an invoice.

    One parcel is delivered inside the period and bills. One never leaves
    transit. One is flagged by a scanner variance landing exactly on the five
    percent line and stays unbillable even after it is delivered. One is picked
    up a day later and needs its own period to be swept. The two that miss are
    still visible as UNBILLED and the account's counts split two and two.

    PRD §3.6: "The ordinary candidate set is every shipment of the requesting shipper that satisfies four conditions simultaneously: `billing_status` is `UNBILLED`; `measurement_status` is `PENDING_SCAN`, `SCANNED`, or `VERIFIED`, which excludes `TOLERANCE_FLAGGED`; `movement_status` is `DELIVERED`, `UNDELIVERABLE`, or `REFUSED`, which excludes `IN_TRANSIT`; and `pickup_date` falls on or after `period_start` and on or before `period_end`, both ends inclusive."
    PRD §3.4: "The scan breaches on cube when `dim_variance_pct` is greater than or equal to 5.00 percent, and it breaches on weight when `weight_variance_lbs` is greater than or equal to the weight allowance."
    PRD §3.4: "While a shipment sits at `TOLERANCE_FLAGGED` it is excluded from billing sweeps entirely, and naming it directly in a sweep is rejected with `ERR_SCAN_TOLERANCE_UNRESOLVED`."
    PRD §3.6: "Every swept package moves `UNBILLED → BILLED` on the billing axis, and the owning account's `unbilled_shipment_count` falls by the line count while `billed_shipment_count` rises by the same amount, preserving the conserved-package-count invariant of §2.11."
    PRD §3.3: "Shipments can be read individually, returning both weight variants, the tolerance verdict, and all three status axes; and listed with optional filters on `shipper_id`, `service_level_id`, `contract_id`, `measurement_status`, `movement_status`, and `billing_status`."

    Design: Corner/calculations/the_sweep_filters_out_in_transit_flagged_and_out_of_period_parcels
    """
    shipper = _acme(api)
    delivered = delivered_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-B-0001", **SMALL_PARCEL
    )
    in_transit = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-B-0002", **SMALL_PARCEL
    )
    assert in_transit.shipment["movement_status"] == "IN_TRANSIT", (
        "an inducted parcel opens on the movement axis at IN_TRANSIT, got "
        f"{in_transit.shipment['movement_status']}"
    )

    # Declared 10 x 10 x 20 cubes to 2000 in3; a scan at 10 x 10 x 21 cubes to
    # 2100, so the variance is exactly 100 * 100 / 2000 = 5.00 percent.
    flagged = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-B-0003",
        zone=2,
        residential_declared=False,
        declared_length_in=10,
        declared_width_in=10,
        declared_height_in=20,
        declared_weight_lbs=30.0,
    )
    scan = add_scan(
        api,
        flagged.shipment_id,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    assert_pct(scan["dim_variance_pct"], 5.00, "dim_variance_pct")
    assert scan["tolerance_status"] == "EXCEEDS_TOLERANCE", (
        "a variance landing exactly on 5.00 percent is a breach, got "
        f"{scan['tolerance_status']}"
    )
    get_success_data(api.deliver_shipment(flagged.shipment_id, CARRIER_OPS_HEADERS))
    flagged_now = refresh_shipment(api, flagged.shipment_id)
    assert_fields(
        flagged_now,
        {"measurement_status": "TOLERANCE_FLAGGED", "movement_status": "DELIVERED"},
    )

    # A day later the clock moves, so this parcel's pickup_date is 2026-08-02.
    set_clock(api, SECOND_DAY_INSTANT)
    next_day = delivered_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-B-0004", **SMALL_PARCEL
    )
    assert next_day.shipment["pickup_date"] == "2026-08-02", (
        f"the later parcel must sit on 2026-08-02, got {next_day.shipment['pickup_date']}"
    )

    first_day = open_invoice(
        api,
        shipper,
        [delivered.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    assert first_day.invoice["line_count"] == 1, (
        "only the delivered, unflagged, in-period parcel may be swept, got "
        f"line_count {first_day.invoice['line_count']}"
    )
    assert_money_equals(
        first_day.invoice["transportation_subtotal_cents"],
        TRANSPORTATION_CENTS,
        "first-day transportation subtotal",
    )
    assert list(first_day.line_by_shipment) == [delivered.shipment_id], (
        "the single line must belong to 1Z-B-0001, got "
        f"{list(first_day.line_by_shipment)}"
    )

    second_day = open_invoice(
        api,
        shipper,
        [next_day.shipment_id],
        period_start="2026-08-02",
        period_end="2026-08-02",
    )
    assert second_day.invoice["line_count"] == 1, (
        "the second period picks up exactly the parcel inducted that day, got "
        f"line_count {second_day.invoice['line_count']}"
    )
    assert_money_equals(
        second_day.invoice["transportation_subtotal_cents"],
        TRANSPORTATION_CENTS,
        "second-day transportation subtotal",
    )
    assert list(second_day.line_by_shipment) == [next_day.shipment_id], (
        f"the second line must belong to 1Z-B-0004, got {list(second_day.line_by_shipment)}"
    )

    unbilled_rows, unbilled_meta = validate_paginated(
        api.list_shipments(
            CARRIER_OPS_HEADERS,
            {
                "shipper_id": shipper.shipper_id,
                "billing_status": "UNBILLED",
                "limit": 100,
            },
        )
    )
    assert unbilled_meta["total_count"] == 2, (
        "the moving parcel and the flagged parcel are the two survivors, got "
        f"total_count {unbilled_meta['total_count']}"
    )
    assert set(ids_of(unbilled_rows)) == {in_transit.shipment_id, flagged.shipment_id}, (
        "the UNBILLED filter must return 1Z-B-0002 and 1Z-B-0003, got "
        f"{sorted(row['tracking_number'] for row in unbilled_rows)}"
    )

    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id), total=4, unbilled=2, billed=2
    )


def test_02_naming_a_parcel_lifts_the_date_gate_but_never_the_billed_gate(api):
    """The include list reaches across periods, and stops dead at a billed parcel.

    A parcel picked up on 2026-08-05 is dragged into a sweep of 2026-08-01
    purely by being named, which proves the date gate is lifted. The same
    mechanism then fails on the parcel already sitting on a line: naming it back
    is a conflict, not a second bill. With nothing left to sweep, a period
    holding no candidates at all is refused outright.

    PRD §3.6: "A named package joins the sweep even when its `pickup_date` falls outside the period and even when its `movement_status` is still `IN_TRANSIT` — naming it lifts the date gate and the movement gate."
    PRD §3.6: "Naming never lifts the other two gates, however: a named package whose `billing_status` has already left `UNBILLED` — that is, one already sitting on a line of a non-void invoice — is rejected with `ERR_SHIPMENT_ALREADY_BILLED` (HTTP 409), and a named package whose `measurement_status` is `TOLERANCE_FLAGGED` is rejected with `ERR_SCAN_TOLERANCE_UNRESOLVED` (HTTP 409)."
    PRD §3.6: "If the combined selection is empty, the whole request is rejected with `ERR_NO_BILLABLE_SHIPMENTS` (HTTP 422)."
    PRD §3.3: "The server stamps `picked_up_at` from the logical clock and derives `pickup_date` as the UTC calendar date of that instant."

    Design: Corner/endpoints/the_include_list_extends_the_sweep_but_never_lifts_the_billed_gate
    """
    shipper = _acme(api)
    early = delivered_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-E-6001", **SMALL_PARCEL
    )
    set_clock(api, FIFTH_DAY_INSTANT)
    late = delivered_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-E-6002", **SMALL_PARCEL
    )
    assert early.shipment["pickup_date"] == "2026-08-01", (
        f"1Z-E-6001 must sit on 2026-08-01, got {early.shipment['pickup_date']}"
    )
    assert late.shipment["pickup_date"] == "2026-08-05", (
        f"1Z-E-6002 must sit on 2026-08-05, got {late.shipment['pickup_date']}"
    )

    ordinary = open_invoice(
        api,
        shipper,
        [early.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    assert ordinary.invoice["line_count"] == 1, (
        "the ordinary candidate set holds only the in-period parcel, got "
        f"line_count {ordinary.invoice['line_count']}"
    )
    assert_money_equals(
        ordinary.invoice["net_amount_cents"], TRANSPORTATION_CENTS, "ordinary sweep net"
    )
    assert list(ordinary.line_by_shipment) == [early.shipment_id], (
        f"the first invoice must bill 1Z-E-6001, got {list(ordinary.line_by_shipment)}"
    )

    # The same one-day period, but now naming the parcel picked up four days
    # later: the date gate lifts for it, while the already-billed parcel that
    # the ordinary scan would have caught has left UNBILLED and drops out.
    named = open_invoice(
        api,
        shipper,
        [late.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
        include_shipment_ids=[late.shipment_id],
    )
    assert named.invoice["line_count"] == 1, (
        "naming one out-of-period parcel yields exactly one line, got "
        f"line_count {named.invoice['line_count']}"
    )
    assert_money_equals(
        named.invoice["net_amount_cents"], TRANSPORTATION_CENTS, "named sweep net"
    )
    assert list(named.line_by_shipment) == [late.shipment_id], (
        f"the second invoice must bill 1Z-E-6002, got {list(named.line_by_shipment)}"
    )

    _sweep_error(
        api,
        shipper.shipper_id,
        ERR_SHIPMENT_ALREADY_BILLED,
        409,
        period_start="2026-08-09",
        period_end="2026-08-09",
        include_shipment_ids=[early.shipment_id],
    )
    _sweep_error(
        api,
        shipper.shipper_id,
        ERR_NO_BILLABLE_SHIPMENTS,
        422,
        period_start="2026-08-09",
        period_end="2026-08-09",
    )

    invoice_rows, invoice_meta = validate_paginated(
        api.list_invoices(
            BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 100}
        )
    )
    assert invoice_meta["total_count"] == 2, (
        "the two refused sweeps must have created nothing, got total_count "
        f"{invoice_meta['total_count']}"
    )
    assert [row["status"] for row in invoice_rows] == ["OPEN", "OPEN"], (
        f"both surviving invoices stay OPEN, got {[row['status'] for row in invoice_rows]}"
    )
    assert set(ids_of(invoice_rows)) == {ordinary.invoice_id, named.invoice_id}, (
        "the listing must hold exactly the two invoices the sweeps created"
    )

    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id), total=2, unbilled=0, billed=2
    )


def test_03_one_unpriceable_parcel_takes_the_whole_sweep_down_with_it(api):
    """A rate table that cannot price one candidate bills none of them.

    The contract prices zone 2 and tiles that zone's whole weight range, so the
    only parcel it cannot price is one rated for a zone its table never names.
    One such parcel among two delivered candidates is enough: the preview of the
    priceable parcel answers normally, the preview of the other refuses, and the
    sweep that would have billed both refuses as a unit, leaving no invoice, no
    line and two still-unbilled packages behind.

    PRD §3.1: "The `rate_table` is an array of rows, each carrying a `zone`, a `min_lbs`, a `max_lbs`, and a `cents_per_lb`; the rows belonging to any one zone must tile the weight range from 1 through 9999 pounds with no gaps and no overlaps."
    PRD §3.6: "The server finds the single row of that contract's `rate_table` whose `zone` equals the shipment's `zone` and whose weight band contains the line's billable pound count — that is, the pound count is greater than or equal to `min_lbs` and less than or equal to `max_lbs`."
    PRD §3.6: "Because a zone's rows tile 1 through 9999 pounds, exactly one row matches; a contract whose table has no covering row is a data error and the request is rejected with `ERR_RATE_ROW_MISSING` (HTTP 422)."
    PRD §3.6: "The preview creates nothing and mutates nothing; it returns `shipment_id`, `contract_id`, `billable_weight_lbs`, `billable_weight_basis`, `rate_cents_per_lb`, `transportation_base_cents`, `surcharge_cents`, `accessorial_total_cents`, and `line_total_cents`, computed by exactly the line-pricing rules above."
    PRD §3.6: "Like the sweep, it fails with `ERR_RATE_ROW_MISSING` when the governing contract has no covering rate row, and with `ERR_SHIPMENT_NOT_FOUND` for an unknown package."

    Design: Corner/validations/a_single_unpriceable_parcel_rejects_the_whole_sweep
    """
    shipper = _acme(api)
    priceable = delivered_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-R-8001", **SMALL_PARCEL
    )
    # 20 x 20 x 20 at 40.0 lb cubes to 8000 in3 and bills at 58 dimensional
    # pounds - a perfectly ordinary weight, rated for a zone this contract
    # never priced.
    unpriceable = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-R-8002",
        zone=5,
        residential_declared=False,
        declared_length_in=20,
        declared_width_in=20,
        declared_height_in=20,
        declared_weight_lbs=40.0,
    )
    assert_lbs(unpriceable.shipment["billable_weight_lbs"], 58, "1Z-R-8002 billable weight")
    assert unpriceable.shipment["preliminary_basis"] == "DIMENSIONAL", (
        "the unpriceable parcel is a dimensional one, got "
        f"{unpriceable.shipment['preliminary_basis']}"
    )

    good_preview = get_success_data(
        api.get_billing_preview(priceable.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_fields(
        good_preview,
        {
            "shipment_id": priceable.shipment_id,
            "contract_id": shipper.contract_id,
            "billable_weight_basis": "DIMENSIONAL",
            "rate_cents_per_lb": 380,
        },
    )
    assert_money_equals(
        good_preview["line_total_cents"], TRANSPORTATION_CENTS, "1Z-R-8001 preview total"
    )

    validate_error(
        api.get_billing_preview(unpriceable.shipment_id, BILLING_OPS_HEADERS),
        ERR_RATE_ROW_MISSING,
        422,
    )
    _sweep_error(
        api,
        shipper.shipper_id,
        ERR_RATE_ROW_MISSING,
        422,
        period_start="2026-08-01",
        period_end="2026-08-01",
    )

    _, invoice_meta = validate_paginated(
        api.list_invoices(
            BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 100}
        )
    )
    assert invoice_meta["total_count"] == 0, (
        "a refused sweep must leave no invoice behind, got total_count "
        f"{invoice_meta['total_count']}"
    )
    _, line_meta = _lines(api)
    assert line_meta["total_count"] == 0, (
        f"no line may survive the refusal, got total_count {line_meta['total_count']}"
    )

    for label, shipment_id in (
        ("1Z-R-8001", priceable.shipment_id),
        ("1Z-R-8002", unpriceable.shipment_id),
    ):
        current = refresh_shipment(api, shipment_id)
        assert current["billing_status"] == "UNBILLED", (
            f"{label} must still be sweepable, got {current['billing_status']}"
        )

    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id), total=2, unbilled=2, billed=0
    )


def test_04_suspension_closes_the_door_without_touching_what_is_inside(api):
    """A suspended account still delivers and still bills its parcel in flight.

    Suspension is deliberately narrow: the second induction is refused, but the
    package inducted a moment earlier keeps moving, reaches DELIVERED and is
    swept onto an invoice for its full 2660 cents. The account's package count
    stays at one throughout, because the refused induction created nothing.

    PRD §3.1: "Suspension is deliberately narrow in effect: no shipment, invoice, dispute, or claim record is touched, and every workflow already in flight runs to completion."
    PRD §3.1: "The only thing suspension blocks is new package induction, which is refused with `ERR_SHIPPER_SUSPENDED` (HTTP 409) while the account's `status` is `SUSPENDED`."
    PRD §3.1: "The suspension itself increments the account's `version` by 1."
    PRD §3.3: "A `shipper_id` that resolves to nothing is `ERR_SHIPPER_NOT_FOUND`, an unknown `service_level_id` is `ERR_SERVICE_LEVEL_NOT_FOUND`, and a suspended account is `ERR_SHIPPER_SUSPENDED`."
    PRD §3.3: "The owning account's `total_shipment_count` and `unbilled_shipment_count` each increase by 1, and `open_charges_cents` is recomputed."

    Design: Corner/validations/a_suspended_shipper_cannot_induct_a_new_parcel
    """
    shipper = _acme(api)
    in_flight = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-S-1001", **SMALL_PARCEL
    )
    assert in_flight.shipment["movement_status"] == "IN_TRANSIT", (
        "the parcel must still be in flight when the account closes, got "
        f"{in_flight.shipment['movement_status']}"
    )

    suspended = suspend_shipper_account(api, shipper.shipper_id)
    assert suspended["status"] == "SUSPENDED", (
        f"the account must reach SUSPENDED, got {suspended['status']}"
    )
    assert suspended["version"] == shipper.shipper_version + 1, (
        "suspension bumps the account version exactly once, from "
        f"{shipper.shipper_version} to {suspended['version']}"
    )

    validate_error(
        api.create_shipment(
            shipment_payload(
                shipper.shipper_id,
                shipper.service_level_ids["EXPRESS"],
                tracking_number="1Z-S-1002",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        ERR_SHIPPER_SUSPENDED,
        409,
    )

    rows, meta = validate_paginated(
        api.list_shipments(
            CARRIER_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused induction must have created nothing, got {meta['total_count']}"
    )
    assert rows[0]["tracking_number"] == "1Z-S-1001", (
        f"only the pre-suspension parcel may exist, got {rows[0]['tracking_number']}"
    )

    get_success_data(api.deliver_shipment(in_flight.shipment_id, CARRIER_OPS_HEADERS))
    delivered = refresh_shipment(api, in_flight.shipment_id)
    assert delivered["movement_status"] == "DELIVERED", (
        "a workflow already in flight runs to completion, got "
        f"{delivered['movement_status']}"
    )

    invoice = open_invoice(
        api,
        shipper,
        [in_flight.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    assert invoice.invoice["line_count"] == 1, (
        "a suspended account is still billable, got line_count "
        f"{invoice.invoice['line_count']}"
    )
    assert_money_equals(
        invoice.invoice["net_amount_cents"], TRANSPORTATION_CENTS, "post-suspension net"
    )

    account = refresh_shipper_account(api, shipper.shipper_id)
    assert account["status"] == "SUSPENDED", (
        f"suspension is terminal, got {account['status']}"
    )
    assert_ledger(account, total=1, unbilled=0, billed=1)


def test_05_a_discount_worth_exactly_half_a_cent_rounds_up_once(api):
    """2766.5 cents of tier discount becomes 2767, not 2766.

    A demand surcharge of 585 cents lifts the transportation subtotal to 50300,
    just past the tier break, and 550 basis points of 50300 is exactly 2766.5
    cents. The half cent rounds up, and it rounds up once on the summed subtotal
    rather than per line: the invoice nets 60033 while its single line still
    carries its own untouched 62800.

    PRD §3.6: "The per-package floor then applies **to the transportation charge alone, and before any surcharge**: `transportation_base_cents` is the greater of the uncapped charge and the governing contract's `min_charge_cents`."
    PRD §3.6: "For each qualifying window the line accrues that window's `per_package_cents`, plus that window's `oversize_add_cents` when and only when the shipment carries an `ASSESSED` accessorial charge with code `OVERSIZE`."
    PRD §3.6: "`transportation_subtotal_cents` is the sum, over the invoice's lines, of `transportation_base_cents` plus `surcharge_cents`."
    PRD §3.6: "The chosen row is the row of the contract's `tier_discount_table` with the greatest `min_transportation_subtotal_cents` that is less than or equal to `transportation_subtotal_cents`, so a subtotal landing exactly on a threshold qualifies for that threshold's tier."
    PRD §3.6: "`tier_discount_cents` is computed **once** on the summed subtotal: `transportation_subtotal_cents` multiplied by `tier_discount_bps`, divided by 10000, and rounded half up to a whole cent."
    PRD §3.6: "`net_amount_cents` is `gross_charges_cents` minus `tier_discount_cents` plus `adjustment_total_cents`."

    Design: Corner/calculations/the_tier_discount_rounds_half_up_on_an_exact_half_cent
    """
    shipper = _acme(api, tier_discount_table=list(FULL_TIER_TABLE))
    window = active_surcharge_window(
        api,
        code="DEM-A",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-02",
        per_package_cents=585,
        oversize_add_cents=0,
    )
    assert window["status"] == "ACTIVE", (
        f"only an ACTIVE window prices anything, got {window['status']}"
    )

    # 47 x 24 x 20 cubes to 22560 in3, so the dimensional pound count is 163;
    # length-plus-girth is 47 + 2 * 44 = 135 in, which trips oversize.
    parcel = delivered_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-P-0500", **BIG_PARCEL
    )
    assert_fields(
        parcel.shipment,
        {
            "declared_cube_in3": 22560,
            "oversize_flag": True,
            "additional_handling_flag": False,
            "preliminary_basis": "DIMENSIONAL",
        },
    )
    assert_lbs(parcel.shipment["billable_weight_lbs"], 163, "1Z-P-0500 billable weight")

    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    line = refresh_invoice_line(api, invoice.line_by_shipment[parcel.shipment_id])
    assert_fields(
        line,
        {
            "billable_weight_lbs": 163,
            "billable_weight_basis": "DIMENSIONAL",
            "rate_cents_per_lb": 305,
        },
    )
    for field, expected in (
        ("transportation_base_cents", BIG_TRANSPORTATION_CENTS),
        ("surcharge_cents", 585),
        ("accessorial_total_cents", OVERSIZE_CENTS),
        ("base_line_total_cents", 62800),
        ("adjustment_total_cents", 0),
        ("line_total_cents", 62800),
    ):
        assert_money_equals(line[field], expected, f"line {field}")

    # 50300 * 550 / 10000 is 2766.5 exactly, which rounds half up to 2767.
    for field, expected in (
        ("transportation_subtotal_cents", 50300),
        ("accessorial_subtotal_cents", OVERSIZE_CENTS),
        ("gross_charges_cents", 62800),
        ("tier_discount_cents", 2767),
        ("net_amount_cents", 60033),
    ):
        assert_money_equals(invoice.invoice[field], expected, f"invoice {field}")
    assert invoice.invoice["tier_discount_bps"] == 550, (
        f"a 50300-cent subtotal earns the 550 bps tier, got "
        f"{invoice.invoice['tier_discount_bps']}"
    )
    assert invoice.invoice["line_count"] == 1, (
        f"one parcel makes one line, got {invoice.invoice['line_count']}"
    )


def test_06_one_cent_decides_whether_a_tier_is_earned_at_all(api):
    """50000 cents of subtotal earns 550 bps; 49999 earns nothing.

    Two shippers hold identical contracts and identical parcels, and the only
    difference is a demand surcharge of 285 cents against 284. That single cent
    lands one subtotal exactly on the threshold and the other one cent short, so
    one invoice takes a 2750-cent discount and the other takes none. The upper
    250000-cent tier is never in reach for either.

    PRD §3.6: "The candidate windows are every surcharge window whose `status` is `ACTIVE`, whose half-open range contains the shipment's `pickup_date` — meaning the date is on or after `start_date` and strictly before `end_date` — and whose scope matches, meaning either `service_level_id` is null or it equals the shipment's `service_level_id`."
    PRD §3.6: "The tier row is selected by reading **step 1 only** — the pre-discount transportation subtotal."
    PRD §3.6: "The chosen row is the row of the contract's `tier_discount_table` with the greatest `min_transportation_subtotal_cents` that is less than or equal to `transportation_subtotal_cents`, so a subtotal landing exactly on a threshold qualifies for that threshold's tier."
    PRD §3.6: "When no row qualifies, `tier_discount_bps` is 0."
    PRD §3.6: "`gross_charges_cents` is the sum, over those lines, of `base_line_total_cents` — which is necessarily step 1 plus step 2."

    Design: Corner/calculations/the_tier_row_is_inclusive_at_its_break_and_one_cent_below_earns_nothing
    """
    on_break = _acme(api, tier_discount_table=list(FULL_TIER_TABLE))
    below_break = _borealis(api, tier_discount_table=list(FULL_TIER_TABLE))
    active_surcharge_window(
        api,
        code="DEM-EXP",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-02",
        per_package_cents=285,
        oversize_add_cents=0,
        service_level_id=on_break.service_level_ids["EXPRESS"],
    )
    active_surcharge_window(
        api,
        code="DEM-GRD",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-02",
        per_package_cents=284,
        oversize_add_cents=0,
        service_level_id=below_break.service_level_ids["GROUND"],
    )

    express_parcel = delivered_shipment(
        api,
        on_break,
        service_level="EXPRESS",
        tracking_number="1Z-Q-0001",
        **BIG_PARCEL,
    )
    ground_parcel = delivered_shipment(
        api,
        below_break,
        service_level="GROUND",
        tracking_number="1Z-Q-0002",
        **BIG_PARCEL,
    )
    for label, parcel in (("1Z-Q-0001", express_parcel), ("1Z-Q-0002", ground_parcel)):
        assert_lbs(parcel.shipment["billable_weight_lbs"], 163, f"{label} billable weight")
        assert parcel.shipment["oversize_flag"] is True, (
            f"{label} must be oversize on length-plus-girth, got "
            f"{parcel.shipment['oversize_flag']}"
        )

    express_invoice = open_invoice(
        api,
        on_break,
        [express_parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    ground_invoice = open_invoice(
        api,
        below_break,
        [ground_parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )

    # 49715 of transportation plus 285 of surcharge is exactly the 50000 break;
    # plus 284 it is 49999, one cent short of any tier at all.
    for field, expected in (
        ("transportation_subtotal_cents", 50000),
        ("accessorial_subtotal_cents", OVERSIZE_CENTS),
        ("gross_charges_cents", 62500),
        ("tier_discount_cents", 2750),
        ("net_amount_cents", 59750),
    ):
        assert_money_equals(express_invoice.invoice[field], expected, f"on-break {field}")
    for field, expected in (
        ("transportation_subtotal_cents", 49999),
        ("accessorial_subtotal_cents", OVERSIZE_CENTS),
        ("gross_charges_cents", 62499),
        ("tier_discount_cents", 0),
        ("net_amount_cents", 62499),
    ):
        assert_money_equals(ground_invoice.invoice[field], expected, f"below-break {field}")

    assert express_invoice.invoice["tier_discount_bps"] == 550, (
        "a subtotal landing exactly on 50000 qualifies for that threshold, got "
        f"{express_invoice.invoice['tier_discount_bps']}"
    )
    assert ground_invoice.invoice["tier_discount_bps"] == 0, (
        "one cent below the break no row qualifies, got "
        f"{ground_invoice.invoice['tier_discount_bps']}"
    )
    for label, invoice in (("on-break", express_invoice), ("below-break", ground_invoice)):
        assert invoice.invoice["line_count"] == 1, (
            f"{label} invoice must hold one line, got {invoice.invoice['line_count']}"
        )
        assert invoice.invoice["tier_discount_bps"] != 1250, (
            f"{label} invoice must never reach the 250000-cent tier, got "
            f"{invoice.invoice['tier_discount_bps']}"
        )


def test_07_the_credit_ceiling_is_the_invoice_net_not_the_line_it_targets(api):
    """Two full-line credits land; the third is legal on its line and still refused.

    Three lines of 62215 gross 186645, but the 8203-cent tier discount means the
    invoice only ever nets 178442. Two credits of 62215 each are affordable, and
    the third — exactly its own line's total, so the line-level ceiling passes at
    equality — would drive the invoice to -8203 and is refused. The money that
    is missing is precisely the discount.

    PRD §3.6: "`tier_discount_cents` is computed **once** on the summed subtotal: `transportation_subtotal_cents` multiplied by `tier_discount_bps`, divided by 10000, and rounded half up to a whole cent."
    PRD §3.7: "The owning account's `open_charges_cents` rises by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1."
    PRD §3.8: "Fifth and last come the two fiscal ceilings, which apply only to credits: for a credit, the credit's magnitude must not exceed the target line's current `line_total_cents`, else `ERR_ADJUSTMENT_EXCEEDS_LINE` (HTTP 422); and the invoice's `net_amount_cents` plus the `delta_cents` must be at least 0, so a credit may never push an invoice negative, else `ERR_CREDIT_EXCEEDS_INVOICE_NET` (HTTP 422)."
    PRD §3.8: "*Hop 2* — because the line moved, the invoice's `adjustment_total_cents` and `net_amount_cents` are recomputed and its `status` moves to `ADJUSTED`."
    PRD §2.11: "`credit_balance_cents` — the negated sum of `delta_cents` over every `BillingAdjustment` whose status is `APPLIED` and which hangs off an invoice line of one of this account's invoices whose status is not `VOID`."
    PRD §2.11: "`open_charges_cents` — the sum of `net_amount_cents` over this account's invoices whose status is either `ISSUED` or `ADJUSTED`."

    Design: Corner/validations/a_credit_may_never_push_the_invoice_net_below_zero
    """
    shipper = _acme(api, tier_discount_table=list(FULL_TIER_TABLE))
    parcels = [
        delivered_shipment(
            api, shipper, service_level="EXPRESS", tracking_number=tracking, **BIG_PARCEL
        )
        for tracking in ("1Z-A-6001", "1Z-A-6002", "1Z-A-6003")
    ]
    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id for parcel in parcels],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    lines = [invoice.line_by_shipment[parcel.shipment_id] for parcel in parcels]
    for label, line_id in zip(("1Z-A-6001", "1Z-A-6002", "1Z-A-6003"), lines):
        assert_money_equals(
            refresh_invoice_line(api, line_id)["line_total_cents"],
            62215,
            f"{label} line total",
        )

    # 149145 * 550 / 10000 is 8202.975, which rounds half up to 8203.
    issued = issued_invoice(api, invoice)
    assert_fields(issued.invoice, {"status": "ISSUED", "line_count": 3, "tier_discount_bps": 550})
    for field, expected in (
        ("transportation_subtotal_cents", 149145),
        ("accessorial_subtotal_cents", 3 * OVERSIZE_CENTS),
        ("gross_charges_cents", 186645),
        ("tier_discount_cents", 8203),
        ("net_amount_cents", 178442),
    ):
        assert_money_equals(issued.invoice[field], expected, f"issued {field}")
    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id), open_charges_cents=178442
    )

    first = propose_adjustment(
        api,
        issued,
        lines[0],
        -62215,
        expected_invoice_version=issued.invoice_version,
    )
    apply_adjustment(api, first)
    after_first = refresh_invoice(api, invoice.invoice_id)
    assert_money_equals(after_first["net_amount_cents"], 116227, "net after one credit")
    assert after_first["status"] == "ADJUSTED", (
        f"the first application moves the invoice to ADJUSTED, got {after_first['status']}"
    )

    second = propose_adjustment(
        api,
        issued,
        lines[1],
        -62215,
        expected_invoice_version=after_first["version"],
    )
    apply_adjustment(api, second)
    after_second = refresh_invoice(api, invoice.invoice_id)
    assert_money_equals(after_second["net_amount_cents"], 54012, "net after two credits")

    # 62216 exceeds the third line's own 62215 total, so the line-level ceiling
    # fires before the invoice-level one is ever reached.
    validate_error(
        api.create_billing_adjustment(
            billing_adjustment_payload(lines[2], -62216, after_second["version"]),
            BILLING_OPS_HEADERS,
        ),
        ERR_ADJUSTMENT_EXCEEDS_LINE,
        422,
    )
    # 62215 passes the line check at equality, and then 54012 - 62215 = -8203
    # fails the invoice-net check.
    validate_error(
        api.create_billing_adjustment(
            billing_adjustment_payload(lines[2], -62215, after_second["version"]),
            BILLING_OPS_HEADERS,
        ),
        ERR_CREDIT_EXCEEDS_INVOICE_NET,
        422,
    )

    final = refresh_invoice(api, invoice.invoice_id)
    assert_money_equals(final["net_amount_cents"], 54012, "net after both refusals")
    assert_fields(
        final,
        {
            "status": "ADJUSTED",
            "pending_adjustment_count": 0,
            "has_pending_adjustments": False,
        },
    )
    assert_money_equals(final["gross_charges_cents"], 186645, "frozen gross charges")
    assert_money_equals(final["tier_discount_cents"], 8203, "frozen tier discount")

    rows, meta = validate_paginated(
        api.list_billing_adjustments(BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 2, (
        "only the two affordable credits may exist, got total_count "
        f"{meta['total_count']}"
    )
    assert [row["status"] for row in rows] == ["APPLIED", "APPLIED"], (
        f"both surviving adjustments are APPLIED, got {[row['status'] for row in rows]}"
    )
    assert set(ids_of(rows)) == {first.adjustment_id, second.adjustment_id}, (
        "the register must hold exactly the two credits that were released"
    )

    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id),
        total=3,
        unbilled=0,
        billed=3,
        credit_balance_cents=124430,
        open_charges_cents=54012,
    )
