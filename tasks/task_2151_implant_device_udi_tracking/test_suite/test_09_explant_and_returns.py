"""Explantation, return disposition and the vendor credit."""

from test_helpers import (
    ApiErrorId,
    CC,
    CO,
    IL,
    RI,
    add_unit,
    agreement_version,
    create_active_agreement,
    create_case,
    create_catalog_item,
    create_lot,
    create_patient,
    create_vendor,
    disposition_explant,
    document_implant,
    get_explant,
    get_invoice,
    get_lot,
    get_record,
    get_unit,
    get_vendor,
    make_vendor_rep_headers,
    record_explant,
    release_lot,
    set_clock,
    setup_billable_units,
    setup_shipped_explant,
    ship_explant,
    start_case,
    submit_invoice,
    validate_error,
    validate_success,
    verify_record,
)


def _consigned_unit_world():
    """One ACTIVE ON_IMPLANT agreement and one released consigned serial at
    462,500, with an IN_PROGRESS case standing ready."""
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    agreement = create_active_agreement(vendor["id"])
    catalog_item = create_catalog_item(vendor["id"])
    lot = create_lot(catalog_item["id"])
    unit = add_unit(
        lot["id"], "SN-0001", 462_500, consignment_agreement_id=agreement["id"]
    )
    release_lot(lot["id"])
    patient = create_patient()
    case = create_case(patient["id"])
    start_case(case["id"])
    return {
        "vendor": vendor,
        "agreement": agreement,
        "catalog_item": catalog_item,
        "lot": get_lot(lot["id"]),
        "unit": get_unit(unit["id"]),
        "patient": patient,
        "case": case,
    }


class TestParallelStateDimensions:
    def test_invoicing_advances_billing_while_custody_stays_implanted(self, api):
        """PRD §2.10: "A `DeviceUnit` is the only resource in the service carrying
        two state machines on one row, and they evolve independently of each other."
        PRD §2.10: "An `IMPLANTED` unit may be `NOT_BILLABLE`, `BILLABLE`,
        `INVOICED` or `RECONCILED`; a `CREDIT_PENDING` unit may be `EXPLANTED` or
        `RETURNED_TO_VENDOR`. Neither dimension constrains the other except where a
        transition below explicitly says so."
        PRD §3.10: "A successful submission creates the invoice in `SUBMITTED`, moves
        every listed unit `BILLABLE → INVOICED` with `vendor_invoice_id` pointing at
        the new invoice, and advances the agreement's `version` by one."

        Design: Difficulty/non_linear_state_machine/device_unit_custody_and_billing_dimensions_advance_independently
        """
        world = _consigned_unit_world()
        record = document_implant(world["case"]["id"], world["unit"])
        verify_record(record["id"])

        invoice = submit_invoice(
            world["vendor"]["id"],
            world["agreement"]["id"],
            [world["unit"]["id"]],
            462_500,
            invoice_number="INV-1",
        )

        unit = get_unit(world["unit"]["id"])
        assert unit["custody_state"] == "IMPLANTED"
        assert unit["billing_state"] == "INVOICED"
        assert unit["vendor_invoice_id"] == invoice["id"]

    def test_explant_advances_custody_while_the_invoice_machine_stands_still(self, api):
        """PRD §3.9: "The device unit moves `IMPLANTED → EXPLANTED`, and when its
        `billing_state` is `BILLABLE` or `INVOICED` it moves to `CREDIT_PENDING`;
        that billing change in turn re-derives the vendor's
        `open_consignment_liability_cents`, removing exactly the amount the implant
        had added."
        PRD §2.11: "Units in `NOT_BILLABLE`, `CREDIT_PENDING`, `CREDITED` or
        `RECONCILED` contribute nothing, and `OWNED` units, which never reach
        `BILLABLE`, contribute nothing ever."

        Design: Difficulty/non_linear_state_machine/device_unit_custody_and_billing_dimensions_advance_independently
        """
        world = _consigned_unit_world()
        record = document_implant(world["case"]["id"], world["unit"])
        verify_record(record["id"])
        invoice = submit_invoice(
            world["vendor"]["id"],
            world["agreement"]["id"],
            [world["unit"]["id"]],
            462_500,
            invoice_number="INV-1",
        )

        validate_success(
            api.create_explant(record["id"], {"reason": "INFECTION"}, CC), 201
        )

        unit = get_unit(world["unit"]["id"])
        assert unit["custody_state"] == "EXPLANTED"
        assert unit["billing_state"] == "CREDIT_PENDING"
        assert unit["vendor_invoice_id"] == invoice["id"], (
            "The explant must not detach the unit from its invoice"
        )
        assert get_invoice(invoice["id"])["status"] == "SUBMITTED"
        assert get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"] == 0


