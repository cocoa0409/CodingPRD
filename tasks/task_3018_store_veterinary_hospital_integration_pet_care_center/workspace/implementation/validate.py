"""Request-shape validation and the layered precondition helpers.

Validation order (PRD §2.12):
  1. header presence + role membership      -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
  2. role permitted for the operation       -> ERR_INSUFFICIENT_PERMISSIONS
  3. path identifier resolution (l-to-r)    -> ERR_*_NOT_FOUND
  4. declared request shape                 -> ERR_INVALID_REQUEST
  5. state / business rules                 -> specific error ids
"""

import db
import domain
from errors import ApiError

ENUMS = {
    "state_code": set(domain.STATE_DEFAULT_DAYS),
    "species": {"CANINE", "FELINE"},
    "handling_tier": {"STANDARD", "SENSITIVE", "HIGH_RISK"},
    "bay_code": {"GROOMING", "VETERINARY", "TRAINING", "VACCINATION"},
    "service_type": {"GROOMING", "TRAINING", "VETERINARY", "VACCINATION"},
    "item_type": {"MEDICATION", "DIET", "TREATMENT"},
    "severity": {"MINOR", "MODERATE", "SEVERE"},
    "incident_type": {"PET_INJURY", "HANDLER_INJURY", "BITE"},
    "tier": {"ESSENTIAL", "PLUS", "UNLIMITED"},
    "vaccine_type": set(domain.VACCINE_TYPES),
    "billing_cycle_count": {1, 3, 6, 12},
}

INT_FIELDS = {
    "service_bay_count", "hospital_capacity", "risk_points", "evidence_count",
    "unit_price_cents", "quantity", "requested_quantity", "claim_amount_cents",
    "credit_redeemed_cents", "courses_required", "courses_completed",
    "health_condition_points", "magnitude", "grooming_visits_consumed",
    "vet_visits_consumed", "vaccine_visits_consumed", "billing_cycle_count",
}

BOOL_FIELDS = {"aggression_acknowledged", "allowed_for_grooming",
               "coverage_required"}

DATETIME_FIELDS = {"starts_at", "ends_at", "scheduled_at", "clinic_date",
                   "open_time", "close_time", "prior_rabies_vaccination_date"}

STRING_FIELDS = {"store_code", "city", "full_name", "email", "member_id",
                 "name", "breed", "bay_id", "pet_id", "clinician_name",
                 "chief_complaint", "medical_notes", "booking_id",
                 "coverage_provider", "clinic_id", "vaccine_type",
                 "item_name", "sku", "authorization_id", "override_reason",
                 "class_code", "package_id", "incident_type", "severity",
                 "tier", "member_state_code", "handling_tier", "service_type",
                 "item_type", "species", "state_code", "bay_code"}

NUMBER_FIELDS = {"weight_kg", "state_sales_tax_rate"}

VERSION_FIELDS = {
    "expected_store_version", "expected_pet_version", "expected_booking_version",
    "expected_encounter_version", "expected_clinic_version", "expected_visit_version",
    "expected_authorization_version", "expected_order_version",
    "expected_incident_version", "expected_package_version",
    "expected_enrollment_version", "expected_cross_sell_version",
    "expected_bay_version",
}

FIELDS = (INT_FIELDS | BOOL_FIELDS | DATETIME_FIELDS | STRING_FIELDS
          | NUMBER_FIELDS | VERSION_FIELDS | {"to_iso8601"})


def _is_int(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return float(value).is_integer()


def check_profile(headers, allowed_roles):
    """Priority 1 and 2 — identity headers, then role permission."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role or role not in domain.ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if "Any" in allowed_roles:
        return role
    if role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
    return role


def normalize(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return body


def shape(body, required=(), optional=(), allowed=None):
    """Validate declared types, enums, required fields and unknown fields."""
    body = normalize(body)
    permitted = set(required) | set(optional)
    if allowed is not None:
        permitted |= set(allowed)
    for key in body:
        if key not in permitted:
            raise ApiError("ERR_INVALID_REQUEST")
    for key in required:
        if key.startswith("expected_"):
            # an omitted expectation is reported by require_expected (priority 22),
            # not as a malformed request
            continue
        if key not in body or body[key] is None:
            raise ApiError("ERR_INVALID_REQUEST")
    for key, value in body.items():
        if value is None:
            continue
        if key in INT_FIELDS:
            if isinstance(value, bool) or not _is_int(value):
                raise ApiError("ERR_INVALID_REQUEST")
        elif key in NUMBER_FIELDS:
            if isinstance(value, bool) or not _is_number(value):
                raise ApiError("ERR_INVALID_REQUEST")
        elif key in BOOL_FIELDS:
            if not isinstance(value, bool):
                raise ApiError("ERR_INVALID_REQUEST")
        elif key in DATETIME_FIELDS:
            try:
                db.parse_dt(value)
            except ValueError:
                raise ApiError("ERR_INVALID_REQUEST")
        elif key in VERSION_FIELDS:
            if isinstance(value, bool) or not _is_int(value):
                raise ApiError("ERR_INVALID_REQUEST")
        elif key in STRING_FIELDS:
            if not isinstance(value, str):
                raise ApiError("ERR_INVALID_REQUEST")
    for key, members in ENUMS.items():
        if key in body and body[key] is not None and body[key] not in members:
            raise ApiError("ERR_INVALID_REQUEST")
    return body


def _is_number(value):
    return isinstance(value, (int, float))


def positive(value, name="field"):
    if value is None or value <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be greater than zero." % name)
    return value


def require_expected(body, parent_version, field):
    """Priority 22 then 23 — the OCC pair."""
    if field not in body or body[field] is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(body[field]) != parent_version:
        raise ApiError("ERR_STALE_VERSION")


def check_backdating(*rows):
    """Priority 6 — history may not be rewritten from an earlier clock.

    The comparison is against the clock value already used to create, read or
    mutate the target resource (PRD §2.5), not against the clock's high-water
    mark, so a rewind followed by a fresh creation is not itself a violation.
    """
    for row in rows:
        if row is None:
            continue
        stamp = row.get("clock_at")
        if stamp is not None and db.clock["current"] < stamp:
            raise ApiError("ERR_BACKDATED_ACTION")
        db.mark_read(row)


def paginate(query):
    """PRD §2.3 — limit 10 default, 1..100, offset 0 default."""
    raw_limit = query.get("limit")
    raw_offset = query.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
            if isinstance(raw_limit, str) and raw_limit.strip() != str(limit):
                raise ValueError
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
            if isinstance(raw_offset, str) and raw_offset.strip() != str(offset):
                raise ValueError
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST")
    return limit, offset