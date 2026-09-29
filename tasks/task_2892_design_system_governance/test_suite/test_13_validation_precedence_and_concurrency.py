"""
Which gate answers, and what a refused write leaves behind.

The gates in this API are ordered, and the order is observable: a body foreign key
answers with its own 404 rather than a shape error, a path id answers before
ownership, a remediated audit satisfies a gate its history would have failed, and
an aggregate budget refuses a grant that is individually affordable. The last two
tests cover the optimistic-concurrency fields, which guard read-modify-write
windows that no state check can see.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_COMPONENT_NOT_FOUND,
    ERR_MIGRATION_GUIDE_REQUIRED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_COMPONENT_VERSION,
    ERR_STALE_TOKEN_SET_VERSION,
    ERR_TEAM_DEBT_BUDGET_EXCEEDED,
    ERR_TEAM_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_conformance_score,
    assert_debt_points,
    assert_fields,
    assert_instant_equals,
    assert_page_meta,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    COMPAT_COMPATIBLE,
    COVERAGE_PARTIAL,
    DEBT_STATE_CLEAR,
    DEFAULT_CLOCK,
    EV_A11Y_AUTOMATED,
    EV_TOKEN_COMPLIANCE,
    EXCEPTION_ONE_OFF_COMPONENT,
    GRANT_APPROVED,
    GRANT_REQUESTED,
    GUIDE_DRAFT,
    GUIDE_MISSING,
    IMPL_SHIPPED,
    KIND_ENHANCEMENT,
    LIFECYCLE_ACTIVE,
    MATURITY_STABLE,
    PLAN_DRAFT,
    PLATFORM_WEB,
    PROPOSAL_ACCEPTED,
    PROPOSAL_READY_FOR_ACCEPTANCE,
)
from test_helpers.factories import (
    accept_payload,
    decision_payload,
    implementation_payload,
    leaf_token_payload,
    migration_guide_payload,
    token_repoint_raw_payload,
)
from test_helpers.fixtures import (
    approve_grant,
    declare_dependency,
    file_audit,
    governance_base,
    make_component,
    make_implementation,
    make_plan,
    make_team,
    make_token_set,
    pin_clock,
    proposal_at_acceptance_gate,
    read_component,
    read_grant,
    read_implementation,
    read_proposal,
    read_team,
    read_token_set,
    request_grant,
    ship,
    stable_component_with_two_platforms,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
)

UNKNOWN_TEAM_UUID = "00000000-0000-4000-8000-00000000dead"
UNKNOWN_COMPONENT_UUID = "00000000-0000-4000-8000-0000000000ff"


def test_an_unresolvable_owning_team_in_the_body_answers_with_the_team_404(api):
    """A body foreign key is an existence gate, not a shape gate.

    PRD: "Every foreign key supplied in the request body resolves, validated in the field order declared by that endpoint's input list — otherwise `ERR_TEAM_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND`, `ERR_TOKEN_SET_NOT_FOUND`, `ERR_TOKEN_NOT_FOUND` or `ERR_RELEASE_NOT_FOUND` (404)."

    Design: Corner/validations/unknown_owning_team_id_in_the_body_is_refused_by_the_fk_existence_gate
    """
    pin_clock(api)

    validate_error(
        api.create_component(
            {
                "name": "Badge",
                "slug": "badge",
                "owning_team_id": UNKNOWN_TEAM_UUID,
                "docs_state": "DRAFT",
            },
            make_design_system_lead_headers(),
        ),
        ERR_TEAM_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_components(
            make_design_system_lead_headers(), params={"limit": 100, "offset": 0}
        )
    )
    assert_page_meta(meta, total_count=0, has_more=False)


def test_the_ship_gate_reads_the_newest_automated_audit_and_not_the_history(api):
    """A remediating audit satisfies the critical-violations gate its predecessor failed.

    PRD: "The `AUTOMATED` `AA` accessibility audit with the greatest `audit_sequence` for this implementation must exist and must report `violations_critical` equal to 0; a missing audit or any open critical finding is `ERR_A11Y_CRITICAL_VIOLATIONS_OPEN`."

    PRD: "For each method it selects the single qualifying `AA` audit with the greatest `audit_sequence` and ignores every earlier one."

    Design: Corner/validations/ship_gate_reads_only_the_greatest_sequence_automated_audit
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
    )
    first = file_audit(
        api, impl["id"], base["team_id"], critical=2, method=AUDIT_METHOD_AUTOMATED
    )
    assert first["audit_sequence"] == 1
    second = file_audit(
        api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED
    )
    assert second["audit_sequence"] == 2

    shipped = ship(api, impl["id"], base["team_id"])
    assert shipped["status"] == IMPL_SHIPPED
    assert_conformance_score(shipped, 75.00)
    assert_instant_equals(shipped["shipped_at"], DEFAULT_CLOCK, "shipped_at")
    assert read_implementation(api, impl["id"])["last_audit_sequence"] == 2


