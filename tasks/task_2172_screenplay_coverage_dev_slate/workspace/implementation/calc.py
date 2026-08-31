"""Domain constants, calculations and cascades."""

from datetime import timedelta
from decimal import Decimal

from core import (
    add_months, db, dec, fail, fmt_dt, now, now_str, parse_date, parse_dt,
    round_half_up, sort_rows, touch, collection_rows,
)

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
MATERIAL_TYPES = ("SPEC_SCRIPT", "BOOK", "ARTICLE", "PLAY", "LIFE_RIGHTS_STORY", "ORIGINAL_PITCH")
GENRES = ("DRAMA", "COMEDY", "THRILLER", "HORROR", "SCIFI", "FAMILY", "DOCUMENTARY")
RIGHTS_CHAIN_STATUSES = ("UNVERIFIED", "PARTIAL", "CLEAR", "DISPUTED")
TIERS = ("NONE", "WATCH", "HOT", "PRIORITY")
DOC_TYPES = ("CHAIN_OF_TITLE", "COPYRIGHT_CERT", "WGA_REGISTRATION", "PRIOR_ASSIGNMENT",
             "LIFE_RIGHTS_RELEASE", "CLEARANCE_OPINION")
SUBMITTED_VIA = ("AGENCY", "MANAGER", "ATTORNEY", "UNSOLICITED", "INTERNAL")
PRIORITY_FLAGS = ("RUSH", "STANDARD", "BACKLOG")
SUBMISSION_STATUSES = ("RECEIVED", "RELEASE_PENDING", "INTAKE_CLEARED", "READER_ASSIGNED",
                       "COVERAGE_IN_REVIEW", "TRACKED", "PASSED", "IN_DEVELOPMENT", "WITHDRAWN")
SUBMISSION_TERMINAL = ("PASSED", "IN_DEVELOPMENT", "WITHDRAWN")
RELEASE_FORM_STATUSES = ("REQUIRED", "SENT", "EXECUTED", "WAIVED", "EXPIRED")
EMPLOYMENT_TYPES = ("STAFF", "FREELANCE")
READER_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")
ASSIGNMENT_STATUSES = ("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "COMPLETED", "RECALLED")
ASSIGNMENT_OPEN = ("ASSIGNED", "IN_PROGRESS", "SUBMITTED")
RECOMMENDATIONS = ("PASS", "CONSIDER", "RECOMMEND", "STRONG_RECOMMEND")
REPORT_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "REJECTED")
BOARD_STATUSES = ("LIVE", "ARCHIVED")
OPTION_STATUSES = ("DRAFTED", "ACTIVE", "EXTENDED", "EXERCISED", "LAPSED", "REVERTED", "TERMINATED")
OPTION_TERMINAL = ("LAPSED", "REVERTED", "TERMINATED")
OPTION_ENCUMBERING = ("ACTIVE", "EXTENDED", "EXERCISED")
RIGHTS_STATUSES = ("OPTIONED", "OWNED", "LAPSED_RIGHTS", "REVERTED")
DEVELOPMENT_STATUSES = ("SETUP", "WRITING", "DRAFT_DELIVERED", "POLISH", "POLISH_DELIVERED",
                        "GREENLIT", "TURNAROUND", "DEAD")
DEV_BLOCKED_FOR_CREATE = ("GREENLIT", "TURNAROUND", "DEAD")
WRITER_STATUSES = ("ACTIVE", "UNAVAILABLE")
ENGAGEMENT_TYPES = ("ORIGINAL_DRAFT", "REWRITE", "POLISH", "PRODUCTION_REWRITE")
ENGAGEMENT_STATUSES = ("PROPOSED", "ATTACHED", "ACTIVE", "COMPLETED", "TERMINATED")
ENGAGEMENT_TERMINAL = ("COMPLETED", "TERMINATED")
MILESTONE_TYPES = ("COMMENCEMENT", "FIRST_DRAFT_DELIVERY", "FIRST_DRAFT_ACCEPTANCE",
                   "REWRITE_DELIVERY", "POLISH_DELIVERY", "PRODUCTION_BONUS")
MILESTONE_STATUSES = ("SCHEDULED", "DUE", "APPROVED", "PAID", "VOIDED")
MILESTONE_UNPAID = ("SCHEDULED", "DUE", "APPROVED")
REVIEW_STATUSES = ("OPEN", "VOTING", "PASSED", "DECLINED", "DEFERRED", "WITHDRAWN")
REVIEW_TERMINAL = ("PASSED", "DECLINED", "DEFERRED", "WITHDRAWN")
MEMBER_STATUSES = ("ACTIVE", "INACTIVE")
VOTE_VALUES = ("APPROVE", "DECLINE", "ABSTAIN", "VETO")

