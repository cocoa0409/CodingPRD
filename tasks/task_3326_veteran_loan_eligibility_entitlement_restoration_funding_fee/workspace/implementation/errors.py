"""Error types and error catalog for the API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Convenience constructors -------------------------------------------------

def unauthenticated(msg="missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def underwriter_is_originator(msg="underwriting decision by loan originator is forbidden"):
    return ApiError("ERR_UNDERWRITER_IS_ORIGINATOR", 403, msg)


def validation(msg="request validation failed"):
    return ApiError("ERR_VALIDATION", 400, msg)


def invalid_enum(msg="enum field carries an undeclared member"):
    return ApiError("ERR_INVALID_ENUM", 400, msg)


def not_found(error_id, msg):
    return ApiError(error_id, 404, msg)


def invalid_state(msg="entity is in a state that does not permit this action"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def coe_not_issued(msg="loan creation requires an ISSUED COE for the borrower"):
    return ApiError("ERR_COE_NOT_ISSUED", 409, msg)


def loan_not_closable(msg="close requires underwriting_status APPROVED"):
    return ApiError("ERR_LOAN_NOT_CLOSABLE", 409, msg)


def loan_not_paid_off(msg="restoration grant requires the loan to be PAID_IN_FULL"):
    return ApiError("ERR_LOAN_NOT_PAID_OFF", 409, msg)


def fee_not_refundable(msg="fee refund requires status COLLECTED"):
    return ApiError("ERR_FEE_NOT_REFUNDABLE", 409, msg)


def reconsideration_exhausted(msg="reconsideration cap of 2 reached"):
    return ApiError("ERR_RECONSIDERATION_EXHAUSTED", 409, msg)


def appraisal_not_assigned(msg="submit-report requires the assigned appraiser on an ASSIGNED or REPAIRS_REQUIRED appraisal"):
    return ApiError("ERR_APPRAISAL_NOT_ASSIGNED", 409, msg)


def stale_version(msg="expected_loan_version does not match current loan version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def discharge_ineligible(msg="character of discharge outside {HONORABLE, GENERAL}"):
    return ApiError("ERR_DISCHARGE_INELIGIBLE", 422, msg)


def insufficient_service(msg="qualifying service days below the category minimum"):
    return ApiError("ERR_INSUFFICIENT_SERVICE", 422, msg)


def service_period_mismatch(msg="referenced child ids do not belong to the asserted parent"):
    return ApiError("ERR_SERVICE_PERIOD_MISMATCH", 422, msg)


def service_period_overlap(msg="new service period overlaps an existing one"):
    return ApiError("ERR_SERVICE_PERIOD_OVERLAP", 409, msg)


def deployment_window_overlap(msg="new deployment window overlaps an existing one"):
    return ApiError("ERR_DEPLOYMENT_WINDOW_OVERLAP", 409, msg)


def seasoning_not_met(msg="refinance seasoning_days below 210"):
    return ApiError("ERR_SEASONING_NOT_MET", 422, msg)


def repairs_outstanding(msg="clearance-required repairs still OPEN or COMPLETED"):
    return ApiError("ERR_REPAIRS_OUTSTANDING", 409, msg)


def assumption_ineligible(msg="assumption approval blocked by buyer eligibility or loan state"):
    return ApiError("ERR_ASSUMPTION_INELIGIBLE", 422, msg)


def invalid_down_payment(msg="down_payment_cents negative or greater than purchase_price_cents"):
    return ApiError("ERR_INVALID_DOWN_PAYMENT", 422, msg)


def insufficient_entitlement(msg="entitlement shortfall not covered by the down payment"):
    return ApiError("ERR_INSUFFICIENT_ENTITLEMENT", 422, msg)
