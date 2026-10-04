"""Error classes: each carries the scaffold error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- auth ---
def err_missing_user_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID or X-User-Role header missing or role not a declared role", 400)

def err_forbidden_role():
    return ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint", 403)

def err_forbidden_identity():
    return ApiError("ERR_FORBIDDEN_IDENTITY",
                    "Customer role may only act on own resources", 403)


# --- existence ---
def err_not_found(error_id, what):
    return ApiError(error_id, f"{what} not found", 404)

def err_phone_not_found():
    return ApiError("ERR_PHONE_NOT_FOUND", "No account with that phone", 404)


# --- request shape ---
def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


# --- OCC ---
def err_stale_store_version():
    return ApiError("ERR_STALE_STORE_VERSION", "expected_store_version is stale", 412)

def err_stale_lot_version():
    return ApiError("ERR_STALE_LOT_VERSION", "expected_livestock_lot_version is stale", 412)


# --- state ---
def err_invalid_state_transition(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg, 409)

def err_campaign_not_in_draft():
    return ApiError("ERR_CAMPAIGN_NOT_IN_DRAFT", "begin-teardown requires DRAFT", 409)

def err_campaign_not_in_teardown():
    return ApiError("ERR_CAMPAIGN_NOT_IN_TEARDOWN", "complete-reset requires TEARDOWN", 409)

def err_campaign_not_verify_pending():
    return ApiError("ERR_CAMPAIGN_NOT_VERIFY_PENDING", "verify requires VERIFY_PENDING", 409)

def err_campaign_not_ready():
    return ApiError("ERR_CAMPAIGN_NOT_READY", "activate requires READY", 409)

def err_schedule_not_draft():
    return ApiError("ERR_SCHEDULE_NOT_DRAFT", "operation requires schedule DRAFT", 409)

def err_schedule_not_published():
    return ApiError("ERR_SCHEDULE_NOT_PUBLISHED", "operation requires schedule PUBLISHED", 409)

def err_posture_not_spring():
    return ApiError("ERR_POSTURE_NOT_SPRING_PLANTING",
                    "chick order creation requires store posture SPRING_PLANTING", 409)

def err_store_floor_closed():
    return ApiError("ERR_STORE_FLOOR_CLOSED",
                    "weighted sale creation requires a non-OFFSEASON store posture", 409)

def err_lot_not_receiving():
    return ApiError("ERR_LOT_NOT_RECEIVING", "open-sale requires lot RECEIVING", 409)

def err_lot_not_on_sale():
    return ApiError("ERR_LOT_NOT_ON_SALE", "operation requires lot ON_SALE", 409)

def err_order_not_reserved():
    return ApiError("ERR_ORDER_NOT_RESERVED", "verify-brooder requires order RESERVED", 409)

def err_order_not_verified():
    return ApiError("ERR_ORDER_NOT_VERIFIED", "fulfill requires order BROODER_VERIFIED", 409)

def err_sale_not_provisional():
    return ApiError("ERR_SALE_NOT_PROVISIONAL", "operation requires sale PROVISIONAL", 409)

def err_account_suspended():
    return ApiError("ERR_ACCOUNT_SUSPENDED", "operation requires an ACTIVE loyalty account", 409)

def err_event_not_published():
    return ApiError("ERR_EVENT_NOT_PUBLISHED", "booking requires ServiceEvent PUBLISHED", 409)


# --- business safety ---
def err_brooder_check_failed():
    return ApiError("ERR_BROODER_CHECK_FAILED", "All three brooder flags must be true", 422)

def err_brooder_verification_expired():
    return ApiError("ERR_BROODER_VERIFICATION_EXPIRED",
                    "brooder verification older than 72 hours; order reverted to RESERVED", 422)

def err_care_log_stale():
    return ApiError("ERR_CARE_LOG_STALE",
                    "lot requires a care log entry within the last 12 hours", 422)

def err_hazmat_cap():
    return ApiError("ERR_HAZMAT_DAILY_CAP_EXCEEDED",
                    "propane finalize would exceed the daily hazmat cap", 422)

def err_vaccine_record_required():
    return ApiError("ERR_VACCINE_RECORD_REQUIRED",
                    "vaccine_record_confirmed must be true for this event", 422)


# --- business temporal ---
def err_outside_sale_window():
    return ApiError("ERR_OUTSIDE_SALE_WINDOW", "outside the schedule sale window", 409)

def err_sale_window_closed():
    return ApiError("ERR_SALE_WINDOW_CLOSED",
                    "fulfill attempted after sale_window_end + 48h grace; order expired", 409)

def err_claim_window_expired():
    return ApiError("ERR_CLAIM_WINDOW_EXPIRED",
                    "mortality claim attempted more than 48h after fulfillment", 422)

def err_pickup_window_expired():
    return ApiError("ERR_PICKUP_WINDOW_EXPIRED",
                    "complete attempted after pickup_deadline; order expired", 409)

def err_schedule_window_overlap():
    return ApiError("ERR_SCHEDULE_WINDOW_OVERLAP",
                    "publish would violate the 7-day sanitization gap", 409)

def err_booking_overlap():
    return ApiError("ERR_BOOKING_OVERLAP", "booking collides with existing occupancy", 409)

def err_outside_checkin_window():
    return ApiError("ERR_OUTSIDE_CHECKIN_WINDOW",
                    "check-in outside [slot_start - 15min, slot_end]", 409)

def err_booking_not_expired():
    return ApiError("ERR_BOOKING_NOT_EXPIRED", "mark-no-show requires now > slot_end", 409)


# --- business constraint ---
def err_min_purchase():
    return ApiError("ERR_MIN_PURCHASE_NOT_MET",
                    "quantity below schedule min_purchase_qty", 422)

def err_daily_capacity():
    return ApiError("ERR_DAILY_CAPACITY_EXCEEDED",
                    "reservation would exceed schedule daily capacity for today", 422)

def err_lot_capacity():
    return ApiError("ERR_LOT_CAPACITY_EXCEEDED",
                    "order quantity exceeds lot quantity_on_hand", 422)

def err_claim_exceeds_remaining():
    return ApiError("ERR_CLAIM_EXCEEDS_REMAINING",
                    "claimed mortality exceeds remaining claimable birds", 422)

def err_tare_exceeds_gross():
    return ApiError("ERR_TARE_EXCEEDS_GROSS",
                    "measured_tare_lbs must be > 0 and <= gross_weight_lbs", 422)

def err_no_staging_bay():
    return ApiError("ERR_NO_STAGING_BAY_AVAILABLE",
                    "no AVAILABLE staging bay of sufficient size", 422)

def err_phone_taken():
    return ApiError("ERR_PHONE_ALREADY_REGISTERED", "phone already registered", 409)

def err_bay_no_taken():
    return ApiError("ERR_BAY_NO_TAKEN", "bay_no already exists for the store", 409)

def err_aisle_count_mismatch():
    return ApiError("ERR_AISLE_COUNT_MISMATCH",
                    "aisles_reset_count must equal campaign aisle_count", 422)

def err_loadout_not_applicable():
    return ApiError("ERR_LOADOUT_NOT_APPLICABLE",
                    "order does not require loadout assistance", 422)

def err_loadout_not_completed():
    return ApiError("ERR_LOADOUT_NOT_COMPLETED",
                    "loadout must be completed before pickup completion", 409)


# --- fiscal ---
def err_insufficient_points():
    return ApiError("ERR_INSUFFICIENT_POINTS", "redeem_points exceed points_balance", 422)


# --- referential ---
def err_reversal_mismatch():
    return ApiError("ERR_REVERSAL_MISMATCH",
                    "REVERSAL sign/magnitude inconsistent with referenced entry", 422)
