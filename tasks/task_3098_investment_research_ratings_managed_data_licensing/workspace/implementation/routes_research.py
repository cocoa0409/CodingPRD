"""Research-domain routes: fund companies, funds, holdings, categories,
methodologies, methodology changes, ratings, proposals, votes, disputes,
conflict flags, and the logical clock."""
from flask import Blueprint, request

import errors
from db import store, _parse_iso
from middleware import (
    require_roles, body, req_str, opt_str, req_int, opt_int, req_bool, req_enum,
)
from response import success_object, success_list, parse_pagination, paginate
import services as S

bp = Blueprint("research", __name__)

OPS = ("ResearchOps",)
ALL_READ = ("ResearchOps", "Analyst", "LicenseAdmin", "ComplianceOfficer", "FundCompanyRep")


def _parse_date(value, field):
    try:
        _parse_iso(value)
    except Exception:
        raise errors.validation(f"Invalid date for {field}: {value}")
    return value


def _windows_overlap(a_from, a_to, b_from, b_to):
    """[from, to) overlap; open-ended when to is None. Abutting is legal."""
    if a_to is not None and a_to <= b_from:
        return False
    if b_to is not None and b_to <= a_from:
        return False
    return True


# ===========================================================================
# Logical clock
# ===========================================================================

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ResearchOps")
    data = body()
    to_iso8601 = req_str(data, "to_iso8601")
    try:
        _parse_iso(to_iso8601)
    except Exception:
        raise errors.validation("Invalid to_iso8601")
    store.set_clock(to_iso8601)
    return success_object({"current_utc": store.clock_iso})


# ===========================================================================
# Fund companies
# ===========================================================================

@bp.post("/research/fund-companies")
def create_fund_company():
    require_roles("ResearchOps")
    data = body()
    legal_name = req_str(data, "legal_name")
    commercial = opt_str(data, "commercial_relationship", "NONE")
    if commercial not in ("NONE", "LICENSED_CLIENT", "INDEX_LICENSEE"):
        raise errors.validation("Invalid commercial_relationship")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "legal_name": legal_name,
            "company_status": "ACTIVE",
            "commercial_relationship": commercial,
            "open_dispute_count": 0,
        }
    )
    store.fund_companies[rec["id"]] = rec
    return success_object(S.company_view(rec), 201)


@bp.get("/research/fund-companies/<cid>")
def get_fund_company(cid):
    require_roles(*ALL_READ)
    company = S.get_company(cid)
    return success_object(S.company_view(company))


