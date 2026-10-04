"""Covered workers, authorizations, disclosures and the dispute cycle."""
import clock
import calculations
import models
import store
from errors import ApiError
from domain import (
    AUTHORIZATION_RESOLVE_DAYS, DISPUTE_REOPEN_GRACE_DAYS, OPEN_DISPUTE_STATES,
)


# ------------------------------------------------------------------ worker control

def opt_out(worker):
    worker["consent_status"] = "REVOKED"
    worker["opt_out"] = True
    for authorization in store.all_rows("consumer_authorizations"):
        if authorization.get("covered_worker_id") != worker["id"]:
            continue
        if authorization.get("status") == "CAPTURED":
            authorization["status"] = "REVOKED"
            authorization["revoked_at"] = clock.now()
            store.touch(authorization)

    affected_employers = set()
    for request in store.all_rows("verification_requests"):
        if request.get("covered_worker_id") != worker["id"]:
            continue
        state = request.get("request_state")
        if request.get("current_employer_id"):
            affected_employers.add(request["current_employer_id"])
        if state in ("SUBMITTED", "PENDING_AUTH", "PERMITTED", "VALIDATED"):
            _decline_with_opt_out(request)
        elif state == "RESPONDED":
            request["request_state"] = "REVERSED_RECONSENT_REQUIRED"
            request["decline_reason"] = "WORKER_OPT_OUT"
            request["_reversed_at"] = clock.now()
            _delete_response(request["id"])
            store.touch(request)
            if request.get("current_employer_id"):
                employer = store.get("employers", request["current_employer_id"])
                if employer is not None:
                    calculations.employer_feed_counters_adjustment(employer)
            verifier = store.get("verifiers", request.get("verifier_id"))
            if verifier is not None:
                calculations.verifier_negative_score(verifier)
    store.touch(worker)
    worker["open_dispute_count"] = _open_dispute_count(worker["id"])
    return worker


def _decline_with_opt_out(request):
    from services_feed import _invalidate_attestations
    request["request_state"] = "DECLINED"
    request["decline_reason"] = "WORKER_OPT_OUT"
    request["fee_charged_cents"] = 0
    _invalidate_attestations(request["id"])
    store.touch(request)


def _delete_response(request_id):
    for response in list(store.all_rows("verification_responses")):
        if response.get("verification_request_id") == request_id:
            store.delete("verification_responses", response["id"])


def _open_dispute_count(worker_id):
    count = 0
    for dispute in store.all_rows("record_disputes"):
        if dispute.get("covered_worker_id") == worker_id:
            if dispute.get("dispute_state") in OPEN_DISPUTE_STATES:
                count += 1
    return count


def opt_in(worker):
    worker["consent_status"] = "PROVIDED"
    worker["opt_out"] = False
    store.touch(worker)
    return worker


# ------------------------------------------------------------------ authorizations

def capture_authorization(authorization, worker):
    now = clock.now()
    for existing in store.all_rows("consumer_authorizations"):
        if existing is authorization:
            continue
        if (existing.get("covered_worker_id") == authorization["covered_worker_id"]
                and existing.get("verifier_id") == authorization["verifier_id"]
                and existing.get("permitted_purpose") == authorization["permitted_purpose"]
                and existing.get("status") == "CAPTURED"
                and existing.get("granted_at") <= now < existing.get("expires_at")):
            raise ApiError("ERR_AUTHORIZATION_OVERLAP")
    store.touch(worker)
    return authorization


def has_captured_authorization(worker_id, verifier_id, purpose, require_live):
    now = clock.now()
    for authorization in store.all_rows("consumer_authorizations"):
        if (authorization.get("covered_worker_id") == worker_id
                and authorization.get("verifier_id") == verifier_id
                and authorization.get("permitted_purpose") == purpose
                and authorization.get("status") == "CAPTURED"):
            if not require_live or authorization.get("expires_at") >= now:
                return authorization
    return None


# ------------------------------------------------------------------ disclosures

def generate_disclosure(disclosure, worker):
    if worker.get("disclosure_state") == "CURRENT":
        raise ApiError("ERR_DISCLOSURE_ALREADY_CURRENT")
    if disclosure.get("disclosure_state") == "SUPERSEDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    calculations.disclosure_file_assembly(worker, disclosure)
    disclosure["disclosure_state"] = "GENERATED"
    store.touch(disclosure)
    worker["disclosure_state"] = "CURRENT"
    store.touch(worker)
    return disclosure


