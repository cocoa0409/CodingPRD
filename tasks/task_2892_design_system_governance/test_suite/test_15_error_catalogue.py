"""
The error catalogue read as a contract in its own right.

Two properties matter here and neither is about the happy path: distinct causes
that the catalogue folds onto one identifier must all reach that identifier, and
distinct identifiers must stay distinct — a generic refusal that merely gets the
HTTP status right is a failure.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_A11Y_CONFORMANCE_INSUFFICIENT,
    ERR_BLOCKED_DEPENDENCY,
    ERR_COMPONENT_DEPENDENCY_NOT_FOUND,
    ERR_COMPONENT_NOT_FOUND,
    ERR_DEPRECATION_ADVANCE_NOT_DUE,
    ERR_DEPRECATION_PLAN_NOT_FOUND,
    ERR_EXCEPTION_GRANT_NOT_FOUND,
    ERR_INVALID_COMPONENT_MATURITY_TRANSITION,
    ERR_INVALID_DEPRECATION_PLAN_STATE,
    ERR_PLATFORM_COVERAGE_INSUFFICIENT,
    ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND,
    ERR_PROPOSAL_NOT_FOUND,
    ERR_RELEASE_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    ERR_TOKEN_NAME_CONFLICT,
    ERR_TOKEN_NOT_FOUND,
    ERR_TOKEN_SET_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNIQUENESS_CONFLICT,
)
from test_helpers.assertions import (
    assert_conformance_score,
    assert_error_envelope,
    assert_fields,
    assert_instant_equals,
    assert_page_meta,
    assert_request_meta,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    BLOCKED_REASON_NONE,
    COMPAT_COMPATIBLE,
    COMPAT_INCOMPATIBLE,
    COVERAGE_PARTIAL,
    COVERAGE_WEB_ONLY,
    DEFAULT_BRAND,
    DEFAULT_CLOCK,
    DEFAULT_MODE,
    DEFAULT_TOKEN_MODE,
    DOCS_STATE_DRAFT,
    DOCS_STATE_PUBLISHED,
    GUIDE_MISSING,
    IMPL_PLANNED,
    IMPL_SHIPPED,
    LIFECYCLE_ACTIVE,
    MATURITY_BETA,
    MATURITY_EXPERIMENTAL,
    MATURITY_STABLE,
    PLAN_DRAFT,
    PLATFORM_IOS,
    PLATFORM_WEB,
)
from test_helpers.factories import (
    component_payload,
    dependency_payload,
    dependency_repin_payload,
    implementation_payload,
    leaf_token_payload,
    promote_payload,
    rescind_payload,
    ship_payload,
)
from test_helpers.fixtures import (
    file_audit,
    file_clean_evidence,
    governance_base,
    leaf_token,
    make_component,
    make_implementation,
    make_plan,
    make_token_set,
    pin_clock,
    promote,
    read_component,
    read_implementation,
    read_token_set,
    ship,
)
from test_helpers.test_users import (
    NO_HEADERS,
    make_contributing_team_headers,
    make_design_system_lead_headers,
    make_headers_with_empty_identity,
    make_system_admin_headers,
)

MISSING_UUID = "00000000-0000-4000-8000-00000000beef"
BRAND_A = "BRAND_A"


def test_every_unresolvable_path_id_answers_with_its_own_entity_error(api):
    """Ten routes, ten dedicated 404 identifiers, no shared generic refusal.

    PRD: "Path identifiers are resolved strictly left to right, and the response names the **first** identifier that fails to resolve."

    PRD: "Each resource kind has its own dedicated 404: teams report `ERR_TEAM_NOT_FOUND`, components report `ERR_COMPONENT_NOT_FOUND`, dependency edges report `ERR_COMPONENT_DEPENDENCY_NOT_FOUND`, platform implementations report `ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND`, token sets report `ERR_TOKEN_SET_NOT_FOUND`, design tokens report `ERR_TOKEN_NOT_FOUND`, contribution proposals report `ERR_PROPOSAL_NOT_FOUND`, releases report `ERR_RELEASE_NOT_FOUND`, deprecation plans report `ERR_DEPRECATION_PLAN_NOT_FOUND` and exception grants report `ERR_EXCEPTION_GRANT_NOT_FOUND`."

    The action routes are included deliberately: publish, advance and re-pin all
    carry a payload, and an implementation that resolved the body first would
    answer with the wrong identifier.

    Design: Corner/errors/every_not_found_id_answers_with_its_own_entity_specific_error
    """
    pin_clock(api)
    lead = make_design_system_lead_headers()
    admin = make_system_admin_headers()

    probes = [
        ("team read", lambda: api.get_team(MISSING_UUID, admin), ERR_TEAM_NOT_FOUND),
        (
            "component read",
            lambda: api.get_component(MISSING_UUID, lead),
            ERR_COMPONENT_NOT_FOUND,
        ),
        (
            "dependency re-pin",
            lambda: api.update_dependency(
                MISSING_UUID, dependency_repin_payload(1), lead
            ),
            ERR_COMPONENT_DEPENDENCY_NOT_FOUND,
        ),
        (
            "implementation read",
            lambda: api.get_implementation(MISSING_UUID, lead),
            ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND,
        ),
        (
            "token set read",
            lambda: api.get_token_set(MISSING_UUID, lead),
            ERR_TOKEN_SET_NOT_FOUND,
        ),
        ("token read", lambda: api.get_token(MISSING_UUID, lead), ERR_TOKEN_NOT_FOUND),
        (
            "proposal read",
            lambda: api.get_proposal(MISSING_UUID, lead),
            ERR_PROPOSAL_NOT_FOUND,
        ),
        (
            "release publish",
            lambda: api.publish_release(MISSING_UUID, admin),
            ERR_RELEASE_NOT_FOUND,
        ),
        (
            "plan advance",
            lambda: api.advance_deprecation_plan(MISSING_UUID, lead),
            ERR_DEPRECATION_PLAN_NOT_FOUND,
        ),
        (
            "grant read",
            lambda: api.get_exception_grant(MISSING_UUID, lead),
            ERR_EXCEPTION_GRANT_NOT_FOUND,
        ),
    ]

    seen = []
    for label, call, expected in probes:
        response = call()
        assert_error_envelope(response)
        assert_request_meta(response)
        detail = validate_error(response, expected, 404)
        assert isinstance(detail.get("message"), str) and detail["message"].strip(), (
            f"{label}: the refusal must carry a non-blank message, got {detail!r}"
        )
        seen.append(detail["error_id"])

    assert len(set(seen)) == 10, (
        f"the ten routes must answer with ten distinct identifiers, got {seen}"
    )


def test_a_repeated_slug_and_a_repeated_platform_share_one_conflict_id(api):
    """Two structurally different keys, one identifier, and one scoped per component.

    PRD: "Uniqueness: a team's `slug`, a component's `slug` and a token set's `slug` are each unique across all rows of their kind; the pair of `component_id` and `platform` is unique per platform implementation; the pair of `consumer_component_id` and `provider_component_id` is unique per dependency edge; and the four-part tuple of `token_set_id`, `name`, `brand` and `mode` is unique per design token."

    PRD: "A component may have at most one implementation per platform: a second declaration for the same `component_id` and `platform` pair is `ERR_UNIQUENESS_CONFLICT`."

    The same platform under a different component is admitted, which is what
    proves the second key is scoped to the component rather than global.

    Design: Corner/errors/slug_and_component_platform_pair_uniqueness_both_answer_with_one_id
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    badge_id = base["component_id"]
    chip = make_component(api, base["team_id"], name="Chip", slug="chip")
    team_headers = make_contributing_team_headers(base["team_id"])
    web = make_implementation(
        api, badge_id, base["team_id"], platform=PLATFORM_WEB,
        package_name="@ds/badge-web", token_compliance_ratio=0.90,
    )

    validate_error(
        api.create_component(
            component_payload(
                base["team_id"], name="Badge (v2 rewrite)", slug="badge"
            ),
            make_design_system_lead_headers(),
        ),
        ERR_UNIQUENESS_CONFLICT,
        409,
    )
    validate_error(
        api.create_implementation(
            badge_id,
            implementation_payload(
                platform=PLATFORM_WEB,
                package_name="@ds/badge-web-next",
                package_version="2.0.0",
                token_compliance_ratio=0.90,
            ),
            team_headers,
        ),
        ERR_UNIQUENESS_CONFLICT,
        409,
    )

    chip_web = validate_success(
        api.create_implementation(
            chip["id"],
            implementation_payload(
                platform=PLATFORM_WEB,
                package_name="@ds/chip-web",
                package_version="1.0.0",
                token_compliance_ratio=0.90,
            ),
            team_headers,
        ),
        201,
    )
    assert chip_web["platform"] == PLATFORM_WEB
    assert chip_web["id"] != web["id"]
    assert chip_web["component_id"] == chip["id"]

    _, badge_meta = validate_paginated(
        api.list_implementations(badge_id, make_design_system_lead_headers())
    )
    assert_page_meta(badge_meta, total_count=1, has_more=False)


