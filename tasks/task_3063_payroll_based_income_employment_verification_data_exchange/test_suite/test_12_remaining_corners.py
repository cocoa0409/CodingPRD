"""Remaining corner instances: terminal permit, accrual re-settlement, and the
satisfaction passes of the freeze and expiry guards."""
from test_helpers import (
    onboard_employer,
    register_worker,
    register_product,
    register_authorized_verifier,
    create_verified_layout,
    create_batch,
    attach_record,
    validate_batch,
    capture_authorization,
    submit_request,
    permit_request,
    materialize_response,
    validate_currency,
    create_validated_batch_accrual,
    post_settlement,
    void_settlement,
    list_accruals,
    get_employer,
    get_request,
    set_clock,
    make_worker_headers,
    make_verifier_headers,
    api,
    validate_success,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
)


def test_permit_on_a_responded_request_is_refused(api):
    """PRD §3.5: "Aiming a permit at a request that is not in `SUBMITTED` or
    `PENDING_AUTH` fails the state check with `ERR_INVALID_STATE` (HTTP 409), and a
    request that has already reached one of its terminal states fails with
    `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §2.8: "a `VerificationRequest` that has reached `RESPONDED`, `DECLINED` or
    `REVERSED_RECONSENT_REQUIRED` ... may not be driven further".

    Design: Corner/state_machines/verification_request_permit_from_terminal_responded_is_invalid
    """
    ctx = _responded_stack()
    response = api.permit_request(
        ctx["request"]["id"], ctx["authorization"]["id"], make_worker_headers(ctx["worker"]["id"])
    )
    validate_error_is_one_of(
        response, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
    )
    after = get_request(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert after["request_state"] == "RESPONDED"


def test_rejected_permit_leaves_the_resolved_tier_untouched(api):
    """PRD §3.5: "on success it moves to `PERMITTED` with its `resolved_product_tier`
    snapshotted by the tier rule below and its `version` bumped."
    PRD §2.8: "An action addressed at a resource that is not in any state from which that
    action is defined fails with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/verification_request_permit_from_terminal_responded_is_invalid
    """
    ctx = _responded_stack()
    before = get_request(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    api.permit_request(
        ctx["request"]["id"], ctx["authorization"]["id"], make_worker_headers(ctx["worker"]["id"])
    )
    after = get_request(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert after["resolved_product_tier"] == before["resolved_product_tier"]


def test_void_restores_accrued_so_the_accrual_can_be_settled_again(api):
    """PRD §3.7: "the `WAIVED` accruals it covers return to `ACCRUED` unconditionally,
    while a `PAID` accrual returns to `ACCRUED` only when the void lands within 30 days
    of that accrual's `updated_at`".
    PRD §3.7: "A void releases exactly the settled figures it had added".

    Design: Corner/state_machines/contributor_accrual_paid_returns_to_accrued_on_void
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    employer_id = ctx["employer"]["id"]

    first = post_settlement(employer_id, settlement_period_end="2026-09-30T00:00:00Z",
                            settlement_budget_cents=12000)
    assert list_accruals(employer_id)[0]["cycle_state"] == "PAID"
    void_settlement(first["settlement_id"])
    assert list_accruals(employer_id)[0]["cycle_state"] == "ACCRUED"

    second = post_settlement(
        employer_id, settlement_period_end="2026-09-30T00:00:00Z", settlement_budget_cents=12000
    )
    accrual = list_accruals(employer_id)[0]
    assert accrual["cycle_state"] == "PAID"
    assert second["accrual_count"] == 1
    assert second["settled_gross_cents"] == 12000
    assert get_employer(employer_id)["compensation_earned_cents"] == 12000


def test_re_settlement_does_not_double_credit_the_employer(api):
    """PRD §3.7: "Eligible accruals are walked in a pinned sequence ... and each is
    offered to the buckets".
    PRD §3.9: "voiding a settlement must leave the total exactly where it stood before
    the settlement posted".

    Design: Corner/state_machines/contributor_accrual_paid_returns_to_accrued_on_void
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    employer_id = ctx["employer"]["id"]
    first = post_settlement(employer_id, settlement_period_end="2026-09-30T00:00:00Z",
                            settlement_budget_cents=12000)
    void_settlement(first["settlement_id"])
    post_settlement(
        employer_id, settlement_period_end="2026-09-30T00:00:00Z", settlement_budget_cents=12000
    )
    assert get_employer(employer_id)["compensation_earned_cents"] == 12000
    assert get_employer(employer_id)["compensation_earned_cents"] != 24000


def test_unfrozen_employer_permits_currency_validation_to_succeed(api):
    """PRD §2.10: "the selected employer's `freeze_state` must be `NONE`, its
    `feed_status` must not be `STALLED`".
    PRD §3.5: "On success the request moves to `VALIDATED`, `records_matched_count` is
    set to the number of resolved records".

    Design: Corner/validations/employer_freeze_rule_does_not_fire_when_freeze_state_is_none
    """
    ctx = _permitted_stack()
    response = api.validate_currency(ctx["request"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    data = validate_success(response, 200)

    assert data["request_state"] == "VALIDATED"
    assert data["decline_reason"] is None
    assert data["records_matched_count"] == 1
    assert get_employer(ctx["employer"]["id"])["freeze_state"] == "NONE"


def test_authorization_expiring_exactly_now_is_still_admissible(api):
    """PRD §2.10: "the presented authorization must be `CAPTURED`; and its `expires_at`
    must be on or after the current instant, so an authorization expiring exactly now is
    still admissible."
    PRD §2.5: "an `expires_at` that is `granted_at` advanced by 365 days and frozen at
    grant time".

    Design: Corner/validations/verified_authorization_exactly_at_expiry_is_still_accepted
    """
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-12-31T00:00:00Z", record_count=900
    )
    attach_record(employer["id"], worker["id"], batch["id"])
    validate_batch(employer["id"], batch["id"])
    product = register_product()
    verifier = register_authorized_verifier()

    set_clock("2026-01-01T00:00:00Z")
    authorization = capture_authorization(worker, verifier)
    assert authorization["expires_at"] == "2027-01-01T00:00:00.000Z"
    request = submit_request(verifier, worker, product)
    request = permit_request(worker["id"], request["id"], authorization["id"])

    set_clock("2027-01-01T00:00:00Z")
    response = api.validate_currency(request["id"], make_verifier_headers(verifier["id"]))
    data = validate_success(response, 200)
    assert data["request_state"] == "VALIDATED"
    assert data["decline_reason"] is None


# --------------------------------------------------------------------------
# local composite builders
# --------------------------------------------------------------------------

def _permitted_stack():
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
        "authorization": authorization,
        "request": request,
    }


def _responded_stack():
    ctx = _permitted_stack()
    request_id = ctx["request"]["id"]
    validate_currency(ctx["verifier"]["id"], request_id)
    ctx["response"] = materialize_response(ctx["verifier"]["id"], request_id)
    ctx["request"] = get_request(request_id, make_verifier_headers(ctx["verifier"]["id"]))
    assert ctx["request"]["request_state"] == "RESPONDED"
    return ctx