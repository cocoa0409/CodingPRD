"""Shared business logic: helpers, calculations, and cascade operations."""
import uuid

from db import store, now_iso, _parse_iso
import errors


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
    return rec


def ledger_new(rec):
    rec["created_at"] = now_iso()
    return rec


# ---------------------------------------------------------------------------
# Lookup helpers (existence, left-to-right handled by callers)
# ---------------------------------------------------------------------------

def get_company(cid):
    c = store.fund_companies.get(cid)
    if c is None:
        raise errors.not_found(f"FundCompany not found: {cid}")
    return c


def get_fund(fid):
    f = store.funds.get(fid)
    if f is None:
        raise errors.not_found(f"Fund not found: {fid}")
    return f


def get_category(cid):
    c = store.categories.get(cid)
    if c is None:
        raise errors.not_found(f"Category not found: {cid}")
    return c


def get_methodology(mid):
    m = store.methodologies.get(mid)
    if m is None:
        raise errors.not_found(f"Methodology not found: {mid}")
    return m


def get_change(cid):
    c = store.methodology_changes.get(cid)
    if c is None:
        raise errors.not_found(f"MethodologyChange not found: {cid}")
    return c


def get_rating(rid):
    r = store.ratings.get(rid)
    if r is None:
        raise errors.not_found(f"Rating not found: {rid}")
    return r


def get_proposal(pid):
    p = store.proposals.get(pid)
    if p is None:
        raise errors.not_found(f"RatingProposal not found: {pid}")
    return p


def get_flag(fid):
    f = store.conflict_flags.get(fid)
    if f is None:
        raise errors.not_found(f"ConflictFlag not found: {fid}")
    return f


def get_licensee(lid):
    l = store.licensees.get(lid)
    if l is None:
        raise errors.not_found(f"Licensee not found: {lid}")
    return l


def get_agreement(aid):
    a = store.agreements.get(aid)
    if a is None:
        raise errors.not_found(f"LicenseAgreement not found: {aid}")
    return a


def get_seat(sid):
    s = store.seats.get(sid)
    if s is None:
        raise errors.not_found(f"SeatEntitlement not found: {sid}")
    return s


def get_audit(aid):
    a = store.audits.get(aid)
    if a is None:
        raise errors.not_found(f"LicenseAudit not found: {aid}")
    return a


def get_dispute(did):
    d = store.disputes.get(did)
    if d is None:
        raise errors.not_found(f"DataDispute not found: {did}")
    return d


def get_index(iid):
    i = store.indices.get(iid)
    if i is None:
        raise errors.not_found(f"IndexDefinition not found: {iid}")
    return i


# ---------------------------------------------------------------------------
# Calculation: quantitative_star_rating (PRD §3.5)
# ---------------------------------------------------------------------------

def compute_star_variants(fund, methodology):
    """Return (final_stars, provisional_stars). Integer floor division only."""
    r3 = fund["trailing_return_3y_bp"]
    r5 = fund["trailing_return_5y_bp"]
    k = fund["risk_score_bp"]
    wr = methodology["weight_return_bp"]
    wk = methodology["weight_risk_bp"]
    ceilings = methodology["rating_ceilings"]

    # Final variant: blended 6000/4000 return leg.
    if r5 is None:
        return_leg = r3
    else:
        return_leg = (r3 * 6000 + r5 * 4000) // 10000
    score = (return_leg * wr + (10000 - k) * wk) // 10000
    final_stars = _stars_for(score, ceilings)

    # Provisional variant: return leg uses R3 alone.
    prov_score = (r3 * wr + (10000 - k) * wk) // 10000
    prov_stars = _stars_for(prov_score, ceilings)
    return final_stars, prov_stars


def _stars_for(score_bp, ceilings):
    c1, c2, c3, c4 = ceilings
    if score_bp >= c1:
        return 5
    if score_bp >= c2:
        return 4
    if score_bp >= c3:
        return 3
    if score_bp >= c4:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Calculation: category_assignment (PRD §3.2)
# ---------------------------------------------------------------------------

def latest_snapshot_rows(fund_id):
    rows = [h for h in store.holdings.values() if h["fund_id"] == fund_id]
    if not rows:
        return None
    latest = max(h["as_of_date"] for h in rows)
    return [h for h in rows if h["as_of_date"] == latest]


