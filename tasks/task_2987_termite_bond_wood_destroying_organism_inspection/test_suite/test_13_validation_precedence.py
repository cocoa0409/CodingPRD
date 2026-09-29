"""Validation precedence and the gates that outrank one another.

Each test drives a request that violates two rules at once and asserts that the
server reports the earlier of the two, then shows the later gate firing on its
own once the earlier one is satisfied.
"""

import pytest

from test_helpers import (
    BOND_ACTIVE,
    BOND_LAPSED,
    BRANCH_MANAGER_ID,
    CATEGORY_FUMIGATION_CERTIFIED,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    CLAIM_APPROVED_RETREAT_ONLY,
    CLAIM_SUBMITTED,
    CLAIM_TYPE_RETREAT,
    CLAIM_UNDER_ADJUDICATION,
    CLAIMS_ADJUDICATOR_ID,
    CONDUCIVE_WOOD_TO_GROUND,
    DECISION_APPROVE_REPAIR,
    DECISION_APPROVE_RETREAT_ONLY,
    ERR_BOND_NOT_FOUND,
    ERR_CATEGORY_NOT_LICENSED,
    ERR_DAMAGE_OUTSIDE_TERM,
    ERR_DUPLICATE_ACTIVE_BOND,
    ERR_DUPLICATE_GRID_FINDING,
    ERR_GRAPH_INCOMPLETE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_LICENSE_STATE_MISMATCH,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PROPERTY_NOT_FOUND,
    ERR_RETENTION_LOCK_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_TIER_EXCLUDES_REPAIR,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VERIFIER_IS_APPLICATOR,
    FINDING_DAMAGE,
    INSPECTION_DRAFT,
    INSPECTION_GRAPHED,
    MANAGER_HEADERS,
    NO_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    PAGINATION_DEFAULT_LIMIT,
    PLAN_ABANDONED,
    PLAN_APPROVED,
    TIER_REPAIR_AND_RETREAT,
    TIER_RETREAT_ONLY,
    add_finding,
    adjudicate_claim,
    application_payload,
    approve_plan,
    assert_bond_money,
    assert_claim_money,
    assert_epa_number_shape,
    assert_instant_equals,
    assert_money,
    assert_status,
    assert_version,
    attach_verification,
    attested_graph_complete_payload,
    bond_payload,
    bonded_property,
    completed_bait_plan,
    completed_liquid_plan,
    conducive_finding_payload,
    damage_claim_payload,
    damage_finding_payload,
    damage_graph,
    file_claim,
    fumigation_plan_payload,
    graphed_inspection,
    inspection_payload,
    issue_bond,
    open_graph,
    property_payload,
    propose_plan,
    record_application,
    register_inspector,
    register_property,
    register_property_and_inspector,
    review_bond_term,
    set_clock,
    sign_empty_graph,
    sign_graph,
    treatment_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
)
from test_helpers.test_users import (
    headers_without_role,
    headers_without_user_id,
    make_applicator_headers,
    make_claims_adjudicator_headers,
    make_field_inspector_headers,
    make_property_owner_headers,
)

CLOCK_START = "2026-08-01T00:00:00Z"
ISSUE_INSTANT = "2026-09-01T00:00:00Z"
TERM_END_INSTANT = "2027-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Shape before body references, body references before the version guard
# ---------------------------------------------------------------------------


def test_a_bad_enum_outranks_an_unresolvable_property_reference(api):
    """A body carrying both an undeclared method and an unknown structure.

    PRD 2.6: request shape is stage 5 and body-reference existence is stage 8,
    and "the **first** violated check determines the response. No later check is
    evaluated once one has failed."

    Design: Corner/validations/shape_check_outranks_body_reference_resolution
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], inspector["id"])

    malformed = treatment_plan_payload(
        NON_EXISTENT_UUID, graph["id"], inspector["id"], method="TENTING"
    )
    validate_error(
        api.create_treatment_plan(malformed, MANAGER_HEADERS), ERR_INVALID_REQUEST
    )

    well_formed = treatment_plan_payload(
        NON_EXISTENT_UUID, graph["id"], inspector["id"]
    )
    validate_error(
        api.create_treatment_plan(well_formed, MANAGER_HEADERS),
        ERR_PROPERTY_NOT_FOUND,
    )

    _, meta = validate_paginated(api.list_treatment_plans(OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "neither refused proposal may persist a plan, got %r" % meta["total_count"]
    )


def test_an_unknown_field_in_the_same_body_is_ignored_rather_than_rejected(api):
    """Shape validation rejects bad declared fields, not undeclared extras.

    PRD 2.6: "Unknown fields are ignored rather than rejected."

    Design: Corner/validations/shape_check_outranks_body_reference_resolution
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    payload = treatment_plan_payload(
        prop["id"], graph["id"], inspector["id"], surprise_field="ignore me"
    )
    plan = validate_success(api.create_treatment_plan(payload, MANAGER_HEADERS), 201)
    assert "surprise_field" not in plan, (
        "an ignored field must not be echoed back on the resource: %r" % sorted(plan)
    )


