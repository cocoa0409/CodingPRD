"""
The derived numbers, one formula at a time.

Coverage is an enumeration rather than a count, the two conformance views run the
same weighted arithmetic over different evidence sets, adoption rounds twice on
the way to an index, alias walks are bounded in both depth and topology, and
exception debt is priced per grant before it is ever summed. Each test here fixes
one of those computations against a figure that only the declared formula gives.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_ACCEPTANCE_EVIDENCE_INCOMPLETE,
    ERR_TOKEN_ALIAS_CYCLE,
    ERR_TOKEN_ALIAS_DEPTH_EXCEEDED,
)
from test_helpers.assertions import (
    assert_conformance_score,
    assert_debt_points,
    assert_decimal_equals,
    assert_decimal_places,
    assert_defect_load,
    assert_fields,
    assert_instant_equals,
    assert_page_meta,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    AUDIT_METHOD_MANUAL,
    COVERAGE_FULL,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    COVERAGE_WEB_ONLY,
    DASHBOARD_VIEW_LATEST,
    DASHBOARD_VIEW_TRAILING,
    DEBT_STATE_CLEAR,
    DEFAULT_CLOCK,
    EV_A11Y_AUTOMATED,
    EV_PLATFORM_PARITY,
    EV_TOKEN_COMPLIANCE,
    EXCEPTION_FORK_OF_SYSTEM_COMPONENT,
    EXCEPTION_ONE_OFF_COMPONENT,
    GRANT_APPROVED,
    IMPL_PLANNED,
    IMPL_SHIPPED,
    KIND_ENHANCEMENT,
    MATURITY_EXPERIMENTAL,
    PLATFORM_ANDROID,
    PLATFORM_IOS,
    PLATFORM_WEB,
    PROPOSAL_READY_FOR_ACCEPTANCE,
    SCAN_KIND_CODE_SCAN,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    VERDICT_APPROVE,
)
from test_helpers.factories import (
    accept_payload,
    adoption_scan_payload,
    alias_token_payload,
    token_repoint_alias_payload,
)
from test_helpers.fixtures import (
    alias_chain,
    approve_grant,
    file_audit,
    file_evidence,
    governance_base,
    leaf_token,
    make_implementation,
    make_release,
    make_proposal,
    make_team,
    make_token_set,
    pin_clock,
    read_component,
    read_grant,
    read_implementation,
    read_team,
    read_token_set,
    request_grant,
    review,
    ship,
    submit,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
)


def _three_platform_component(api):
    """A component with WEB, IOS and ANDROID declared, each cleared to ship."""
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    ids = {}
    for platform, package in (
        (PLATFORM_WEB, "@ds/badge-web"),
        (PLATFORM_IOS, "DSBadge"),
        (PLATFORM_ANDROID, "com.acme.ds.badge"),
    ):
        impl = make_implementation(
            api,
            base["component_id"],
            base["team_id"],
            platform=platform,
            package_name=package,
        )
        file_audit(
            api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED
        )
        ids[platform] = impl["id"]
    base["implementation_ids"] = ids
    return base


def test_coverage_walks_web_only_then_partial_then_full_as_platforms_ship(api):
    """Coverage is membership of the shipped platform set, not its cardinality.

    PRD: "Coverage is derived from the set of *distinct* platforms among the component's implementations whose `status` is exactly `SHIPPED`."
    PRD: "`PARTIAL` when the set contains `WEB` and exactly one of `IOS` and `ANDROID`;"
    PRD: "`FULL` when the set contains `WEB` and both `IOS` and `ANDROID`."

    Design: Corner/calculations/coverage_state_walks_web_only_then_partial_then_full_as_platforms_ship
    """
    scenario = _three_platform_component(api)
    ids = scenario["implementation_ids"]

    ship(api, ids[PLATFORM_WEB], scenario["team_id"])
    after_web = read_component(api, scenario["component_id"])
    assert_fields(
        after_web,
        {"coverage_state": COVERAGE_WEB_ONLY, "shipped_platform_count": 1},
        "component after WEB",
    )

    ship(api, ids[PLATFORM_IOS], scenario["team_id"])
    after_ios = read_component(api, scenario["component_id"])
    assert_fields(
        after_ios,
        {"coverage_state": COVERAGE_PARTIAL, "shipped_platform_count": 2},
        "component after IOS",
    )

    android = ship(api, ids[PLATFORM_ANDROID], scenario["team_id"])
    assert android["status"] == IMPL_SHIPPED
    after_android = read_component(api, scenario["component_id"])
    assert_fields(
        after_android,
        {"coverage_state": COVERAGE_FULL, "shipped_platform_count": 3},
        "component after ANDROID",
    )
    assert_conformance_score(after_android, 75.00, "governance_conformance_score")


def test_the_governance_rollup_ignores_a_planned_implementations_bad_audit(api):
    """The minimum is taken over live platforms only, so a planned row cannot drag it.

    PRD: "Consider the component's implementations whose `status` is `SHIPPED` or `BLOCKED`."
    PRD: "Otherwise it is the **minimum** swept score across that set: the component is only as accessible as its worst live platform."

    Design: Corner/calculations/governance_rollup_excludes_planned_implementations_from_the_minimum
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    web = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
    )
    file_audit(api, web["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED)
    shipped = ship(api, web["id"], base["team_id"])
    assert_conformance_score(shipped, 75.00)

    ios = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_IOS,
        package_name="DSBadge",
        package_version="0.9.0",
        token_compliance_ratio=0.60,
    )
    assert ios["status"] == IMPL_PLANNED
    assert_conformance_score(
        read_component(api, base["component_id"]), 75.00, "governance_conformance_score"
    )

    bad = file_audit(
        api, ios["id"], base["team_id"], critical=3, method=AUDIT_METHOD_AUTOMATED
    )
    assert_defect_load(bad, 3, 0, 0)
    assert_conformance_score(read_implementation(api, ios["id"]), 63.00)
    assert_conformance_score(
        read_component(api, base["component_id"]), 75.00, "governance_conformance_score"
    )


def test_the_adoption_ratio_and_the_index_each_round_half_up_in_turn(api):
    """Two thirds is stored as 66.67 and the index is blended from that stored figure.

    PRD: "Otherwise the ratio is `system_instance_count` divided by that total, multiplied by 100, and rounded half up to two decimal places — so it is a percentage on the closed interval from 0.00 to 100.00, not a fraction."
    PRD: "It multiplies the code-scanning figure by 0.70 and the design-linting figure by 0.30, adds the two products, and rounds half up to two decimal places."

    Design: Corner/calculations/adoption_ratio_and_index_round_half_up_at_each_of_the_two_stages
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")
    assert_decimal_equals(team["adoption_index_latest"], 0.00, 2, "adoption_index_latest")

    scan = validate_success(
        api.create_adoption_scan(
            team["id"],
            adoption_scan_payload(
                "2026-07-01T00:00:00.000Z",
                "2026-07-31T00:00:00.000Z",
                system_instance_count=2,
                legacy_instance_count=1,
                one_off_instance_count=0,
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            make_contributing_team_headers(team["id"]),
        ),
        201,
    )
    assert_decimal_equals(scan["adoption_ratio"], 66.67, 2, "adoption_ratio")
    assert_decimal_places(scan["adoption_ratio"], 2, "adoption_ratio")
    assert_instant_equals(scan["scanned_at"], DEFAULT_CLOCK, "scanned_at")

    rolled_up = read_team(api, team["id"])
    assert_decimal_equals(
        rolled_up["adoption_index_latest"], 46.67, 2, "adoption_index_latest"
    )
    assert_decimal_equals(
        rolled_up["adoption_index_trailing"], 46.67, 2, "adoption_index_trailing"
    )


def test_filing_the_manual_pass_removes_its_penalty_and_adds_its_own_load(api):
    """The latest-evidence score rises when the second method's evidence arrives.

    PRD: "A row's `defect_load` weights findings by severity: ten points for each critical finding, four for each serious finding, and one for each moderate finding, summed."
    PRD: "Add the two products. Subtract that sum from 100, then subtract a further 25.0 for each missing method."
    PRD: "Its result is written to the implementation's `conformance_score` on every audit filing, so remediating a bad audit by filing a good one immediately raises the number."

    Design: Corner/calculations/missing_method_penalty_disappears_when_the_manual_pass_is_filed
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
    )

    automated = file_audit(
        api,
        impl["id"],
        base["team_id"],
        serious=1,
        moderate=1,
        method=AUDIT_METHOD_AUTOMATED,
    )
    assert automated["audit_sequence"] == 1
    assert_defect_load(automated, 0, 1, 1)
    assert_conformance_score(read_implementation(api, impl["id"]), 73.00)

    manual = file_audit(
        api, impl["id"], base["team_id"], moderate=2, method=AUDIT_METHOD_MANUAL
    )
    assert manual["audit_sequence"] == 2
    assert_defect_load(manual, 0, 0, 2)

    both = read_implementation(api, impl["id"])
    assert_conformance_score(both, 96.80)
    assert both["last_audit_sequence"] == 2
    assert_conformance_score(
        read_component(api, base["component_id"]), 0.00, "governance_conformance_score"
    )


