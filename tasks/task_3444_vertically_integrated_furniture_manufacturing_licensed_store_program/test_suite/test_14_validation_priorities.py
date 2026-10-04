"""Validation pipeline precedence: state guards beat the always-last credit
gate, temporal guards beat domain constraints, and request shape beats
existence (PRD §2.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    book_appointment_response,
    create_retail_account,
    create_retail_order,
    make_wholesale_buyer_headers,
    setup_hd_picked_order,
    setup_open_cycle,
    transition_retail_account,
    validate_error,
)


class TestAccountHoldBeatsCreditOverflow:
    """Difficulty instance: account_hold_beats_credit_overflow_on_submit.
    The HOLD state's draft carries provisional total 3865700 (qty 50 at the
    14% tier: 77314 * 50), which alone would fail the 1000000 credit gate."""

    def _setup(self):
        ctx = setup_open_cycle()
        account = create_retail_account(
            business_name="Metro Discount Furniture", credit_limit_cents=1_000_000
        )
        transition_retail_account(account["id"], "HOLD")
        order = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=50)
        return ctx, account, order

    def test_hold_state_error_wins_over_credit_gate(self, api, platform_admin_headers):
        """PRD §2.8: "7. **State-machine guards.** ... retail account active at submit
        (`ERR_ACCOUNT_ON_HOLD`) ... — all HTTP 409."
        PRD §2.8: "10. **The wholesale credit gate is always last.** Only after every
        other guard has passed does order submit evaluate the credit limit, rejecting
        with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."
        PRD §2.8: "The ordering is observable: a submit that would fail both the credit
        gate and, say, a stale cycle surfaces the cycle error, because the credit gate
        runs last"

        Design: Difficulty/priority_pair_validation_conflict/account_hold_beats_credit_overflow_on_submit
        """
        _ctx, account, order = self._setup()
        # Sanity: the draft alone would overflow the credit gate.
        assert order["provisional_total_cents"] == 3_865_700
        resp = api.transition_order(
            order["id"],
            {"action": "SUBMIT"},
            make_wholesale_buyer_headers(account["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD.value)
        assert resp.status_code == 409
        assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value

    def test_hold_state_alone_yields_account_on_hold(self, api, platform_admin_headers):
        """PRD §3.5: "the buyer orderable — a licensee in `ACTIVE` or `PROBATION`
        status, otherwise `ERR_LICENSEE_NOT_ORDERABLE`, or a retail account in `ACTIVE`
        status, otherwise `ERR_ACCOUNT_ON_HOLD`"

        Design: Difficulty/priority_pair_validation_conflict/account_hold_beats_credit_overflow_on_submit
        """
        ctx = setup_open_cycle()
        account = create_retail_account(credit_limit_cents=5_000_000)
        transition_retail_account(account["id"], "HOLD")
        # qty 1 totals 89900 — comfortably inside the limit, so only the HOLD
        # state guard can fire.
        order = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=1)
        resp = api.transition_order(
            order["id"],
            {"action": "SUBMIT"},
            make_wholesale_buyer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD.value)


class TestLeadTimeBeatsWindowDuration:
    """Difficulty instance: lead_time_beats_window_duration_on_appointment_create.
    Clock is 2026-09-01T00:00:00Z; the 2026-09-02T09:00 window is only 33 hours
    out (lead violated) AND 60 minutes long (duration violated)."""

    def test_double_violation_reports_lead_time(self, api, platform_admin_headers):
        """PRD §2.8: "Every request is validated against an ordered pipeline. When a
        request violates several rules at once, the failure reported is the one whose
        pipeline stage comes earliest — lower stage number wins."
        PRD §2.8: "8. **Temporal guards.** Delivery window not in the past
        (`ERR_WINDOW_IN_PAST`), the 48-hour booking lead (`ERR_LEAD_TIME_TOO_SHORT`),
        and the warranty filing windows (`ERR_WARRANTY_WINDOW_EXPIRED`) — all HTTP 422."
        PRD §2.8: "9. **Domain constraints.** ... window duration bounds
        (`ERR_WINDOW_DURATION_INVALID`) ..."

        Design: Difficulty/priority_pair_validation_conflict/lead_time_beats_window_duration_on_appointment_create
        """
        ctx = setup_hd_picked_order(quantity=1)
        resp = book_appointment_response(
            ctx["order"],
            ctx,
            "2026-09-02T09:00:00Z",
            "2026-09-02T10:00:00Z",
            crew_units=1,
        )
        err = validate_error(resp, ApiErrorId.ERR_LEAD_TIME_TOO_SHORT.value)
        assert resp.status_code == 422
        assert err["error_id"] != ApiErrorId.ERR_WINDOW_DURATION_INVALID.value

    def test_lead_time_violation_alone(self, api, platform_admin_headers):
        """PRD §3.6: "`window_start` at least `DELIVERY_MIN_LEAD_HOURS` — 48 hours —
        ahead of the current time (`ERR_LEAD_TIME_TOO_SHORT`)"

        Design: Difficulty/priority_pair_validation_conflict/lead_time_beats_window_duration_on_appointment_create
        """
        ctx = setup_hd_picked_order(quantity=1)
        # 33 hours ahead but a valid 120-minute duration: only the lead rule fires.
        resp = book_appointment_response(
            ctx["order"],
            ctx,
            "2026-09-02T09:00:00Z",
            "2026-09-02T11:00:00Z",
            crew_units=1,
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_TOO_SHORT.value)


class TestShapeBeforeExistence:
    def test_bogus_action_on_unknown_order_returns_validation_before_not_found(self, api, logistics_coordinator_headers):
        """PRD §2.8: "2. **Request shape.** Required fields present, types valid, enum
        values in range, `week_start` midnight-aligned, `approved_parts` well-formed,
        `actual_duration_minutes` present when completing an appointment — any such
        defect is `ERR_VALIDATION` (HTTP 400)."
        PRD §2.8: "5. **Existence.** Path ids and body foreign-key ids must exist,
        validated left to right (§2.9), with the first missing reference producing its
        entity-specific 404 error."
        PRD §2.8: "the failure reported is the one whose pipeline stage comes earliest
        — lower stage number wins."

        Design: Corner/validations/bogus_action_on_unknown_order_returns_validation_before_not_found
        """
        resp = api.transition_order(
            NON_EXISTENT_UUID, {"action": "BOGUS"}, logistics_coordinator_headers
        )
        err = validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
        assert resp.status_code == 400
        assert err["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value
