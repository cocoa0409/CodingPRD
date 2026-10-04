"""Routes: artists, releases, tracks."""
from flask import Blueprint

from store import store
from util import (auth, require_role, body_json, need, as_str, as_int, as_num, as_enum,
                  as_dt, as_bool, as_str_list, ok_object, list_response, pub,
                  opt_enum_filter, opt_str_filter, err, ALPHA2)
import services as S

bp = Blueprint("core", __name__)

ALL_ROLES = ["PlatformAdmin", "RightsHolder", "PlaylistEditor", "EditorialLead", "FraudAnalyst"]


def get_artist(aid):
    a = store.artists.get(aid)
    if a is None:
        err("ERR_NOT_FOUND", 404, "Artist not found")
    return a


def get_release(rid):
    r = store.releases.get(rid)
    if r is None:
        err("ERR_NOT_FOUND", 404, "Release not found")
    return r


def get_track(tid):
    t = store.tracks.get(tid)
    if t is None:
        err("ERR_NOT_FOUND", 404, "Track not found")
    return t


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------

@bp.post("/catalog/artists")
def create_artist():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = body_json()
    stage_name = as_str(need(b, "stage_name"), "stage_name")
    primary_genre = as_enum(need(b, "primary_genre"), "primary_genre", S.GENRES)
    home_territory = as_str(need(b, "home_territory"), "home_territory")
    if not ALPHA2.match(home_territory):
        err("ERR_INVALID_REQUEST", 400, "home_territory must be an ISO alpha-2 code")
    follower_count = as_int(need(b, "follower_count"), "follower_count")
    if follower_count < 0:
        err("ERR_INVALID_REQUEST", 400, "follower_count must be >= 0")
    a = S.base_entity()
    a.update({
        "stage_name": stage_name,
        "primary_genre": primary_genre,
        "home_territory": home_territory,
        "follower_count": follower_count,
        "status": "ACTIVE",
        "fraud_strikes": 0,
    })
    store.artists[a["id"]] = a
    return ok_object(pub(a), 201)


@bp.get("/catalog/artists/<aid>")
def fetch_artist(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    if role == "RightsHolder" and aid != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own artist record")
    a = get_artist(aid)
    return ok_object(pub(a))


@bp.get("/catalog/artists")
def list_artists():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "PlaylistEditor", "EditorialLead", "FraudAnalyst"])
    f_status = opt_enum_filter("status", S.ARTIST_STATUSES)
    f_genre = opt_enum_filter("primary_genre", S.GENRES)
    items = list(store.artists.values())
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    if f_genre is not None:
        items = [a for a in items if a["primary_genre"] == f_genre]
    return list_response(items)


@bp.post("/catalog/artists/<aid>/suspend")
def suspend_artist(aid):
    uid, role = auth()
    require_role(role, ["FraudAnalyst"])
    a = get_artist(aid)
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE artist can be suspended")
    S.suspend_artist(a)
    return ok_object(pub(a))


@bp.post("/catalog/artists/<aid>/reinstate")
def reinstate_artist(aid):
    uid, role = auth()
    require_role(role, ["FraudAnalyst"])
    a = get_artist(aid)
    if a["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Only a SUSPENDED artist can be reinstated")
    if a["fraud_strikes"] >= S.FRAUD_STRIKE_LIMIT:
        err("ERR_INVALID_STATE", 409, "Artist at the fraud strike limit cannot be reinstated")
    a["status"] = "ACTIVE"
    S.touch(a)
    return ok_object(pub(a))


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

