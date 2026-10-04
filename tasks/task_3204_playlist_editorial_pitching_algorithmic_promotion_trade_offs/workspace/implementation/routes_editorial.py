"""Routes: editorial playlists, pitches, placements."""
from flask import Blueprint

from store import store
from util import (auth, require_role, body_json, need, as_str, as_int, as_enum,
                  ok_object, list_response, pub, opt_enum_filter, opt_str_filter, err)
import services as S

bp = Blueprint("editorial", __name__)

PITCH_READERS = ["PlatformAdmin", "RightsHolder", "PlaylistEditor", "EditorialLead"]
DAY_SECONDS = S.DAY_SECONDS


def get_playlist(pid):
    p = store.playlists.get(pid)
    if p is None:
        err("ERR_NOT_FOUND", 404, "Playlist not found")
    return p


def get_pitch(pid):
    p = store.pitches.get(pid)
    if p is None:
        err("ERR_NOT_FOUND", 404, "Pitch not found")
    return p


def get_placement(pid):
    p = store.placements.get(pid)
    if p is None:
        err("ERR_NOT_FOUND", 404, "Placement not found")
    return p


# ---------------------------------------------------------------------------
# Playlists
# ---------------------------------------------------------------------------

@bp.post("/catalog/playlists")
def create_playlist():
    uid, role = auth()
    require_role(role, ["EditorialLead"])
    b = body_json()
    name = as_str(need(b, "name"), "name")
    genre_focus = as_enum(need(b, "genre_focus"), "genre_focus", S.GENRES)
    mood_focus = as_enum(need(b, "mood_focus"), "mood_focus", S.MOODS_ANY)
    slot_count = as_int(need(b, "slot_count"), "slot_count")
    if slot_count < 1 or slot_count > 50:
        err("ERR_INVALID_REQUEST", 400, "slot_count must be between 1 and 50")
    cadence = as_int(need(b, "rotation_cadence_days"), "rotation_cadence_days")
    if cadence < 1:
        err("ERR_INVALID_REQUEST", 400, "rotation_cadence_days must be >= 1")
    owning_team = as_enum(need(b, "owning_team"), "owning_team", S.TEAMS)
    p = S.base_entity()
    p.update({
        "name": name,
        "genre_focus": genre_focus,
        "mood_focus": mood_focus,
        "slot_count": slot_count,
        "rotation_cadence_days": cadence,
        "owning_team": owning_team,
        "status": "ACTIVE",
    })
    store.playlists[p["id"]] = p
    return ok_object(pub(p), 201)


@bp.get("/catalog/playlists/<pid>")
def fetch_playlist(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "RightsHolder", "PlaylistEditor", "EditorialLead", "FraudAnalyst"])
    p = get_playlist(pid)
    return ok_object(pub(p))


@bp.get("/catalog/playlists")
def list_playlists():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "PlaylistEditor", "EditorialLead"])
    f_team = opt_enum_filter("owning_team", S.TEAMS)
    f_status = opt_enum_filter("status", S.PLAYLIST_STATUSES)
    items = list(store.playlists.values())
    if f_team is not None:
        items = [p for p in items if p["owning_team"] == f_team]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/playlists/<pid>/retire")
def retire_playlist(pid):
    uid, role = auth()
    require_role(role, ["EditorialLead"])
    p = get_playlist(pid)
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE playlist can be retired")
    p["status"] = "RETIRED"
    S.touch(p)
    S.evict_playlist_placements(p["id"], ("SCHEDULED", "ACTIVE", "REINSTATED", "ROTATED_OUT"))
    return ok_object(pub(p))


# ---------------------------------------------------------------------------
# Pitches
# ---------------------------------------------------------------------------

