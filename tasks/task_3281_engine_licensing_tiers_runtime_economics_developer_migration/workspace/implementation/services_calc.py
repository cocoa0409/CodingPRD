"""Tier constants, tier determination, standing, upgrade risk, runtime fee calc."""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from helpers import current_date, months_between_period

TIER_RANK = {"PERSONAL": 1, "EDUCATION": 2, "PRO": 3, "ENTERPRISE": 4}
TIER_CODES = set(TIER_RANK.keys())

INSTALL_THRESHOLD = 1_000_000
REVENUE_THRESHOLD_CENTS = 100_000_000
RATE_LOW_CENTS = 20
RATE_HIGH_CENTS = 5
RATE_TIER_BOUNDARY = 100_000

WAIVER_CAP_PCT = Decimal("0.5")

SHARE_BOUNDARY_CENTS = 100_000_000
SHARE_LOW_PCT = Decimal("0.30")
SHARE_HIGH_PCT = Decimal("0.25")

SEAT_MONTH_CENTS = 15000


def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def active_tier_config(tier_code):
    """The ACTIVE TierConfig for a tier_code, or None."""
    for t in db.tiers.values():
        if t["tier_code"] == tier_code and t["tier_config_status"] == "ACTIVE":
            return t
    return None


def org_declarations(org_id):
    decls = [d for d in db.revenue_declarations.values() if d["org_id"] == org_id]
    decls.sort(key=lambda d: (d["period_month"], d["declared_at"]))
    return decls


def tier_determination(org):
    """Compute both variants. Returns dict of figures."""
    decls = org_declarations(org["id"])
    months = len(set(d["period_month"] for d in decls))
    recent = decls[-12:]
    ttm = sum(d["gross_revenue_cents"] for d in recent)
    if months == 0:
        actual = 0
        annualized = 0
    elif months < 12:
        actual = ttm
        annualized = round_half_up_int(Decimal(ttm) / Decimal(months) * Decimal(12))
    else:
        actual = ttm
        annualized = ttm
    lifetime_funding = sum(d["funding_received_cents"] for d in decls)
    return {
        "actual_ttm_revenue_cents": actual,
        "annualized_revenue_cents": annualized,
        "lifetime_funding_cents": lifetime_funding,
        "months_declared": months,
    }


def _signal_tier(org, effective_revenue, lifetime_funding):
    """Lowest-ranked ACTIVE tier whose ceilings admit the figures, or None when no
    ACTIVE config admits them (PRD §3.1: 'reading constants from ACTIVE tier configs
    only' — with no admitting config there is no signal tier)."""
    verified = org.get("education_verified", False)
    best = None
    for code in ("PERSONAL", "EDUCATION", "PRO", "ENTERPRISE"):
        cfg = active_tier_config(code)
        if cfg is None:
            continue
        rev_ok = cfg["revenue_ceiling_cents"] == 0 or effective_revenue <= cfg["revenue_ceiling_cents"]
        fund_ok = cfg["funding_ceiling_cents"] == 0 or lifetime_funding <= cfg["funding_ceiling_cents"]
        if rev_ok and fund_ok:
            best = code
            break
    if best is None:
        return None
    # EDUCATION requires verification; otherwise treated as PERSONAL rank
    if best == "EDUCATION" and not verified:
        best = "PERSONAL"
    return best


def effective_tier_from_variant(org, variant):
    figs = tier_determination(org)
    rev = figs["actual_ttm_revenue_cents"] if variant == "actual" else figs["annualized_revenue_cents"]
    signal = _signal_tier(org, rev, figs["lifetime_funding_cents"])
    declared = org["declared_tier_code"]
    # EDUCATION declared tier without verification treated at PERSONAL rank
    declared_rank_code = declared
    if declared == "EDUCATION" and not org.get("education_verified", False):
        declared_rank_code = "PERSONAL"
    if signal is None:
        return declared
    if TIER_RANK[signal] >= TIER_RANK[declared_rank_code]:
        return signal
    return declared


