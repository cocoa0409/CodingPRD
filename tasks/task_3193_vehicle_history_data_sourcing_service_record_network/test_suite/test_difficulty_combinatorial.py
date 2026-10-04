"""Depth tests: combinatorial formulas — multi-input accident confidence and the
pinned counter-last evaluation order of dealer report pricing."""

from test_helpers import (
    VIN_A,
    advance_epoch,
    create_dealer,
    get_dealer,
    make_dealer_agent_headers,
    purchase_dealer_report,
    purchase_n_dealer_reports,
    register_source,
    set_clock,
    setup_network,
    subscribe_dealer,
    submit_record,
    submit_title,
    validate_success,
)


class TestAccidentConfidenceMultiInput:
    def test_cumulative_corroboration_scores_40_60_80(self, api, admin_headers):
        """PRD §3.5: "Records in that agreeing set submitted by sources of the same `source_type` as this record's source contribute a same-type bonus of 10 points each, capped at two contributing records for a maximum of 20 points. Records in that set from sources of a different `source_type` contribute a cross-type bonus of 20 points each, likewise capped at two contributing records for a maximum of 40 points. The base of 40 plus both bonuses is then multiplied by the submitting source's `reliability_score` divided by 100"

        Design: Difficulty/combinatorial_formula/accident_confidence_multi_input_nonlinear
        """
        setup_network(api)
        mva = register_source(api, source_type="MVA")
        ins = register_source(api, source_type="INSURER")
        auc = register_source(api, source_type="AUCTION")

        first = submit_record(
            api, mva["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=5, payload_ref="a1", idempotency_key="k-a1",
        )
        assert first["confidence_score"] == 40, (
            f"base only, no corroborators at ingest: expected 40, got {first['confidence_score']}"
        )

        second = submit_record(
            api, ins["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=5, payload_ref="a2", idempotency_key="k-a2",
        )
        assert second["confidence_score"] == 60, (
            f"one cross-type corroborator (+20): expected 60, got {second['confidence_score']}"
        )

        third = submit_record(
            api, auc["id"], record_type="ACCIDENT", event_date="2026-09-01",
            damage_severity=5, payload_ref="a3", idempotency_key="k-a3",
        )
        assert third["confidence_score"] == 80, (
            f"two cross-type corroborators (+40): expected 80, got {third['confidence_score']}"
        )

    def test_same_and_cross_type_caps_cross_high_boundary(self, api, admin_headers):
        """PRD §3.5: "`HIGH` when the score is at least 85, `MEDIUM` when at least 70, `LOW` when at least 40, and `UNRELIABLE` below 40."
        PRD §3.5: "Records in that agreeing set submitted by sources of the same `source_type` as this record's source contribute a same-type bonus of 10 points each, capped at two contributing records for a maximum of 20 points."

        Design: Difficulty/combinatorial_formula/accident_confidence_multi_input_nonlinear
        """
        setup_network(api)
        mva = register_source(api, source_type="MVA")
        # A second MVA source: the agreeing set only admits records "submitted by a
        # different source" (PRD §3.5), so the same-type corroborator must come from
        # a distinct source of the same type.
        mva2 = register_source(api, source_type="MVA")
        ins = register_source(api, source_type="INSURER")
        auc = register_source(api, source_type="AUCTION")

        for source, ref in ((mva2, "a1"), (ins, "a2"), (auc, "a3")):
            submit_record(
                api, source["id"], record_type="ACCIDENT", event_date="2026-09-01",
                damage_severity=5, payload_ref=ref, idempotency_key=f"k-{ref}",
            )
        # Fourth record from the first MVA source on the next day: 1 same-type
        # (mva2) plus 2 cross-type (INSURER, AUCTION) corroborators. The clock
        # must advance to 2026-09-02 first — a future event_date is rejected.
        set_clock(api, "2026-09-02T00:00:00Z")
        fourth = submit_record(
            api, mva["id"], record_type="ACCIDENT", event_date="2026-09-02",
            damage_severity=3, payload_ref="a4", idempotency_key="k-a4",
        )
        assert fourth["confidence_score"] == 90, (
            f"40 + 10*min(2,1) + 20*min(2,2) = 90, got {fourth['confidence_score']}"
        )
        assert fourth["confidence_level"] == "HIGH", (
            f"90 >= 85 must be HIGH, got {fourth['confidence_level']}"
        )
        # The third record (80) sits in the MEDIUM band, proving the boundary was crossed.
        assert 70 <= 80 < 85 and fourth["confidence_score"] >= 85


class TestReportPriceCounterLastOrder:
    def test_first_overage_block_priced_against_pre_increment_counter(self, api, admin_headers):
        """PRD §3.11: "Pricing follows a pinned evaluation order: determine eligibility, then compute included-versus-overage position, then compute the tiered overage price, then apply the floor, then debit the ledger, and only then increment the usage counter — so the current order is always priced against the pre-increment counter."
        PRD §3.11: "Within a valid window, the first tranche of reports is included in the subscription — 25 reports for `STANDARD`, 200 for `PRO` — and costs 0 cents while `period_reports_used` is below the included count."

        Design: Difficulty/combinatorial_formula/report_price_counter_last_evaluation_order
        """
        network, dealer, vehicle_id = _setup_subscribed_dealer_with_vehicle(api)
        orders = purchase_n_dealer_reports(api, dealer["id"], vehicle_id, 25)
        assert all(order["price_cents"] == 0 for order in orders), (
            "the first 25 STANDARD reports must be included (0 cents)"
        )
        for i in range(10):
            order = purchase_dealer_report(api, dealer["id"], vehicle_id)
            assert order["price_cents"] == 500, (
                f"overage unit {i + 1} must cost 500c (pre-increment counter), got {order['price_cents']}"
            )
        dealer_after = get_dealer(api, dealer["id"])
        assert dealer_after["period_reports_used"] == 35
        assert dealer_after["invoice_balance_cents"] == 5000

    def test_overage_unit_eleven_steps_down_and_debits_ledger(self, api, admin_headers):
        """PRD §3.11: "Beyond the included count, each report is an overage unit priced on a declining tier: the first ten overage reports (overage units 1 through 10) cost 500 cents each, the next ten (units 11 through 20) cost 400 cents each, the tier stepping down by 100 cents for every further block of ten overage units, subject to a floor of 300 cents per report below which the price never falls."
        PRD §3.11: "Every overage charge accrues to the dealer's `invoice_balance_cents`, and `period_reports_used` increments by one with each dealer-subscription purchase"

        Design: Difficulty/combinatorial_formula/report_price_counter_last_evaluation_order
        """
        network, dealer, vehicle_id = _setup_subscribed_dealer_with_vehicle(api)
        purchase_n_dealer_reports(api, dealer["id"], vehicle_id, 35)
        order36 = purchase_dealer_report(api, dealer["id"], vehicle_id)
        # Overage unit 11: 500 - 100 * ((11 - 1) // 10) = 400.
        assert order36["price_cents"] == 400, (
            f"11th overage unit must cost 400c, got {order36['price_cents']}"
        )
        dealer_after = get_dealer(api, dealer["id"])
        assert dealer_after["period_reports_used"] == 36
        # 10 * 500 + 1 * 400 debited over the 11 overage orders.
        assert dealer_after["invoice_balance_cents"] == 5400, (
            f"invoice must be 5400c, got {dealer_after['invoice_balance_cents']}"
        )


def _setup_subscribed_dealer_with_vehicle(api):
    """Network + MVA source + CLEAN-titled vehicle + STANDARD-subscribed dealer."""
    from test_helpers import setup_network_with_source, VIN_A as _VIN
    from test_helpers import create_dealer as _cd, subscribe_dealer as _sd

    network, source = setup_network_with_source(api)
    title = submit_title(api, source["id"], _VIN, "CA", "clean", idempotency_key="k-t1", payload_ref="t1")
    dealer = _cd(api)
    _sd(api, dealer["id"], tier="STANDARD")
    return network, dealer, title["vehicle_id"]
