"""The fifteen calculation rules of the PRD, plus their pinned constants."""
from decimal import Decimal

from store import db, ordered
from util import ceil_dec, dec, fmt1, normalize, num, r1, r2, sha256_hex

# --- pinned constants -----------------------------------------------------
ORNAMENTATION_LISTING_THRESHOLD_PCT = dec("5.0")
STAGE_RANK = {"TRIM": 0, "FIBER": 1, "YARN": 2, "FABRIC": 3, "CUT_AND_SEW": 4}
CARE_MIN_CYCLES = 5
CARE_MAX_SHRINKAGE_PCT = dec("3.0")
CARE_MIN_COLORFASTNESS = dec("3.5")
PRODUCT_CLASS_DURABILITY_FACTOR = {
    "WOVEN_OUTERWEAR": dec("1.00"), "KNIT_TOP": dec("1.25"),
    "HOSIERY": dec("1.50"), "HOME_TEXTILE": dec("0.80"),
}
ORGANIC_CLAIM_MIN_PCT = dec("95.0")
WRINKLE_FREE_MAX_SHRINKAGE_PCT = dec("2.0")
PER_UNIT_PENALTY_USD = dec("1.25")
STATUTORY_CAP_RATE = dec("0.80")
ESCALATION_BY_POSTURE = {"OPEN": dec("1.00"), "RESTRICTED": dec("1.50"), "SUSPENDED": dec("2.00")}
PROMPT_CORRECTION_WINDOW_DAYS = 10
MITIGATION_RATE_PROMPT_FULL = dec("1.00")
MITIGATION_RATE_PARTIAL = dec("0.50")
PENALTY_SUSPEND_LEDGER_USD = dec("25000.00")
CRITICAL_FINDING_RESTRICT_THRESHOLD = 3
SEVERITY_ESCALATION_UNITS = 5000
LAB_BENCH_CAPACITY = 2
CONDITIONING_BUFFER_HOURS = 24
FIBER_TEST_VALIDITY_DAYS = 365
CARE_TEST_VALIDITY_DAYS = 730
REDELIVERY_WINDOW_DAYS = 30

LADDER_BLOCKING_ORDER = ["ERR_FIBER_NOT_SUBSTANTIATED", "ERR_ORIGIN_NOT_ISSUED",
                         "ERR_CARE_NOT_SUBSTANTIATED", "ERR_DURABILITY_INSUFFICIENT"]


# --- 1. effective_fiber_content_text -------------------------------------
def effective_fiber_content_text(declared_fibers):
    lines = declared_fibers or []
    if not lines:
        return ""
    listed = [l for l in lines
              if not l["ornamentation_exempt"]
              and l["declared_pct"] >= ORNAMENTATION_LISTING_THRESHOLD_PCT]
    bucketed = [l for l in lines
                if l["ornamentation_exempt"]
                or l["declared_pct"] < ORNAMENTATION_LISTING_THRESHOLD_PCT]
    listed = sorted(listed, key=lambda l: (-l["declared_pct"], l["fiber_generic_name"]))
    parts = [fmt1(l["declared_pct"]) + "% " + l["fiber_generic_name"] for l in listed]
    if bucketed:
        total = sum((l["declared_pct"] for l in bucketed), Decimal("0"))
        parts.append(fmt1(r1(total)) + "% OTHER FIBER")
    return ", ".join(parts)


