"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 3.1-3.9).

Shared helpers first, then one function per named calculation.  Every rounding
order is the one pinned by its own rule: risk scoring keeps its per-finding
products unrounded and rounds the sum once, while the disapproval assessment
rounds each line before summing.
"""

from decimal import Decimal

from core import D, db, q2, now, oldest_first, newest_first

# ---- constants ------------------------------------------------------------
DESTINATION_PENALTY_MISMATCH = D("15.00")
DESTINATION_PENALTY_CLOAKING = D("40.00")
CERT_CREDIT_PER_RULE = D("8.00")
CERT_CREDIT_CAP = D("24.00")

DECAY_HALF_AT_DAYS = 90
DECAY_ZERO_AT_DAYS = 180

QUEUE_BASE = {"STANDARD": D("30.00"), "REGULATED_CERT": D("45.00"), "POLITICAL": D("60.00")}
SEVERITY_COMPONENT_FACTOR = D("2.00")
SEVERITY_COMPONENT_CAP = D("30.00")
HISTORY_STEP_POINTS = D("10.00")
HISTORY_STEP_VALUE = D("5.00")
HISTORY_COMPONENT_CAP = D("15.00")
VERIFICATION_GAP = D("10.00")
DISCLOSURE_GAP = D("12.00")

REASON_FACTOR = {
    "AUTO_SCREENING": D("0.80"),
    "MANUAL_REVIEW": D("1.00"),
    "CERT_MISSING": D("0.60"),
    "CLOAKING": D("2.00"),
    "DESTINATION_MISMATCH": D("1.25"),
    "POLITICAL_DISCLOSURE": D("1.50"),
}
INTEGRITY_BASE_WEIGHT = D("10.00")
ASSESSED_POINTS_CAP = D("100.00")
INTEGRITY_REASON_SEQUENCE = ("CERT_MISSING", "CLOAKING", "DESTINATION_MISMATCH", "POLITICAL_DISCLOSURE")

REPEAT_ACTION_POINTS = D("5.00")
SURCHARGE_TIER_1_AT = D("20.00")
SURCHARGE_TIER_2_AT = D("35.00")
ACTION_THRESHOLDS = {"WARNING": D("10.00"), "RESTRICTION": D("25.00"), "SUSPENSION": D("40.00")}
ENFORCEMENT_DURATION_DAYS = {"WARNING": 30, "RESTRICTION": 60, "SUSPENSION": 180}
ENFORCEMENT_COOLDOWN_HOURS = 72

DEFAULT_SLA_HOURS = 48
APPEAL_WINDOW_HOURS_STANDARD = 72
APPEAL_WINDOW_HOURS_POLITICAL = 168
ARCHIVE_RETENTION_DAYS = 2555

ACTION_SEVERITY = {"WARNING": 1, "RESTRICTION": 2, "SUSPENSION": 3}
DISPOSITION_HARSHNESS = {
    "BLOCKED": 4,
    "RESTRICTED_CERT_REQUIRED": 3,
    "ALLOWED_WITH_DISCLAIMER": 2,
    "ALLOWED": 1,
}
CLASS_FALLBACK_DISPOSITION = {
    "PROHIBITED": "BLOCKED",
    "RESTRICTED": "RESTRICTED_CERT_REQUIRED",
    "REGULATED": "ALLOWED",
}


# ---- shared helpers -------------------------------------------------------
def host(url):
    """PRD 3.8: text between the first '://' and the next '/', lowercased."""
    if not isinstance(url, str):
        return ""
    marker = url.find("://")
    remainder = url[marker + 3:] if marker >= 0 else url
    slash = remainder.find("/")
    if slash >= 0:
        remainder = remainder[:slash]
    return remainder.lower()


def rule_by_code(code):
    for rule in db.policy_rules.values():
        if rule["code"] == code:
            return rule
    return None


def rules_for(creative):
    """The matched rule set: rules whose code appears in declared_category_codes."""
    matched = []
    for code in creative["declared_category_codes"]:
        rule = rule_by_code(code)
        if rule is not None and rule["id"] not in [r["id"] for r in matched]:
            matched.append(rule)
    return matched


def override_for(rule, country_code):
    for row in db.country_overrides.values():
        if row["policy_rule_id"] == rule["id"] and row["country_code"] == country_code:
            return row
    return None


def country_multiplier(rule, creative):
    best = None
    for country in creative["target_country_codes"]:
        row = override_for(rule, country)
        value = row["severity_multiplier"] if row is not None else D("1.00")
        if best is None or value > best:
            best = value
    return best if best is not None else D("1.00")


def strictest_multiplier(creative):
    best = None
    for rule in rules_for(creative):
        for country in creative["target_country_codes"]:
            row = override_for(rule, country)
            value = row["severity_multiplier"] if row is not None else D("1.00")
            if best is None or value > best:
                best = value
    return best if best is not None else D("1.00")


def disposition(rule, country_code):
    row = override_for(rule, country_code)
    if row is not None:
        return row["disposition"]
    return CLASS_FALLBACK_DISPOSITION[rule["category_class"]]


def strictest_disposition(rule, creative, countries=None):
    pool = creative["target_country_codes"] if countries is None else countries
    best = None
    for country in pool:
        value = disposition(rule, country)
        if best is None or DISPOSITION_HARSHNESS[value] > DISPOSITION_HARSHNESS[best]:
            best = value
    return best


def runs_for(creative):
    return [r for r in db.screening_runs.values() if r["ad_creative_id"] == creative["id"]]


def latest_run(creative):
    rows = runs_for(creative)
    if not rows:
        return None
    return max(rows, key=lambda r: r["sequence_index"])


def decisions_of_run(run):
    if run is None:
        return []
    rows = [d for d in db.classifier_decisions.values() if d["screening_run_id"] == run["id"]]
    return oldest_first(rows)


def latest_decisions(creative):
    return decisions_of_run(latest_run(creative))


def qualifying_decisions(creative):
    """Decisions of the latest run with disposition AUTO_DISAPPROVE or ROUTE_MANUAL."""
    return [d for d in latest_decisions(creative)
            if d["disposition"] in ("AUTO_DISAPPROVE", "ROUTE_MANUAL")]


def findings(creative):
    """Risk-score input set: latest-run decisions whose confidence reaches the
    matched rule's confidence_manual_threshold."""
    result = []
    for decision in latest_decisions(creative):
        rule = db.policy_rules.get(decision["policy_rule_id"])
        if rule is None:
            continue
        if decision["confidence"] >= rule["confidence_manual_threshold"]:
            result.append(decision)
    return result


