"""Cascades: critic revocation / reinstatement and publication revocation."""
from db import db
from helpers import touch
from scoring import recompute_tomatometer


def _affected_release_ids(critic_id):
    ids = set()
    for r in db.reviews.values():
        if r["critic_id"] == critic_id and r["status"] in ("PUBLISHED", "FLAGGED"):
            ids.add(r["release_id"])
    return ids


def revoke_critic(critic):
    """Fire the critic-revocation cascade (PRD 3.1).

    Decrement the publication's accredited_critic_count exactly once (only when
    the critic currently counts toward it), mark the critic REVOKED, and
    recompute tomatometer + certification for every affected release.
    """
    pub = db.publications.get(critic["publication_id"])
    counted = critic["accreditation_status"] in ("ACCREDITED", "PROBATION", "UNDER_REVIEW")
    # UNDER_REVIEW implies the critic was ACCREDITED at filing time and still counts.
    releases = _affected_release_ids(critic["id"])
    critic["accreditation_status"] = "REVOKED"
    touch(critic)
    if pub is not None and counted:
        pub["accredited_critic_count"] = max(0, pub["accredited_critic_count"] - 1)
        touch(pub)
    for rel_id in releases:
        rel = db.releases.get(rel_id)
        if rel is not None:
            recompute_tomatometer(rel)


def reinstate_critic(critic):
    """Mirror cascade: ACCREDITED again -> recompute affected releases."""
    releases = _affected_release_ids(critic["id"])
    critic["accreditation_status"] = "ACCREDITED"
    touch(critic)
    for rel_id in releases:
        rel = db.releases.get(rel_id)
        if rel is not None:
            recompute_tomatometer(rel)


def revoke_publication(pub):
    """Publication -> REVOKED; cascade to linked accredited/probation critics."""
    pub["status"] = "REVOKED"
    touch(pub)
    for critic in list(db.critics.values()):
        if critic["publication_id"] != pub["id"]:
            continue
        if critic["accreditation_status"] in ("ACCREDITED", "PROBATION", "UNDER_REVIEW"):
            revoke_critic(critic)
