"""Error classes and error id constants for the prescription data licensing API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", msg, 403)


def err_forbidden_ownership(msg="Acting party does not own this resource"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", msg, 403)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Request body failed schema validation"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="Target entity state does not permit this transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_agreement_not_active(msg="Agreement (or its supplier) is not ACTIVE"):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", msg, 409)


def err_batch_invalid_state(msg="Batch status does not permit the requested transition"):
    return ApiError("ERR_BATCH_INVALID_STATE", msg, 409)


def err_opt_out_invalid_state(msg="Opt-out status does not permit the requested transition"):
    return ApiError("ERR_OPT_OUT_INVALID_STATE", msg, 409)


def err_delivery_invalid_state(msg="Delivery status does not permit the requested transition"):
    return ApiError("ERR_DELIVERY_INVALID_STATE", msg, 409)


def err_prescriber_not_active(msg="Prescriber must be ACTIVE"):
    return ApiError("ERR_PRESCRIBER_NOT_ACTIVE", msg, 409)


def err_client_suspended(msg="Client (or its product) is SUSPENDED"):
    return ApiError("ERR_CLIENT_SUSPENDED", msg, 409)


def err_reidentification_prohibited(msg="Re-identification of de-identified data is prohibited"):
    return ApiError("ERR_REIDENTIFICATION_PROHIBITED", msg, 403)


def err_opt_out_violation(msg="Prescriber has an ACTIVE opt-out"):
    return ApiError("ERR_PRESCRIBER_OPT_OUT_VIOLATION", msg, 422)


def err_jurisdiction_restricted(msg="Prescriber's state has an effective restrictive jurisdiction rule"):
    return ApiError("ERR_JURISDICTION_RESTRICTED", msg, 422)


def err_deid_qa_below_threshold(msg="deid_qa_score below 0.90"):
    return ApiError("ERR_DEID_QA_BELOW_THRESHOLD", msg, 422)


def err_agreement_window_overlap(msg="Exclusivity window overlaps a non-TERMINATED agreement of the same supplier and domain"):
    return ApiError("ERR_AGREEMENT_WINDOW_OVERLAP", msg, 409)


def err_delivery_window_missed(msg="Current logical date precedes the period end date"):
    return ApiError("ERR_DELIVERY_WINDOW_MISSED", msg, 422)


def err_audit_cooldown_active(msg="New audit window violates the cooldown or overlaps an open audit"):
    return ApiError("ERR_AUDIT_COOLDOWN_ACTIVE", msg, 422)


def err_product_version_stale(msg="Product pinned methodology version is stale"):
    return ApiError("ERR_PRODUCT_VERSION_STALE", msg, 409)


def err_no_deliverable_cells(msg="No CURRENT projection cells match the delivery period"):
    return ApiError("ERR_NO_DELIVERABLE_CELLS", msg, 422)


def err_duplicate_opt_out(msg="An active opt-out already exists for this prescriber"):
    return ApiError("ERR_DUPLICATE_OPT_OUT", msg, 409)


def err_royalty_budget_exhausted(msg="Accepting the batch would exceed the royalty budget"):
    return ApiError("ERR_ROYALTY_BUDGET_EXHAUSTED", msg, 402)


def err_insufficient_entitlement(msg="Client entitlement balance is insufficient"):
    return ApiError("ERR_INSUFFICIENT_ENTITLEMENT", msg, 402)
