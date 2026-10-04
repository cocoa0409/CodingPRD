"""Donation request endpoints: create, match, fulfill, cancel."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles
from response import object_response
from services import (
    new_record, touch, serialize_donation, school_posture, title_license_status,
    accrue_royalty, parse_month,
)
from routes.common import get_body, path_get, ref_get, req_field, req_int

bp = Blueprint("donations", __name__)


@bp.post("/club/donation-requests")
@require_roles("Teacher", "SchoolAdmin")
def create_donation():
    body = get_body()
    school_id = req_field(body, "school_id")
    teacher_id = req_field(body, "teacher_id")
    title_id = req_field(body, "title_id")
    qty = req_int(body, "qty_requested")
    school = ref_get(db.schools, school_id, "School")
    teacher = ref_get(db.teachers, teacher_id, "Teacher")
    title = ref_get(db.titles, title_id, "Title")
    if qty < 1:
        raise_err("ERR_INVALID_REQUEST", "qty_requested must be >= 1")
    if title_license_status(title) != "ACTIVE":
        raise_err("ERR_LICENSE_SUSPENDED", "Title license is SUSPENDED")
    if not school["low_income_program"]:
        raise_err("ERR_NOT_LOW_INCOME", "School is not in the low-income program")
    donation = new_record({
        "school_id": school_id,
        "teacher_id": teacher_id,
        "title_id": title_id,
        "qty_requested": qty,
        "qty_matched": None,
        "status": "OPEN",
    })
    db.donation_requests[donation["id"]] = donation
    return object_response(serialize_donation(donation), 201)


@bp.get("/club/donation-requests/<did>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Donor")
def get_donation(did):
    return object_response(serialize_donation(path_get(db.donation_requests, did, "DonationRequest")))


@bp.post("/club/donation-requests/<did>/match")
@require_roles("Donor")
def match_donation(did):
    donation = path_get(db.donation_requests, did, "DonationRequest")
    if donation["status"] in ("FULFILLED", "CANCELLED"):
        raise_err("ERR_ALREADY_TERMINAL", "DonationRequest is %s" % donation["status"])
    if donation["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Match requires status OPEN")
    school = db.schools.get(donation["school_id"])
    if school is not None and school_posture(school["id"]) != "NORMAL":
        raise_err("ERR_SCHOOL_RESTRICTED", "School posture is RESTRICTED")
    title = db.titles.get(donation["title_id"])
    if title is not None and title_license_status(title) != "ACTIVE":
        raise_err("ERR_LICENSE_SUSPENDED", "Title license is SUSPENDED")
    donation["qty_matched"] = donation["qty_requested"]
    donation["status"] = "MATCHED"
    touch(donation)
    return object_response(serialize_donation(donation))


@bp.post("/club/donation-requests/<did>/fulfill")
@require_roles("ClubAdmin")
def fulfill_donation(did):
    donation = path_get(db.donation_requests, did, "DonationRequest")
    if donation["status"] in ("FULFILLED", "CANCELLED"):
        raise_err("ERR_ALREADY_TERMINAL", "DonationRequest is %s" % donation["status"])
    if donation["status"] != "MATCHED":
        raise_err("ERR_DONATION_NOT_MATCHED", "Fulfill requires status MATCHED")
    title = db.titles.get(donation["title_id"])
    if title is not None and title_license_status(title) != "ACTIVE":
        raise_err("ERR_LICENSE_SUSPENDED", "Title license is SUSPENDED")

    teacher = db.teachers[donation["teacher_id"]]
    school_id = donation["school_id"]
    qty = donation["qty_matched"]

    # Find or force-create a PUBLISHED cycle for (school, teacher.grade_band).
    cycle = None
    for c in db.flyer_cycles.values():
        if (c["school_id"] == school_id and c["grade_band"] == teacher["grade_band"]
                and c["status"] == "PUBLISHED"):
            cycle = c
            break
    if cycle is None:
        month = db.clock.date.strftime("%Y-%m")
        cycle = new_record({
            "school_id": school_id,
            "month": month,
            "grade_band": teacher["grade_band"],
            "status": "DRAFT",
        })
        db.flyer_cycles[cycle["id"]] = cycle
        # System-forced publish bypasses offering_count >= 1.
        cycle["status"] = "PUBLISHED"
        touch(cycle)
        # Offering for this title so the line can reference it (price 0 pinned below anyway).
        offering = new_record({
            "cycle_id": cycle["id"],
            "title_id": donation["title_id"],
            "flyer_price_cents": 0,
        })
        db.offerings[offering["id"]] = offering
    else:
        offering = None
        for o in db.offerings.values():
            if o["cycle_id"] == cycle["id"] and o["title_id"] == donation["title_id"]:
                offering = o
                break
        if offering is None:
            offering = new_record({
                "cycle_id": cycle["id"],
                "title_id": donation["title_id"],
                "flyer_price_cents": 0,
            })
            db.offerings[offering["id"]] = offering

    order = new_record({
        "cycle_id": cycle["id"],
        "teacher_id": teacher["id"],
        "status": "SUBMITTED",
        "ship_status": "PENDING",
        "points_status": "UNAWARDED",
        "subtotal_cents": 0,
        "rewardable_subtotal_cents": 0,
        "discount_cents": 0,
        "net_total_cents": 0,
        "shipping_fee_cents": 0,
        "awarded_base_points": 0,
        "awarded_bonus_points": 0,
        "awarded_total_points": 0,
    })
    db.class_orders[order["id"]] = order
    line = new_record({
        "class_order_id": order["id"],
        "offering_id": offering["id"],
        "student_name": "DONATION",
        "submitted_by": "TEACHER",
        "qty": qty,
        "unit_price_cents": 0,
        "fair_overlap": False,
        "donation_funded": True,
        "status": "ACTIVE",
        "points_earned": 0,
    })
    db.order_lines[line["id"]] = line

    teacher["donated_books_received"] += qty
    touch(teacher)
    accrue_royalty(title, qty)

    donation["status"] = "FULFILLED"
    touch(donation)
    return object_response(serialize_donation(donation))


@bp.post("/club/donation-requests/<did>/cancel")
@require_roles("SchoolAdmin", "ClubAdmin")
def cancel_donation(did):
    donation = path_get(db.donation_requests, did, "DonationRequest")
    if donation["status"] in ("FULFILLED", "CANCELLED"):
        raise_err("ERR_ALREADY_TERMINAL", "DonationRequest is %s" % donation["status"])
    if donation["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Cancel requires status OPEN")
    donation["status"] = "CANCELLED"
    touch(donation)
    return object_response(serialize_donation(donation))
