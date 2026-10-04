"""/survey/release-events: create, list, read, advance (PRD 2.7, 2.9, 3.9)."""
from flask import Blueprint, request

from authz import get_auth, require_role, require_action_role
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_VALIDATION, ERR_CYCLE_NOT_FOUND, ERR_RELEASE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_CYCLE_NOT_CERTIFIED,
    ERR_DISCLOSURE_NOT_APPROVED, ERR_SEGREGATION_OF_DUTIES,
    ERR_PREANNOUNCE_LEAD_TOO_SHORT, ERR_DUPLICATE_RELEASE, ERR_RELEASE_TOO_EARLY,
)
from releases_util import (
    check_window_overlap, embargo_open_at_for, revoke_grants,
)
from store import DB, new_entity, sorted_entities, touch, now, PREANNOUNCE_LEAD
from validate import get_body, req_str, req_int, req_instant

bp = Blueprint("releases", __name__)

ACTION_ROLES = {
    "POSTPONE": {"ReleaseManager"},
    "RESCHEDULE": {"ReleaseManager"},
    "OPEN_EMBARGO": {"ReleaseManager"},
    "PUBLISH": {"ReleaseManager"},
    "APPROVE_DISCLOSURE": {"DisclosureOfficer"},
    "REJECT_DISCLOSURE": {"DisclosureOfficer"},
}


@bp.post("/release-events")
def create_release():
    _user, role = get_auth()
    require_role(role, {"ReleaseManager"})
    data = get_body()

    cycle = None
    if data.get("cycle_id") is not None:
        cycle = DB["cycles"].get(data["cycle_id"])
        if cycle is None:
            raise_err(ERR_CYCLE_NOT_FOUND, "cycle_id does not resolve")

    req_str(data, "cycle_id")
    release_at = req_instant(data, "release_at")

    # Temporal: the 3-day pre-announcement lead.
    if release_at < now() + PREANNOUNCE_LEAD:
        raise_err(ERR_PREANNOUNCE_LEAD_TOO_SHORT,
                  "release_at must be at least 3 days after the current clock")

    # Business: one release per cycle; embargo windows may not overlap.
    if any(r for r in DB["releases"].values() if r["cycle_id"] == cycle["id"]):
        raise_err(ERR_DUPLICATE_RELEASE, "a release already exists for this cycle")
    program = next(
        (p for p in DB["programs"].values() if p["code"] == cycle["program_code"]),
        None,
    )
    embargo_open_at = embargo_open_at_for(program, release_at)
    check_window_overlap(program["code"], embargo_open_at, release_at)

    release = new_entity("releases", {
        "cycle_id": cycle["id"],
        "program_code": cycle["program_code"],
        "release_at": release_at,
        "embargo_open_at": embargo_open_at,
        "pub_status": "SCHEDULED",
        "disclosure_status": "PENDING",
        "revision_notice_required": False,
        "active_embargo_grant_count": 0,
    })
    return ok(release, status=201)


