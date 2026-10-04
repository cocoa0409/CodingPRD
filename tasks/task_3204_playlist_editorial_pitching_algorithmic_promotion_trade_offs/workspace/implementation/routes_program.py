"""Routes: promotions, streams, fraud cases."""
import uuid

from flask import Blueprint

from store import store
from util import (auth, require_role, body_json, need, as_str, as_int, as_num,
                  as_enum, as_dt, ok_object, list_response, pub,
                  opt_enum_filter, opt_str_filter, opt_bool_filter, err)
import services as S

bp = Blueprint("program", __name__)

PROMO_READERS = ["PlatformAdmin", "RightsHolder", "FraudAnalyst"]
STREAM_READERS = ["PlatformAdmin", "FraudAnalyst"]


def get_promotion(eid):
    e = store.promotions.get(eid)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Promotion enrollment not found")
    return e


def get_stream(sid):
    s = store.streams.get(sid)
    if s is None:
        err("ERR_NOT_FOUND", 404, "Stream event not found")
    return s


def get_case(cid):
    c = store.fraud_cases.get(cid)
    if c is None:
        err("ERR_NOT_FOUND", 404, "Fraud case not found")
    return c


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------

def _windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/catalog/promotions")
def create_promotion():
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    b = body_json()
    track_id = need(b, "track_id")
    if not isinstance(track_id, str) or track_id not in store.tracks:
        err("ERR_NOT_FOUND", 404, "track_id does not exist")
    track = store.tracks[track_id]
    if S.owner_artist_id("track", track) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only enroll their own tracks")
    df = as_num(need(b, "discount_factor"), "discount_factor")
    if not (0 < df < 1):
        err("ERR_INVALID_REQUEST", 400, "discount_factor must be strictly between 0 and 1")
    starts_raw, starts_dt = as_dt(need(b, "starts_on"), "starts_on")
    ends_raw, ends_dt = as_dt(need(b, "ends_on"), "ends_on")
    if starts_dt >= ends_dt:
        err("ERR_ENROLLMENT_WINDOW_OVERLAP", 409, "starts_on must be strictly before ends_on")
    for e in store.promotions.values():
        if (e["track_id"] == track_id and e["status"] in ("ENROLLED", "SUSPENDED")
                and _windows_overlap(starts_dt, ends_dt, e["_starts_dt"], e["_ends_dt"])):
            err("ERR_ENROLLMENT_WINDOW_OVERLAP", 409,
                "Enrollment window overlaps another non-terminal enrollment for the track")
    if S.fraud_hold(track_id):
        err("ERR_FRAUD_HOLD", 409, "Track is under an open fraud investigation")
    e = S.base_entity()
    e.update({
        "track_id": track_id,
        "discount_factor": df,
        "starts_on": starts_raw,
        "ends_on": ends_raw,
        "_starts_dt": starts_dt,
        "_ends_dt": ends_dt,
        "disclosure_token": "disc_" + uuid.uuid4().hex,
        "status": "ENROLLED",
    })
    store.promotions[e["id"]] = e
    return ok_object(pub(e), 201)


@bp.get("/catalog/promotions/<eid>")
def fetch_promotion(eid):
    uid, role = auth()
    require_role(role, PROMO_READERS)
    e = get_promotion(eid)
    if role == "RightsHolder" and S.owner_artist_id("promotion", e) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only access their own enrollments")
    return ok_object(pub(e))


@bp.get("/catalog/promotions")
def list_promotions():
    uid, role = auth()
    require_role(role, PROMO_READERS)
    f_track = opt_str_filter("track_id")
    f_status = opt_enum_filter("status", S.PROMOTION_STATUSES)
    items = list(store.promotions.values())
    if role == "RightsHolder":
        items = [e for e in items if S.owner_artist_id("promotion", e) == uid]
    if f_track is not None:
        items = [e for e in items if e["track_id"] == f_track]
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    return list_response(items)


