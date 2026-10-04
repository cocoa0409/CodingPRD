"""QC audits, findings, and repurchase demands."""
from flask import Blueprint

from core import (
    ApiError, db, dump, endpoint, f_enum, f_str, body, new_row, now,
    paginate, q_enum, q_str, respond_object, sort_created, touch,
)
from svc import (
    MISREP_CATEGORIES, appeal_deadline_from, recompute_oversight_score,
)

bp = Blueprint("qc", __name__)

ALL_ROLES = ("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")
SAMPLING_METHODS = ("RANDOM", "TARGETED", "DISCRETIONARY")
DEFECT_CATEGORIES = ("INCOME_MISREP", "ASSET_MISREP", "EMPLOYMENT_MISREP", "COLLATERAL", "ELIGIBILITY", "OTHER")
SEVERITIES = ("SIGNIFICANT", "MODERATE", "MINOR")
AUDIT_STATUSES = ("OPEN", "IN_REVIEW", "FINDINGS_ISSUED", "CLOSED")
FINDING_STATUSES = ("IDENTIFIED", "REPURCHASE_ISSUED", "APPEALED", "UPHELD", "OVERTURNED", "REMEDIATED")
DEMAND_STATUSES = ("ISSUED", "APPEALED", "UPHELD", "WITHDRAWN", "SETTLED")

# A finding is terminal for audit-close purposes when it is OVERTURNED or
# REMEDIATED, or UPHELD with its demand settled or withdrawn (PRD 3.9).
def _finding_terminal_for_close(finding):
    if finding["status"] in ("OVERTURNED", "REMEDIATED"):
        return True
    if finding["status"] == "UPHELD":
        for demand in db.demands.values():
            if demand["finding_id"] == finding["id"]:
                return demand["status"] in ("SETTLED", "WITHDRAWN")
    return False


# ---------------------------------------------------------------------------
# QC audits
# ---------------------------------------------------------------------------
@bp.post("/gse/qc-audits")
@endpoint("QcAuditor")
def create_audit():
    payload = body()
    seller_id = f_str(payload, "seller_id")
    sampling_method = f_enum(payload, "sampling_method", SAMPLING_METHODS)
    if seller_id not in db.sellers:
        raise ApiError("ERR_NOT_FOUND", "Seller not found.")
    audit = new_row(
        "audit",
        seller_id=seller_id,
        sampling_method=sampling_method,
        status="OPEN",
    )
    db.audits[audit["id"]] = audit
    return respond_object(dump(audit), 201)


def get_audit_or_404(audit_id):
    audit = db.audits.get(audit_id)
    if audit is None:
        raise ApiError("ERR_NOT_FOUND", "QC audit not found.")
    return audit


@bp.get("/gse/qc-audits/<audit_id>")
@endpoint(*ALL_ROLES)
def get_audit(audit_id):
    return respond_object(dump(get_audit_or_404(audit_id)), 200)


