"""Error catalogue for the Rheumatology Biologic Coordination API.

Error ids and their HTTP status codes are taken verbatim from PRD section 5
(Error Code Catalogue) and cross-checked against SCAFFOLD.yaml `errors`.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_EPISODE_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_CHAIR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_PATIENT_VERSION": 412,
    "ERR_STALE_EPISODE_VERSION": 412,
    "ERR_VISIT_NOT_CHECKED_IN": 409,
    "ERR_AUTHORIZATION_STATE_INVALID": 409,
    "ERR_APPEAL_ROUNDS_EXHAUSTED": 409,
    "ERR_EPISODE_NOT_PLANNED": 409,
    "ERR_EPISODE_NOT_ACTIVE": 409,
    "ERR_EPISODE_NOT_HELD": 409,
    "ERR_APPOINTMENT_STATE_INVALID": 409,
    "ERR_ENROLLMENT_STATE_INVALID": 409,
    "ERR_FUNDING_NOT_AUTHORIZED": 409,
    "ERR_CHAIR_CLOSED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW": 409,
    "ERR_WASHOUT_PERIOD_NOT_ELAPSED": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_CHAIR_TIME_CONFLICT": 409,
    "ERR_CLINICIAN_CAPACITY_EXCEEDED": 409,
    "ERR_AUTHORIZATION_UNITS_EXHAUSTED": 409,
    "ERR_TB_SCREEN_NOT_CLEARED": 422,
    "ERR_HBV_ACTIVE_INFECTION_CONTRAINDICATED": 422,
    "ERR_HBV_SCREEN_INCOMPLETE": 422,
    "ERR_MONITORING_LAB_OVERDUE": 422,
    "ERR_SELF_INJECTION_TRAINING_INCOMPLETE": 422,
    "ERR_ACUTE_PHASE_REACTANT_MISSING": 422,
    "ERR_RESUMPTION_PROTOCOL_INCOMPLETE": 422,
    "ERR_STEP_THERAPY_NOT_SATISFIED": 422,
    "ERR_FORMULARY_EXCEPTION_NOT_ATTESTED": 422,
    "ERR_NO_BENEFIT_CHANNEL_AVAILABLE": 422,
    "ERR_PRIOR_EPISODE_INVALID": 422,
    "ERR_SITE_OF_CARE_MISMATCH": 422,
    "ERR_REGISTRY_CONSENT_MISSING": 422,
    "ERR_QUALITY_PERIOD_NO_VISITS": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST": (
        "The acting clinician may not sign a formulary exception."
    ),
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the addressed resource.",
    "ERR_PATIENT_NOT_FOUND": "The requested patient does not exist.",
    "ERR_VISIT_NOT_FOUND": "The requested visit does not exist.",
    "ERR_EPISODE_NOT_FOUND": "The requested therapy episode does not exist.",
    "ERR_AUTHORIZATION_NOT_FOUND": "The requested authorization does not exist.",
    "ERR_APPOINTMENT_NOT_FOUND": "The requested infusion appointment does not exist.",
    "ERR_ENROLLMENT_NOT_FOUND": "The requested assistance enrollment does not exist.",
    "ERR_CHAIR_NOT_FOUND": "The requested infusion chair does not exist.",
    "ERR_REFERENCE_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_STALE_PATIENT_VERSION": "The supplied patient version is stale.",
    "ERR_STALE_EPISODE_VERSION": "The supplied therapy episode version is stale.",
    "ERR_VISIT_NOT_CHECKED_IN": "The visit is not in the required status.",
    "ERR_AUTHORIZATION_STATE_INVALID": "The authorization is not in a permitted status.",
    "ERR_APPEAL_ROUNDS_EXHAUSTED": "The permitted appeal rounds are exhausted.",
    "ERR_EPISODE_NOT_PLANNED": "The therapy episode is not PLANNED.",
    "ERR_EPISODE_NOT_ACTIVE": "The therapy episode is not ACTIVE.",
    "ERR_EPISODE_NOT_HELD": "The therapy episode is not HELD.",
    "ERR_APPOINTMENT_STATE_INVALID": "The appointment is not in a permitted status.",
    "ERR_ENROLLMENT_STATE_INVALID": "The enrollment is not in a permitted status.",
    "ERR_FUNDING_NOT_AUTHORIZED": "The therapy episode funding state is not AUTHORIZED.",
    "ERR_CHAIR_CLOSED": "The infusion chair is CLOSED.",
    "ERR_SEGREGATION_OF_DUTIES": (
        "The attesting counselor may not be the submitting counselor."
    ),
    "ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW": (
        "The requested start falls outside every approved coverage window."
    ),
    "ERR_WASHOUT_PERIOD_NOT_ELAPSED": "The washout period has not elapsed.",
    "ERR_DUPLICATE_IDENTIFIER": "A natural key collides within its own collection.",
    "ERR_CHAIR_TIME_CONFLICT": "The requested chair occupancy conflicts with an existing one.",
    "ERR_CLINICIAN_CAPACITY_EXCEEDED": "The clinician concurrent-visit cap is exceeded.",
    "ERR_AUTHORIZATION_UNITS_EXHAUSTED": "No approved authorization has a unit left to reserve.",
    "ERR_TB_SCREEN_NOT_CLEARED": "The tuberculosis screen is not cleared.",
    "ERR_HBV_ACTIVE_INFECTION_CONTRAINDICATED": (
        "Active hepatitis B infection contraindicates this therapy."
    ),
    "ERR_HBV_SCREEN_INCOMPLETE": "The hepatitis B posture is incomplete.",
    "ERR_MONITORING_LAB_OVERDUE": "The episode's monitoring is overdue.",
    "ERR_SELF_INJECTION_TRAINING_INCOMPLETE": "Self-injection training has not passed.",
    "ERR_ACUTE_PHASE_REACTANT_MISSING": "The acute-phase reactant value is required.",
    "ERR_RESUMPTION_PROTOCOL_INCOMPLETE": "The resumption protocol is not satisfied.",
    "ERR_STEP_THERAPY_NOT_SATISFIED": "Step therapy is not satisfied.",
    "ERR_FORMULARY_EXCEPTION_NOT_ATTESTED": "The formulary exception has not been signed.",
    "ERR_NO_BENEFIT_CHANNEL_AVAILABLE": "The plan funds neither channel this drug can use.",
    "ERR_PRIOR_EPISODE_INVALID": "The named prior episode is not a valid predecessor.",
    "ERR_SITE_OF_CARE_MISMATCH": "The chair's site type does not match the episode's site of care.",
    "ERR_REGISTRY_CONSENT_MISSING": "The patient has not consented to registry participation.",
    "ERR_QUALITY_PERIOD_NO_VISITS": "The reporting window contains no qualifying visit.",
}


class ApiError(Exception):
    """A rejection carrying an error id, a human message and an HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