def assign_category(fund):
    """Run the category assignment over the fund's latest snapshot.
    Returns the winning Category record or None when nothing is eligible."""
    snapshot = latest_snapshot_rows(fund["id"])
    if not snapshot:
        return None
    best = None
    best_score = None
    for cat in store.categories.values():
        if not cat["active"]:
            continue
        asset_bp = 0
        sector_bp = 0
        for h in snapshot:
            ac = cat["dominant_asset_class"]
            if ac == "MIXED":
                if h["asset_class"] in ("EQUITY", "BOND"):
                    asset_bp += h["weight_bp"]
            elif h["asset_class"] == ac:
                asset_bp += h["weight_bp"]
            sec = cat["dominant_sector"]
            if sec == "MIXED" or h["sector"] == sec:
                sector_bp += h["weight_bp"]
        if asset_bp < cat["min_weight_bp"]:
            continue
        score = asset_bp * 7000 + sector_bp * 3000
        if (
            best is None
            or score > best_score
            or (score == best_score and cat["category_code"] < best["category_code"])
        ):
            best = cat
            best_score = score
    return best


def apply_category_assignment(fund):
    """Best-effort category assignment used after holdings ingestion.
    On change: update category_id, increment category_assignment_revision and
    the fund's version (PRD §3.2)."""
    winner = assign_category(fund)
    new_id_val = winner["id"] if winner else None
    if new_id_val != fund["category_id"]:
        fund["category_id"] = new_id_val
        fund["category_assignment_revision"] += 1
        touch(fund)


# ---------------------------------------------------------------------------
# Calculation: license_fee_quote (PRD §3.8)
# ---------------------------------------------------------------------------

_SEAT_FEE = {"DISPLAY": 120000, "REDISTRIBUTION": 250000, "DERIVED_WORKS": 500000}


def volume_discount_bp(seat_limit):
    if seat_limit <= 10:
        return 0
    if seat_limit <= 50:
        return 1000
    if seat_limit <= 200:
        return 2000
    return 3000


def fee_quote(tier, seat_limit, base_fee_cents):
    seat_component_raw = _SEAT_FEE[tier] * seat_limit
    seat_component = seat_component_raw - (seat_component_raw * volume_discount_bp(seat_limit)) // 10000
    pre_surcharge = base_fee_cents + seat_component
    surcharge_bp = 2500 if tier == "DERIVED_WORKS" else 0
    return pre_surcharge + (pre_surcharge * surcharge_bp) // 10000


# ---------------------------------------------------------------------------
# Calculation: audit_penalty (PRD §3.9)
# ---------------------------------------------------------------------------

_AUDIT_RATE = {"DISPLAY": 50000, "REDISTRIBUTION": 150000, "DERIVED_WORKS": 400000}


def audit_penalty(agreement, unlicensed_uses_found):
    per_use = _AUDIT_RATE[agreement["tier"]]
    raw = per_use * unlicensed_uses_found
    licensee_id = agreement["licensee_id"]
    prior_penalty = any(
        a["audit_status"] == "CLOSED_WITH_PENALTY"
        and store.agreements[a["agreement_id"]]["licensee_id"] == licensee_id
        for a in store.audits.values()
    )
    uplift_bp = 5000 if prior_penalty else 0
    penalty = raw + (raw * uplift_bp) // 10000
    return max(penalty, 100000)


# ---------------------------------------------------------------------------
# Calculation: index_rebalance (PRD §3.10)
# ---------------------------------------------------------------------------

def index_rebalance(index):
    rows = [c for c in store.constituents.values() if c["index_id"] == index["id"]]
    rows.sort(key=lambda c: (-c["target_weight_bp"], store.funds[c["fund_id"]]["ticker"]))
    cap = index["single_constituent_cap_bp"]
    excess = 0
    for c in rows:
        final = min(c["target_weight_bp"], cap)
        excess += c["target_weight_bp"] - final
        c["final_weight_bp"] = final
    while excess > 0:
        added = 0
        for c in rows:
            if excess <= 0:
                break
            d = min(excess, cap - c["final_weight_bp"])
            if d > 0:
                c["final_weight_bp"] += d
                excess -= d
                added += d
        if added == 0:
            break
    return rows


# ---------------------------------------------------------------------------
# Calculation: data_quality_score (PRD §3.7)
# ---------------------------------------------------------------------------

