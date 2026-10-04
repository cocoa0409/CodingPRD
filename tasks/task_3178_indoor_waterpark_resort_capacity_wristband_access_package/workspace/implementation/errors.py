"""Error catalogue and the exception type that carries it."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super(ApiError, self).__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


def unauthenticated(message="X-User-Role or X-User-ID header missing or unrecognised."):
    return err("ERR_UNAUTHENTICATED", message, 401)


def forbidden(message="The acting role is not permitted for this operation."):
    return err("ERR_FORBIDDEN", message, 403)


def ownership_mismatch(message="The acting Group does not own the targeted GroupBooking."):
    return err("ERR_GROUP_OWNERSHIP_MISMATCH", message, 403)


def not_found(message="The referenced resource does not resolve under this resort."):
    return err("ERR_NOT_FOUND", message, 404)


def invalid_request(message="The request body is missing a required field or carries an undeclared field."):
    return err("ERR_INVALID_REQUEST", message, 400)


def invalid_state(message="The target resource is not in a state that permits the requested transition."):
    return err("ERR_INVALID_STATE", message, 409)


def pool_closed(message="The property's pool posture is CLOSED."):
    return err("ERR_POOL_CLOSED", message, 409)


def water_quality_out_of_range(message="The submitted reading is not physically plausible."):
    return err("ERR_WATER_QUALITY_OUT_OF_RANGE", message, 422)


def shift_rotation_violation(message="The shift breaches the rotation roster."):
    return err("ERR_SHIFT_ROTATION_VIOLATION", message, 409)


def attraction_not_open(message="The attraction is not open or is short of its staffing floor."):
    return err("ERR_ATTRACTION_NOT_OPEN", message, 409)


def park_capacity_exceeded(message="The occupancy units for the service date would exceed the park capacity."):
    return err("ERR_PARK_CAPACITY_EXCEEDED", message, 409)


def day_pass_cap_exceeded(message="The day-passed units for the service date would exceed the day-pass cap."):
    return err("ERR_DAY_PASS_CAP_EXCEEDED", message, 409)


def day_pass_units_exhausted(message="The day pass has fewer RESERVED units remaining than the presenting band consumes."):
    return err("ERR_DAY_PASS_UNITS_EXHAUSTED", message, 409)


def arcade_limit_exceeded(message="The amount would push arcade spend above the band's ceiling."):
    return err("ERR_ARCADE_LIMIT_EXCEEDED", message, 402)


def room_charge_disabled(message="Room charging is disabled on this wristband."):
    return err("ERR_ROOM_CHARGE_DISABLED", message, 409)


def wristband_not_active(message="The wristband is not ACTIVE with GRANTED access."):
    return err("ERR_WRISTBAND_NOT_ACTIVE", message, 409)


def wristband_already_reissued(message="The wristband has already been superseded."):
    return err("ERR_WRISTBAND_ALREADY_REISSUED", message, 409)


def held_units_not_releasable(message="The wristband carries arcade spend and cannot be re-issued."):
    return err("ERR_HELD_UNITS_NOT_RELEASABLE", message, 409)


def account_lien_outstanding(message="The folio still carries an outstanding arcade spend."):
    return err("ERR_ACCOUNT_LIEN_OUTSTANDING", message, 409)


def declined_authorization(message="The authorising gateway declined the charge."):
    return err("ERR_DECLINED_AUTHORIZATION", message, 402)


def cabana_double_booked(message="The cabana window overlaps a standing occupation."):
    return err("ERR_CABANA_DOUBLE_BOOKED", message, 409)


def cabana_occupied(message="The cabana booking cannot be transitioned while its current occupation stands."):
    return err("ERR_CABANA_OCCUPIED", message, 409)


def cabana_units_unavailable(message="member_units exceeds the cabana's capacity."):
    return err("ERR_CABANA_UNITS_UNAVAILABLE", message, 409)


def group_split_admission(message="A second group member cannot be admitted separately."):
    return err("ERR_GROUP_SPLIT_ADMISSION", message, 409)


def group_minimum_not_met(message="The birthday booking is below the party minimum."):
    return err("ERR_GROUP_MINIMUM_NOT_MET", message, 409)


def service_date_out_of_range(message="The service date is more than 365 days after the current service date."):
    return err("ERR_SERVICE_DATE_OUT_OF_RANGE", message, 409)


def payment_declined(message="The deposit does not meet the group's requirement."):
    return err("ERR_PAYMENT_DECLINED", message, 409)


def no_eligible_session(message="No session in the resort can seat the requested party."):
    return err("ERR_NO_ELIGIBLE_SESSION", message, 409)


def stale_resort_version(message="expected_resort_version does not match the resort's current version."):
    return err("ERR_STALE_RESORT_VERSION", message, 412)


def stale_cabana_version(message="expected_cabana_version does not match the cabana's current version."):
    return err("ERR_STALE_CABANA_VERSION", message, 412)


def duplicate_reading_at_instant(message="A reading already exists for this attraction at this instant."):
    return err("ERR_DUPLICATE_READING_AT_INSTANT", message, 409)