class TestVendorLiabilityConservation:
    def test_implanting_a_consigned_unit_adds_its_frozen_price_to_the_liability(
        self, api
    ):
        """PRD §2.11: "`open_consignment_liability_cents` on a vendor is the sum of
        `contract_price_cents` over every device unit whose lot's catalog item
        belongs to that vendor and whose `billing_state` is `BILLABLE` or
        `INVOICED`."
        PRD §3.5: "When that unit's `ownership` is `CONSIGNED` and its agreement is
        `ACTIVE` with a `billing_trigger` of `ON_IMPLANT`, its `billing_state` moves
        `NOT_BILLABLE → BILLABLE`, `contract_price_cents` is frozen from
        `acquisition_cost_cents` and `price_list_version_at_billing` from the
        agreement's current `price_list_version`; that billing change in turn
        re-derives the vendor's `open_consignment_liability_cents`."

        Design: Difficulty/compensating_invariant/vendor_liability_conserved_across_implant_explant_roundtrip
        """
        world = _consigned_unit_world()
        assert (
            get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"] == 0
        )

        document_implant(world["case"]["id"], world["unit"])

        assert (
            get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"]
            == 462_500
        )
        unit = get_unit(world["unit"]["id"])
        assert unit["billing_state"] == "BILLABLE"
        assert unit["contract_price_cents"] == 462_500
        assert unit["price_list_version_at_billing"] == 1

    def test_explanting_removes_exactly_what_the_implant_added(self, api):
        """PRD §2.11: "The conserved-quantity guarantee is monetary: implanting a
        consigned unit moves it from `NOT_BILLABLE` to `BILLABLE` and adds its
        frozen contract price to the sum, explanting it moves it to `CREDIT_PENDING`
        and removes exactly that amount, and neither shipping the return nor
        recording the credit touches the sum again — so the liability after a full
        explant-and-return cycle equals the liability before the implant."
        PRD §3.9: "A unit implanted for at most 30 whole days earns 100 percent of
        its basis; a unit implanted for at least 31 and at most 180 whole days earns
        75 percent; a unit implanted for 181 whole days or more earns 50 percent."

        Design: Difficulty/compensating_invariant/vendor_liability_conserved_across_implant_explant_roundtrip
        """
        world = _consigned_unit_world()
        record = document_implant(world["case"]["id"], world["unit"])
        assert (
            get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"]
            == 462_500
        )

        verify_record(record["id"])
        explant = validate_success(
            api.create_explant(record["id"], {"reason": "DEVICE_FAILURE"}, CC), 201
        )

        assert (
            get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"] == 0
        )
        assert explant["credit_expected_cents"] == 462_500
        assert explant["status"] == "RECORDED"

        unit = get_unit(world["unit"]["id"])
        assert unit["billing_state"] == "CREDIT_PENDING"
        assert unit["custody_state"] == "EXPLANTED"
        assert get_record(record["id"])["status"] == "EXPLANTED"


class TestReturnCreditTiers:
    def test_thirty_days_earns_full_credit_and_thirty_one_days_falls_a_tier(self, api):
        """PRD §3.9: "The expected credit degrades with time in the body. Measure the
        elapsed interval from the unit's `implanted_at_utc` to the logical clock,
        express it in whole days of 86,400 seconds each and discard any remainder. A
        unit implanted for at most 30 whole days earns 100 percent of its basis; a
        unit implanted for at least 31 and at most 180 whole days earns 75 percent; a
        unit implanted for 181 whole days or more earns 50 percent."
        PRD §3.9: "The basis multiplied by the tier percentage is rounded half up to
        a whole cent."

        Design: Corner/calculations/explant_return_credit_tier_boundary_at_thirty_and_thirty_one_days
        """
        world = setup_billable_units(
            (462_500, 462_500),
            verify=True,
            case_overrides={"scheduled_end_utc": "2026-09-10T12:00:00Z"},
        )

        set_clock("2026-10-01T00:00:00Z")
        first = validate_success(
            api.create_explant(
                world["records"][0]["id"], {"reason": "DEVICE_FAILURE"}, CC
            ),
            201,
        )
        assert first["credit_expected_cents"] == 462_500

        set_clock("2026-10-02T00:00:00Z")
        second = validate_success(
            api.create_explant(
                world["records"][1]["id"], {"reason": "DEVICE_FAILURE"}, CC
            ),
            201,
        )
        assert second["credit_expected_cents"] == 346_875

        assert get_unit(world["units"][0]["id"])["billing_state"] == "CREDIT_PENDING"
        assert get_unit(world["units"][1]["id"])["billing_state"] == "CREDIT_PENDING"
        assert get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"] == 0


