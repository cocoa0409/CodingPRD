"""Derived values, recomputations and cascades.

Every accumulator here is recomputed from its declared input set (PRD 2.7), never
patched by a remembered delta.  Pure `compute_*` helpers only write fields; the
caller decides when a resource has been mutated and calls `touch_if_changed`.
"""
import calendar
import datetime
import re
from decimal import Decimal

from constants import (
    ALERT_COOLING_HOURS, ASSOCIATION_ANNUAL_BUDGET_CENTS, DISSENT_DAMPING_STRIKES,
    ENGAGEMENT_PER_ACTION, FILING_LAG_DAYS, FLAT_FLOOR_EXEMPT_BASE_CENTS,
    FLAT_FLOOR_MIN_PCT, INCUMBENCY_FACTOR, JURISDICTION_RULES, MIN_ROSTER_WEIGHT,
    MIN_SEATS, SCORE_TIER_FULL, SCORE_TIER_HALF, SCORE_TIER_QUARTER,
    SCORE_WEIGHT_ALIGNMENT, SCORE_WEIGHT_ENGAGEMENT, SCORE_WEIGHT_INCUMBENCY,
    SCORE_WEIGHT_RELEVANCE, STAFF_HOURLY_RATE_CENTS, TIER_WEIGHT, hours3, pct,
    rhu_int, round_half_up,
)
from core import (
    clock_date, coll, fail, format_instant, instant_date, now_dt, ordered, parse_date,
    rows_of, touch,
)


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def lookup(collection, row_id, error_id):
    row = coll(collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "No such resource: %s." % row_id)
    return row


def snapshot(row, fields):
    return {f: row.get(f) for f in fields}


def touch_if_changed(row, snap):
    for field, value in snap.items():
        if row.get(field) != value:
            touch(row)
            return True
    return False


def rule(jurisdiction_code):
    return JURISDICTION_RULES[jurisdiction_code]


def where(collection, **criteria):
    out = []
    for row in rows_of(collection):
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return ordered(out)


# --------------------------------------------------------------------------- #
# Member
# --------------------------------------------------------------------------- #
def member_pac_solicitable(member):
    """True iff a GRANTED approval of this member covers the logical clock date."""
    today = clock_date()
    for approval in rows_of("approvals"):
        if approval["member_id"] != member["id"] or approval["status"] != "GRANTED":
            continue
        start = parse_date(approval["effective_date"])
        end = parse_date(approval["expires_at_date"])
        if start <= today <= end:
            return True
    return False


def compute_member_dissent_count(member):
    member["recorded_dissent_count"] = sum(
        1 for v in rows_of("votes")
        if v["member_id"] == member["id"] and v["dissent_status"] == "RECORDED"
    )


# --------------------------------------------------------------------------- #
# Committee roster health (PRD 3.2)
# --------------------------------------------------------------------------- #
COMMITTEE_TRACKED = ("seat_count", "total_voting_weight", "roster_state")


def committee_seats(committee_id):
    return where("seats", committee_id=committee_id)


def compute_committee_roster(committee):
    seats = [s for s in committee_seats(committee["id"]) if s["status"] in ("ACTIVE", "DAMPENED")]
    committee["seat_count"] = len(seats)
    committee["total_voting_weight"] = sum(s["voting_weight"] for s in seats)
    if committee["seat_count"] < MIN_SEATS:
        committee["roster_state"] = "FORMING"
    elif committee["total_voting_weight"] < MIN_ROSTER_WEIGHT:
        committee["roster_state"] = "IMPAIRED"
    else:
        committee["roster_state"] = "QUORATE"


def seat_for(committee_id, member_id):
    for seat in committee_seats(committee_id):
        if seat["member_id"] == member_id:
            return seat
    return None


