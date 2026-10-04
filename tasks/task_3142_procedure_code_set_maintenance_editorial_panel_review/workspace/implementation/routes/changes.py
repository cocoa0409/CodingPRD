"""Code change filing, listing and the change-level workflow actions."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from errors import (
    ERR_ALREADY_REFERRED_TO_JUNE_MINUTES,
    ERR_ALREADY_TERMINAL,
    ERR_APPROVAL_PERCENT_TOO_LOW,
    ERR_CYCLE_LIMIT_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_MEETING_NOT_OPEN,
    ERR_NO_HOLD_KIND,
    ERR_NO_QUORUM,
    ERR_COMMENT_PERIOD_TOO_SHORT,
    ERR_UNAUTHORIZED,
    ApiError,
)
from money import dec
from response import object_response
from routes.common import guard, list_response, one
from services import changes as CH
from services import cycles as CY
from services import credits as CR
from services import votes as VT
from clock import logical_now

bp = Blueprint("changes", __name__)

STAFF = (auth.EDITORIAL_STAFF,)
CHANGE_READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR, auth.COMMITTEE_REVIEWER)
CHANGE_READERS_APPLICANT = CHANGE_READERS + (auth.CHANGE_APPLICANT,)
SOCIETY_CHANGE_READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)
FILERS = (auth.EDITORIAL_STAFF, auth.CHANGE_APPLICANT)
CHAIR = (auth.EDITORIAL_PANEL_CHAIR,)

APPROVABLE_DETERMINATIONS = ("APPROVED", "REJECTED", "TABLED")
OUTSIDE_CAST_LIMIT = dec("1")


@bp.post("/code-changes")
@guard(FILERS)
def file_change(actor):
    data = P.body()

    # Tier 3 (existence): referenced body foreign keys resolve left to right.
    applicant_id = P.text_or_none(data.get("applicant_id"))
    if applicant_id is not None:
        R.fk(store.applicants, applicant_id, "ChangeApplicant")
    society_id = P.text_or_none(data.get("society_id"))
    if society_id is not None:
        R.fk(store.societies, society_id, "SpecialtySociety")

    # Tier 4+ (business constraints), in the order PRD 3.1 fixes.
    code = CH.validate_code_format(data.get("code"))
    if CH.code_already_exists(code):
        CH.code_exists_error()

    change_type = P.text(data.get("change_type"))
    tier = P.text(data.get("clinical_evidence_tier"))
    volume = P.integer(data.get("procedure_volume_threshold"), 0)
    if not CH.evidence_sufficient(change_type, tier, volume):
        CH.evidence_error()

    change = store.create(store.code_changes, {
        "code": code,
        "change_type": change_type,
        "category": P.text(data.get("category")),
        "code_family": P.text(data.get("code_family")),
        "applicant_id": applicant_id,
        "society_id": society_id,
        "clinical_evidence_tier": tier,
        "evidence_sufficiency_index": P.number(data.get("evidence_sufficiency_index"), 0),
        "procedure_volume_threshold": volume,
        "organ_system_count": P.integer(data.get("organ_system_count"), 1),
        "descriptor_current": P.text(data.get("descriptor_current")),
        "descriptor_proposed": P.text_or_none(data.get("descriptor_proposed")),
        "guidelines": P.text_or_none(data.get("guidelines")),
        "parenthetical_instructions": P.text_or_none(
            data.get("parenthetical_instructions")
        ),
        "cycles_in_process": P.integer(data.get("cycles_in_process"), 0),
        "administrative_review_status": "UNDER_ADMIN_REVIEW",
        "posting_state": "NOT_POSTED",
        "review_status": "DRAFT",
        "meeting_id": None,
        "comment_period_open_at": None,
        "comment_period_close_at": None,
        "determination": "PENDING",
        "held_for_full_panel": False,
        "cea_credits": 0.0,
        "verdict_recorded_at": None,
        "cycle_id": None,
        "effective_date": None,
        "_created_by": actor.user_id,
    })

    # Descriptor text completeness is the final filing check and must run
    # against the filed record so that a rejection leaves no corpus entry.
    if not CH.descriptor_text_complete(change):
        del store.code_changes[change["id"]]
        CH.descriptor_text_error()

    return object_response(one(change), 201)


@bp.get("/code-changes")
@guard(CHANGE_READERS)
def list_changes(actor):
    rows = store.sorted_rows(store.code_changes)
    args = request.args
    for field in ("review_status", "determination", "category", "applicant_id",
                  "society_id", "meeting_id", "change_type"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    ceiling = args.get("evidence_sufficiency_index_max")
    if ceiling not in (None, ""):
        rows = [r for r in rows
                if dec(r.get("evidence_sufficiency_index")) <= dec(ceiling)]
    return list_response(rows)


@bp.get("/code-changes/<change_id>")
@guard(CHANGE_READERS_APPLICANT)
def read_change(actor, change_id):
    return object_response(one(R.code_change(change_id)))


@bp.get("/specialty-societies/<society_id>/code-changes")
@guard(SOCIETY_CHANGE_READERS)
def list_society_changes(actor, society_id):
    society = R.society(society_id)
    rows = [c for c in store.sorted_rows(store.code_changes)
            if c.get("society_id") == society["id"]]
    return list_response(rows)


# --- administrative return and posting ------------------------------------

@bp.post("/code-changes/<change_id>/administrative-returns")
@guard(STAFF)
def administrative_return(actor, change_id):
    change = R.code_change(change_id)
    if change.get("review_status") != "POSTED_FOR_COMMENT":
        raise ApiError(ERR_INVALID_STATE, "change is not posted for comment")
    if change.get("administrative_review_status") != "ADMIN_COMPLETE":
        raise ApiError(ERR_INVALID_STATE, "administrative screening is not complete")

    change["administrative_review_status"] = "ADMIN_RETURNED"
    change["posting_state"] = "NOT_POSTED"
    change["review_status"] = "DRAFT"
    # A posting pulled off the docket resolves to under 30 days.
    days = CY.comment_duration_days(
        change.get("comment_period_open_at"), change.get("comment_period_close_at")
    )
    change["comment_period_days"] = days if days is not None else 0
    store.bump(change)
    return object_response(one(change), 200)


@bp.post("/code-changes/<change_id>/postings")
@guard(STAFF)
def post_change(actor, change_id):
    change = R.code_change(change_id)
    data = P.body()
    open_at = P.dt(data.get("comment_period_open_at"))
    close_at = P.dt(data.get("comment_period_close_at"))

    if change.get("administrative_review_status") == "ADMIN_RETURNED":
        raise ApiError(ERR_INVALID_STATE, "a returned change cannot be posted")
    if change.get("cycle_id") is None:
        raise ApiError(ERR_INVALID_STATE, "change has not entered a release cycle")
    if not CY.window_acceptable(open_at, close_at):
        raise ApiError(ERR_COMMENT_PERIOD_TOO_SHORT,
                       "comment window must run at least 30 whole days")
    if change.get("review_status") != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "change is not in draft")

    change["comment_period_open_at"] = open_at
    change["comment_period_close_at"] = close_at
    change["administrative_review_status"] = "ADMIN_COMPLETE"
    change["posting_state"] = "COMMENT_OPEN"
    change["review_status"] = "POSTED_FOR_COMMENT"
    store.bump(change)
    return object_response(one(change), 200)


# --- returns, supplementary reports, referrals, determinations ------------

@bp.post("/code-changes/<change_id>/returns")
@guard(STAFF)
def return_change(actor, change_id):
    change = R.code_change(change_id)
    status = change.get("review_status")

    if status == "AGENDA_SET":
        meeting_id = change.get("meeting_id")
        if not meeting_id:
            raise ApiError(ERR_INVALID_STATE, "change carries no docketed meeting")
        meeting = store.meetings.get(meeting_id)
        if meeting is None:
            raise ApiError(ERR_MEETING_NOT_OPEN, "docketed meeting no longer exists")
        if meeting.get("meeting_status") not in ("SCHEDULED", "PUBLIC_COMMENT_OPEN"):
            raise ApiError(ERR_MEETING_NOT_OPEN, "meeting does not admit a return")
        if not CH.descriptor_text_complete(change):
            CH.descriptor_text_error()
        change["meeting_id"] = None
        change["review_status"] = "DRAFT"
        meeting["agenda_status"] = "UNSET"
        store.bump(meeting)
        VT.recompute_quorum(meeting)
        store.bump(change)
        return object_response(one(change), 200)

    if status != "REFERRED":
        raise ApiError(ERR_INVALID_STATE, "change is not docketed or referred")
    if int(change.get("cycles_in_process") or 0) < 3:
        raise ApiError(ERR_INVALID_STATE, "change has not exhausted its carried cycles")

    change["determination"] = "PENDING"
    change["held_for_full_panel"] = False
    change["meeting_id"] = None
    change["review_status"] = "DRAFT"
    CR.recompute_for_change(change)
    store.bump(change)
    return object_response(one(change), 200)


@bp.post("/code-changes/<change_id>/supplementary-reports")
@guard(STAFF)
def supplementary_report(actor, change_id):
    change = R.code_change(change_id)
    if change.get("review_status") != "REFERRED":
        raise ApiError(ERR_INVALID_STATE, "change is not referred")
    if int(change.get("cycles_in_process") or 0) > 2:
        raise ApiError(ERR_CYCLE_LIMIT_EXCEEDED,
                       "a change already carried to three cycles may not be carried to a fourth")
    if not change.get("held_for_full_panel"):
        raise ApiError(ERR_INVALID_STATE, "change is not held for full-panel action")

    change["cycles_in_process"] = int(change.get("cycles_in_process") or 0) + 1
    change["held_for_full_panel"] = False
    change["review_status"] = "POSTED_FOR_COMMENT"
    change["posting_state"] = "COMMENT_OPEN"
    store.bump(change)
    return object_response(one(change), 200)


@bp.post("/code-changes/<change_id>/referrals")
@guard(CHAIR)
def refer_change(actor, change_id):
    change = R.code_change(change_id)
    data = P.body()
    reason = data.get("reason")
    if reason in (None, ""):
        raise ApiError(ERR_NO_HOLD_KIND, "a referral must name its hold basis")
    if change.get("review_status") != "PANEL_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "change is not in panel review")
    if change.get("held_for_full_panel"):
        raise ApiError(ERR_INVALID_STATE, "change is already held for full-panel action")
    completed = any(
        review.get("change_id") == change["id"]
        and review.get("review_status") == "COMPLETE"
        for review in store.committee_reviews.values()
    )
    if not completed:
        raise ApiError(ERR_INVALID_STATE,
                       "no advisory committee review has completed for this change")

    change["held_for_full_panel"] = True
    change["determination"] = "REFERRED_TO_JUNE_MINUTES"
    # PANEL_REVIEW -> REFERRED: the change leaves the balloting stage and waits
    # on the June minutes until a supplementary report carries it forward.
    change["review_status"] = "REFERRED"
    CR.recompute_for_change(change)
    meeting = store.meetings.get(change.get("meeting_id"))
    if meeting is not None:
        meeting["meeting_status"] = "RECESSED"
        store.bump(meeting)
    store.bump(change)
    return object_response(one(change), 200)


@bp.post("/code-changes/<change_id>/determinations")
@guard(CHAIR)
def record_determination(actor, change_id):
    change = R.code_change(change_id)
    data = P.body()
    requested = data.get("determination")
    meeting = store.meetings.get(change.get("meeting_id")) if change.get("meeting_id") else None

    # Segregation of duties: the identity that filed a change may not record
    # its panel determination (PRD.md 2.1 / 2.4).
    if actor.user_id == change.get("_created_by"):
        raise ApiError(ERR_UNAUTHORIZED,
                       "the filing identity may not record the panel determination")

    # 1. The one-percent outside-cast limit is evaluated ahead of everything
    #    else on this path (PRD.md 3.5); the same code and status are returned
    #    for a percentage below the citation-mode floor.
    if meeting is not None:
        share = VT.outside_cast_share(meeting)
        if share is not None and dec(share) > OUTSIDE_CAST_LIMIT:
            raise ApiError(ERR_APPROVAL_PERCENT_TOO_LOW,
                           "more than one percent of the weighted yes vote was cast from outside "
                           "the seated societies")

    # 2. Meeting quorum is evaluated before the full-panel hold check.
    if meeting is not None:
        VT.recompute_quorum(meeting)
    if meeting is None or not bool(meeting.get("quorum_present")):
        raise ApiError(ERR_NO_QUORUM, "the meeting has no quorum")

    # 3. The full-panel hold check precedes the approval percentage floor.
    if change.get("held_for_full_panel"):
        raise ApiError(ERR_ALREADY_REFERRED_TO_JUNE_MINUTES,
                       "a held change must be carried to the June minutes")

    # 4. Citation-only mode applies the two-thirds floor at three decimals.
    if meeting is not None and bool(meeting.get("citation_mode")) \
            and not VT.motion_carried(meeting):
        raise ApiError(ERR_APPROVAL_PERCENT_TOO_LOW,
                       "the citation-mode weighted approval floor is not met")

    # 5. A category III addition cannot be advanced without supporting data.
    if not CH.support_data_present(change):
        CH.support_data_error()

    # 6. Admissibility of the change's current review status is evaluated last.
    if change.get("review_status") != "PANEL_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "change is not in panel review")
    if requested not in APPROVABLE_DETERMINATIONS:
        raise ApiError(ERR_INVALID_STATE, "unsupported determination")

    change["determination"] = requested
    change["review_status"] = "DETERMINED"
    change["verdict_recorded_at"] = logical_now()
    CR.recompute_for_change(change)
    if meeting is not None:
        VT.panel_weighted_vote_tally(meeting)
        VT.recompute_quorum(meeting)
        store.bump(meeting)
    store.bump(change)
    return object_response(one(change), 200)


@bp.post("/code-changes/<change_id>/revert-to-draft")
@guard(STAFF)
def revert_to_draft(actor, change_id):
    change = R.code_change(change_id)
    determination = change.get("determination")

    # A change whose determination is already APPROVED is terminal and cannot
    # be reverted through this path at all.
    if determination == "APPROVED":
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "a change whose determination is APPROVED may not be reverted to draft")
    if change.get("review_status") != "DETERMINED":
        raise ApiError(ERR_INVALID_STATE, "the change is not in a determined state")
    if determination not in ("REFERRED_TO_JUNE_MINUTES", "TABLED"):
        raise ApiError(ERR_INVALID_STATE, "determination does not admit a revert")
    if determination == "REFERRED_TO_JUNE_MINUTES":
        meeting = store.meetings.get(change.get("meeting_id")) if change.get("meeting_id") else None
        if meeting is None or meeting.get("meeting_month") != "JUNE":
            raise ApiError(ERR_INVALID_STATE,
                           "a June referral may only be reverted from a June meeting")

    change["cycles_in_process"] = int(change.get("cycles_in_process") or 0) + 1
    change["determination"] = "PENDING"
    change["review_status"] = "DRAFT"
    CR.recompute_for_change(change)
    store.bump(change)
    return object_response(one(change), 200)


@bp.delete("/code-changes/<change_id>")
@guard(FILERS)
def withdraw_change(actor, change_id):
    change = R.code_change(change_id)
    status = change.get("review_status")

    if actor.role == auth.CHANGE_APPLICANT:
        # Ownership: the change references the acting ChangeApplicant.
        if change.get("applicant_id") != actor.user_id:
            raise ApiError(ERR_UNAUTHORIZED, "this applicant did not file the change")

    if status not in ("DRAFT", "POSTED_FOR_COMMENT"):
        raise ApiError(ERR_INVALID_STATE, "change cannot be withdrawn from its current state")
    if change.get("cycle_id") is not None:
        raise ApiError(ERR_INVALID_STATE, "change has already entered a release cycle")
    if status == "DRAFT" and change.get("administrative_review_status") not in (
        "UNDER_ADMIN_REVIEW", "ADMIN_COMPLETE"
    ):
        raise ApiError(ERR_INVALID_STATE, "administrative screening does not admit a withdrawal")

    if status == "POSTED_FOR_COMMENT":
        for comment in store.public_comments.values():
            if comment.get("change_id") == change["id"] and comment.get("withdrawn_at") is None:
                comment["withdrawn_at"] = logical_now()
                store.bump(comment)

    # review_status and posting_state are deliberately left untouched.
    change["determination"] = "WITHDRAWN"
    change["withdrawal_reason"] = P.text_or_none(P.body().get("withdrawal_reason"))
    CR.recompute_for_change(change)
    store.bump(change)
    return object_response(one(change), 200)