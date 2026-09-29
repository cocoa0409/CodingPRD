"""Who may act, and what happens to everyone else.

The first half of this module proves that each of the five roles can complete
the writes the specification reserves for it, and that the two shared write
surfaces really do accept either owner. The second half walks the four
authorisation rungs in the order §2.6 fixes for them, and then the one
segregation-of-duties rule that separates a submitting analyst from a
certifying one.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_FORBIDDEN_SCOPE,
    ERR_INVALID_ROLE,
    ERR_MISSING_AUTH,
    ERR_SAME_USER_CERTIFICATION,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import validate_unpaginated
from test_helpers.constants import (
    ACTION_OPEN,
    ALLERGEN_WHEAT,
    ANALYSIS_CERTIFIED,
    ANALYSIS_REJECTED,
    ANALYSIS_SUBMITTED,
    BOARD_PRIMARY_MENU_BOARD,
    CITATION_CALORIES_NOT_DECLARED,
    COVERAGE_NOT_COVERED,
    CROSS_CONTACT_NONE,
    DECISION_CERTIFY,
    DECISION_REJECT,
    ITEM_CLASS_STANDARD,
    LABELING_DECLARED,
    LISTING_LISTED,
    METHOD_DATABASE,
    METHOD_LAB_ANALYSIS,
    POSTURE_EXEMPT,
    PREEMPTION_PREEMPTED,
    PREEMPTION_VARIANCE_ALLOWED,
    REASON_NO_STANDARD_MENU_ITEMS,
    RECIPE_ANALYSIS_PENDING,
    RECIPE_APPROVED,
    RECIPE_DRAFT,
    REQUIREMENT_SUCCINCT_STATEMENT,
    ROLE_BASE,
    ROLE_BRAND_COMPLIANCE_OFFICER,
    STATEMENT_FEDERAL_DEFAULT,
    UNIT_OPERATING,
    UNIT_TEMPORARILY_CLOSED,
    VARIABLE_NONE,
    VARIANCE_DECISION_OPEN_REVIEW,
    VARIANCE_UNDER_REVIEW,
)
from test_helpers.factories import (
    analysis_decision_payload,
    component_payload,
    enforcement_action_payload,
    establishment_payload,
    listing_payload,
    menu_board_payload,
    menu_item_payload,
    recipe_payload,
    status_change_payload,
    submit_for_analysis_payload,
    variance_decision_payload,
    variance_request_payload,
)
from test_helpers.fixtures import (
    Env,
    add_components,
    make_brand,
    make_establishment,
    make_jurisdiction,
    open_recipe_version,
    seed_registry,
    set_clock,
    submit_recipe,
)
from test_helpers.test_users import (
    ANALYST_CERTIFIER,
    ANALYST_CERTIFIER_USER_ID,
    ANALYST_SUBMITTER,
    ANALYST_SUBMITTER_USER_ID,
    PLATFORM_ADMIN,
    UNKNOWN_ROLE,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    make_brand_officer_headers,
    make_publisher_headers,
    make_regulator_headers,
)


def _sandwich_as_served() -> Dict[str, Any]:
    """One BASE component of 100 g at 100 Cal per 100 g."""
    return component_payload(
        component_name="Sandwich as served",
        role=ROLE_BASE,
        grams=100,
        calories_per_100g=100,
        sodium_mg_per_100g=200,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_WHEAT,
        cross_contact_risk=CROSS_CONTACT_NONE,
    )


def test_the_five_roles_each_complete_the_writes_reserved_for_them(api):
    """Admin, officer, analyst pair and publisher each land their own write.

    PRD 2.1 hands each role its own writes. The program operator "registers
    chain brands, registers state and local authorities, registers and
    re-statuses units, runs coverage determinations on demand, and controls the
    service's logical clock." The brand's officer "owns the menu, the disclosure
    packet, variance filings and citation responses", the analyst "owns recipe
    versions, their components, and the certification decision", and the
    publisher "owns menu boards, the lines printed on them, publication and
    reprints." PRD 4 fixes the answers: "An operation that brings a new
    resource row into existence answers" 201, while "an operation that
    modifies, transitions or reads an existing resource answers" 200.

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_writes
    """
    env = seed_registry(
        api,
        code="NY-VAR",
        name="New York",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        unit_label="NY-0001",
        unit_label_prefix="NY-B",
    )

    item = validate_unpaginated(
        api.create_menu_item(
            menu_item_payload(
                brand_id=env.brand_id,
                name="Grill Sandwich",
                item_class=ITEM_CLASS_STANDARD,
                variable_type=VARIABLE_NONE,
                first_offered_on="2026-01-05",
            ),
            env.officer,
        ),
        201,
    )

    recipe = validate_unpaginated(
        api.create_recipe(
            item["id"],
            recipe_payload(
                expected_menu_item_version=item["version"],
                change_note="Initial specification",
            ),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    validate_unpaginated(
        api.add_recipe_component(
            recipe["id"], _sandwich_as_served(), ANALYST_SUBMITTER
        ),
        201,
    )
    analysis = validate_unpaginated(
        api.submit_for_analysis(
            recipe["id"],
            submit_for_analysis_payload(method=METHOD_DATABASE),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    decided = validate_unpaginated(
        api.decide_analysis(
            analysis["id"],
            analysis_decision_payload(
                decision=DECISION_CERTIFY,
                decision_note="Database values verified",
            ),
            ANALYST_CERTIFIER,
        )
    )
    assert decided["status"] == ANALYSIS_CERTIFIED
    assert env.read_item(item["id"])["labeling_status"] == LABELING_DECLARED

    board = validate_unpaginated(
        api.create_menu_board(
            menu_board_payload(
                establishment_id=env.establishment_id,
                board_type=BOARD_PRIMARY_MENU_BOARD,
                succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT,
            ),
            env.publisher,
        ),
        201,
    )
    listing = validate_unpaginated(
        api.create_listing(
            board["id"],
            listing_payload(menu_item_id=item["id"], sodium_warning_icon=False),
            env.publisher,
        ),
        201,
    )
    assert listing["listing_status"] == LISTING_LISTED
    assert env.read_board(board["id"])["listing_count"] == 1


def test_the_regulator_decides_a_variance_and_opens_a_citation(api):
    """The two writes the specification reserves for a `StateRegulator`.

    PRD 2.1: "When `X-User-Role` is `StateRegulator`, `X-User-ID` is the `id` of
    the acting `Jurisdiction`; ownership checks on any resource that references
    a `Jurisdiction` compare the resource's jurisdiction foreign key to
    `X-User-ID`. This role decides variance requests and drives enforcement."
    The brand's own officer owns the filing side, because that role "owns the
    menu, the disclosure packet, variance filings and citation responses".

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_writes
    """
    env = seed_registry(
        api,
        code="NY-VAR",
        name="New York",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        unit_label="NY-0001",
        unit_label_prefix="NY-B",
    )

    variance = validate_unpaginated(
        api.create_variance_request(
            variance_request_payload(
                brand_id=env.brand_id,
                jurisdiction_id=env.jurisdiction_id,
                requirement_code=REQUIREMENT_SUCCINCT_STATEMENT,
                justification="Signage vendor delay",
                requested_start_date="2026-09-01",
                requested_end_date="2026-09-30",
            ),
            env.officer,
        ),
        201,
    )

    reviewed = validate_unpaginated(
        api.decide_variance_request(
            variance["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_OPEN_REVIEW,
                decision_note="Docketed",
            ),
            env.regulator,
        )
    )
    assert reviewed["status"] == VARIANCE_UNDER_REVIEW
    assert env.read_variance(variance["id"])["status"] == VARIANCE_UNDER_REVIEW

    action = validate_unpaginated(
        api.create_enforcement_action(
            enforcement_action_payload(
                establishment_id=env.establishment_id,
                citation_code=CITATION_CALORIES_NOT_DECLARED,
                inspection_note="Routine inspection",
            ),
            env.regulator,
        ),
        201,
    )
    assert action["status"] == ACTION_OPEN
    assert action["citation_code"] == CITATION_CALORIES_NOT_DECLARED
    assert env.read_action(action["id"])["status"] == ACTION_OPEN


def _one_brand_and_one_unit(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """An authority, a brand, and the brand's first unit registered by the admin."""
    set_clock(api)
    jurisdiction = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    first = make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=jurisdiction["id"],
        unit_label="ID-0001",
        unit_status=UNIT_OPERATING,
    )
    return jurisdiction, brand, first


