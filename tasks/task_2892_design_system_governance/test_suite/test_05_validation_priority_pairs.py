"""
Pairs of gates that a single request breaks at once.

Every scenario here is built so that two different refusals are simultaneously
true, which makes the reported error id the whole subject of the test: the lower
priority number must win and the higher one must stay invisible.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import (
    ERR_A11Y_CONFORMANCE_INSUFFICIENT,
    ERR_COMPONENT_DEPRECATION_IN_PROGRESS,
    ERR_DEPRECATION_NOTICE_TOO_SHORT,
    ERR_DEPRECATION_WINDOW_OVERLAP,
    ERR_INVALID_EXCEPTION_GRANT_STATE,
    ERR_TEAM_DEBT_BUDGET_EXCEEDED,
)
from test_helpers.assertions import (
    assert_conformance_score,
    assert_debt_points,
    assert_fields,
    assert_page_meta,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    AUDIT_METHOD_MANUAL,
    COVERAGE_WEB_ONLY,
    DEBT_STATE_CLEAR,
    DEMOTION_REASON_NONE,
    DOCS_STATE_DRAFT,
    GRANT_DENIED,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DEPRECATION_ANNOUNCED,
    MATURITY_BETA,
    MATURITY_EXPERIMENTAL,
    PLAN_DRAFT,
    PLATFORM_WEB,
)
from test_helpers.factories import (
    decision_payload,
    deprecation_plan_payload,
    promote_payload,
)
from test_helpers.fixtures import (
    announce_plan,
    approve_grant,
    file_audit,
    governance_base,
    make_implementation,
    make_plan,
    read_component,
    read_grant,
    read_implementation,
    read_team,
    request_grant,
    ship,
)
from test_helpers.test_users import make_design_system_lead_headers


def _denied_grant_worth_more_than_the_budget(api):
    """
    A denied grant whose points would breach its team's budget if re-approved.

    The team's budget is 5.00 points and the grant prices at 6.00, so a second
    decision that reached the budget gate would fail there too.
    """
    base = governance_base(
        api,
        team_name="Thrifty Team",
        team_slug="thrifty-team",
        component_name="Side Sheet",
        component_slug="side-sheet",
        team_overrides={"debt_budget_points": 5.00},
    )
    grant = request_grant(api, base["team_id"], base["component_id"])
    denied = approve_grant(api, grant["id"], decision="DENY")
    assert denied["state"] == GRANT_DENIED
    base.update({"grant_id": grant["id"], "denied": denied})
    return base


def test_a_decided_grant_reports_its_state_rather_than_the_budget_breach(api):
    """The state gate is checked before the budget arithmetic is even reached.

    PRD: "The grant must be in `REQUESTED`, otherwise `ERR_INVALID_EXCEPTION_GRANT_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/exception_state_gate_outranks_debt_budget_gate
    """
    scenario = _denied_grant_worth_more_than_the_budget(api)

    detail = validate_error(
        api.decide_exception_grant(
            scenario["grant_id"],
            decision_payload("APPROVE"),
            make_design_system_lead_headers(),
        ),
        ERR_INVALID_EXCEPTION_GRANT_STATE,
        409,
    )
    assert detail["error_id"] != ERR_TEAM_DEBT_BUDGET_EXCEEDED


def test_the_refused_second_decision_leaves_the_ledger_completely_untouched(api):
    """A refusal at the state gate writes nothing, not even a partial charge.

    PRD: "A denial sets `state` to `DENIED` and records `decided_by_user_id` and `decided_at`, leaves `debt_points` at 0.00, changes no team roll-up and no component counter, and increments only the grant's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/exception_state_gate_outranks_debt_budget_gate
    """
    scenario = _denied_grant_worth_more_than_the_budget(api)

    validate_error(
        api.decide_exception_grant(
            scenario["grant_id"],
            decision_payload("APPROVE"),
            make_design_system_lead_headers(),
        ),
        ERR_INVALID_EXCEPTION_GRANT_STATE,
    )

    grant = read_grant(api, scenario["grant_id"])
    assert grant["state"] == GRANT_DENIED
    assert_debt_points(grant, 0.00)
    assert grant["pinned_maturity_level"] is None

    team = read_team(api, scenario["team_id"])
    assert_debt_points(team, 0.00, "outstanding_debt_points")
    assert_debt_points(team, 0.00, "lifetime_debt_points")
    assert team["debt_state"] == DEBT_STATE_CLEAR
    assert read_component(api, scenario["component_id"])["one_off_exception_count"] == 0


def _deprecated_component_below_the_conformance_floor(api):
    """
    A component that is both under deprecation and short of the BETA score floor.

    Its automated evidence was remediated, so the shipping gate passes and the
    engineer's view reads 82.00, while the governance sweep still carries the
    original bad automated audit and reads 66.00.
    """
    base = governance_base(
        api,
        team_name="Overlay Team",
        team_slug="overlay-team",
        component_name="Tooltip",
        component_slug="tooltip",
        component_overrides={"docs_state": DOCS_STATE_DRAFT},
    )
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/tooltip-web",
    )
    file_audit(api, impl["id"], base["team_id"], critical=4, method=AUDIT_METHOD_AUTOMATED)
    file_audit(api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED)
    file_audit(api, impl["id"], base["team_id"], critical=3, method=AUDIT_METHOD_MANUAL)
    shipped = ship(api, impl["id"], base["team_id"])
    assert_conformance_score(shipped, 82.00)

    plan = make_plan(
        api,
        base["component_id"],
        "2026-08-01T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
        "2026-09-25T00:00:00.000Z",
    )
    announce_plan(api, plan["id"])

    base.update({"implementation_id": impl["id"], "plan_id": plan["id"]})
    return base


def test_the_conformance_floor_is_reported_ahead_of_the_deprecation_block(api):
    """Both promotion gates fail and the accessibility score is the one reported.

    PRD: "`governance_conformance_score` is at least 70.00 for a `BETA` promotion and at least 90.00 for a `STABLE` promotion, inclusive at both boundaries — otherwise `ERR_A11Y_CONFORMANCE_INSUFFICIENT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/promotion_conformance_gate_outranks_deprecation_in_progress_gate
    """
    scenario = _deprecated_component_below_the_conformance_floor(api)

    detail = validate_error(
        api.promote_maturity(
            scenario["component_id"],
            promote_payload(MATURITY_BETA),
            make_design_system_lead_headers(),
        ),
        ERR_A11Y_CONFORMANCE_INSUFFICIENT,
        422,
    )
    assert detail["error_id"] != ERR_COMPONENT_DEPRECATION_IN_PROGRESS


def test_the_sweep_that_refused_the_promotion_is_harsher_than_the_engineers_view(api):
    """The refused promotion leaves both dimensions and both scores as they were.

    PRD: "**The governance-sweep view** is deliberately harsher, and it is the only view any promotion gate reads."

    The implementation still reads 82.00 from its latest evidence while the
    component's rolled-up sweep reads 66.00, which is what failed the gate.

    Design: Difficulty/priority_pair_validation_conflict/promotion_conformance_gate_outranks_deprecation_in_progress_gate
    """
    scenario = _deprecated_component_below_the_conformance_floor(api)

    validate_error(
        api.promote_maturity(
            scenario["component_id"],
            promote_payload(MATURITY_BETA),
            make_design_system_lead_headers(),
        ),
        ERR_A11Y_CONFORMANCE_INSUFFICIENT,
    )

    component = read_component(api, scenario["component_id"])
    assert_fields(
        component,
        {
            "maturity_level": MATURITY_EXPERIMENTAL,
            "maturity_demotion_reason": DEMOTION_REASON_NONE,
            "lifecycle_state": LIFECYCLE_DEPRECATION_ANNOUNCED,
            "coverage_state": COVERAGE_WEB_ONLY,
        },
        "component",
    )
    assert_conformance_score(component, 66.00, "governance_conformance_score")
    implementation = read_implementation(api, scenario["implementation_id"])
    assert_conformance_score(implementation, 82.00)


def _component_with_one_drafted_deprecation_window(api):
    """
    An experimental component already carrying a drafted plan whose window runs
    from the first of August up to the first of December.
    """
    base = governance_base(
        api,
        team_name="Legacy Team",
        team_slug="legacy-team",
        component_name="Legacy Modal",
        component_slug="legacy-modal",
    )
    first = make_plan(
        api,
        base["component_id"],
        "2026-08-01T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
        "2026-12-01T00:00:00.000Z",
    )
    assert_fields(
        first,
        {"state": PLAN_DRAFT, "required_notice_days": 14, "actual_notice_days": 19},
        "first plan",
    )
    base["first_plan_id"] = first["id"]
    return base


def test_a_short_notice_window_is_reported_ahead_of_the_window_collision(api):
    """A plan that is both too short and overlapping reports the notice failure.

    PRD: "The first requires `actual_notice_days` to be at least `required_notice_days`, inclusive at the boundary, so a plan that serves exactly the required number of days passes."

    The second plan serves four days against a requirement of fourteen and also
    intersects the drafted window, so both refusals are live at once.

    Design: Difficulty/priority_pair_validation_conflict/deprecation_notice_gate_outranks_window_overlap_gate
    """
    scenario = _component_with_one_drafted_deprecation_window(api)

    detail = validate_error(
        api.create_deprecation_plan(
            scenario["component_id"],
            deprecation_plan_payload(
                "2026-09-01T00:00:00.000Z",
                "2026-09-05T00:00:00.000Z",
                "2026-11-01T00:00:00.000Z",
            ),
            make_design_system_lead_headers(),
        ),
        ERR_DEPRECATION_NOTICE_TOO_SHORT,
        422,
    )
    assert detail["error_id"] != ERR_DEPRECATION_WINDOW_OVERLAP


def test_the_refused_plan_is_never_created_and_the_lifecycle_stays_active(api):
    """A refusal at the notice gate leaves the component with its single plan.

    PRD: "A plan occupies the half-open interval that begins at its `announced_at` and ends just before its `removal_at`, on its component."

    Design: Difficulty/priority_pair_validation_conflict/deprecation_notice_gate_outranks_window_overlap_gate
    """
    scenario = _component_with_one_drafted_deprecation_window(api)

    validate_error(
        api.create_deprecation_plan(
            scenario["component_id"],
            deprecation_plan_payload(
                "2026-09-01T00:00:00.000Z",
                "2026-09-05T00:00:00.000Z",
                "2026-11-01T00:00:00.000Z",
            ),
            make_design_system_lead_headers(),
        ),
        ERR_DEPRECATION_NOTICE_TOO_SHORT,
    )

    rows, meta = validate_paginated(
        api.list_deprecation_plans(
            scenario["component_id"], make_design_system_lead_headers()
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [scenario["first_plan_id"]]
    assert read_component(api, scenario["component_id"])["lifecycle_state"] == LIFECYCLE_ACTIVE
