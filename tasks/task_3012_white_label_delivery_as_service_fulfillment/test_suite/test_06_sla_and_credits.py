"""SLA reporting, attainment variants, late-delivery credit thresholds, and
the service-credit ledger (PRD sections 3.7, 3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_courier,
    admin_headers,
    base_chain,
    batch_orders,
    c_headers,
    complete_delivery,
    decide_claim,
    dispatch_batch,
    drive_to_in_transit,
    file_claim,
    finalize_report,
    get_merchant,
    get_order,
    list_report_credits,
    m_headers,
    make_order_ready_fresh,
    open_report,
    set_clock,
    settle_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def _deliver(api, env, order_id, courier_id, at):
    set_clock(at)
    return complete_delivery(courier_id, order_id)


def _two_late_orders_env(api, merchant_overrides=None, lateness_seconds=700):
    """Two orders promised 01:00:00Z, both completed `lateness_seconds` late
    in one batch (invoice 500 each at surge 1.0)."""
    env = base_chain(merchant_overrides=merchant_overrides)
    m_id = env["merchant"]["id"]
    s_id = env["store"]["id"]
    c_id = env["courier"]["id"]
    o1 = make_order_ready_fresh(m_id, s_id, "sl-1", promised_at="2026-09-01T01:00:00Z")
    o2 = make_order_ready_fresh(
        m_id, s_id, "sl-2", promised_at="2026-09-01T01:00:00Z",
        quote_overrides={"address_text": "11 Dest Rd"},
    )
    batch = batch_orders(s_id, c_id, [o1["id"], o2["id"]])
    dispatch_batch(c_id, batch["id"])
    drive_to_in_transit(c_id, o1["id"])
    drive_to_in_transit(c_id, o2["id"])
    mm, ss = divmod(lateness_seconds, 60)
    at = f"2026-09-01T01:{mm:02d}:{ss:02d}Z"
    o1 = _deliver(api, env, o1["id"], c_id, at)
    o2 = _deliver(api, env, o2["id"], c_id, at)
    env = dict(env)
    env.update({"order1": o1, "order2": o2})
    return env


class TestLateCreditBoundaries:
    def _grace_boundary_env(self, api):
        """Two identical orders promised 01:00:00Z, both IN_TRANSIT in one
        dispatched batch, clock parked at exactly 600s past promised."""
        env = base_chain(merchant_overrides={"late_credit_enabled": False})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(m_id, s_id, "bp-1",
                                    promised_at="2026-09-01T01:00:00Z")
        o2 = make_order_ready_fresh(
            m_id, s_id, "bp-2", promised_at="2026-09-01T01:00:00Z",
            quote_overrides={"address_text": "11 Dest Rd"},
        )
        batch = batch_orders(s_id, c_id, [o1["id"], o2["id"]],
                             window_start="2026-09-01T00:30:00Z",
                             window_end="2026-09-01T02:00:00Z")
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, o1["id"])
        drive_to_in_transit(c_id, o2["id"])
        set_clock("2026-09-01T01:10:00Z")
        return env, o1, o2, c_id

    def test_grace_boundary_exact_600s_vs_601s(self, api):
        """PRD section 3.7: "Lateness up to and including ten minutes (600
        seconds) earns no credit — exactly ten minutes is still on time.
        Lateness beyond ten minutes and up to and including thirty minutes
        (1800 seconds) earns a credit of the `merchant_invoice_cents`
        multiplied by one quarter (25 percent), rounded half up. Lateness
        beyond thirty minutes earns a credit equal to the full
        `merchant_invoice_cents`. The result is stored on the order as
        `late_credit_cents`."

        Design: Difficulty/boundary_precision_check/late_credit_grace_boundary_exact_600s_vs_601s
        """
        env, o1, o2, c_id = self._grace_boundary_env(api)
        m_id = env["merchant"]["id"]

        done1 = complete_delivery(c_id, o1["id"])  # exactly 600s late
        assert done1["late_credit_cents"] == 0

        set_clock("2026-09-01T01:10:01Z")
        done2 = complete_delivery(c_id, o2["id"])  # 601s late
        assert done2["late_credit_cents"] == 125

    def test_grace_boundary_599s_and_601s_flank_the_band(self, api):
        """PRD section 3.7: "Lateness up to and including ten minutes (600
        seconds) earns no credit — exactly ten minutes is still on time.
        Lateness beyond ten minutes and up to and including thirty minutes
        (1800 seconds) earns a credit of the `merchant_invoice_cents`
        multiplied by one quarter (25 percent), rounded half up."

        Design: Difficulty/boundary_precision_check/late_credit_grace_boundary_exact_600s_vs_601s
        """
        env = base_chain(merchant_overrides={"late_credit_enabled": False})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(m_id, s_id, "bp-3",
                                    promised_at="2026-09-01T01:00:00Z")
        o2 = make_order_ready_fresh(
            m_id, s_id, "bp-4", promised_at="2026-09-01T01:00:00Z",
            quote_overrides={"address_text": "11 Dest Rd"},
        )
        batch = batch_orders(s_id, c_id, [o1["id"], o2["id"]],
                             window_start="2026-09-01T00:30:00Z",
                             window_end="2026-09-01T02:00:00Z")
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, o1["id"])
        drive_to_in_transit(c_id, o2["id"])

        set_clock("2026-09-01T01:09:59Z")  # 599s: inside grace
        assert complete_delivery(c_id, o1["id"])["late_credit_cents"] == 0

        set_clock("2026-09-01T01:10:01Z")  # 601s: 25% band
        assert complete_delivery(c_id, o2["id"])["late_credit_cents"] == 125

    def test_full_refund_band_over_1800s(self, api):
        """PRD section 3.7: "Lateness up to and including ten minutes (600
        seconds) earns no credit — exactly ten minutes is still on time.
        Lateness beyond ten minutes and up to and including thirty minutes
        (1800 seconds) earns a credit of the `merchant_invoice_cents`
        multiplied by one quarter (25 percent), rounded half up. Lateness
        beyond thirty minutes earns a credit equal to the full
        `merchant_invoice_cents`."

        Design: Corner/calculations/late_credit_full_refund_band_over_1800s
        """
        env = base_chain(merchant_overrides={"late_credit_enabled": False})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(m_id, s_id, "lf-1",
                                    promised_at="2026-09-01T01:00:00Z")
        o2 = make_order_ready_fresh(
            m_id, s_id, "lf-2", promised_at="2026-09-01T01:00:00Z",
            quote_overrides={"address_text": "11 Dest Rd"},
        )
        batch = batch_orders(s_id, c_id, [o1["id"], o2["id"]],
                             window_start="2026-09-01T00:30:00Z",
                             window_end="2026-09-01T02:00:00Z")
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, o1["id"])
        drive_to_in_transit(c_id, o2["id"])

        set_clock("2026-09-01T01:30:00Z")  # exactly 1800s: still the 25% band
        assert complete_delivery(c_id, o1["id"])["late_credit_cents"] == 125

        set_clock("2026-09-01T01:30:01Z")  # 1801s: full invoice
        assert complete_delivery(c_id, o2["id"])["late_credit_cents"] == 500


class TestReportWindow:
    def test_report_excludes_out_of_window_deliveries(self, api):
        """PRD section 3.9: "A `PlatformAdmin` opens an SLA report for a
        merchant over a half-open period from `period_start` to `period_end`,
        the end strictly after the start; the report begins `OPEN`."
        PRD section 3.9: "The population is the merchant's delivered orders
        whose `delivered_at` falls inside the half-open window;
        `total_deliveries` is its size, and an order counts as late when its
        `delivered_at` is later than its `promised_at` plus the ten-minute
        grace."

        Design: Corner/calculations/sla_report_excludes_out_of_window_deliveries
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        # o1 delivered in-window on time.
        o1 = make_order_ready_fresh(m_id, s_id, "rw-1",
                                    promised_at="2026-09-01T02:00:00Z")
        b1 = batch_orders(s_id, c_id, [o1["id"]])
        dispatch_batch(c_id, b1["id"])
        drive_to_in_transit(c_id, o1["id"])
        _deliver(api, env, o1["id"], c_id, "2026-09-01T01:00:00Z")

        # o2 delivered exactly at period_end 2026-09-02T00:00:00Z: excluded by
        # the half-open window.
        o2 = make_order_ready_fresh(
            m_id, s_id, "rw-2", promised_at="2026-09-02T02:00:00Z",
            quote_overrides={"address_text": "11 Dest Rd"},
        )
        b2 = batch_orders(s_id, c_id, [o2["id"]],
                          window_start="2026-09-01T23:00:00Z",
                          window_end="2026-09-02T00:00:00Z")
        dispatch_batch(c_id, b2["id"])
        drive_to_in_transit(c_id, o2["id"])
        _deliver(api, env, o2["id"], c_id, "2026-09-02T00:00:00Z")

        report = open_report(m_id)
        finalized = finalize_report(report["id"])
        assert finalized["total_deliveries"] == 1
        assert finalized["attainment_rate_gross"] == 1.0


