"""Every named calculation of the PRD, with its pinned order and rounding.

PRD 2.8: money and bandwidth carry two decimals, score-shaped figures two
decimals, and ratio/unit-price/composite figures four decimals; every quantise
is ROUND_HALF_UP.
"""

import math
from decimal import Decimal

from db import D0, db, dec, q2, q4, rows

# ---------------------------------------------------------------------------
# Title collections
# ---------------------------------------------------------------------------


def title_assets(title_id):
    return [a for a in rows(db.assets) if a["title_id"] == title_id]


def title_ladders(title_id):
    return [l for l in rows(db.ladders) if l["title_id"] == title_id]


def title_packages(title_id):
    return [p for p in rows(db.packages) if p["title_id"] == title_id]


def title_windows(title_id):
    return [w for w in rows(db.windows) if w["title_id"] == title_id]


def title_jobs(title_id):
    return [j for j in rows(db.jobs) if j["title_id"] == title_id]


def package_rules(package_id):
    return [r for r in rows(db.entitlement_rules) if r["package_id"] == package_id]


def vendor_metrics(vendor_id):
    return [m for m in rows(db.metrics) if m["vendor_id"] == vendor_id]


# ---------------------------------------------------------------------------
# Readiness scoring (PRD 3.1): weights 0.50 master, 0.20 ladder, 0.30 package.
# Each component is rounded to two decimals *before* being weighted.
# ---------------------------------------------------------------------------

W_MASTER = Decimal("0.50")
W_LADDER = Decimal("0.20")
W_PACKAGE = Decimal("0.30")

READINESS_GATE = Decimal("80.00")


def _component_master(assets, passing_states):
    if not assets:
        return q2(0)
    hits = len([a for a in assets if a["qc_state"] in passing_states])
    return q2(dec(100) * dec(hits) / dec(len(assets)))


def _component_flag(present):
    return q2(100) if present else q2(0)


def readiness_scores(title_id):
    assets = title_assets(title_id)
    ladders = title_ladders(title_id)
    packages = title_packages(title_id)

    prov_master = _component_master(assets, ("INGESTED", "QC_PASSED"))
    prov_ladder = _component_flag(
        any(l["state"] in ("DRAFT", "VALIDATED", "LOCKED") for l in ladders)
    )
    prov_package = _component_flag(
        any(p["state"] in ("PENDING", "PACKAGED") for p in packages)
    )
    provisional = q2(
        prov_master * W_MASTER + prov_ladder * W_LADDER + prov_package * W_PACKAGE
    )

    cert_master = _component_master(assets, ("QC_PASSED",))
    cert_ladder = _component_flag(any(l["state"] == "LOCKED" for l in ladders))
    cert_package = _component_flag(any(p["state"] == "PACKAGED" for p in packages))
    certified = q2(
        cert_master * W_MASTER + cert_ladder * W_LADDER + cert_package * W_PACKAGE
    )
    return provisional, certified


# ---------------------------------------------------------------------------
# QC verdict (PRD 3.2)
# ---------------------------------------------------------------------------

LOUDNESS_TARGET = Decimal("-24.0")
LOUDNESS_TOLERANCE = Decimal("2.0")
LOUDNESS_WEIGHT = Decimal("6.0")
ARTIFACT_WEIGHT = Decimal("4.0")
CAPTION_PENALTY = Decimal("30.0")


