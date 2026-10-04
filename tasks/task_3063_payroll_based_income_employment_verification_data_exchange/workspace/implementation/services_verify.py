"""Verification requests, the admission gauntlet, responses and attestations."""
import clock
import calculations
import models
import store
from errors import ApiError
from domain import (
    AUTHORIZATION_RESOLVE_DAYS, FREEZE_LIVE_STATES, OPEN_DISPUTE_STATES,
    VERIFIER_CLASS_TO_PRODUCT_CLASS,
)
from services_consent import escalate_dispute, _delete_response, dispute_escalation_sweep


# ------------------------------------------------------------------ helpers

def verifier_of(request):
    return store.get("verifiers", request.get("verifier_id"))


def worker_of(request):
    return store.get("covered_workers", request.get("covered_worker_id"))


def product_of(request):
    return store.get("verification_products", request.get("product_id"))


def resolution_for(request):
    """Resolve the request's selected employer and matched span.

    The matched span comes from the candidate pool; when the pool is empty
    (PRD §3.5: every candidate is DISPUTED, IMMUTABLE or FROZEN, or its employer
    is frozen) the employer is still identified from the worker's most recent
    span so the freeze guard of §2.10 can name it — the empty-pool case itself
    remains `None` and is reported by the match check.
    """
    worker_id = request.get("covered_worker_id")
    record = calculations.employer_match_selection(worker_id)
    if record is None:
        record = calculations.nearest_span_record(worker_id)
    employer = store.get("employers", record.get("employer_id")) if record else None
    if employer is None:
        return {"record": None, "employer": None, "tier": None, "months": 0}
    product = product_of(request)
    months = calculations.available_history_months(employer["id"], worker_id)
    tier = (calculations.tier_resolution(product, employer["id"], worker_id)
            if product else None)
    return {"record": record, "employer": employer, "tier": tier, "months": months}


def projected_fee(request, resolution):
    verifier = verifier_of(request)
    product = product_of(request)
    projected = (verifier.get("transaction_count") or 0) + 1
    return calculations.verification_fee(projected, resolution.get("tier"), product.get("base_fee_cents"))


def check_posture(verifier):
    if verifier.get("posture") != "NORMAL" or verifier.get("entitlement_status") != "AUTHORIZED":
        raise ApiError("ERR_VERIFIER_RESTRICTED")


def check_opt_out(worker):
    if worker.get("opt_out") or worker.get("consent_status") == "REVOKED":
        raise ApiError("ERR_WORKER_OPT_OUT")


def check_submission_purpose(request, verifier):
    """At submission the asserted purpose need only match the requesting party's own
    declared purpose; with no matching live authorization present the request parks
    in PENDING_AUTH (PRD §3.5)."""
    if request.get("permissible_purpose_asserted") != verifier.get("permitted_purpose"):
        raise ApiError("ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE")


def check_purpose(request, verifier, authorization):
    """Purpose comparison runs before the expiry comparison."""
    asserted = request.get("permissible_purpose_asserted")
    if authorization is None:
        authorization = _live_authorization(request)
        if authorization is not None:
            request["consumer_authorization_id"] = authorization["id"]
    if authorization is None or authorization.get("status") != "CAPTURED":
        raise ApiError("ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE")
    if (authorization.get("permitted_purpose") != asserted
            or verifier.get("permitted_purpose") != asserted):
        raise ApiError("ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE")
    if authorization.get("expires_at") < clock.now():
        raise ApiError("ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE")


def _live_authorization(request):
    for auth in store.all_rows("consumer_authorizations"):
        if (auth.get("covered_worker_id") == request.get("covered_worker_id")
                and auth.get("verifier_id") == request.get("verifier_id")
                and auth.get("permitted_purpose") == request.get("permissible_purpose_asserted")
                and auth.get("status") == "CAPTURED"):
            return auth
    return None


