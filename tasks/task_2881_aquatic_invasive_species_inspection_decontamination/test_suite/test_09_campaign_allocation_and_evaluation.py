"""Education campaigns: allocation rounding, budget conservation and the two baselines."""
from test_helpers import (
    add_disposed_record,
    add_site,
    assert_campaign_allocations_sum_to_budget,
    create_and_open_station,
    create_station,
    create_water_body,
    fetch_campaign,
    fetch_station,
    move_campaign,
    move_station,
    plan_campaign,
    run_campaign_evaluation,
    set_clock,
    setup_program,
)

CAMPAIGN_START = "2026-08-10T00:00:00Z"
CAMPAIGN_END = "2026-08-20T00:00:00Z"


def _three_planned_candidate_stations():
    """Three PLANNED stations on one water body, created Alpha then Bravo then Charlie.

    No inspection record exists, so every traffic weight is 1 and the total
    weight is 3.
    """
    set_clock("2026-08-01T00:00:00Z")
    water_body = create_water_body(risk_tier="MODERATE")
    stations = [
        create_station(
            name=name, station_type="WATERBODY_ACCESS", water_body_id=water_body["id"]
        )
        for name in ("Alpha Access", "Bravo Access", "Charlie Access")
    ]
    campaign = plan_campaign(
        water_body["id"], CAMPAIGN_START, CAMPAIGN_END, 100000,
        evaluation_method="PRE_POST", impressions=0,
    )
    return water_body, stations, campaign


class TestCampaignAllocationFloorThenOrderedRemainder:
    """Each share is floored per station and the remainder walks the pinned order."""

    def test_the_odd_cent_goes_to_the_first_candidate_in_the_pinned_order(self):
        """100,000 cents over three equal weights is 33334 / 33333 / 33333.

        PRD: "Each candidate's allocation is first computed as the campaign's
        `budget_cents` multiplied by that candidate's weight, divided by the total
        weight, and floored to whole cents — floored per station, individually. The
        remainder is then the `budget_cents` minus the sum of those floored
        allocations, and it is handed out one cent at a time to the candidates in
        the pinned order: the first candidate in the order gets an extra cent, then
        the second, and so on until the remainder is exhausted."

        Design: Difficulty/combinatorial_formula/campaign_allocation_floor_per_station_then_ordered_remainder
        """
        _water_body, stations, campaign = _three_planned_candidate_stations()

        launched = move_campaign(campaign["id"], "RUNNING")

        assert launched["status"] == "RUNNING"
        allocations = launched["station_allocations"]
        assert [row["station_id"] for row in allocations] == [
            station["id"] for station in stations
        ]
        assert [row["allocated_cents"] for row in allocations] == [33334, 33333, 33333]

    def test_the_allocations_sum_to_the_budget_and_reach_the_station_ledgers(self):
        """No cent is lost and each station banks its own share.

        PRD: "Because the remainder is always at least zero and always smaller than
        the number of candidates, the resulting allocations sum to exactly
        `budget_cents`."  PRD: "each amount is added to that station's
        `campaign_allocated_cents`."

        Design: Difficulty/combinatorial_formula/campaign_allocation_floor_per_station_then_ordered_remainder
        """
        _water_body, stations, campaign = _three_planned_candidate_stations()

        move_campaign(campaign["id"], "RUNNING")

        launched = fetch_campaign(campaign["id"])
        assert_campaign_allocations_sum_to_budget(launched)
        ledgers = [
            fetch_station(station["id"])["campaign_allocated_cents"]
            for station in stations
        ]
        assert ledgers == [33334, 33333, 33333]


