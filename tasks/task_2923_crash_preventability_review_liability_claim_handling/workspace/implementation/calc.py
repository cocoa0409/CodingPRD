"""Every derived quantity in the domain (PRD 2.5, 2.7, 3.1-3.9).

All arithmetic is Decimal-based; floats never take part in a money or precision
computation.
"""

from datetime import timedelta
from decimal import Decimal

from envelope import rhu, rhu_int
from store import db, ordered, rows

DAY = timedelta(days=1)

# ---------------------------------------------------------------------------
# Enumerations (declaration order matters for breakdown arrays)
# ---------------------------------------------------------------------------
SEVERITIES = ("MINOR", "MODERATE", "SEVERE", "CATASTROPHIC")
ROUTE_CLASSES = ("LOCAL", "REGIONAL", "LINEHAUL")
TENURE_BANDS = ("UNDER_12_MONTHS", "MONTHS_12_TO_36", "OVER_36_MONTHS")
TOW_REASONS = ("NONE", "CONVENIENCE", "DISABLING_DAMAGE")
EVIDENCE_KINDS = ("TELEMATICS_SNAPSHOT", "FORWARD_CAMERA",
                  "DRIVER_FACING_CAMERA", "ELD_LOG", "SCENE_PHOTO")
PRESERVATION_STATES = ("REQUESTED", "PRESERVED", "PURGED_BEFORE_HOLD", "RELEASED")
PREVENTABILITY = ("REPORTED", "UNDER_REVIEW", "PREVENTABLE", "NON_PREVENTABLE")
REPORTING_STATUSES = ("PENDING_FILING", "FILED", "LATE_FILED", "NOT_REQUIRED")
DRIVER_STATUSES = ("ACTIVE", "SUSPENDED_PENDING_ACTION", "RETRAINING_REQUIRED",
                   "TERMINATED")
ACTION_TIERS = ("NONE", "COACHING", "RETRAINING", "SUSPENSION",
                "TERMINATION_REVIEW")
ACTION_TYPES = ("COACHING", "RETRAINING", "SUSPENSION",
                "TERMINATION_RECOMMENDATION")
RETRAINING_STATUSES = ("NOT_REQUIRED", "PENDING", "COMPLETED")
ACTION_STATUSES = ("ISSUED", "COMPLETED", "VOIDED")
REVIEW_STATUSES = ("DRAFT", "DELIBERATION", "DECIDED", "CLOSED_FINAL")
DETERMINATIONS = ("PENDING", "PREVENTABLE", "NON_PREVENTABLE")
DECISION_BASES = ("NOT_APPLICABLE", "UNWEIGHTED_MAJORITY", "WEIGHTED_CRITERIA")
VOTES = ("PREVENTABLE", "NON_PREVENTABLE", "ABSTAIN")
HANDLING_STATUSES = ("SETUP", "NEGOTIATION", "SETTLEMENT_COMPLETE", "CLOSED")
RESERVE_STATUSES = ("PROVISIONAL", "REVISED", "FINAL")
COUNSEL_TYPES = ("NONE", "PANEL", "IN_HOUSE", "LEAD_TRIAL")
LAYER_TYPES = ("SIR", "PRIMARY", "EXCESS")
CLAIMANT_TYPES = ("THIRD_PARTY_PROPERTY", "THIRD_PARTY_BODILY_INJURY")
DEMAND_STATUSES = ("DEMANDED", "OFFER_OUTSTANDING", "COUNTER_OUTSTANDING",
                   "SETTLED", "CLOSED_PAID")
ROUND_OUTCOMES = ("OPEN", "COUNTERED", "ACCEPTED", "SUPERSEDED")
SUBRO_STATUSES = ("DRAFT", "READY_TO_PURSUE", "RECOVERED", "DENIED",
                  "WRITTEN_OFF")
RISK_TIERS = ("STANDARD", "ELEVATED", "CRITICAL")
STAFFING_POSTURES = ("OK", "STRAINED", "CRITICAL")
APPEAL_GROUNDS_CODES = ("NEW_EVIDENCE", "PROCEDURAL", "CRITERIA_MISAPPLICATION")
RESOLUTIONS = ("RECOVERED", "DENIED", "WRITTEN_OFF")
ANALYTICS_BASES = ("AS_DETERMINED", "AS_REPORTED")

