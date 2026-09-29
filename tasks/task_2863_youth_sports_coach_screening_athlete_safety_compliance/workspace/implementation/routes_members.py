"""Members: registration, reads, the eligibility projection, screening-order
creation and membership renewal."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import ops
import pagelib
import serialize
import store
import validate
from errors import fail
from routes_clubs import (CONTACT_ELIGIBILITIES, MEMBERSHIP_STATUSES, MEMBER_ROLE_TYPES,
                          SCREENING_STATUSES, STAY_STATUSES)

bp = Blueprint("members", __name__)

ORDER_STATUSES = ("ORDERED", "RESULT_RETURNED", "ADJUDICATED", "VOIDED")
TRAINING_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "EXPIRED")
VARIANTS = ("AUDIT_SNAPSHOT", "RENEWAL_FORWARD")

MEMBER_SPEC = {
    "club_id": validate.string(min_len=1),
    "full_name": validate.string(min_len=1, max_len=120),
    "email": validate.string(min_len=1, max_len=320),
    "role_type": validate.enum(MEMBER_ROLE_TYPES),
    "has_minor_athlete_contact": validate.boolean(),
    "date_of_birth": validate.datestr(),
    "jurisdiction_codes": validate.array(
        validate.string(min_len=2, max_len=2, pattern=validate.UPPER2),
        min_items=1, max_items=6, unique=True),
}


@bp.post("/members")
@auth.endpoint("NgbAdmin", "ClubAdministrator")
def register_member():
    data = validate.body(auth.payload(), MEMBER_SPEC)
    if "@" not in data["email"]:
        validate.bad("email must contain an at-sign")
    club = auth.club(data["club_id"])
    auth.scope(data["club_id"])
    lowered = data["email"].lower()
    for other in store.MEMBERS.values():
        if other["email"].lower() == lowered:
            fail("ERR_DUPLICATE_MEMBER_EMAIL", "email is already registered")
    if club["compliance_posture"] == "FROZEN":
        fail("ERR_CLUB_POSTURE_FROZEN", "club posture FROZEN blocks member registration")
    row = store.new_row(
        club_id=data["club_id"],
        full_name=data["full_name"],
        email=data["email"],
        role_type=data["role_type"],
        has_minor_athlete_contact=data["has_minor_athlete_contact"],
        date_of_birth=data["date_of_birth"],
        jurisdiction_codes=data["jurisdiction_codes"],
        risk_points=0,
        required_tier="TIER_1",
        screening_status="UNSCREENED",
        screening_expires_at=None,
        membership_status="PENDING",
        training_status="NEVER",
        contact_eligibility="RESTRICTED",
        eligible_through=None,
        records_retained_through=None,
        last_renewed_at=None,
        active_assignment_count=0,
    )
    store.MEMBERS[row["id"]] = row
    calc.apply_tier_assignment(row)
    derive.recompute_member(row)
    derive.recompute_club(club)
    return envelope.created(serialize.member(row))


@bp.get("/members/<member_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer", "Member")
def read_member(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    auth.owner(member_id)
    return envelope.ok(serialize.member(member))


@bp.get("/members")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "SafeSportOfficer")
def list_members():
    args = request.args
    validate.query_enum(args, "screening_status", SCREENING_STATUSES)
    validate.query_enum(args, "membership_status", MEMBERSHIP_STATUSES)
    validate.query_enum(args, "contact_eligibility", CONTACT_ELIGIBILITIES)
    validate.query_enum(args, "role_type", MEMBER_ROLE_TYPES)
    rows = [m for m in store.MEMBERS.values()
            if pagelib.match(m, args, "club_id")
            and pagelib.match(m, args, "role_type")
            and pagelib.match(m, args, "screening_status")
            and pagelib.match(m, args, "membership_status")
            and pagelib.match(m, args, "contact_eligibility")]
    return pagelib.page(store.ordered(rows), serialize.member, args)


@bp.get("/members/<member_id>/screening-orders")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def list_member_orders(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    args = request.args
    validate.query_enum(args, "status", ORDER_STATUSES)
    rows = [o for o in store.orders_of(member_id) if pagelib.match(o, args, "status")]
    return pagelib.page(store.ordered(rows), serialize.screening_order, args)


@bp.get("/members/<member_id>/training-assignments")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer", "Member")
def list_member_training(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    auth.owner(member_id)
    args = request.args
    validate.query_enum(args, "status", TRAINING_STATUSES)
    rows = [a for a in store.assignments_of(member_id)
            if pagelib.match(a, args, "status") and pagelib.match(a, args, "course_code")]
    return pagelib.page(store.ordered(rows), serialize.training_assignment, args)


@bp.get("/members/<member_id>/room-stays")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor")
def list_member_room_stays(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    args = request.args
    validate.query_enum(args, "status", STAY_STATUSES)
    rows = [s for s in store.ROOM_STAYS.values()
            if s["member_id"] == member_id and pagelib.match(s, args, "status")]
    rows.sort(key=lambda s: (s["check_in"], s["created_at"], s["_seq"]))
    return pagelib.page(rows, serialize.room_stay, args)


@bp.get("/members/<member_id>/eligibility-projection")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer", "Member")
def read_projection(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    auth.owner(member_id)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "AUDIT_SNAPSHOT"
    elif variant not in VARIANTS:
        validate.bad("variant must be AUDIT_SNAPSHOT or RENEWAL_FORWARD")
    return envelope.ok(serialize.projection(member, variant))


ORDER_SPEC = {
    "expedited": validate.boolean(required=False, default=False),
    "expected_club_version": validate.integer(minimum=0),
}


@bp.post("/members/<member_id>/screening-orders")
@auth.endpoint("ClubAdministrator")
def create_screening_order(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    data = validate.body(auth.payload(), ORDER_SPEC)
    club = auth.club(member["club_id"])
    if data["expected_club_version"] != club["version"]:
        fail("ERR_STALE_CLUB_VERSION", "expected_club_version does not match the club")
    in_flight = any(o["status"] in ("ORDERED", "RESULT_RETURNED")
                    for o in store.orders_of(member_id))
    if member["screening_status"] not in ("UNSCREENED", "CLEARED", "EXPIRED", "DISQUALIFIED"):
        fail("ERR_MEMBER_INVALID_STATE",
             "no screening order may be placed from %s" % member["screening_status"])
    if in_flight:
        fail("ERR_MEMBER_INVALID_STATE", "another screening order is already in flight")
    if club["compliance_posture"] == "FROZEN":
        fail("ERR_CLUB_POSTURE_FROZEN", "club posture FROZEN blocks screening orders")
    if member["screening_status"] == "DISQUALIFIED":
        fail("ERR_MEMBER_DISQUALIFIED", "a disqualified member may never be re-screened")

    tier = member["required_tier"]
    jurisdiction_count = len(member["jurisdiction_codes"])
    charge = calc.screening_order_charge(tier, jurisdiction_count, data["expedited"])
    if club["escrow_balance_cents"] < charge["charged_cents"]:
        fail("ERR_ESCROW_INSUFFICIENT", "the club escrow does not cover this screen")

    row = store.new_row(
        member_id=member_id,
        tier=tier,
        jurisdiction_count=jurisdiction_count,
        expedited=data["expedited"],
        gross_subtotal_cents=charge["gross_subtotal_cents"],
        discount_cents=charge["discount_cents"],
        expedite_cents=charge["expedite_cents"],
        charged_cents=charge["charged_cents"],
        status="ORDERED",
        vendor_disposition=None,
        disposition=None,
        returned_at=None,
        adjudicated_at=None,
        expires_at=None,
        void_reason=None,
    )
    store.SCREENING_ORDERS[row["id"]] = row
    club["escrow_balance_cents"] -= charge["charged_cents"]
    store.bump(club)
    member["screening_status"] = "SCREENING_ORDERED"
    store.bump(member)
    derive.recompute_all()
    return envelope.created(serialize.screening_order(row))


@bp.post("/members/<member_id>/renew")
@auth.endpoint("ClubAdministrator")
def renew_membership(member_id):
    member = auth.member(member_id)
    auth.scope_member(member)
    data = validate.body(auth.payload(), {"attestation_signed": validate.boolean()})
    club = auth.club(member["club_id"])
    if member["membership_status"] not in ("ACTIVE", "LAPSED"):
        fail("ERR_MEMBER_INVALID_STATE",
             "no renewal transition exists from %s" % member["membership_status"])
    if club["compliance_posture"] != "OPEN":
        fail("ERR_CLUB_POSTURE_FROZEN", "club posture %s blocks renewal"
             % club["compliance_posture"])
    if member["screening_status"] == "DISQUALIFIED":
        fail("ERR_MEMBER_DISQUALIFIED", "a disqualified member may not renew")
    if derive.has_measure(member_id, ("PERMANENT",)):
        fail("ERR_CONTACT_NOT_PERMITTED", "a permanently restricted member may not renew")
    if member["screening_status"] != "CLEARED":
        fail("ERR_SCREENING_NOT_CURRENT", "the member's screening is not current")
    if member["training_status"] != "CURRENT":
        fail("ERR_TRAINING_NOT_CURRENT", "the member's training is not current")
    window_opens = None
    if member["eligible_through"] is not None:
        window_opens = clock.plus_days(member["eligible_through"], -calc.RENEWAL_WINDOW_DAYS)
    if not data["attestation_signed"] or window_opens is None or clock.now() < window_opens:
        fail("ERR_RENEWAL_WINDOW_NOT_OPEN", "the renewal window is not open")

    member["membership_status"] = "ACTIVE"
    member["last_renewed_at"] = clock.now()
    calc.apply_tier_assignment(member)
    derive.recompute_member(member)
    ops.stamp_horizons(member)
    derive.recompute_member(member)
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.member(member))
