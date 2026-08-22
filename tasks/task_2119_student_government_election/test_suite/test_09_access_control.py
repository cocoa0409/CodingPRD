"""Who may act: the context headers, the endpoint role list and the ownership
rung that sits below both."""

from test_helpers import (
    ApiErrorId,
    NONEXISTENT_ID,
    TEST_USERS,
    adjudicate_signature_payload,
    create_election_payload,
    make_candidate_headers,
    read_candidacy,
    read_signature,
    setup_petition_under_review,
    setup_petitioning_election,
    validate_error,
    validate_paginated,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_a_request_without_the_context_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in which that
    user is acting. Both headers must be present and non-empty; a request missing either
    one, or supplying an empty value, is rejected with `ERR_UNAUTHENTICATED` before any
    other consideration — before the resource is looked up, before the payload is parsed,
    before any business rule runs."

    Design: Corner/rbac/omitting_x_user_headers_returns_unauthenticated
    """
    response = api.list_elections({})

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["response_type"] == "error"


def test_the_registrar_may_not_declare_an_election(api):
    """PRD §2.1: "Each endpoint in Section 4 lists the roles permitted to invoke it; a
    request whose `X-User-Role` is not among them is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: "| POST   | `/elections`                                              | Open a new election cycle in status DRAFT                                                                                                                                                                                                        | ElectionCommissioner   |"

    Design: Corner/rbac/registrar_cannot_create_election_returns_unauthorized
    """
    validate_error(
        api.create_election(create_election_payload(), REGISTRAR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    _, meta = validate_paginated(api.list_elections(COMMISSIONER))
    assert meta["total_count"] == 0, "the refused declaration mints no election"


def test_a_candidate_may_not_adjudicate_a_signature_on_their_own_petition(api):
    """PRD §2.1: "Each endpoint in Section 4 lists the roles permitted to invoke it; a
    request whose `X-User-Role` is not among them is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.3: "Adjudication is the commissioner's act and is available while the election
    is `PETITIONING`."

    Design: Corner/rbac/candidate_cannot_adjudicate_a_petition_signature
    """
    scenario = setup_petition_under_review(required_signature_count=1, signer_count=1)
    candidacy = scenario["candidacy"]
    signature = scenario["signatures"][0]

    validate_error(
        api.adjudicate_signature(
            signature["id"],
            adjudicate_signature_payload("VERIFIED"),
            make_candidate_headers(candidacy["student_id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    assert read_signature(signature["id"])["status"] == "SUBMITTED"
    assert read_candidacy(candidacy["id"])["petition_signature_valid_count"] == 0


def test_a_candidate_may_not_submit_another_students_petition(api):
    """PRD §2.1: "An entity-backed role acting on a row it does not own is rejected with
    `ERR_NOT_RESOURCE_OWNER`. That ownership check runs on candidacy creation, petition
    submission, candidacy withdrawal, slate-membership changes, training records,
    campaign-expense reporting, petition-signature creation, appeal filing, and referendum
    submission."
    PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting
    `Student`; ownership checks on any resource that references a `Student` compare the
    resource's foreign-key field to `X-User-ID` — specifically, a candidacy's `student_id`
    for any act on that candidacy, the `student_id` of the candidacy named by a campaign
    expense's `candidacy_id`, and the `student_id` of the candidacy named by an appeal's
    `candidacy_id`."

    Design: Corner/rbac/candidate_cannot_submit_another_students_petition
    """
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"]}],
        candidates=[{"office": 0}, {"office": 0}],
        approve=False,
    )
    target = scenario["candidacies"][0]
    other_student = scenario["candidate_students"][1]

    response = api.submit_petition(
        target["id"], make_candidate_headers(other_student["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
        "the acting role is permitted on this endpoint; only ownership fails"
    )
    assert read_candidacy(target["id"])["status"] == "DRAFT"


def test_authorization_is_decided_before_the_resource_is_looked_up(api):
    """PRD §2.5: "1. Both context headers present and non-empty — `ERR_UNAUTHENTICATED`
    (401), on every endpoint."
    PRD §2.5: "2. The acting role is listed for the endpoint — `ERR_UNAUTHORIZED` (403), on
    every endpoint."
    PRD §2.5: "3. Every path-parameter resource exists, left to right — the twelve 404
    errors above, on every endpoint with a path parameter."

    Design: Corner/validations/unauthorized_role_beats_unknown_resource_id
    """
    response = api.certify(NONEXISTENT_ID, REGISTRAR)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_ELECTION_NOT_FOUND.value
    ), "authorization is evaluated before existence"
