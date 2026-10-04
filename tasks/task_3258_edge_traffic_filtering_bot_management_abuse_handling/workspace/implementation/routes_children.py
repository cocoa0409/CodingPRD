"""Routes: purge requests, IP blocks, abuse reports, and child list/get
endpoints."""
import re
from datetime import timedelta

from flask import request

from core import (db, body, success, require_roles, check_ownership,
                  req_str, req_int, req_enum, stamp_new, touch,
                  err_invalid, err_invalid_state, err_terminal,
                  err_duplicate, err_not_found, err_routing,
                  CATEGORY_BASE, ABUSE_CATEGORIES, PURGE_TYPES, IP_VERSIONS,
                  BLOCK_BASE_SECONDS, DISPOSITIONS,
                  parse_dt, now, now_str, fmt_ts, paginate,
                  purge_out, ipblock_out, abuse_out, ddos_out)

_V4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _ip_shape_ok(ip, version):
    if version == "V4":
        return bool(_V4_RE.match(ip))
    # V6: colon-separated, no dots
    return (":" in ip) and ("." not in ip)


def _zone_for_child_create(zone_id):
    """Reference existence then state: zone must exist and be ACTIVE."""
    z = db.zones.get(zone_id)
    if z is None:
        raise err_not_found("zone_id does not resolve")
    if z["status"] == "DELETED":
        raise err_terminal("Zone is DELETED")
    if z["status"] != "ACTIVE":
        raise err_invalid_state("Zone must be ACTIVE")
    return z