# --- 2. fiber_tolerance_evaluation ---------------------------------------
def fiber_tolerance_evaluation(style, measured_fibers):
    from validate import market_of
    markets = [market_of(code) for code in style["target_market_codes"]]
    markets = [m for m in markets if m is not None]
    non_exempt = [l for l in style["declared_fibers"] if not l["ornamentation_exempt"]]
    is_absolute_claim = (len(non_exempt) == 1 and non_exempt[0]["declared_pct"] == dec("100.0"))
    key = "absolute_claim_tolerance_pp" if is_absolute_claim else "fiber_tolerance_pp"
    tolerance = min([m[key] for m in markets]) if markets else dec("0.0")

    declared = {l["fiber_generic_name"]: l["declared_pct"] for l in non_exempt}
    measured = {m["fiber_generic_name"]: m["measured_pct"] for m in (measured_fibers or [])}
    names = set(declared) | set(measured)
    deltas = [abs(measured.get(n, dec("0.0")) - declared.get(n, dec("0.0"))) for n in names]
    delta_max = r1(max(deltas)) if deltas else dec("0.0")
    return delta_max, (delta_max <= tolerance)


# --- 3. origin_country_determination -------------------------------------
def _argmax_country(pool, metric_key):
    groups = {}
    for node in pool:
        groups.setdefault(node["country_code"], []).append(node)
    scored = []
    for country, nodes in groups.items():
        total = sum((n[metric_key] for n in nodes), Decimal("0"))
        top_rank = max(STAGE_RANK[n["stage"]] for n in nodes)
        scored.append((-total, -top_rank, country))
    scored.sort()
    return scored[0][2] if scored else None


def origin_pools(style_id):
    nodes = [n for n in db.material_inputs.values()
             if n["style_id"] == style_id and not n["is_ornamentation"]]
    a_pool = [n for n in nodes if n["stage"] in ("YARN", "FABRIC", "CUT_AND_SEW")]
    b_pool = [n for n in nodes if n["stage"] == "YARN"]
    if not b_pool:
        b_pool = [n for n in nodes if n["stage"] == "FIBER"]
    return nodes, a_pool, b_pool


def origin_country_determination(style_id):
    nodes, a_pool, b_pool = origin_pools(style_id)
    st_country = _argmax_country(a_pool, "value_added_usd")
    yf_country = _argmax_country(b_pool, "weight_grams")
    return st_country, yf_country, len(nodes)


# --- 4. care_performance_evaluation --------------------------------------
def care_performance_evaluation(test):
    return (test["cycles_run"] >= CARE_MIN_CYCLES
            and abs(test["dimensional_change_pct"]) <= CARE_MAX_SHRINKAGE_PCT
            and test["colorfastness_grade"] >= CARE_MIN_COLORFASTNESS)


# --- 5. durability_adequacy ----------------------------------------------
def durability_floor(market_codes, product_class):
    from validate import market_of
    regimes = [market_of(c) for c in market_codes]
    regimes = [r for r in regimes if r is not None]
    if not regimes:
        return 0
    base = max(r["min_durability_cycles"] for r in regimes)
    factor = PRODUCT_CLASS_DURABILITY_FACTOR[product_class]
    return ceil_dec(dec(base) * factor)


def durability_adequacy(spec, style, care_test):
    floor = durability_floor(spec["market_codes"], style["product_class"])
    substantiated = min(care_test["legibility_cycles"], spec["durability_cycles_rating"])
    return substantiated >= floor


# --- 6. label_content_hash -----------------------------------------------
def label_content_hash(spec, brand):
    care_code_string = "/".join([
        str(spec["wash_temp_c"]), spec["bleach_code"], spec["dry_code"],
        spec["iron_code"], spec["dryclean_code"]])
    if spec["identity_display_mode"] == "RN":
        identity_string = brand["rn_number"] if brand and brand.get("rn_number") else ""
    else:
        identity_string = normalize(brand["legal_name"]) if brand else ""
    canonical = "|".join([
        normalize(spec["fiber_content_text"]),
        normalize(spec["origin_text"]),
        care_code_string,
        identity_string,
        ",".join(sorted(spec["languages"])),
    ])
    return sha256_hex(canonical)