def test_five_alias_hops_are_admitted_and_the_sixth_is_refused(api):
    """The depth bound is inclusive at five and the refusal writes nothing at all.

    PRD: "If the walk would exceed 5 hops, the write is refused with `ERR_TOKEN_ALIAS_DEPTH_EXCEEDED` (HTTP 422)."
    PRD: "Both refusals happen **before any row is written**, so a rejected token creation leaves `token_count`, `max_alias_depth` and the token set's `version` untouched."
    PRD: "A set's `max_alias_depth` is the greatest `alias_depth` among its tokens, and 0 when the set is empty."

    Design: Corner/calculations/alias_chain_of_six_hops_is_refused_while_five_hops_is_admitted
    """
    pin_clock(api)
    token_set = make_token_set(api, name="Core", slug="core")
    assert token_set["version"] == 1

    chain = alias_chain(api, token_set["id"], 5, raw_value="#000000")
    depths = [row["alias_depth"] for row in chain["tokens"]]
    assert depths == [0, 1, 2, 3, 4, 5], f"alias depths walked as {depths}"
    assert chain["tokens"][1]["resolved_value"] == "#000000"
    assert chain["tokens"][5]["resolved_value"] == "#000000"

    before = read_token_set(api, token_set["id"])
    assert_fields(
        before, {"version": 7, "max_alias_depth": 5, "token_count": 6}, "token set"
    )

    validate_error(
        api.create_token(
            alias_token_payload(
                token_set["id"], "color.chain.6", chain["tokens"][5]["id"], 7
            ),
            make_design_system_lead_headers(),
        ),
        ERR_TOKEN_ALIAS_DEPTH_EXCEEDED,
        422,
    )

    after = read_token_set(api, token_set["id"])
    assert_fields(
        after, {"version": 7, "max_alias_depth": 5, "token_count": 6}, "token set"
    )
    rows, meta = validate_paginated(
        api.list_tokens(
            make_design_system_lead_headers(),
            params={"token_set_id": token_set["id"]},
        )
    )
    assert_page_meta(meta, total_count=6, has_more=False)
    assert "color.chain.6" not in [row["name"] for row in rows]