def recompute_effective_tier(org):
    """Effective tier uses the annualized projection variant (PRD §3.1: the annualized
    variant governs the self-service tier assessment). Bumps version if changed."""
    new_tier = effective_tier_from_variant(org, "annualized")
    if new_tier != org["effective_tier_code"]:
        org["effective_tier_code"] = new_tier
        from helpers import touch
        touch(org)
    return org["effective_tier_code"]


def open_audit_cases(org_id):
    return [c for c in db.audit_cases.values()
            if c["org_id"] == org_id and c["case_status"] in ("OPENED", "EVIDENCE_REQUESTED", "APPEALED")]


def overdue_invoices(org_id):
    out = []
    for inv in db.invoices.values():
        proj = db.projects.get(inv["project_id"])
        if proj and proj["org_id"] == org_id and inv["payment_status"] == "OVERDUE":
            out.append(inv)
    return out


def compute_standing(org):
    """Derived: GOOD | REVIEW | SUSPENDED."""
    if org["trust_score"] < 25:
        standing = "SUSPENDED"
    elif org["trust_score"] < 50 or open_audit_cases(org["id"]) or overdue_invoices(org["id"]):
        standing = "REVIEW"
    else:
        standing = "GOOD"
    if standing != org.get("org_standing"):
        org["org_standing"] = standing
        from helpers import touch
        touch(org)
        # Cascade: standing dropped to REVIEW/SUSPENDED -> APPROVED listings re-enter PENDING_REVIEW
        if standing in ("REVIEW", "SUSPENDED"):
            from helpers import touch as t2
            for l in db.asset_listings.values():
                if l["creator_org_id"] == org["id"] and l["listing_status"] == "APPROVED":
                    l["listing_status"] = "PENDING_REVIEW"
                    l["review_rounds"] = l.get("review_rounds", 0) + 1
                    t2(l)
    return org["org_standing"]


def compute_migration_status(org):
    """Latest non-terminal MigrationAssessment state."""
    assessments = [a for a in db.migration_assessments.values() if a["org_id"] == org["id"]]
    non_terminal = [a for a in assessments if a["assessment_status"] not in ("COMPLETED", "ABANDONED")]
    if not non_terminal:
        return "NONE"
    non_terminal.sort(key=lambda a: a["created_at"])
    latest = non_terminal[-1]
    if latest["assessment_status"] in ("REQUESTED", "EXPORT_READY"):
        return "ASSESSING"
    if latest["assessment_status"] == "COOLING_OFF":
        return "COOLING_OFF"
    return "NONE"


def is_migrated(org_id):
    """True if org has a COMPLETED migration assessment (MIGRATED is terminal)."""
    for a in db.migration_assessments.values():
        if a["org_id"] == org_id and a["assessment_status"] == "COMPLETED":
            return True
    return False


def compute_risk_score(project):
    ev = db.editor_versions.get(project["editor_version_id"])
    if ev is None:
        return 0
    support_weight = {"SUPPORTED": 0, "LTS": 1, "DEPRECATED": 2, "SUNSET": 3}[ev["support_status"]]
    c1 = Decimal(25) * Decimal(support_weight) / Decimal(3)
    today = current_date()
    from helpers import parse_date, months_between
    rel = parse_date(ev["released_on"])
    age_months = months_between(rel, today) if rel else 0
    age_factor = min(Decimal(age_months) / Decimal(36), Decimal(1))
    c2 = Decimal(20) * age_factor
    installs = project.get("lifetime_installs", 0)
    install_factor = Decimal(str(math.log10(1 + installs))) / Decimal(7)
    if install_factor > 1:
        install_factor = Decimal(1)
    c3 = Decimal(35) * install_factor
    api_factor = Decimal(min(ev.get("deprecated_api_count", 0), 200)) / Decimal(200)
    c4 = Decimal(20) * api_factor
    total = c1 + c2 + c3 + c4
    if total > 100:
        total = Decimal(100)
    return round_half_up_int(total)


