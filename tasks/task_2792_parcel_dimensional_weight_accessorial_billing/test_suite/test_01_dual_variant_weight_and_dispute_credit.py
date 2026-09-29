"""Both places where one shape of arithmetic runs in two variants.

The billable-weight calculation runs a preliminary variant from the shipper's
declaration and a final variant from the governing scan; the dispute credit runs
a full-reprice variant for a weight claim and an accessorial-only variant for a
named-charge claim. Each pair is exercised on data engineered so the two
variants cannot produce the same number.
"""

import pytest

from test_helpers import (
    BILLING_OPS_HEADERS,
    FULL_TIER_TABLE,
    RESIDENTIAL_OVERRIDE_540,
    ROUNDING_DECLARED,
    TOLERANCE_EDGE_DECLARED,
    accessorials_for_shipment,
    add_scan,
    assert_fields,
    assert_lbs,
    assert_ledger,
    assert_money_equals,
    assert_null_fields,
    assert_package_count_conserved,
    assert_pct,
    delivered_shipment,
    evidence_payload,
    filed_dispute,
    find_row,
    get_success_data,
    induct_shipment,
    issued_invoice,
    line_for_shipment,
    make_revenue_auditor_headers,
    open_invoice,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipment,
    refresh_shipper_account,
    shipper_with_active_contract,
    validate_success,
)

# The auditor identity that adjudicates both disputes in this module.
AUDITOR_HEADERS = make_revenue_auditor_headers("auditor.kim")


@pytest.fixture
def ground_parcel(api):
    """A 10 x 10 x 20 inch, 30.0 lb GROUND parcel under a 139 divisor contract."""
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={
            "tier_discount_table": list(FULL_TIER_TABLE),
            "accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540),
            "residential_waived": False,
        },
        with_express=False,
    )
    return induct_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-P-0001",
        zone=2,
        residential_declared=False,
        **TOLERANCE_EDGE_DECLARED,
    )


def test_preliminary_variant_bills_the_declared_scale_weight_on_an_actual_basis(
    api, ground_parcel
):
    """PRD §3.3: "Each of the three declared dimensions is individually rounded half up to a whole number of inches."
    PRD §3.3: "Otherwise, when the actual billable pound count is greater than or equal to the dimensional pound count, the basis is `ACTUAL`."
    PRD §3.3: "While no scan exists it equals `preliminary_billable_weight_lbs`; once a governing scan exists it equals `final_billable_weight_lbs` instead (§3.4)."
    PRD §3.3: "Until the first scan arrives, `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, `final_basis`, `dim_variance_pct`, and `weight_variance_lbs` are all null on the shipment."

    Design: Difficulty/dual_variant_calc/billable_weight_preliminary_vs_final_basis_flip
    """
    shipment = ground_parcel.shipment

    assert shipment["declared_cube_in3"] == 2000, (
        "10 x 10 x 20 inches must cube to 2000 in3, got "
        f"{shipment['declared_cube_in3']}"
    )
    assert shipment["divisor_used"] == 139, (
        f"the contract divisor must be frozen onto the shipment, got {shipment['divisor_used']}"
    )
    assert_lbs(shipment["preliminary_dim_weight_lbs"], 15, "preliminary_dim_weight_lbs")
    assert_lbs(
        shipment["preliminary_billable_weight_lbs"], 30, "preliminary_billable_weight_lbs"
    )
    assert shipment["preliminary_basis"] == "ACTUAL", (
        "30 actual pounds beats 15 dimensional pounds, so the basis is ACTUAL, got "
        f"{shipment['preliminary_basis']}"
    )
    assert_lbs(shipment["billable_weight_lbs"], 30, "billable_weight_lbs")
    assert_null_fields(
        shipment,
        [
            "scanned_cube_in3",
            "final_dim_weight_lbs",
            "final_billable_weight_lbs",
            "final_basis",
            "dim_variance_pct",
            "weight_variance_lbs",
        ],
    )
    assert shipment["measurement_status"] == "PENDING_SCAN"