def test_an_unknown_bond_reference_outranks_a_stale_version_expectation(api):
    """A claim naming a missing bond and a wrong version reports the 404.

    PRD 2.6: "This check runs after shape validation and, critically, **before**
    the stale-version check of stage 9: a claim filing that carries both an
    unknown bond reference and a stale expected version reports the 404, never
    the 412."

    Design: Corner/validations/body_reference_resolution_outranks_the_occ_version_guard
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    prop = chain["property"]
    owner = make_property_owner_headers(prop["id"])

    payload = damage_claim_payload(NON_EXISTENT_UUID, 99, 1000.00)
    validate_error(api.create_damage_claim(payload, owner), ERR_BOND_NOT_FOUND)

    bond = chain["bond"]
    assert_version(bond, 1, "bond")
    good = damage_claim_payload(bond["id"], bond["version"], 1000.00)
    claim = validate_success(api.create_damage_claim(good, owner), 201)
    assert_status(claim, CLAIM_SUBMITTED, "damage_claim")

    reread = validate_success(api.get_bond(bond["id"], OFFICER_HEADERS))
    assert_version(reread, 2, "bond")


def test_replaying_the_consumed_bond_version_is_refused_by_the_guard(api):
    """The second blind filing against the same bond fails its version check.

    PRD 2.7: "Filing a damage claim ... requires the non-optional field
    `expected_bond_version` ... If that value does not equal the bond's current
    `version`, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/body_reference_resolution_outranks_the_occ_version_guard
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    prop = chain["property"]
    bond = chain["bond"]
    owner = make_property_owner_headers(prop["id"])

    first = damage_claim_payload(bond["id"], bond["version"], 1000.00)
    validate_success(api.create_damage_claim(first, owner), 201)

    replay = damage_claim_payload(bond["id"], bond["version"], 500.00)
    validate_error(api.create_damage_claim(replay, owner), ERR_STALE_VERSION)

    reread = validate_success(api.get_bond(bond["id"], OFFICER_HEADERS))
    assert_version(reread, 2, "bond")
    _, meta = validate_paginated(
        api.list_damage_claims(OFFICER_HEADERS, bond_id=bond["id"])
    )
    assert meta["total_count"] == 1, (
        "the refused replay must not persist a second claim, got %r"
        % meta["total_count"]
    )


# ---------------------------------------------------------------------------
# Authentication before authorisation; pagination on every collection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [NO_HEADERS, headers_without_user_id(), headers_without_role()],
    ids=["both-absent", "empty-user-id", "empty-role"],
)
def test_an_incomplete_identity_is_refused_before_the_role_is_considered(api, headers):
    """A missing or empty identity header answers 401, never 403.

    PRD 2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about it is examined."

    Design: Corner/validations/auth_header_missing_x_user_role_outranks_the_role_check
    """
    validate_error(
        api.create_property(property_payload(), headers), ERR_UNAUTHENTICATED
    )
    _, meta = validate_paginated(api.list_properties(OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "an unauthenticated write must persist nothing, got %r" % meta["total_count"]
    )


def test_a_complete_identity_in_the_wrong_role_is_refused_at_the_next_stage(api):
    """Only once both headers are present does the role check speak.

    PRD 2.1: "If `X-User-Role` is not one of the six declared roles, or is a
    declared role that the target operation does not admit, the rejection is
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/auth_header_missing_x_user_role_outranks_the_role_check
    """
    validate_error(
        api.create_property(
            property_payload(), make_property_owner_headers("owner-9")
        ),
        ERR_UNAUTHORIZED,
    )


def test_the_clock_read_is_the_one_endpoint_exempt_from_the_headers(api):
    """A caller supplying no identity headers at all may still read the clock.

    PRD 2.5: "any caller may read the clock's present value without supplying
    authentication headers at all — the clock read is the single endpoint exempt
    from the header requirement."

    Design: Corner/validations/auth_header_missing_x_user_role_outranks_the_role_check
    """
    reading = validate_success(api.get_clock())
    assert_instant_equals(reading["current_utc"], CLOCK_START)


def _list_collection(api, collection, params):
    """Read one of the three top-level collections with the supplied paging."""
    if collection == "properties":
        return api.list_properties(OFFICER_HEADERS, params=params)
    if collection == "inspections":
        return api.list_inspections(OFFICER_HEADERS, params=params)
    return api.list_bonds(OFFICER_HEADERS, params=params)


@pytest.mark.parametrize("collection", ["properties", "inspections", "bonds"])
@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}],
    ids=["limit-below-one", "limit-above-hundred", "negative-offset"],
)
def test_out_of_range_paging_is_refused_on_every_collection(api, collection, params):
    """Each of the three out-of-range paging inputs is refused everywhere.

    PRD 2.3: "When `limit` falls outside the range 1 through 100, or `offset` is
    negative, or either value is not an integer, the read is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_bounds_are_enforced_on_every_list_endpoint
    """
    validate_error(_list_collection(api, collection, params), ERR_INVALID_PAGINATION)


def test_the_inclusive_paging_boundaries_are_accepted(api):
    """A limit of exactly 100 and an offset of exactly 0 are legal.

    PRD 2.3: "`limit` controls page size: it defaults to 10, may not be smaller
    than 1, and may not be larger than 100. `offset` controls the starting
    position: it defaults to 0 and may not be negative."

    Design: Corner/validations/pagination_bounds_are_enforced_on_every_list_endpoint
    """
    set_clock(api, CLOCK_START)
    register_property(api)
    register_property(api, address_line1="24 Live Oak Terrace")

    rows, meta = validate_paginated(
        api.list_properties(OFFICER_HEADERS, params={"limit": 100, "offset": 0})
    )
    assert meta["limit"] == 100, "the accepted limit must be echoed back"
    assert meta["offset"] == 0, "the accepted offset must be echoed back"
    assert meta["total_count"] == 2, (
        "both structures must be counted, got %r" % meta["total_count"]
    )
    assert len(rows) == 2, "a 100-row page holds both structures, got %r" % len(rows)
    assert meta["has_more"] is False, "no rows remain beyond a 100-row page"


def test_a_page_beyond_the_last_row_is_empty_but_still_counts_the_matches(api):
    """total_count reports the matching rows before paging, not after it.

    PRD 2.3: "Both values are echoed back in `meta` alongside `total_count`, the
    number of rows matching the request before paging, and `has_more`, which is
    true exactly when rows remain beyond the current page."

    Design: Corner/validations/pagination_bounds_are_enforced_on_every_list_endpoint
    """
    set_clock(api, CLOCK_START)
    register_property(api)
    register_property(api, address_line1="24 Live Oak Terrace")

    rows, meta = validate_paginated(
        api.list_properties(OFFICER_HEADERS, params={"limit": 1, "offset": 500})
    )
    assert rows == [], "a page past the end carries no rows, got %r" % rows
    assert meta["total_count"] == 2, (
        "the total ignores the page window, got %r" % meta["total_count"]
    )
    assert meta["has_more"] is False, "nothing remains beyond an exhausted collection"

    first_page, first_meta = validate_paginated(
        api.list_properties(OFFICER_HEADERS, params={"limit": 1, "offset": 0})
    )
    assert len(first_page) == 1, "a one-row page holds one row"
    assert first_meta["has_more"] is True, "a second structure remains beyond page one"


