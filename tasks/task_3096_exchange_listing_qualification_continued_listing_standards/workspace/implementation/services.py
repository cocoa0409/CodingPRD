"""Business logic: standards evaluation, deficiency detection, fees, cascades."""
from datetime import timedelta

from core import (ApiError, fmt_dt, make_common, make_immutable, now_dt,
                  now_str, parse_dt, store, touch)

TIERS = ["GLOBAL_SELECT", "GLOBAL", "CAPITAL"]

# ------------------------------------------------- entry standards (§3.2)
def _s(passed, margin):
    return {"passed": bool(passed), "margin": int(margin)}


def evaluate_entry_standards(app):
    """Fill evaluated_standards for the application's target_tier.
    Returns (results_list, any_passed)."""
    t = app["target_tier"]
    results = []
    if t == "GLOBAL_SELECT":
        s1 = app["income_from_continuing_operations_cents"] >= 1100000000
        results.append({"standard_code": "GLOBAL_SELECT_S1",
                        "passed": s1,
                        "margin": app["income_from_continuing_operations_cents"] - 1100000000})
        s2 = (app["market_value_listed_securities_cents"] >= 45000000000000
              and app["unrestricted_publicly_held_shares"] >= 1250000)
        results.append({"standard_code": "GLOBAL_SELECT_S2",
                        "passed": s2,
                        "margin": min(
                            app["market_value_listed_securities_cents"] - 45000000000000,
                            app["unrestricted_publicly_held_shares"] - 1250000)})
        s3 = (app["total_revenue_cents"] >= 9000000000000
              and app["market_value_listed_securities_cents"] >= 20000000000000)
        results.append({"standard_code": "GLOBAL_SELECT_S3",
                        "passed": s3,
                        "margin": min(
                            app["total_revenue_cents"] - 9000000000000,
                            app["market_value_listed_securities_cents"] - 20000000000000)})
    elif t == "GLOBAL":
        s1 = (app["stockholders_equity_cents"] >= 1500000000
              and app["market_value_unrestricted_publicly_held_cents"] >= 800000000
              and app["round_lot_holders"] >= 400
              and app["market_makers"] >= 3)
        results.append({"standard_code": "GLOBAL_S1", "passed": s1,
                        "margin": min(
                            app["stockholders_equity_cents"] - 1500000000,
                            app["market_value_unrestricted_publicly_held_cents"] - 800000000,
                            app["round_lot_holders"] - 400,
                            app["market_makers"] - 3)})
        s2 = (app["market_value_listed_securities_cents"] >= 7500000000000
              and app["market_value_unrestricted_publicly_held_cents"] >= 2000000000
              and app["round_lot_holders"] >= 400
              and app["market_makers"] >= 3)
        results.append({"standard_code": "GLOBAL_S2", "passed": s2,
                        "margin": min(
                            app["market_value_listed_securities_cents"] - 7500000000000,
                            app["market_value_unrestricted_publicly_held_cents"] - 2000000000,
                            app["round_lot_holders"] - 400,
                            app["market_makers"] - 3)})
        s3 = (app["total_revenue_cents"] >= 7500000000000
              and app["market_value_unrestricted_publicly_held_cents"] >= 2000000000
              and app["round_lot_holders"] >= 400
              and app["market_makers"] >= 3)
        results.append({"standard_code": "GLOBAL_S3", "passed": s3,
                        "margin": min(
                            app["total_revenue_cents"] - 7500000000000,
                            app["market_value_unrestricted_publicly_held_cents"] - 2000000000,
                            app["round_lot_holders"] - 400,
                            app["market_makers"] - 3)})
    elif t == "CAPITAL":
        base = (app["bid_price_cents"] >= 400
                and app["publicly_held_shares"] >= 1000000
                and app["round_lot_holders"] >= 300
                and app["market_makers"] >= 3)
        base_margin = min(app["bid_price_cents"] - 400,
                          app["publicly_held_shares"] - 1000000,
                          app["round_lot_holders"] - 300,
                          app["market_makers"] - 3)
        a1 = app["stockholders_equity_cents"] >= 500000000
        results.append({"standard_code": "CAPITAL_A1",
                        "passed": base and a1,
                        "margin": min(base_margin,
                                      app["stockholders_equity_cents"] - 500000000)})
        a2 = app["market_value_listed_securities_cents"] >= 5000000000000
        results.append({"standard_code": "CAPITAL_A2",
                        "passed": base and a2,
                        "margin": min(base_margin,
                                      app["market_value_listed_securities_cents"] - 5000000000000)})
        a3 = app["income_from_continuing_operations_cents"] >= 75000000
        results.append({"standard_code": "CAPITAL_A3",
                        "passed": base and a3,
                        "margin": min(base_margin,
                                      app["income_from_continuing_operations_cents"] - 75000000)})
    any_passed = any(r["passed"] for r in results)
    return results, any_passed


