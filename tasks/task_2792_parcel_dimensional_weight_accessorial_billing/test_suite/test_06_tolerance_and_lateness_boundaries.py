"""Values that land exactly on a threshold rather than near one.

A cube variance of exactly 5.00 percent, a scale variance of exactly the
derived 0.6 pound allowance, and a delivery landing exactly on the commitment
instant all sit on a comparison edge where the direction of the inequality is
the whole answer.
"""

import pytest

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    DEFAULT_CLOCK_UTC,
    ERR_SHIPMENT_NOT_LATE,
    REVENUE_AUDITOR_HEADERS,
    REVENUE_AUDITOR_USER_ID,
    SMALL_DECLARED,
    TOLERANCE_EDGE_DECLARED,
    add_scan,
    assert_instant,
    assert_lbs,
    assert_money_equals,
    assert_pct,
    get_success_data,
    guarantee_claim_payload,
    induct_shipment,
    issued_invoice,
    line_for_shipment,
    open_invoice,
    refresh_invoice,
    refresh_shipment,
    set_clock,
    shipper_with_active_contract,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The two inclusive tolerance edges
# ---------------------------------------------------------------------------
@pytest.fixture
def tolerance_boundary_parcels(api):
    """Two GROUND parcels declared at 30.0 lb with cubes of 2000 and 4000 in3.

    A 2100 in3 capture against the 2000 in3 cube is exactly 5.00 percent, a
    4100 in3 capture against the 4000 in3 cube is exactly 2.50 percent, and the
    weight allowance for either is max(0.5, 0.6) = 0.6 lb.
    """
    shipper = shipper_with_active_contract(
        api, account_number="SH-1001", with_express=False
    )
    parcel_a = induct_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-PTA-0041",
        zone=2,
        residential_declared=False,
        **TOLERANCE_EDGE_DECLARED,
    )
    parcel_b = induct_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-PTB-0042",
        zone=2,
        residential_declared=False,
        declared_length_in=10,
        declared_width_in=10,
        declared_height_in=40,
        declared_weight_lbs=30.0,
    )
    assert parcel_a.shipment["declared_cube_in3"] == 2000
    assert parcel_b.shipment["declared_cube_in3"] == 4000
    return {"shipper": shipper, "parcel_a": parcel_a, "parcel_b": parcel_b}


def _scan_count(api, shipment_id):
    """How many measurement rows a package has accumulated."""
    return len(
        get_success_data(
            api.list_scans(shipment_id, CARRIER_OPS_HEADERS, {"limit": 100})
        )
    )


