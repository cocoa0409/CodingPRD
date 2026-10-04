"""Membership packages, billing cycles, the balance ledger and training (PRD §3.8 / §3.9)."""

import db
import domain
import validate
from errors import ApiError
from services import core


def create(body, store_id, member_id):
    store = core.require_store(store_id)
    member = core.require_member(member_id)
    if member["home_store_id"] != store_id:
        raise ApiError("ERR_MEMBER_HOME_STORE_MISMATCH")
    body = validate.shape(
        body,
        required=["tier", "member_state_code", "state_sales_tax_rate",
                  "billing_cycle_count", "monthly_fee_cents"],
        optional=[])
    if body["state_sales_tax_rate"] < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    validate.check_backdating(store, member)
    active_same_tier = [p for p in core.member_packages(member_id)
                        if p["tier"] == body["tier"] and p["status"] == "ACTIVE"]
    if active_same_tier:
        raise ApiError("ERR_PACKAGE_ALREADY_ACTIVE")

    tier = body["tier"]
    inclusions = domain.TIER_INCLUSIONS[tier]
    included_total = (inclusions["grooming"] + inclusions["vet"] + inclusions["vaccine"])
    fee = int(body["monthly_fee_cents"])
    if fee == 0:
        fee = domain.DEFAULT_MONTHLY_FEE_CENTS[tier]
    rate = domain.dec(body["state_sales_tax_rate"])
    monthly_total = domain.monthly_total_cents(fee, rate)

    row = db.new_row()
    row.update({
        "member_id": member_id, "member_state_code": body["member_state_code"],
        "tier": tier, "state_sales_tax_rate": domain.json_number(rate),
        "monthly_fee_cents": fee,
        "monthly_total_cents": domain.json_number(monthly_total),
        "total_price_cents": domain.json_number(
            monthly_total * int(body["billing_cycle_count"])),
        "billing_cycle_count": int(body["billing_cycle_count"]),
        "grooming_visits_included": inclusions["grooming"],
        "vet_visits_included": inclusions["vet"],
        "vaccine_visits_included": inclusions["vaccine"],
        "included_visits_total": included_total,
        "consumed_visits": 0, "cycles_consumed": 0,
        "overage_visits": max(0, included_total - domain.TIER_HARD_CAP[tier]),
        "status": "ACTIVE",
    })
    db.add("packages", row)
    # Every prepaid cycle is reserved at subscription time as PENDING, so the
    # package carries its whole repayment schedule and a cancellation can void
    # the cycles that were never billed.
    for index in range(1, int(body["billing_cycle_count"]) + 1):
        cycle = db.new_row()
        cycle.update({
            "package_id": row["id"], "cycle_index": index,
            "cycle_total_cents": 0, "overage_credit_cents": 0,
            "tax_cents": 0, "status": "PENDING",
        })
        db.add("cycles", cycle)
    core.recompute_member_balance(member)
    return row


def advance_cycle(body, store_id, member_id, package_id):
    store = core.require_store(store_id)
    member = core.require_member(member_id)
    pkg = core.require_package(package_id)
    if pkg["member_id"] != member_id:
        raise ApiError("ERR_PACKAGE_NOT_FOUND")
    body = validate.shape(
        body,
        required=["expected_package_version"],
        optional=["grooming_visits_consumed", "vet_visits_consumed",
                  "vaccine_visits_consumed"])
    validate.check_backdating(store, member, pkg)
    if pkg["status"] != "ACTIVE":
        raise ApiError("ERR_PACKAGE_NOT_ACTIVE")
    validate.require_expected(body, pkg["version"], "expected_package_version")

    grooming = int(body.get("grooming_visits_consumed") or 0)
    vet = int(body.get("vet_visits_consumed") or 0)
    vaccine = int(body.get("vaccine_visits_consumed") or 0)
    if min(grooming, vet, vaccine) < 0:
        raise ApiError("ERR_INVALID_REQUEST")

    pre_tax = (grooming * domain.GROOMING_VISIT_CREDIT_CENTS
               + vet * domain.VET_VISIT_CREDIT_CENTS
               + vaccine * domain.VACCINE_VISIT_CREDIT_CENTS)
    consumed = grooming + vet + vaccine
    overage_visits = max(0, consumed - pkg["included_visits_total"])
    overage_credit = overage_visits * domain.OVERAGE_CREDIT_CENTS
    total, tax = domain.cycle_totals(pre_tax, overage_credit, pkg["state_sales_tax_rate"])

    next_index = pkg["cycles_consumed"] + 1
    row = None
    for candidate in core.package_cycles(pkg["id"]):
        if candidate["cycle_index"] == next_index and candidate["status"] == "PENDING":
            row = candidate
            break
    if row is None:
        row = db.new_row()
        row.update({"package_id": pkg["id"], "cycle_index": next_index,
                    "cycle_total_cents": 0, "overage_credit_cents": 0,
                    "tax_cents": 0, "status": "PENDING"})
        db.add("cycles", row)
    row["cycle_total_cents"] = domain.json_number(total)
    row["overage_credit_cents"] = overage_credit
    row["tax_cents"] = domain.json_number(tax)
    # PENDING -> BILLED as part of the same operation
    row["status"] = "BILLED"
    db.touch(row)

    pkg["cycles_consumed"] += 1
    pkg["consumed_visits"] += consumed
    db.touch(pkg)
    # The caller's next write is against the package, so the response carries the
    # package's post-advance version as the row's version (the cycle itself is
    # billed in the same operation that creates it).
    row["version"] = pkg["version"]
    member = core.require_member(pkg["member_id"])
    core.recompute_member_balance(member)
    return row


