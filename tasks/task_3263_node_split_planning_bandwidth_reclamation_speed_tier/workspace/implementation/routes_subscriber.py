"""Routes: customer premises, equipment, speed tiers, provisioning requests, refresh campaigns."""

from flask import Blueprint, request

import calcs
import db
from errors import raise_err
from middleware import body_json, require_roles
from response import paginate, sorted_by_created, success

bp = Blueprint("subscriber", __name__)

CAPABILITY_CLASSES = {"D30", "D31", "D40"}
UPSTREAM_CONFIGS = {"LEGACY", "MID_SPLIT", "HIGH_SPLIT"}
CAMPAIGN_TARGETS = {"D31", "D40"}


# ------------------------------------------------------------ Premises

@bp.post("/service-groups/<rid>/customer-premises")
def create_premise(rid):
    require_roles(["ProvisioningAgent"])
    sg = db.get_or_404(db.service_groups, rid)
    data = body_json(
        required=[("premise_ref", "str", None), ("address", "str", None)],
    )
    rec = db.stamp_new({
        "id": db.new_id(),
        "service_group_id": sg["id"],
        "premise_ref": data["premise_ref"],
        "address": data["address"],
        "current_tier_id": None,
        "provisioned_downstream_mbps": 0,
    })
    db.customer_premises[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/customer-premises/<rid>")
def get_premise(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.customer_premises, rid)
    return success(rec, 200)


@bp.get("/service-groups/<rid>/customer-premises")
def list_premises_of_sg(rid):
    require_roles(["Any"])
    sg = db.get_or_404(db.service_groups, rid)
    items = sorted_by_created(
        [p for p in db.customer_premises.values() if p["service_group_id"] == sg["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


@bp.get("/customer-premises")
def list_premises():
    require_roles(["Any"])
    items = list(db.customer_premises.values())
    sg_filter = request.args.get("service_group_id")
    tier_filter = request.args.get("current_tier_id")
    if sg_filter:
        items = [p for p in items if p["service_group_id"] == sg_filter]
    if tier_filter:
        items = [p for p in items if p["current_tier_id"] == tier_filter]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


# ------------------------------------------------------------ Equipment

@bp.post("/customer-premises/<rid>/equipment")
def create_equipment(rid):
    require_roles(["ProvisioningAgent"])
    premise = db.get_or_404(db.customer_premises, rid)
    data = body_json(
        required=[
            ("model", "str", None),
            ("docsis_version", "str", None),
            ("capability_class", "str", CAPABILITY_CLASSES),
            ("max_downstream_mbps", "int", None),
            ("video_legacy", "bool", None),
        ],
    )
    rec = db.stamp_new({
        "id": db.new_id(),
        "customer_premise_id": premise["id"],
        "model": data["model"],
        "docsis_version": data["docsis_version"],
        "capability_class": data["capability_class"],
        "max_downstream_mbps": data["max_downstream_mbps"],
        "video_legacy": data["video_legacy"],
        "status": "ACTIVE",
    })
    db.customer_equipment[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/equipment/<rid>")
def get_equipment(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.customer_equipment, rid)
    return success(rec, 200)


@bp.get("/customer-premises/<rid>/equipment")
def list_equipment(rid):
    require_roles(["Any"])
    premise = db.get_or_404(db.customer_premises, rid)
    items = sorted_by_created(
        [e for e in db.customer_equipment.values() if e["customer_premise_id"] == premise["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


@bp.post("/equipment/<rid>/swap")
def swap_equipment(rid):
    require_roles(["ProvisioningAgent"])
    old = db.get_or_404(db.customer_equipment, rid)
    data = body_json(
        required=[
            ("model", "str", None),
            ("docsis_version", "str", None),
            ("capability_class", "str", CAPABILITY_CLASSES),
            ("max_downstream_mbps", "int", None),
        ],
        optional=[("refresh_campaign_id", "str", None)],
    )
    if old["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Only ACTIVE equipment can be swapped")
    campaign = None
    if data.get("refresh_campaign_id") is not None:
        campaign = db.refresh_campaigns.get(data["refresh_campaign_id"])
        if campaign is None:
            raise_err("ERR_NOT_FOUND", "Refresh campaign not found")
        if campaign["status"] != "LAUNCHED":
            raise_err("ERR_CAMPAIGN_NOT_LAUNCHED")
    old["status"] = "RETIRED"
    db.touch(old)
    new = db.stamp_new({
        "id": db.new_id(),
        "customer_premise_id": old["customer_premise_id"],
        "model": data["model"],
        "docsis_version": data["docsis_version"],
        "capability_class": data["capability_class"],
        "max_downstream_mbps": data["max_downstream_mbps"],
        "video_legacy": old["video_legacy"],
        "status": "ACTIVE",
    })
    db.customer_equipment[new["id"]] = new
    if campaign is not None:
        campaign["swapped_count"] += 1
        db.touch(campaign)
    return success(new, 201)


# ------------------------------------------------------------ Speed tiers

@bp.post("/speed-tiers")
def create_speed_tier():
    require_roles(["PlatformAdmin"])
    data = body_json(
        required=[
            ("tier_code", "str", None),
            ("downstream_mbps", "int", None),
            ("upstream_mbps", "int", None),
            ("min_capability_class", "str", CAPABILITY_CLASSES),
            ("min_upstream_config", "str", UPSTREAM_CONFIGS),
        ],
    )
    rec = db.stamp_new({
        "id": db.new_id(),
        "tier_code": data["tier_code"],
        "downstream_mbps": data["downstream_mbps"],
        "upstream_mbps": data["upstream_mbps"],
        "min_capability_class": data["min_capability_class"],
        "min_upstream_config": data["min_upstream_config"],
        "status": "PUBLISHED",
    })
    db.speed_tiers[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/speed-tiers/<rid>")
def get_speed_tier(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.speed_tiers, rid)
    return success(rec, 200)


@bp.post("/speed-tiers/<rid>/retire")
def retire_speed_tier(rid):
    require_roles(["PlatformAdmin"])
    rec = db.get_or_404(db.speed_tiers, rid)
    body_json()
    if rec["status"] != "PUBLISHED":
        raise_err("ERR_INVALID_STATE", "Only PUBLISHED tiers can be retired")
    rec["status"] = "RETIRED"
    db.touch(rec)
    return success(rec, 200)


# ------------------------------------------------------------ Provisioning requests

@bp.post("/customer-premises/<rid>/provisioning-requests")
def create_provisioning_request(rid):
    require_roles(["ProvisioningAgent"])
    premise = db.get_or_404(db.customer_premises, rid)
    data = body_json(
        required=[
            ("speed_tier_id", "str", None),
            ("expected_customer_premise_version", "int", None),
        ],
    )
    tier = db.speed_tiers.get(data["speed_tier_id"])
    if tier is None:
        raise_err("ERR_NOT_FOUND", "Speed tier not found")
    if data["expected_customer_premise_version"] != premise["version"]:
        raise_err("ERR_STALE_VERSION")
    sg = db.service_groups[premise["service_group_id"]]
    if sg["posture"] == "CRITICAL":
        raise_err("ERR_SG_CONGESTED")

    # Supersede existing PENDING/VALIDATED/FAILED requests of this premise
    for pr in db.provisioning_requests.values():
        if (pr["customer_premise_id"] == premise["id"]
                and pr["status"] in ("PENDING", "VALIDATED", "FAILED")):
            pr["status"] = "CANCELLED"
            db.touch(pr)

    rec = db.stamp_new({
        "id": db.new_id(),
        "customer_premise_id": premise["id"],
        "speed_tier_id": tier["id"],
        "status": "PENDING",
        "config_file_content": None,
        "failure_reason": None,
    })
    db.provisioning_requests[rec["id"]] = rec
    db.touch(premise)
    return success(rec, 201)


@bp.get("/provisioning-requests/<rid>")
def get_provisioning_request(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.provisioning_requests, rid)
    return success(rec, 200)


@bp.get("/provisioning-requests")
def list_provisioning_requests():
    require_roles(["Any"])
    items = list(db.provisioning_requests.values())
    p = request.args.get("customer_premise_id")
    t = request.args.get("speed_tier_id")
    s = request.args.get("status")
    if p:
        items = [r for r in items if r["customer_premise_id"] == p]
    if t:
        items = [r for r in items if r["speed_tier_id"] == t]
    if s:
        items = [r for r in items if r["status"] == s]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


def _fail_validation(pr, error_id):
    pr["status"] = "FAILED"
    pr["failure_reason"] = error_id
    pr["config_file_content"] = None
    db.touch(pr)
    raise_err(error_id)


@bp.post("/provisioning-requests/<rid>/validate")
def validate_provisioning_request(rid):
    require_roles(["ProvisioningAgent"])
    pr = db.get_or_404(db.provisioning_requests, rid)
    body_json()
    if pr["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Only PENDING requests can be validated")
    premise = db.customer_premises[pr["customer_premise_id"]]
    tier = db.speed_tiers[pr["speed_tier_id"]]
    sg = db.service_groups[premise["service_group_id"]]
    node = db.optical_nodes[sg["optical_node_id"]]

    # Check 1: tier published
    if tier["status"] != "PUBLISHED":
        _fail_validation(pr, "ERR_TIER_RETIRED")

    # Check 2: CPE capability
    capable = None
    for cpe in db.customer_equipment.values():
        if cpe["customer_premise_id"] != premise["id"] or cpe["status"] != "ACTIVE":
            continue
        if (calcs.CAPABILITY_RANK[cpe["capability_class"]] >= calcs.CAPABILITY_RANK[tier["min_capability_class"]]
                and cpe["max_downstream_mbps"] >= tier["downstream_mbps"]):
            if (capable is None
                    or calcs.CAPABILITY_RANK[cpe["capability_class"]] > calcs.CAPABILITY_RANK[capable["capability_class"]]):
                capable = cpe
    if capable is None:
        _fail_validation(pr, "ERR_CAPABILITY_INSUFFICIENT")

    # Check 3: upstream config rank
    if calcs.UPSTREAM_RANK[node["upstream_config"]] < calcs.UPSTREAM_RANK[tier["min_upstream_config"]]:
        _fail_validation(pr, "ERR_UPSTREAM_CONFIG_INSUFFICIENT")

    # Check 4: capacity projection
    capacity = sg["downstream_capacity_mbps"]
    if capacity == 0:
        _fail_validation(pr, "ERR_CAPACITY_EXCEEDED")
    projected = sg["current_load_mbps"] + tier["downstream_mbps"]
    if projected * 100 >= sg["critical_threshold_pct"] * capacity:
        _fail_validation(pr, "ERR_CAPACITY_EXCEEDED")

    pr["status"] = "VALIDATED"
    pr["config_file_content"] = (
        f"TIER={tier['tier_code']};DS={tier['downstream_mbps']};"
        f"US={tier['upstream_mbps']};CPE={capable['capability_class']}"
    )
    db.touch(pr)
    return success(pr, 200)


@bp.post("/provisioning-requests/<rid>/activate")
def activate_provisioning_request(rid):
    require_roles(["ProvisioningAgent"])
    pr = db.get_or_404(db.provisioning_requests, rid)
    body_json()
    if pr["status"] != "VALIDATED":
        raise_err("ERR_INVALID_STATE", "Only VALIDATED requests can be activated")
    premise = db.customer_premises[pr["customer_premise_id"]]
    tier = db.speed_tiers[pr["speed_tier_id"]]
    # Supersede any ACTIVE request of the same premise
    for other in db.provisioning_requests.values():
        if (other["customer_premise_id"] == premise["id"]
                and other["id"] != pr["id"] and other["status"] == "ACTIVE"):
            other["status"] = "CANCELLED"
            db.touch(other)
    pr["status"] = "ACTIVE"
    db.touch(pr)
    premise["current_tier_id"] = tier["id"]
    premise["provisioned_downstream_mbps"] = tier["downstream_mbps"]
    db.touch(premise)
    sg = db.service_groups[premise["service_group_id"]]
    sg["provisioned_downstream_mbps"] = sum(
        p["provisioned_downstream_mbps"]
        for p in db.customer_premises.values()
        if p["service_group_id"] == sg["id"])
    db.touch(sg)
    return success(pr, 200)


@bp.post("/provisioning-requests/<rid>/retry")
def retry_provisioning_request(rid):
    require_roles(["ProvisioningAgent"])
    pr = db.get_or_404(db.provisioning_requests, rid)
    body_json()
    if pr["status"] != "FAILED":
        raise_err("ERR_INVALID_STATE", "Only FAILED requests can be retried")
    pr["status"] = "PENDING"
    pr["failure_reason"] = None
    db.touch(pr)
    return success(pr, 200)


@bp.post("/provisioning-requests/<rid>/cancel")
def cancel_provisioning_request(rid):
    require_roles(["ProvisioningAgent"])
    pr = db.get_or_404(db.provisioning_requests, rid)
    body_json()
    if pr["status"] == "CANCELLED":
        raise_err("ERR_INVALID_STATE", "Request is already cancelled")
    was_active = pr["status"] == "ACTIVE"
    pr["status"] = "CANCELLED"
    db.touch(pr)
    if was_active:
        premise = db.customer_premises[pr["customer_premise_id"]]
        premise["current_tier_id"] = None
        premise["provisioned_downstream_mbps"] = 0
        db.touch(premise)
        sg = db.service_groups[premise["service_group_id"]]
        sg["provisioned_downstream_mbps"] = sum(
            p["provisioned_downstream_mbps"]
            for p in db.customer_premises.values()
            if p["service_group_id"] == sg["id"])
        db.touch(sg)
    return success(pr, 200)


# ------------------------------------------------------------ Refresh campaigns

@bp.post("/franchise-areas/<rid>/refresh-campaigns")
def create_refresh_campaign(rid):
    require_roles(["ProvisioningAgent"])
    fa = db.get_or_404(db.franchise_areas, rid)
    data = body_json(
        required=[
            ("campaign_code", "str", None),
            ("target_capability_class", "str", CAMPAIGN_TARGETS),
        ],
    )
    rec = db.stamp_new({
        "id": db.new_id(),
        "franchise_area_id": fa["id"],
        "campaign_code": data["campaign_code"],
        "target_capability_class": data["target_capability_class"],
        "status": "DRAFT",
        "targeted_count": 0,
        "swapped_count": 0,
    })
    db.refresh_campaigns[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/refresh-campaigns/<rid>")
def get_refresh_campaign(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.refresh_campaigns, rid)
    return success(rec, 200)


@bp.get("/franchise-areas/<rid>/refresh-campaigns")
def list_refresh_campaigns(rid):
    require_roles(["Any"])
    fa = db.get_or_404(db.franchise_areas, rid)
    items = sorted_by_created(
        [c for c in db.refresh_campaigns.values() if c["franchise_area_id"] == fa["id"]])
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


def _fa_premise_ids(fa_id):
    node_ids = {n["id"] for n in db.optical_nodes.values() if n["franchise_area_id"] == fa_id}
    sg_ids = {s["id"] for s in db.service_groups.values() if s["optical_node_id"] in node_ids}
    return {p["id"] for p in db.customer_premises.values() if p["service_group_id"] in sg_ids}


@bp.post("/refresh-campaigns/<rid>/launch")
def launch_refresh_campaign(rid):
    require_roles(["ProvisioningAgent"])
    rec = db.get_or_404(db.refresh_campaigns, rid)
    body_json()
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only DRAFT campaigns can be launched")
    premise_ids = _fa_premise_ids(rec["franchise_area_id"])
    target_rank = calcs.CAPABILITY_RANK[rec["target_capability_class"]]
    count = 0
    for cpe in db.customer_equipment.values():
        if (cpe["customer_premise_id"] in premise_ids and cpe["status"] == "ACTIVE"
                and calcs.CAPABILITY_RANK[cpe["capability_class"]] < target_rank):
            count += 1
    rec["targeted_count"] = count
    rec["status"] = "LAUNCHED"
    db.touch(rec)
    return success(rec, 200)


@bp.post("/refresh-campaigns/<rid>/close")
def close_refresh_campaign(rid):
    require_roles(["ProvisioningAgent"])
    rec = db.get_or_404(db.refresh_campaigns, rid)
    body_json()
    if rec["status"] != "LAUNCHED":
        raise_err("ERR_INVALID_STATE", "Only LAUNCHED campaigns can be closed")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return success(rec, 200)
