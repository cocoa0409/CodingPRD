"""Validation ordering corners: freeze gate vs state legality, and
freeze-blocked operations across the gated endpoint set.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    compute_week,
    create_methodology_version,
    create_provider,
    freeze_chart,
    get_chart,
    get_success_data,
    set_clock,
    setup_open_week_scenario,
    submit_report_ok,
    validate_error,
)

MANAGER = TEST_USERS["chart_manager_headers"]
OPS = TEST_USERS["chart_ops_headers"]


class TestFreezePriorityOverState:
    def test_activate_on_frozen_chart_reports_frozen_not_invalid_state(self, api):
        """PRD §2.8:"then the optimistic-concurrency check where declared,
        then the chart-freeze gate, then target-state legality for the
        requested transition"
    PRD §2.9:"While a `ChartFreeze` with status
        `ACTIVE` exists for a chart, five operations are blocked with
        `ERR_CHART_FROZEN` (HTTP 409): locking a week, computing a week,
        publishing a week, accepting a consumption report, and activating a
        methodology version"

    Design: Corner/validations/chart_freeze_priority_over_invalid_state_on_activate"""
        scenario = setup_open_week_scenario()
        chart = scenario["chart"]
        mv2 = create_methodology_version(chart, version_label="v2",
                                         w_sales=2.0)
        freeze_chart(chart["id"])
        chart_now = get_chart(chart["id"])
        resp = api.activate_methodology_version(
            chart["id"], mv2["id"],
            {"expected_chart_version": chart_now["version"]}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHART_FROZEN)

    def test_report_accept_blocked_while_frozen(self, api):
        """PRD §2.9:"While a `ChartFreeze` with status `ACTIVE` exists for
        a chart, five operations are blocked with `ERR_CHART_FROZEN`
        (HTTP 409): locking a week, computing a week, publishing a week,
        accepting a consumption report, and activating a methodology
        version"

    Design: Corner/validations/chart_freeze_priority_over_invalid_state_on_activate"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        report = submit_report_ok(provider, scenario["title"]["id"],
                                  scenario["week"]["id"],
                                  component_kind="SALES", quantity=10,
                                  file_fingerprint="fz-acc")
        freeze_chart(scenario["chart"]["id"])
        resp = api.accept_report(report["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CHART_FROZEN)