def _org_has_active_agreement_for_platform(org_id, platform_code):
    for a in db.export_agreements.values():
        if a["org_id"] == org_id and a["platform_code"] == platform_code and a["agreement_status"] == "ACTIVE":
            return True
    return False


def compute_fee_schedule_label(project, org):
    """Pinned order: BASE (active grandfather) > CONVERTED > current ACTIVE policy > BASE."""
    pinned = project.get("pinned_policy_change_id")
    if pinned:
        for c in db.grandfather_commitments.values():
            if (c["policy_change_id"] == pinned and c["project_id"] == project["id"]
                    and c["commitment_status"] == "ACTIVE"):
                return "BASE"
    # CONVERTED: org converted by audit
    for case in db.audit_cases.values():
        if case["org_id"] == org["id"] and case["case_status"] in ("CONVERTED", "APPEALED"):
            return "CONVERTED"
    # Current ACTIVE policy change
    active_changes = [p for p in db.policy_changes.values() if p["change_status"] == "ACTIVE"]
    if active_changes:
        return "CONVERTED"
    return "BASE"


def compute_runtime_fee(project, org, billable_installs, variant, lifetime_before_override=None):
    """Runtime fee assessment. Returns (amount_cents, fee_schedule_label)."""
    label = compute_fee_schedule_label(project, org)
    cfg = active_tier_config(org["effective_tier_code"])
    if cfg is not None and cfg.get("runtime_fee_exempt"):
        return 0, label
    if project.get("charity_flag"):
        return 0, label
    if lifetime_before_override is not None:
        lifetime_before = lifetime_before_override
    else:
        lifetime_before = project.get("lifetime_installs", 0)
    # Gate: actual_ttm revenue variant
    figs = tier_determination(org)
    revenue = figs["actual_ttm_revenue_cents"]
    if lifetime_before + billable_installs < INSTALL_THRESHOLD:
        return 0, label
    if revenue < REVENUE_THRESHOLD_CENTS:
        return 0, label
    # Chargeable portion above threshold
    below = max(0, INSTALL_THRESHOLD - lifetime_before)
    chargeable = max(0, billable_installs - below)
    if chargeable <= 0:
        return 0, label
    # Rates by schedule
    if label == "BASE":
        low_rate, high_rate = RATE_LOW_CENTS, RATE_HIGH_CENTS
    else:
        # CONVERTED / current policy rate
        active_changes = [p for p in db.policy_changes.values() if p["change_status"] == "ACTIVE"]
        if active_changes:
            rate = active_changes[-1]["new_per_install_cents"]
            low_rate = rate
            high_rate = rate
        else:
            low_rate, high_rate = RATE_LOW_CENTS, RATE_HIGH_CENTS
    # Marginal per-install tiers, line-then-sum rounding
    first = min(chargeable, RATE_TIER_BOUNDARY)
    rest = chargeable - first
    line1 = round_half_up_int(Decimal(first) * Decimal(low_rate))
    line2 = round_half_up_int(Decimal(rest) * Decimal(high_rate))
    return line1 + line2, label


def org_balance_due(org_id):
    """Sum outstanding over non-terminal-credit invoices."""
    total = 0
    for inv in db.invoices.values():
        proj = db.projects.get(inv["project_id"])
        if not proj or proj["org_id"] != org_id:
            continue
        if inv["assessment_status"] in ("FINALIZED", "ADJUSTED") and inv["payment_status"] in ("UNPAID", "OVERDUE"):
            outstanding = inv["final_amount_cents"] - inv["paid_cents"] - inv["waived_cents"]
            total += max(outstanding, 0)
    return total


def sync_org_balance(org):
    org["balance_due_cents"] = org_balance_due(org["id"])
