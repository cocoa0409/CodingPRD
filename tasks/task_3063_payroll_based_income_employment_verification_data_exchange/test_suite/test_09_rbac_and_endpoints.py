"""Role scoping, ownership denial and the worker's control of their file."""
from test_helpers import (
    onboard_employer,
    register_worker,
    register_authorized_verifier,
    register_product,
    create_verified_layout,
    create_batch,
    attach_record,
    validate_batch,
    capture_authorization,
    submit_request,
    permit_request,
    validate_currency,
    materialize_response,
    get_request,
    get_worker,
    get_disclosure,
    set_clock,
    make_worker_headers,
    make_employer_headers,
    make_verifier_headers,
    api,
    validate_success,
    validate_error,
    ApiErrorId,
)


def test_verifier_cannot_validate_currency_on_another_parties_request(api):
    """PRD §2.1: "When `X-User-Role` is `Verifier`, `X-User-ID` is the `id` of the
    acting `Verifier`, and ownership checks compare `verifier_id` to `X-User-ID`."
    PRD §2.10: "Ownership next: an entity-backed role acting on another entity's row
    yields `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/verifier_cannot_validate_currency_on_another_requesting_party_request
    """
    ctx = _request_at_permitted()
    verifier_b = register_authorized_verifier(
        legal_name="Harbor Mortgage Group", verifier_class="MORTGAGE_LENDER"
    )
    response = api.validate_currency(ctx["request"]["id"], make_verifier_headers(verifier_b["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert get_request(
        ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"])
    )["request_state"] == "PERMITTED"


def test_employer_role_cannot_reach_the_verifier_exclusive_operation(api):
    """PRD §2.1: "Request permitting is shared between `CoveredWorker` and
    `PlatformAdmin`."
    PRD §2.10: "Role authorization next: a role the operation does not list yields
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | /work-number/verification-requests/{id}/validate-currency | Check
    that the resolved records are current enough for instant verification. | Verifier".

    Design: Corner/rbac/employer_cannot_validate_currency_at_all
    """
    ctx = _request_at_permitted()
    headers = make_employer_headers(ctx["employer"]["id"])
    response = api.validate_currency(ctx["request"]["id"], headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_employer_role_is_refused_even_against_its_own_employer_row_request(api):
    """PRD §2.1: "A role that is present and recognized but not listed on the addressed
    operation's role set fails with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/employer_cannot_validate_currency_at_all
    """
    ctx = _request_at_permitted()
    headers = make_employer_headers(ctx["employer"]["id"])
    response = api.validate_currency(ctx["request"]["id"], headers)
    assert response.status_code == 403
    assert get_request(
        ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"])
    )["request_state"] == "PERMITTED"


def test_worker_cannot_request_a_disclosure_for_another_worker(api):
    """PRD §2.1: "When `X-User-Role` is `CoveredWorker`, `X-User-ID` is the `id` of the
    acting `CoveredWorker`, and ownership checks compare `covered_worker_id` on the
    addressed resource to `X-User-ID`."

    Design: Corner/rbac/worker_cannot_read_another_workers_own_disclosure
    """
    worker_a = register_worker()
    worker_b = register_worker(full_name="Ivan Petrov", ssn_last4="2288", date_of_birth="1990-07-21")
    response = api.create_disclosure(worker_b["id"], make_worker_headers(worker_a["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)


def test_worker_can_request_their_own_disclosure(api):
    """PRD §2.10: "Ownership next: an entity-backed role acting on another entity's row
    yields `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
    PRD §4: "POST | /work-number/consumer-disclosures | Request a disclosure of the
    worker's own data file. | CoveredWorker".

    Design: Corner/rbac/worker_cannot_read_another_workers_own_disclosure
    """
    worker_a = register_worker()
    response = api.create_disclosure(worker_a["id"], make_worker_headers(worker_a["id"]))
    data = validate_success(response, 201)
    assert data["covered_worker_id"] == worker_a["id"]
    assert data["disclosure_state"] == "REQUESTED"


def test_opt_out_declines_live_requests_and_reverses_responded_ones(api):
    """PRD §3.2: "Setting opt-out flips `consent_status` to `REVOKED` and `opt_out` to
    true, revokes every live authorization, declines every request still in `SUBMITTED`,
    `PENDING_AUTH`, `PERMITTED` or `VALIDATED` with `WORKER_OPT_OUT`, reverses every
    request already `RESPONDED` into `REVERSED_RECONSENT_REQUIRED`".

    Design: Corner/endpoints/worker_opt_out_declines_every_open_request_for_that_worker
    """
    ctx = _two_requests_one_responded()
    api.opt_out_worker(ctx["worker"]["id"], make_worker_headers(ctx["worker"]["id"]))

    first = get_request(ctx["req_1"], make_worker_headers(ctx["worker"]["id"]))
    second = get_request(ctx["req_2"], make_worker_headers(ctx["worker"]["id"]))
    assert first["request_state"] == "DECLINED"
    assert first["decline_reason"] == "WORKER_OPT_OUT"
    assert second["request_state"] == "REVERSED_RECONSENT_REQUIRED"


def test_opt_out_revokes_consent_and_the_live_authorization(api):
    """PRD §2.5: "Its `status` is `CAPTURED` at creation and moves to `REVOKED` when
    the worker opts out."
    PRD §3.2: "Opting back in flips `consent_status` to `PROVIDED` and `opt_out` to
    false".

    Design: Corner/endpoints/worker_opt_out_declines_every_open_request_for_that_worker
    """
    ctx = _two_requests_one_responded()
    worker_id = ctx["worker"]["id"]
    api.opt_out_worker(worker_id, make_worker_headers(worker_id))

    worker = get_worker(worker_id)
    assert worker["opt_out"] is True
    assert worker["consent_status"] == "REVOKED"
    auth = validate_success(
        api.get_authorization(ctx["authorization"]["id"], make_worker_headers(worker_id)), 200
    )
    assert auth["status"] == "REVOKED"


def test_response_list_filters_by_verification_request(api):
    """PRD §4: "GET | /work-number/verification-responses | List responses, optionally
    scoped to a request. | Verifier, CoveredWorker, PlatformAdmin".
    PRD §3.5: "A `VerificationResponse` row is created carrying the same
    `product_tier`, `rendered_fields`, `employment_status`, `tenure_months`,
    `income_history`, `active_employment_found` and `employer_feed_status`".

    Design: Corner/endpoints/reversals_list_filters_by_verification_request
    """
    from test_helpers import list_responses
    ctx = _responded_stack()
    rows = list_responses(ctx["request"]["id"], ctx["verifier"]["id"])
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["verification_request_id"] == ctx["request"]["id"]
    assert rows[0]["product_tier"] == "EMPLOYMENT_INCOME"
    assert "employment_status" in rows[0]["rendered_fields"]


def test_response_list_is_empty_for_a_request_without_a_response(api):
    """PRD §2.4: "a response row is never mutated in place — the reversal path deletes
    it."

    Design: Corner/endpoints/reversals_list_filters_by_verification_request
    """
    from test_helpers import list_responses
    ctx = _request_at_permitted()
    assert list_responses(ctx["request"]["id"], ctx["verifier"]["id"]) == []


# --------------------------------------------------------------------------
# local composite builders
# --------------------------------------------------------------------------

def _request_at_permitted():
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])
    product = register_product()
    verifier = register_authorized_verifier()
    authorization = capture_authorization(worker, verifier)
    request = submit_request(verifier, worker, product)
    request = permit_request(worker["id"], request["id"], authorization["id"])
    return {
        "employer": employer,
        "worker": worker,
        "verifier": verifier,
        "product": product,
        "authorization": authorization,
        "request": request,
    }


def _responded_stack():
    ctx = _request_at_permitted()
    request_id = ctx["request"]["id"]
    validate_currency(ctx["verifier"]["id"], request_id)
    ctx["response"] = materialize_response(ctx["verifier"]["id"], request_id)
    ctx["request"] = get_request(request_id, make_verifier_headers(ctx["verifier"]["id"]))
    assert ctx["request"]["request_state"] == "RESPONDED"
    return ctx


def _two_requests_one_responded():
    ctx = _request_at_permitted()
    verifier = ctx["verifier"]
    worker = ctx["worker"]
    req_2 = submit_request(verifier, worker, ctx["product"])
    req_2 = permit_request(worker["id"], req_2["id"], ctx["authorization"]["id"])
    validate_currency(verifier["id"], req_2["id"])
    materialize_response(verifier["id"], req_2["id"])
    ctx["req_1"] = ctx["request"]["id"]
    ctx["req_2"] = req_2["id"]
    return ctx