@bp.post("/catalog/promotions/<eid>/suspend")
def suspend_promotion(eid):
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    e = get_promotion(eid)
    if S.owner_artist_id("promotion", e) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only suspend their own enrollments")
    b = body_json()
    if e["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "Only an ENROLLED enrollment can be suspended")
    if b.get("disclosure_token") != e["disclosure_token"]:
        err("ERR_DISCLOSURE_TOKEN_MISMATCH", 403,
            "Suspend requires the disclosure token minted at enroll time")
    e["status"] = "SUSPENDED"
    S.touch(e)
    return ok_object(pub(e))


@bp.post("/catalog/promotions/<eid>/resume")
def resume_promotion(eid):
    uid, role = auth()
    require_role(role, ["RightsHolder"])
    e = get_promotion(eid)
    if S.owner_artist_id("promotion", e) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only resume their own enrollments")
    body_json()
    if e["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Only a SUSPENDED enrollment can be resumed")
    if store.clock >= e["_ends_dt"]:
        err("ERR_INVALID_STATE", 409, "Enrollment window has already ended")
    for o in store.promotions.values():
        if (o["id"] != e["id"] and o["track_id"] == e["track_id"] and o["status"] == "ENROLLED"
                and _windows_overlap(e["_starts_dt"], e["_ends_dt"], o["_starts_dt"], o["_ends_dt"])):
            err("ERR_ENROLLMENT_WINDOW_OVERLAP", 409,
                "Another ENROLLED row for the track overlaps this window")
    track = store.tracks[e["track_id"]]
    artist = S.artist_of_track(track)
    if artist is None or artist["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Track's artist must be ACTIVE to resume")
    if S.fraud_hold(e["track_id"]):
        err("ERR_FRAUD_HOLD", 409, "Track is under an open fraud investigation")
    e["status"] = "ENROLLED"
    S.touch(e)
    return ok_object(pub(e))


@bp.post("/catalog/promotions/<eid>/terminate")
def terminate_promotion(eid):
    uid, role = auth()
    require_role(role, ["RightsHolder", "FraudAnalyst"])
    e = get_promotion(eid)
    if role == "RightsHolder" and S.owner_artist_id("promotion", e) != uid:
        err("ERR_FORBIDDEN", 403, "RightsHolder may only terminate their own enrollments")
    if e["status"] not in ("ENROLLED", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "Only an ENROLLED or SUSPENDED enrollment can be terminated")
    e["status"] = "TERMINATED"
    S.touch(e)
    return ok_object(pub(e))


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------

@bp.post("/catalog/streams")
def create_stream():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = body_json()
    track_id = need(b, "track_id")
    if not isinstance(track_id, str) or track_id not in store.tracks:
        err("ERR_NOT_FOUND", 404, "track_id does not exist")
    territory = as_str(need(b, "territory"), "territory")
    source = as_enum(need(b, "source"), "source", S.STREAM_SOURCES)
    occ_raw, occ_dt = as_dt(need(b, "occurred_on"), "occurred_on")
    ms_played = as_int(need(b, "ms_played"), "ms_played")
    if ms_played < 0:
        err("ERR_INVALID_REQUEST", 400, "ms_played must be >= 0")
    covering = None
    for per in sorted(store.periods.values(), key=lambda x: x["_seq"]):
        if per["status"] == "OPEN" and per["_ps_dt"] <= occ_dt < per["_pe_dt"]:
            covering = per
            break
    if covering is None:
        err("ERR_NO_OPEN_PERIOD", 409, "No OPEN royalty period covers occurred_on")
    s = S.base_entity(with_version=False)
    s.update({
        "track_id": track_id,
        "territory": territory,
        "source": source,
        "occurred_on": occ_raw,
        "_occ_dt": occ_dt,
        "ms_played": ms_played,
        "is_tainted": False,
        "royalty_period_id": covering["id"],
    })
    store.streams[s["id"]] = s
    return ok_object(pub(s), 201)


@bp.get("/catalog/streams/<sid>")
def fetch_stream(sid):
    uid, role = auth()
    require_role(role, STREAM_READERS)
    s = get_stream(sid)
    return ok_object(pub(s))


@bp.get("/catalog/streams")
def list_streams():
    uid, role = auth()
    require_role(role, STREAM_READERS)
    f_track = opt_str_filter("track_id")
    f_period = opt_str_filter("royalty_period_id")
    f_tainted = opt_bool_filter("is_tainted")
    items = list(store.streams.values())
    if f_track is not None:
        items = [s for s in items if s["track_id"] == f_track]
    if f_period is not None:
        items = [s for s in items if s["royalty_period_id"] == f_period]
    if f_tainted is not None:
        items = [s for s in items if s["is_tainted"] == f_tainted]
    return list_response(items)


# ---------------------------------------------------------------------------
# Fraud cases
# ---------------------------------------------------------------------------

@bp.post("/catalog/fraud-cases")
def create_fraud_case():
    uid, role = auth()
    require_role(role, ["FraudAnalyst"])
    b = body_json()
    track_id = need(b, "track_id")
    if not isinstance(track_id, str) or track_id not in store.tracks:
        err("ERR_NOT_FOUND", 404, "track_id does not exist")
    ws_raw, ws_dt = as_dt(need(b, "window_start"), "window_start")
    we_raw, we_dt = as_dt(need(b, "window_end"), "window_end")
    if ws_dt >= we_dt:
        err("ERR_INVALID_REQUEST", 400, "window_start must be strictly before window_end")
    bot = as_num(need(b, "signal_bot_ratio"), "signal_bot_ratio")
    vel = as_num(need(b, "signal_velocity_zscore"), "signal_velocity_zscore")
    dev = as_num(need(b, "signal_device_concentration"), "signal_device_concentration")
    for name, v in (("signal_bot_ratio", bot), ("signal_velocity_zscore", vel),
                    ("signal_device_concentration", dev)):
        if v < 0 or v > 1:
            err("ERR_INVALID_REQUEST", 400, "%s must be in [0, 1]" % name)
    conf = S.fraud_confidence(bot, vel, dev)
    fc = S.base_entity()
    fc.update({
        "track_id": track_id,
        "window_start": ws_raw,
        "window_end": we_raw,
        "_ws_dt": ws_dt,
        "_we_dt": we_dt,
        "signal_bot_ratio": bot,
        "signal_velocity_zscore": vel,
        "signal_device_concentration": dev,
        "confidence_score": float(conf),
        "verdict": "AUTO_FLAGGED" if conf >= S.FRAUD_AUTO_FLAG_THRESHOLD else "OPEN",
        "clawback_cents": 0,
        "_clawback_applied": False,
    })
    store.fraud_cases[fc["id"]] = fc
    return ok_object(pub(fc), 201)


@bp.get("/catalog/fraud-cases/<cid>")
def fetch_fraud_case(cid):
    uid, role = auth()
    require_role(role, STREAM_READERS)
    fc = get_case(cid)
    return ok_object(pub(fc))


@bp.get("/catalog/fraud-cases")
def list_fraud_cases():
    uid, role = auth()
    require_role(role, STREAM_READERS)
    f_track = opt_str_filter("track_id")
    f_verdict = opt_enum_filter("verdict", S.VERDICTS)
    items = list(store.fraud_cases.values())
    if f_track is not None:
        items = [c for c in items if c["track_id"] == f_track]
    if f_verdict is not None:
        items = [c for c in items if c["verdict"] == f_verdict]
    return list_response(items)


@bp.post("/catalog/fraud-cases/<cid>/adjudicate")
def adjudicate_case(cid):
    uid, role = auth()
    require_role(role, ["FraudAnalyst"])
    fc = get_case(cid)
    b = body_json()
    verdict = as_enum(need(b, "verdict"), "verdict", ["CONFIRM", "DISMISS"])
    if fc["verdict"] not in ("OPEN", "AUTO_FLAGGED"):
        err("ERR_INVALID_STATE", 409, "Only an OPEN or AUTO_FLAGGED case can be adjudicated")
    if verdict == "DISMISS":
        fc["verdict"] = "DISMISSED"
        S.touch(fc)
        return ok_object(pub(fc))
    from decimal import Decimal
    if Decimal(str(fc["confidence_score"])) < S.FRAUD_CONFIRM_THRESHOLD:
        err("ERR_FRAUD_THRESHOLD_NOT_MET", 409,
            "CONFIRM requires confidence_score >= FRAUD_CONFIRM_THRESHOLD")
    S.confirm_case(fc)
    return ok_object(pub(fc))
