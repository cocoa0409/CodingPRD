"""Routes: disputes (classification and score display)."""
from flask import Blueprint, request
from db import db
from errors import err
from middleware import require_roles
from helpers import (body_json, require_field, new_entity, touch,
                     get_or_404, list_page)
from response import success_object, success_list, dispute_view
from scoring import recompute_tomatometer, recompute_all_scores

bp = Blueprint("disputes", __name__)

FILING_ROLES = ("Critic", "StudioRep")
LIST_ROLES = ("PlatformAdmin", "AccreditationBoard")
GET_ROLES = ("PlatformAdmin", "AccreditationBoard", "Critic", "StudioRep")


@bp.post("/disputes")
def create_dispute():
    user_id, role = require_roles(*FILING_ROLES)
    body = body_json()
    dispute_kind = require_field(body, "dispute_kind")
    if dispute_kind not in ("CLASSIFICATION", "SCORE_DISPLAY"):
        raise err("ERR_INVALID_REQUEST", "dispute_kind must be CLASSIFICATION or SCORE_DISPLAY")
    filed_by_critic_id = body.get("filed_by_critic_id")
    filed_by_studio = body.get("filed_by_studio")
    # Filer fields must be consistent with the caller role and filer type:
    # exactly one of the two filer fields, matching the caller's role.
    if role == "Critic":
        if not isinstance(filed_by_critic_id, str) or filed_by_studio is not None:
            raise err("ERR_INVALID_REQUEST",
                      "A Critic filer must set filed_by_critic_id and must not set filed_by_studio")
    else:
        if not isinstance(filed_by_studio, str) or filed_by_critic_id is not None:
            raise err("ERR_INVALID_REQUEST",
                      "A StudioRep filer must set filed_by_studio and must not set filed_by_critic_id")

    subject_review_id = body.get("subject_review_id")
    subject_release_id = body.get("subject_release_id")
    requested_classification = body.get("requested_classification")

    review = None
    rel = None
    if dispute_kind == "CLASSIFICATION":
        if not isinstance(subject_review_id, str) or subject_release_id is not None:
            raise err("ERR_INVALID_REQUEST",
                      "CLASSIFICATION disputes require subject_review_id and no subject_release_id")
        review = get_or_404(db.reviews, subject_review_id, "CriticReview")
        # Requested classification: present, FRESH/ROTTEN, and different from current.
        if (requested_classification not in ("FRESH", "ROTTEN")
                or review.get("classification") is None
                or requested_classification == review.get("classification")):
            raise err("ERR_INVALID_RECLASSIFICATION",
                      "requested_classification must be FRESH or ROTTEN and differ from "
                      "the review's current classification")
        # Segregation of duties: a critic may not dispute their own review.
        if filed_by_critic_id is not None and filed_by_critic_id == review["critic_id"]:
            raise err("ERR_SELF_DISPUTE_FORBIDDEN",
                      "A critic may not dispute the classification of their own review")
        if review["status"] != "PUBLISHED":
            raise err("ERR_INVALID_STATE",
                      "Review in status %s cannot be disputed" % review["status"])
        rel = db.releases.get(review["release_id"])
    else:
        if not isinstance(subject_release_id, str) or subject_review_id is not None:
            raise err("ERR_INVALID_REQUEST",
                      "SCORE_DISPLAY disputes require subject_release_id and no subject_review_id")
        if requested_classification is not None:
            raise err("ERR_INVALID_REQUEST",
                      "requested_classification is only valid for CLASSIFICATION disputes")
        rel = get_or_404(db.releases, subject_release_id, "Release")

    if filed_by_critic_id is not None:
        get_or_404(db.critics, filed_by_critic_id, "Critic")

    dispute = new_entity(db.disputes, {
        "subject_review_id": subject_review_id,
        "subject_release_id": subject_release_id,
        "dispute_kind": dispute_kind,
        "filed_by_critic_id": filed_by_critic_id,
        "filed_by_studio": filed_by_studio,
        "requested_classification": requested_classification,
        "status": "FILED",
    })
    if review is not None:
        review["status"] = "FLAGGED"
        touch(review)
    return success_object(dispute_view(dispute), status=201)


