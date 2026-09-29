"""Tenths of a pound, tenths of an inch, and the money they move.

Every constant in the rating engine is a strict comparison, and this file
proves it by twinning parcels that differ by the smallest legal step. Fifty
pounds exactly earns nothing while 50.1 lb earns a handling charge; 48.4
inches rounds down and stays quiet while 48.5 rounds up and does not; and
five inches of length past the eight-foot mark swaps one accessorial for
another, engages the ninety-pound floor and jumps the rate row all at once.
The file closes on the two baselines those thresholds are measured against: an
induction where every gate stays silent, and a parcel that is never scanned
and therefore bills on its declared measurements from end to end.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    assert_fields,
    assert_instant,
    assert_lbs,
    assert_ledger,
    assert_money_equals,
    assert_null_fields,
    find_row,
    get_success_data,
    induct_shipment,
    open_invoice,
    refresh_invoice_line,
    refresh_shipment,
    refresh_shipper_account,
    shipment_payload,
    shipper_with_active_contract,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

AH_CENTS = 2450
OVERSIZE_CENTS = 12500

CLOCK_INSTANT = "2026-08-01T00:00:00Z"


def _acme(api):
    """SH-2001 holding one ACTIVE EXPRESS-only contract with no overrides."""
    return shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )


def _preview(api, shipment_id):
    """The billing desk's dry run of one parcel's price."""
    return get_success_data(api.get_billing_preview(shipment_id, BILLING_OPS_HEADERS))


def _charges(api, shipment_id):
    """Page one parcel's accessorial charges, keeping the envelope meta."""
    return validate_paginated(
        api.list_accessorials(shipment_id, BILLING_OPS_HEADERS, {"limit": 100})
    )


