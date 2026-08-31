"""Authoring the system description, its review loop and supersession, the boundary
components beneath it, and the stale-view protection on authoring."""

from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    add_component,
    approve_description,
    assert_system_description,
    author_description,
    create_engagement,
    create_subservice_org,
    lock_boundary,
    make_auditor_headers,
    read_engagement,
    set_subservice_method,
    submit_description_for_review,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]


def test_new_description_starts_in_draft_with_zero_review_rounds(api):
    """PRD 3.1: "The new row begins in `DRAFT` with `review_round` at 0 and
    `boundary_locked` false, and the server records the calling operator's identity as
    `authored_by_user_id` — the value that later prevents that same operator from
    approving their own work."
    PRD 3.1: "Its `supersedes_system_description_id` is null until approval, and its
    `in_scope_component_count` and `carved_out_component_count` counters begin at 0."
    PRD 3.1: "Authoring bumps the engagement's `version`."

    Design: Corner/state_machines/corner_system_description_starts_in_draft_with_zero_review_rounds
    """
    engagement = create_engagement(client_name="Seed")
    response = api.create_system_description(
        {
            "engagement_id": engagement["id"],
            "version_label": "v1",
            "boundary_narrative": "Initial boundary.",
            "expected_engagement_version": engagement["version"],
        },
        CL_HEADERS,
    )
    data = validate_success(response, 201)
    assert_system_description(data)
    assert data["status"] == "DRAFT"
    assert data["review_round"] == 0
    assert data["boundary_locked"] is False
    assert data["approved_at"] is None
    assert data["supersedes_system_description_id"] is None
    assert data["in_scope_component_count"] == 0
    assert read_engagement(engagement["id"])["version"] == 2, (
        "Authoring a description bumps the engagement's version from 1 to 2"
    )


def test_approve_straight_from_draft_is_refused(api):
    """PRD 3.1: "Approval — `IN_REVIEW → APPROVED`, performed by an `Auditor` — is where
    the interesting consequences live."
    PRD 2.7: "The supplied `action`, `disposition` or `method` value is an outgoing edge
    from the row's current state, else `ERR_TRANSITION_NOT_ALLOWED` (409)."

    Design: Corner/state_machines/corner_system_description_approve_directly_from_draft_rejected
    """
    engagement = create_engagement(client_name="Skip Review")
    description = author_description(engagement["id"], boundary_narrative="Initial boundary.")
    add_component(description["id"])

    response = api.transition_system_description(
        description["id"], {"action": "APPROVE"}, AUD_HEADERS
    )
    assert response.status_code == 409, (
        f"APPROVE is not an edge out of DRAFT, expected 409, got {response.status_code}"
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )

    after = validate_success(api.get_system_description(description["id"], CL_HEADERS))
    assert after["status"] == "DRAFT"
    assert after["approved_at"] is None
    assert read_engagement(engagement["id"])["approved_system_description_id"] is None


