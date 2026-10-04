"""Reviewer profiles: member self-application, self-service attestation /
window updates, PlatformAdmin status administration (PRD 3.3).

Unavailability windows are CLOSED date intervals: touching endpoints count as
overlapping (ERR_AVAILABILITY_WINDOW_OVERLAP).
"""

from clock import clock
from domain import windows_overlap
from envelope import ok
from errors import api_error
from auth import authenticate, authorize
from listing import list_response
from serialize import reviewer_profile
from store import store, new_id, touch
from validate import (
    REVIEWER_STATUSES,
    get_body,
    opt_str_list,
    pagination,
    parse_date,
    query_filter,
    req_str,
)


def _now():
    return clock.now_iso()


def _parse_windows(body):
    """Validate shape of unavailability_windows (priority 2). Returns a list of
    dicts carrying both the raw strings and parsed dates (internal `_` keys)."""
    raw = body.get("unavailability_windows")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise api_error("ERR_VALIDATION", "unavailability_windows must be a list")
    windows = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise api_error("ERR_VALIDATION", "each unavailability window must be an object")
        start = parse_date(entry.get("start_date"), "start_date")
        end = parse_date(entry.get("end_date"), "end_date")
        if start > end:
            raise api_error("ERR_VALIDATION", "window start_date must not follow end_date")
        windows.append(
            {
                "start_date": entry["start_date"],
                "end_date": entry["end_date"],
                "_start_date": start,
                "_end_date": end,
            }
        )
    return windows


def create_reviewer_profile():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    employer_government_id = req_str(body, "employer_government_id")
    conflicted = opt_str_list(body, "conflicted_government_ids")
    windows = _parse_windows(body)
    authorize(role, ["Member"])
    # body FK resolution in input order (PRD 2.7): member_id, then employer
    if member_id not in store.members:
        raise api_error("ERR_MEMBER_NOT_FOUND", "member not found")
    if employer_government_id not in store.governments:
        raise api_error("ERR_GOVERNMENT_NOT_FOUND", "employer government not found")
    # ownership: self-application only
    if member_id != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "member_id must equal the caller's identity")
    # priority 8: closed-interval overlap (touching endpoints overlap)
    if windows and windows_overlap(windows):
        raise api_error(
            "ERR_AVAILABILITY_WINDOW_OVERLAP",
            "unavailability windows must not intersect (closed intervals)",
        )
    now = _now()
    p = {
        "id": new_id(),
        "member_id": member_id,
        "employer_government_id": employer_government_id,
        "conflicted_government_ids": conflicted,
        "unavailability_windows": windows or [],
        "independence_attested": False,
        "status": "APPLICANT",
        "trained_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.reviewer_profiles[p["id"]] = p
    return ok(reviewer_profile(p), 201)


def update_reviewer_profile(profile_id):
    uid, role = authenticate()
    body = get_body()
    # shape (priority 2)
    status = body.get("status")
    if status is not None and status not in REVIEWER_STATUSES:
        raise api_error("ERR_VALIDATION", "status must be a declared reviewer status")
    attested = body.get("independence_attested")
    if attested is not None and not isinstance(attested, bool):
        raise api_error("ERR_VALIDATION", "independence_attested must be a boolean")
    conflicted = None
    if "conflicted_government_ids" in body and body["conflicted_government_ids"] is not None:
        conflicted = opt_str_list(body, "conflicted_government_ids")
    windows = _parse_windows(body)
    authorize(role, ["Reviewer", "PlatformAdmin"])
    p = store.reviewer_profiles.get(profile_id)
    if p is None:
        raise api_error("ERR_REVIEWER_NOT_FOUND", "reviewer profile not found")
    # Plan mutations without applying them: every check must pass before any
    # field changes (an error raised mid-way must leave the record untouched).
    new_status = None
    set_trained_at = False
    new_attested = None
    if role == "Reviewer":
        # ownership: own profile only
        if uid != p["id"]:
            raise api_error("ERR_NOT_RESOURCE_OWNER", "a reviewer may update only their own profile")
        # reviewers may never write their own status
        if status is not None:
            raise api_error("ERR_FORBIDDEN_ROLE", "reviewer status is administered by PlatformAdmin")
        if attested is True:
            # TRAINED -> ELIGIBLE; APPLICANT -> ERR_REVIEWER_NOT_TRAINED
            if p["status"] == "APPLICANT":
                raise api_error("ERR_REVIEWER_NOT_TRAINED", "training must precede attestation")
            if p["status"] != "TRAINED":
                raise api_error(
                    "ERR_REVIEWER_STATE_INVALID",
                    "independence attestation requires status TRAINED",
                )
            new_status = "ELIGIBLE"
            new_attested = True
        elif attested is False:
            new_attested = False
    else:
        # PlatformAdmin: status administration per the ReviewerProfile machine
        if status is not None:
            src = p["status"]
            ok_transition = (
                (status == "TRAINED" and src == "APPLICANT")
                or (status == "SUSPENDED" and src == "ELIGIBLE")
                or (status == "ELIGIBLE" and src == "SUSPENDED")
                or (status == "RETIRED" and src in ("ELIGIBLE", "SUSPENDED"))
            )
            if not ok_transition:
                raise api_error(
                    "ERR_REVIEWER_STATE_INVALID",
                    "reviewer status transition %s -> %s not allowed" % (src, status),
                )
            new_status = status
            set_trained_at = status == "TRAINED"
    # priority 8: window overlap check (closed intervals; touching overlaps)
    if windows is not None and windows_overlap(windows):
        raise api_error(
            "ERR_AVAILABILITY_WINDOW_OVERLAP",
            "unavailability windows must not intersect (closed intervals)",
        )
    # All checks passed: apply
    now = _now()
    mutated = False
    if new_status is not None:
        p["status"] = new_status
        if set_trained_at:
            p["trained_at"] = now
        mutated = True
    if new_attested is not None:
        p["independence_attested"] = new_attested
        mutated = True
    if conflicted is not None:
        p["conflicted_government_ids"] = conflicted
        mutated = True
    if windows is not None:
        p["unavailability_windows"] = windows
        mutated = True
    if mutated:
        touch(p, now)
    return ok(reviewer_profile(p))


def get_reviewer_profile(profile_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "Reviewer"])
    p = store.reviewer_profiles.get(profile_id)
    if p is None:
        raise api_error("ERR_REVIEWER_NOT_FOUND", "reviewer profile not found")
    if role == "Reviewer" and uid != p["id"]:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "a reviewer may read only their own profile")
    return ok(reviewer_profile(p))


def list_reviewer_profiles():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector"])
    limit, offset = pagination()
    rows = list(store.reviewer_profiles.values())
    member_id = query_filter("member_id")
    if member_id is not None:
        rows = [p for p in rows if p["member_id"] == member_id]
    employer = query_filter("employer_government_id")
    if employer is not None:
        rows = [p for p in rows if p["employer_government_id"] == employer]
    status = query_filter("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return list_response(rows, reviewer_profile, limit, offset)


def register(app):
    app.add_url_rule("/gfoa/reviewer-profiles", "create_reviewer_profile", create_reviewer_profile, methods=["POST"])
    app.add_url_rule("/gfoa/reviewer-profiles/<profile_id>", "update_reviewer_profile", update_reviewer_profile, methods=["PUT"])
    app.add_url_rule("/gfoa/reviewer-profiles/<profile_id>", "get_reviewer_profile", get_reviewer_profile, methods=["GET"])
    app.add_url_rule("/gfoa/reviewer-profiles", "list_reviewer_profiles", list_reviewer_profiles, methods=["GET"])
