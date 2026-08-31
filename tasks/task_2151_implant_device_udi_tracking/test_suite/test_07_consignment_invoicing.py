"""Vendor invoice submission and the two reconciliation variants."""

from test_helpers import (
    ApiErrorId,
    CC,
    IL,
    RI,
    RT,
    add_unit,
    agreement_version,
    create_active_agreement,
    create_agreement,
    create_case,
    create_catalog_item,
    create_lot,
    create_patient,
    create_vendor,
    document_implant,
    get_invoice,
    get_lot,
    get_unit,
    lot_version,
    make_vendor_rep_headers,
    match_invoice,
    release_lot,
    set_clock,
    setup_billable_units,
    setup_submitted_invoice,
    start_case,
    submit_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)

LINER_CATALOG = {
    "device_identifier": "00812345678912",
    "description": "Acetabular Liner",
    "category": "STANDARD_IMPLANT",
    "list_charge_cents": 600_000,
    "charge_code": "CDM-77150",
}
KNEE_CATALOG = {
    "device_identifier": "00812345678981",
    "description": "Knee Femoral Component",
    "category": "HIGH_COST_IMPLANT",
    "list_charge_cents": 1_500_000,
    "charge_code": "CDM-77220",
}


def _period_trueup_world():
    """Three consigned units consumed inside the period; the invoice bills only
    the two cheapest."""
    return setup_submitted_invoice(
        925_000,
        (462_500, 462_500, 500_001),
        invoiced_unit_indexes=[0, 1],
        agreement_overrides={
            "agreement_code": "AGR-B",
            "reconciliation_method": "PERIOD_TRUEUP",
        },
        catalog_overrides=LINER_CATALOG,
    )


class TestPeriodTrueUpVariant:
    def test_period_trueup_widens_the_denominator_beyond_the_invoice(self, api):
        """PRD §3.10: "Under `PERIOD_TRUEUP` the check is period-level, and it
        deliberately widens the denominator beyond the invoice."
        PRD §3.10: "Sum the pool's `contract_price_cents`, divide by the number of
        units in the pool, and round that per-item average half up to a whole cent
        **before** multiplying — then multiply the rounded average by the number of
        *this invoice's* units belonging to that catalog item and add the product
        into the running total."
        PRD §3.10: "Under `UNIT_MATCH` the check is serial-level and never looks
        outside the invoice: `expected_total_cents` is the exact sum of
        `contract_price_cents` over the device units whose `vendor_invoice_id`
        equals this invoice at match time."

        Design: Difficulty/dual_variant_calc/consignment_unit_match_vs_period_trueup_divergence
        """
        world = _period_trueup_world()

        matched = validate_success(api.match_invoice(world["invoice"]["id"], RI), 200)
        assert matched["reconciliation_variant"] == "PERIOD_TRUEUP"
        assert matched["expected_total_cents"] == 950_000
        assert matched["expected_total_cents"] != 925_000, (
            "925000 is the UNIT_MATCH reading of the identical invoice"
        )

    def test_period_trueup_variance_puts_the_invoice_on_variance_hold(self, api):
        """PRD §3.10: "Whichever variant ran, `variance_cents` is then the invoice's
        `submitted_total_cents` minus its `expected_total_cents` — submitted first,
        expected second, so an over-billing vendor produces a positive variance —
        and `variance_bps` is the absolute value of that variance multiplied by
        10,000, divided by `expected_total_cents`, and rounded half up to a whole
        number of basis points."
        PRD §3.10: "The fork is then on the computed number against the agreement's
        `invoice_tolerance_bps`: a `variance_bps` **strictly greater** than the
        tolerance sends the invoice `SUBMITTED → VARIANCE_HOLD`, and a
        `variance_bps` less than or exactly equal to the tolerance sends it
        `SUBMITTED → MATCHED`. Equality passes."

        Design: Difficulty/dual_variant_calc/consignment_unit_match_vs_period_trueup_divergence
        """
        world = _period_trueup_world()
        matched = match_invoice(world["invoice"]["id"])

        assert matched["variance_cents"] == -25_000
        assert matched["variance_bps"] == 263
        assert matched["status"] == "VARIANCE_HOLD"

        uninvoiced = get_unit(world["units"][2]["id"])
        assert uninvoiced["billing_state"] == "BILLABLE"
        assert uninvoiced["vendor_invoice_id"] is None


