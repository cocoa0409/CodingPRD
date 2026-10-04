"""Routes: profile modules, presaves, logical clock."""
from flask import Blueprint

from store import store
from util import (auth, require_role, body_json, need, as_str, as_enum, as_dt,
                  ok_object, list_response, pub, opt_enum_filter, opt_str_filter,
                  err, ALPHA2)
import services as S

bp = Blueprint("misc", __name__)

MODULE_READERS = ["PlatformAdmin", "RightsHolder"]


def get_module(mid):
    m = store.modules.get(mid)
    if m is None:
        err("ERR_NOT_FOUND", 404, "Profile module not found")
    return m


def get_presave(pid):
    p = store.presaves.get(pid)
    if p is None:
        err("ERR_NOT_FOUND", 404, "Pre-save not found")
    return p


# ---------------------------------------------------------------------------
# Profile modules
# ---------------------------------------------------------------------------

@bp.post("/catalog/profile-modules")
def create_module():
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    b = body_json()
    if "artist_id" in b and b["artist_id"] is not None and b["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only attach modules to their own artist")
    artist_id = need(b, "artist_id")
    if not isinstance(artist_id, str) or artist_id not in store.artists:
        err("ERR_NOT_FOUND", 404, "artist_id does not exist")
    module_type = need(b, "module_type")
    track_id = b.get("track_id")
    if isinstance(module_type, str) and module_type == "CANVAS":
        if track_id is None:
            err("ERR_INVALID_REQUEST", 400, "track_id is required for CANVAS modules")
        if not isinstance(track_id, str) or track_id not in store.tracks:
            err("ERR_NOT_FOUND", 404, "track_id does not exist")
    module_type = as_enum(module_type, "module_type", S.MODULE_TYPES)
    payload_uri = as_str(need(b, "payload_uri"), "payload_uri")
    m = S.base_entity()
    m.update({
        "artist_id": artist_id,
        "module_type": module_type,
        "track_id": track_id if module_type == "CANVAS" else None,
        "payload_uri": payload_uri,
        "status": "ENABLED",
    })
    store.modules[m["id"]] = m
    return ok_object(pub(m), 201)


@bp.get("/catalog/profile-modules/<mid>")
def fetch_module(mid):
    uid, role = auth()
    require_role(role, MODULE_READERS)
    m = get_module(mid)
    if role == "RightsHolder" and m["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own modules")
    return ok_object(pub(m))


@bp.get("/catalog/profile-modules")
def list_modules():
    uid, role = auth()
    require_role(role, MODULE_READERS)
    f_artist = opt_str_filter("artist_id")
    f_track = opt_str_filter("track_id")
    f_type = opt_enum_filter("module_type", S.MODULE_TYPES)
    f_status = opt_enum_filter("status", S.MODULE_STATUSES)
    items = list(store.modules.values())
    if role == "RightsHolder":
        items = [m for m in items if m["artist_id"] == uid]
    if f_artist is not None:
        items = [m for m in items if m["artist_id"] == f_artist]
    if f_track is not None:
        items = [m for m in items if m.get("track_id") == f_track]
    if f_type is not None:
        items = [m for m in items if m["module_type"] == f_type]
    if f_status is not None:
        items = [m for m in items if m["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/profile-modules/<mid>/disable")
def disable_module(mid):
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    m = get_module(mid)
    if m["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only disable their own modules")
    if m["status"] != "ENABLED":
        err("ERR_INVALID_STATE", 409, "Only an ENABLED module can be disabled")
    m["status"] = "DISABLED"
    S.touch(m)
    return ok_object(pub(m))


# ---------------------------------------------------------------------------
# Pre-saves
# ---------------------------------------------------------------------------

@bp.post("/catalog/presaves")
def create_presave():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = body_json()
    release_id = need(b, "release_id")
    if not isinstance(release_id, str) or release_id not in store.releases:
        err("ERR_NOT_FOUND", 404, "release_id does not exist")
    rel = store.releases[release_id]
    fan_token = as_str(need(b, "fan_token"), "fan_token")
    territory = as_str(need(b, "territory"), "territory")
    if rel["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Pre-saves require a SCHEDULED release")
    if any(p["release_id"] == release_id and p["fan_token"] == fan_token
           for p in store.presaves.values()):
        err("ERR_INVALID_REQUEST", 400, "fan_token already registered for this release")
    if not ALPHA2.match(territory):
        err("ERR_TERRITORY_RESTRICTED", 422, "territory must be a valid ISO alpha-2 code")
    if rel["territory_allowlist"] and territory not in rel["territory_allowlist"]:
        err("ERR_TERRITORY_RESTRICTED", 422, "Pre-save territory is outside the release allowlist")
    p = S.base_entity(with_version=False)
    p.update({
        "release_id": release_id,
        "fan_token": fan_token,
        "territory": territory,
        "status": "SAVED",
    })
    store.presaves[p["id"]] = p
    S.recompute_presave_count(rel)
    return ok_object(pub(p), 201)


@bp.get("/catalog/presaves/<pid>")
def fetch_presave(pid):
    uid, role = auth()
    require_role(role, MODULE_READERS)
    p = get_presave(pid)
    if role == "RightsHolder" and S.owner_artist_id("presave", p) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access pre-saves on their own releases")
    return ok_object(pub(p))


@bp.get("/catalog/presaves")
def list_presaves():
    uid, role = auth()
    require_role(role, MODULE_READERS)
    f_release = opt_str_filter("release_id")
    f_status = opt_enum_filter("status", S.PRESAVE_STATUSES)
    items = list(store.presaves.values())
    if role == "RightsHolder":
        items = [p for p in items if S.owner_artist_id("presave", p) == uid]
    if f_release is not None:
        items = [p for p in items if p["release_id"] == f_release]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/presaves/<pid>/cancel")
def cancel_presave(pid):
    uid, role = auth()
    require_role(role, MODULE_READERS)
    p = get_presave(pid)
    if role == "RightsHolder" and S.owner_artist_id("presave", p) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only cancel pre-saves on their own releases")
    if p["status"] != "SAVED":
        err("ERR_INVALID_STATE", 409, "Only a SAVED pre-save can be cancelled")
    p["status"] = "CANCELLED"
    rel = store.releases.get(p["release_id"])
    if rel is not None:
        S.recompute_presave_count(rel)
    return ok_object(pub(p))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/catalog/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = body_json()
    raw, dt = as_dt(need(b, "current_utc"), "current_utc")
    S.advance_clock(dt, raw)
    return ok_object({"current_utc": raw})
