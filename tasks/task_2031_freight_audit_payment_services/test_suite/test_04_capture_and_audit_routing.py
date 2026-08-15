"""Capture-time duplicate detection and finalize-time audit routing.

Covers PRD §3.3 fuzzy duplicate detection (closed seven-day window, 50 bp
amount band, non-voided candidate set), PRD §3.4 no-contract diversion, the
variance-tolerance boundary, and exception-routing precedence.
"""
from test_helpers import (
    ANALYST,
    capture_invoice,
    create_contract,
    create_invoice,
    create_shipment,
    finalize_invoice,
    find_line,
    first_exception,
    get_invoice,
    rate_invoice,
    setup_standard_chain,
    validate_success,
)

_TOLERANCE = {"audit_tolerance_minor": 500, "audit_tolerance_pct_bp": 200}


class TestVarianceToleranceBoundary:
    """Canonical 500 kg fixture rates at 87500; the client's tolerances are
    500 minor units and 200 bp."""

    def _invoice_billed(self, api, chain, number, base_billed):
        shipment = create_shipment(
            chain["client"]["id"], chain["carrier"]["id"], pro_number=f"PRO-{number}"
        )
        invoice = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number=number,
            shipment_id=shipment["id"],
            billed_total_minor=base_billed + 7500 + 5000,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": base_billed},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
            ],
        )
        capture_invoice(invoice["id"])
        rate_invoice(invoice["id"])
        return invoice

    def test_variance_equal_to_tolerance_clears(self, api):
        """PRD §3.4: "Equality at either tolerance passes — a variance exactly
        at the tolerance clears rather than routes."

        Billed 88000 vs rated 87500: |variance| 500 == audit_tolerance_minor
        and floor(500 x 10000 / 87500) = 57 bp <= 200 bp, so the invoice clears
        with approved = 88000 - 500 = 87500.

        Design: Difficulty/boundary_precision_check/variance_tolerance_exact_boundary_clears
        """
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice = self._invoice_billed(api, chain, "INV-0002", 75500)
        finalized = finalize_invoice(invoice["id"])
        assert finalized["audit_status"] == "CLEARED"
        assert finalized["variance_minor"] == 500
        assert finalized["approved_amount_minor"] == 87500

    def test_variance_one_over_tolerance_routes_to_exception(self, api):
        """PRD §3.4: "third, an absolute `variance_minor` exceeding the
        client's `audit_tolerance_minor` **or** a `variance_pct_bp` exceeding
        the client's `audit_tolerance_pct_bp` raises `RATE_MISMATCH` with a
        disputed amount equal to the positive part of the variance (the
        variance itself when positive, zero otherwise), routed to `CARRIER`."

        Billed 88001 vs rated 87500: |variance| 501 > 500 routes.

        Design: Difficulty/boundary_precision_check/variance_tolerance_exact_boundary_clears
        """
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice = self._invoice_billed(api, chain, "INV-0003", 75501)
        finalized = finalize_invoice(invoice["id"])
        assert finalized["audit_status"] == "EXCEPTION"
        exception = first_exception(invoice["id"])
        assert exception["code"] == "RATE_MISMATCH"
        assert exception["disputed_amount_minor"] == 501
        assert exception["routed_queue"] == "CARRIER"