class TestToleranceBoundary:
    def test_variance_exactly_at_the_tolerance_takes_the_matched_branch(self, api):
        """PRD §3.10: "The fork is then on the computed number against the
        agreement's `invoice_tolerance_bps`: a `variance_bps` **strictly greater**
        than the tolerance sends the invoice `SUBMITTED → VARIANCE_HOLD`, and a
        `variance_bps` less than or exactly equal to the tolerance sends it
        `SUBMITTED → MATCHED`. Equality passes."
        PRD §3.10: "Under `UNIT_MATCH` the check is serial-level and never looks
        outside the invoice: `expected_total_cents` is the exact sum of
        `contract_price_cents` over the device units whose `vendor_invoice_id`
        equals this invoice at match time."

        Design: Difficulty/boundary_precision_check/invoice_variance_bps_equal_to_tolerance_takes_matched_branch
        """
        world = setup_billable_units(
            (1_000_000, 1_000_000),
            catalog_overrides=KNEE_CATALOG,
            case_overrides={
                "case_number": "CASE-5",
                "or_room_code": "OR-2",
                "scheduled_start_utc": "2026-09-14T08:00:00Z",
                "scheduled_end_utc": "2026-09-14T12:00:00Z",
            },
        )
        invoice = submit_invoice(
            world["vendor"]["id"],
            world["agreement"]["id"],
            [world["units"][0]["id"]],
            1_015_000,
            invoice_number="INV-A",
        )

        matched = validate_success(api.match_invoice(invoice["id"], RI), 200)
        assert matched["expected_total_cents"] == 1_000_000
        assert matched["variance_cents"] == 15_000
        assert matched["variance_bps"] == 150
        assert matched["status"] == "MATCHED"

    def test_one_basis_point_over_the_tolerance_takes_the_variance_hold_branch(self, api):
        """PRD §3.10: "The fork is then on the computed number against the
        agreement's `invoice_tolerance_bps`: a `variance_bps` **strictly greater**
        than the tolerance sends the invoice `SUBMITTED → VARIANCE_HOLD`, and a
        `variance_bps` less than or exactly equal to the tolerance sends it
        `SUBMITTED → MATCHED`. Equality passes."
        PRD §3.1: "Two optional terms carry defaults: `invoice_tolerance_bps`, the
        absolute variance tolerance in basis points, defaults to 150 and must be at
        least 0 and at most 10000; `replenishment_days`, the contractual
        replenishment service level in days, defaults to 14 and is recorded for
        reporting only — no rule in this service enforces it."

        Design: Difficulty/boundary_precision_check/invoice_variance_bps_equal_to_tolerance_takes_matched_branch
        """
        world = setup_billable_units(
            (1_000_000, 1_000_000),
            catalog_overrides=KNEE_CATALOG,
            case_overrides={
                "case_number": "CASE-5",
                "or_room_code": "OR-2",
                "scheduled_start_utc": "2026-09-14T08:00:00Z",
                "scheduled_end_utc": "2026-09-14T12:00:00Z",
            },
        )
        invoice = submit_invoice(
            world["vendor"]["id"],
            world["agreement"]["id"],
            [world["units"][1]["id"]],
            1_015_100,
            invoice_number="INV-B",
        )

        matched = validate_success(api.match_invoice(invoice["id"], RI), 200)
        assert matched["variance_cents"] == 15_100
        assert matched["variance_bps"] == 151
        assert matched["status"] == "VARIANCE_HOLD"