def test_01_fifty_pounds_exactly_earns_no_handling_charge_and_50_1_lb_does(api):
    """The additional-handling weight constant is a strict greater-than.

    Two 20 x 20 x 20 parcels both bill at 58 dimensional pounds, so their
    transportation charge is identical to the cent. The only difference is a
    tenth of a pound across the fifty-pound line, and the whole 2450-cent gap
    in the two previews is that comparison and nothing else.

    PRD §3.3: "The `additional_handling_flag` is set true only when `oversize_flag` is false and at least one of three conditions holds: the governing scale weight strictly exceeds 50 pounds, the longest dimension strictly exceeds 48 inches — four feet — or the package is marked non-conveyable."
    PRD §3.3: "`OVERSIZE` is assessed when `oversize_flag` is true, and `ADDITIONAL_HANDLING` when `additional_handling_flag` is true."
    PRD §3.3: "Otherwise the carrier default applies: $5.90 for `RESIDENTIAL`, $125.00 for `OVERSIZE`, $24.50 for `ADDITIONAL_HANDLING`, $22.00 for `ADDRESS_CORRECTION`, $18.00 for `RETURN_UNDELIVERABLE`, and $13.50 for `REFUSAL`."
    PRD §3.3: "2. The dimensional pound count is the cube divided by `divisor_used` as an exact rational division, and the quotient is then taken up to the next whole pound whenever any fraction remains."
    PRD §3.6: "The server finds the single row of that contract's `rate_table` whose `zone` equals the shipment's `zone` and whose weight band contains the line's billable pound count — that is, the pound count is greater than or equal to `min_lbs` and less than or equal to `max_lbs`."

    Design: Corner/calculations/the_additional_handling_weight_constant_is_a_strict_threshold
    """
    shipper = _acme(api)
    cube = {
        "zone": 2,
        "residential_declared": False,
        "declared_length_in": 20,
        "declared_width_in": 20,
        "declared_height_in": 20,
    }
    at_threshold = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-H-0001",
        declared_weight_lbs=50.0,
        **cube,
    )
    over_threshold = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-H-0002",
        declared_weight_lbs=50.1,
        **cube,
    )

    # 20 x 20 x 20 cubes to 8000 in3, and 8000 / 139 = 57.55 taken up to the
    # next whole pound is 58 - which beats both parcels' actual weight.
    for label, parcel in (
        ("1Z-H-0001", at_threshold.shipment),
        ("1Z-H-0002", over_threshold.shipment),
    ):
        assert_fields(
            parcel,
            {
                "tracking_number": label,
                "declared_cube_in3": 8000,
                "oversize_flag": False,
                "preliminary_basis": "DIMENSIONAL",
            },
        )
        assert_lbs(parcel["billable_weight_lbs"], 58, f"{label} billable weight")

    assert at_threshold.shipment["additional_handling_flag"] is False, (
        "50.0 lb is not strictly greater than the fifty-pound constant"
    )
    assert over_threshold.shipment["additional_handling_flag"] is True, (
        "50.1 lb clears the fifty-pound constant"
    )

    # The parcel that stayed under the line carries nothing at all.
    quiet_rows, quiet_meta = _charges(api, at_threshold.shipment_id)
    assert quiet_meta["total_count"] == 0, (
        f"the 50.0 lb parcel should carry no charge, got {quiet_rows}"
    )
    quiet_preview = _preview(api, at_threshold.shipment_id)
    assert_fields(quiet_preview, {"rate_cents_per_lb": 340})
    assert_lbs(quiet_preview["billable_weight_lbs"], 58, "preview billable weight")
    assert_money_equals(
        quiet_preview["transportation_base_cents"], 19720, "58 lb at 340"
    )
    assert_money_equals(quiet_preview["accessorial_total_cents"], 0, "quiet accessorials")
    assert_money_equals(quiet_preview["line_total_cents"], 19720, "quiet line total")

    # Its twin carries exactly one charge, at the carrier default rate.
    loud_rows, loud_meta = _charges(api, over_threshold.shipment_id)
    assert loud_meta["total_count"] == 1, (
        f"the 50.1 lb parcel should carry one charge, got {loud_rows}"
    )
    handling = find_row(loud_rows, code="ADDITIONAL_HANDLING")
    assert_fields(handling, {"status": "ASSESSED", "source": "AUTO"})
    assert_money_equals(handling["amount_cents"], AH_CENTS, "handling charge")
    loud_preview = _preview(api, over_threshold.shipment_id)
    assert_fields(loud_preview, {"rate_cents_per_lb": 340})
    assert_money_equals(
        loud_preview["transportation_base_cents"], 19720, "identical transportation"
    )
    assert_money_equals(loud_preview["line_total_cents"], 22170, "loud line total")
    assert (
        loud_preview["line_total_cents"] - quiet_preview["line_total_cents"] == AH_CENTS
    ), "the entire gap between the twins is the one accessorial"