@bp.post("/catalog/releases")
def create_release():
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    b = body_json()
    # Ownership (priority 2) before body-FK existence (priority 3)
    if "artist_id" in b and b["artist_id"] is not None and b["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only create releases for their own artist")
    artist_id = need(b, "artist_id")
    if not isinstance(artist_id, str) or artist_id not in store.artists:
        err("ERR_NOT_FOUND", 404, "artist_id does not exist")
    title = as_str(need(b, "title"), "title")
    release_type = as_enum(need(b, "release_type"), "release_type", S.RELEASE_TYPES)
    rd_raw, rd_dt = as_dt(need(b, "release_date"), "release_date")
    genre_tags = as_str_list(need(b, "genre_tags"), "genre_tags")
    if not (1 <= len(genre_tags) <= 3) or any(g not in S.GENRES for g in genre_tags):
        err("ERR_INVALID_REQUEST", 400, "genre_tags must contain 1-3 declared genre values")
    mood_tags = as_str_list(need(b, "mood_tags"), "mood_tags")
    if len(mood_tags) > 4 or any(m not in S.MOODS for m in mood_tags):
        err("ERR_INVALID_REQUEST", 400, "mood_tags must contain 0-4 declared mood values")
    allowlist = b.get("territory_allowlist", [])
    allowlist = as_str_list(allowlist, "territory_allowlist")
    for t in allowlist:
        if not ALPHA2.match(t):
            err("ERR_TERRITORY_RESTRICTED", 422, "territory_allowlist entries must be valid ISO alpha-2 codes")
    r = S.base_entity()
    r.update({
        "artist_id": artist_id,
        "title": title,
        "release_type": release_type,
        "release_date": rd_raw,
        "_rd_dt": rd_dt,
        "territory_allowlist": allowlist,
        "genre_tags": genre_tags,
        "mood_tags": mood_tags,
        "status": "SCHEDULED",
        "date_change_count": 0,
        "presave_count": 0,
    })
    store.releases[r["id"]] = r
    return ok_object(pub(r), 201)


