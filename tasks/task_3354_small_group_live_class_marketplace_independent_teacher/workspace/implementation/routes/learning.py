"""Learner accounts, subscriptions, seat reservation and enrollment lifecycle."""

from datetime import timedelta

from flask import Blueprint, request

from core import auth, clock, constants as C, envelope, store
from core.errors import fail
from services import calc, cascades, views

from .common import api, resolve, resolve_listing, resolve_section

bp = Blueprint("learning", __name__)


def age_at(birth, instant):
    years = instant.year - birth.year
    if (instant.month, instant.day) < (birth.month, birth.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Learner
# ---------------------------------------------------------------------------
@bp.post("/outschool/learners")
@api(["Parent", "PlatformAdmin"])
def create_learner(role, user_id):
    data = auth.body()
    auth.require_fields(data, ["display_name", "birth_date", "parent_user_id"])
    birth = clock.try_parse_datetime(data["birth_date"])
    if birth is None:
        fail("ERR_LEARNER_AGE_OUT_OF_RANGE", "birth_date must be an ISO 8601 date")
    if not (birth < clock.CURRENT_DEFAULT_UTC):
        fail("ERR_LEARNER_AGE_OUT_OF_RANGE", "A birth date must lie before 2026-09-01T00:00:00Z")
    learner = store.make_record(
        "learners",
        display_name=data["display_name"],
        birth_date_raw=data["birth_date"],
        birth_date_dt=birth,
        parent_user_id=data["parent_user_id"],
        subscription_tier="NONE",
        confirmation_credit_cents=0,
        enrollment_sequence=0,
        abuse_strike_count=0,
    )
    return envelope.Result(201, views.learner_out(learner))


@bp.get("/outschool/learners/<learner_id>")
@api(["Parent", "PlatformAdmin"])
def get_learner(role, user_id, learner_id):
    learner = resolve("learners", learner_id, "Learner")
    return envelope.Result(200, views.learner_out(learner))


@bp.post("/outschool/learners/<learner_id>/subscription")
@api(["Parent", "PlatformAdmin"])
def set_subscription(role, user_id, learner_id):
    learner = resolve("learners", learner_id, "Learner")
    data = auth.body()
    auth.require_fields(data, ["subscription_tier"])
    tier = auth.require_enum(data, "subscription_tier", ("NONE", "PLUS", "FAMILY"))
    learner["subscription_tier"] = tier
    learner["confirmation_credit_cents"] = C.SUBSCRIPTION_INCLUDED_CREDIT_CENTS[tier]
    store.touch(learner)
    return envelope.Result(200, views.learner_out(learner))


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
@bp.post("/outschool/class-listings/<listing_id>/sections/<section_id>/enrollments")
@api(["Parent", "PlatformAdmin"])
def create_enrollment(role, user_id, listing_id, section_id):
    listing = resolve_listing(listing_id)
    section = resolve_section(listing, section_id)
    data = auth.body()
    learner_id = data.get("learner_id")
    if auth.is_blank(learner_id):
        fail("ERR_MISSING_REQUIRED_FIELD", "Field 'learner_id' is required")
    learner = store.find("learners", learner_id)
    if learner is None:
        fail("ERR_REFERENTIAL_INTEGRITY", "The referenced learner does not exist")

    birth = learner["birth_date_dt"]
    age = age_at(birth, section["start_utc_dt"])
    if not (birth < clock.CURRENT_DEFAULT_UTC):
        fail("ERR_LEARNER_AGE_OUT_OF_RANGE", "The learner's birth date is not in the past")
    if age < listing["min_age"] or age > listing["max_age"]:
        fail("ERR_LEARNER_AGE_OUT_OF_RANGE", "The learner's age falls outside the listing's age band")

    teacher = store.find("teachers", listing["teacher_id"])
    if teacher is not None and teacher["status"] in ("SUSPENDED", "TERMINATED"):
        fail("ERR_TEACHER_SUSPENDED", "The owning teacher is not in good standing")

    occ = calc.occupancy(section)
    if occ["seats_remaining"] <= 0:
        fail("ERR_SECTION_FULL", "The section has no remaining seats")

    if not (section["start_utc_dt"] > clock.now()):
        fail("ERR_SECTION_ALREADY_STARTED", "The section has already started")

    for existing in calc.enrollments_of_section(section["id"]):
        if existing["learner_id"] != learner["id"]:
            continue
        if existing["status"] in ("RESERVED", "PENDING_CONFIRMATION", "CONFIRMED"):
            fail("ERR_DUPLICATE_ENROLLMENT", "This learner already holds an enrollment on this section")

    coupon_code = data.get("coupon_code")
    if not auth.is_blank(coupon_code):
        if coupon_code not in C.CATALOG_COUPONS:
            fail("ERR_COUPON_NOT_FOUND", "Unknown coupon code")
        for existing in store.all_of("enrollments"):
            if (
                existing["learner_id"] == learner["id"]
                and existing["coupon_code"] == coupon_code
                and existing["status"] == "CONFIRMED"
            ):
                fail("ERR_COUPON_ALREADY_REDEEMED", "This learner has already redeemed that coupon")
    else:
        coupon_code = None

    auth.require_parent_owner(role, user_id, learner)

    price = calc.enrollment_price(listing, learner, coupon_code)
    enrollment = store.make_record(
        "enrollments",
        section_id=section["id"],
        learner_id=learner["id"],
        status="RESERVED",
        coupon_code=coupon_code,
        subscription_discount_cents=price["subscription_discount_cents"],
        coupon_discount_cents=price["coupon_discount_cents"],
        discounted_price_cents=price["discounted_price_cents"],
        refund_category=None,
        refund_cents=0,
        cancelled_by=None,
        credit_applied_cents=0,
        cash_refund_cents=0,
    )
    learner["enrollment_sequence"] += 1
    store.touch(learner)
    store.touch(section)
    return envelope.Result(201, views.enrollment_out(enrollment))


@bp.get("/outschool/enrollments/<enrollment_id>")
@api(["Parent", "Teacher", "PlatformAdmin"])
def get_enrollment(role, user_id, enrollment_id):
    enrollment = resolve("enrollments", enrollment_id, "Enrollment")
    return envelope.Result(200, views.enrollment_out(enrollment))


@bp.get("/outschool/enrollments")
@api(["Parent", "Teacher", "PlatformAdmin"])
def list_enrollments(role, user_id):
    items = store.by_created(store.all_of("enrollments"))
    for field in ("learner_id", "section_id", "status"):
        value = request.args.get(field)
        if value:
            items = [x for x in items if x.get(field) == value]
    return envelope.paged([views.enrollment_out(x) for x in items], request.args)


@bp.post("/outschool/enrollments/<enrollment_id>/confirm")
@api(["Parent", "PlatformAdmin"])
def confirm_enrollment(role, user_id, enrollment_id):
    enrollment = resolve("enrollments", enrollment_id, "Enrollment")
    if enrollment["status"] != "RESERVED":
        fail("ERR_INVALID_STATE", "Only a RESERVED enrollment may be confirmed")
    section = store.find("sections", enrollment["section_id"])
    if section is None or section["status"] != "MIN_ENROLLMENT_MET":
        fail("ERR_INVALID_STATE", "The section has not reached MIN_ENROLLMENT_MET")
    learner = store.find("learners", enrollment["learner_id"])
    if learner["confirmation_credit_cents"] < enrollment["discounted_price_cents"]:
        fail("ERR_CREDIT_INSUFFICIENT", "The learner's confirmation credit is insufficient")
    auth.require_parent_owner(role, user_id, learner)
    enrollment["status"] = "CONFIRMED"
    store.touch(enrollment)
    learner["confirmation_credit_cents"] -= enrollment["discounted_price_cents"]
    store.touch(learner)
    store.touch(section)
    return envelope.Result(200, views.enrollment_out(enrollment))


@bp.post("/outschool/enrollments/<enrollment_id>/cancel")
@api(["Parent", "PlatformAdmin"])
def cancel_enrollment(role, user_id, enrollment_id):
    enrollment = resolve("enrollments", enrollment_id, "Enrollment")
    if enrollment["status"] not in ("RESERVED", "CONFIRMED"):
        fail("ERR_INVALID_STATE", "This enrollment may not be cancelled")
    section = store.find("sections", enrollment["section_id"])
    listing = calc.listing_of_section(section) if section else None
    if enrollment["status"] == "CONFIRMED" and not (clock.now() < section["start_utc_dt"]):
        fail("ERR_INVALID_STATE", "A confirmed enrollment may only be cancelled before the section starts")
    learner = store.find("learners", enrollment["learner_id"])
    auth.require_parent_owner(role, user_id, learner)

    was_confirmed = enrollment["status"] == "CONFIRMED"
    original_total = calc.section_discounted_total(section["id"])
    cutoff = section["start_utc_dt"] - timedelta(hours=C.AUTO_CANCEL_CUTOFF_HOURS)
    learner_fault = clock.now() < cutoff
    tier = calc.refund_tier(section, listing, clock.now(), learner_fault)
    enrollment["status"] = "CANCELLED_BY_TEACHER"
    cascades.write_refund(enrollment, learner, tier, "parent")
    if learner_fault:
        learner["abuse_strike_count"] += 1
        store.touch(learner)

    teacher = store.find("teachers", listing["teacher_id"]) if listing else None
    seat_loss = False
    if was_confirmed and not learner_fault:
        if teacher is not None:
            cascades.teacher_fault_clawback(teacher, [(section, original_total)])
        occ = calc.occupancy(section)
        if (
            section["status"] in ("OPEN_FOR_ENROLLMENT", "MIN_ENROLLMENT_MET")
            and clock.now() < section["start_utc_dt"]
            and occ["enrolled_count"] < section["min_learners"]
        ):
            seat_loss = True
            cascades.cancel_section_and_enrollments(
                section, "AUTO_CANCELLED_SEAT_LOSS", "platform", "CANCELLED_BY_TEACHER", "FULL"
            )
            if teacher is not None:
                cascades.teacher_fault_clawback(teacher, [(section, original_total)])
    if not seat_loss and section["status"] == "MIN_ENROLLMENT_MET":
        occ = calc.occupancy(section)
        if occ["enrolled_count"] < section["min_learners"]:
            section["status"] = "OPEN_FOR_ENROLLMENT"
            store.touch(section)
    return envelope.Result(200, views.enrollment_out(enrollment))