def test_02_the_longest_side_test_reads_the_rounded_inch_not_the_raw_one(api):
    """One tenth of an inch moves the cube and the accessorial together.

    A 48.4-inch side rounds half up to 48 and stays under the four-foot
    handling line; a 48.5-inch side rounds to 49 and trips it. The same
    rounding feeds the cube, so the longer parcel also gains a dimensional
    pound. Both effects must show up, and both from the rounded figure.

    PRD §3.3: "1. Each of the three declared dimensions is individually rounded half up to a whole number of inches."
    PRD §3.3: "It starts from the three rounded whole-inch dimensions of the governing measurement set."
    PRD §3.3: "The `additional_handling_flag` is set true only when `oversize_flag` is false and at least one of three conditions holds: the governing scale weight strictly exceeds 50 pounds, the longest dimension strictly exceeds 48 inches — four feet — or the package is marked non-conveyable."
    PRD §3.3: "Otherwise the basis is `DIMENSIONAL`."
    PRD §3.6: "The per-package floor then applies **to the transportation charge alone, and before any surcharge**: `transportation_base_cents` is the greater of the uncapped charge and the governing contract's `min_charge_cents`."

    Design: Corner/calculations/the_longest_side_threshold_compares_rounded_inches_not_raw_inches
    """
    shipper = _acme(api)
    rounds_down = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-J-0001",
        zone=2,
        residential_declared=False,
        declared_length_in=48.4,
        declared_width_in=10,
        declared_height_in=10,
        declared_weight_lbs=30.0,
    )
    rounds_up = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-J-0002",
        zone=2,
        residential_declared=False,
        declared_length_in=48.5,
        declared_width_in=10,
        declared_height_in=10,
        declared_weight_lbs=30.0,
    )

    # 48.4 rounds to 48 for a 4800 in3 cube; 48.5 rounds half up to 49 for 4900.
    assert_fields(
        rounds_down.shipment,
        {
            "declared_cube_in3": 4800,
            "oversize_flag": False,
            "additional_handling_flag": False,
            "preliminary_basis": "DIMENSIONAL",
        },
    )
    assert_fields(
        rounds_up.shipment,
        {
            "declared_cube_in3": 4900,
            "oversize_flag": False,
            "additional_handling_flag": True,
            "preliminary_basis": "DIMENSIONAL",
        },
    )
    assert_lbs(rounds_down.shipment["billable_weight_lbs"], 35, "4800 in3 over 139")
    assert_lbs(rounds_up.shipment["billable_weight_lbs"], 36, "4900 in3 over 139")

    down_preview = _preview(api, rounds_down.shipment_id)
    assert_fields(down_preview, {"rate_cents_per_lb": 340})
    assert_money_equals(down_preview["transportation_base_cents"], 11900, "35 lb at 340")
    assert_money_equals(down_preview["accessorial_total_cents"], 0, "no charge")
    assert_money_equals(down_preview["line_total_cents"], 11900, "rounded-down total")

    up_preview = _preview(api, rounds_up.shipment_id)
    assert_fields(up_preview, {"rate_cents_per_lb": 340})
    assert_money_equals(up_preview["transportation_base_cents"], 12240, "36 lb at 340")
    assert_money_equals(up_preview["accessorial_total_cents"], AH_CENTS, "one charge")
    assert_money_equals(up_preview["line_total_cents"], 14690, "rounded-up total")

    down_rows, down_meta = _charges(api, rounds_down.shipment_id)
    assert down_meta["total_count"] == 0, (
        f"a rounded 48 inches must assess nothing, got {down_rows}"
    )
    up_rows, up_meta = _charges(api, rounds_up.shipment_id)
    assert up_meta["total_count"] == 1, (
        f"a rounded 49 inches must assess one charge, got {up_rows}"
    )
    handling = find_row(up_rows, code="ADDITIONAL_HANDLING")
    assert_fields(handling, {"status": "ASSESSED", "source": "AUTO"})
    assert_money_equals(handling["amount_cents"], AH_CENTS, "handling charge")


