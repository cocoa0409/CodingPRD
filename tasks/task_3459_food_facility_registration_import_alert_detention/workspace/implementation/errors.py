"""Error type and the canonical error-id catalog (SCAFFOLD section 1.6)."""


MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID or X-User-Role header missing, or the role is not one of the seven declared roles",
    "ERR_FORBIDDEN": "Caller role is not authorized for this operation",
    "ERR_OWNERSHIP_VIOLATION": "Caller is not the owning principal of the target resource",
    "ERR_SEGREGATION_OF_DUTIES": "The petition adjudicator must differ from the alert's creator",
    "ERR_FACILITY_NOT_FOUND": "Facility id does not resolve",
    "ERR_IMPORTER_NOT_FOUND": "ImporterFirm id does not resolve",
    "ERR_PRIOR_NOTICE_NOT_FOUND": "PriorNotice id does not resolve",
    "ERR_ENTRY_NOT_FOUND": "ImportEntry id does not resolve",
    "ERR_SAMPLE_NOT_FOUND": "SampleAnalysis id does not resolve",
    "ERR_IMPORT_ALERT_NOT_FOUND": "ImportAlert id does not resolve",
    "ERR_ALERT_PETITION_NOT_FOUND": "AlertPetition id does not resolve",
    "ERR_INSPECTION_NOT_FOUND": "Inspection id does not resolve",
    "ERR_RECALL_NOT_FOUND": "Recall id does not resolve",
    "ERR_LAB_NOT_FOUND": "lab_code names no existing Laboratory",
    "ERR_INVALID_REQUEST": "Request is malformed: missing required field, invalid enum value, range violation, inconsistent alert scope fields, or a non-forward clock set",
    "ERR_DUPLICATE_UFI": "ufi already registered on another facility",
    "ERR_DUPLICATE_ACCOUNT_CODE": "Importer account_code already in use",
    "ERR_DUPLICATE_LAB_CODE": "lab_code already in use",
    "ERR_FACILITY_NOT_RENEWABLE": "Facility is not in a renewable registration status",
    "ERR_PN_NOT_CONFIRMED": "Prior notice is not in CONFIRMED status",
    "ERR_IMPORTER_REVOKED": "Importer standing is REVOKED",
    "ERR_ENTRY_INVALID_STATE": "Entry action violates the review_status / disposition_status guards",
    "ERR_IMPORT_ALERT_NOT_ACTIVE": "Import alert is not ACTIVE",
    "ERR_PETITION_NOT_REVIEWABLE": "Petition is not in EVIDENCE_REVIEW status",
    "ERR_INSPECTION_NOT_OPEN": "Inspection is not in SCHEDULED status",
    "ERR_RECALL_INVALID_STATE": "Recall is not in the state this operation requires",
    "ERR_LAB_CAPACITY_EXCEEDED": "Laboratory daily aggregate sample capacity would be exceeded",
    "ERR_INSPECTION_SCHEDULE_OVERLAP": "Inspector already holds an overlapping SCHEDULED inspection",
    "ERR_REGISTRATION_NOT_ACTIVE": "Facility registration_status is not REGISTERED",
    "ERR_ACTIVE_RECALL_BLOCKS_ENTRY": "A CLASS_I CLASSIFIED recall blocks entry creation for this facility and product code",
    "ERR_NOTICE_TOO_LATE": "Prior-notice lead time is below the applicable minimum",
    "ERR_NOTICE_TOO_EARLY": "Prior-notice lead time exceeds 720 hours",
    "ERR_RENEWAL_WINDOW_CLOSED": "Renewal attempted outside [expires_at - 90 days, expires_at + 30 days]",
    "ERR_DETENTION_RESPONSE_DEADLINE_PASSED": "The detention response deadline has passed",
    "ERR_SAMPLE_DATE_PAST": "analysis_date falls before the current logical UTC date",
    "ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY": "Inspection target facility must be FOREIGN",
    "ERR_ALERT_SCOPE_MISMATCH": "Petition filer is outside the alert scope",
    "ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS": "Consecutive compliant streak below 3 or evidence_links empty",
    "ERR_UNITS_ACCOUNTING_MISMATCH": "Reported units do not reconcile with the conserved totals",
    "ERR_EFFECTIVENESS_THRESHOLD_NOT_MET": "Recall effectiveness/contact thresholds are not met for its classification",
    "ERR_STALE_VERSION": "Expected version does not match the parent resource's current version",
}

HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_IMPORTER_NOT_FOUND": 404,
    "ERR_PRIOR_NOTICE_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_IMPORT_ALERT_NOT_FOUND": 404,
    "ERR_ALERT_PETITION_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_RECALL_NOT_FOUND": 404,
    "ERR_LAB_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_UFI": 409,
    "ERR_DUPLICATE_ACCOUNT_CODE": 409,
    "ERR_DUPLICATE_LAB_CODE": 409,
    "ERR_FACILITY_NOT_RENEWABLE": 409,
    "ERR_PN_NOT_CONFIRMED": 409,
    "ERR_IMPORTER_REVOKED": 409,
    "ERR_ENTRY_INVALID_STATE": 409,
    "ERR_IMPORT_ALERT_NOT_ACTIVE": 409,
    "ERR_PETITION_NOT_REVIEWABLE": 409,
    "ERR_INSPECTION_NOT_OPEN": 409,
    "ERR_RECALL_INVALID_STATE": 409,
    "ERR_LAB_CAPACITY_EXCEEDED": 409,
    "ERR_INSPECTION_SCHEDULE_OVERLAP": 409,
    "ERR_REGISTRATION_NOT_ACTIVE": 422,
    "ERR_ACTIVE_RECALL_BLOCKS_ENTRY": 422,
    "ERR_NOTICE_TOO_LATE": 422,
    "ERR_NOTICE_TOO_EARLY": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 422,
    "ERR_DETENTION_RESPONSE_DEADLINE_PASSED": 422,
    "ERR_SAMPLE_DATE_PAST": 422,
    "ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY": 422,
    "ERR_ALERT_SCOPE_MISMATCH": 422,
    "ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS": 422,
    "ERR_UNITS_ACCOUNTING_MISMATCH": 422,
    "ERR_EFFECTIVENESS_THRESHOLD_NOT_MET": 422,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    """Carries an error_id, HTTP status, and human-readable message."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = HTTP_STATUS[error_id]
        self.message = message or MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


def raise_err(error_id, message=None):
    raise ApiError(error_id, message)