def test_a_cube_variance_landing_exactly_on_five_percent_is_a_breach(
    api, tolerance_boundary_parcels
):
    """PRD §3.4: "`dim_variance_pct` is the absolute difference between the scan's `scanned_cube_in3` and the shipment's `declared_cube_in3`, multiplied by 100, divided by the shipment's `declared_cube_in3`, and rounded half up to two decimal places."
    PRD §3.4: "The scan breaches on cube when `dim_variance_pct` is greater than or equal to 5.00 percent, and it breaches on weight when `weight_variance_lbs` is greater than or equal to the weight allowance."
    PRD §3.4: "Both comparisons are inclusive: a variance landing exactly on the threshold is a breach."
    PRD §3.4: "An `AUTOMATED_DWS` capture whose verdict is `EXCEEDS_TOLERANCE` drives the shipment to `TOLERANCE_FLAGGED`, reachable both as `PENDING_SCAN → TOLERANCE_FLAGGED` and as `SCANNED → TOLERANCE_FLAGGED`."

    Design: Difficulty/boundary_precision_check/scan_tolerance_breaches_at_exactly_five_percent_and_at_exactly_the_weight_allowance
    """
    parcel_a = tolerance_boundary_parcels["parcel_a"]
    scan = add_scan(
        api,
        parcel_a.shipment_id,
        expected_version=parcel_a.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    assert scan["scanned_cube_in3"] == 2100, (
        f"10 x 10 x 21 inches must cube to 2100 in3, got {scan['scanned_cube_in3']}"
    )
    assert_pct(scan["dim_variance_pct"], 5.00, "dim_variance_pct")
    assert_lbs(scan["weight_variance_lbs"], 0.0, "weight_variance_lbs")
    assert scan["tolerance_status"] == "EXCEEDS_TOLERANCE", (
        "5.00 percent is greater than or equal to the 5.00 percent threshold, so it "
        f"breaches; a strict comparison would wrongly pass it, got {scan['tolerance_status']}"
    )

    shipment = refresh_shipment(api, parcel_a.shipment_id)
    assert shipment["measurement_status"] == "TOLERANCE_FLAGGED"
    assert_lbs(shipment["final_dim_weight_lbs"], 16, "final_dim_weight_lbs")
    assert_lbs(shipment["final_billable_weight_lbs"], 30, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "ACTUAL"
    assert _scan_count(api, parcel_a.shipment_id) == 1


def test_a_cube_variance_of_two_and_a_half_percent_stays_inside_tolerance(
    api, tolerance_boundary_parcels
):
    """PRD §3.4: "The scan's `tolerance_status` is `EXCEEDS_TOLERANCE` when either breach fires, and `WITHIN_TOLERANCE` when neither does."
    PRD §3.4: "An `AUTOMATED_DWS` capture whose verdict is `WITHIN_TOLERANCE` drives the shipment to `SCANNED`."
    PRD §3.3: "Otherwise, when the actual billable pound count is greater than or equal to the dimensional pound count, the basis is `ACTUAL`."

    Design: Difficulty/boundary_precision_check/scan_tolerance_breaches_at_exactly_five_percent_and_at_exactly_the_weight_allowance
    """
    parcel_b = tolerance_boundary_parcels["parcel_b"]
    scan = add_scan(
        api,
        parcel_b.shipment_id,
        expected_version=parcel_b.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=41,
        scanned_weight_lbs=30.0,
    )
    assert scan["scanned_cube_in3"] == 4100, (
        f"10 x 10 x 41 inches must cube to 4100 in3, got {scan['scanned_cube_in3']}"
    )
    assert_pct(scan["dim_variance_pct"], 2.50, "dim_variance_pct")
    assert_lbs(scan["weight_variance_lbs"], 0.0, "weight_variance_lbs")
    assert scan["tolerance_status"] == "WITHIN_TOLERANCE", (
        "the same 100 in3 absolute change against a 4000 in3 cube is only 2.50 "
        f"percent and must not breach, got {scan['tolerance_status']}"
    )

    shipment = refresh_shipment(api, parcel_b.shipment_id)
    assert shipment["measurement_status"] == "SCANNED"
    assert_lbs(shipment["final_dim_weight_lbs"], 30, "final_dim_weight_lbs")
    assert_lbs(shipment["final_billable_weight_lbs"], 30, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "ACTUAL", (
        "30 actual pounds ties the 30 dimensional pounds and a tie resolves to "
        f"ACTUAL, got {shipment['final_basis']}"
    )


def test_a_scale_variance_landing_exactly_on_the_derived_allowance_is_a_breach(
    api, tolerance_boundary_parcels
):
    """PRD §3.4: "`weight_variance_lbs` is the absolute difference between `scanned_weight_lbs` and the shipment's `declared_weight_lbs`, rounded half up to one decimal place."
    PRD §3.4: "The **weight allowance** is the greater of half a pound and two percent of the shipment's `declared_weight_lbs`, where the percentage figure is itself rounded half up to one decimal place before the comparison of the two candidates."
    PRD §2.6: "**Round half up to one decimal place.** The scale-weight variance `weight_variance_lbs` and the derived weight allowance are carried at exactly one decimal place."
    PRD §3.4: "The full measurement history of a package is readable as a list ordered oldest first, so the sequence of variances and verdicts that produced the current determination is auditable end to end."

    Design: Difficulty/boundary_precision_check/scan_tolerance_breaches_at_exactly_five_percent_and_at_exactly_the_weight_allowance
    """
    parcel_a = tolerance_boundary_parcels["parcel_a"]
    parcel_b = tolerance_boundary_parcels["parcel_b"]
    add_scan(
        api,
        parcel_b.shipment_id,
        expected_version=parcel_b.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=41,
        scanned_weight_lbs=30.0,
    )
    inside = refresh_shipment(api, parcel_b.shipment_id)
    assert inside["measurement_status"] == "SCANNED"

    scan = add_scan(
        api,
        parcel_b.shipment_id,
        expected_version=inside["version"],
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=40,
        scanned_weight_lbs=30.6,
    )
    assert scan["scanned_cube_in3"] == 4000
    assert_pct(scan["dim_variance_pct"], 0.00, "dim_variance_pct")
    assert_lbs(scan["weight_variance_lbs"], 0.6, "weight_variance_lbs")
    assert scan["tolerance_status"] == "EXCEEDS_TOLERANCE", (
        "0.6 lb is greater than or equal to the 0.6 lb allowance — two percent of "
        "30.0 lb beats the half-pound floor — so the cube being untouched cannot "
        f"save it, got {scan['tolerance_status']}"
    )

    shipment = refresh_shipment(api, parcel_b.shipment_id)
    assert shipment["measurement_status"] == "TOLERANCE_FLAGGED"
    assert_lbs(shipment["final_billable_weight_lbs"], 31, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "ACTUAL", (
        "31 actual pounds beats the 29 dimensional pounds of a 4000 in3 cube, got "
        f"{shipment['final_basis']}"
    )
    assert _scan_count(api, parcel_b.shipment_id) == 2, (
        "both captures survive as history"
    )
    assert _scan_count(api, parcel_a.shipment_id) == 0, (
        "the other parcel must not have been scanned at all"
    )


# ---------------------------------------------------------------------------
# One second either side of the commitment instant
# ---------------------------------------------------------------------------
COMMITMENT_UTC = "2026-08-02T00:00:00Z"
ONE_SECOND_LATE_UTC = "2026-08-02T00:00:01Z"


@pytest.fixture
def parcels_straddling_the_commitment_instant(api):
    """Two identical EXPRESS parcels, one delivered on the dot and one a second late.

    Both are inducted at the 2026-08-01T00:00:00Z clock under a 24 hour
    guarantee, so both commit to 2026-08-02T00:00:00Z, and both price at 2660
    cents. No surcharge window exists, so nothing suspends the guarantee.
    """
    shipper = shipper_with_active_contract(
        api, account_number="SH-1001", with_ground=False
    )
    on_time = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PL-0051",
        zone=2,
        residential_declared=False,
        **SMALL_DECLARED,
    )
    late = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PM-0052",
        zone=2,
        residential_declared=False,
        **SMALL_DECLARED,
    )
    for parcel in (on_time, late):
        assert_instant(
            parcel.shipment["guarantee_deadline_utc"],
            COMMITMENT_UTC,
            "guarantee_deadline_utc",
        )

    set_clock(api, COMMITMENT_UTC)
    validate_success(api.deliver_shipment(on_time.shipment_id, CARRIER_OPS_HEADERS))
    set_clock(api, ONE_SECOND_LATE_UTC)
    validate_success(api.deliver_shipment(late.shipment_id, CARRIER_OPS_HEADERS))

    invoice = issued_invoice(
        api, open_invoice(api, shipper, [on_time.shipment_id, late.shipment_id])
    )
    return {
        "shipper": shipper,
        "invoice": invoice,
        "on_time": on_time,
        "late": late,
        "on_time_line": line_for_shipment(api, invoice.invoice_id, on_time.shipment_id),
        "late_line": line_for_shipment(api, invoice.invoice_id, late.shipment_id),
    }


def _file_claim(api, shipment_id, reason):
    """File a guarantee claim as the auditor who will also adjudicate it."""
    return api.create_guarantee_claim(
        guarantee_claim_payload(shipment_id, claimed_reason=reason),
        REVENUE_AUDITOR_HEADERS,
    )


def _claims_for(api, shipment_id):
    """Every guarantee claim row that exists for one shipment."""
    return get_success_data(
        api.list_guarantee_claims(
            REVENUE_AUDITOR_HEADERS, {"shipment_id": shipment_id, "limit": 100}
        )
    )


def test_a_delivery_landing_exactly_on_the_commitment_instant_is_on_time(
    api, parcels_straddling_the_commitment_instant
):
    """PRD §3.9: "The package is late when its `delivered_at` is **strictly after** that instant; a delivery landing exactly on the commitment instant is on time and earns nothing."
    PRD §3.9: "and the delivery must be strictly late, else `ERR_SHIPMENT_NOT_LATE` (HTTP 422)"
    PRD §3.5: "That `delivered_at` instant is the one later compared against `guarantee_deadline_utc` when a money-back claim is assessed."

    Design: Difficulty/boundary_precision_check/guarantee_lateness_uses_strict_inequality_at_the_commitment_instant
    """
    ctx = parcels_straddling_the_commitment_instant
    on_time = refresh_shipment(api, ctx["on_time"].shipment_id)
    assert_instant(on_time["picked_up_at"], DEFAULT_CLOCK_UTC, "picked_up_at")
    assert_instant(
        on_time["guarantee_deadline_utc"], COMMITMENT_UTC, "guarantee_deadline_utc"
    )
    assert_instant(on_time["delivered_at"], COMMITMENT_UTC, "delivered_at")

    validate_error(
        _file_claim(api, ctx["on_time"].shipment_id, "On the dot"),
        ERR_SHIPMENT_NOT_LATE,
        422,
    )
    assert _claims_for(api, ctx["on_time"].shipment_id) == [], (
        "an equal instant must create no claim row at all"
    )


def test_a_delivery_one_second_past_the_commitment_yields_a_one_second_claim(
    api, parcels_straddling_the_commitment_instant
):
    """PRD §3.9: "The `late_by_seconds` figure is the whole number of seconds from the deadline to `delivered_at`, and it is strictly positive for any fileable claim."
    PRD §3.9: "The `candidate_refund_cents` is therefore 0 when the package is not late or when the guarantee is suspended, and otherwise it is the non-voided invoice line's `transportation_base_cents` — the floored transportation charge and nothing else."
    PRD §3.9: "A filed claim opens at `status` `FILED` with `filed_by_user_id` stamped from the filer's `X-User-ID`, `invoice_line_id` resolved to the package's live line, `guarantee_deadline_utc` and `delivered_at` frozen from the shipment, `late_by_seconds` and `candidate_refund_cents` computed as above, `refund_cents` at 0, and `adjudicated_at` null."

    Design: Difficulty/boundary_precision_check/guarantee_lateness_uses_strict_inequality_at_the_commitment_instant
    """
    ctx = parcels_straddling_the_commitment_instant
    late = refresh_shipment(api, ctx["late"].shipment_id)
    assert_instant(late["delivered_at"], ONE_SECOND_LATE_UTC, "delivered_at")
    assert_instant(
        late["guarantee_deadline_utc"], COMMITMENT_UTC, "guarantee_deadline_utc"
    )

    claim = validate_success(
        _file_claim(api, ctx["late"].shipment_id, "One second past the commitment"), 201
    )
    assert claim["status"] == "FILED"
    assert claim["late_by_seconds"] == 1, (
        f"one second past the deadline is one second late, got {claim['late_by_seconds']}"
    )
    assert_money_equals(
        claim["candidate_refund_cents"], 2660, "candidate_refund_cents"
    )
    assert_money_equals(claim["refund_cents"], 0, "refund_cents")
    assert claim["invoice_line_id"] == ctx["late_line"]["id"]
    assert claim["filed_by_user_id"] == REVENUE_AUDITOR_USER_ID
    assert claim["adjudicated_at"] is None

    rows = _claims_for(api, ctx["late"].shipment_id)
    assert len(rows) == 1, f"exactly one claim must exist, found {len(rows)}"
    assert rows[0]["id"] == claim["id"]


def test_neither_the_refusal_nor_the_filing_moves_a_cent_on_the_invoice(
    api, parcels_straddling_the_commitment_instant
):
    """PRD §3.9: "Crucially, approval does not move money."
    PRD §3.6: "`net_amount_cents` is `gross_charges_cents` minus `tier_discount_cents` plus `adjustment_total_cents`."
    PRD §3.6: "When no row qualifies, `tier_discount_bps` is 0."

    Design: Difficulty/boundary_precision_check/guarantee_lateness_uses_strict_inequality_at_the_commitment_instant
    """
    ctx = parcels_straddling_the_commitment_instant
    validate_error(
        _file_claim(api, ctx["on_time"].shipment_id, "On the dot"),
        ERR_SHIPMENT_NOT_LATE,
        422,
    )
    validate_success(
        _file_claim(api, ctx["late"].shipment_id, "One second past the commitment"), 201
    )

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["line_count"] == 2
    assert_money_equals(
        invoice["transportation_subtotal_cents"], 5320, "transportation_subtotal_cents"
    )
    assert_money_equals(invoice["gross_charges_cents"], 5320, "gross_charges_cents")
    assert invoice["tier_discount_bps"] == 0
    assert_money_equals(invoice["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert_money_equals(invoice["net_amount_cents"], 5320, "net_amount_cents")
    assert invoice["pending_adjustment_count"] == 0, (
        "filing a claim raises no adjustment, got "
        f"{invoice['pending_adjustment_count']}"
    )

    lines = get_success_data(
        api.list_invoice_lines(
            BILLING_OPS_HEADERS, {"invoice_id": ctx["invoice"].invoice_id, "limit": 100}
        )
    )
    assert all(line["adjustment_total_cents"] == 0 for line in lines), (
        f"no line may have moved: {[line['adjustment_total_cents'] for line in lines]}"
    )