# ---- calculations.certification_coverage ---------------------------------
def coverage_candidates(advertiser_id, rule_id, country_code, at_instant):
    result = []
    for cert in db.certifications.values():
        if cert["advertiser_id"] != advertiser_id:
            continue
        if cert["policy_rule_id"] != rule_id:
            continue
        if cert["issuing_country_code"] != country_code:
            continue
        if cert["status"] != "ACTIVE":
            continue
        if not (cert["valid_from"] <= at_instant and at_instant < cert["valid_until"]):
            continue
        result.append(cert)
    return result


def coverage_selection(candidates):
    """Ranked valid_until DESC, tie-break created_at ASC (never id)."""
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda c: (-c["valid_until"].timestamp(),
                                                c["created_at"].timestamp(), c["_seq"]))
    return ordered[0]


def country_demands_license(rule, country_code):
    if rule["requires_certification"]:
        return True
    row = override_for(rule, country_code)
    return bool(row is not None and row["requires_license"])


# ---- calculations.creative_risk_score -----------------------------------
def provisional_risk_score(creative):
    total = D("0")
    for decision in findings(creative):
        rule = db.policy_rules[decision["policy_rule_id"]]
        total += rule["base_severity_weight"] * country_multiplier(rule, creative) * decision["confidence"]
    value = q2(total)
    return value if value < D("100.00") else D("100.00")


def destination_penalty(creative):
    if creative["destination_status"] == "CLOAKING_CONFIRMED":
        return DESTINATION_PENALTY_CLOAKING
    if creative["destination_status"] == "MISMATCH_FLAGGED":
        return DESTINATION_PENALTY_MISMATCH
    return D("0.00")


def certification_credit(creative):
    instant = now()
    covered = set()
    for decision in findings(creative):
        rule = db.policy_rules[decision["policy_rule_id"]]
        if rule["id"] in covered:
            continue
        for country in creative["target_country_codes"]:
            if coverage_candidates(creative["advertiser_id"], rule["id"], country, instant):
                covered.add(rule["id"])
                break
    credit = CERT_CREDIT_PER_RULE * D(len(covered))
    return credit if credit < CERT_CREDIT_CAP else CERT_CREDIT_CAP


def final_risk_score(creative):
    raw = D(creative["risk_score_provisional"]) + destination_penalty(creative) - certification_credit(creative)
    value = q2(raw)
    if value < D("0.00"):
        value = D("0.00")
    if value > D("100.00"):
        value = D("100.00")
    return value


# ---- calculations.advertiser_violation_points ----------------------------
def ledger_of(advertiser_id):
    rows = [e for e in db.violation_ledger_entries.values() if e["advertiser_id"] == advertiser_id]
    return sorted(rows, key=lambda e: e["entry_index"])


def violation_points_raw(advertiser_id):
    total = D("0")
    for entry in ledger_of(advertiser_id):
        total += entry["delta_points"]
    value = q2(total)
    return value if value > D("0.00") else D("0.00")