# ------------------------------------------------------------------ disputes

def file_dispute(dispute, record, worker, employer):
    record["record_state"] = "DISPUTED"
    store.touch(record)
    worker["open_dispute_count"] = (worker.get("open_dispute_count") or 0) + 1
    store.touch(worker)
    employer["dispute_open_count"] = (employer.get("dispute_open_count") or 0) + 1
    store.touch(employer)
    dispute["dispute_state"] = "AWAITING_EMPLOYER"
    dispute["response_due_date"] = clock.add_days(dispute["filed_at"], 45)
    store.touch(dispute)
    return dispute


def notice_dispute(dispute):
    if dispute.get("dispute_state") == "CLOSED":
        raise ApiError("ERR_DISPUTE_TERMINAL")
    if dispute.get("dispute_state") != "AWAITING_EMPLOYER":
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() > dispute.get("response_due_date"):
        raise ApiError("ERR_DISPUTE_RESPONSE_WINDOW_EXPIRED")
    dispute["dispute_state"] = "NOTICE_SENT"
    dispute["notice_sent_at"] = clock.now()
    store.touch(dispute)
    return dispute


def respond_dispute(dispute, resolution, record, worker, employer):
    state = dispute.get("dispute_state")
    if state == "CLOSED":
        raise ApiError("ERR_DISPUTE_TERMINAL")
    late = clock.now() > dispute.get("response_due_date")
    if resolution == "ACKNOWLEDGED":
        if state != "NOTICE_SENT":
            raise ApiError("ERR_INVALID_STATE")
        if late:
            raise ApiError("ERR_DISPUTE_RESPONSE_WINDOW_EXPIRED")
        dispute["dispute_state"] = "EMPLOYER_RESPONDED"
        store.touch(dispute)
        return dispute
    if resolution not in ("UPHELD", "CORRECTED"):
        raise ApiError("ERR_INVALID_STATE")
    if state not in OPEN_DISPUTE_STATES:
        raise ApiError("ERR_INVALID_STATE")
    if late:
        raise ApiError("ERR_DISPUTE_RESPONSE_WINDOW_EXPIRED")

    now = clock.now()
    if resolution == "UPHELD":
        dispute["dispute_state"] = "RESOLVED_UPHELD"
        dispute["resolved_at"] = now
        record["record_state"] = "VERIFIED"
        store.touch(record)
    else:
        dispute["dispute_state"] = "RESOLVED_CORRECTED"
        dispute["resolved_at"] = now
        _apply_correction(dispute, record, employer)
        record["record_state"] = "CORRECTED"
        calculations.recompute_record(record, employer)
        store.touch(record)
        worker["corrected_record_count"] = (worker.get("corrected_record_count") or 0) + 1
        _revive_declined_requests(employer, dispute)
    worker["open_dispute_count"] = max(0, (worker.get("open_dispute_count") or 0) - 1)
    store.touch(worker)
    employer["dispute_open_count"] = max(0, (employer.get("dispute_open_count") or 0) - 1)
    store.touch(employer)
    store.touch(dispute)
    return dispute


def _apply_correction(dispute, record, employer):
    field = dispute.get("claimed_field")
    value = dispute.get("claimed_correct_value")
    if field == "TENURE":
        try:
            record["standard_hours_per_week"] = float(value)
        except (TypeError, ValueError):
            record["standard_hours_per_week"] = value
    elif field == "EMPLOYMENT_STATUS":
        record["employment_status"] = value
    elif field == "HIRE_DATE":
        record["hire_date"] = clock.parse_iso(value)
    elif field == "SEPARATION_DATE":
        record["separation_date"] = clock.parse_iso(value)
    elif field == "PAY_RATE":
        try:
            record["pay_rate_cents"] = int(value)
        except (TypeError, ValueError):
            record["pay_rate_cents"] = value


def _revive_declined_requests(employer, dispute):
    for request in store.all_rows("verification_requests"):
        if request.get("current_employer_id") != employer["id"]:
            continue
        if request.get("request_state") != "DECLINED":
            continue
        if request.get("decline_reason") != "RECORD_STALE_INSUFFICIENT_HISTORY":
            continue
        attestation = models.new_verification_attestation({
            "verification_request_id": request["id"],
            "verifier_id": request.get("verifier_id"),
            "attested_purpose": request.get("permissible_purpose_asserted"),
        })
        store.insert("verification_attestations", attestation)