def _running_campaign_over_four_stations():
    """Four stations on one water body; only the CLOSED one is not a candidate."""
    set_clock("2026-08-01T00:00:00Z")
    water_body = create_water_body(risk_tier="MODERATE")
    open_station = create_and_open_station(water_body["id"], name="Tongue A")
    planned_station = create_station(
        name="Tongue B", station_type="WATERBODY_ACCESS", water_body_id=water_body["id"]
    )
    suspended_station = create_and_open_station(water_body["id"], name="Tongue C")
    suspended_station = move_station(suspended_station["id"], "SUSPENDED")
    closed_station = create_station(
        name="Tongue D", station_type="WATERBODY_ACCESS", water_body_id=water_body["id"]
    )
    closed_station = move_station(closed_station["id"], "CLOSED")
    campaign = plan_campaign(
        water_body["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", 100000,
        evaluation_method="PRE_POST",
    )
    campaign = move_campaign(campaign["id"], "RUNNING")
    return {
        "campaign": campaign,
        "open": open_station,
        "planned": planned_station,
        "suspended": suspended_station,
        "closed": closed_station,
    }


class TestCampaignBudgetConservedAcrossLaunchAndCancellation:
    """Cancellation replays the recorded allocations rather than recomputing them."""

    def test_the_launch_excludes_the_closed_station_and_banks_the_odd_cent_first(self):
        """PLANNED and SUSPENDED stations qualify; the CLOSED one never does.

        PRD: "The candidate stations are exactly those whose `water_body_id` equals
        the campaign's `target_water_body_id` and whose `status` is `PLANNED`,
        `OPEN` or `SUSPENDED`; closed stations never qualify."

        Design: Difficulty/compensating_invariant/campaign_budget_conserved_across_launch_and_cancellation
        """
        program = _running_campaign_over_four_stations()

        campaign = fetch_campaign(program["campaign"]["id"])

        assert [row["allocated_cents"] for row in campaign["station_allocations"]] == [
            33334, 33333, 33333,
        ]
        assert [row["station_id"] for row in campaign["station_allocations"]] == [
            program["open"]["id"], program["planned"]["id"], program["suspended"]["id"],
        ]
        assert_campaign_allocations_sum_to_budget(campaign)
        assert fetch_station(program["open"]["id"])["campaign_allocated_cents"] == 33334
        assert fetch_station(program["closed"]["id"])["campaign_allocated_cents"] == 0

    def test_the_cancellation_returns_every_cent_including_the_odd_one(self):
        """Each station is debited exactly what `station_allocations` recorded.

        PRD: "`RUNNING → CANCELLED` is the compensating action for the launch: it
        subtracts from each station's `campaign_allocated_cents` exactly the
        `allocated_cents` recorded for that station in `station_allocations`, sets
        `station_allocations` back to the empty array, advances the `version` of
        every de-allocated station by 1, and advances the campaign's `version` by 1."

        Design: Difficulty/compensating_invariant/campaign_budget_conserved_across_launch_and_cancellation
        """
        program = _running_campaign_over_four_stations()

        cancelled = move_campaign(program["campaign"]["id"], "CANCELLED")

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["station_allocations"] == []
        for key in ("open", "planned", "suspended", "closed"):
            station = fetch_station(program[key]["id"])
            assert station["campaign_allocated_cents"] == 0, (
                f"{key} station must be fully de-allocated"
            )

    def test_allocation_and_de_allocation_never_move_a_station_status(self):
        """The money ledger is the only thing the two transitions touch.

        PRD: "`PLANNED → CANCELLED` touches no station at all, because nothing was
        ever allocated; it merely sets `status` to `CANCELLED` and advances the
        campaign's `version` by 1."

        Design: Difficulty/compensating_invariant/campaign_budget_conserved_across_launch_and_cancellation
        """
        program = _running_campaign_over_four_stations()

        move_campaign(program["campaign"]["id"], "CANCELLED")

        assert fetch_station(program["planned"]["id"])["status"] == "PLANNED"
        assert fetch_station(program["suspended"]["id"])["status"] == "SUSPENDED"
        assert fetch_station(program["open"]["id"])["status"] == "OPEN"
        assert fetch_station(program["closed"]["id"])["status"] == "CLOSED"


def _two_campaigns_over_the_identical_window():
    """Two RUNNING campaigns on one lake, differing only in `evaluation_method`.

    The target lake carries one PASSED and one REFUSED record in the pre-window
    2026-07-31..2026-08-10 (pre/post baseline 1/2) and one PASSED and one
    REFUSED record inside 2026-08-10..2026-08-20 (window rate 1/2).  A single
    extra PASSED record on a second lake lifts the statewide window rate to
    2/3.  The clock ends past both campaigns' `end_at`.
    """
    ctx = setup_program(risk_tier="LOW", infestation_status="CLEAN")
    other = add_site(ctx, "other", risk_tier="LOW", station_name="Other Access")
    set_clock("2026-08-25T00:00:00Z")
    add_disposed_record(ctx, arrived_at="2026-08-01T10:00:00Z", disposition="PASS")
    add_disposed_record(ctx, arrived_at="2026-08-02T10:00:00Z", disposition="REFUSE")
    add_disposed_record(ctx, arrived_at="2026-08-11T10:00:00Z", disposition="PASS")
    add_disposed_record(ctx, arrived_at="2026-08-12T10:00:00Z", disposition="REFUSE")
    add_disposed_record(
        ctx, site=other, arrived_at="2026-08-13T10:00:00Z", disposition="PASS"
    )
    target_id = ctx["water_body"]["id"]
    pre_post = plan_campaign(
        target_id, CAMPAIGN_START, CAMPAIGN_END, 100000,
        name="Clean Drain Dry 2026", evaluation_method="PRE_POST", impressions=12000,
    )
    pre_post = move_campaign(pre_post["id"], "RUNNING")
    corridor = plan_campaign(
        target_id, CAMPAIGN_START, CAMPAIGN_END, 1000,
        name="Corridor Control 2026", evaluation_method="CONTROL_CORRIDOR",
        impressions=12000,
    )
    corridor = move_campaign(corridor["id"], "RUNNING")
    return ctx, pre_post, corridor


class TestCampaignEffectivenessPrePostVersusControlCorridor:
    """Both baselines are always scored; `evaluation_method` picks which one lands."""

    def test_pre_post_compares_the_target_lake_against_its_own_history(self):
        """A baseline of 0.5 equal to the window rate scores 50 plus the 2-point bonus.

        PRD: "The **pre/post** baseline is the target scope over the equal-length
        window immediately preceding `start_at` — the window length being `end_at`
        minus `start_at`, so the baseline window runs from `start_at` minus that
        length up to `start_at` — and if that baseline is undefined for want of any
        dispositioned record, it is taken as 0.0000 rather than rejected."  PRD:
        "The baseline the selected `evaluation_method` names is stored as
        `baseline_compliance_rate`, rounded half up to four decimal places, and its
        score is stored as `effectiveness_score`; the other method's score is
        stored as `alternate_effectiveness_score`."

        Design: Difficulty/dual_variant_calc/campaign_effectiveness_pre_post_versus_control_corridor
        """
        _ctx, pre_post, _corridor = _two_campaigns_over_the_identical_window()

        campaign = run_campaign_evaluation(
            pre_post["id"], evaluation_method="PRE_POST", impressions=12000
        )

        assert campaign["status"] == "EVALUATED"
        assert float(campaign["window_compliance_rate"]) == 0.5
        assert float(campaign["baseline_compliance_rate"]) == 0.5
        assert float(campaign["effectiveness_score"]) == 52.00
        assert float(campaign["alternate_effectiveness_score"]) == 35.33

    def test_the_control_corridor_baseline_is_the_statewide_rate_over_the_same_window(self):
        """A statewide baseline of 2/3 drags the identical data down to 35.33.

        PRD: "The **control-corridor** baseline is the statewide scope over exactly
        the same window as the campaign; it can never be undefined here, because
        the target denominator is a subset of the statewide denominator and is
        already known to be non-empty."  PRD: "Under `PRE_POST` the effectiveness
        score is the before/after comparison on the same water body and the
        alternate is the synthetic-control comparison; under `CONTROL_CORRIDOR` the
        two swap."

        Design: Difficulty/dual_variant_calc/campaign_effectiveness_pre_post_versus_control_corridor
        """
        _ctx, _pre_post, corridor = _two_campaigns_over_the_identical_window()

        campaign = run_campaign_evaluation(
            corridor["id"], evaluation_method="CONTROL_CORRIDOR", impressions=12000
        )

        assert campaign["status"] == "EVALUATED"
        assert float(campaign["window_compliance_rate"]) == 0.5
        assert float(campaign["baseline_compliance_rate"]) == 0.6667
        assert float(campaign["effectiveness_score"]) == 35.33
        assert float(campaign["alternate_effectiveness_score"]) == 52.00

    def test_the_two_methods_diverge_by_the_same_amount_on_identical_records(self):
        """52.00 against 35.33 is the 16.67-point disagreement, and no money moves.

        PRD: "On identical data the two differ whenever the target water body's own
        compliance history differs from the contemporaneous statewide rate, which
        is precisely the disagreement the program office wants to see."  PRD:
        "Evaluation sets `status` to `EVALUATED`, advances the campaign's `version`
        by 1, and deliberately leaves `station_allocations` and every station's
        `campaign_allocated_cents` exactly as they were — evaluating a campaign can
        never drift the money ledger."

        Design: Difficulty/dual_variant_calc/campaign_effectiveness_pre_post_versus_control_corridor
        """
        ctx, pre_post, corridor = _two_campaigns_over_the_identical_window()
        station_id = ctx["station"]["id"]
        assert fetch_station(station_id)["campaign_allocated_cents"] == 101000

        scored_pre_post = run_campaign_evaluation(
            pre_post["id"], evaluation_method="PRE_POST", impressions=12000
        )
        scored_corridor = run_campaign_evaluation(
            corridor["id"], evaluation_method="CONTROL_CORRIDOR", impressions=12000
        )

        divergence = float(scored_pre_post["effectiveness_score"]) - float(
            scored_corridor["effectiveness_score"]
        )
        assert round(divergence, 2) == 16.67
        assert fetch_station(station_id)["campaign_allocated_cents"] == 101000
        assert [row["allocated_cents"] for row in scored_pre_post["station_allocations"]] == [
            100000
        ]
        assert [row["allocated_cents"] for row in scored_corridor["station_allocations"]] == [
            1000
        ]
