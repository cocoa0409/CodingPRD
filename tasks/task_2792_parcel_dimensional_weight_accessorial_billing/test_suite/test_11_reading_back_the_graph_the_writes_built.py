"""Every row a write created must be findable again through a declared read.

The topology here is flat: no child carries a path back to its parent except a
foreign key, so the only way to walk from an invoice to its lines, from a line
to its dispute, or from a dispute to the credit it minted is a filtered
collection endpoint. These tests page through those collections, check that
`total_count` describes the filtered set rather than the page, and confirm the
pure-computation preview never leaves a row behind.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    DEFAULT_CLOCK_UTC,
    ERR_INVALID_PAGINATION,
    REVENUE_AUDITOR_HEADERS,
    SYSTEM_ACTOR,
    add_manual_accessorial,
    add_scan,
    assert_fields,
    assert_instant,
    assert_lbs,
    assert_ledger,
    assert_money_equals,
    assert_version_unchanged,
    delivered_shipment,
    dispute_payload,
    evidence_payload,
    get_success_data,
    ids_of,
    induct_shipment,
    invoice_sweep_payload,
    issued_invoice,
    open_invoice,
    refresh_invoice,
    refresh_shipment,
    refresh_shipper_account,
    shipper_with_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

SMALL_PARCEL = {
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}


def _acme(api):
    """SH-2001 holding the standard EXPRESS-only activated contract C1."""
    return shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )


def _list_shipments(api, **params):
    """Page the shipment collection as the billing desk sees it."""
    return validate_paginated(api.list_shipments(BILLING_OPS_HEADERS, dict(params)))


def test_01_a_three_row_result_set_pages_twice_and_reports_its_true_size(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the limit and offset are applied."
    PRD §2.3: "The `offset` parameter skips a number of leading records; it defaults to 0 and must not be negative."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §3.3: "Shipments can be read individually, returning both weight variants, the tolerance verdict, and all three status axes; and listed with optional filters on `shipper_id`, `service_level_id`, `contract_id`, `measurement_status`, `movement_status`, and `billing_status`."

    Design: Corner/entities/shipment_listing_reports_total_count_and_has_more_across_pages
    """
    shipper = _acme(api)
    for tracking_number in ("1Z-L-0001", "1Z-L-0002", "1Z-L-0003"):
        induct_shipment(
            api,
            shipper,
            service_level="EXPRESS",
            tracking_number=tracking_number,
            zone=2,
            residential_declared=False,
            **SMALL_PARCEL,
        )

    response = api.list_shipments(
        BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", (
        "a collection comes back as an array, got "
        f"{response.json()['response_type']!r}"
    )
    assert len(first_page) == 2, f"limit 2 must cap the page at 2 rows, got {len(first_page)}"
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3, (
        "total_count describes the whole filtered set, not the page, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True

    second_page, second_meta = _list_shipments(
        api, shipper_id=shipper.shipper_id, limit=2, offset=2
    )
    assert len(second_page) == 1, (
        f"one row remains behind the offset, got {len(second_page)}"
    )
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3, (
        "the second page reports the same set size as the first, got "
        f"{second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False

    seen = [row["tracking_number"] for row in first_page + second_page]
    assert sorted(seen) == ["1Z-L-0001", "1Z-L-0002", "1Z-L-0003"], (
        f"the two pages must cover every parcel exactly once, saw {seen}"
    )
    assert len(set(ids_of(first_page + second_page))) == 3, (
        "no row may appear on both pages"
    )

    billed, billed_meta = _list_shipments(
        api, shipper_id=shipper.shipper_id, billing_status="BILLED"
    )
    assert billed == [], (
        f"nothing has been swept yet, got {[row['tracking_number'] for row in billed]}"
    )
    assert billed_meta["total_count"] == 0, (
        f"an empty filtered set counts 0, got {billed_meta['total_count']}"
    )
    assert billed_meta["has_more"] is False


def test_02_the_detail_read_and_the_status_filters_agree_with_what_create_returned(api):
    """PRD §3.3: "Shipments can be read individually, returning both weight variants, the tolerance verdict, and all three status axes; and listed with optional filters on `shipper_id`, `service_level_id`, `contract_id`, `measurement_status`, `movement_status`, and `billing_status`."
    PRD §3.5: "A `CarrierOps` operator drives the shipment `IN_TRANSIT → DELIVERED`, and the server stamps `delivered_at` from the logical clock and increments the shipment's `version` by 1."
    PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp `created_at` in ascending order, so the oldest record appears first."

    Design: Corner/endpoints/shipment_create_read_and_filtered_list_round_trip
    """
    shipper = _acme(api)
    parcels = [
        induct_shipment(
            api,
            shipper,
            service_level="EXPRESS",
            tracking_number=tracking_number,
            zone=2,
            residential_declared=False,
            **SMALL_PARCEL,
        )
        for tracking_number in ("1Z-E-1001", "1Z-E-1002", "1Z-E-1003")
    ]
    first, _second, third = parcels
    validate_success(api.deliver_shipment(first.shipment_id, CARRIER_OPS_HEADERS))

    detail = get_success_data(api.get_shipment(first.shipment_id, BILLING_OPS_HEADERS))
    assert detail["id"] == first.shipment_id
    assert detail["tracking_number"] == "1Z-E-1001"
    assert_lbs(detail["billable_weight_lbs"], 7, "billable_weight_lbs")
    assert detail["movement_status"] == "DELIVERED", (
        f"the detail read must show the delivery, got {detail['movement_status']}"
    )

    delivered, delivered_meta = _list_shipments(
        api, shipper_id=shipper.shipper_id, movement_status="DELIVERED"
    )
    assert delivered_meta["total_count"] == 1, (
        f"only one parcel has been delivered, got {delivered_meta['total_count']}"
    )
    assert ids_of(delivered) == [first.shipment_id]

    moving, moving_meta = _list_shipments(
        api,
        shipper_id=shipper.shipper_id,
        movement_status="IN_TRANSIT",
        limit=2,
        offset=0,
    )
    assert moving_meta["total_count"] == 2, (
        f"two parcels are still moving, got {moving_meta['total_count']}"
    )
    assert len(moving) == 2
    assert moving_meta["has_more"] is False, (
        "a two-row set fits inside a limit of 2, so nothing follows it"
    )

    tail, tail_meta = _list_shipments(api, shipper_id=shipper.shipper_id, limit=2, offset=2)
    assert len(tail) == 1
    assert tail[0]["id"] == third.shipment_id, (
        "the collection is ordered oldest first, so the third induction is the "
        f"third row, got {tail[0]['tracking_number']}"
    )
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    validate_error(
        api.list_shipments(
            BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 0}
        ),
        ERR_INVALID_PAGINATION,
        400,
    )


def test_03_the_billing_preview_prices_the_parcel_without_persisting_anything(api):
    """PRD §3.6: "The preview creates nothing and mutates nothing; it returns `shipment_id`, `contract_id`, `billable_weight_lbs`, `billable_weight_basis`, `rate_cents_per_lb`, `transportation_base_cents`, `surcharge_cents`, `accessorial_total_cents`, and `line_total_cents`, computed by exactly the line-pricing rules above."
    PRD §3.6: "**Previewing a price without billing.** `BillingOps` and `RevenueAuditor` may dry-run the pricing of a single package at its current billable weight."
    PRD §3.4: "The **weight allowance** is the greater of half a pound and two percent of the shipment's `declared_weight_lbs`, where the percentage figure is itself rounded half up to one decimal place before the comparison of the two candidates."
    PRD §3.4: "The shipment's `billable_weight_lbs` then switches to `final_billable_weight_lbs` and stays there for as long as a scan exists."

    Design: Corner/endpoints/the_billing_preview_prices_without_persisting_anything
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-E-5001",
        zone=2,
        residential_declared=False,
        declared_length_in=30,
        declared_width_in=12,
        declared_height_in=12,
        declared_weight_lbs=40.0,
    )
    assert parcel.shipment["declared_cube_in3"] == 4320

    first = get_success_data(
        api.get_billing_preview(parcel.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_money_equals(first["line_total_cents"], 13600, "line_total_cents")
    assert_lbs(first["billable_weight_lbs"], 40, "billable_weight_lbs")
    assert first["billable_weight_basis"] == "ACTUAL", (
        "40 actual pounds beat the 32 dimensional pounds of a 4320 in3 cube, got "
        f"{first['billable_weight_basis']}"
    )
    assert first["rate_cents_per_lb"] == 340, (
        f"40 lb sits in the 21-70 lb zone-2 band, got {first['rate_cents_per_lb']}"
    )
    assert first["shipment_id"] == parcel.shipment_id
    assert first["contract_id"] == shipper.contract_id

    auditor_view = get_success_data(
        api.get_billing_preview(parcel.shipment_id, REVENUE_AUDITOR_HEADERS)
    )
    assert_money_equals(
        auditor_view["line_total_cents"], first["line_total_cents"], "line_total_cents"
    )

    unmoved = refresh_shipment(api, parcel.shipment_id)
    assert_version_unchanged(parcel.shipment, unmoved)

    scan = add_scan(
        api,
        parcel.shipment_id,
        expected_version=parcel.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=30,
        scanned_width_in=12,
        scanned_height_in=12,
        scanned_weight_lbs=40.7,
    )
    assert_lbs(scan["weight_variance_lbs"], 0.7, "weight_variance_lbs")
    assert scan["tolerance_status"] == "WITHIN_TOLERANCE", (
        "the allowance is the greater of 0.5 and 0.8 lb, and 0.7 lb stays under 0.8, "
        f"got {scan['tolerance_status']}"
    )

    after_scan = get_success_data(
        api.get_billing_preview(parcel.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_lbs(after_scan["billable_weight_lbs"], 41, "billable_weight_lbs")
    assert_money_equals(after_scan["line_total_cents"], 13940, "line_total_cents")

    invoices, invoice_meta = validate_paginated(
        api.list_invoices(BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id})
    )
    assert invoice_meta["total_count"] == 0, (
        f"no preview may create an invoice, found {len(invoices)}"
    )
    _lines, line_meta = validate_paginated(
        api.list_invoice_lines(BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert line_meta["total_count"] == 0, (
        f"no preview may create a line, found {line_meta['total_count']}"
    )

    governed = refresh_shipment(api, parcel.shipment_id)
    assert governed["measurement_status"] == "SCANNED"
    assert governed["version"] == parcel.shipment_version + 1, (
        "the scan is the only mutation the parcel saw, expected version "
        f"{parcel.shipment_version + 1}, got {governed['version']}"
    )


def test_04_every_child_row_is_reachable_from_its_parent_id_alone(api):
    """PRD §3.6: "Invoice lines may be read individually — returning billable weight and basis, rate, transportation base, surcharge, accessorial total, adjustment total, and line total — and listed with optional filters on `invoice_id` and `shipment_id`."
    PRD §3.5: "Every accessorial ever attached to a package remains readable, including `WAIVED` and `REVERSED` history rows, through a per-shipment listing that accepts optional filters on `status` and on `code`."
    PRD §3.4: "The full measurement history of a package is readable as a list ordered oldest first, so the sequence of variances and verdicts that produced the current determination is auditable end to end."
    PRD §3.6: "The selected packages are then ordered by `pickup_date` ascending and, within a date, by the shipment's `created_at` ascending — never by identifier — and exactly one `InvoiceLine` is created per package in that order."

    Design: Corner/entities/flat_topology_children_are_reachable_from_every_parent_id
    """
    shipper = _acme(api)
    first = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-F-0001",
        zone=2,
        residential_declared=False,
        **SMALL_PARCEL,
    )
    second = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-F-0002",
        zone=2,
        residential_declared=False,
        **SMALL_PARCEL,
    )
    charge = add_manual_accessorial(
        api, first.shipment_id, "ADDRESS_CORRECTION", reason="bad suite number"
    )
    scan = add_scan(
        api,
        first.shipment_id,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=12,
        scanned_width_in=10,
        scanned_height_in=8,
        scanned_weight_lbs=6.0,
    )
    validate_success(api.deliver_shipment(first.shipment_id, CARRIER_OPS_HEADERS))
    validate_success(api.deliver_shipment(second.shipment_id, CARRIER_OPS_HEADERS))
    invoice = open_invoice(
        api,
        shipper,
        [first.shipment_id, second.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )

    by_invoice, by_invoice_meta = validate_paginated(
        api.list_invoice_lines(
            BILLING_OPS_HEADERS, {"invoice_id": invoice.invoice_id, "limit": 100}
        )
    )
    assert by_invoice_meta["total_count"] == 2, (
        f"both parcels were swept onto one invoice, got {by_invoice_meta['total_count']}"
    )
    assert all(row["invoice_id"] == invoice.invoice_id for row in by_invoice), (
        f"a foreign key filter may not leak: {[row['invoice_id'] for row in by_invoice]}"
    )

    by_shipment, by_shipment_meta = validate_paginated(
        api.list_invoice_lines(
            BILLING_OPS_HEADERS, {"shipment_id": second.shipment_id, "limit": 100}
        )
    )
    assert by_shipment_meta["total_count"] == 1, (
        f"one line belongs to the second parcel, got {by_shipment_meta['total_count']}"
    )
    assert by_shipment[0]["shipment_id"] == second.shipment_id

    charged, charged_meta = validate_paginated(
        api.list_accessorials(first.shipment_id, BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert charged_meta["total_count"] == 1, (
        f"the hand-entered charge is the parcel's only one, got {charged_meta['total_count']}"
    )
    assert charged[0]["id"] == charge["id"]
    assert charged[0]["shipment_id"] == first.shipment_id

    _sibling_charges, sibling_meta = validate_paginated(
        api.list_accessorials(second.shipment_id, BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert sibling_meta["total_count"] == 0, (
        "the sibling parcel's charge must not leak across the foreign key, got "
        f"{sibling_meta['total_count']}"
    )

    _sibling_scans, sibling_scan_meta = validate_paginated(
        api.list_scans(second.shipment_id, CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert sibling_scan_meta["total_count"] == 0, (
        f"only the first parcel was scanned, got {sibling_scan_meta['total_count']}"
    )
    owned_scans, _owned_meta = validate_paginated(
        api.list_scans(first.shipment_id, CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert ids_of(owned_scans) == [scan["id"]]

    invoices, invoices_meta = validate_paginated(
        api.list_invoices(BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id})
    )
    assert invoices_meta["total_count"] == 1
    assert ids_of(invoices) == [invoice.invoice_id]

    rolled_up = refresh_invoice(api, invoice.invoice_id)
    assert rolled_up["line_count"] == 2
    assert_money_equals(
        rolled_up["transportation_subtotal_cents"], 5320, "transportation_subtotal_cents"
    )
    assert_money_equals(
        rolled_up["accessorial_subtotal_cents"], 2200, "accessorial_subtotal_cents"
    )


def test_05_a_line_leads_to_its_dispute_and_on_to_the_credit_the_dispute_minted(api):
    """PRD §3.9: "Each filing creates an immutable `EvidenceItem` recording its `dispute_id`, the `submitted_by_user_id` taken from the filer's `X-User-ID`, and a computed `accepted` verdict: the item is accepted when the dispute's `required_item_type` is null at submission time, or when the item's `item_type` equals the outstanding `required_item_type`; otherwise it is not accepted."
    PRD §3.9: "This is reachable both as `UNDER_REVIEW → EVIDENCE_REQUESTED` and as `SUBMITTED → EVIDENCE_REQUESTED`, and both branches behave identically: the requested type is stored in `required_item_type`, `round_count` rises by 1, and the dispute's `version` increments by 1."
    PRD §3.9: "*Hop 2* creates a `BillingAdjustment` with `reason` `DISPUTE_CREDIT`, `delta_cents` equal to the negation of `granted_credit_cents`, `dispute_id` set to this dispute, and `created_by_user_id` set to the literal `system` — and it is created **already at `APPLIED`**, bypassing the segregation-of-duties gate entirely because no human proposed it."
    PRD §3.8: "Adjustments may be read individually — exposing the proposer, the applier, and any linkage to a dispute or guarantee claim — and listed with optional filters on `invoice_line_id`, `dispute_id`, `guarantee_claim_id`, and `status`."
    PRD §3.9: "Disputes may be read individually and listed with optional filters on `invoice_line_id` and `status`; a dispute's evidence items are listable with their acceptance verdicts."

    Design: Corner/endpoints/an_invoice_line_links_its_shipment_dispute_and_adjustment
    """
    shipper = _acme(api)
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-E-4001",
        zone=2,
        residential_declared=True,
        **SMALL_PARCEL,
    )
    invoice = issued_invoice(
        api,
        open_invoice(
            api,
            shipper,
            [parcel.shipment_id],
            period_start="2026-08-01",
            period_end="2026-08-01",
        ),
    )

    rows, rows_meta = validate_paginated(
        api.list_invoice_lines(
            BILLING_OPS_HEADERS, {"shipment_id": parcel.shipment_id, "limit": 100}
        )
    )
    assert rows_meta["total_count"] == 1
    line = rows[0]
    assert line["invoice_id"] == invoice.invoice_id, (
        "the shipment id alone resolved the line and the line names its invoice, got "
        f"{line['invoice_id']}"
    )
    assert_money_equals(line["line_total_cents"], 3250, "line_total_cents")

    dispute = validate_success(
        api.create_dispute(
            dispute_payload(
                line["id"],
                claim_type="ACCESSORIAL",
                claimed_reason="commercial dock, not residential",
                disputed_codes=["RESIDENTIAL"],
            ),
            shipper.shipper_headers,
        ),
        201,
    )

    requested = validate_success(
        api.request_evidence(dispute["id"], "ADDRESS_PROOF", REVENUE_AUDITOR_HEADERS)
    )
    assert requested["round_count"] == 1, (
        f"one document was asked for, got round_count {requested['round_count']}"
    )
    assert requested["required_item_type"] == "ADDRESS_PROOF"

    evidence = validate_success(
        api.submit_evidence(
            dispute["id"],
            evidence_payload(
                item_type="ADDRESS_PROOF", reference="doc://address-proof/9911"
            ),
            shipper.shipper_headers,
        ),
        201,
    )
    assert evidence["accepted"] is True, (
        "the filed type matches the outstanding request, so it is accepted"
    )
    under_review = get_success_data(
        api.get_dispute(dispute["id"], REVENUE_AUDITOR_HEADERS)
    )
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["accepted_evidence_count"] == 1
    assert under_review["required_item_type"] is None

    resolved = validate_success(
        api.resolve_dispute(dispute["id"], "UPHELD", REVENUE_AUDITOR_HEADERS)
    )
    assert resolved["status"] == "UPHELD"
    assert_money_equals(
        resolved["granted_credit_cents"], 590, "granted_credit_cents"
    )

    by_dispute, by_dispute_meta = validate_paginated(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"dispute_id": dispute["id"], "limit": 100}
        )
    )
    assert by_dispute_meta["total_count"] == 1, (
        "the dispute id must find the credit it minted, got "
        f"{by_dispute_meta['total_count']} adjustments"
    )
    credit = by_dispute[0]
    assert_money_equals(credit["delta_cents"], -590, "delta_cents")
    assert credit["status"] == "APPLIED", (
        f"a system-minted dispute credit is born applied, got {credit['status']}"
    )
    assert credit["created_by_user_id"] == SYSTEM_ACTOR
    assert credit["invoice_line_id"] == line["id"]

    by_line, by_line_meta = validate_paginated(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"invoice_line_id": line["id"], "limit": 100}
        )
    )
    assert by_line_meta["total_count"] == 1
    assert ids_of(by_line) == [credit["id"]], (
        "the line filter and the dispute filter must find the same single row"
    )

    back_to_dispute, _ = validate_paginated(
        api.list_disputes(
            BILLING_OPS_HEADERS, {"invoice_line_id": line["id"], "limit": 100}
        )
    )
    assert ids_of(back_to_dispute) == [dispute["id"]], (
        "every link must be navigable in both directions"
    )
    filed_evidence, _ = validate_paginated(
        api.list_dispute_evidence(dispute["id"], REVENUE_AUDITOR_HEADERS, {"limit": 100})
    )
    assert ids_of(filed_evidence) == [evidence["id"]]

    adjusted = refresh_invoice(api, invoice.invoice_id)
    assert adjusted["status"] == "ADJUSTED"
    assert_money_equals(adjusted["net_amount_cents"], 2660, "net_amount_cents")

    charges, _ = validate_paginated(
        api.list_accessorials(parcel.shipment_id, BILLING_OPS_HEADERS, {"limit": 100})
    )
    residential = [row for row in charges if row["code"] == "RESIDENTIAL"]
    assert len(residential) == 1
    assert residential[0]["status"] == "WAIVED", (
        "an upheld accessorial dispute waives the charge it credited, got "
        f"{residential[0]['status']}"
    )


def test_06_each_write_is_already_visible_to_the_very_next_read(api):
    """PRD §3.3: "The owning account's `total_shipment_count` and `unbilled_shipment_count` each increase by 1, and `open_charges_cents` is recomputed."
    PRD §3.6: "Every swept package moves `UNBILLED → BILLED` on the billing axis, and the owning account's `unbilled_shipment_count` falls by the line count while `billed_shipment_count` rises by the same amount, preserving the conserved-package-count invariant of §2.11."
    PRD §3.7: "The owning account's `open_charges_cents` rises by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1."
    PRD §3.7: "The operator supplies a `payment_reference`, the remittance reference captured at settlement, which is stored on the invoice."
    PRD §3.1: "Reading an account back returns those five figures computed live, so the account view is always the authoritative ledger snapshot."

    Design: Corner/consistency_model/every_write_is_visible_to_the_next_read_with_no_settling_period
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-Y-1001",
        zone=2,
        residential_declared=False,
        **SMALL_PARCEL,
    )

    after_induction = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(after_induction, total=1, unbilled=1, billed=0, open_charges_cents=0)

    validate_success(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
    delivered = refresh_shipment(api, parcel.shipment_id)
    assert delivered["movement_status"] == "DELIVERED"
    assert_instant(delivered["delivered_at"], DEFAULT_CLOCK_UTC, "delivered_at")

    swept = validate_success(
        api.create_invoice(
            invoice_sweep_payload(
                shipper.shipper_id, period_start="2026-08-01", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    assert_money_equals(swept["net_amount_cents"], 2660, "net_amount_cents")

    after_sweep = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(after_sweep, total=1, unbilled=0, billed=1, open_charges_cents=0)
    billed_parcel = refresh_shipment(api, parcel.shipment_id)
    assert billed_parcel["billing_status"] == "BILLED", (
        "the sweep's effect on the package is readable at once, got "
        f"{billed_parcel['billing_status']}"
    )

    issued = validate_success(api.issue_invoice(swept["id"], BILLING_OPS_HEADERS))
    assert_fields(issued, {"status": "ISSUED"})
    assert_instant(issued["issued_at"], DEFAULT_CLOCK_UTC, "issued_at")
    assert_instant(
        issued["dispute_deadline_utc"], "2026-10-30T00:00:00Z", "dispute_deadline_utc"
    )

    after_issue = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(after_issue, open_charges_cents=2660)

    settled = validate_success(
        api.settle_invoice(swept["id"], "ACH-77120", BILLING_OPS_HEADERS)
    )
    assert settled["status"] == "SETTLED"
    assert settled["payment_reference"] == "ACH-77120"

    after_settlement = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        after_settlement, open_charges_cents=0, credit_balance_cents=0
    )
    repeated = refresh_shipper_account(api, shipper.shipper_id)
    assert repeated == after_settlement, (
        "a second identical read must return exactly the same body, so no assertion "
        "here ever needs a retry"
    )
