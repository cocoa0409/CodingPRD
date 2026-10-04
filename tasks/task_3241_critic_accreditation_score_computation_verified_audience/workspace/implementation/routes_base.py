"""Routes: logical clock, publications, critics, accreditation reviews."""
from flask import Blueprint
from db import db, _parse_iso, _fmt_iso
from errors import err
from middleware import require_roles, get_auth
from helpers import (body_json, require_field, new_entity, touch,
                     get_or_404, list_page)
from response import (success_object, success_list, publication_view,
                      critic_view, accreditation_review_view)
from scoring import critic_standing_final
from cascades import reinstate_critic, revoke_critic, revoke_publication

bp = Blueprint("base", __name__)

ANY_ROLE = ("PlatformAdmin", "AccreditationBoard", "Critic", "StudioRep", "AudienceMember")
PUB_REACH_TIERS = ("NATIONAL", "REGIONAL", "NICHE")


# ---------------- logical clock ----------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = body_json()
    to_iso = require_field(body, "to_iso8601")
    try:
        db.logical_clock = _parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    return success_object({"current_utc": _fmt_iso(db.logical_clock)})


# ---------------- publications ----------------

@bp.post("/publications")
def create_publication():
    require_roles("PlatformAdmin")
    body = body_json()
    outlet_name = require_field(body, "outlet_name")
    reach_tier = require_field(body, "reach_tier")
    if not isinstance(outlet_name, str) or not isinstance(reach_tier, str):
        raise err("ERR_INVALID_REQUEST", "outlet_name and reach_tier must be strings")
    if reach_tier not in PUB_REACH_TIERS:
        raise err("ERR_INVALID_REQUEST", "reach_tier must be one of NATIONAL, REGIONAL, NICHE")
    for p in db.publications.values():
        if p["outlet_name"] == outlet_name and p["status"] != "REVOKED":
            raise err("ERR_INVALID_REQUEST", "outlet_name must be unique across non-revoked publications")
    pub = new_entity(db.publications, {
        "outlet_name": outlet_name,
        "reach_tier": reach_tier,
        "status": "PENDING",
        "accredited_critic_count": 0,
    })
    return success_object(publication_view(pub), status=201)


@bp.get("/publications/<pid>")
def get_publication(pid):
    require_roles(*ANY_ROLE)
    pub = get_or_404(db.publications, pid, "Publication")
    return success_object(publication_view(pub))


