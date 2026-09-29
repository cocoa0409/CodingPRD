"""
Refusals whose cause lives on a different row from the one being written.

In each scenario the row named in the request path is in a perfectly legal state;
what blocks the write is the state of a component, a team or a token set that the
request never mentions.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import (
    ERR_COMPONENT_LIFECYCLE_BLOCKS_SHIP,
    ERR_PINNED_TOKEN_SET_STALE,
    ERR_TEAM_DEBT_FROZEN,
)
from test_helpers.assertions import (
    assert_debt_points,
    assert_fields,
    assert_page_meta,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    COVERAGE_NONE,
    DEBT_STATE_FROZEN,
    DOCS_STATE_DRAFT,
    IMPL_PLANNED,
    KIND_ENHANCEMENT,
    LIFECYCLE_SUNSET,
    MATURITY_EXPERIMENTAL,
    PLAN_SUNSET,
    PLATFORM_WEB,
    PROPOSAL_READY_FOR_ACCEPTANCE,
)
from test_helpers.factories import (
    accept_payload,
    proposal_payload,
    ship_payload,
)
from test_helpers.fixtures import (
    advance_plan,
    announce_plan,
    approve_grant,
    file_audit,
    governance_base,
    leaf_token,
    make_implementation,
    make_plan,
    pin_clock,
    proposal_at_acceptance_gate,
    read_component,
    read_implementation,
    read_proposal,
    read_team,
    read_token_set,
    request_grant,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
)

SUNSET_CLOCK = "2026-08-20T00:00:00.000Z"


def _planned_implementation_of_a_sunset_component(api):
    """
    A planned implementation whose accessibility evidence is clean, owned by a
    component whose deprecation plan has already advanced into sunset.
    """
    base = governance_base(
        api,
        team_name="Disclosure Team",
        team_slug="disclosure-team",
        component_name="Accordion",
        component_slug="accordion",
    )
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/accordion-web",
    )
    file_audit(api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED)

    plan = make_plan(
        api,
        base["component_id"],
        "2026-08-01T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
        "2026-09-25T00:00:00.000Z",
    )
    announce_plan(api, plan["id"])
    pin_clock(api, SUNSET_CLOCK)
    sunset = advance_plan(api, plan["id"])
    assert sunset["state"] == PLAN_SUNSET
    assert read_component(api, base["component_id"])["lifecycle_state"] == LIFECYCLE_SUNSET

    base.update({"implementation_id": impl["id"], "plan_id": plan["id"]})
    return base


def test_shipping_is_refused_when_the_owning_component_has_reached_sunset(api):
    """The implementation is shippable; its component is not.

    PRD: "The owning component's `lifecycle_state` must be `ACTIVE` or `DEPRECATION_ANNOUNCED`; a component already at `SUNSET` or `REMOVED` refuses the ship with `ERR_COMPONENT_LIFECYCLE_BLOCKS_SHIP`."

    Design: Difficulty/cross_entity_state_dependency/ship_refused_because_owning_component_lifecycle_reached_sunset
    """
    scenario = _planned_implementation_of_a_sunset_component(api)

    validate_error(
        api.ship_implementation(
            scenario["implementation_id"],
            ship_payload(),
            make_contributing_team_headers(scenario["team_id"]),
        ),
        ERR_COMPONENT_LIFECYCLE_BLOCKS_SHIP,
        409,
    )


def test_the_refused_ship_leaves_the_implementation_planned_and_coverage_empty(api):
    """A refused first ship never stamps the shipping instant.

    PRD: "Declaration returns 201 with `status` at `PLANNED`, `conformance_score` at 0.00, `last_audit_sequence` at 0, `blocked_reason` at `NONE` and `shipped_at` null."

    Design: Difficulty/cross_entity_state_dependency/ship_refused_because_owning_component_lifecycle_reached_sunset
    """
    scenario = _planned_implementation_of_a_sunset_component(api)

    validate_error(
        api.ship_implementation(
            scenario["implementation_id"],
            ship_payload(),
            make_contributing_team_headers(scenario["team_id"]),
        ),
        ERR_COMPONENT_LIFECYCLE_BLOCKS_SHIP,
    )

    implementation = read_implementation(api, scenario["implementation_id"])
    assert_fields(
        implementation, {"status": IMPL_PLANNED, "shipped_at": None}, "implementation"
    )
    component = read_component(api, scenario["component_id"])
    assert_fields(
        component,
        {
            "shipped_platform_count": 0,
            "coverage_state": COVERAGE_NONE,
            "maturity_level": MATURITY_EXPERIMENTAL,
            "lifecycle_state": LIFECYCLE_SUNSET,
        },
        "component",
    )


def _team_frozen_by_two_approved_grants(api):
    """
    A team whose two approved grants land exactly on its debt budget.

    Each grant prices at 12 base points for a one-off component times 1.00 for web
    reach times 0.50 for an experimental component, which is 6.00.
    """
    base = governance_base(
        api,
        team_name="Overdrawn Team",
        team_slug="overdrawn-team",
        component_name="Data Grid",
        component_slug="data-grid",
        team_overrides={"debt_budget_points": 12.00, "platform_scope": "WEB_ONLY"},
    )
    for _ in range(2):
        requested = request_grant(api, base["team_id"], base["component_id"])
        approved = approve_grant(api, requested["id"])
        assert_debt_points(approved, 6.00)
    return base


def test_opening_a_proposal_is_refused_while_the_author_team_is_frozen(api):
    """The team's ledger, not the proposal payload, is what blocks the write.

    PRD: "Opening is refused with `ERR_TEAM_DEBT_FROZEN` when the authoring team's `debt_state` is `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/proposal_creation_refused_because_author_team_debt_state_is_frozen
    """
    scenario = _team_frozen_by_two_approved_grants(api)

    team = read_team(api, scenario["team_id"])
    assert_debt_points(team, 12.00, "outstanding_debt_points")
    assert team["debt_state"] == DEBT_STATE_FROZEN

    validate_error(
        api.create_proposal(
            proposal_payload(
                scenario["team_id"],
                scenario["component_id"],
                scenario["token_set_id"],
                title="Add a compact density",
                proposal_kind=KIND_ENHANCEMENT,
            ),
            make_contributing_team_headers(scenario["team_id"]),
        ),
        ERR_TEAM_DEBT_FROZEN,
        422,
    )


def test_the_frozen_team_owns_no_proposals_and_keeps_its_whole_debt(api):
    """Freezing bars the contribution pipeline without forgiving any debt.

    PRD: "A `FROZEN` team is barred from opening or submitting contribution proposals with `ERR_TEAM_DEBT_FROZEN`, as described in §3.6."

    Design: Difficulty/cross_entity_state_dependency/proposal_creation_refused_because_author_team_debt_state_is_frozen
    """
    scenario = _team_frozen_by_two_approved_grants(api)

    validate_error(
        api.create_proposal(
            proposal_payload(
                scenario["team_id"],
                scenario["component_id"],
                scenario["token_set_id"],
                title="Add a compact density",
                proposal_kind=KIND_ENHANCEMENT,
            ),
            make_contributing_team_headers(scenario["team_id"]),
        ),
        ERR_TEAM_DEBT_FROZEN,
    )

    _rows, meta = validate_paginated(
        api.list_proposals(
            make_design_system_lead_headers(),
            {"author_team_id": scenario["team_id"]},
        )
    )
    assert_page_meta(meta, total_count=0, has_more=False)

    team = read_team(api, scenario["team_id"])
    assert_debt_points(team, 12.00, "outstanding_debt_points")
    assert_debt_points(team, 12.00, "lifetime_debt_points")
    assert team["debt_state"] == DEBT_STATE_FROZEN


def _ready_proposal_whose_token_set_moved(api):
    """
    A proposal at the acceptance gate whose pinned token set has since advanced.

    One token is written into the set after both reviews were filed, which lifts
    the set's version past the version the proposal pinned at submit time.
    """
    base = proposal_at_acceptance_gate(
        api,
        proposal_kind=KIND_ENHANCEMENT,
        semver_base="4.2.0",
        team_name="Platform Team",
        team_slug="platform-team",
        component_name="Stepper",
        component_slug="stepper",
        component_overrides={"docs_state": DOCS_STATE_DRAFT},
    )
    assert base["proposal"]["pinned_token_set_version"] == 1
    leaf_token(api, base["token_set_id"], "color.stepper.rail", "#4455FF", 1)
    assert read_token_set(api, base["token_set_id"])["version"] == 2
    return base


def test_acceptance_is_refused_when_the_pinned_token_set_has_advanced(api):
    """The reviewed design no longer matches the tokens it was authored against.

    PRD: "the token set named by `pinned_token_set_id` must still have a `version` equal to the proposal's `pinned_token_set_version`, otherwise `ERR_PINNED_TOKEN_SET_STALE`, because the design was reviewed against tokens that have since moved"

    Design: Difficulty/cross_entity_state_dependency/acceptance_refused_because_pinned_token_set_version_advanced_after_review
    """
    scenario = _ready_proposal_whose_token_set_moved(api)

    component_version = read_component(api, scenario["component_id"])["version"]
    validate_error(
        api.accept_proposal(
            scenario["proposal_id"],
            accept_payload(scenario["release_id"], component_version),
            make_design_system_lead_headers(),
        ),
        ERR_PINNED_TOKEN_SET_STALE,
        409,
    )


def test_the_refused_acceptance_leaves_the_proposal_at_its_gate(api):
    """No release link, no acceptance instant and no documentation side effect.

    PRD: "A successful acceptance returns 200, moves the proposal `READY_FOR_ACCEPTANCE → ACCEPTED`, stamps `accepted_at` from the logical clock, writes `released_in_release_id` to the named release, and increments the proposal's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/acceptance_refused_because_pinned_token_set_version_advanced_after_review
    """
    scenario = _ready_proposal_whose_token_set_moved(api)

    component_version = read_component(api, scenario["component_id"])["version"]
    validate_error(
        api.accept_proposal(
            scenario["proposal_id"],
            accept_payload(scenario["release_id"], component_version),
            make_design_system_lead_headers(),
        ),
        ERR_PINNED_TOKEN_SET_STALE,
    )

    proposal = read_proposal(api, scenario["proposal_id"])
    assert_fields(
        proposal,
        {
            "state": PROPOSAL_READY_FOR_ACCEPTANCE,
            "released_in_release_id": None,
            "accepted_at": None,
            "pinned_token_set_version": 1,
        },
        "proposal",
    )
    component = read_component(api, scenario["component_id"])
    assert_fields(
        component,
        {"docs_state": DOCS_STATE_DRAFT, "current_major_version": 1},
        "component",
    )
