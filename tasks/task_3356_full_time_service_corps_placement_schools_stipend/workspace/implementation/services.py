"""Business logic: calculations (per SCAFFOLD §1.3) and cascade side effects."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import store, touch, clock_date

# ---- calculation constants (SCAFFOLD §1.3) ----
STIPEND_PERIODS_PER_YEAR = 26
STIPEND_PERIOD_DAYS = 14
FULL_TERM_HOURS = Decimal("120")
MIN_PARTIAL_AWARD_HOURS = Decimal("24")
EDUCATION_AWARD_FULL_CENTS = 739500
PROJECTED_DAILY_HOURS = Decimal("8.0")
FUNDRAISING_CAP_FRACTION = Decimal("0.10")
TIGHT_HEADROOM_CENTS = 500000
INSTALLMENT_1_FRACTION = Decimal("0.5")
DAILY_HOUR_CAP = Decimal("12.0")
HOUR_QUANTUM = Decimal("0.25")
IMPROVEMENT_THRESHOLD_PCT = Decimal("5.0")


def rhu_cents(x):
    """round_half_up to integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_dec(v):
    return Decimal(str(v))


# ---- lookups -------------------------------------------------------------

def site_of_member(m):
    return store.sites.get(m["site_id"])


def members_of_site(site_id):
    return [m for m in store.members.values() if m["site_id"] == site_id]


def schools_of_site(site_id):
    return [s for s in store.schools.values() if s["site_id"] == site_id]


def teams_of_school(school_id):
    return [t for t in store.teams.values() if t["school_id"] == school_id]


def assignments_of_team(team_id):
    return [a for a in store.assignments.values() if a["team_id"] == team_id]


def assignments_of_member(member_id):
    return [a for a in store.assignments.values() if a["corps_member_id"] == member_id]


def students_of_school(school_id):
    return [s for s in store.students.values() if s["school_id"] == school_id]


def entries_of_member(member_id):
    return [e for e in store.hour_entries.values() if e["corps_member_id"] == member_id]


def payments_of_member(member_id):
    return [p for p in store.payments.values() if p["corps_member_id"] == member_id]


# ---- derived counters ----------------------------------------------------

def team_active_count(team):
    return sum(1 for a in assignments_of_team(team["id"]) if a["status"] == "ACTIVE")


def team_backfill_count(team):
    return sum(1 for a in assignments_of_team(team["id"]) if a["is_backfill"])


def team_min_members(team):
    return team["team_size_snapshot"] - 2


def member_active_assignment_count(m):
    return sum(1 for a in assignments_of_member(m["id"]) if a["status"] == "ACTIVE")


def member_active_caseload_count(m):
    return sum(1 for s in store.students.values()
               if s.get("assigned_member_id") == m["id"]
               and s["caseload_status"] == "ASSIGNED")


def verified_hours(m):
    total = Decimal("0")
    for e in entries_of_member(m["id"]):
        if e["status"] == "VERIFIED":
            total += hours_dec(e["hours"])
    return total


def verified_fundraising_hours(m):
    total = Decimal("0")
    for e in entries_of_member(m["id"]):
        if e["status"] == "VERIFIED" and e["category"] == "FUNDRAISING":
            total += hours_dec(e["hours"])
    return total


def member_net_stipend(m):
    # Running ledger: a payment contributes its net while PAID; clawback is the
    # exact compensating action returning the ledger to its prior value (I-CASH).
    return sum(p.get("_outlay_cents", 0) for p in payments_of_member(m["id"]))


def member_projection(m):
    """projected_hours_total, award_projected_cents (forward-looking variant)."""
    site = site_of_member(m)
    v = verified_hours(m)
    remaining = 0
    if site is not None:
        from db import parse_date
        end = parse_date(site["service_year_end"])
        today = clock_date()
        if today < end:
            remaining = (end - today).days
    projected = v + Decimal(remaining) * PROJECTED_DAILY_HOURS
    if projected >= FULL_TERM_HOURS:
        award = EDUCATION_AWARD_FULL_CENTS
    elif projected >= MIN_PARTIAL_AWARD_HOURS:
        award = rhu_cents(Decimal(EDUCATION_AWARD_FULL_CENTS) * projected / FULL_TERM_HOURS)
    else:
        award = 0
    return projected, award


# ---- site funding ledger --------------------------------------------------