def check_class(verifier, product):
    mapped = VERIFIER_CLASS_TO_PRODUCT_CLASS.get(verifier.get("verifier_class"))
    if mapped is None or product.get("requesting_class") != mapped:
        raise ApiError("ERR_PRODUCT_NOT_PERMITTED_FOR_CLASS")
    if not product.get("active", True):
        raise ApiError("ERR_PRODUCT_NOT_PERMITTED_FOR_CLASS")


def freeze_is_live(employer):
    """True only while a freeze is pending or in force; released and lapsed
    employers are unfrozen (PRD §2.7)."""
    return (employer or {}).get("freeze_state") in FREEZE_LIVE_STATES


def check_freeze(resolution):
    employer = resolution.get("employer")
    if employer is None:
        raise ApiError("ERR_NO_EMPLOYER_MATCH")
    if freeze_is_live(employer):
        raise ApiError("ERR_EMPLOYER_FROZEN")


def check_match(resolution):
    if resolution.get("record") is None:
        raise ApiError("ERR_NO_EMPLOYER_MATCH")


def check_feed(resolution):
    employer = resolution.get("employer")
    if employer is None:
        raise ApiError("ERR_NO_EMPLOYER_MATCH")
    if employer.get("feed_status") == "STALLED":
        raise ApiError("ERR_EMPLOYER_FEED_STALLED")


def check_escrow(verifier, fee, request=None):
    if (verifier.get("escrow_balance_cents") or 0) < fee:
        if request is not None:
            # PRD §2.10 step 10 names ESCROW_INSUFFICIENT as the decline reason.
            decline_request(request, "ESCROW_INSUFFICIENT")
            store.touch(request)
            return False
        raise ApiError("ERR_ESCROW_INSUFFICIENT")
    return True


# ------------------------------------------------------------------ submission

def create_request(request):
    """Submission is gated only by posture, purpose and class (PRD §3.5); the
    freeze/feed/match/escrow hop of §2.10 runs when the request is permitted,
    validated and answered, not when it is merely recorded."""
    verifier = verifier_of(request)
    product = product_of(request)
    check_posture(verifier)
    check_submission_purpose(request, verifier)
    check_class(verifier, product)

    captured = None
    for auth in store.all_rows("consumer_authorizations"):
        if (auth.get("covered_worker_id") == request.get("covered_worker_id")
                and auth.get("verifier_id") == request.get("verifier_id")
                and auth.get("permitted_purpose") == request.get("permissible_purpose_asserted")
                and auth.get("status") == "CAPTURED"):
            captured = auth
            break
    if captured is None:
        request["request_state"] = "PENDING_AUTH"
        store.touch(request)
    return request


# ------------------------------------------------------------------ permit

def permit_request(request, authorization):
    """Permitting is gated by posture, purpose and class (PRD §3.5 / §2.10
    steps 6, 8 and 9). The freeze/feed/match/escrow hop of step 10 and the escrow
    comparison bind the response-materialization path, not the permit itself."""
    verifier = verifier_of(request)
    worker = worker_of(request)
    product = product_of(request)

    check_posture(verifier)
    check_opt_out(worker)
    check_purpose(request, verifier, authorization)
    check_class(verifier, product)

    resolution = resolution_for(request)
    request["consumer_authorization_id"] = authorization["id"]
    request["request_state"] = "PERMITTED"
    request["resolved_product_tier"] = resolution["tier"]
    store.touch(request)
    return request


# ------------------------------------------------------------------ currency validation

