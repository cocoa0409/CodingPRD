"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    """An error carrying the catalogued error_id, message and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status

    def to_body(self):
        return {"error_id": self.error_id, "message": self.message}


# --- Authorization --------------------------------------------------------
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = (
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
ERR_INSUFFICIENT_PERMISSIONS = ("ERR_INSUFFICIENT_PERMISSIONS", 403)

# --- Not found ------------------------------------------------------------
ERR_REGION_NOT_FOUND = ("ERR_REGION_NOT_FOUND", 404)
ERR_MEMBER_NOT_FOUND = ("ERR_MEMBER_NOT_FOUND", 404)
ERR_CARE_SITE_NOT_FOUND = ("ERR_CARE_SITE_NOT_FOUND", 404)
ERR_DEPARTMENT_NOT_FOUND = ("ERR_DEPARTMENT_NOT_FOUND", 404)
ERR_PROVIDER_NOT_FOUND = ("ERR_PROVIDER_NOT_FOUND", 404)
ERR_NETWORK_SERVICE_NOT_FOUND = ("ERR_NETWORK_SERVICE_NOT_FOUND", 404)
ERR_APPOINTMENT_NOT_FOUND = ("ERR_APPOINTMENT_NOT_FOUND", 404)
ERR_REFERRAL_NOT_FOUND = ("ERR_REFERRAL_NOT_FOUND", 404)
ERR_OUTSIDE_CLAIM_NOT_FOUND = ("ERR_OUTSIDE_CLAIM_NOT_FOUND", 404)
ERR_REGIONAL_BUDGET_NOT_FOUND = ("ERR_REGIONAL_BUDGET_NOT_FOUND", 404)
ERR_CAPACITY_PLAN_NOT_FOUND = ("ERR_CAPACITY_PLAN_NOT_FOUND", 404)
ERR_MEMBER_TRANSFER_NOT_FOUND = ("ERR_MEMBER_TRANSFER_NOT_FOUND", 404)
ERR_QUALITY_METRIC_NOT_FOUND = ("ERR_QUALITY_METRIC_NOT_FOUND", 404)
ERR_ALERT_NOT_FOUND = ("ERR_ALERT_NOT_FOUND", 404)
ERR_REFERENTIAL_INTEGRATION_NOT_FOUND = (
    "ERR_REFERENTIAL_INTEGRATION_NOT_FOUND", 404)

ERR_REFERENCED_RESOURCE_NOT_FOUND = ("ERR_REFERENCED_RESOURCE_NOT_FOUND", 422)
ERR_CROSS_REGION_REFERENCE = ("ERR_CROSS_REGION_REFERENCE", 422)

# --- State ----------------------------------------------------------------
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_REFERRAL_NOT_DECIDABLE = ("ERR_REFERRAL_NOT_DECIDABLE", 409)
ERR_CLAIM_NOT_ADJUDICABLE = ("ERR_CLAIM_NOT_ADJUDICABLE", 409)
ERR_BUDGET_NOT_SUBMITTABLE = ("ERR_BUDGET_NOT_SUBMITTABLE", 409)
ERR_CAPACITY_PLAN_NOT_ACTIVATABLE = ("ERR_CAPACITY_PLAN_NOT_ACTIVATABLE", 409)
ERR_TRANSFER_NOT_COMPLETABLE = ("ERR_TRANSFER_NOT_COMPLETABLE", 409)
ERR_METRIC_NOT_FINALIZABLE = ("ERR_METRIC_NOT_FINALIZABLE", 409)

# --- Temporal -------------------------------------------------------------
ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED = (
    "ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED", 409)
ERR_REFERRAL_EXPIRED = ("ERR_REFERRAL_EXPIRED", 409)
ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED = (
    "ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED", 409)

# --- Network and coverage -------------------------------------------------
ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK = (
    "ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK", 409)
ERR_NO_IN_NETWORK_CAPACITY = ("ERR_NO_IN_NETWORK_CAPACITY", 409)
ERR_VOLUME_COMPONENT_NOT_PERMITTED = (
    "ERR_VOLUME_COMPONENT_NOT_PERMITTED", 422)
ERR_APPEAL_ROUNDS_EXHAUSTED = ("ERR_APPEAL_ROUNDS_EXHAUSTED", 409)
ERR_REFERRAL_NOT_AUTHORIZED = ("ERR_REFERRAL_NOT_AUTHORIZED", 409)
ERR_UNAUTHORIZED_NETWORK_EXPANSION = (
    "ERR_UNAUTHORIZED_NETWORK_EXPANSION", 409)
ERR_BUDGET_NOT_APPROVED = ("ERR_BUDGET_NOT_APPROVED", 409)
ERR_DUPLICATE_QUALITY_METRIC = ("ERR_DUPLICATE_QUALITY_METRIC", 409)
ERR_DUPLICATE_CAPACITY_PLAN = ("ERR_DUPLICATE_CAPACITY_PLAN", 409)
ERR_DUPLICATE_NETWORK_SERVICE = ("ERR_DUPLICATE_NETWORK_SERVICE", 409)
ERR_PROVIDER_SCHEDULE_OVERLAP = ("ERR_PROVIDER_SCHEDULE_OVERLAP", 409)

# --- Posture and capacity -------------------------------------------------
ERR_REGION_POSTURE_FROZEN = ("ERR_REGION_POSTURE_FROZEN", 409)
ERR_DEPARTMENT_CAPACITY_EXHAUSTED = ("ERR_DEPARTMENT_CAPACITY_EXHAUSTED", 409)
ERR_FTE_BUDGET_EXCEEDED = ("ERR_FTE_BUDGET_EXCEEDED", 409)
ERR_BUDGET_FISCAL_LINE_EXCEEDED = ("ERR_BUDGET_FISCAL_LINE_EXCEEDED", 402)

# --- Concurrency ----------------------------------------------------------
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


_MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER":
        "The X-User-ID and X-User-Role headers must both be present and valid.",
    "ERR_INSUFFICIENT_PERMISSIONS":
        "The acting role does not hold this operation.",
    "ERR_REFERENCED_RESOURCE_NOT_FOUND":
        "An identifier supplied in the request body does not resolve to a stored row.",
    "ERR_CROSS_REGION_REFERENCE":
        "The referenced rows do not share one region of record.",
    "ERR_INVALID_STATE":
        "The target row is not in a state from which this trigger is declared.",
    "ERR_REFERRAL_NOT_DECIDABLE":
        "A referral decision requires PENDING_TRIAGE or APPEALED status.",
    "ERR_CLAIM_NOT_ADJUDICABLE":
        "Adjudication requires SUBMITTED, PENDED or APPEALED claim status.",
    "ERR_BUDGET_NOT_SUBMITTABLE":
        "Submission requires a DRAFT or REOPENED budget.",
    "ERR_CAPACITY_PLAN_NOT_ACTIVATABLE":
        "Activation requires a capacity plan in UNDER_REVIEW status.",
    "ERR_TRANSFER_NOT_COMPLETABLE":
        "Completion requires a transfer in PENDING_EFFECTIVE status.",
    "ERR_METRIC_NOT_FINALIZABLE":
        "Finalization requires a metric in MEASURING or REOPENED status.",
    "ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED":
        "The referral triage window has closed.",
    "ERR_REFERRAL_EXPIRED":
        "The referral authorization has expired.",
    "ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED":
        "The transfer's effective instant has not been reached.",
    "ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK":
        "No in-network department satisfies this service under the network rules.",
    "ERR_NO_IN_NETWORK_CAPACITY":
        "No in-network department holds remaining budgeted supply.",
    "ERR_VOLUME_COMPONENT_NOT_PERMITTED":
        "Provider compensation may not carry a procedure-volume component.",
    "ERR_APPEAL_ROUNDS_EXHAUSTED":
        "The appeal-round maximum has been reached.",
    "ERR_REFERRAL_NOT_AUTHORIZED":
        "The named referral does not authorize this booking.",
    "ERR_UNAUTHORIZED_NETWORK_EXPANSION":
        "The external contract count exceeds the permitted maximum.",
    "ERR_BUDGET_NOT_APPROVED":
        "An APPROVED regional budget is required for this period.",
    "ERR_DUPLICATE_QUALITY_METRIC":
        "A metric already exists for this region, metric code and period.",
    "ERR_DUPLICATE_CAPACITY_PLAN":
        "A capacity plan already exists for this department and period.",
    "ERR_PROVIDER_SCHEDULE_OVERLAP":
        "The provider already holds an intersecting appointment.",
    "ERR_REGION_POSTURE_FROZEN":
        "The region's posture is FROZEN and refuses this mutation.",
    "ERR_DEPARTMENT_CAPACITY_EXHAUSTED":
        "The department's appointment supply is exhausted or closed.",
    "ERR_FTE_BUDGET_EXCEEDED":
        "Filled staffing would exceed the site's budgeted headcount.",
    "ERR_BUDGET_FISCAL_LINE_EXCEEDED":
        "The request would exceed an approved fiscal line.",
    "ERR_STALE_VERSION":
        "The supplied expected_member_version does not match the stored version.",
}


def message_for(error_id, fallback=""):
    if error_id in _MESSAGES:
        return _MESSAGES[error_id]
    return fallback or ("The request could not be completed (%s)." % error_id)


def raise_error(spec, message=None):
    error_id, status = spec
    raise ApiError(error_id, message or message_for(error_id), status)