def test_an_unknown_path_id_answers_before_the_ownership_check_can(api):
    """The same caller gets a 404 for a missing component and a 403 for someone else's.

    PRD: "Every id appearing in the URL path resolves to an existing row, validated left to right — otherwise the matching 404: `ERR_TEAM_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_COMPONENT_DEPENDENCY_NOT_FOUND`, `ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND`, `ERR_TOKEN_SET_NOT_FOUND`, `ERR_TOKEN_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_DEPRECATION_PLAN_NOT_FOUND` or `ERR_EXCEPTION_GRANT_NOT_FOUND`."
    PRD: "When `X-User-Role` is `ContributingTeam`, `X-User-ID` equals the owning team id of the target resource as resolved in §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/path_existence_is_checked_before_contributing_team_ownership
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    other = make_team(api, name="Growth", slug="growth", platform_scope="WEB_ONLY")
    intruder = make_contributing_team_headers(other["id"])
    body = implementation_payload(
        platform=PLATFORM_WEB,
        package_name="@growth/badge-web",
        package_version="1.0.0",
    )

    validate_error(
        api.create_implementation(UNKNOWN_COMPONENT_UUID, body, intruder),
        ERR_COMPONENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_implementation(base["component_id"], body, intruder),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )

    _rows, meta = validate_paginated(
        api.list_implementations(
            base["component_id"], make_design_system_lead_headers()
        )
    )
    assert_page_meta(meta, total_count=0, has_more=False)


def test_an_unpublished_guide_announces_an_experimental_plan_but_not_a_stable_one(api):
    """One request, two components, and only the maturity level decides the outcome.

    PRD: "One asymmetry matters: when the component's `maturity_level` is `STABLE`, `publish` must be true — a `STABLE` component may not be announced without a published guide — and a `publish` of false in that situation is `ERR_MIGRATION_GUIDE_REQUIRED`."
    PRD: "With `publish` false on a non-`STABLE` component, the operation records the `migration_guide_url`, sets `migration_guide_state` to `DRAFT`, leaves the plan's `state` at `DRAFT`, increments the plan's `version` by 1, and touches nothing else."

    Design: Corner/validations/the_publish_false_announce_gate_applies_only_to_stable_components
    """
    base = stable_component_with_two_platforms(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    badge = read_component(api, base["component_id"])
    assert_fields(
        badge,
        {"maturity_level": MATURITY_STABLE, "coverage_state": COVERAGE_PARTIAL},
        "badge",
    )
    assert_conformance_score(badge, 100.00, "governance_conformance_score")

    chip = make_component(api, base["team_id"], name="Chip", slug="chip")
    badge_plan = make_plan(
        api,
        base["component_id"],
        "2026-08-01T00:00:00.000Z",
        "2026-11-20T00:00:00.000Z",
        "2026-12-25T00:00:00.000Z",
    )
    assert_fields(
        badge_plan,
        {"required_notice_days": 105, "actual_notice_days": 111},
        "badge plan",
    )
    chip_plan = make_plan(
        api,
        chip["id"],
        "2026-08-01T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
        "2026-09-25T00:00:00.000Z",
    )
    assert chip_plan["required_notice_days"] == 14

    parked = validate_success(
        api.attach_migration_guide(
            chip_plan["id"],
            migration_guide_payload(
                migration_guide_url="https://ds.example.com/migrate/chip", publish=False
            ),
            make_design_system_lead_headers(),
        )
    )
    assert_fields(
        parked,
        {
            "state": PLAN_DRAFT,
            "migration_guide_state": GUIDE_DRAFT,
            "migration_guide_url": "https://ds.example.com/migrate/chip",
        },
        "chip plan",
    )

    validate_error(
        api.attach_migration_guide(
            badge_plan["id"],
            migration_guide_payload(
                migration_guide_url="https://ds.example.com/migrate/badge",
                publish=False,
            ),
            make_design_system_lead_headers(),
        ),
        ERR_MIGRATION_GUIDE_REQUIRED,
        422,
    )

    rows, meta = validate_paginated(
        api.list_deprecation_plans(
            base["component_id"], make_design_system_lead_headers()
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_fields(
        rows[0],
        {"state": PLAN_DRAFT, "migration_guide_state": GUIDE_MISSING},
        "badge plan",
    )
    assert rows[0]["migration_guide_url"] is None
    assert read_component(api, base["component_id"])["lifecycle_state"] == LIFECYCLE_ACTIVE


def test_two_individually_affordable_grants_breach_the_budget_together(api):
    """The budget gate compares the running total, not the single grant's price.

    PRD: "And on approval only, the requesting team's `outstanding_debt_points` plus the debt this grant would carry must not exceed the team's `debt_budget_points`; exceeding it is `ERR_TEAM_DEBT_BUDGET_EXCEEDED`."

    Two one-off grants at 10.50 each are each affordable against a 20.00 budget,
    but the second approval would take the outstanding total to 21.00.

    Design: Corner/validations/two_individually_affordable_grants_breach_the_budget_collectively
    """
    base = governance_base(
        api,
        team_slug="design-guild",
        component_slug="badge",
        team_overrides={"debt_budget_points": 20.00},
    )
    first = request_grant(
        api,
        base["team_id"],
        base["component_id"],
        expires_at="2026-10-01T00:00:00.000Z",
        exception_kind=EXCEPTION_ONE_OFF_COMPONENT,
        platform_scope="ALL",
        justification="campaign badge one",
    )
    second = request_grant(
        api,
        base["team_id"],
        base["component_id"],
        expires_at="2026-10-01T00:00:00.000Z",
        exception_kind=EXCEPTION_ONE_OFF_COMPONENT,
        platform_scope="ALL",
        justification="campaign badge two",
    )

    approved = approve_grant(api, first["id"])
    assert approved["state"] == GRANT_APPROVED
    assert_debt_points(approved, 10.50)
    after_first = read_team(api, base["team_id"])
    assert_debt_points(after_first, 10.50, "outstanding_debt_points")
    assert after_first["debt_state"] == DEBT_STATE_CLEAR

    validate_error(
        api.decide_exception_grant(
            second["id"],
            decision_payload("APPROVE"),
            make_design_system_lead_headers(),
        ),
        ERR_TEAM_DEBT_BUDGET_EXCEEDED,
        422,
    )

    untouched = read_grant(api, second["id"])
    assert untouched["state"] == GRANT_REQUESTED
    assert_debt_points(untouched, 0.00)
    assert untouched["decided_at"] is None

    after_refusal = read_team(api, base["team_id"])
    assert_debt_points(after_refusal, 10.50, "outstanding_debt_points")
    assert_debt_points(after_refusal, 10.50, "lifetime_debt_points")
    assert after_refusal["debt_state"] == DEBT_STATE_CLEAR


def test_a_component_version_read_before_a_new_dependency_edge_is_stale(api):
    """A write the lead never made moved the version the acceptance echoes.

    PRD: "The optimistic-concurrency field matches its parent's current `version`: `expected_component_version` against the target component on acceptance, `expected_token_set_version` against the token set on every token write — otherwise `ERR_STALE_COMPONENT_VERSION` or `ERR_STALE_TOKEN_SET_VERSION` (412)."
    PRD: "The consumer component's `blocked_dependency_count` is then recomputed as the number of its outgoing edges whose `compatibility_state` is `INCOMPATIBLE` or `SUNSET_PROVIDER`, and the consumer component's `version` is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/accept_with_a_component_version_read_before_a_dependency_edge_is_stale
    """
    base = proposal_at_acceptance_gate(
        api,
        proposal_kind=KIND_ENHANCEMENT,
        semver_base="1.0.0",
        team_slug="design-guild",
        component_name="Badge",
        component_slug="badge",
    )
    assert base["required_evidence_kinds"] == [EV_A11Y_AUTOMATED, EV_TOKEN_COMPLIANCE]
    assert (
        base["engineering_review"]["resulting_proposal_state"]
        == PROPOSAL_READY_FOR_ACCEPTANCE
    )

    version_before = read_component(api, base["component_id"])["version"]
    provider = make_component(api, base["team_id"], name="Icon", slug="icon")
    edge = declare_dependency(api, base["component_id"], provider["id"], 1)
    assert edge["compatibility_state"] == COMPAT_COMPATIBLE
    version_now = read_component(api, base["component_id"])["version"]
    assert version_now == version_before + 1, (
        "declaring an outgoing edge must increment the consumer component's version"
    )

    validate_error(
        api.accept_proposal(
            base["proposal_id"],
            accept_payload(base["release_id"], version_before),
            make_design_system_lead_headers(),
        ),
        ERR_STALE_COMPONENT_VERSION,
        412,
    )
    parked = read_proposal(api, base["proposal_id"])
    assert parked["state"] == PROPOSAL_READY_FOR_ACCEPTANCE
    assert parked["released_in_release_id"] is None
    assert parked["accepted_at"] is None

    accepted = validate_success(
        api.accept_proposal(
            base["proposal_id"],
            accept_payload(base["release_id"], version_now),
            make_design_system_lead_headers(),
        )
    )
    assert accepted["state"] == PROPOSAL_ACCEPTED
    assert accepted["released_in_release_id"] == base["release_id"]
    assert_instant_equals(accepted["accepted_at"], DEFAULT_CLOCK, "accepted_at")


def test_a_second_token_write_replaying_the_first_reads_version_is_stale(api):
    """Every token write moves the parent set, so the version cannot be reused.

    PRD: "Every token write also carries `expected_token_set_version` as described in §2.6."
    PRD: "A successful write returns 201, recomputes the set's `token_count` and `max_alias_depth`, and increments the token set's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/a_second_token_write_with_the_first_reads_version_is_stale
    """
    pin_clock(api)
    token_set = make_token_set(api, name="Core", slug="core")
    assert token_set["version"] == 1

    first = validate_success(
        api.create_token(
            leaf_token_payload(token_set["id"], "color.surface", "#FFFFFF", 1),
            make_design_system_lead_headers(),
        ),
        201,
    )

    validate_error(
        api.create_token(
            leaf_token_payload(
                token_set["id"], "space.md", "16px", 1, category="SPACING"
            ),
            make_design_system_lead_headers(),
        ),
        ERR_STALE_TOKEN_SET_VERSION,
        412,
    )
    mid = read_token_set(api, token_set["id"])
    assert_fields(mid, {"version": 2, "token_count": 1}, "token set")

    second = validate_success(
        api.create_token(
            leaf_token_payload(
                token_set["id"], "space.md", "16px", 2, category="SPACING"
            ),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert second["id"] != first["id"]
    assert second["resolved_value"] == "16px"
    after = read_token_set(api, token_set["id"])
    assert_fields(after, {"version": 3, "token_count": 2}, "token set")

    updated = validate_success(
        api.update_token(
            second["id"],
            token_repoint_raw_payload("20px", 3),
            make_design_system_lead_headers(),
        )
    )
    assert_fields(updated, {"resolved_value": "20px", "version": 2}, "token")
    assert read_token_set(api, token_set["id"])["version"] == 4