def seat_weight(member, status):
    base = TIER_WEIGHT[member["membership_tier"]]
    if status == "DAMPENED":
        return max(1, base // 2)
    return base


# --------------------------------------------------------------------------- #
# Ballot tally (PRD 3.4 / calculations.position_ballot_tally)
# --------------------------------------------------------------------------- #
POSITION_TALLY_FIELDS = (
    "support_weight", "oppose_weight", "abstain_weight", "quorum_pct", "consensus_pct",
    "last_tally_outcome", "status", "round_number", "ballot_deadline_date",
    "dissent_register_count", "adopted_at",
)


def position_votes(position_id):
    return where("votes", position_id=position_id)


def current_round_cast_votes(position):
    return [
        v for v in position_votes(position["id"])
        if v["round_number"] == position["round_number"] and v["ballot_status"] == "CAST"
    ]


def compute_tally(position, committee):
    """Writes the tally snapshot and returns the branch outcome."""
    votes = current_round_cast_votes(position)
    support = sum(v["weight_snapshot"] for v in votes if v["ballot"] == "SUPPORT")
    oppose = sum(v["weight_snapshot"] for v in votes if v["ballot"] == "OPPOSE")
    abstain = sum(v["weight_snapshot"] for v in votes if v["ballot"] == "ABSTAIN")
    participating = support + oppose + abstain
    total_weight = committee["total_voting_weight"]
    if total_weight:
        quorum = round_half_up(Decimal(100) * Decimal(participating) / Decimal(total_weight), 2)
    else:
        quorum = Decimal("0.00")
    if support + oppose == 0:
        consensus = Decimal("0.00")
    else:
        consensus = round_half_up(Decimal(100) * Decimal(support) / Decimal(support + oppose), 2)
    position["support_weight"] = support
    position["oppose_weight"] = oppose
    position["abstain_weight"] = abstain
    position["quorum_pct"] = float(quorum)
    position["consensus_pct"] = float(consensus)
    quorum_threshold = Decimal(str(committee["quorum_threshold_pct"]))
    consensus_threshold = Decimal(str(committee["consensus_threshold_pct"]))
    if quorum < quorum_threshold:
        outcome = "NO_QUORUM"
    elif consensus >= consensus_threshold:
        outcome = "CONSENSUS"
    else:
        outcome = "DISSENSUS"
    position["last_tally_outcome"] = outcome
    return outcome


def adopt_cascade(position, committee):
    """Cascade links 1-4 of POST /policy-positions/{id}/adopt (PRD 3.4)."""
    recorded = []
    for vote in position_votes(position["id"]):
        if (vote["round_number"] == position["round_number"]
                and vote["ballot_status"] == "CAST"
                and vote["ballot"] == "OPPOSE"
                and vote["dissent_status"] == "FILED"):
            vote["dissent_status"] = "RECORDED"
            touch(vote)
            recorded.append(vote)
    position["dissent_register_count"] = len(recorded)

    member_ids = []
    for vote in recorded:
        if vote["member_id"] not in member_ids:
            member_ids.append(vote["member_id"])

    for member_id in member_ids:
        member = coll("members").get(member_id)
        if member is not None:
            snap = snapshot(member, ("recorded_dissent_count",))
            compute_member_dissent_count(member)
            touch_if_changed(member, snap)
        seat = seat_for(committee["id"], member_id)
        if seat is None:
            continue
        seat_snap = snapshot(seat, ("dissent_strikes", "status", "voting_weight"))
        seat["dissent_strikes"] = seat["dissent_strikes"] + 1
        if seat["dissent_strikes"] >= DISSENT_DAMPING_STRIKES and seat["status"] == "ACTIVE":
            seat["status"] = "DAMPENED"
            if member is not None:
                seat["voting_weight"] = seat_weight(member, "DAMPENED")
        touch_if_changed(seat, seat_snap)


# --------------------------------------------------------------------------- #
# Lobbying registration accumulators (calculations.registration_reportable_accumulator)
# --------------------------------------------------------------------------- #
REGISTRATION_TRACKED = (
    "status", "filed_at", "terminated_at", "amendment_round",
    "ytd_reportable_cents", "ytd_reportable_hours",
)


def registration_activities(registration_id):
    return where("activities", registration_id=registration_id)


def compute_registration_totals(registration):
    logged = [a for a in registration_activities(registration["id"]) if a["status"] == "LOGGED"]
    registration["ytd_reportable_cents"] = sum(a["expenditure_cents"] for a in logged)
    total_hours = Decimal("0")
    for activity in logged:
        total_hours += Decimal(str(activity["hours"]))
    registration["ytd_reportable_hours"] = hours3(total_hours)


def coverage_windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap: abutting windows do not collide (PRD 3.5)."""
    return start_a < end_b and start_b < end_a


# --------------------------------------------------------------------------- #
# Reporting periods and the filing calendar (PRD 3.6)
# --------------------------------------------------------------------------- #
_QUARTER_RE = re.compile(r"^(\d{4})Q([1-9][0-9]*)$")
_HALF_RE = re.compile(r"^(\d{4})H([1-9][0-9]*)$")


def period_bounds(period_code, cadence):
    """Returns (period_start_date, period_end_date) or None when the label is illegal."""
    if not isinstance(period_code, str):
        return None
    if cadence == "QUARTERLY":
        match = _QUARTER_RE.match(period_code)
        if not match:
            return None
        index = int(match.group(2))
        if index < 1 or index > 4:
            return None
        first_month = 3 * (index - 1) + 1
        last_month = first_month + 2
    else:
        match = _HALF_RE.match(period_code)
        if not match:
            return None
        index = int(match.group(2))
        if index < 1 or index > 2:
            return None
        first_month = 6 * (index - 1) + 1
        last_month = first_month + 5
    year = int(match.group(1))
    try:
        start = datetime.date(year, first_month, 1)
        end = datetime.date(year, last_month, calendar.monthrange(year, last_month)[1])
    except ValueError:
        return None
    return start, end


def require_period(period_code, jurisdiction_code):
    cadence = rule(jurisdiction_code)["report_cadence"]
    bounds = period_bounds(period_code, cadence)
    if bounds is None:
        fail("ERR_PERIOD_CADENCE_MISMATCH",
             "period_code '%s' does not match the %s cadence." % (period_code, cadence))
    start, end = bounds
    due = end + datetime.timedelta(days=FILING_LAG_DAYS[cadence])
    return start, end, due, cadence


# --------------------------------------------------------------------------- #
# Expenditure report totals (calculations.reportable_expenditure_total)
# --------------------------------------------------------------------------- #
REPORT_TRACKED = (
    "method_a_total_cents", "method_b_total_cents", "filed_total_cents",
    "included_activity_count", "status", "certified_by_user_id", "certified_at", "late",
)


def staff_cost_for(hours):
    return rhu_int(Decimal(str(hours)) * Decimal(STAFF_HOURLY_RATE_CENTS))


def report_inclusion_set(report):
    start = parse_date(report["period_start_date"])
    end = parse_date(report["period_end_date"])
    included = []
    for activity in registration_activities(report["registration_id"]):
        if activity["status"] != "LOGGED":
            continue
        activity_date = parse_date(activity["activity_date"])
        if start <= activity_date <= end:
            included.append(activity)
    return included


def compute_report_totals(report):
    included = report_inclusion_set(report)
    method_a = sum(a["expenditure_cents"] for a in included)
    method_b = sum(a["expenditure_cents"] + a["staff_cost_cents"] for a in included)
    report["method_a_total_cents"] = method_a
    report["method_b_total_cents"] = method_b
    report["filed_total_cents"] = method_a if report["basis"] == "METHOD_A" else method_b
    report["included_activity_count"] = len(included)


def reports_covering_activity(activity, statuses):
    """Reports of the activity's registration whose period window contains it."""
    activity_date = parse_date(activity["activity_date"])
    out = []
    for report in where("reports", registration_id=activity["registration_id"]):
        if report["status"] not in statuses:
            continue
        start = parse_date(report["period_start_date"])
        end = parse_date(report["period_end_date"])
        if start <= activity_date <= end:
            out.append(report)
    return out


def refresh_open_reports(activity):
    for report in reports_covering_activity(activity, ("OPEN",)):
        snap = snapshot(report, REPORT_TRACKED)
        compute_report_totals(report)
        touch_if_changed(report, snap)


# --------------------------------------------------------------------------- #
# Dues deductibility notice (calculations.dues_deductibility_notice)
# --------------------------------------------------------------------------- #
def deductibility_notice(member):
    dues_year = str(member["dues_year"])
    spend = 0
    for report in rows_of("reports"):
        if report["status"] == "CERTIFIED" and str(report["period_code"])[:4] == dues_year:
            spend += report["filed_total_cents"]
    ratio = round_half_up(
        Decimal(100) * Decimal(spend) / Decimal(ASSOCIATION_ANNUAL_BUDGET_CENTS), 2)
    if ratio > Decimal("100.00"):
        ratio = Decimal("100.00")
    dues = Decimal(member["annual_dues_cents"])
    if member["notice_method"] == "RATIO":
        nondeductible_pct = ratio
        base = dues
    else:
        nondeductible_pct = ratio if ratio > FLAT_FLOOR_MIN_PCT else FLAT_FLOOR_MIN_PCT
        base = dues - Decimal(FLAT_FLOOR_EXEMPT_BASE_CENTS)
        if base < 0:
            base = Decimal(0)
    nondeductible_amount = rhu_int(base * nondeductible_pct / Decimal(100))
    return {
        "member_id": member["id"],
        "dues_year": member["dues_year"],
        "notice_method": member["notice_method"],
        "ratio_pct": float(ratio),
        "nondeductible_pct": float(nondeductible_pct),
        "nondeductible_amount_cents": nondeductible_amount,
        "deductible_amount_cents": member["annual_dues_cents"] - nondeductible_amount,
        "lobbying_spend_cents": spend,
    }


# --------------------------------------------------------------------------- #
# Grassroots campaigns and the constituent match set (PRD 3.7)
# --------------------------------------------------------------------------- #
CAMPAIGN_TRACKED = (
    "status", "alert_count", "matched_member_total", "unmatched_alert_count",
    "cumulative_cost_cents", "disclosure_required", "last_alert_at",
)


def campaign_alerts(campaign_id):
    return where("alerts", campaign_id=campaign_id)


def constituent_match_set(campaign, target_district_code):
    """The four-predicate eligibility filter, ranked engagement_score DESC / created_at ASC."""
    position = coll("positions").get(campaign["position_id"])
    committee_id = position["committee_id"] if position else None
    eligible = []
    for member in rows_of("members"):
        if member["status"] != "ACTIVE":
            continue
        if member["advocacy_optout"]:
            continue
        if member["home_district_code"] != target_district_code:
            continue
        seat = seat_for(committee_id, member["id"]) if committee_id else None
        if seat is None or seat["status"] not in ("ACTIVE", "DAMPENED"):
            continue
        eligible.append(member)
    eligible.sort(key=lambda m: (-m["engagement_score"], m["created_at"], m["_seq"]))
    return [m["id"] for m in eligible]


def compute_campaign_accumulators(campaign):
    alerts = campaign_alerts(campaign["id"])
    campaign["alert_count"] = len(alerts)
    campaign["matched_member_total"] = sum(a["matched_member_count"] for a in alerts)
    campaign["unmatched_alert_count"] = sum(1 for a in alerts if a["status"] == "NO_MATCH")
    campaign["cumulative_cost_cents"] = sum(a["cost_cents"] for a in alerts)
    threshold = rule(campaign["target_jurisdiction_code"])["grassroots_disclosure_threshold_cents"]
    if campaign["cumulative_cost_cents"] >= threshold:
        campaign["disclosure_required"] = True


def cooling_window_ok(campaign, dispatch_dt):
    last = campaign.get("last_alert_at")
    if not last:
        return True
    from core import parse_instant
    last_dt = parse_instant(last)
    return (dispatch_dt - last_dt) >= datetime.timedelta(hours=ALERT_COOLING_HOURS)


# --------------------------------------------------------------------------- #
# Prior approvals (PRD 3.8)
# --------------------------------------------------------------------------- #
def approvals_of_member(member_id):
    return where("approvals", member_id=member_id)


def windows_collide(start_a, end_a, start_b, end_b):
    """Closed-closed overlap: windows that merely touch do collide (PRD 3.8)."""
    return start_a <= end_b and start_b <= end_a


def granted_approval_covering(member_id, on_date):
    for approval in approvals_of_member(member_id):
        if approval["status"] != "GRANTED":
            continue
        start = parse_date(approval["effective_date"])
        end = parse_date(approval["expires_at_date"])
        if start <= on_date <= end:
            return approval
    return None


# --------------------------------------------------------------------------- #
# Segregated fund, candidates and contributions (PRD 3.8, 3.9)
# --------------------------------------------------------------------------- #
FUND_TRACKED = (
    "receipts_total_cents", "committed_balance_cents", "disbursed_total_cents",
    "filing_fee_accrued_cents", "available_balance_cents", "posture",
    "filings_completed_count", "last_filed_period_code",
)
CANDIDATE_TRACKED = (
    "latest_support_score", "pending_support_cents", "committed_support_cents",
    "disbursed_support_cents",
)
CONTRIBUTION_TRACKED = (
    "status", "board_approved_by_user_id", "disbursed_at", "voided_at", "void_reason",
)
ABSORBING_STATUSES = ("PENDING_BOARD", "SUSPENDED", "BOARD_APPROVED", "DISBURSED")


def fund_contributions(fund_id):
    return where("contributions", fund_id=fund_id)


def candidate_contributions(candidate_id):
    return where("contributions", candidate_id=candidate_id)


def compute_fund_balances(fund):
    contributions = fund_contributions(fund["id"])
    fund["committed_balance_cents"] = sum(
        c["amount_cents"] for c in contributions if c["status"] == "BOARD_APPROVED")
    fund["disbursed_total_cents"] = sum(
        c["amount_cents"] for c in contributions if c["status"] == "DISBURSED")
    fund["available_balance_cents"] = (
        fund["receipts_total_cents"] - fund["committed_balance_cents"]
        - fund["disbursed_total_cents"] - fund["filing_fee_accrued_cents"]
    )


def posture_for(fund):
    return "RESTRICTED" if fund["available_balance_cents"] < fund["min_reserve_cents"] else "OPEN"


def compute_candidate_totals(candidate):
    contributions = candidate_contributions(candidate["id"])
    candidate["pending_support_cents"] = sum(
        c["amount_cents"] for c in contributions if c["status"] == "PENDING_BOARD")
    candidate["committed_support_cents"] = sum(
        c["amount_cents"] for c in contributions if c["status"] == "BOARD_APPROVED")
    candidate["disbursed_support_cents"] = sum(
        c["amount_cents"] for c in contributions if c["status"] == "DISBURSED")


def refresh_candidates(candidate_ids):
    for candidate_id in dict.fromkeys(candidate_ids):
        candidate = coll("candidates").get(candidate_id)
        if candidate is None:
            continue
        snap = snapshot(candidate, CANDIDATE_TRACKED)
        compute_candidate_totals(candidate)
        touch_if_changed(candidate, snap)


def settle_fund(fund):
    """Recompute balances, re-evaluate posture and propagate the suspension cascade.

    The fund row itself is not touched here; the caller owns that decision.
    """
    compute_fund_balances(fund)
    new_posture = posture_for(fund)
    if new_posture == fund["posture"]:
        return
    fund["posture"] = new_posture
    affected = []
    if new_posture == "RESTRICTED":
        for contribution in fund_contributions(fund["id"]):
            if contribution["status"] == "PENDING_BOARD":
                contribution["status"] = "SUSPENDED"
                touch(contribution)
                affected.append(contribution["candidate_id"])
    else:
        for contribution in fund_contributions(fund["id"]):
            if contribution["status"] == "SUSPENDED":
                contribution["status"] = "PENDING_BOARD"
                touch(contribution)
                affected.append(contribution["candidate_id"])
    refresh_candidates(affected)


def district_engagement(district_code):
    matched = 0
    for alert in rows_of("alerts"):
        if alert["status"] == "DISPATCHED" and alert["target_district_code"] == district_code:
            matched += alert["matched_member_count"]
    value = ENGAGEMENT_PER_ACTION * matched
    return Decimal(min(100, value))


def candidate_support_score(candidate):
    raw = (SCORE_WEIGHT_ALIGNMENT * Decimal(str(candidate["voting_alignment_pct"]))
           + SCORE_WEIGHT_RELEVANCE * Decimal(candidate["committee_relevance_score"])
           + SCORE_WEIGHT_INCUMBENCY * Decimal(INCUMBENCY_FACTOR[candidate["incumbency"]])
           + SCORE_WEIGHT_ENGAGEMENT * district_engagement(candidate["district_code"]))
    return round_half_up(raw, 2)


def candidate_absorbed_cents(candidate, exclude_id=None):
    total = 0
    for contribution in candidate_contributions(candidate["id"]):
        if contribution["id"] == exclude_id:
            continue
        if contribution["status"] in ABSORBING_STATUSES:
            total += contribution["amount_cents"]
    return total


def contribution_allowance(candidate, score):
    """calculations.contribution_allowance; raises ERR_SCORE_BELOW_FLOOR under the floor."""
    limit = rule(candidate["jurisdiction_code"])["per_candidate_election_limit_cents"]
    if score >= SCORE_TIER_FULL:
        share = Decimal("1.00")
    elif score >= SCORE_TIER_HALF:
        share = Decimal("0.50")
    elif score >= SCORE_TIER_QUARTER:
        share = Decimal("0.25")
    else:
        fail("ERR_SCORE_BELOW_FLOOR",
             "Computed support_score %s is below the 55.00 contribution floor." % score)
    tier_allowance = rhu_int(Decimal(limit) * share)
    remaining = limit - candidate_absorbed_cents(candidate)
    if remaining < 0:
        remaining = 0
    return min(tier_allowance, remaining), limit