def pause(body, store_id, member_id, package_id):
    return _lifecycle(body, store_id, member_id, package_id, "ACTIVE", "PAUSED",
                      "ERR_PACKAGE_NOT_ACTIVE")


def resume(body, store_id, member_id, package_id):
    return _lifecycle(body, store_id, member_id, package_id, "PAUSED", "ACTIVE",
                      "ERR_PACKAGE_NOT_PAUSED")


def _lifecycle(body, store_id, member_id, package_id, required, target, error_id):
    store = core.require_store(store_id)
    member = core.require_member(member_id)
    pkg = core.require_package(package_id)
    if pkg["member_id"] != member_id:
        raise ApiError("ERR_PACKAGE_NOT_FOUND")
    body = validate.shape(body, required=["expected_package_version"], optional=[])
    validate.check_backdating(store, member, pkg)
    if pkg["status"] != required:
        raise ApiError(error_id)
    validate.require_expected(body, pkg["version"], "expected_package_version")
    pkg["status"] = target
    db.touch(pkg)
    return pkg


def cancel(body, store_id, member_id, package_id):
    store = core.require_store(store_id)
    member = core.require_member(member_id)
    pkg = core.require_package(package_id)
    if pkg["member_id"] != member_id:
        raise ApiError("ERR_PACKAGE_NOT_FOUND")
    body = validate.shape(body, required=["expected_package_version"], optional=[])
    validate.check_backdating(store, member, pkg)
    # cancellation is reachable only from PAUSED
    if pkg["status"] != "PAUSED":
        raise ApiError("ERR_PACKAGE_NOT_PAUSED")
    validate.require_expected(body, pkg["version"], "expected_package_version")

    for cycle in core.package_cycles(pkg["id"]):
        if cycle["status"] == "PENDING":
            cycle["status"] = "VOID"
            db.touch(cycle)
    for enrollment in core.package_enrollments(pkg["id"]):
        if enrollment["status"] in ("PENDING_ACK", "RESTRICTED", "IN_PROGRESS"):
            enrollment["status"] = "CANCELLED"
            db.touch(enrollment)
    pkg["status"] = "CANCELLED"
    db.touch(pkg)
    core.recompute_training_slots(store, touch_row=True)
    member = core.require_member(pkg["member_id"])
    core.recompute_member_balance(member)
    return pkg


# ---------------------------------------------------------------------------
# training enrollments (§3.9)
# ---------------------------------------------------------------------------

def create_enrollment(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["package_id", "pet_id", "class_code"],
                          optional=["courses_required"])
    pkg = core.require_package(body["package_id"])
    pet = core.require_pet(body["pet_id"])
    member = core.require_member(pkg["member_id"])
    if pet["member_id"] != member["id"]:
        raise ApiError("ERR_PET_MEMBER_MISMATCH")
    validate.check_backdating(store, pkg, pet)
    courses_required = int(body.get("courses_required") or 1)
    if courses_required < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    row = db.new_row()
    row.update({
        "package_id": pkg["id"], "store_id": store_id, "pet_id": pet["id"],
        "class_code": body["class_code"], "courses_required": courses_required,
        "courses_completed": 0, "courses_needed": courses_required,
        "status": "PENDING_ACK",
    })
    db.add("enrollments", row)
    core.recompute_training_slots(store, touch_row=True)
    return row


def _load_enrollment(store_id, enrollment_id):
    core.require_store(store_id)
    enrollment = core.require_enrollment(enrollment_id)
    if enrollment["store_id"] != store_id:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND")
    return enrollment


def _courses_needed(enrollment):
    return max(0, enrollment["courses_required"] - enrollment["courses_completed"])


