"""Who may do what, and in which order the refusal is decided.

Five roles divide this network's duties, and the divisions are strict in both
directions: each role can run the whole of its own half of a revenue-recovery
run, and none of them can reach across. Two operators of the same role are
still two people when money moves, a shipper's identity is the account it may
read and nothing more, and the four authorization checks answer before the body
or the referenced identifiers are ever examined.
"""

from test_helpers import (
    BILLING_OPS_ALT_HEADERS,
    BILLING_OPS_ALT_USER_ID,
    BILLING_OPS_HEADERS,
    BILLING_OPS_USER_ID,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_INVALID_REQUEST,
    ERR_MISSING_AUTH_HEADERS,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
    ERR_SHIPPER_SCOPE_VIOLATION,
    ERR_UNKNOWN_ROLE,
    NON_EXISTENT_UUID,
    REVENUE_AUDITOR_HEADERS,
    SYSTEM_ACTOR,
    accessorial_payload,
    assert_fields,
    assert_ledger,
    assert_money_equals,
    assert_version_unchanged,
    billing_adjustment_payload,
    dispute_payload,
    evidence_payload,
    express_service_level_payload,
    get_success_data,
    headers_for_role,
    headers_with_no_auth,
    ids_of,
    invoice_sweep_payload,
    make_shipper_user_headers,
    rate_contract_payload,
    refresh_invoice,
    refresh_shipment,
    refresh_shipper_account,
    scan_payload,
    shipment_payload,
    shipper_account_payload,
    surcharge_window_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

# 12 x 10 x 8 in at 6.0 lb in zone 2 prices to a 2660-cent transportation
# charge; the residential variant adds the 590-cent RESIDENTIAL fee.
SMALL_PARCEL = {
    "zone": 2,
    "residential_declared": False,
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}
TRANSPORTATION_ONLY_CENTS = 2660
RESIDENTIAL_CENTS = 590
RESIDENTIAL_LINE_CENTS = 3250


def _onboard_acme(api, headers=CARRIER_ADMIN_HEADERS, residential_waived=None):
    """The admin's own half of the setup: account, EXPRESS service, ACTIVE C1."""
    account = validate_success(
        api.create_shipper_account(
            shipper_account_payload(
                account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME
            ),
            headers,
        ),
        201,
    )
    express = validate_success(
        api.create_service_level(express_service_level_payload(), headers), 201
    )
    contract_kwargs = {}
    if residential_waived is not None:
        contract_kwargs["residential_waived"] = residential_waived
    contract = validate_success(
        api.create_rate_contract(
            rate_contract_payload(account["id"], **contract_kwargs), headers
        ),
        201,
    )
    activated = validate_success(
        api.activate_rate_contract(contract["id"], account["version"], headers)
    )
    return account, express, activated


def _first_line(api, invoice_id):
    """The single invoice line of a one-parcel invoice."""
    rows = get_success_data(
        api.list_invoice_lines(BILLING_OPS_HEADERS, {"invoice_id": invoice_id})
    )
    assert len(rows) == 1, f"expected one line on the invoice, found {len(rows)}"
    return rows[0]


def test_01_all_five_roles_complete_one_revenue_recovery_run_between_them(api):
    """PRD §2.1: "A `CarrierAdmin` is the network administrator: shipper onboarding and suspension, rate contracts, service levels, surcharge windows, and the logical clock all belong to this role, and it never touches money on an issued invoice."
    PRD §2.1: "A `CarrierOps` operator works at the induction point and on the road: inducting packages, capturing measurement scans, recording delivery, and recording delivery exceptions."
    PRD §2.1: "A `BillingOps` operator runs the revenue desk: billing sweeps, invoice issue, settlement and void, accessorial waivers, and the proposal and application of billing adjustments — though never both the proposal and the application of the same one."
    PRD §2.1: "A `RevenueAuditor` staffs the independent audit and adjudication desk: dispute review, evidence requests, dispute resolution, and guarantee refund audits; it reads broadly but moves no money until a billing operator applies the adjustment it produced."
    PRD §3.5: "Both `CarrierOps` and `BillingOps` may therefore assess a charge by hand against a shipment by naming a `code` from the seven-member accessorial family (`RESIDENTIAL`, `DELIVERY_AREA`, `OVERSIZE`, `ADDITIONAL_HANDLING`, `ADDRESS_CORRECTION`, `RETURN_UNDELIVERABLE`, `REFUSAL`) and optionally a `reason` recording the justification."
    PRD §3.6: "`BillingOps` and `RevenueAuditor` may dry-run the pricing of a single package at its current billable weight."

    Design: Corner/rbac/each_of_the_five_roles_can_run_its_own_exclusive_operations
    """
    # --- the administrator's half: onboarding, catalogue, contract, window ---
    account, express, contract = _onboard_acme(api, residential_waived=False)
    assert contract["status"] == "ACTIVE"
    window = validate_success(
        api.create_surcharge_window(
            surcharge_window_payload(
                code="PEAK-2026",
                kind="PEAK_SEASON",
                start_date="2026-11-01",
                end_date="2026-11-10",
                per_package_cents=500,
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        201,
    )
    armed = validate_success(
        api.activate_surcharge_window(window["id"], CARRIER_ADMIN_HEADERS)
    )
    assert armed["status"] == "ACTIVE"

    # --- the operations half: induction, measurement, hand entry, delivery ---
    residential = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-B-1001",
                zone=2,
                residential_declared=True,
                declared_length_in=12,
                declared_width_in=10,
                declared_height_in=8,
                declared_weight_lbs=6.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    scan = validate_success(
        api.create_scan(
            residential["id"],
            scan_payload(
                residential["version"],
                scan_source="AUTOMATED_DWS",
                scanned_length_in=12,
                scanned_width_in=10,
                scanned_height_in=8,
                scanned_weight_lbs=6.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    assert scan["tolerance_status"] == "WITHIN_TOLERANCE"

    second = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-B-1002",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    # Hand entry is one of the two operations the two desks share.
    by_hand = validate_success(
        api.create_accessorial(
            second["id"],
            accessorial_payload(
                code="ADDRESS_CORRECTION", reason="suite number missing"
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    assert_money_equals(by_hand["amount_cents"], 2200, "ADDRESS_CORRECTION amount_cents")
    assert by_hand["source"] == "MANUAL"

    delivered = validate_success(
        api.deliver_shipment(residential["id"], CARRIER_OPS_HEADERS)
    )
    assert delivered["movement_status"] == "DELIVERED"

    # --- the revenue desk: the sweep and the publication ---
    invoice = validate_success(
        api.create_invoice(
            invoice_sweep_payload(
                account["id"], period_start="2026-08-01", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    assert invoice["line_count"] == 1, (
        f"only the delivered parcel is swept, got line_count {invoice['line_count']}"
    )
    assert_money_equals(
        invoice["net_amount_cents"], RESIDENTIAL_LINE_CENTS, "net_amount_cents"
    )
    issued = validate_success(api.issue_invoice(invoice["id"], BILLING_OPS_HEADERS))
    assert issued["status"] == "ISSUED"
    line = _first_line(api, invoice["id"])

    # --- the customer and the audit desk: dispute, evidence, resolution ---
    shipper_headers = make_shipper_user_headers(account["id"])
    dispute = validate_success(
        api.create_dispute(
            dispute_payload(
                line["id"],
                claim_type="ACCESSORIAL",
                claimed_reason="commercial dock, not residential",
                disputed_codes=["RESIDENTIAL"],
            ),
            shipper_headers,
        ),
        201,
    )
    validate_success(
        api.request_evidence(dispute["id"], "ADDRESS_PROOF", REVENUE_AUDITOR_HEADERS)
    )
    evidence = validate_success(
        api.submit_evidence(
            dispute["id"],
            evidence_payload(
                item_type="ADDRESS_PROOF", reference="doc://address-proof/4410"
            ),
            shipper_headers,
        ),
        201,
    )
    assert evidence["accepted"] is True, (
        "the filed document matches the outstanding request, so it must be accepted"
    )
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], "UPHELD", REVENUE_AUDITOR_HEADERS)
    )
    assert resolved["status"] == "UPHELD"
    assert_money_equals(
        resolved["granted_credit_cents"], RESIDENTIAL_CENTS, "granted_credit_cents"
    )

    # The auditor may also read the shared preview, which now sees the waived fee.
    preview = get_success_data(
        api.get_billing_preview(residential["id"], REVENUE_AUDITOR_HEADERS)
    )
    assert_money_equals(
        preview["line_total_cents"], TRANSPORTATION_ONLY_CENTS, "line_total_cents"
    )
    assert_money_equals(
        preview["accessorial_total_cents"], 0, "preview accessorial_total_cents"
    )

    account_after = refresh_shipper_account(api, account["id"])
    assert_ledger(
        account_after,
        total=2,
        unbilled=1,
        billed=1,
        credit_balance_cents=RESIDENTIAL_CENTS,
        open_charges_cents=TRANSPORTATION_ONLY_CENTS,
    )


def test_02_eight_crossings_of_the_role_boundary_are_all_refused(api):
    """PRD §2.1: "When the role is recognized but is not among the roles authorized for the requested operation (see the authorization column of the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "These four authorization checks are evaluated in a fixed order, and the first failure wins: header presence first, then role recognition, then endpoint permission, then shipper scoping."
    PRD §2.10: "**Authentication and authorization** (§2.1): header presence, role recognition, endpoint permission, shipper scoping."
    PRD §2.10: "**Existence of every referenced record**, in path order and then body order: `ERR_SHIPPER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_SURCHARGE_WINDOW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — each at HTTP 404, in that relative order when a single request touches several."
    PRD §3.3: "Induction is performed by a `CarrierOps` operator at the moment a package enters the network."
    PRD §3.4: "A `CarrierOps` operator records a measurement capture against a shipment by supplying a `scan_source`, the four captured figures `scanned_length_in`, `scanned_width_in`, `scanned_height_in`, and `scanned_weight_lbs`, the mandatory `expected_shipment_version` described in §2.7, and optionally `non_conveyable_observed` — the belt operator's own observation, defaulting to false, that the package cannot ride the automated sort."

    Design: Corner/rbac/no_role_may_reach_another_roles_exclusive_operations
    """
    account, express, _ = _onboard_acme(api)
    parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-B-2001",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    validate_success(api.deliver_shipment(parcel["id"], CARRIER_OPS_HEADERS))
    delivered = refresh_shipment(api, parcel["id"])
    invoice = validate_success(
        api.create_invoice(
            invoice_sweep_payload(
                account["id"], period_start="2026-08-01", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    line = _first_line(api, invoice["id"])
    # The sweep legitimately bumped the swept package's own version, so the
    # baseline for "the refused writes changed nothing" is the post-sweep read.
    swept = refresh_shipment(api, parcel["id"])
    shipper_headers = make_shipper_user_headers(account["id"])

    crossings = {
        # The induction desk may not run the revenue desk's sweep.
        "sweep by operations": api.create_invoice(
            invoice_sweep_payload(
                account["id"], period_start="2026-08-02", period_end="2026-08-02"
            ),
            CARRIER_OPS_HEADERS,
        ),
        # The revenue desk may not induct.
        "induction by billing": api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-B-2002",
                **SMALL_PARCEL,
            ),
            BILLING_OPS_HEADERS,
        ),
        # The administrator owns every rate, yet cannot publish a bill.
        "issue by the administrator": api.issue_invoice(
            invoice["id"], CARRIER_ADMIN_HEADERS
        ),
        # The auditor adjudicates but may not author the money movement.
        "proposal by the auditor": api.create_billing_adjustment(
            billing_adjustment_payload(line["id"], -100, invoice["version"]),
            REVENUE_AUDITOR_HEADERS,
        ),
        # Only the paying customer may contest its own bill.
        "dispute by operations": api.create_dispute(
            dispute_payload(
                line["id"],
                claim_type="WEIGHT",
                claimed_reason="operations filing on the shipper's behalf",
            ),
            CARRIER_OPS_HEADERS,
        ),
        # The customer may not sit in judgement, not even on a dispute that
        # does not exist: the permission check answers before the identifier.
        "resolution by the customer": api.resolve_dispute(
            NON_EXISTENT_UUID, "UPHELD", shipper_headers
        ),
        # The clock belongs to the administrator alone.
        "clock by billing": api.set_clock("2026-08-09T00:00:00Z", BILLING_OPS_HEADERS),
        # Scanning is the induction desk's own capability.
        "scan by billing": api.create_scan(
            parcel["id"],
            scan_payload(
                swept["version"],
                scan_source="MANUAL_REWEIGH",
                scanned_length_in=12,
                scanned_width_in=10,
                scanned_height_in=8,
                scanned_weight_lbs=9.0,
            ),
            BILLING_OPS_HEADERS,
        ),
    }
    for label, response in crossings.items():
        assert response.status_code == 403, (
            f"{label} must be refused at the permission tier, got "
            f"{response.status_code}"
        )
        validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)

    # Nothing crossed the boundary, so nothing changed behind it.
    invoice_after = refresh_invoice(api, invoice["id"])
    assert invoice_after["status"] == "OPEN", (
        f"the refused issue must leave the invoice unpublished, got {invoice_after['status']}"
    )
    assert_version_unchanged(invoice, invoice_after)

    shipment_rows, shipment_meta = validate_paginated(
        api.list_shipments(
            CARRIER_OPS_HEADERS, {"shipper_id": account["id"], "limit": 100}
        )
    )
    assert shipment_meta["total_count"] == 1, (
        f"the refused induction persisted nothing, found {shipment_meta['total_count']}"
    )
    assert ids_of(shipment_rows) == [parcel["id"]]

    _, adjustment_meta = validate_paginated(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"invoice_line_id": line["id"], "limit": 100}
        )
    )
    assert adjustment_meta["total_count"] == 0, (
        f"the refused proposal persisted nothing, found {adjustment_meta['total_count']}"
    )
    _, dispute_meta = validate_paginated(
        api.list_disputes(BILLING_OPS_HEADERS, {"invoice_line_id": line["id"], "limit": 100})
    )
    assert dispute_meta["total_count"] == 0, (
        f"the refused dispute persisted nothing, found {dispute_meta['total_count']}"
    )

    after = refresh_shipment(api, parcel["id"])
    assert_version_unchanged(swept, after)
    assert after["measurement_status"] == "PENDING_SCAN", (
        f"the refused capture measured nothing, got {after['measurement_status']}"
    )

    # The refused clock call left the logical clock where it was, so a parcel
    # inducted now still picks up on the same day.
    latecomer = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-B-2003",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    assert latecomer["pickup_date"] == "2026-08-01", (
        f"the clock must still read 2026-08-01, got {latecomer['pickup_date']}"
    )


def test_03_the_operator_who_proposes_a_credit_may_not_be_the_one_who_releases_it(api):
    """PRD §2.8: "When an adjustment is applied, the applying operator's `X-User-ID` must differ from that stored value; if they are the same, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "A proposal is created by `BillingOps` at `status` `PROPOSED` with `created_by_user_id` set to the proposing operator's `X-User-ID`, `applied_by_user_id` null, and `applied_at` null."
    PRD §3.8: "Application stamps `applied_by_user_id` from the acting `X-User-ID` and `applied_at` from the logical clock, and then propagates through a four-hop cascade:"
    PRD §2.8: "An adjustment produced by upholding a dispute is created *already applied* and therefore never reaches the apply gate at all."
    PRD §3.9: "*Hop 2* creates a `BillingAdjustment` with `reason` `DISPUTE_CREDIT`, `delta_cents` equal to the negation of `granted_credit_cents`, `dispute_id` set to this dispute, and `created_by_user_id` set to the literal `system` — and it is created **already at `APPLIED`**, bypassing the segregation-of-duties gate entirely because no human proposed it."

    Design: Corner/rbac/the_operator_who_proposes_a_credit_may_not_be_the_one_who_releases_it
    """
    account, express, _ = _onboard_acme(api, residential_waived=False)
    parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-B-3001",
                zone=2,
                residential_declared=True,
                declared_length_in=12,
                declared_width_in=10,
                declared_height_in=8,
                declared_weight_lbs=6.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    validate_success(api.deliver_shipment(parcel["id"], CARRIER_OPS_HEADERS))
    invoice = validate_success(
        api.create_invoice(
            invoice_sweep_payload(
                account["id"], period_start="2026-08-01", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    issued = validate_success(api.issue_invoice(invoice["id"], BILLING_OPS_HEADERS))
    assert_money_equals(
        issued["net_amount_cents"], RESIDENTIAL_LINE_CENTS, "net_amount_cents"
    )
    line = _first_line(api, invoice["id"])

    # The first operator authors a goodwill credit against the published line.
    proposal = validate_success(
        api.create_billing_adjustment(
            billing_adjustment_payload(
                line["id"],
                -300,
                issued["version"],
                reason="ACCESSORIAL_CORRECTION",
                note="partial goodwill",
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    assert proposal["created_by_user_id"] == BILLING_OPS_USER_ID, (
        "the proposer's own identity is stored on the proposal, got "
        f"{proposal['created_by_user_id']}"
    )
    assert proposal["status"] == "PROPOSED"

    # The same operator cannot also release it.
    refused = api.apply_billing_adjustment(proposal["id"], BILLING_OPS_HEADERS)
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    still_pending = get_success_data(
        api.get_billing_adjustment(proposal["id"], BILLING_OPS_HEADERS)
    )
    assert still_pending["status"] == "PROPOSED", (
        f"the refused release must leave the credit unpaid, got {still_pending['status']}"
    )
    assert still_pending["applied_by_user_id"] is None
    assert still_pending["applied_at"] is None
    mid_invoice = refresh_invoice(api, invoice["id"])
    assert mid_invoice["pending_adjustment_count"] == 1, (
        "the credit is still waiting for a second pair of hands, got "
        f"{mid_invoice['pending_adjustment_count']}"
    )

    # A second operator of the same desk closes the gate legitimately.
    applied = validate_success(
        api.apply_billing_adjustment(proposal["id"], BILLING_OPS_ALT_HEADERS)
    )
    assert_fields(
        applied,
        {
            "status": "APPLIED",
            "created_by_user_id": BILLING_OPS_USER_ID,
            "applied_by_user_id": BILLING_OPS_ALT_USER_ID,
        },
    )

    # The engine's own credit skips the gate: it is born applied by `system`.
    shipper_headers = make_shipper_user_headers(account["id"])
    dispute = validate_success(
        api.create_dispute(
            dispute_payload(
                line["id"],
                claim_type="ACCESSORIAL",
                claimed_reason="commercial dock, not residential",
                disputed_codes=["RESIDENTIAL"],
            ),
            shipper_headers,
        ),
        201,
    )
    validate_success(
        api.request_evidence(dispute["id"], "ADDRESS_PROOF", REVENUE_AUDITOR_HEADERS)
    )
    validate_success(
        api.submit_evidence(
            dispute["id"],
            evidence_payload(
                item_type="ADDRESS_PROOF", reference="doc://address-proof/7712"
            ),
            shipper_headers,
        ),
        201,
    )
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], "UPHELD", REVENUE_AUDITOR_HEADERS)
    )
    assert_money_equals(
        resolved["granted_credit_cents"], RESIDENTIAL_CENTS, "granted_credit_cents"
    )

    minted = get_success_data(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"dispute_id": dispute["id"], "limit": 100}
        )
    )
    assert len(minted) == 1, (
        f"upholding mints exactly one credit, found {len(minted)}"
    )
    engine_credit = minted[0]
    assert_fields(
        engine_credit,
        {
            "status": "APPLIED",
            "reason": "DISPUTE_CREDIT",
            "created_by_user_id": SYSTEM_ACTOR,
            "applied_by_user_id": SYSTEM_ACTOR,
        },
    )
    assert_money_equals(
        engine_credit["delta_cents"], -RESIDENTIAL_CENTS, "delta_cents"
    )

    final_invoice = refresh_invoice(api, invoice["id"])
    assert_money_equals(
        final_invoice["net_amount_cents"],
        RESIDENTIAL_LINE_CENTS - 300 - RESIDENTIAL_CENTS,
        "net_amount_cents",
    )
    assert final_invoice["pending_adjustment_count"] == 0, (
        "both credits have been released, got "
        f"{final_invoice['pending_adjustment_count']}"
    )
    assert final_invoice["has_pending_adjustments"] is False

    account_after = refresh_shipper_account(api, account["id"])
    assert_ledger(
        account_after,
        total=1,
        unbilled=0,
        billed=1,
        credit_balance_cents=300 + RESIDENTIAL_CENTS,
        open_charges_cents=RESIDENTIAL_LINE_CENTS - 300 - RESIDENTIAL_CENTS,
    )


def test_04_a_shipper_reaching_another_shippers_records_is_out_of_scope(api):
    """PRD §2.1: "Concretely, a `ShipperUser` may only reach a shipment whose `shipper_id` equals its `X-User-ID`, an invoice whose `shipper_id` equals its `X-User-ID`, an invoice line whose owning invoice belongs to it, a dispute whose line rolls up to its own invoice, and a guarantee claim whose shipment belongs to it; and any `shipper_id` value it names in a request body must equal its own `X-User-ID`."
    PRD §2.1: "A violation of any of these is rejected with `ERR_SHIPPER_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `ShipperUser`, `X-User-ID` is the `id` of the acting `ShipperAccount`; ownership checks on any resource that references a `ShipperAccount` compare the resource's owning-account field to `X-User-ID`."
    PRD §2.1: "The scoping check applies to every endpoint whose authorized roles include `ShipperUser`."
    PRD §2.10: "**Authentication and authorization** (§2.1): header presence, role recognition, endpoint permission, shipper scoping."

    Design: Corner/errors/a_shipper_user_reaching_another_shippers_data_is_a_scope_violation
    """
    acme, express, _ = _onboard_acme(api)
    borealis = validate_success(
        api.create_shipper_account(
            shipper_account_payload(
                account_number="SH-2002", name="Borealis Freight"
            ),
            CARRIER_ADMIN_HEADERS,
        ),
        201,
    )

    parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                acme["id"],
                express["id"],
                tracking_number="1Z-V-6001",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    validate_success(api.deliver_shipment(parcel["id"], CARRIER_OPS_HEADERS))
    invoice = validate_success(
        api.create_invoice(
            invoice_sweep_payload(
                acme["id"], period_start="2026-08-01", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    validate_success(api.issue_invoice(invoice["id"], BILLING_OPS_HEADERS))
    line = _first_line(api, invoice["id"])

    intruder = make_shipper_user_headers(borealis["id"])

    validate_error(
        api.get_invoice(invoice["id"], intruder), ERR_SHIPPER_SCOPE_VIOLATION, 403
    )
    validate_error(
        api.get_shipment(parcel["id"], intruder), ERR_SHIPPER_SCOPE_VIOLATION, 403
    )
    validate_error(
        api.list_shipments(intruder, {"shipper_id": acme["id"], "limit": 100}),
        ERR_SHIPPER_SCOPE_VIOLATION,
        403,
    )
    # Contesting a stranger's line is a scope violation, not a missing line and
    # not a business-rule failure: the ownership check answers first.
    validate_error(
        api.create_dispute(
            dispute_payload(
                line["id"],
                claim_type="WEIGHT",
                claimed_reason="not my parcel but I want the credit",
            ),
            intruder,
        ),
        ERR_SHIPPER_SCOPE_VIOLATION,
        403,
    )

    # The owner reads its own bill without impediment.
    owner = make_shipper_user_headers(acme["id"])
    own_view = get_success_data(api.get_invoice(invoice["id"], owner))
    assert_money_equals(
        own_view["net_amount_cents"], TRANSPORTATION_ONLY_CENTS, "net_amount_cents"
    )

    # The intruder's own scope is simply empty, not forbidden.
    own_rows, own_meta = validate_paginated(
        api.list_shipments(intruder, {"shipper_id": borealis["id"], "limit": 100})
    )
    assert own_meta["total_count"] == 0, (
        f"Borealis has inducted nothing, found {own_meta['total_count']}"
    )
    assert own_rows == []

    _, dispute_meta = validate_paginated(api.list_disputes(intruder, {"limit": 100}))
    assert dispute_meta["total_count"] == 0, (
        f"the refused filing persisted nothing, found {dispute_meta['total_count']}"
    )


def test_05_absent_headers_answer_before_the_body_or_the_path_is_read(api):
    """PRD §2.1: "If either header is absent or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else is examined — this check has the highest precedence in the system."
    PRD §2.1: "A value that is not one of these five is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."
    PRD §2.1: "When the role is recognized but is not among the roles authorized for the requested operation (see the authorization column of the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.10: "Endpoints that address a nested resource validate their path segments strictly left to right, and the first unresolvable segment decides the error."
    PRD §2.10: "**Request schema**: every required field of the endpoint's input is present, every value has its declared type, every enum value is a declared member, every numeric range holds, and every dimension or weight carries at most one decimal place."
    PRD §2.10: "A scan list under a shipment that does not exist yields `ERR_SHIPMENT_NOT_FOUND`; an evidence list under a dispute that does not exist yields `ERR_DISPUTE_NOT_FOUND`."

    Design: Corner/validations/missing_auth_headers_outrank_every_other_validation
    """
    account, express, _ = _onboard_acme(api)
    real_parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-P-3001",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    assert real_parcel["version"] == 1

    # One request body, wrong in three different ways at once: a path that
    # resolves to nothing, an undeclared enum member and a negative dimension.
    path = f"/shipments/{NON_EXISTENT_UUID}/scans"
    bad_body = {
        "scan_source": "NOT_A_SOURCE",
        "scanned_length_in": -5,
        "scanned_width_in": 10,
        "scanned_height_in": 8,
        "scanned_weight_lbs": 6.0,
        "expected_shipment_version": real_parcel["version"],
    }

    # 1. Nothing at all: the header check has the highest precedence.
    no_headers = api.raw_post(path, bad_body, headers_with_no_auth())
    first = validate_error(no_headers, ERR_MISSING_AUTH_HEADERS, 401)

    # 2. Headers present but the capacity is not one of the five.
    unknown = api.raw_post(path, bad_body, headers_for_role("WarehouseGoblin", "ops.one"))
    second = validate_error(unknown, ERR_UNKNOWN_ROLE, 401)

    # 3. A real role that this endpoint does not admit.
    forbidden = api.raw_post(path, bad_body, BILLING_OPS_HEADERS)
    third = validate_error(forbidden, ERR_ROLE_NOT_PERMITTED, 403)

    # 4. Only once the caller is authorized does the missing path segment speak,
    #    and the malformed body still never gets a word in.
    authorized = api.raw_post(path, bad_body, CARRIER_OPS_HEADERS)
    fourth = validate_error(authorized, ERR_SHIPMENT_NOT_FOUND, 404)

    reported = [entry["error_id"] for entry in (first, second, third, fourth)]
    assert ERR_INVALID_REQUEST not in reported, (
        "the schema tier sits below both authorization and existence, so the "
        f"undeclared scan_source and the negative inch must stay silent, got {reported}"
    )
    assert reported == [
        ERR_MISSING_AUTH_HEADERS,
        ERR_UNKNOWN_ROLE,
        ERR_ROLE_NOT_PERMITTED,
        ERR_SHIPMENT_NOT_FOUND,
    ], f"the four refusals must descend the precedence ladder in order, got {reported}"

    # The genuine package was never touched by any of the four attempts.
    _, scan_meta = validate_paginated(
        api.list_scans(real_parcel["id"], CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert scan_meta["total_count"] == 0, (
        f"no capture may have landed anywhere, found {scan_meta['total_count']}"
    )
    after = refresh_shipment(api, real_parcel["id"])
    assert_version_unchanged(real_parcel, after)


def test_06_an_unauthorised_caller_never_learns_whether_an_id_exists(api):
    """PRD §2.1: "These four authorization checks are evaluated in a fixed order, and the first failure wins: header presence first, then role recognition, then endpoint permission, then shipper scoping."
    PRD §2.1: "Because scoping runs last of the four, a `ShipperUser` reaching an endpoint it is not permitted to use at all sees `ERR_ROLE_NOT_PERMITTED` rather than a scope error."
    PRD §2.10: "**Existence of every referenced record**, in path order and then body order: `ERR_SHIPPER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_SURCHARGE_WINDOW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — each at HTTP 404, in that relative order when a single request touches several."
    PRD §3.3: "Induction is performed by a `CarrierOps` operator at the moment a package enters the network."
    PRD §2.10: "Across the whole API, validation follows a fixed global precedence, and the first failing tier decides the response:"

    Design: Corner/validations/role_denial_is_evaluated_before_the_referenced_ids
    """
    # Nothing has been onboarded at all, so both identifiers in the body are
    # fictitious.
    phantom_service_level_id = "00000000-0000-0000-0000-000000000001"
    body = shipment_payload(
        NON_EXISTENT_UUID,
        phantom_service_level_id,
        tracking_number="1Z-S-3001",
        **SMALL_PARCEL,
    )

    # The customer role cannot induct at all, and its refusal comes from the
    # permission check — one tier above existence — even though it names its own
    # identifier in the body and every id in that body is fictitious.
    customer = api.raw_post("/shipments", body, make_shipper_user_headers(NON_EXISTENT_UUID))
    validate_error(customer, ERR_ROLE_NOT_PERMITTED, 403)

    # The induction desk is permitted, so the same body now falls through to the
    # existence tier and reports the first unresolvable reference in body order.
    operator = api.create_shipment(body, CARRIER_OPS_HEADERS)
    validate_error(operator, ERR_SHIPPER_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_shipments(CARRIER_OPS_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 0, (
        f"neither refused induction may have persisted a parcel, found {meta['total_count']}"
    )