def test_omitting_the_paging_parameters_yields_the_declared_defaults(api):
    """An unqualified collection read pages with limit 10 from offset 0.

    PRD 2.3: "Every collection read accepts two optional query parameters.
    `limit` controls page size: it defaults to 10 ... `offset` controls the
    starting position: it defaults to 0."

    Design: Corner/validations/pagination_bounds_are_enforced_on_every_list_endpoint
    """
    set_clock(api, CLOCK_START)
    register_property(api)

    _, meta = validate_paginated(api.list_properties(OFFICER_HEADERS))
    assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, (
        "the default page size is 10, got %r" % meta["limit"]
    )
    assert meta["offset"] == 0, "the default offset is 0, got %r" % meta["offset"]


# ---------------------------------------------------------------------------
# Jurisdiction and endorsement gates
# ---------------------------------------------------------------------------


def test_an_out_of_state_licence_may_not_open_a_graph(api):
    """A Florida credential cannot be pointed at a Georgia structure.

    PRD 2.6: "The acting inspector's `license_state` equals the `state_code` of
    the structure being inspected or treated; a licence issued by another state
    may neither sign a graph nor discharge a pesticide."

    Design: Corner/validations/licence_state_must_match_the_property_state_on_both_gated_endpoints
    """
    set_clock(api, CLOCK_START)
    georgia = register_property(api, state_code="GA", address_line1="44 Peachtree Ridge")
    florida = register_property(api)
    inspector = register_inspector(api, license_state="FL")

    payload = inspection_payload(georgia["id"], inspector["id"])
    validate_error(
        api.create_inspection(payload, make_field_inspector_headers(inspector["id"])),
        ERR_LICENSE_STATE_MISMATCH,
    )

    graph = open_graph(api, florida["id"], inspector["id"])
    assert_status(graph, INSPECTION_DRAFT, "inspection")
    _, meta = validate_paginated(
        api.list_inspections(OFFICER_HEADERS, property_id=georgia["id"])
    )
    assert meta["total_count"] == 0, (
        "the refused graph must not have been opened, got %r" % meta["total_count"]
    )


def test_an_out_of_state_licence_may_not_discharge_a_pesticide(api):
    """The same jurisdiction rule guards the application endpoint.

    PRD 3.6: "The acting applicator must be the plan's `applicator_id`, must hold
    an `ACTIVE` licence whose `license_expires_on` is not before the clock date,
    must hold a `license_state` equal to the treated structure's `state_code`."

    Design: Corner/validations/licence_state_must_match_the_property_state_on_both_gated_endpoints
    """
    set_clock(api, CLOCK_START)
    prop, local = register_property_and_inspector(
        api, state_code="GA", address_line1="44 Peachtree Ridge"
    )
    graph = graphed_inspection(api, prop["id"], local["id"])
    foreigner = register_inspector(api, license_state="FL", full_name="Rosa Ibarra")

    plan = approve_plan(
        api, propose_plan(api, prop["id"], graph["id"], foreigner["id"])["id"]
    )
    assert_status(plan, PLAN_APPROVED, "treatment_plan")

    validate_error(
        api.create_application(
            plan["id"],
            application_payload(plan["version"]),
            make_applicator_headers(foreigner["id"]),
        ),
        ERR_LICENSE_STATE_MISMATCH,
    )

    reread = validate_success(api.get_treatment_plan(plan["id"], OFFICER_HEADERS))
    assert_money(reread["gallons_applied_total"], 0.00)
    assert_version(reread, plan["version"], "treatment_plan")
    _, meta = validate_paginated(api.list_applications(plan["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "the refused discharge must not persist a record, got %r" % meta["total_count"]
    )


def _fumigation_plan_for(api, prop_id, graph_id, applicator_id, permit, start, reentry):
    """Propose and approve one fumigation plan for the supplied applicator."""
    payload = fumigation_plan_payload(
        prop_id,
        graph_id,
        applicator_id,
        fumigation_start_at=start,
        fumigation_reentry_at=reentry,
        fumigation_permit_number=permit,
    )
    plan = validate_success(api.create_treatment_plan(payload, MANAGER_HEADERS), 201)
    return approve_plan(api, plan["id"])


def test_a_fumigant_discharge_without_the_endorsement_flag_is_refused(api):
    """The certification alone does not license a fumigant discharge.

    PRD 2.9: "Recording a pesticide application against a `FUMIGATION` plan
    requires both `FUMIGATION_CERTIFIED` among the categories **and**
    `fumigation_endorsement` set to true — the certification and the endorsement
    are separate facts and both are demanded."

    Design: Corner/validations/fumigation_application_needs_the_category_and_the_endorsement_flag
    """
    set_clock(api, CLOCK_START)
    prop, signer = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], signer["id"])
    unendorsed = register_inspector(
        api,
        license_state="FL",
        full_name="Teodor Vance",
        license_categories=[CATEGORY_TERMITE_APPLICATOR, CATEGORY_FUMIGATION_CERTIFIED],
        fumigation_endorsement=False,
    )
    plan = _fumigation_plan_for(
        api,
        prop["id"],
        graph["id"],
        unendorsed["id"],
        "FUM-004417",
        "2026-08-10T08:00:00Z",
        "2026-08-12T08:00:00Z",
    )

    set_clock(api, "2026-08-10T12:00:00Z")
    validate_error(
        api.create_application(
            plan["id"],
            application_payload(
                plan["version"], gallons_applied=0.10, product_epa_number="1015-88"
            ),
            make_applicator_headers(unendorsed["id"]),
        ),
        ERR_CATEGORY_NOT_LICENSED,
    )

    reread = validate_success(api.get_treatment_plan(plan["id"], OFFICER_HEADERS))
    assert_status(reread, PLAN_APPROVED, "treatment_plan")
    assert_version(reread, plan["version"], "treatment_plan")
    _, meta = validate_paginated(api.list_applications(plan["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "an unlicensed discharge must not be recorded, got %r" % meta["total_count"]
    )


def test_a_fully_endorsed_applicator_may_discharge_the_fumigant(api):
    """Both facts present, the same discharge is accepted.

    PRD 2.9: "Endorsement requirements are checked per operation, and a missing
    endorsement blocks the request even when the licence is `ACTIVE` and
    unexpired."

    Design: Corner/validations/fumigation_application_needs_the_category_and_the_endorsement_flag
    """
    set_clock(api, CLOCK_START)
    prop, signer = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], signer["id"])
    endorsed = register_inspector(
        api,
        license_state="FL",
        full_name="Teodor Vance",
        license_categories=[CATEGORY_TERMITE_APPLICATOR, CATEGORY_FUMIGATION_CERTIFIED],
        fumigation_endorsement=True,
    )
    plan = _fumigation_plan_for(
        api,
        prop["id"],
        graph["id"],
        endorsed["id"],
        "FUM-004418",
        "2026-08-10T08:00:00Z",
        "2026-08-12T08:00:00Z",
    )

    set_clock(api, "2026-08-10T12:00:00Z")
    record = validate_success(
        api.create_application(
            plan["id"],
            application_payload(
                plan["version"], gallons_applied=0.10, product_epa_number="1015-88"
            ),
            make_applicator_headers(endorsed["id"]),
        ),
        201,
    )
    assert_instant_equals(record["applied_at"], "2026-08-10T12:00:00Z")
    assert_epa_number_shape(record["product_epa_number"])
    assert record["applicator_license_number"] == endorsed["license_number"], (
        "the record snapshots the acting licence number, got %r"
        % record["applicator_license_number"]
    )
    assert record["applicator_license_state"] == "FL", (
        "the record snapshots the acting licence state, got %r"
        % record["applicator_license_state"]
    )
    assert record["state_code"] == "FL", (
        "the record snapshots the treated structure's jurisdiction, got %r"
        % record["state_code"]
    )


