"""The calculation engine (SCAFFOLD 1.3 / PRD 2.7, 3.3, 3.4, 3.5, 3.7, 3.8).

Money never leaves integer cents; percentages are round-half-up to exactly two
decimal places and are emitted as JSON numbers.  Nothing here uses float.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants
import db
import lookup

ZERO_PCT = Decimal("0.00")
CENT = Decimal(1)


def round_half_up(value, places=0):
    """Round half up — never Python's banker's rounding."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def pct2(numerator, denominator):
    """100 * numerator / denominator, round_half_up to 2 dp; 0.00 when denom 0."""
    if not denominator:
        return ZERO_PCT
    value = (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
    return round_half_up(value, 2)


def ceil_div(numerator, denominator):
    q, r = divmod(int(numerator), int(denominator))
    return q + (1 if r else 0)


# ===========================================================================
# calculations.petition_signature_valid_count  (PRD 3.3)
# ===========================================================================
def signature_verdict(signature, candidacy):
    """The first matching test decides; the ordering of the three ineligibility
    tests is part of the contract (PRD 3.3)."""
    student = db.store.students.get(signature["signer_student_id"])
    office = db.store.offices.get(candidacy["office_id"])
    if student is None:
        return "UNKNOWN"
    if student["enrollment_status"] != "ENROLLED":
        return "INELIGIBLE_NOT_ENROLLED"
    if student["disciplinary_hold"]:
        return "INELIGIBLE_HOLD"
    if office is None or student["class_year"] not in (office["eligible_class_years"] or []):
        return "INELIGIBLE_CLASS_YEAR"
    return "ELIGIBLE"


def recompute_petition_counters(candidacy):
    """Recompute the five conserved signature counters of one candidacy.

    VERIFIED rows are re-scored one by one in (signed_at ASC, created_at ASC)
    order so re-scoring is deterministic.
    """
    rows = lookup.signatures_of(candidacy["id"])
    total = len(rows)
    pending = sum(1 for r in rows if r["status"] == "SUBMITTED")
    rejected = sum(1 for r in rows if r["status"] == "REJECTED")
    voided = sum(1 for r in rows if r["status"] == "VOIDED")

    verified = [r for r in rows if r["status"] == "VERIFIED"]
    verified.sort(key=lambda r: (r["signed_at"], r["created_at"], r["_seq"]))
    valid = 0
    for row in verified:
        verdict = signature_verdict(row, candidacy)
        db.set_fields(row, eligibility_result=verdict)
        if verdict == "ELIGIBLE":
            valid += 1
    ineligible = len(verified) - valid

    return db.set_fields(
        candidacy,
        petition_signature_total_count=total,
        petition_signature_pending_count=pending,
        petition_signature_rejected_count=rejected,
        petition_signature_voided_count=voided,
        petition_signature_valid_count=valid,
        petition_signature_ineligible_count=ineligible,
    )


# ===========================================================================
# calculations.campaign_spend_assessment  (PRD 3.4)
# ===========================================================================
def own_reported(candidacy_id):
    return sum(e["amount_cents"] for e in lookup.expenses_of(candidacy_id)
               if e["status"] in ("REPORTED", "APPROVED"))


def own_any(candidacy_id):
    return sum(e["amount_cents"] for e in lookup.expenses_of(candidacy_id))


def own_reversed(candidacy_id):
    return sum(e["amount_cents"] for e in lookup.expenses_of(candidacy_id)
               if e["status"] == "REVERSED")


def own_solo_approved(candidacy_id):
    return sum(e["amount_cents"] for e in lookup.expenses_of(candidacy_id)
               if e["status"] == "APPROVED" and not e["shared_with_slate"])


def poster_count_of(candidacy_id):
    return sum(e["quantity"] for e in lookup.expenses_of(candidacy_id)
               if e["category"] == "POSTER" and e["status"] in ("REPORTED", "APPROVED"))


def live_root(candidacy):
    return candidacy["slate_leader_candidacy_id"] or candidacy["id"]


def live_members(candidacy):
    """The live slate: the root plus every candidacy pointing at that root."""
    root = live_root(candidacy)
    members = [c for c in db.store.candidacies.values()
               if c["id"] == root or c["slate_leader_candidacy_id"] == root]
    return db.by_seq(members)


def provisional_committed(candidacy, extra_cents=0):
    """PROVISIONAL: joint-and-several over the *live* slate pool."""
    total = sum(own_reported(m["id"]) for m in live_members(candidacy))
    return total + extra_cents


def recompute_spend_for(candidacy):
    return db.set_fields(
        candidacy,
        spending_reported_cents=own_any(candidacy["id"]),
        spending_reversed_cents=own_reversed(candidacy["id"]),
        spending_committed_cents=provisional_committed(candidacy),
        poster_count=poster_count_of(candidacy["id"]),
    )


def recompute_spend_group(candidacy):
    """Recompute the ledger for every member of this candidacy's live slate."""
    for member in live_members(candidacy):
        recompute_spend_for(member)


def slate_expense_allocation(candidacy):
    """Per-line rounding, remainder to the earliest frozen member (PRD 3.4).

    Rounding once per line and then summing is the pinned behaviour; summing
    the pool first and rounding at the end produces different cents.
    """
    members = list(candidacy.get("slate_snapshot_member_ids") or [])
    if not members:
        return 0
    count = len(members)
    earliest_member = members[0]

    shared = []
    for member_id in members:
        for expense in lookup.expenses_of(member_id):
            if expense["status"] == "APPROVED" and expense["shared_with_slate"]:
                shared.append(expense)
    shared.sort(key=lambda e: (e["incurred_at"], e["created_at"], e["_seq"]))

    charge = 0
    for expense in shared:
        per_member = int(round_half_up(Decimal(expense["amount_cents"]) / Decimal(count)))
        remainder = expense["amount_cents"] - per_member * count
        charge += per_member
        if candidacy["id"] == earliest_member:
            charge += remainder
    return charge


def final_spend(candidacy):
    """FINAL: pro-rata over the frozen snapshot, APPROVED lines only."""
    return own_solo_approved(candidacy["id"]) + slate_expense_allocation(candidacy)


# ===========================================================================
# calculations.compliance_penalty_points  (PRD 3.5)
# ===========================================================================
def _case_order_key(case):
    return (case["upheld_at"], case["created_at"], case["_seq"])


def score_case(case, at_certification=False):
    """Write penalty_points, prior_upheld_count, timing_factor_applied and
    overspend_points_applied on `case` from the active spend basis."""
    candidacy = db.store.candidacies.get(case["candidacy_id"])
    election = db.store.elections.get(case["election_id"])

    base = Decimal(constants.PENALTY_BASE[case["severity"]])

    this_key = _case_order_key(case)
    prior = 0
    for other in lookup.cases_of(case["candidacy_id"]):
        if other["id"] == case["id"] or other["status"] != "UPHELD":
            continue
        if other.get("upheld_at") is None:
            continue
        if _case_order_key(other) < this_key:
            prior += 1
    repeat_multiplier = Decimal(1) + Decimal(constants.REPEAT_STEP) * Decimal(prior)

    timing = Decimal("1.0")
    if election is not None:
        opens = election.get("voting_opens_at")
        closes = election.get("voting_closes_at")
        if opens is not None and closes is not None:
            if opens <= case["upheld_at"] <= closes:
                timing = Decimal(constants.VOTING_WINDOW_FACTOR)

    if at_certification:
        basis = candidacy.get("spending_final_cents") if candidacy else None
    else:
        basis = candidacy.get("spending_committed_cents") if candidacy else None
    basis = 0 if basis is None else basis
    cap = election["spending_cap_cents"] if election else 0
    overspend_cents = max(0, basis - cap)
    overspend_points = min(
        constants.OVERSPEND_POINTS_CAP,
        ceil_div(overspend_cents, constants.OVERSPEND_CENTS_PER_POINT),
    )

    raw = base * repeat_multiplier * timing + Decimal(overspend_points)
    points = min(constants.PENALTY_POINTS_MAX, int(round_half_up(raw)))

    db.set_fields(
        case,
        prior_upheld_count=prior,
        timing_factor_applied=timing,
        overspend_points_applied=overspend_points,
        penalty_points=points,
    )
    return points


def recompute_penalty_total(candidacy):
    total = sum(c["penalty_points"] for c in lookup.cases_of(candidacy["id"])
                if c["status"] == "UPHELD")
    return db.set_fields(candidacy, penalty_points_total=total)


# ===========================================================================
# calculations.election_turnout  (PRD 3.7)
# ===========================================================================
def eligible_class_years_of_election(election_id):
    years = set()
    for office in lookup.offices_of(election_id):
        for year in office["eligible_class_years"] or []:
            years.add(year)
    return years


def freeze_electorate(election):
    """Round-1 open-voting freezes the electorate size; it never moves again."""
    years = eligible_class_years_of_election(election["id"])
    count = 0
    for student in db.store.students.values():
        if student["enrollment_status"] != "ENROLLED":
            continue
        if student["disciplinary_hold"]:
            continue
        if student["class_year"] in years:
            count += 1
    return count


def recompute_turnout(election):
    cast = sum(1 for v in db.store.votes.values()
               if v["election_id"] == election["id"]
               and v["round"] == election["current_round"]
               and v["status"] == "CAST")
    turnout = pct2(cast, election["eligible_voter_count"])
    return db.set_fields(election, ballots_cast_count=cast, turnout_pct=turnout)


# ===========================================================================
# ranking (PRD 3.8) — certified_votes DESC, valid signatures DESC, created ASC
# ===========================================================================
def rank_key(candidacy):
    return (
        -candidacy["certified_votes_count"],
        -candidacy["petition_signature_valid_count"],
        candidacy["created_at"],
        candidacy["_seq"],
    )


def ranked(candidacies):
    return sorted(candidacies, key=rank_key)