def validate_currency(request):
    verifier = verifier_of(request)
    worker = worker_of(request)
    check_posture(verifier)
    check_opt_out(worker)
    authorization = store.get("consumer_authorizations", request.get("consumer_authorization_id"))
    check_purpose(request, verifier, authorization)

    if request.get("request_state") not in ("PERMITTED", "VALIDATED"):
        raise ApiError("ERR_INVALID_STATE")

    if request.get("request_state") == "VALIDATED":
        # Re-validation exists to notice that a resolved record left CURRENT and
        # to fall the request back (PRD §3.5); it is not a fresh admission, so the
        # freeze/feed/match hop does not re-run and cannot decline the request.
        request = _fall_back_if_not_current(request, verifier)
        return request

    resolution = resolution_for(request)
    check_freeze(resolution)
    check_match(resolution)
    check_feed(resolution)

    if request.get("request_state") == "PERMITTED":
        records = calculations.selected_employer_records(
            resolution["employer"]["id"], request.get("covered_worker_id"))
        if not records:
            raise ApiError("ERR_NO_EMPLOYER_MATCH")
        if any(record.get("currency_state") == "FROZEN" for record in records):
            _decline_currency_failure(request, resolution)
            store.touch(request)
            return request
        if resolution["employer"].get("feed_status") != "CURRENT" or any(
                record.get("currency_state") != "CURRENT" for record in records):
            _decline_currency_failure(request, resolution)
            store.touch(request)
            return request
        request["request_state"] = "VALIDATED"
        request["current_employer_id"] = resolution["employer"]["id"]
        request["records_matched_count"] = len(records)
        verifier["transaction_count"] = (verifier.get("transaction_count") or 0) + 1
        store.touch(verifier)
        store.touch(request)
        return request

    raise ApiError("ERR_INVALID_STATE")


def _fall_back_if_not_current(request, verifier):
    """A VALIDATED request whose resolved records leave CURRENT falls back to
    PERMITTED with its matched count and transaction count released (PRD §3.5)."""
    employer_id = request.get("current_employer_id")
    if employer_id is None:
        resolution = resolution_for(request)
        employer_id = resolution["employer"]["id"] if resolution.get("employer") else None
        request["current_employer_id"] = employer_id
    records = (calculations.selected_employer_records(employer_id, request.get("covered_worker_id"))
               if employer_id else [])
    if any(record.get("currency_state") != "CURRENT" for record in records):
        request["request_state"] = "PERMITTED"
        request["records_matched_count"] = 0
        verifier["transaction_count"] = max(0, (verifier.get("transaction_count") or 0) - 1)
        store.touch(verifier)
    store.touch(request)
    return request


def _decline_currency_failure(request, resolution):
    employer = resolution.get("employer")
    if employer is not None and employer.get("freeze_state") == "ACTIVE":
        reason = "EMPLOYER_FROZEN"
    else:
        reason = "RECORD_STALE_INSUFFICIENT_HISTORY"
    from services_feed import decline_request
    decline_request(request, reason)


# ------------------------------------------------------------------ response build

def build_response(request, actor_id=None):
    verifier = verifier_of(request)
    worker = worker_of(request)
    product = product_of(request)

    check_posture(verifier)
    check_opt_out(worker)
    if actor_id is not None and actor_id != verifier.get("id"):
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    authorization = store.get("consumer_authorizations", request.get("consumer_authorization_id"))
    check_purpose(request, verifier, authorization)

    resolution = resolution_for(request)
    check_freeze(resolution)
    check_match(resolution)
    check_feed(resolution)
    fee = projected_fee(request, resolution)
    check_escrow(verifier, fee)

    was_validated = request.get("request_state") == "VALIDATED"
    employer = resolution["employer"]
    record = resolution["record"]
    tier = resolution["tier"]
    months = resolution["months"]
    records = calculations.selected_employer_records(employer["id"], request.get("covered_worker_id"))

    request["request_state"] = "RESPONDED"
    request["resolved_product_tier"] = tier
    request["current_employer_id"] = employer["id"]
    request["current_employment_status"] = record.get("employment_status")
    request["current_tenure_months"] = record.get("tenure_months")
    rendered = calculations.response_field_projection(product, tier, records)
    request["rendered_field_set"] = rendered
    request["records_matched_count"] = len([r for r in records
                                            if r.get("record_state") != "IMMUTABLE"])
    history = calculations.income_history_buckets(tier, product, records, months)
    active_open = any(
        r.get("employment_status") in ("ACTIVE", "LEAVE_OF_ABSENCE", "FURLOUGH")
        and (r.get("separation_date") is None
             or record.get("separation_date") is None)
        for r in records
    )

    request["fee_charged_cents"] = fee
    verifier["escrow_balance_cents"] = (verifier.get("escrow_balance_cents") or 0) - fee
    calculations.refresh_employer_feed_status(employer)
    calculations.employer_feed_counters_adjustment(employer)
    if not was_validated:
        verifier["transaction_count"] = (verifier.get("transaction_count") or 0) + 1
    response_row = models.new_verification_response({
        "verification_request_id": request["id"],
        "product_tier": tier,
        "rendered_fields": rendered,
        "employment_status": record.get("employment_status"),
        "tenure_months": record.get("tenure_months"),
        "income_history": history,
        "active_employment_found": active_open,
        "employer_feed_status": employer.get("feed_status"),
    })
    store.insert("verification_responses", response_row)
    _supersede_attestations(request["id"])
    attestation = models.new_verification_attestation({
        "verification_request_id": request["id"],
        "verifier_id": verifier["id"],
        "attested_purpose": request.get("permissible_purpose_asserted"),
    })
    attestation["attestation_state"] = "SIGNED"
    store.insert("verification_attestations", attestation)

    request["responded_at"] = clock.now()
    store.touch(request)
    store.touch(verifier)
    store.touch(employer)
    return response_row