def evaluate_continued_standards(tier, mvls, mvph, holders):
    """Continued standards per §3.5 / calculations continued mode."""
    if tier == "GLOBAL_SELECT":
        return mvls >= 30000000000000
    if tier == "GLOBAL":
        return mvph >= 5000000000 and holders >= 400
    if tier == "CAPITAL":
        return mvph >= 1000000000 and holders >= 300
    return False


# ------------------------------------------------- governance (§3.2)
def validate_governance(app):
    board = app["board_directors"] or []
    audit = app["audit_committee"] or []
    comp = app["compensation_committee"] or []
    board_names = set()
    independent_count = 0
    for d in board:
        if not isinstance(d, dict):
            raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                           "board_directors entries must be objects", 422)
        board_names.add(d.get("director_name"))
        if d.get("is_independent"):
            independent_count += 1
    # strictly > 50%
    if not board or independent_count * 2 <= len(board):
        raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                       "Board must have strictly majority independent directors", 422)
    # audit: >=3 members, all independent, >=1 financial expert, subset of board
    if len(audit) < 3:
        raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                       "Audit committee must have at least 3 members", 422)
    expert = 0
    for m in audit:
        if m.get("director_name") not in board_names:
            raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                           "Audit committee member not on the board", 422)
        if not m.get("is_independent"):
            raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                           "Audit committee members must all be independent", 422)
        if m.get("is_financial_expert"):
            expert += 1
    if expert < 1:
        raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                       "Audit committee needs at least one financial expert", 422)
    # comp: >=2 members, all independent, subset of board
    if len(comp) < 2:
        raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                       "Compensation committee must have at least 2 members", 422)
    for m in comp:
        if m.get("director_name") not in board_names:
            raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                           "Compensation committee member not on the board", 422)
        if not m.get("is_independent"):
            raise ApiError("ERR_GOVERNANCE_COMPOSITION",
                           "Compensation committee members must all be independent", 422)


# ------------------------------------------------- fee brackets (§3.10)
MID_YEAR_SURCHARGE_CENTS = 1000000

_ENTRY_SHARED = [
    (1, 50000000, 15000000, 25000000),
    (50000001, 75000000, 20000000, 30000000),
    (75000001, 100000000, 25000000, 35000000),
    (100000001, None, 29500000, 50000000),
]
_ENTRY_CAPITAL = [
    (1, 5000000, 5000000, 7500000),
    (5000001, 15000000, 7500000, 10000000),
    (15000001, None, 10000000, 15000000),
]
_ANNUAL_SHARED = [
    (1, 50000000, 4500000, 10500000),
    (50000001, 75000000, 5500000, 12500000),
    (75000001, 100000000, 6500000, 14500000),
    (100000001, None, 7500000, 17500000),
]
_ANNUAL_CAPITAL = [
    (1, 5000000, 3000000, 5000000),
    (5000001, 15000000, 4000000, 6500000),
    (15000001, None, 5000000, 8000000),
]