def test_both_owners_may_register_a_unit_and_move_its_status(api):
    """The two shared write surfaces accept the admin and the officer alike.

    PRD 3.1: "Units are registered either one at a time or in bulk, and either
    a `PlatformAdmin` or the brand's own `BrandComplianceOfficer` may do it."
    The status change is shared on the same terms: "When a
    `BrandComplianceOfficer` drives the change, its `X-User-ID` must equal the
    unit's `brand_id`." Each closure then re-counts, because "Each of the first
    three moves recomputes `Brand.counted_unit_count`, re-runs the coverage
    determination on the `OPERATING_ONLY` basis, and recomputes
    `compliance_posture`", and the basis counts only "the number of the brand's
    units whose `unit_status` is `OPERATING` and whose
    `operates_under_brand_name` is true".

    Design: Corner/rbac/shared_writes_accept_both_owners_and_reads_accept_every_role
    """
    jurisdiction, brand, first = _one_brand_and_one_unit(api)
    officer = make_brand_officer_headers(brand["id"])

    second = validate_unpaginated(
        api.create_establishment(
            establishment_payload(
                brand_id=brand["id"],
                jurisdiction_id=jurisdiction["id"],
                unit_label="ID-0002",
                unit_status=UNIT_OPERATING,
            ),
            officer,
        ),
        201,
    )
    assert second["unit_status"] == UNIT_OPERATING

    closed_by_officer = validate_unpaginated(
        api.change_establishment_status(
            first["id"],
            status_change_payload(
                new_unit_status=UNIT_TEMPORARILY_CLOSED, effective_note="Remodel"
            ),
            officer,
        )
    )
    closed_by_admin = validate_unpaginated(
        api.change_establishment_status(
            second["id"],
            status_change_payload(
                new_unit_status=UNIT_TEMPORARILY_CLOSED, effective_note="Remodel"
            ),
            PLATFORM_ADMIN,
        )
    )
    assert closed_by_officer["unit_status"] == UNIT_TEMPORARILY_CLOSED
    assert closed_by_admin["unit_status"] == UNIT_TEMPORARILY_CLOSED

    read_brand = validate_unpaginated(api.get_brand(brand["id"], PLATFORM_ADMIN))
    assert read_brand["counted_unit_count"] == 0
    assert read_brand["coverage_status"] == COVERAGE_NOT_COVERED
    assert read_brand["coverage_reason"] == REASON_NO_STANDARD_MENU_ITEMS
    assert read_brand["compliance_posture"] == POSTURE_EXEMPT