def test_03_five_inches_past_eight_feet_switches_the_whole_pricing_path(api):
    """The eight-foot line swaps the charge, engages the floor and moves the row.

    Three 5.0 lb parcels: 95 inches long, 100 inches long, and a stubby one
    whose length-plus-girth reaches 136 inches. The 95-inch parcel is merely
    awkward and pays handling. The 100-inch parcel is oversize, so handling
    disappears, the ninety-pound floor engages, and the floor itself pushes the
    parcel into a cheaper per-pound row for a far larger bill. The third parcel
    trips the same flag by girth, but its dimensional weight already beats the
    floor, so its basis stays dimensional.

    PRD §3.3: "The `oversize_flag` is set true when the longest dimension strictly exceeds 96 inches — eight feet — or when length-plus-girth strictly exceeds 130 inches."
    PRD §3.3: "Oversize absorbs additional handling: the two flags are mutually exclusive by construction, and a package that trips the oversize geometry never also carries an additional-handling charge."
    PRD §3.3: "4. An oversize floor applies when the geometry test described below trips the shipment's `oversize_flag`: an oversize parcel bills at no fewer than 90 pounds."
    PRD §3.3: "5. The billable weight is the greatest of those three quantities — the actual billable pound count, the dimensional pound count, and the oversize floor — and is written to `preliminary_billable_weight_lbs`."
    PRD §3.3: "When the oversize floor strictly exceeds *both* the actual billable pound count and the dimensional pound count, the basis is `OVERSIZE_FLOOR`."
    PRD §3.6: "The server finds the single row of that contract's `rate_table` whose `zone` equals the shipment's `zone` and whose weight band contains the line's billable pound count — that is, the pound count is greater than or equal to `min_lbs` and less than or equal to `max_lbs`."

    Design: Corner/cross_cutting_complexity_layers/the_ninety_six_inch_threshold_switches_on_a_different_pricing_path
    """
    shipper = _acme(api)
    under = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-X-2001",
        zone=2,
        residential_declared=False,
        declared_length_in=95,
        declared_width_in=6,
        declared_height_in=6,
        declared_weight_lbs=5.0,
    )
    over = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-X-2002",
        zone=2,
        residential_declared=False,
        declared_length_in=100,
        declared_width_in=6,
        declared_height_in=6,
        declared_weight_lbs=5.0,
    )
    girth = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-X-2003",
        zone=2,
        residential_declared=False,
        declared_length_in=40,
        declared_width_in=24,
        declared_height_in=24,
        declared_weight_lbs=5.0,
    )

    # UNDER: 95 is not past 96 and 95 + 2 x (6 + 6) = 119 is not past 130, but
    # 95 inches is well past the four-foot handling line.
    assert_fields(
        under.shipment,
        {
            "declared_cube_in3": 3420,
            "oversize_flag": False,
            "additional_handling_flag": True,
            "preliminary_basis": "DIMENSIONAL",
        },
    )
    assert_lbs(under.shipment["billable_weight_lbs"], 25, "3420 in3 over 139")
    assert_money_equals(
        under.shipment["accessorial_total_cents"], AH_CENTS, "under accessorials"
    )
    under_rows, under_meta = _charges(api, under.shipment_id)
    assert under_meta["total_count"] == 1, f"expected one charge, got {under_rows}"
    assert_money_equals(
        find_row(under_rows, code="ADDITIONAL_HANDLING")["amount_cents"],
        AH_CENTS,
        "handling charge",
    )
    under_preview = _preview(api, under.shipment_id)
    assert_fields(under_preview, {"rate_cents_per_lb": 340})
    assert_money_equals(under_preview["transportation_base_cents"], 8500, "25 lb at 340")
    assert_money_equals(under_preview["line_total_cents"], 10950, "under total")

    # OVER: five more inches, and the handling charge is replaced outright.
    assert_fields(
        over.shipment,
        {
            "declared_cube_in3": 3600,
            "oversize_flag": True,
            "additional_handling_flag": False,
            "preliminary_basis": "OVERSIZE_FLOOR",
        },
    )
    assert_lbs(over.shipment["preliminary_dim_weight_lbs"], 26, "3600 in3 over 139")
    assert_lbs(over.shipment["billable_weight_lbs"], 90, "the oversize floor")
    over_rows, over_meta = _charges(api, over.shipment_id)
    assert over_meta["total_count"] == 1, (
        f"oversize absorbs handling, so exactly one charge is due, got {over_rows}"
    )
    oversize = find_row(over_rows, code="OVERSIZE")
    assert_fields(oversize, {"status": "ASSESSED", "source": "AUTO"})
    assert_money_equals(oversize["amount_cents"], OVERSIZE_CENTS, "oversize charge")
    over_preview = _preview(api, over.shipment_id)
    assert_fields(over_preview, {"rate_cents_per_lb": 305})
    assert_money_equals(over_preview["transportation_base_cents"], 27450, "90 lb at 305")
    assert_money_equals(over_preview["line_total_cents"], 39950, "over total")
    assert (
        over_preview["line_total_cents"] - under_preview["line_total_cents"] == 29000
    ), "five inches of length is worth 29000 cents on this parcel"

    # GIRTH: the same flag reached the other way, but the floor never binds.
    assert_fields(
        girth.shipment,
        {
            "declared_cube_in3": 23040,
            "oversize_flag": True,
            "additional_handling_flag": False,
            "preliminary_basis": "DIMENSIONAL",
        },
    )
    assert_lbs(girth.shipment["billable_weight_lbs"], 166, "23040 in3 over 139")
    assert_money_equals(
        girth.shipment["accessorial_total_cents"], OVERSIZE_CENTS, "girth accessorials"
    )
    girth_preview = _preview(api, girth.shipment_id)
    assert_fields(girth_preview, {"rate_cents_per_lb": 305})
    assert_money_equals(
        girth_preview["transportation_base_cents"], 50630, "166 lb at 305"
    )
    assert_money_equals(girth_preview["line_total_cents"], 63130, "girth total")

    # The 1195-cent floor never binds on any of the three.
    for label, preview in (
        ("1Z-X-2001", under_preview),
        ("1Z-X-2002", over_preview),
        ("1Z-X-2003", girth_preview),
    ):
        assert preview["transportation_base_cents"] > 1195, (
            f"{label} should price well above the per-package minimum"
        )