# --------------------------------------------------------------------------
# Domain constants
# --------------------------------------------------------------------------
SIGNATORY_AGENCIES = ("CAA", "WME", "UTA", "GERSH", "APA")
TURNAROUND_HOURS = {"RUSH": 24, "STANDARD": 72, "BACKLOG": 168}
REQUIRED_CHAIN_TYPES = ("CHAIN_OF_TITLE", "COPYRIGHT_CERT")
CHAIN_CLEAR_MIN_DOCS = 3
COVERAGE_MIN_SYNOPSIS_WORDS = 250
COVERAGE_MAX_REVISION_ROUNDS = 2
CALIBRATION_ANCHOR = Decimal("5.50")
SCORE_WEIGHTS = (
    ("logline_score", Decimal("0.10")),
    ("structure_score", Decimal("0.30")),
    ("character_score", Decimal("0.25")),
    ("dialogue_score", Decimal("0.15")),
    ("marketability_score", Decimal("0.20")),
)
RECOMMENDATION_BONUS = {"PASS": 0, "CONSIDER": 8, "RECOMMEND": 18, "STRONG_RECOMMEND": 30}
COMPETITION_BONUS_PER_RIVAL = 3
COMPETITION_BONUS_CAP = 15
CLEAR_CHAIN_BONUS = 10
REVISION_PENALTY = 5
TIER_WATCH_MIN = Decimal("60.00")
TIER_HOT_MIN = Decimal("85.00")
TIER_PRIORITY_MIN = Decimal("110.00")
READER_BUFFER_HOURS = 12
ESCALATION_BAND_MID_MIN = 2000000000
ESCALATION_BAND_HIGH_MIN = 6000000000
CREDIT_BAND_MID_MIN = 25000000
CREDIT_BAND_HIGH_MIN = 100000000
TURNAROUND_REVERSION_MONTHS = 18
DEV_BUDGET_WRITER_SHARE_BPS = 1200
GUILD_MINIMUM_FEE_CENTS = {
    "ORIGINAL_DRAFT": 7500000,
    "REWRITE": 5000000,
    "POLISH": 2500000,
    "PRODUCTION_REWRITE": 5000000,
}
MILESTONE_TEMPLATES = {
    "ORIGINAL_DRAFT": (("COMMENCEMENT", 3000), ("FIRST_DRAFT_DELIVERY", 4000),
                       ("FIRST_DRAFT_ACCEPTANCE", 3000)),
    "REWRITE": (("COMMENCEMENT", 4000), ("REWRITE_DELIVERY", 6000)),
    "POLISH": (("COMMENCEMENT", 5000), ("POLISH_DELIVERY", 5000)),
    "PRODUCTION_REWRITE": (("COMMENCEMENT", 3334), ("REWRITE_DELIVERY", 3333),
                           ("PRODUCTION_BONUS", 3333)),
}
MILESTONE_DUE_OFFSET_DAYS = {
    "COMMENCEMENT": 0,
    "FIRST_DRAFT_DELIVERY": 84,
    "FIRST_DRAFT_ACCEPTANCE": 98,
    "REWRITE_DELIVERY": 56,
    "POLISH_DELIVERY": 28,
    "PRODUCTION_BONUS": 120,
}
WRITER_MAX_CONCURRENT_ENGAGEMENTS = 2
GREENLIGHT_QUORUM_PCT = Decimal("60.00")
GREENLIGHT_APPROVAL_PCT = Decimal("66.67")
GREENLIGHT_MIN_ACTIVE_MEMBERS = 3


# --------------------------------------------------------------------------
# Small relational helpers
# --------------------------------------------------------------------------
def rows_where(collection, **criteria):
    out = []
    for row in collection_rows(collection):
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out


def documents_of(property_id):
    return rows_where("documents", property_id=property_id)


def release_forms_of(submission_id):
    return rows_where("release_forms", submission_id=submission_id)


def assignments_of(submission_id):
    return rows_where("assignments", submission_id=submission_id)


def report_of_assignment(assignment_id):
    found = rows_where("reports", assignment_id=assignment_id)
    return found[0] if found else None


def milestones_of(engagement_id):
    rows = rows_where("milestones", engagement_id=engagement_id)
    return sorted(rows, key=lambda m: m["sequence_index"])


def engagements_of_project(project_id):
    return rows_where("engagements", project_id=project_id)


def engagements_of_writer(writer_id):
    return rows_where("engagements", writer_id=writer_id)


