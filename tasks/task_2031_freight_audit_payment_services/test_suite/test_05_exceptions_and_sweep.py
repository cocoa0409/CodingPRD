"""Dispute exceptions: negotiation loop, resolution pins, and expiry.

Covers PRD §3.4 rerate gating and resolution-pinned clearing, PRD §3.5 the
negotiation cycle with its round limit and dispute window, the §2.8
evaluation order between state legality and fiscal checks, and the §3.1/§3.5
daily sweep.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    build_rate_mismatch_exception,
    finalize_invoice,
    get_invoice,
    list_invoice_exceptions,
    make_carrier_rep_headers,
    notify_and_respond,
    rerate_invoice,
    set_clock,
    setup_standard_chain,
    validate_error,
    validate_success,
)

_TOLERANCE = {"audit_tolerance_minor": 500, "audit_tolerance_pct_bp": 200}


def _get_exception(invoice_id: str, exception_id: str):
    for exception in list_invoice_exceptions(invoice_id):
        if exception["id"] == exception_id:
            return exception
    raise AssertionError(f"exception {exception_id} not found on invoice {invoice_id}")


class TestParallelDimensions:
    """The audit dimension cycles while the payment dimension stays UNPAID."""

    def _setup(self, api):
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice, exception = build_rate_mismatch_exception(chain)
        notify_and_respond(exception["id"], chain["carrier"]["id"])
        return chain, invoice, exception

    def test_audit_cycle_leaves_payment_dimension_untouched(self, api):
        """PRD §1: "Every invoice carries two independent status dimensions —
        an audit dimension that walks from receipt through rating to clearance
        or exception, and a payment dimension that walks from unpaid through
        scheduling to settlement".

        The invoice is born UNPAID and stays UNPAID across EXCEPTION, the
        rerate back to RATED, and the final clear to CLEARED.

        Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_independent_progress
        """
        _chain, invoice, _exception = self._setup(api)
        created = get_invoice(invoice["id"])
        assert created["payment_status"] == "UNPAID"
        assert created["audit_status"] == "EXCEPTION"
        validate_success(
            api.resolve_exception(_exception["id"], {"outcome": "ACCEPT"}, ANALYST), 200
        )
        rerated = rerate_invoice(invoice["id"])
        assert rerated["audit_status"] == "RATED"
        assert rerated["payment_status"] == "UNPAID"
        cleared = finalize_invoice(invoice["id"])
        assert cleared["audit_status"] == "CLEARED"
        assert cleared["payment_status"] == "UNPAID"

    def test_resolved_accepted_pins_approved_to_rated_total(self, api):
        """PRD §3.5: "Resolving with an `outcome` of `ACCEPT` moves
        `CARRIER_RESPONDED` → `RESOLVED_ACCEPTED`: the carrier concedes the
        full dispute, `resolution_credit_minor` is set to the full
        `disputed_amount_minor`, the invoice's `approved_amount_minor` is
        pinned to its `rated_total_minor`, and `home_total_minor` is
        recomputed." PRD §3.4: "When any exception on the invoice already
        stands at `RESOLVED_ACCEPTED` or `RESOLVED_CONCEDED`, the invoice
        clears and the resolution's pinned amount governs
        `approved_amount_minor`."

        The rated total is 87500; with invoice currency equal to the home
        currency the home total is the identity.

        Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_independent_progress
        """
        _chain, invoice, exception = self._setup(api)
        resolved = validate_success(
            api.resolve_exception(exception["id"], {"outcome": "ACCEPT"}, ANALYST), 200
        )
        assert resolved["status"] == "RESOLVED_ACCEPTED"
        assert resolved["resolution_credit_minor"] == 3500
        rerate_invoice(invoice["id"])
        cleared = finalize_invoice(invoice["id"])
        assert cleared["audit_status"] == "CLEARED"
        assert cleared["approved_amount_minor"] == 87500
        assert cleared["home_total_minor"] == 87500


class TestNegotiationRoundLimit:
    """CARRIER_RESPONDED -> counter -> CARRIER_NOTIFIED cycles with a hard
    stop after three counters."""

    def _setup(self, api):
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice, exception = build_rate_mismatch_exception(chain)
        notify_and_respond(exception["id"], chain["carrier"]["id"])
        return chain, invoice, exception

    def _counter_round(self, api, exception_id: str, carrier_id: str):
        """One counter plus the carrier's renewed response."""
        counted = validate_success(api.counter_exception(exception_id, ANALYST), 200)
        validate_success(
            api.respond_exception_carrier(
                exception_id, {}, make_carrier_rep_headers(carrier_id)
            ),
            200,
        )
        return counted

    def test_third_counter_succeeds_at_the_boundary(self, api):
        """PRD §3.5: "If the answer is unsatisfying, the `AuditAnalyst`
        counters, moving `CARRIER_RESPONDED` back to `CARRIER_NOTIFIED` and
        incrementing `round_count` by one. At most three counters are allowed:
        the counter succeeds while `round_count` is below three, so the third
        counter (moving the count from 2 to 3) still succeeds, but a fourth
        attempt fails with `ERR_NEGOTIATION_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/exception_counter_cycle_round_limit
        """
        chain, _invoice, exception = self._setup(api)
        carrier_id = chain["carrier"]["id"]
        first = self._counter_round(api, exception["id"], carrier_id)
        assert first["round_count"] == 1
        second = self._counter_round(api, exception["id"], carrier_id)
        assert second["round_count"] == 2
        third = validate_success(api.counter_exception(exception["id"], ANALYST), 200)
        assert third["round_count"] == 3
        assert third["status"] == "CARRIER_NOTIFIED"

    def test_fourth_counter_is_rejected(self, api):
        """PRD §3.5: "At most three counters are allowed: the counter succeeds
        while `round_count` is below three, so the third counter (moving the
        count from 2 to 3) still succeeds, but a fourth attempt fails with
        `ERR_NEGOTIATION_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/exception_counter_cycle_round_limit
        """
        chain, _invoice, exception = self._setup(api)
        carrier_id = chain["carrier"]["id"]
        self._counter_round(api, exception["id"], carrier_id)
        self._counter_round(api, exception["id"], carrier_id)
        validate_success(api.counter_exception(exception["id"], ANALYST), 200)
        validate_success(
            api.respond_exception_carrier(
                exception["id"], {}, make_carrier_rep_headers(carrier_id)
            ),
            200,
        )
        res = api.counter_exception(exception["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT, expected_status=409)


class TestStateMasksFiscal:
    """A state-illegal resolve is reported before the fiscal credit check."""

    def _expired_exception(self, api):
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice, exception = build_rate_mismatch_exception(chain)
        set_clock("2026-09-15T00:00:00Z")
        get_sweep = api.run_daily_sweep(chain["client"]["id"], ADMIN)
        validate_success(get_sweep, 200)
        expired = _get_exception(invoice["id"], exception["id"])
        assert expired["status"] == "EXPIRED", "Setup failed: exception not EXPIRED"
        return chain, invoice, exception

    def test_resolve_expired_exception_reports_invalid_state_not_fiscal(self, api):
        """PRD §2.8: "Every request passes through a fixed evaluation pipeline,
        and a failure at any stage short-circuits the stages after it — when
        several rules would independently reject the same request, the earliest
        stage's error is the one reported." State legality (stage 6,
        `ERR_INVALID_STATE`) precedes fiscal amounts (stage 11,
        `ERR_CREDIT_EXCEEDS_DISPUTED`), so resolving an EXPIRED exception with
        an over-large credit reports the state violation.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_expired_exception_resolve
        """
        _chain, _invoice, exception = self._expired_exception(api)
        res = api.resolve_exception(
            exception["id"], {"outcome": "CONCEDE", "credit_minor": 999999}, ANALYST
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_analyst_resolve_of_escalated_reports_invalid_state_not_fiscal(self, api):
        """PRD §3.5: "An escalated exception leaves the negotiation loop: only
        a `FapAdmin` can close it, by force-resolving `ESCALATED` →
        `RESOLVED_CONCEDED` under the same concession rule". For an
        `AuditAnalyst` the ESCALATED state forbids the transition, and per PRD
        §2.8 that stage-6 failure is reported before the stage-11 credit
        check (`ERR_CREDIT_EXCEEDS_DISPUTED`) is ever evaluated.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_expired_exception_resolve
        """
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        _invoice, exception = build_rate_mismatch_exception(chain)
        validate_success(api.escalate_exception(exception["id"], ANALYST), 200)
        res = api.resolve_exception(
            exception["id"], {"outcome": "CONCEDE", "credit_minor": 999999}, ANALYST
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestResolutionGuards:
    def test_credit_above_disputed_is_rejected(self, api):
        """PRD §3.5: "Resolving with an `outcome` of `CONCEDE` moves
        `CARRIER_RESPONDED` → `RESOLVED_CONCEDED`: the request carries a
        `credit_minor` that must not exceed the `disputed_amount_minor`
        (`ERR_CREDIT_EXCEEDS_DISPUTED`)".

        Design: Corner/validations/credit_exceeds_disputed_rejected
        """
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice, exception = build_rate_mismatch_exception(chain)
        notify_and_respond(exception["id"], chain["carrier"]["id"])
        res = api.resolve_exception(
            exception["id"], {"outcome": "CONCEDE", "credit_minor": 9999}, ANALYST
        )
        validate_error(res, ApiErrorId.ERR_CREDIT_EXCEEDS_DISPUTED, expected_status=409)
        current = _get_exception(invoice["id"], exception["id"])
        assert current["status"] == "CARRIER_RESPONDED"

    def test_carrier_response_after_dispute_window_is_rejected(self, api):
        """PRD §3.5: "A `CarrierRep` then answers, moving `CARRIER_NOTIFIED` →
        `CARRIER_RESPONDED`, optionally attaching a `response_note`; the acting
        carrier's identity must match the invoice's `carrier_id`
        (`ERR_FORBIDDEN_FOR_ROLE` otherwise), and the same dispute-window check
        applies with the same error." The window rule: "the current logical
        date must not be later than `opened_date` plus the client's
        `dispute_window_days`, otherwise the action fails with
        `ERR_DISPUTE_WINDOW_EXPIRED`."

        Opened 2026-08-01 with a 30-day window; at 2026-09-15 the response
        fails even without any sweep expiring the exception first.

        Design: Corner/validations/dispute_window_expired_blocks_response
        """
        chain = setup_standard_chain(
            client_overrides={"dispute_window_days": 30, **_TOLERANCE}
        )
        invoice, exception = build_rate_mismatch_exception(chain)
        validate_success(api.notify_exception_carrier(exception["id"], ANALYST), 200)
        set_clock("2026-09-15T00:00:00Z")
        res = api.respond_exception_carrier(
            exception["id"], {}, make_carrier_rep_headers(chain["carrier"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED, expected_status=409)
        current = _get_exception(invoice["id"], exception["id"])
        assert current["status"] == "CARRIER_NOTIFIED"

    def test_rerate_blocked_while_exception_open(self, api):
        """PRD §3.4: "It is refused with `ERR_EXCEPTION_STILL_ACTIVE` while any
        exception on the invoice stands at `OPEN`, `CARRIER_NOTIFIED`,
        `CARRIER_RESPONDED`, or `ESCALATED`; resolved or expired exceptions do
        not block it."

        Design: Corner/validations/rerate_with_open_exception_rejected
        """
        chain = setup_standard_chain(client_overrides=_TOLERANCE)
        invoice, _exception = build_rate_mismatch_exception(chain)
        res = api.rerate_invoice(invoice["id"], {}, ANALYST)
        validate_error(res, ApiErrorId.ERR_EXCEPTION_STILL_ACTIVE, expected_status=409)
        current = get_invoice(invoice["id"])
        assert current["audit_status"] == "EXCEPTION"


class TestDailySweep:
    def test_sweep_expires_overdue_contract_and_stale_exception(self, api):
        """PRD §3.2: "The daily sweep expires every `ACTIVE` contract whose
        `effective_to` is on or before the current logical date, moving it to
        `EXPIRED`." PRD §3.5: "Exceptions that outlive the dispute window
        expire through the daily sweep: when the current logical date is later
        than `opened_date` plus `dispute_window_days`, an exception in `OPEN`,
        `CARRIER_NOTIFIED`, or `CARRIER_RESPONDED` moves to `EXPIRED`."
        PRD §3.1: the sweep "expires the client's overdue contracts and dispute
        exceptions and reports what it touched as `expired_contract_ids` and
        `expired_exception_ids`".

        At 2026-09-15 the contract ending 2026-09-01 and the exception opened
        2026-08-01 (30-day window) both expire; the invoice remains in audit
        EXCEPTION (PRD §3.5: "the invoice itself remains in audit status
        `EXCEPTION` until it is rerated").

        Design: Corner/state_machines/sweep_expires_contract_and_exception
        """
        chain = setup_standard_chain(
            client_overrides={"dispute_window_days": 30, **_TOLERANCE},
            contract_overrides={"effective_to": "2026-09-01"},
        )
        invoice, exception = build_rate_mismatch_exception(chain)
        set_clock("2026-09-15T00:00:00Z")
        sweep = validate_success(api.run_daily_sweep(chain["client"]["id"], ADMIN), 200)
        assert chain["contract"]["id"] in sweep["expired_contract_ids"]
        assert exception["id"] in sweep["expired_exception_ids"]
        contract = validate_success(api.get_rate_contract(chain["contract"]["id"], ADMIN))
        assert contract["status"] == "EXPIRED"
        expired = _get_exception(invoice["id"], exception["id"])
        assert expired["status"] == "EXPIRED"
        current = get_invoice(invoice["id"])
        assert current["audit_status"] == "EXCEPTION"
