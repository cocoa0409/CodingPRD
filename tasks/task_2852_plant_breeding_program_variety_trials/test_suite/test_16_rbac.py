"""
Access control with no seniority to fall back on: six peer roles each owning a
disjoint slice of the write surface, a seventh whose identifier is a scope key
rather than an identity, and one guard that reads a stored header value.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    ANALYST_HEADERS,
    BAD_ROLE_HEADERS,
    DIRECTOR_HEADERS,
    NO_ROLE_HEADERS,
    NO_USER_HEADERS,
    PLANNER_HEADERS,
    REGULATORY_APPROVER_HEADERS,
    REGULATORY_APPROVER_USER_ID,
    REGULATORY_DRAFTER_USER_ID,
    REGULATORY_HEADERS,
    SCIENTIST_HEADERS,
    AgreementStatus,
    ApiErrorId,
    DecisionType,
    StewardshipStatus,
    factories,
    fixtures,
    make_program_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_no_peer_role_can_borrow_another_roles_exclusive_operation(api):
    """
    The shared reads answer whoever asks, but every exclusive write refuses every
    role but its owner — including `ProgramLead`, which owns no exclusive operation
    of its own — and a malformed identity is a 401 before the role rung is reached.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of those
    seven strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
    If the headers are well formed but the acting role is not among the roles
    authorised for the endpoint in §4, the request is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.1: "The seven roles are peers rather than a hierarchy: each owns a
    disjoint slice of the pipeline."
    PRD 2.7: "**Role authorisation.** The acting role appears in the endpoint's
    authorised list in §4 — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to
    every endpoint."

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id, designation="SX-1001")
    site = fixtures.create_site(api, site_code="RB1")
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )

    for headers in (PLANNER_HEADERS, REGULATORY_HEADERS):
        rows, _meta = validate_paginated(
            api.list_lines(headers, {"program_id": program_id, "limit": 20})
        )
        assert [row["id"] for row in rows] == [line["id"]]
    validate_success(api.get_line(line["id"], ANALYST_HEADERS))
    validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))

    validate_error(
        api.create_program(factories.program_payload(), AGRONOMIST_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_site(factories.site_payload(site_code="RB2"), SCIENTIST_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(line["id"], site["id"], plot_count=9),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_analysis(series["id"], factories.analysis_payload(1), PLANNER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_lot(
            factories.lot_payload(
                line["id"], "US_CORNBELT", [factories.allocation("US_CORNBELT", 100)]
            ),
            REGULATORY_HEADERS,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_agreement(line["id"], factories.agreement_payload(), PLANNER_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    # ProgramLead holds no exclusive operation and cannot borrow the director's.
    validate_error(
        api.create_decision(
            factories.decision_payload(
                line["id"], series["id"], line["version"],
                decision=DecisionType.HOLD, granted_plots=0,
            ),
            make_program_lead_headers(program_id),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    for headers in (NO_ROLE_HEADERS, NO_USER_HEADERS, BAD_ROLE_HEADERS):
        validate_error(
            api.create_program(factories.program_payload(), headers),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )

    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["active_line_count"] == 1
    assert validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))[
        "entry_count"
    ] == 0


def test_a_program_leads_user_id_is_a_scope_key_on_writes_and_on_reads(api):
    """
    The same role, endpoint and body succeed for the programme whose id equals
    `X-User-ID` and are refused for its sibling, and the scope is followed through
    the body's foreign keys as well as through the path.

    PRD 2.1: "When `X-User-Role` is `ProgramLead`, `X-User-ID` is the `id` of the
    acting `BreedingProgram`; ownership checks compare the owning programme of
    every resource named in the path and in the body — the `program_id` of an
    objective, line, trial series or crossing block, or the programme behind the
    line that stands behind an agreement, a seed increase lot, a nursery planting,
    a trial entry or a backcross project — against `X-User-ID`, and any mismatch is
    rejected with `ERR_PROGRAM_SCOPE_VIOLATION` (HTTP 403)."
    PRD 2.7: "**Programme scope.** When the acting role is `ProgramLead`,
    `X-User-ID` must equal the owning `BreedingProgram` identifier of every
    resource named in the path and in the body — otherwise
    `ERR_PROGRAM_SCOPE_VIOLATION` (403). Applies to every endpoint whose authorised
    roles include `ProgramLead`."

    Design: Corner/rbac/program_lead_is_scoped_to_the_program_named_by_its_user_id
    """
    p1, obj1 = fixtures.program_with_objective(api)
    p2, obj2 = fixtures.program_with_objective(
        api,
        program_overrides={
            "name": "Soy Southern",
            "market_zone": "SOUTHERN",
            "total_plot_budget": 3000,
            "total_budget_usd": 900000.00,
        },
        objective_overrides={"market_segment": "MG5_SOUTH"},
    )
    lead_of_p1 = make_program_lead_headers(p1)
    lead_of_p2 = make_program_lead_headers(p2)

    own = validate_success(
        api.create_line(
            factories.line_payload(p1, obj1, designation="SX-1001"), lead_of_p1
        ),
        201,
    )
    assert validate_success(api.get_program(p1, DIRECTOR_HEADERS))[
        "active_line_count"
    ] == 1

    validate_error(
        api.create_line(
            factories.line_payload(
                p2, obj2, designation="SY-2001", seed_inventory_g=200000
            ),
            lead_of_p1,
        ),
        ApiErrorId.PROGRAM_SCOPE_VIOLATION,
        403,
    )
    assert validate_success(api.get_program(p2, DIRECTOR_HEADERS))[
        "active_line_count"
    ] == 0

    validate_error(
        api.get_line(own["id"], lead_of_p2),
        ApiErrorId.PROGRAM_SCOPE_VIOLATION,
        403,
    )
    readable = validate_success(api.get_line(own["id"], lead_of_p1))
    assert readable["id"] == own["id"]
    assert readable["program_id"] == p1


def test_the_suspend_guard_reads_the_stored_approver_and_then_yields_to_the_state(api):
    """
    The refusal depends on who approved rather than on any role: the approver is
    blocked while a different holder of the very same role succeeds, and once the
    agreement is terminal the state rung outranks the duties rung for a third
    caller from an entirely different role.

    PRD 2.7: "**Segregation of duties.** `X-User-ID` differs from the agreement's
    `approved_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to
    agreement suspension."
    PRD 2.7: "**Agreement state.** The stewardship agreement is `DRAFT` or
    `CHANGES_REQUESTED` for submission, `SUBMITTED` for review, and `APPROVED` for
    suspension — otherwise `ERR_AGREEMENT_INVALID_STATE` (409)."
    PRD 3.9: "A successful suspension cascades in a pinned order. The agreement
    moves `APPROVED → SUSPENDED` and stores `suspension_reason`. Because of that,
    the line's `stewardship_status` becomes `SUSPENDED` and its `version`
    increments."
    PRD 3.9: "`SUSPENDED` is where an agreement's lifecycle ends."

    Design: Corner/rbac/suspending_an_agreement_requires_a_second_pair_of_hands
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id, designation="SX-1001")
    agreement = fixtures.approved_agreement(api, line["id"], markets=["US_CORNBELT"])
    assert agreement["approved_by_user_id"] == REGULATORY_APPROVER_USER_ID
    assert agreement["submitted_by_user_id"] == REGULATORY_DRAFTER_USER_ID

    validate_error(
        api.suspend_agreement(
            agreement["id"],
            factories.suspend_payload("self-suspension attempt by the approver"),
            REGULATORY_APPROVER_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert validate_success(api.get_agreement(agreement["id"], REGULATORY_HEADERS))[
        "status"
    ] == AgreementStatus.APPROVED

    suspended = validate_success(
        api.suspend_agreement(
            agreement["id"],
            factories.suspend_payload("dossier withdrawn by the regulator"),
            REGULATORY_HEADERS,
        )
    )
    assert suspended["status"] == AgreementStatus.SUSPENDED
    assert suspended["suspension_reason"] == "dossier withdrawn by the regulator"
    assert validate_success(api.get_line(line["id"], DIRECTOR_HEADERS))[
        "stewardship_status"
    ] == StewardshipStatus.SUSPENDED

    # pd-1 is not the approver, so only the terminal state can refuse this one.
    validate_error(
        api.suspend_agreement(
            agreement["id"],
            factories.suspend_payload("second attempt"),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.AGREEMENT_INVALID_STATE,
        409,
    )
    assert validate_success(api.get_program(program_id, DIRECTOR_HEADERS))[
        "pre_commercial_units_bags"
    ] == 0