@bp.get("/release-events")
def list_releases():
    get_auth()
    items = sorted_entities("releases")
    for param in ("cycle_id", "pub_status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _load_release(rid):
    release = DB["releases"].get(rid)
    if release is None:
        raise_err(ERR_RELEASE_NOT_FOUND, "release event not found")
    return release


@bp.get("/release-events/<rid>")
def get_release(rid):
    get_auth()
    return ok(_load_release(rid))


def _open_embargo(release):
    if release["pub_status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE,
                  f"cannot open embargo from {release['pub_status']}")
    return release


def _check_cycle_certified(cycle, allowed):
    if cycle["cycle_status"] not in allowed:
        raise_err(ERR_CYCLE_NOT_CERTIFIED,
                  f"cycle must be {' or '.join(allowed)}")


def _check_disclosure_approved(release):
    if release["disclosure_status"] != "APPROVED":
        raise_err(ERR_DISCLOSURE_NOT_APPROVED,
                  "disclosure_status must be APPROVED")


@bp.post("/release-events/<rid>/advance")
def advance_release(rid):
    user, role = get_auth()
    require_role(role, {"ReleaseManager", "DisclosureOfficer"})
    # Stage 2 per-action authorization precedes stage 3 path existence
    # (PRD 2.8); peek without raising so a malformed body reports at stage 5.
    peek = request.get_json(silent=True)
    if isinstance(peek, dict):
        require_action_role(role, peek.get("action"), ACTION_ROLES)
    release = _load_release(rid)
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTION_ROLES:
        raise_err(ERR_VALIDATION, f"unknown release action '{action}'")
    expected_version = req_int(data, "expected_release_version")
    new_release_at = None
    if action == "RESCHEDULE":
        new_release_at = req_instant(data, "new_release_at")

    cycle = DB["cycles"].get(release["cycle_id"])
    pub = release["pub_status"]
    discl = release["disclosure_status"]
    clock = now()

    # Stage 6: generic state validity per action.
    if action == "POSTPONE" and pub not in ("SCHEDULED", "EMBARGO_OPEN"):
        raise_err(ERR_INVALID_STATE, f"cannot postpone a release in {pub}")
    if action == "RESCHEDULE" and pub != "POSTPONED":
        raise_err(ERR_INVALID_STATE, f"cannot reschedule a release in {pub}")
    if action == "OPEN_EMBARGO" and pub != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"cannot open embargo from {pub}")
    if action == "PUBLISH" and pub != "EMBARGO_OPEN":
        raise_err(ERR_INVALID_STATE, f"cannot publish from {pub}")
    if action in ("APPROVE_DISCLOSURE", "REJECT_DISCLOSURE") \
            and discl not in ("PENDING", "REJECTED"):
        raise_err(ERR_INVALID_STATE,
                  f"disclosure review not possible from {discl}")

    # Stage 7: OCC on the release.
    if expected_version != release["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_release_version does not match the release version")

    # Stages 8-11 in declared order.
    if action == "OPEN_EMBARGO":
        _check_cycle_certified(cycle, ("CERTIFIED",))
        _check_disclosure_approved(release)
        if clock < release["embargo_open_at"]:
            raise_err(ERR_RELEASE_TOO_EARLY, "embargo window has not opened yet")
    elif action == "PUBLISH":
        _check_disclosure_approved(release)
        if clock < release["release_at"]:
            raise_err(ERR_RELEASE_TOO_EARLY, "release instant has not arrived yet")
    elif action in ("APPROVE_DISCLOSURE", "REJECT_DISCLOSURE"):
        _check_cycle_certified(cycle, ("CERTIFIED", "PUBLISHED"))
        if user == cycle["certified_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "the certifying analyst may not review this release's disclosure")
    elif action == "RESCHEDULE":
        if new_release_at < clock + PREANNOUNCE_LEAD:
            raise_err(ERR_PREANNOUNCE_LEAD_TOO_SHORT,
                      "new_release_at must be at least 3 days after the current clock")
        program = next(
            (p for p in DB["programs"].values() if p["code"] == release["program_code"]),
            None,
        )
        new_open = embargo_open_at_for(program, new_release_at)
        check_window_overlap(program["code"], new_open, new_release_at,
                             exclude_id=release["id"])

    # Side effects.
    if action == "POSTPONE":
        if pub == "EMBARGO_OPEN":
            revoke_grants(
                [g for g in DB["grants"].values()
                 if g["release_event_id"] == release["id"]],
                touch_releases=False,
            )
            release["active_embargo_grant_count"] = 0
        release["pub_status"] = "POSTPONED"
    elif action == "RESCHEDULE":
        release["release_at"] = new_release_at
        release["embargo_open_at"] = new_open
        release["pub_status"] = "SCHEDULED"
    elif action == "OPEN_EMBARGO":
        count = 0
        for outlet in sorted_entities("outlets"):
            if outlet["accreditation_status"] != "ACCREDITED":
                continue
            new_entity("grants", {
                "release_event_id": release["id"],
                "media_outlet_id": outlet["id"],
                "grant_status": "ISSUED",
                "issued_at": clock,
                "first_accessed_at": None,
            })
            count += 1
        release["active_embargo_grant_count"] = count
        release["pub_status"] = "EMBARGO_OPEN"
    elif action == "PUBLISH":
        release["pub_status"] = "PUBLISHED"
        if cycle["cycle_status"] == "CERTIFIED":
            cycle["cycle_status"] = "PUBLISHED"
            touch(cycle)
    elif action == "APPROVE_DISCLOSURE":
        release["disclosure_status"] = "APPROVED"
        release["revision_notice_required"] = False
    elif action == "REJECT_DISCLOSURE":
        release["disclosure_status"] = "REJECTED"

    touch(release)  # every successful release advance increments version by 1
    return ok(release)
