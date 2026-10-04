"""Cargo invoicing (provisional vs final) and laytime/demurrage accounting."""
import pytest

from test_helpers import (
    CM,
    MS,
    OP,
    ApiErrorId,
    FINAL_INVOICE_PAYLOAD,
    get_success_data,
    laytime_statement_payload,
    setup_departed_call,
    setup_nominated_call,
    validate_error,
    validate_success,
)


class TestCargoInvoicing:
    def test_cargo_invoice_provisional_vs_final_index(self, api):
        """PRD §3.5: "The provisional variant fires at vessel departure and uses
        the SPA's `estimated_index_price_usd_per_mmbtu` as the index price,
        recording the result as `provisional_invoice_usd`. The final variant fires
        at final-invoice issuance and uses the supplied
        `actual_index_price_usd_per_mmbtu`, recording `final_invoice_usd`".
        PRD §3.5: "In both variants the invoice is the slot's `quantity_mmbtu`
        multiplied by the sum of the SPA's `fixed_liquefaction_fee_usd_per_mmbtu`
        and the SPA's `commodity_multiplier` times an index price, rounded half-up
        to 2 decimal places."
        (3,600,000 * (3.50 + 1.15*2.85) == 24,399,000.00 provisional;
        3,600,000 * (3.50 + 1.15*3.10) == 25,434,000.00 final.)

        Design: Difficulty/dual_variant_calc/cargo_invoice_provisional_vs_final_index
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T22:24:00Z",
        )
        slot = ctx["slot"]
        assert slot["provisional_invoice_usd"] == pytest.approx(24399000.00, abs=0.01), (
            f"provisional invoice must be 24399000.00, got "
            f"{slot['provisional_invoice_usd']}"
        )
        slot = get_success_data(
            api.issue_final_invoice(slot["id"], FINAL_INVOICE_PAYLOAD, CM)
        )
        assert slot["final_invoice_usd"] == pytest.approx(25434000.00, abs=0.01), (
            f"final invoice must be 25434000.00, got {slot['final_invoice_usd']}"
        )
        assert slot["billing_status"] == "FINAL_INVOICED"
        assert slot["lift_status"] == "LOADED"

    def test_cargo_invoice_variants_differ_when_index_prices_differ(self, api):
        """PRD §3.5: "for an identical quantity the two variants differ whenever
        the estimated and actual index prices differ."
        PRD §3.5: "In both variants the invoice is the slot's `quantity_mmbtu`
        multiplied by the sum of the SPA's `fixed_liquefaction_fee_usd_per_mmbtu`
        and the SPA's `commodity_multiplier` times an index price, rounded half-up
        to 2 decimal places."

        Design: Difficulty/dual_variant_calc/cargo_invoice_provisional_vs_final_index
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T22:24:00Z",
        )
        slot = ctx["slot"]
        provisional = slot["provisional_invoice_usd"]
        slot = get_success_data(
            api.issue_final_invoice(slot["id"], FINAL_INVOICE_PAYLOAD, CM)
        )
        final = slot["final_invoice_usd"]
        assert final == pytest.approx(25434000.00, abs=0.01)
        assert provisional == pytest.approx(24399000.00, abs=0.01)
        assert final != provisional, (
            "the two invoice variants must differ when estimated != actual index price"
        )
        # 1,035,000.00 delta on identical quantity
        assert final - provisional == pytest.approx(1035000.00, abs=0.01)

    def test_cargo_slot_parallel_lift_billing_dimensions(self, api):
        """PRD §3.4: "A cargo slot carries two parallel status dimensions. Its
        `lift_status` tracks the physical lifting lifecycle ... while its
        `billing_status` tracks invoicing — `UNBILLED`, `PROVISIONALLY_INVOICED`,
        `FINAL_INVOICED` — and the two evolve independently."
        PRD §3.4: "it computes `final_invoice_usd`, moves `billing_status` to
        `FINAL_INVOICED`, and leaves `lift_status` untouched at `LOADED`".

        Design: Difficulty/non_linear_state_machine/cargo_slot_parallel_lift_billing_dimensions
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T08:00:00Z",
        )
        slot = get_success_data(
            api.issue_final_invoice(
                ctx["slot"]["id"], FINAL_INVOICE_PAYLOAD, CM
            )
        )
        assert slot["lift_status"] == "LOADED", (
            f"final invoicing must leave lift_status LOADED, got {slot['lift_status']}"
        )
        assert slot["billing_status"] == "FINAL_INVOICED"

    def test_final_invoice_preserves_provisional_figures(self, api):
        """PRD §3.4: "it computes `final_invoice_usd`, moves `billing_status` to
        `FINAL_INVOICED`, and leaves `lift_status` untouched at `LOADED`".
        PRD §3.5: "In both variants the invoice is the slot's `quantity_mmbtu`
        multiplied by the sum of the SPA's `fixed_liquefaction_fee_usd_per_mmbtu`
        and the SPA's `commodity_multiplier` times an index price, rounded half-up
        to 2 decimal places."

        Design: Difficulty/non_linear_state_machine/cargo_slot_parallel_lift_billing_dimensions
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T08:00:00Z",
        )
        slot = get_success_data(
            api.issue_final_invoice(ctx["slot"]["id"], FINAL_INVOICE_PAYLOAD, CM)
        )
        assert slot["final_invoice_usd"] == pytest.approx(25434000.00, abs=0.01)
        assert slot["provisional_invoice_usd"] == pytest.approx(24399000.00, abs=0.01), (
            "both billing dimensions must remain readable at once"
        )

    def test_final_invoice_before_departure_rejected(self, api):
        """PRD §3.4: "This requires the slot to be `LOADED` with `billing_status`
        exactly `PROVISIONALLY_INVOICED` — invoicing before departure or after
        finalization is rejected with `ERR_SLOT_INVALID_STATE`".

        Design: Corner/state_machines/final_invoice_before_departure_rejected
        """
        from test_helpers import (
            create_customer,
            create_draft_adp,
            create_spa_payload,
            add_cargo_slot,
            make_customer_rep_headers,
        )

        customer = create_customer(legal_name="Bet Energy")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        slot = add_cargo_slot(
            adp["id"],
            window_start="2027-02-01T00:00:00Z",
            window_end="2027-02-08T00:00:00Z",
        )
        resp = api.issue_final_invoice(slot["id"], FINAL_INVOICE_PAYLOAD, CM)
        err = validate_error(resp, ApiErrorId.ERR_SLOT_INVALID_STATE.value)
        assert err["error_id"] == "ERR_SLOT_INVALID_STATE"
        slot = get_success_data(api.get_cargo_slot(slot["id"], CM))
        assert slot["billing_status"] == "UNBILLED"


