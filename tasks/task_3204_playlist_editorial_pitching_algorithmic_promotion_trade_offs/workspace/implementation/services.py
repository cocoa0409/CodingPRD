"""Business services: entity helpers, cascades, calculations, clock transitions."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from store import store
from util import fmt_ts, fmt_instant, new_id

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml constants / calculations)
# ---------------------------------------------------------------------------
MIN_PITCH_LEAD_DAYS = 7
PITCH_WINDOW_DAYS = 7
MAX_REVISION_ROUNDS = 2
MAX_DATE_CHANGES = 3
FRAUD_STRIKE_LIMIT = 2
TERMINATION_STRIKE_LIMIT = 3
FRAUD_AUTO_FLAG_THRESHOLD = Decimal("0.7000")
FRAUD_CONFIRM_THRESHOLD = Decimal("0.8500")
PER_STREAM_RATE_CENTS = Decimal("0.40")
BOOST_CAP = 90
BPS_BASE = 10000
DAY_SECONDS = 86400

GENRES = ["POP", "HIPHOP", "ROCK", "ELECTRONIC", "LATIN", "COUNTRY", "JAZZ", "CLASSICAL"]
MOODS = ["CHILL", "ENERGETIC", "MELANCHOLY", "FOCUS", "PARTY", "ROMANTIC"]
MOODS_ANY = MOODS + ["ANY"]
TEAMS = ["EDITORIAL_A", "EDITORIAL_B"]
RELEASE_TYPES = ["SINGLE", "EP", "ALBUM"]
STREAM_SOURCES = ["EDITORIAL_PLAYLIST", "ALGORITHMIC", "ORGANIC"]
MODULE_TYPES = ["CANVAS", "MERCH"]

ARTIST_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
RELEASE_STATUSES = ["SCHEDULED", "LIVE", "REMOVED"]
TRACK_STATUSES = ["AVAILABLE", "REMOVED"]
PITCH_STATUSES = ["PITCHED", "UNDER_REVIEW", "NEEDS_REVISION", "ACCEPTED", "REJECTED", "WITHDRAWN"]
PLAYLIST_STATUSES = ["ACTIVE", "RETIRED"]
PLACEMENT_STATUSES = ["SCHEDULED", "ACTIVE", "ROTATED_OUT", "REINSTATED", "EVICTED"]
PROMOTION_STATUSES = ["ENROLLED", "SUSPENDED", "TERMINATED"]
VERDICTS = ["OPEN", "AUTO_FLAGGED", "CONFIRMED", "DISMISSED"]
PERIOD_STATUSES = ["OPEN", "CLOSED", "SETTLED"]
MODULE_STATUSES = ["ENABLED", "DISABLED"]
PRESAVE_STATUSES = ["SAVED", "CONVERTED", "CANCELLED"]

NONTERMINAL_PITCH = ("PITCHED", "UNDER_REVIEW", "NEEDS_REVISION")


def dec(v):
    return Decimal(str(v))


def base_entity(with_version=True):
    e = {"id": new_id(), "created_at": fmt_ts(store.clock)}
    if with_version:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    e["_seq"] = store.next_seq()
    return e


def touch(e):
    """Refresh updated_at and bump version on a common-fields entity."""
    if "version" in e:
        e["updated_at"] = fmt_ts(store.clock)
        e["version"] += 1


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def tracks_of_release(rid):
    return [t for t in store.tracks.values() if t["release_id"] == rid]


def tracks_of_artist(aid):
    rids = {r["id"] for r in store.releases.values() if r["artist_id"] == aid}
    return [t for t in store.tracks.values() if t["release_id"] in rids]


def artist_of_track(track):
    rel = store.releases.get(track["release_id"])
    return store.artists.get(rel["artist_id"]) if rel else None


def release_of_pitch(pitch):
    t = store.tracks.get(pitch["track_id"])
    return store.releases.get(t["release_id"]) if t else None


def owner_artist_id(kind, e):
    if kind == "artist":
        return e["id"]
    if kind == "release":
        return e["artist_id"]
    if kind == "track":
        return store.releases[e["release_id"]]["artist_id"]
    if kind == "pitch":
        return owner_artist_id("track", store.tracks[e["track_id"]])
    if kind == "placement":
        return owner_artist_id("track", store.tracks[e["track_id"]])
    if kind == "promotion":
        return owner_artist_id("track", store.tracks[e["track_id"]])
    if kind == "statement":
        return e["artist_id"]
    if kind == "module":
        return e["artist_id"]
    if kind == "presave":
        return store.releases[e["release_id"]]["artist_id"]
    return None


def fraud_hold(track_id):
    return any(
        fc["track_id"] == track_id and fc["verdict"] in ("OPEN", "AUTO_FLAGGED")
        for fc in store.fraud_cases.values()
    )


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def recompute_presave_count(release):
    n = sum(
        1 for p in store.presaves.values()
        if p["release_id"] == release["id"] and p["status"] in ("SAVED", "CONVERTED")
    )
    if n != release["presave_count"]:
        release["presave_count"] = n
        touch(release)


def withdraw_pitch(p, bump_release=True):
    if p["status"] in NONTERMINAL_PITCH:
        p["status"] = "WITHDRAWN"
        touch(p)
        if bump_release:
            rel = release_of_pitch(p)
            if rel is not None:
                touch(rel)


def evict_placements(track_ids, statuses):
    ids = set(track_ids)
    for p in sorted(store.placements.values(), key=lambda x: x["_seq"]):
        if p["track_id"] in ids and p["status"] in statuses:
            if p["status"] in ("ACTIVE", "REINSTATED"):
                p["_deactivated_on"] = store.clock
            p["status"] = "EVICTED"
            touch(p)


def evict_playlist_placements(playlist_id, statuses):
    for p in sorted(store.placements.values(), key=lambda x: x["_seq"]):
        if p["playlist_id"] == playlist_id and p["status"] in statuses:
            if p["status"] in ("ACTIVE", "REINSTATED"):
                p["_deactivated_on"] = store.clock
            p["status"] = "EVICTED"
            touch(p)


def terminate_enrollments(track_ids, statuses=("ENROLLED", "SUSPENDED")):
    ids = set(track_ids)
    for e in sorted(store.promotions.values(), key=lambda x: x["_seq"]):
        if e["track_id"] in ids and e["status"] in statuses:
            e["status"] = "TERMINATED"
            touch(e)


def disable_modules_for_track(tid):
    for m in store.modules.values():
        if m.get("track_id") == tid and m["module_type"] == "CANVAS" and m["status"] == "ENABLED":
            m["status"] = "DISABLED"
            touch(m)


def remove_track(t, evict_statuses=("SCHEDULED", "ACTIVE", "REINSTATED")):
    if t["status"] == "AVAILABLE":
        t["status"] = "REMOVED"
        touch(t)
    evict_placements([t["id"]], evict_statuses)
    terminate_enrollments([t["id"]])
    disable_modules_for_track(t["id"])


def suspend_artist(a):
    if a["status"] != "ACTIVE":
        return
    a["status"] = "SUSPENDED"
    touch(a)
    tids = [t["id"] for t in tracks_of_artist(a["id"])]
    terminate_enrollments(tids, ("ENROLLED",))
    evict_placements(tids, ("ACTIVE", "REINSTATED"))


def terminate_artist(a):
    if a["status"] == "TERMINATED":
        return
    a["status"] = "TERMINATED"
    touch(a)
    tids = []
    for t in tracks_of_artist(a["id"]):
        tids.append(t["id"])
        if t["status"] == "AVAILABLE":
            t["status"] = "REMOVED"
            touch(t)
        disable_modules_for_track(t["id"])
    evict_placements(tids, ("SCHEDULED", "ACTIVE", "REINSTATED", "ROTATED_OUT"))
    terminate_enrollments(tids, ("ENROLLED", "SUSPENDED"))
    for m in store.modules.values():
        if m["artist_id"] == a["id"] and m["status"] == "ENABLED":
            m["status"] = "DISABLED"
            touch(m)
    for r in store.releases.values():
        if r["artist_id"] == a["id"] and r["status"] == "LIVE":
            r["status"] = "REMOVED"
            touch(r)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def effective_rate(track_id, occurred_dt):
    """1.0, or the covering enrollment's discount_factor (windows non-overlap)."""
    for e in store.promotions.values():
        if e["track_id"] == track_id and e["_starts_dt"] <= occurred_dt < e["_ends_dt"]:
            return dec(e["discount_factor"])
    return Decimal("1")


