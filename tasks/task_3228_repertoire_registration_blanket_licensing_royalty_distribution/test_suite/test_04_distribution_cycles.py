"""Distribution cycles: pool formation, allocation, statements, distribution."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_publisher_headers,
    make_songwriter_headers,
    make_licensee_headers,
    validate_error,
    validate_success,
    create_performance_payload,
    create_cycle_payload,
    create_publisher_affiliate,
    setup_performance_ready,
    setup_with_performance,
    setup_distributed_cycle,
    setup_calculating_cycle,
    _create_work,
    _create_claim,
    _confirm_work,
    _create_licensee,
    _issue_license,
    _ingest_performance,
    _create_cycle,
    _close_collection,
    _list_cycle_statements,
)

REGISTRAR = TEST_USERS["pro_registrar_headers"]
LIC_ADMIN = TEST_USERS["pro_licensing_admin_headers"]
DISTRIBUTOR = TEST_USERS["royalty_distributor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
SYSADMIN = TEST_USERS["pro_system_admin_headers"]


class TestDifficultyPoolTruncationOrder:
    def test_truncate_per_license_before_summing(self, api):
        """PRD §3.8: "Every license whose covered window from effective_date through
        expiry_date intersects the cycle's period — meaning the effective date falls on
        or before period_end and the expiry date falls on or after period_start — and
        whose status is anything other than TERMINATED contributes its pinned
        fee_basis_cents, prorated: the license contributes its basis multiplied by the
        number of covered days in the intersection (counting both endpoints of the
        overlap inclusively) divided by 365, with the per-license result truncated to an
        integer before any summing."
        PRD §3.8: "The truncated per-license amounts are summed into a gross pool, the
        administration deduct of 15 percent is removed, and the remainder is rounded
        half-up once to whole cents."

        Design: Difficulty/combinatorial_formula/pool_proration_truncation_order
        """
        # Move the logical clock inside the license window before any lazy expiry
        # evaluation (the boot clock is 2026-09-01, past the window's expiry_date).
        validate_success(api.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, SYSADMIN))
        ctx = setup_performance_ready(
            license_overrides={"effective_date": "2026-01-01", "expiry_date": "2026-07-01"}
        )
        event = _ingest_performance(
            ctx["work"]["id"], ctx["license"]["id"], performance_date="2026-02-01",
            play_count=100,
        )
        cycle = _create_cycle(label="2026FULL", period_start="2026-01-01", period_end="2026-12-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        closed = _close_collection(cycle["id"])
        # int(4_800_000_000 * 182 / 365) = 2_393_424_657 (truncated);
        # round_half_up(2_393_424_657 * 0.85) = 2_034_110_958
        assert closed["pool_amount_cents"] == 2034410958

    def test_per_license_truncation_not_rounding(self, api):
        """PRD §3.8: "the license contributes its basis multiplied by the number of
        covered days in the intersection (counting both endpoints of the overlap
        inclusively) divided by 365, with the per-license result truncated to an integer
        before any summing."
        PRD §3.8: "The truncated per-license amounts are summed into a gross pool, the
        administration deduct of 15 percent is removed, and the remainder is rounded
        half-up once to whole cents. The evaluation order is pinned — prorate each
        license, truncate each license, sum, apply the administration rate, round once."

        Design: Difficulty/combinatorial_formula/pool_proration_truncation_order
        """
        # 2026-01-01..2026-06-30 is 181 days: int(4800000000*181/365) = 2_380_273_972
        # (truncated, not 2_380_273_973 rounded); * 0.85 = 2_023_232_876.2 -> 2_023_232_876
        # Move the logical clock inside the license window before any lazy expiry
        # evaluation (the boot clock is 2026-09-01, past the window's expiry_date).
        validate_success(api.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, SYSADMIN))
        ctx = setup_performance_ready(
            license_overrides={"effective_date": "2026-01-01", "expiry_date": "2026-06-30"}
        )
        event = _ingest_performance(
            ctx["work"]["id"], ctx["license"]["id"], performance_date="2026-02-01", play_count=100
        )
        cycle = _create_cycle(label="HALF", period_start="2026-01-01", period_end="2026-12-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]],}, DISTRIBUTOR
            )
        )
        closed = _close_collection(cycle["id"])
        assert closed["pool_amount_cents"] == 2023232876


class TestDifficultyPoolPartialIntersection:
    def test_license_covering_90_of_365_days_contributes_prorated(self, api):
        """PRD §3.8: "Every license whose covered window from effective_date through
        expiry_date intersects the cycle's period — meaning the effective date falls on
        or before period_end and the expiry date falls on or after period_start — and
        whose status is anything other than TERMINATED contributes its pinned
        fee_basis_cents, prorated: the license contributes its basis multiplied by the
        number of covered days in the intersection (counting both endpoints of the
        overlap inclusively) divided by 365, with the per-license result truncated to an
        integer before any summing."

        Design: Difficulty/resource_temporal_overlap/pool_proration_partial_period_intersection
        """
        # Move the logical clock inside the license window before any lazy expiry
        # evaluation (the boot clock is 2026-09-01, past the window's expiry_date).
        validate_success(api.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, SYSADMIN))
        ctx = setup_performance_ready(
            license_overrides={"effective_date": "2026-01-01", "expiry_date": "2026-03-31"}
        )
        event = _ingest_performance(
            ctx["work"]["id"], ctx["license"]["id"], performance_date="2026-02-01", play_count=100
        )
        cycle = _create_cycle(label="Q-FULL", period_start="2026-01-01", period_end="2026-12-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        closed = _close_collection(cycle["id"])
        # int(4_800_000_000 * 90 / 365) = 1_183_561_643; * 0.85 = 1_006_027_396.55 -> 1_006_027_397
        assert closed["pool_amount_cents"] == 1006027397

    def test_terminated_license_contributes_nothing(self, api):
        """PRD §3.8: "Every license whose covered window from effective_date through
        expiry_date intersects the cycle's period — meaning the effective date falls on
        or before period_end and the expiry date falls on or after period_start — and
        whose status is anything other than TERMINATED contributes its pinned
        fee_basis_cents, prorated".

        Design: Difficulty/resource_temporal_overlap/pool_proration_partial_period_intersection
        """
        # Move the logical clock inside the license window before any lazy expiry
        # evaluation (the boot clock is 2026-09-01, past the window's expiry_date).
        validate_success(api.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, SYSADMIN))
        ctx = setup_performance_ready(
            license_overrides={"effective_date": "2026-01-01", "expiry_date": "2026-03-31"}
        )
        event = _ingest_performance(
            ctx["work"]["id"], ctx["license"]["id"], performance_date="2026-02-01", play_count=100
        )
        # A second licensee whose license is TERMINATED before the close: contributes 0.
        other = _create_licensee(legal_name="Gone Net")
        other_license = _issue_license(
            other, effective_date="2026-01-01", expiry_date="2026-03-31"
        )
        validate_success(api.terminate_license(other_license["id"], LIC_ADMIN))

        cycle = _create_cycle(label="Q-TERM", period_start="2026-01-01", period_end="2026-12-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        closed = _close_collection(cycle["id"])
        # Only the surviving license contributes: same prorated amount as the single case.
        assert closed["pool_amount_cents"] == 1006027397


class TestDifficultyResidueReconciliation:
    def _build_two_work_scenario(self, api):
        # Distinct created_at per affiliate (clock advanced between creations) so the
        # PRD's residue tie-break (rounded amount desc, affiliate created_at asc) is
        # deterministic.
        validate_success(api.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"}, SYSADMIN))
        writer_x = create_publisher_affiliate(legal_name="Writer X", affiliation_code="WRX",
                                              party_type="SONGWRITER")
        validate_success(api.set_clock({"to_iso8601": "2026-01-02T00:00:00Z"}, SYSADMIN))
        pub_x = create_publisher_affiliate(legal_name="Pub X", affiliation_code="PUBX")
        validate_success(api.set_clock({"to_iso8601": "2026-01-03T00:00:00Z"}, SYSADMIN))
        pub_y = create_publisher_affiliate(legal_name="Pub Y", affiliation_code="PUBY")
        work_x = _create_work(pub_x["id"], title="Song X")
        work_y = _create_work(pub_y["id"], title="Song Y")
        _create_claim(work_x["id"], writer_x["id"], "WRITER", 5000)
        _create_claim(work_x["id"], pub_x["id"], "PUBLISHER", 5000)
        _create_claim(work_y["id"], pub_y["id"], "PUBLISHER", 10000)
        _confirm_work(work_x["id"])
        _confirm_work(work_y["id"])
        licensee = _create_licensee(legal_name="Net B")
        license_ = _issue_license(licensee)
        ev_x = _ingest_performance(
            work_x["id"], license_["id"], performance_date="2026-02-01", play_count=400
        )
        ev_y = _ingest_performance(
            work_y["id"], license_["id"], performance_date="2026-02-02",
            medium="NETWORK_TV", daypart="PRIME", play_count=40,
        )
        cycle = _create_cycle(label="2026Q1", period_start="2026-01-01", period_end="2026-03-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [ev_x["id"], ev_y["id"]]}, DISTRIBUTOR
            )
        )
        # Suspend pub_x so its share routes to the unclaimed pool.
        validate_success(api.update_affiliate(pub_x["id"], {"status": "SUSPENDED"}, REGISTRAR))
        closed = _close_collection(cycle["id"])
        statements = _list_cycle_statements(closed["id"])
        pool = validate_success(api.get_cycle_pool(closed["id"], DISTRIBUTOR))
        return {
            "writer_x": writer_x, "pub_x": pub_x, "pub_y": pub_y,
            "cycle": closed, "statements": statements, "pool": pool,
        }

    def test_residue_reconciles_rounded_sum_to_pool(self, api):
        """PRD §3.8: "Each affiliate's per-work amount is rounded half-up to cents, and
        the cycle-level rounding residue — the pool minus the sum of all rounded amounts
        — is reconciled cent by cent: a positive residue is awarded one cent at a time
        to statements ordered by rounded amount descending and then by the affiliate's
        created_at ascending, and a negative residue is clawed back one cent at a time
        from statements in that same order, so the largest statements absorb rounding
        drift in both directions."
        PRD §3.8: "An affiliate whose status is not ACTIVE still has a statement created
        recording its gross, but the entire gross is recorded as unclaimed_amount_cents
        and the same cents credit the cycle's unclaimed pool rather than the affiliate."

        Design: Difficulty/combinatorial_formula/allocation_circular_residue_resolution
        """
        ctx = self._build_two_work_scenario(api)
        cycle, statements, pool = ctx["cycle"], ctx["statements"], ctx["pool"]
        # Pool: int(4_800_000_000 * 90/365) * 0.85 rounded once = 1_006_027_397.
        assert cycle["pool_amount_cents"] == 1006027397

        by_affiliate = {s["affiliate_id"]: s for s in statements}
        st_wx = by_affiliate[ctx["writer_x"]["id"]]
        st_px = by_affiliate[ctx["pub_x"]["id"]]
        st_py = by_affiliate[ctx["pub_y"]["id"]]
        # work X: credit 400.0 split 5000/5000; work Y: credit 200.0. Unit value
        # pool/600; every statement rounds half-up to 335_342_466, leaving a -1 residue
        # clawed from the tied statements by affiliate created_at order (writer_x is
        # earliest).
        assert st_wx["gross_amount_cents"] == 335342465
        assert st_py["gross_amount_cents"] == 335342466
        # SUSPENDED pub_x: whole gross routed to the pool.
        assert st_px["unclaimed_amount_cents"] == 335342466
        assert pool["balance_cents"] == 335342466
        # Reconciliation closes the circle.
        total = sum(s["gross_amount_cents"] for s in statements)
        assert total == cycle["pool_amount_cents"]

    def test_unclaimed_portion_carries_no_admin_fee(self, api):
        """PRD §3.8: "The administration fee never touches the unclaimed portion: pool
        credits are gross cents, and each statement's admin_fee_cents is computed only
        on the payable remainder."
        PRD §3.8: "The per-statement administration fee is 5 percent of the payable
        amount — the gross_amount_cents minus the unclaimed_amount_cents — rounded
        half-up to whole cents, and capped so the fee never exceeds the payable amount
        itself; a statement whose payable amount is zero carries a zero fee."

        Design: Difficulty/combinatorial_formula/allocation_circular_residue_resolution
        """
        ctx = self._build_two_work_scenario(api)
        by_affiliate = {s["affiliate_id"]: s for s in ctx["statements"]}
        st_px = by_affiliate[ctx["pub_x"]["id"]]
        # Fully unclaimed statement: payable == 0 -> zero admin fee (zero floor).
        assert st_px["admin_fee_cents"] == 0
        assert st_px["gross_amount_cents"] == st_px["unclaimed_amount_cents"]
        st_py = by_affiliate[ctx["pub_y"]["id"]]
        # Payable statement: 5% of gross rounded half-up.
        assert st_py["admin_fee_cents"] == 16767123  # round_half_up(335_342_466 * 0.05)


class TestCornerAdminFeeZeroFloor:
    def test_fully_unclaimed_statement_carries_zero_admin_fee(self, api):
        """PRD §3.8: "The per-statement administration fee is 5 percent of the payable
        amount — the gross_amount_cents minus the unclaimed_amount_cents — rounded
        half-up to whole cents, and capped so the fee never exceeds the payable amount
        itself; a statement whose payable amount is zero carries a zero fee."
        PRD §3.8: "An affiliate whose status is not ACTIVE still has a statement created
        recording its gross, but the entire gross is recorded as unclaimed_amount_cents
        and the same cents credit the cycle's unclaimed pool rather than the affiliate."

        Design: Corner/calculations/admin_fee_zero_floor_on_fully_unclaimed_statement
        """
        pub = create_publisher_affiliate(legal_name="ZF Pub", affiliation_code="ZFP")
        work = _create_work(pub["id"], title="ZF Song")
        _create_claim(work["id"], pub["id"], "PUBLISHER", 10000)
        _confirm_work(work["id"])
        licensee = _create_licensee(legal_name="ZF Net")
        license_ = _issue_license(licensee)
        event = _ingest_performance(
            work["id"], license_["id"], performance_date="2026-02-01", play_count=10
        )
        cycle = _create_cycle(label="ZF1", period_start="2026-01-01", period_end="2026-03-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        validate_success(api.update_affiliate(pub["id"], {"status": "SUSPENDED"}, REGISTRAR))
        closed = _close_collection(cycle["id"])
        statements = _list_cycle_statements(closed["id"])
        assert len(statements) == 1
        stmt = statements[0]
        assert stmt["gross_amount_cents"] == 1006027397
        assert stmt["unclaimed_amount_cents"] == 1006027397
        assert stmt["admin_fee_cents"] == 0


class TestDifficultyPoolConservation:
    def _build_conservation_scenario(self, api):
        # Distinct created_at per affiliate (clock advanced between creations) so the
        # PRD's residue tie-break (rounded amount desc, affiliate created_at asc) is
        # deterministic: the writer is earliest and absorbs the clawback cent.
        validate_success(api.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"}, SYSADMIN))
        writer = create_publisher_affiliate(legal_name="Writer V", affiliation_code="WRV",
                                            party_type="SONGWRITER")
        validate_success(api.set_clock({"to_iso8601": "2026-01-02T00:00:00Z"}, SYSADMIN))
        pub = create_publisher_affiliate(legal_name="Pub V", affiliation_code="PUBV")
        work = _create_work(pub["id"], title="Song V")
        _create_claim(work["id"], writer["id"], "WRITER", 5000)
        _create_claim(work["id"], pub["id"], "PUBLISHER", 5000)
        _confirm_work(work["id"])
        licensee = _create_licensee(legal_name="Inv Radio")
        license_ = _issue_license(licensee)
        event = _ingest_performance(
            work["id"], license_["id"], performance_date="2026-02-01", play_count=100
        )
        cycle = _create_cycle(label="V1", period_start="2026-01-01", period_end="2026-03-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        # Suspend the writer so its share routes to the pool.
        validate_success(api.update_affiliate(writer["id"], {"status": "SUSPENDED"}, REGISTRAR))
        closed = _close_collection(cycle["id"])
        statements = _list_cycle_statements(closed["id"])
        for s in statements:
            get_success_data(api.finalize_statement(s["id"], DISTRIBUTOR))
        distributed = validate_success(api.distribute_cycle(closed["id"], DISTRIBUTOR))
        pool = validate_success(api.get_cycle_pool(closed["id"], DISTRIBUTOR))
        pub_after = validate_success(api.get_affiliate(pub["id"], FINANCE))
        return {
            "writer": writer, "pub": pub, "cycle": distributed,
            "statements": statements, "pool": pool, "pub_after": pub_after,
        }

    def test_distribution_conserves_pool_across_statements_and_unclaimed(self, api):
        """PRD §3.8: "An affiliate whose status is not ACTIVE still has a statement
        created recording its gross, but the entire gross is recorded as
        unclaimed_amount_cents and the same cents credit the cycle's unclaimed pool
        rather than the affiliate."
        PRD §3.9: "Distribution moves the cycle to DISTRIBUTED, moves every FINALIZED
        statement to PAID, credits each affiliate's royalty_balance_cents and
        total_paid_cents by the statement's net minus its unclaimed amount".

        Design: Difficulty/compensating_invariant/distribution_conserves_pool_across_statements_and_unclaimed
        """
        ctx = self._build_conservation_scenario(api)
        cycle, pool = ctx["cycle"], ctx["pool"]
        assert cycle["pool_amount_cents"] == 1006027397

        by_affiliate = {s["affiliate_id"]: s for s in ctx["statements"]}
        st_w = by_affiliate[ctx["writer"]["id"]]
        st_p = by_affiliate[ctx["pub"]["id"]]
        # Equal 5000-bps shares tie at 503_013_699 rounded; the -1 cent negative residue
        # is clawed from the earlier-created affiliate (the writer) per the pinned order.
        assert st_w["gross_amount_cents"] == 503013698
        assert st_p["gross_amount_cents"] == 503013699
        assert pool["balance_cents"] == 503013698
        # Publisher net: gross minus 5% admin on payable (round_half_up(503_013_699*0.05)
        # = 25_150_685) = 477_863_014.
        assert ctx["pub_after"]["royalty_balance_cents"] == 477863014
        assert ctx["pub_after"]["total_paid_cents"] == 477863014
        # Conservation: statement grosses sum to the pool, and pool balance + paid net +
        # withheld admin recompose the pool.
        assert st_w["gross_amount_cents"] + st_p["gross_amount_cents"] == 1006027397
        assert pool["balance_cents"] + 477863014 + 25150685 == 1006027397

    def test_late_claim_moves_cents_from_pool_to_affiliate_conserving_total(self, api):
        """PRD §3.9: "Applying an APPROVED adjustment moves it to the terminal APPLIED,
        adds the delta_cents to the affiliate's royalty_balance_cents, and — for a
        positive LATE_CLAIM delta — debits the same cents from the cycle's unclaimed
        pool."
        PRD §3.9: "A LATE_CLAIM adjustment pays out of the cycle's unclaimed pool, and
        approval requires the clock date to be on or before the cycle's
        claims_open_until — the claim is still valid on the final day — and the claimed
        amount to be no greater than the pool's current balance_cents."

        Design: Difficulty/compensating_invariant/distribution_conserves_pool_across_statements_and_unclaimed
        """
        ctx = self._build_conservation_scenario(api)
        cycle, pool, writer = ctx["cycle"], ctx["pool"], ctx["writer"]
        by_affiliate = {s["affiliate_id"]: s for s in ctx["statements"]}
        st_w = by_affiliate[writer["id"]]

        # The claims window (period_end + 90 days = 2026-06-29) is open at 2026-04-15.
        validate_success(api.set_clock({"to_iso8601": "2026-04-15T00:00:00Z"}, SYSADMIN))
        claim_amount = 1000000
        adj = validate_success(
            api.create_adjustment(
                st_w["id"],
                {"delta_cents": claim_amount, "reason": "LATE_CLAIM"},
                make_songwriter_headers(writer["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.approve_adjustment(adj["id"], FINANCE))
        validate_success(api.apply_adjustment(adj["id"], FINANCE))

        pool_after = validate_success(api.get_cycle_pool(cycle["id"], DISTRIBUTOR))
        writer_after = validate_success(api.get_affiliate(writer["id"], FINANCE))
        assert pool_after["balance_cents"] == pool["balance_cents"] - claim_amount
        assert writer_after["royalty_balance_cents"] == claim_amount
        # The cycle-level conserved quantity is unchanged: cents moved, none created.
        assert (
            pool_after["balance_cents"]
            + writer_after["royalty_balance_cents"]
            + ctx["pub_after"]["royalty_balance_cents"]
            + 25150685
            == cycle["pool_amount_cents"]
        )


class TestCornerCycleGuards:
    def test_distribute_with_draft_statements_rejected(self, api):
        """PRD §3.9: "When every statement of the current epoch is FINALIZED, the
        distributor distributes the cycle; attempting distribution while any
        current-epoch statement remains DRAFT is rejected with
        ERR_STATEMENTS_NOT_FINALIZED."

        Design: Corner/state_machines/cycle_distribute_with_draft_statements_rejected
        """
        ctx = setup_calculating_cycle()
        resp = api.distribute_cycle(ctx["cycle"]["id"], DISTRIBUTOR)
        validate_error(resp, ApiErrorId.ERR_STATEMENTS_NOT_FINALIZED)
        after = validate_success(api.get_cycle(ctx["cycle"]["id"], DISTRIBUTOR))
        assert after["status"] == "CALCULATING"

    def test_close_with_no_performances_rejected(self, api):
        """PRD §3.8: "Closing collection requires at least one ACCEPTED event captured
        in the cycle — an empty close is rejected with ERR_CYCLE_NO_PERFORMANCES".

        Design: Corner/state_machines/cycle_close_with_no_performances_rejected
        """
        cycle = _create_cycle(label="EMPTY1")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        fresh = validate_success(api.get_cycle(cycle["id"], DISTRIBUTOR))
        resp = api.close_collection(
            cycle["id"], {"expected_cycle_version": fresh["version"]}, DISTRIBUTOR
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_NO_PERFORMANCES)


class TestCornerImmediateConsistency:
    def test_distribution_credit_visible_immediately(self, api):
        """PRD §3.9: "Distribution moves the cycle to DISTRIBUTED, moves every
        FINALIZED statement to PAID, credits each affiliate's royalty_balance_cents and
        total_paid_cents by the statement's net minus its unclaimed amount, and sets the
        cycle's claims_open_until to 90 days after period_end if not already set — the
        window during which late claims remain valid."

        Design: Corner/consistency_model/distribution_effects_visible_immediately
        """
        ctx = setup_calculating_cycle()
        statements = _list_cycle_statements(ctx["cycle"]["id"])
        for s in statements:
            get_success_data(api.finalize_statement(s["id"], DISTRIBUTOR))
        distributed = validate_success(api.distribute_cycle(ctx["cycle"]["id"], DISTRIBUTOR))
        assert distributed["status"] == "DISTRIBUTED"

        affiliate_after = validate_success(
            api.get_affiliate(ctx["publisher"]["id"], FINANCE)
        )
        # Single 10000-bps claim on the only work: gross == pool 1_006_027_397,
        # admin round_half_up(gross * 0.05) = 50_301_370, net 955_726_027.
        assert affiliate_after["royalty_balance_cents"] == 955726027
        assert affiliate_after["total_paid_cents"] == 955726027