def quality_score_bp(company):
    import datetime as _dt

    clock = store.clock_datetime()
    window_start = clock - _dt.timedelta(days=365)
    accepted = 0
    for d in store.disputes.values():
        if d["dispute_status"] != "RESOLVED_ACCEPTED":
            continue
        fund = store.funds.get(d["fund_id"])
        if fund is None or fund["fund_company_id"] != company["id"]:
            continue
        resolved_at = _parse_iso(d.get("_resolved_at_logical", d["updated_at"]))
        if window_start <= resolved_at <= clock:
            accepted += 1
    score = 10000 - 1500 * accepted - 500 * company["open_dispute_count"]
    return max(score, 0)


# ---------------------------------------------------------------------------
# Conflict helpers (PRD §2.7)
# ---------------------------------------------------------------------------

def create_commercial_conflict_flag_if_needed(fund):
    company = store.fund_companies.get(fund["fund_company_id"])
    if company is not None and company["commercial_relationship"] != "NONE":
        flag = stamp_new({"id": new_id()})
        flag.update(
            {
                "fund_id": fund["id"],
                "flag_kind": "COMMERCIAL_RATING_CONFLICT",
                "flag_status": "OPEN",
                "blocking": True,
            }
        )
        store.conflict_flags[flag["id"]] = flag


def has_open_commercial_conflict(fund_id):
    return any(
        f["fund_id"] == fund_id
        and f["flag_kind"] == "COMMERCIAL_RATING_CONFLICT"
        and f["flag_status"] == "OPEN"
        for f in store.conflict_flags.values()
    )


# ---------------------------------------------------------------------------
# Rating cascades
# ---------------------------------------------------------------------------

def restate_rating(rating):
    """PUBLISHED -> RESTATED with a successor created (PRD §3.4 / §3.7).
    Returns the successor rating."""
    rating["rating_status"] = "RESTATED"
    touch(rating)
    methodology = store.methodologies.get(rating["methodology_id"])
    fund = store.funds.get(rating["fund_id"])
    succ = stamp_new({"id": new_id()})
    succ.update(
        {
            "fund_id": rating["fund_id"],
            "methodology_id": rating["methodology_id"],
            "rating_kind": rating["rating_kind"],
            "rating_status": (
                "PROVISIONAL" if rating["rating_kind"] == "QUANTITATIVE" else "COMMITTEE_REVIEW"
            ),
            "restatement_of_id": rating["id"],
            "suppression_reason": "NONE",
            "as_of_date": store.clock_date_str(),
        }
    )
    if rating["rating_kind"] == "QUANTITATIVE" and methodology is not None and fund is not None:
        stars, prov = compute_star_variants(fund, methodology)
        succ["stars"] = stars
        succ["provisional_stars"] = prov
        succ["analyst_grade"] = None
    else:
        succ["stars"] = None
        succ["provisional_stars"] = None
        succ["analyst_grade"] = None
    store.ratings[succ["id"]] = succ
    return succ


