"""
The declared shape of the entities: creation, defaults, reads and listings.

Every row in this API arrives with a large computed surface that the client never
supplies, so the tests here separate what a caller may set from what the server
mints, and they check the refusals that keep a malformed or unresolvable write
from ever reaching storage.
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_COMPONENT_NOT_FOUND,
    ERR_DEPENDENCY_CYCLE,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (
    assert_absent,
    assert_append_only_row,
    assert_array_envelope,
    assert_fields,
    assert_instant_equals,
    assert_object_envelope,
    assert_page_meta,
    assert_request_meta,
    assert_versioned_row,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    CHANNEL_STABLE,
    COMPAT_COMPATIBLE,
    COVERAGE_NONE,
    DEBT_STATE_CLEAR,
    DEFAULT_CLOCK,
    DEFAULT_DEBT_BUDGET_POINTS,
    DEFAULT_TEAM_PLATFORM_SCOPE,
    DEMOTION_REASON_NONE,
    DIRECTION_CONSUMES,
    DOCS_STATE_DRAFT,
    DOCS_STATE_MISSING,
    IMPL_PLANNED,
    LIFECYCLE_ACTIVE,
    MATURITY_EXPERIMENTAL,
    NOTES_PENDING,
    PLATFORM_WEB,
    RELEASE_DRAFT,
)
from test_helpers.factories import (
    audit_payload,
    component_payload,
    dependency_payload,
    implementation_payload,
    release_payload,
    team_payload,
)
from test_helpers.fixtures import (
    declare_dependency,
    governance_base,
    make_component,
    make_team,
    pin_clock,
    read_component,
    read_implementation,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
    make_system_admin_headers,
)

UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_COMPONENT_UUID = "33333333-3333-4333-8333-333333333333"


def test_component_creation_returns_the_success_envelope_and_every_declared_default(api):
    """A create carrying only the required inputs seeds the whole computed surface.

    PRD: "Registration returns 201 and seeds a large computed surface: `maturity_level` at `EXPERIMENTAL`, `lifecycle_state` at `ACTIVE`, `maturity_demotion_reason` at `NONE`, `current_major_version` at 1, `shipped_platform_count` at 0, `coverage_state` at `NONE`, `governance_conformance_score` at 0.00, `blocked_dependency_count` at 0, `pending_breaking_change_count` at 0 and `one_off_exception_count` at 0."

    Design: Corner/entities/component_creation_returns_201_with_success_envelope_and_declared_defaults
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")

    response = api.create_component(
        component_payload(team["id"], name="Badge", slug="badge"),
        make_design_system_lead_headers(),
    )
    component = validate_success(response, 201)
    assert_object_envelope(response)
    assert_request_meta(response)

    assert_fields(
        component,
        {
            "name": "Badge",
            "slug": "badge",
            "owning_team_id": team["id"],
            "maturity_level": MATURITY_EXPERIMENTAL,
            "lifecycle_state": LIFECYCLE_ACTIVE,
            "maturity_demotion_reason": DEMOTION_REASON_NONE,
            "docs_state": DOCS_STATE_MISSING,
            "current_major_version": 1,
            "shipped_platform_count": 0,
            "coverage_state": COVERAGE_NONE,
            "governance_conformance_score": 0.00,
            "blocked_dependency_count": 0,
            "pending_breaking_change_count": 0,
            "one_off_exception_count": 0,
            "version": 1,
        },
        "component",
    )
    assert_instant_equals(component["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant_equals(
        component["conformance_baseline_at"], DEFAULT_CLOCK, "conformance_baseline_at"
    )
    assert component["docs_last_reviewed_at"] is None


def test_a_component_read_echoes_the_stored_row_without_bumping_its_version(api):
    """A read is not a mutation, so the version the create returned still stands.

    PRD: "A single component read returns both state dimensions and every governance roll-up on the row."

    Design: Corner/entities/component_read_returns_exactly_the_stored_row
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")
    created = make_component(
        api, team["id"], name="Badge", slug="badge", docs_state=DOCS_STATE_DRAFT
    )
    assert created["version"] == 1

    response = api.get_component(
        created["id"], make_contributing_team_headers(team["id"])
    )
    read = validate_success(response, 200)
    assert_object_envelope(response)
    assert_fields(
        read,
        {
            "id": created["id"],
            "slug": "badge",
            "owning_team_id": team["id"],
            "docs_state": DOCS_STATE_DRAFT,
            "maturity_level": MATURITY_EXPERIMENTAL,
            "lifecycle_state": LIFECYCLE_ACTIVE,
            "version": 1,
        },
        "component",
    )
    assert read["docs_last_reviewed_at"] is None
    assert read_component(api, created["id"])["version"] == 1


def test_the_component_listing_reports_the_prefilter_total_and_the_remainder_flag(api):
    """Two pages over three rows report the same total and opposite remainder flags.

    PRD: "`total_count` is the number of rows matching the request's filters before pagination is applied, and `has_more` is true exactly when rows matching those filters remain beyond the returned page."

    Design: Corner/entities/component_listing_paginates_with_total_count_and_has_more
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")
    created = [
        make_component(api, team["id"], name=name, slug=slug)["id"]
        for name, slug in (("Badge", "badge"), ("Chip", "chip"), ("Switch", "switch"))
    ]

    first_response = api.list_components(
        make_design_system_lead_headers(), {"limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert_array_envelope(first_response)
    assert len(first_rows) == 2, f"expected 2 rows on the first page, got {len(first_rows)}"
    assert_page_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)

    second_rows, second_meta = validate_paginated(
        api.list_components(make_design_system_lead_headers(), {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, f"expected 1 row on the second page, got {len(second_rows)}"
    assert_page_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)

    walked = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert sorted(walked) == sorted(created), (
        f"the two pages must walk every component exactly once, got {walked}"
    )


def test_an_unknown_component_path_id_answers_with_the_component_not_found_code(api):
    """A well-formed but unknown path id is a 404 rather than an empty success.

    PRD: "Every id appearing in the URL path resolves to an existing row, validated left to right — otherwise the matching 404: `ERR_TEAM_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_COMPONENT_DEPENDENCY_NOT_FOUND`, `ERR_PLATFORM_IMPLEMENTATION_NOT_FOUND`, `ERR_TOKEN_SET_NOT_FOUND`, `ERR_TOKEN_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_DEPRECATION_PLAN_NOT_FOUND` or `ERR_EXCEPTION_GRANT_NOT_FOUND`."

    Design: Corner/entities/component_read_with_unknown_uuid_returns_component_not_found
    """
    pin_clock(api)

    response = api.get_component(UNKNOWN_UUID, make_design_system_lead_headers())
    detail = validate_error(response, ERR_COMPONENT_NOT_FOUND, 404)
    assert isinstance(detail["message"], str) and detail["message"].strip(), (
        "an error payload must carry a non-empty human-readable message"
    )
    assert_absent(detail, ["id", "slug", "maturity_level", "lifecycle_state"], "error data")


def test_a_team_registration_without_a_slug_is_refused_and_persists_nothing(api):
    """The slug is a required input, so the shape gate answers before storage.

    PRD: "A `SystemAdmin` registers each product or design group by supplying a human-readable `name` of between 1 and 120 non-blank characters and a URL-safe `slug` in lowercase kebab-case that must be unique across every registered team; a collision is rejected with `ERR_UNIQUENESS_CONFLICT`."
    PRD: "Any failure is `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/team_creation_without_slug_is_refused_as_invalid_request
    """
    pin_clock(api)

    validate_error(
        api.create_team(
            {"name": "Slugless Team", "platform_scope": "ALL", "debt_budget_points": 40.00},
            make_system_admin_headers(),
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # The API declares no team-collection listing, so the refusal itself is the
    # whole observable: the shape gate answers before any row can be written.


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(api):
    """A team's scope and budget and a release's channel all have declared fallbacks.

    PRD: "`debt_budget_points` caps the outstanding technical debt the team may carry, is expressed to two decimal places, may not be negative, and defaults to 40.00."
    PRD: "The release is created with a 201 response in `state` `DRAFT`, with `release_notes_state` at `PENDING`, `breaking_change_count` and `escalated_proposal_count` at 0, and `semver`, `policy_tier`, `breaking_ratio` and `published_at` all null."

    Design: Corner/entities/team_and_release_optional_inputs_fall_back_to_declared_defaults
    """
    pin_clock(api)

    team_response = api.create_team(
        team_payload(name="Defaults Team", slug="defaults-team"),
        make_system_admin_headers(),
    )
    team = validate_success(team_response, 201)
    assert_fields(
        team,
        {
            "platform_scope": DEFAULT_TEAM_PLATFORM_SCOPE,
            "debt_budget_points": DEFAULT_DEBT_BUDGET_POINTS,
            "debt_state": DEBT_STATE_CLEAR,
            "outstanding_debt_points": 0.00,
            "lifetime_debt_points": 0.00,
            "blocked_implementation_count": 0,
            "adoption_index_latest": 0.00,
            "adoption_index_trailing": 0.00,
        },
        "team",
    )

    release_response = api.create_release(
        release_payload("3.4.0"), make_system_admin_headers()
    )
    release = validate_success(release_response, 201)
    assert_fields(
        release,
        {
            "channel": CHANNEL_STABLE,
            "state": RELEASE_DRAFT,
            "release_notes_state": NOTES_PENDING,
            "breaking_change_count": 0,
            "escalated_proposal_count": 0,
        },
        "release",
    )
    for field in ("semver", "policy_tier", "breaking_ratio", "published_at"):
        assert release[field] is None, (
            f"release.{field} must be null before publication, got {release[field]!r}"
        )


def test_an_implementations_computed_fields_ignore_whatever_the_client_sends(api):
    """Only the compliance ratio on this row is a client input; the rest are derived.

    PRD: "Declaration returns 201 with `status` at `PLANNED`, `conformance_score` at 0.00, `last_audit_sequence` at 0, `blocked_reason` at `NONE` and `shipped_at` null."

    Design: Corner/entities/implementation_computed_fields_ignore_client_supplied_values
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")

    response = api.create_implementation(
        base["component_id"],
        implementation_payload(
            platform=PLATFORM_WEB,
            package_name="@ds/badge-web",
            package_version="1.0.0",
            token_compliance_ratio=0.94,
            status="SHIPPED",
            conformance_score=99.99,
            last_audit_sequence=17,
        ),
        make_contributing_team_headers(base["team_id"]),
    )
    implementation = validate_success(response, 201)
    assert_fields(
        implementation,
        {
            "status": IMPL_PLANNED,
            "conformance_score": 0.00,
            "last_audit_sequence": 0,
            "token_compliance_ratio": 0.94,
        },
        "implementation",
    )
    assert implementation["shipped_at"] is None

    audit = validate_success(
        api.create_accessibility_audit(
            implementation["id"],
            audit_payload(0, 1, 3, method=AUDIT_METHOD_AUTOMATED),
            make_contributing_team_headers(base["team_id"]),
        ),
        201,
    )
    assert audit["defect_load"] == 7
    assert audit["audit_sequence"] == 1

    after = read_implementation(api, implementation["id"])
    assert_fields(
        after, {"conformance_score": 72.20, "last_audit_sequence": 1}, "implementation"
    )
    component = read_component(api, base["component_id"])
    assert_fields(
        component,
        {"shipped_platform_count": 0, "coverage_state": COVERAGE_NONE},
        "component",
    )


def test_ids_and_audit_stamps_are_minted_by_the_server_at_the_logical_clock(api):
    """Two creations in one clock instant still receive distinct bare-UUID ids.

    PRD: "Every resource in the system carries an `id`: a server-minted UUID string with no type prefix and no embedded semantics."

    Design: Corner/entities/system_fields_are_server_minted_and_client_ids_are_ignored
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")

    first = make_component(api, team["id"], name="Badge", slug="badge")
    second = make_component(api, team["id"], name="Chip", slug="chip")

    for row, label in ((first, "first component"), (second, "second component")):
        assert_versioned_row(row, expected_version=1, label=label)
        assert is_valid_uuid(row["id"]), f"{label}.id is not a bare UUID: {row['id']!r}"
        assert_instant_equals(row["created_at"], DEFAULT_CLOCK, f"{label}.created_at")
        assert_instant_equals(row["updated_at"], DEFAULT_CLOCK, f"{label}.updated_at")

    assert first["id"] != second["id"], (
        "two rows written in the same request instant must still be distinguishable"
    )


def test_a_platform_outside_the_declared_enumeration_is_refused(api):
    """The platform field admits three members and nothing that merely sounds like one.

    PRD: "A `ContributingTeam` that owns the component, or a `DesignSystemLead`, declares one by naming the `platform` — `WEB`, `IOS` or `ANDROID` — together with the distributed `package_name` of 1 to 160 non-blank characters and a `package_version` that must be a three-part dotted numeric semantic version such as `2.4.0`."

    Design: Corner/entities/invalid_platform_enum_member_is_refused_by_shape_validation
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")

    validate_error(
        api.create_implementation(
            base["component_id"],
            implementation_payload(
                platform="WATCH",
                package_name="@ds/badge-watch",
                package_version="1.0.0",
                token_compliance_ratio=0.95,
            ),
            make_contributing_team_headers(base["team_id"]),
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_implementations(
            base["component_id"], make_design_system_lead_headers()
        )
    )
    assert_page_meta(meta, total_count=0, has_more=False)
    assert rows == [], f"the refused declaration must leave no implementation, found {rows}"


def test_an_accessibility_audit_carries_no_version_and_no_updated_at(api):
    """Evidence rows are append-only, which is why a bad audit can only be superseded.

    PRD: "**These three carry only `id` and `created_at`. They have no `updated_at` field and no `version` field at all** — the fields are absent from their payloads, not merely unchanging."

    Design: Corner/entities/accessibility_audit_rows_are_append_only_with_no_version_field
    """
    base = governance_base(api, team_slug="design-guild", component_slug="badge")
    implementation = validate_success(
        api.create_implementation(
            base["component_id"],
            implementation_payload(
                platform=PLATFORM_WEB,
                package_name="@ds/badge-web",
                package_version="1.0.0",
                token_compliance_ratio=0.95,
            ),
            make_contributing_team_headers(base["team_id"]),
        ),
        201,
    )

    response = api.create_accessibility_audit(
        implementation["id"],
        audit_payload(0, 1, 2, method=AUDIT_METHOD_AUTOMATED),
        make_contributing_team_headers(base["team_id"]),
    )
    audit = validate_success(response, 201)
    assert_append_only_row(audit, "audit")
    assert_fields(audit, {"audit_sequence": 1, "defect_load": 6}, "audit")
    assert_instant_equals(audit["audited_at"], DEFAULT_CLOCK, "audited_at")
    assert read_implementation(api, implementation["id"])["last_audit_sequence"] == 1


def test_an_implementation_under_an_unknown_component_reports_the_parent_failure(api):
    """The path id is resolved before the body is considered at all.

    PRD: "Path identifiers are resolved strictly left to right, and the response names the **first** identifier that fails to resolve."

    Design: Corner/entities/implementation_creation_under_unknown_component_path_id_is_refused
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")

    validate_error(
        api.create_implementation(
            UNKNOWN_COMPONENT_UUID,
            implementation_payload(
                platform=PLATFORM_WEB,
                package_name="@ds/ghost-web",
                package_version="1.0.0",
                token_compliance_ratio=0.95,
            ),
            make_contributing_team_headers(team["id"]),
        ),
        ERR_COMPONENT_NOT_FOUND,
        404,
    )


def test_a_dependency_edge_that_closes_a_three_node_cycle_is_refused(api):
    """The cycle guard reads the transitive closure, not just the direct pair.

    PRD: "The requested dependency edge does not close a cycle in the component dependency graph, measured over the transitive closure of all dependency edges regardless of their `compatibility_state` — otherwise `ERR_DEPENDENCY_CYCLE` (409)."

    Design: Corner/entities/dependency_edge_that_would_close_a_graph_cycle_is_refused
    """
    pin_clock(api)
    team = make_team(api, name="Design Guild", slug="design-guild")
    alpha = make_component(api, team["id"], name="Alpha", slug="alpha")
    beta = make_component(api, team["id"], name="Beta", slug="beta")
    gamma = make_component(api, team["id"], name="Gamma", slug="gamma")

    alpha_beta = declare_dependency(api, alpha["id"], beta["id"], 1)
    beta_gamma = declare_dependency(api, beta["id"], gamma["id"], 1)
    assert alpha_beta["compatibility_state"] == COMPAT_COMPATIBLE
    assert beta_gamma["compatibility_state"] == COMPAT_COMPATIBLE

    validate_error(
        api.create_dependency(
            gamma["id"],
            dependency_payload(alpha["id"], 1),
            make_design_system_lead_headers(),
        ),
        ERR_DEPENDENCY_CYCLE,
        409,
    )

    for component_id, edge_id in (
        (alpha["id"], alpha_beta["id"]),
        (beta["id"], beta_gamma["id"]),
    ):
        rows, _meta = validate_paginated(
            api.list_dependencies(component_id, make_design_system_lead_headers())
        )
        surviving = [row for row in rows if row["id"] == edge_id]
        assert surviving, f"edge {edge_id} must survive the refused write"
        assert surviving[0]["compatibility_state"] == COMPAT_COMPATIBLE

    _rows, gamma_meta = validate_paginated(
        api.list_dependencies(
            gamma["id"],
            make_design_system_lead_headers(),
            {"direction": DIRECTION_CONSUMES},
        )
    )
    assert_page_meta(gamma_meta, total_count=0, has_more=False)
