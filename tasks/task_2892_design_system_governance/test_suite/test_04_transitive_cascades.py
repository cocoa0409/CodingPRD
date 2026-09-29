"""
Cascades that travel several hops away from the request that started them.

Each hop fires because the previous hop mutated a row, not because the original
call named the row, so the interesting assertions are the ones several joins away
from the endpoint that was invoked.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.constants import (
    BLOCKED_REASON_UPSTREAM_BREAKING_CHANGE,
    COMPAT_COMPATIBLE,
    COMPAT_INCOMPATIBLE,
    COMPAT_SUNSET_PROVIDER,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    DEMOTION_REASON_UPSTREAM_SUNSET,
    DOCS_STATE_PUBLISHED,
    IMPL_BLOCKED,
    IMPL_SHIPPED,
    KIND_BREAKING_CHANGE,
    LIFECYCLE_SUNSET,
    MATURITY_BETA,
    MATURITY_STABLE,
    PLAN_SUNSET,
    PLATFORM_IOS,
    PLATFORM_WEB,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    VERDICT_APPROVE,
)
from test_helpers.fixtures import (
    accept,
    advance_plan,
    announce_plan,
    declare_dependency,
    file_clean_evidence,
    file_evidence,
    governance_base,
    make_component,
    make_implementation,
    make_plan,
    make_proposal,
    make_release,
    pin_clock,
    promote,
    provider_and_consumer,
    read_component,
    read_implementation,
    read_team,
    review,
    ship,
    submit,
)
from test_helpers.test_users import make_design_system_lead_headers

SUNSET_CLOCK = "2026-08-20T00:00:00.000Z"


def _read_edge(api, component_id, edge_id):
    """Read one dependency edge back through the listing that owns it."""
    rows, _meta = validate_paginated(
        api.list_dependencies(component_id, make_design_system_lead_headers())
    )
    matches = [row for row in rows if row["id"] == edge_id]
    assert matches, f"edge {edge_id} is not listed under component {component_id}"
    return matches[0]


def _breaking_change_accepted_on_a_consumed_provider(api):
    """
    A provider whose breaking change has just been accepted, with one consumer
    pinned to the major version the provider has now moved past.
    """
    base = provider_and_consumer(api, pinned_provider_major=1)
    impl = make_implementation(
        api,
        base["consumer_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/menu-button-web",
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    ship(api, impl["id"], base["team_id"])

    proposal = make_proposal(
        api,
        base["team_id"],
        base["provider_id"],
        base["token_set_id"],
        title="Drop the deprecated icon size prop",
        proposal_kind=KIND_BREAKING_CHANGE,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    file_evidence(
        api, proposal["id"], base["team_id"], list(submitted["required_evidence_kinds"])
    )
    review(api, proposal["id"], STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE)
    review(api, proposal["id"], STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE)
    release = make_release(api, "1.4.0")
    provider_version = read_component(api, base["provider_id"])["version"]
    accepted = accept(api, proposal["id"], release["id"], provider_version)

    base.update(
        {
            "implementation_id": impl["id"],
            "release_id": release["id"],
            "proposal_id": proposal["id"],
            "accepted": accepted,
        }
    )
    return base


def test_accepting_a_breaking_change_bumps_the_major_and_flips_the_pinned_edge(api):
    """Hops one and two: the major moves and the stale pin turns incompatible.

    PRD: "**Hop 2** fires because hop 1 changed `current_major_version`. Every dependency edge whose `provider_component_id` is this component and whose `pinned_provider_major` is now less than the new `current_major_version` flips from `COMPATIBLE` to `INCOMPATIBLE`, and each affected consumer component's `blocked_dependency_count` is recomputed upward."

    Design: Difficulty/transitive_cascade/breaking_change_accept_cascades_four_hops_to_team_counter
    """
    scenario = _breaking_change_accepted_on_a_consumed_provider(api)

    provider = read_component(api, scenario["provider_id"])
    assert_fields(
        provider,
        {
            "current_major_version": 2,
            "pending_breaking_change_count": 1,
            "docs_state": DOCS_STATE_PUBLISHED,
        },
        "provider",
    )

    edge = _read_edge(api, scenario["consumer_id"], scenario["dependency_id"])
    assert_fields(
        edge,
        {"pinned_provider_major": 1, "compatibility_state": COMPAT_INCOMPATIBLE},
        "edge",
    )
    assert read_component(api, scenario["consumer_id"])["blocked_dependency_count"] == 1


def test_the_breaking_change_cascade_reaches_the_owning_teams_counter(api):
    """Hops three and four: the shipped platform blocks and the team counter rises.

    PRD: "**Hop 4** fires because hop 3 changed those implementations' `status`. For each affected consumer, the `blocked_implementation_count` of the team named by its `owning_team_id` is recomputed upward."

    Design: Difficulty/transitive_cascade/breaking_change_accept_cascades_four_hops_to_team_counter
    """
    scenario = _breaking_change_accepted_on_a_consumed_provider(api)

    implementation = read_implementation(api, scenario["implementation_id"])
    assert_fields(
        implementation,
        {
            "status": IMPL_BLOCKED,
            "blocked_reason": BLOCKED_REASON_UPSTREAM_BREAKING_CHANGE,
        },
        "implementation",
    )
    consumer = read_component(api, scenario["consumer_id"])
    assert_fields(
        consumer,
        {"shipped_platform_count": 0, "coverage_state": COVERAGE_NONE},
        "consumer",
    )
    assert read_team(api, scenario["team_id"])["blocked_implementation_count"] == 1


def _stable_consumer_of_a_sunset_provider(api):
    """
    A stable consumer whose provider has just been advanced into sunset.

    The provider is experimental with no shipped platform, so its notice window is
    the shortest the policy allows; the consumer reaches stable through two clean
    platform ships and a published documentation page.
    """
    base = governance_base(api, component_name="Icon Core", component_slug="icon-core")
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
    assert edge["compatibility_state"] == COMPAT_COMPATIBLE

    promote(api, consumer["id"], MATURITY_BETA)
    stable = promote(api, consumer["id"], MATURITY_STABLE)
    assert_fields(
        stable,
        {"maturity_level": MATURITY_STABLE, "coverage_state": COVERAGE_PARTIAL},
        "consumer",
    )

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

    base.update(
        {
            "provider_id": provider_id,
            "consumer_id": consumer["id"],
            "web_implementation_id": web["id"],
            "ios_implementation_id": ios["id"],
            "dependency_id": edge["id"],
            "plan_id": plan["id"],
            "plan": sunset,
            "baseline_at": stable["conformance_baseline_at"],
        }
    )
    return base


def test_provider_sunset_flips_the_edge_and_counts_its_blocked_dependents(api):
    """Hops one and two: the lifecycle moves and every compatible edge is cut.

    PRD: "**Hop 2** fires because hop 1 changed the component's `lifecycle_state`: every dependency edge whose `provider_component_id` is this component and whose `compatibility_state` is `COMPATIBLE` flips to `SUNSET_PROVIDER`; each affected consumer component's `blocked_dependency_count` is recomputed upward; and the plan's `blocked_dependent_count` is set to the number of consumer components whose count rose."

    Design: Difficulty/transitive_cascade/provider_sunset_cascades_three_hops_and_demotes_stable_consumer
    """
    scenario = _stable_consumer_of_a_sunset_provider(api)

    assert_fields(
        scenario["plan"],
        {"state": PLAN_SUNSET, "blocked_dependent_count": 1},
        "plan",
    )
    assert read_component(api, scenario["provider_id"])["lifecycle_state"] == LIFECYCLE_SUNSET

    edge = _read_edge(api, scenario["consumer_id"], scenario["dependency_id"])
    assert edge["compatibility_state"] == COMPAT_SUNSET_PROVIDER
    assert read_component(api, scenario["consumer_id"])["blocked_dependency_count"] == 1


def test_the_sunset_cascade_demotes_the_stable_consumer_without_touching_its_ships(api):
    """Hop three demotes maturity and leaves the baseline and the ships alone.

    PRD: "**Hop 3** fires because hop 2 raised those counts: every affected consumer component whose `maturity_level` is `STABLE` is demoted to `BETA` with `maturity_demotion_reason` set to `UPSTREAM_SUNSET`, and its `conformance_baseline_at` is left untouched."

    The sunset cascade stops at maturity: both implementations stay SHIPPED, so
    coverage still reads PARTIAL and the team's blocked counter never moves.

    Design: Difficulty/transitive_cascade/provider_sunset_cascades_three_hops_and_demotes_stable_consumer
    """
    scenario = _stable_consumer_of_a_sunset_provider(api)

    consumer = read_component(api, scenario["consumer_id"])
    assert_fields(
        consumer,
        {
            "maturity_level": MATURITY_BETA,
            "maturity_demotion_reason": DEMOTION_REASON_UPSTREAM_SUNSET,
            "shipped_platform_count": 2,
            "coverage_state": COVERAGE_PARTIAL,
        },
        "consumer",
    )
    assert_instant_equals(
        consumer["conformance_baseline_at"],
        scenario["baseline_at"],
        "consumer.conformance_baseline_at",
    )
    for implementation_id in (
        scenario["web_implementation_id"],
        scenario["ios_implementation_id"],
    ):
        assert read_implementation(api, implementation_id)["status"] == IMPL_SHIPPED
    assert read_team(api, scenario["team_id"])["blocked_implementation_count"] == 0
