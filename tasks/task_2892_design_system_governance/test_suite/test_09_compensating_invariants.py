"""
The two compensating actions and the quantities they conserve.

Repayment gives back a debt total and rescission gives back a dependency-block
total. Each test pairs the conserved quantity with a quantity that is deliberately
not conserved, because that pairing is what distinguishes an exact compensation
from a recomputation from scratch.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_debt_points,
    assert_fields,
    assert_instant_equals,
)
from test_helpers.constants import (
    COMPAT_COMPATIBLE,
    COMPAT_SUNSET_PROVIDER,
    COVERAGE_PARTIAL,
    DEBT_STATE_CLEAR,
    DEFAULT_CLOCK,
    DEMOTION_REASON_UPSTREAM_SUNSET,
    DOCS_STATE_PUBLISHED,
    GRANT_APPROVED,
    GRANT_REPAID,
    IMPL_SHIPPED,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_SUNSET,
    MATURITY_BETA,
    MATURITY_EXPERIMENTAL,
    MATURITY_STABLE,
    PLAN_RESCINDED,
    PLAN_SUNSET,
    PLATFORM_IOS,
    PLATFORM_WEB,
)
from test_helpers.factories import repay_payload, rescind_payload
from test_helpers.fixtures import (
    advance_plan,
    announce_plan,
    approve_grant,
    declare_dependency,
    file_clean_evidence,
    governance_base,
    make_component,
    make_implementation,
    make_plan,
    pin_clock,
    promote,
    read_component,
    read_grant,
    read_implementation,
    read_team,
    request_grant,
    ship,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
)

SUNSET_CLOCK = "2026-08-20T00:00:00.000Z"


def _team_carrying_one_ten_fifty_grant(api):
    """
    A team carrying one approved all-platform grant against an experimental part.

    Twelve base points for a one-off component, times 1.75 for all-platform reach,
    times 0.50 for experimental maturity, is 10.50.
    """
    base = governance_base(
        api,
        team_name="Bespoke Team",
        team_slug="bespoke-team",
        component_name="Mega Menu",
        component_slug="mega-menu",
    )
    requested = request_grant(
        api, base["team_id"], base["component_id"], platform_scope="ALL"
    )
    approved = approve_grant(api, requested["id"])
    assert_fields(
        approved,
        {"state": GRANT_APPROVED, "pinned_maturity_level": MATURITY_EXPERIMENTAL},
        "grant",
    )
    assert_debt_points(approved, 10.50)
    base.update({"grant_id": requested["id"]})
    return base


def test_repayment_returns_the_outstanding_total_to_its_pre_approval_value(api):
    """The outstanding sum falls by exactly the repaid grant's points.

    PRD: "Repaying an exception grant returns a team's `outstanding_debt_points` to precisely its pre-approval value while leaving `lifetime_debt_points` untouched."

    Design: Difficulty/compensating_invariant/exception_repayment_returns_outstanding_debt_to_its_pre_approval_value
    """
    scenario = _team_carrying_one_ten_fifty_grant(api)

    before = read_team(api, scenario["team_id"])
    assert_debt_points(before, 10.50, "outstanding_debt_points")

    repaid = validate_success(
        api.repay_exception_grant(
            scenario["grant_id"],
            repay_payload(),
            make_contributing_team_headers(scenario["team_id"]),
        )
    )
    assert repaid["state"] == GRANT_REPAID
    assert_debt_points(repaid, 10.50)
    assert_instant_equals(repaid["repaid_at"], DEFAULT_CLOCK, "repaid_at")

    after = read_team(api, scenario["team_id"])
    assert_debt_points(after, 0.00, "outstanding_debt_points")
    assert after["debt_state"] == DEBT_STATE_CLEAR


def test_repayment_leaves_the_lifetime_total_and_the_historic_amount_in_place(api):
    """What is conserved is the outstanding sum, not the record of the deviation.

    PRD: "Because `REPAID` is inside the lifetime set, `lifetime_debt_points` does not move."

    The repaid grant keeps its 10.50 on the row as the historic amount owed, and
    the component's exception counter is the figure that falls.

    Design: Difficulty/compensating_invariant/exception_repayment_returns_outstanding_debt_to_its_pre_approval_value
    """
    scenario = _team_carrying_one_ten_fifty_grant(api)

    assert read_component(api, scenario["component_id"])["one_off_exception_count"] == 1

    validate_success(
        api.repay_exception_grant(
            scenario["grant_id"],
            repay_payload(),
            make_contributing_team_headers(scenario["team_id"]),
        )
    )

    team = read_team(api, scenario["team_id"])
    assert_debt_points(team, 10.50, "lifetime_debt_points")
    assert_debt_points(team, 0.00, "outstanding_debt_points")
    grant = read_grant(api, scenario["grant_id"])
    assert grant["state"] == GRANT_REPAID
    assert_debt_points(grant, 10.50)
    assert read_component(api, scenario["component_id"])["one_off_exception_count"] == 0


def _sunset_provider_of_a_demoted_consumer(api):
    """
    A sunset provider whose consumer was demoted out of STABLE by the cascade.

    The consumer ships on web and iOS with clean evidence and a published
    documentation page, which is what carried it to STABLE before the provider's
    plan advanced.
    """
    base = governance_base(
        api,
        team_name="Chrome Team",
        team_slug="chrome-team",
        component_name="Icon Core",
        component_slug="icon-core",
    )
    provider_id = base["component_id"]
    consumer = make_component(
        api,
        base["team_id"],
        name="Nav Bar",
        slug="nav-bar",
        docs_state=DOCS_STATE_PUBLISHED,
    )
    web = make_implementation(
        api,
        consumer["id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/nav-bar-web",
        package_version="6.0.0",
    )
    file_clean_evidence(api, web["id"], base["team_id"])
    ship(api, web["id"], base["team_id"], package_version="6.0.0")
    ios = make_implementation(
        api,
        consumer["id"],
        base["team_id"],
        platform=PLATFORM_IOS,
        package_name="DSNavBar",
        package_version="6.0.0",
    )
    file_clean_evidence(api, ios["id"], base["team_id"])
    ship(api, ios["id"], base["team_id"], package_version="6.0.0")

    edge = declare_dependency(api, consumer["id"], provider_id, 1)
    promote(api, consumer["id"], MATURITY_BETA)
    stable = promote(api, consumer["id"], MATURITY_STABLE)
    assert stable["maturity_level"] == MATURITY_STABLE

    plan = make_plan(
        api,
        provider_id,
        "2026-08-01T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
        "2026-09-25T00:00:00.000Z",
    )
    announce_plan(api, plan["id"])
    pin_clock(api, SUNSET_CLOCK)
    sunset = advance_plan(api, plan["id"])
    assert_fields(
        sunset, {"state": PLAN_SUNSET, "blocked_dependent_count": 1}, "plan"
    )
    demoted = read_component(api, consumer["id"])
    assert_fields(
        demoted,
        {
            "maturity_level": MATURITY_BETA,
            "maturity_demotion_reason": DEMOTION_REASON_UPSTREAM_SUNSET,
            "blocked_dependency_count": 1,
        },
        "consumer",
    )
    assert (
        read_component(api, provider_id)["lifecycle_state"] == LIFECYCLE_SUNSET
    )

    base.update(
        {
            "provider_id": provider_id,
            "consumer_id": consumer["id"],
            "web_implementation_id": web["id"],
            "ios_implementation_id": ios["id"],
            "dependency_id": edge["id"],
            "plan_id": plan["id"],
        }
    )
    return base


def _edge_state(api, component_id, edge_id):
    """Read one dependency edge's compatibility state through its listing."""
    rows, _meta = validate_paginated(
        api.list_dependencies(component_id, make_design_system_lead_headers())
    )
    matches = [row for row in rows if row["id"] == edge_id]
    assert matches, f"edge {edge_id} is not listed under component {component_id}"
    return matches[0]["compatibility_state"]


