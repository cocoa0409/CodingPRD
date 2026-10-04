"""Calculations and shared business logic."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err

UPSTREAM_CAPACITY = {"LEGACY": 27, "MID_SPLIT": 108, "HIGH_SPLIT": 204}
UPSTREAM_RANK = {"LEGACY": 0, "MID_SPLIT": 1, "HIGH_SPLIT": 2}
CAPABILITY_RANK = {"D30": 0, "D31": 1, "D40": 2}

ACTIVE_ACTION_STATUSES = ("PROPOSED", "APPROVED", "IN_PROGRESS")


def round_half_up_1(value):
    """Round to 1 decimal place, half up. Returns a float with 1 decimal."""
    d = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------- Spectrum

def block_channels(block):
    return block["mhz"] // 6


def block_capacity(block):
    if block["status"] == "DATA_ACTIVE":
        return block_channels(block) * 38
    return 0


def node_blocks(node_id):
    return [b for b in db.spectrum_blocks.values() if b["optical_node_id"] == node_id]


def node_service_groups(node_id):
    return [s for s in db.service_groups.values() if s["optical_node_id"] == node_id]


def node_downstream_capacity(node_id):
    return sum(block_capacity(b) for b in node_blocks(node_id))


# ------------------------------------------------------------ Service groups

def sg_samples_in_window(sg):
    now = db.clock_now()
    start = now - timedelta(days=7)
    out = []
    for s in db.utilization_samples.values():
        if s["service_group_id"] != sg["id"]:
            continue
        try:
            measured = db.parse_dt(s["measured_at"])
        except ValueError:
            continue
        if start <= measured <= now:
            out.append((measured, s))
    return out


def recompute_service_group(sg, allow_auto_action=True):
    """Recompute capacity/load/pct/posture for a service group and touch it.

    SPLIT_RETIRED service groups stay frozen.
    """
    if sg["posture"] == "SPLIT_RETIRED":
        return sg
    node = db.optical_nodes.get(sg["optical_node_id"])
    sg["downstream_capacity_mbps"] = node_downstream_capacity(sg["optical_node_id"])
    sg["upstream_capacity_mbps"] = UPSTREAM_CAPACITY[node["upstream_config"]]
    sg["provisioned_downstream_mbps"] = sum(
        p["provisioned_downstream_mbps"]
        for p in db.customer_premises.values()
        if p["service_group_id"] == sg["id"]
    )

    window = sg_samples_in_window(sg)
    capacity = sg["downstream_capacity_mbps"]
    if not window:
        load = 0
    elif sg["utilization_method"] == "PEAK_PCT95":
        vals = sorted(s["downstream_mbps"] for _, s in window)
        rank = math.ceil(0.95 * len(vals))
        if rank < 1:
            rank = 1
        load = vals[rank - 1]
    else:  # SUSTAINED_AVG
        eligible = [s["downstream_mbps"] for _, s in window
                    if capacity > 0 and s["downstream_mbps"] * 2 >= capacity]
        if not eligible:
            eligible = [s["downstream_mbps"] for _, s in window]
        load = sum(eligible) // len(eligible)
    sg["current_load_mbps"] = load

    if capacity == 0:
        pct = 0.0
    else:
        pct = round_half_up_1(Decimal(load * 100) / Decimal(capacity))
    sg["current_utilization_pct"] = pct

    old_posture = sg["posture"]
    if pct >= sg["critical_threshold_pct"]:
        new_posture = "CRITICAL"
    elif pct >= sg["warn_threshold_pct"]:
        new_posture = "ELEVATED"
    else:
        new_posture = "NORMAL"
    sg["posture"] = new_posture
    db.touch(sg)

    if (allow_auto_action and new_posture == "CRITICAL"
            and old_posture in ("NORMAL", "ELEVATED")):
        maybe_auto_create_action(sg, node)
    return sg


def active_action_for_sg(sg_id):
    for a in db.capacity_actions.values():
        if a["service_group_id"] == sg_id and a["status"] in ACTIVE_ACTION_STATUSES:
            return a
    return None


def maybe_auto_create_action(sg, node):
    if active_action_for_sg(sg["id"]) is not None:
        return None
    video_blocks = [b for b in node_blocks(node["id"]) if b["status"] == "VIDEO_ACTIVE"]
    if len(video_blocks) >= 2:
        action_type = "SPECTRUM_RECLAIM"
        target_block_ids = [b["id"] for b in video_blocks[:-1]]  # leave one untargeted
        target_upstream = None
    elif node["upstream_config"] == "LEGACY":
        action_type = "MID_SPLIT_UPGRADE"
        target_block_ids = None
        target_upstream = "MID_SPLIT"
    elif node["upstream_config"] == "MID_SPLIT":
        action_type = "HIGH_SPLIT_UPGRADE"
        target_block_ids = None
        target_upstream = "HIGH_SPLIT"
    else:
        action_type = "NODE_SPLIT"
        target_block_ids = None
        target_upstream = None
    action = db.stamp_new({
        "id": db.new_id(),
        "service_group_id": sg["id"],
        "action_type": action_type,
        "origin": "SYSTEM",
        "status": "PROPOSED",
        "target_block_ids": target_block_ids,
        "target_upstream_config": target_upstream,
        "superseded_by_id": None,
        "note": None,
    })
    db.capacity_actions[action["id"]] = action
    return action


# ------------------------------------------------------------ Homes / franchise

def franchise_homes_progress(fa_id):
    total = 0
    for node in db.optical_nodes.values():
        if node["franchise_area_id"] != fa_id:
            continue
        for sg in db.service_groups.values():
            if sg["optical_node_id"] == node["id"] and sg["posture"] != "SPLIT_RETIRED":
                total += sg["homes_passed"]
    return total


# ------------------------------------------------------------ Node split waterfall

def homes_allocation(homes, child_count, min_per, max_per):
    """Waterfall allocation. Returns list of allocations or raises ERR_ALLOCATION_INVALID."""
    remaining = homes
    allocs = []
    for i in range(1, child_count):
        base = remaining // (child_count - i + 1)
        alloc = min(max(base, min_per), max_per)
        allocs.append(alloc)
        remaining -= alloc
    if remaining < min_per or remaining > max_per:
        raise_err("ERR_ALLOCATION_INVALID")
    allocs.append(remaining)
    return allocs


# ------------------------------------------------------------ Complaint scoring

def complaint_scores(complaint, variant):
    if variant == "EVIDENCE_WEIGHTED":
        sp = float(complaint["plant_signal"])
        sh = float(complaint["home_signal"])
        sd = float(complaint["destination_signal"])
    else:  # RECENCY_WEIGHTED
        prior = None
        for c in db.congestion_complaints.values():
            if (c["customer_premise_id"] == complaint["customer_premise_id"]
                    and c["status"] in ("RESOLVED", "CLOSED")):
                if prior is None or (c["created_at"], c["id"]) > (prior["created_at"], prior["id"]):
                    prior = c
        boost = {"PLANT": 0.0, "IN_HOME": 0.0, "DESTINATION": 0.0}
        if prior is not None and prior.get("cause_category") in boost:
            boost[prior["cause_category"]] = 40.0
        sp = 0.6 * complaint["plant_signal"] + boost["PLANT"]
        sh = 0.6 * complaint["home_signal"] + boost["IN_HOME"]
        sd = 0.6 * complaint["destination_signal"] + boost["DESTINATION"]
    sp = round_half_up_1(sp)
    sh = round_half_up_1(sh)
    sd = round_half_up_1(sd)
    # argmax with tie priority PLANT > IN_HOME > DESTINATION
    scores = [("PLANT", sp), ("IN_HOME", sh), ("DESTINATION", sd)]
    best = max(range(3), key=lambda i: (scores[i][1], -i))
    return sp, sh, sd, scores[best][0]
