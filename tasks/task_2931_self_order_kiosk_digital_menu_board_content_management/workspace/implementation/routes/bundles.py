"""Content bundles: slot geometry, the validation fork and publication (PRD 3.4)."""
from flask import Blueprint

import auth
import calc
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, append_audit, new_row, ordered, touch
from errors import fail
from routes.common import fk, listing, path_row

bp = Blueprint("bundles", __name__)

VERBS = ("VALIDATE", "ACCESSIBILITY_AUDIT", "PUBLISH", "ROLLBACK")
PASS_TOKENS = ("PASS", "PASSED")


def _snapshot_item_ids(bundle):
    codes = []
    for slot in bundle.get("daypart_slots", []):
        for code in slot.get("category_codes", []):
            if code not in codes:
                codes.append(code)
    ids = []
    for item in ordered(list(DB.menu_items.values())):
        if item.get("category") in codes:
            ids.append(item["id"])
    return ids


def _accessibility_blocked(bundle):
    for item_id in bundle.get("snapshot_item_ids", []):
        item = DB.menu_items.get(item_id)
        if item is None:
            continue
        if not (item.get("screen_reader_text") or "").strip():
            return True
        if float(item.get("contrast_ratio") or 0) < C.MIN_CONTRAST_RATIO:
            return True
    return False


@bp.post("/content-bundles")
def create_bundle():
    auth.enter(["ContentManager"])
    data = shapes.body()
    cluster_id = fk(data, "cluster_id", "clusters")
    if cluster_id is None:
        shapes.req_str(data, "cluster_id", 1, None)
    effective = shapes.opt_instant(data, "effective_from_utc", None)
    highest = 0
    for other in DB.bundles.values():
        if other.get("cluster_id") == cluster_id and other["bundle_version"] > highest:
            highest = other["bundle_version"]
    row = new_row({
        "cluster_id": cluster_id,
        "bundle_version": highest + 1,
        "state": "DRAFT",
        "accessibility_audit_state": "PENDING",
        "daypart_slots": [],
        "snapshot_item_ids": [],
        "price_snapshot": [],
        "price_snapshot_checksum": 0,
        "live_price_checksum": 0,
        "stale_flag": False,
        "validation_findings": [],
        "accessibility_findings": [],
        "published_at_utc": None,
        "effective_from_utc": clockmod.iso(effective) if effective else None,
    })
    DB.bundles[row["id"]] = row
    return response.created(serialize.dump("bundle", row))


@bp.get("/content-bundles")
def list_bundles():
    auth.enter(auth.ALL_READ_ROLES)
    return listing("bundles", "bundle")


@bp.get("/content-bundles/<bundle_id>")
def get_bundle(bundle_id):
    auth.enter(auth.ALL_READ_ROLES)
    row = path_row("bundles", bundle_id)
    derive.recompute_bundle(row)
    return response.ok(serialize.dump("bundle", row))


@bp.post("/content-bundles/<bundle_id>/daypart-slots")
def append_slot(bundle_id):
    auth.enter(["ContentManager"])
    bundle = path_row("bundles", bundle_id)
    data = shapes.body()
    expected = shapes.req_int(data, "expected_content_bundle_version", 0, None)
    code = shapes.req_str(data, "daypart_code", 1, 24)
    start = shapes.req_minute_of_day(data, "start_minute_of_day")
    end = shapes.req_minute_of_day(data, "end_minute_of_day")
    layout = shapes.req_str(data, "layout_code", 1, 24)
    buffer_minutes = shapes.req_int(data, "buffer_minutes", 0, C.MINUTES_PER_DAY - 1)
    categories = shapes.opt_enum_array(data, "category_codes", C.CATEGORIES, [])
    if expected != bundle.get("version"):
        fail("ERR_STALE_CONTENT_BUNDLE_VERSION", "expected_content_bundle_version does not match")
    if bundle["state"] not in ("DRAFT", "VALIDATED"):
        fail("ERR_INVALID_STATE_TRANSITION", "slots may only be appended to an editable bundle")
    if start >= end:
        fail("ERR_DAYPART_SLOT_OVERLAP", "start_minute_of_day must be strictly below the end")
    for slot in bundle.get("daypart_slots", []):
        if start < slot["end_minute_of_day"] and slot["start_minute_of_day"] < end:
            fail("ERR_DAYPART_SLOT_OVERLAP", "the interval overlaps an existing slot")
    slot = {
        "daypart_code": code,
        "start_minute_of_day": start,
        "end_minute_of_day": end,
        "layout_code": layout,
        "buffer_minutes": buffer_minutes,
        "category_codes": categories,
        "created_at": clockmod.now_iso(),
        "_seq": DB.next_seq(),
    }
    bundle["daypart_slots"] = list(bundle.get("daypart_slots", [])) + [slot]
    bundle["snapshot_item_ids"] = _snapshot_item_ids(bundle)
    bundle["accessibility_audit_state"] = "PENDING"
    if bundle["state"] == "VALIDATED":
        bundle["state"] = "DRAFT"
    touch(bundle)
    return response.ok(serialize.dump("bundle", bundle))


