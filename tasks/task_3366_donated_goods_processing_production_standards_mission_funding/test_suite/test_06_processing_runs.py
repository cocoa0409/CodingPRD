"""Processing runs: dual gross/net rate reckoning, terminal close, and the
eligible-standard gate at open."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    close_run,
    create_run,
    create_standard,
    get_run,
    make_member_admin_headers,
    setup_org_with_standard,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAD = TEST_USERS["production_lead_headers"]


def _setup_two_runs():
    org, site, std = setup_org_with_standard("Org Dual Rate")
    run1 = create_run(site["id"], std["id"])
    run2 = create_run(site["id"], std["id"])
    return run1, run2


class TestProcessingRuns:
    def test_gross_and_net_rates_diverge_on_unsalables(self, api):
        """PRD 3.4: "The **gross** rate, `gross_rate_iph`, credits every item
        touched: `item_count_processed` multiplied by 60 and divided by
        `labor_minutes`, so a run with many unsalables still scores well on
        effort."
        PRD 3.4: "The **net** rate, `net_rate_iph`, counts only sellable
        output: `item_count_processed` minus `unsalable_count`, multiplied by
        60, divided by `labor_minutes`."
        PRD 3.4: "The `performance_flag` is `MET` when the net rate is at least
        the target — the boundary is inclusive, so an exact tie counts as met —
        and `MISSED` otherwise."

        Design: Difficulty/dual_variant_calc/production_rate_gross_vs_net_diverge
        """
        run1, _run2 = _setup_two_runs()
        closed = close_run(run1["id"], item_count_processed=130,
                           unsalable_count=10, labor_minutes=120,
                           labor_cost_cents=3600)
        assert closed["gross_rate_iph"] == 65.0, "130 * 60 / 120"
        assert closed["net_rate_iph"] == 60.0, "(130 - 10) * 60 / 120"
        assert closed["variance_bps"] == 0
        assert closed["performance_flag"] == "MET", "net exactly at target is MET"
        assert closed["status"] == "CLOSED"

    def test_net_below_target_yields_negative_variance_and_missed(self, api):
        """PRD 3.4: "The `variance_bps` is the net rate minus the target,
        multiplied by 10000 and divided by the target, rounded half-up to an
        integer with ties away from zero."
        PRD 3.4: "Performance is judged against the *pinned* standard's
        `target_items_per_hour` — supersession of that standard after the run
        opened does not re-target it."

        Design: Difficulty/dual_variant_calc/production_rate_gross_vs_net_diverge
        """
        _run1, run2 = _setup_two_runs()
        closed = close_run(run2["id"], item_count_processed=118,
                           unsalable_count=8, labor_minutes=120,
                           labor_cost_cents=3600)
        assert closed["gross_rate_iph"] == 59.0, "118 * 60 / 120"
        assert closed["net_rate_iph"] == 55.0, "(118 - 8) * 60 / 120"
        # round_half_up((55 - 60) * 10000 / 60) = round_half_up(-833.33..)
        assert closed["variance_bps"] == -833
        assert closed["performance_flag"] == "MISSED"

    def test_run_close_twice_returns_invalid_state(self, api):
        """PRD 3.4: "Closing a run — again a `ProductionLead` act, requiring
        the run still `OPEN` and the organization `ACTIVE` — is where
        production is measured."
        PRD 3.4: "A closed run is terminal at `CLOSED`."

        Design: Corner/state_machines/run_close_twice_returns_invalid_state
        """
        org, site, std = setup_org_with_standard("Org RC")
        run = create_run(site["id"], std["id"])
        closed = close_run(run["id"], item_count_processed=120,
                           unsalable_count=0, labor_minutes=120,
                           labor_cost_cents=3600)
        assert closed["net_rate_iph"] == 60.0
        resp = api_client.close_processing_run(
            run["id"],
            {"item_count_processed": 1, "unsalable_count": 0,
             "labor_minutes": 60, "labor_cost_cents": 30},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = get_run(run["id"])
        assert reread["item_count_processed"] == 120, "first close must stand"

    def test_run_open_with_superseded_standard_rejected(self, api):
        """PRD 3.4: "The named standard must be `ACTIVE` and belong to the same
        organization as the site; otherwise the open is rejected with
        `ERR_NO_ELIGIBLE_STANDARD`."
        PRD 3.3: "Supersession is deliberately shallow — items already priced
        against the old standard keep their pinned `priced_standard_id`, and
        runs already opened against it keep their pinned
        `production_standard_id`; neither is re-evaluated."

        Design: Corner/validations/run_open_with_superseded_standard_rejected
        """
        org, site, std1 = setup_org_with_standard("Org SS")
        std2 = create_standard(
            org["id"], target_items_per_hour=80, hourly_cost_cents=2000,
            grade_price_map={"A": 1200, "B": 800, "C": 500},
            price_floor_cents=100, price_ceiling_cents=6000)
        resp = api_client.create_processing_run(
            {"site_id": site["id"], "production_standard_id": std1["id"]}, LEAD)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STANDARD)
        rows, _meta = validate_paginated(api_client.list_production_standards(
            org["id"], make_member_admin_headers(org["id"])))
        by_id = {r["id"]: r["status"] for r in rows}
        assert by_id[std1["id"]] == "SUPERSEDED"
        assert by_id[std2["id"]] == "ACTIVE"
        runs, runs_meta = validate_paginated(api_client.list_processing_runs(
            LEAD, params={"site_id": site["id"]}))
        assert runs_meta["total_count"] == 0