def _pick_table(fee_kind, tier):
    if fee_kind == "ENTRY":
        return _ENTRY_CAPITAL if tier == "CAPITAL" else _ENTRY_SHARED
    return _ANNUAL_CAPITAL if tier == "CAPITAL" else _ANNUAL_SHARED


def compute_fee(fee_kind, tier, shares, delisted_mid_year=False):
    table = _pick_table(fee_kind, tier)
    for lo, hi, mn, mx in table:
        if hi is None:
            if shares >= lo:
                amt = min(shares, mx)
                amt = max(amt, mn)
                break
        elif lo <= shares <= hi:
            amt = min(max(shares, mn), mx)
            break
    else:
        # shares above all brackets: clamp to top row max
        lo, hi, mn, mx = table[-1]
        amt = min(shares, mx)
        amt = max(amt, mn)
    if delisted_mid_year:
        amt += MID_YEAR_SURCHARGE_CENTS
    return amt


# ------------------------------------------------- deficiency thresholds
BID_THRESHOLD_CENTS = 100
_CONT_MVPH = {"GLOBAL": 5000000000, "CAPITAL": 1000000000}  # GLOBAL_SELECT n/a
_CONT_MVLS = {"GLOBAL_SELECT": 30000000000000, "GLOBAL": 7500000000000,
              "CAPITAL": 5000000000000}
_CONT_HOLDERS = {"GLOBAL_SELECT": 400, "GLOBAL": 400, "CAPITAL": 300}

MONITORED = ["BID_PRICE", "MVPHS", "MVLS", "ROUND_LOT_HOLDERS",
             "TOTAL_SHAREHOLDERS"]
TRIGGER_DAYS = {"BID_PRICE": 30, "MVPHS": 10, "MVLS": 10,
                "ROUND_LOT_HOLDERS": 10, "TOTAL_SHAREHOLDERS": 10}
REGAIN_DAYS = 10
CURE_DAYS = 180
APPEAL_WINDOW_DAYS = 7

DEFICIENCY_TERMINAL = {"REGAINED", "DELIST_UPHELD", "DELIST_REVERSED"}


def _fails(standard, tier, snap):
    """True if snapshot strictly fails the continued threshold for standard."""
    if standard == "BID_PRICE":
        return snap["closing_bid_cents"] < BID_THRESHOLD_CENTS
    if standard == "MVPHS":
        if tier == "GLOBAL_SELECT":
            return False  # GLOBAL_SELECT uses the MVLS leg instead
        return snap["market_value_publicly_held_cents"] < _CONT_MVPH[tier]
    if standard == "MVLS":
        return snap["market_value_listed_securities_cents"] < _CONT_MVLS[tier]
    if standard == "ROUND_LOT_HOLDERS":
        return snap["round_lot_holders"] < _CONT_HOLDERS[tier]
    if standard == "TOTAL_SHAREHOLDERS":
        return snap["total_shareholders"] < _CONT_HOLDERS[tier]
    return False


def _snapshots_desc(issuer_id):
    snaps = [s for s in store.snapshots.values() if s["issuer_id"] == issuer_id]
    return sorted(snaps, key=lambda s: s["trade_date"], reverse=True)


def _consecutive_fail_run(standard, tier, snaps_desc):
    run = 0
    for snap in snaps_desc:
        if _fails(standard, tier, snap):
            run += 1
        else:
            break
    return run


def _consecutive_compliant_run(standard, tier, snaps_desc):
    run = 0
    for snap in snaps_desc:
        if not _fails(standard, tier, snap):
            run += 1
        else:
            break
    return run


def create_compliance_record(issuer_id, deficiency_id, method, qualifying_days):
    rec = make_immutable({
        "issuer_id": issuer_id,
        "deficiency_id": deficiency_id,
        "regained_at": now_str(),
        "qualifying_days": int(qualifying_days),
        "method": method,
    })
    store.compliance_records[rec["id"]] = rec
    return rec