@bp.post("/publications/<pid>/transition")
def transition_publication(pid):
    require_roles("AccreditationBoard")
    pub = get_or_404(db.publications, pid, "Publication")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("ACCREDIT", "PROBATE", "REINSTATE"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    allowed = {
        "ACCREDIT": {"PENDING"},
        "PROBATE": {"ACCREDITED"},
        "REINSTATE": {"PROBATION"},
    }
    if pub["status"] not in allowed[action]:
        raise err("ERR_INVALID_STATE",
                  "Publication in status %s cannot perform %s" % (pub["status"], action))
    target = {"ACCREDIT": "ACCREDITED", "PROBATE": "PROBATION", "REINSTATE": "ACCREDITED"}[action]
    pub["status"] = target
    if action == "PROBATE":
        # Recompute leaves the count unchanged: the count tracks linked critics
        # in ACCREDITED/PROBATION/UNDER_REVIEW (incremented at ACCREDIT,
        # decremented exactly once per critic at revocation).
        pub["accredited_critic_count"] = sum(
            1 for c in db.critics.values()
            if c["publication_id"] == pid
            and c["accreditation_status"] in ("ACCREDITED", "PROBATION", "UNDER_REVIEW"))
    touch(pub)
    return success_object(publication_view(pub))


# ---------------- critics ----------------

@bp.get("/publications/<pid>/critics")
def list_publication_critics(pid):
    require_roles(*ANY_ROLE)
    get_or_404(db.publications, pid, "Publication")
    items, limit, offset, total = list_page(
        db.critics, critic_view,
        filters=lambda c: c["publication_id"] == pid)
    return success_list(items, limit, offset, total)

@bp.post("/critics")
def create_critic():
    require_roles("PlatformAdmin")
    body = body_json()
    full_name = require_field(body, "full_name")
    publication_id = require_field(body, "publication_id")
    if not isinstance(full_name, str) or not isinstance(publication_id, str):
        raise err("ERR_INVALID_REQUEST", "full_name and publication_id must be strings")
    is_top = body.get("is_top_critic", False)
    if not isinstance(is_top, bool):
        raise err("ERR_INVALID_REQUEST", "is_top_critic must be a boolean")
    get_or_404(db.publications, publication_id, "Publication")
    critic = new_entity(db.critics, {
        "full_name": full_name,
        "publication_id": publication_id,
        "is_top_critic": is_top,
        "accreditation_status": "APPLIED",
        "standing_score_bps": 10000,
        "last_review_period_start": None,
    })
    return success_object(critic_view(critic), status=201)


@bp.get("/critics/<cid>")
def get_critic(cid):
    require_roles(*ANY_ROLE)
    critic = get_or_404(db.critics, cid, "Critic")
    return success_object(critic_view(critic))


@bp.post("/critics/<cid>/transition")
def transition_critic(cid):
    user_id, role = require_roles("AccreditationBoard", "Critic")
    critic = get_or_404(db.critics, cid, "Critic")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("ACCREDIT", "PROBATE", "REINSTATE", "REAPPLY"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    # REAPPLY is performed by the critic themselves, and only on their own record.
    if action == "REAPPLY":
        if role != "Critic":
            raise err("ERR_UNAUTHORIZED", "REAPPLY may only be performed by the critic")
        if user_id != cid:
            raise err("ERR_FORBIDDEN", "A critic may only re-apply on their own record")
        if critic["accreditation_status"] != "REVOKED":
            raise err("ERR_INVALID_STATE",
                      "Critic in status %s cannot REAPPLY" % critic["accreditation_status"])
        critic["accreditation_status"] = "APPLIED"
        touch(critic)
        return success_object(critic_view(critic))
    # Board-only actions.
    if role != "AccreditationBoard":
        raise err("ERR_UNAUTHORIZED", "Only AccreditationBoard may perform %s" % action)
    if action == "ACCREDIT":
        if critic["accreditation_status"] != "APPLIED":
            raise err("ERR_INVALID_STATE",
                      "Critic in status %s cannot be accredited" % critic["accreditation_status"])
        pub = get_or_404(db.publications, critic["publication_id"], "Publication")
        if pub["status"] != "ACCREDITED":
            raise err("ERR_PUBLICATION_NOT_ACCREDITED",
                      "Employing publication is not ACCREDITED")
        critic["accreditation_status"] = "ACCREDITED"
        touch(critic)
        pub["accredited_critic_count"] = pub["accredited_critic_count"] + 1
        touch(pub)
        return success_object(critic_view(critic))
    if action == "PROBATE":
        if critic["accreditation_status"] != "ACCREDITED":
            raise err("ERR_INVALID_STATE",
                      "Critic in status %s cannot be placed on probation" % critic["accreditation_status"])
        critic["accreditation_status"] = "PROBATION"
        touch(critic)
        return success_object(critic_view(critic))
    # REINSTATE
    if critic["accreditation_status"] != "PROBATION":
        raise err("ERR_INVALID_STATE",
                  "Critic in status %s cannot be reinstated" % critic["accreditation_status"])
    reinstate_critic(critic)
    return success_object(critic_view(critic))


# ---------------- accreditation reviews ----------------

def _review_subject_filter(r, args):
    scid = args.get("subject_critic_id")
    spid = args.get("subject_publication_id")
    if scid and r.get("subject_critic_id") != scid:
        return False
    if spid and r.get("subject_publication_id") != spid:
        return False
    return True


@bp.post("/accreditation-reviews")
def create_accreditation_review():
    require_roles("AccreditationBoard")
    body = body_json()
    scid = body.get("subject_critic_id")
    spid = body.get("subject_publication_id")
    if (scid is None) == (spid is None):
        raise err("ERR_INVALID_REQUEST",
                  "Exactly one of subject_critic_id or subject_publication_id must be set")
    period_start = require_field(body, "period_start")
    period_end = require_field(body, "period_end")
    try:
        ps = _parse_iso(period_start)
        pe = _parse_iso(period_end)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "period_start / period_end must be ISO 8601 instants")
    decision_note = body.get("decision_note")
    if decision_note is not None and not isinstance(decision_note, str):
        raise err("ERR_INVALID_REQUEST", "decision_note must be a string")
    critic = None
    if scid is not None:
        if not isinstance(scid, str):
            raise err("ERR_INVALID_REQUEST", "subject_critic_id must be a string")
        critic = get_or_404(db.critics, scid, "Critic")
    else:
        if not isinstance(spid, str):
            raise err("ERR_INVALID_REQUEST", "subject_publication_id must be a string")
        get_or_404(db.publications, spid, "Publication")
    review = new_entity(db.accreditation_reviews, {
        "subject_critic_id": scid,
        "subject_publication_id": spid,
        "period_start": period_start,
        "period_end": period_end,
        "status": "FILED",
        "decision_note": decision_note,
    })
    if critic is not None and critic["accreditation_status"] == "ACCREDITED":
        critic["accreditation_status"] = "UNDER_REVIEW"
        touch(critic)
    return success_object(accreditation_review_view(review), status=201)


@bp.get("/accreditation-reviews")
def list_accreditation_reviews():
    require_roles("PlatformAdmin", "AccreditationBoard")
    from flask import request as _req
    items, limit, offset, total = list_page(
        db.accreditation_reviews, accreditation_review_view,
        filters=lambda r: _review_subject_filter(r, _req.args))
    return success_list(items, limit, offset, total)


@bp.get("/accreditation-reviews/<rid>")
def get_accreditation_review(rid):
    require_roles("PlatformAdmin", "AccreditationBoard")
    review = get_or_404(db.accreditation_reviews, rid, "AccreditationReview")
    return success_object(accreditation_review_view(review))


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; mere adjacency is not overlap."""
    return a_start < b_end and b_start < a_end


@bp.post("/accreditation-reviews/<rid>/transition")
def transition_accreditation_review(rid):
    require_roles("AccreditationBoard")
    review = get_or_404(db.accreditation_reviews, rid, "AccreditationReview")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("BEGIN_REVIEW", "RULE_UPHOLD", "RULE_REVOKE", "DISMISS"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    decision_note = body.get("decision_note")
    if decision_note is not None and not isinstance(decision_note, str):
        raise err("ERR_INVALID_REQUEST", "decision_note must be a string")

    if action == "BEGIN_REVIEW":
        if review["status"] != "FILED":
            raise err("ERR_INVALID_STATE",
                      "AccreditationReview in status %s cannot begin review" % review["status"])
        ps = _parse_iso(review["period_start"])
        pe = _parse_iso(review["period_end"])
        for other in db.accreditation_reviews.values():
            if other["id"] == review["id"] or other["status"] == "DISMISSED":
                continue
            if (other.get("subject_critic_id") != review.get("subject_critic_id")
                    or other.get("subject_publication_id") != review.get("subject_publication_id")):
                continue
            if _windows_overlap(ps, pe, _parse_iso(other["period_start"]),
                                _parse_iso(other["period_end"])):
                raise err("ERR_ACC_REVIEW_PERIOD_OVERLAP",
                          "Review window overlaps an existing non-DISMISSED review for this subject")
        review["status"] = "IN_REVIEW"
        touch(review)
        return success_object(accreditation_review_view(review))

    # Rulings require IN_REVIEW.
    if review["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE",
                  "AccreditationReview in status %s cannot be ruled" % review["status"])
    if decision_note is not None:
        review["decision_note"] = decision_note

    critic = db.critics.get(review["subject_critic_id"]) if review.get("subject_critic_id") else None
    pub = db.publications.get(review["subject_publication_id"]) if review.get("subject_publication_id") else None

    if action == "RULE_UPHOLD":
        review["status"] = "UPHELD"
        touch(review)
        if critic is not None:
            critic["accreditation_status"] = "ACCREDITED"
            critic["standing_score_bps"] = critic_standing_final(
                critic["id"], review["period_start"], review["period_end"])
            critic["last_review_period_start"] = review["period_start"]
            touch(critic)
        return success_object(accreditation_review_view(review))

    if action == "RULE_REVOKE":
        review["status"] = "REVOKED"
        touch(review)
        if critic is not None:
            revoke_critic(critic)
        elif pub is not None and pub["status"] in ("ACCREDITED", "PROBATION"):
            revoke_publication(pub)
        return success_object(accreditation_review_view(review))

    # DISMISS
    review["status"] = "DISMISSED"
    touch(review)
    if critic is not None and critic["accreditation_status"] == "UNDER_REVIEW":
        critic["accreditation_status"] = "ACCREDITED"
        touch(critic)
    return success_object(accreditation_review_view(review))