def _verb_roles(verb):
    if verb == "ACCESSIBILITY_AUDIT":
        return ("ComplianceOfficer", "PlatformAdmin")
    return ("ContentManager", "PlatformAdmin")


def _validation_findings(bundle):
    findings = []
    codes = []
    for slot in bundle.get("daypart_slots", []):
        for code in slot.get("category_codes", []):
            if code not in codes:
                codes.append(code)
    for code in codes:
        if not any(i.get("category") == code for i in DB.menu_items.values()):
            findings.append("EMPTY_CATEGORY:" + code)
    for rule in ordered(list(DB.upsell_rules.values())):
        if rule.get("cluster_id") == bundle.get("cluster_id") and rule.get("state") == "SUSPENDED":
            findings.append("SUSPENDED_UPSELL_RULE:" + rule["id"])
    return findings


def _freeze_price_snapshot(bundle):
    zones = derive.zones_of_cluster(bundle.get("cluster_id"))
    snapshot = []
    for item_id in bundle.get("snapshot_item_ids", []):
        item = DB.menu_items.get(item_id)
        if item is None:
            continue
        for zone in zones:
            snapshot.append({
                "menu_item_id": item_id,
                "price_zone_id": zone["id"],
                "price_cents": calc.effective_zone_price(item, zone),
            })
    return snapshot