def test_rescission_gives_back_exactly_the_dependency_block_total(api):
    """The conserved quantity is the block total the cascade recorded.

    PRD: "Rescinding from `SUNSET` drives the component's lifecycle dimension `SUNSET → ACTIVE` and gives back exactly what hop 2 of the sunset cascade took: every dependency edge whose `provider_component_id` is this component and whose `compatibility_state` is `SUNSET_PROVIDER` returns to `COMPATIBLE`, and each affected consumer's `blocked_dependency_count` falls by precisely the amount that hop added."

    Design: Difficulty/compensating_invariant/deprecation_rescission_returns_the_dependency_block_total_but_not_the_demotion
    """
    scenario = _sunset_provider_of_a_demoted_consumer(api)

    assert (
        _edge_state(api, scenario["consumer_id"], scenario["dependency_id"])
        == COMPAT_SUNSET_PROVIDER
    )

    rescinded = validate_success(
        api.rescind_deprecation_plan(
            scenario["plan_id"], rescind_payload(), make_design_system_lead_headers()
        )
    )
    assert_fields(
        rescinded, {"state": PLAN_RESCINDED, "blocked_dependent_count": 0}, "plan"
    )
    assert_instant_equals(rescinded["rescinded_at"], SUNSET_CLOCK, "rescinded_at")

    assert (
        _edge_state(api, scenario["consumer_id"], scenario["dependency_id"])
        == COMPAT_COMPATIBLE
    )
    assert read_component(api, scenario["consumer_id"])["blocked_dependency_count"] == 0
    assert read_component(api, scenario["provider_id"])["lifecycle_state"] == LIFECYCLE_ACTIVE


def test_rescission_does_not_give_back_the_consumers_maturity(api):
    """A demotion is a governance fact and survives the compensation.

    PRD: "What is **not** given back is maturity: a consumer demoted to `BETA` with `maturity_demotion_reason` `UPSTREAM_SUNSET` stays demoted, because a demotion is a governance fact rather than a bookkeeping entry."

    Design: Difficulty/compensating_invariant/deprecation_rescission_returns_the_dependency_block_total_but_not_the_demotion
    """
    scenario = _sunset_provider_of_a_demoted_consumer(api)

    validate_success(
        api.rescind_deprecation_plan(
            scenario["plan_id"], rescind_payload(), make_design_system_lead_headers()
        )
    )

    consumer = read_component(api, scenario["consumer_id"])
    assert_fields(
        consumer,
        {
            "maturity_level": MATURITY_BETA,
            "maturity_demotion_reason": DEMOTION_REASON_UPSTREAM_SUNSET,
            "blocked_dependency_count": 0,
            "shipped_platform_count": 2,
            "coverage_state": COVERAGE_PARTIAL,
        },
        "consumer",
    )
    for implementation_id in (
        scenario["web_implementation_id"],
        scenario["ios_implementation_id"],
    ):
        assert read_implementation(api, implementation_id)["status"] == IMPL_SHIPPED
    assert read_team(api, scenario["team_id"])["blocked_implementation_count"] == 0
