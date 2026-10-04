"""Compensating invariants: appeal overturn restores reliability; settle+void conserves liability."""

from test_helpers import (
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    warmup_clean_completion,
    accept_block,
    deactivate_driver,
    submit_appeal,
    submit_evidence,
    decide_appeal,
    get_driver,
    get_station,
    list_driver_assignments,
    complete_block_flow,
    settle_pay_statement,
    void_pay_statement,
)


class TestAppealOverturnRestoresReliability:
    def test_deactivation_then_overturned_appeal_restores_reliability(self, api):
        """PRD §3.8: "Deciding `OVERTURNED` reinstates the driver from `DEACTIVATED` to
        `ACTIVE`, and with it reverses the deactivation strikes: every assignment
        forfeited with `forfeit_cause` `SYSTEM_DEACTIVATION` and not already reversed
        has `strike_reversed` set to true, so those strikes stop counting, after which
        reliability and tier are recomputed per §2.8."
        PRD §2.8: "it starts at 10000 when the driver registers, each non-reversed
        forfeiture within the last 30 days subtracts 500 basis points, each non-reversed
        no-show within the last 30 days subtracts 1000 basis points, and the score never
        falls below 0."

        Design: Difficulty/compensating_invariant/deactivation_then_overturned_appeal_restores_reliability
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        warmup_clean_completion(station, driver, vehicle)

        bx = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:00:00Z",
            ends_at="2026-09-01T14:00:00Z",
            base_pay_cents=4000,
        )
        by = create_published_block(
            station["id"],
            starts_at="2026-09-01T14:00:00Z",
            ends_at="2026-09-01T16:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        ax = accept_block(bx["id"], driver["id"], vehicle["id"])
        ay = accept_block(by["id"], driver["id"], vehicle["id"])

        pre = get_driver(driver["id"])
        assert pre["reliability_score_bp"] == 10000
        assert pre["rating_tier"] == "PREMIER"

        deactivate_driver(driver["id"], reason="fraud investigation")
        mid = get_driver(driver["id"])
        assert mid["reliability_score_bp"] == 9000
        assert mid["rating_tier"] == "PLUS"

        appeal = submit_appeal(driver["id"], reason="incorrect deactivation")
        submit_evidence(appeal["id"], driver["id"], note="station CCTV exonerates driver")
        decide_appeal(appeal["id"], "OVERTURNED", reason="evidence conclusive")

        post = get_driver(driver["id"])
        # Forward + compensating action conserve reliability exactly.
        assert post["reliability_score_bp"] == 10000
        assert post["rating_tier"] == "PREMIER"
        assert post["status"] == "ACTIVE"

        forfeited = list_driver_assignments(driver["id"], params={"status": "FORFEITED"})
        assert len(forfeited) == 2
        for row in forfeited:
            assert row["strike_reversed"] is True
            assert row["forfeit_cause"] == "SYSTEM_DEACTIVATION"

    def test_overturn_reverses_only_deactivation_strikes(self, api):
        """PRD §3.8: "Deciding `OVERTURNED` reinstates the driver from `DEACTIVATED` to
        `ACTIVE`, and with it reverses the deactivation strikes: every assignment
        forfeited with `forfeit_cause` `SYSTEM_DEACTIVATION` and not already reversed
        has `strike_reversed` set to true, so those strikes stop counting, after which
        reliability and tier are recomputed per §2.8. Reinstatement does not resurrect
        history — revoked offers are not restored, and expired or forfeited blocks stay
        as they are."

        Design: Difficulty/compensating_invariant/deactivation_then_overturned_appeal_restores_reliability
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        warmup_clean_completion(station, driver, vehicle)

        # One driver-initiated forfeit (NOT a deactivation strike) at 08:00.
        bf = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:00:00Z",
            ends_at="2026-09-01T14:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        from test_helpers import forfeit

        af = accept_block(bf["id"], driver["id"], vehicle["id"])
        forfeit(af["id"], driver["id"])

        # One further assignment that will be forfeited via deactivation.
        bx = create_published_block(
            station["id"],
            starts_at="2026-09-01T14:00:00Z",
            ends_at="2026-09-01T16:00:00Z",
            base_pay_cents=4000,
        )
        ax = accept_block(bx["id"], driver["id"], vehicle["id"])

        deactivate_driver(driver["id"], reason="fraud investigation")
        mid = get_driver(driver["id"])
        assert mid["reliability_score_bp"] == 9000  # 10000 - 500 (driver) - 500 (system)

        appeal = submit_appeal(driver["id"], reason="incorrect deactivation")
        submit_evidence(appeal["id"], driver["id"], note="station CCTV exonerates driver")
        decide_appeal(appeal["id"], "OVERTURNED", reason="evidence conclusive")

        post = get_driver(driver["id"])
        # Only the SYSTEM_DEACTIVATION strike is reversed; the driver-initiated
        # forfeit keeps counting.
        assert post["reliability_score_bp"] == 9500
        assert post["status"] == "ACTIVE"

        forfeited = list_driver_assignments(driver["id"], params={"status": "FORFEITED"})
        by_cause = {row["forfeit_cause"]: row for row in forfeited}
        assert by_cause["SYSTEM_DEACTIVATION"]["strike_reversed"] is True
        assert by_cause["DRIVER_INITIATED"]["strike_reversed"] is False


class TestSettleVoidConservesLiabilities:
    def test_settle_then_void_conserves_station_pay_liabilities(self, api):
        """PRD §3.6: "A `PlatformAdmin` settles an `OPEN` statement, stamping
        `settled_at` and moving it to `SETTLED`; settling adds the statement's
        `final_pay_cents` to the station's `pay_liabilities_cents`, which is defined as
        the sum of `final_pay_cents` over all `SETTLED` statements belonging to that
        station's blocks — `OPEN` and `VOIDED` statements are excluded. A settled
        statement can later be voided, stamping `voided_at` and moving it to `VOIDED`,
        which removes its amount from the station liability again; a settle followed by
        a void leaves the liability unchanged."

        Design: Difficulty/compensating_invariant/settle_then_void_conserves_station_pay_liabilities
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        # Warm-up block: STANDARD at accept, no surge, one on-time compliant 1.0kg
        # package => final = 4000 + 0 + 155 - 0 = 4155.
        _b, _a, ps, _pkgs = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            package_specs=[
                {
                    "tracking_code": "PW-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T02:30:00Z",
                }
            ],
        )
        assert ps["final_pay_cents"] == 4155
        assert ps["status"] == "OPEN"
        assert get_station(station["id"])["pay_liabilities_cents"] == 0

        settled = settle_pay_statement(ps["id"])
        assert settled["status"] == "SETTLED"
        assert get_station(station["id"])["pay_liabilities_cents"] == 4155

        voided = void_pay_statement(ps["id"])
        assert voided["status"] == "VOIDED"
        assert get_station(station["id"])["pay_liabilities_cents"] == 0

    def test_settle_adds_exactly_final_pay_to_liabilities(self, api):
        """PRD §3.6: "settling adds the statement's `final_pay_cents` to the station's
        `pay_liabilities_cents`, which is defined as the sum of `final_pay_cents` over
        all `SETTLED` statements belonging to that station's blocks — `OPEN` and
        `VOIDED` statements are excluded."

        Design: Difficulty/compensating_invariant/settle_then_void_conserves_station_pay_liabilities
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        _b, _a, ps, _pkgs = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            package_specs=[
                {
                    "tracking_code": "PW-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T02:30:00Z",
                }
            ],
        )
        settle_pay_statement(ps["id"])
        assert get_station(station["id"])["pay_liabilities_cents"] == ps["final_pay_cents"]
