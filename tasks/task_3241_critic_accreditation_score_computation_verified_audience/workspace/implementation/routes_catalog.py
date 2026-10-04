"""Routes: titles, releases, critic reviews."""
from flask import Blueprint, request
from db import db, _parse_iso, now_iso
from errors import err
from middleware import require_roles
from helpers import (body_json, require_field, new_entity, touch,
                     get_or_404, list_page)
from response import (success_object, success_list, title_view,
                      release_view, review_view, score_snapshot_view,
                      bombing_incident_view)
from scoring import recompute_tomatometer, recompute_all_scores

bp = Blueprint("catalog", __name__)

ANY_ROLE = ("PlatformAdmin", "AccreditationBoard", "Critic", "StudioRep", "AudienceMember")


# ---------------- titles ----------------

@bp.post("/titles")
def create_title():
    require_roles("PlatformAdmin")
    body = body_json()
    canonical_name = require_field(body, "canonical_name")
    release_year = require_field(body, "release_year")
    if not isinstance(canonical_name, str):
        raise err("ERR_INVALID_REQUEST", "canonical_name must be a string")
    if not isinstance(release_year, int) or isinstance(release_year, bool):
        raise err("ERR_INVALID_REQUEST", "release_year must be an integer")
    title = new_entity(db.titles, {
        "canonical_name": canonical_name,
        "release_year": release_year,
        "posture": "SETUP",
    })
    return success_object(title_view(title), status=201)


@bp.patch("/titles/<tid>")
def update_title(tid):
    require_roles("PlatformAdmin")
    title = get_or_404(db.titles, tid, "Title")
    body = body_json()
    posture = require_field(body, "posture")
    if posture not in ("SETUP", "OPEN", "RETIRED"):
        raise err("ERR_INVALID_REQUEST", "posture must be SETUP, OPEN or RETIRED")
    allowed = {("SETUP", "OPEN"), ("OPEN", "RETIRED")}
    if (title["posture"], posture) not in allowed:
        raise err("ERR_INVALID_STATE",
                  "Title posture %s cannot transition to %s" % (title["posture"], posture))
    title["posture"] = posture
    touch(title)
    return success_object(title_view(title))


# ---------------- releases ----------------

@bp.post("/titles/<tid>/releases")
def create_release(tid):
    require_roles("PlatformAdmin")
    title = get_or_404(db.titles, tid, "Title")
    body = body_json()
    cut_label = require_field(body, "cut_label")
    tws = require_field(body, "theatrical_window_start")
    twe = require_field(body, "theatrical_window_end")
    embargo = require_field(body, "embargo_until")
    if not isinstance(cut_label, str):
        raise err("ERR_INVALID_REQUEST", "cut_label must be a string")
    try:
        _parse_iso(tws)
        _parse_iso(twe)
        _parse_iso(embargo)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST",
                  "theatrical_window_start, theatrical_window_end and embargo_until must be ISO 8601 instants")
    rel = new_entity(db.releases, {
        "title_id": title["id"],
        "cut_label": cut_label,
        "theatrical_window_start": tws,
        "theatrical_window_end": twe,
        "embargo_until": embargo,
        "status": "UPCOMING",
        "audience_display_suspended": False,
        "tomatometer_pct": None,
        "audience_score_pct": None,
        "certification": "NONE",
    })
    return success_object(release_view(rel, db), status=201)


@bp.get("/releases")
def list_releases():
    require_roles(*ANY_ROLE)
    title_id = request.args.get("title_id")
    items, limit, offset, total = list_page(
        db.releases, lambda r: release_view(r, db),
        filters=lambda r: title_id is None or r["title_id"] == title_id)
    return success_list(items, limit, offset, total)


@bp.get("/releases/<rid>")
def get_release(rid):
    require_roles(*ANY_ROLE)
    rel = get_or_404(db.releases, rid, "Release")
    return success_object(release_view(rel, db))