class TestRateWithoutCoveringContract:
    """The carrier's only contract stays DRAFT, so no ACTIVE or SUPERSEDED
    contract covers the as-of date."""

    def _setup(self, api):
        chain = setup_standard_chain(with_contract=False)
        # Draft contract is created but never activated.
        create_contract(chain["carrier"]["id"], name="C-DRAFT")
        shipment = create_shipment(chain["client"]["id"], chain["carrier"]["id"])
        invoice = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0009",
            shipment_id=shipment["id"],
        )
        capture_invoice(invoice["id"])
        return chain, invoice

    def test_rate_diverts_to_exception_with_no_contract_code(self, api):
        """PRD §3.4: "The contract selector considers the carrier's contracts
        in `ACTIVE` or `SUPERSEDED` status whose half-open window contains the
        as-of date and picks the one with the latest `activated_at`, breaking
        ties by latest `created_at`." PRD §3.4: "When no contract covers the
        date, no rating happens at all: the invoice instead moves `CAPTURED` →
        `EXCEPTION`, and the system opens an audit exception with code
        `NO_CONTRACT`, a `disputed_amount_minor` equal to the full
        `billed_total_minor`, and routing to the `AUDIT_TEAM` queue."

        A DRAFT contract is in neither eligible status, so nothing covers.

        Design: Difficulty/cross_entity_state_dependency/invoice_rate_without_active_contract_routes_no_contract
        """
        _chain, invoice = self._setup(api)
        rated = rate_invoice(invoice["id"])
        assert rated["audit_status"] == "EXCEPTION"
        exception = first_exception(invoice["id"])
        assert exception["code"] == "NO_CONTRACT"
        assert exception["routed_queue"] == "AUDIT_TEAM"
        assert exception["disputed_amount_minor"] == 87500

    def test_diverted_invoice_is_not_rated(self, api):
        """PRD §3.4: "When no contract covers the date, no rating happens at
        all". PRD §3.3: "The computed fields start dormant —
        `rated_total_minor` is 0 until a rating pass runs, `duplicate_flag` is
        only assigned during capture, and `variance_minor`, `variance_pct_bp`,
        `approved_amount_minor`, `home_total_minor`, `due_date`,
        `scheduled_minor`, and `paid_minor` take their values from the audit
        and payment events described below."

        Design: Difficulty/cross_entity_state_dependency/invoice_rate_without_active_contract_routes_no_contract
        """
        _chain, invoice = self._setup(api)
        rate_invoice(invoice["id"])
        current = get_invoice(invoice["id"])
        assert current["audit_status"] == "EXCEPTION"
        assert current["rated_total_minor"] == 0
        assert current.get("rated_contract_id") is None


class TestFuzzyDuplicateWindow:
    """Reference invoice INV-0001 billed 87500 dated 2026-08-03 is captured
    first; each probe invoice is then captured against it."""

    def _setup_reference(self, api):
        chain = setup_standard_chain(with_contract=False)
        reference = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0001",
        )
        capture_invoice(reference["id"])
        return chain

    def test_seven_day_diff_same_amount_flags_fuzzy(self, api):
        """PRD §3.3: "Capture runs fuzzy duplicate detection against every
        other non-voided invoice of the same client and carrier: the invoice is
        flagged `FUZZY` when there exists another such invoice whose billed
        total differs from the new invoice's `billed_total_minor` by an amount
        that, multiplied by ten thousand, does not exceed fifty times the new
        invoice's billed total (with the new invoice's total treated as 1 if it
        were zero) **and** whose `invoice_date` lies at most seven days away
        from the new invoice's `invoice_date`, both ends of that window
        inclusive; otherwise the flag is set to `NONE`. Both fuzzy boundaries
        are inclusive."

        INV-0010: equal amount (0 bp <= 50 bp) and exactly 7 days away — both
        boundaries are inclusive, so the flag is FUZZY.

        Design: Difficulty/resource_temporal_overlap/fuzzy_duplicate_closed_window_boundary
        """
        chain = self._setup_reference(api)
        probe = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0010",
            invoice_date="2026-08-10",
        )
        captured = capture_invoice(probe["id"])
        assert captured["duplicate_flag"] == "FUZZY"

    def test_eight_day_diff_and_excess_amount_flags_none(self, api):
        """PRD §3.3: "otherwise the flag is set to `NONE`. Both fuzzy
        boundaries are inclusive."

        INV-0011 dated 2026-08-11 (8 days from INV-0001, outside the window)
        and billed 90000 (difference 2500 x 10000 > 50 x 90000, outside the
        band): the flag is NONE.

        Design: Difficulty/resource_temporal_overlap/fuzzy_duplicate_closed_window_boundary
        """
        chain = self._setup_reference(api)
        probe = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0011",
            invoice_date="2026-08-11",
            billed_total_minor=90000,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 77000},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 8000},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
            ],
        )
        captured = capture_invoice(probe["id"])
        assert captured["duplicate_flag"] == "NONE"


