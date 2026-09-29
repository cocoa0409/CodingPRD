"""Error catalogue and the ApiError exception.

Every error_id / HTTP status pair below is transcribed from PRD.md section 5
(Error Code Catalogue).  Two extra ids marked EXTRA cover source-state
conflicts the PRD narrative requires but does not name in its catalogue
(recording a verdict on an already-resulted HealthTest, and deciding an
already-decided MatingRecommendation); both use HTTP 409 like every other
source-state conflict in this domain.
"""

ERROR_HTTP = {
    # ---- request shape ----
    "ERR_VALIDATION": 400,
    "ERR_USER_ID_REQUIRED": 400,
    # ---- auth ----
    "ERR_UNAUTHORIZED": 403,
    "ERR_DISTRIBUTOR_SCOPE": 403,
    "ERR_FACILITY_SCOPE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CERTIFIER_TESTED_SIRE": 403,
    # ---- not found ----
    "ERR_RESOURCE_NOT_FOUND": 404,
    # ---- uniqueness ----
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_PENDING_TEST": 409,
    # ---- optimistic concurrency ----
    "ERR_STALE_SIRE_VERSION": 412,
    "ERR_STALE_STRAW_LOT_VERSION": 412,
    # ---- state ----
    "ERR_SIRE_ACQUISITION_STATE": 409,
    "ERR_SIRE_COLLECTION_STATE": 409,
    "ERR_FACILITY_SUSPENDED": 409,
    "ERR_BOOKING_STATE": 409,
    "ERR_EJACULATE_STATE": 409,
    "ERR_LOT_STATE": 409,
    "ERR_LOT_NOT_RELEASED": 409,
    "ERR_EVALUATION_STATE": 409,
    "ERR_CERTIFICATE_STATE": 409,
    "ERR_TRANSFER_STATE": 409,
    "ERR_TANK_OUT_OF_SERVICE": 409,
    "ERR_HEALTH_TEST_STATE": 409,          # EXTRA (see module docstring)
    "ERR_RECOMMENDATION_STATE": 409,       # EXTRA (see module docstring)
    # ---- business safety / regulatory ----
    "ERR_ISOLATION_INCOMPLETE": 422,
    "ERR_HEALTH_TESTS_NOT_CURRENT": 422,
    "ERR_COUNTRY_TEST_MISSING": 422,
    "ERR_QC_BELOW_THRESHOLD": 422,
    # ---- business referential ----
    "ERR_SIRE_NOT_AT_FACILITY": 422,
    "ERR_TANK_NOT_OWNED_BY_DISTRIBUTOR": 422,
    "ERR_CERTIFICATE_NOT_APPLICABLE": 422,
    "ERR_LOT_SIRE_MISMATCH": 422,
    "ERR_INVALID_RETEST_TARGET": 422,
    "ERR_PEDIGREE_CYCLE": 422,
    # ---- business temporal ----
    "ERR_SIRE_REST_BUFFER": 422,
    "ERR_CLOCK_REWIND": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_BOOKING_NOT_STARTED": 422,
    "ERR_SAMPLE_DATE_FUTURE": 422,
    # ---- business constraint / capacity ----
    "ERR_FACILITY_AT_CAPACITY": 422,
    "ERR_BENCH_CAPACITY_EXCEEDED": 422,
    "ERR_DOSE_CAP_EXCEEDED": 422,
    "ERR_INSUFFICIENT_DOSES": 422,
    "ERR_TANK_CAPACITY_EXCEEDED": 422,
    "ERR_PRODUCT_LINE_FIELDS": 422,
    "ERR_DESTINATION_NOT_APPROVED": 422,
    "ERR_PRODUCT_NOT_PERMITTED": 422,
    "ERR_ISOLATION_TOO_SHORT": 422,
    "ERR_RESUBMISSION_LIMIT": 422,
    "ERR_CONSIGNMENT_DISABLED": 422,
    "ERR_NO_ELIGIBLE_SIRE": 422,
    # ---- business fiscal ----
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