# ---------------------------------------------------------------------------
# Completeness and uniqueness inside one graph
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{}, {"no_findings_attested": False}],
    ids=["attestation-omitted", "attestation-false"],
)
def test_an_unattested_empty_graph_may_not_be_signed(api, body):
    """A graph with nothing on it needs the inspector's formal attestation.

    PRD 3.3: "A graph with no cell notations at all may only be signed when the
    request sets `no_findings_attested` to true ... without that attestation a
    zero-notation graph is refused with `ERR_GRAPH_INCOMPLETE`."

    Design: Corner/validations/zero_finding_graph_completion_requires_the_attestation
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])

    validate_error(
        api.graph_complete(
            graph["id"], body, make_field_inspector_headers(inspector["id"])
        ),
        ERR_GRAPH_INCOMPLETE,
    )

    reread = validate_success(api.get_inspection(graph["id"], OFFICER_HEADERS))
    assert_status(reread, INSPECTION_DRAFT, "inspection")
    assert reread["graph_completed_at"] is None, (
        "a refused signing must leave graph_completed_at null, got %r"
        % reread["graph_completed_at"]
    )


def test_an_attested_empty_graph_signs_and_persists_the_attestation(api):
    """The attestation is stored on the graph it justified.

    PRD 3.3: "The submitted value of `no_findings_attested` is persisted on the
    graph, defaulting to false when the request omits it."

    Design: Corner/validations/zero_finding_graph_completion_requires_the_attestation
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    signed = sign_empty_graph(api, graph["id"], inspector["id"])

    assert_status(signed, INSPECTION_GRAPHED, "inspection")
    assert signed["no_findings_attested"] is True, (
        "the supplied attestation must be persisted, got %r"
        % signed["no_findings_attested"]
    )
    assert signed["findings_count"] == 0, (
        "an empty graph counts no notations, got %r" % signed["findings_count"]
    )
    assert_instant_equals(signed["graph_completed_at"], CLOCK_START)


def test_a_graph_carrying_one_notation_needs_no_attestation(api):
    """The attestation is demanded only of a zero-notation graph.

    PRD 3.3: "`findings_count` is the number of notations on the graph."

    Design: Corner/validations/zero_finding_graph_completion_requires_the_attestation
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api, graph["id"], inspector["id"], damage_finding_payload("C5", 1200.00)
    )
    signed = sign_graph(api, graph["id"], inspector["id"])

    assert_status(signed, INSPECTION_GRAPHED, "inspection")
    assert signed["no_findings_attested"] is False, (
        "an omitted attestation defaults to false, got %r"
        % signed["no_findings_attested"]
    )
    assert signed["findings_count"] == 1, (
        "the single notation must be counted, got %r" % signed["findings_count"]
    )


def test_one_cell_may_not_carry_two_notations_of_the_same_type(api):
    """A second DAMAGE notation on cell C5 is refused as a duplicate.

    PRD 3.3: "Within one graph the pair of `grid_ref` and `finding_type` must be
    unique ... but never two notations of the same type; the second attempt is
    `ERR_DUPLICATE_GRID_FINDING`."

    Design: Corner/validations/grid_ref_and_finding_type_pair_is_unique_within_one_graph
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api, graph["id"], inspector["id"], damage_finding_payload("C5", 1200.00)
    )

    validate_error(
        api.create_finding(
            graph["id"],
            damage_finding_payload("C5", 900.00),
            make_field_inspector_headers(inspector["id"]),
        ),
        ERR_DUPLICATE_GRID_FINDING,
    )

    rows, meta = validate_paginated(
        api.list_findings(graph["id"], OFFICER_HEADERS, finding_type=FINDING_DAMAGE)
    )
    assert meta["total_count"] == 1, (
        "the duplicate must not have been written, got %r" % meta["total_count"]
    )
    assert_money(rows[0]["damage_estimate_usd"], 1200.00)