class TestLaytimeAccounting:
    def test_laytime_sof_vs_pumplog_basis(self, api):
        """PRD §3.5: "Under the pump-log variant, `used_laytime_hours_pumplog` is
        `pump_hours` plus a connection allowance of 2 hours". PRD §3.5: "The
        `billed_demurrage_usd` is the variant selected by `billing_basis`".
        PRD §3.5: "`allowed_laytime_hours` is the slot quantity divided by the
        terminal loading rate of 240,000 MMBTU per hour, rounded up to a whole
        number of hours, plus a berth allowance of 4 hours."
        (Allowed = ceil(3600000/240000)+4 = 19h; SOF used = 34.40-4 = 30.40h ->
        40,375.00; pump-log used = 26.5+2 = 28.50h -> 33,645.83; billed on the
        SOF basis is 40,375.00.)

        Design: Difficulty/dual_variant_calc/laytime_sof_vs_pumplog_basis
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T22:24:00Z",
        )
        resp = api.create_laytime_statement(
            ctx["call"]["id"],
            {
                "billing_basis": "SOF_BASIS",
                "excluded_periods": [
                    {
                        "start": "2027-01-13T02:00:00Z",
                        "end": "2027-01-13T06:00:00Z",
                        "reason": "TERMINAL_SHORE_DELAY",
                    }
                ],
                "pump_hours": 26.5,
            },
            MS,
        )
        ls = validate_success(resp, expected_status=201)
        assert ls["allowed_laytime_hours"] == pytest.approx(19, abs=0.001)
        assert ls["laytime_start_at"] == "2027-01-12T12:00:00Z", (
            f"laytime start is the earlier of NOR+6h and berthed_at; got "
            f"{ls['laytime_start_at']}"
        )
        assert ls["used_laytime_hours_sof"] == pytest.approx(30.40, abs=0.005)
        assert ls["used_laytime_hours_pumplog"] == pytest.approx(28.50, abs=0.005)
        assert ls["demurrage_amount_sof_usd"] == pytest.approx(40375.00, abs=0.01)
        assert ls["demurrage_amount_pumplog_usd"] == pytest.approx(33645.83, abs=0.01)
        assert ls["billed_demurrage_usd"] == pytest.approx(40375.00, abs=0.01), (
            "SOF_BASIS selects the SOF variant for billing"
        )

    def test_laytime_allowed_hours_formula(self, api):
        """PRD §3.5: "The `allowed_laytime_hours` is the slot quantity divided by
        the terminal loading rate of 240,000 MMBTU per hour, rounded up to a whole
        number of hours, plus a berth allowance of 4 hours."
        PRD §3.5: "Laytime begins at `laytime_start_at`, the earlier of two
        instants: six hours after `nor_tendered_at`, or `berthed_at`."

        Design: Difficulty/dual_variant_calc/laytime_sof_vs_pumplog_basis
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T22:24:00Z",
        )
        ls = get_success_data(
            api.create_laytime_statement(
                ctx["call"]["id"],
                {
                    "billing_basis": "SOF_BASIS",
                    "excluded_periods": [
                        {
                            "start": "2027-01-13T02:00:00Z",
                            "end": "2027-01-13T06:00:00Z",
                            "reason": "TERMINAL_SHORE_DELAY",
                        }
                    ],
                    "pump_hours": 26.5,
                },
                MS,
            )
        )
        # ceil(3600000 / 240000) + 4 == 15 + 4 == 19
        assert ls["allowed_laytime_hours"] == pytest.approx(19, abs=0.001)
        # min(06:00 + 6h, 14:00) == 12:00
        assert ls["laytime_start_at"] == "2027-01-12T12:00:00Z"
        # elapsed 22:24 next day - 12:00 = 34.40h
        assert ls["elapsed_hours"] == pytest.approx(34.40, abs=0.005)

    def test_demurrage_segment_rounding_order(self, api):
        """PRD §3.5: "Under the statement-of-facts variant, the rounding order is
        pinned: each excluded period's duration is first rounded to whole minutes,
        the rounded periods are summed and converted to hours, and only then is
        the sum subtracted from `elapsed_hours` to yield `used_laytime_hours_sof`
        (summing raw seconds and rounding once at the end yields a different cent
        result and is not permitted)."
        (30m30s -> 31m and 60m30s -> 61m sum to 92m = 1.53h; used = 21.50 - 1.53
        = 19.97h; demurrage = 0.97/24 * 85000 = 3,435.42.)

        Design: Difficulty/combinatorial_formula/demurrage_segment_rounding_order
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T00:00:00Z",
            berth_time="2027-01-12T05:00:00Z",
            depart_time="2027-01-13T02:30:00Z",
        )
        resp = api.create_laytime_statement(
            ctx["call"]["id"],
            {
                "billing_basis": "SOF_BASIS",
                "excluded_periods": [
                    {
                        "start": "2027-01-12T10:00:00Z",
                        "end": "2027-01-12T10:30:30Z",
                        "reason": "WEATHER",
                    },
                    {
                        "start": "2027-01-12T15:00:00Z",
                        "end": "2027-01-12T16:00:30Z",
                        "reason": "TERMINAL_SHORE_DELAY",
                    },
                ],
            },
            MS,
        )
        ls = validate_success(resp, expected_status=201)
        assert ls["used_laytime_hours_sof"] == pytest.approx(19.97, abs=0.005), (
            f"per-period minute rounding must yield 19.97h, got "
            f"{ls['used_laytime_hours_sof']}"
        )
        assert ls["billed_demurrage_usd"] == pytest.approx(3435.42, abs=0.01), (
            f"billed demurrage must be 3435.42, got {ls['billed_demurrage_usd']}"
        )
        assert not (
            ls["billed_demurrage_usd"] == pytest.approx(3470.83, abs=0.01)
        ), "summing raw seconds first (91m) is not permitted"

    def test_demurrage_rounding_order_changes_cent_result(self, api):
        """PRD §3.5: "each excluded period's duration is first rounded to whole
        minutes, the rounded periods are summed and converted to hours, and only
        then is the sum subtracted from `elapsed_hours`".
        PRD §3.5: "Demurrage accrues only when used laytime is strictly greater
        than allowed laytime — at exact equality the amount is exactly zero — and
        equals the excess hours divided by 24 and multiplied by the call's
        `demurrage_rate_usd_per_day`".

        Design: Difficulty/combinatorial_formula/demurrage_segment_rounding_order
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T00:00:00Z",
            berth_time="2027-01-12T05:00:00Z",
            depart_time="2027-01-13T02:30:00Z",
        )
        ls = get_success_data(
            api.create_laytime_statement(
                ctx["call"]["id"],
                {
                    "billing_basis": "SOF_BASIS",
                    "excluded_periods": [
                        {
                            "start": "2027-01-12T10:00:00Z",
                            "end": "2027-01-12T10:30:30Z",
                            "reason": "WEATHER",
                        },
                        {
                            "start": "2027-01-12T15:00:00Z",
                            "end": "2027-01-12T16:00:30Z",
                            "reason": "TERMINAL_SHORE_DELAY",
                        },
                    ],
                },
                MS,
            )
        )
        # excess 19.97 - 19 == 0.97h; 0.97 / 24 * 85000 == 3435.42
        excess = ls["used_laytime_hours_sof"] - ls["allowed_laytime_hours"]
        assert excess == pytest.approx(0.97, abs=0.005)
        assert ls["demurrage_amount_sof_usd"] == pytest.approx(3435.42, abs=0.01)

    def test_demurrage_zero_when_used_equals_allowed(self, api):
        """PRD §3.5: "Demurrage accrues only when used laytime is strictly greater
        than allowed laytime — at exact equality the amount is exactly zero".

        Design: Difficulty/boundary_precision_check/demurrage_zero_when_used_equals_allowed
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T00:00:00Z",
            berth_time="2027-01-12T05:00:00Z",
            depart_time="2027-01-13T00:00:00Z",
        )
        ls = get_success_data(
            api.create_laytime_statement(
                ctx["call"]["id"],
                {"billing_basis": "SOF_BASIS"},
                MS,
            )
        )
        assert ls["used_laytime_hours_sof"] == pytest.approx(19.00, abs=0.005)
        assert ls["allowed_laytime_hours"] == pytest.approx(19, abs=0.001)
        assert ls["billed_demurrage_usd"] == pytest.approx(0.00, abs=0.001), (
            f"demurrage at exact equality must be exactly zero, got "
            f"{ls['billed_demurrage_usd']}"
        )

    def test_demurrage_positive_when_used_exceeds_allowed_by_fraction(self, api):
        """PRD §3.5: "Demurrage accrues only when used laytime is strictly greater
        than allowed laytime — at exact equality the amount is exactly zero — and
        equals the excess hours divided by 24 and multiplied by the call's
        `demurrage_rate_usd_per_day`, computed independently as
        `demurrage_amount_sof_usd` and `demurrage_amount_pumplog_usd`."

        Design: Difficulty/boundary_precision_check/demurrage_zero_when_used_equals_allowed
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T22:24:00Z",
        )
        ls = get_success_data(
            api.create_laytime_statement(
                ctx["call"]["id"],
                {
                    "billing_basis": "SOF_BASIS",
                    "excluded_periods": [
                        {
                            "start": "2027-01-13T02:00:00Z",
                            "end": "2027-01-13T06:00:00Z",
                            "reason": "TERMINAL_SHORE_DELAY",
                        }
                    ],
                },
                MS,
            )
        )
        # used 30.40 > allowed 19 -> demurrage = 11.40/24 * 85000 == 40375.00
        assert ls["used_laytime_hours_sof"] > ls["allowed_laytime_hours"]
        assert ls["billed_demurrage_usd"] == pytest.approx(40375.00, abs=0.01)

    def test_laytime_statement_before_departure_rejected(self, api):
        """PRD §3.5: "Submitting a statement for a call that has not departed is
        rejected with `ERR_CALL_INVALID_STATE`."

        Design: Corner/state_machines/laytime_statement_before_departure_rejected
        """
        ctx = setup_nominated_call(
            slot_spec={
                "window_start": "2027-01-10T00:00:00Z",
                "window_end": "2027-01-17T00:00:00Z",
            }
        )
        call = get_success_data(
            api.accept_vessel_call(
                ctx["call"]["id"],
                {
                    "berth_id": ctx["berth"]["id"],
                    "window_start": "2027-01-12T00:00:00Z",
                    "window_end": "2027-01-14T00:00:00Z",
                },
                MS,
            )
        )
        get_success_data(api.set_clock("2027-01-12T06:00:00Z", OP))
        get_success_data(api.tender_nor(call["id"], ctx["rep"]))
        get_success_data(api.set_clock("2027-01-12T14:00:00Z", OP))
        call = get_success_data(api.berth_vessel_call(call["id"], MS))
        assert call["status"] == "BERTHED"
        resp = api.create_laytime_statement(
            call["id"], {"billing_basis": "SOF_BASIS"}, MS
        )
        err = validate_error(resp, ApiErrorId.ERR_CALL_INVALID_STATE.value)
        assert err["error_id"] == "ERR_CALL_INVALID_STATE"
        call = get_success_data(api.get_vessel_call(call["id"], MS))
        assert call["status"] == "BERTHED"