@bp.get("/catalog/releases/<rid>")
def fetch_release(rid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    r = get_release(rid)
    if role == "RightsHolder" and r["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own releases")
    return ok_object(pub(r))


@bp.get("/catalog/releases")
def list_releases():
    uid, role = auth()
    require_role(role, ALL_ROLES)
    f_artist = opt_str_filter("artist_id")
    f_status = opt_enum_filter("status", S.RELEASE_STATUSES)
    items = list(store.releases.values())
    if role == "RightsHolder":
        items = [r for r in items if r["artist_id"] == uid]
    if f_artist is not None:
        items = [r for r in items if r["artist_id"] == f_artist]
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/releases/<rid>/change-date")
def change_release_date(rid):
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    r = get_release(rid)
    if r["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only change their own releases")
    b = body_json()
    new_raw, new_dt = as_dt(need(b, "release_date"), "release_date")
    expected = as_int(need(b, "expected_release_version"), "expected_release_version")
    if r["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Only a SCHEDULED release can change its date")
    if ((r["_rd_dt"] - store.clock).total_seconds() < S.PITCH_WINDOW_DAYS * S.DAY_SECONDS
            or new_dt <= store.clock
            or r["date_change_count"] >= S.MAX_DATE_CHANGES):
        err("ERR_DATE_CHANGE_WINDOW", 409,
            "Date change inside the pitch window, new date not in the future, or MAX_DATE_CHANGES reached")
    if expected != r["version"]:
        err("ERR_STALE_VERSION", 412, "expected_release_version does not match the release version")
    r["release_date"] = new_raw
    r["_rd_dt"] = new_dt
    r["date_change_count"] += 1
    S.touch(r)
    # withdraw pitches that lose the minimum lead under the new date
    tids = {t["id"] for t in S.tracks_of_release(r["id"])}
    for p in sorted(store.pitches.values(), key=lambda x: x["_seq"]):
        if p["track_id"] in tids and p["status"] in S.NONTERMINAL_PITCH:
            new_days = int((new_dt - p["_submitted_at"]).total_seconds() // S.DAY_SECONDS)
            if new_days < S.MIN_PITCH_LEAD_DAYS:
                S.withdraw_pitch(p)
    return ok_object(pub(r))


@bp.post("/catalog/releases/<rid>/remove")
def remove_release(rid):
    uid, role = auth()
    require_role(role, ["RightsHolder", "FraudAnalyst"])
    r = get_release(rid)
    if role == "RightsHolder":
        if r["artist_id"] != uid:
            err("ERR_FORBIDDEN", 403, "RightsHolder may only remove their own releases")
        if r["status"] != "SCHEDULED":
            err("ERR_INVALID_STATE", 409, "RightsHolder may only remove a SCHEDULED release")
    else:
        if r["status"] == "REMOVED":
            err("ERR_INVALID_STATE", 409, "Release is already REMOVED")
    was = r["status"]
    r["status"] = "REMOVED"
    S.touch(r)
    tracks = S.tracks_of_release(r["id"])
    if was == "SCHEDULED":
        for t in tracks:
            S.remove_track(t, evict_statuses=("SCHEDULED", "ACTIVE", "REINSTATED"))
        for p in store.presaves.values():
            if p["release_id"] == r["id"] and p["status"] == "SAVED":
                p["status"] = "CANCELLED"
        tids = {t["id"] for t in tracks}
        for pitch in sorted(store.pitches.values(), key=lambda x: x["_seq"]):
            if pitch["track_id"] in tids and pitch["status"] in S.NONTERMINAL_PITCH:
                pitch["status"] = "WITHDRAWN"
                S.touch(pitch)
        S.recompute_presave_count(r)
    else:  # LIVE removal via fraud path
        for t in tracks:
            S.remove_track(t, evict_statuses=("SCHEDULED", "ACTIVE", "REINSTATED", "ROTATED_OUT"))
    return ok_object(pub(r))


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

@bp.post("/catalog/tracks")
def create_track():
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    b = body_json()
    release_id = need(b, "release_id")
    if not isinstance(release_id, str) or release_id not in store.releases:
        err("ERR_NOT_FOUND", 404, "release_id does not exist")
    rel = store.releases[release_id]
    if rel["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only add tracks to their own releases")
    title = as_str(need(b, "title"), "title")
    duration_ms = as_int(need(b, "duration_ms"), "duration_ms")
    if duration_ms < 30000:
        err("ERR_INVALID_REQUEST", 400, "duration_ms must be >= 30000")
    focus = b.get("is_focus_track", False)
    focus = as_bool(focus, "is_focus_track")
    if focus:
        for t in S.tracks_of_release(release_id):
            if t["is_focus_track"]:
                err("ERR_INVALID_REQUEST", 400, "Release already has a focus track")
    t = S.base_entity()
    t.update({
        "release_id": release_id,
        "title": title,
        "duration_ms": duration_ms,
        "is_focus_track": focus,
        "status": "AVAILABLE",
    })
    store.tracks[t["id"]] = t
    return ok_object(pub(t), 201)


@bp.get("/catalog/tracks/<tid>")
def fetch_track(tid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    t = get_track(tid)
    if role == "RightsHolder" and S.owner_artist_id("track", t) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own tracks")
    return ok_object(pub(t))


@bp.get("/catalog/tracks")
def list_tracks():
    uid, role = auth()
    require_role(role, ALL_ROLES)
    f_release = opt_str_filter("release_id")
    f_status = opt_enum_filter("status", S.TRACK_STATUSES)
    items = list(store.tracks.values())
    if role == "RightsHolder":
        items = [t for t in items if S.owner_artist_id("track", t) == uid]
    if f_release is not None:
        items = [t for t in items if t["release_id"] == f_release]
    if f_status is not None:
        items = [t for t in items if t["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/tracks/<tid>/signal-rollup")
def signal_rollup(tid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    t = get_track(tid)
    b = body_json()
    _, ws_dt = as_dt(need(b, "window_start"), "window_start")
    _, we_dt = as_dt(need(b, "window_end"), "window_end")
    save_rate = as_num(need(b, "save_rate"), "save_rate")
    completion_rate = as_num(need(b, "completion_rate"), "completion_rate")
    skip_rate = as_num(need(b, "skip_rate"), "skip_rate")
    for name, v in (("save_rate", save_rate), ("completion_rate", completion_rate), ("skip_rate", skip_rate)):
        if v < 0 or v > 1:
            err("ERR_INVALID_REQUEST", 400, "%s must be in [0, 1]" % name)
    score, variant = S.boost_score(t, ws_dt, we_dt, save_rate, completion_rate, skip_rate)
    return ok_object({"boost_score": score, "variant": variant})