def run_monitor(issuer):
    """Detection + regain scan for one issuer. Returns (created, regained)."""
    issuer_id = issuer["id"]
    listing = None
    for l in store.listings.values():
        if l["issuer_id"] == issuer_id and l["status"] != "DELISTED":
            listing = l
            break
    if listing is None:
        listing = next((l for l in store.listings.values()
                        if l["issuer_id"] == issuer_id), None)
    tier = listing["tier"] if listing else "CAPITAL"
    snaps_desc = _snapshots_desc(issuer_id)

    created = []
    if snaps_desc:
        for standard in MONITORED:
            if standard == "MVPHS" and tier == "GLOBAL_SELECT":
                # GLOBAL_SELECT uses the MVLS leg instead of MVPHS
                continue
            run = _consecutive_fail_run(standard, tier, snaps_desc)
            if run >= TRIGGER_DAYS[standard]:
                existing = any(
                    d for d in store.deficiencies.values()
                    if d["issuer_id"] == issuer_id
                    and d["standard_code"] == standard
                    and d["status"] not in DEFICIENCY_TERMINAL)
                if not existing:
                    now = now_dt()
                    d = make_common({
                        "issuer_id": issuer_id,
                        "standard_code": standard,
                        "tier_at_detection": tier,
                        "consecutive_days_failed": run,
                        "detected_at": now_str(),
                        "compliance_due_at": fmt_dt(now + timedelta(days=CURE_DAYS)),
                        "staff_determined_at": None,
                        "still_open": True,
                        "status": "OPEN",
                        "closed_at": None,
                    })
                    store.deficiencies[d["id"]] = d
                    created.append(d)

    regained = []
    for d in list(store.deficiencies.values()):
        if d["issuer_id"] != issuer_id or d["status"] in DEFICIENCY_TERMINAL:
            continue
        if d["status"] not in ("OPEN", "PLAN_SUBMITTED"):
            d["still_open"] = True
            touch(d)
            continue
        standard = d["standard_code"]
        if standard not in MONITORED:
            # STOCKHOLDERS_EQUITY is not snapshot-monitored
            d["still_open"] = True
            touch(d)
            continue
        det_tier = d["tier_at_detection"]
        if standard == "MVPHS" and det_tier == "GLOBAL_SELECT":
            d["still_open"] = True
            touch(d)
            continue
        run = _consecutive_compliant_run(standard, det_tier, snaps_desc)
        if run >= REGAIN_DAYS:
            d["status"] = "REGAINED"
            d["still_open"] = False
            d["closed_at"] = now_str()
            touch(d)
            create_compliance_record(issuer_id, d["id"], "NATURAL", run)
            regained.append(d)
        else:
            d["still_open"] = True
            touch(d)
    return created, regained