def test_one_cell_may_carry_two_notations_of_different_types(api):
    """Uniqueness is on the pair, so a conducive note joins the damage note.

    PRD 3.3: "The same cell may legitimately carry both a `DAMAGE` notation and a
    `CONDUCIVE_CONDITION` notation — rotten sill plate above a wood-to-ground
    contact — but never two notations of the same type."

    Design: Corner/validations/grid_ref_and_finding_type_pair_is_unique_within_one_graph
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api, graph["id"], inspector["id"], damage_finding_payload("C5", 1200.00)
    )
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        conducive_finding_payload("C5", CONDUCIVE_WOOD_TO_GROUND),
    )
    signed = sign_graph(api, graph["id"], inspector["id"])

    assert signed["findings_count"] == 2, (
        "both notations belong to the graph, got %r" % signed["findings_count"]
    )
    assert signed["conducive_condition_count"] == 1, (
        "exactly one notation is conducive, got %r"
        % signed["conducive_condition_count"]
    )
    assert_money(signed["damage_estimate_total_usd"], 1200.00)


def test_the_uniqueness_rule_is_scoped_to_a_single_graph(api):
    """Cell C5 may be notated again on a different graph of the same structure.

    PRD 3.3: "Within one graph the pair of `grid_ref` and `finding_type` must be
    unique."

    Design: Corner/validations/grid_ref_and_finding_type_pair_is_unique_within_one_graph
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    first = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api, first["id"], inspector["id"], damage_finding_payload("C5", 1200.00)
    )
    second = open_graph(api, prop["id"], inspector["id"])

    notation = validate_success(
        api.create_finding(
            second["id"],
            damage_finding_payload("C5", 900.00),
            make_field_inspector_headers(inspector["id"]),
        ),
        201,
    )
    assert notation["grid_ref"] == "C5", (
        "the second graph accepts the same cell, got %r" % notation["grid_ref"]
    )
    _, first_meta = validate_paginated(
        api.list_findings(first["id"], OFFICER_HEADERS)
    )
    _, second_meta = validate_paginated(
        api.list_findings(second["id"], OFFICER_HEADERS)
    )
    assert first_meta["total_count"] == 1, "the first graph keeps its own notation"
    assert second_meta["total_count"] == 1, "the second graph carries its own notation"


# ---------------------------------------------------------------------------
# One encumbrance per structure; coverage windows
# ---------------------------------------------------------------------------


def _two_completed_treatments(api):
    """One structure, one signed graph and two COMPLETED treatments on it."""
    prop, inspector = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    liquid = completed_liquid_plan(api, prop["id"], graph["id"], inspector["id"])
    bait = completed_bait_plan(api, prop["id"], graph["id"], inspector["id"])
    return prop, graph, liquid, bait


def test_a_structure_may_not_hold_two_active_bonds(api):
    """The second issuance against a bonded structure is refused.

    PRD 3.7: "a structure may hold at most one bond in status `ACTIVE` or
    `LAPSED` at any instant, and a second issuance is refused with
    `ERR_DUPLICATE_ACTIVE_BOND`."

    Design: Corner/validations/second_bond_is_refused_while_the_first_one_is_merely_lapsed
    """
    set_clock(api, CLOCK_START)
    prop, _graph, liquid, bait = _two_completed_treatments(api)
    set_clock(api, ISSUE_INSTANT)
    first = issue_bond(api, prop["id"], liquid["id"])
    assert_status(first, BOND_ACTIVE, "bond")

    validate_error(
        api.create_bond(
            bond_payload(prop["id"], bait["id"], coverage_tier=TIER_RETREAT_ONLY),
            MANAGER_HEADERS,
        ),
        ERR_DUPLICATE_ACTIVE_BOND,
    )

    _, meta = validate_paginated(
        api.list_bonds(OFFICER_HEADERS, property_id=prop["id"])
    )
    assert meta["total_count"] == 1, (
        "the structure keeps exactly one bond, got %r" % meta["total_count"]
    )


def test_a_lapsed_bond_still_encumbers_the_structure(api):
    """A bond mid-lapse blocks a replacement just as an active one does.

    PRD 3.7: "a second issuance is refused with `ERR_DUPLICATE_ACTIVE_BOND` even
    when the first bond is mid-lapse — a lapsed bond is still an encumbrance on
    the structure until it terminates."

    Design: Corner/validations/second_bond_is_refused_while_the_first_one_is_merely_lapsed
    """
    set_clock(api, CLOCK_START)
    prop, _graph, liquid, bait = _two_completed_treatments(api)
    set_clock(api, ISSUE_INSTANT)
    first = issue_bond(api, prop["id"], liquid["id"])
    assert first["current_term_end"] == "2027-09-01", (
        "the term ends 365 days after issuance, got %r" % first["current_term_end"]
    )

    set_clock(api, "2027-10-02T00:00:00Z")
    lapsed = review_bond_term(api, first["id"])
    assert_status(lapsed, BOND_LAPSED, "bond")
    assert lapsed["lapse_date"] == "2027-10-01", (
        "the lapse date is the grace deadline that was missed, got %r"
        % lapsed["lapse_date"]
    )

    validate_error(
        api.create_bond(
            bond_payload(prop["id"], bait["id"], coverage_tier=TIER_RETREAT_ONLY),
            MANAGER_HEADERS,
        ),
        ERR_DUPLICATE_ACTIVE_BOND,
    )

    rows, meta = validate_paginated(
        api.list_bonds(OFFICER_HEADERS, property_id=prop["id"])
    )
    assert meta["total_count"] == 1, (
        "no replacement bond may be written, got %r" % meta["total_count"]
    )
    assert_status(rows[0], BOND_LAPSED, "bond")