class TestAlreadyInvoicedPrecedence:
    def test_a_unit_already_on_an_invoice_reports_the_exclusivity_error(self, api):
        """PRD §3.10: "Each named serial must be free of an existing invoice,
        checked first: a unit whose `vendor_invoice_id` is already set is rejected
        with `ERR_UNIT_ALREADY_INVOICED`. Only after that does the billing check
        run: every named unit must be in `billing_state` `BILLABLE`, and one that is
        not is rejected with `ERR_UNIT_NOT_BILLABLE`."
        PRD §2.6: "Invoice exclusivity — every unit in `device_unit_ids` has a null
        `vendor_invoice_id`. Applies to invoice submission and resubmission.
        Failure: `ERR_UNIT_ALREADY_INVOICED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/already_invoiced_constraint_precedes_not_billable_fiscal
        """
        world = setup_submitted_invoice(462_500, (462_500,))

        error = validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": world["vendor"]["id"],
                    "consignment_agreement_id": world["agreement"]["id"],
                    "invoice_number": "INV-2",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [world["units"][0]["id"]],
                    "expected_agreement_version": agreement_version(
                        world["agreement"]["id"]
                    ),
                },
                make_vendor_rep_headers(world["vendor"]["id"]),
            ),
            ApiErrorId.ERR_UNIT_ALREADY_INVOICED,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_UNIT_NOT_BILLABLE.value

    def test_the_rejected_second_invoice_leaves_the_first_binding_untouched(self, api):
        """PRD §2.6: "Every request runs through one ordered ladder of checks.
        **The first check that fails determines the entire response; no later check
        runs, and no side effect belonging to a later stage is applied.**"
        PRD §3.10: "A successful submission creates the invoice in `SUBMITTED`, moves
        every listed unit `BILLABLE → INVOICED` with `vendor_invoice_id` pointing at
        the new invoice, and advances the agreement's `version` by one."

        Design: Difficulty/priority_pair_validation_conflict/already_invoiced_constraint_precedes_not_billable_fiscal
        """
        world = setup_submitted_invoice(462_500, (462_500,))
        first_invoice = world["invoice"]

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": world["vendor"]["id"],
                    "consignment_agreement_id": world["agreement"]["id"],
                    "invoice_number": "INV-2",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [world["units"][0]["id"]],
                    "expected_agreement_version": agreement_version(
                        world["agreement"]["id"]
                    ),
                },
                make_vendor_rep_headers(world["vendor"]["id"]),
            ),
            ApiErrorId.ERR_UNIT_ALREADY_INVOICED,
            409,
        )

        unit = get_unit(world["units"][0]["id"])
        assert unit["vendor_invoice_id"] == first_invoice["id"]
        assert unit["billing_state"] == "INVOICED"

        _, meta = validate_paginated(
            api.list_vendor_invoices(IL, {"vendor_id": world["vendor"]["id"]})
        )
        assert meta["total_count"] == 1


