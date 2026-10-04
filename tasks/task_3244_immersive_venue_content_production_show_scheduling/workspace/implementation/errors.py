"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Missing or invalid X-User-Role header"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_state(msg="Entity not in a state that permits the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def show_conflict(msg="Show reserved window overlaps an existing non-cancelled show"):
    return ApiError("ERR_SHOW_CONFLICT", msg, 422)


def maintenance_conflict(msg="Maintenance window overlaps a show reserved window or end_time <= start_time"):
    return ApiError("ERR_MAINTENANCE_CONFLICT", msg, 422)


def zone_capacity(msg="Booking seats exceed remaining zone capacity"):
    return ApiError("ERR_ZONE_CAPACITY_EXCEEDED", msg, 422)


def accessibility_zone(msg="WHEELCHAIR/COMPANION seat kind not permitted in APEX zone"):
    return ApiError("ERR_ACCESSIBILITY_ZONE", msg, 422)


def no_approved_asset(msg="Show confirm requires at least one APPROVED asset"):
    return ApiError("ERR_NO_APPROVED_ASSET", msg, 422)


def tech_not_ready(msg="Show confirm requires tech_readiness == READY"):
    return ApiError("ERR_TECH_NOT_READY", msg, 422)


def production_already_active(msg="Another production is already ACTIVE"):
    return ApiError("ERR_PRODUCTION_ALREADY_ACTIVE", msg, 409)


def campaign_overlap(msg="Sponsor already has an ACTIVE campaign whose flight window overlaps"):
    return ApiError("ERR_CAMPAIGN_OVERLAP", msg, 422)


def batch_busy(msg="Batch has no submitted assets, or another batch is RENDERING/SETTLING"):
    return ApiError("ERR_BATCH_BUSY", msg, 409)


def render_blocked(msg="ENV_FX maintenance window overlaps the projected render window"):
    return ApiError("ERR_RENDER_BLOCKED_BY_MAINTENANCE", msg, 422)


def hold_expired(msg="Booking hold window (15 min) has elapsed"):
    return ApiError("ERR_BOOKING_HOLD_EXPIRED", msg, 422)


def asset_not_in_qc(msg="QC approve/fail requires asset in QC"):
    return ApiError("ERR_ASSET_NOT_IN_QC", msg, 409)


def format_mismatch(msg="Haptic-capable production requires WRAP_16K capture format"):
    return ApiError("ERR_FORMAT_MISMATCH", msg, 422)
