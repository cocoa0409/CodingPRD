"""Domain logic: scoring math, duplicate sweep, fielding cascades, awards,
license fees, and entitlement lookups. All index math is exact Decimal with
round-half-up to 0 decimals at the pinned rounding steps."""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import clock, store
from errors import fail
from records import new_record, touch

BASE_CENTS = {"DIGITAL": 250000, "NATIONAL": 600000, "GLOBAL": 1500000}
INCLUDED_MARKETS = {"DIGITAL": 1, "NATIONAL": 3, "GLOBAL": 999}
PER_MARKET_CENTS = 150000
TERM_DISCOUNT = Decimal("0.85")
PRIOR_VIOLATION_MULT = Decimal("1.25")
MIN_FEE_CENTS = 220000
MINOR_SUSPENSION_THRESHOLD = 2


# ---------------------------------------------------------------- lookups

def factors_of(mv_id):
    if mv_id is None:
        return []
    fs = [f for f in store.factors.values() if f["methodology_version_id"] == mv_id]
    return sorted(fs, key=lambda f: (f["ordinal"], f["_seq"]))


def active_mv(study):
    return store.methodology_versions.get(study["active_methodology_id"])


def frames_of(study_id):
    return [f for f in store.sample_frames.values() if f["study_id"] == study_id]


def brand_results_of(study_id):
    return [b for b in store.brand_results.values() if b["study_id"] == study_id]


def find_brand_result(study_id, brand_id):
    for b in store.brand_results.values():
        if b["study_id"] == study_id and b["brand_id"] == brand_id:
            return b
    return None


def accepted_responses(study_id, brand_id):
    return [
        r for r in store.responses.values()
        if r["study_id"] == study_id and r["brand_id"] == brand_id
        and r["quality_status"] == "ACCEPTED"
    ]


def find_active_subscription(client_id, study_id):
    now = clock.now()
    for s in store.subscriptions.values():
        if (
            s["client_id"] == client_id
            and s["study_id"] == study_id
            and s["status"] == "ACTIVE"
            and s["starts_at"] <= now <= s["ends_at"]
        ):
            return s
    return None


# ---------------------------------------------------------------- index math