@bp.get("/gse/qc-audits")
@endpoint(*ALL_ROLES)
def list_audits():
    rows = list(db.audits.values())
    seller_id = q_str("seller_id")
    status = q_enum("status", AUDIT_STATUSES)
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.post("/gse/qc-audits/<audit_id>/findings")
@endpoint("QcAuditor")
def add_finding(audit_id):
    audit = get_audit_or_404(audit_id)
    payload = body()
    loan_id = f_str(payload, "loan_id")
    defect_category = f_enum(payload, "defect_category", DEFECT_CATEGORIES)
    severity = f_enum(payload, "severity", SEVERITIES)
    loan = db.loans.get(loan_id)
    if loan is None:
        raise ApiError("ERR_NOT_FOUND", "Loan not found.")
    if audit["status"] not in ("OPEN", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", "Findings cannot be added to an audit in status %s." % audit["status"])
    if loan["status"] != "PURCHASED" or loan["seller_id"] != audit["seller_id"]:
        raise ApiError("ERR_LOAN_NOT_PURCHASED", "Finding loan must be PURCHASED and belong to the audit's seller.")
    finding = new_row(
        "finding",
        audit_id=audit["id"],
        loan_id=loan_id,
        defect_category=defect_category,
        severity=severity,
        status="IDENTIFIED",
    )
    db.findings[finding["id"]] = finding
    if audit["status"] == "OPEN":
        audit["status"] = "IN_REVIEW"
        touch(audit)
    servicer = db.servicers.get(loan["servicer_id"])
    if servicer is not None:
        recompute_oversight_score(servicer)
    return respond_object(dump(finding), 201)


@bp.get("/gse/qc-findings")
@endpoint(*ALL_ROLES)
def list_findings():
    rows = list(db.findings.values())
    audit_id = q_str("audit_id")
    loan_id = q_str("loan_id")
    status = q_enum("status", FINDING_STATUSES)
    if audit_id is not None:
        rows = [r for r in rows if r["audit_id"] == audit_id]
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


def get_finding_or_404(finding_id):
    finding = db.findings.get(finding_id)
    if finding is None:
        raise ApiError("ERR_NOT_FOUND", "QC finding not found.")
    return finding


@bp.get("/gse/qc-findings/<finding_id>")
@endpoint(*ALL_ROLES)
def get_finding(finding_id):
    return respond_object(dump(get_finding_or_404(finding_id)), 200)


@bp.post("/gse/qc-audits/<audit_id>/issue-findings")
@endpoint("QcAuditor")
def issue_findings(audit_id):
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_REVIEW audit can issue findings.")
    audit["status"] = "FINDINGS_ISSUED"
    touch(audit)
    return respond_object(dump(audit), 200)


@bp.post("/gse/qc-audits/<audit_id>/close")
@endpoint("QcAuditor")
def close_audit(audit_id):
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only a FINDINGS_ISSUED audit can be closed.")
    for finding in db.findings.values():
        if finding["audit_id"] == audit["id"] and not _finding_terminal_for_close(finding):
            raise ApiError("ERR_AUDIT_HAS_OPEN_FINDINGS", "Audit has findings not in a terminal state.")
    audit["status"] = "CLOSED"
    touch(audit)
    return respond_object(dump(audit), 200)


# ---------------------------------------------------------------------------
# Repurchase demands
# ---------------------------------------------------------------------------
@bp.post("/gse/qc-findings/<finding_id>/issue-demand")
@endpoint("GseAdmin")
def issue_demand(finding_id):
    finding = get_finding_or_404(finding_id)
    if finding["status"] != "IDENTIFIED":
        raise ApiError("ERR_INVALID_STATE", "Only an IDENTIFIED finding can ground a demand.")
    audit = db.audits.get(finding["audit_id"])
    if audit is None or audit["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_NOT_ISSUED", "Findings must be issued before demands can be created.")
    loan = db.loans.get(finding["loan_id"])
    if loan is not None and finding["defect_category"] in MISREP_CATEGORIES:
        if loan.get("relief_tier") in ("INDEPENDENT_VALIDATION", "PAYMENT_HISTORY_36"):
            raise ApiError("ERR_RELIEF_TIER_BLOCKS_DEMAND", "Loan relief tier bars demands for misrepresentation defects.")
    demand = new_row(
        "demand",
        finding_id=finding["id"],
        loan_id=finding["loan_id"],
        amount_cents=int(loan["unpaid_principal_balance_cents"]) if loan is not None else 0,
        status="ISSUED",
        appeal_deadline=appeal_deadline_from(now()),
        appeal_rounds_used=0,
    )
    db.demands[demand["id"]] = demand
    finding["status"] = "REPURCHASE_ISSUED"
    touch(finding)
    if loan is not None:
        servicer = db.servicers.get(loan["servicer_id"])
        if servicer is not None:
            recompute_oversight_score(servicer)
    return respond_object(dump(demand), 201)


def get_demand_or_404(demand_id):
    demand = db.demands.get(demand_id)
    if demand is None:
        raise ApiError("ERR_NOT_FOUND", "Repurchase demand not found.")
    return demand


@bp.get("/gse/repurchase-demands/<demand_id>")
@endpoint(*ALL_ROLES)
def get_demand(demand_id):
    return respond_object(dump(get_demand_or_404(demand_id)), 200)


@bp.get("/gse/repurchase-demands")
@endpoint(*ALL_ROLES)
def list_demands():
    rows = list(db.demands.values())
    finding_id = q_str("finding_id")
    loan_id = q_str("loan_id")
    status = q_enum("status", DEMAND_STATUSES)
    if finding_id is not None:
        rows = [r for r in rows if r["finding_id"] == finding_id]
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


def _demand_finding(demand):
    return db.findings.get(demand["finding_id"])


@bp.post("/gse/repurchase-demands/<demand_id>/appeal")
@endpoint("SellerOfficer")
def appeal_demand(demand_id):
    demand = get_demand_or_404(demand_id)
    body()  # appeal_reason accepted but not persisted on the demand
    if demand["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED or UPHELD demand can be appealed.")
    # Temporal gates precede constraint gates (PRD §2.9).
    if now() > demand["appeal_deadline"]:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "Appeal attempted after the appeal deadline.")
    if int(demand["appeal_rounds_used"]) >= 2:
        raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED", "This demand has consumed its 2 appeal rounds.")
    demand["status"] = "APPEALED"
    demand["appeal_rounds_used"] = int(demand["appeal_rounds_used"]) + 1
    touch(demand)
    finding = _demand_finding(demand)
    if finding is not None:
        finding["status"] = "APPEALED"
        touch(finding)
    loan = db.loans.get(demand["loan_id"])
    if loan is not None:
        servicer = db.servicers.get(loan["servicer_id"])
        if servicer is not None:
            recompute_oversight_score(servicer)
    return respond_object(dump(demand), 200)


