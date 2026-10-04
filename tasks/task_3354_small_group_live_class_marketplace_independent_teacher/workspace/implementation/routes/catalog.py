"""ClassListing and Section endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from core import auth, clock, constants as C, envelope, store
from core.errors import fail
from services import calc, cascades, views

from .common import api, resolve, resolve_listing, resolve_section

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# ClassListing
# ---------------------------------------------------------------------------
@bp.post("/outschool/class-listings")
@api(["Teacher", "PlatformAdmin"])
def create_listing(role, user_id):
    data = auth.body()
    teacher = store.find("teachers", data.get("teacher_id"))
    if teacher is None:
        fail("ERR_REFERENTIAL_INTEGRITY", "The referenced teacher does not exist")
    min_age = data.get("min_age")
    max_age = data.get("max_age")
    if isinstance(min_age, int) and isinstance(max_age, int):
        if min_age < 3 or max_age > 18 or min_age > max_age:
            fail("ERR_INVALID_AGE_BAND", "min_age >= 3, max_age <= 18 and min_age <= max_age")
    auth.require_fields(
        data,
        ["teacher_id", "title", "format", "min_age", "max_age", "max_learners", "list_price_cents"],
    )
    auth.require_enum(data, "format", C.FORMATS)
    max_learners = auth.require_int(data, "max_learners", 1, 18)
    auth.require_int(data, "min_age", 3, 18)
    auth.require_int(data, "max_age", 3, 18)
    price = auth.require_int(data, "list_price_cents", 1)
    sequence = 0
    for existing in store.all_of("listings"):
        if existing["teacher_id"] == teacher["id"]:
            sequence = max(sequence, existing["listing_sequence"])
    listing = store.make_record(
        "listings",
        teacher_id=teacher["id"],
        title=data["title"],
        format=data["format"],
        min_age=min_age,
        max_age=max_age,
        max_learners=max_learners,
        list_price_cents=price,
        content_review_state="PENDING_REVIEW",
        policy_rejection_reason_code=None,
        lifecycle_state="DRAFT",
        listing_sequence=sequence + 1,
    )
    return envelope.Result(201, views.listing_out(listing))


@bp.get("/outschool/class-listings/<listing_id>")
@api(["Teacher", "TeacherReviewer", "Parent", "PlatformAdmin"])
def get_listing(role, user_id, listing_id):
    listing = resolve_listing(listing_id)
    return envelope.Result(200, views.listing_out(listing))


@bp.get("/outschool/class-listings")
@api(["Teacher", "TeacherReviewer", "Parent", "PlatformAdmin"])
def list_listings(role, user_id):
    items = store.by_created(store.all_of("listings"))
    for field in ("teacher_id", "lifecycle_state", "content_review_state", "format"):
        value = request.args.get(field)
        if value:
            items = [x for x in items if x.get(field) == value]
    return envelope.paged([views.listing_out(x) for x in items], request.args)


@bp.post("/outschool/class-listings/<listing_id>/policy-review")
@api(["PlatformAdmin"])
def policy_review(role, user_id, listing_id):
    listing = resolve_listing(listing_id)
    if listing["content_review_state"] != "PENDING_REVIEW":
        fail("ERR_INVALID_STATE", "This listing is not awaiting content review")
    if listing["min_age"] < 3 or listing["max_age"] > 18 or listing["min_age"] > listing["max_age"]:
        fail("ERR_INVALID_AGE_BAND", "min_age >= 3, max_age <= 18 and min_age <= max_age")
    data = auth.body()
    auth.require_fields(data, ["decision"])
    decision = auth.require_enum(data, "decision", ("APPROVE", "REJECT"))
    reason = data.get("reason_code")
    if reason is not None and reason not in C.POLICY_REJECTION_REASONS:
        fail("ERR_INVALID_ENUM_VALUE", "reason_code must be AGE_MISMATCH, CONTENT_POLICY or PRICING_POLICY")
    if decision == "APPROVE":
        listing["content_review_state"] = "POLICY_APPROVED"
    else:
        listing["content_review_state"] = "POLICY_REJECTED"
        listing["policy_rejection_reason_code"] = reason
        listing["lifecycle_state"] = "ARCHIVED"
        store.touch(listing)
        cascades.archive_listing_sections(listing)
    store.touch(listing)
    return envelope.Result(200, views.listing_out(listing))


@bp.post("/outschool/class-listings/<listing_id>/publish")
@api(["Teacher", "PlatformAdmin"])
def publish_listing(role, user_id, listing_id):
    listing = resolve_listing(listing_id)
    if listing["lifecycle_state"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT listing may be published")
    if listing["content_review_state"] != "POLICY_APPROVED":
        fail("ERR_INVALID_STATE", "The listing has not passed content review")
    auth.require_teacher_owner(role, user_id, listing["teacher_id"])
    teacher = store.find("teachers", listing["teacher_id"])
    cascades.require_active_teacher(teacher, role)
    listing["lifecycle_state"] = "PUBLISHED"
    store.touch(listing)
    return envelope.Result(200, views.listing_out(listing))


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------
@bp.post("/outschool/class-listings/<listing_id>/sections")
@api(["Teacher", "PlatformAdmin"])
def create_section(role, user_id, listing_id):
    listing = resolve_listing(listing_id)
    if listing["lifecycle_state"] == "ARCHIVED":
        fail("ERR_REFERENTIAL_INTEGRITY", "The parent listing is archived")
    data = auth.body()
    start_raw = data.get("start_utc")
    end_raw = data.get("end_utc")
    start_dt = clock.try_parse_datetime(start_raw)
    end_dt = clock.try_parse_datetime(end_raw)
    if start_dt is None or end_dt is None:
        if start_raw is None or end_raw is None:
            auth.require_fields(data, ["timezone", "start_utc", "end_utc", "min_learners", "capacity"])
        fail("ERR_INVALID_TIME_WINDOW", "start_utc and end_utc must be ISO 8601 instants")
    if not (start_dt < end_dt) or start_dt <= clock.CURRENT_DEFAULT_UTC or end_dt <= clock.CURRENT_DEFAULT_UTC:
        fail("ERR_INVALID_TIME_WINDOW", "start_utc must precede end_utc and both must follow 2026-09-01T00:00:00Z")
    capacity = data.get("capacity")
    min_learners = data.get("min_learners")
    if isinstance(capacity, int) and isinstance(min_learners, int):
        if capacity < 1 or capacity > 18 or capacity > listing["max_learners"] or min_learners > capacity:
            fail("ERR_CAPACITY_EXCEEDS_LISTING", "capacity must fit the listing's max_learners and min_learners must fit capacity")
    if listing["content_review_state"] != "POLICY_APPROVED":
        fail("ERR_LISTING_NOT_APPROVED", "Sections may only be scheduled under a POLICY_APPROVED listing")
    auth.require_fields(data, ["timezone", "start_utc", "end_utc", "min_learners", "capacity"])
    capacity = auth.require_int(data, "capacity", 1, 18)
    min_learners = auth.require_int(data, "min_learners", 1)
    if capacity > listing["max_learners"] or min_learners > capacity:
        fail("ERR_CAPACITY_EXCEEDS_LISTING", "capacity must fit the listing's max_learners and min_learners must fit capacity")
    expected = data.get("expected_learners")
    if expected is not None:
        expected = auth.require_int(data, "expected_learners", 0)
    section = store.make_record(
        "sections",
        class_listing_id=listing["id"],
        timezone=data["timezone"],
        start_utc_raw=start_raw,
        end_utc_raw=end_raw,
        start_utc_dt=start_dt,
        end_utc_dt=end_dt,
        min_learners=min_learners,
        capacity=capacity,
        expected_learners=expected,
        status="SCHEDULED",
        outcome=None,
    )
    return envelope.Result(201, views.section_out(section))


@bp.get("/outschool/class-listings/<listing_id>/sections")
@api(["Teacher", "Parent", "TeacherReviewer", "PlatformAdmin"])
def list_sections(role, user_id, listing_id):
    listing = resolve_listing(listing_id)
    items = [
        s for s in store.by_created(store.all_of("sections"))
        if s["class_listing_id"] == listing["id"]
    ]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return envelope.paged([views.section_out(s) for s in items], request.args)


@bp.post("/outschool/class-listings/<listing_id>/sections/<section_id>/open")
@api(["Teacher", "PlatformAdmin"])
def open_section(role, user_id, listing_id, section_id):
    listing = resolve_listing(listing_id)
    section = resolve_section(listing, section_id)
    if section["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED section may be opened")
    auth.require_teacher_owner(role, user_id, listing["teacher_id"])
    teacher = store.find("teachers", listing["teacher_id"])
    cascades.require_active_teacher(teacher, role)
    if listing["lifecycle_state"] != "PUBLISHED":
        fail("ERR_LISTING_NOT_PUBLISHED", "The parent listing is not PUBLISHED")
    if listing["content_review_state"] != "POLICY_APPROVED":
        fail("ERR_INVALID_STATE", "The parent listing has not passed content review")
    section["status"] = "OPEN_FOR_ENROLLMENT"
    store.touch(section)
    return envelope.Result(200, views.section_out(section))


@bp.post("/outschool/class-listings/<listing_id>/sections/<section_id>/meet-minimum")
@api(["Teacher", "PlatformAdmin"])
def meet_minimum(role, user_id, listing_id, section_id):
    listing = resolve_listing(listing_id)
    section = resolve_section(listing, section_id)
    if section["status"] != "OPEN_FOR_ENROLLMENT":
        fail("ERR_SECTION_NOT_OPEN", "The section is not OPEN_FOR_ENROLLMENT")
    occ = calc.occupancy(section)
    if not occ["enrollment_min_met"]:
        fail("ERR_MIN_ENROLLMENT_NOT_MET", "Confirmed enrollment has not reached min_learners")
    section["status"] = "MIN_ENROLLMENT_MET"
    store.touch(section)
    return envelope.Result(200, views.section_out(section))


@bp.post("/outschool/class-listings/<listing_id>/sections/<section_id>/cancel")
@api(["Teacher", "PlatformAdmin"])
def cancel_section(role, user_id, listing_id, section_id):
    listing = resolve_listing(listing_id)
    section = resolve_section(listing, section_id)
    if section["status"] not in ("SCHEDULED", "OPEN_FOR_ENROLLMENT", "MIN_ENROLLMENT_MET"):
        fail("ERR_INVALID_STATE", "This section may not be cancelled")
    if not (clock.now() < section["start_utc_dt"]):
        fail("ERR_INVALID_STATE", "A section may only be cancelled before it starts")
    auth.require_teacher_owner(role, user_id, listing["teacher_id"])
    teacher = store.find("teachers", listing["teacher_id"])
    cascades.require_active_teacher(teacher, role)

    original_total = sum(
        e["discounted_price_cents"]
        for e in calc.enrollments_of_section(section["id"])
        if e["status"] in ("RESERVED", "CONFIRMED")
    )
    cascades.cancel_section_and_enrollments(
        section, "CANCELLED_BY_TEACHER", "teacher", "CANCELLED_BY_TEACHER", "FULL"
    )
    if teacher is not None:
        cascades.teacher_fault_clawback(teacher, [(section, original_total)])
    return envelope.Result(200, views.section_out(section))