def test_repointing_a_leaf_onto_its_own_alias_is_refused_as_a_cycle(api):
    """The cycle guard runs on the re-point, not only on the original write.

    PRD: "If the walk returns to the token it started from, including the degenerate case of a token aliasing itself, or reaches any token it has already visited on the same walk, the write is refused with `ERR_TOKEN_ALIAS_CYCLE` (HTTP 409)."
    PRD: "The resulting alias graph is re-walked in full before anything is written, and the same cycle and depth guards apply with the same two error codes."

    Design: Corner/calculations/repointing_a_leaf_token_onto_its_own_alias_closes_a_cycle_and_is_refused
    """
    pin_clock(api)
    token_set = make_token_set(api, name="Core", slug="core")
    leaf = leaf_token(api, token_set["id"], "color.base", "#0055FF", 1)
    mid = validate_success(
        api.create_token(
            alias_token_payload(token_set["id"], "color.mid", leaf["id"], 2),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert_fields(
        mid, {"alias_depth": 1, "resolved_value": "#0055FF"}, "alias token"
    )
    before = read_token_set(api, token_set["id"])
    assert_fields(before, {"version": 3, "max_alias_depth": 1}, "token set")

    validate_error(
        api.update_token(
            leaf["id"],
            token_repoint_alias_payload(mid["id"], 3),
            make_design_system_lead_headers(),
        ),
        ERR_TOKEN_ALIAS_CYCLE,
        409,
    )

    untouched = validate_success(
        api.get_token(leaf["id"], make_design_system_lead_headers())
    )
    assert untouched["alias_of_token_id"] is None
    assert_fields(
        untouched, {"raw_value": "#0055FF", "alias_depth": 0}, "leaf token"
    )
    after = read_token_set(api, token_set["id"])
    assert_fields(after, {"version": 3, "max_alias_depth": 1}, "token set")


def test_partial_coverage_adds_platform_parity_to_the_required_evidence_set(api):
    """Coverage measured at submit time widens the requirement past the base set.

    PRD: "To that base, `PLATFORM_PARITY` is added when — and only when — the target component's `coverage_state` at the moment of the submit is `PARTIAL` or `FULL`."
    PRD: "The union is stored in `required_evidence_kinds` as an ascending-sorted array with no duplicates, and its members are drawn from exactly six kinds: `A11Y_AUTOMATED`, `A11Y_MANUAL`, `DOC_PAGE`, `MIGRATION_GUIDE`, `PLATFORM_PARITY` and `TOKEN_COMPLIANCE`."

    Design: Corner/calculations/partial_coverage_adds_platform_parity_to_the_required_evidence_set
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    for platform, package in (
        (PLATFORM_WEB, "@ds/badge-web"),
        (PLATFORM_IOS, "DSBadge"),
    ):
        impl = make_implementation(
            api,
            base["component_id"],
            base["team_id"],
            platform=platform,
            package_name=package,
        )
        file_audit(api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED)
        ship(api, impl["id"], base["team_id"])
    assert read_component(api, base["component_id"])["coverage_state"] == COVERAGE_PARTIAL

    release = make_release(api, "1.2.0")
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge focus ring",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    assert submitted["required_evidence_kinds"] == [
        EV_A11Y_AUTOMATED,
        EV_PLATFORM_PARITY,
        EV_TOKEN_COMPLIANCE,
    ]

    filed = file_evidence(
        api,
        proposal["id"],
        base["team_id"],
        [EV_A11Y_AUTOMATED, EV_TOKEN_COMPLIANCE],
    )
    assert filed["submitted_evidence_kinds"] == [EV_A11Y_AUTOMATED, EV_TOKEN_COMPLIANCE]
    review(api, proposal["id"], STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE)
    ready = review(api, proposal["id"], STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE)
    assert ready["resulting_proposal_state"] == PROPOSAL_READY_FOR_ACCEPTANCE

    component_version = read_component(api, base["component_id"])["version"]
    validate_error(
        api.accept_proposal(
            proposal["id"],
            accept_payload(release["id"], component_version),
            make_design_system_lead_headers(),
        ),
        ERR_ACCEPTANCE_EVIDENCE_INCOMPLETE,
        422,
    )
    stalled = validate_success(
        api.get_proposal(proposal["id"], make_design_system_lead_headers())
    )
    assert stalled["state"] == PROPOSAL_READY_FOR_ACCEPTANCE
    assert stalled["released_in_release_id"] is None
    assert stalled["accepted_at"] is None


def test_two_grants_on_different_tiers_are_priced_apart_and_then_summed(api):
    """Each grant takes its own base, reach and maturity factors before the ledger adds up.

    PRD: "The base is 12 points for `ONE_OFF_COMPONENT`, 8 points for `FORK_OF_SYSTEM_COMPONENT` and 5 points for `RAW_TOKEN_USAGE`."
    PRD: "The platform factor is 1.00 for `WEB`, 1.25 for `IOS`, 1.25 for `ANDROID` and 1.75 for `ALL`."
    PRD: "A team's `outstanding_debt_points` is the sum of `debt_points` across that team's grants in `APPROVED` or `EXPIRED`, rounded half up to two decimal places."
    PRD: "Separately, each component's `one_off_exception_count` is the number of grants naming it as `substitute_for_component_id` whose `state` is `APPROVED` or `EXPIRED`"

    Design: Corner/calculations/two_grants_on_different_tiers_round_per_grant_then_sum_to_fourteen_fifty
    """
    base = governance_base(
        api,
        team_slug="design-guild",
        component_slug="badge",
        team_overrides={"debt_budget_points": 40.00},
    )
    assert base["component"]["maturity_level"] == MATURITY_EXPERIMENTAL

    fork = request_grant(
        api,
        base["team_id"],
        base["component_id"],
        expires_at="2026-10-01T00:00:00.000Z",
        exception_kind=EXCEPTION_FORK_OF_SYSTEM_COMPONENT,
        platform_scope=PLATFORM_WEB,
        justification="web fork while the shared badge lands",
    )
    one_off = request_grant(
        api,
        base["team_id"],
        base["component_id"],
        expires_at="2026-10-01T00:00:00.000Z",
        exception_kind=EXCEPTION_ONE_OFF_COMPONENT,
        platform_scope="ALL",
        justification="bespoke marketing badge",
    )

    decided_fork = approve_grant(api, fork["id"])
    assert_fields(
        decided_fork,
        {"state": GRANT_APPROVED, "pinned_maturity_level": MATURITY_EXPERIMENTAL},
        "fork grant",
    )
    assert_debt_points(decided_fork, 4.00)
    assert_instant_equals(decided_fork["decided_at"], DEFAULT_CLOCK, "decided_at")

    after_first = read_team(api, base["team_id"])
    assert_debt_points(after_first, 4.00, "outstanding_debt_points")
    assert_debt_points(after_first, 4.00, "lifetime_debt_points")
    assert after_first["debt_state"] == DEBT_STATE_CLEAR

    decided_one_off = approve_grant(api, one_off["id"])
    assert_fields(
        decided_one_off,
        {"state": GRANT_APPROVED, "pinned_maturity_level": MATURITY_EXPERIMENTAL},
        "one-off grant",
    )
    assert_debt_points(decided_one_off, 10.50)
    assert_debt_points(read_grant(api, fork["id"]), 4.00)

    after_second = read_team(api, base["team_id"])
    assert_debt_points(after_second, 14.50, "outstanding_debt_points")
    assert_debt_points(after_second, 14.50, "lifetime_debt_points")
    assert after_second["debt_state"] == DEBT_STATE_CLEAR
    # `one_off_exception_count` counts every grant naming the component as
    # `substitute_for_component_id` whose state is APPROVED or EXPIRED, whatever
    # its `exception_kind`, so both approved grants are in the count.
    assert read_component(api, base["component_id"])["one_off_exception_count"] == 2


def test_the_dashboard_serves_the_latest_scan_variant_when_no_view_is_asked_for(api):
    """The endpoint's own default decides the variant, and both variants agree with the row.

    PRD: "A team-level dashboard read surfaces one of those two views, selected by the optional `view` field, whose accepted values are `LATEST_SCAN` and `TRAILING_WINDOW` and which defaults to `LATEST_SCAN` when omitted."
    PRD: "`code_scan_ratio` and `design_lint_ratio` are that same variant's per-channel inputs — the single most recent scan's ratio under the latest-scan view, the two-row average under the trailing-window view — and each reads 0.00 when its channel has no scan."

    Design: Corner/calculations/dashboard_defaults_to_the_latest_scan_variant_when_view_is_omitted
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")
    team_headers = make_contributing_team_headers(team["id"])

    june = validate_success(
        api.create_adoption_scan(
            team["id"],
            adoption_scan_payload(
                "2026-06-01T00:00:00.000Z",
                "2026-06-30T00:00:00.000Z",
                system_instance_count=3,
                legacy_instance_count=2,
                one_off_instance_count=0,
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            team_headers,
        ),
        201,
    )
    july = validate_success(
        api.create_adoption_scan(
            team["id"],
            adoption_scan_payload(
                "2026-07-01T00:00:00.000Z",
                "2026-07-31T00:00:00.000Z",
                system_instance_count=9,
                legacy_instance_count=1,
                one_off_instance_count=0,
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            team_headers,
        ),
        201,
    )
    assert_decimal_equals(june["adoption_ratio"], 60.00, 2, "June adoption_ratio")
    assert_decimal_equals(july["adoption_ratio"], 90.00, 2, "July adoption_ratio")

    stored = read_team(api, team["id"])
    assert_decimal_equals(
        stored["adoption_index_latest"], 63.00, 2, "adoption_index_latest"
    )
    assert_decimal_equals(
        stored["adoption_index_trailing"], 52.50, 2, "adoption_index_trailing"
    )

    default_view = validate_success(api.get_team_dashboard(team["id"], team_headers))
    assert default_view["view"] == DASHBOARD_VIEW_LATEST
    assert_decimal_equals(default_view["adoption_index"], 63.00, 2, "adoption_index")
    assert_decimal_equals(default_view["code_scan_ratio"], 90.00, 2, "code_scan_ratio")
    assert_decimal_equals(default_view["design_lint_ratio"], 0.00, 2, "design_lint_ratio")
    assert default_view["scanned_kind_count"] == 1

    trailing = validate_success(
        api.get_team_dashboard(
            team["id"], team_headers, params={"view": DASHBOARD_VIEW_TRAILING}
        )
    )
    assert trailing["view"] == DASHBOARD_VIEW_TRAILING
    assert_decimal_equals(trailing["adoption_index"], 52.50, 2, "adoption_index")


def test_every_derived_field_is_already_settled_in_the_response_that_moved_it(api):
    """One request per fact: no re-read, no retry and no delay makes the numbers appear.

    PRD: "A successful ship returns 200, sets `status` to `SHIPPED`, stamps `shipped_at` from the logical clock, resets `blocked_reason` to `NONE`, recomputes the component's `shipped_platform_count` and `coverage_state`, recomputes the component's `governance_conformance_score` under the governance-sweep view of §3.4, and — when the ship cleared a previously `BLOCKED` row — recomputes the owning team's `blocked_implementation_count` downward."
    PRD: "The server stamps `scanned_at` from the logical clock, computes the row's `adoption_ratio`, and increments the team's `version`."

    Design: Corner/consistency_model/every_derived_field_is_already_correct_in_the_response_that_caused_it
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")
    assert_decimal_equals(team["adoption_index_latest"], 0.00, 2, "adoption_index_latest")
    component = validate_success(
        api.create_component(
            {"name": "Badge", "slug": "badge", "owning_team_id": team["id"]},
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert component["coverage_state"] == COVERAGE_NONE
    assert_conformance_score(component, 0.00, "governance_conformance_score")

    impl = make_implementation(
        api,
        component["id"],
        team["id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
        token_compliance_ratio=0.96,
    )
    automated = file_audit(
        api, impl["id"], team["id"], moderate=5, method=AUDIT_METHOD_AUTOMATED
    )
    assert_defect_load(automated, 0, 0, 5)
    file_audit(api, impl["id"], team["id"], method=AUDIT_METHOD_MANUAL)

    shipped = ship(
        api, impl["id"], team["id"], package_version="1.0.0", token_compliance_ratio=0.96
    )
    assert shipped["status"] == IMPL_SHIPPED
    assert_conformance_score(shipped, 98.00)
    assert_instant_equals(shipped["shipped_at"], DEFAULT_CLOCK, "shipped_at")

    rolled_up = read_component(api, component["id"])
    assert_fields(
        rolled_up,
        {"coverage_state": COVERAGE_WEB_ONLY, "shipped_platform_count": 1},
        "component",
    )
    assert_conformance_score(rolled_up, 98.00, "governance_conformance_score")

    scan = validate_success(
        api.create_adoption_scan(
            team["id"],
            adoption_scan_payload(
                "2026-07-01T00:00:00.000Z",
                "2026-07-31T00:00:00.000Z",
                system_instance_count=8,
                legacy_instance_count=2,
                one_off_instance_count=0,
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            make_contributing_team_headers(team["id"]),
        ),
        201,
    )
    assert_decimal_equals(scan["adoption_ratio"], 80.00, 2, "adoption_ratio")
    assert_decimal_equals(
        read_team(api, team["id"])["adoption_index_latest"],
        56.00,
        2,
        "adoption_index_latest",
    )

    dashboard = validate_success(
        api.get_team_dashboard(team["id"], make_contributing_team_headers(team["id"]))
    )
    assert_decimal_equals(dashboard["adoption_index"], 56.00, 2, "adoption_index")
    assert_decimal_equals(dashboard["code_scan_ratio"], 80.00, 2, "code_scan_ratio")