def test_damage_reported_on_the_first_day_of_the_term_is_covered(api):
    """The opening boundary of the coverage window is inclusive.

    PRD 3.10: "The clock's UTC date, which stamps `reported_at`, must also fall
    inside the bond's current coverage window — on or after `current_term_start`
    and on or before `current_term_end`, both inclusive."

    Design: Corner/validations/damage_reported_one_day_past_the_term_end_is_outside_coverage
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    bond = chain["bond"]
    assert bond["current_term_start"] == "2026-09-01", (
        "the term opens on the issuance date, got %r" % bond["current_term_start"]
    )

    claim = file_claim(api, bond, chain["property"]["id"], 1000.00)
    assert_status(claim, CLAIM_SUBMITTED, "damage_claim")
    assert_instant_equals(claim["reported_at"], ISSUE_INSTANT)


def test_damage_reported_on_the_last_day_of_the_term_is_covered(api):
    """The closing boundary of the coverage window is inclusive too.

    PRD 3.7: "`current_term_end` is 365 days after `current_term_start` and is
    the inclusive last date of the term."

    Design: Corner/validations/damage_reported_one_day_past_the_term_end_is_outside_coverage
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    bond = chain["bond"]
    assert bond["current_term_end"] == "2027-09-01", (
        "the term ends 365 days after it opened, got %r" % bond["current_term_end"]
    )

    set_clock(api, TERM_END_INSTANT)
    claim = file_claim(api, bond, chain["property"]["id"], 1000.00)
    assert_status(claim, CLAIM_SUBMITTED, "damage_claim")
    assert_instant_equals(claim["reported_at"], TERM_END_INSTANT)


