"""ServiceAuthorization creation, guarded by enrollment-version OCC."""

import db
from common import assert_faith_based_ok, assert_grant_not_frozen
from errors import ApiError

OVERLAP_STATUSES = ("DRAFT", "ACTIVE", "EXHAUSTED")
SERVICE_CODES = (
    "HOUSING_RENT_ASSIST",
    "FOOD_PANTRY_BOX",
    "CLINICAL_COUNSELING_HOUR",
    "IMMIGRATION_LEGAL_HOUR",
    "REFUGEE_CASE_MGMT_HOUR",
)


def _overlaps(enrollment_id, service_code, start, end):
    """Half-open intervals: an existing period_end equal to the new
    period_start is NOT an overlap."""
    for auth in db.rows("service_authorizations"):
        if auth.get("enrollment_id") != enrollment_id:
            continue
        if auth.get("service_code") != service_code:
            continue
        if auth.get("status") not in OVERLAP_STATUSES:
            continue
        other_start = auth.get("period_start")
        other_end = auth.get("period_end")
        if other_start is None or other_end is None:
            continue
        if start < other_end and other_start < end:
            return True
    return False


def create(enrollment, grant, payload):
    program = db.get("programs", enrollment.get("program_id"))
    assert_grant_not_frozen(grant)
    expected = payload.get("expected_enrollment_version")
    if expected is None or int(expected) != enrollment.get("version"):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_enrollment_version does not match the enrollment's current version.",
        )
    assert_faith_based_ok(grant, program)

    service_code = payload.get("service_code")
    if service_code not in SERVICE_CODES:
        raise ApiError("ERR_BAD_REQUEST", "service_code is not a declared unit-of-service code.")
    start = payload.get("period_start")
    end = payload.get("period_end")
    units = payload.get("authorized_units")
    rate = payload.get("unit_rate_cents")
    if start is None or end is None or units is None or rate is None:
        raise ApiError(
            "ERR_BAD_REQUEST",
            "authorized_units, unit_rate_cents, period_start and period_end are required.",
        )
    if int(units) < 1 or int(rate) < 1:
        raise ApiError("ERR_BAD_REQUEST", "authorized_units and unit_rate_cents must be at least 1.")
    from clock import parse as parse_iso
    start_dt = parse_iso(start)
    end_dt = parse_iso(end)
    if _overlaps(enrollment["id"], service_code, start_dt, end_dt):
        raise ApiError(
            "ERR_AUTHORIZATION_PERIOD_OVERLAP",
            "The requested window overlaps an existing authorization for the same "
            "enrollment and service code.",
        )
    auth = db.create("service_authorizations", {
        "enrollment_id": enrollment["id"],
        "grant_id": grant["id"],
        "service_code": service_code,
        "authorized_units": int(units),
        "unit_rate_cents": int(rate),
        "units_delivered": 0,
        "period_start": start_dt,
        "period_end": end_dt,
        "status": "ACTIVE",
    })
    db.touch(enrollment)
    return auth