def test_04_an_active_shipper_with_a_covering_contract_passes_every_gate(api):
    """The positive control: an induction where nothing at all goes wrong.

    An ACTIVE account, an ACTIVE contract covering today, and a tracking
    number nobody has used. The response must be a 201 whose body shows the
    contract bound, the divisor copied, the clock stamped, all three status
    axes at their opening values and the account's two counters up by one.

    PRD §3.3: "The candidates are ranked by `effective_from` descending, so the most recently effective contract wins; ties on `effective_from` are broken by `created_at` ascending, so the earlier-drafted contract wins a tie."
    PRD §3.3: "The first row of that ranking becomes the shipment's `contract_id`, and its `dim_divisor` is copied onto the shipment as `divisor_used`."
    PRD §3.3: "The server stamps `picked_up_at` from the logical clock and derives `pickup_date` as the UTC calendar date of that instant."
    PRD §3.3: "All three status axes open at their initial values: `measurement_status` at `PENDING_SCAN`, `movement_status` at `IN_TRANSIT`, and `billing_status` at `UNBILLED`."
    PRD §3.3: "The owning account's `total_shipment_count` and `unbilled_shipment_count` each increase by 1, and `open_charges_cents` is recomputed."
    PRD §3.3: "Otherwise the basis is `DIMENSIONAL`."

    Design: Corner/validations/an_active_shipper_induction_satisfies_every_gate_at_once
    """
    shipper = _acme(api)
    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id),
        total=0,
        unbilled=0,
        billed=0,
        open_charges_cents=0,
        credit_balance_cents=0,
    )

    parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                shipper.shipper_id,
                shipper.service_level_ids["EXPRESS"],
                tracking_number="1Z-S-2001",
                zone=2,
                residential_declared=False,
                declared_length_in=12,
                declared_width_in=10,
                declared_height_in=8,
                declared_weight_lbs=6.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )

    # The only ACTIVE contract covering 2026-08-01 is bound, divisor and all.
    assert_fields(
        parcel,
        {
            "tracking_number": "1Z-S-2001",
            "contract_id": shipper.contract_id,
            "divisor_used": 139,
            "pickup_date": "2026-08-01",
            "measurement_status": "PENDING_SCAN",
            "movement_status": "IN_TRANSIT",
            "billing_status": "UNBILLED",
            "preliminary_basis": "DIMENSIONAL",
        },
    )
    assert_instant(parcel["picked_up_at"], CLOCK_INSTANT, "picked_up_at")
    assert_lbs(parcel["billable_weight_lbs"], 7, "960 in3 over 139")

    # And the account's counters moved by exactly one package.
    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id),
        total=1,
        unbilled=1,
        billed=0,
        open_charges_cents=0,
        credit_balance_cents=0,
    )


