"""Error catalog and the exception every failure path raises.

The identifiers and their HTTP statuses come from the PRD's error catalogue
(§5) and the conditions that trigger them are stated in §2 and §3.
"""

# --- envelope / request ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_DUPLICATE_PARTICIPANT_NPI = "ERR_DUPLICATE_PARTICIPANT_NPI"

# --- auth ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"

# --- existence ---
ERR_PARTICIPANT_NOT_FOUND = "ERR_PARTICIPANT_NOT_FOUND"
ERR_PRESCRIPTION_NOT_FOUND = "ERR_PRESCRIPTION_NOT_FOUND"
ERR_ENDPOINT_NOT_FOUND = "ERR_ENDPOINT_NOT_FOUND"
ERR_ATTEMPT_NOT_FOUND = "ERR_ATTEMPT_NOT_FOUND"
ERR_PATIENT_NOT_FOUND = "ERR_PATIENT_NOT_FOUND"
ERR_CONSENT_NOT_FOUND = "ERR_CONSENT_NOT_FOUND"
ERR_SIGNING_SESSION_NOT_FOUND = "ERR_SIGNING_SESSION_NOT_FOUND"
ERR_BENEFIT_CHECK_NOT_FOUND = "ERR_BENEFIT_CHECK_NOT_FOUND"
ERR_FEE_ENTRY_NOT_FOUND = "ERR_FEE_ENTRY_NOT_FOUND"

# --- state ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_ROUTE_ATTEMPT_IN_PROGRESS = "ERR_ROUTE_ATTEMPT_IN_PROGRESS"
ERR_LAST_ACTIVE_ENDPOINT = "ERR_LAST_ACTIVE_ENDPOINT"
ERR_HISTORY_BATCH_IN_PROGRESS = "ERR_HISTORY_BATCH_IN_PROGRESS"

# --- concurrency ---
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_PARTICIPANT_STALE_VERSION = "ERR_PARTICIPANT_STALE_VERSION"

# --- safety ---
ERR_IDENTITY_PROOFING_REQUIRED = "ERR_IDENTITY_PROOFING_REQUIRED"
ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD = "ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD"
ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED = "ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED"
ERR_ACCOUNT_LOCKED = "ERR_ACCOUNT_LOCKED"
ERR_OTP_INVALID = "ERR_OTP_INVALID"
ERR_CRITICAL_ORDER_DELIVERY_REQUIRED = "ERR_CRITICAL_ORDER_DELIVERY_REQUIRED"

# --- certification ---
ERR_CERT_TESTS_INCOMPLETE = "ERR_CERT_TESTS_INCOMPLETE"
ERR_CERT_TEST_PREREQUISITE = "ERR_CERT_TEST_PREREQUISITE"
ERR_UNKNOWN_TEST_CODE = "ERR_UNKNOWN_TEST_CODE"
ERR_CERT_NO_ENDPOINT = "ERR_CERT_NO_ENDPOINT"

# --- routing / directory ---
ERR_NO_ROUTE_AVAILABLE = "ERR_NO_ROUTE_AVAILABLE"
ERR_MESSAGE_STANDARD_MISMATCH = "ERR_MESSAGE_STANDARD_MISMATCH"
ERR_FALLBACK_HOP_LIMIT_EXCEEDED = "ERR_FALLBACK_HOP_LIMIT_EXCEEDED"
ERR_FALLBACK_NOT_PERMITTED = "ERR_FALLBACK_NOT_PERMITTED"
ERR_FALLBACK_CHANNEL_UNAVAILABLE = "ERR_FALLBACK_CHANNEL_UNAVAILABLE"
ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK = "ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK"
ERR_ENDPOINT_OUT_OF_SERVICE_WINDOW = "ERR_ENDPOINT_OUT_OF_SERVICE_WINDOW"
ERR_ENDPOINT_INTERVAL_OVERLAP = "ERR_ENDPOINT_INTERVAL_OVERLAP"
ERR_ENDPOINT_NOT_STABLE = "ERR_ENDPOINT_NOT_STABLE"
ERR_ENDPOINT_NOT_ROUTED_ATTEMPT = "ERR_ENDPOINT_NOT_ROUTED_ATTEMPT"
ERR_ENDPOINT_COVERAGE_WARNING = "ERR_ENDPOINT_COVERAGE_WARNING"
ERR_ATTEMPT_PRESCRIPTION_MISMATCH = "ERR_ATTEMPT_PRESCRIPTION_MISMATCH"

