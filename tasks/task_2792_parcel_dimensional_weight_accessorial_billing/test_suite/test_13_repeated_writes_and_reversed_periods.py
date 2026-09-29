"""The second attempt, and the calendar read backwards.

Four different uniqueness constraints in this domain — an account number, a
service code, a window code, a tracking number — all report the same conflict,
and four different endpoints that accept a date range all report the same
unprocessable period. The state machines behave the same way: cancelling a
cancelled window, issuing an issued invoice, delivering a refused parcel and
scanning a verified one are refusals, not replays, and each one leaves the
record exactly as the first attempt left it.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_DUPLICATE_KEY,
    ERR_INVALID_PERIOD,
    ERR_INVOICE_NOT_IN_STATE,
    ERR_MEASUREMENT_FINAL,
    ERR_SHIPMENT_NOT_IN_TRANSIT,
    ERR_WINDOW_NOT_IN_STATE,
    REVENUE_AUDITOR_HEADERS,
    accessorials_for_shipment,
    assert_fields,
    assert_instant,
    assert_instants_equal,
    assert_ledger,
    assert_lbs,
    assert_money_equals,
    assert_version_unchanged,
    create_surcharge_window,
    delivered_shipment,
    exception_payload,
    find_row,
    get_success_data,
    guarantee_scan_payload,
    ids_of,
    induct_shipment,
    invoice_sweep_payload,
    open_invoice,
    raise_exception,
    rate_contract_payload,
    refresh_invoice,
    refresh_shipment,
    refresh_shipper_account,
    scan_payload,
    service_level_payload,
    shipment_payload,
    shipper_account_payload,
    shipper_with_active_contract,
    surcharge_window_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

# The reference parcel: 12 x 10 x 8 in at 6.0 lb in zone 2, which prices to a
# 2660-cent transportation charge under the standard contract.
SMALL_PARCEL = {
    "zone": 2,
    "residential_declared": False,
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}
SMALL_PARCEL_NET_CENTS = 2660


def _acme(api):
    """SH-2001 holding the standard EXPRESS-only activated contract C1."""
    return shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )


def _windows(api):
    """Page every surcharge window through the admin's own view."""
    return validate_paginated(
        api.list_surcharge_windows(CARRIER_ADMIN_HEADERS, {"limit": 100})
    )


def _shipments(api, shipper_id):
    """Page the parcels of one account."""
    return validate_paginated(
        api.list_shipments(CARRIER_OPS_HEADERS, {"shipper_id": shipper_id, "limit": 100})
    )