def test_approving_a_second_description_supersedes_the_first(api):
    """PRD 3.1: "On success the server stamps `approved_at` with the logical clock; moves
    the engagement's previously approved description — there is at most one — from
    `APPROVED` to `SUPERSEDED`, recording that row's identifier in the new row's
    `supersedes_system_description_id`; repoints the engagement's
    `approved_system_description_id` at the newly approved row; copies that row's
    `boundary_locked` onto the engagement's own `boundary_locked`; and increments the
    engagement's `version`."
    PRD 3.1: "A description reaches `SUPERSEDED` only through this system-driven path,
    never by direct request."

    Design: Corner/state_machines/corner_second_description_approval_supersedes_the_first
    """
    engagement = create_engagement(client_name="Supersede")
    first = author_description(engagement["id"], version_label="v1", boundary_narrative="First boundary.")
    add_component(first["id"], component_type="SOFTWARE", name="Core API")
    submit_description_for_review(first["id"])
    approve_description(first["id"])

    second = author_description(
        engagement["id"],
        version_label="v2",
        boundary_narrative="Second boundary with the data store added.",
    )
    add_component(second["id"], component_type="DATA", name="Ledger store")
    submit_description_for_review(second["id"])
    approved = validate_success(
        api.transition_system_description(second["id"], {"action": "APPROVE"}, AUD_HEADERS)
    )

    assert approved["status"] == "APPROVED"
    assert approved["supersedes_system_description_id"] == first["id"]

    first_after = validate_success(api.get_system_description(first["id"], CL_HEADERS))
    assert first_after["status"] == "SUPERSEDED"
    assert read_engagement(engagement["id"])["approved_system_description_id"] == second["id"]

    rows, meta = validate_paginated(
        api.list_system_descriptions(
            CL_HEADERS, params={"supersedes_system_description_id": first["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]

    _, superseded_meta = validate_paginated(
        api.list_system_descriptions(
            CL_HEADERS, params={"engagement_id": engagement["id"], "status": "SUPERSEDED"}
        )
    )
    assert superseded_meta["total_count"] == 1


def test_boundary_component_against_an_unknown_description_is_not_found(api):
    """PRD 3.2: "A `ComplianceLead` adds one by naming its `system_description_id` and
    giving it a `name` of 1 to 120 characters, unique among that description's
    components; a repeat name is `ERR_DUPLICATE_RESOURCE`."
    PRD 2.7: "Every identifier supplied in the request body must name a stored row of the
    entity it references, else that entity's not-found code (404)."

    Design: Corner/entities/corner_boundary_component_requires_existing_parent_description
    """
    create_engagement(client_name="Orphan")

    response = api.create_boundary_component(
        {
            "system_description_id": MISSING_UUID,
            "component_type": "DATA",
            "name": "Ghost store",
        },
        CL_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SYSTEM_DESCRIPTION_NOT_FOUND.value, 404)


def test_boundary_scope_and_its_companion_fields_must_agree(api):
    """PRD 3.2: "A component that is `CARVED_OUT` must supply a
    `subservice_organization_id` and must leave `exclusion_rationale` null."
    PRD 3.2: "A component that is `IN_SCOPE` must leave both null. Any other combination
    is rejected with `ERR_BOUNDARY_SCOPE_MISMATCH`."

    Design: Corner/validations/corner_carved_out_component_without_subservice_organization_rejected
    """
    engagement = create_engagement(client_name="Scope Coherence")
    description = author_description(engagement["id"], boundary_narrative="Boundary.")

    carved = api.create_boundary_component(
        {
            "system_description_id": description["id"],
            "component_type": "INFRASTRUCTURE",
            "name": "Third-party racks",
            "scope_status": "CARVED_OUT",
        },
        CL_HEADERS,
    )
    validate_error(carved, ApiErrorId.ERR_BOUNDARY_SCOPE_MISMATCH.value, 422)

    in_scope = api.create_boundary_component(
        {
            "system_description_id": description["id"],
            "component_type": "DATA",
            "name": "Marketing lake",
            "scope_status": "IN_SCOPE",
            "exclusion_rationale": "Not part of the service",
        },
        CL_HEADERS,
    )
    validate_error(in_scope, ApiErrorId.ERR_BOUNDARY_SCOPE_MISMATCH.value, 422)

    _, meta = validate_paginated(
        api.list_boundary_components(
            CL_HEADERS, params={"system_description_id": description["id"]}
        )
    )
    assert meta["total_count"] == 0, "Neither incoherent component may be stored"
    stored = validate_success(api.get_system_description(description["id"], CL_HEADERS))
    assert stored["in_scope_component_count"] == 0


def test_locked_boundary_refuses_new_components_and_rescoping(api):
    """PRD 3.1: "From the moment a description's boundary is locked, no boundary component
    may be created against it and no existing component's scope may be changed; both
    attempts are rejected with `ERR_BOUNDARY_LOCKED`."
    PRD 3.1: "Locking sets `boundary_locked` to true on the description and on the
    engagement, and increments the engagement's `version`."

    Design: Corner/validations/corner_locked_boundary_rejects_new_components
    """
    engagement = create_engagement(client_name="Frozen Boundary")
    description = author_description(engagement["id"], boundary_narrative="Boundary.")
    component = add_component(description["id"], component_type="SOFTWARE", name="Core API")
    submit_description_for_review(description["id"])
    approve_description(description["id"])
    lock_boundary(description["id"])

    added = api.create_boundary_component(
        {
            "system_description_id": description["id"],
            "component_type": "DATA",
            "name": "Late addition",
        },
        CL_HEADERS,
    )
    validate_error(added, ApiErrorId.ERR_BOUNDARY_LOCKED.value, 409)

    rescoped = api.set_boundary_component_scope(
        component["id"],
        {"scope_status": "EXCLUDED", "exclusion_rationale": "Reconsidered"},
        CL_HEADERS,
    )
    validate_error(rescoped, ApiErrorId.ERR_BOUNDARY_LOCKED.value, 409)

    stored = validate_success(api.get_system_description(description["id"], CL_HEADERS))
    assert stored["in_scope_component_count"] == 1
    assert validate_success(api.get_boundary_component(component["id"], CL_HEADERS))[
        "scope_status"
    ] == "IN_SCOPE"
    assert read_engagement(engagement["id"])["boundary_locked"] is True


def test_author_may_not_approve_their_own_description(api):
    """PRD 3.1: "First, segregation of duties: the acting `X-User-ID` must differ from the
    description's `authored_by_user_id`, and an author approving their own narrative is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/corner_description_author_cannot_approve_own_description
    """
    engagement = create_engagement(client_name="Self Approve", user_id="shared-1")
    description = author_description(
        engagement["id"], boundary_narrative="Boundary.", author_id="shared-1"
    )
    add_component(description["id"], actor_id="shared-1")
    submit_description_for_review(description["id"], actor_id="shared-1")

    self_approval = api.transition_system_description(
        description["id"], {"action": "APPROVE"}, make_auditor_headers("shared-1")
    )
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    independent = validate_success(
        api.transition_system_description(
            description["id"], {"action": "APPROVE"}, make_auditor_headers("aud-2")
        )
    )
    assert independent["status"] == "APPROVED"
    assert independent["authored_by_user_id"] == "shared-1"
    assert read_engagement(engagement["id"], user_id="shared-1")[
        "approved_system_description_id"
    ] == description["id"]


def test_carved_out_component_pointing_at_an_inclusive_organization_blocks_approval(api):
    """PRD 3.1: "Second, coherence between the boundary and the subservice presentation
    methods: every boundary component of this description whose `scope_status` is
    `CARVED_OUT` must point at a subservice organization whose `method` is `CARVE_OUT`,
    and a carved-out component pointing at an organization presented inclusively is
    rejected with `ERR_CSOC_NOT_ARTICULATED`."

    Design: Corner/validations/corner_carved_out_component_pointing_at_inclusive_org_blocks_approval
    """
    engagement = create_engagement(client_name="Incoherent")
    organization = create_subservice_org(engagement["id"], name="HostCo")
    set_subservice_method(organization["id"], "INCLUSIVE")

    description = author_description(engagement["id"], boundary_narrative="Boundary.")
    add_component(description["id"], component_type="SOFTWARE", name="Core API")
    component = add_component(
        description["id"],
        component_type="INFRASTRUCTURE",
        name="HostCo racks",
        scope_status="CARVED_OUT",
        subservice_organization_id=organization["id"],
    )
    submit_description_for_review(description["id"])

    response = api.transition_system_description(
        description["id"], {"action": "APPROVE"}, AUD_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_CSOC_NOT_ARTICULATED.value, 409)

    stored = validate_success(api.get_system_description(description["id"], CL_HEADERS))
    assert stored["status"] == "IN_REVIEW"
    assert stored["carved_out_component_count"] == 1
    assert stored["in_scope_component_count"] == 1
    assert validate_success(
        api.get_subservice_organization(organization["id"], CL_HEADERS)
    )["method"] == "INCLUSIVE"
    assert read_engagement(engagement["id"])["approved_system_description_id"] is None
    assert component["scope_status"] == "CARVED_OUT"


def test_rescoping_a_component_to_excluded_moves_the_description_counters(api):
    """PRD 3.2: "A component that is `EXCLUDED` must supply an `exclusion_rationale` and
    must leave `subservice_organization_id` null."
    PRD 3.2: "Adding or rescoping a component recomputes the owning description's
    `in_scope_component_count` and `carved_out_component_count`."

    Design: Corner/endpoints/corner_set_scope_moves_component_to_excluded_with_rationale
    """
    engagement = create_engagement(client_name="Rescope")
    description = author_description(engagement["id"], boundary_narrative="Boundary.")
    first = add_component(description["id"], component_type="SOFTWARE", name="Core API")
    second = add_component(description["id"], component_type="DATA", name="Marketing lake")

    updated = validate_success(
        api.set_boundary_component_scope(
            second["id"],
            {
                "scope_status": "EXCLUDED",
                "exclusion_rationale": "Marketing data is outside the service commitment",
            },
            CL_HEADERS,
        )
    )
    assert updated["scope_status"] == "EXCLUDED"
    assert updated["exclusion_rationale"] == "Marketing data is outside the service commitment"
    assert updated["subservice_organization_id"] is None

    assert validate_success(api.get_boundary_component(first["id"], CL_HEADERS))[
        "scope_status"
    ] == "IN_SCOPE"

    stored = validate_success(api.get_system_description(description["id"], CL_HEADERS))
    assert stored["in_scope_component_count"] == 1
    assert stored["carved_out_component_count"] == 0

    _, meta = validate_paginated(
        api.list_boundary_components(
            CL_HEADERS,
            params={"system_description_id": description["id"], "scope_status": "EXCLUDED"},
        )
    )
    assert meta["total_count"] == 1


def test_lock_boundary_before_approval_is_refused(api):
    """PRD 3.1: "Once a description is approved, a `ComplianceLead` **locks its
    boundary**."
    PRD 2.7: "The row's own current state satisfies the requested transition's originating
    state and every precondition of that transition that does not reach into another
    entity, else `ERR_INVALID_STATE` (409)."

    Design: Corner/errors/corner_lock_boundary_on_a_draft_description_returns_invalid_state
    """
    engagement = create_engagement(client_name="Early Lock")
    description = author_description(engagement["id"], boundary_narrative="Boundary.")
    add_component(description["id"])

    response = api.lock_boundary(description["id"], CL_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert validate_success(api.get_system_description(description["id"], CL_HEADERS))[
        "boundary_locked"
    ] is False
    assert read_engagement(engagement["id"])["boundary_locked"] is False


def test_second_authoring_from_a_stale_engagement_view_is_rejected(api):
    """PRD 2.5: "Authoring a system description — `POST /soc/system-descriptions` —
    requires a non-optional `expected_engagement_version` field carrying the `version` of
    the target engagement as the client last observed it. If that value does not equal the
    engagement's current `version`, the create is rejected with
    `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."
    PRD 2.4: "The engagement's `version` is incremented by one when a system description
    is authored against it, when an approval of a system description takes effect, when a
    boundary is locked, when any engagement phase transition is applied, when a readiness
    assessment is run, and when a calendar ops-run is executed."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_engagement_version_rejects_second_description
    """
    engagement = create_engagement(client_name="Stale View")
    observed_version = engagement["version"]
    assert observed_version == 1

    first = validate_success(
        api.create_system_description(
            {
                "engagement_id": engagement["id"],
                "version_label": "v1",
                "boundary_narrative": "First boundary.",
                "expected_engagement_version": observed_version,
            },
            CL_HEADERS,
        ),
        201,
    )

    stale = api.create_system_description(
        {
            "engagement_id": engagement["id"],
            "version_label": "v2",
            "boundary_narrative": "Second boundary from a stale view.",
            "expected_engagement_version": observed_version,
        },
        CL_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value, 412)

    fresh_version = read_engagement(engagement["id"])["version"]
    assert fresh_version == 2, f"Authoring bumped the engagement to version 2, got {fresh_version}"

    second = validate_success(
        api.create_system_description(
            {
                "engagement_id": engagement["id"],
                "version_label": "v2",
                "boundary_narrative": "Second boundary from a fresh view.",
                "expected_engagement_version": fresh_version,
            },
            CL_HEADERS,
        ),
        201,
    )
    assert first["version_label"] == "v1"
    assert second["version_label"] == "v2"

    _, meta = validate_paginated(
        api.list_system_descriptions(CL_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 2
    assert read_engagement(engagement["id"])["version"] == 3


def test_each_return_to_draft_lap_increments_the_review_round(api):
    """PRD 3.1: "The examining `Auditor` may push it back, `IN_REVIEW → DRAFT`, which is
    permitted only while the description's own `boundary_locked` is still false and which
    increments `review_round` by one — the `DRAFT → IN_REVIEW → DRAFT` pair is a genuine
    loop and a description may traverse it any number of times."

    Design: Difficulty/non_linear_state_machine/system_description_review_loop_increments_round_twice_then_approves
    """
    engagement = create_engagement(client_name="Northwind")
    description = author_description(
        engagement["id"], boundary_narrative="First draft of the boundary."
    )
    add_component(description["id"], component_type="PEOPLE", name="Platform SRE team")

    submit_description_for_review(description["id"])
    first_lap = validate_success(
        api.transition_system_description(
            description["id"],
            {"action": "RETURN_TO_DRAFT", "reason": "Boundary omits the data store"},
            AUD_HEADERS,
        )
    )
    assert first_lap["review_round"] == 1, (
        f"The first return to draft sets review_round 1, got {first_lap['review_round']}"
    )
    assert first_lap["status"] == "DRAFT"

    submit_description_for_review(description["id"])
    second_lap = validate_success(
        api.transition_system_description(
            description["id"],
            {"action": "RETURN_TO_DRAFT", "reason": "Subservice narrative still missing"},
            AUD_HEADERS,
        )
    )
    assert second_lap["review_round"] == 2, (
        f"The second return to draft sets review_round 2, got {second_lap['review_round']}"
    )
    assert second_lap["status"] == "DRAFT"


def test_approval_after_two_review_laps_freezes_the_review_round(api):
    """PRD 3.1: "The examining `Auditor` may push it back, `IN_REVIEW → DRAFT`, which is
    permitted only while the description's own `boundary_locked` is still false and which
    increments `review_round` by one — the `DRAFT → IN_REVIEW → DRAFT` pair is a genuine
    loop and a description may traverse it any number of times."
    PRD 3.1: "On success the server stamps `approved_at` with the logical clock; moves the
    engagement's previously approved description — there is at most one — from `APPROVED`
    to `SUPERSEDED`, recording that row's identifier in the new row's
    `supersedes_system_description_id`; repoints the engagement's
    `approved_system_description_id` at the newly approved row; copies that row's
    `boundary_locked` onto the engagement's own `boundary_locked`; and increments the
    engagement's `version`."

    Design: Difficulty/non_linear_state_machine/system_description_review_loop_increments_round_twice_then_approves
    """
    engagement = create_engagement(client_name="Northwind")
    description = author_description(
        engagement["id"], boundary_narrative="First draft of the boundary."
    )
    add_component(description["id"], component_type="PEOPLE", name="Platform SRE team")

    for reason in ("Boundary omits the data store", "Subservice narrative still missing"):
        submit_description_for_review(description["id"])
        validate_success(
            api.transition_system_description(
                description["id"], {"action": "RETURN_TO_DRAFT", "reason": reason}, AUD_HEADERS
            )
        )
    submit_description_for_review(description["id"])
    approved = validate_success(
        api.transition_system_description(description["id"], {"action": "APPROVE"}, AUD_HEADERS)
    )

    assert approved["status"] == "APPROVED"
    assert approved["review_round"] == 2, (
        f"Approval must leave review_round frozen at 2, got {approved['review_round']}"
    )
    assert approved["supersedes_system_description_id"] is None, (
        "The first approved description of an engagement supersedes nothing"
    )
    assert read_engagement(engagement["id"])["approved_system_description_id"] == description["id"]