@bp.get("/research/fund-companies")
def list_fund_companies():
    require_roles("ResearchOps", "Analyst", "LicenseAdmin", "ComplianceOfficer")
    limit, offset = parse_pagination(request.args)
    items = sorted(store.fund_companies.values(), key=lambda c: c["created_at"])
    status = request.args.get("company_status")
    if status is not None:
        items = [c for c in items if c["company_status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([S.company_view(c) for c in page], limit, offset, total)


@bp.get("/research/fund-companies/<cid>/funds")
def list_company_funds(cid):
    require_roles(*ALL_READ)
    S.get_company(cid)
    limit, offset = parse_pagination(request.args)
    items = [f for f in store.funds.values() if f["fund_company_id"] == cid]
    items.sort(key=lambda f: f["created_at"])
    total = len(items)
    return success_list([S.fund_view(f) for f in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/fund-companies/<cid>/disputes")
def list_company_disputes(cid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer", "FundCompanyRep")
    S.get_company(cid)
    limit, offset = parse_pagination(request.args)
    fund_ids = {f["id"] for f in store.funds.values() if f["fund_company_id"] == cid}
    items = [d for d in store.disputes.values() if d["fund_id"] in fund_ids]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    return success_list([S.dispute_view(d) for d in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/fund-companies/<cid>/suspend")
def suspend_fund_company(cid):
    require_roles("ResearchOps")
    company = S.get_company(cid)
    if company["company_status"] != "ACTIVE":
        raise errors.invalid_state("FundCompany must be ACTIVE to suspend")
    company["company_status"] = "SUSPENDED"
    S.touch(company)
    # Cascade: ACTIVE funds -> SUSPENDED; their non-terminal ratings suppressed.
    for fund in store.funds.values():
        if fund["fund_company_id"] == cid and fund["fund_status"] == "ACTIVE":
            fund["fund_status"] = "SUSPENDED"
            S.touch(fund)
            for rating in store.ratings.values():
                if (
                    rating["fund_id"] == fund["id"]
                    and rating["rating_status"] in ("PROVISIONAL", "COMMITTEE_REVIEW")
                ):
                    rating["suppression_reason"] = "DISPUTE_HOLD"
                    S.touch(rating)
    return success_object(S.company_view(company))


@bp.post("/research/fund-companies/<cid>/reinstate")
def reinstate_fund_company(cid):
    require_roles("ResearchOps")
    company = S.get_company(cid)
    if company["company_status"] != "SUSPENDED":
        raise errors.invalid_state("FundCompany must be SUSPENDED to reinstate")
    if company["open_dispute_count"] != 0:
        raise errors.open_disputes_remain()
    company["company_status"] = "ACTIVE"
    S.touch(company)
    for fund in store.funds.values():
        if fund["fund_company_id"] == cid and fund["fund_status"] == "SUSPENDED":
            fund["fund_status"] = "ACTIVE"
            S.touch(fund)
    return success_object(S.company_view(company))


@bp.post("/research/fund-companies/<cid>/offboard")
def offboard_fund_company(cid):
    require_roles("ResearchOps")
    company = S.get_company(cid)
    if company["company_status"] != "ACTIVE":
        raise errors.invalid_state("FundCompany must be ACTIVE to offboard")
    for fund in store.funds.values():
        if fund["fund_company_id"] == cid and fund["fund_status"] in ("ACTIVE", "SUSPENDED"):
            raise errors.invalid_state("All funds must be LIQUIDATED before offboarding")
    if company["open_dispute_count"] != 0:
        raise errors.open_disputes_remain()
    company["company_status"] = "OFFBOARDED"
    S.touch(company)
    return success_object(S.company_view(company))


# ===========================================================================
# Funds & holdings
# ===========================================================================

@bp.post("/research/funds")
def create_fund():
    require_roles("ResearchOps")
    data = body()
    fund_company_id = data.get("fund_company_id")
    ticker = data.get("ticker")
    inception_date = data.get("inception_date")
    r3 = data.get("trailing_return_3y_bp")
    r5 = data.get("trailing_return_5y_bp")
    risk = data.get("risk_score_bp")
    for field, val in (("fund_company_id", fund_company_id), ("ticker", ticker),
                       ("inception_date", inception_date)):
        if val is None or not isinstance(val, str) or val == "":
            raise errors.validation(f"Missing or invalid required field: {field}")
    for field, val in (("trailing_return_3y_bp", r3), ("risk_score_bp", risk)):
        if val is None or isinstance(val, bool) or not isinstance(val, int):
            raise errors.validation(f"Missing or invalid required field: {field}")
    if r5 is not None and (isinstance(r5, bool) or not isinstance(r5, int)):
        raise errors.validation("trailing_return_5y_bp must be an integer or null")
    _parse_date(inception_date, "inception_date")
    # Body FK existence (priority 4).
    if fund_company_id not in store.fund_companies:
        raise errors.reference_not_found(f"FundCompany not found: {fund_company_id}")
    # Uniqueness: ticker globally unique (priority 8).
    if any(f["ticker"] == ticker for f in store.funds.values()):
        raise errors.uniqueness(f"Fund ticker already exists: {ticker}")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "fund_company_id": fund_company_id,
            "ticker": ticker,
            "inception_date": inception_date,
            "fund_status": "ACTIVE",
            "category_id": None,
            "category_assignment_revision": 0,
            "trailing_return_3y_bp": r3,
            "trailing_return_5y_bp": r5,
            "risk_score_bp": risk,
        }
    )
    store.funds[rec["id"]] = rec
    return success_object(S.fund_view(rec), 201)


@bp.get("/research/funds/<fid>")
def get_fund(fid):
    require_roles(*ALL_READ)
    return success_object(S.fund_view(S.get_fund(fid)))


@bp.get("/research/funds")
def list_funds():
    require_roles(*ALL_READ)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.funds.values(), key=lambda f: f["created_at"])
    if request.args.get("fund_company_id") is not None:
        items = [f for f in items if f["fund_company_id"] == request.args["fund_company_id"]]
    if request.args.get("fund_status") is not None:
        items = [f for f in items if f["fund_status"] == request.args["fund_status"]]
    if request.args.get("category_id") is not None:
        items = [f for f in items if f["category_id"] == request.args["category_id"]]
    total = len(items)
    return success_list([S.fund_view(f) for f in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/funds/<fid>/holdings")
def ingest_holdings(fid):
    require_roles("ResearchOps")
    fund = S.get_fund(fid)
    data = body()
    as_of_date = data.get("as_of_date")
    holdings = data.get("holdings")
    if as_of_date is None or not isinstance(as_of_date, str):
        raise errors.validation("Missing or invalid required field: as_of_date")
    _parse_date(as_of_date, "as_of_date")
    if holdings is None or not isinstance(holdings, list) or len(holdings) == 0:
        raise errors.validation("holdings must be a non-empty array")
    allowed_ac = {"EQUITY", "BOND", "CASH", "OTHER"}
    allowed_sec = {"TECH", "HEALTH", "FINANCE", "ENERGY", "CONSUMER", "INDUSTRIAL", "MIXED"}
    total_weight = 0
    for h in holdings:
        if not isinstance(h, dict):
            raise errors.validation("Each holding must be an object")
        ticker = h.get("security_ticker")
        ac = h.get("asset_class")
        sec = h.get("sector")
        w = h.get("weight_bp")
        if not isinstance(ticker, str) or ticker == "":
            raise errors.validation("security_ticker required")
        if ac not in allowed_ac:
            raise errors.validation("Invalid asset_class")
        if sec not in allowed_sec:
            raise errors.validation("Invalid sector")
        if w is None or isinstance(w, bool) or not isinstance(w, int):
            raise errors.validation("weight_bp must be an integer")
        total_weight += w
    # Snapshot integrity (priority 10).
    if total_weight != 10000:
        raise errors.snapshot_invalid("Snapshot weights must sum to exactly 10000 bp")
    if _parse_iso(as_of_date) > store.clock_datetime():
        raise errors.snapshot_invalid("as_of_date must not be in the future")
    if any(h["fund_id"] == fid and h["as_of_date"] == as_of_date for h in store.holdings.values()):
        raise errors.snapshot_invalid("Snapshot date already ingested for this fund")
    created = []
    for h in holdings:
        rec = S.ledger_new({"id": S.new_id()})
        rec.update(
            {
                "fund_id": fid,
                "as_of_date": as_of_date,
                "security_ticker": h["security_ticker"],
                "asset_class": h["asset_class"],
                "sector": h["sector"],
                "weight_bp": h["weight_bp"],
            }
        )
        store.holdings[rec["id"]] = rec
        created.append(S.holding_view(rec))
    # Best-effort category assignment (PRD §3.2).
    S.apply_category_assignment(fund)
    return success_list(created, len(created), 0, len(created), status=201)


@bp.get("/research/funds/<fid>/holdings")
def list_holdings(fid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer", "FundCompanyRep")
    S.get_fund(fid)
    limit, offset = parse_pagination(request.args)
    items = [h for h in store.holdings.values() if h["fund_id"] == fid]
    if request.args.get("as_of_date") is not None:
        items = [h for h in items if h["as_of_date"] == request.args["as_of_date"]]
    items.sort(key=lambda h: h["created_at"])
    total = len(items)
    return success_list([S.holding_view(h) for h in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/funds/<fid>/assign-category")
def assign_category(fid):
    require_roles("ResearchOps")
    fund = S.get_fund(fid)
    winner = S.assign_category(fund)
    if winner is None:
        raise errors.no_eligible_category()
    S.apply_category_assignment(fund)
    return success_object(S.fund_view(fund))


@bp.post("/research/funds/<fid>/liquidate")
def liquidate_fund(fid):
    require_roles("ResearchOps")
    fund = S.get_fund(fid)
    if fund["fund_status"] != "ACTIVE":
        raise errors.invalid_state("Fund must be ACTIVE to liquidate")
    if any(
        d["fund_id"] == fid and d["dispute_status"] in ("OPEN", "UNDER_INVESTIGATION")
        for d in store.disputes.values()
    ):
        raise errors.open_disputes_remain()
    fund["fund_status"] = "LIQUIDATED"
    S.touch(fund)
    for rating in store.ratings.values():
        if rating["fund_id"] == fid and rating["rating_status"] in (
            "PROVISIONAL", "COMMITTEE_REVIEW", "PUBLISHED"
        ):
            S.withdraw_rating(rating)
    # Strip from constituents of LIVE or DRAFT indices (row deleted).
    for cid_row in [
        c["id"]
        for c in store.constituents.values()
        if c["fund_id"] == fid
        and store.indices[c["index_id"]]["index_status"] in ("LIVE", "DRAFT")
    ]:
        del store.constituents[cid_row]
    return success_object(S.fund_view(fund))


@bp.get("/research/funds/<fid>/ratings")
def list_fund_ratings(fid):
    require_roles(*ALL_READ)
    S.get_fund(fid)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.ratings.values() if r["fund_id"] == fid]
    if request.args.get("rating_status") is not None:
        items = [r for r in items if r["rating_status"] == request.args["rating_status"]]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    return success_list([S.rating_view(r) for r in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/funds/<fid>/disputes")
def list_fund_disputes(fid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer", "FundCompanyRep")
    S.get_fund(fid)
    limit, offset = parse_pagination(request.args)
    items = [d for d in store.disputes.values() if d["fund_id"] == fid]
    if request.args.get("dispute_status") is not None:
        items = [d for d in items if d["dispute_status"] == request.args["dispute_status"]]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    return success_list([S.dispute_view(d) for d in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/funds/<fid>/conflict-flags")
def list_fund_conflict_flags(fid):
    require_roles("ResearchOps", "ComplianceOfficer")
    S.get_fund(fid)
    limit, offset = parse_pagination(request.args)
    items = [f for f in store.conflict_flags.values() if f["fund_id"] == fid]
    if request.args.get("flag_status") is not None:
        items = [f for f in items if f["flag_status"] == request.args["flag_status"]]
    items.sort(key=lambda f: f["created_at"])
    total = len(items)
    return success_list([S.flag_view(f) for f in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/funds/<fid>/disputes")
def raise_dispute(fid):
    user_id, _role = require_roles("FundCompanyRep")
    fund = S.get_fund(fid)
    data = body()
    raised_by = data.get("raised_by_company_id")
    disputed_field = data.get("disputed_field")
    corrected_value = data.get("corrected_value")
    if raised_by is None or not isinstance(raised_by, str):
        raise errors.validation("Missing or invalid required field: raised_by_company_id")
    if disputed_field is None or not isinstance(disputed_field, str):
        raise errors.validation("Missing or invalid required field: disputed_field")
    numeric_fields = ("TRAILING_RETURN_3Y", "TRAILING_RETURN_5Y", "RISK_SCORE")
    if disputed_field not in ("HOLDINGS",) + numeric_fields + ("CATEGORY",):
        raise errors.validation("Invalid disputed_field")
    if corrected_value is not None and (isinstance(corrected_value, bool) or not isinstance(corrected_value, int)):
        raise errors.validation("corrected_value must be an integer")
    # Body FK existence (priority 4).
    if raised_by not in store.fund_companies:
        raise errors.reference_not_found(f"FundCompany not found: {raised_by}")
    # Dispute-issuer / corrected-value rules (priority 13).
    if raised_by != fund["fund_company_id"] or raised_by != user_id:
        raise errors.dispute_not_issuer()
    if disputed_field in numeric_fields and corrected_value is None:
        raise errors.dispute_not_issuer("corrected_value required for a numeric disputed_field")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "fund_id": fid,
            "raised_by_company_id": raised_by,
            "disputed_field": disputed_field,
            "corrected_value": corrected_value,
            "dispute_status": "OPEN",
            "resolution_note": None,
        }
    )
    store.disputes[rec["id"]] = rec
    return success_object(S.dispute_view(rec), 201)


@bp.get("/research/funds/<fid>/constituents")
def list_fund_constituents(fid):
    require_roles("LicenseAdmin", "ResearchOps", "Analyst", "ComplianceOfficer")
    S.get_fund(fid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.constituents.values() if c["fund_id"] == fid]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    return success_list([S.constituent_view(c) for c in paginate(items, limit, offset)], limit, offset, total)


# ===========================================================================
# Categories
# ===========================================================================

@bp.post("/research/categories")
def create_category():
    require_roles("ResearchOps")
    data = body()
    category_code = req_str(data, "category_code")
    dac = req_enum(data, "dominant_asset_class", ("EQUITY", "BOND", "MIXED"))
    dsec = req_enum(
        data, "dominant_sector",
        ("TECH", "HEALTH", "FINANCE", "ENERGY", "CONSUMER", "INDUSTRIAL", "MIXED"),
    )
    min_weight = req_int(data, "min_weight_bp")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise errors.validation("active must be a boolean")
    if any(c["category_code"] == category_code for c in store.categories.values()):
        raise errors.uniqueness(f"Category code already exists: {category_code}")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "category_code": category_code,
            "dominant_asset_class": dac,
            "dominant_sector": dsec,
            "min_weight_bp": min_weight,
            "active": active,
        }
    )
    store.categories[rec["id"]] = rec
    return success_object(S.category_view(rec), 201)


@bp.get("/research/categories")
def list_categories():
    require_roles(*ALL_READ)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.categories.values(), key=lambda c: c["created_at"])
    if request.args.get("active") is not None:
        raw = request.args["active"]
        if raw not in ("true", "false"):
            raise errors.validation("active must be true or false")
        want = raw == "true"
        items = [c for c in items if c["active"] == want]
    total = len(items)
    return success_list([S.category_view(c) for c in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/categories/<cid>")
def get_category(cid):
    require_roles(*ALL_READ)
    return success_object(S.category_view(S.get_category(cid)))


# ===========================================================================
# Methodologies & changes
# ===========================================================================

@bp.post("/research/methodologies")
def create_methodology():
    require_roles("ResearchOps")
    data = body()
    code = req_str(data, "methodology_code")
    kind = req_enum(data, "methodology_kind", ("QUANTITATIVE", "ANALYST"))
    version_number = req_int(data, "version_number")
    effective_from = req_str(data, "effective_from")
    effective_to = opt_str(data, "effective_to", None)
    wr = req_int(data, "weight_return_bp")
    wk = req_int(data, "weight_risk_bp")
    ceilings = data.get("rating_ceilings")
    if not isinstance(ceilings, list) or len(ceilings) != 4:
        raise errors.validation("rating_ceilings must be an array of four integers")
    for c in ceilings:
        if isinstance(c, bool) or not isinstance(c, int):
            raise errors.validation("rating_ceilings entries must be integers")
    if not (ceilings[0] >= ceilings[1] >= ceilings[2] >= ceilings[3]):
        raise errors.validation("rating_ceilings must be descending cutoffs")
    if wr + wk != 10000:
        raise errors.validation("weight_return_bp + weight_risk_bp must equal 10000")
    _parse_date(effective_from, "effective_from")
    if effective_to is not None:
        _parse_date(effective_to, "effective_to")
    # Uniqueness: (methodology_code, version_number).
    if any(
        m["methodology_code"] == code and m["version_number"] == version_number
        for m in store.methodologies.values()
    ):
        raise errors.uniqueness("Methodology (code, version_number) already exists")
    # Window ordering: effective_to must be > effective_from when non-null.
    if effective_to is not None and effective_to <= effective_from:
        raise errors.temporal_overlap("effective_to must be later than effective_from")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "methodology_code": code,
            "methodology_kind": kind,
            "version_number": version_number,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "methodology_status": "DRAFT",
            "weight_return_bp": wr,
            "weight_risk_bp": wk,
            "rating_ceilings": list(ceilings),
        }
    )
    store.methodologies[rec["id"]] = rec
    return success_object(S.methodology_view(rec), 201)


@bp.get("/research/methodologies/<mid>")
def get_methodology(mid):
    require_roles("ResearchOps", "Analyst", "LicenseAdmin", "ComplianceOfficer")
    return success_object(S.methodology_view(S.get_methodology(mid)))


@bp.get("/research/methodologies")
def list_methodologies():
    require_roles("ResearchOps", "Analyst", "LicenseAdmin", "ComplianceOfficer")
    limit, offset = parse_pagination(request.args)
    items = sorted(store.methodologies.values(), key=lambda m: m["created_at"])
    if request.args.get("methodology_code") is not None:
        items = [m for m in items if m["methodology_code"] == request.args["methodology_code"]]
    if request.args.get("methodology_status") is not None:
        items = [m for m in items if m["methodology_status"] == request.args["methodology_status"]]
    total = len(items)
    return success_list([S.methodology_view(m) for m in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/methodologies/<mid>/changes")
def list_methodology_changes(mid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer")
    S.get_methodology(mid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.methodology_changes.values() if c["methodology_id"] == mid]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    return success_list([S.change_view(c) for c in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/methodologies/<mid>/activate")
def activate_methodology(mid):
    require_roles("ResearchOps")
    meth = S.get_methodology(mid)
    if meth["methodology_status"] != "DRAFT":
        raise errors.invalid_state("Methodology must be DRAFT to activate")
    # Temporal overlap with same-code EFFECTIVE siblings (priority 9).
    for other in store.methodologies.values():
        if (
            other["id"] != mid
            and other["methodology_code"] == meth["methodology_code"]
            and other["methodology_status"] == "EFFECTIVE"
            and _windows_overlap(
                meth["effective_from"], meth["effective_to"],
                other["effective_from"], other["effective_to"],
            )
        ):
            raise errors.temporal_overlap("Overlapping EFFECTIVE window for the same methodology_code")
    # Supersede same-code EFFECTIVE incumbents whose windows abut/are covered.
    for other in store.methodologies.values():
        if (
            other["id"] != mid
            and other["methodology_code"] == meth["methodology_code"]
            and other["methodology_status"] == "EFFECTIVE"
            and meth["effective_from"] >= other["effective_from"]
            and (other["effective_to"] is None or meth["effective_from"] <= other["effective_to"])
        ):
            other["methodology_status"] = "SUPERSEDED"
            other["effective_to"] = meth["effective_from"]
            S.touch(other)
    meth["methodology_status"] = "EFFECTIVE"
    S.touch(meth)
    return success_object(S.methodology_view(meth))


@bp.post("/research/methodologies/<mid>/retire")
def retire_methodology(mid):
    require_roles("ResearchOps")
    meth = S.get_methodology(mid)
    if meth["methodology_status"] not in ("DRAFT", "EFFECTIVE"):
        raise errors.invalid_state("Methodology must be DRAFT or EFFECTIVE to retire")
    if meth["methodology_status"] == "EFFECTIVE":
        if any(
            i["methodology_id"] == mid and i["index_status"] == "LIVE"
            for i in store.indices.values()
        ):
            raise errors.invalid_state("An EFFECTIVE methodology referenced by a LIVE index cannot be retired")
    meth["methodology_status"] = "RETIRED"
    S.touch(meth)
    return success_object(S.methodology_view(meth))


@bp.post("/research/methodologies/<mid>/changes")
def propose_methodology_change(mid):
    require_roles("ResearchOps")
    meth = S.get_methodology(mid)
    data = body()
    restatement_required = req_bool(data, "restatement_required")
    effective_date = req_str(data, "effective_date")
    expected_version = req_int(data, "expected_methodology_version")
    _parse_date(effective_date, "effective_date")
    if expected_version != meth["version"]:
        raise errors.stale_version("expected_methodology_version does not match the methodology's current version")
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "methodology_id": mid,
            "change_status": "PROPOSED",
            "restatement_required": restatement_required,
            "effective_date": effective_date,
            "client_notice_sent": False,
            "restated_rating_count": None,
        }
    )
    store.methodology_changes[rec["id"]] = rec
    # Proposing a change advances the methodology's version (side effect).
    S.touch(meth)
    return success_object(S.change_view(rec), 201)


@bp.get("/research/methodology-changes/<cid>")
def get_methodology_change(cid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer")
    return success_object(S.change_view(S.get_change(cid)))


@bp.get("/research/methodology-changes/<cid>/notices")
def list_change_notices(cid):
    require_roles("ResearchOps", "ComplianceOfficer")
    S.get_change(cid)
    limit, offset = parse_pagination(request.args)
    items = [n for n in store.client_notices.values() if n["methodology_change_id"] == cid]
    items.sort(key=lambda n: n["created_at"])
    total = len(items)
    return success_list([S.notice_view(n) for n in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/methodology-changes/<cid>/approve")
def approve_change(cid):
    require_roles("ResearchOps")
    change = S.get_change(cid)
    if change["change_status"] != "PROPOSED":
        raise errors.invalid_state("MethodologyChange must be PROPOSED to approve")
    meth = store.methodologies.get(change["methodology_id"])
    if meth is None or meth["methodology_status"] != "EFFECTIVE":
        raise errors.invalid_state("The underlying methodology must be EFFECTIVE to approve a change")
    if change["effective_date"] < store.clock_date_str():
        raise errors.future_effective_date("effective_date is before the current logical-clock date")
    change["change_status"] = "APPROVED"
    S.touch(change)
    return success_object(S.change_view(change))


@bp.post("/research/methodology-changes/<cid>/notices")
def record_notice(cid):
    require_roles("ResearchOps")
    change = S.get_change(cid)
    data = body()
    licensee_id = data.get("licensee_id")
    notice_channel = data.get("notice_channel")
    if licensee_id is None or not isinstance(licensee_id, str):
        raise errors.validation("Missing or invalid required field: licensee_id")
    if notice_channel not in ("EMAIL", "PORTAL", "API"):
        raise errors.validation("Invalid notice_channel")
    if licensee_id not in store.licensees:
        raise errors.reference_not_found(f"Licensee not found: {licensee_id}")
    rec = S.ledger_new({"id": S.new_id()})
    rec.update(
        {
            "methodology_change_id": cid,
            "licensee_id": licensee_id,
            "notice_channel": notice_channel,
            "notice_sent_at": store.clock_iso,
        }
    )
    store.client_notices[rec["id"]] = rec
    if not change["client_notice_sent"]:
        change["client_notice_sent"] = True
        S.touch(change)
    return success_object(S.notice_view(rec), 201)


@bp.post("/research/methodology-changes/<cid>/effectuate")
def effectuate_change(cid):
    require_roles("ResearchOps")
    change = S.get_change(cid)
    if change["change_status"] != "APPROVED" or not change["client_notice_sent"]:
        raise errors.invalid_state("MethodologyChange must be APPROVED with client notice recorded to effectuate")
    if store.clock_date_str() < change["effective_date"]:
        raise errors.future_effective_date("Logical clock has not reached the effective_date")
    change["change_status"] = "EFFECTIVE"
    if change["restatement_required"]:
        targets = [
            r for r in store.ratings.values()
            if r["methodology_id"] == change["methodology_id"] and r["rating_status"] == "PUBLISHED"
        ]
        for rating in targets:
            S.restate_rating(rating)
        change["restated_rating_count"] = len(targets)
    else:
        change["restated_rating_count"] = 0
    S.touch(change)
    return success_object(S.change_view(change))


@bp.post("/research/methodology-changes/<cid>/withdraw")
def withdraw_change(cid):
    require_roles("ResearchOps")
    change = S.get_change(cid)
    if change["change_status"] not in ("PROPOSED", "APPROVED"):
        raise errors.invalid_state("MethodologyChange must be PROPOSED or APPROVED to withdraw")
    change["change_status"] = "WITHDRAWN"
    S.touch(change)
    return success_object(S.change_view(change))


# ===========================================================================
# Ratings & committee
# ===========================================================================

@bp.post("/research/ratings/compute")
def compute_rating():
    require_roles("ResearchOps")
    data = body()
    fund_id = data.get("fund_id")
    methodology_id = data.get("methodology_id")
    if fund_id is None or not isinstance(fund_id, str):
        raise errors.validation("Missing or invalid required field: fund_id")
    if methodology_id is None or not isinstance(methodology_id, str):
        raise errors.validation("Missing or invalid required field: methodology_id")
    if fund_id not in store.funds:
        raise errors.reference_not_found(f"Fund not found: {fund_id}")
    if methodology_id not in store.methodologies:
        raise errors.reference_not_found(f"Methodology not found: {methodology_id}")
    fund = store.funds[fund_id]
    meth = store.methodologies[methodology_id]
    if meth["methodology_status"] != "EFFECTIVE":
        raise errors.methodology_not_effective()
    if fund["fund_status"] != "ACTIVE":
        raise errors.invalid_state("Fund must be ACTIVE to compute a rating")
    if not S.latest_snapshot_rows(fund_id):
        raise errors.invalid_state("Fund must have at least one ingested holdings snapshot")
    stars, prov = S.compute_star_variants(fund, meth)
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "fund_id": fund_id,
            "methodology_id": methodology_id,
            "rating_kind": "QUANTITATIVE",
            "stars": stars,
            "analyst_grade": None,
            "rating_status": "PROVISIONAL",
            "as_of_date": store.clock_date_str(),
            "provisional_stars": prov,
            "restatement_of_id": None,
            "suppression_reason": "NONE",
        }
    )
    store.ratings[rec["id"]] = rec
    S.create_commercial_conflict_flag_if_needed(fund)
    return success_object(S.rating_view(rec), 201)


@bp.post("/research/ratings")
def initiate_analyst_rating():
    require_roles("Analyst")
    data = body()
    fund_id = data.get("fund_id")
    methodology_id = data.get("methodology_id")
    if fund_id is None or not isinstance(fund_id, str):
        raise errors.validation("Missing or invalid required field: fund_id")
    if methodology_id is None or not isinstance(methodology_id, str):
        raise errors.validation("Missing or invalid required field: methodology_id")
    if fund_id not in store.funds:
        raise errors.reference_not_found(f"Fund not found: {fund_id}")
    if methodology_id not in store.methodologies:
        raise errors.reference_not_found(f"Methodology not found: {methodology_id}")
    meth = store.methodologies[methodology_id]
    if meth["methodology_kind"] != "ANALYST":
        raise errors.rating_kind_mismatch("Methodology must be of kind ANALYST to initiate an analyst rating")
    if meth["methodology_status"] != "EFFECTIVE":
        raise errors.methodology_not_effective()
    fund = store.funds[fund_id]
    rec = S.stamp_new({"id": S.new_id()})
    rec.update(
        {
            "fund_id": fund_id,
            "methodology_id": methodology_id,
            "rating_kind": "ANALYST",
            "stars": None,
            "analyst_grade": None,
            "rating_status": "PROVISIONAL",
            "as_of_date": store.clock_date_str(),
            "provisional_stars": None,
            "restatement_of_id": None,
            "suppression_reason": "NONE",
        }
    )
    store.ratings[rec["id"]] = rec
    S.create_commercial_conflict_flag_if_needed(fund)
    return success_object(S.rating_view(rec), 201)


@bp.get("/research/ratings/<rid>")
def get_rating(rid):
    require_roles(*ALL_READ)
    return success_object(S.rating_view(S.get_rating(rid)))


@bp.get("/research/ratings")
def list_ratings():
    require_roles(*ALL_READ)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.ratings.values(), key=lambda r: r["created_at"])
    if request.args.get("fund_id") is not None:
        items = [r for r in items if r["fund_id"] == request.args["fund_id"]]
    if request.args.get("methodology_id") is not None:
        items = [r for r in items if r["methodology_id"] == request.args["methodology_id"]]
    if request.args.get("rating_status") is not None:
        items = [r for r in items if r["rating_status"] == request.args["rating_status"]]
    if request.args.get("restatement_of_id") is not None:
        items = [r for r in items if r["restatement_of_id"] == request.args["restatement_of_id"]]
    total = len(items)
    return success_list([S.rating_view(r) for r in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/ratings/<rid>/publish")
def publish_rating(rid):
    require_roles("ResearchOps")
    rating = S.get_rating(rid)
    # State legality first (priority 5), then the conflict gate (priority 6).
    if rating["rating_status"] != "PROVISIONAL":
        raise errors.invalid_state("Rating must be PROVISIONAL to publish")
    if rating["rating_kind"] != "QUANTITATIVE":
        raise errors.rating_kind_mismatch("Only quantitative ratings are published directly")
    meth = store.methodologies.get(rating["methodology_id"])
    if meth is None or meth["methodology_status"] != "EFFECTIVE":
        raise errors.methodology_not_effective()
    if rating["suppression_reason"] != "NONE":
        raise errors.suppressed_rating()
    fund = store.funds.get(rating["fund_id"])
    if fund is None or fund["fund_status"] != "ACTIVE":
        raise errors.invalid_state("Fund must be ACTIVE to publish a rating")
    if S.has_open_commercial_conflict(rating["fund_id"]):
        raise errors.conflict_of_interest()
    # Supersede any prior PUBLISHED quantitative rating for the same fund.
    for other in store.ratings.values():
        if (
            other["id"] != rid
            and other["fund_id"] == rating["fund_id"]
            and other["rating_kind"] == rating["rating_kind"]
            and other["rating_status"] == "PUBLISHED"
        ):
            other["rating_status"] = "SUPERSEDED"
            S.touch(other)
    rating["rating_status"] = "PUBLISHED"
    S.touch(rating)
    return success_object(S.rating_view(rating))


@bp.post("/research/ratings/<rid>/withdraw")
def withdraw_rating(rid):
    require_roles("ResearchOps")
    rating = S.get_rating(rid)
    if rating["rating_status"] in ("WITHDRAWN", "SUPERSEDED"):
        raise errors.invalid_state("Rating is already in a terminal state")
    S.withdraw_rating(rating)
    return success_object(S.rating_view(rating))


@bp.post("/research/ratings/<rid>/proposals")
def open_proposal(rid):
    user_id, _role = require_roles("Analyst")
    rating = S.get_rating(rid)
    data = body()
    proposed_grade = req_enum(
        data, "proposed_grade", ("GOLD", "SILVER", "BRONZE", "NEUTRAL", "NEGATIVE")
    )
    # State legality (priority 5), then conflict gate (priority 6).
    if rating["rating_status"] != "PROVISIONAL":
        raise errors.invalid_state("Rating must be PROVISIONAL to open a proposal")
    if rating["rating_kind"] != "ANALYST":
        raise errors.rating_kind_mismatch("Proposals may only be opened on analyst ratings")
    fund = store.funds.get(rating["fund_id"])
    if fund is None or fund["fund_status"] != "ACTIVE":
        raise errors.invalid_state("Fund must be ACTIVE to open a proposal")
    if S.has_open_commercial_conflict(rating["fund_id"]):
        raise errors.conflict_of_interest()
    proposal = S.stamp_new({"id": S.new_id()})
    proposal.update(
        {
            "rating_id": rid,
            "proposed_grade": proposed_grade,
            "proposed_by": user_id,
            "proposal_status": "OPEN",
            "approvals": 0,
            "rejections": 0,
        }
    )
    store.proposals[proposal["id"]] = proposal
    rating["rating_status"] = "COMMITTEE_REVIEW"
    S.touch(rating)
    return success_object(S.proposal_view(proposal), 201)


@bp.get("/research/proposals")
def list_proposals():
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer")
    limit, offset = parse_pagination(request.args)
    items = sorted(store.proposals.values(), key=lambda p: p["created_at"])
    if request.args.get("rating_id") is not None:
        items = [p for p in items if p["rating_id"] == request.args["rating_id"]]
    if request.args.get("proposal_status") is not None:
        items = [p for p in items if p["proposal_status"] == request.args["proposal_status"]]
    total = len(items)
    return success_list([S.proposal_view(p) for p in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/research/proposals/<pid>")
def get_proposal(pid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer")
    return success_object(S.proposal_view(S.get_proposal(pid)))


@bp.get("/research/proposals/<pid>/votes")
def list_votes(pid):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer")
    S.get_proposal(pid)
    limit, offset = parse_pagination(request.args)
    items = [v for v in store.votes.values() if v["proposal_id"] == pid]
    items.sort(key=lambda v: v["created_at"])
    total = len(items)
    return success_list([S.vote_view(v) for v in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/research/proposals/<pid>/votes")
def cast_vote(pid):
    user_id, _role = require_roles("Analyst")
    proposal = S.get_proposal(pid)
    data = body()
    vote = req_enum(data, "vote", ("APPROVE", "REJECT", "ABSTAIN"))
    if proposal["proposal_status"] not in ("OPEN", "QUORUM_MET"):
        raise errors.invalid_state("Votes may only be cast on an OPEN or QUORUM_MET proposal")
    # SoD: proposer cannot vote; one vote per voter (priority 7).
    if proposal["proposed_by"] == user_id:
        raise errors.sod_violation("The proposer may not vote on their own proposal")
    if any(v["proposal_id"] == pid and v["voter_id"] == user_id for v in store.votes.values()):
        raise errors.sod_violation("A voter may not vote twice on the same proposal")
    rec = S.ledger_new({"id": S.new_id()})
    rec.update({"proposal_id": pid, "voter_id": user_id, "vote": vote})
    store.votes[rec["id"]] = rec
    # Recompute counters.
    votes = [v for v in store.votes.values() if v["proposal_id"] == pid]
    approvals = sum(1 for v in votes if v["vote"] == "APPROVE")
    rejections = sum(1 for v in votes if v["vote"] == "REJECT")
    total_votes = len(votes)
    proposal["approvals"] = approvals
    proposal["rejections"] = rejections
    # Auto-transitions (PRD §3.6).
    rating = store.ratings.get(proposal["rating_id"])
    if approvals >= 2 and total_votes >= 3 and approvals > rejections:
        proposal["proposal_status"] = "APPROVED"
        if (
            rating is not None
            and rating["rating_status"] == "COMMITTEE_REVIEW"
            and rating["suppression_reason"] == "NONE"
            and not S.has_open_commercial_conflict(rating["fund_id"])
        ):
            rating["analyst_grade"] = proposal["proposed_grade"]
            for other in store.ratings.values():
                if (
                    other["id"] != rating["id"]
                    and other["fund_id"] == rating["fund_id"]
                    and other["rating_kind"] == "ANALYST"
                    and other["rating_status"] == "PUBLISHED"
                ):
                    other["rating_status"] = "SUPERSEDED"
                    S.touch(other)
            rating["rating_status"] = "PUBLISHED"
            S.touch(rating)
    elif rejections >= 2 and total_votes >= 3 and rejections >= approvals:
        proposal["proposal_status"] = "REJECTED"
        if rating is not None and rating["rating_status"] == "COMMITTEE_REVIEW":
            rating["rating_status"] = "PROVISIONAL"
            S.touch(rating)
    elif total_votes >= 3 and proposal["proposal_status"] == "OPEN":
        proposal["proposal_status"] = "QUORUM_MET"
    S.touch(proposal)
    return success_object(S.vote_view(rec), 201)


@bp.post("/research/proposals/<pid>/withdraw")
def withdraw_proposal(pid):
    user_id, _role = require_roles("Analyst")
    proposal = S.get_proposal(pid)
    if proposal["proposal_status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN proposal may be withdrawn")
    if proposal["proposed_by"] != user_id:
        raise errors.forbidden("Only the proposing analyst may withdraw this proposal")
    proposal["proposal_status"] = "WITHDRAWN"
    S.touch(proposal)
    rating = store.ratings.get(proposal["rating_id"])
    if rating is not None and rating["rating_status"] == "COMMITTEE_REVIEW":
        rating["rating_status"] = "PROVISIONAL"
        S.touch(rating)
    return success_object(S.proposal_view(proposal))


# ===========================================================================
# Conflict flags
# ===========================================================================

@bp.post("/research/conflict-flags/<fid>/waive")
def waive_conflict_flag(fid):
    require_roles("ComplianceOfficer")
    flag = S.get_flag(fid)
    if flag["flag_status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN conflict flag may be waived")
    flag["flag_status"] = "WAIVED"
    flag["blocking"] = False
    S.touch(flag)
    return success_object(S.flag_view(flag))


@bp.get("/research/conflict-flags/<fid>")
def get_conflict_flag(fid):
    require_roles("ResearchOps", "ComplianceOfficer")
    return success_object(S.flag_view(S.get_flag(fid)))


# ===========================================================================
# Data disputes (operator side)
# ===========================================================================

@bp.get("/research/data-disputes/<did>")
def get_dispute(did):
    require_roles("ResearchOps", "Analyst", "ComplianceOfficer", "FundCompanyRep")
    return success_object(S.dispute_view(S.get_dispute(did)))


@bp.post("/research/data-disputes/<did>/investigate")
def investigate_dispute(did):
    require_roles("ResearchOps")
    dispute = S.get_dispute(did)
    if dispute["dispute_status"] != "OPEN":
        raise errors.invalid_state("Dispute must be OPEN to investigate")
    dispute["dispute_status"] = "UNDER_INVESTIGATION"
    S.touch(dispute)
    company = store.fund_companies.get(dispute["raised_by_company_id"])
    if company is not None:
        company["open_dispute_count"] += 1
        S.touch(company)
    fund = store.funds.get(dispute["fund_id"])
    if fund is not None:
        for rating in store.ratings.values():
            if rating["fund_id"] == fund["id"] and rating["rating_status"] in (
                "PROVISIONAL", "COMMITTEE_REVIEW"
            ):
                rating["suppression_reason"] = "DISPUTE_HOLD"
                S.touch(rating)
    return success_object(S.dispute_view(dispute))


@bp.post("/research/data-disputes/<did>/resolve")
def resolve_dispute(did):
    require_roles("ResearchOps")
    dispute = S.get_dispute(did)
    data = body()
    outcome = data.get("outcome")
    if outcome is not None and outcome not in ("ACCEPTED", "REJECTED"):
        raise errors.validation("Invalid outcome")
    resolution_note = data.get("resolution_note")
    if resolution_note is None or not isinstance(resolution_note, str):
        raise errors.validation("Missing or invalid required field: resolution_note")
    expected_version = data.get("expected_dispute_version")
    if expected_version is None or isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.validation("Missing or invalid required field: expected_dispute_version")
    if outcome is None:
        raise errors.validation("Missing or invalid required field: outcome")
    if dispute["dispute_status"] != "UNDER_INVESTIGATION":
        raise errors.invalid_state("Dispute must be UNDER_INVESTIGATION to resolve")
    if expected_version != dispute["version"]:
        raise errors.stale_version("expected_dispute_version does not match the dispute's current version")

    fund = store.funds.get(dispute["fund_id"])
    company = store.fund_companies.get(dispute["raised_by_company_id"])

    if outcome == "ACCEPTED":
        dispute["dispute_status"] = "RESOLVED_ACCEPTED"
    else:
        dispute["dispute_status"] = "RESOLVED_REJECTED"
    dispute["resolution_note"] = resolution_note
    # Logical-clock resolution time drives the trailing-365-day quality window
    # (PRD §2.10: date-dependent rules never use wall-clock time).
    dispute["_resolved_at_logical"] = store.clock_iso
    S.touch(dispute)

    if company is not None:
        company["open_dispute_count"] -= 1
        S.touch(company)

    if outcome == "ACCEPTED" and fund is not None:
        numeric_field_map = {
            "TRAILING_RETURN_3Y": "trailing_return_3y_bp",
            "TRAILING_RETURN_5Y": "trailing_return_5y_bp",
            "RISK_SCORE": "risk_score_bp",
        }
        if dispute["disputed_field"] in numeric_field_map:
            fund[numeric_field_map[dispute["disputed_field"]]] = dispute["corrected_value"]
            S.touch(fund)
            # Restate every PUBLISHED rating on the fund.
            for rating in list(store.ratings.values()):
                if rating["fund_id"] == fund["id"] and rating["rating_status"] == "PUBLISHED":
                    S.restate_rating(rating)
        elif dispute["disputed_field"] == "CATEGORY":
            S.apply_category_assignment(fund)

    # Clear DISPUTE_HOLD unless another open/investigation dispute remains.
    if fund is not None:
        remaining = any(
            d["fund_id"] == fund["id"]
            and d["dispute_status"] in ("OPEN", "UNDER_INVESTIGATION")
            for d in store.disputes.values()
        )
        if not remaining:
            for rating in store.ratings.values():
                if (
                    rating["fund_id"] == fund["id"]
                    and rating["suppression_reason"] == "DISPUTE_HOLD"
                ):
                    rating["suppression_reason"] = "NONE"
                    S.touch(rating)
    return success_object(S.dispute_view(dispute))