CRITERION_KEYS = ("speed_and_spacing", "hazard_recognition",
                  "vehicle_condition_precheck", "regulatory_compliance",
                  "evasive_action")
CRITERION_WEIGHTS = {
    "speed_and_spacing": Decimal("0.30"),
    "hazard_recognition": Decimal("0.25"),
    "regulatory_compliance": Decimal("0.20"),
    "vehicle_condition_precheck": Decimal("0.15"),
    "evasive_action": Decimal("0.10"),
}

APPEAL_MAX_ROUNDS = 1
APPEAL_WINDOW_DAYS = 14
RESCISSION_WINDOW_HOURS = 168
SUSPENSION_BUFFER_HOURS = 24
COMMITTEE_QUORUM_MIN = 3
RESERVE_FLOOR_CENTS = 250000
EXPENSE_RATE = Decimal("0.18")
WEIGHTED_PREVENTABLE_THRESHOLD = Decimal("2.50")

REQUIRED_EVIDENCE = {
    "MINOR": ("TELEMATICS_SNAPSHOT",),
    "MODERATE": ("TELEMATICS_SNAPSHOT", "FORWARD_CAMERA"),
    "SEVERE": ("TELEMATICS_SNAPSHOT", "FORWARD_CAMERA", "ELD_LOG"),
    "CATASTROPHIC": ("TELEMATICS_SNAPSHOT", "FORWARD_CAMERA", "ELD_LOG"),
}
DUPLICATION_KINDS = ("TELEMATICS_SNAPSHOT", "FORWARD_CAMERA", "ELD_LOG")

SEVERITY_POINTS = {"MINOR": Decimal(2), "MODERATE": Decimal(4),
                   "SEVERE": Decimal(8), "CATASTROPHIC": Decimal(12)}
SEVERITY_BASE_CENTS = {"MINOR": 500000, "MODERATE": 2500000,
                       "SEVERE": 12000000, "CATASTROPHIC": 45000000}
INJURY_CENTS = 3500000
FATALITY_CENTS = 90000000


