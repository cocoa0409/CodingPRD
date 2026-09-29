"""The two recovery channels, and the gates a shipper must pass to use them.

A dispute may only name a charge the parcel actually carries, so an accessorial
claim against an oversize fee that was never assessed is refused exactly as an
accessorial claim naming nothing at all is. The guarantee channel is stricter
still: it counts fifteen days from delivery to the second, it answers each of
the four ways a package can be ineligible with its own error, and it offers a
bulk sweep that files every eligible claim in one call and silently steps over
the packages that do not qualify rather than failing the run.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_CLAIM_WINDOW_CLOSED,
    ERR_DISPUTED_CODE_NOT_ASSESSED,
    ERR_GUARANTEE_SUSPENDED,
    ERR_SERVICE_NOT_GUARANTEED,
    ERR_SHIPMENT_NOT_DELIVERED,
    ERR_SHIPMENT_NOT_INVOICED,
    REVENUE_AUDITOR_HEADERS,
    activate_surcharge_window,
    assert_fields,
    assert_instant,
    assert_money_equals,
    assert_null_fields,
    cancel_surcharge_window,
    create_surcharge_window,
    dispute_payload,
    get_success_data,
    guarantee_claim_payload,
    guarantee_scan_payload,
    ids_of,
    induct_shipment,
    issued_invoice,
    open_invoice,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipment,
    set_clock,
    shipper_with_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

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
RESIDENTIAL_CENTS = 590

# An EXPRESS parcel inducted at the default clock commits to 24 hours, so it is
# late by three hours - 10800 seconds - when it lands at 03:00 the next day.
COMMITMENT_INSTANT = "2026-08-02T00:00:00Z"
LATE_DELIVERY_INSTANT = "2026-08-02T03:00:00Z"
LATE_BY_SECONDS = 10800
CLAIM_EDGE_INSTANT = "2026-08-17T03:00:00Z"
ONE_SECOND_LATER_INSTANT = "2026-08-17T03:00:01Z"


def _acme(api, with_ground=False):
    """SH-2001 holding one ACTIVE contract and the guaranteed EXPRESS service."""
    return shipper_with_active_contract(
        api,
        account_number=ACME_ACCOUNT_NUMBER,
        name=ACME_NAME,
        with_ground=with_ground,
    )


def _file_claim(api, shipment_id, reason):
    """File one guarantee claim as the revenue auditor, returning the response."""
    return api.create_guarantee_claim(
        guarantee_claim_payload(shipment_id, claimed_reason=reason),
        REVENUE_AUDITOR_HEADERS,
    )


def _claims(api, **params):
    """Page the guarantee-claim register through the auditor's own view."""
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(api.list_guarantee_claims(REVENUE_AUDITOR_HEADERS, query))