class TestDoubleFinalize:
    def test_report_double_finalize_rejected(self, api):
        """PRD section 3.9: "Finalizing an `OPEN` report (any other state
        yields `ERR_INVALID_STATE`) computes four measures and accrues
        credits."
        PRD section 3.9: "`attainment_rate_gross` is one minus the ratio of
        late to total — defined as 1.0 when there are no deliveries at all."

        Design: Corner/state_machines/report_double_finalize_rejected
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(m_id, s_id, "df-1",
                                    promised_at="2026-09-01T02:00:00Z")
        b1 = batch_orders(s_id, c_id, [o1["id"]])
        dispatch_batch(c_id, b1["id"])
        drive_to_in_transit(c_id, o1["id"])
        _deliver(api, env, o1["id"], c_id, "2026-09-01T01:00:00Z")

        report = open_report(m_id)
        first = finalize_report(report["id"])
        assert first["status"] == "FINALIZED"
        assert first["attainment_rate_gross"] == 1.0

        validate_error(api.finalize_sla_report(report["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)

        credits = list_report_credits(report["id"])
        assert credits == [], "on-time delivery accrues no credits"


class TestGrossVsFaultAdjusted:
    def _sla_three_order_env(self, api):
        """Two late orders (o1 courier fault, o2 merchant fault settled) and
        one on-time order (o3 via a second courier)."""
        env = base_chain(merchant_overrides={"late_credit_enabled": False})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        o1 = make_order_ready_fresh(m_id, s_id, "sla-1",
                                    promised_at="2026-09-01T01:00:00Z")
        o2 = make_order_ready_fresh(
            m_id, s_id, "sla-2", promised_at="2026-09-01T01:00:00Z",
            quote_overrides={"address_text": "11 Dest Rd"},
        )
        o3 = make_order_ready_fresh(
            m_id, s_id, "sla-3", promised_at="2026-09-01T02:00:00Z",
            quote_overrides={"address_text": "12 Dest Rd"},
        )
        b1 = batch_orders(s_id, c_id, [o1["id"], o2["id"]],
                          window_start="2026-09-01T00:30:00Z",
                          window_end="2026-09-01T01:30:00Z")
        dispatch_batch(c_id, b1["id"])
        drive_to_in_transit(c_id, o1["id"])
        drive_to_in_transit(c_id, o2["id"])
        set_clock("2026-09-01T01:11:40Z")  # 700s late
        complete_delivery(c_id, o1["id"])
        complete_delivery(c_id, o2["id"])

        courier2 = add_courier(name="SLA Courier 2")
        b2 = batch_orders(s_id, courier2["id"], [o3["id"]],
                          window_start="2026-09-01T01:00:00Z",
                          window_end="2026-09-01T02:00:00Z")
        dispatch_batch(courier2["id"], b2["id"])
        drive_to_in_transit(courier2["id"], o3["id"])
        set_clock("2026-09-01T01:40:00Z")  # on time for promised 02:00
        complete_delivery(courier2["id"], o3["id"])

        # Settle a MERCHANT_FULFILLMENT claim on o2.
        claim = decide_claim(
            file_claim(m_id, o2["id"], "MERCHANT_FULFILLMENT", 500)["id"], "APPROVE"
        )
        settle_claim(claim["id"])

        report = open_report(m_id)
        env = dict(env)
        env.update({"o1": o1, "o2": o2, "o3": o3, "report": report,
                    "courier2": courier2})
        return env

    def test_gross_counts_all_late_fault_adjusted_excludes_merchant_fault(self, api):
        """PRD section 3.9: "`late_deliveries_gross` counts every late order
        regardless of fault, and `attainment_rate_gross` is one minus the
        ratio of late to total — defined as 1.0 when there are no deliveries
        at all. The `attainment_rate_fault_adjusted` variant excludes from
        both the numerator and the denominator any late order that carries a
        `SETTLED` refund claim whose `fault_code` is `MERCHANT_FULFILLMENT`,
        so identical data can yield a higher fault-adjusted rate than the
        gross one; it is likewise 1.0 when its adjusted population is empty.
        Both rates are stored rounded half up to four decimal places."
        PRD section 3.9: "Credits accrue when the gross attainment falls below
        97 percent: one service credit per late order in the gross population,
        each copying that order's `late_credit_cents` as its `amount_cents`"

        Design: Difficulty/dual_variant_calc/sla_attainment_gross_vs_fault_adjusted
        """
        env = self._sla_three_order_env(api)
        m_id = env["merchant"]["id"]

        report = finalize_report(env["report"]["id"])
        assert report["total_deliveries"] == 3
        assert report["late_deliveries_gross"] == 2
        assert report["attainment_rate_gross"] == pytest.approx(0.3333, abs=1e-6)
        assert report["attainment_rate_fault_adjusted"] == pytest.approx(0.5, abs=1e-6)
        assert (
            report["attainment_rate_fault_adjusted"] != report["attainment_rate_gross"]
        )

        credits = list_report_credits(env["report"]["id"])
        assert len(credits) == 2, "credits are keyed to the GROSS late population"
        assert all(c["amount_cents"] == 125 for c in credits)
        assert all(c["status"] == "ACCRUED" for c in credits)

        # late_credit_enabled is False: no auto-apply.
        assert get_merchant(m_id)["credit_balance_cents"] == 0

    def test_rates_rounded_to_four_decimal_places(self, api):
        """PRD section 2.7: "Attainment rates on SLA reports are the one
        non-integer quantity in the system: they are stored as decimals
        rounded half up to four decimal places."
        PRD section 3.9: "The `attainment_rate_fault_adjusted` variant
        excludes from both the numerator and the denominator any late order
        that carries a `SETTLED` refund claim whose `fault_code` is
        `MERCHANT_FULFILLMENT`"

        Design: Difficulty/dual_variant_calc/sla_attainment_gross_vs_fault_adjusted
        """
        env = self._sla_three_order_env(api)
        report = finalize_report(env["report"]["id"])

        gross = report["attainment_rate_gross"]
        adjusted = report["attainment_rate_fault_adjusted"]
        for rate in (gross, adjusted):
            assert round(rate, 4) == rate, "rates are stored rounded to 4 places"
        # 1 - 2/3 = 0.33333... must round to 0.3333, not truncate to 0.3333
        # via floor nor float-splat to 0.3333333333.
        assert gross == pytest.approx(0.3333, abs=1e-9)
        assert adjusted == pytest.approx(0.5, abs=1e-9)
        # The fault-adjusted rate is higher than gross on identical data.
        assert adjusted > gross


class TestFinalizeCascade:
    def test_finalize_cascade_to_credit_auto_apply_and_merchant_balance(self, api):
        """PRD section 3.9: "Credits accrue when the gross attainment falls
        below 97 percent: one service credit per late order in the gross
        population, each copying that order's `late_credit_cents` as its
        `amount_cents`, stamped with the `reason` `LATE_DELIVERY`, linked to
        the report through `sla_report_id` and to the order through
        `delivery_order_id`, and starting `ACCRUED`. When the merchant's
        `late_credit_enabled` flag is set, finalization immediately applies
        each new credit: the credit moves to `APPLIED` and the merchant's
        `credit_balance_cents` grows by the credit's amount."

        Design: Difficulty/transitive_cascade/report_finalize_cascade_to_credit_auto_apply_and_merchant_balance
        """
        env = base_chain()  # late_credit_enabled defaults to True
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        o1 = make_order_ready_fresh(m_id, s_id, "rc-1",
                                    promised_at="2026-09-01T01:00:00Z")
        batch = batch_orders(s_id, c_id, [o1["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, o1["id"])
        set_clock("2026-09-01T01:11:40Z")  # 700s late -> 25% of 500 = 125
        done = complete_delivery(c_id, o1["id"])
        assert done["late_credit_cents"] == 125

        report = open_report(m_id)
        finalize_report(report["id"])

        credits = list_report_credits(report["id"])
        assert len(credits) == 1
        credit = credits[0]
        assert credit["amount_cents"] == 125
        assert credit["delivery_order_id"] == o1["id"]
        assert credit["sla_report_id"] == report["id"]
        assert credit["status"] == "APPLIED", (
            "late_credit_enabled true: auto-applied with no manual apply call"
        )

        assert get_merchant(m_id)["credit_balance_cents"] == 125

    def test_no_auto_apply_when_late_credit_disabled(self, api):
        """PRD section 3.9: "Otherwise the credit waits in `ACCRUED` until a
        `PlatformAdmin` applies it — which adds `amount_cents` to the
        merchant's `credit_balance_cents` — or voids it, which moves it to
        `VOIDED` with no balance effect."
        PRD section 3.1: "the credit balance is the running sum of
        `amount_cents` across the merchant's service credits in `APPLIED`
        status, excluding any in `VOIDED`."

        Design: Difficulty/transitive_cascade/report_finalize_cascade_to_credit_auto_apply_and_merchant_balance
        """
        env = base_chain(merchant_overrides={"late_credit_enabled": False})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        o1 = make_order_ready_fresh(m_id, s_id, "rc-2",
                                    promised_at="2026-09-01T01:00:00Z")
        batch = batch_orders(s_id, c_id, [o1["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, o1["id"])
        set_clock("2026-09-01T01:11:40Z")
        complete_delivery(c_id, o1["id"])

        report = open_report(m_id)
        finalize_report(report["id"])

        credits = list_report_credits(report["id"])
        assert len(credits) == 1
        assert credits[0]["status"] == "ACCRUED", (
            "late_credit_enabled false: the credit waits in ACCRUED"
        )
        assert get_merchant(m_id)["credit_balance_cents"] == 0

        applied = validate_success(
            api.apply_service_credit(credits[0]["id"], admin_headers())
        )
        assert applied["status"] == "APPLIED"
        assert get_merchant(m_id)["credit_balance_cents"] == 125


class TestCreditLedgerConservation:
    def test_apply_void_credit_balance_conservation(self, api):
        """PRD section 3.1: "the credit balance is the running sum of
        `amount_cents` across the merchant's service credits in `APPLIED`
        status, excluding any in `VOIDED`."
        PRD section 3.9: "Otherwise the credit waits in `ACCRUED` until a
        `PlatformAdmin` applies it — which adds `amount_cents` to the
        merchant's `credit_balance_cents` — or voids it, which moves it to
        `VOIDED` with no balance effect. Both apply and void require the
        credit to be `ACCRUED`, else `ERR_INVALID_STATE`; `APPLIED` and
        `VOIDED` are terminal."

        Design: Difficulty/compensating_invariant/apply_void_credit_balance_conservation
        """
        env = _two_late_orders_env(
            api, merchant_overrides={"late_credit_enabled": False}
        )
        m_id = env["merchant"]["id"]
        report = open_report(m_id)
        finalize_report(report["id"])

        credits = list_report_credits(report["id"])
        assert len(credits) == 2
        assert all(c["status"] == "ACCRUED" for c in credits)
        assert get_merchant(m_id)["credit_balance_cents"] == 0

        validate_success(api.apply_service_credit(credits[0]["id"], admin_headers()))
        assert get_merchant(m_id)["credit_balance_cents"] == 125

        validate_success(api.void_service_credit(credits[1]["id"], admin_headers()))
        # A voided-before-apply credit contributes exactly 0 to the balance.
        assert get_merchant(m_id)["credit_balance_cents"] == 125

        c1 = validate_success(api.get_service_credit(credits[0]["id"], admin_headers()))
        c2 = validate_success(api.get_service_credit(credits[1]["id"], admin_headers()))
        assert c1["status"] == "APPLIED"
        assert c2["status"] == "VOIDED"

        # Ledger identity: balance == sum of APPLIED amounts.
        applied_sum = sum(
            c["amount_cents"] for c in (c1, c2) if c["status"] == "APPLIED"
        )
        assert get_merchant(m_id)["credit_balance_cents"] == applied_sum == 125

    def test_apply_and_void_require_accrued_state(self, api):
        """PRD section 3.9: "Both apply and void require the credit to be
        `ACCRUED`, else `ERR_INVALID_STATE`; `APPLIED` and `VOIDED` are
        terminal."

        Design: Difficulty/compensating_invariant/apply_void_credit_balance_conservation
        """
        env = _two_late_orders_env(
            api, merchant_overrides={"late_credit_enabled": False}
        )
        m_id = env["merchant"]["id"]
        report = open_report(m_id)
        finalize_report(report["id"])
        credits = list_report_credits(report["id"])
        assert len(credits) == 2

        validate_success(api.apply_service_credit(credits[0]["id"], admin_headers()))
        validate_success(api.void_service_credit(credits[1]["id"], admin_headers()))

        # Terminal credits reject both further transitions.
        validate_error(api.apply_service_credit(credits[0]["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.void_service_credit(credits[0]["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.apply_service_credit(credits[1]["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.void_service_credit(credits[1]["id"], admin_headers()),
                       ApiErrorId.ERR_INVALID_STATE)

        # No double-counting anywhere in the ledger.
        assert get_merchant(m_id)["credit_balance_cents"] == 125