def _supersede_attestations(request_id):
    for attestation in store.all_rows("verification_attestations"):
        if attestation.get("verification_request_id") != request_id:
            continue
        if attestation.get("attestation_state") == "SIGNED":
            attestation["attestation_state"] = "SUPERSEDED"
            store.touch(attestation)


# ------------------------------------------------------------------ reconsent / decline / reverse

def reconsent(request):
    worker = worker_of(request)
    state = request.get("request_state")
    if state == "PERMITTED":
        if worker.get("opt_out"):
            raise ApiError("ERR_WORKER_OPT_OUT")
        if clock.days_elapsed(request.get("submitted_at")) < AUTHORIZATION_RESOLVE_DAYS:
            raise ApiError("ERR_INVALID_STATE")
        request["request_state"] = "SUBMITTED"
        request["resolved_product_tier"] = None
        request["consumer_authorization_id"] = None
        store.touch(request)
        return request
    if state == "REVERSED_RECONSENT_REQUIRED":
        if worker.get("opt_out"):
            raise ApiError("ERR_WORKER_OPT_OUT")
        captured = None
        for auth in store.all_rows("consumer_authorizations"):
            if (auth.get("covered_worker_id") == request.get("covered_worker_id")
                    and auth.get("verifier_id") == request.get("verifier_id")
                    and auth.get("status") == "CAPTURED"):
                captured = auth
                break
        if captured is None:
            raise ApiError("ERR_INVALID_STATE")
        request["request_state"] = "SUBMITTED"
        request["decline_reason"] = None
        store.touch(request)
        return request
    if state == "SUBMITTED":
        return request
    if state in ("DECLINED", "RESPONDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    raise ApiError("ERR_INVALID_STATE")


def decline_by_actor(request, reason):
    from services_feed import decline_request
    return decline_request(request, reason)


def reverse_request(request):
    from services_feed import _invalidate_attestations
    verifier = verifier_of(request)
    # A reversal removes the response row (PRD §2.4, §3.5) and invalidates the
    # SIGNED attestation the response carried (PRD §3.2).
    _delete_response(request["id"])
    request["request_state"] = "REVERSED_RECONSENT_REQUIRED"
    request["decline_reason"] = "WORKER_OPT_OUT"
    request["_reversed_at"] = clock.now()
    # The request is no longer RESPONDED, so the fields the response build had
    # written no longer describe a live response (PRD §3.5).
    request["resolved_product_tier"] = None
    request["current_employment_status"] = None
    request["current_tenure_months"] = None
    request["rendered_field_set"] = []
    request["records_matched_count"] = 0
    _invalidate_attestations(request["id"])
    _revive_one_attestation(request)
    employer = store.get("employers", request.get("current_employer_id"))
    if employer is not None:
        calculations.employer_feed_counters_adjustment(employer)
        store.touch(employer)
    if verifier is not None:
        calculations.verifier_negative_score(verifier)
        store.touch(verifier)
    store.touch(request)
    return request


def _revive_one_attestation(request):
    """The reversal path invalidates the request's SIGNED attestation; the
    attestation is restored so the request still carries a title (PRD §2.4, §3.5)."""
    for attestation in store.all_rows("verification_attestations"):
        if attestation.get("verification_request_id") != request["id"]:
            continue
        if attestation.get("attestation_state") == "INVALIDATED":
            attestation["attestation_state"] = "SIGNED"
            store.touch(attestation)
            return attestation
    return None


def fallback_requests_for_employer(employer_id):
    for request in store.all_rows("verification_requests"):
        if request.get("request_state") != "VALIDATED":
            continue
        if request.get("current_employer_id") != employer_id:
            continue
        request["request_state"] = "PERMITTED"
        request["records_matched_count"] = 0
        store.touch(request)
        verifier = verifier_of(request)
        if verifier is not None:
            verifier["transaction_count"] = max(0, (verifier.get("transaction_count") or 0) - 1)
            store.touch(verifier)


# ------------------------------------------------------------------ verifier admin

def accredit(verifier):
    verifier["entitlement_status"] = "PENDING_REVIEW"
    store.touch(verifier)
    return verifier


def authorize_verifier(verifier):
    verifier["entitlement_status"] = "AUTHORIZED"
    calculations.verifier_negative_score(verifier)
    store.touch(verifier)
    return verifier


def adjust_escrow(verifier, amount_cents):
    verifier["escrow_balance_cents"] = (verifier.get("escrow_balance_cents") or 0) + int(amount_cents or 0)
    store.touch(verifier)
    return verifier


# ------------------------------------------------------------------ currency reviews

def score_review(review, employer):
    review["missing_periods"] = calculations.missing_periods_for(review)
    review["currency_score"] = calculations.feed_currency_score(review, employer)
    review["review_state"] = "SCORED"
    employer["review_state"] = "SCORED"
    employer["review_period_end"] = review.get("review_period_end")
    employer["missing_periods"] = review["missing_periods"]
    employer["currency_score"] = review["currency_score"]
    calculations.refresh_employer_feed_status(employer)
    store.touch(employer)
    store.touch(review)
    return review


def escalate_review(review, employer):
    review["review_state"] = "ESCALATED"
    review["_escalated_at"] = clock.now()
    employer["review_state"] = "ESCALATED"
    employer["feed_status"] = "STALLED"
    for record in store.all_rows("employment_records"):
        if record.get("employer_id") != employer["id"]:
            continue
        if record.get("currency_state") == "CURRENT":
            record["currency_state"] = "STALE"
            store.touch(record)
    fallback_requests_for_employer(employer["id"])
    calculations.refresh_verifiers_for_employer(employer["id"])
    store.touch(employer)
    store.touch(review)
    return review


def rescore_review(review, employer):
    if review.get("review_state") == "ESCALATED":
        if employer.get("feed_status") not in ("CURRENT", "DELAYED"):
            raise ApiError("ERR_INVALID_STATE")
        review["review_state"] = "SCORED"
        review["currency_score"] = calculations.feed_currency_score(review, employer)
        employer["currency_score"] = review["currency_score"]
        store.touch(review)
        store.touch(employer)
        return review
    if review.get("review_state") == "CLEARED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    review["missing_periods"] = calculations.missing_periods_for(review)
    review["currency_score"] = calculations.feed_currency_score(review, employer)
    employer["missing_periods"] = review["missing_periods"]
    employer["currency_score"] = review["currency_score"]
    employer["review_state"] = "SCORED"
    if (employer.get("feed_status") == "CURRENT" and review["missing_periods"] == 0):
        review["review_state"] = "CLEARED"
        employer["review_state"] = "CLEARED"
    else:
        review["review_state"] = "SCORED"
    store.touch(review)
    store.touch(employer)
    return review