def _dispute_filter(d, args):
    srid = args.get("subject_review_id")
    srelid = args.get("subject_release_id")
    fbc = args.get("filed_by_critic_id")
    if srid is not None and d.get("subject_review_id") != srid:
        return False
    if srelid is not None and d.get("subject_release_id") != srelid:
        return False
    if fbc is not None and d.get("filed_by_critic_id") != fbc:
        return False
    return True


@bp.get("/disputes")
def list_disputes():
    require_roles(*LIST_ROLES)
    items, limit, offset, total = list_page(
        db.disputes, dispute_view,
        filters=lambda d: _dispute_filter(d, request.args))
    return success_list(items, limit, offset, total)


@bp.get("/disputes/<did>")
def get_dispute(did):
    require_roles(*GET_ROLES)
    dispute = get_or_404(db.disputes, did, "Dispute")
    return success_object(dispute_view(dispute))


@bp.post("/disputes/<did>/transition")
def transition_dispute(did):
    require_roles("AccreditationBoard")
    dispute = get_or_404(db.disputes, did, "Dispute")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("TRIAGE", "RETURN", "RULE_UPHOLD", "RULE_REJECT"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    # Terminal disputes reject all actions.
    if dispute["status"] in ("UPHELD", "REJECTED"):
        raise err("ERR_DISPUTE_ALREADY_TERMINAL",
                  "Dispute in status %s is terminal" % dispute["status"])
    # Optimistic concurrency on the dispute version (applies to all transitions).
    expected = body.get("expected_dispute_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err("ERR_INVALID_REQUEST", "expected_dispute_version must be an integer")
        if expected != dispute["version"]:
            raise err("ERR_STALE_VERSION",
                      "expected_dispute_version %s does not match current version %s"
                      % (expected, dispute["version"]))

    review = db.reviews.get(dispute["subject_review_id"]) if dispute.get("subject_review_id") else None
    rel = (db.releases.get(dispute["subject_release_id"])
           if dispute.get("subject_release_id") else None)

    if action == "TRIAGE":
        if dispute["status"] != "FILED":
            raise err("ERR_INVALID_STATE",
                      "Dispute in status %s cannot be triaged" % dispute["status"])
        dispute["status"] = "TRIAGED"
        touch(dispute)
        return success_object(dispute_view(dispute))

    if action == "RETURN":
        if dispute["status"] != "TRIAGED":
            raise err("ERR_INVALID_STATE",
                      "Dispute in status %s cannot be returned" % dispute["status"])
        dispute["status"] = "FILED"
        touch(dispute)
        return success_object(dispute_view(dispute))

    # Rulings only from TRIAGED.
    if dispute["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE",
                  "Dispute in status %s cannot be ruled" % dispute["status"])

    if action == "RULE_UPHOLD":
        if dispute["dispute_kind"] == "CLASSIFICATION":
            if review is None:
                raise err("ERR_NOT_FOUND", "Subject review not found")
            if review["status"] != "FLAGGED" or not dispute.get("requested_classification"):
                raise err("ERR_INVALID_STATE",
                          "CLASSIFICATION uphold requires the subject review in FLAGGED "
                          "status with a requested_classification present")
            review["classification"] = dispute["requested_classification"]
            review["status"] = "PUBLISHED"
            touch(review)
            dispute["status"] = "UPHELD"
            touch(dispute)
            review_rel = db.releases.get(review["release_id"])
            if review_rel is not None:
                recompute_tomatometer(review_rel)
        else:
            dispute["status"] = "UPHELD"
            touch(dispute)
            if rel is not None:
                recompute_all_scores(rel)
        return success_object(dispute_view(dispute))

    # RULE_REJECT
    dispute["status"] = "REJECTED"
    touch(dispute)
    if dispute["dispute_kind"] == "CLASSIFICATION" and review is not None:
        if review["status"] == "FLAGGED":
            review["status"] = "PUBLISHED"
            touch(review)
    return success_object(dispute_view(dispute))