def project_for_option(option_id):
    found = rows_where("projects", option_agreement_id=option_id)
    return found[0] if found else None


# --------------------------------------------------------------------------
# Rights chain derivation
# --------------------------------------------------------------------------
def recompute_rights_chain(prop):
    live = [d for d in documents_of(prop["id"]) if not d.get("superseded")]
    verified = [d for d in live if d.get("verified") is True]
    prop["verified_document_count"] = len(verified)
    verified_types = set(d["doc_type"] for d in verified)
    if any(d["doc_type"] == "PRIOR_ASSIGNMENT" and d.get("verified") is not True for d in live):
        status = "DISPUTED"
    elif set(REQUIRED_CHAIN_TYPES).issubset(verified_types) and len(verified) >= CHAIN_CLEAR_MIN_DOCS:
        status = "CLEAR"
    elif len(verified) >= 1:
        status = "PARTIAL"
    else:
        status = "UNVERIFIED"
    prop["rights_chain_status"] = status


def recompute_encumbrance(prop):
    count = 0
    for opt in rows_where("options", property_id=prop["id"]):
        if opt["status"] in OPTION_ENCUMBERING:
            count += 1
    prop["encumbrance_count"] = count


# --------------------------------------------------------------------------
# Submission intake
# --------------------------------------------------------------------------
def release_form_requirement(submitted_via, submitting_agency):
    return bool(submitted_via == "UNSOLICITED" or submitting_agency not in SIGNATORY_AGENCIES)


def coverage_turnaround_due(received_at_dt, priority_flag):
    return received_at_dt + timedelta(hours=TURNAROUND_HOURS[priority_flag])


def apply_lazy_expiry(submission):
    """Move stale release forms to EXPIRED. Returns True when anything expired."""
    current = now()
    changed = False
    for form in release_forms_of(submission["id"]):
        if form["status"] in ("REQUIRED", "SENT", "EXECUTED"):
            expires = parse_dt(form["expires_at"])
            if expires < current:
                form["status"] = "EXPIRED"
                touch(form)
                changed = True
    return changed


# --------------------------------------------------------------------------
# Reader selection / windows
# --------------------------------------------------------------------------
def reader_window_conflict(reader_id, window_start, window_due, exclude_assignment_id=None):
    for assignment in rows_where("assignments", reader_id=reader_id):
        if assignment["status"] not in ASSIGNMENT_OPEN:
            continue
        if exclude_assignment_id and assignment["id"] == exclude_assignment_id:
            continue
        existing_start = parse_dt(assignment["window_start"])
        existing_due = parse_dt(assignment["window_due"])
        buffered_due = existing_due + timedelta(hours=READER_BUFFER_HOURS)
        if window_start <= buffered_due and existing_start <= window_due:
            return True
    return False


def recompute_reader_counters(reader):
    active = 0
    for assignment in rows_where("assignments", reader_id=reader["id"]):
        if assignment["status"] in ASSIGNMENT_OPEN:
            active += 1
    reader["active_assignment_count"] = active
    approved = approved_reports_of_reader(reader["id"])
    reader["completed_report_count"] = len(approved)


def approved_reports_of_reader(reader_id):
    out = []
    for report in collection_rows("reports"):
        if report["status"] != "APPROVED":
            continue
        assignment = db.assignments.get(report["assignment_id"])
        if assignment and assignment["reader_id"] == reader_id:
            out.append(report)
    return out


def recompute_calibration_bias(reader):
    approved = approved_reports_of_reader(reader["id"])
    if not approved:
        reader["calibration_bias"] = Decimal("0.00")
        return
    total = Decimal(0)
    for report in approved:
        total += dec(report["composite_score"])
    mean = total / Decimal(len(approved))
    reader["calibration_bias"] = round_half_up(mean - CALIBRATION_ANCHOR, 2)


def select_reader(prop, submission, window_start, window_due, excluded_ids):
    recalled_reader_ids = set()
    for assignment in assignments_of(submission["id"]):
        if assignment["status"] == "RECALLED":
            recalled_reader_ids.add(assignment["reader_id"])
    candidates = []
    for reader in collection_rows("readers"):
        if reader["status"] != "ACTIVE":
            continue
        if reader["active_assignment_count"] >= reader["weekly_capacity"]:
            continue
        if not (reader["specialty_genre"] == prop["genre"] or reader["employment_type"] == "STAFF"):
            continue
        if reader["id"] in excluded_ids:
            continue
        if reader["id"] in recalled_reader_ids:
            continue
        if reader_window_conflict(reader["id"], window_start, window_due):
            continue
        candidates.append(reader)
    if not candidates:
        return None

    def rank_key(reader):
        genre_penalty = 0 if reader["specialty_genre"] == prop["genre"] else 1
        load = Decimal(reader["active_assignment_count"]) / Decimal(reader["weekly_capacity"])
        return (genre_penalty, load, -reader["completed_report_count"],
                reader.get("created_at") or "", reader.get("_seq") or 0)

    candidates.sort(key=rank_key)
    return candidates[0]


