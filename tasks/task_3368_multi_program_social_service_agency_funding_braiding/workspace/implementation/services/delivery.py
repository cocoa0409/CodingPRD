"""ServiceDelivery recording, documentation (braiding), billing and reversal."""

import clock
import db
from common import assert_faith_based_ok, assert_grant_not_frozen
from errors import ApiError
from services import allocation, posture


def _covers(auth, at):
    start = auth.get("period_start")
    end = auth.get("period_end")
    if start is None or end is None:
        return False
    return start <= at < end


def enrollment_has_active_authorization(enrollment_id, at):
    for auth in db.rows("service_authorizations"):
        if auth.get("enrollment_id") != enrollment_id:
            continue
        if auth.get("status") != "ACTIVE":
            continue
        if _covers(auth, at):
            return True
    return False


def create(auth, grant, client, payload):
    enrollment = db.get("enrollments", auth.get("enrollment_id"))
    assert_grant_not_frozen(grant)
    expected = payload.get("expected_service_authorization_version")
    if expected is None or int(expected) != auth.get("version"):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_service_authorization_version does not match the "
            "authorization's current version.",
        )
    units = payload.get("units_delivered")
    rate = payload.get("unit_rate_cents")
    if units is None or rate is None:
        raise ApiError("ERR_BAD_REQUEST", "units_delivered and unit_rate_cents are required.")
    if int(units) < 1:
        raise ApiError("ERR_ZERO_UNITS", "A zero-unit delivery is never billable.")
    now = clock.now()
    if enrollment is None or not enrollment_has_active_authorization(enrollment["id"], now):
        raise ApiError(
            "ERR_NO_ACTIVE_AUTHORIZATION",
            "The enrollment holds no ACTIVE authorization covering the logical clock.",
        )
    service_date = payload.get("service_date")
    delivery = db.create("service_deliveries", {
        "service_authorization_id": auth["id"],
        "grant_id": grant["id"],
        "client_id": client["id"],
        "service_date": clock.parse(service_date) if service_date else now,
        "sequence_no": db.next_delivery_seq(),
        "units_delivered": int(units),
        "unit_rate_cents": int(rate),
        "gross_cost_cents": int(units) * int(rate),
        "allocated_total_cents": 0,
        "admin_total_cents": 0,
        "alternate_disallowed_cents": 0,
        "documentation_status": "INCOMPLETE",
        "status": "DRAFT",
    })
    db.touch(auth)
    return delivery


def _lines(delivery):
    return [
        line for line in db.rows("cost_allocations")
        if line.get("service_delivery_id") == delivery["id"]
    ]


def _grant_amounts(lines):
    """Sum of allocated plus administrative cents per receiving grant."""
    amounts = {}
    for line in lines:
        if line.get("status") not in ("PROVISIONAL", "COMMITTED"):
            continue
        grant_id = line.get("grant_id")
        amounts[grant_id] = amounts.get(grant_id, 0) \
            + line.get("allocated_amount_cents", 0) + line.get("admin_amount_cents", 0)
    return amounts


def document(delivery):
    if delivery.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT delivery may be documented.")
    auth = db.get("service_authorizations", delivery.get("service_authorization_id"))
    enrollment = db.get("enrollments", auth.get("enrollment_id")) if auth else None
    grant = db.get("grants", delivery.get("grant_id"))
    program = db.get("programs", enrollment.get("program_id")) if enrollment else None
    if auth is None or enrollment is None or grant is None:
        raise ApiError("ERR_INVALID_STATE", "The delivery's parent graph does not resolve.")
    units = delivery.get("units_delivered", 0)
    if units < 1:
        raise ApiError("ERR_INVALID_STATE", "A delivery with no units cannot be documented.")
    if auth.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The authorization is not ACTIVE.")
    if units + auth.get("units_delivered", 0) > auth.get("authorized_units", 0):
        raise ApiError(
            "ERR_INVALID_STATE",
            "The delivery exceeds the authorization's remaining authorized units.",
        )
    assert_grant_not_frozen(grant)
    if not _covers(auth, clock.now()):
        raise ApiError(
            "ERR_INVALID_STATE",
            "The logical clock is outside the authorization's usable window.",
        )
    assert_faith_based_ok(grant, program)
    for candidate in allocation.candidate_grants(delivery):
        funder = db.get("funders", candidate.get("funder_id"))
        if funder is None:
            continue
        if candidate.get("admin_rate_pct", 0) > funder.get("max_admin_rate_pct", 0):
            raise ApiError(
                "ERR_ADMIN_RATE_EXCEEDED",
                "Grant %s carries an administrative rate above the funder's ceiling."
                % candidate.get("grant_code"),
            )
    allocation.braid(delivery)
    allocated, admin = allocation.delivery_totals(delivery)
    delivery["gross_cost_cents"] = units * delivery.get("unit_rate_cents", 0)
    delivery["allocated_total_cents"] = allocated
    delivery["admin_total_cents"] = admin
    delivery["documentation_status"] = "COMPLETE"
    delivery["status"] = "DOCUMENTED"
    db.touch(delivery)
    auth["units_delivered"] = auth.get("units_delivered", 0) + units
    if auth["units_delivered"] >= auth.get("authorized_units", 0):
        auth["status"] = "EXHAUSTED"
    db.touch(auth)
    return delivery