def reopen_dispute(dispute, worker, employer):
    state = dispute.get("dispute_state")
    if state == "CLOSED":
        raise ApiError("ERR_DISPUTE_TERMINAL")
    if state not in ("RESOLVED_UPHELD", "RESOLVED_CORRECTED"):
        raise ApiError("ERR_INVALID_STATE")
    if clock.days_elapsed(dispute.get("resolved_at")) > DISPUTE_REOPEN_GRACE_DAYS:
        raise ApiError("ERR_INVALID_STATE")
    dispute["dispute_state"] = "NOTICE_SENT"
    store.touch(dispute)
    worker["open_dispute_count"] = (worker.get("open_dispute_count") or 0) + 1
    store.touch(worker)
    employer["dispute_open_count"] = (employer.get("dispute_open_count") or 0) + 1
    store.touch(employer)
    return dispute


def reconfirm_record(record, worker):
    record["record_state"] = "VERIFIED"
    store.touch(record)
    worker["corrected_record_count"] = max(0, (worker.get("corrected_record_count") or 0) - 1)
    store.touch(worker)
    return record


def retain_record(record, employer):
    record["record_state"] = "IMMUTABLE"
    store.touch(record)
    for disclosure in store.all_rows("consumer_disclosures"):
        if disclosure.get("covered_worker_id") != record.get("covered_worker_id"):
            continue
        if disclosure.get("disclosure_state") == "GENERATED":
            disclosure["disclosure_state"] = "SUPERSEDED"
            disclosure["held_record_count"] = (disclosure.get("held_record_count") or 0) + 1
            store.touch(disclosure)
    return record


# ------------------------------------------------------------------ sweeps

def dispute_escalation_sweep():
    for dispute in store.all_rows("record_disputes"):
        state = dispute.get("dispute_state")
        if state in OPEN_DISPUTE_STATES and clock.now() > dispute.get("response_due_date"):
            escalate_dispute(dispute)
        elif (state in ("RESOLVED_UPHELD", "RESOLVED_CORRECTED")
              and dispute.get("_closed") is None
              and clock.days_elapsed(dispute.get("resolved_at")) > DISPUTE_REOPEN_GRACE_DAYS):
            dispute["dispute_state"] = "CLOSED"
            store.touch(dispute)


def escalate_dispute(dispute):
    now = clock.now()
    dispute["dispute_state"] = "ESCALATED"
    dispute["_escalated_at"] = now
    store.touch(dispute)
    record = store.get("employment_records", dispute.get("employment_record_id"))
    if record is None:
        return dispute
    employer = store.get("employers", record.get("employer_id"))
    if employer is None:
        return dispute
    employer["feed_status"] = "DELAYED"
    for row in store.all_rows("employment_records"):
        if row.get("employer_id") != employer["id"]:
            continue
        if row.get("currency_state") == "CURRENT":
            row["currency_state"] = "STALE"
            store.touch(row)
    store.touch(employer)
    calculations.refresh_verifiers_for_employer(employer["id"])
    return dispute


def refresh_all_employer_feed_status():
    for employer in store.all_rows("employers"):
        calculations.refresh_employer_feed_status(employer)
        _cascade_currency(employer)


def _cascade_currency(employer):
    status = employer.get("feed_status")
    if status in ("DELAYED", "STALLED"):
        for record in store.all_rows("employment_records"):
            if record.get("employer_id") != employer["id"]:
                continue
            if record.get("currency_state") == "CURRENT":
                record["currency_state"] = "STALE"
                store.touch(record)
                _fallback_requests(record)
    elif status == "CURRENT":
        for record in store.all_rows("employment_records"):
            if record.get("employer_id") != employer["id"]:
                continue
            if record.get("currency_state") == "STALE":
                record["currency_state"] = "CURRENT"
                store.touch(record)


def _fallback_requests(record):
    for request in store.all_rows("verification_requests"):
        if request.get("request_state") != "VALIDATED":
            continue
        if request.get("current_employer_id") != record.get("employer_id"):
            continue
        request["request_state"] = "PERMITTED"
        request["records_matched_count"] = 0
        store.touch(request)
        verifier = store.get("verifiers", request.get("verifier_id"))
        if verifier is not None:
            verifier["transaction_count"] = max(0, (verifier.get("transaction_count") or 0) - 1)
            store.touch(verifier)