def test_final_variant_flips_the_basis_to_dimensional_and_takes_over_billable_weight(
    api, ground_parcel
):
    """PRD §3.4: "The final variant runs the identical five steps and the identical basis-labelling rule as the preliminary one, differing only in its inputs: it reads the governing scan's captured dimensions and captured weight rather than the declaration, and it re-derives `oversize_flag` and `additional_handling_flag` from that captured geometry, using `non_conveyable_observed` from the governing scan in place of the shipper's `non_conveyable_declared` in the additional-handling test."
    PRD §3.4: "The shipment's `billable_weight_lbs` then switches to `final_billable_weight_lbs` and stays there for as long as a scan exists."
    PRD §3.4: "A `MANUAL_REWEIGH` capture is authoritative regardless of variance and drives the shipment straight to `VERIFIED`, reachable as `PENDING_SCAN → VERIFIED`, `SCANNED → VERIFIED`, and `TOLERANCE_FLAGGED → VERIFIED`."

    Design: Difficulty/dual_variant_calc/billable_weight_preliminary_vs_final_basis_flip
    """
    scan = add_scan(
        api,
        ground_parcel.shipment_id,
        expected_version=ground_parcel.shipment_version,
        scan_source="MANUAL_REWEIGH",
        scanned_length_in=24,
        scanned_width_in=18,
        scanned_height_in=14,
        scanned_weight_lbs=30.4,
    )
    assert scan["scanned_cube_in3"] == 6048, (
        f"24 x 18 x 14 inches must cube to 6048 in3, got {scan['scanned_cube_in3']}"
    )
    assert_pct(scan["dim_variance_pct"], 202.40, "dim_variance_pct")
    assert scan["tolerance_status"] == "EXCEEDS_TOLERANCE"

    shipment = refresh_shipment(api, ground_parcel.shipment_id)
    assert shipment["scanned_cube_in3"] == 6048
    assert_lbs(shipment["final_dim_weight_lbs"], 44, "final_dim_weight_lbs")
    assert_lbs(shipment["final_billable_weight_lbs"], 44, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "DIMENSIONAL", (
        "44 dimensional pounds now beat 31 actual pounds, so the final basis is "
        f"DIMENSIONAL, got {shipment['final_basis']}"
    )
    assert_lbs(shipment["billable_weight_lbs"], 44, "billable_weight_lbs")
    assert shipment["measurement_status"] == "VERIFIED"
    assert shipment["oversize_flag"] is False
    assert shipment["additional_handling_flag"] is False
    # The preliminary variant is history, not overwritten.
    assert_lbs(
        shipment["preliminary_billable_weight_lbs"], 30, "preliminary_billable_weight_lbs"
    )
    assert shipment["preliminary_basis"] == "ACTUAL"


def test_price_follows_the_final_variant_into_a_higher_weight_band(api, ground_parcel):
    """PRD §3.6: "The server finds the single row of that contract's `rate_table` whose `zone` equals the shipment's `zone` and whose weight band contains the line's billable pound count — that is, the pound count is greater than or equal to `min_lbs` and less than or equal to `max_lbs`."
    PRD §3.6: "The per-package floor then applies **to the transportation charge alone, and before any surcharge**: `transportation_base_cents` is the greater of the uncapped charge and the governing contract's `min_charge_cents`."
    PRD §3.6: "The preview creates nothing and mutates nothing; it returns `shipment_id`, `contract_id`, `billable_weight_lbs`, `billable_weight_basis`, `rate_cents_per_lb`, `transportation_base_cents`, `surcharge_cents`, `accessorial_total_cents`, and `line_total_cents`, computed by exactly the line-pricing rules above."

    Design: Difficulty/dual_variant_calc/billable_weight_preliminary_vs_final_basis_flip
    """
    add_scan(
        api,
        ground_parcel.shipment_id,
        expected_version=ground_parcel.shipment_version,
        scan_source="MANUAL_REWEIGH",
        scanned_length_in=24,
        scanned_width_in=18,
        scanned_height_in=14,
        scanned_weight_lbs=30.4,
    )

    preview = validate_success(
        api.get_billing_preview(ground_parcel.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_lbs(preview["billable_weight_lbs"], 44, "preview billable_weight_lbs")
    assert preview["billable_weight_basis"] == "DIMENSIONAL"
    assert_money_equals(preview["rate_cents_per_lb"], 340, "rate_cents_per_lb")
    assert_money_equals(
        preview["transportation_base_cents"], 14960, "transportation_base_cents"
    )
    assert preview["transportation_base_cents"] != 10200, (
        "pricing must use the final 44 pound determination, not the preliminary 30"
    )
    assert_money_equals(preview["surcharge_cents"], 0, "surcharge_cents")
    assert_money_equals(preview["accessorial_total_cents"], 0, "accessorial_total_cents")
    assert_money_equals(preview["line_total_cents"], 14960, "line_total_cents")


@pytest.fixture
def divergent_disputes(api):
    """Two identical residential EXPRESS parcels on one issued invoice.

    Parcel A is disputed on its RESIDENTIAL charge, parcel B on its billable
    weight, and both disputes are driven to UNDER_REVIEW with one accepted
    evidence item each so either may be upheld.
    """
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540)},
        with_ground=False,
    )
    parcel_a = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PKG-A",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    parcel_b = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PKG-B",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    invoice = issued_invoice(
        api, open_invoice(api, shipper, [parcel_a.shipment_id, parcel_b.shipment_id])
    )
    line_a = line_for_shipment(api, invoice.invoice_id, parcel_a.shipment_id)
    line_b = line_for_shipment(api, invoice.invoice_id, parcel_b.shipment_id)

    dispute_a = filed_dispute(
        api,
        invoice,
        line_a["id"],
        claim_type="ACCESSORIAL",
        disputed_codes=["RESIDENTIAL"],
        claimed_reason="The destination is a commercial dock, not a residence",
    )
    get_success_data(
        api.submit_evidence(
            dispute_a.dispute_id,
            evidence_payload(item_type="ADDRESS_PROOF", reference="doc://lease-agreement-A"),
            shipper.shipper_headers,
        )
    )
    dispute_b = filed_dispute(
        api,
        invoice,
        line_b["id"],
        claim_type="WEIGHT",
        claimed_reason="The billed weight does not match the parcel",
    )
    get_success_data(
        api.submit_evidence(
            dispute_b.dispute_id,
            evidence_payload(item_type="SCALE_CERT", reference="doc://scale-cert-B"),
            shipper.shipper_headers,
        )
    )
    return {
        "shipper": shipper,
        "invoice": invoice,
        "parcel_a": parcel_a,
        "parcel_b": parcel_b,
        "line_a": line_a,
        "line_b": line_b,
        "dispute_a": dispute_a,
        "dispute_b": dispute_b,
    }