def bill(delivery):
    if delivery.get("status") != "DOCUMENTED":
        raise ApiError("ERR_INVALID_STATE", "Only a DOCUMENTED delivery may be billed.")
    if delivery.get("documentation_status") != "COMPLETE":
        raise ApiError("ERR_INVALID_STATE", "The delivery is not fully documented.")
    lines = _lines(delivery)
    amounts = _grant_amounts(lines)
    for grant_id in amounts:
        grant = db.get("grants", grant_id)
        if grant is None or grant.get("status") not in ("OPEN", "THROTTLED"):
            raise ApiError(
                "ERR_GRANT_FROZEN",
                "A receiving grant is FROZEN and refuses this billing.",
            )
    if allocation.disallowance(delivery) > 0:
        raise ApiError(
            "ERR_DUPLICATE_SERVICE_BILLING",
            "Another delivery already bills this client for the same service code "
            "on the same day.",
        )
    for line in lines:
        if line.get("status") == "PROVISIONAL":
            line["status"] = "COMMITTED"
            db.touch(line)
    for grant_id, amount in amounts.items():
        grant = db.get("grants", grant_id)
        grant["obligated_cents"] = grant.get("obligated_cents", 0) - amount
        grant["expended_cents"] = grant.get("expended_cents", 0) + amount
        posture.recompute(grant)
    delivery["status"] = "BILLED"
    db.touch(delivery)
    return delivery


def void(delivery):
    status = delivery.get("status")
    if status not in ("DOCUMENTED", "BILLED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DOCUMENTED or BILLED delivery may be voided.")
    auth = db.get("service_authorizations", delivery.get("service_authorization_id"))
    lines = _lines(delivery)
    amounts = _grant_amounts(lines)
    if status == "DOCUMENTED":
        for line in lines:
            line["status"] = "REVERSED"
            line["allocated_amount_cents"] = 0
            line["admin_amount_cents"] = 0
            line["disallowed_cents"] = 0
            db.touch(line)
        for grant_id, amount in amounts.items():
            grant = db.get("grants", grant_id)
            if grant is None:
                continue
            grant["obligated_cents"] = grant.get("obligated_cents", 0) - amount
            posture.recompute(grant)
        delivery["documentation_status"] = "INCOMPLETE"
        delivery["allocated_total_cents"] = 0
        delivery["admin_total_cents"] = 0
        delivery["status"] = "DRAFT"
    else:
        for line in lines:
            if line.get("status") in ("PROVISIONAL", "COMMITTED"):
                line["status"] = "REVERSED"
                db.touch(line)
        for grant_id, amount in amounts.items():
            grant = db.get("grants", grant_id)
            if grant is None:
                continue
            grant["expended_cents"] = grant.get("expended_cents", 0) - amount
            posture.recompute(grant)
        delivery["status"] = "VOIDED"
    if auth is not None:
        auth["units_delivered"] = max(
            0, auth.get("units_delivered", 0) - delivery.get("units_delivered", 0)
        )
        if auth.get("status") == "EXHAUSTED":
            auth["status"] = "ACTIVE"
        db.touch(auth)
    db.touch(delivery)
    return delivery