def test_a_brand_read_answers_a_regulator_an_analyst_and_a_foreign_publisher(api):
    """Three roles with no claim on the brand all read it successfully.

    PRD 2.1: "Ownership scoping applies to writes only. Every read endpoint in
    this specification is open to all five roles and is never ownership-scoped:
    a `StateRegulator` may read a brand it has never cited, and a
    `BrandComplianceOfficer` may read a competitor's menu."

    Design: Corner/rbac/shared_writes_accept_both_owners_and_reads_accept_every_role
    """
    jurisdiction, brand, first = _one_brand_and_one_unit(api)

    for headers in (
        make_regulator_headers(jurisdiction["id"]),
        ANALYST_SUBMITTER,
        make_publisher_headers(first["id"]),
        make_brand_officer_headers(brand["id"]),
        PLATFORM_ADMIN,
    ):
        read = validate_unpaginated(api.get_brand(brand["id"], headers))
        assert read["id"] == brand["id"], (
            f"the brand read must answer {headers['X-User-Role']}"
        )
        assert read["counted_unit_count"] == 1


def _two_brands_each_with_a_unit(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Two unrelated chains in one authority, so a foreign target exists."""
    set_clock(api)
    jurisdiction = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand_a = make_brand(api)
    brand_b = make_brand(
        api, legal_name="Silver Spoon Group LLC", doing_business_as="Silver Spoon"
    )
    unit_a = make_establishment(
        api,
        brand_id=brand_a["id"],
        jurisdiction_id=jurisdiction["id"],
        unit_label="ID-A-0001",
        unit_status=UNIT_OPERATING,
    )
    unit_b = make_establishment(
        api,
        brand_id=brand_b["id"],
        jurisdiction_id=jurisdiction["id"],
        unit_label="ID-B-0001",
        unit_status=UNIT_OPERATING,
    )
    return jurisdiction, brand_a, brand_b, unit_a, unit_b


def _grill_sandwich_for(brand_id: str) -> Dict[str, Any]:
    return menu_item_payload(
        brand_id=brand_id,
        name="Grill Sandwich",
        item_class=ITEM_CLASS_STANDARD,
        variable_type=VARIABLE_NONE,
        first_offered_on="2026-01-05",
    )


def test_an_empty_user_id_is_refused_before_the_role_is_looked_at(api):
    """A valid role cannot rescue a request that names no principal.

    PRD 2.1: "A request that omits `X-User-ID`, sends it with no value, or
    sends it as an empty string is rejected with `ERR_MISSING_AUTH` (HTTP 401)
    before anything else about the request is examined, including before
    `X-User-Role` is looked at." PRD 2.6 rung 1 repeats the placement:
    "`X-User-ID` present and non-empty, else `ERR_MISSING_AUTH`. Applies to
    every endpoint."

    Design: Corner/rbac/missing_x_user_id_unknown_role_wrong_role_and_foreign_scope_are_each_rejected
    """
    _jurisdiction, brand_a, _brand_b, _unit_a, _unit_b = _two_brands_each_with_a_unit(api)

    validate_error(
        api.create_menu_item(
            _grill_sandwich_for(brand_a["id"]),
            headers_with_empty_user_id(ROLE_BRAND_COMPLIANCE_OFFICER),
        ),
        ERR_MISSING_AUTH,
        401,
    )

    read = validate_unpaginated(api.get_brand(brand_a["id"], PLATFORM_ADMIN))
    assert read["standard_item_count"] == 0


def test_an_unknown_role_is_refused_as_an_invalid_role_and_never_as_unauthorized(api):
    """The role vocabulary is checked before the operation's permissions are.

    PRD 2.1: "A request whose `X-User-Role` is absent, empty, or not exactly
    one of the five recognised role names is rejected with `ERR_INVALID_ROLE`,
    also HTTP 401. Only after both headers are known good does the service ask
    whether that role is permitted on the requested operation; a recognised
    role attempting an operation it does not hold receives `ERR_UNAUTHORIZED`
    (HTTP 403)." PRD 2.6 rung 2 states the consequence: "Because this rung
    precedes endpoint authorization, an unknown role never produces
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/missing_x_user_id_unknown_role_wrong_role_and_foreign_scope_are_each_rejected
    """
    _jurisdiction, brand_a, _brand_b, _unit_a, _unit_b = _two_brands_each_with_a_unit(api)
    probe = headers_with_unknown_role(brand_a["id"])
    assert probe["X-User-Role"] == UNKNOWN_ROLE

    validate_error(
        api.create_menu_item(_grill_sandwich_for(brand_a["id"]), probe),
        ERR_INVALID_ROLE,
        401,
    )

    read = validate_unpaginated(api.get_brand(brand_a["id"], PLATFORM_ADMIN))
    assert read["standard_item_count"] == 0


def test_role_authorization_is_decided_before_ownership(api):
    """A publisher aiming at a foreign brand is unauthorised, not out of scope.

    PRD 2.1: "Because role authorization is decided before ownership, a caller
    holding the wrong role for an operation *and* pointing at somebody else's
    resource receives `ERR_UNAUTHORIZED`, not `ERR_FORBIDDEN_SCOPE`." PRD 2.6
    orders the two rungs to match: rung 3 is "The role is authorized for the
    requested operation, else `ERR_UNAUTHORIZED`. Applies to every endpoint."

    Design: Corner/rbac/missing_x_user_id_unknown_role_wrong_role_and_foreign_scope_are_each_rejected
    """
    _jurisdiction, _brand_a, brand_b, unit_a, _unit_b = _two_brands_each_with_a_unit(api)

    validate_error(
        api.create_menu_item(
            _grill_sandwich_for(brand_b["id"]),
            make_publisher_headers(unit_a["id"]),
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    read = validate_unpaginated(api.get_brand(brand_b["id"], PLATFORM_ADMIN))
    assert read["standard_item_count"] == 0


def test_the_right_role_acting_for_the_wrong_owner_is_refused_by_scope(api):
    """Two entity-backed roles reach the ownership rung and fail it.

    PRD 2.1: "A write by one of the three entity-backed roles against a
    resource that belongs to a different entity than the one `X-User-ID` names
    is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)." PRD 2.6 rung 4 names
    the comparison: "For the entity-backed roles, `X-User-ID` equals the `id`
    of the entity the write targets — the `Brand` for a
    `BrandComplianceOfficer`, the `Establishment` for a `MenuboardPublisher`,
    the `Jurisdiction` for a `StateRegulator` — else `ERR_FORBIDDEN_SCOPE`.
    Applies to every write; reads are never ownership-scoped."

    Design: Corner/rbac/missing_x_user_id_unknown_role_wrong_role_and_foreign_scope_are_each_rejected
    """
    _jurisdiction, brand_a, brand_b, unit_a, unit_b = _two_brands_each_with_a_unit(api)

    validate_error(
        api.create_menu_item(
            _grill_sandwich_for(brand_b["id"]),
            make_brand_officer_headers(brand_a["id"]),
        ),
        ERR_FORBIDDEN_SCOPE,
        403,
    )
    validate_error(
        api.create_menu_board(
            menu_board_payload(
                establishment_id=unit_b["id"],
                board_type=BOARD_PRIMARY_MENU_BOARD,
                succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT,
            ),
            make_publisher_headers(unit_a["id"]),
        ),
        ERR_FORBIDDEN_SCOPE,
        403,
    )

    competitor = validate_unpaginated(
        api.get_brand(brand_b["id"], make_brand_officer_headers(brand_a["id"]))
    )
    assert competitor["id"] == brand_b["id"]
    assert competitor["standard_item_count"] == 0
    assert (
        validate_unpaginated(api.get_brand(brand_a["id"], PLATFORM_ADMIN))[
            "standard_item_count"
        ]
        == 0
    )
    boards, board_meta = validate_paginated(
        api.list_menu_boards(
            PLATFORM_ADMIN, params={"establishment_id": unit_b["id"], "limit": 10}
        )
    )
    assert boards == []
    assert board_meta["total_count"] == 0


def _analysis_submitted_by_the_first_analyst(api: ApiClient) -> Tuple[Env, str, str, str]:
    """One item, one DRAFT recipe with a base component, submitted by analyst-1."""
    env = seed_registry(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED,
        unit_count=1, unit_label="ID-0001",
    )
    item = validate_unpaginated(
        api.create_menu_item(_grill_sandwich_for(env.brand_id), env.officer), 201
    )
    recipe = open_recipe_version(env, item["id"])
    add_components(env, recipe["id"], [_sandwich_as_served()])
    analysis = submit_recipe(env, recipe["id"], method=METHOD_DATABASE)
    return env, item["id"], recipe["id"], analysis["id"]


def test_the_submitting_analyst_cannot_certify_its_own_analysis(api):
    """A self-`CERTIFY` is turned away and the analysis stays pending.

    PRD 3.4: "the analyst whose `X-User-ID` was recorded in
    `submitted_by_user_id` may not certify that analysis and is turned away
    with `ERR_SAME_USER_CERTIFICATION` (HTTP 403), while a `REJECT` from that
    same analyst is entirely permitted." PRD 2.6 rung 18: "On a certification
    decision the acting analyst's `X-User-ID` differs from the analysis's
    `submitted_by_user_id`, else `ERR_SAME_USER_CERTIFICATION`. Applies to the
    analysis decision."

    Design: Corner/rbac/the_submitting_analyst_cannot_certify_but_may_reject
    """
    env, item_id, recipe_id, analysis_id = _analysis_submitted_by_the_first_analyst(api)
    assert env.read_analysis(analysis_id)["submitted_by_user_id"] == (
        ANALYST_SUBMITTER_USER_ID
    )

    validate_error(
        api.decide_analysis(
            analysis_id,
            analysis_decision_payload(
                decision=DECISION_CERTIFY,
                decision_note="Self-certifying my own submission",
            ),
            ANALYST_SUBMITTER,
        ),
        ERR_SAME_USER_CERTIFICATION,
        403,
    )

    analysis = env.read_analysis(analysis_id)
    assert analysis["status"] == ANALYSIS_SUBMITTED
    assert analysis["decided_by_user_id"] is None
    assert env.read_recipe(recipe_id)["status"] == RECIPE_ANALYSIS_PENDING
    assert env.read_item(item_id)["declared_calorie_max"] is None


def test_the_submitting_analyst_may_reject_and_a_second_analyst_certifies(api):
    """The same analyst rejects its own work, then a colleague certifies the retry.

    PRD 3.4: "A rejection writes `decided_by_user_id` and `decision_note` on the
    analysis, moves the analysis to `REJECTED`, and then branches on how many
    rejections the recipe has already absorbed. While `revision_round` is below
    3, the recipe returns from `ANALYSIS_PENDING` to `DRAFT` with
    `revision_round` incremented by 1 and becomes editable again so further
    components can be added". Segregation binds only the other decision:
    "the analyst whose `X-User-ID` was recorded in `submitted_by_user_id` may
    not certify that analysis and is turned away with
    `ERR_SAME_USER_CERTIFICATION` (HTTP 403), while a `REJECT` from that same
    analyst is entirely permitted."

    Design: Corner/rbac/the_submitting_analyst_cannot_certify_but_may_reject
    """
    env, item_id, recipe_id, analysis_id = _analysis_submitted_by_the_first_analyst(api)

    rejected = validate_unpaginated(
        api.decide_analysis(
            analysis_id,
            analysis_decision_payload(
                decision=DECISION_REJECT,
                decision_note="My own sampling was unsound",
            ),
            ANALYST_SUBMITTER,
        )
    )
    assert rejected["status"] == ANALYSIS_REJECTED
    assert rejected["decided_by_user_id"] == ANALYST_SUBMITTER_USER_ID

    recipe = env.read_recipe(recipe_id)
    assert recipe["status"] == RECIPE_DRAFT
    assert recipe["revision_round"] == 1

    retry = validate_unpaginated(
        api.submit_for_analysis(
            recipe_id,
            submit_for_analysis_payload(method=METHOD_LAB_ANALYSIS),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    certified = validate_unpaginated(
        api.decide_analysis(
            retry["id"],
            analysis_decision_payload(
                decision=DECISION_CERTIFY,
                decision_note="Independent laboratory confirmation",
            ),
            ANALYST_CERTIFIER,
        )
    )
    assert certified["status"] == ANALYSIS_CERTIFIED
    assert certified["decided_by_user_id"] == ANALYST_CERTIFIER_USER_ID
    assert env.read_recipe(recipe_id)["status"] == RECIPE_APPROVED
    assert env.read_item(item_id)["labeling_status"] == LABELING_DECLARED