class TestAgreementPrecondition:
    def test_billing_under_a_draft_agreement_is_refused(self, api):
        """PRD §3.10: "The agreement must be `ACTIVE`, failing which the answer is
        `ERR_AGREEMENT_NOT_ACTIVE`, and the vendor's `standing` must be `ACTIVE`,
        failing which the answer is `ERR_VENDOR_ON_HOLD` — a vendor with an open
        `CLASS_I` field action cannot invoice at all."
        PRD §3.1: "The agreement opens in `DRAFT` with `price_list_version` at 1."

        Design: Difficulty/cross_entity_state_dependency/invoice_create_blocked_by_draft_agreement
        """
        world = _two_agreement_world()

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": world["vendor"]["id"],
                    "consignment_agreement_id": world["draft_agreement"]["id"],
                    "invoice_number": "INV-1",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [world["unit"]["id"]],
                    "expected_agreement_version": world["draft_agreement"]["version"],
                },
                make_vendor_rep_headers(world["vendor"]["id"]),
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE,
            409,
        )
        assert world["draft_agreement"]["status"] == "DRAFT"

    def test_the_refused_invoice_leaves_the_billable_unit_unbound(self, api):
        """PRD §3.1: "An agreement moves `DRAFT → ACTIVE` when the `InventoryLead`
        activates it, which advances the agreement's `version` by one; attempting to
        activate an agreement that is not in `DRAFT` is rejected with
        `ERR_INVALID_LIFECYCLE_STATE`."
        PRD §3.10: "A successful submission creates the invoice in `SUBMITTED`, moves
        every listed unit `BILLABLE → INVOICED` with `vendor_invoice_id` pointing at
        the new invoice, and advances the agreement's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/invoice_create_blocked_by_draft_agreement
        """
        world = _two_agreement_world()

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": world["vendor"]["id"],
                    "consignment_agreement_id": world["draft_agreement"]["id"],
                    "invoice_number": "INV-1",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [world["unit"]["id"]],
                    "expected_agreement_version": world["draft_agreement"]["version"],
                },
                make_vendor_rep_headers(world["vendor"]["id"]),
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE,
            409,
        )

        unit = get_unit(world["unit"]["id"])
        assert unit["billing_state"] == "BILLABLE"
        assert unit["vendor_invoice_id"] is None

        _, meta = validate_paginated(
            api.list_vendor_invoices(
                IL, {"consignment_agreement_id": world["draft_agreement"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestBillingEligibility:
    def test_a_hospital_owned_unit_can_never_appear_on_a_consignment_invoice(self, api):
        """PRD §2.10: "`ownership` is set once, at unit receipt: it is `CONSIGNED`
        when a `consignment_agreement_id` was supplied and `OWNED` when it was not,
        and it never changes afterwards. An `OWNED` unit never becomes billable and
        therefore never contributes to any vendor liability or invoice."
        PRD §3.10: "Only after that does the billing check run: every named unit
        must be in `billing_state` `BILLABLE`, and one that is not is rejected with
        `ERR_UNIT_NOT_BILLABLE`."

        Design: Corner/validations/owned_unit_is_not_billable_on_a_consignment_invoice
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        agreement = create_active_agreement(vendor["id"])
        catalog_item = create_catalog_item(vendor["id"])
        lot = create_lot(catalog_item["id"])
        unit = add_unit(lot["id"], "SN-0001", 400_000)
        release_lot(lot["id"])

        patient = create_patient()
        case = create_case(patient["id"])
        start_case(case["id"])
        document_implant(case["id"], unit)

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": vendor["id"],
                    "consignment_agreement_id": agreement["id"],
                    "invoice_number": "INV-1",
                    "submitted_total_cents": 400_000,
                    "device_unit_ids": [unit["id"]],
                    "expected_agreement_version": agreement_version(agreement["id"]),
                },
                make_vendor_rep_headers(vendor["id"]),
            ),
            ApiErrorId.ERR_UNIT_NOT_BILLABLE,
            409,
        )

        after = get_unit(unit["id"])
        assert after["ownership"] == "OWNED"
        assert after["billing_state"] == "NOT_BILLABLE"
        assert after["contract_price_cents"] is None

        _, meta = validate_paginated(
            api.list_vendor_invoices(IL, {"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_rep_may_not_bill_under_another_vendors_identity(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a vendor
        compare that resource's vendor foreign key to `X-User-ID`: on invoice
        submission and resubmission the check is direct, against the invoice's
        `vendor_id`; on a return credit the check walks from the explant record to
        its implant record, to the device unit, to that unit's lot, to that lot's
        catalog item, and compares the catalog item's `vendor_id`. A `VendorRep`
        acting on another vendor's row is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/vendorrep_cannot_invoice_units_belonging_to_another_vendor
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor_a = create_vendor(name="Ortholux A", vendor_code="ORTHO-A")
        vendor_b = create_vendor(name="Ortholux B", vendor_code="ORTHO-B")
        agreement = create_active_agreement(vendor_a["id"])
        catalog_item = create_catalog_item(vendor_a["id"])
        lot = create_lot(catalog_item["id"])
        unit = add_unit(
            lot["id"], "SN-0001", 462_500, consignment_agreement_id=agreement["id"]
        )
        release_lot(lot["id"])

        patient = create_patient()
        case = create_case(patient["id"])
        start_case(case["id"])
        document_implant(case["id"], unit)

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": vendor_a["id"],
                    "consignment_agreement_id": agreement["id"],
                    "invoice_number": "INV-1",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [unit["id"]],
                    "expected_agreement_version": agreement_version(agreement["id"]),
                },
                make_vendor_rep_headers(vendor_b["id"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        _, meta = validate_paginated(
            api.list_vendor_invoices(IL, {"vendor_id": vendor_a["id"]})
        )
        assert meta["total_count"] == 0

        after = get_unit(unit["id"])
        assert after["billing_state"] == "BILLABLE"
        assert after["vendor_invoice_id"] is None


class TestOptimisticConcurrencyOnLotAndAgreement:
    def test_stale_lot_and_stale_agreement_versions_are_both_rejected(self, api):
        """PRD §2.7: "A request to `POST /udi/lots/{lot_id}/device-units` must carry
        `expected_lot_version` holding the client's last observed `version` of that
        lot. A lot legitimately accepts repeated unit additions while it sits in
        quarantine, so no state precondition stops a later request; the
        stale-version check is the only guard that stops a receiver from posting
        serials against a `received_qty` it no longer knows. A mismatch is rejected
        with `ERR_STALE_LOT_VERSION` (HTTP 412)."
        PRD §2.7: "A request to `POST /udi/vendor-invoices` must carry
        `expected_agreement_version` holding the client's last observed `version` of
        the consignment agreement named in the body. An agreement legitimately
        accepts many invoices, so nothing in the invoice lifecycle blocks a later
        submission; the stale-version check is what stops a vendor from billing
        under a price-list revision it has not yet seen. A mismatch is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_lot_and_agreement_versions_reject_dependent_creates
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        agreement = create_active_agreement(vendor["id"])
        catalog_item = create_catalog_item(vendor["id"])
        lot = create_lot(catalog_item["id"])
        stale_lot_version = lot["version"]
        first_unit = add_unit(
            lot["id"], "SN-0001", 462_500, consignment_agreement_id=agreement["id"]
        )

        validate_error(
            api.add_device_unit(
                lot["id"],
                {
                    "udi_serial": "SN-0002",
                    "acquisition_cost_cents": 462_500,
                    "consignment_agreement_id": agreement["id"],
                    "expected_lot_version": stale_lot_version,
                },
                RT,
            ),
            ApiErrorId.ERR_STALE_LOT_VERSION,
            412,
        )
        assert get_lot(lot["id"])["received_qty"] == 1

        second_unit = validate_success(
            api.add_device_unit(
                lot["id"],
                {
                    "udi_serial": "SN-0002",
                    "acquisition_cost_cents": 462_500,
                    "consignment_agreement_id": agreement["id"],
                    "expected_lot_version": lot_version(lot["id"]),
                },
                RT,
            ),
            201,
        )
        assert get_lot(lot["id"])["received_qty"] == 2

        release_lot(lot["id"])
        patient = create_patient()
        case = create_case(patient["id"], scheduled_end_utc="2026-09-10T12:00:00Z")
        start_case(case["id"])
        document_implant(case["id"], get_unit(first_unit["id"]))
        document_implant(case["id"], get_unit(second_unit["id"]), laterality="RIGHT")

        stale_agreement_version = agreement_version(agreement["id"])
        submit_invoice(
            vendor["id"],
            agreement["id"],
            [first_unit["id"]],
            462_500,
            invoice_number="INV-1",
        )

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": vendor["id"],
                    "consignment_agreement_id": agreement["id"],
                    "invoice_number": "INV-2",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [second_unit["id"]],
                    "expected_agreement_version": stale_agreement_version,
                },
                make_vendor_rep_headers(vendor["id"]),
            ),
            ApiErrorId.ERR_STALE_AGREEMENT_VERSION,
            412,
        )

        _, meta = validate_paginated(
            api.list_vendor_invoices(IL, {"consignment_agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 1

        unbilled = get_unit(second_unit["id"])
        assert unbilled["billing_state"] == "BILLABLE"
        assert unbilled["vendor_invoice_id"] is None


def _two_agreement_world():
    """One vendor holding an ACTIVE agreement and a never-activated DRAFT one;
    a consigned unit under the ACTIVE agreement, implanted so it is BILLABLE."""
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    active = create_active_agreement(vendor["id"], agreement_code="AGR-A")
    draft = create_agreement(vendor["id"], agreement_code="AGR-B")
    catalog_item = create_catalog_item(vendor["id"])
    lot = create_lot(catalog_item["id"])
    unit = add_unit(lot["id"], "SN-0001", 462_500, consignment_agreement_id=active["id"])
    release_lot(lot["id"])

    patient = create_patient()
    case = create_case(patient["id"])
    start_case(case["id"])
    document_implant(case["id"], get_unit(unit["id"]))

    return {
        "vendor": vendor,
        "active_agreement": active,
        "draft_agreement": draft,
        "unit": get_unit(unit["id"]),
    }