def test_01_four_natural_keys_all_report_the_same_conflict(api):
    """PRD §3.1: "The `account_number` is the carrier-assigned identifier and must be between 4 and 32 characters long and unique across all shipper accounts; a collision is rejected with `ERR_DUPLICATE_KEY`."
    PRD §3.2: "The `code` must be uppercase snake case and unique across all service levels, with a collision rejected as `ERR_DUPLICATE_KEY`; `guarantee_hours` must be an integer between 1 and 336 inclusive — that is, anywhere from a single hour up to a full fourteen days of transit."
    PRD §3.2: "The `code` must be unique across all windows (`ERR_DUPLICATE_KEY` otherwise)."
    PRD §3.3: "The payload identifies the owner with `shipper_id`, the purchased service with `service_level_id`, and the parcel itself with a `tracking_number` between 8 and 32 characters and unique across all shipments (`ERR_DUPLICATE_KEY` on a collision)."
    PRD §2.10: "**Natural-key uniqueness**: `ERR_DUPLICATE_KEY` (HTTP 409)."

    Design: Corner/errors/duplicate_natural_keys_raise_the_same_conflict_on_four_entities
    """
    shipper = _acme(api)
    express_id = shipper.service_level_ids["EXPRESS"]
    create_surcharge_window(
        api,
        code="DEMAND-A",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-10",
        per_package_cents=500,
    )
    induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-V-2001",
        **SMALL_PARCEL,
    )

    # Four retries, each one colliding on a different natural key.
    account_error = validate_error(
        api.create_shipper_account(
            shipper_account_payload(
                account_number=ACME_ACCOUNT_NUMBER, name="Impostor Parcel Co"
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_KEY,
        409,
    )
    service_error = validate_error(
        api.create_service_level(
            service_level_payload(
                code="EXPRESS",
                name="Express Two Day",
                guarantee_hours=48,
                guaranteed=True,
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_KEY,
        409,
    )
    # November never touches DEMAND-A's August range, so nothing but the code
    # can be the reason this one is refused.
    window_error = validate_error(
        api.create_surcharge_window(
            surcharge_window_payload(
                code="DEMAND-A",
                kind="DEMAND",
                start_date="2026-11-01",
                end_date="2026-11-10",
                per_package_cents=700,
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_KEY,
        409,
    )
    shipment_error = validate_error(
        api.create_shipment(
            shipment_payload(
                shipper.shipper_id,
                express_id,
                tracking_number="1Z-V-2001",
                zone=2,
                residential_declared=False,
                declared_length_in=20,
                declared_width_in=20,
                declared_height_in=20,
                declared_weight_lbs=40.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        ERR_DUPLICATE_KEY,
        409,
    )

    reported = {
        row["error_id"]
        for row in (account_error, service_error, window_error, shipment_error)
    }
    assert reported == {ERR_DUPLICATE_KEY}, (
        "all four uniqueness constraints must surface as the one conflict, got "
        f"{sorted(reported)}"
    )

    account = refresh_shipper_account(api, shipper.shipper_id)
    assert account["name"] == ACME_NAME, (
        f"the impostor must not have overwritten the incumbent, got {account['name']!r}"
    )
    assert_ledger(account, total=1, unbilled=1, billed=0)

    window_rows, window_meta = _windows(api)
    assert window_meta["total_count"] == 1, (
        f"the refused window must not be persisted, found {window_meta['total_count']}"
    )
    assert window_rows[0]["per_package_cents"] == 500, (
        "the surviving window keeps its own amount, got "
        f"{window_rows[0]['per_package_cents']}"
    )

    shipment_rows, shipment_meta = _shipments(api, shipper.shipper_id)
    assert shipment_meta["total_count"] == 1, (
        f"the refused induction must not be persisted, found {shipment_meta['total_count']}"
    )
    assert shipment_rows[0]["declared_weight_lbs"] == 6.0, (
        "the surviving parcel keeps its own declaration, got "
        f"{shipment_rows[0]['declared_weight_lbs']}"
    )


def test_02_every_endpoint_that_takes_a_period_refuses_a_reversed_one(api):
    """PRD §3.1: "`effective_to` must be on or after `effective_from`; a reversed window is rejected with `ERR_INVALID_PERIOD` (HTTP 422)."
    PRD §3.6: "A `period_end` earlier than `period_start` is `ERR_INVALID_PERIOD` (HTTP 422); an unresolvable `shipper_id` is `ERR_SHIPPER_NOT_FOUND`."
    PRD §3.2: "`end_date` must be strictly after `start_date`; a same-date or reversed range is `ERR_INVALID_PERIOD` (HTTP 422)."
    PRD §3.9: "A `period_end` earlier than `period_start` is `ERR_INVALID_PERIOD`, and an unresolvable `shipper_id` is `ERR_SHIPPER_NOT_FOUND`."
    PRD §3.2: "A window opens at `status` `SCHEDULED`, which means it is on the calendar but invisible to pricing."

    Design: Corner/errors/inverted_periods_are_unprocessable_on_every_endpoint_that_takes_one
    """
    shipper = _acme(api)

    # A 2027 contract period cannot collide with the 2026 incumbent, so the
    # reversed dates are the only possible ground for refusal.
    contract_error = validate_error(
        api.create_rate_contract(
            rate_contract_payload(
                shipper.shipper_id,
                effective_from="2027-06-01",
                effective_to="2027-05-31",
                rate_table=[
                    {"zone": 2, "min_lbs": 1, "max_lbs": 9999, "cents_per_lb": 380}
                ],
                tier_discount_table=[],
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        ERR_INVALID_PERIOD,
        422,
    )
    sweep_error = validate_error(
        api.create_invoice(
            invoice_sweep_payload(
                shipper.shipper_id, period_start="2026-08-05", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        ERR_INVALID_PERIOD,
        422,
    )
    # A window is half-open, so a start equal to its end encloses no day at all.
    window_error = validate_error(
        api.create_surcharge_window(
            surcharge_window_payload(
                code="PEAK-2026",
                kind="PEAK_SEASON",
                start_date="2026-11-01",
                end_date="2026-11-01",
                per_package_cents=500,
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        ERR_INVALID_PERIOD,
        422,
    )
    audit_error = validate_error(
        api.scan_guarantee_claims(
            guarantee_scan_payload(
                shipper.shipper_id, period_start="2026-08-05", period_end="2026-08-01"
            ),
            REVENUE_AUDITOR_HEADERS,
        ),
        ERR_INVALID_PERIOD,
        422,
    )

    reported = {
        row["error_id"]
        for row in (contract_error, sweep_error, window_error, audit_error)
    }
    assert reported == {ERR_INVALID_PERIOD}, (
        "one error covers all four period shapes, got " f"{sorted(reported)}"
    )

    # The same code over the shortest legal half-open range is accepted.
    accepted = validate_success(
        api.create_surcharge_window(
            surcharge_window_payload(
                code="PEAK-2026",
                kind="PEAK_SEASON",
                start_date="2026-11-01",
                end_date="2026-11-02",
                per_package_cents=500,
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED", (
        f"a one-day window is legal and opens SCHEDULED, got {accepted['status']}"
    )

    contracts, contract_meta = validate_paginated(
        api.list_rate_contracts(
            CARRIER_ADMIN_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 100}
        )
    )
    assert contract_meta["total_count"] == 1, (
        f"only the incumbent contract may exist, found {contract_meta['total_count']}"
    )
    assert ids_of(contracts) == [shipper.contract_id]

    _, invoice_meta = validate_paginated(
        api.list_invoices(
            BILLING_OPS_HEADERS, {"shipper_id": shipper.shipper_id, "limit": 100}
        )
    )
    assert invoice_meta["total_count"] == 0, (
        "the reversed sweep was refused before it could open an invoice, found "
        f"{invoice_meta['total_count']}"
    )

    window_rows, window_meta = _windows(api)
    assert window_meta["total_count"] == 1, (
        f"only the accepted window may exist, found {window_meta['total_count']}"
    )
    assert ids_of(window_rows) == [accepted["id"]]


def test_03_a_cancelled_window_can_be_neither_cancelled_again_nor_armed(api):
    """PRD §3.2: "Cancellation reaches the window from either of two states: `SCHEDULED` → `CANCELLED` simply retires an unarmed window and bumps its `version`; `ACTIVE` → `CANCELLED` removes it from the candidate set for every *future* pricing evaluation and likewise bumps its `version`."
    PRD §3.2: "Arming a window whose `status` is not `SCHEDULED`, or cancelling one that is already `CANCELLED`, is rejected with `ERR_WINDOW_NOT_IN_STATE` (HTTP 409); an unknown window identifier is `ERR_SURCHARGE_WINDOW_NOT_FOUND`."
    PRD §3.2: "Arming it moves it `SCHEDULED` → `ACTIVE`, at which point it enters the surcharge candidate set consulted during line pricing, and its `version` increments by 1."

    Design: Corner/state_machines/cancelling_an_already_cancelled_window_is_an_invalid_transition
    """
    window = create_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-15",
        per_package_cents=150,
    )
    assert window["status"] == "SCHEDULED"
    assert window["version"] == 1

    cancelled = get_success_data(
        api.cancel_surcharge_window(window["id"], CARRIER_ADMIN_HEADERS)
    )
    assert cancelled["status"] == "CANCELLED", (
        f"retiring an unarmed window is legal, got {cancelled['status']}"
    )
    assert cancelled["version"] == 2, (
        f"the retirement bumps the version once, got {cancelled['version']}"
    )

    # Neither repeating the retirement nor arming the corpse is admitted.
    validate_error(
        api.cancel_surcharge_window(window["id"], CARRIER_ADMIN_HEADERS),
        ERR_WINDOW_NOT_IN_STATE,
        409,
    )
    validate_error(
        api.activate_surcharge_window(window["id"], CARRIER_ADMIN_HEADERS),
        ERR_WINDOW_NOT_IN_STATE,
        409,
    )

    final = get_success_data(
        api.get_surcharge_window(window["id"], CARRIER_ADMIN_HEADERS)
    )
    assert final["status"] == "CANCELLED", (
        f"a refused transition must not resurrect the window, got {final['status']}"
    )
    assert_version_unchanged(cancelled, final)


def test_04_issuing_an_invoice_twice_never_credits_the_ledger_twice(api):
    """PRD §3.7: "Issuing moves the invoice `OPEN → ISSUED` and is permitted only when its `status` is `OPEN` and its `line_count` is at least 1; anything else is rejected with `ERR_INVOICE_NOT_IN_STATE` (HTTP 409)."
    PRD §3.7: "Issue stamps `issued_at` from the logical clock and derives `dispute_deadline_utc` as that instant advanced by the ninety-day dispute window."
    PRD §3.7: "The owning account's `open_charges_cents` rises by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1."
    PRD §3.1: "Reading an account back returns those five figures computed live, so the account view is always the authoritative ledger snapshot."

    Design: Corner/state_machines/issuing_an_already_issued_invoice_is_rejected_not_replayed
    """
    shipper = _acme(api)
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-Y-0001",
        **SMALL_PARCEL,
    )
    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    assert invoice.invoice["line_count"] == 1
    assert_money_equals(
        invoice.invoice["net_amount_cents"], SMALL_PARCEL_NET_CENTS, "net_amount_cents"
    )

    published = validate_success(
        api.issue_invoice(invoice.invoice_id, BILLING_OPS_HEADERS)
    )
    assert published["status"] == "ISSUED"
    assert published["version"] == 2, (
        f"the first issue bumps the version once, got {published['version']}"
    )
    assert_instant(published["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert published["dispute_deadline_utc"] is not None, (
        "issue must derive the dispute deadline from the stamped instant"
    )

    validate_error(
        api.issue_invoice(invoice.invoice_id, BILLING_OPS_HEADERS),
        ERR_INVOICE_NOT_IN_STATE,
        409,
    )

    after = refresh_invoice(api, invoice.invoice_id)
    assert after["status"] == "ISSUED"
    assert_version_unchanged(published, after)
    assert_instants_equal(after["issued_at"], published["issued_at"], "issued_at")
    assert_instants_equal(
        after["dispute_deadline_utc"],
        published["dispute_deadline_utc"],
        "dispute_deadline_utc",
    )
    assert_money_equals(
        after["net_amount_cents"], SMALL_PARCEL_NET_CENTS, "net_amount_cents"
    )

    account = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account,
        total=1,
        unbilled=0,
        billed=1,
        credit_balance_cents=0,
        open_charges_cents=SMALL_PARCEL_NET_CENTS,
    )


def test_05_a_refused_parcel_can_be_neither_delivered_nor_excepted_again(api):
    """PRD §3.5: "Recording delivery or any exception against a shipment whose `movement_status` has already left `IN_TRANSIT` is rejected with `ERR_SHIPMENT_NOT_IN_TRANSIT` (HTTP 409)."
    PRD §3.5: "`kind` `REFUSED` drives the shipment `IN_TRANSIT → REFUSED` and creates **two** accessorial charges in the same request."
    PRD §3.5: "The second carries code `RETURN_UNDELIVERABLE` at $18.00 or its contract override, because a refused parcel must still travel back to the shipper."
    PRD §3.5: "A `CarrierOps` operator drives the shipment `IN_TRANSIT → DELIVERED`, and the server stamps `delivered_at` from the logical clock and increments the shipment's `version` by 1."
    PRD §3.5: "In all three cases the shipment's `accessorial_total_cents` rises by the sum of the newly assessed amounts, the shipment's `version` increments by 1, and the reconciliation branch of §2.9 runs."

    Design: Corner/state_machines/delivering_a_refused_parcel_is_blocked_by_the_movement_precondition
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-X-0001",
        **SMALL_PARCEL,
    )

    refused = raise_exception(
        api, parcel.shipment_id, "REFUSED", reason="consignee refused delivery"
    )
    assert refused["movement_status"] == "REFUSED", (
        f"a refusal takes the parcel off the delivery path, got {refused['movement_status']}"
    )
    assert_money_equals(
        refused["accessorial_total_cents"], 3150, "accessorial_total_cents"
    )

    # The movement axis has left IN_TRANSIT, so neither outcome is reachable.
    validate_error(
        api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS),
        ERR_SHIPMENT_NOT_IN_TRANSIT,
        409,
    )
    validate_error(
        api.create_exception(
            parcel.shipment_id,
            exception_payload("UNDELIVERABLE", reason="second attempt"),
            CARRIER_OPS_HEADERS,
        ),
        ERR_SHIPMENT_NOT_IN_TRANSIT,
        409,
    )

    final = refresh_shipment(api, parcel.shipment_id)
    assert final["movement_status"] == "REFUSED", (
        f"the refused transitions changed nothing, got {final['movement_status']}"
    )
    assert final["delivered_at"] is None, (
        f"no delivery instant may be stamped, got {final['delivered_at']!r}"
    )
    assert_version_unchanged(refused, final)

    charges = accessorials_for_shipment(api, parcel.shipment_id, limit=100)
    assert len(charges) == 2, (
        "the refusal minted exactly two charges and the rejected calls minted none, "
        f"found {[row['code'] for row in charges]}"
    )
    refusal = find_row(charges, code="REFUSAL")
    assert_money_equals(refusal["amount_cents"], 1350, "REFUSAL amount_cents")
    return_leg = find_row(charges, code="RETURN_UNDELIVERABLE")
    assert_money_equals(
        return_leg["amount_cents"], 1800, "RETURN_UNDELIVERABLE amount_cents"
    )
    assert {row["status"] for row in charges} == {"ASSESSED"}


def test_06_a_verified_measurement_admits_no_further_capture(api):
    """PRD §3.4: "A `MANUAL_REWEIGH` capture is authoritative regardless of variance and drives the shipment straight to `VERIFIED`, reachable as `PENDING_SCAN → VERIFIED`, `SCANNED → VERIFIED`, and `TOLERANCE_FLAGGED → VERIFIED`."
    PRD §3.4: "Every one of those seven transitions requires that the shipment's `measurement_status` is not already `VERIFIED`, and every one requires a matching `expected_shipment_version`."
    PRD §3.4: "Capturing against an already-`VERIFIED` shipment is rejected with `ERR_MEASUREMENT_FINAL` (HTTP 409); the version check runs first, so a request that is both stale and aimed at a verified shipment reports `ERR_STALE_SHIPMENT_VERSION`."
    PRD §3.4: "From the governing scan the server recomputes the final variant of the billable-weight calculation, writing `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, and `final_basis` onto the shipment, and mirroring the governing scan's `dim_variance_pct` and `weight_variance_lbs` onto the shipment's like-named fields."
    PRD §3.4: "Every successful capture increments the shipment's `version` by 1."

    Design: Corner/state_machines/a_verified_measurement_is_locked_against_further_scans
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-V-0001",
        zone=2,
        residential_declared=False,
        declared_length_in=10,
        declared_width_in=10,
        declared_height_in=20,
        declared_weight_lbs=30.0,
    )

    scan = get_success_data(
        api.create_scan(
            parcel.shipment_id,
            scan_payload(
                parcel.shipment_version,
                scan_source="MANUAL_REWEIGH",
                scanned_length_in=10,
                scanned_width_in=10,
                scanned_height_in=22,
                scanned_weight_lbs=31.0,
            ),
            CARRIER_OPS_HEADERS,
        )
    )
    assert scan["scanned_cube_in3"] == 2200

    verified = refresh_shipment(api, parcel.shipment_id)
    assert_fields(
        verified,
        {
            "measurement_status": "VERIFIED",
            "scanned_cube_in3": 2200,
            "final_basis": "ACTUAL",
        },
    )
    assert_lbs(verified["final_billable_weight_lbs"], 31, "final_billable_weight_lbs")
    assert verified["version"] == parcel.shipment_version + 1

    # Both sources are refused, and the versions offered are the current ones,
    # so no stale-version guard can be what answers.
    validate_error(
        api.create_scan(
            parcel.shipment_id,
            scan_payload(
                verified["version"],
                scan_source="AUTOMATED_DWS",
                scanned_length_in=10,
                scanned_width_in=10,
                scanned_height_in=22,
                scanned_weight_lbs=31.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        ERR_MEASUREMENT_FINAL,
        409,
    )
    validate_error(
        api.create_scan(
            parcel.shipment_id,
            scan_payload(
                verified["version"],
                scan_source="MANUAL_REWEIGH",
                scanned_length_in=10,
                scanned_width_in=10,
                scanned_height_in=24,
                scanned_weight_lbs=33.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        ERR_MEASUREMENT_FINAL,
        409,
    )

    history = get_success_data(
        api.list_scans(parcel.shipment_id, CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert ids_of(history) == [scan["id"]], (
        f"the refused captures must append nothing, found {len(history)} scans"
    )

    final = refresh_shipment(api, parcel.shipment_id)
    assert_version_unchanged(verified, final)
    assert final["scanned_cube_in3"] == 2200, (
        "the governing measurement is unchanged by the refusals, got "
        f"{final['scanned_cube_in3']}"
    )
