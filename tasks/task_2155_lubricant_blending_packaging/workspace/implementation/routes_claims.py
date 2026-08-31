"""Approval claims and package (label) configurations."""
from flask import Blueprint

import calc
import cascades
import core
import enums
import store
import views
from core import (authenticate, body, fail, now, opt_bool, opt_enum, opt_int, opt_str,
                  pagination, q_enum, q_str, req_enum, req_num, req_str, req_str_list)

bp = Blueprint("claims", __name__)


# ==========================================================================
# ApprovalClaim
# ==========================================================================
@bp.post("/approval-claims")
def create_claim():
    authenticate(["ComplianceOfficer"])
    b = body()
    spec_id = req_str(b, "product_spec_id")
    claim_body = req_enum(b, "claim_body", enums.CLAIM_BODIES)
    claim_code = req_str(b, "claim_code")

    spec = store.must_get("ProductSpec", spec_id)

    for existing in store.where("ApprovalClaim", product_spec_id=spec["id"]):
        if (existing["claim_body"] == claim_body
                and existing["claim_code"] == claim_code
                and existing["status"] in ("DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED")):
            fail("ERR_DUPLICATE_CLAIM")

    record = {
        "product_spec_id": spec["id"],
        "claim_body": claim_body,
        "claim_code": claim_code,
        "pinned_spec_revision": None,
        "status": "DRAFT",
        "licence_number": None,
        "valid_until": None,
        "requires_recertification": False,
        "suspension_reason": None,
    }
    return views.one(store.insert("ApprovalClaim", record), 201)


@bp.get("/approval-claims/<cid>")
def read_claim(cid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("ApprovalClaim", cid))


@bp.get("/approval-claims")
def list_claims():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    spec_id = q_str("product_spec_id")
    status = q_enum("status", enums.CLAIM_STATUSES)
    claim_body = q_enum("claim_body", enums.CLAIM_BODIES)
    rows = store.where("ApprovalClaim", product_spec_id=spec_id, status=status,
                       claim_body=claim_body)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/approval-claims/<cid>/submit")
def submit_claim(cid):
    authenticate(["ComplianceOfficer"])
    claim = store.must_get("ApprovalClaim", cid)
    if claim["status"] not in ("DRAFT", "SUSPENDED"):                # rung 10
        fail("ERR_INVALID_STATE")
    spec = store.get("ProductSpec", claim["product_spec_id"])
    if spec is None or spec["status"] != "ACTIVE":                   # rung 13
        fail("ERR_SPEC_NOT_ACTIVE")
    eligible = any(
        r["status"] == "ACTIVE" and r["spec_revision_pinned"] == spec["revision"]
        for r in store.where("BlendRecipe", product_spec_id=spec["id"]))
    if not eligible:                                                 # rung 31
        fail("ERR_NO_ELIGIBLE_RECIPE")
    claim["pinned_spec_revision"] = spec["revision"]
    claim["status"] = "SUBMITTED"
    store.touch(claim)
    return views.one(claim)


@bp.post("/approval-claims/<cid>/decision")
def decide_claim(cid):
    authenticate(["ComplianceOfficer"])
    b = body()
    decision = req_enum(b, "decision", enums.CLAIM_DECISIONS)
    licence_number = opt_str(b, "licence_number")
    opt_str(b, "reason")
    if decision == "APPROVE" and not licence_number:
        fail("ERR_INVALID_REQUEST", "Field 'licence_number' is required for APPROVE.")

    claim = store.must_get("ApprovalClaim", cid)
    if claim["status"] != "SUBMITTED":                               # rung 10
        fail("ERR_INVALID_STATE")

    if decision == "APPROVE":
        claim["status"] = "ACTIVE"
        claim["licence_number"] = licence_number
        claim["requires_recertification"] = False
        claim["valid_until"] = calc.claim_valid_until(now())
        store.touch(claim)
        cascades.unblock_configs_for_spec(claim["product_spec_id"])
    else:
        claim["status"] = "REJECTED"
        store.touch(claim)
    return views.one(claim)