# --- consent / history ---
ERR_CONSENT_REQUIRED = "ERR_CONSENT_REQUIRED"
ERR_CONSENT_EXPIRED = "ERR_CONSENT_EXPIRED"
ERR_CONSENT_INTERVAL_OVERLAP = "ERR_CONSENT_INTERVAL_OVERLAP"
ERR_CONSENT_STALE = "ERR_CONSENT_STALE"
ERR_HISTORY_SOURCE_UNCERTIFIED = "ERR_HISTORY_SOURCE_UNCERTIFIED"

# --- fiscal ---
ERR_ENTRY_NOT_REVERSIBLE = "ERR_ENTRY_NOT_REVERSIBLE"

# Human-readable text per error. Tests only assert the identifier and the
# status, but the envelope requires a non-empty message.
MESSAGES = {
    ERR_INVALID_REQUEST: "The request body is malformed or carries an unrecognised field or enum member.",
    ERR_DUPLICATE_PARTICIPANT_NPI: "A participant with the same participant_type and npi pair already exists.",
    ERR_UNAUTHENTICATED: "The X-User-Role header is absent or names an undeclared role.",
    ERR_FORBIDDEN_ROLE: "The acting role is not permitted for this operation.",
    ERR_PARTICIPANT_NOT_FOUND: "The referenced network participant does not exist.",
    ERR_PRESCRIPTION_NOT_FOUND: "The referenced prescription does not exist.",
    ERR_ENDPOINT_NOT_FOUND: "The referenced directory endpoint does not exist.",
    ERR_ATTEMPT_NOT_FOUND: "The referenced routing attempt does not exist.",
    ERR_PATIENT_NOT_FOUND: "The referenced patient does not exist.",
    ERR_CONSENT_NOT_FOUND: "The referenced consent record does not exist.",
    ERR_SIGNING_SESSION_NOT_FOUND: "The referenced signing session does not exist.",
    ERR_BENEFIT_CHECK_NOT_FOUND: "The referenced benefit check does not exist.",
    ERR_FEE_ENTRY_NOT_FOUND: "The referenced transaction fee entry does not exist.",
    ERR_INVALID_STATE: "The resource is not in a state that admits the requested operation.",
    ERR_ALREADY_TERMINAL: "The resource is already in a terminal state for this machine.",
    ERR_ROUTE_ATTEMPT_IN_PROGRESS: "The prescription already has a routing attempt in flight.",
    ERR_LAST_ACTIVE_ENDPOINT: "Disabling this endpoint would leave the participant with no ACTIVE endpoint for the service set.",
    ERR_HISTORY_BATCH_IN_PROGRESS: "The patient already holds a medication history batch that is aggregating.",
    ERR_STALE_VERSION: "expected_prescription_version does not match the prescription's current version.",
    ERR_PARTICIPANT_STALE_VERSION: "expected_participant_version does not match the participant's current version.",
    ERR_IDENTITY_PROOFING_REQUIRED: "Identity proofing and two-factor authentication must both have passed on an OPEN session.",
    ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD: "The message standard does not support the controlled schedule.",
    ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED: "The receiving pharmacy holds no ACTIVE NEW_RX endpoint for a controlled order.",
    ERR_ACCOUNT_LOCKED: "The signing session is locked after three failed challenge attempts.",
    ERR_OTP_INVALID: "The supplied otp_code does not match the session's current challenge code.",
    ERR_CRITICAL_ORDER_DELIVERY_REQUIRED: "A CRITICAL order must reach a delivery outcome before it may be cancelled.",
    ERR_CERT_TESTS_INCOMPLETE: "The certification test set is incomplete.",
    ERR_CERT_TEST_PREREQUISITE: "A conditional certification test's prerequisite has not been passed.",
    ERR_UNKNOWN_TEST_CODE: "The supplied test_code is not one of the declared certification tests.",
    ERR_CERT_NO_ENDPOINT: "The participant holds no directory endpoint to certify.",
    ERR_NO_ROUTE_AVAILABLE: "No directory endpoint satisfies the routing selector.",
    ERR_MESSAGE_STANDARD_MISMATCH: "The selected endpoint's message standard differs from the prescription's.",
    ERR_FALLBACK_HOP_LIMIT_EXCEEDED: "The prescription already carries three non-network routing attempts.",
    ERR_FALLBACK_NOT_PERMITTED: "The failure code requires a fallback channel and none is provisioned.",
    ERR_FALLBACK_CHANNEL_UNAVAILABLE: "The fallback channel is FAX but no fax number is provisioned.",
    ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK: "The prescription carries no UNDELIVERABLE or REJECTED attempt.",
    ERR_ENDPOINT_OUT_OF_SERVICE_WINDOW: "The logical clock sits outside the endpoint's service interval.",
    ERR_ENDPOINT_INTERVAL_OVERLAP: "The endpoint's interval overlaps an existing endpoint's interval.",
    ERR_ENDPOINT_NOT_STABLE: "The endpoint's chronological reliability ratio is below 0.95.",
    ERR_ENDPOINT_NOT_ROUTED_ATTEMPT: "The reported attempt's target endpoint is not this endpoint.",
    ERR_ENDPOINT_COVERAGE_WARNING: "The degrade would push the participant's ACTIVE-endpoint share below one half.",
    ERR_ATTEMPT_PRESCRIPTION_MISMATCH: "The reported attempt does not belong to the named prescription.",
    ERR_CONSENT_REQUIRED: "No ACTIVE consent with the required scope exists for the patient.",
    ERR_CONSENT_EXPIRED: "The consent's validity interval has already elapsed.",
    ERR_CONSENT_INTERVAL_OVERLAP: "The new consent window overlaps an existing ACTIVE window for the same scope.",
    ERR_CONSENT_STALE: "The patient's consent_version advanced past the batch's snapshot during aggregation.",
    ERR_HISTORY_SOURCE_UNCERTIFIED: "The reporting participant is not CERTIFIED.",
    ERR_ENTRY_NOT_REVERSIBLE: "The fee entry is not a POSTED, unreversed ordinary charge.",
}

