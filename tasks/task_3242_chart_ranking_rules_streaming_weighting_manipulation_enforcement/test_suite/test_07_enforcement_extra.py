"""Extra provider-gating corner: suspension mid-week also blocks a report
whose event data is otherwise fully valid (paired with the primary accept
gate test).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_provider,
    get_success_data,
    setup_open_week_scenario,
    submit_report_ok,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["chart_ops_headers"]


class TestProviderStatusGateExtra:
    def test_suspended_provider_blocks_second_report_accept(self, api):
        """PRD §3.3:"the provider must be `ACTIVE` (a suspended provider
        yields `ERR_ACCOUNT_SUSPENDED`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/report_accept_gated_by_provider_status"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="STREAM_ON_DEMAND",
                                   territory="DOMESTIC")
        r1 = submit_report_ok(provider, scenario["title"]["id"],
                              scenario["week"]["id"],
                              component_kind="STREAM_ON_DEMAND_PAID",
                              quantity=2500, file_fingerprint="xp-keep")
        r2 = submit_report_ok(provider, scenario["title"]["id"],
                              scenario["week"]["id"],
                              component_kind="STREAM_ON_DEMAND_AD",
                              quantity=2500, file_fingerprint="xp-blocked")
        accept_ok = api.accept_report(r1["id"], OPS)
        assert accept_ok.status_code == 200
        get_success_data(api.suspend_provider(provider["id"], ADMIN))
        resp = api.accept_report(r2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        assert get_success_data(api.get_report(r2["id"], OPS))["status"] == "RECEIVED"


class TestDisqualifyCascadeExtra:
    def test_disqualified_title_excluded_from_later_compute(self, api):
        """PRD §3.5:"The gates are: the title's `eligibility_posture` must
        be `ELIGIBLE`"
    PRD §3.6:"A `DISQUALIFY` finding is the maximum
        sanction: the title's `eligibility_posture` becomes `DISQUALIFIED`"

    Design: Difficulty/transitive_cascade/disqualify_cascade_depth3"""
        from test_helpers import (
            accept_report,
            compute_week,
            create_week,
            disqualify_title_via_investigation,
            find_entry,
            set_clock,
        )
        scenario = setup_open_week_scenario()
        title = scenario["title"]
        week = scenario["week"]
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        report = submit_report_ok(provider, title["id"], week["id"],
                                  component_kind="SALES", quantity=10,
                                  file_fingerprint="dq-1")
        accept_report(report["id"])
        disqualify_title_via_investigation(title["id"], week["id"], "inv-dq")
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"],
                                       TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        assert find_entry(entries, title["id"]) is None, (
            "a DISQUALIFIED title is skipped at compute")