def test_01_an_accessorial_dispute_may_only_name_a_charge_the_parcel_carries(api):
    """OVERSIZE is refused on a parcel that only ever earned a residential fee.

    The line under dispute carries exactly one accessorial charge, so naming a
    different code is a cross-entity miss rather than a bad enum value, and
    naming no code at all fails the same rule from the other side. Only the code
    actually assessed opens a dispute, and it opens with nothing credited.

    PRD §3.9: "Finally, for an `ACCESSORIAL` claim, `disputed_codes` must be non-empty and every code it lists must have at least one `ASSESSED` accessorial charge on the disputed line's shipment; for a `WEIGHT` claim, `disputed_codes` must be empty or absent."
    PRD §3.9: "A violation of either half is `ERR_DISPUTED_CODE_NOT_ASSESSED` (HTTP 422)."
    PRD §3.9: "A new dispute opens at `status` `SUBMITTED` with `shipper_user_id` stamped from the filer's `X-User-ID`, `round_count` at 0, `required_item_type` null, `accepted_evidence_count` at 0, `granted_credit_cents` at 0, and `resolved_at` null."
    PRD §3.3: "`RESIDENTIAL` is assessed when the shipment's `residential_declared` is true *and* the governing contract's `residential_waived` is false."
    PRD §3.9: "Disputes may be read individually and listed with optional filters on `invoice_line_id` and `status`; a dispute's evidence items are listable with their acceptance verdicts."

    Design: Corner/validations/an_accessorial_dispute_must_name_a_code_that_was_actually_assessed
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-S-4001",
        zone=2,
        residential_declared=True,
        declared_length_in=12,
        declared_width_in=10,
        declared_height_in=8,
        declared_weight_lbs=6.0,
    )
    assert_money_equals(
        parcel.shipment["accessorial_total_cents"],
        RESIDENTIAL_CENTS,
        "1Z-S-4001 accessorial total",
    )
    get_success_data(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))

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
    line_id = invoice.line_by_shipment[parcel.shipment_id]
    line = refresh_invoice_line(api, line_id)
    assert_money_equals(line["transportation_base_cents"], TRANSPORTATION_CENTS, "line base")
    assert_money_equals(line["accessorial_total_cents"], RESIDENTIAL_CENTS, "line accessorials")
    assert_money_equals(
        line["line_total_cents"], TRANSPORTATION_CENTS + RESIDENTIAL_CENTS, "line total"
    )

    validate_error(
        api.create_dispute(
            dispute_payload(
                line_id,
                claim_type="ACCESSORIAL",
                claimed_reason="we were charged for an oversize parcel",
                disputed_codes=["OVERSIZE"],
            ),
            shipper.shipper_headers,
        ),
        ERR_DISPUTED_CODE_NOT_ASSESSED,
        422,
    )
    validate_error(
        api.create_dispute(
            dispute_payload(
                line_id,
                claim_type="ACCESSORIAL",
                claimed_reason="this is a commercial address",
                disputed_codes=[],
            ),
            shipper.shipper_headers,
        ),
        ERR_DISPUTED_CODE_NOT_ASSESSED,
        422,
    )

    accepted = validate_success(
        api.create_dispute(
            dispute_payload(
                line_id,
                claim_type="ACCESSORIAL",
                claimed_reason="this is a commercial address",
                disputed_codes=["RESIDENTIAL"],
            ),
            shipper.shipper_headers,
        ),
        201,
    )
    assert_fields(
        accepted,
        {
            "invoice_line_id": line_id,
            "claim_type": "ACCESSORIAL",
            "status": "SUBMITTED",
            "disputed_codes": ["RESIDENTIAL"],
            "round_count": 0,
            "accepted_evidence_count": 0,
            "granted_credit_cents": 0,
        },
    )
    assert_null_fields(accepted, ["required_item_type", "resolved_at"])

    rows, meta = validate_paginated(
        api.list_disputes(BILLING_OPS_HEADERS, {"invoice_line_id": line_id, "limit": 100})
    )
    assert meta["total_count"] == 1, (
        "the two refused filings must have persisted nothing, got total_count "
        f"{meta['total_count']}"
    )
    assert ids_of(rows) == [accepted["id"]], (
        "the only dispute on the line is the residential one"
    )


def test_02_the_claim_window_is_open_at_fifteen_days_and_shut_one_second_later(api):
    """Two identical late parcels, one second apart, and only one is claimable.

    Both parcels commit to 24 hours, both land three hours late, and both sit on
    the same issued invoice. The first claim is filed at exactly delivery plus
    fifteen days and is accepted for the transportation base alone; the second is
    filed one second after that and is refused. Nothing about the second parcel
    changes, and the invoice carries no proposal either way.

    PRD §3.9: "Seven guards apply, in this order: the `shipment_id` must resolve (`ERR_SHIPMENT_NOT_FOUND`); the package's `movement_status` must be `DELIVERED`, else `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409); the logical clock must be at or before `delivered_at` advanced by fifteen days, with equality still inside the window, else `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422); no other claim on the same `shipment_id` may be sitting at `FILED`, `APPROVED`, or `REFUNDED`, else `ERR_DUPLICATE_CLAIM` (HTTP 409) — a previously `DENIED` claim does not block a refile; the purchased service level must have `guaranteed` set to true, else `ERR_SERVICE_NOT_GUARANTEED` (HTTP 422); the package must sit on an invoice line whose `voided` is false and whose invoice is `ISSUED` or `ADJUSTED`, else `ERR_SHIPMENT_NOT_INVOICED` (HTTP 422) because there is nothing to refund; no `ACTIVE` `PEAK_SEASON` surcharge window may cover the package's `pickup_date`, else `ERR_GUARANTEE_SUSPENDED` (HTTP 422); and the delivery must be strictly late, else `ERR_SHIPMENT_NOT_LATE` (HTTP 422)."
    PRD §3.9: "The commitment instant is the package's `guarantee_deadline_utc`, itself `picked_up_at` advanced by the service level's `guarantee_hours`."
    PRD §3.9: "The `late_by_seconds` figure is the whole number of seconds from the deadline to `delivered_at`, and it is strictly positive for any fileable claim."
    PRD §3.9: "The `candidate_refund_cents` is therefore 0 when the package is not late or when the guarantee is suspended, and otherwise it is the non-voided invoice line's `transportation_base_cents` — the floored transportation charge and nothing else."
    PRD §3.9: "A filed claim opens at `status` `FILED` with `filed_by_user_id` stamped from the filer's `X-User-ID`, `invoice_line_id` resolved to the package's live line, `guarantee_deadline_utc` and `delivered_at` frozen from the shipment, `late_by_seconds` and `candidate_refund_cents` computed as above, `refund_cents` at 0, and `adjudicated_at` null."

    Design: Corner/validations/the_claim_window_closes_one_second_after_fifteen_days
    """
    shipper = _acme(api)
    inside = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-T-5001", **SMALL_PARCEL
    )
    outside = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-T-5002", **SMALL_PARCEL
    )
    for label, parcel in (("1Z-T-5001", inside), ("1Z-T-5002", outside)):
        assert_instant(
            parcel.shipment["guarantee_deadline_utc"],
            COMMITMENT_INSTANT,
            f"{label} guarantee deadline",
        )

    set_clock(api, LATE_DELIVERY_INSTANT)
    for parcel in (inside, outside):
        get_success_data(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
        assert_instant(
            refresh_shipment(api, parcel.shipment_id)["delivered_at"],
            LATE_DELIVERY_INSTANT,
            "delivered_at",
        )

    invoice = issued_invoice(
        api,
        open_invoice(
            api,
            shipper,
            [inside.shipment_id, outside.shipment_id],
            period_start="2026-08-01",
            period_end="2026-08-01",
        ),
    )
    assert invoice.invoice["line_count"] == 2, (
        f"both late parcels must be billed, got line_count {invoice.invoice['line_count']}"
    )
    for parcel in (inside, outside):
        line = refresh_invoice_line(api, invoice.line_by_shipment[parcel.shipment_id])
        assert_money_equals(
            line["transportation_base_cents"], TRANSPORTATION_CENTS, "line transportation"
        )

    # Fifteen days after 2026-08-02T03:00:00Z is 2026-08-17T03:00:00Z, and
    # equality is still inside the window.
    set_clock(api, CLAIM_EDGE_INSTANT)
    claim = validate_success(
        _file_claim(
            api, inside.shipment_id, "delivered three hours past the 24 h commitment"
        ),
        201,
    )
    assert_fields(
        claim,
        {
            "shipment_id": inside.shipment_id,
            "invoice_line_id": invoice.line_by_shipment[inside.shipment_id],
            "status": "FILED",
            "late_by_seconds": LATE_BY_SECONDS,
        },
    )
    assert_money_equals(
        claim["candidate_refund_cents"], TRANSPORTATION_CENTS, "candidate refund"
    )
    assert_money_equals(claim["refund_cents"], 0, "refund before adjudication")
    assert_instant(
        claim["guarantee_deadline_utc"], COMMITMENT_INSTANT, "frozen guarantee deadline"
    )
    assert_instant(claim["delivered_at"], LATE_DELIVERY_INSTANT, "frozen delivered_at")
    assert_null_fields(claim, ["adjudicated_at"])

    set_clock(api, ONE_SECOND_LATER_INSTANT)
    validate_error(
        _file_claim(
            api, outside.shipment_id, "delivered three hours past the 24 h commitment"
        ),
        ERR_CLAIM_WINDOW_CLOSED,
        422,
    )

    rows, meta = _claims(api)
    assert meta["total_count"] == 1, (
        f"the refused claim must have created nothing, got {meta['total_count']}"
    )
    assert ids_of(rows) == [claim["id"]], "only the in-window claim may exist"
    _, late_meta = _claims(api, shipment_id=outside.shipment_id)
    assert late_meta["total_count"] == 0, (
        f"1Z-T-5002 must carry no claim at all, got {late_meta['total_count']}"
    )

    final = refresh_invoice(api, invoice.invoice_id)
    assert final["pending_adjustment_count"] == 0, (
        "filing alone proposes nothing, got pending_adjustment_count "
        f"{final['pending_adjustment_count']}"
    )


def test_03_the_audit_sweep_files_the_two_late_parcels_and_steps_over_the_third(api):
    """One call, three delivered parcels, two claims filed and one skipped.

    The bulk sweep does not fail because a package was on time: it reports the
    on-time parcel as skipped and files the other two with exactly the figures a
    single filing would have produced. Run again, the same call files nothing at
    all, because the claims it just created now make every parcel a duplicate.

    PRD §3.9: "The sweep files one `FILED` claim for every eligible late package of that shipper, oldest `pickup_date` first, applying exactly the same eligibility rules and computing exactly the same figures as a single filing would."
    PRD §3.9: "Ineligible packages are skipped silently — the sweep never fails because one package was on time, unguaranteed, uninvoiced, or already claimed."
    PRD §3.9: "It returns `filed_count`, `skipped_count`, and the `claim_ids` of the claims it created."
    PRD §3.9: "The package is late when its `delivered_at` is **strictly after** that instant; a delivery landing exactly on the commitment instant is on time and earns nothing."
    PRD §3.9: "The `candidate_refund_cents` is therefore 0 when the package is not late or when the guarantee is suspended, and otherwise it is the non-voided invoice line's `transportation_base_cents` — the floored transportation charge and nothing else."

    Design: Corner/endpoints/the_guarantee_audit_sweep_files_every_eligible_claim_in_one_call
    """
    shipper = _acme(api)
    late_pair = [
        induct_shipment(
            api, shipper, service_level="EXPRESS", tracking_number=tracking, **SMALL_PARCEL
        )
        for tracking in ("1Z-E-3001", "1Z-E-3002")
    ]
    on_time = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-E-3003", **SMALL_PARCEL
    )

    # Half a day into the 24 hour commitment is comfortably on time.
    set_clock(api, "2026-08-01T12:00:00Z")
    get_success_data(api.deliver_shipment(on_time.shipment_id, CARRIER_OPS_HEADERS))
    set_clock(api, LATE_DELIVERY_INSTANT)
    for parcel in late_pair:
        get_success_data(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
    assert_instant(
        refresh_shipment(api, on_time.shipment_id)["delivered_at"],
        "2026-08-01T12:00:00Z",
        "1Z-E-3003 delivered_at",
    )

    invoice = issued_invoice(
        api,
        open_invoice(
            api,
            shipper,
            [parcel.shipment_id for parcel in late_pair] + [on_time.shipment_id],
            period_start="2026-08-01",
            period_end="2026-08-01",
        ),
    )
    assert invoice.invoice["line_count"] == 3, (
        f"all three parcels must be billed, got line_count {invoice.invoice['line_count']}"
    )

    sweep = validate_success(
        api.scan_guarantee_claims(
            guarantee_scan_payload(
                shipper.shipper_id, period_start="2026-08-01", period_end="2026-08-01"
            ),
            REVENUE_AUDITOR_HEADERS,
        ),
        200,
    )
    assert_fields(sweep, {"filed_count": 2, "skipped_count": 1})
    assert len(sweep["claim_ids"]) == 2, (
        f"claim_ids must name the two filed claims, got {sweep['claim_ids']}"
    )

    filed_ids = []
    for label, parcel in (("1Z-E-3001", late_pair[0]), ("1Z-E-3002", late_pair[1])):
        rows, meta = _claims(api, shipment_id=parcel.shipment_id)
        assert meta["total_count"] == 1, (
            f"{label} must carry exactly one claim, got {meta['total_count']}"
        )
        claim = rows[0]
        assert_fields(
            claim,
            {
                "status": "FILED",
                "late_by_seconds": LATE_BY_SECONDS,
                "invoice_line_id": invoice.line_by_shipment[parcel.shipment_id],
            },
        )
        assert_money_equals(
            claim["candidate_refund_cents"],
            TRANSPORTATION_CENTS,
            f"{label} candidate refund",
        )
        filed_ids.append(claim["id"])
    assert set(sweep["claim_ids"]) == set(filed_ids), (
        "the returned claim_ids must be exactly the claims the sweep created"
    )

    _, on_time_meta = _claims(api, shipment_id=on_time.shipment_id)
    assert on_time_meta["total_count"] == 0, (
        f"the on-time parcel earns nothing, got {on_time_meta['total_count']}"
    )

    repeat = validate_success(
        api.scan_guarantee_claims(
            guarantee_scan_payload(
                shipper.shipper_id, period_start="2026-08-01", period_end="2026-08-01"
            ),
            REVENUE_AUDITOR_HEADERS,
        ),
        200,
    )
    assert_fields(repeat, {"filed_count": 0, "skipped_count": 3})
    assert repeat["claim_ids"] == [], (
        f"a second sweep creates nothing, got claim_ids {repeat['claim_ids']}"
    )

    rows, meta = _claims(api)
    assert meta["total_count"] == 2, (
        f"two sweeps must leave exactly two claims, got {meta['total_count']}"
    )
    assert set(ids_of(rows)) == set(filed_ids), (
        "the register holds only the claims of the first sweep"
    )
    assert refresh_invoice(api, invoice.invoice_id)["pending_adjustment_count"] == 0, (
        "filing alone moves no money, so no adjustment may be pending"
    )


def test_04_four_ways_to_be_ineligible_answer_with_four_different_errors(api):
    """Unguaranteed, undelivered, uninvoiced and peak-suspended, each named.

    All four parcels belong to the same shipper and three of the four are three
    hours late, so lateness is never what refuses them. The guard order decides
    which error each one hears, and only the peak suspension is reversible: once
    the window is withdrawn the same filing that was refused succeeds unchanged.

    PRD §3.9: "Seven guards apply, in this order: the `shipment_id` must resolve (`ERR_SHIPMENT_NOT_FOUND`); the package's `movement_status` must be `DELIVERED`, else `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409); the logical clock must be at or before `delivered_at` advanced by fifteen days, with equality still inside the window, else `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422); no other claim on the same `shipment_id` may be sitting at `FILED`, `APPROVED`, or `REFUNDED`, else `ERR_DUPLICATE_CLAIM` (HTTP 409) — a previously `DENIED` claim does not block a refile; the purchased service level must have `guaranteed` set to true, else `ERR_SERVICE_NOT_GUARANTEED` (HTTP 422); the package must sit on an invoice line whose `voided` is false and whose invoice is `ISSUED` or `ADJUSTED`, else `ERR_SHIPMENT_NOT_INVOICED` (HTTP 422) because there is nothing to refund; no `ACTIVE` `PEAK_SEASON` surcharge window may cover the package's `pickup_date`, else `ERR_GUARANTEE_SUSPENDED` (HTTP 422); and the delivery must be strictly late, else `ERR_SHIPMENT_NOT_LATE` (HTTP 422)."
    PRD §3.2: "When `guaranteed` is false the service carries no money-back commitment at all and no guarantee claim may ever be filed against a package that bought it."
    PRD §3.3: "It also computes `guarantee_deadline_utc` as `picked_up_at` advanced by the purchased service's `guarantee_hours`; when the purchased service has `guaranteed` set to false, `guarantee_deadline_utc` is null instead, because there is no commitment to miss."
    PRD §3.9: "The money-back commitment is suspended, however, when there exists a surcharge window whose `status` is `ACTIVE`, whose `kind` is `PEAK_SEASON`, whose half-open range contains the package's `pickup_date` — on or after `start_date` and strictly before `end_date` — and whose scope matches, meaning either its `service_level_id` is null or it equals the package's `service_level_id`."
    PRD §3.2: "Cancellation reaches the window from either of two states: `SCHEDULED` → `CANCELLED` simply retires an unarmed window and bumps its `version`; `ACTIVE` → `CANCELLED` removes it from the candidate set for every *future* pricing evaluation and likewise bumps its `version`."

    Design: Corner/errors/guarantee_claim_ineligibility_is_reported_with_a_specific_error_each_time
    """
    shipper = _acme(api, with_ground=True)
    unguaranteed = induct_shipment(
        api, shipper, service_level="GROUND", tracking_number="1Z-V-7001", **SMALL_PARCEL
    )
    in_transit = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-V-7002", **SMALL_PARCEL
    )
    suspended = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-V-7003", **SMALL_PARCEL
    )
    assert_null_fields(unguaranteed.shipment, ["guarantee_deadline_utc"])
    assert_instant(
        suspended.shipment["guarantee_deadline_utc"],
        COMMITMENT_INSTANT,
        "1Z-V-7003 guarantee deadline",
    )

    set_clock(api, LATE_DELIVERY_INSTANT)
    for parcel in (unguaranteed, suspended):
        get_success_data(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
    assert refresh_shipment(api, in_transit.shipment_id)["movement_status"] == "IN_TRANSIT", (
        "1Z-V-7002 must still be moving when its claim is attempted"
    )

    invoice = issued_invoice(
        api,
        open_invoice(
            api,
            shipper,
            [unguaranteed.shipment_id, suspended.shipment_id],
            period_start="2026-08-01",
            period_end="2026-08-01",
        ),
    )
    assert invoice.invoice["line_count"] == 2, (
        f"only the two delivered parcels are billed, got {invoice.invoice['line_count']}"
    )
    for label, parcel in (("1Z-V-7001", unguaranteed), ("1Z-V-7003", suspended)):
        line = refresh_invoice_line(api, invoice.line_by_shipment[parcel.shipment_id])
        assert_money_equals(
            line["transportation_base_cents"], TRANSPORTATION_CENTS, f"{label} transportation"
        )
        assert_money_equals(line["surcharge_cents"], 0, f"{label} surcharge")

    # A fourth parcel picked up and delivered later, deliberately never billed.
    set_clock(api, "2026-08-05T00:00:00Z")
    uninvoiced = induct_shipment(
        api, shipper, service_level="EXPRESS", tracking_number="1Z-V-7004", **SMALL_PARCEL
    )
    set_clock(api, "2026-08-06T03:00:00Z")
    get_success_data(api.deliver_shipment(uninvoiced.shipment_id, CARRIER_OPS_HEADERS))
    assert refresh_shipment(api, uninvoiced.shipment_id)["billing_status"] == "UNBILLED", (
        "1Z-V-7004 must remain off every invoice"
    )

    # Armed only now, so the already-priced lines keep their zero surcharge while
    # the guarantee stops running over every August pickup date.
    window = create_surcharge_window(
        api,
        code="PEAK-2026",
        kind="PEAK_SEASON",
        start_date="2026-08-01",
        end_date="2026-09-01",
        per_package_cents=500,
    )
    armed = activate_surcharge_window(api, window["id"])
    assert armed["status"] == "ACTIVE", f"the peak window must be armed, got {armed['status']}"

    validate_error(
        _file_claim(api, unguaranteed.shipment_id, "ground parcel arrived late"),
        ERR_SERVICE_NOT_GUARANTEED,
        422,
    )
    validate_error(
        _file_claim(api, in_transit.shipment_id, "this parcel is overdue"),
        ERR_SHIPMENT_NOT_DELIVERED,
        409,
    )
    validate_error(
        _file_claim(api, uninvoiced.shipment_id, "delivered three hours late"),
        ERR_SHIPMENT_NOT_INVOICED,
        422,
    )
    validate_error(
        _file_claim(api, suspended.shipment_id, "delivered three hours late"),
        ERR_GUARANTEE_SUSPENDED,
        422,
    )
    _, blocked_meta = _claims(api)
    assert blocked_meta["total_count"] == 0, (
        f"four refusals must have created nothing, got {blocked_meta['total_count']}"
    )

    withdrawn = cancel_surcharge_window(api, window["id"])
    assert withdrawn["status"] == "CANCELLED", (
        f"the peak window must be withdrawn, got {withdrawn['status']}"
    )

    claim = validate_success(
        _file_claim(api, suspended.shipment_id, "delivered three hours late"),
        201,
    )
    assert_fields(
        claim,
        {
            "shipment_id": suspended.shipment_id,
            "invoice_line_id": invoice.line_by_shipment[suspended.shipment_id],
            "status": "FILED",
            "late_by_seconds": LATE_BY_SECONDS,
        },
    )
    assert_money_equals(
        claim["candidate_refund_cents"], TRANSPORTATION_CENTS, "candidate refund"
    )

    rows, meta = _claims(api)
    assert meta["total_count"] == 1, (
        f"only the retried peak parcel may hold a claim, got {meta['total_count']}"
    )
    assert ids_of(rows) == [claim["id"]], "the register holds exactly the retried claim"
    line = refresh_invoice_line(api, invoice.line_by_shipment[suspended.shipment_id])
    assert_money_equals(line["surcharge_cents"], 0, "withdrawn window reprices nothing")