def test_a_tokens_identity_is_its_four_part_tuple_and_not_its_name(api):
    """The same name at a different brand is a different token, not a collision.

    PRD: "The four-part combination of `token_set_id`, `name`, `brand` and `mode` must be unique; a second token at the same coordinates is refused with `ERR_TOKEN_NAME_CONFLICT`."

    PRD: "A collision yields `ERR_UNIQUENESS_CONFLICT` (409), except for the design-token tuple, which yields `ERR_TOKEN_NAME_CONFLICT` (409)."

    PRD: "Both refusals happen **before any row is written**, so a rejected token creation leaves `token_count`, `max_alias_depth` and the token set's `version` untouched."

    Design: Corner/errors/token_identity_is_the_four_part_tuple_not_the_name
    """
    pin_clock(api)
    token_set = make_token_set(
        api,
        name="Core",
        slug="core",
        default_brand=DEFAULT_BRAND,
        default_mode=DEFAULT_MODE,
    )
    set_id = token_set["id"]
    assert token_set["version"] == 1

    first = leaf_token(
        api, set_id, "color.surface", "#FFFFFF", 1,
        brand=DEFAULT_BRAND, mode=DEFAULT_TOKEN_MODE,
    )
    assert_fields(
        read_token_set(api, set_id), {"version": 2, "token_count": 1}, "token set"
    )

    validate_error(
        api.create_token(
            leaf_token_payload(
                set_id, "color.surface", "#FEFEFE", 2,
                brand=DEFAULT_BRAND, mode=DEFAULT_TOKEN_MODE,
            ),
            make_design_system_lead_headers(),
        ),
        ERR_TOKEN_NAME_CONFLICT,
        409,
    )
    assert_fields(
        read_token_set(api, set_id),
        {"version": 2, "token_count": 1},
        "token set after the refusal",
    )

    second = validate_success(
        api.create_token(
            leaf_token_payload(
                set_id, "color.surface", "#FAF7F0", 2,
                brand=BRAND_A, mode=DEFAULT_TOKEN_MODE,
            ),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert second["id"] != first["id"]
    assert_fields(
        second,
        {"brand": BRAND_A, "name": "color.surface", "resolved_value": "#FAF7F0"},
        "second token",
    )

    _, token_meta = validate_paginated(
        api.list_tokens(
            make_design_system_lead_headers(), params={"token_set_id": set_id}
        )
    )
    assert_page_meta(token_meta, total_count=2)


def test_stable_promotion_from_web_only_coverage_is_refused_on_the_coverage_gate(api):
    """Every earlier gate passes, so the coverage gate is the one that answers.

    PRD: "Promotion to `STABLE` requires five: a `coverage_state` of `PARTIAL` or `FULL`, otherwise `ERR_PLATFORM_COVERAGE_INSUFFICIENT`; a `governance_conformance_score` of at least 90.00, inclusive at the boundary, otherwise `ERR_A11Y_CONFORMANCE_INSUFFICIENT`; a `docs_state` of `PUBLISHED`, otherwise `ERR_INVALID_COMPONENT_MATURITY_TRANSITION`; a `blocked_dependency_count` of 0, otherwise `ERR_BLOCKED_DEPENDENCY`; and again no deprecation plan for this component in state `ANNOUNCED` or `SUNSET`, otherwise `ERR_COMPONENT_DEPRECATION_IN_PROGRESS`."

    PRD: "`WEB_ONLY` when the set is exactly the single platform `WEB`;"

    Design: Corner/errors/stable_promotion_from_web_only_coverage_is_refused_on_the_coverage_gate
    """
    base = governance_base(
        api,
        team_slug="design-guild",
        component_name="Badge",
        component_slug="badge",
        component_overrides={"docs_state": DOCS_STATE_PUBLISHED},
    )
    impl = make_implementation(
        api, base["component_id"], base["team_id"], platform=PLATFORM_WEB,
        package_name="@ds/badge-web", token_compliance_ratio=0.98,
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    ship(api, impl["id"], base["team_id"], token_compliance_ratio=0.98)

    beta = promote(api, base["component_id"], MATURITY_BETA)
    assert_fields(
        beta,
        {"maturity_level": MATURITY_BETA, "coverage_state": COVERAGE_WEB_ONLY},
        "component at BETA",
    )
    assert_conformance_score(beta, 100.00, "governance_conformance_score")
    assert_instant_equals(
        beta["conformance_baseline_at"], DEFAULT_CLOCK, "conformance_baseline_at"
    )

    detail = validate_error(
        api.promote_maturity(
            base["component_id"],
            promote_payload(MATURITY_STABLE),
            make_design_system_lead_headers(),
        ),
        ERR_PLATFORM_COVERAGE_INSUFFICIENT,
        422,
    )
    assert detail["error_id"] != ERR_INVALID_COMPONENT_MATURITY_TRANSITION

    after = read_component(api, base["component_id"])
    assert_fields(
        after,
        {
            "maturity_level": MATURITY_BETA,
            "docs_state": DOCS_STATE_PUBLISHED,
            "version": beta["version"],
        },
        "component after the refusal",
    )
    assert_instant_equals(
        after["conformance_baseline_at"],
        beta["conformance_baseline_at"],
        "conformance_baseline_at",
    )


def test_step_skipping_and_the_docs_precondition_share_one_maturity_error(api):
    """One identifier answers an undeclared step and an unpublished docs page.

    PRD: "Only `EXPERIMENTAL → BETA` and `BETA → STABLE` are declared; asking for any other destination — `EXPERIMENTAL` straight to `STABLE`, or a request to move down — is `ERR_INVALID_COMPONENT_MATURITY_TRANSITION`."

    PRD: "Promotion to `STABLE` requires five: a `coverage_state` of `PARTIAL` or `FULL`, otherwise `ERR_PLATFORM_COVERAGE_INSUFFICIENT`; a `governance_conformance_score` of at least 90.00, inclusive at the boundary, otherwise `ERR_A11Y_CONFORMANCE_INSUFFICIENT`; a `docs_state` of `PUBLISHED`, otherwise `ERR_INVALID_COMPONENT_MATURITY_TRANSITION`; a `blocked_dependency_count` of 0, otherwise `ERR_BLOCKED_DEPENDENCY`; and again no deprecation plan for this component in state `ANNOUNCED` or `SUNSET`, otherwise `ERR_COMPONENT_DEPRECATION_IN_PROGRESS`."

    The documentation branch is reached on a component whose coverage and score
    both clear their gates, so neither of those identifiers is available as an
    excuse.

    Design: Corner/errors/maturity_step_skipping_and_the_docs_precondition_share_one_error_id
    """
    base = governance_base(
        api,
        team_slug="design-guild",
        component_name="Badge",
        component_slug="badge",
        component_overrides={"docs_state": DOCS_STATE_DRAFT},
    )
    badge_id = base["component_id"]
    chip = make_component(api, base["team_id"], name="Chip", slug="chip")

    for platform, package in ((PLATFORM_WEB, "@ds/badge-web"), (PLATFORM_IOS, "DSBadge")):
        impl = make_implementation(
            api, badge_id, base["team_id"], platform=platform,
            package_name=package, token_compliance_ratio=0.98,
        )
        file_clean_evidence(api, impl["id"], base["team_id"])
        ship(api, impl["id"], base["team_id"], token_compliance_ratio=0.98)

    beta = promote(api, badge_id, MATURITY_BETA)
    assert_fields(
        beta,
        {"maturity_level": MATURITY_BETA, "coverage_state": COVERAGE_PARTIAL},
        "badge at BETA",
    )
    assert_conformance_score(beta, 100.00, "governance_conformance_score")

    skipped = validate_error(
        api.promote_maturity(
            chip["id"], promote_payload(MATURITY_STABLE), make_design_system_lead_headers()
        ),
        ERR_INVALID_COMPONENT_MATURITY_TRANSITION,
        409,
    )
    assert skipped["error_id"] != ERR_PLATFORM_COVERAGE_INSUFFICIENT

    undocumented = validate_error(
        api.promote_maturity(
            badge_id, promote_payload(MATURITY_STABLE), make_design_system_lead_headers()
        ),
        ERR_INVALID_COMPONENT_MATURITY_TRANSITION,
        409,
    )
    assert undocumented["error_id"] not in (
        ERR_PLATFORM_COVERAGE_INSUFFICIENT,
        ERR_A11Y_CONFORMANCE_INSUFFICIENT,
    )

    assert read_component(api, badge_id)["maturity_level"] == MATURITY_BETA
    assert read_component(api, chip["id"])["maturity_level"] == MATURITY_EXPERIMENTAL


def test_a_draft_plan_can_be_neither_advanced_nor_rescinded(api):
    """Draft is the plan's opening position and neither action leaves it.

    PRD: "Advancing a plan that is in `DRAFT`, or one that has already reached `REMOVED`, is `ERR_INVALID_DEPRECATION_PLAN_STATE`."

    PRD: "Rescission is the compensating action, available from `ANNOUNCED` and from `SUNSET` and refused from anywhere else with `ERR_INVALID_DEPRECATION_PLAN_STATE`."

    PRD: "The plan takes its `component_id` from the request path, is created with a 201 response in `state` `DRAFT` with `blocked_dependent_count` at 0 and `rescinded_at` null, and its `migration_guide_state` starts at `DRAFT` when a `migration_guide_url` was supplied and at `MISSING` otherwise."

    The clock has not reached `sunset_at` either, so the state refusal has to
    outrank the temporal one rather than merely coincide with it.

    Design: Corner/errors/draft_plans_can_be_neither_advanced_nor_rescinded
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
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
            "version": 1,
            "migration_guide_state": GUIDE_MISSING,
            "blocked_dependent_count": 0,
            "rescinded_at": None,
        },
        "plan",
    )

    advanced = validate_error(
        api.advance_deprecation_plan(plan["id"], make_design_system_lead_headers()),
        ERR_INVALID_DEPRECATION_PLAN_STATE,
        409,
    )
    assert advanced["error_id"] != ERR_DEPRECATION_ADVANCE_NOT_DUE

    validate_error(
        api.rescind_deprecation_plan(
            plan["id"],
            rescind_payload("changed our minds before announcing"),
            make_design_system_lead_headers(),
        ),
        ERR_INVALID_DEPRECATION_PLAN_STATE,
        409,
    )

    rows, meta = validate_paginated(
        api.list_deprecation_plans(
            base["component_id"],
            make_design_system_lead_headers(),
            params={"state": PLAN_DRAFT, "limit": 100, "offset": 0},
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_fields(
        rows[0],
        {"state": PLAN_DRAFT, "version": 1, "rescinded_at": None, "id": plan["id"]},
        "plan after both refusals",
    )
    assert read_component(api, base["component_id"])["lifecycle_state"] == LIFECYCLE_ACTIVE


def test_a_stale_major_pin_blocks_the_first_ship_until_it_is_repinned(api):
    """The dependency gate reads live derived state, not a sticky flag.

    PRD: "Finally the owning component's `blocked_dependency_count` must be 0, otherwise `ERR_BLOCKED_DEPENDENCY` — and for a recovery from `BLOCKED` this is the substantive gate, because the consumer must first re-pin its dependency edge to the provider's new major version before it can ship again."

    PRD: "When the edge becomes `COMPATIBLE` the consumer's `blocked_dependency_count` is recomputed downward."

    PRD: "A successful ship returns 200, sets `status` to `SHIPPED`, stamps `shipped_at` from the logical clock, resets `blocked_reason` to `NONE`, recomputes the component's `shipped_platform_count` and `coverage_state`, recomputes the component's `governance_conformance_score` under the governance-sweep view of §3.4, and — when the ship cleared a previously `BLOCKED` row — recomputes the owning team's `blocked_implementation_count` downward."

    No cascade is involved: the edge is born incompatible because it was pinned
    one major ahead of what the provider publishes, and a refused ship is not
    itself a block.

    Design: Corner/errors/a_stale_major_pin_blocks_the_first_ship_until_it_is_repinned
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Icon", component_slug="icon"
    )
    provider_id = base["component_id"]
    consumer = make_component(api, base["team_id"], name="Badge", slug="badge")
    impl = make_implementation(
        api, consumer["id"], base["team_id"], platform=PLATFORM_WEB,
        package_name="@ds/badge-web", token_compliance_ratio=0.93,
    )
    file_audit(api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED)
    edge = validate_success(
        api.create_dependency(
            consumer["id"],
            dependency_payload(provider_id, pinned_provider_major=2),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert edge["compatibility_state"] == COMPAT_INCOMPATIBLE
    assert read_component(api, consumer["id"])["blocked_dependency_count"] == 1

    team_headers = make_contributing_team_headers(base["team_id"])
    validate_error(
        api.ship_implementation(
            impl["id"],
            ship_payload(package_version="1.0.0", token_compliance_ratio=0.93),
            team_headers,
        ),
        ERR_BLOCKED_DEPENDENCY,
        409,
    )
    assert_fields(
        read_implementation(api, impl["id"]),
        {"status": IMPL_PLANNED, "blocked_reason": BLOCKED_REASON_NONE},
        "implementation after the refused ship",
    )

    repinned = validate_success(
        api.update_dependency(
            edge["id"], dependency_repin_payload(1), make_design_system_lead_headers()
        )
    )
    assert repinned["compatibility_state"] == COMPAT_COMPATIBLE

    shipped = validate_success(
        api.ship_implementation(
            impl["id"],
            ship_payload(package_version="1.0.0", token_compliance_ratio=0.93),
            team_headers,
        )
    )
    assert shipped["status"] == IMPL_SHIPPED
    assert_instant_equals(shipped["shipped_at"], DEFAULT_CLOCK, "shipped_at")
    assert_fields(
        read_component(api, consumer["id"]),
        {"blocked_dependency_count": 0, "coverage_state": COVERAGE_WEB_ONLY},
        "consumer after the recovery",
    )


def test_empty_string_identity_headers_are_treated_as_absent(api):
    """Blank identity headers fail authentication ahead of every other check.

    PRD: "A header that is absent, sent as an empty string, or sent as whitespace only is treated as absent, and the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "The one carve-out is the logical-clock capability of §2.4, which does not reject a request for absent or blank headers; when headers are supplied to it they must still name `SystemAdmin`."

    Both probes name a component that really exists, so a 403 or a 404 would mean
    the authentication check had been evaluated too late.

    Design: Corner/errors/empty_string_identity_headers_are_treated_as_absent
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    component_id = base["component_id"]
    blank = make_headers_with_empty_identity()

    read_refusal = api.get_component(component_id, blank)
    assert_error_envelope(read_refusal)
    read_detail = validate_error(read_refusal, ERR_UNAUTHENTICATED, 401)
    assert isinstance(read_detail.get("message"), str) and read_detail["message"].strip()
    assert "id" not in read_detail and "maturity_level" not in read_detail, (
        f"a refusal must not leak the resource it declined to serve: {read_detail!r}"
    )

    write_refusal = api.promote_maturity(component_id, promote_payload(MATURITY_BETA), blank)
    assert_error_envelope(write_refusal)
    validate_error(write_refusal, ERR_UNAUTHENTICATED, 401)

    served = validate_success(
        api.get_component(component_id, make_design_system_lead_headers())
    )
    assert served["id"] == component_id
    assert served["maturity_level"] == MATURITY_EXPERIMENTAL

    exempt = api.set_clock_raw({"to_iso8601": DEFAULT_CLOCK}, NO_HEADERS)
    assert exempt.status_code == 200, (
        "the logical-clock capability is the declared carve-out and must answer "
        f"without identity headers, got {exempt.status_code}"
    )
