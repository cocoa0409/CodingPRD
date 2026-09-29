"""The merge-purge fork and the name conservation law it must obey.

A run forks on the net mailable universe it computes: the completed branch
nets every input rental, the failed branch nets nothing and is terminal.
Either way the four name aggregates partition the gross universe exactly, and
they keep partitioning it after a cancelled rental forces a recompute.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    assert_merge_purge_names_conserved,
    assert_merge_purge_run,
    assert_prospect_list_rental,
    fetch_rental,
    fetch_segment,
    get_success_data,
    new_plan,
    new_rental_in_state,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    validate_paginated,
)


def _run_by_id(api, plan_id, run_id) -> dict:
    runs, _meta = validate_paginated(api.list_merge_purge_runs(plan_id, BROKER))
    return next(row for row in runs if row["id"] == run_id)


def _suppressed_housefile_world() -> dict:
    """A single DORMANT segment and one wholly duplicated rental, so the first
    run can only net zero names."""
    set_clock(CLOCK_START)
    season = new_season()
    dormant = new_segment(
        season["id"],
        segment_code="S_DORMANT",
        recency_days=900,
        orders_12mo=0,
        ltv_cents=1000,
        housefile_count=8000,
        avg_order_value_cents=5000,
        historical_response_rate_bps=100,
    )
    rental = new_rental_in_state(
        season["id"],
        coop_model_score=640,
        delivered_gross_names=5000,
        list_source_name="COOP-A",
        requested_gross_names=5000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=10000,
        inter_list_overlap_bps=0,
    )
    plan = new_plan(season["id"], plan_code="P1")
    return {
        "season": season,
        "dormant": dormant,
        "rental": rental,
        "plan": plan,
    }


def _two_rental_world() -> dict:
    """An active and a dormant segment plus two delivered rentals, merged in
    one run ordered by cooperative model score."""
    set_clock(CLOCK_START)
    season = new_season()
    active = new_segment(season["id"], segment_code="S_ACTIVE")
    dormant = new_segment(
        season["id"],
        segment_code="S_DORMANT",
        recency_days=900,
        orders_12mo=0,
        ltv_cents=1000,
        housefile_count=8000,
        avg_order_value_cents=9000,
        historical_response_rate_bps=40,
    )
    r1 = new_rental_in_state(
        season["id"],
        coop_model_score=640,
        delivered_gross_names=25000,
        list_source_name="COOP-R1",
        requested_gross_names=25000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=2000,
        inter_list_overlap_bps=2500,
    )
    r2 = new_rental_in_state(
        season["id"],
        coop_model_score=720,
        delivered_gross_names=10000,
        list_source_name="COOP-R2",
        requested_gross_names=10000,
        cost_per_thousand_cents=9200,
        housefile_overlap_bps=1000,
        inter_list_overlap_bps=1000,
    )
    plan = new_plan(season["id"], plan_code="P1")
    run = run_merge_purge(plan["id"], [r1["id"], r2["id"]])
    return {
        "season": season,
        "active": active,
        "dormant": dormant,
        "r1": r1,
        "r2": r2,
        "plan": plan,
        "merge_purge_run": run,
    }


class TestMergePurgeFork:
    def test_a_run_that_nets_nothing_fails_and_nets_no_rental(self):
        """PRD §3.3: "When `net_mailable_names` is exactly zero the run takes the
        `PENDING → FAILED` branch instead, and the two branches diverge in ways
        that outlive the status field: the four name aggregates are still
        persisted for audit, but **no** rental moves to `NETTED` and no
        `net_names_delivered` is written, and **no** other merge-purge run of the
        plan is superseded — a previously completed universe survives a failed
        re-run intact."

        Design: Difficulty/non_linear_state_machine/merge_purge_fork_completed_and_failed_branches_differ_in_side_effects
        """
        world = _suppressed_housefile_world()
        assert world["dormant"]["contact_strategy"] == "SUPPRESS_ONLY"

        plan_version_before = world["plan"]["version"]
        failed = run_merge_purge(world["plan"]["id"], [world["rental"]["id"]])
        assert_merge_purge_run(failed)
        assert failed["status"] == "FAILED"
        assert failed["housefile_leaf_segment_count"] == 1
        assert failed["gross_input_names"] == 13000
        assert failed["suppressed_names"] == 8000
        assert failed["duplicates_removed"] == 5000
        assert failed["net_mailable_names"] == 0
        assert failed["observed_plan_version"] == plan_version_before
        assert failed["processing_order"] == [world["rental"]["id"]]
        assert_merge_purge_names_conserved(failed)

        rental = fetch_rental(world["rental"]["id"])
        assert_prospect_list_rental(rental)
        assert rental["status"] == "DELIVERED"

    def test_a_widened_housefile_completes_and_promotes_the_rental_to_netted(self, api):
        """PRD §3.3: "When `net_mailable_names` is greater than zero the run takes
        the `PENDING → COMPLETED` branch: `gross_input_names`,
        `suppressed_names`, `duplicates_removed`, `net_mailable_names`,
        `processing_order` and `housefile_leaf_segment_count` are all persisted;
        every rental in the input set moves `DELIVERED → NETTED` with its
        `net_names_delivered` written to its post-dedup count; every *other*
        merge-purge run of the same plan sitting in `COMPLETED` moves to
        `SUPERSEDED`; the accepted version is stored as `observed_plan_version`;
        and the plan's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/merge_purge_fork_completed_and_failed_branches_differ_in_side_effects
        """
        world = _suppressed_housefile_world()
        rental_id = world["rental"]["id"]
        plan_id = world["plan"]["id"]
        failed = run_merge_purge(plan_id, [rental_id])

        new_segment(world["season"]["id"], segment_code="S_ACTIVE")
        completed = run_merge_purge(plan_id, [rental_id])
        assert_merge_purge_run(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["housefile_leaf_segment_count"] == 2
        assert completed["gross_input_names"] == 43000
        assert completed["suppressed_names"] == 8000
        assert completed["duplicates_removed"] == 5000
        assert completed["net_mailable_names"] == 30000
        assert_merge_purge_names_conserved(completed)

        rental = fetch_rental(rental_id)
        assert rental["status"] == "NETTED"
        assert rental["net_names_delivered"] == 0
        assert rental["unit_cost_cents_per_name"] == 9

        assert _run_by_id(api, plan_id, failed["id"])["status"] == "FAILED"


class TestMergePurgeNameConservation:
    def test_the_processing_order_by_coop_score_drives_the_duplicate_partition(self):
        """PRD §2.7: "A merge-purge run's `gross_input_names` always equals
        `net_mailable_names` plus `suppressed_names` plus `duplicates_removed`."

        Design: Difficulty/compensating_invariant/merge_purge_conserves_names_across_a_stale_recompute
        """
        world = _two_rental_world()
        assert world["dormant"]["segment_tier"] == "DORMANT"
        assert world["dormant"]["contact_strategy"] == "SUPPRESS_ONLY"

        run = world["merge_purge_run"]
        assert_merge_purge_run(run)
        assert run["housefile_leaf_segment_count"] == 2
        assert run["processing_order"] == [world["r2"]["id"], world["r1"]["id"]]
        assert run["gross_input_names"] == 73000
        assert run["suppressed_names"] == 8000
        assert run["duplicates_removed"] == 11000
        assert run["net_mailable_names"] == 54000
        assert_merge_purge_names_conserved(run)

        assert fetch_rental(world["r2"]["id"])["net_names_delivered"] == 9000
        assert fetch_rental(world["r1"]["id"])["net_names_delivered"] == 15000

    def test_cancelling_a_rental_recomputes_the_run_without_leaking_names(self, api):
        """PRD §3.2: "every merge-purge run in `COMPLETED` status whose input set
        contains this rental moves to `STALE` and recomputes its name aggregates
        with the cancelled rental excluded from both the input set and the pinned
        processing order."

        Design: Difficulty/compensating_invariant/merge_purge_conserves_names_across_a_stale_recompute
        """
        world = _two_rental_world()
        plan_id = world["plan"]["id"]
        run_id = world["merge_purge_run"]["id"]

        get_success_data(
            api.cancel_rental(
                world["r1"]["id"], BROKER, {"reason": "broker withdrew the list"}
            )
        )

        run = _run_by_id(api, plan_id, run_id)
        assert run["status"] == "STALE"
        assert run["gross_input_names"] == 48000
        assert run["suppressed_names"] == 8000
        assert run["duplicates_removed"] == 1000
        assert run["net_mailable_names"] == 39000
        assert_merge_purge_names_conserved(run)
        assert run["processing_order"] == [world["r2"]["id"]]

        assert fetch_rental(world["r2"]["id"])["net_names_delivered"] == 9000
        cancelled = fetch_rental(world["r1"]["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["gross_names"] == 0
        assert cancelled["net_names_delivered"] == 0

        assert fetch_segment(world["dormant"]["id"])["housefile_count"] == 8000
        assert fetch_segment(world["active"]["id"])["housefile_count"] == 30000