@bp.post("/content-bundles/<bundle_id>/actions")
def drive_bundle(bundle_id):
    ctx = auth.enter(["ContentManager", "ComplianceOfficer", "PlatformAdmin"])
    data = shapes.body()
    raw_action = data.get("action")
    if isinstance(raw_action, str) and raw_action in VERBS:
        auth.require_roles(ctx, _verb_roles(raw_action))
    bundle = path_row("bundles", bundle_id)
    action = shapes.req_enum(data, "action", VERBS)
    if bundle["state"] == "ROLLED_BACK":
        fail("ERR_ALREADY_TERMINAL", "a rolled-back bundle is terminal")

    if action == "VALIDATE":
        if bundle["state"] != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION", "VALIDATE is not declared out of %s" % bundle["state"])
        if not bundle.get("daypart_slots"):
            fail("ERR_INVALID_STATE_TRANSITION", "a bundle with no slots cannot be validated")
        if _accessibility_blocked(bundle):
            fail("ERR_SCREEN_READER_TEXT_MISSING", "a snapshot item is not accessibility-ready")
        findings = _validation_findings(bundle)
        bundle["validation_findings"] = findings
        bundle["state"] = "VALIDATED" if not findings else "DRAFT"
        touch(bundle)
        if findings:
            append_audit("CONTENT_BUNDLE", bundle["id"], "BUNDLE_VALIDATION_FAILED",
                         ctx["role"], ctx["user_id"], detail=findings[0])
        else:
            append_audit("CONTENT_BUNDLE", bundle["id"], "BUNDLE_VALIDATED",
                         ctx["role"], ctx["user_id"], detail="TECHNICAL_VALIDATION_PASSED")

    elif action == "ACCESSIBILITY_AUDIT":
        if bundle["state"] not in ("DRAFT", "VALIDATED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "ACCESSIBILITY_AUDIT is not declared out of %s" % bundle["state"])
        raw_result = data.get("audit_result")
        if raw_result is None:
            fail("ERR_INVALID_REQUEST", "audit_result is required")
        if isinstance(raw_result, bool):
            passed = raw_result
            token = "PASS" if raw_result else "FAIL"
        elif isinstance(raw_result, str):
            token = raw_result.strip()
            passed = token.upper() in PASS_TOKENS
        else:
            fail("ERR_INVALID_REQUEST", "audit_result must be a string")
        findings_key = "accessibility_findings" if "accessibility_findings" in data else "findings"
        findings = shapes.opt_str_array(data, findings_key, [])
        if _accessibility_blocked(bundle):
            fail("ERR_SCREEN_READER_TEXT_MISSING", "a snapshot item is not accessibility-ready")
        bundle["accessibility_audit_state"] = "PASSED" if passed else "FAILED"
        bundle["accessibility_findings"] = findings
        touch(bundle)
        append_audit("CONTENT_BUNDLE", bundle["id"], "BUNDLE_ACCESSIBILITY_AUDITED",
                     ctx["role"], ctx["user_id"], detail=token)

    elif action == "PUBLISH":
        if bundle["state"] != "VALIDATED":
            fail("ERR_INVALID_STATE_TRANSITION", "PUBLISH is not declared out of %s" % bundle["state"])
        if bundle.get("accessibility_audit_state") != "PASSED":
            fail("ERR_ACCESSIBILITY_AUDIT_REQUIRED", "the accessibility audit has not passed")
        bundle["snapshot_item_ids"] = _snapshot_item_ids(bundle)
        for item_id in bundle["snapshot_item_ids"]:
            item = DB.menu_items.get(item_id)
            if item is None:
                continue
            if not (item.get("screen_reader_text") or "").strip() or item.get("accessibility_state") != "READY":
                fail("ERR_SCREEN_READER_TEXT_MISSING", "a snapshot item regressed since the audit")
        snapshot = _freeze_price_snapshot(bundle)
        total = sum(entry["price_cents"] for entry in snapshot)
        bundle["price_snapshot"] = snapshot
        bundle["price_snapshot_checksum"] = total
        bundle["live_price_checksum"] = total
        bundle["stale_flag"] = False
        bundle["published_at_utc"] = clockmod.now_iso()
        previous = [b for b in ordered(list(DB.bundles.values()))
                    if b.get("cluster_id") == bundle.get("cluster_id")
                    and b["id"] != bundle["id"] and b.get("state") == "PUBLISHED"]
        bundle["state"] = "PUBLISHED"
        touch(bundle)
        append_audit("CONTENT_BUNDLE", bundle["id"], "BUNDLE_PUBLISHED", ctx["role"],
                     ctx["user_id"], detail="CONTENT_PUBLISHED")
        for old in previous:
            derive.apply_changes(old, {"state": "SUPERSEDED"})
            append_audit("CONTENT_BUNDLE", old["id"], "BUNDLE_SUPERSEDED", ctx["role"],
                         ctx["user_id"], detail="NEWER_BUNDLE_PUBLISHED")
        derive.reconcile()

    else:  # ROLLBACK
        if bundle["state"] != "PUBLISHED":
            fail("ERR_INVALID_STATE_TRANSITION", "ROLLBACK is not declared out of %s" % bundle["state"])
        derive.apply_changes(bundle, {"state": "ROLLED_BACK"})
        append_audit("CONTENT_BUNDLE", bundle["id"], "BUNDLE_ROLLED_BACK", ctx["role"],
                     ctx["user_id"], detail="PUBLICATION_ROLLED_BACK")
        candidates = [b for b in DB.bundles.values()
                      if b.get("cluster_id") == bundle.get("cluster_id")
                      and b.get("state") == "SUPERSEDED"]
        if candidates:
            republished = max(candidates, key=lambda b: b["bundle_version"])
            derive.apply_changes(republished, {"state": "PUBLISHED"})
            derive.recompute_bundle(republished)
            append_audit("CONTENT_BUNDLE", republished["id"], "BUNDLE_REPUBLISHED", ctx["role"],
                         ctx["user_id"], detail="PREVIOUS_BUNDLE_RESTORED")
        derive.reconcile()

    return response.ok(serialize.dump("bundle", bundle))
