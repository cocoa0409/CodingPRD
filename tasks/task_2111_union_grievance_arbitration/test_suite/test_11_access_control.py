"""Authentication, role separation, case scoping and segregation of duties."""

from test_helpers import (
    ANALYST_USER_ID,
    DIRECTOR_USER_ID,
    ApiErrorId,
    add_employee,
    add_witness_employee,
    build_user_headers,
    draft_offer,
    file_grievance,
    grievance_version,
    hold_open_step,
    make_analyst_headers,
    make_director_headers,
    make_grievant_headers,
    make_steward_headers,
    read_grievance,
    respond_step,
    setup_authorized_offer,
    setup_base,
    setup_grievance,
    step_response_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_missing_identity_and_undeclared_roles_are_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    operator, and `X-User-Role`, naming the role that operator is acting in. If either header
    is missing or empty, or if `X-User-Role` names anything other than one of the six roles
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_and_unknown_roles_return_unauthenticated
    """
    ctx = setup_grievance()

    no_identity = api.get_grievance(
        ctx["grievance"]["id"],
        {"X-User-Role": "UnionSteward", "Content-Type": "application/json"},
    )
    validate_error(no_identity, ApiErrorId.ERR_UNAUTHENTICATED.value)

    unknown_role = api.get_grievance(
        ctx["grievance"]["id"], build_user_headers("pc-01", "PayrollClerk")
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_authentication_is_checked_before_the_resource_exists(api):
    """PRD §2.10: "Both headers are present and `X-User-Role` names one of the six declared
    roles — otherwise `ERR_UNAUTHENTICATED`."
    PRD §2.10: "Every resource named by a path parameter exists, resolved left to right —
    otherwise the matching not-found error from §2.9."

    Design: Corner/rbac/missing_headers_and_unknown_roles_return_unauthenticated
    """
    response = api.get_grievance(UNKNOWN_UUID, build_user_headers("pc-01", "PayrollClerk"))
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_peer_roles_cannot_reach_each_others_exclusive_operations(api, analyst_headers):
    """PRD §2.1: "A `LaborRelationsAnalyst` is the case handler inside the labor relations
    office."
    PRD §2.1: "If the headers are well formed but the named role is not among the roles
    authorized for the requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."

    Design: Corner/rbac/analyst_and_administrator_cannot_reach_other_roles_exclusive_operations
    """
    ctx = setup_grievance()
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")
    version = grievance_version(ctx["grievance"]["id"])

    analyst_authorizing = api.authorize_settlement_offer(
        offer["id"], {"expected_grievance_version": version}, analyst_headers
    )
    validate_error(analyst_authorizing, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    steward_answering = api.respond_grievance_step(
        step["id"],
        step_response_payload("DENIED", response_summary="Union answering for the employer"),
        ctx["steward_headers"],
    )
    validate_error(steward_answering, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    rows, _ = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    assert rows[0]["status"] == "HELD"


def test_the_director_may_authorize_what_the_analyst_may_not(api, director_headers, analyst_headers):
    """PRD §2.1: "Authorizing settlement offers is this role's only write power, which is
    deliberate: it keeps approval strictly separated from case handling."
    PRD §3.4: "**Authorization** is where the employer's approval hierarchy bites, and only a
    `LaborRelationsDirector` or a `ChiefNegotiator` may attempt it."

    Design: Corner/rbac/analyst_and_administrator_cannot_reach_other_roles_exclusive_operations
    """
    ctx = setup_grievance()
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    version = grievance_version(ctx["grievance"]["id"])

    validate_error(
        api.authorize_settlement_offer(
            offer["id"], {"expected_grievance_version": version}, analyst_headers
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    authorized = validate_success(
        api.authorize_settlement_offer(
            offer["id"], {"expected_grievance_version": version}, director_headers
        ),
        200,
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_by_user_id"] == DIRECTOR_USER_ID
    assert authorized["prepared_by_user_id"] == ANALYST_USER_ID


def test_a_grievant_reads_their_own_case_only(api):
    """PRD §2.1: "A `Grievant` has no write powers at all and may read only their own case:
    reading a single grievance, and listing that grievance's step records, are permitted only
    when the grievance's `grievant_id` equals the caller's `X-User-ID`. Any other grievance
    returns `ERR_NOT_CASE_PARTICIPANT` (HTTP 403)."

    Design: Corner/rbac/grievant_cannot_read_another_members_grievance
    """
    ctx = setup_base()
    add_witness_employee(ctx)
    own = file_grievance(ctx, statement="Suspension of Ortiz")
    other = file_grievance(
        ctx, grievant_id=ctx["witness"]["id"], statement="Suspension of Brooks"
    )
    grievant_headers = make_grievant_headers(ctx["grievant"]["id"])

    own_read = validate_success(api.get_grievance(own["id"], grievant_headers), 200)
    assert own_read["case_number"] == "GR-L2100-0001"

    other_read = api.get_grievance(other["id"], grievant_headers)
    validate_error(other_read, ApiErrorId.ERR_NOT_CASE_PARTICIPANT.value)

    _, meta = validate_paginated(api.list_grievance_steps(own["id"], grievant_headers))
    assert meta["total_count"] == 0


def test_the_grievance_listing_is_closed_to_the_grievant_role(api):
    """PRD §2.1: "If the headers are well formed but the named role is not among the roles
    authorized for the requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."
    PRD §4: "List grievances with filters covering every foreign key on the entity, including
    the self-referential consolidated_into_id. Ordered by created_at ASC, then case_number
    ASC."

    Design: Corner/rbac/grievant_cannot_read_another_members_grievance
    """
    ctx = setup_grievance()
    grievant_headers = make_grievant_headers(ctx["grievant"]["id"])

    response = api.list_grievances(
        grievant_headers, params={"bargaining_unit_id": ctx["unit"]["id"]}
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)


def test_only_the_filing_steward_may_appeal_or_withdraw(api):
    """PRD §2.1: "In particular, the steward who files a grievance is stamped onto it, and
    only that steward may take union-side action on it thereafter — an attempt by a different
    steward is rejected with `ERR_NOT_FILING_STEWARD` (HTTP 403)."
    PRD §2.10: "A `UnionSteward` taking a union-side action is the steward who filed the
    grievance — otherwise `ERR_NOT_FILING_STEWARD`. This guards five acts: appealing a
    grievance, withdrawing or consolidating a grievance, demanding arbitration, taking a panel
    strike as the `UnionSteward`, and responding to a settlement offer as the `UnionSteward`."

    Design: Corner/rbac/non_filing_steward_cannot_appeal_or_withdraw_the_case
    """
    ctx = setup_base()
    second_steward = add_employee(
        ctx, "second_steward",
        full_name="Paula Reed", employee_number="STW-2",
        hire_date="2018-01-08T00:00:00Z", seniority_date="2018-01-08T00:00:00Z",
        hourly_rate_cents=3_200, classification="CLERICAL",
        supervisor_id=ctx["supervisor"]["id"],
    )
    grievance = file_grievance(ctx)
    intruder = make_steward_headers(second_steward["id"])

    appeal = api.appeal_grievance(
        grievance["id"], {"appeal_statement": "Wrong steward appealing"}, intruder
    )
    validate_error(appeal, ApiErrorId.ERR_NOT_FILING_STEWARD.value)

    withdraw = api.withdraw_grievance(
        grievance["id"], {"reason": "Wrong steward withdrawing"}, intruder
    )
    validate_error(withdraw, ApiErrorId.ERR_NOT_FILING_STEWARD.value)

    after = read_grievance(grievance["id"])
    assert after["filed_by_steward_employee_id"] == ctx["steward"]["id"]
    assert after["status"] == "FILED"
    assert after["current_step"] == 1


def test_the_operator_who_answered_the_step_may_not_authorize_the_settlement(api, analyst_headers):
    """PRD §2.11: "First, the operator who recorded an employer answer at any step of a
    grievance — captured as `responded_by_user_id` on that `GrievanceStep` — may never
    authorize a settlement offer on that same grievance, whatever role they hold; the attempt
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_bars_the_step_responder_from_authorizing
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")
    answered = respond_step(
        step["id"], "DENIED",
        headers=make_analyst_headers("u-77"),
        response_summary="Answered by u-77",
    )
    assert answered["responded_by_user_id"] == "u-77"

    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    version = grievance_version(ctx["grievance"]["id"])

    response = api.authorize_settlement_offer(
        offer["id"], {"expected_grievance_version": version}, make_director_headers("u-77")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    unchanged = validate_success(api.get_settlement_offer(offer["id"], analyst_headers), 200)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["authorized_by_user_id"] is None


def test_a_different_director_identity_may_authorize_the_same_offer(api, director_headers):
    """PRD §2.11: "The office's compliance posture rests on one principle: the person who
    commits the employer to a position is never the person who reviewed it."
    PRD §3.4: "An authorization that clears all three bars moves the offer from `DRAFT` to
    `AUTHORIZED`, stamps `authorized_by_user_id` with the acting `X-User-ID` and
    `authorized_at` with the clock's current instant, and sets `expires_at` to ten days after
    that instant."

    Design: Corner/rbac/segregation_of_duties_bars_the_step_responder_from_authorizing
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")
    respond_step(
        step["id"], "DENIED",
        headers=make_analyst_headers("u-77"),
        response_summary="Answered by u-77",
    )
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    version = grievance_version(ctx["grievance"]["id"])

    validate_error(
        api.authorize_settlement_offer(
            offer["id"], {"expected_grievance_version": version}, make_director_headers("u-77")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    authorized = validate_success(
        api.authorize_settlement_offer(
            offer["id"], {"expected_grievance_version": version}, director_headers
        ),
        200,
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_by_user_id"] == DIRECTOR_USER_ID


def test_party_alignment_is_enforced_when_an_offer_is_drafted(api, analyst_headers):
    """PRD §3.4: "A `LaborRelationsAnalyst` drafts the employer's positions and a
    `UnionSteward` drafts the union's; the drafting payload declares which side it speaks for
    through `offering_party`, either `UNION` or `EMPLOYER`, and the acting role's party must
    equal that declaration or the draft is rejected with `ERR_PARTY_ROLE_MISMATCH`."

    Design: Corner/rbac/party_alignment_is_enforced_on_offer_creation_and_response
    """
    ctx = setup_grievance()

    response = api.create_settlement_offer(
        ctx["grievance"]["id"],
        {"offering_party": "EMPLOYER", "monetary_cents": 30_000},
        ctx["steward_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PARTY_ROLE_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_settlement_offers(
            analyst_headers, params={"grievance_id": ctx["grievance"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_only_the_receiving_party_may_respond_to_an_authorized_offer(api, director_headers, analyst_headers):
    """PRD §3.4: "**Responding** to an authorized offer belongs to the other side of the
    table: a `UnionSteward` responds to employer offers and a `LaborRelationsDirector` responds
    to union offers, and in both cases the acting role's party must be the opposite of the
    offer's `offering_party`, failing with `ERR_PARTY_ROLE_MISMATCH`."
    PRD §3.4: "`REJECT` moves the offer to `REJECTED` and changes nothing else — the grievance
    is untouched and the negotiation may continue with a fresh draft."

    Design: Corner/rbac/party_alignment_is_enforced_on_offer_creation_and_response
    """
    ctx = setup_authorized_offer(monetary_cents=40_000)

    same_side = api.respond_settlement_offer(
        ctx["offer"]["id"], {"decision": "ACCEPT"}, director_headers
    )
    validate_error(same_side, ApiErrorId.ERR_PARTY_ROLE_MISMATCH.value)

    rejected = validate_success(
        api.respond_settlement_offer(
            ctx["offer"]["id"],
            {"decision": "REJECT", "response_note": "Too low"},
            ctx["steward_headers"],
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "FILED"
    assert grievance["settled_amount_cents"] == 0

    _, meta = validate_paginated(
        api.list_settlement_offers(
            analyst_headers, params={"grievance_id": ctx["grievance"]["id"]}
        )
    )
    assert meta["total_count"] == 1