@bp.post("/releases/<rid>/transition")
def transition_release(rid):
    require_roles("PlatformAdmin")
    rel = get_or_404(db.releases, rid, "Release")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("OPEN", "CLOSE"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    if action == "OPEN":
        if rel["status"] != "UPCOMING":
            raise err("ERR_INVALID_STATE",
                      "Release in status %s cannot be opened" % rel["status"])
        title = db.titles.get(rel["title_id"])
        if title is None or title["posture"] != "OPEN":
            raise err("ERR_TITLE_NOT_OPEN", "Parent title posture is not OPEN")
        rel["status"] = "OPEN"
    else:
        if rel["status"] != "OPEN":
            raise err("ERR_INVALID_STATE",
                      "Release in status %s cannot be closed" % rel["status"])
        rel["status"] = "CLOSED"
    touch(rel)
    return success_object(release_view(rel, db))


@bp.post("/releases/<rid>/score-recalculation")
def recalculate_release(rid):
    require_roles("AccreditationBoard", "PlatformAdmin")
    rel = get_or_404(db.releases, rid, "Release")
    body = body_json()
    expected = require_field(body, "expected_release_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_release_version must be an integer")
    if expected != rel["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_release_version %s does not match current version %s"
                  % (expected, rel["version"]))
    # A snapshot may not be persisted from an empty input set.
    has_live_review = any(
        r["release_id"] == rid and r["status"] in ("PUBLISHED", "FLAGGED")
        for r in db.reviews.values())
    has_live_rating = any(
        r["release_id"] == rid and r["status"] in ("VERIFIED", "UNVERIFIED")
        for r in db.audience_ratings.values())
    if not has_live_review and not has_live_rating:
        raise err("ERR_SCORE_NOT_COMPUTABLE",
                  "Both score input sets are empty; no snapshot may be persisted")
    recompute_all_scores(rel)
    return success_object(release_view(rel, db))


@bp.get("/releases/<rid>/score-snapshots")
def list_score_snapshots(rid):
    require_roles(*ANY_ROLE)
    get_or_404(db.releases, rid, "Release")
    items, limit, offset, total = list_page(
        db.score_snapshots, score_snapshot_view,
        filters=lambda s: s["release_id"] == rid)
    return success_list(items, limit, offset, total)


@bp.get("/releases/<rid>/bombing-incidents")
def list_release_bombing_incidents(rid):
    require_roles(*ANY_ROLE)
    get_or_404(db.releases, rid, "Release")
    items, limit, offset, total = list_page(
        db.bombing_incidents, bombing_incident_view,
        filters=lambda i: i["release_id"] == rid)
    return success_list(items, limit, offset, total)


# ---------------- critic reviews ----------------

@bp.post("/releases/<rid>/reviews")
def ingest_review(rid):
    user_id, _role = require_roles("Critic")
    rel = get_or_404(db.releases, rid, "Release")
    body = body_json()
    critic_id = require_field(body, "critic_id")
    body_text = require_field(body, "body_text")
    self_designation = require_field(body, "self_designation")
    if not isinstance(critic_id, str) or not isinstance(body_text, str):
        raise err("ERR_INVALID_REQUEST", "critic_id and body_text must be strings")
    if self_designation not in ("FRESH", "ROTTEN"):
        raise err("ERR_INVALID_REQUEST", "self_designation must be FRESH or ROTTEN")
    critic = get_or_404(db.critics, critic_id, "Critic")
    if critic_id != user_id:
        raise err("ERR_FORBIDDEN", "critic_id must equal X-User-ID")
    if critic["accreditation_status"] not in ("ACCREDITED", "PROBATION"):
        raise err("ERR_CRITIC_NOT_ACCREDITED",
                  "Critic accreditation_status %s does not permit review ingestion"
                  % critic["accreditation_status"])
    for r in db.reviews.values():
        if (r["critic_id"] == critic_id and r["release_id"] == rid
                and r["status"] != "WITHDRAWN"):
            raise err("ERR_DUPLICATE_REVIEW",
                      "Critic already has a non-WITHDRAWN review on this release")
    review = new_entity(db.reviews, {
        "release_id": rel["id"],
        "critic_id": critic_id,
        "body_text": body_text,
        "self_designation": self_designation,
        "classification": None,
        "status": "INGESTED",
        "published_at": None,
    })
    return success_object(review_view(review), status=201)


@bp.get("/reviews")
def list_reviews():
    require_roles(*ANY_ROLE)
    release_id = request.args.get("release_id")
    critic_id = request.args.get("critic_id")

    def _f(r):
        if release_id is not None and r["release_id"] != release_id:
            return False
        if critic_id is not None and r["critic_id"] != critic_id:
            return False
        return True

    items, limit, offset, total = list_page(db.reviews, review_view, filters=_f)
    return success_list(items, limit, offset, total)


@bp.get("/reviews/<rvid>")
def get_review(rvid):
    require_roles(*ANY_ROLE)
    review = get_or_404(db.reviews, rvid, "CriticReview")
    return success_object(review_view(review))


@bp.post("/reviews/<rvid>/transition")
def transition_review(rvid):
    user_id, _role = require_roles("Critic")
    review = get_or_404(db.reviews, rvid, "CriticReview")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("PUBLISH", "WITHDRAW"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    if review["critic_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Only the review author may perform this transition")
    critic = db.critics.get(review["critic_id"])
    rel = db.releases.get(review["release_id"])

    if action == "PUBLISH":
        if review["status"] != "INGESTED":
            raise err("ERR_INVALID_STATE",
                      "Review in status %s cannot be published" % review["status"])
        if critic is None or critic["accreditation_status"] not in ("ACCREDITED", "PROBATION"):
            raise err("ERR_CRITIC_NOT_ACCREDITED",
                      "Critic accreditation_status does not permit publication")
        if rel is None or rel["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Release is not OPEN")
        if db.logical_clock < _parse_iso(rel["embargo_until"]):
            raise err("ERR_EMBARGO_ACTIVE",
                      "The logical clock has not reached the release embargo instant")
        review["classification"] = review["self_designation"]
        review["published_at"] = now_iso()
        review["status"] = "PUBLISHED"
        touch(review)
        recompute_tomatometer(rel)
        return success_object(review_view(review))

    # WITHDRAW
    if review["status"] not in ("PUBLISHED", "FLAGGED"):
        raise err("ERR_INVALID_STATE",
                  "Review in status %s cannot be withdrawn" % review["status"])
    was_flagged = review["status"] == "FLAGGED"
    review["status"] = "WITHDRAWN"
    touch(review)
    if was_flagged:
        # Auto-reject any FILED or TRIAGED classification dispute against this review.
        for d in db.disputes.values():
            if (d.get("dispute_kind") == "CLASSIFICATION"
                    and d.get("subject_review_id") == review["id"]
                    and d["status"] in ("FILED", "TRIAGED")):
                d["status"] = "REJECTED"
                touch(d)
    if rel is not None:
        recompute_tomatometer(rel)
    return success_object(review_view(review))
