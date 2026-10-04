"""Underwriting: class-of-business determination, risk score, premium calc."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

import db
import errors

ALL_LINES = ("GL", "PL", "TOOLS")


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Class-of-business determination (scaffold calculation 1)
# ---------------------------------------------------------------------------
def _matched_rules(now=None):
    """All enabled, in-window appetite rules at the clock instant."""
    now = now or db.clock_now()
    out = []
    for r in db.appetite_rules.values():
        if not r["is_enabled"]:
            continue
        ef = db.parse_iso(r["effective_from"]) if isinstance(r["effective_from"], str) else r["effective_from"]
        et = db.parse_iso(r["effective_to"]) if isinstance(r["effective_to"], str) else r["effective_to"]
        if ef <= now < et:
            out.append(r)
    return out


def class_by_code(code):
    """Resolve an AppetiteRule.class_code (the ClassCode's human `code`)
    to its ClassCode record."""
    for c in db.class_codes.values():
        if c["code"] == code:
            return c
    return None


def classify(raw_description):
    """Returns (winner_class_record or None, matched_rule_records, routed_refer_bool,
    ambiguity_bool, decline_bool).

    Raises nothing; callers map results to quote status / errors.
    """
    tokens = db.tokenize(raw_description or "")
    rules = _matched_rules()
    matches = [r for r in rules if r["keyword"].lower() in tokens]

    # group matches by class_code
    by_class = {}
    for r in matches:
        by_class.setdefault(r["class_code"], []).append(r)

    refer_hit = False
    candidates = []  # admitted classes
    for class_id, rs in by_class.items():
        dispositions = {r["disposition"] for r in rs}
        if "DECLINE" in dispositions:
            continue  # excluded entirely
        if "REFER" in dispositions:
            refer_hit = True
            continue  # routes to REFERRED regardless of score
        # all ADMIT
        cls = class_by_code(class_id)
        if cls is None:
            continue
        if not cls["appetite_active"]:
            continue
        score = len(rs)
        rank_sum = sum(r["priority_rank"] for r in rs)
        earliest = min(r["_seq"] for r in rs)
        candidates.append({
            "class": cls,
            "score": score,
            "rank_sum": rank_sum,
            "earliest": earliest,
        })

    # REFER disposition on any matched rule routes the quote to REFERRED
    # regardless of score (per PRD 3.1), as long as that class was matched.
    if not candidates and not refer_hit:
        return None, matches, False, False, True  # decline

    if refer_hit and not candidates:
        return None, matches, True, False, False

    if candidates:
        candidates.sort(key=lambda c: (-c["score"], c["rank_sum"], c["earliest"]))
        top = candidates[0]
        tied = [c for c in candidates
                if c["score"] == top["score"]
                and c["rank_sum"] == top["rank_sum"]
                and c["earliest"] == top["earliest"]]
        # "More than one admitted class with equal top score after all
        # tie-breaks" — tie-breaks are deterministic (earliest creation),
        # so ambiguity requires genuinely identical keys. With distinct
        # earliest seq, first is unique. Ambiguity arises when two admitted
        # classes share score and rank_sum but... earliest always differs
        # unless same rule. We treat ambiguity as: >1 candidate sharing top
        # score AND top rank_sum whose earliest seq values coincide — which
        # cannot happen across classes. To honor the rule, treat >1
        # candidate with equal (score, rank_sum) as ambiguous unless the
        # earliest tie-break resolves to a single class.
        equal_top = [c for c in candidates
                     if c["score"] == top["score"] and c["rank_sum"] == top["rank_sum"]]
        if len(equal_top) > 1:
            # earliest tie-break: pick min earliest; if multiple share it -> ambiguous
            min_e = min(c["earliest"] for c in equal_top)
            winners = [c for c in equal_top if c["earliest"] == min_e]
            if len(winners) > 1:
                return None, matches, refer_hit, True, False
            top = winners[0]
        return top["class"], matches, refer_hit, False, False

    return None, matches, refer_hit, False, False


# ---------------------------------------------------------------------------
# Risk score (scaffold calculation 2)
# ---------------------------------------------------------------------------
def signal_points(severity):
    if severity >= 80:
        return 25
    if severity >= 50:
        return 15
    if severity >= 20:
        return 8
    return 3


def pending_signals(account_id):
    return [s for s in db.risk_signals.values()
            if s["business_account_id"] == account_id and s["status"] == "PENDING"]


def compute_risk_score(cls, account_id, uw_answers):
    base = round_half_up(Decimal(str(cls["risk_factor"])) * Decimal(20))
    pts = base
    for s in pending_signals(account_id):
        pts += signal_points(s["severity"])
    # Each uw_answers entry equal to the string "yes" contributes 10 points.
    for v in (uw_answers or {}).values():
        if v == "yes":
            pts += 10
    return max(0, min(100, pts))


# ---------------------------------------------------------------------------
# Premium (scaffold calculation 3)
# ---------------------------------------------------------------------------
def tier_multiplier(u):
    if u < 50:
        return Decimal("1.00")
    if u < 200:
        return Decimal("1.15")
    return Decimal("1.30")


def package_discount(n_lines):
    if n_lines >= 3:
        return Decimal("0.20")
    if n_lines == 2:
        return Decimal("0.10")
    return Decimal("0")


def premium_cents(cls, selected_lines, exposure_units, claims_free, variant="provisional",
                  exposure_uplift=False):
    """Premium formula, pinned order: tiering -> risk_factor -> package ->
    claims-free -> single final round_half_up.

    final variant: exposure-earned-audit uplift of exactly 3% applies if any
    EFFECTIVE COVERAGE_ADJUST raised exposure on the lineage.
    """
    mult = tier_multiplier(exposure_units)
    rf = Decimal(str(cls["risk_factor"]))
    total = Decimal(0)
    for line in selected_lines:
        rate = Decimal(int(cls["base_rates_cents"][line]))
        total += rate * Decimal(int(exposure_units)) * mult
    total = total * rf
    total = total * (Decimal(1) - package_discount(len(selected_lines)))
    if claims_free:
        total = total * (Decimal(1) - Decimal("0.05"))
    if variant == "final" and exposure_uplift:
        total = total * Decimal("1.03")
    return round_half_up(total)


def premium_basis_hash(class_code_id, selected_lines, exposure_units, uw_answers, signal_ids):
    payload = {
        "class_code_id": class_code_id,
        "selected_lines": sorted(selected_lines),
        "exposure_units": int(exposure_units),
        "uw_answers": {k: uw_answers.get(k) for k in sorted((uw_answers or {}).keys())},
        "signals": sorted(signal_ids),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
