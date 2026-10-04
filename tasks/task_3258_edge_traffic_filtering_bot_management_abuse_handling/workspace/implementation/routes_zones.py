"""Routes: zones CRUD/config plus zone-scoped operations
(verify, traffic-hits, bot-classifications, honeypots, honeypot-hits,
ddos-events).
"""
from datetime import timedelta

from core import (db, body, success, require_roles, check_ownership,
                  req_str, req_int, req_bool, req_enum, stamp_new, touch,
                  err_invalid, err_invalid_state, err_terminal,
                  err_duplicate, err_not_found, err_proxy, err_verify,
                  err_plan, err_rule_overlap, err_band_overlap,
                  err_mitigation, err_stale,
                  PLAN_FEATURES, PROXYABLE_TYPES, RECORD_TYPES, RULE_KINDS,
                  RULE_ACTIONS, RULE_STATUSES, SUB_SENSITIVITIES,
                  SUB_STATUSES, OVERRIDE_ACTIONS, OVERRIDE_STATUSES,
                  BAND_ACTIONS, BAND_STATUSES, ONBOARDING_TYPES,
                  DOS_SENSITIVITIES, CDN_SUFFIX,
                  HONEYPOT_LOOKBACK_SECONDS, HUMAN_SCORE, VERIFIED_SCORE,
                  FIGHT_MODE_MIN_SCORE, FIGHT_MODE_MAX_SCORE,
                  RATE_LIMIT_WINDOW_SECONDS,
                  AUTO_THRESHOLD_MULTIPLIER, SENSITIVITY_MULTIPLIER,
                  AUTO_MITIGATION_TTL_HOURS, PROVISIONAL_WINDOW_SECONDS,
                  delegation_ok, parse_dt, now, now_str, paginate,
                  zone_out, ddos_out, ipblock_out)

# ---------------------------------------------------------------------------
# Embedded collection validators (shared by POST /api/zones and PATCH)
# ---------------------------------------------------------------------------


def validate_dns_records(records):
    if not isinstance(records, list):
        raise err_invalid("dns_records must be an array")
    seen = set()
    for r in records:
        if not isinstance(r, dict):
            raise err_invalid("dns_records items must be objects")
        name = r.get("name")
        rtype = r.get("record_type")
        content = r.get("content")
        proxied = r.get("proxied")
        if not isinstance(name, str) or not name:
            raise err_invalid("dns_records[].name is required")
        if rtype not in RECORD_TYPES:
            raise err_invalid("dns_records[].record_type must be A|AAAA|CNAME|TXT")
        if not isinstance(content, str):
            raise err_invalid("dns_records[].content is required")
        if not isinstance(proxied, bool):
            raise err_invalid("dns_records[].proxied must be a boolean")
        if name in seen:
            raise err_duplicate(f"Duplicate dns record name '{name}'")
        seen.add(name)
    for r in records:
        if r["proxied"] is True and r["record_type"] not in PROXYABLE_TYPES:
            raise err_proxy()


def validate_traffic_rules(rules, plan_features):
    if not isinstance(rules, list):
        raise err_invalid("traffic_rules must be an array")
    seen = set()
    for r in rules:
        if not isinstance(r, dict):
            raise err_invalid("traffic_rules items must be objects")
        name = r.get("name")
        kind = r.get("rule_kind")
        action = r.get("action")
        status = r.get("status", "ACTIVE")
        if not isinstance(name, str) or not name:
            raise err_invalid("traffic_rules[].name is required")
        if kind not in RULE_KINDS:
            raise err_invalid("traffic_rules[].rule_kind must be FIREWALL_FILTER|RATE_LIMIT")
        if not isinstance(r.get("expression"), str):
            raise err_invalid("traffic_rules[].expression is required")
        if action not in RULE_ACTIONS:
            raise err_invalid("traffic_rules[].action must be ALLOW|BLOCK")
        if status not in RULE_STATUSES:
            raise err_invalid("traffic_rules[].status must be ACTIVE|DISABLED")
        thr = r.get("rate_limit_threshold_rpm")
        if kind == "RATE_LIMIT":
            if isinstance(thr, bool) or not isinstance(thr, int) or thr < 1:
                raise err_invalid(
                    "rate_limit_threshold_rpm is required for RATE_LIMIT rules")
        else:
            if thr is not None:
                raise err_invalid(
                    "rate_limit_threshold_rpm is forbidden for FIREWALL_FILTER rules")
        if name in seen:
            raise err_duplicate(f"Duplicate traffic rule name '{name}'")
        seen.add(name)
        r["status"] = status
    # plan gate: rate limiting
    if any(r["rule_kind"] == "RATE_LIMIT" for r in rules) and \
            not plan_features["rate_limiting"]:
        raise err_plan("Plan tier does not include rate limiting")
    # action-conflict overlap (regardless of status)
    for i in range(len(rules)):
        for j in range(i + 1, len(rules)):
            a, b = rules[i], rules[j]
            if a["rule_kind"] == "FIREWALL_FILTER" and \
                    b["rule_kind"] == "FIREWALL_FILTER" and \
                    a["expression"] == b["expression"] and \
                    a["action"] != b["action"]:
                raise err_rule_overlap()