def site_ledger(s):
    member_ids = {m["id"] for m in members_of_site(s["id"])}
    pays = [p for p in store.payments.values() if p["corps_member_id"] in member_ids]
    # sum(net over PAID) - sum(net over CLAWED_BACK), read cumulatively: a
    # clawed-back payment's net was added when PAID and subtracted at clawback,
    # so the pay+clawback pair conserves cash (PRD §3.7, invariant I-CASH).
    outlay = sum(p.get("_outlay_cents", 0) for p in pays)
    total_received = (s["district_received_cents"] + s["philanthropy_received_cents"]
                      + s["federal_received_cents"])
    obligations = s["annual_stipend_cents"] * sum(
        1 for m in members_of_site(s["id"]) if m["stipend_status"] == "ACTIVE")
    headroom = total_received - outlay - obligations
    if headroom < 0:
        posture = "DEFICIT"
    elif headroom < TIGHT_HEADROOM_CENTS:
        posture = "TIGHT"
    else:
        posture = "FUNDED"
    return {
        "total_received_cents": total_received,
        "stipend_outlay_cents": outlay,
        "projected_obligations_cents": obligations,
        "funding_headroom_cents": headroom,
        "funding_posture": posture,
    }


def site_cost_share(s):
    """Per-school rounding pinned BEFORE summation."""
    i1_total = 0
    i2_total = 0
    for sc in schools_of_site(s["id"]):
        if sc["agreement_status"] in ("SIGNED", "ACTIVE", "AMENDMENT_REVIEW", "COMPLETED"):
            i1 = rhu_cents(Decimal(sc["annual_cost_share_cents"]) * INSTALLMENT_1_FRACTION)
            i1_total += i1
            i2_total += sc["annual_cost_share_cents"] - i1
    return {
        "cost_share_installment_1_cents": i1_total,
        "cost_share_installment_2_cents": i2_total,
        "cost_share_total_cents": i1_total + i2_total,
    }


# ---- stipend amounts -------------------------------------------------------

def stipend_base_amount(site):
    """Provisional variant: independent of period length."""
    return rhu_cents(Decimal(site["annual_stipend_cents"]) / Decimal(STIPEND_PERIODS_PER_YEAR))


def stipend_final_amounts(base_amount_cents, period_days, deduction_cents):
    gross = rhu_cents(Decimal(base_amount_cents) * Decimal(period_days)
                      / Decimal(STIPEND_PERIOD_DAYS))
    net = max(0, gross - deduction_cents)
    return gross, net


# ---- fundraising cap --------------------------------------------------------

def fundraising_cap_ok(m, candidate_hours):
    """Order pinned: post-verification total -> 10% floored to 0.25 -> compare."""
    t_new = verified_hours(m) + hours_dec(candidate_hours)
    cap = (t_new * FUNDRAISING_CAP_FRACTION * Decimal(4)).to_integral_value(
        rounding=ROUND_FLOOR) / Decimal(4)
    return (verified_fundraising_hours(m) + hours_dec(candidate_hours)) <= cap


# ---- evaluation metrics ------------------------------------------------------

def evaluation_metrics(school_id, period_start, period_end):
    eligible = 0
    improved = 0
    for s in students_of_school(school_id):
        if s["enrollment_status"] not in ("ACTIVE", "EXITED"):
            continue
        start = s.get("assigned_start_date")
        if start is None or start > period_end:
            continue
        end = s.get("assigned_end_date")
        if end is not None and end < period_start:
            continue
        eligible += 1
        cur = s.get("current_attendance_pct")
        if cur is not None and (Decimal(str(cur)) - Decimal(str(s["baseline_attendance_pct"]))) >= IMPROVEMENT_THRESHOLD_PCT:
            improved += 1
    if eligible == 0:
        pct = 0.0
    else:
        pct = float((Decimal(100) * Decimal(improved) / Decimal(eligible)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP))
    return eligible, improved, pct


# ---- cascades ----------------------------------------------------------------

def _end_assignment_record(a, end_date):
    a["status"] = "ENDED"
    a["end_date"] = end_date
    touch(a)


def _reevaluate_team_after_loss(team):
    """DEPLOYED team dropping below min staffing slides to UNDERSTAFFED."""
    if team["status"] == "DEPLOYED" and team_active_count(team) < team_min_members(team):
        team["status"] = "UNDERSTAFFED"