def test_05_a_parcel_that_is_never_scanned_bills_on_its_declaration(api):
    """No scan on file means the declaration is the governing measurement.

    A 10 x 10 x 20 parcel at 30.0 lb has a dimensional weight of only 15
    pounds, so its scale weight wins and the basis is actual. Nothing ever
    scans it, so every final measurement field stays null, its scan history
    stays empty, and the sweep still bills it — copying the preliminary pound
    count and the preliminary basis straight onto the line.

    PRD §3.3: "The shipment also publishes a single `billable_weight_lbs` field, which is the pound count that actually prices the package."
    PRD §3.3: "While no scan exists it equals `preliminary_billable_weight_lbs`; once a governing scan exists it equals `final_billable_weight_lbs` instead (§3.4)."
    PRD §3.3: "Until the first scan arrives, `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, `final_basis`, `dim_variance_pct`, and `weight_variance_lbs` are all null on the shipment."
    PRD §3.3: "Otherwise, when the actual billable pound count is greater than or equal to the dimensional pound count, the basis is `ACTUAL`."
    PRD §3.6: "Note the asymmetry that a package still `PENDING_SCAN` is perfectly billable and will be priced from its preliminary declaration, while a package whose scanner verdict is unresolved is not."
    PRD §3.6: "Each line records its owning `invoice_id` and its `shipment_id` (unique among the lines of all non-void invoices), freezes the package's current `billable_weight_lbs` onto the line's own `billable_weight_lbs`, and freezes the winning basis label onto `billable_weight_basis` — taking `final_basis` when a scan governs the package and `preliminary_basis` otherwise."

    Design: Corner/calculations/an_unscanned_parcel_bills_on_its_preliminary_variant
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-U-0001",
        zone=2,
        residential_declared=False,
        declared_length_in=10,
        declared_width_in=10,
        declared_height_in=20,
        declared_weight_lbs=30.0,
    )
    born = parcel.shipment

    # 2000 in3 over the 139 divisor is 15 pounds, against 30 on the scale.
    assert_fields(born, {"declared_cube_in3": 2000, "preliminary_basis": "ACTUAL"})
    assert_lbs(born["preliminary_dim_weight_lbs"], 15, "dimensional pound count")
    assert_lbs(born["preliminary_billable_weight_lbs"], 30, "preliminary billable")
    assert_lbs(born["billable_weight_lbs"], 30, "published billable weight")
    assert_null_fields(
        born,
        [
            "scanned_cube_in3",
            "final_dim_weight_lbs",
            "final_billable_weight_lbs",
            "final_basis",
            "dim_variance_pct",
            "weight_variance_lbs",
        ],
    )
    scan_rows, scan_meta = validate_paginated(
        api.list_scans(parcel.shipment_id, BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert scan_meta["total_count"] == 0, (
        f"this parcel is never scanned, got {scan_rows}"
    )

    validate_success(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
    # Still PENDING_SCAN on the measurement axis, and still perfectly billable.
    assert_fields(
        refresh_shipment(api, parcel.shipment_id),
        {"measurement_status": "PENDING_SCAN", "movement_status": "DELIVERED"},
    )

    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    assert_money_equals(
        invoice.invoice["transportation_subtotal_cents"], 10200, "30 lb at 340"
    )
    line = refresh_invoice_line(api, invoice.line_by_shipment[parcel.shipment_id])
    assert_fields(line, {"billable_weight_basis": "ACTUAL", "rate_cents_per_lb": 340})
    assert_lbs(line["billable_weight_lbs"], 30, "frozen billable weight")
    assert_money_equals(line["line_total_cents"], 10200, "line total")
    assert_money_equals(line["accessorial_total_cents"], 0, "no accessorials")