# --- 7. hangtag_consistency ----------------------------------------------
def claim_supported(claim, parent, style):
    if claim == "MADE_IN_USA":
        return normalize(parent["origin_text"]) == "MADE IN US"
    if claim == "ORGANIC_COTTON":
        for line in style["declared_fibers"]:
            if (line["fiber_generic_name"] == "ORGANIC COTTON"
                    and line["declared_pct"] >= ORGANIC_CLAIM_MIN_PCT):
                return True
        return False
    if claim == "WRINKLE_FREE":
        care = db.lab_tests.get(parent.get("care_test_id"))
        if care is None or care["state"] != "PASSED":
            return False
        change = care.get("dimensional_change_pct")
        return change is not None and change <= WRINKLE_FREE_MAX_SHRINKAGE_PCT
    return False


def hangtag_claims_ok(spec, parent, style):
    return all(claim_supported(c, parent, style) for c in (spec.get("marketing_claims") or []))


def hangtag_text_ok(spec, parent):
    return (normalize(spec["fiber_content_text"]) == normalize(parent["fiber_content_text"])
            and normalize(spec["origin_text"]) == normalize(parent["origin_text"]))


def hangtag_consistency(spec):
    if spec["artifact_type"] == "PERMANENT_LABEL":
        return "NOT_APPLICABLE"
    parent = db.label_specs.get(spec.get("parent_label_spec_id"))
    if parent is None:
        return "INCONSISTENT"
    style = db.styles.get(spec["style_id"])
    ok = hangtag_text_ok(spec, parent) and hangtag_claims_ok(spec, parent, style)
    return "CONSISTENT" if ok else "INCONSISTENT"


# --- 11/12. brand ledger and posture -------------------------------------
def responsible_of(brand):
    if brand is None:
        return None
    if brand["responsibility_mode"] == "LICENSOR_OF_RECORD":
        return brand["licensor_brand_id"]
    return brand["id"]


def brand_penalty_ledger(brand_id, exclude_shipment_id=None):
    total = Decimal("0")
    for shipment in db.import_shipments.values():
        if shipment["id"] == exclude_shipment_id:
            continue
        if shipment["marking_state"] not in ("REDELIVERY_ORDERED", "MARKING_CORRECTED"):
            continue
        importer = db.brands.get(shipment["importer_brand_id"])
        if responsible_of(importer) != brand_id:
            continue
        total += shipment["penalty_assessed_usd"] - shipment["penalty_mitigated_usd"]
    return r2(total)


def critical_audit_finding_count(brand_id):
    total = 0
    for audit in db.compliance_audits.values():
        audited = db.brands.get(audit["brand_id"])
        if responsible_of(audited) == brand_id:
            total += audit_counts(audit["id"])[1]
    return total


def brand_posture(brand_id, exclude_shipment_id=None):
    ledger = brand_penalty_ledger(brand_id, exclude_shipment_id)
    if ledger > PENALTY_SUSPEND_LEDGER_USD:
        return "SUSPENDED"
    for audit in db.compliance_audits.values():
        audited = db.brands.get(audit["brand_id"])
        if responsible_of(audited) != brand_id:
            continue
        if audit["state"] != "IN_REVIEW":
            continue
        if audit_counts(audit["id"])[1] >= CRITICAL_FINDING_RESTRICT_THRESHOLD:
            return "RESTRICTED"
    return "OPEN"


def brand_of_record(brand):
    """The Brand row that carries responsibility for this brand."""
    if brand is None:
        return None
    return db.brands.get(responsible_of(brand))


# --- 9. marking_penalty_assessment ---------------------------------------
def marking_penalty_assessment(shipment, regime, posture_at_review):
    duty_base = r2(shipment["declared_value_usd"] * regime["marking_duty_rate"])
    ad_valorem = r2(duty_base * ESCALATION_BY_POSTURE[posture_at_review])
    statutory = min(r2(dec(shipment["quantity_units"]) * PER_UNIT_PENALTY_USD),
                    r2(shipment["declared_value_usd"] * STATUTORY_CAP_RATE))
    basis = "STATUTORY_PER_UNIT" if posture_at_review == "SUSPENDED" else "AD_VALOREM"
    assessed = statutory if basis == "STATUTORY_PER_UNIT" else ad_valorem
    return ad_valorem, statutory, basis, assessed