def register(app):

    # ------------------------------ purge requests -------------------------

    @app.post("/api/purge-requests")
    def create_purge():
        role, uid = require_roles("ZoneAdmin")
        data = body()
        zone_id = data.get("zone_id")
        if isinstance(zone_id, str) and zone_id not in db.zones:
            raise err_not_found("zone_id does not resolve")
        zone_id = req_str(data, "zone_id")
        purge_type = req_enum(data, "purge_type", PURGE_TYPES)
        urls = data.get("urls")
        z = _zone_for_child_create(zone_id)
        check_ownership(z, role, uid)
        if purge_type == "PURGE_URL":
            if not isinstance(urls, list) or len(urls) == 0:
                raise err_invalid(
                    "urls is required and must be non-empty for PURGE_URL")
            for u in urls:
                if not isinstance(u, str):
                    raise err_invalid("urls must contain strings")
        else:
            if urls is not None:
                raise err_invalid("urls is forbidden for PURGE_ALL")
        purge = stamp_new({
            "zone_id": zone_id,
            "purge_type": purge_type,
            "urls": urls if purge_type == "PURGE_URL" else None,
            "status": "QUEUED",
            "requested_at": now_str(),
            "origin_shield_degraded": z.get("origin_shield_pop_code") is not None,
        })
        db.purge_requests[purge["id"]] = purge
        return success(purge_out(purge), 201)

    @app.get("/api/purge-requests")
    def list_purges():
        require_roles("ZoneAdmin", "PlatformAdmin", "NetworkPlanner")
        items = list(db.purge_requests.values())
        zone_id = request.args.get("zone_id")
        status = request.args.get("status")
        if zone_id is not None:
            items = [p for p in items if p["zone_id"] == zone_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        items.sort(key=lambda p: (p["created_at"], p["id"]))
        page, meta = paginate(items)
        return success([purge_out(p) for p in page], 200, meta)

    @app.get("/api/purge-requests/<pid>")
    def get_purge(pid):
        require_roles("ZoneAdmin", "PlatformAdmin", "NetworkPlanner")
        p = db.purge_requests.get(pid)
        if p is None:
            raise err_not_found("Purge request not found")
        return success(purge_out(p))

    # ------------------------------ ip blocks ------------------------------

    @app.post("/api/ip-blocks")
    def create_block():
        role, uid = require_roles("TrustSafetyAnalyst")
        data = body()
        zone_id = data.get("zone_id")
        if isinstance(zone_id, str) and zone_id not in db.zones:
            raise err_not_found("zone_id does not resolve")
        zone_id = req_str(data, "zone_id")
        ip = req_str(data, "ip")
        ip_version = req_enum(data, "ip_version", IP_VERSIONS)
        reason = req_str(data, "reason")
        z = _zone_for_child_create(zone_id)
        if not _ip_shape_ok(ip, ip_version):
            raise err_invalid("ip_version does not match the ip shape")
        live = any(b["zone_id"] == zone_id and b["ip"] == ip
                   and b["status"] in ("PROVISIONAL", "CONFIRMED")
                   for b in db.ip_blocks.values())
        if live:
            raise err_duplicate(f"ip '{ip}' already blocked for this zone")
        block = stamp_new({
            "zone_id": zone_id,
            "ip": ip,
            "ip_version": ip_version,
            "reason": reason,
            "status": "PROVISIONAL",
            "confirmed_at": None,
            "expires_at": fmt_ts(now() + timedelta(seconds=900)),
            "blocked_seconds_total": None,
        })
        db.ip_blocks[block["id"]] = block
        return success(ipblock_out(block), 201)

    @app.get("/api/ip-blocks")
    def list_blocks():
        require_roles("TrustSafetyAnalyst", "PlatformAdmin", "ZoneAdmin")
        items = list(db.ip_blocks.values())
        zone_id = request.args.get("zone_id")
        status = request.args.get("status")
        ip = request.args.get("ip")
        if zone_id is not None:
            items = [b for b in items if b["zone_id"] == zone_id]
        if status is not None:
            items = [b for b in items if b["status"] == status]
        if ip is not None:
            items = [b for b in items if b["ip"] == ip]
        items.sort(key=lambda b: (b["created_at"], b["id"]))
        page, meta = paginate(items)
        return success([ipblock_out(b) for b in page], 200, meta)

    @app.get("/api/ip-blocks/<bid>")
    def get_block(bid):
        require_roles("TrustSafetyAnalyst", "PlatformAdmin", "ZoneAdmin")
        b = db.ip_blocks.get(bid)
        if b is None:
            raise err_not_found("IP block not found")
        return success(ipblock_out(b))

    @app.post("/api/ip-blocks/<bid>/confirm")
    def confirm_block(bid):
        require_roles("TrustSafetyAnalyst")
        b = db.ip_blocks.get(bid)
        if b is None:
            raise err_not_found("IP block not found")
        if b["status"] == "EXPIRED":
            raise err_terminal("IP block is EXPIRED")
        if b["status"] != "PROVISIONAL":
            raise err_invalid_state("Only PROVISIONAL blocks can be confirmed")
        if not now() < parse_dt(b["expires_at"]):
            raise err_invalid_state("Provisional window has lapsed")
        confirmed = now()
        b["status"] = "CONFIRMED"
        b["confirmed_at"] = fmt_ts(confirmed)
        b["expires_at"] = fmt_ts(confirmed + timedelta(seconds=BLOCK_BASE_SECONDS))
        touch(b)
        return success(ipblock_out(b), 200)

    @app.patch("/api/ip-blocks/<bid>")
    def patch_block(bid):
        require_roles("TrustSafetyAnalyst")
        b = db.ip_blocks.get(bid)
        if b is None:
            raise err_not_found("IP block not found")
        data = body()
        extend = data.get("extend")
        if not isinstance(extend, bool):
            raise err_invalid("extend must be a boolean")
        if b["status"] == "EXPIRED":
            raise err_terminal("IP block is EXPIRED")
        if b["status"] != "CONFIRMED":
            raise err_invalid_state("Only CONFIRMED blocks can be extended")
        if extend is True:
            cur = parse_dt(b["expires_at"])
            confirmed = parse_dt(b["confirmed_at"])
            candidates = [cur,
                          confirmed + timedelta(seconds=BLOCK_BASE_SECONDS),
                          now() + timedelta(seconds=BLOCK_BASE_SECONDS)]
            b["expires_at"] = fmt_ts(max(candidates))
            touch(b)
        return success(ipblock_out(b), 200)

    # ------------------------------ abuse reports --------------------------

    @app.post("/api/abuse-reports")
    def create_abuse():
        require_roles("Anonymous")
        data = body()
        zone_id = data.get("zone_id")
        if isinstance(zone_id, str) and zone_id not in db.zones:
            raise err_not_found("zone_id does not resolve")
        zone_id = req_str(data, "zone_id")
        reporter_email = req_str(data, "reporter_email")
        category = req_enum(data, "category", ABUSE_CATEGORIES)
        description = req_str(data, "description")
        target_url = req_str(data, "target_url")
        trust = req_int(data, "reporter_trust_score", minimum=1, maximum=100)
        z = _zone_for_child_create(zone_id)
        routing = "HOSTED" if z["onboarding_type"] == "FULL" else "PROXIED"
        report = stamp_new({
            "zone_id": zone_id,
            "reporter_email": reporter_email,
            "category": category,
            "description": description,
            "target_url": target_url,
            "reporter_trust_score": trust,
            "priority_score": CATEGORY_BASE[category] + trust,
            "routing_mode": routing,
            "forwarded_to": None,
            "status": "SUBMITTED",
            "forwarded_at": None,
            "resolved_at": None,
        })
        db.abuse_reports[report["id"]] = report
        return success(abuse_out(report), 201)

    @app.get("/api/abuse-reports")
    def list_abuse():
        require_roles("TrustSafetyAnalyst", "PlatformAdmin")
        items = list(db.abuse_reports.values())
        zone_id = request.args.get("zone_id")
        status = request.args.get("status")
        category = request.args.get("category")
        if zone_id is not None:
            items = [r for r in items if r["zone_id"] == zone_id]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        if category is not None:
            items = [r for r in items if r["category"] == category]
        items.sort(key=lambda r: (r["created_at"], r["id"]))
        page, meta = paginate(items)
        return success([abuse_out(r) for r in page], 200, meta)

    @app.get("/api/abuse-reports/<rid>")
    def get_abuse(rid):
        require_roles("TrustSafetyAnalyst", "PlatformAdmin")
        r = db.abuse_reports.get(rid)
        if r is None:
            raise err_not_found("Abuse report not found")
        return success(abuse_out(r))

    @app.post("/api/abuse-reports/<rid>/claim")
    def claim_abuse(rid):
        require_roles("TrustSafetyAnalyst")
        r = db.abuse_reports.get(rid)
        if r is None:
            raise err_not_found("Abuse report not found")
        if r["status"] == "CLOSED":
            raise err_terminal("Abuse report is CLOSED")
        if r["status"] not in ("SUBMITTED", "ACTION_TAKEN"):
            raise err_invalid_state(
                "Only SUBMITTED or ACTION_TAKEN reports can be claimed")
        r["status"] = "REVIEWING"
        touch(r)
        return success(abuse_out(r), 200)

    @app.post("/api/abuse-reports/<rid>/disposition")
    def disposition_abuse(rid):
        require_roles("TrustSafetyAnalyst")
        r = db.abuse_reports.get(rid)
        if r is None:
            raise err_not_found("Abuse report not found")
        data = body()
        disposition = req_enum(data, "disposition", DISPOSITIONS)
        if r["status"] == "CLOSED":
            raise err_terminal("Abuse report is CLOSED")
        if r["status"] != "REVIEWING":
            raise err_invalid_state("Only REVIEWING reports can be dispositioned")
        z = db.zones.get(r["zone_id"])
        if z is None or z["status"] != "ACTIVE":
            raise err_invalid_state("The report's zone must be ACTIVE")
        if disposition == "TAKE_ACTION" and r["routing_mode"] != "HOSTED":
            raise err_routing()
        if disposition == "FORWARD":
            r["status"] = "FORWARDED"
            r["forwarded_at"] = now_str()
            if r["routing_mode"] == "PROXIED":
                r["forwarded_to"] = z["origin_host_email"]
            else:
                acct = db.accounts.get(z["account_id"])
                r["forwarded_to"] = acct["account_email"] if acct else None
        else:
            r["status"] = "ACTION_TAKEN"
        touch(r)
        return success(abuse_out(r), 200)

    @app.post("/api/abuse-reports/<rid>/close")
    def close_abuse(rid):
        require_roles("TrustSafetyAnalyst")
        r = db.abuse_reports.get(rid)
        if r is None:
            raise err_not_found("Abuse report not found")
        if r["status"] == "CLOSED":
            raise err_terminal("Abuse report is CLOSED")
        if r["status"] not in ("FORWARDED", "ACTION_TAKEN"):
            raise err_invalid_state(
                "Only FORWARDED or ACTION_TAKEN reports can be closed")
        r["status"] = "CLOSED"
        r["resolved_at"] = now_str()
        touch(r)
        return success(abuse_out(r), 200)

    # ------------------------------ ddos events ----------------------------

    @app.get("/api/ddos-events")
    def list_ddos():
        require_roles("ZoneAdmin", "PlatformAdmin", "NetworkPlanner")
        items = list(db.ddos_events.values())
        zone_id = request.args.get("zone_id")
        status = request.args.get("status")
        if zone_id is not None:
            items = [e for e in items if e["zone_id"] == zone_id]
        if status is not None:
            items = [e for e in items if e["status"] == status]
        items.sort(key=lambda e: (e["created_at"], e["id"]))
        page, meta = paginate(items)
        return success([ddos_out(e) for e in page], 200, meta)

    @app.get("/api/ddos-events/<eid>")
    def get_ddos(eid):
        require_roles("ZoneAdmin", "PlatformAdmin", "NetworkPlanner")
        e = db.ddos_events.get(eid)
        if e is None:
            raise err_not_found("DDoS event not found")
        return success(ddos_out(e))
