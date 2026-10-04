"""Error classes and error ID constants (from SCAFFOLD §1.6 error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers, or unknown role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not allowed on this endpoint or ownership check failed"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_distributor_mismatch(msg="DistributorAgent identity does not match the order's distributor"):
    return ApiError("ERR_DISTRIBUTOR_MISMATCH", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Missing required field or invalid value"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_uniqueness(msg="Uniqueness constraint violated"):
    return ApiError("ERR_UNIQUENESS_CONFLICT", 409, msg)


def err_invalid_agreement_state(msg="Agreement transition not allowed from current state"):
    return ApiError("ERR_INVALID_AGREEMENT_STATE", 409, msg)


def err_agreement_not_active(msg="An ACTIVE license agreement is required"):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, msg)


def err_invalid_store_state(msg="Store transition not allowed from current state"):
    return ApiError("ERR_INVALID_STORE_STATE", 409, msg)


def err_store_not_operating(msg="Operation requires the store to be OPERATING"):
    return ApiError("ERR_STORE_NOT_OPERATING", 409, msg)


def err_invalid_order_state(msg="Order transition not allowed from current state"):
    return ApiError("ERR_INVALID_ORDER_STATE", 409, msg)


def err_invalid_cert_state(msg="Certification transition not allowed from current state"):
    return ApiError("ERR_INVALID_CERTIFICATION_STATE", 409, msg)


def err_sales_report_not_draft(msg="Sales report is not in DRAFT status"):
    return ApiError("ERR_SALES_REPORT_NOT_DRAFT", 409, msg)


def err_invalid_statement_state(msg="Statement transition not allowed from current state"):
    return ApiError("ERR_INVALID_STATEMENT_STATE", 409, msg)


def err_invalid_inspection_state(msg="Inspection transition not allowed from current state"):
    return ApiError("ERR_INVALID_INSPECTION_STATE", 409, msg)


def err_invalid_corrective_state(msg="Corrective-action transition not allowed from current state"):
    return ApiError("ERR_INVALID_CORRECTIVE_STATE", 409, msg)


def err_invalid_campaign_state(msg="Campaign operation not allowed from current state"):
    return ApiError("ERR_INVALID_CAMPAIGN_STATE", 409, msg)


def err_sod(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_venue_type_prohibited(msg="Product is not permitted at this venue type"):
    return ApiError("ERR_VENUE_TYPE_PROHIBITED", 422, msg)


def err_proprietary_restricted(msg="Proprietary product cannot be assorted while store is in PROBATION"):
    return ApiError("ERR_PROPRIETARY_ITEM_RESTRICTED", 422, msg)


def err_insufficient_staff(msg="Fewer than 2 CERTIFIED active BARISTA employees"):
    return ApiError("ERR_INSUFFICIENT_CERTIFIED_STAFF", 422, msg)


def err_footprint(msg="Equipment footprint usage would exceed the venue cap"):
    return ApiError("ERR_FOOTPRINT_EXCEEDED", 422, msg)


def err_empty_order(msg="Order has no lines"):
    return ApiError("ERR_EMPTY_ORDER", 422, msg)


def err_max_reopens(msg="Corrective action already reopened the maximum number of times"):
    return ApiError("ERR_MAX_REOPENS_EXCEEDED", 422, msg)


def err_posture_probation(msg="Operation not permitted while store posture is PROBATION"):
    return ApiError("ERR_STORE_POSTURE_PROBATION", 422, msg)


def err_outside_venue_hours(msg="Inspection window falls outside host venue hours or is malformed"):
    return ApiError("ERR_INSPECTION_OUTSIDE_VENUE_HOURS", 422, msg)


def err_inspector_conflict(msg="Inspector has an overlapping scheduled inspection"):
    return ApiError("ERR_INSPECTOR_SCHEDULE_CONFLICT", 409, msg)


def err_campaign_conflict(msg="Campaign window overlaps an existing PLANNED/ACTIVE campaign"):
    return ApiError("ERR_CAMPAIGN_WINDOW_CONFLICT", 409, msg)


def err_campaign_window(msg="Campaign activation attempted outside its window"):
    return ApiError("ERR_CAMPAIGN_WINDOW_NOT_OPEN", 422, msg)


def err_sales_overlap(msg="A FINALIZED sales report already covers an overlapping period"):
    return ApiError("ERR_SALES_PERIOD_OVERLAP", 409, msg)


def err_distributor_not_approved(msg="Distributor is not approved"):
    return ApiError("ERR_DISTRIBUTOR_NOT_APPROVED", 422, msg)


def err_product_not_in_assortment(msg="Order line product is not in the store's active assortment"):
    return ApiError("ERR_PRODUCT_NOT_IN_ASSORTMENT", 422, msg)


def err_invalid_loyalty_event(msg="Loyalty event store_format/store_id consistency violated"):
    return ApiError("ERR_INVALID_LOYALTY_EVENT", 422, msg)


def err_order_budget(msg="Order total exceeds the per-order budget ceiling"):
    return ApiError("ERR_ORDER_BUDGET_EXCEEDED", 422, msg)


def err_loyalty_insufficient(msg="Redeem/adjust exceeds member balance or format cap"):
    return ApiError("ERR_LOYALTY_INSUFFICIENT_POINTS", 422, msg)


def err_credit_exceeds(msg="Credit outside 0..(total_cost_cents - received_value_cents)"):
    return ApiError("ERR_DISPUTE_CREDIT_EXCEEDS_SHORTAGE", 422, msg)


def err_stale_version(msg="expected_agreement_version does not match the agreement's current version"):
    return ApiError("ERR_STALE_AGREEMENT_VERSION", 412, msg)