@bp.post("/approval-claims/<cid>/lifecycle")
def claim_lifecycle(cid):
    authenticate(["ComplianceOfficer"])
    b = body()
    action = req_enum(b, "action", enums.CLAIM_ACTIONS)
    reason = opt_str(b, "reason")
    claim = store.must_get("ApprovalClaim", cid)

    if action == "REVISE":
        if claim["status"] != "REJECTED":
            fail("ERR_INVALID_STATE")
        claim["status"] = "DRAFT"
        claim["pinned_spec_revision"] = None
        store.touch(claim)
    elif action == "SUSPEND":
        if claim["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE")
        cascades.suspend_claim(claim, reason)
    else:  # WITHDRAW
        if claim["status"] not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE")
        from_active = claim["status"] == "ACTIVE"
        claim["status"] = "WITHDRAWN"
        store.touch(claim)
        if from_active:
            cascades.block_configs_for_claim(claim)
    return views.one(claim)


# ==========================================================================
# PackageConfiguration
# ==========================================================================
@bp.post("/package-configurations")
def create_config():
    authenticate(["ProductManager"])
    b = body()
    spec_id = req_str(b, "product_spec_id")
    package_type = req_enum(b, "package_type", enums.PACKAGE_TYPES)
    label_brand = req_str(b, "label_brand")
    fill_volume_l = req_num(b, "fill_volume_l", gt=0)
    private_label = opt_bool(b, "private_label", False)
    customer_id = opt_str(b, "customer_id")
    units_per_case = opt_int(b, "units_per_case")
    claim_codes = req_str_list(b, "claim_codes", [])

    spec = store.must_get("ProductSpec", spec_id)
    if customer_id is not None:
        store.must_get("Customer", customer_id)

    record = {
        "product_spec_id": spec["id"],
        "customer_id": customer_id,
        "package_type": package_type,
        "label_brand": label_brand,
        "private_label": private_label,
        "fill_volume_l": fill_volume_l,
        "units_per_case": units_per_case if package_type == "CASE_12X1L" else None,
        "claim_codes": claim_codes,
        "status": "DRAFT",
        "superseded_by_id": None,
    }
    return views.one(store.insert("PackageConfiguration", record), 201)


@bp.get("/package-configurations/<cid>")
def read_config(cid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("PackageConfiguration", cid))


@bp.get("/package-configurations")
def list_configs():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    spec_id = q_str("product_spec_id")
    customer_id = q_str("customer_id")
    superseded_by_id = q_str("superseded_by_id")
    package_type = q_enum("package_type", enums.PACKAGE_TYPES)
    status = q_enum("status", enums.CONFIG_STATUSES)
    rows = store.where("PackageConfiguration", product_spec_id=spec_id,
                       customer_id=customer_id, superseded_by_id=superseded_by_id,
                       package_type=package_type, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/package-configurations/<cid>/activate")
def activate_config(cid):
    authenticate(["ProductManager"])
    config = store.must_get("PackageConfiguration", cid)
    if config["status"] != "DRAFT":                                  # rung 10
        fail("ERR_INVALID_STATE")
    spec = store.get("ProductSpec", config["product_spec_id"])
    if spec is None or spec["status"] != "ACTIVE":                   # rung 13
        fail("ERR_SPEC_NOT_ACTIVE")
    active_codes = set(
        c["claim_code"] for c in store.where("ApprovalClaim",
                                             product_spec_id=config["product_spec_id"])
        if c["status"] == "ACTIVE")
    for code in (config["claim_codes"] or []):                       # rung 30
        if code not in active_codes:
            fail("ERR_CLAIM_NOT_ACTIVE")

    config["status"] = "ACTIVE"
    store.touch(config)
    cascades.supersede_configs(config)
    return views.one(config)


@bp.post("/package-configurations/<cid>/retire")
def retire_config(cid):
    authenticate(["ProductManager"])
    b = body()
    req_str(b, "reason")
    config = store.must_get("PackageConfiguration", cid)
    if config["status"] not in ("DRAFT", "ACTIVE", "CLAIM_BLOCKED"):
        fail("ERR_INVALID_STATE")
    for run in store.where("PackagingRun", package_configuration_id=config["id"]):
        if run["status"] in ("SCHEDULED", "RUNNING"):
            fail("ERR_INVALID_STATE",
                 "A packaging run on this configuration is still SCHEDULED or RUNNING.")
    config["status"] = "RETIRED"
    store.touch(config)
    return views.one(config)


@bp.get("/package-configurations/<cid>/order-lines")
def list_config_order_lines(cid):
    authenticate(["PlatformAdmin", "ProductManager", "QualityManager",
                  "ComplianceOfficer", "SalesRep"])
    limit, offset = pagination()
    status = q_enum("status", enums.ORDER_LINE_STATUSES)
    store.must_get("PackageConfiguration", cid)
    rows = store.where("OrderLine", package_configuration_id=cid, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)