# --------------------------------------------------------------------------
# Coverage scoring / calibration / heat
# --------------------------------------------------------------------------
def coverage_score_pair(report, reader):
    raw = Decimal(0)
    for field, weight in SCORE_WEIGHTS:
        raw += weight * Decimal(report[field])
    composite = round_half_up(raw, 2)
    bias = dec(reader["calibration_bias"])
    adjusted = raw - bias
    if adjusted < Decimal("1.00"):
        adjusted = Decimal("1.00")
    if adjusted > Decimal("10.00"):
        adjusted = Decimal("10.00")
    normalized = round_half_up(adjusted, 2)
    return composite, normalized


def tier_rank(tier):
    return TIERS.index(tier)


def tracking_heat_score(report, prop, submission):
    competing = 0
    for other in rows_where("submissions", property_id=prop["id"]):
        if other["id"] == submission["id"]:
            continue
        if other["status"] in ("TRACKED", "IN_DEVELOPMENT"):
            competing += 1
    total = dec(report["normalized_score"]) * Decimal(10)
    total += Decimal(RECOMMENDATION_BONUS[report["recommendation"]])
    total += Decimal(min(COMPETITION_BONUS_CAP, COMPETITION_BONUS_PER_RIVAL * competing))
    if prop["rights_chain_status"] == "CLEAR":
        total += Decimal(CLEAR_CHAIN_BONUS)
    total -= Decimal(REVISION_PENALTY * report["revision_round_count"])
    heat = round_half_up(total, 2)
    if heat >= TIER_PRIORITY_MIN:
        tier = "PRIORITY"
    elif heat >= TIER_HOT_MIN:
        tier = "HOT"
    elif heat >= TIER_WATCH_MIN:
        tier = "WATCH"
    else:
        tier = "NONE"
    return heat, tier, competing


# --------------------------------------------------------------------------
# Option pricing
# --------------------------------------------------------------------------
def option_pricing(option):
    project = project_for_option(option["id"])
    if project is None:
        escalation = 0
    else:
        budget = project["budget_cents"]
        if budget < ESCALATION_BAND_MID_MIN:
            escalation = 0
        elif budget < ESCALATION_BAND_HIGH_MIN:
            escalation = 1500
        else:
            escalation = 2500
    adjusted = int(round_half_up(
        Decimal(option["purchase_price_cents"]) * Decimal(10000 + escalation) / Decimal(10000), 0))
    if adjusted < CREDIT_BAND_MID_MIN:
        cap_bps = 10000
    elif adjusted < CREDIT_BAND_HIGH_MIN:
        cap_bps = 7500
    else:
        cap_bps = 5000
    fees_paid = option["option_fee_cents"]
    if option.get("extension_exercised"):
        fees_paid += option.get("extension_fee_cents") or 0
    if option.get("applicable_to_purchase"):
        cap_amount = (adjusted * cap_bps) // 10000
        credit = min(fees_paid, cap_amount)
    else:
        credit = 0
    option["escalation_bps"] = escalation
    option["adjusted_purchase_price_cents"] = adjusted
    option["applicable_credit_cents"] = credit
    option["net_purchase_due_cents"] = adjusted - credit


def option_period_conflict(option):
    start = parse_dt(option["option_start_at"])
    end = parse_dt(option["option_end_at"])
    for other in rows_where("options", property_id=option["property_id"]):
        if other["id"] == option["id"]:
            continue
        if other["status"] not in OPTION_ENCUMBERING:
            continue
        if not other.get("option_end_at"):
            continue
        other_start = parse_dt(other["option_start_at"])
        other_end = parse_dt(other["option_end_at"])
        if start < other_end and other_start < end:
            return True
    return False


# --------------------------------------------------------------------------
# Project / writer ledgers
# --------------------------------------------------------------------------
def project_writer_budget_cap(budget_cents):
    return (budget_cents * DEV_BUDGET_WRITER_SHARE_BPS) // 10000


def recompute_project_commitment(project):
    total = 0
    for engagement in engagements_of_project(project["id"]):
        if engagement["status"] in ("ATTACHED", "ACTIVE", "COMPLETED"):
            total += engagement["total_fee_cents"]
    project["committed_writer_fee_cents"] = total


