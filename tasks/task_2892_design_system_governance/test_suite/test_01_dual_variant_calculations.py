"""
Two scores over one evidence set, and two adoption indices over one scan set.

Each pair of readings is computed from exactly the same stored rows, so a test
that only ever looks at one of the two numbers cannot tell whether the second
variant exists at all.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    assert_instant_equals,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    AUDIT_METHOD_MANUAL,
    COVERAGE_WEB_ONLY,
    DASHBOARD_VIEW_LATEST,
    DASHBOARD_VIEW_TRAILING,
    DEFAULT_CLOCK,
    PLATFORM_WEB,
    SCAN_KIND_CODE_SCAN,
    SCAN_KIND_DESIGN_LINT,
)
from test_helpers.fixtures import (
    file_audit,
    governance_base,
    make_implementation,
    read_component,
    read_implementation,
    read_team,
    ship,
)
from test_helpers.test_users import (
    make_design_system_lead_headers,
    make_system_admin_headers,
)


def _shipped_web_with_three_audits(api):
    """
    A shipped web implementation carrying one superseded bad automated audit.

    The three audits are filed in sequence order: an automated pass reporting
    three serious and two moderate findings, a later clean-ish automated pass
    reporting one moderate finding, and a manual pass reporting one serious
    finding. The two views then disagree because the worst automated audit is no
    longer the latest one.
    """
    base = governance_base(api, component_name="Data Table", component_slug="data-table")
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/data-table-web",
        package_version="1.0.0",
    )
    file_audit(api, impl["id"], base["team_id"], 0, 3, 2, method=AUDIT_METHOD_AUTOMATED)
    file_audit(api, impl["id"], base["team_id"], 0, 0, 1, method=AUDIT_METHOD_AUTOMATED)
    file_audit(api, impl["id"], base["team_id"], 0, 1, 0, method=AUDIT_METHOD_MANUAL)
    shipped = ship(
        api, impl["id"], base["team_id"], package_version="1.0.0", token_compliance_ratio=0.95
    )
    base.update({"implementation_id": impl["id"], "shipped": shipped})
    return base


def test_latest_evidence_view_reads_only_the_greatest_sequence_audit_per_method(api):
    """The implementation's own score ignores every superseded audit.

    PRD: "For each method it selects the single qualifying `AA` audit with the greatest `audit_sequence` and ignores every earlier one."

    The latest automated load is 1 and the latest manual load is 4, so the score
    is 100 minus 0.4 times 1 minus 0.6 times 4, which is 97.20.

    Design: Difficulty/dual_variant_calc/a11y_governance_sweep_scores_below_latest_evidence
    """
    scenario = _shipped_web_with_three_audits(api)

    impl = read_implementation(api, scenario["implementation_id"])
    assert_decimal_equals(impl["conformance_score"], 97.20, 2, "conformance_score")
    assert impl["last_audit_sequence"] == 3


def test_governance_sweep_rolls_up_the_worst_audit_and_reads_below_the_engineer_view(api):
    """The component roll-up takes the worst audit per method, not the newest.

    PRD: "On identical evidence, the governance sweep yields a strictly lower number than the latest-evidence view whenever any superseded audit was worse than the latest."

    The worst automated load in the window is 14 and the worst manual load is 4,
    so the swept score is 92.00 against the implementation's own 97.20 — a gap of
    5.20 in favour of the engineer's view.

    Design: Difficulty/dual_variant_calc/a11y_governance_sweep_scores_below_latest_evidence
    """
    scenario = _shipped_web_with_three_audits(api)

    impl = read_implementation(api, scenario["implementation_id"])
    component = read_component(api, scenario["component_id"])

    assert_decimal_equals(
        component["governance_conformance_score"], 92.00, 2, "governance_conformance_score"
    )
    assert_decimal_equals(impl["conformance_score"], 97.20, 2, "conformance_score")
    gap = round(impl["conformance_score"] - component["governance_conformance_score"], 2)
    assert gap == 5.20, f"expected a 5.20 gap between the two views, got {gap}"
    assert_fields(
        component,
        {"coverage_state": COVERAGE_WEB_ONLY, "shipped_platform_count": 1},
        "component",
    )


def _team_with_four_scans(api):
    """
    A team whose two adoption channels each carry an old poor scan and a new good one.

    Code scanning improves from 40.00 to 90.00 and design linting from 50.00 to
    80.00, which is the shape that makes the two index variants disagree.
    """
    base = governance_base(api, team_name="Metrics Team", team_slug="metrics-team")
    team_id = base["team_id"]
    lead = make_design_system_lead_headers()
    # Filing a measurement is authorised for ContributingTeam and SystemAdmin only,
    # and a SystemAdmin may file on any team's behalf without an ownership check.
    admin = make_system_admin_headers()
    rows = [
        (SCAN_KIND_CODE_SCAN, "2026-06-01T00:00:00.000Z", "2026-06-29T00:00:00.000Z", 40, 60),
        (SCAN_KIND_CODE_SCAN, "2026-07-01T00:00:00.000Z", "2026-07-31T00:00:00.000Z", 90, 10),
        (SCAN_KIND_DESIGN_LINT, "2026-06-01T00:00:00.000Z", "2026-06-29T00:00:00.000Z", 50, 50),
        (SCAN_KIND_DESIGN_LINT, "2026-07-01T00:00:00.000Z", "2026-07-31T00:00:00.000Z", 80, 20),
    ]
    from test_helpers.factories import adoption_scan_payload

    for kind, start, end, system, legacy in rows:
        response = api.create_adoption_scan(
            team_id,
            adoption_scan_payload(start, end, system, legacy, 0, scan_kind=kind),
            admin,
        )
        validate_success(response, 201)
    base["lead"] = lead
    return base


def test_latest_scan_index_moves_immediately_with_the_freshest_scan_in_each_channel(api):
    """The latest-scan view reads the single most recent scan of each channel.

    PRD: "Under this view a single good scan moves the number immediately."

    Code scanning contributes 90.00 at weight 0.70 and design linting 80.00 at
    weight 0.30, so the index is 87.00.

    Design: Difficulty/dual_variant_calc/team_adoption_trailing_window_reads_below_latest_scan
    """
    scenario = _team_with_four_scans(api)

    dashboard = validate_success(
        api.get_team_dashboard(
            scenario["team_id"], scenario["lead"], {"view": DASHBOARD_VIEW_LATEST}
        )
    )
    assert dashboard["view"] == DASHBOARD_VIEW_LATEST
    assert_decimal_equals(dashboard["adoption_index"], 87.00, 2, "adoption_index")
    assert_decimal_equals(dashboard["code_scan_ratio"], 90.00, 2, "code_scan_ratio")
    assert_decimal_equals(dashboard["design_lint_ratio"], 80.00, 2, "design_lint_ratio")
    assert dashboard["scanned_kind_count"] == 2

    team = read_team(api, scenario["team_id"])
    assert_decimal_equals(team["adoption_index_latest"], 87.00, 2, "adoption_index_latest")


def test_trailing_window_index_averages_two_rows_per_channel_and_reads_lower(api):
    """The trailing-window view averages the two newest rows of each channel.

    PRD: "Because the average drags a fresh improvement backwards, a team that has just improved reads materially lower here than under the latest-scan view on exactly the same rows."

    Each channel averages to 65.00, so the blended index is 65.00 — 22.00 below
    the latest-scan reading over the very same four scans.

    Design: Difficulty/dual_variant_calc/team_adoption_trailing_window_reads_below_latest_scan
    """
    scenario = _team_with_four_scans(api)

    dashboard = validate_success(
        api.get_team_dashboard(
            scenario["team_id"], scenario["lead"], {"view": DASHBOARD_VIEW_TRAILING}
        )
    )
    assert dashboard["view"] == DASHBOARD_VIEW_TRAILING
    assert_decimal_equals(dashboard["adoption_index"], 65.00, 2, "adoption_index")
    assert_decimal_equals(dashboard["code_scan_ratio"], 65.00, 2, "code_scan_ratio")
    assert_decimal_equals(dashboard["design_lint_ratio"], 65.00, 2, "design_lint_ratio")

    team = read_team(api, scenario["team_id"])
    assert_decimal_equals(team["adoption_index_latest"], 87.00, 2, "adoption_index_latest")
    assert_decimal_equals(
        team["adoption_index_trailing"], 65.00, 2, "adoption_index_trailing"
    )
    gap = round(team["adoption_index_latest"] - team["adoption_index_trailing"], 2)
    assert gap == 22.00, f"expected a 22.00 gap between the two variants, got {gap}"
    assert_instant_equals(
        validate_success(
            api.get_team(scenario["team_id"], scenario["lead"])
        )["created_at"],
        DEFAULT_CLOCK,
        "team.created_at",
    )
