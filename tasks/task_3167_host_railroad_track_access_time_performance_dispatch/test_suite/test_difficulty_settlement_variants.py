"""Settlement statements: GROSS vs NET attribution and the penalty tier branches."""

from test_helpers import fixtures


def _world_with_host20_and_dwell7(api):
    """A completed run 20 minutes late, with a CONFIRMED host incident of 20
    minutes and a CONFIRMED STATION_DWELL (non-host) incident of 7 minutes."""
    net = fixtures.run_0902_completed_20_late(api)
    host_incident = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )
    fixtures.confirm_incident(api, host_incident["id"])
    dwell_incident = fixtures.code_incident(api, net, net["run"]["id"], "STATION_DWELL", 7)
    fixtures.confirm_incident(api, dwell_incident["id"])
    net.update({"host_incident": host_incident, "dwell_incident": dwell_incident})
    return net


def test_gross_statement_uses_raw_host_sum_then_reissue_uses_net(api):
    """The same incident set yields 20 host minutes under GROSS and 13 under NET.

    The issued statement's GROSS host_delay_minutes is the raw confirmed
    host-attributable sum (20); after the host disputes and the operator
    reissues, the NET variant subtracts the confirmed non-host minutes (7).

    PRD: "Under `GROSS` — used at creation and issuance — `host_delay_minutes` is the raw sum of confirmed host-attributable minutes."
    PRD: "Under `NET` — used when a disputed statement is reissued — `host_delay_minutes` is the confirmed host-attributable sum minus the confirmed non-host sum, clamped at zero; identical incident data therefore yields NET no greater than GROSS."
    PRD: "the operator reissues a disputed statement (`DISPUTED` → `REISSUED`), which flips `computation_variant` from `GROSS` to `NET` and recomputes `otp_pct`, `host_delay_minutes`, `penalty_cents`, `incentive_cents`, and `net_cents` from the currently `CONFIRMED` incidents"
    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_host_minutes
    """
    net = _world_with_host20_and_dwell7(api)
    statement = fixtures.create_statement(api, net)
    # GROSS at creation: raw host sum; the single run is late so otp is 0.0000,
    # below target - 0.15, giving tier multiplier 3: 50 x 20 x 3 = 3000.
    assert statement["computation_variant"] == "GROSS"
    assert statement["host_delay_minutes"] == 20
    assert statement["penalty_cents"] == 3000

    fixtures.issue_statement(api, statement["id"])
    fixtures.dispute_statement(api, net, statement["id"])
    reissued = fixtures.reissue_statement(api, statement["id"])

    assert reissued["computation_variant"] == "NET"
    assert reissued["host_delay_minutes"] == 13  # 20 host - 7 non-host
    assert reissued["penalty_cents"] == 1950  # 50 x 13 x 3
    assert reissued["net_cents"] == -1950


def test_reissued_net_is_never_greater_than_gross_for_identical_incidents(api):
    """Reissue over an unchanged incident set satisfies NET <= GROSS on host minutes.

    PRD: "Under `NET` — used when a disputed statement is reissued — `host_delay_minutes` is the confirmed host-attributable sum minus the confirmed non-host sum, clamped at zero; identical incident data therefore yields NET no greater than GROSS."
    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_host_minutes
    """
    net = _world_with_host20_and_dwell7(api)
    statement = fixtures.create_statement(api, net)
    gross_host_minutes = statement["host_delay_minutes"]

    fixtures.issue_statement(api, statement["id"])
    fixtures.dispute_statement(api, net, statement["id"])
    reissued = fixtures.reissue_statement(api, statement["id"])

    assert reissued["computation_variant"] == "NET"
    assert reissued["host_delay_minutes"] <= gross_host_minutes
    assert reissued["host_delay_minutes"] == 13


