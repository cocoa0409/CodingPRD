"""
Where the declared machines open, what one transition writes, and what they refuse.

Four independent state machines run in this API and none of them may skip ahead
because a later gate happens to be satisfiable. The tests here pin each machine's
opening position, the full side-effect set of a single admitted transition, and
the refusals guarding ownership, undeclared transitions, terminal states and the
logical clock.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DEPRECATION_ADVANCE_NOT_DUE,
    ERR_INVALID_IMPLEMENTATION_STATE,
    ERR_INVALID_PROPOSAL_STATE,
    ERR_INVALID_RELEASE_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REVISION_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_ascending,
    assert_breaking_ratio,
    assert_conformance_score,
    assert_debt_points,
    assert_fields,
    assert_instant_equals,
    assert_page_meta,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    BLOCKED_REASON_NONE,
    CLASS_PATCH,
    COVERAGE_WEB_ONLY,
    DEFAULT_CLOCK,
    DOCS_STATE_PUBLISHED,
    EV_A11Y_AUTOMATED,
    EV_DOC_PAGE,
    EV_TOKEN_COMPLIANCE,
    EXCEPTION_RAW_TOKEN_USAGE,
    GRANT_REQUESTED,
    GUIDE_DRAFT,
    GUIDE_PUBLISHED,
    IMPL_PLANNED,
    IMPL_SHIPPED,
    KIND_ENHANCEMENT,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DEPRECATION_ANNOUNCED,
    NOTES_PUBLISHED,
    PLAN_ANNOUNCED,
    PLAN_DRAFT,
    PLATFORM_WEB,
    PROPOSAL_ACCEPTED,
    PROPOSAL_CHANGES_REQUESTED,
    PROPOSAL_DESIGN_CRITIQUE,
    PROPOSAL_DRAFT,
    RELEASE_PUBLISHED,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    TIER_INCREMENTAL,
    VERDICT_APPROVE,
    VERDICT_REQUEST_CHANGES,
)
from test_helpers.factories import (
    accept_payload,
    deprecation_plan_payload,
    exception_grant_payload,
    implementation_payload,
    proposal_payload,
    ship_payload,
)
from test_helpers.fixtures import (
    accept,
    announce_plan,
    file_audit,
    file_evidence,
    governance_base,
    leaf_token,
    make_implementation,
    make_plan,
    make_proposal,
    make_release,
    make_team,
    read_component,
    read_implementation,
    read_proposal,
    read_team,
    read_token_set,
    review,
    ship,
    submit,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
    make_system_admin_headers,
)

ENHANCEMENT_EVIDENCE = [EV_A11Y_AUTOMATED, EV_TOKEN_COMPLIANCE]


def test_the_four_machines_each_open_in_their_declared_initial_state(api):
    """A first write opens each machine at its start, never one step further on.

    PRD: "A successful open returns 201 with `state` at `DRAFT`, `revision_round` at 0, both `required_evidence_kinds` and `submitted_evidence_kinds` as empty arrays, and `released_in_release_id`, `pinned_token_set_version`, `raw_change_class`, `effective_change_class`, `design_critique_reviewer_user_id`, `engineering_reviewer_user_id`, `submitted_at` and `accepted_at` all null."
    PRD: "The grant is created with a 201 response in `state` `REQUESTED`, with `debt_points` at 0.00, and with `pinned_maturity_level`, `decided_by_user_id`, `decided_at` and `repaid_at` all null."
    PRD: "The plan takes its `component_id` from the request path, is created with a 201 response in `state` `DRAFT` with `blocked_dependent_count` at 0 and `rescinded_at` null, and its `migration_guide_state` starts at `DRAFT` when a `migration_guide_url` was supplied and at `MISSING` otherwise."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    team_headers = make_contributing_team_headers(base["team_id"])

    proposal = validate_success(
        api.create_proposal(
            proposal_payload(
                base["team_id"],
                base["component_id"],
                base["token_set_id"],
                title="Badge density tweak",
                proposal_kind=KIND_ENHANCEMENT,
                touches_public_api=False,
            ),
            team_headers,
        ),
        201,
    )
    assert_fields(
        proposal,
        {
            "state": PROPOSAL_DRAFT,
            "revision_round": 0,
            "required_evidence_kinds": [],
            "submitted_evidence_kinds": [],
        },
        "proposal",
    )
    assert proposal["submitted_at"] is None
    assert proposal["accepted_at"] is None
    assert proposal["pinned_token_set_version"] is None

    implementation = validate_success(
        api.create_implementation(
            base["component_id"],
            implementation_payload(
                platform=PLATFORM_WEB,
                package_name="@ds/badge-web",
                package_version="1.0.0",
                token_compliance_ratio=0.95,
            ),
            team_headers,
        ),
        201,
    )
    assert implementation["status"] == IMPL_PLANNED

    grant = validate_success(
        api.create_exception_grant(
            exception_grant_payload(
                base["team_id"],
                base["component_id"],
                "2026-10-01T00:00:00.000Z",
                exception_kind=EXCEPTION_RAW_TOKEN_USAGE,
                platform_scope=PLATFORM_WEB,
                justification="temporary hard-coded brand blue",
            ),
            team_headers,
        ),
        201,
    )
    assert grant["state"] == GRANT_REQUESTED
    assert_debt_points(grant, 0.00)
    assert grant["pinned_maturity_level"] is None

    plan = validate_success(
        api.create_deprecation_plan(
            base["component_id"],
            deprecation_plan_payload(
                "2026-08-01T00:00:00.000Z",
                "2026-08-20T00:00:00.000Z",
                "2026-09-25T00:00:00.000Z",
                migration_guide_url="https://ds.example.com/migrate/badge",
            ),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert_fields(
        plan,
        {"state": PLAN_DRAFT, "migration_guide_state": GUIDE_DRAFT, "blocked_dependent_count": 0},
        "plan",
    )
    assert plan["rescinded_at"] is None

    assert_debt_points(read_team(api, base["team_id"]), 0.00, "outstanding_debt_points")
    assert read_component(api, base["component_id"])["lifecycle_state"] == LIFECYCLE_ACTIVE


def test_one_submit_executes_every_declared_side_effect_at_once(api):
    """The submit pins the token version that is current now, not the one at open time.

    PRD: "Both submits stamp `submitted_at` from the logical clock, pin `pinned_token_set_version` to the current `version` of the token set named by `pinned_token_set_id` (a re-pin on every resubmit; the staleness re-validation happens later, at acceptance), recompute `required_evidence_kinds`, increment the proposal's `version` by 1, and return 200."
    PRD: "The base requirement follows `proposal_kind`: a `NEW_COMPONENT` requires `A11Y_AUTOMATED`, `A11Y_MANUAL`, `DOC_PAGE` and `TOKEN_COMPLIANCE`; an `ENHANCEMENT` requires only `A11Y_AUTOMATED` and `TOKEN_COMPLIANCE`; and a `BREAKING_CHANGE` requires `A11Y_AUTOMATED`, `A11Y_MANUAL`, `DOC_PAGE`, `MIGRATION_GUIDE` and `TOKEN_COMPLIANCE`."

    Design: Corner/state_machines/proposal_submit_pins_token_version_and_freezes_the_evidence_set
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    leaf_token(api, base["token_set_id"], "color.brand.base", "#0055FF", 1)
    assert read_token_set(api, base["token_set_id"])["version"] == 2

    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge density tweak",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    assert_fields(
        submitted,
        {
            "state": PROPOSAL_DESIGN_CRITIQUE,
            "revision_round": 1,
            "pinned_token_set_version": 2,
            "required_evidence_kinds": ENHANCEMENT_EVIDENCE,
            "submitted_evidence_kinds": [],
        },
        "proposal",
    )
    assert_instant_equals(submitted["submitted_at"], DEFAULT_CLOCK, "submitted_at")


def test_a_second_team_cannot_submit_a_proposal_it_does_not_author(api):
    """Ownership is compared against the identity header, not against the role name.

    PRD: "When `X-User-Role` is `ContributingTeam`, `X-User-ID` equals the owning team id of the target resource as resolved in §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/state_machines/submit_by_a_team_that_does_not_own_the_proposal_is_refused
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    intruder = make_team(
        api, name="Intruder", slug="intruder", platform_scope="WEB_ONLY"
    )
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge density tweak",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )

    validate_error(
        api.submit_proposal(
            proposal["id"], make_contributing_team_headers(intruder["id"])
        ),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )

    unchanged = read_proposal(api, proposal["id"])
    assert_fields(
        unchanged, {"state": PROPOSAL_DRAFT, "revision_round": 0}, "proposal"
    )
    assert unchanged["submitted_at"] is None


def test_acceptance_is_not_reachable_from_the_design_critique_position(api):
    """The acceptance transition leaves READY_FOR_ACCEPTANCE and nowhere else.

    PRD: "The target resource is in a state from which the requested transition is declared — otherwise `ERR_INVALID_PROPOSAL_STATE`, `ERR_INVALID_COMPONENT_MATURITY_TRANSITION`, `ERR_INVALID_IMPLEMENTATION_STATE`, `ERR_INVALID_DEPRECATION_PLAN_STATE`, `ERR_INVALID_EXCEPTION_GRANT_STATE` or `ERR_INVALID_RELEASE_STATE` (409). Applies to every state-changing write."

    Design: Corner/state_machines/accept_attempted_from_design_critique_is_not_a_declared_transition
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge density tweak",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    assert submitted["state"] == PROPOSAL_DESIGN_CRITIQUE
    file_evidence(api, proposal["id"], base["team_id"], ENHANCEMENT_EVIDENCE)
    release = make_release(api, "1.0.0")

    validate_error(
        api.accept_proposal(
            proposal["id"],
            accept_payload(release["id"], base["component"]["version"]),
            make_design_system_lead_headers(),
        ),
        ERR_INVALID_PROPOSAL_STATE,
        409,
    )

    unchanged = read_proposal(api, proposal["id"])
    assert unchanged["state"] == PROPOSAL_DESIGN_CRITIQUE
    assert unchanged["released_in_release_id"] is None
    assert unchanged["accepted_at"] is None


def test_a_published_release_refuses_a_second_publication(api):
    """PUBLISHED is terminal, so the second call cannot re-run the arithmetic.

    PRD: "Its `state` has only two values, `DRAFT` and the terminal `PUBLISHED`."
    PRD: "Three preconditions apply: the release must be in `DRAFT`, otherwise `ERR_INVALID_RELEASE_STATE`; at least one contribution proposal must have its `released_in_release_id` pointing at this release with `state` `ACCEPTED`, otherwise `ERR_INVALID_RELEASE_STATE` again, because an empty release has nothing to version; and — evaluated **after** the version arithmetic below has run — every carried proposal whose `effective_change_class` came out as `MAJOR` must carry `MIGRATION_GUIDE` in its `submitted_evidence_kinds`, otherwise `ERR_MIGRATION_GUIDE_REQUIRED`."

    Design: Corner/state_machines/republishing_a_published_release_is_refused_from_its_terminal_state
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge density tweak",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )
    submit(api, proposal["id"], base["team_id"])
    file_evidence(
        api,
        proposal["id"],
        base["team_id"],
        [EV_A11Y_AUTOMATED, EV_TOKEN_COMPLIANCE, EV_DOC_PAGE],
    )
    review(api, proposal["id"], STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE)
    review(api, proposal["id"], STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE)

    release = make_release(api, "2.3.4")
    accepted = accept(
        api, proposal["id"], release["id"], base["component"]["version"]
    )
    assert accepted["state"] == PROPOSAL_ACCEPTED
    assert read_component(api, base["component_id"])["docs_state"] == DOCS_STATE_PUBLISHED

    published = validate_success(
        api.publish_release(release["id"], make_system_admin_headers())
    )
    assert_fields(
        published,
        {
            "state": RELEASE_PUBLISHED,
            "semver": "2.3.5",
            "policy_tier": TIER_INCREMENTAL,
            "breaking_change_count": 0,
            "escalated_proposal_count": 0,
            "release_notes_state": NOTES_PUBLISHED,
        },
        "release",
    )
    assert_breaking_ratio(published, 0.0000)
    assert_instant_equals(published["published_at"], DEFAULT_CLOCK, "published_at")

    validate_error(
        api.publish_release(release["id"], make_system_admin_headers()),
        ERR_INVALID_RELEASE_STATE,
        409,
    )

    carried, meta = validate_paginated(
        api.list_proposals(
            make_design_system_lead_headers(),
            params={"released_in_release_id": release["id"]},
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_fields(
        carried[0],
        {"state": PROPOSAL_ACCEPTED, "effective_change_class": CLASS_PATCH},
        "carried proposal",
    )


def test_a_shipped_implementation_refuses_a_second_shipment(api):
    """Shipping opens from PLANNED and from BLOCKED, never from SHIPPED itself.

    PRD: "Shipping is available from exactly two positions on the implementation's state machine — `PLANNED → SHIPPED` for a first release and `BLOCKED → SHIPPED` for a recovery — and attempting it from `SHIPPED` or from the terminal `RETIRED` is `ERR_INVALID_IMPLEMENTATION_STATE`."

    Design: Corner/state_machines/shipping_an_already_shipped_implementation_twice_is_refused
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
        package_version="1.0.0",
    )
    audit = file_audit(
        api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED
    )
    assert audit["defect_load"] == 0

    shipped = ship(api, impl["id"], base["team_id"], package_version="1.0.0")
    assert_fields(
        shipped,
        {
            "status": IMPL_SHIPPED,
            "blocked_reason": BLOCKED_REASON_NONE,
            "package_version": "1.0.0",
        },
        "implementation",
    )
    assert_instant_equals(shipped["shipped_at"], DEFAULT_CLOCK, "shipped_at")
    assert_conformance_score(shipped, 75.00)
    component = read_component(api, base["component_id"])
    assert_fields(
        component,
        {"shipped_platform_count": 1, "coverage_state": COVERAGE_WEB_ONLY},
        "component",
    )
    assert_conformance_score(component, 75.00, "governance_conformance_score")

    validate_error(
        api.ship_implementation(
            impl["id"],
            ship_payload(package_version="1.0.1", token_compliance_ratio=0.99),
            make_contributing_team_headers(base["team_id"]),
        ),
        ERR_INVALID_IMPLEMENTATION_STATE,
        409,
    )

    unchanged = read_implementation(api, impl["id"])
    assert_fields(
        unchanged,
        {
            "status": IMPL_SHIPPED,
            "package_version": "1.0.0",
            "token_compliance_ratio": 0.95,
        },
        "implementation",
    )


def test_a_fourth_submit_is_refused_rather_than_clamped_to_round_three(api):
    """The revision counter terminates the loop instead of saturating at its cap.

    PRD: "The revision cap is a refusal, not a silent clamp: a fourth round is rejected rather than capped at three."

    Design: Corner/state_machines/fourth_submit_hits_the_revision_round_termination_condition
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge density tweak",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )

    for expected_round in (1, 2, 3):
        submitted = submit(api, proposal["id"], base["team_id"])
        assert_fields(
            submitted,
            {"state": PROPOSAL_DESIGN_CRITIQUE, "revision_round": expected_round},
            f"proposal at round {expected_round}",
        )
        verdict = review(
            api, proposal["id"], STAGE_DESIGN_CRITIQUE, VERDICT_REQUEST_CHANGES
        )
        assert_fields(
            verdict,
            {
                "revision_round": expected_round,
                "resulting_proposal_state": PROPOSAL_CHANGES_REQUESTED,
            },
            f"review at round {expected_round}",
        )

    validate_error(
        api.submit_proposal(
            proposal["id"], make_contributing_team_headers(base["team_id"])
        ),
        ERR_REVISION_LIMIT_EXCEEDED,
        422,
    )

    stuck = read_proposal(api, proposal["id"])
    assert_fields(
        stuck,
        {"state": PROPOSAL_CHANGES_REQUESTED, "revision_round": 3},
        "proposal",
    )

    rows, meta = validate_paginated(
        api.list_reviews(proposal["id"], make_design_system_lead_headers())
    )
    assert_page_meta(meta, total_count=3, has_more=False)
    assert [row["revision_round"] for row in rows] == [1, 2, 3]
    assert_ascending(rows, "created_at")


def test_an_announced_plan_cannot_advance_before_its_sunset_instant(api):
    """The clock, not the announcement, is what opens the sunset step.

    PRD: "In both steps the logical clock must have reached the due instant — at or past `sunset_at` for the first, at or past `removal_at` for the second — otherwise `ERR_DEPRECATION_ADVANCE_NOT_DUE`."

    Design: Corner/state_machines/advancing_an_announced_plan_before_its_sunset_instant_is_refused
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    plan = make_plan(
        api,
        base["component_id"],
        "2026-08-01T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
        "2026-09-25T00:00:00.000Z",
    )
    assert_fields(
        plan,
        {
            "state": PLAN_DRAFT,
            "required_notice_days": 14,
            "actual_notice_days": 19,
        },
        "plan",
    )

    announced = announce_plan(api, plan["id"])
    assert_fields(
        announced,
        {"state": PLAN_ANNOUNCED, "migration_guide_state": GUIDE_PUBLISHED},
        "plan",
    )
    assert (
        read_component(api, base["component_id"])["lifecycle_state"]
        == LIFECYCLE_DEPRECATION_ANNOUNCED
    )

    validate_error(
        api.advance_deprecation_plan(plan["id"], make_design_system_lead_headers()),
        ERR_DEPRECATION_ADVANCE_NOT_DUE,
        409,
    )

    still_announced = read_component(api, base["component_id"])
    assert still_announced["lifecycle_state"] == LIFECYCLE_DEPRECATION_ANNOUNCED
    rows, meta = validate_paginated(
        api.list_deprecation_plans(
            base["component_id"], make_design_system_lead_headers()
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_fields(rows[0], {"state": PLAN_ANNOUNCED}, "plan")