def end_assignment_manual(a, end_date):
    _end_assignment_record(a, end_date)
    team = store.teams[a["team_id"]]
    _reevaluate_team_after_loss(team)
    touch(team)


def _link3_member_cascade(member_id):
    """Dissolution link 3: member whose last ACTIVE assignment just ended and
    whose service_status is ACTIVE gets stipend suspended (if ACTIVE) and
    SCHEDULED payments forfeited with TEAM_DISSOLVED."""
    m = store.members.get(member_id)
    if m is None:
        return
    if member_active_assignment_count(m) != 0:
        return
    if m["service_status"] != "ACTIVE":
        return
    changed = False
    if m["stipend_status"] == "ACTIVE":
        m["stipend_status"] = "SUSPENDED"
        changed = True
    for p in payments_of_member(member_id):
        if p["status"] == "SCHEDULED":
            p["status"] = "FORFEITED"
            p["decision_reason"] = "TEAM_DISSOLVED"
            touch(p)
    if changed:
        touch(m)


def dissolve_team(team, date_str):
    ended_member_ids = []
    for a in assignments_of_team(team["id"]):
        if a["status"] == "ACTIVE":
            _end_assignment_record(a, date_str)
            ended_member_ids.append(a["corps_member_id"])
    team["status"] = "DISSOLVED"
    touch(team)
    for mid in ended_member_ids:
        _link3_member_cascade(mid)


def complete_team(team, date_str):
    for a in assignments_of_team(team["id"]):
        if a["status"] == "ACTIVE":
            _end_assignment_record(a, date_str)
    team["status"] = "COMPLETED"
    touch(team)


def terminate_school(school, date_str):
    """LINK 1 teams -> DISSOLVED; LINK 2 assignments ended; LINK 3 member
    stipend/payment cascade; students exited and released."""
    for t in teams_of_school(school["id"]):
        if t["status"] in ("FORMING", "DEPLOYED", "UNDERSTAFFED"):
            dissolve_team(t, date_str)
    for s in students_of_school(school["id"]):
        if s["enrollment_status"] == "ACTIVE":
            s["enrollment_status"] = "EXITED"
            if s["caseload_status"] == "ASSIGNED":
                s["caseload_status"] = "UNASSIGNED"
                s["assigned_end_date"] = date_str
                s["assigned_member_id"] = None
            touch(s)


def complete_school_agreement(school, date_str):
    for t in teams_of_school(school["id"]):
        if t["status"] in ("DEPLOYED", "UNDERSTAFFED"):
            complete_team(t, date_str)


def member_exit(m, exit_type, exit_date_str):
    """Award certification (chronological variant) + full exit cascade."""
    v = verified_hours(m)
    if exit_type == "COMPLETED_TERM":
        m["award_status"] = "EARNED_FULL"
        m["award_amount_cents"] = EDUCATION_AWARD_FULL_CENTS
        m["service_status"] = "COMPLETED"
    else:
        m["service_status"] = "EXITED_EARLY"
        if exit_type == "COMPELLING_CIRCUMSTANCE" and v >= MIN_PARTIAL_AWARD_HOURS:
            m["award_status"] = "EARNED_PARTIAL"
            m["award_amount_cents"] = rhu_cents(
                Decimal(EDUCATION_AWARD_FULL_CENTS) * v / FULL_TERM_HOURS)
        else:
            m["award_status"] = "FORFEITED"
            m["award_amount_cents"] = 0
    m["exit_type"] = exit_type
    m["exit_date"] = exit_date_str
    # LINK 1 + LINK 2
    for a in assignments_of_member(m["id"]):
        if a["status"] == "ACTIVE":
            _end_assignment_record(a, exit_date_str)
            team = store.teams[a["team_id"]]
            _reevaluate_team_after_loss(team)
            touch(team)
    # caseload release
    for s in store.students.values():
        if s.get("assigned_member_id") == m["id"] and s["caseload_status"] == "ASSIGNED":
            s["caseload_status"] = "UNASSIGNED"
            s["assigned_end_date"] = exit_date_str
            s["assigned_member_id"] = None
            touch(s)
    # payments forfeited
    for p in payments_of_member(m["id"]):
        if p["status"] in ("SCHEDULED", "APPROVED"):
            p["status"] = "FORFEITED"
            p["decision_reason"] = "MEMBER_EXITED"
            touch(p)
    m["stipend_status"] = "ENDED"
    touch(m)