class TestDispositionBranches:
    def test_local_disposal_and_a_denied_credit_both_return_the_liability(self, api):
        """PRD §3.9: "The local-disposal branch takes no RA number and moves the
        explant `RECORDED → DISPOSED_LOCALLY`, moves the device unit `EXPLANTED →
        DISPOSED`, and moves its `billing_state` `CREDIT_PENDING → BILLABLE`, which
        in turn re-derives the vendor's `open_consignment_liability_cents` — the
        hospital keeps the liability precisely because nothing is going back."
        PRD §3.9: "An amount of exactly zero is a denial: the explant moves to the
        terminal `CREDIT_DENIED` and the device unit's `billing_state` moves
        `CREDIT_PENDING → BILLABLE`, putting the liability back onto the hospital's
        open balance — the compensating branch for a return the vendor refused to
        honour."
        PRD §3.9: "It moves the explant to `SHIPPED` and the device unit `EXPLANTED
        → RETURNED_TO_VENDOR`, re-deriving the lot's `on_hand_qty` and
        `consumed_qty`."

        Design: Corner/state_machines/explant_dispose_locally_returns_liability_and_credit_zero_denies
        """
        world = setup_billable_units(
            (462_500, 462_500),
            verify=True,
            case_overrides={"scheduled_end_utc": "2026-09-10T12:00:00Z"},
        )
        explant_one = record_explant(world["records"][0]["id"], reason="INFECTION")
        explant_two = record_explant(world["records"][1]["id"], reason="UPGRADE")

        disposed = validate_success(
            api.disposition_explant(
                explant_one["id"], {"disposition": "DISPOSE_LOCALLY"}, IL
            ),
            200,
        )
        assert disposed["status"] == "DISPOSED_LOCALLY"
        unit_one = get_unit(world["units"][0]["id"])
        assert unit_one["custody_state"] == "DISPOSED"
        assert unit_one["billing_state"] == "BILLABLE"

        authorized = validate_success(
            api.disposition_explant(
                explant_two["id"],
                {"disposition": "RETURN_TO_VENDOR", "return_authorization_no": "RA-77"},
                IL,
            ),
            200,
        )
        assert authorized["status"] == "RETURN_AUTHORIZED"
        assert authorized["return_authorization_no"] == "RA-77"

        ship_explant(explant_two["id"])
        denied = validate_success(
            api.credit_explant(
                explant_two["id"],
                {"credit_issued_cents": 0},
                make_vendor_rep_headers(world["vendor"]["id"]),
            ),
            200,
        )
        assert denied["status"] == "CREDIT_DENIED"
        unit_two = get_unit(world["units"][1]["id"])
        assert unit_two["custody_state"] == "RETURNED_TO_VENDOR"
        assert unit_two["billing_state"] == "BILLABLE"

        assert (
            get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"]
            == 925_000
        )
        lot = get_lot(world["lot"]["id"])
        assert lot["received_qty"] == 2
        assert lot["on_hand_qty"] == 0
        assert lot["consumed_qty"] == 2


class TestCreditCeiling:
    def test_a_credit_above_the_expected_figure_is_refused_then_the_exact_one_settles(
        self, api
    ):
        """PRD §3.9: "A `VendorRep`, acting only on their own vendor's devices,
        records `credit_issued_cents` against a `SHIPPED` explant. That amount must
        not exceed the record's `credit_expected_cents`; a larger figure is rejected
        with `ERR_CREDIT_EXCEEDS_EXPECTED`. A strictly positive amount moves the
        explant to the terminal `CREDIT_ISSUED` and the device unit's
        `billing_state` `CREDIT_PENDING → CREDITED`."

        Design: Corner/validations/credit_issued_above_expected_is_rejected_then_exact_credit_settles
        """
        world = setup_shipped_explant(462_500)
        vendor_headers = make_vendor_rep_headers(world["vendor"]["id"])
        assert world["explant"]["status"] == "SHIPPED"
        assert get_explant(world["explant"]["id"])["credit_expected_cents"] == 462_500

        validate_error(
            api.credit_explant(
                world["explant"]["id"], {"credit_issued_cents": 462_501}, vendor_headers
            ),
            ApiErrorId.ERR_CREDIT_EXCEEDS_EXPECTED,
            422,
        )
        assert get_explant(world["explant"]["id"])["status"] == "SHIPPED"

        issued = validate_success(
            api.credit_explant(
                world["explant"]["id"], {"credit_issued_cents": 462_500}, vendor_headers
            ),
            200,
        )
        assert issued["status"] == "CREDIT_ISSUED"
        assert issued["credit_issued_cents"] == 462_500

        unit = get_unit(world["unit"]["id"])
        assert unit["billing_state"] == "CREDITED"
        assert unit["custody_state"] == "RETURNED_TO_VENDOR"
        assert get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"] == 0