def whole_days(start, end):
    """Whole days between two instants, part-days discarded."""
    return int((end - start).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Crash intake: recordability and the filing clock
# ---------------------------------------------------------------------------
def recordability(crash):
    codes = []
    if crash["fatality_count"] >= 1:
        codes.append("FATALITY")
    if crash["injury_transported_count"] >= 1:
        codes.append("INJURY_TRANSPORTED")
    if crash["tow_away"] and crash["tow_reason"] == "DISABLING_DAMAGE":
        codes.append("DISABLING_TOW")
    if crash["hazmat_release"]:
        codes.append("HAZMAT_RELEASE")
    return codes


def apply_recordability(crash):
    codes = recordability(crash)
    crash["recordability_codes"] = codes
    crash["dot_recordable"] = len(codes) > 0
    if codes:
        hours = 24 if crash["hazmat_release"] else 72
        crash["report_due_at"] = crash["occurred_at"] + timedelta(hours=hours)
        crash["reporting_status"] = "PENDING_FILING"
    else:
        crash["report_due_at"] = None
        crash["reporting_status"] = "NOT_REQUIRED"


# ---------------------------------------------------------------------------
# Evidence posture
# ---------------------------------------------------------------------------
def crash_evidence_items(crash_id):
    return [item for item in db.evidence_items.values()
            if item["crash_id"] == crash_id]


def brackets(item, occurred_at):
    return (item["window_start_at"] <= occurred_at
            and occurred_at < item["window_end_at"])


def evidence_posture(crash):
    items = crash_evidence_items(crash["id"])
    for item in items:
        if item["preservation_state"] == "PURGED_BEFORE_HOLD":
            return "COMPROMISED"
    required = REQUIRED_EVIDENCE[crash["severity"]]
    for kind in required:
        satisfied = False
        for item in items:
            if (item["kind"] == kind
                    and item["preservation_state"] == "PRESERVED"
                    and brackets(item, crash["occurred_at"])):
                satisfied = True
                break
        if not satisfied:
            return "PARTIAL"
    return "COMPLETE"


# ---------------------------------------------------------------------------
# Committee arithmetic
# ---------------------------------------------------------------------------
def weighted_member_score(scores, mechanical_factor):
    keys = list(CRITERION_KEYS)
    if not mechanical_factor:
        keys.remove("vehicle_condition_precheck")
    denominator = sum((CRITERION_WEIGHTS[k] for k in keys), Decimal(0))
    total = sum((Decimal(scores[k]) * CRITERION_WEIGHTS[k] for k in keys),
                Decimal(0))
    return rhu(total / denominator, 2)


def case_votes(review_case_id):
    return ordered([v for v in db.committee_votes.values()
                    if v["review_case_id"] == review_case_id])


def live_votes(review_case_id):
    return [v for v in case_votes(review_case_id) if not v["superseded"]]


def live_substantive(review_case_id):
    return [v for v in live_votes(review_case_id) if v["vote"] != "ABSTAIN"]


def vote_counts(review_case_id):
    live = live_votes(review_case_id)
    active = len([v for v in live if v["vote"] != "ABSTAIN"])
    abstain = len([v for v in live if v["vote"] == "ABSTAIN"])
    return active, abstain


def committee_score(review_case_id):
    ballots = live_substantive(review_case_id)
    if not ballots:
        return None
    total = sum((b["weighted_member_score"] for b in ballots), Decimal(0))
    return rhu(total / Decimal(len(ballots)), 2)


def determination_from(review_case_id, posture, score):
    if posture == "COMPROMISED":
        basis = "WEIGHTED_CRITERIA"
        determination = ("PREVENTABLE"
                         if score is not None
                         and score >= WEIGHTED_PREVENTABLE_THRESHOLD
                         else "NON_PREVENTABLE")
    else:
        basis = "UNWEIGHTED_MAJORITY"
        ballots = live_substantive(review_case_id)
        yes = len([b for b in ballots if b["vote"] == "PREVENTABLE"])
        no = len([b for b in ballots if b["vote"] == "NON_PREVENTABLE"])
        determination = "PREVENTABLE" if yes > no else "NON_PREVENTABLE"
    return determination, basis


# ---------------------------------------------------------------------------
# Driver accountability
# ---------------------------------------------------------------------------
def tenure_band(driver, at=None):
    at = db.now if at is None else at
    from datetime import datetime, timezone
    hire = driver["hire_date"]
    hire_instant = datetime(hire.year, hire.month, hire.day, tzinfo=timezone.utc)
    days = whole_days(hire_instant, at)
    if days < 365:
        return "UNDER_12_MONTHS"
    if days < 1096:
        return "MONTHS_12_TO_36"
    return "OVER_36_MONTHS"


def decay_factor(age_days):
    if age_days < 365:
        return Decimal("1.0")
    if age_days < 730:
        return Decimal("0.5")
    return Decimal("0.0")


def driver_crashes(driver_id):
    return [c for c in db.crashes.values() if c["driver_id"] == driver_id]


def preventable_points(driver):
    total = Decimal(0)
    for crash in driver_crashes(driver["id"]):
        if crash["preventability_status"] != "PREVENTABLE":
            continue
        age = whole_days(crash["occurred_at"], db.now)
        total += SEVERITY_POINTS[crash["severity"]] * decay_factor(age)
    return rhu(total, 1)


def action_tier(points):
    if points >= 12:
        return "TERMINATION_REVIEW"
    if points >= 8:
        return "SUSPENSION"
    if points >= 4:
        return "RETRAINING"
    if points >= 1:
        return "COACHING"
    return "NONE"


def required_action_tier(driver):
    return action_tier(preventable_points(driver))


ACTION_TYPE_RANK = {"COACHING": 1, "RETRAINING": 2, "SUSPENSION": 3,
                    "TERMINATION_RECOMMENDATION": 4}
TIER_RANK = {"NONE": 0, "COACHING": 1, "RETRAINING": 2, "SUSPENSION": 3,
             "TERMINATION_REVIEW": 4}


# ---------------------------------------------------------------------------
# Terminal aggregates and analytics
# ---------------------------------------------------------------------------
def terminal_drivers(terminal_id):
    return [d for d in db.drivers.values() if d["terminal_id"] == terminal_id]


def active_driver_count(terminal_id):
    return len([d for d in terminal_drivers(terminal_id)
                if d["status"] != "TERMINATED"])


def suspended_driver_count(terminal_id):
    return len([d for d in terminal_drivers(terminal_id)
                if d["status"] in ("SUSPENDED_PENDING_ACTION",
                                   "RETRAINING_REQUIRED")])


def staffing_posture(terminal_id):
    active = active_driver_count(terminal_id)
    if active == 0:
        return "OK"
    suspended = suspended_driver_count(terminal_id)
    if suspended * 2 >= active:
        return "CRITICAL"
    if suspended * 5 >= active:
        return "STRAINED"
    return "OK"


def late_filing_count(terminal_id):
    return len([c for c in db.crashes.values()
                if c["terminal_id"] == terminal_id
                and c["reporting_status"] == "LATE_FILED"])


def analytics_window():
    end = db.now
    return end - timedelta(days=365), end


def crashes_in_window(terminal_id):
    start, end = analytics_window()
    return [c for c in db.crashes.values()
            if c["terminal_id"] == terminal_id
            and start <= c["occurred_at"] < end]


def crash_rate(count, annual_miles_millions):
    return rhu(Decimal(count) / annual_miles_millions, 3)


def risk_tier(rate):
    if rate >= Decimal("3.000"):
        return "CRITICAL"
    if rate >= Decimal("1.500"):
        return "ELEVATED"
    return "STANDARD"


def terminal_preventable_count(terminal_id):
    return len([c for c in crashes_in_window(terminal_id)
                if c["preventability_status"] == "PREVENTABLE"])


# ---------------------------------------------------------------------------
# Litigation risk and the reserve
# ---------------------------------------------------------------------------
PREVENTABILITY_POINTS = {"PREVENTABLE": 30, "UNDER_REVIEW": 10, "REPORTED": 5,
                         "NON_PREVENTABLE": 0}
POSTURE_POINTS = {"COMPROMISED": 25, "PARTIAL": 5, "COMPLETE": 0}


def claim_demands(claim_id):
    return ordered([d for d in db.demands.values() if d["claim_id"] == claim_id])


def litigation_risk_score(claim):
    crash = db.crashes[claim["crash_id"]]
    score = PREVENTABILITY_POINTS[crash["preventability_status"]]
    score += POSTURE_POINTS[evidence_posture(crash)]
    if crash["fatality_count"] >= 1:
        score += 20
    if crash["hazmat_release"]:
        score += 10
    driver = db.drivers.get(crash["driver_id"])
    if driver is not None and tenure_band(driver) == "UNDER_12_MONTHS":
        score += 5
    for demand in claim_demands(claim["id"]):
        if (demand["claimant_type"] == "THIRD_PARTY_BODILY_INJURY"
                and demand["represented_by_counsel"]):
            score += 15
            break
    return min(score, 100)


def litigation_risk_multiplier(score):
    if score <= 24:
        return Decimal("1.00")
    if score <= 54:
        return Decimal("1.15")
    if score <= 79:
        return Decimal("1.35")
    return Decimal("1.60")


def counsel_required(score):
    return score >= 55


def provisional_gross(crash):
    return (SEVERITY_BASE_CENTS[crash["severity"]]
            + crash["injury_transported_count"] * INJURY_CENTS
            + crash["fatality_count"] * FATALITY_CENTS)


def demand_weighted_gross(claim):
    total = 0
    for demand in claim_demands(claim["id"]):
        if demand["status"] in ("SETTLED", "CLOSED_PAID"):
            total += demand["settlement_total_cents"]
        else:
            total += demand["demand_amount_cents"]
    return total


def reserve_from_gross(gross, multiplier, counsel_assigned):
    indemnity = rhu_int(Decimal(gross) * multiplier)
    expense = rhu_int(Decimal(gross) * EXPENSE_RATE) if counsel_assigned else 0
    return max(indemnity + expense, RESERVE_FLOOR_CENTS)


def compute_reserve(claim, basis):
    score = litigation_risk_score(claim)
    multiplier = litigation_risk_multiplier(score)
    if basis == "DEMAND_BASED":
        gross = demand_weighted_gross(claim)
    else:
        gross = provisional_gross(db.crashes[claim["crash_id"]])
    return reserve_from_gross(gross, multiplier, claim["counsel_assigned"])


def total_incurred(claim):
    return (claim["indemnity_paid_cents"] + claim["alae_paid_cents"]
            + claim["outstanding_reserve_cents"]
            - claim["subrogation_recovered_cents"])


def claim_exposure(claim):
    return (claim["outstanding_reserve_cents"] + claim["indemnity_paid_cents"]
            + claim["alae_paid_cents"] + claim["reserve_released_cents"])


# ---------------------------------------------------------------------------
# Settlement arithmetic and the policy tower
# ---------------------------------------------------------------------------
def alae_rate(indemnity_cents):
    if indemnity_cents >= 25000000:
        return Decimal("0.15")
    if indemnity_cents >= 5000000:
        return Decimal("0.12")
    return Decimal("0.08")


def settlement_figures(indemnity_cents):
    rate = alae_rate(indemnity_cents)
    alae = rhu_int(Decimal(indemnity_cents) * rate)
    return indemnity_cents, alae, indemnity_cents + alae


def tower_layers(program_year):
    layers = [l for l in db.policy_layers.values()
              if l["program_year"] == program_year]
    return sorted(layers, key=lambda l: l["layer_index"])


def tower_well_formed(program_year):
    layers = tower_layers(program_year)
    if not layers:
        return False
    if layers[0]["layer_index"] != 1:
        return False
    if layers[0]["layer_type"] != "SIR":
        return False
    if layers[0]["attachment_point_cents"] != 0:
        return False
    cumulative = 0
    for position, layer in enumerate(layers, start=1):
        if layer["layer_index"] != position:
            return False
        if layer["attachment_point_cents"] != cumulative:
            return False
        cumulative += layer["limit_cents"]
    return True


def program_year_of(crash):
    return crash["occurred_at"].year


def allocate(claim, program_year, amount):
    """Walk the tower. Returns (entries, leftover)."""
    consumed = {}
    for entry in claim["layer_allocations"]:
        key = entry["policy_layer_id"]
        consumed[key] = consumed.get(key, 0) + entry["allocated_cents"]
    remaining = amount
    entries = []
    for layer in tower_layers(program_year):
        if remaining <= 0:
            break
        capacity = layer["limit_cents"] - consumed.get(layer["id"], 0)
        if capacity <= 0:
            continue
        take = capacity if capacity < remaining else remaining
        entries.append({
            "policy_layer_id": layer["id"],
            "layer_index": layer["layer_index"],
            "layer_type": layer["layer_type"],
            "allocated_cents": take,
        })
        remaining -= take
    return entries, remaining


# ---------------------------------------------------------------------------
# Negotiation ledger helpers
# ---------------------------------------------------------------------------
def demand_rounds(demand_id):
    return sorted([r for r in db.negotiation_rounds.values()
                   if r["demand_id"] == demand_id],
                  key=lambda r: r["round_index"])


def standing_round(demand_id):
    ledger = demand_rounds(demand_id)
    for row in reversed(ledger):
        if row["outcome"] != "SUPERSEDED":
            return row
    return None


def highest_round(demand_id):
    ledger = demand_rounds(demand_id)
    return ledger[-1] if ledger else None


def round_count(demand_id):
    return len(demand_rounds(demand_id))


# ---------------------------------------------------------------------------
# Subrogation helpers
# ---------------------------------------------------------------------------
def claim_subrogations(claim_id):
    return ordered([s for s in db.subrogation_demands.values()
                    if s["claim_id"] == claim_id])


def max_recoverable(base_cents, at_fault_percentage):
    return rhu_int(Decimal(base_cents) * Decimal(at_fault_percentage)
                   / Decimal(100))
