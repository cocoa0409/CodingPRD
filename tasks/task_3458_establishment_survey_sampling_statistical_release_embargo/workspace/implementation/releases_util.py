"""Release helpers: embargo-window overlap rule (PRD 2.9) and the
active_embargo_grant_count recompute."""
from datetime import timedelta

from errors import raise_err, ERR_EMBARGO_WINDOW_OVERLAP
from store import DB, touch, ACTIVE_GRANT_STATUSES


def check_window_overlap(program_code, embargo_open_at, release_at, exclude_id=None):
    """Reject when [embargo_open_at, release_at) overlaps the window of any
    other release of the same program in SCHEDULED or EMBARGO_OPEN. Half-open
    semantics: back-to-back windows do not overlap."""
    for rel in DB["releases"].values():
        if rel["program_code"] != program_code:
            continue
        if rel["id"] == exclude_id:
            continue
        if rel["pub_status"] not in ("SCHEDULED", "EMBARGO_OPEN"):
            continue
        other_open = rel["embargo_open_at"]
        other_close = rel["release_at"]
        if embargo_open_at < other_close and other_open < release_at:
            raise_err(
                ERR_EMBARGO_WINDOW_OVERLAP,
                "embargo window overlaps another live release of this program",
            )


def recompute_grant_count(release, do_touch=True):
    """active_embargo_grant_count = grants of this release in ISSUED/ACCESSED."""
    count = sum(
        1
        for g in DB["grants"].values()
        if g["release_event_id"] == release["id"] and g["grant_status"] in ACTIVE_GRANT_STATUSES
    )
    if release["active_embargo_grant_count"] != count:
        release["active_embargo_grant_count"] = count
        if do_touch:
            touch(release)


def revoke_grants(grants, touch_releases=True):
    """Move each grant in ISSUED/ACCESSED to REVOKED and recompute the owning
    release's counter. touch_releases=False lets a release advance perform a
    single version bump for the whole action."""
    affected_release_ids = set()
    for g in grants:
        if g["grant_status"] in ACTIVE_GRANT_STATUSES:
            g["grant_status"] = "REVOKED"
            touch(g)
            affected_release_ids.add(g["release_event_id"])
    for rid in affected_release_ids:
        rel = DB["releases"].get(rid)
        if rel is not None:
            recompute_grant_count(rel, do_touch=touch_releases)


def embargo_open_at_for(program, release_at):
    return release_at - timedelta(minutes=program["embargo_window_minutes"])