# ------------------------------------------------- delisting cascade (§3.8)
def execute_delisting(listing):
    issuer = store.issuers[listing["issuer_id"]]
    ts = now_str()
    # ACTIVE -> SUSPENDED -> DELISTED in one request
    listing["status"] = "SUSPENDED"
    listing["suspended_at"] = ts
    touch(listing)
    listing["status"] = "DELISTED"
    listing["delisted_at"] = ts
    touch(listing)
    issuer["status"] = "DELISTED"
    touch(issuer)

    # invoice pending fees
    for f in store.fees.values():
        if f["issuer_id"] == issuer["id"] and f["status"] == "PENDING":
            f["status"] = "INVOICED"
            touch(f)

    # fill ANNUAL fee if none for clock year
    clock_year = now_dt().year
    annual_exists = any(
        f for f in store.fees.values()
        if f["issuer_id"] == issuer["id"] and f["fee_kind"] == "ANNUAL"
        and f["assessment_year"] == clock_year)
    if not annual_exists:
        # shares: latest ANNUAL assessment if any else approving app's UPHS,
        # halved (floor) per EFFECTIVE REVERSE_SPLIT, earliest first
        annuals = [f for f in store.fees.values()
                   if f["issuer_id"] == issuer["id"] and f["fee_kind"] == "ANNUAL"]
        if annuals:
            annuals.sort(key=lambda f: f["created_at"])
            shares = annuals[-1]["shares_outstanding"]
        else:
            app = store.applications.get(listing.get("application_id"))
            shares = app["unrestricted_publicly_held_shares"] if app else 1
        splits = [a for a in store.actions.values()
                  if a["issuer_id"] == issuer["id"]
                  and a["status"] == "EFFECTIVE"
                  and a["action_type"] == "REVERSE_SPLIT"]
        splits.sort(key=lambda a: (a.get("updated_at") or "", a["id"]))
        for a in splits:
            shares = shares // a["split_ratio_denominator"]
        if shares < 1:
            shares = 1
        fee = make_common({
            "issuer_id": issuer["id"],
            "fee_kind": "ANNUAL",
            "tier": listing["tier"],
            "assessment_year": clock_year,
            "shares_outstanding": shares,
            "amount_cents": compute_fee("ANNUAL", listing["tier"], shares,
                                        delisted_mid_year=True),
            "delisted_mid_year": True,
            "status": "PENDING",
        })
        store.fees[fee["id"]] = fee
        fee["status"] = "INVOICED"
        touch(fee)

    # close open deficiencies
    for d in store.deficiencies.values():
        if d["issuer_id"] == issuer["id"] and d["status"] in (
                "OPEN", "PLAN_SUBMITTED", "STAFF_DELIST_DETERMINED",
                "PANEL_REVIEW"):
            d["status"] = "DELIST_UPHELD"
            d["closed_at"] = ts
            touch(d)

    # affirm undecided appeals
    for a in store.appeals.values():
        if a["issuer_id"] == issuer["id"] and a["status"] in (
                "FILED", "PANEL_REVIEWING"):
            a["status"] = "PANEL_AFFIRMED"
            a["decided_by"] = "PANEL"
            touch(a)

    # cancel submitted corporate actions
    for a in store.actions.values():
        if a["issuer_id"] == issuer["id"] and a["status"] == "SUBMITTED":
            a["status"] = "CANCELLED"
            touch(a)


# ------------------------------------------------- reverse split (§3.9)
def effect_reverse_split(issuer, action):
    issuer_id = issuer["id"]
    qualifying = [d for d in store.deficiencies.values()
                  if d["issuer_id"] == issuer_id
                  and d["standard_code"] == "BID_PRICE"
                  and d["status"] in ("OPEN", "PLAN_SUBMITTED")]
    if not qualifying:
        raise ApiError("ERR_NO_QUALIFYING_DEFICIENCY",
                       "No OPEN/PLAN_SUBMITTED BID_PRICE deficiency", 422)
    action["status"] = "EFFECTIVE"
    touch(action)
    snaps_desc = _snapshots_desc(issuer_id)[:10]
    n = action["split_ratio_denominator"]
    run = 0
    for snap in snaps_desc:
        if snap["closing_bid_cents"] * n >= BID_THRESHOLD_CENTS:
            run += 1
        else:
            break
    if run >= REGAIN_DAYS:
        d = qualifying[0]
        was_plan = d["status"] == "PLAN_SUBMITTED"
        d["status"] = "REGAINED"
        d["still_open"] = False
        d["closed_at"] = now_str()
        touch(d)
        create_compliance_record(issuer_id, d["id"], "REVERSE_SPLIT", run)
        if was_plan:
            for p in store.plans.values():
                if p["deficiency_id"] == d["id"] and p["status"] == "PENDING_REVIEW":
                    p["status"] = "REJECTED"
                    touch(p)