class TestRoutingPrecedence:
    def test_fuzzy_duplicate_outranks_invalid_accessorial(self, api):
        """PRD §3.4: "Otherwise the routing checks run in a strict precedence
        order and the first match wins: first, a `duplicate_flag` of `FUZZY`
        raises an exception with code `DUPLICATE_FUZZY`, a
        `disputed_amount_minor` equal to the full `billed_total_minor`, and
        routing to `AUDIT_TEAM`; second, any line flagged as an invalid
        accessorial raises `INVALID_ACCESSORIAL` with a disputed amount equal
        to the sum of the billed amounts of the invalid lines, routed to
        `CARRIER`".

        INV-0005 is both a fuzzy duplicate (same amount, two days after
        INV-0001) and carries a LIFTGATE line its shipment never rendered, so
        precedence assigns DUPLICATE_FUZZY.

        Design: Corner/calculations/exception_routing_precedence_fuzzy_over_accessorial
        """
        chain = setup_standard_chain()
        sh1 = create_shipment(chain["client"]["id"], chain["carrier"]["id"])
        reference = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0001",
            shipment_id=sh1["id"],
        )
        capture_invoice(reference["id"])
        sh5 = create_shipment(
            chain["client"]["id"],
            chain["carrier"]["id"],
            pro_number="PRO-1005",
            ship_date="2026-08-04",
            accessorials_rendered=[],
        )
        probe = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0005",
            shipment_id=sh5["id"],
            invoice_date="2026-08-05",
        )
        capture_invoice(probe["id"])
        rate_invoice(probe["id"])
        finalized = finalize_invoice(probe["id"])
        assert finalized["audit_status"] == "EXCEPTION"
        exception = first_exception(probe["id"])
        assert exception["code"] == "DUPLICATE_FUZZY"
        assert exception["disputed_amount_minor"] == 87500
        assert exception["routed_queue"] == "AUDIT_TEAM"

    def test_unrendered_accessorial_routes_invalid_accessorial(self, api):
        """PRD §3.4: "For an accessorial line (`LIFTGATE`, `RESIDENTIAL`,
        `INSIDE_DELIVERY`, `DETENTION`, `STORAGE`): when the lane's
        `accessorials` do not offer that code, or the shipment's
        `accessorials_rendered` do not include it, the rated amount is 0 and
        the line is flagged as an invalid accessorial". PRD §3.4: "second, any
        line flagged as an invalid accessorial raises `INVALID_ACCESSORIAL`
        with a disputed amount equal to the sum of the billed amounts of the
        invalid lines, routed to `CARRIER`".

        Design: Corner/calculations/invalid_accessorial_routing
        """
        chain = setup_standard_chain()
        shipment = create_shipment(
            chain["client"]["id"],
            chain["carrier"]["id"],
            pro_number="PRO-1006",
            ship_date="2026-08-14",
            accessorials_rendered=[],
        )
        invoice = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0006",
            shipment_id=shipment["id"],
            invoice_date="2026-08-15",
            billed_total_minor=88000,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 75000},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5500},
            ],
        )
        capture_invoice(invoice["id"])
        rate_invoice(invoice["id"])
        finalized = finalize_invoice(invoice["id"])
        assert finalized["audit_status"] == "EXCEPTION"
        liftgate = find_line(invoice["id"], "LIFTGATE")
        assert liftgate["rated_amount_minor"] == 0
        exception = first_exception(invoice["id"])
        assert exception["code"] == "INVALID_ACCESSORIAL"
        assert exception["disputed_amount_minor"] == 5500
        assert exception["routed_queue"] == "CARRIER"


class TestFuzzyCandidateSet:
    def test_voided_invoice_is_excluded_from_fuzzy_detection(self, api):
        """PRD §3.3: "Capture runs fuzzy duplicate detection against every
        other non-voided invoice of the same client and carrier". After the
        identical INV-A is voided, no non-voided candidate remains, so INV-B
        (same amount, same date) captures with duplicate_flag NONE.

        Design: Corner/cross_cutting_layers/voided_invoice_excluded_from_fuzzy_detection
        """
        chain = setup_standard_chain(with_contract=False)
        inv_a = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-A",
            billed_total_minor=87500,
            lines=[{"charge_code": "OTHER", "billed_amount_minor": 87500}],
        )
        capture_invoice(inv_a["id"])
        validate_success(api.void_invoice(inv_a["id"], ANALYST), 200)
        inv_b = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-B",
            billed_total_minor=87500,
            lines=[{"charge_code": "OTHER", "billed_amount_minor": 87500}],
        )
        captured = capture_invoice(inv_b["id"])
        assert captured["duplicate_flag"] == "NONE"