def fraud_confidence(b, v, d):
    val = Decimal("0.40") * dec(b) + Decimal("0.35") * dec(v) + Decimal("0.25") * dec(d)
    return val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def confirm_case(fc):
    fc["verdict"] = "CONFIRMED"
    touch(fc)
    track = store.tracks[fc["track_id"]]
    rel = store.releases[track["release_id"]]
    artist = store.artists[rel["artist_id"]]
    # 1. taint streams in [window_start, window_end) not already tainted
    newly = []
    for s in store.streams.values():
        if (s["track_id"] == fc["track_id"] and not s["is_tainted"]
                and fc["_ws_dt"] <= s["_occ_dt"] < fc["_we_dt"]):
            s["is_tainted"] = True
            newly.append(s)
    # 2. clawback over newly tainted streams
    total = Decimal("0")
    for s in newly:
        total += effective_rate(fc["track_id"], s["_occ_dt"]) * PER_STREAM_RATE_CENTS
    cents = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    fc["clawback_cents"] = cents
    target = None
    for st in sorted(store.statements.values(), key=lambda x: x["_seq"]):
        per = store.periods[st["period_id"]]
        if st["artist_id"] == artist["id"] and per["status"] == "CLOSED":
            target = st
            break
    if target is not None:
        target["clawback_cents"] += cents
        target["net_payout_cents"] = target["gross_payout_cents"] - target["clawback_cents"]
        touch(target)
        fc["_clawback_applied"] = True
    # 3. terminate enrollments; 4. evict placements
    terminate_enrollments([fc["track_id"]], ("ENROLLED", "SUSPENDED"))
    evict_placements([fc["track_id"]], ("ACTIVE", "REINSTATED"))
    # 5. strike cascade
    artist["fraud_strikes"] += 1
    touch(artist)
    if artist["fraud_strikes"] >= TERMINATION_STRIKE_LIMIT:
        terminate_artist(artist)
    elif artist["fraud_strikes"] >= FRAUD_STRIKE_LIMIT:
        suspend_artist(artist)