def _maybe_complete(enrollment, store):
    enrollment["courses_needed"] = _courses_needed(enrollment)
    if enrollment["courses_needed"] == 0 and enrollment["status"] in ("PENDING_ACK", "RESTRICTED", "IN_PROGRESS"):
        enrollment["status"] = "COMPLETED"
        db.touch(enrollment)
        core.recompute_training_slots(store, touch_row=True)


def begin_course(body, store_id, enrollment_id):
    store = core.require_store(store_id)
    enrollment = _load_enrollment(store_id, enrollment_id)
    body = validate.shape(body, required=["expected_enrollment_version"], optional=[])
    pkg = core.require_package(enrollment["package_id"])
    pet = core.require_pet(enrollment["pet_id"])
    validate.check_backdating(store, enrollment, pkg, pet)
    if enrollment["status"] != "PENDING_ACK":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    if pkg["status"] != "ACTIVE":
        raise ApiError("ERR_PACKAGE_NOT_ACTIVE")
    if pet["status"] != "ACTIVE":
        raise ApiError("ERR_PET_ARCHIVED")
    if store["hospital_posture"] == "FROZEN":
        raise ApiError("ERR_STORE_HOSPITAL_FROZEN")
    validate.require_expected(body, enrollment["version"], "expected_enrollment_version")
    enrollment["status"] = "RESTRICTED"
    db.touch(enrollment)
    core.recompute_training_slots(store, touch_row=True)
    return enrollment


def return_to_ack(body, store_id, enrollment_id):
    store = core.require_store(store_id)
    enrollment = _load_enrollment(store_id, enrollment_id)
    body = validate.shape(body, required=["expected_enrollment_version"], optional=[])
    validate.check_backdating(store, enrollment)
    if enrollment["status"] != "RESTRICTED":
        raise ApiError("ERR_ENROLLMENT_NOT_RESTRICTED")
    validate.require_expected(body, enrollment["version"], "expected_enrollment_version")
    enrollment["status"] = "PENDING_ACK"
    db.touch(enrollment)
    core.recompute_training_slots(store, touch_row=True)
    return enrollment


def start_course(body, store_id, enrollment_id):
    store = core.require_store(store_id)
    enrollment = _load_enrollment(store_id, enrollment_id)
    body = validate.shape(body, required=["expected_enrollment_version"], optional=[])
    validate.check_backdating(store, enrollment)
    if enrollment["status"] not in ("PENDING_ACK", "RESTRICTED"):
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    if _courses_needed(enrollment) < 1:
        raise ApiError("ERR_COURSES_ALREADY_COMPLETE")
    validate.require_expected(body, enrollment["version"], "expected_enrollment_version")
    enrollment["status"] = "IN_PROGRESS"
    enrollment["courses_needed"] = _courses_needed(enrollment)
    db.touch(enrollment)
    _maybe_complete(enrollment, store)
    return enrollment


def revert_course(body, store_id, enrollment_id):
    store = core.require_store(store_id)
    enrollment = _load_enrollment(store_id, enrollment_id)
    body = validate.shape(body, required=["expected_enrollment_version"], optional=[])
    validate.check_backdating(store, enrollment)
    if enrollment["status"] != "IN_PROGRESS":
        raise ApiError("ERR_ENROLLMENT_NOT_IN_PROGRESS")
    validate.require_expected(body, enrollment["version"], "expected_enrollment_version")
    enrollment["status"] = "PENDING_ACK"
    enrollment["courses_needed"] = _courses_needed(enrollment)
    db.touch(enrollment)
    core.recompute_training_slots(store, touch_row=True)
    return enrollment


def record_progress(body, store_id, enrollment_id):
    """Advance the completed-course count; reaching the requirement completes it."""
    store = core.require_store(store_id)
    enrollment = _load_enrollment(store_id, enrollment_id)
    body = validate.shape(body, required=["courses_completed"],
                          optional=["expected_enrollment_version"])
    validate.check_backdating(store, enrollment)
    completed = int(body["courses_completed"])
    if completed < 0 or completed > enrollment["courses_required"]:
        raise ApiError("ERR_INVALID_REQUEST")
    if "expected_enrollment_version" in body and body["expected_enrollment_version"] is not None:
        if int(body["expected_enrollment_version"]) != enrollment["version"]:
            raise ApiError("ERR_STALE_VERSION")
    enrollment["courses_completed"] = completed
    enrollment["courses_needed"] = _courses_needed(enrollment)
    db.touch(enrollment)
    _maybe_complete(enrollment, store)
    core.recompute_training_slots(store, touch_row=True)
    return enrollment