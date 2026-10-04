"""Institution onboarding, response envelope, agreements, and the clock."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    create_institution, create_institution_with_registrars,
    create_institution_payload, create_agreement_payload,
    create_period_payload, add_agreement, advance_clock,
    assert_institution,
)

OPS = TEST_USERS["ops_headers"]


def test_institution_create_embeds_users_and_defaults(api):
    """PRD section 3.1: "Creation provisions one InstitutionUser per array
    member, each starting `ACTIVE`, each email unique within the institution;
    the create response embeds the provisioned `users` array in the same
    order the members were supplied, and that embedded array appears on the
    create response only."
    PRD section 3.1: "The institution itself begins `ACTIVE`, with
    `suspension_reason` of `NONE` and `compliance_standing` of `COMPLIANT`."
    PRD section 2.5: "`version` (integer): starts at 1 at creation and
    increments by one on every mutation of the resource".

    Design: Corner/entities/institution_create_embeds_users_and_defaults
    """
    resp = api_client.create_institution(create_institution_payload(), OPS)
    data = validate_success(resp, 201)
    assert_institution(data)
    assert data["users"][0]["email"] == "sub@su.edu"
    assert data["users"][0]["role"] == "SUBMITTER"
    assert data["users"][0]["status"] == "ACTIVE"
    assert data["users"][1]["email"] == "cert@su.edu"
    assert data["users"][1]["role"] == "CERTIFIER"
    assert data["status"] == "ACTIVE"
    assert data["suspension_reason"] == "NONE"
    assert data["compliance_standing"] == "COMPLIANT"
    assert data["version"] == 1

    got = validate_success(api_client.get_institution(data["id"], OPS), 200)
    assert got["status"] == "ACTIVE"
    assert got["suspension_reason"] == "NONE"
    assert got["compliance_standing"] == "COMPLIANT"


def test_response_envelope_shapes(api):
    """PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string
    that identifies the specific error."
    PRD section 2.8: "Each kind of unresolved reference reports its own error
    — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`".

    Design: Corner/endpoints/response_envelope_shapes
    """
    resp = api_client.create_institution(create_institution_payload(), OPS)
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert len(body["meta"]["api_request_id"]) > 0

    err_resp = api_client.get_institution(NON_EXISTENT_UUID, OPS)
    validate_error(err_resp, ApiErrorId.ERR_INSTITUTION_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_INSTITUTION_NOT_FOUND"


def test_missing_required_field_rejected(api):
    """PRD section 2.8: "Payload well-formedness — required fields present,
    types correct, enum members valid, dates parseable — is enforced on every
    creation and action endpoint; a malformed payload is rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/missing_required_field_rejected
    """
    create_institution()
    bad = {"name": "No OPE University",
           "users": [{"email": "sub@x.edu", "role": "SUBMITTER"}]}
    resp = api_client.create_institution(bad, OPS)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_invalid_enum_member_rejected(api):
    """PRD section 2.8: "Payload well-formedness — required fields present,
    types correct, enum members valid, dates parseable — is enforced on every
    creation and action endpoint; a malformed payload is rejected with
    `ERR_VALIDATION` (HTTP 400)."
    PRD section 3.7: "An operator creates a Requester account with an
    `org_name`, a `requester_kind` of `EMPLOYER` or `BACKGROUND_SCREENER`".

    Design: Corner/validations/invalid_enum_member_rejected
    """
    create_institution()
    resp = api_client.create_requester(
        {"org_name": "Loan Corp", "requester_kind": "LENDER"}, OPS,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_clock_must_move_strictly_forward(api):
    """PRD section 2.4: "A `ClearinghouseOps`-only capability advances the
    clock to a supplied `to_iso8601` instant; the target must be strictly
    later than the current logical time, and a non-forward move is rejected
    with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/clock_must_move_strictly_forward
    """
    create_institution()
    advance_clock("2026-10-01T00:00:00Z")
    backward = api_client.set_clock("2026-09-15T00:00:00Z", OPS)
    validate_error(backward, ApiErrorId.ERR_VALIDATION)
    equal = api_client.set_clock("2026-10-01T00:00:00Z", OPS)
    validate_error(equal, ApiErrorId.ERR_VALIDATION)


def test_scheduled_default_clock_is_pinned(api):
    """PRD section 2.4: "Before any clock operation has been called, the
    logical clock reads exactly 2026-09-01T00:00:00Z."
    PRD section 3.1: "An agreement's initial status is computed from the
    current logical time: `ACTIVE` when now falls inside the window (on or
    after `effective_from` and before `effective_to`), and `SCHEDULED` when
    now is earlier than `effective_from`".
    PRD section 3.2: "A period's lifecycle is clock-driven: `SCHEDULED`
    before submissions open, `OPEN` once now reaches `submission_opens_at`".

    Design: Corner/complexity_layers/scheduled_default_clock_is_pinned
    """
    ctx = create_institution_with_registrars()
    ag = add_agreement(ctx["inst_id"],
                       effective_from="2026-09-01", effective_to="2027-06-30")
    assert ag["status"] == "ACTIVE", (
        "effective_from 2026-09-01 <= default now 2026-09-01T00:00:00Z "
        "< effective_to must create the agreement ACTIVE"
    )
    period_resp = api_client.create_reporting_period(
        ctx["inst_id"],
        create_period_payload(
            term_label="Early Fall 2026", term_start="2026-08-01",
            term_end="2026-12-15", submission_opens_at="2026-09-01",
            submission_due_at="2026-12-20",
        ),
        OPS,
    )
    period = validate_success(period_resp, 201)
    assert period["status"] == "OPEN", (
        "default now reaches submission_opens_at 2026-09-01, so the period "
        "is created OPEN"
    )


def test_agreement_overlap_rejected_one_day_early(api):
    """PRD section 3.1: "The window must not overlap any `SCHEDULED` or
    `ACTIVE` agreement of the same institution — adjacency, where one
    agreement's `effective_from` equals another's `effective_to`, is
    permitted — and an overlapping submission is rejected with
    `ERR_AGREEMENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/agreement_half_open_adjacency
    """
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"],
                  effective_from="2026-01-01", effective_to="2027-06-30")
    resp = api_client.create_agreement(
        ctx["inst_id"],
        create_agreement_payload(effective_from="2027-06-29",
                                 effective_to="2028-06-30"),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_agreement_adjacency_allowed_at_exclusive_end(api):
    """PRD section 3.1: "coverage includes `effective_from` and runs up to
    but not including `effective_to`."
    PRD section 3.1: "adjacency, where one agreement's `effective_from`
    equals another's `effective_to`, is permitted".

    Design: Difficulty/resource_temporal_overlap/agreement_half_open_adjacency
    """
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"],
                  effective_from="2026-01-01", effective_to="2027-06-30")
    resp = api_client.create_agreement(
        ctx["inst_id"],
        create_agreement_payload(effective_from="2027-06-30",
                                 effective_to="2028-06-30"),
        OPS,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED", (
        "adjacent successor starts at 2027-06-30, in the future, so it is "
        "created SCHEDULED"
    )


def test_agreement_window_inclusive_start_exclusive_end(api):
    """PRD section 3.1: "As the clock advances, a `SCHEDULED` agreement whose
    `effective_from` has been reached — with `effective_to` still in the
    future — flips to `ACTIVE`; an `ACTIVE` agreement whose `effective_to`
    has been reached flips to `EXPIRED`".
    PRD section 3.1: "the institution flips from `ACTIVE` to `SUSPENDED`
    with `suspension_reason` of `AGREEMENT_LAPSE`".

    Design: Corner/state_machines/agreement_window_inclusive_start_exclusive_end
    """
    ctx = create_institution_with_registrars()
    resp = api_client.create_agreement(
        ctx["inst_id"],
        create_agreement_payload(effective_from="2026-10-01",
                                 effective_to="2026-11-01"),
        OPS,
    )
    ag = validate_success(resp, 201)
    assert ag["status"] == "SCHEDULED", "now 2026-09-01 < effective_from"

    advance_clock("2026-10-01T00:00:00Z")
    data, _m = validate_paginated(api_client.list_agreements(ctx["inst_id"], OPS))
    assert data[0]["status"] == "ACTIVE", (
        "now == effective_from is inside the half-open window"
    )

    advance_clock("2026-11-01T00:00:00Z")
    data, _m = validate_paginated(api_client.list_agreements(ctx["inst_id"], OPS))
    assert data[0]["status"] == "EXPIRED", (
        "now == effective_to is outside the half-open window"
    )
    inst = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert inst["status"] == "SUSPENDED"
    assert inst["suspension_reason"] == "AGREEMENT_LAPSE"