class TestLaytimeStatementLifecycle:
    def test_laytime_dispute_resolve_branch(self, api):
        """PRD §3.5: "A `CommercialManager` resolves a disputed statement by
        supplying an `adjusted_demurrage_amount_usd` and optionally a
        `resolution_note`; resolution records the commercially agreed override in
        `adjusted_demurrage_usd` (which may differ from `billed_demurrage_usd`)
        and moves `DISPUTED` to `RESOLVED`."

        Design: Corner/endpoints/laytime_dispute_resolve_branch
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T00:00:00Z",
            berth_time="2027-01-12T05:00:00Z",
            depart_time="2027-01-13T02:30:00Z",
        )
        ls = get_success_data(
            api.create_laytime_statement(
                ctx["call"]["id"],
                {
                    "billing_basis": "SOF_BASIS",
                    "excluded_periods": [
                        {
                            "start": "2027-01-12T10:00:00Z",
                            "end": "2027-01-12T10:30:30Z",
                            "reason": "WEATHER",
                        },
                        {
                            "start": "2027-01-12T15:00:00Z",
                            "end": "2027-01-12T16:00:30Z",
                            "reason": "TERMINAL_SHORE_DELAY",
                        },
                    ],
                },
                MS,
            )
        )
        get_success_data(
            api.dispute_laytime_statement(
                ls["id"], {"reason": "excluded period disputed"}, ctx["rep"]
            )
        )
        ls = get_success_data(
            api.resolve_laytime_statement(
                ls["id"],
                {
                    "adjusted_demurrage_amount_usd": 20000.00,
                    "resolution_note": "split the difference",
                },
                CM,
            )
        )
        assert ls["status"] == "RESOLVED"
        assert ls["billed_demurrage_usd"] == pytest.approx(3435.42, abs=0.01), (
            "the computed variant must be unchanged by resolution"
        )
        assert ls["adjusted_demurrage_usd"] == pytest.approx(20000.00, abs=0.01), (
            "the adjusted amount may differ from billed_demurrage_usd"
        )
        # a second resolve on the RESOLVED statement fails
        resp = api.resolve_laytime_statement(
            ls["id"], {"adjusted_demurrage_amount_usd": 1.00}, CM
        )
        err = validate_error(resp, ApiErrorId.ERR_STATEMENT_INVALID_STATE.value)
        assert err["error_id"] == "ERR_STATEMENT_INVALID_STATE"

    def test_laytime_agree_branch(self, api):
        """PRD §3.5: "The buyer's `CustomerRep` either agrees, moving `SUBMITTED`
        to `AGREED` and closing the matter, or disputes — optionally with a
        `reason` — moving `SUBMITTED` to `DISPUTED`." PRD §3.5: "Agreeing after a
        dispute, or resolving a statement that was never disputed, is rejected
        with `ERR_STATEMENT_INVALID_STATE`."

        Design: Corner/endpoints/laytime_agree_branch
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T00:00:00Z",
            berth_time="2027-01-12T05:00:00Z",
            depart_time="2027-01-13T00:00:00Z",
        )
        ls = get_success_data(
            api.create_laytime_statement(
                ctx["call"]["id"], {"billing_basis": "SOF_BASIS"}, MS
            )
        )
        ls = get_success_data(api.agree_laytime_statement(ls["id"], ctx["rep"]))
        assert ls["status"] == "AGREED"
        assert ls["billed_demurrage_usd"] == pytest.approx(0.00, abs=0.001)
        # a later dispute on the AGREED statement fails (terminal state)
        resp = api.dispute_laytime_statement(ls["id"], {}, ctx["rep"])
        err = validate_error(resp, ApiErrorId.ERR_STATEMENT_INVALID_STATE.value)
        assert err["error_id"] == "ERR_STATEMENT_INVALID_STATE"