def recompute_greenlight_ready(project):
    project["greenlight_ready"] = bool(
        project["rights_status"] == "OWNED"
        and project["development_status"] in ("DRAFT_DELIVERED", "POLISH_DELIVERED"))


def recompute_writer_ledger(writer):
    committed = 0
    paid = 0
    active = 0
    for engagement in engagements_of_writer(writer["id"]):
        if engagement["status"] in ("ATTACHED", "ACTIVE"):
            active += 1
        for milestone in milestones_of(engagement["id"]):
            if milestone["status"] in MILESTONE_UNPAID:
                committed += milestone["gross_amount_cents"]
            elif milestone["status"] == "PAID":
                paid += milestone["gross_amount_cents"]
    writer["committed_fee_cents"] = committed
    writer["paid_fee_cents"] = paid
    writer["active_engagement_count"] = active


def milestone_schedule(engagement):
    template = MILESTONE_TEMPLATES[engagement["engagement_type"]]
    total = engagement["total_fee_cents"]
    lines = []
    for index, (mtype, pct) in enumerate(template):
        gross = (total * pct) // 10000
        lines.append({"milestone_type": mtype, "sequence_index": index,
                      "percentage_bps": pct, "gross_amount_cents": gross})
    remainder = total - sum(line["gross_amount_cents"] for line in lines)
    winner = None
    for line in lines:
        if winner is None:
            winner = line
        elif line["percentage_bps"] > winner["percentage_bps"]:
            winner = line
        elif (line["percentage_bps"] == winner["percentage_bps"]
              and line["sequence_index"] < winner["sequence_index"]):
            winner = line
    winner["gross_amount_cents"] += remainder
    start = parse_date(engagement["start_date"])
    for line in lines:
        due = start + timedelta(days=MILESTONE_DUE_OFFSET_DAYS[line["milestone_type"]])
        line["due_on"] = due.strftime("%Y-%m-%d")
    return lines


def writer_overlap_count(writer_id, candidate):
    cand_start = parse_date(candidate["start_date"])
    cand_end = parse_date(candidate["end_date"])
    count = 0
    for engagement in engagements_of_writer(writer_id):
        if engagement["id"] == candidate["id"]:
            continue
        if engagement["status"] not in ("ATTACHED", "ACTIVE"):
            continue
        other_start = parse_date(engagement["start_date"])
        other_end = parse_date(engagement["end_date"])
        if other_start <= cand_end and cand_start <= other_end:
            count += 1
    return count


# --------------------------------------------------------------------------
# Shared cascades
# --------------------------------------------------------------------------
def void_engagement_milestones(engagement):
    """VOID the unpaid milestones of an engagement being terminated."""
    for milestone in milestones_of(engagement["id"]):
        if milestone["status"] in MILESTONE_UNPAID:
            milestone["status"] = "VOIDED"
            touch(milestone)


def terminate_open_engagements(project, reason):
    """Terminate PROPOSED/ATTACHED/ACTIVE engagements on a project and unwind ledgers."""
    affected_writers = {}
    for engagement in engagements_of_project(project["id"]):
        if engagement["status"] not in ("PROPOSED", "ATTACHED", "ACTIVE"):
            continue
        engagement["status"] = "TERMINATED"
        engagement["termination_reason"] = reason
        touch(engagement)
        void_engagement_milestones(engagement)
        writer = db.writers.get(engagement["writer_id"])
        if writer is not None:
            affected_writers[writer["id"]] = writer
    for writer in affected_writers.values():
        recompute_writer_ledger(writer)
        touch(writer)
    recompute_project_commitment(project)


def withdraw_open_reviews(project, reason):
    for review in rows_where("reviews", project_id=project["id"]):
        if review["status"] in ("OPEN", "VOTING"):
            review["status"] = "WITHDRAWN"
            review["withdrawal_reason"] = reason
            touch(review)


def recompute_review_tallies(review):
    votes = rows_where("votes", review_id=review["id"])
    cast = sum(v["weight_bps_snapshot"] for v in votes)
    abstain = sum(v["weight_bps_snapshot"] for v in votes if v["vote_value"] == "ABSTAIN")
    approve = sum(v["weight_bps_snapshot"] for v in votes if v["vote_value"] == "APPROVE")
    veto = any(v["vote_value"] == "VETO" and v.get("_veto_power") for v in votes)
    review["cast_weight_bps"] = cast
    review["decisive_weight_bps"] = cast - abstain
    review["approve_weight_bps"] = approve
    review["veto_cast"] = bool(veto)