# --- 10. penalty_mitigation ----------------------------------------------
def penalty_mitigation(shipment, corrected_units, clock):
    from util import plus_days
    ratio = dec(corrected_units) / dec(shipment["quantity_units"])
    prompt = clock <= plus_days(shipment["review_decided_at"], PROMPT_CORRECTION_WINDOW_DAYS)
    complete = corrected_units == shipment["quantity_units"]
    rate = MITIGATION_RATE_PROMPT_FULL if (complete and prompt) else MITIGATION_RATE_PARTIAL
    return r2(shipment["penalty_assessed_usd"] * rate * ratio)


# --- 13. finding_severity ------------------------------------------------
_BASE_SEVERITY = {
    "FIBER_CONTENT_MISSTATED": "CRITICAL", "ORIGIN_MISSTATED": "CRITICAL",
    "CARE_UNSUBSTANTIATED": "MAJOR", "IDENTITY_MISSING": "MAJOR",
    "PLACEMENT_NON_PERMANENT": "MAJOR", "HANGTAG_INCONSISTENT": "MINOR",
}
_ESCALATE = {"MINOR": "MAJOR", "MAJOR": "CRITICAL", "CRITICAL": "CRITICAL"}


def finding_severity(finding_code, units_affected):
    base = _BASE_SEVERITY[finding_code]
    if units_affected >= SEVERITY_ESCALATION_UNITS:
        return _ESCALATE[base]
    return base


# --- 14. audit_rollup ----------------------------------------------------
def findings_of(audit_id):
    return [f for f in db.audit_findings.values() if f["audit_id"] == audit_id]


def audit_counts(audit_id):
    findings = findings_of(audit_id)
    open_set = [f for f in findings if f["state"] in ("OPEN", "REMEDIATED")]
    open_count = len(open_set)
    critical = len([f for f in open_set if f["severity"] == "CRITICAL"])
    units = sum(f["units_affected"] for f in findings)
    return open_count, critical, units, len(findings)


def audit_rollup(audit):
    """Re-derive the counters and the derived audit state.  Returns True on a
    state change so the caller can honour the posture-recompute triggers."""
    open_count, critical, units, total = audit_counts(audit["id"])
    audit["open_finding_count"] = open_count
    audit["critical_finding_count"] = critical
    audit["units_in_scope"] = units
    changed = False
    if audit["state"] == "IN_REVIEW" and open_count == 0 and total > 0:
        audit["state"] = "PENDING_CLOSURE"
        changed = True
    elif audit["state"] == "PENDING_CLOSURE" and open_count > 0:
        audit["state"] = "IN_REVIEW"
        changed = True
    return changed


# --- 15. finding_unit_conservation ---------------------------------------
def units_unresolved(finding):
    return (finding["units_affected"] - finding["units_relabeled"]
            - finding["units_destroyed"] - finding["units_released"])


# --- style derived helpers ----------------------------------------------
def label_readiness(style):
    if (style["substantiation_state"] == "FIBER_SUBSTANTIATED"
            and style["origin_state"] == "ORIGIN_ISSUED"):
        return "READY"
    return "BLOCKED"


def current_issued_determination(style_id):
    for det in db.origin_determinations.values():
        if det["style_id"] == style_id and det["state"] == "ISSUED":
            return det
    return None


def passed_fiber_test(style_id):
    for test in db.lab_tests.values():
        if (test["style_id"] == style_id and test["test_type"] == "FIBER_CONTENT"
                and test["state"] == "PASSED"):
            return test
    return None


def newest_passed_care_test(style_id):
    rows = [t for t in db.lab_tests.values()
            if t["style_id"] == style_id and t["test_type"] == "CARE_PERFORMANCE"
            and t["state"] == "PASSED"]
    rows = ordered(rows)
    return rows[-1] if rows else None