def withdraw_rating(rating):
    rating["rating_status"] = "WITHDRAWN"
    touch(rating)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def company_view(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "company_status": c["company_status"],
        "commercial_relationship": c["commercial_relationship"],
        "open_dispute_count": c["open_dispute_count"],
        "quality_score_bp": quality_score_bp(c),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def fund_view(f):
    return {
        "id": f["id"],
        "fund_company_id": f["fund_company_id"],
        "ticker": f["ticker"],
        "inception_date": f["inception_date"],
        "fund_status": f["fund_status"],
        "category_id": f["category_id"],
        "category_assignment_revision": f["category_assignment_revision"],
        "trailing_return_3y_bp": f["trailing_return_3y_bp"],
        "trailing_return_5y_bp": f["trailing_return_5y_bp"],
        "risk_score_bp": f["risk_score_bp"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def holding_view(h):
    return {
        "id": h["id"],
        "fund_id": h["fund_id"],
        "as_of_date": h["as_of_date"],
        "security_ticker": h["security_ticker"],
        "asset_class": h["asset_class"],
        "sector": h["sector"],
        "weight_bp": h["weight_bp"],
        "created_at": h["created_at"],
    }


def category_view(c):
    return {
        "id": c["id"],
        "category_code": c["category_code"],
        "dominant_asset_class": c["dominant_asset_class"],
        "dominant_sector": c["dominant_sector"],
        "min_weight_bp": c["min_weight_bp"],
        "active": c["active"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def methodology_view(m):
    return {
        "id": m["id"],
        "methodology_code": m["methodology_code"],
        "methodology_kind": m["methodology_kind"],
        "version_number": m["version_number"],
        "effective_from": m["effective_from"],
        "effective_to": m["effective_to"],
        "methodology_status": m["methodology_status"],
        "weight_return_bp": m["weight_return_bp"],
        "weight_risk_bp": m["weight_risk_bp"],
        "rating_ceilings": list(m["rating_ceilings"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def change_view(c):
    return {
        "id": c["id"],
        "methodology_id": c["methodology_id"],
        "change_status": c["change_status"],
        "restatement_required": c["restatement_required"],
        "effective_date": c["effective_date"],
        "client_notice_sent": c["client_notice_sent"],
        "restated_rating_count": c["restated_rating_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def rating_view(r):
    return {
        "id": r["id"],
        "fund_id": r["fund_id"],
        "methodology_id": r["methodology_id"],
        "rating_kind": r["rating_kind"],
        "stars": r["stars"],
        "analyst_grade": r["analyst_grade"],
        "rating_status": r["rating_status"],
        "as_of_date": r["as_of_date"],
        "provisional_stars": r["provisional_stars"],
        "restatement_of_id": r["restatement_of_id"],
        "suppression_reason": r["suppression_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def proposal_view(p):
    return {
        "id": p["id"],
        "rating_id": p["rating_id"],
        "proposed_grade": p["proposed_grade"],
        "proposed_by": p["proposed_by"],
        "proposal_status": p["proposal_status"],
        "approvals": p["approvals"],
        "rejections": p["rejections"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def vote_view(v):
    return {
        "id": v["id"],
        "proposal_id": v["proposal_id"],
        "voter_id": v["voter_id"],
        "vote": v["vote"],
        "created_at": v["created_at"],
    }


def licensee_view(l):
    return {
        "id": l["id"],
        "licensee_name": l["licensee_name"],
        "licensee_status": l["licensee_status"],
        "arrears_cents": l["arrears_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def agreement_view(a):
    return {
        "id": a["id"],
        "licensee_id": a["licensee_id"],
        "tier": a["tier"],
        "seat_limit": a["seat_limit"],
        "seats_in_use": a["seats_in_use"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "agreement_status": a["agreement_status"],
        "base_fee_cents": a["base_fee_cents"],
        "audit_count": a["audit_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def seat_view(s):
    return {
        "id": s["id"],
        "agreement_id": s["agreement_id"],
        "workstation_user_id": s["workstation_user_id"],
        "seat_status": s["seat_status"],
        "entitled_data_scope": s["entitled_data_scope"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def audit_view(a):
    return {
        "id": a["id"],
        "agreement_id": a["agreement_id"],
        "audit_status": a["audit_status"],
        "unlicensed_uses_found": a["unlicensed_uses_found"],
        "penalty_cents": a["penalty_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def dispute_view(d):
    return {
        "id": d["id"],
        "fund_id": d["fund_id"],
        "raised_by_company_id": d["raised_by_company_id"],
        "disputed_field": d["disputed_field"],
        "corrected_value": d["corrected_value"],
        "dispute_status": d["dispute_status"],
        "resolution_note": d["resolution_note"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def index_view(i):
    return {
        "id": i["id"],
        "index_code": i["index_code"],
        "methodology_id": i["methodology_id"],
        "max_constituents": i["max_constituents"],
        "single_constituent_cap_bp": i["single_constituent_cap_bp"],
        "index_status": i["index_status"],
        "licensed_agreement_id": i["licensed_agreement_id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def constituent_view(c):
    return {
        "id": c["id"],
        "index_id": c["index_id"],
        "fund_id": c["fund_id"],
        "target_weight_bp": c["target_weight_bp"],
        "final_weight_bp": c["final_weight_bp"],
        "created_at": c["created_at"],
    }


def flag_view(f):
    return {
        "id": f["id"],
        "fund_id": f["fund_id"],
        "flag_kind": f["flag_kind"],
        "flag_status": f["flag_status"],
        "blocking": f["blocking"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def notice_view(n):
    return {
        "id": n["id"],
        "methodology_change_id": n["methodology_change_id"],
        "licensee_id": n["licensee_id"],
        "notice_channel": n["notice_channel"],
        "notice_sent_at": n["notice_sent_at"],
        "created_at": n["created_at"],
    }