def validate_subscriptions(subs, plan_features):
    if not isinstance(subs, list):
        raise err_invalid("ruleset_subscriptions must be an array")
    seen = set()
    for s in subs:
        if not isinstance(s, dict):
            raise err_invalid("ruleset_subscriptions items must be objects")
        slug = s.get("slug")
        if not isinstance(slug, str) or not slug:
            raise err_invalid("ruleset_subscriptions[].slug is required")
        if s.get("sensitivity") not in SUB_SENSITIVITIES:
            raise err_invalid("ruleset_subscriptions[].sensitivity must be LOW|MEDIUM|HIGH")
        status = s.get("status", "ACTIVE")
        if status not in SUB_STATUSES:
            raise err_invalid("ruleset_subscriptions[].status must be ACTIVE|UNSUBSCRIBED")
        if slug in seen:
            raise err_duplicate(f"Duplicate subscription slug '{slug}'")
        seen.add(slug)
        s["status"] = status
        overrides = s.get("overrides", [])
        if not isinstance(overrides, list):
            raise err_invalid("overrides must be an array")
        oseen = set()
        for ov in overrides:
            if not isinstance(ov, dict):
                raise err_invalid("overrides items must be objects")
            mrid = ov.get("managed_rule_id")
            if not isinstance(mrid, str) or not mrid:
                raise err_invalid("overrides[].managed_rule_id is required")
            if ov.get("override_action") not in OVERRIDE_ACTIONS:
                raise err_invalid("overrides[].override_action must be DISABLE|CHALLENGE")
            ostatus = ov.get("status", "ACTIVE")
            if ostatus not in OVERRIDE_STATUSES:
                raise err_invalid("overrides[].status must be ACTIVE|REVERTED")
            if mrid in oseen:
                raise err_duplicate(f"Duplicate managed_rule_id '{mrid}'")
            oseen.add(mrid)
            ov["status"] = ostatus
    if subs and not plan_features["managed_rulesets"]:
        raise err_plan("Plan tier does not include managed rulesets")


def validate_bands(bands, plan_features):
    if not isinstance(bands, list):
        raise err_invalid("bot_action_bands must be an array")
    seen = set()
    for b in bands:
        if not isinstance(b, dict):
            raise err_invalid("bot_action_bands items must be objects")
        name = b.get("name")
        if not isinstance(name, str) or not name:
            raise err_invalid("bot_action_bands[].name is required")
        if b.get("action") not in BAND_ACTIONS:
            raise err_invalid("bot_action_bands[].action must be BLOCK|CHALLENGE|LOG")
        mn, mx = b.get("min_score"), b.get("max_score")
        if isinstance(mn, bool) or not isinstance(mn, int) or \
                isinstance(mx, bool) or not isinstance(mx, int):
            raise err_invalid("bot_action_bands[] min_score/max_score must be integers")
        if mn > mx:
            raise err_invalid("bot_action_bands[] requires min_score <= max_score")
        status = b.get("status", "ACTIVE")
        if status not in BAND_STATUSES:
            raise err_invalid("bot_action_bands[].status must be ACTIVE|DISABLED")
        if name in seen:
            raise err_duplicate(f"Duplicate bot action band name '{name}'")
        seen.add(name)
        b["status"] = status
    if bands and not plan_features["bot_classification"]:
        raise err_plan("Plan tier does not include bot classification")
    active = [b for b in bands if b["status"] == "ACTIVE"]
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            if a["min_score"] <= b["max_score"] and b["min_score"] <= a["max_score"]:
                raise err_band_overlap()


