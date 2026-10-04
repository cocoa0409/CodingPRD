"""Requester accounts: creation defaults, vetting cycle, auth boundaries."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, build_user_headers,
    create_institution, create_institution_with_registrars,
    setup_student_with_file, create_requester, vet_requester,
    create_degree_request, make_requester_headers,
    create_requester_payload, create_institution_payload,
)

OPS = TEST_USERS["ops_headers"]


def test_requester_create_defaults_credit_zero(api):
    """PRD section 3.7: "An operator creates a Requester account with an
    `org_name`, a `requester_kind` of `EMPLOYER` or `BACKGROUND_SCREENER`,
    and an optional `initial_credit_cents` that defaults to zero; the
    account begins `PENDING_VETTING` with `credit_balance_cents` equal to
    the seed credit."
    PRD section 2.5: "`version` (integer): starts at 1 at creation".

    Design: Corner/entities/requester_create_defaults_credit_zero
    """
    create_institution()
    resp = api_client.create_requester(
        create_requester_payload(org_name="Bare Org",
                                 requester_kind="BACKGROUND_SCREENER"),
        OPS,
    )
    data = validate_success(resp, 201)
    assert data["credit_balance_cents"] == 0
    assert data["status"] == "PENDING_VETTING"
    assert data["version"] == 1


def test_requester_denied_terminal_and_pending_guards(api):
    """PRD section 3.7: "`VET` moves a `PENDING_VETTING` account to `VETTED`
    — and later re-vets a `SUSPENDED` account back to `VETTED` — stamping
    `vetted_at` with the most recent vetting time, while `DENY` moves a
    `PENDING_VETTING` account to terminal `DENIED`; a decision fired from
    any other from-state is rejected with `ERR_INVALID_STATE`."
    PRD section 3.7: "An operator may also suspend a `VETTED` account".

    Design: Corner/state_machines/requester_denied_terminal_and_pending_guards
    """
    r1 = create_requester(kind="BACKGROUND_SCREENER", org="Bad Actor Inc")
    denied = vet_requester(r1["id"], "DENY")
    assert denied["status"] == "DENIED"
    r2 = create_requester(kind="EMPLOYER", org="New Org")

    vet_again = api_client.vet_requester(r1["id"], {"outcome": "VET"}, OPS)
    validate_error(vet_again, ApiErrorId.ERR_INVALID_STATE)
    susp_denied = api_client.suspend_requester(r1["id"], OPS)
    validate_error(susp_denied, ApiErrorId.ERR_INVALID_STATE)
    susp_pending = api_client.suspend_requester(r2["id"], OPS)
    validate_error(susp_pending, ApiErrorId.ERR_INVALID_STATE)


def test_err_requester_not_found(api):
    """PRD section 2.8: "Each kind of unresolved reference reports its own
    error — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_DEGREE_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, or
    `ERR_DATASET_NOT_FOUND`, each HTTP 404".

    Design: Corner/errors/err_requester_not_found
    """
    create_institution()
    resp = api_client.vet_requester(NON_EXISTENT_UUID, {"outcome": "VET"}, OPS)
    validate_error(resp, ApiErrorId.ERR_REQUESTER_NOT_FOUND)


def _vetting_cycle_scene(api):
    """Student at a compliant institution plus a fresh PENDING_VETTING
    requester with a large balance."""
    ctx = setup_student_with_file(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )
    ctx["requester"] = create_requester(credit=100000)
    ctx["requester_id"] = ctx["requester"]["id"]
    return ctx


def test_unvetted_and_suspended_requester_cannot_buy(api):
    """PRD section 3.7: "Next, a requester caller's account must be `VETTED`
    (`ERR_REQUESTER_NOT_VETTED`)."
    PRD section 3.7: "An operator may also suspend a `VETTED` account:
    in-flight `QUOTED` requests are unaffected, but new request creation is
    rejected with `ERR_REQUESTER_NOT_VETTED` (HTTP 403)."

    Design: Difficulty/non_linear_state_machine/requester_vetting_suspension_revetting_cycle
    """
    ctx = _vetting_cycle_scene(api)
    pending = api_client.create_verification_request(
        {"requester_id": ctx["requester_id"], "student_id": ctx["student_id"],
         "institution_id": ctx["inst_id"], "product_type": "DEGREE",
         "purpose": "EMPLOYMENT"},
        make_requester_headers(ctx["requester_id"]),
    )
    validate_error(pending, ApiErrorId.ERR_REQUESTER_NOT_VETTED)

    vet_requester(ctx["requester_id"], "VET")
    suspended = validate_success(
        api_client.suspend_requester(ctx["requester_id"], OPS), 200,
    )
    assert suspended["status"] == "SUSPENDED"
    while_suspended = api_client.create_verification_request(
        {"requester_id": ctx["requester_id"], "student_id": ctx["student_id"],
         "institution_id": ctx["inst_id"], "product_type": "DEGREE",
         "purpose": "EMPLOYMENT"},
        make_requester_headers(ctx["requester_id"]),
    )
    validate_error(while_suspended, ApiErrorId.ERR_REQUESTER_NOT_VETTED)


def test_revet_reopens_purchasing(api):
    """PRD section 3.7: "`VET` moves a `PENDING_VETTING` account to `VETTED`
    — and later re-vets a `SUSPENDED` account back to `VETTED` — stamping
    `vetted_at` with the most recent vetting time".
    PRD section 3.7: "A created request is `QUOTED`".

    Design: Difficulty/non_linear_state_machine/requester_vetting_suspension_revetting_cycle
    """
    ctx = _vetting_cycle_scene(api)
    vet_requester(ctx["requester_id"], "VET")
    validate_success(api_client.suspend_requester(ctx["requester_id"], OPS), 200)
    revetted = vet_requester(ctx["requester_id"], "VET")
    assert revetted["status"] == "VETTED", "the cycle closes back to VETTED"
    req = create_degree_request(
        ctx["inst_id"], ctx["student_id"], ctx["requester_id"],
    )
    assert req["status"] == "QUOTED"


def test_rbac_requester_cannot_create_institution(api):
    """PRD section 3.1: "A `ClearinghouseOps` operator onboards an
    institution by supplying its legal `name`, its federal `ope_id`".
    PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_requester_cannot_create_institution
    """
    rq = create_requester()
    resp = api_client.create_institution(
        create_institution_payload(name="Rogue U", ope_id="00777700",
                                   users=[{"email": "sub@rogue.edu",
                                           "role": "SUBMITTER"}]),
        make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unauthenticated_unknown_entity_backed_user(api):
    """PRD section 2.1: "A request missing either header, or whose
    `X-User-ID` fails to resolve to an existing entity for an entity-backed
    role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD section 2.1: "When `X-User-Role` is `RegistrarSubmitter`, `X-User-ID`
    is the `id` of the acting `InstitutionUser` whose registrar-office
    `role` is `SUBMITTER`."

    Design: Corner/validations/unauthenticated_unknown_entity_backed_user
    """
    ctx = create_institution_with_registrars()
    resp = api_client.get_institution(
        ctx["inst_id"],
        build_user_headers(NON_EXISTENT_UUID, "RegistrarSubmitter"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_role_gate_preempts_existence_check(api):
    """PRD section 2.8: "Every request is evaluated against an ordered
    cascade of checks, and the first failure wins: its error is the
    response. Broadly, authentication and role membership come first
    (§2.1), then payload well-formedness, then existence of referenced
    resources, then state-machine applicability, then institutional and
    agreement state, and finally the business, temporal, and fiscal rules of
    the specific workflow narrated in §3."
    PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/role_gate_preempts_existence_check
    """
    rq = create_requester()
    resp = api_client.get_enrollment_file(
        NON_EXISTENT_UUID, make_requester_headers(rq["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
