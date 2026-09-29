"""Error catalogue for the Motor Carrier Operating Authority API (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else CATALOG[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> HTTP status, exactly as PRD section 5 lists them (34 codes).
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_CARRIER_OWNER": 403,
    "ERR_INSURER_NOT_FILING_PARTY": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_AUTHORITY_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_STALE_AUTHORITY_VERSION": 412,
    "ERR_APPLICATION_INVALID_STATE": 409,
    "ERR_AUTHORITY_INVALID_STATE": 409,
    "ERR_FILING_NOT_ACTIVE": 409,
    "ERR_PROCEEDING_NOT_OPEN": 409,
    "ERR_AUDIT_INVALID_STATE": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_SHIPMENT_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_FILING_INTERVAL_OVERLAP": 409,
    "ERR_DESIGNATION_INTERVAL_CONFLICT": 409,
    "ERR_HAZMAT_AUTHORITY_REQUIRED": 422,
    "ERR_PASSENGER_AUTHORITY_REQUIRED": 422,
    "ERR_WAITING_PERIOD_NOT_ELAPSED": 422,
    "ERR_PROCESS_AGENT_STATE_NOT_COVERED": 422,
    "ERR_INSURER_NOT_AUTHORIZED_IN_STATE": 422,
    "ERR_PROCESS_AGENT_NOT_DESIGNATED": 422,
    "ERR_PREDECESSOR_INVALID": 422,
    "ERR_PROCESS_AGENT_COVERAGE_INCOMPLETE": 422,
    "ERR_INSURANCE_NOT_ON_FILE": 422,
    "ERR_INSURANCE_BELOW_MINIMUM": 422,
    "ERR_BOND_FILING_REQUIRED": 422,
    "ERR_BIENNIAL_UPDATE_DELINQUENT": 422,
    "ERR_FILING_FEE_OUTSTANDING": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and X-User-Role must be present and non-empty.",
    "ERR_UNAUTHORIZED": "The acting role is not admitted by this endpoint.",
    "ERR_NOT_CARRIER_OWNER": "The acting carrier does not own the target resource.",
    "ERR_INSURER_NOT_FILING_PARTY": "The acting insurer is not the filing party.",
    "ERR_INVALID_REQUEST": "The request body is not structurally valid.",
    "ERR_CARRIER_NOT_FOUND": "No carrier with the given id.",
    "ERR_APPLICATION_NOT_FOUND": "No authority application with the given id.",
    "ERR_AUTHORITY_NOT_FOUND": "No operating authority with the given id.",
    "ERR_FILING_NOT_FOUND": "No insurance filing with the given id.",
    "ERR_REFERENCE_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_STALE_AUTHORITY_VERSION": "expected_authority_version does not match the authority's current version.",
    "ERR_APPLICATION_INVALID_STATE": "The application does not admit the requested trigger.",
    "ERR_AUTHORITY_INVALID_STATE": "The authority does not admit the requested trigger.",
    "ERR_FILING_NOT_ACTIVE": "The target insurance filing is not ACTIVE.",
    "ERR_PROCEEDING_NOT_OPEN": "The revocation proceeding is not open.",
    "ERR_AUDIT_INVALID_STATE": "The safety audit does not admit a result.",
    "ERR_CONTRACT_NOT_ACTIVE": "The customer contract is not ACTIVE.",
    "ERR_SHIPMENT_INVALID_STATE": "The shipment does not admit the requested trigger.",
    "ERR_SEGREGATION_OF_DUTIES": "The activating officer published this application.",
    "ERR_FILING_INTERVAL_OVERLAP": "The new filing collides with the incumbent filing on its coverage slot.",
    "ERR_DESIGNATION_INTERVAL_CONFLICT": "The requested designation interval conflicts with an existing designation.",
    "ERR_HAZMAT_AUTHORITY_REQUIRED": "The authority lacks the required hazardous-materials endorsement.",
    "ERR_PASSENGER_AUTHORITY_REQUIRED": "The commodity class does not match the authority's class.",
    "ERR_WAITING_PERIOD_NOT_ELAPSED": "The activation waiting period has not elapsed.",
    "ERR_PROCESS_AGENT_STATE_NOT_COVERED": "The process agent does not cover a requested state.",
    "ERR_INSURER_NOT_AUTHORIZED_IN_STATE": "The insurer is not admitted in the carrier's domicile state.",
    "ERR_PROCESS_AGENT_NOT_DESIGNATED": "An endpoint of the movement sits outside the designated states.",
    "ERR_PREDECESSOR_INVALID": "The predecessor authority is incompatible with the application kind.",
    "ERR_PROCESS_AGENT_COVERAGE_INCOMPLETE": "Process-agent coverage is incomplete.",
    "ERR_INSURANCE_NOT_ON_FILE": "Required insurance is not on file.",
    "ERR_INSURANCE_BELOW_MINIMUM": "Required coverage does not meet its minimum limit.",
    "ERR_BOND_FILING_REQUIRED": "A surety bond or trust fund filing is required.",
    "ERR_BIENNIAL_UPDATE_DELINQUENT": "The carrier is not current on its unified-registration obligations.",
    "ERR_FILING_FEE_OUTSTANDING": "The carrier has an outstanding filing-fee balance.",
}


def err(error_id, message=None):
    return ApiError(error_id, message)


def invalid(message="The request body is not structurally valid."):
    return ApiError("ERR_INVALID_REQUEST", message)