def generate_statements(period):
    streams = [s for s in store.streams.values()
               if s["royalty_period_id"] == period["id"] and not s["is_tainted"]]
    per_artist = {}
    for s in streams:
        t = store.tracks[s["track_id"]]
        r = store.releases[t["release_id"]]
        aid = r["artist_id"]
        w = effective_rate(s["track_id"], s["_occ_dt"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ent = per_artist.setdefault(aid, {"raw": 0, "eff": Decimal("0")})
        ent["raw"] += 1
        ent["eff"] += w
    if not per_artist:
        return
    if period["closed_variant"] == "GROSS":
        denom = Decimal(sum(e["raw"] for e in per_artist.values()))
        for e in per_artist.values():
            e["share"] = int((Decimal(BPS_BASE) * Decimal(e["raw"]) / denom)
                             .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        denom = sum(e["eff"] for e in per_artist.values())
        for e in per_artist.values():
            e["share"] = int((Decimal(BPS_BASE) * e["eff"] / denom)
                             .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    pool = period["pool_cents"]
    total_floor = 0
    for e in per_artist.values():
        e["gross"] = int((Decimal(pool) * Decimal(e["share"]) / Decimal(BPS_BASE))
                         .to_integral_value(rounding=ROUND_FLOOR))
        total_floor += e["gross"]
    remainder = pool - total_floor
    order = sorted(
        per_artist.items(),
        key=lambda kv: (-kv[1]["share"], store.artists[kv[0]]["created_at"], store.artists[kv[0]]["_seq"]),
    )
    idx = 0
    while remainder > 0 and order:
        order[idx % len(order)][1]["gross"] += 1
        remainder -= 1
        idx += 1
    for aid, e in sorted(per_artist.items(), key=lambda kv: store.artists[kv[0]]["_seq"]):
        pending = 0
        for fc in sorted(store.fraud_cases.values(), key=lambda x: x["_seq"]):
            if fc["verdict"] == "CONFIRMED" and not fc.get("_clawback_applied"):
                t = store.tracks[fc["track_id"]]
                if store.releases[t["release_id"]]["artist_id"] == aid:
                    pending += fc["clawback_cents"]
                    fc["_clawback_applied"] = True
        st = base_entity()
        st.update({
            "period_id": period["id"],
            "artist_id": aid,
            "raw_streams": e["raw"],
            "effective_streams": float(e["eff"]),
            "share_bps": e["share"],
            "gross_payout_cents": e["gross"],
            "clawback_cents": pending,
            "net_payout_cents": e["gross"] - pending,
        })
        store.statements[st["id"]] = st


def boost_score(track, window_start_dt, window_end_dt, save_rate, completion_rate, skip_rate):
    raw = Decimal(100) * (Decimal("0.5") * dec(save_rate)
                          + Decimal("0.3") * dec(completion_rate)
                          - Decimal("0.2") * dec(skip_rate))
    artist = artist_of_track(track)
    fc_ = artist["follower_count"]
    if fc_ < 10000:
        mult = Decimal("0.8")
    elif fc_ < 100000:
        mult = Decimal("1.0")
    else:
        mult = Decimal("1.2")
    score = int((raw * mult).to_integral_value(rounding=ROUND_FLOOR))
    score = min(BOOST_CAP, max(0, score))
    placed = False
    for p in store.placements.values():
        if p["track_id"] != track["id"]:
            continue
        act = p.get("_act_dt")
        if act is None:
            continue
        deact = p.get("_deactivated_on")
        if act < window_end_dt and (deact is None or deact > window_start_dt):
            placed = True
            break
    variant = "STANDARD" if placed else "COLD_START"
    if variant == "COLD_START":
        score = score // 2
    return score, variant


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def go_live(r):
    r["status"] = "LIVE"
    touch(r)
    rows = [p for p in store.presaves.values()
            if p["release_id"] == r["id"] and p["status"] == "SAVED"]
    rows.sort(key=lambda p: (p["created_at"], p["fan_token"]))
    allow = r["territory_allowlist"]
    for p in rows:
        p["status"] = "CONVERTED" if (not allow or p["territory"] in allow) else "CANCELLED"
    recompute_presave_count(r)


def advance_clock(dt, raw):
    store.clock = dt
    store.clock_raw = raw
    for r in sorted(store.releases.values(), key=lambda x: x["_seq"]):
        if r["status"] == "SCHEDULED" and r["_rd_dt"] <= store.clock:
            a = store.artists.get(r["artist_id"])
            if a is not None and a["status"] == "ACTIVE":
                go_live(r)
    for p in sorted(store.placements.values(), key=lambda x: x["_seq"]):
        if p["status"] in ("ACTIVE", "REINSTATED") and p.get("_srot_dt") is not None \
                and p["_srot_dt"] <= store.clock:
            p["status"] = "ROTATED_OUT"
            p["_deactivated_on"] = store.clock
            touch(p)