@bp.post("/catalog/pitches")
def create_pitch():
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    b = body_json()
    track_id = need(b, "track_id")
    if not isinstance(track_id, str) or track_id not in store.tracks:
        err("ERR_NOT_FOUND", 404, "track_id does not exist")
    if "target_playlist_id" in b and b["target_playlist_id"] is not None:
        tp = b["target_playlist_id"]
        if not isinstance(tp, str) or tp not in store.playlists:
            err("ERR_NOT_FOUND", 404, "target_playlist_id does not exist")
    track = store.tracks[track_id]
    rel = store.releases[track["release_id"]]
    if rel["artist_id"] != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only pitch their own tracks")
    pitch_text = as_str(need(b, "pitch_text"), "pitch_text")
    if len(pitch_text) > 2000:
        err("ERR_INVALID_REQUEST", 400, "pitch_text must be at most 2000 characters")
    target_playlist_id = as_str(need(b, "target_playlist_id"), "target_playlist_id")
    playlist = store.playlists[target_playlist_id]
    # business rules in PRD order: window -> pitchability -> fit -> fraud hold
    if (rel["_rd_dt"] - store.clock).total_seconds() < S.MIN_PITCH_LEAD_DAYS * DAY_SECONDS:
        err("ERR_PITCH_WINDOW_CLOSED", 409, "Pitch submission is inside the minimum lead window")
    if (not track["is_focus_track"]) or track["status"] != "AVAILABLE" or any(
            p["track_id"] == track_id and p["status"] in S.NONTERMINAL_PITCH
            for p in store.pitches.values()):
        err("ERR_PITCH_NOT_PITCHABLE", 409,
            "Track is not the focus track, not AVAILABLE, or already has a non-terminal pitch")
    if (playlist["status"] != "ACTIVE"
            or playlist["genre_focus"] not in rel["genre_tags"]
            or (playlist["mood_focus"] != "ANY" and playlist["mood_focus"] not in rel["mood_tags"])):
        err("ERR_PLAYLIST_FIT_MISMATCH", 409,
            "Playlist retired, or genre/mood tags do not satisfy the playlist focus")
    if S.fraud_hold(track_id):
        err("ERR_FRAUD_HOLD", 409, "Track is under an open fraud investigation")
    p = S.base_entity()
    submitted_days = int((rel["_rd_dt"] - store.clock).total_seconds() // DAY_SECONDS)
    p.update({
        "track_id": track_id,
        "pitch_text": pitch_text,
        "target_playlist_id": target_playlist_id,
        "status": "PITCHED",
        "submitted_days_before_release": submitted_days,
        "revision_round": 0,
        "_submitted_at": store.clock,
    })
    store.pitches[p["id"]] = p
    return ok_object(pub(p), 201)


@bp.get("/catalog/pitches/<pid>")
def fetch_pitch(pid):
    uid, role = auth()
    require_role(role, PITCH_READERS)
    p = get_pitch(pid)
    if role == "RightsHolder" and S.owner_artist_id("pitch", p) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own pitches")
    return ok_object(pub(p))


@bp.get("/catalog/pitches")
def list_pitches():
    uid, role = auth()
    require_role(role, PITCH_READERS)
    f_track = opt_str_filter("track_id")
    f_playlist = opt_str_filter("target_playlist_id")
    f_status = opt_enum_filter("status", S.PITCH_STATUSES)
    items = list(store.pitches.values())
    if role == "RightsHolder":
        items = [p for p in items if S.owner_artist_id("pitch", p) == uid]
    if f_track is not None:
        items = [p for p in items if p["track_id"] == f_track]
    if f_playlist is not None:
        items = [p for p in items if p["target_playlist_id"] == f_playlist]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/pitches/<pid>/claim")
def claim_pitch(pid):
    uid, role = auth()
    require_role(role, ["PlaylistEditor"])
    p = get_pitch(pid)
    b = body_json()
    team = as_str(need(b, "team"), "team")
    if p["status"] != "PITCHED":
        err("ERR_INVALID_STATE", 409, "Only a PITCHED pitch can be claimed")
    playlist = store.playlists[p["target_playlist_id"]]
    if team != playlist["owning_team"]:
        err("ERR_FORBIDDEN", 403, "Editor's team does not own the target playlist")
    p["status"] = "UNDER_REVIEW"
    S.touch(p)
    return ok_object(pub(p))


@bp.post("/catalog/pitches/<pid>/request-revision")
def request_revision(pid):
    uid, role = auth()
    require_role(role, ["PlaylistEditor"])
    p = get_pitch(pid)
    if p["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an UNDER_REVIEW pitch can be sent back for revision")
    p["status"] = "NEEDS_REVISION"
    S.touch(p)
    return ok_object(pub(p))


@bp.post("/catalog/pitches/<pid>/revise")
def revise_pitch(pid):
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    p = get_pitch(pid)
    if S.owner_artist_id("pitch", p) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only revise their own pitches")
    b = body_json()
    pitch_text = as_str(need(b, "pitch_text"), "pitch_text")
    if len(pitch_text) > 2000:
        err("ERR_INVALID_REQUEST", 400, "pitch_text must be at most 2000 characters")
    if p["status"] != "NEEDS_REVISION":
        err("ERR_INVALID_STATE", 409, "Only a NEEDS_REVISION pitch can be revised")
    if p["revision_round"] >= S.MAX_REVISION_ROUNDS:
        err("ERR_INVALID_STATE", 409, "Maximum revision rounds reached")
    rel = S.release_of_pitch(p)
    if (rel is None or rel["status"] != "SCHEDULED"
            or (rel["_rd_dt"] - store.clock).total_seconds() < S.MIN_PITCH_LEAD_DAYS * DAY_SECONDS):
        err("ERR_PITCH_WINDOW_CLOSED", 409, "Revision is inside the minimum lead window or release not SCHEDULED")
    p["pitch_text"] = pitch_text
    p["revision_round"] += 1
    p["status"] = "PITCHED"
    S.touch(p)
    return ok_object(pub(p))


@bp.post("/catalog/pitches/<pid>/decide")
def decide_pitch(pid):
    uid, role = auth()
    require_role(role, ["EditorialLead"])
    p = get_pitch(pid)
    b = body_json()
    decision = as_enum(need(b, "decision"), "decision", ["ACCEPT", "REJECT"])
    if p["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an UNDER_REVIEW pitch can be decided")
    if decision == "REJECT":
        p["status"] = "REJECTED"
        S.touch(p)
        return ok_object(pub(p))
    # ACCEPT
    rel = S.release_of_pitch(p)
    if rel is None or rel["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Pitch release must still be SCHEDULED to accept")
    artist = store.artists[rel["artist_id"]]
    if artist["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Pitch artist must be ACTIVE to accept")
    playlist = store.playlists[p["target_playlist_id"]]
    occupied = {
        pl["slot_index"] for pl in store.placements.values()
        if pl["playlist_id"] == playlist["id"] and pl["status"] in ("SCHEDULED", "ACTIVE", "REINSTATED")
    }
    free = None
    for s in range(playlist["slot_count"]):
        if s not in occupied:
            free = s
            break
    if free is None:
        err("ERR_NO_FREE_SLOT", 409, "No free slot on the target playlist")
    p["status"] = "ACCEPTED"
    S.touch(p)
    placement = S.base_entity()
    placement.update({
        "playlist_id": playlist["id"],
        "track_id": p["track_id"],
        "pitch_id": p["id"],
        "slot_index": free,
        "activated_on": None,
        "scheduled_rotation_on": None,
        "status": "SCHEDULED",
        "_act_dt": None,
        "_srot_dt": None,
    })
    store.placements[placement["id"]] = placement
    return ok_object(pub(p))


@bp.post("/catalog/pitches/<pid>/withdraw")
def withdraw_pitch(pid):
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    p = get_pitch(pid)
    if S.owner_artist_id("pitch", p) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only withdraw their own pitches")
    if p["status"] not in S.NONTERMINAL_PITCH:
        err("ERR_INVALID_STATE", 409, "Only a non-terminal pitch can be withdrawn")
    S.withdraw_pitch(p)
    return ok_object(pub(p))


# ---------------------------------------------------------------------------
# Placements
# ---------------------------------------------------------------------------

@bp.get("/catalog/placements/<pid>")
def fetch_placement(pid):
    uid, role = auth()
    require_role(role, PITCH_READERS)
    p = get_placement(pid)
    if role == "RightsHolder" and S.owner_artist_id("placement", p) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own placements")
    return ok_object(pub(p))


@bp.get("/catalog/placements")
def list_placements():
    uid, role = auth()
    require_role(role, PITCH_READERS)
    f_playlist = opt_str_filter("playlist_id")
    f_track = opt_str_filter("track_id")
    f_pitch = opt_str_filter("pitch_id")
    f_status = opt_enum_filter("status", S.PLACEMENT_STATUSES)
    items = list(store.placements.values())
    if role == "RightsHolder":
        items = [p for p in items if S.owner_artist_id("placement", p) == uid]
    if f_playlist is not None:
        items = [p for p in items if p["playlist_id"] == f_playlist]
    if f_track is not None:
        items = [p for p in items if p["track_id"] == f_track]
    if f_pitch is not None:
        items = [p for p in items if p["pitch_id"] == f_pitch]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    return list_response(items)


def _slot_occupied(playlist_id, slot_index):
    return any(
        pl["playlist_id"] == playlist_id and pl["slot_index"] == slot_index
        and pl["status"] in ("ACTIVE", "REINSTATED")
        for pl in store.placements.values()
    )


def _placement_env_checks(p):
    playlist = store.playlists[p["playlist_id"]]
    if playlist["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Playlist must be ACTIVE")
    track = store.tracks[p["track_id"]]
    if track["status"] != "AVAILABLE":
        err("ERR_INVALID_STATE", 409, "Track must be AVAILABLE")
    rel = store.releases[track["release_id"]]
    if rel["status"] != "LIVE":
        err("ERR_INVALID_STATE", 409, "Release must be LIVE")
    return playlist, track


def _stamp_window(p, playlist):
    from datetime import timedelta
    from util import fmt_instant
    p["activated_on"] = fmt_instant(store.clock)
    p["_act_dt"] = store.clock
    rot = store.clock + timedelta(days=playlist["rotation_cadence_days"])
    p["scheduled_rotation_on"] = fmt_instant(rot)
    p["_srot_dt"] = rot
    p.pop("_deactivated_on", None)


@bp.post("/catalog/placements/<pid>/activate")
def activate_placement(pid):
    uid, role = auth()
    require_role(role, ["PlaylistEditor"])
    p = get_placement(pid)
    if p["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Only a SCHEDULED placement can be activated")
    playlist, track = _placement_env_checks(p)
    if _slot_occupied(p["playlist_id"], p["slot_index"]):
        err("ERR_SLOT_OCCUPIED", 409, "Slot is occupied by an ACTIVE or REINSTATED placement")
    if S.fraud_hold(p["track_id"]):
        err("ERR_FRAUD_HOLD", 409, "Track is under an open fraud investigation")
    p["status"] = "ACTIVE"
    _stamp_window(p, playlist)
    S.touch(p)
    return ok_object(pub(p))


@bp.post("/catalog/placements/<pid>/rotate")
def rotate_placement(pid):
    uid, role = auth()
    require_role(role, ["PlaylistEditor"])
    p = get_placement(pid)
    if p["status"] not in ("ACTIVE", "REINSTATED"):
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE or REINSTATED placement can be rotated")
    if store.clock < p["_srot_dt"]:
        err("ERR_ROTATION_TOO_EARLY", 409, "Manual rotation before scheduled_rotation_on is forbidden")
    p["status"] = "ROTATED_OUT"
    p["_deactivated_on"] = store.clock
    S.touch(p)
    return ok_object(pub(p))


@bp.post("/catalog/placements/<pid>/reinstate")
def reinstate_placement(pid):
    uid, role = auth()
    require_role(role, ["PlaylistEditor"])
    p = get_placement(pid)
    if p["status"] != "ROTATED_OUT":
        err("ERR_INVALID_STATE", 409, "Only a ROTATED_OUT placement can be reinstated")
    playlist, track = _placement_env_checks(p)
    if _slot_occupied(p["playlist_id"], p["slot_index"]):
        err("ERR_SLOT_OCCUPIED", 409, "Slot is occupied by an ACTIVE or REINSTATED placement")
    p["status"] = "REINSTATED"
    _stamp_window(p, playlist)
    S.touch(p)
    return ok_object(pub(p))