def test_penalty_tier_three_branch_combines_rate_minutes_and_multiplier(api):
    """OTP 50.0000 against target 0.80 selects tier multiplier 3 over 10 host minutes.

    Two runs complete on 2026-09-03: run1 on time (15 minutes late, at
    threshold), run2 late (16 minutes); one CONFIRMED host incident of 10
    minutes. OTP is 1/2 = 50.0000, below target - 0.15, so the penalty is
    50 x 10 x 3 = 1500 cents; train_miles is 2 runs x 40.0 corridor miles = 80.

    PRD: "Otherwise the host owes a penalty: a tier multiplier applies — one when the OTP fraction is within 0.05 of the target (at least target minus 0.05), two when it is at least target minus 0.15, and three when it falls below that — and `penalty_cents` is the `penalty_rate_cents_per_minute` multiplied by the statement's `host_delay_minutes` and by the tier multiplier, rounded half-up to whole cents, with `incentive_cents` zero."
    PRD: "`train_miles` is that count multiplied by the corridor's total mileage (the sum over segments of `milepost_end` minus `milepost_start`)"
    Design: Difficulty/combinatorial_formula/penalty_tier_multiplier_branching
    """
    net = fixtures.runs_0903_one_ontime_one_late(api)
    incident = fixtures.code_incident(
        api, net, net["run2"]["id"], "HOST_SIGNAL", 10, segment_passage_id=net["passage2_ids"][1]
    )
    fixtures.confirm_incident(api, incident["id"])

    statement = fixtures.create_statement(api, net)

    assert statement["completed_run_count"] == 2
    assert statement["otp_pct"] == 50.0000
    assert statement["train_miles"] == 80
    assert statement["host_delay_minutes"] == 10
    assert statement["penalty_cents"] == 1500
    assert statement["incentive_cents"] == 0
    assert statement["net_cents"] == -1500


def test_penalty_tier_branch_zeroes_incentive_and_sets_negative_net(api):
    """In the penalty branch, incentive_cents is zero and net_cents is the negated penalty.

    PRD: "Otherwise the host owes a penalty: a tier multiplier applies — one when the OTP fraction is within 0.05 of the target (at least target minus 0.05), two when it is at least target minus 0.15, and three when it falls below that — and `penalty_cents` is the `penalty_rate_cents_per_minute` multiplied by the statement's `host_delay_minutes` and by the tier multiplier, rounded half-up to whole cents, with `incentive_cents` zero. The `net_cents` of the statement is `incentive_cents` minus `penalty_cents`."
    Design: Difficulty/combinatorial_formula/penalty_tier_multiplier_branching
    """
    net = fixtures.runs_0903_one_ontime_one_late(api)
    incident = fixtures.code_incident(api, net, net["run2"]["id"], "HOST_SIGNAL", 10)
    fixtures.confirm_incident(api, incident["id"])

    statement = fixtures.create_statement(api, net)

    assert statement["incentive_cents"] == 0
    assert statement["penalty_cents"] == 1500
    assert statement["net_cents"] == statement["incentive_cents"] - statement["penalty_cents"]


def test_reissued_statement_host_minutes_equal_live_confirmed_net_sum(api):
    """The reissued NET host_delay_minutes clamps the confirmed host-minus-non-host sum at zero.

    A CONFIRMED host incident of 20 minutes and a CONFIRMED WEATHER (non-host)
    incident of 25 minutes feed an issued GROSS statement at 20 host minutes;
    on reissue the NET variant computes 20 - 25, clamped to zero, so the
    penalty and net collapse to zero.

    PRD: "the operator reissues a disputed statement (`DISPUTED` → `REISSUED`), which flips `computation_variant` from `GROSS` to `NET` and recomputes `otp_pct`, `host_delay_minutes`, `penalty_cents`, `incentive_cents`, and `net_cents` from the currently `CONFIRMED` incidents"
    PRD: "Under `NET` — used when a disputed statement is reissued — `host_delay_minutes` is the confirmed host-attributable sum minus the confirmed non-host sum, clamped at zero; identical incident data therefore yields NET no greater than GROSS."
    PRD: "The eligible incident population is delay incidents on the period's completed runs of the corridor with `status` `CONFIRMED`; `DISPUTED` and `REVERSED` incidents are excluded from both sets."
    Design: Difficulty/compensating_invariant/confirmed_host_minutes_conserved_through_dispute_cycle
    """
    net = fixtures.run_0902_completed_20_late(api)
    host_incident = fixtures.code_incident(api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20)
    fixtures.confirm_incident(api, host_incident["id"])
    weather_incident = fixtures.code_incident(api, net, net["run"]["id"], "WEATHER", 25)
    fixtures.confirm_incident(api, weather_incident["id"])

    statement = fixtures.create_statement(api, net)
    assert statement["host_delay_minutes"] == 20
    fixtures.issue_statement(api, statement["id"])

    fixtures.dispute_statement(api, net, statement["id"])
    reissued = fixtures.reissue_statement(api, statement["id"])

    assert reissued["computation_variant"] == "NET"
    assert reissued["host_delay_minutes"] == 0
    assert reissued["penalty_cents"] == 0
    assert reissued["incentive_cents"] == 0
    assert reissued["net_cents"] == 0