def _age_days(entry, instant):
    seconds = (instant - entry["created_at"]).total_seconds()
    if seconds < 0:
        seconds = 0
    return int(seconds // 86400)


def decay_factor(entry, instant):
    age = _age_days(entry, instant)
    if age < DECAY_HALF_AT_DAYS:
        return D("1.00")
    if age < DECAY_ZERO_AT_DAYS:
        return D("0.50")
    return D("0.00")


def violation_points_decayed(advertiser_id):
    instant = now()
    total = D("0")
    for entry in ledger_of(advertiser_id):
        total += entry["delta_points"] * decay_factor(entry, instant)
    value = q2(total)
    return value if value > D("0.00") else D("0.00")


# ---- calculations.enforcement_severity_index -----------------------------
def actions_of(advertiser_id):
    return [a for a in db.enforcement_actions.values() if a["advertiser_id"] == advertiser_id]


def active_action(advertiser_id):
    rows = [a for a in actions_of(advertiser_id) if a["status"] == "ACTIVE"]
    if not rows:
        return None
    return newest_first(rows)[0]


def enforcement_severity_index(advertiser):
    closed = len([a for a in actions_of(advertiser["id"])
                  if a["status"] in ("SUPERSEDED", "LIFTED", "EXPIRED")])
    base_index = q2(advertiser["violation_points_decayed"] + REPEAT_ACTION_POINTS * D(closed))
    if base_index < SURCHARGE_TIER_1_AT:
        surcharge = D("0.00")
    elif base_index < SURCHARGE_TIER_2_AT:
        surcharge = D("3.50")
    else:
        surcharge = D("9.00")
    return q2(base_index + surcharge)


def select_action_type(severity_index):
    if severity_index >= ACTION_THRESHOLDS["SUSPENSION"]:
        return "SUSPENSION"
    if severity_index >= ACTION_THRESHOLDS["RESTRICTION"]:
        return "RESTRICTION"
    if severity_index >= ACTION_THRESHOLDS["WARNING"]:
        return "WARNING"
    return None


# ---- calculations.review_task_priority_score ----------------------------
def review_task_priority_score(queue, primary_rule, creative, advertiser):
    base = QUEUE_BASE[queue]
    if primary_rule is None:
        severity_component = D("0.00")
    else:
        product = q2(primary_rule["base_severity_weight"]
                     * strictest_multiplier(creative)
                     * SEVERITY_COMPONENT_FACTOR)
        severity_component = product if product < SEVERITY_COMPONENT_CAP else SEVERITY_COMPONENT_CAP
    steps = int(advertiser["violation_points_decayed"] / HISTORY_STEP_POINTS)
    history_component = HISTORY_STEP_VALUE * D(steps)
    if history_component > HISTORY_COMPONENT_CAP:
        history_component = HISTORY_COMPONENT_CAP
    verification_gap = VERIFICATION_GAP if (
        advertiser["identity_status"] != "VERIFIED"
        or advertiser["business_standing_status"] != "VERIFIED") else D("0.00")
    disclaimer = creative["disclaimer_text"]
    disclosure_gap = DISCLOSURE_GAP if (
        creative["political_flag"] and (disclaimer is None or disclaimer == "")) else D("0.00")
    dominant = severity_component if severity_component > history_component else history_component
    total = q2(base + dominant + verification_gap + disclosure_gap)
    return total if total < D("100.00") else D("100.00")


# ---- calculations.screening_disposition ---------------------------------
def decision_disposition(rule, confidence):
    if confidence >= rule["confidence_auto_disapprove_threshold"]:
        return "AUTO_DISAPPROVE"
    if confidence >= rule["confidence_manual_threshold"]:
        return "ROUTE_MANUAL"
    return "BELOW_THRESHOLD"


def screening_outcome(creative, advertiser, decision_rows):
    """Six clauses in exactly this order; first match wins."""
    for decision in decision_rows:
        if decision["disposition"] != "AUTO_DISAPPROVE":
            continue
        rule = db.policy_rules[decision["policy_rule_id"]]
        if strictest_disposition(rule, creative) == "BLOCKED":
            return "AUTO_DISAPPROVED"
    if creative["political_flag"]:
        return "ROUTED_MANUAL"
    for decision in decision_rows:
        if decision["disposition"] in ("AUTO_DISAPPROVE", "ROUTE_MANUAL"):
            return "ROUTED_MANUAL"
    if advertiser["identity_status"] != "VERIFIED" or advertiser["business_standing_status"] != "VERIFIED":
        return "ROUTED_MANUAL"
    if advertiser["account_status"] in ("RESTRICTED", "WARNED"):
        for rule in rules_for(creative):
            if rule["category_class"] in ("PROHIBITED", "RESTRICTED"):
                return "ROUTED_MANUAL"
    return "AUTO_APPROVED"


def screening_route(creative, decision_rows):
    """Step 3: queue and primary_policy_rule_id for a ROUTED_MANUAL outcome."""
    qualifying = [d for d in decision_rows
                  if d["disposition"] in ("AUTO_DISAPPROVE", "ROUTE_MANUAL")]
    if creative["political_flag"]:
        queue = "POLITICAL"
    else:
        queue = "STANDARD"
        for decision in qualifying:
            rule = db.policy_rules[decision["policy_rule_id"]]
            if rule["requires_certification"]:
                queue = "REGULATED_CERT"
                break
            hit = False
            for country in creative["target_country_codes"]:
                row = override_for(rule, country)
                if row is not None and row["requires_license"]:
                    hit = True
                    break
            if hit:
                queue = "REGULATED_CERT"
                break
    primary_rule_id = None
    if qualifying:
        ranked = sorted(
            qualifying,
            key=lambda d: (-d["confidence"], db.policy_rules[d["policy_rule_id"]]["code"]),
        )
        primary_rule_id = ranked[0]["policy_rule_id"]
    return queue, primary_rule_id


# ---- calculations.disapproval_points_assessment -------------------------
def disapproval_assessment(creative, reason_codes, decided_by_reviewer_id):
    source_reason = "AUTO_SCREENING" if decided_by_reviewer_id is None else "MANUAL_REVIEW"
    lines = []
    phase_1 = sorted(qualifying_decisions(creative),
                     key=lambda d: db.policy_rules[d["policy_rule_id"]]["code"])
    for decision in phase_1:
        rule = db.policy_rules[decision["policy_rule_id"]]
        line_points = q2(rule["base_severity_weight"]
                         * country_multiplier(rule, creative)
                         * REASON_FACTOR[source_reason])
        lines.append({
            "policy_rule_code": rule["code"],
            "reason_code": source_reason,
            "line_points": line_points,
        })
    strictest = strictest_multiplier(creative)
    for reason in INTEGRITY_REASON_SEQUENCE:
        if reason in reason_codes:
            line_points = q2(INTEGRITY_BASE_WEIGHT * strictest * REASON_FACTOR[reason])
            lines.append({
                "policy_rule_code": None,
                "reason_code": reason,
                "line_points": line_points,
            })
    total = D("0")
    for line in lines:
        total += line["line_points"]
    if total > ASSESSED_POINTS_CAP:
        total = ASSESSED_POINTS_CAP
    codes = sorted(set(line["policy_rule_code"] for line in lines
                       if line["policy_rule_code"] is not None))
    return lines, q2(total), codes


# ---- calculations.destination_check_result ------------------------------
def reference_crawler_check(creative, exclude_id=None):
    rows = [c for c in db.destination_checks.values()
            if c["ad_creative_id"] == creative["id"]
            and c["user_agent_variant"] == "CRAWLER"
            and c["id"] != exclude_id]
    if not rows:
        return None
    ordered = sorted(
        rows,
        key=lambda c: (c["created_at"].timestamp(), c["http_status"], c["fetched_final_url"], c["_seq"]),
        reverse=True,
    )
    return ordered[0]


def destination_check_result(creative, check_type, user_agent_variant,
                            fetched_final_url, fetched_content_category, http_status):
    declared_host = host(creative["display_url"])
    final_host = host(fetched_final_url)
    if http_status >= 400:
        return "MISMATCH", "DEST_UNREACHABLE"
    last_crawler = reference_crawler_check(creative)
    if user_agent_variant == "USER" and last_crawler is not None \
            and host(last_crawler["fetched_final_url"]) != final_host:
        return "CLOAKING", "UA_DIVERGENCE"
    if final_host != declared_host:
        return "MISMATCH", "HOST_MISMATCH"
    if fetched_content_category != "GENERAL" \
            and fetched_content_category not in creative["declared_category_codes"]:
        return "MISMATCH", "CATEGORY_MISMATCH"
    return "CLEARED", None


# ---- calculations.serving_eligibility_gate ------------------------------
def serving_gate(creative, advertiser):
    codes = []
    if creative["review_status"] not in ("AUTO_APPROVED", "APPROVED_LIMITED"):
        codes.append("REVIEW_NOT_APPROVED")
    if creative["destination_status"] != "DESTINATION_CLEARED":
        codes.append("DESTINATION_NOT_CLEARED")
    if advertiser["account_status"] not in ("ACTIVE", "WARNED"):
        codes.append("ACCOUNT_ENFORCEMENT")
    archived = any(e["ad_creative_id"] == creative["id"]
                   for e in db.political_archive_entries.values())
    political_ok = (not creative["political_flag"]) or (
        archived and advertiser["political_eligibility_status"] == "ELIGIBLE")
    if not political_ok:
        codes.append("POLITICAL_ARCHIVE_MISSING")
    return (len(codes) == 0), codes