def _get_zone_or_404(zid):
    z = db.zones.get(zid)
    if z is None:
        raise err_not_found("Zone not found")
    return z


def _get_zone_for_child(zid, role, uid, require_active=True):
    z = _get_zone_or_404(zid)
    check_ownership(z, role, uid)
    if z["status"] == "DELETED":
        raise err_terminal("Zone is DELETED")
    if require_active and z["status"] != "ACTIVE":
        raise err_invalid_state("Zone must be ACTIVE")
    return z


def _plan_features(zone):
    acct = db.accounts.get(zone["account_id"])
    tier = acct["plan_tier"] if acct else "FREE"
    return PLAN_FEATURES[tier]


def register(app):

    @app.post("/api/zones")
    def create_zone():
        role, uid = require_roles("ZoneAdmin")
        data = body()
        account_id = data.get("account_id")
        if isinstance(account_id, str) and account_id not in db.accounts:
            raise err_not_found("account_id does not resolve")
        account_id = req_str(data, "account_id")
        domain = req_str(data, "domain_name")
        onboarding = req_enum(data, "onboarding_type", ONBOARDING_TYPES)
        origin_email = req_str(data, "origin_host_email")
        records = data.get("dns_records", [])
        acct = db.accounts[account_id]
        if account_id != uid:
            # ZoneAdmin operates only on zones of their own account
            from core import err_unauthorized
            raise err_unauthorized()
        if any(z["domain_name"] == domain for z in db.zones.values()):
            raise err_duplicate(f"domain_name '{domain}' already exists")
        features = PLAN_FEATURES[acct["plan_tier"]]
        validate_dns_records(records)
        if acct.get("status", "ACTIVE") != "ACTIVE":
            raise err_invalid_state("Account must be ACTIVE")
        zone = stamp_new({
            "account_id": account_id,
            "domain_name": domain,
            "onboarding_type": onboarding,
            "origin_host_email": origin_email,
            "status": "PENDING",
            "dns_records": records,
            "bot_fight_mode": False,
            "dos_sensitivity": "DEFAULT",
            "dos_mitigation_active": False,
            "origin_shield_pop_code": None,
            "edge_ttl_seconds": 3600,
            "cache_reserve": False,
            "last_purged_at": None,
            "honeypot_paths": [],
            "traffic_rules": [],
            "ruleset_subscriptions": [],
            "bot_action_bands": [],
            "bot_classifications": [],
        })
        db.zones[zone["id"]] = zone
        db.honeypot_logs[zone["id"]] = []
        return success(zone_out(zone), 201)

    @app.get("/api/zones")
    def list_zones():
        require_roles("PlatformAdmin", "ZoneAdmin", "TrustSafetyAnalyst",
                      "NetworkPlanner")
        items = list(db.zones.values())
        account_id = None
        from flask import request
        account_id = request.args.get("account_id")
        status = request.args.get("status")
        onboarding = request.args.get("onboarding_type")
        if account_id is not None:
            items = [z for z in items if z["account_id"] == account_id]
        if status is not None:
            items = [z for z in items if z["status"] == status]
        if onboarding is not None:
            items = [z for z in items if z["onboarding_type"] == onboarding]
        items.sort(key=lambda z: (z["created_at"], z["id"]))
        page, meta = paginate(items)
        return success([zone_out(z) for z in page], 200, meta)

    @app.get("/api/zones/<zid>")
    def get_zone(zid):
        role, uid = require_roles("PlatformAdmin", "ZoneAdmin",
                                  "TrustSafetyAnalyst", "NetworkPlanner")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        return success(zone_out(z))

    @app.patch("/api/zones/<zid>")
    def patch_zone(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        data = body()
        features = _plan_features(z)
        # shape checks first
        if "edge_ttl_seconds" in data:
            v = data["edge_ttl_seconds"]
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise err_invalid("edge_ttl_seconds must be a positive integer")
        if "cache_reserve" in data and not isinstance(data["cache_reserve"], bool):
            raise err_invalid("cache_reserve must be a boolean")
        if "bot_fight_mode" in data and not isinstance(data["bot_fight_mode"], bool):
            raise err_invalid("bot_fight_mode must be a boolean")
        if "dos_sensitivity" in data and \
                data["dos_sensitivity"] not in DOS_SENSITIVITIES:
            raise err_invalid("dos_sensitivity must be DEFAULT|LOW|HIGH")
        if "origin_shield_pop_code" in data and \
                data["origin_shield_pop_code"] is not None and \
                not isinstance(data["origin_shield_pop_code"], str):
            raise err_invalid("origin_shield_pop_code must be a string or null")
        if "expected_zone_version" in data and \
                (isinstance(data["expected_zone_version"], bool) or
                 not isinstance(data["expected_zone_version"], int)):
            raise err_invalid("expected_zone_version must be an integer")
        # state admissibility
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] != "ACTIVE":
            raise err_invalid_state("Zone must be ACTIVE for patching")
        # duplicate check for domain-like fields happens inside validators
        new_records = None
        if "dns_records" in data:
            new_records = data["dns_records"]
            validate_dns_records(new_records)
        new_rules = None
        if "traffic_rules" in data:
            new_rules = data["traffic_rules"]
            validate_traffic_rules(new_rules, features)
        new_subs = None
        if "ruleset_subscriptions" in data:
            new_subs = data["ruleset_subscriptions"]
            validate_subscriptions(new_subs, features)
        new_bands = None
        if "bot_action_bands" in data:
            new_bands = data["bot_action_bands"]
            validate_bands(new_bands, features)
        # reference existence: origin_shield_pop_code -> ACTIVE Pop.code
        if "origin_shield_pop_code" in data and \
                data["origin_shield_pop_code"] is not None:
            code = data["origin_shield_pop_code"]
            if not any(p["code"] == code and p["status"] == "ACTIVE"
                       for p in db.pops.values()):
                raise err_not_found(
                    f"No ACTIVE PoP with code '{code}'")
        # plan gating on scalar toggles
        if data.get("bot_fight_mode") is True and \
                not features["bot_classification"]:
            raise err_plan("Plan tier does not include bot classification")
        if "dos_sensitivity" in data and data["dos_sensitivity"] != "DEFAULT" \
                and not features["dos_sensitivity"]:
            raise err_plan("Plan tier does not include DoS sensitivity tuning")
        if "origin_shield_pop_code" in data and \
                data["origin_shield_pop_code"] is not None and \
                not features["origin_shield"]:
            raise err_plan("Plan tier does not include origin shield")
        if data.get("cache_reserve") is True and not features["cache_reserve"]:
            raise err_plan("Plan tier does not include cache reserve")
        # OCC: required whenever dos_sensitivity present
        if "dos_sensitivity" in data:
            if "expected_zone_version" not in data:
                raise err_invalid(
                    "expected_zone_version is required when dos_sensitivity is present")
            if data["expected_zone_version"] != z["version"]:
                raise err_stale()
        # mitigation freeze on traffic_rules replacement
        if "traffic_rules" in data and z.get("dos_mitigation_active"):
            raise err_mitigation()
        # apply
        if new_records is not None:
            z["dns_records"] = new_records
        if new_rules is not None:
            z["traffic_rules"] = new_rules
        if new_subs is not None:
            z["ruleset_subscriptions"] = new_subs
        if new_bands is not None:
            z["bot_action_bands"] = new_bands
        if "edge_ttl_seconds" in data:
            z["edge_ttl_seconds"] = data["edge_ttl_seconds"]
        if "cache_reserve" in data:
            z["cache_reserve"] = data["cache_reserve"]
        if "origin_shield_pop_code" in data:
            z["origin_shield_pop_code"] = data["origin_shield_pop_code"]
        if "bot_fight_mode" in data:
            z["bot_fight_mode"] = data["bot_fight_mode"]
        if "dos_sensitivity" in data:
            z["dos_sensitivity"] = data["dos_sensitivity"]
        touch(z)
        return success(zone_out(z), 200)

    @app.post("/api/zones/<zid>/verify")
    def verify_zone(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] not in ("PENDING", "MOVED"):
            raise err_invalid_state("Only PENDING or MOVED zones can be verified")
        if not delegation_ok(z):
            raise err_verify()
        z["status"] = "ACTIVE"
        touch(z)
        return success(zone_out(z), 200)

    @app.delete("/api/zones/<zid>")
    def delete_zone(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] not in ("ACTIVE", "PENDING"):
            raise err_invalid_state("Only ACTIVE or PENDING zones can be deleted")
        was_active = z["status"] == "ACTIVE"
        z["status"] = "DELETED"
        touch(z)
        if was_active:
            for r in db.abuse_reports.values():
                if r["zone_id"] == zid and r["status"] in ("SUBMITTED", "REVIEWING"):
                    r["status"] = "CLOSED"
                    r["resolved_at"] = now_str()
                    touch(r)
        return success(zone_out(z), 200)

    @app.post("/api/zones/<zid>/traffic-hits")
    def traffic_hit(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        data = body()
        occurred_raw = req_str(data, "occurred_at")
        client_ip = req_str(data, "client_ip")
        occurred = parse_dt(occurred_raw)
        if occurred is None:
            raise err_invalid("occurred_at must be an ISO 8601 timestamp")
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] != "ACTIVE":
            raise err_invalid_state("Zone must be ACTIVE")
        if z.get("dos_mitigation_active"):
            raise err_mitigation()
        triggered = []
        blocked_id = None
        for rule in z.get("traffic_rules", []):
            if rule.get("rule_kind") != "RATE_LIMIT" or rule.get("status") != "ACTIVE":
                continue
            key = (zid, rule["name"])
            log = db.rule_hit_logs.setdefault(key, [])
            log.append(occurred_raw)
            window_start = occurred - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS - 1)
            count = sum(1 for ts in log
                        if window_start <= parse_dt(ts) <= occurred)
            if count >= rule["rate_limit_threshold_rpm"]:
                triggered.append(rule["name"])
                if rule["action"] == "BLOCK":
                    live = any(b["zone_id"] == zid and b["ip"] == client_ip
                               and b["status"] in ("PROVISIONAL", "CONFIRMED")
                               for b in db.ip_blocks.values())
                    if not live and blocked_id is None:
                        from core import fmt_ts
                        block = stamp_new({
                            "zone_id": zid,
                            "ip": client_ip,
                            "ip_version": None,
                            "reason": "rate-limit trigger",
                            "status": "PROVISIONAL",
                            "confirmed_at": None,
                            "expires_at": fmt_ts(now() + timedelta(
                                seconds=PROVISIONAL_WINDOW_SECONDS)),
                        })
                        db.ip_blocks[block["id"]] = block
                        blocked_id = block["id"]
        return success({"triggered_rule_names": triggered,
                        "blocked_ip_block_id": blocked_id}, 201)

    @app.post("/api/zones/<zid>/bot-classifications")
    def bot_classification(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        data = body()
        fingerprint = req_str(data, "request_fingerprint")
        verified = req_bool(data, "verified_crawler")
        client_ip = req_str(data, "client_ip")
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] != "ACTIVE":
            raise err_invalid_state("Zone must be ACTIVE")
        if any(c["request_fingerprint"] == fingerprint
               for c in z.get("bot_classifications", [])):
            raise err_duplicate(
                f"request_fingerprint '{fingerprint}' already classified")
        features = _plan_features(z)
        classified_at = now()
        hit_log = db.honeypot_logs.get(zid, [])
        honeypot_hit = False
        if features["bot_classification"]:
            for h in hit_log:
                if h["client_ip"] != client_ip:
                    continue
                hit_at = parse_dt(h["hit_at"])
                lo = classified_at - timedelta(seconds=HONEYPOT_LOOKBACK_SECONDS)
                if lo <= hit_at <= classified_at:
                    honeypot_hit = True
                    break
        if honeypot_hit:
            bot_score = 1
            classification = "HONEYPOT_BOT"
        elif verified:
            bot_score = VERIFIED_SCORE
            classification = "VERIFIED_BOT"
        else:
            bot_score = 1 + (sum(ord(c) for c in fingerprint) % 99)
            classification = "HUMAN" if bot_score == HUMAN_SCORE else "LIKELY_AUTOMATED"
        if classification == "VERIFIED_BOT":
            action_taken = "ALLOW"
        elif classification == "HONEYPOT_BOT":
            action_taken = "BLOCK"
        else:
            action_taken = None
            for band in z.get("bot_action_bands", []):
                if band.get("status") == "ACTIVE" and \
                        band["min_score"] <= bot_score <= band["max_score"]:
                    action_taken = band["action"]
                    break
            if action_taken is None:
                if z.get("bot_fight_mode") and \
                        FIGHT_MODE_MIN_SCORE <= bot_score <= FIGHT_MODE_MAX_SCORE:
                    action_taken = "BLOCK:FIGHT_MODE"
                else:
                    action_taken = "ALLOW"
        item = {
            "request_fingerprint": fingerprint,
            "verified_crawler": verified,
            "client_ip": client_ip,
            "classification": classification,
            "bot_score": bot_score,
            "classified_at": now_str(),
            "action_taken": action_taken,
        }
        z["bot_classifications"].append(item)
        return success(dict(item), 201)

    @app.post("/api/zones/<zid>/honeypots")
    def add_honeypot(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        data = body()
        url_path = req_str(data, "url_path")
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] != "ACTIVE":
            raise err_invalid_state("Zone must be ACTIVE")
        if url_path in z.get("honeypot_paths", []):
            raise err_duplicate(f"honeypot path '{url_path}' already exists")
        z.setdefault("honeypot_paths", []).append(url_path)
        touch(z)
        return success(zone_out(z), 200)

    @app.post("/api/zones/<zid>/honeypot-hits")
    def honeypot_hit(zid):
        role, uid = require_roles("ZoneAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        data = body()
        client_ip = req_str(data, "client_ip")
        url_path = req_str(data, "url_path")
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] != "ACTIVE":
            raise err_invalid_state("Zone must be ACTIVE")
        if url_path not in z.get("honeypot_paths", []):
            raise err_not_found(f"honeypot path '{url_path}' does not exist")
        hit_at = now_str()
        db.honeypot_logs.setdefault(zid, []).append(
            {"hit_at": hit_at, "client_ip": client_ip})
        return success({"honeypot_path": url_path,
                        "client_ip": client_ip,
                        "hit_at": hit_at}, 201)

    @app.post("/api/zones/<zid>/ddos-events")
    def create_ddos_event(zid):
        role, uid = require_roles("ZoneAdmin", "PlatformAdmin")
        z = _get_zone_or_404(zid)
        check_ownership(z, role, uid)
        data = body()
        observed = req_int(data, "observed_rps", minimum=0)
        baseline = req_int(data, "baseline_rps", minimum=1)
        if z["status"] == "DELETED":
            raise err_terminal("Zone is DELETED")
        if z["status"] != "ACTIVE":
            raise err_invalid_state("Zone must be ACTIVE")
        mult = SENSITIVITY_MULTIPLIER[z.get("dos_sensitivity", "DEFAULT")]
        import math
        threshold = math.floor(baseline * AUTO_THRESHOLD_MULTIPLIER * mult)
        auto_mitigated = observed >= threshold
        activated_at = now()
        expires_at = activated_at + timedelta(hours=AUTO_MITIGATION_TTL_HOURS)
        from core import fmt_ts
        event = stamp_new({
            "zone_id": zid,
            "observed_rps": observed,
            "baseline_rps": baseline,
            "trigger_threshold_rps": threshold,
            "auto_mitigated": auto_mitigated,
            "status": "ACTIVATED",
            "activated_at": fmt_ts(activated_at),
            "expires_at": fmt_ts(expires_at),
        })
        db.ddos_events[event["id"]] = event
        if auto_mitigated:
            z["dos_mitigation_active"] = True
        return success(ddos_out(event), 201)
