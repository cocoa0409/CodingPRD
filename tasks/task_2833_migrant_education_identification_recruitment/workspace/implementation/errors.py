"""Error catalogue for the Migrant Education Identification & Recruitment API.

Every error_id and HTTP status comes straight from PRD section 5.
"""

ERROR_CATALOG = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": (401, "Missing or unrecognized caller identity"),
    "ERR_UNAUTHORIZED": (403, "Role not permitted for this operation"),
    # request shape
    "ERR_INVALID_REQUEST": (422, "Request body or query parameters failed shape validation"),
    # existence
    "ERR_AREA_NOT_FOUND": (404, "Agricultural area not found"),
    "ERR_RECRUITER_NOT_FOUND": (404, "Recruiter not found"),
    "ERR_ASSIGNMENT_NOT_FOUND": (404, "Recruiter assignment not found"),
    "ERR_STUDENT_NOT_FOUND": (404, "Student not found"),
    "ERR_MOVE_NOT_FOUND": (404, "Qualifying move not found"),
    "ERR_INTERVIEW_NOT_FOUND": (404, "Interview record not found"),
    "ERR_COE_NOT_FOUND": (404, "Certificate of eligibility not found"),
    "ERR_QC_REVIEW_NOT_FOUND": (404, "Quality control review not found"),
    "ERR_TERM_NOT_FOUND": (404, "Eligibility term not found"),
    "ERR_TRANSFER_NOT_FOUND": (404, "Record transfer request not found"),
    "ERR_PLAN_NOT_FOUND": (404, "Service plan not found"),
    "ERR_DELIVERY_NOT_FOUND": (404, "Service delivery not found"),
    # state machine
    "ERR_COE_NOT_IN_DRAFT": (409, "Certificate is not in a correctable state"),
    "ERR_COE_INVALID_STATE": (409, "Certificate is not in a state that permits this action"),
    "ERR_QC_REVIEW_ALREADY_DECIDED": (409, "Quality control review has already been decided"),
    "ERR_ASSIGNMENT_INVALID_STATE": (409, "Assignment is not in a state that permits this action"),
    "ERR_MOVE_ALREADY_ADJUDICATED": (409, "Qualifying move has already been adjudicated"),
    "ERR_PLAN_INVALID_STATE": (409, "Service plan is not in a state that permits this action"),
    "ERR_TERM_INVALID_STATE": (409, "Eligibility term is not in a state that permits this action"),
    "ERR_TRANSFER_INVALID_STATE": (409, "Transfer request is not in a state that permits this action"),
    # optimistic concurrency
    "ERR_STALE_STUDENT_VERSION": (412, "Student version does not match expected_student_version"),
    "ERR_STALE_AREA_VERSION": (412, "Area version does not match expected_area_version"),
    # business safety
    "ERR_SEGREGATION_OF_DUTIES": (403, "Reviewer may not decide a certificate they initiated"),
    "ERR_QC_CREDENTIAL_REQUIRED": (403, "Quality control decisions require a QC_CERTIFIED credential"),
    "ERR_MOVE_NOT_QUALIFYING": (422, "Move does not involve agricultural or fishing work"),
    "ERR_MOVE_NOT_VERIFIED": (409, "The linked qualifying move has not been verified"),
    "ERR_INTERVIEW_DOCUMENTATION_MISSING": (409, "No supporting initial interview on file for this student and move"),
    # referential integrity
    "ERR_REINTERVIEW_STUDENT_MISMATCH": (422, "Re-interview record does not belong to this certificate"),
    "ERR_DUPLICATE_ACTIVE_COE": (409, "Another live certificate already exists for this student and move"),
    "ERR_TRANSFER_SELF_MATCH": (422, "A transfer request cannot be matched to its own student record"),
    "ERR_CREDITS_NOT_ALLOWED_FOR_PLAN_TYPE": (422, "Credits may only be awarded on a credit accrual plan"),
    # temporal
    "ERR_MOVE_DATE_IN_FUTURE": (422, "Date is later than the current logical clock"),
    "ERR_RESIDENCY_DATE_BEFORE_MOVE": (422, "Residency date precedes the qualifying move"),
    "ERR_PEAK_SEASON_NOT_COVERED": (422, "Primary coverage must span the area's whole peak season"),
    "ERR_RECRUITER_ASSIGNMENT_OVERLAP": (409, "Recruiter already has coverage intersecting these dates"),
    "ERR_REIDENTIFICATION_WINDOW_CLOSED": (409, "The reidentification grace period has closed"),
    # constraint / capacity
    "ERR_RECRUITER_NOT_ACTIVE": (409, "Recruiter is not active"),
    "ERR_AREA_NOT_OPEN": (409, "Area is not open for coverage"),
    "ERR_STUDENT_NOT_ELIGIBLE_FOR_SERVICES": (409, "Student is not currently eligible for services"),
    "ERR_OSY_PLAN_REQUIRES_OUT_OF_SCHOOL": (422, "OSY alternative plans require an out-of-school student"),
    "ERR_SUPPLEMENTAL_REQUIRES_ENROLLED": (422, "Supplemental instruction requires an enrolled student"),
    "ERR_INVALID_SERVICE_HOURS": (422, "Service hours or credits are outside the permitted grid"),
    "ERR_DELIVERY_NOT_REVERSIBLE": (409, "Delivery record cannot be reversed"),
    "ERR_AREA_COVERAGE_CAPACITY_EXCEEDED": (409, "Area primary coverage capacity exceeded on at least one date"),
    "ERR_NO_QC_CANDIDATES": (409, "No certificates are eligible for quality control selection"),
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed"))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else status
        self.message = message if message else default_message
        super().__init__("%s: %s" % (self.error_id, self.message))


def api_error(error_id, message=None):
    return ApiError(error_id, message)


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)