@bp.post("/gse/repurchase-demands/<demand_id>/resolve-appeal")
@endpoint("GseAdmin")
def resolve_appeal(demand_id):
    demand = get_demand_or_404(demand_id)
    payload = body()
    outcome = f_enum(payload, "outcome", ("UPHELD", "OVERTURNED"))
    if demand["status"] != "APPEALED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPEALED demand can be resolved.")
    finding = _demand_finding(demand)
    if outcome == "UPHELD":
        demand["status"] = "UPHELD"
        touch(demand)
        if finding is not None:
            finding["status"] = "UPHELD"
            touch(finding)
    else:
        demand["status"] = "WITHDRAWN"
        touch(demand)
        if finding is not None:
            finding["status"] = "OVERTURNED"
            touch(finding)
    loan = db.loans.get(demand["loan_id"])
    if loan is not None:
        servicer = db.servicers.get(loan["servicer_id"])
        if servicer is not None:
            recompute_oversight_score(servicer)
    return respond_object(dump(demand), 200)


@bp.post("/gse/repurchase-demands/<demand_id>/settle")
@endpoint("SellerOfficer")
def settle_demand(demand_id):
    demand = get_demand_or_404(demand_id)
    if demand["status"] != "UPHELD":
        raise ApiError("ERR_DEMAND_NOT_UPHELD", "Settle requires demand status UPHELD.")
    loan = db.loans.get(demand["loan_id"])
    seller = db.sellers.get(loan["seller_id"]) if loan is not None else None
    # Fiscal check: outstanding UPHELD demands (this one included) vs net worth.
    outstanding = 0
    for other in db.demands.values():
        if other["status"] != "UPHELD":
            continue
        other_loan = db.loans.get(other["loan_id"])
        if other_loan is not None and loan is not None and other_loan["seller_id"] == loan["seller_id"]:
            outstanding += int(other["amount_cents"])
    if seller is not None and outstanding > int(seller["net_worth_cents"]):
        raise ApiError("ERR_INSUFFICIENT_SELLER_FUNDS", "Seller net worth cannot cover outstanding UPHELD demands.")
    demand["status"] = "SETTLED"
    touch(demand)
    finding = _demand_finding(demand)
    if finding is not None:
        finding["status"] = "REMEDIATED"
        touch(finding)
    if loan is not None:
        loan["status"] = "REPURCHASED"
        touch(loan)
        servicer = db.servicers.get(loan["servicer_id"])
        if servicer is not None:
            recompute_oversight_score(servicer)
    return respond_object(dump(demand), 200)
