"""Error catalog (scaffold section 1.6 / PRD section 5). Each entry maps the
error id to (HTTP status, default human-readable message)."""


class ApiError(Exception):
    """Domain error carrying the error_id and HTTP status for the envelope."""

    def __init__(self, error_id, message=None):
        if error_id not in ERROR_CATALOG:
            raise KeyError("unknown error id: %s" % error_id)
        http_status, default_message = ERROR_CATALOG[error_id]
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or default_message


ERROR_CATALOG = {
    # auth
    "ERR_UNAUTHENTICATED": (401, "X-User-Role or X-User-ID header missing, or role value unknown"),
    "ERR_UNAUTHORIZED": (403, "Role not permitted for this endpoint"),
    "ERR_FORBIDDEN_OWNERSHIP": (403, "Entity-backed role acting on a resource it does not own"),
    # schema
    "ERR_INVALID_REQUEST": (400, "Request body failed schema validation"),
    # existence
    "ERR_BUREAU_NOT_FOUND": (404, "Bureau does not exist"),
    "ERR_BUSINESS_NOT_FOUND": (404, "Business does not exist"),
    "ERR_CONSUMER_NOT_FOUND": (404, "Consumer does not exist"),
    "ERR_COMPLAINT_NOT_FOUND": (404, "Complaint does not exist"),
    "ERR_APPLICATION_NOT_FOUND": (404, "AccreditationApplication does not exist"),
    "ERR_INVOICE_NOT_FOUND": (404, "DuesInvoice does not exist"),
    "ERR_MEDIATION_NOT_FOUND": (404, "MediationCase does not exist"),
    "ERR_ARBITRATION_NOT_FOUND": (404, "ArbitrationCase does not exist"),
    "ERR_SNAPSHOT_NOT_FOUND": (404, "RatingSnapshot does not exist"),
    "ERR_DISPUTE_NOT_FOUND": (404, "RatingDispute does not exist"),
    "ERR_AD_REVIEW_NOT_FOUND": (404, "AdvertisingReview does not exist"),
    "ERR_SCAM_REPORT_NOT_FOUND": (404, "ScamReport does not exist"),
    # optimistic concurrency
    "ERR_STALE_VERSION": (412, "expected_business_version does not match the current Business version"),
    # referential integrity
    "ERR_TERRITORY_UNCOVERED": (422, "No bureau covers the business home_state_code"),
    "ERR_STATE_ALREADY_ASSIGNED": (409, "A state code is already assigned to another bureau"),
    "ERR_APPLICATION_ALREADY_ACTIVE": (409, "Business already has an application in DRAFT, SUBMITTED or APPROVED_PENDING_DUES"),
    "ERR_SNAPSHOT_BUSINESS_MISMATCH": (422, "snapshot_id or disputed_complaint_id does not belong to the disputing business"),
    # application state machine
    "ERR_APPLICATION_INVALID_STATE": (409, "Application is not in the required from-state"),
    "ERR_REAPPLICATION_COOLING": (409, "Fewer than 30 days since the denied application's decided_at"),
    "ERR_BUSINESS_TOO_YOUNG": (422, "Business is younger than 183 days at submit"),
    "ERR_ADVERTISING_REVIEW_ADVERSE": (422, "An advertising review of the business is UNDER_REVIEW or REFERRED_TO_REGULATOR"),
    "ERR_ADVERSE_COMPLAINT_HISTORY": (422, "Business has unanswered or unresolved complaints in the trailing window"),
    "ERR_OUTSTANDING_DUES_BALANCE": (422, "Business carries an overdue balance or a recently voided invoice"),
    # dues invoices
    "ERR_INVOICE_INVALID_STATE": (409, "Ledger entry against a VOID or REFUNDED invoice, or an undefined from-state"),
    "ERR_PAYMENT_EXCEEDS_BALANCE": (422, "PAYMENT amount_cents exceeds the outstanding balance"),
    "ERR_REFUND_EXCEEDS_PAID": (422, "REFUND amount_cents exceeds the net amount paid"),
    # complaints
    "ERR_COMPLAINT_INVALID_STATE": (409, "Complaint is not in the required from-state"),
    "ERR_RESPONSE_WINDOW_EXPIRED": (409, "Business response arrived after the response deadline"),
    "ERR_REBUTTAL_LIMIT_REACHED": (409, "Complaint already has 3 consumer rebuttals"),
    "ERR_REOPEN_WINDOW_EXPIRED": (409, "Reopen attempted more than 30 days after closed_at"),
    "ERR_MEDIATION_WINDOW_EXPIRED": (409, "Mediation offer attempted more than 14 days after last_unresolved_at"),
    # mediation / arbitration
    "ERR_MEDIATION_INVALID_STATE": (409, "Mediation action from a wrong state"),
    "ERR_MEDIATOR_SCHEDULE_CONFLICT": (409, "Mediator already has a SCHEDULED session intersecting the requested one"),
    "ERR_ARBITRATION_INVALID_STATE": (409, "Arbitration action from a wrong state"),
    "ERR_HEARING_ROOM_CONFLICT": (409, "Same-room hearing violates the 30-minute buffer rule"),
    # rating disputes
    "ERR_DISPUTE_WINDOW_EXPIRED": (409, "Rating dispute filed more than 10 days after the snapshot's published_at"),
    "ERR_DISPUTE_INVALID_STATE": (409, "Appeal decision on a dispute not in UNDER_APPEAL_REVIEW"),
    # advertising / scam
    "ERR_AD_REVIEW_INVALID_STATE": (409, "Conclude on an AdvertisingReview not in UNDER_REVIEW"),
    "ERR_SCAM_REPORT_INVALID_STATE": (409, "Publish on a ScamReport not in RECEIVED"),
}