def _rhu(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def factor_scores(responses, factors):
    """Per-factor integer scores: round_half_up(mean * 100), each rounded
    BEFORE the weighted sum (pinned order)."""
    out = []
    for f in factors:
        total = 0
        for r in responses:
            for e in r["factor_scores"]:
                if e.get("factor_code") == f["code"]:
                    total += e.get("score")
                    break
        mean100 = (Decimal(total) * 100) / Decimal(len(responses))
        out.append((f, _rhu(mean100)))
    return out


def index_score(responses, factors):
    if not responses:
        return None
    fs = factor_scores(responses, factors)
    weighted = sum(Decimal(f["weight_bp"] * s) for f, s in fs)
    return _rhu(weighted / Decimal(10000))


# ---------------------------------------------------------------- fielding

def sweep_brand(study_id, brand_id):
    """Duplicate sweep within one brand: among ACCEPTED responses sharing a
    respondent_token keep earliest submitted_at; tie -> PANEL frame over
    CUSTOMER_LIST; further tie -> earliest created_at. Losers flip to
    REJECTED with reject_reason DUPLICATE (terminal)."""
    accepted = accepted_responses(study_id, brand_id)
    by_token = {}
    for r in accepted:
        by_token.setdefault(r["respondent_token"], []).append(r)
    for token, rs in by_token.items():
        if len(rs) < 2:
            continue

        def key(r):
            f = store.sample_frames.get(r["frame_id"])
            panel = 0 if (f is not None and f["source_type"] == "PANEL") else 1
            return (r["submitted_at"], panel, r["created_at"], r["_seq"])

        rs.sort(key=key)
        for loser in rs[1:]:
            loser["quality_status"] = "REJECTED"
            loser["reject_reason"] = "DUPLICATE"
            touch(loser)


def close_fielding(study):
    """FIELDING -> FIELDING_CLOSED cascade: close OPEN frames, sweep each
    closed frame's brand, then upsert one BrandResult per framed brand with
    the pre-sweep provisional snapshot and post-sweep accepted_n."""
    sid = study["id"]
    frames = frames_of(sid)
    brands = []
    for f in frames:
        if f["brand_id"] not in brands:
            brands.append(f["brand_id"])
    pre = {bid: accepted_responses(sid, bid) for bid in brands}
    flipped = [f for f in frames if f["status"] == "OPEN"]
    for f in flipped:
        f["status"] = "CLOSED"
        touch(f)
    for f in flipped:
        sweep_brand(sid, f["brand_id"])
    factors = factors_of(study["active_methodology_id"])
    for bid in brands:
        post = accepted_responses(sid, bid)
        br = find_brand_result(sid, bid)
        if br is None:
            br = new_record()
            br.update({"study_id": sid, "brand_id": bid})
            store.brand_results[br["id"]] = br
        br["provisional_accepted_n"] = len(pre[bid])
        br["provisional_index"] = index_score(pre[bid], factors) if pre[bid] else None
        br["accepted_n"] = len(post)
        br["final_index"] = None
        br["eligible"] = None
        br["significance_group"] = None
        br["rank_position"] = None
        br["status"] = "PROVISIONAL"
        touch(br)


def shortfall_brand_ids(study):
    sid = study["id"]
    framed = {f["brand_id"] for f in frames_of(sid)}
    results = brand_results_of(sid)
    short = set()
    for bid in framed:
        br = next((b for b in results if b["brand_id"] == bid), None)
        n = br["accepted_n"] if br is not None else 0
        if n < study["min_sample_per_brand"]:
            short.add(bid)
    return short


def reopen_fielding(study, from_scored):
    short = shortfall_brand_ids(study)
    if not short:
        fail("ERR_NO_SHORTFALL", "No framed brand is below min_sample_per_brand")
    for f in frames_of(study["id"]):
        if f["status"] == "CLOSED" and f["brand_id"] in short:
            f["status"] = "OPEN"
            touch(f)
    if from_scored:
        for br in brand_results_of(study["id"]):
            br["eligible"] = None
            br["significance_group"] = None
            br["rank_position"] = None
            br["final_index"] = None
            br["status"] = "PROVISIONAL"
            touch(br)
    study["status"] = "FIELDING"


# ---------------------------------------------------------------- scoring / awards

def compute_scoring(study):
    sid = study["id"]
    any_accepted = any(
        r["study_id"] == sid and r["quality_status"] == "ACCEPTED"
        for r in store.responses.values()
    )
    if not any_accepted:
        fail("ERR_NO_RESPONSES", "Scoring compute requires at least one ACCEPTED response")
    mv = active_mv(study)
    factors = factors_of(mv["id"])
    results = brand_results_of(sid)
    for br in results:
        rs = accepted_responses(sid, br["brand_id"])
        br["accepted_n"] = len(rs)
        br["final_index"] = index_score(rs, factors) if rs else None
        br["eligible"] = br["accepted_n"] >= study["min_sample_per_brand"]
        br["significance_group"] = None
        br["rank_position"] = None
        br["status"] = "FINAL"
        touch(br)
    elig = [br for br in results if br["eligible"]]

    def brand_order_key(br):
        b = store.brands.get(br["brand_id"])
        return (b["created_at"], b["_seq"]) if b is not None else (study["created_at"], 0)

    elig.sort(key=lambda br: (-br["final_index"], -br["accepted_n"], brand_order_key(br)))
    z = float(mv["z_value"])
    sd = float(mv["pooled_sd_1000"])
    eps = float(mv["tie_epsilon"])
    group = 0
    leader = None
    for br in elig:
        if leader is None:
            group = 1
            br["significance_group"] = 1
            leader = br
            continue
        cd = z * sd * math.sqrt(1.0 / leader["accepted_n"] + 1.0 / br["accepted_n"])
        if leader["final_index"] - br["final_index"] > cd:
            group += 1
            br["significance_group"] = group
            leader = br
        else:
            br["significance_group"] = group
    for br in elig:
        br["rank_position"] = 1 + sum(
            1 for o in elig if o["final_index"] > br["final_index"] + eps
        )
    study["status"] = "SCORED"
    touch(study)
    return {
        "study_id": sid,
        "computed_count": len(results),
        "eligible_count": len(elig),
    }


def determine_awards(study, user_id):
    sid = study["id"]
    mv = active_mv(study)
    if mv is not None and mv.get("pinned_by_user_id") == user_id:
        fail("ERR_SOD_CONFLICT", "Award determiner may not be the methodology pinner")
    results = brand_results_of(sid)
    if not any(br["eligible"] for br in results):
        fail("ERR_NO_ELIGIBLE_BRAND", "At least one eligible BrandResult is required")
    winners = [
        br for br in results
        if br["eligible"] and br["rank_position"] == 1 and br["significance_group"] == 1
    ]
    winners.sort(key=lambda br: br["_seq"])
    for br in winners:
        a = new_record()
        a.update({
            "study_id": sid,
            "brand_id": br["brand_id"],
            "rank_position": br["rank_position"],
            "significance_group": br["significance_group"],
            "status": "EMBARGOED",
            "published_at": None,
        })
        store.awards[a["id"]] = a
        br["status"] = "AWARDED"
        touch(br)
    study["status"] = "AWARDS_SET"
    touch(study)
    return {"study_id": sid, "award_count": len(winners)}


# ---------------------------------------------------------------- licensing

def fee_quote(tier, markets):
    return BASE_CENTS[tier] + max(0, markets - INCLUDED_MARKETS[tier]) * PER_MARKET_CENTS


def fee_invoice(lic):
    raw = BASE_CENTS[lic["tier"]] + max(0, lic["markets_count"] - INCLUDED_MARKETS[lic["tier"]]) * PER_MARKET_CENTS
    term_mult = Decimal("0.85") if lic["term_months"] >= 24 else Decimal("1")
    has_revoked = any(
        l["client_id"] == lic["client_id"] and l["status"] == "REVOKED"
        for l in store.licenses.values()
    )
    viol_mult = PRIOR_VIOLATION_MULT if has_revoked else Decimal("1")
    fee = _rhu(Decimal(raw) * term_mult * viol_mult)
    return max(MIN_FEE_CENTS, fee)


def suspend_license(lic):
    lic["status"] = "SUSPENDED"
    lic["suspension_count"] += 1
    touch(lic)


def resolve_open_audits(license_id, resolution):
    for a in store.usage_audits.values():
        if a["license_id"] == license_id and a["status"] in ("OPEN", "ESCALATED"):
            a["status"] = "RESOLVED"
            a["resolution"] = resolution
            touch(a)
