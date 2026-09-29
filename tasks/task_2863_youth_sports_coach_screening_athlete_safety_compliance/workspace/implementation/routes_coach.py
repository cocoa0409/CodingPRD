"""Coach placements: creation, activation and electronic-communication
authorization (PRD section 3.6)."""

from flask import Blueprint, g, request

import auth
import clock
import derive
import envelope
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("coach", __name__)

COACH_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED")
CHANNEL_KINDS = ("TEAM_PLATFORM", "GROUP_EMAIL", "GROUP_SMS", "PRIVATE_DIRECT_MESSAGE")

CREATE_SPEC = {
    "member_id": validate.string(min_len=1),
    "club_id": validate.string(min_len=1),
    "team_name": validate.string(min_len=1, max_len=80),
    "season_start": validate.instant(),
    "season_end": validate.instant(),
}


@bp.get("/coach-assignments")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def list_coach_assignments():
    args = request.args
    validate.query_enum(args, "status", COACH_STATUSES)
    rows = [a for a in store.COACH_ASSIGNMENTS.values()
            if pagelib.match(a, args, "member_id")
            and pagelib.match(a, args, "club_id")
            and pagelib.match(a, args, "status")]
    return pagelib.page(store.ordered(rows), serialize.coach_assignment, args)


@bp.get("/coach-assignments/<coach_assignment_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def read_coach_assignment(coach_assignment_id):
    row = auth.coach_assignment(coach_assignment_id)
    auth.scope(row["club_id"])
    return envelope.ok(serialize.coach_assignment(row))


@bp.post("/coach-assignments")
@auth.endpoint("ClubAdministrator")
def create_coach_assignment():
    data = validate.body(auth.payload(), CREATE_SPEC)
    if data["season_end"] <= data["season_start"]:
        validate.bad("season_end must be strictly after season_start")
    member = auth.member(data["member_id"])
    club = auth.club(data["club_id"])
    auth.scope(data["club_id"])
    if club["compliance_posture"] == "FROZEN":
        fail("ERR_CLUB_POSTURE_FROZEN", "club posture FROZEN blocks placement creation")
    if member["screening_status"] == "DISQUALIFIED":
        fail("ERR_MEMBER_DISQUALIFIED", "a disqualified member may not be placed")
    if derive.has_measure(member["id"], ("PERMANENT",)):
        fail("ERR_CONTACT_NOT_PERMITTED", "a permanently restricted member may not be placed")
    row = store.new_row(
        member_id=member["id"],
        club_id=club["id"],
        team_name=data["team_name"],
        season_start=data["season_start"],
        season_end=data["season_end"],
        status="PENDING",
        activated_at=None,
        eligibility_snapshot_version=None,
        electronic_comm_authorized=False,
        electronic_comm_channel_kind=None,
        parent_copy_required=None,
        suspended_reason=None,
    )
    store.COACH_ASSIGNMENTS[row["id"]] = row
    derive.recompute_all()
    return envelope.created(serialize.coach_assignment(row))


@bp.post("/coach-assignments/<coach_assignment_id>/activate")
@auth.endpoint("ClubAdministrator")
def activate_coach_assignment(coach_assignment_id):
    row = auth.coach_assignment(coach_assignment_id)
    auth.scope(row["club_id"])
    data = validate.body(auth.payload(), {"expected_member_version": validate.integer(minimum=0)})
    member = store.MEMBERS[row["member_id"]]
    club = store.CLUBS[row["club_id"]]
    if data["expected_member_version"] != member["version"]:
        fail("ERR_STALE_MEMBER_VERSION", "expected_member_version does not match the member")
    if row["status"] != "PENDING":
        fail("ERR_COACH_ASSIGNMENT_INVALID_STATE",
             "only a PENDING placement may be activated")
    if club["compliance_posture"] != "OPEN":
        fail("ERR_CLUB_POSTURE_FROZEN",
             "club posture %s blocks activation" % club["compliance_posture"])
    if member["screening_status"] == "DISQUALIFIED":
        fail("ERR_MEMBER_DISQUALIFIED", "a disqualified member may not be activated")
    if derive.has_measure(member["id"], ("PERMANENT", "ACTIVE")):
        fail("ERR_CONTACT_NOT_PERMITTED", "the member is under a restriction")
    if member["screening_status"] != "CLEARED":
        fail("ERR_SCREENING_NOT_CURRENT", "the member's screening is not current")
    if member["training_status"] != "CURRENT":
        fail("ERR_TRAINING_NOT_CURRENT", "the member's training is not current")

    row["status"] = "ACTIVE"
    row["activated_at"] = clock.now()
    row["eligibility_snapshot_version"] = member["version"]
    store.bump(row)
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.coach_assignment(row))


ECOMM_SPEC = {
    "channel_kind": validate.enum(CHANNEL_KINDS),
    "parent_copy_required": validate.boolean(),
}


@bp.post("/coach-assignments/<coach_assignment_id>/electronic-communication-authorization")
@auth.endpoint("ClubAdministrator")
def authorize_electronic_comm(coach_assignment_id):
    row = auth.coach_assignment(coach_assignment_id)
    auth.scope(row["club_id"])
    data = validate.body(auth.payload(), ECOMM_SPEC)
    member = store.MEMBERS[row["member_id"]]
    club = store.CLUBS[row["club_id"]]
    if row["status"] == "TERMINATED":
        fail("ERR_COACH_ASSIGNMENT_INVALID_STATE", "the placement is terminated")
    if derive.has_measure(member["id"], ("PERMANENT", "ACTIVE")):
        fail("ERR_CONTACT_NOT_PERMITTED", "the member is under a restriction")
    if row["status"] != "ACTIVE":
        fail("ERR_ELECTRONIC_COMM_NOT_PERMITTED",
             "only an ACTIVE placement may carry an electronic-communication authorization")
    if member["contact_eligibility"] != "ELIGIBLE":
        fail("ERR_ELECTRONIC_COMM_NOT_PERMITTED",
             "the member is not eligible for athlete contact")
    if club["minor_athlete_program"] and data["channel_kind"] == "PRIVATE_DIRECT_MESSAGE":
        fail("ERR_ELECTRONIC_COMM_NOT_PERMITTED",
             "private direct messaging with minor athletes is prohibited")
    if member["has_minor_athlete_contact"] and not data["parent_copy_required"]:
        fail("ERR_ELECTRONIC_COMM_NOT_PERMITTED",
             "a parent or guardian must be copied on every message")

    row["electronic_comm_authorized"] = True
    row["electronic_comm_channel_kind"] = data["channel_kind"]
    row["parent_copy_required"] = data["parent_copy_required"]
    store.bump(row)
    derive.recompute_all()
    return envelope.ok(serialize.coach_assignment(row))