def test_accessorial_only_variant_credits_exactly_the_named_charge(
    api, divergent_disputes
):
    """PRD §3.9: "The raw credit is the sum of `amount_cents` over the shipment's accessorial charges whose code appears in `disputed_codes` *and* whose `status` is `ASSESSED`."
    PRD §3.9: "*Hop 2* creates a `BillingAdjustment` with `reason` `DISPUTE_CREDIT`, `delta_cents` equal to the negation of `granted_credit_cents`, `dispute_id` set to this dispute, and `created_by_user_id` set to the literal `system` — and it is created **already at `APPLIED`**, bypassing the segregation-of-duties gate entirely because no human proposed it."
    PRD §3.9: "*Hop 2b* runs only for an `ACCESSORIAL` claim: every disputed accessorial charge whose `status` is `ASSESSED` moves to `WAIVED`, so the charge stops contributing money going forward as well as being credited backwards."

    Design: Difficulty/dual_variant_calc/dispute_credit_full_reprice_vs_accessorial_only_divergence
    """
    dispute_a = divergent_disputes["dispute_a"]
    resolved = validate_success(
        api.resolve_dispute(dispute_a.dispute_id, "UPHELD", AUDITOR_HEADERS)
    )
    assert resolved["status"] == "UPHELD"
    assert_money_equals(resolved["granted_credit_cents"], 540, "granted_credit_cents")

    rows = validate_success(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"dispute_id": dispute_a.dispute_id}
        )
    )
    assert len(rows) == 1, (
        f"an upheld accessorial dispute mints exactly one credit, found {len(rows)}"
    )
    assert_fields(
        rows[0],
        {
            "reason": "DISPUTE_CREDIT",
            "delta_cents": -540,
            "status": "APPLIED",
            "created_by_user_id": "system",
            "dispute_id": dispute_a.dispute_id,
        },
    )

    line_a = refresh_invoice_line(api, divergent_disputes["line_a"]["id"])
    assert_money_equals(line_a["adjustment_total_cents"], -540, "adjustment_total_cents")
    assert_money_equals(line_a["line_total_cents"], 7220, "line_total_cents")
    assert_money_equals(line_a["base_line_total_cents"], 7760, "base_line_total_cents")

    charges = accessorials_for_shipment(api, divergent_disputes["parcel_a"].shipment_id)
    residential = find_row(charges, code="RESIDENTIAL")
    assert residential["status"] == "WAIVED", (
        "the credited residential charge must stop contributing money, got "
        f"{residential['status']}"
    )