def test_damage_reported_one_day_past_the_term_end_is_outside_coverage(api):
    """One day beyond the inclusive end, the same filing is refused.

    PRD 3.10: "damage reported outside the current term is not covered by it; a
    filing outside the window is `ERR_DAMAGE_OUTSIDE_TERM`."

    Design: Corner/validations/damage_reported_one_day_past_the_term_end_is_outside_coverage
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    prop = chain["property"]
    bond = chain["bond"]
    file_claim(api, bond, prop["id"], 1000.00)

    set_clock(api, "2027-09-02T00:00:00Z")
    reread = validate_success(api.get_bond(bond["id"], OFFICER_HEADERS))
    assert_status(reread, BOND_ACTIVE, "bond")
    validate_error(
        api.create_damage_claim(
            damage_claim_payload(bond["id"], reread["version"], 1000.00),
            make_property_owner_headers(prop["id"]),
        ),
        ERR_DAMAGE_OUTSIDE_TERM,
    )

    _, meta = validate_paginated(
        api.list_damage_claims(OFFICER_HEADERS, bond_id=bond["id"])
    )
    assert meta["total_count"] == 1, (
        "the out-of-term filing must not persist a claim, got %r"
        % meta["total_count"]
    )
    final = validate_success(api.get_bond(bond["id"], OFFICER_HEADERS))
    assert_version(final, 2, "bond")


# ---------------------------------------------------------------------------
# Retention, segregation of duties and ownership
# ---------------------------------------------------------------------------


def _approved_plan_with_one_record(api):
    """An APPROVED Florida plan carrying exactly one pesticide record."""
    prop, inspector = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    plan = approve_plan(
        api, propose_plan(api, prop["id"], graph["id"], inspector["id"])["id"]
    )
    record_application(
        api, plan["id"], inspector["id"], plan["version"], gallons_applied=95.00
    )
    return prop, inspector, plan


@pytest.mark.parametrize(
    "instant",
    [CLOCK_START, "2030-07-31T23:59:59Z"],
    ids=["day-of-discharge", "last-retained-day"],
)
def test_abandonment_is_locked_while_a_record_is_still_retained(api, instant):
    """The lock holds for as long as the record's retention date has not passed.

    PRD 3.6: "A plan may not be abandoned while **any** of its pesticide records
    still has a `retention_until` on or after the clock's UTC date; the refusal is
    `ERR_RETENTION_LOCK_ACTIVE`."

    Design: Corner/validations/retention_lock_blocks_abandonment_until_the_record_expires
    """
    set_clock(api, CLOCK_START)
    _prop, _inspector, plan = _approved_plan_with_one_record(api)

    set_clock(api, instant)
    validate_error(
        api.abandon_treatment_plan(plan["id"], {}, MANAGER_HEADERS),
        ERR_RETENTION_LOCK_ACTIVE,
    )
    reread = validate_success(api.get_treatment_plan(plan["id"], OFFICER_HEADERS))
    assert_status(reread, PLAN_APPROVED, "treatment_plan")


def test_abandonment_succeeds_the_day_after_the_record_ages_out(api):
    """One day past the Florida retention deadline the plan abandons.

    PRD 3.6: "the practical consequence is that a plan which has discharged
    chemical can only be abandoned once every one of its records has aged out of
    its state retention period."

    Design: Corner/validations/retention_lock_blocks_abandonment_until_the_record_expires
    """
    set_clock(api, CLOCK_START)
    _prop, _inspector, plan = _approved_plan_with_one_record(api)

    set_clock(api, "2030-08-01T00:00:00Z")
    abandoned = validate_success(
        api.abandon_treatment_plan(plan["id"], {}, MANAGER_HEADERS)
    )
    assert_status(abandoned, PLAN_ABANDONED, "treatment_plan")

    rows, meta = validate_paginated(api.list_applications(plan["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 1, (
        "the record outlives the plan it belonged to, got %r" % meta["total_count"]
    )
    assert rows[0]["retention_until"] == "2030-07-31", (
        "four Florida retention years are 1460 days, got %r"
        % rows[0]["retention_until"]
    )


def test_a_plan_that_discharged_nothing_abandons_freely(api):
    """With no records there is nothing to retain and nothing to lock.

    PRD 3.6: "A plan that never discharged anything has no records and abandons
    freely."

    Design: Corner/validations/retention_lock_blocks_abandonment_until_the_record_expires
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    plan = approve_plan(
        api, propose_plan(api, prop["id"], graph["id"], inspector["id"])["id"]
    )

    abandoned = validate_success(
        api.abandon_treatment_plan(plan["id"], {}, MANAGER_HEADERS)
    )
    assert_status(abandoned, PLAN_ABANDONED, "treatment_plan")
    _, meta = validate_paginated(api.list_applications(plan["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "no record was ever written, got %r" % meta["total_count"]
    )


def _retreat_only_claim_awaiting_decision(api):
    """A verified RETREAT claim on a RETREAT_ONLY bond the manager underwrote."""
    chain = bonded_property(api, coverage_tier=TIER_RETREAT_ONLY, issue_instant=ISSUE_INSTANT)
    prop = chain["property"]
    bond = chain["bond"]
    assert bond["issued_by_user_id"] == BRANCH_MANAGER_ID, (
        "the underwriting operator is recorded on the bond, got %r"
        % bond["issued_by_user_id"]
    )
    peer = register_inspector(api, license_state="FL", full_name="Ines Duarte Alvarez")
    verifier_graph = damage_graph(
        api, prop["id"], peer["id"], [("E4", 6000.00, False, 2)]
    )
    claim = file_claim(
        api, bond, prop["id"], 3000.00, claim_type=CLAIM_TYPE_RETREAT
    )
    claim = attach_verification(api, claim["id"], verifier_graph["id"], peer["id"])
    assert_status(claim, CLAIM_UNDER_ADJUDICATION, "damage_claim")
    assert_claim_money(
        claim,
        eligible_damage_usd=3000.00,
        deductible_usd=210.00,
        projected_payout_usd=0.00,
    )
    return chain, claim


def test_the_underwriting_manager_may_not_adjudicate_its_own_bond(api):
    """A duties conflict is reported ahead of the coverage-tier objection.

    PRD 2.6: "Segregation of duties on adjudication. The adjudicating
    `X-User-ID` differs from the bond's `issued_by_user_id` — otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/validations/segregation_of_duties_outranks_the_coverage_tier_check
    """
    chain, claim = _retreat_only_claim_awaiting_decision(api)
    validate_error(
        api.adjudicate_claim(
            claim["id"],
            {"decision": DECISION_APPROVE_REPAIR},
            make_claims_adjudicator_headers(BRANCH_MANAGER_ID),
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    reread = validate_success(api.get_damage_claim(claim["id"], OFFICER_HEADERS))
    assert_status(reread, CLAIM_UNDER_ADJUDICATION, "damage_claim")
    assert reread["adjudicated_by_user_id"] is None, (
        "a refused decision records no adjudicator, got %r"
        % reread["adjudicated_by_user_id"]
    )
    assert chain["bond"]["coverage_tier"] == TIER_RETREAT_ONLY


def test_an_independent_adjudicator_then_meets_the_coverage_tier_objection(api):
    """With the duties conflict removed the tier check speaks.

    PRD 3.10: "`APPROVE_REPAIR` ... requires the bond's `coverage_tier` to be
    `REPAIR_AND_RETREAT`, since a retreat-only bond cannot pay for repairs at
    all — the refusal is `ERR_TIER_EXCLUDES_REPAIR`."

    Design: Corner/validations/segregation_of_duties_outranks_the_coverage_tier_check
    """
    _chain, claim = _retreat_only_claim_awaiting_decision(api)
    validate_error(
        api.adjudicate_claim(
            claim["id"],
            {"decision": DECISION_APPROVE_REPAIR},
            make_claims_adjudicator_headers(),
        ),
        ERR_TIER_EXCLUDES_REPAIR,
    )
    reread = validate_success(api.get_damage_claim(claim["id"], OFFICER_HEADERS))
    assert_status(reread, CLAIM_UNDER_ADJUDICATION, "damage_claim")


def test_the_retreat_only_branch_raises_an_obligation_without_paying(api):
    """The decision a retreat-only bond does admit costs no money.

    PRD 3.10: "`APPROVE_RETREAT_ONLY` moves the claim to
    `APPROVED_RETREAT_ONLY`, sets `approved_payout_usd` to 0.00 ... an obligation
    is raised: the bond's `retreat_required` is set true and its
    `retreat_credit_count` rises by one."

    Design: Corner/validations/segregation_of_duties_outranks_the_coverage_tier_check
    """
    chain, claim = _retreat_only_claim_awaiting_decision(api)
    decided = adjudicate_claim(
        api,
        claim["id"],
        DECISION_APPROVE_RETREAT_ONLY,
        headers=make_claims_adjudicator_headers(),
    )
    assert_status(decided, CLAIM_APPROVED_RETREAT_ONLY, "damage_claim")
    assert_claim_money(decided, approved_payout_usd=0.00)
    assert decided["adjudicated_by_user_id"] == CLAIMS_ADJUDICATOR_ID, (
        "the deciding operator is recorded, got %r"
        % decided["adjudicated_by_user_id"]
    )

    bond = validate_success(
        api.get_bond(chain["bond"]["id"], OFFICER_HEADERS)
    )
    assert bond["retreat_required"] is True, "the retreat obligation must be raised"
    assert bond["retreat_credit_count"] == 1, (
        "one retreat credit is owed, got %r" % bond["retreat_credit_count"]
    )
    assert_bond_money(
        bond,
        repair_liability_cap_usd=0.00,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=0.00,
    )


def test_the_treating_applicator_may_not_verify_the_damage_claimed_against_it(api):
    """The applicator who did the work cannot be the one who verifies the damage.

    PRD 3.10: "it must **not** be the `applicator_id` of the plan the bond was
    written against, or the attempt is `ERR_VERIFIER_IS_APPLICATOR`."

    Design: Corner/validations/the_treating_applicator_may_not_certify_the_damage_claimed_against_it
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    prop = chain["property"]
    applicator = chain["inspector"]
    claim = file_claim(api, chain["bond"], prop["id"], 4000.00)
    own_graph = damage_graph(
        api, prop["id"], applicator["id"], [("F6", 8000.00, False, 2)]
    )

    validate_error(
        api.attach_verification(
            claim["id"],
            verification_payload(own_graph["id"]),
            make_field_inspector_headers(applicator["id"]),
        ),
        ERR_VERIFIER_IS_APPLICATOR,
    )

    reread = validate_success(api.get_damage_claim(claim["id"], OFFICER_HEADERS))
    assert_status(reread, CLAIM_SUBMITTED, "damage_claim")
    assert reread["verifying_inspection_id"] is None, (
        "a refused verification attaches nothing, got %r"
        % reread["verifying_inspection_id"]
    )
    assert_claim_money(
        reread,
        eligible_damage_usd=0.00,
        deductible_usd=0.00,
        projected_payout_usd=0.00,
    )
    bond = validate_success(api.get_bond(chain["bond"]["id"], OFFICER_HEADERS))
    assert_bond_money(bond, reserved_claim_amount_usd=0.00)


def test_a_peer_inspector_may_verify_the_very_same_damage(api):
    """The same graph findings, signed by someone else, price the claim.

    PRD 3.10: "The graph's `inspector_id` must be the acting inspector, or the
    attempt is `ERR_NOT_RESOURCE_OWNER`, and it must **not** be the
    `applicator_id` of the plan the bond was written against."

    Design: Corner/validations/the_treating_applicator_may_not_certify_the_damage_claimed_against_it
    """
    chain = bonded_property(api, issue_instant=ISSUE_INSTANT)
    prop = chain["property"]
    assert chain["bond"]["coverage_tier"] == TIER_REPAIR_AND_RETREAT, (
        "this bond carries a monetary repair ceiling, got %r"
        % chain["bond"]["coverage_tier"]
    )
    peer = register_inspector(api, license_state="FL", full_name="Ines Duarte Alvarez")
    claim = file_claim(api, chain["bond"], prop["id"], 4000.00)
    peer_graph = damage_graph(
        api, prop["id"], peer["id"], [("F6", 8000.00, False, 2)]
    )

    verified = attach_verification(api, claim["id"], peer_graph["id"], peer["id"])
    assert_status(verified, CLAIM_UNDER_ADJUDICATION, "damage_claim")
    assert verified["verifying_inspection_id"] == peer_graph["id"]
    assert_claim_money(
        verified,
        eligible_damage_usd=4000.00,
        deductible_usd=280.00,
        projected_payout_usd=3720.00,
    )
    bond = validate_success(api.get_bond(chain["bond"]["id"], OFFICER_HEADERS))
    assert_bond_money(
        bond,
        repair_liability_cap_usd=11664.00,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=3720.00,
        remaining_repair_cap_usd=7944.00,
    )


def test_an_inspector_may_not_notate_or_sign_another_inspectors_graph(api):
    """Ownership is checked before the signing endorsement is looked at.

    PRD 2.1: "In the first three, the acting `FieldInspector`'s `X-User-ID` must
    equal the `inspector_id` carried by the graph ... A mismatch in any of the
    five is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/an_inspector_may_not_write_to_another_inspectors_rows
    """
    set_clock(api, CLOCK_START)
    prop, owner = register_property_and_inspector(api)
    intruder = register_inspector(
        api,
        license_state="FL",
        full_name="Rosa Ibarra",
        license_categories=[CATEGORY_TERMITE_APPLICATOR],
    )
    draft = open_graph(api, prop["id"], owner["id"])

    validate_error(
        api.create_finding(
            draft["id"],
            damage_finding_payload("A4", 500.00),
            make_field_inspector_headers(intruder["id"]),
        ),
        ERR_NOT_RESOURCE_OWNER,
    )
    validate_error(
        api.graph_complete(
            draft["id"],
            attested_graph_complete_payload(),
            make_field_inspector_headers(intruder["id"]),
        ),
        ERR_NOT_RESOURCE_OWNER,
    )

    reread = validate_success(api.get_inspection(draft["id"], OFFICER_HEADERS))
    assert_status(reread, INSPECTION_DRAFT, "inspection")
    assert reread["findings_count"] == 0, (
        "the intruder's notation must not exist, got %r" % reread["findings_count"]
    )
    _, meta = validate_paginated(api.list_findings(draft["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 0, (
        "the graph carries no notations, got %r" % meta["total_count"]
    )


def test_ownership_outranks_the_endorsement_check_on_a_discharge(api):
    """A stranger to the plan is refused as a stranger, not as unendorsed.

    PRD 2.1: "In the fourth, the acting `Applicator`'s `X-User-ID` must equal the
    `applicator_id` on the plan being discharged."

    Design: Corner/validations/an_inspector_may_not_write_to_another_inspectors_rows
    """
    set_clock(api, CLOCK_START)
    prop = register_property(api)
    signer = register_inspector(
        api,
        license_state="FL",
        full_name="Marcus Lindell",
        license_categories=[CATEGORY_WDO_INSPECTOR],
    )
    graph = graphed_inspection(api, prop["id"], signer["id"])
    applicator = register_inspector(
        api,
        license_state="FL",
        full_name="Rosa Ibarra",
        license_categories=[CATEGORY_TERMITE_APPLICATOR],
    )
    plan = approve_plan(
        api, propose_plan(api, prop["id"], graph["id"], applicator["id"])["id"]
    )

    validate_error(
        api.create_application(
            plan["id"],
            application_payload(plan["version"]),
            make_applicator_headers(signer["id"]),
        ),
        ERR_NOT_RESOURCE_OWNER,
    )

    record = record_application(
        api, plan["id"], applicator["id"], plan["version"], gallons_applied=95.00
    )
    assert_money(record["gallons_applied"], 95.00)
    reread = validate_success(api.get_treatment_plan(plan["id"], OFFICER_HEADERS))
    assert_money(reread["gallons_applied_total"], 95.00)
    _, meta = validate_paginated(api.list_applications(plan["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 1, (
        "only the plan's own applicator wrote a record, got %r" % meta["total_count"]
    )
