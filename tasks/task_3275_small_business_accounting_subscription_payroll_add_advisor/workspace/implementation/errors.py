"""Error model + response envelope helpers."""
import secrets
import string
from flask import jsonify
import db


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _rid():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _rid(),
        "api_request_timestamp": db.fmt(db.now()),
    }


def ok(data, response_type="object", status=200, meta_extra=None):
    meta = _meta()
    if meta_extra:
        meta.update(meta_extra)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# Common error shortcuts
def missing_header():
    raise ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400,
                   "X-User-Role or X-User-ID header missing or malformed")


def forbidden_role():
    raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted for this endpoint")


def identity_mismatch(msg="Identity mismatch"):
    raise ApiError("ERR_IDENTITY_MISMATCH", 403, msg)


def not_found(msg="Not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Malformed body or missing field"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_enum(field, value):
    raise ApiError("ERR_INVALID_ENUM", 400, f"Invalid enum for {field}: {value}")


def invalid_state(msg="Invalid state transition"):
    raise ApiError("ERR_INVALID_STATE_TRANSITION", 400, msg)


def stale_version():
    raise ApiError("ERR_STALE_VERSION", 412, "Expected version does not match current version")


def not_writable():
    raise ApiError("ERR_SUBSCRIPTION_NOT_WRITABLE", 400,
                   "Subscription lifecycle blocks writes")


def feature_gated():
    raise ApiError("ERR_FEATURE_NOT_IN_TIER", 400, "Feature not included in current plan tier")


def seat_limit():
    raise ApiError("ERR_SEAT_LIMIT_REACHED", 400, "Seat limit would be exceeded")


def needs_primary_admin():
    raise ApiError("ERR_REQUIRES_PRIMARY_ADMIN", 403, "Operation requires PRIMARY_ADMIN")


def trial_expired():
    raise ApiError("ERR_TRIAL_EXPIRED", 400, "Trial expired with no payment method")


def reactivation_expired():
    raise ApiError("ERR_REACTIVATION_WINDOW_EXPIRED", 400, "Reactivation window expired")


def payroll_already_active():
    raise ApiError("ERR_PAYROLL_ALREADY_ACTIVE", 409, "Payroll add-on already active")


def payroll_not_active():
    raise ApiError("ERR_PAYROLL_NOT_ACTIVE", 400, "Payroll add-on not ACTIVE")


def payroll_cancel_blocked():
    raise ApiError("ERR_PAYROLL_CANCEL_BLOCKED_BY_FILING", 400,
                   "Full-service filing in flight")


def employee_terminated():
    raise ApiError("ERR_EMPLOYEE_ALREADY_TERMINATED", 400, "Employee already terminated")


def invoice_not_payable():
    raise ApiError("ERR_INVOICE_NOT_PAYABLE", 400, "Invoice not in a payable state")


def billing_blocked():
    raise ApiError("ERR_BILLING_STATE_BLOCKED", 400, "Blocked by outstanding billing state")


def transfer_pending():
    raise ApiError("ERR_TRANSFER_ALREADY_PENDING", 409, "Transfer already pending")


def transfer_expired():
    raise ApiError("ERR_TRANSFER_EXPIRED", 400, "Transfer expired")


def firm_not_active():
    raise ApiError("ERR_FIRM_NOT_ACTIVE", 400, "Firm not ACTIVE")


def conn_not_authorizable():
    raise ApiError("ERR_CONNECTION_NOT_AUTHORIZABLE", 400,
                   "Connection not authorizable from current state")


def consent_expired():
    raise ApiError("ERR_CONSENT_EXPIRED", 400, "Consent expired")


def conn_already_exists():
    raise ApiError("ERR_CONNECTION_ALREADY_EXISTS", 409,
                   "Connection with same institution/mask already exists")


def txn_locked():
    raise ApiError("ERR_TXN_LOCKED_BY_RECONCILIATION", 400,
                   "Transaction locked by reconciliation")


def recon_overlap():
    raise ApiError("ERR_STATEMENT_WINDOW_OVERLAP", 409, "Statement window overlap")


def recon_not_zero():
    raise ApiError("ERR_RECON_DIFFERENCE_NOT_ZERO", 400, "Difference not zero")


def rule_not_pausable():
    raise ApiError("ERR_RULE_NOT_PAUSABLE", 400, "Rule not pausable")


def rule_not_resumable():
    raise ApiError("ERR_RULE_NOT_RESUMABLE", 400, "Rule not resumable")


def integration_not_active():
    raise ApiError("ERR_INTEGRATION_NOT_ACTIVE", 400, "Integration not ACTIVE")


def integration_resume_blocked():
    raise ApiError("ERR_INTEGRATION_RESUME_BLOCKED", 400, "Conflicts still open")


def conflict_not_open():
    raise ApiError("ERR_CONFLICT_NOT_OPEN", 400, "Conflict not OPEN")


def migration_in_flight():
    raise ApiError("ERR_MIGRATION_ALREADY_IN_FLIGHT", 409, "Migration already in flight")


def migration_not_cancellable():
    raise ApiError("ERR_MIGRATION_NOT_CANCELLABLE", 400, "Migration not cancellable")


def grant_not_acceptable():
    raise ApiError("ERR_GRANT_NOT_ACCEPTABLE", 400, "Grant not acceptable")


def grant_not_revocable():
    raise ApiError("ERR_GRANT_NOT_REVOCABLE", 400, "Grant in terminal state")


def duplicate_active_grant():
    raise ApiError("ERR_DUPLICATE_ACTIVE_GRANT", 409, "Active grant already exists")


def export_not_downloadable():
    raise ApiError("ERR_EXPORT_NOT_DOWNLOADABLE", 400, "Export not downloadable")


def export_requires_primary():
    raise ApiError("ERR_EXPORT_SCOPE_REQUIRES_PRIMARY_ADMIN", 403,
                   "FULL_LEDGER scope requires PRIMARY_ADMIN")


def duplicate(msg="Duplicate"):
    raise ApiError("ERR_DUPLICATE", 409, msg)


def window_expired():
    raise ApiError("ERR_WINDOW_EXPIRED", 400, "Window expired")


def company_read_only():
    raise ApiError("ERR_COMPANY_READ_ONLY", 400, "Company is READ_ONLY")