def qc_figures(asset):
    deviation = q2(abs(dec(asset["peak_audio_lufs"]) - LOUDNESS_TARGET))
    coverage = q2(100) if asset["audio_language"] in asset["caption_languages"] else q2(0)
    artifact_penalty = q2(dec(asset["artifact_defect_count"]) * ARTIFACT_WEIGHT)
    excess = deviation - LOUDNESS_TOLERANCE
    if excess < 0:
        excess = D0
    loudness_penalty = q2(excess * LOUDNESS_WEIGHT)
    caption_penalty = q2(0) if coverage == q2(100) else q2(CAPTION_PENALTY)
    severity = q2(artifact_penalty + loudness_penalty + caption_penalty)

    blocking = []
    if asset["artifact_defect_count"] >= 8:
        blocking.append("ARTIFACT_BURST")
    if deviation > Decimal("6.0"):
        blocking.append("LOUDNESS_OUT_OF_SPEC")
    if coverage == q2(0):
        blocking.append("CAPTION_MISSING")
    if len(blocking) >= 2:
        code = "MULTI_DEFECT"
    elif len(blocking) == 1:
        code = blocking[0]
    elif severity >= Decimal("40.0"):
        code = "MULTI_DEFECT"
    else:
        code = "NONE"

    if code != "NONE":
        verdict = "FAIL"
    elif severity > q2(0) or asset["artifact_defect_count"] >= 3:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return {
        "loudness_deviation_db": deviation,
        "caption_coverage_pct": coverage,
        "artifact_penalty": artifact_penalty,
        "loudness_penalty": loudness_penalty,
        "caption_penalty": caption_penalty,
        "severity_index": severity,
        "blocking_defect_code": code,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Device compatibility scoring (PRD 3.3)
# ---------------------------------------------------------------------------

COVERAGE_TARGET_RUNGS = Decimal("5")
RESOLUTION_BONUS = Decimal("5.00")

TV_CLASSES = ("SMART_TV_4K", "SMART_TV_HD", "SET_TOP_LEGACY")
MOBILE_CLASSES = ("MOBILE_HIGH", "MOBILE_LOW")


def _rung_fits(rung, profile):
    return (
        rung["height_px"] <= profile["max_height_px"]
        and rung["bitrate_kbps"] >= profile["min_bitrate_kbps"]
        and rung["bitrate_kbps"] <= profile["max_bitrate_kbps"]
    )


def _drm_satisfied(profile, title_id):
    required = profile["required_drm_system"]
    if required == "NONE":
        return True
    for package in title_packages(title_id):
        if package["state"] in ("PENDING", "PACKAGED") and required in package["drm_systems"]:
            return True
    return False


def compat_figures(ladder):
    candidates = [p for p in rows(db.device_profiles) if p["state"] == "ACTIVE"]
    compatible = []
    for profile in candidates:
        if ladder["codec_family"] not in profile["supported_codecs"]:
            continue
        if not any(_rung_fits(r, profile) for r in ladder["rungs"]):
            continue
        if not _drm_satisfied(profile, ladder["title_id"]):
            continue
        compatible.append(profile)
    count = len(compatible)
    multiplier = dec(ladder["rung_count"]) / COVERAGE_TARGET_RUNGS
    if multiplier > Decimal("1.00"):
        multiplier = Decimal("1.00")
    reach = sum((dec(p["market_share_pct"]) for p in compatible), D0)
    base = q2(reach * multiplier)
    bonus = RESOLUTION_BONUS if (ladder["peak_height_px"] >= 2160 and count >= 1) else q2(0)
    score = base + bonus
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return q2(score), count


def rung_geometry_flaw(rungs):
    """Rejection precedence: bitrate monotonicity, then duplicate height."""
    bitrates = [r["bitrate_kbps"] for r in rungs]
    heights = [r["height_px"] for r in rungs]
    if any(bitrates[i] >= bitrates[i + 1] for i in range(len(bitrates) - 1)):
        return "BITRATE_NOT_MONOTONIC"
    if len(set(heights)) != len(heights):
        return "DUPLICATE_HEIGHT"
    if any(heights[i] >= heights[i + 1] for i in range(len(heights) - 1)):
        return "BITRATE_NOT_MONOTONIC"
    return None


# ---------------------------------------------------------------------------
# Reprocess cost estimate (PRD 3.9) -- per-rung costs are rounded to cents
# *before* being summed; the sum is then re-rounded.
# ---------------------------------------------------------------------------

CODEC_FACTORS = {
    "H264": Decimal("1.00"),
    "HEVC": Decimal("1.35"),
    "AV1": Decimal("2.10"),
}

ENCODE_RATE = Decimal("0.02")

TRIGGER_WEIGHTS = {
    "CODEC_DEPRECATION": Decimal("40.0"),
    "STANDARD_UPDATE": Decimal("30.0"),
    "QUALITY_REGRESSION": Decimal("20.0"),
    "DEVICE_MATRIX_CHANGE": Decimal("10.0"),
}

PRIORITY_COST_CAP = Decimal("20.0")


def billable_minutes(title_id):
    durations = [
        a["duration_seconds"]
        for a in title_assets(title_id)
        if a["qc_state"] != "QC_REJECTED"
    ]
    if not durations:
        return 0
    return int(math.ceil(max(durations) / 60.0))


def reprocess_cost(title_id, rungs, target_codec):
    minutes_billed = dec(billable_minutes(title_id))
    factor = CODEC_FACTORS[target_codec]
    per_rung = []
    for rung in rungs:
        mbps = dec(rung["bitrate_kbps"]) / Decimal("1000.0")
        per_rung.append(q2(minutes_billed * mbps * factor * ENCODE_RATE))
    total = q2(sum(per_rung, D0))
    return per_rung, total


def priority_rank(trigger_reason, cost_estimate):
    contribution = dec(cost_estimate) / Decimal("10.0")
    if contribution > PRIORITY_COST_CAP:
        contribution = PRIORITY_COST_CAP
    return q2(TRIGGER_WEIGHTS[trigger_reason] + contribution)


# ---------------------------------------------------------------------------
# Vendor selection and egress projection (PRD 3.7)
# ---------------------------------------------------------------------------

HEALTH_ELIGIBILITY_FLOOR = Decimal("60.00")
WEIGHTED_COST_WEIGHT = Decimal("1000.0")
WEIGHTED_SURCHARGE_EXTRA = Decimal("0.02")
GB_PER_PLAY = Decimal("2.5")
FLAT_ZERO_DEMAND_GB = Decimal("1000.00")

REASON_CODES = {
    "PERFORMANCE": "PERFORMANCE_RANK",
    "COST": "COST_RANK",
    "WEIGHTED": "WEIGHTED_RANK",
}


def weighted_composite(vendor):
    return q4(
        dec(vendor["health_score_contract"])
        - dec(vendor["cost_per_gb_usd"]) * WEIGHTED_COST_WEIGHT
    )


def eligible_vendors(region_code, excluded):
    out = []
    for vendor in rows(db.vendors):
        if vendor["state"] != "ACTIVE":
            continue
        if region_code not in vendor["regions"]:
            continue
        if dec(vendor["health_score_contract"]) < HEALTH_ELIGIBILITY_FLOOR:
            continue
        if vendor["id"] in excluded:
            continue
        out.append(vendor)
    return out


def rank_vendors(candidates, steering_mode):
    """created_at ascending is the final and exhaustive tie-break in all modes."""
    ordered = sorted(candidates, key=lambda v: v["_seq"])
    ordered.sort(key=lambda v: (v["created_at"],))
    if steering_mode == "PERFORMANCE":
        ordered.sort(
            key=lambda v: (-dec(v["health_score_contract"]), dec(v["cost_per_gb_usd"]))
        )
    elif steering_mode == "COST":
        ordered.sort(
            key=lambda v: (dec(v["cost_per_gb_usd"]), -dec(v["health_score_contract"]))
        )
    else:
        ordered.sort(key=lambda v: -weighted_composite(v))
    return ordered


def select_vendors(region_code, excluded, steering_mode):
    ranked = rank_vendors(eligible_vendors(region_code, excluded), steering_mode)
    primary = ranked[0]["id"] if len(ranked) >= 1 else None
    backup = ranked[1]["id"] if len(ranked) >= 2 else None
    if len(ranked) >= 2:
        state = "ACTIVE"
    elif len(ranked) == 1:
        state = "STANDBY_ONLY"
    else:
        state = "UNROUTABLE"
    reason = REASON_CODES[steering_mode] if ranked else "NO_CANDIDATE"
    return primary, backup, state, reason, len(ranked)


def egress_projection(policy):
    attempts = 0
    for metric in rows(db.metrics):
        if metric["title_id"] == policy["title_id"] and metric["region_code"] == policy["region_code"]:
            attempts += metric["play_attempts"]
    if attempts == 0:
        volume_gb = q2(FLAT_ZERO_DEMAND_GB)
    else:
        volume_gb = q2(dec(attempts) * GB_PER_PLAY)
    primary_id = policy.get("primary_vendor_id")
    if not primary_id:
        return q2(0)
    vendor = db.vendors.get(primary_id)
    if vendor is None:
        return q2(0)
    base_cost = q2(volume_gb * dec(vendor["cost_per_gb_usd"]))
    if base_cost < Decimal("500.00"):
        rate = Decimal("0.08")
    elif base_cost < Decimal("2000.00"):
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.03")
    if policy["steering_mode"] == "WEIGHTED":
        rate = rate + WEIGHTED_SURCHARGE_EXTRA
    surcharge = q2(base_cost * rate)
    return q2(base_cost + surcharge)


# ---------------------------------------------------------------------------
# Playback quality index and vendor health (PRD 3.7)
# ---------------------------------------------------------------------------

REBUFFER_WEIGHT = Decimal("2.5")
STARTUP_TARGET_MS = Decimal("2000")
STARTUP_WEIGHT = Decimal("1.5")
ERROR_WEIGHT = Decimal("4.0")
BREACH_THRESHOLD = Decimal("70.00")
BREACH_COUNT_DRAIN = 5
DEGRADE_FLOOR = Decimal("50.00")
RECOVERY_FLOOR = Decimal("75.00")


def quality_figures(play_attempts, rebuffer_events, startup_ms_p95, error_count, profile):
    attempts = dec(play_attempts)
    rebuffer_ratio = q4(dec(rebuffer_events) / attempts)
    error_rate = q4(dec(error_count) / attempts)
    startup_excess = dec(startup_ms_p95) - STARTUP_TARGET_MS
    if startup_excess < 0:
        startup_excess = D0
    penalty_raw = q4(
        rebuffer_ratio * dec(100) * REBUFFER_WEIGHT
        + (startup_excess / Decimal("100.0")) * STARTUP_WEIGHT
        + error_rate * dec(100) * ERROR_WEIGHT
    )
    penalty = q4(penalty_raw * dec(profile["quality_normalization_factor"]))
    index = dec(100) - penalty
    if index < 0:
        index = D0
    if index > dec(100):
        index = dec(100)
    quality_index = q2(index)
    return {
        "rebuffer_ratio": rebuffer_ratio,
        "error_rate": error_rate,
        "quality_index": quality_index,
        "breach_flag": quality_index < BREACH_THRESHOLD,
    }


def vendor_health(vendor_id):
    metrics = vendor_metrics(vendor_id)
    if not metrics:
        return q2(100), q2(100), 0
    newest = sorted(metrics, key=lambda m: m["_seq"])
    newest.sort(key=lambda m: (m["window_start_at"], m["created_at"]), reverse=True)
    window = newest[:3]
    rolling = q2(
        sum((dec(m["quality_index"]) for m in window), D0) / dec(len(window))
    )
    weight_total = sum((dec(m["play_attempts"]) for m in metrics), D0)
    weighted = sum(
        (dec(m["quality_index"]) * dec(m["play_attempts"]) for m in metrics), D0
    )
    contract = q2(weighted / weight_total) if weight_total > 0 else q2(100)
    breaches = len([m for m in metrics if m["breach_flag"]])
    return rolling, contract, breaches


# ---------------------------------------------------------------------------
# Two interval geometries (PRD 2.10)
# ---------------------------------------------------------------------------


def windows_conflict(existing, req_start, req_end):
    """Licensing windows are half-open; abutting intervals never conflict."""
    return existing["window_start_at"] < req_end and req_start < existing["window_end_at"]


def reservation_holders(vendor_id, exclude_reservation_id=None):
    out = []
    for reservation in rows(db.reservations):
        if reservation["active_vendor_id"] != vendor_id:
            continue
        if reservation["state"] not in ("RESERVED", "ARMED", "LIVE", "FAILED_OVER"):
            continue
        if exclude_reservation_id and reservation["id"] == exclude_reservation_id:
            continue
        out.append(reservation)
    return out


def reserved_ledger(vendor_id):
    """Derived bandwidth ledger, never an incrementally patched counter."""
    held = sum(
        (dec(r["reserved_gbps"]) for r in reservation_holders(vendor_id)), D0
    )
    return q2(held)


def capacity_held_against(vendor_id, req_start, req_end, buffer_min, exclude_id=None):
    """Closed, buffer-inflated geometry: each side inflates by its own buffer."""
    from db import minutes

    lo = req_start - minutes(buffer_min)
    hi = req_end + minutes(buffer_min)
    total = D0
    for reservation in reservation_holders(vendor_id, exclude_id):
        own_lo = reservation["window_start_at"] - minutes(reservation["buffer_minutes"])
        own_hi = reservation["window_end_at"] + minutes(reservation["buffer_minutes"])
        if own_lo <= hi and own_hi >= lo:
            total += dec(reservation["reserved_gbps"])
    return q2(total)


# ---------------------------------------------------------------------------
# Entitlement decision (PRD 3.5)
# ---------------------------------------------------------------------------


def rule_matches(rule, region_code, subscription_tier, device_class, device_profile):
    if not (rule["region_code"] == region_code or rule["region_code"] == "*"):
        return False
    if not (rule["subscription_tier"] == subscription_tier or rule["subscription_tier"] == "ANY"):
        return False
    scope = rule["device_class_scope"]
    if scope == "TV_ONLY" and device_class not in TV_CLASSES:
        return False
    if scope == "MOBILE_ONLY" and device_class not in MOBILE_CLASSES:
        return False
    if device_profile["hdcp_required"] and rule["hdcp_level"] not in ("TYPE_0", "TYPE_1"):
        return False
    return True


def rank_rules(candidates, region_code):
    """priority DESC, then region specificity DESC, then created_at ASC."""
    ordered = sorted(candidates, key=lambda r: r["_seq"])
    ordered.sort(key=lambda r: r["created_at"])
    ordered.sort(
        key=lambda r: (-r["priority"], 0 if r["region_code"] == region_code else 1)
    )
    return ordered


HDCP_ORDER = {"NONE": 0, "TYPE_0": 1, "TYPE_1": 2}