def test_full_reprice_variant_grants_nothing_when_the_line_reprices_to_itself(
    api, divergent_disputes
):
    """PRD §3.9: "The raw credit is the disputed line's `line_total_cents` minus that recomputed base line total, floored at 0 so a reprice that came out higher never becomes a rebill."
    PRD §3.9: "A computed credit of 0 is a perfectly legal `UPHELD` outcome and creates no adjustment."

    Design: Difficulty/dual_variant_calc/dispute_credit_full_reprice_vs_accessorial_only_divergence
    """
    dispute_b = divergent_disputes["dispute_b"]
    resolved = validate_success(
        api.resolve_dispute(dispute_b.dispute_id, "UPHELD", AUDITOR_HEADERS)
    )
    assert resolved["status"] == "UPHELD"
    assert_money_equals(resolved["granted_credit_cents"], 0, "granted_credit_cents")

    rows = validate_success(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"dispute_id": dispute_b.dispute_id}
        )
    )
    assert rows == [], (
        f"a zero credit creates no adjustment, found {len(rows)} rows"
    )

    line_b = refresh_invoice_line(api, divergent_disputes["line_b"]["id"])
    assert_money_equals(line_b["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert_money_equals(line_b["line_total_cents"], 7760, "line_total_cents")

    charges = accessorials_for_shipment(api, divergent_disputes["parcel_b"].shipment_id)
    residential = find_row(charges, code="RESIDENTIAL")
    assert residential["status"] == "ASSESSED", (
        "a weight dispute never waives a charge, got " f"{residential['status']}"
    )

    invoice = refresh_invoice(api, divergent_disputes["invoice"].invoice_id)
    assert invoice["status"] == "ISSUED", (
        "with no adjustment minted the invoice never reaches ADJUSTED, got "
        f"{invoice['status']}"
    )
    assert_money_equals(invoice["net_amount_cents"], 15520, "net_amount_cents")


def test_the_two_variants_diverge_on_identical_parcels_and_the_ledger_absorbs_only_one(
    api, divergent_disputes
):
    """PRD §3.9: "This variant ignores the weight determination entirely, so on the same line with the same data it will generally produce a different number than a full reprice — for instance a real credit for a wrongly assessed residential fee where a reprice would have produced nothing at all."
    PRD §3.9: "*Hop 4* — because the invoice moved, the owning account's `credit_balance_cents` rises by `granted_credit_cents`."
    PRD §2.11: "**Conserved package count:** `unbilled_shipment_count` plus `billed_shipment_count` equals `total_shipment_count`."

    Design: Difficulty/dual_variant_calc/dispute_credit_full_reprice_vs_accessorial_only_divergence
    """
    accessorial_credit = validate_success(
        api.resolve_dispute(
            divergent_disputes["dispute_a"].dispute_id, "UPHELD", AUDITOR_HEADERS
        )
    )["granted_credit_cents"]
    weight_credit = validate_success(
        api.resolve_dispute(
            divergent_disputes["dispute_b"].dispute_id, "UPHELD", AUDITOR_HEADERS
        )
    )["granted_credit_cents"]

    assert accessorial_credit == 540 and weight_credit == 0, (
        "identical parcels must diverge by variant: accessorial-only credited "
        f"{accessorial_credit}, full reprice credited {weight_credit}"
    )

    invoice = refresh_invoice(api, divergent_disputes["invoice"].invoice_id)
    assert invoice["status"] == "ADJUSTED"
    assert_money_equals(invoice["gross_charges_cents"], 15520, "gross_charges_cents")
    assert_money_equals(invoice["adjustment_total_cents"], -540, "adjustment_total_cents")
    assert_money_equals(invoice["net_amount_cents"], 14980, "net_amount_cents")

    account = refresh_shipper_account(api, divergent_disputes["shipper"].shipper_id)
    assert_ledger(
        account, total=2, unbilled=0, billed=2, credit_balance_cents=540,
        open_charges_cents=14980,
    )
    assert_package_count_conserved(account)