# HTTP status per error identifier (PRD §5).
HTTP_STATUS = {
    ERR_INVALID_REQUEST: 400,
    ERR_DUPLICATE_PARTICIPANT_NPI: 409,
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_PARTICIPANT_NOT_FOUND: 404,
    ERR_PRESCRIPTION_NOT_FOUND: 404,
    ERR_ENDPOINT_NOT_FOUND: 404,
    ERR_ATTEMPT_NOT_FOUND: 404,
    ERR_PATIENT_NOT_FOUND: 404,
    ERR_CONSENT_NOT_FOUND: 404,
    ERR_SIGNING_SESSION_NOT_FOUND: 404,
    ERR_BENEFIT_CHECK_NOT_FOUND: 404,
    ERR_FEE_ENTRY_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_ALREADY_TERMINAL: 409,
    ERR_ROUTE_ATTEMPT_IN_PROGRESS: 409,
    ERR_LAST_ACTIVE_ENDPOINT: 409,
    ERR_HISTORY_BATCH_IN_PROGRESS: 409,
    ERR_STALE_VERSION: 412,
    ERR_PARTICIPANT_STALE_VERSION: 412,
    ERR_IDENTITY_PROOFING_REQUIRED: 422,
    ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD: 422,
    ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED: 422,
    ERR_ACCOUNT_LOCKED: 423,
    ERR_OTP_INVALID: 422,
    ERR_CRITICAL_ORDER_DELIVERY_REQUIRED: 422,
    ERR_CERT_TESTS_INCOMPLETE: 422,
    ERR_CERT_TEST_PREREQUISITE: 422,
    ERR_UNKNOWN_TEST_CODE: 422,
    ERR_CERT_NO_ENDPOINT: 422,
    ERR_NO_ROUTE_AVAILABLE: 422,
    ERR_MESSAGE_STANDARD_MISMATCH: 422,
    ERR_FALLBACK_HOP_LIMIT_EXCEEDED: 422,
    ERR_FALLBACK_NOT_PERMITTED: 422,
    ERR_FALLBACK_CHANNEL_UNAVAILABLE: 422,
    ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK: 422,
    ERR_ENDPOINT_OUT_OF_SERVICE_WINDOW: 422,
    ERR_ENDPOINT_INTERVAL_OVERLAP: 422,
    ERR_ENDPOINT_NOT_STABLE: 422,
    ERR_ENDPOINT_NOT_ROUTED_ATTEMPT: 422,
    ERR_ENDPOINT_COVERAGE_WARNING: 422,
    ERR_ATTEMPT_PRESCRIPTION_MISMATCH: 422,
    ERR_CONSENT_REQUIRED: 422,
    ERR_CONSENT_EXPIRED: 422,
    ERR_CONSENT_INTERVAL_OVERLAP: 422,
    ERR_CONSENT_STALE: 409,
    ERR_HISTORY_SOURCE_UNCERTIFIED: 422,
    ERR_ENTRY_NOT_REVERSIBLE: 422,
}


class ApiError(Exception):
    """Carries the error identifier, the human message and the HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)