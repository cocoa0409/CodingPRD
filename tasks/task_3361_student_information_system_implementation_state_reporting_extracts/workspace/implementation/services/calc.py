"""Business calculations: membership days, FTE variants, absence posture,
truancy exit inference, severity scoring, escalation priority.

Precision rules (PRD section 2.6):
- membership/counts are integers (whole calendar days, half-open intervals)
- fte_adm / fte_count_date: round-half-up to exactly 3 decimals, cap 1.0
- absence_rate carried as an exact rational (Fraction), compared unrounded
- escalation hours are whole hours, floor
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from dates import whole_days
from db import get_clock, new_id, stamp_new, store

AT_RISK_THRESHOLD = Fraction(1, 20)          # 0.05
DEFAULT_CHRONIC_THRESHOLD = Fraction(1, 10)  # 0.10 (spec default)
DEFAULT_AUTO_WITHDRAW_STREAK = 10            # spec default
FTE_CAP = Fraction(1, 1)
SEVERITY_CAP = 100
ESCALATION_WINDOW_HOURS = 48

GRADES = ["KG", "01", "02", "03", "04", "05", "06",
          "07", "08", "09", "10", "11", "12"]


def next_grade(grade):
    return GRADES[GRADES.index(grade) + 1]


def get_published_spec(state_code):
    """The at-most-one PUBLISHED spec for a state_code, or None."""
    for spec in store["specs"].values():
        if spec["state_code"] == state_code and spec["status"] == "PUBLISHED":
            return spec
    return None


def district_of_year(year):
    return store["districts"].get(year["district_id"])


def round3(frac):
    """round_half_up to exactly 3 decimal places -> Decimal."""
    d = Decimal(frac.numerator) / Decimal(frac.denominator)
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def recompute_enrollment(e):
    """Pinned recompute: membership -> absence_weight_sum -> rate -> posture,
    then both FTE variants. Absence events on/after a set exit_date are excluded
    (an event on the exit date itself does not count)."""
    year = store["school_years"][e["school_year_id"]]
    district = district_of_year(year)
    spec = get_published_spec(district["state_code"]) if district else None

    # 1. membership_days = prior_segment_days + current segment days.
    #    A withdrawn segment has already been folded into prior_segment_days,
    #    so its current contribution is 0 (no double counting).
    if e.get("segment_closed"):
        current = 0
    else:
        seg_start = max(e["entry_date"], year["start_date"])
        seg_end = min(e["exit_date"], year["end_date"]) if e["exit_date"] is not None else year["end_date"]
        current = max(0, whole_days(seg_start, seg_end))
    e["membership_days"] = e["prior_segment_days"] + current

    # 2. absence_weight_sum = event weights (date < exit when exit set)
    #    + action_days of APPROVED OSS incidents (full 1.0 per day).
    total = Fraction(0)
    for ev in store["attendance_events"].values():
        if ev["enrollment_id"] != e["id"]:
            continue
        if e["exit_date"] is not None and not (ev["attendance_date"] < e["exit_date"]):
            continue
        total += Fraction(str(ev["absence_weight"]))
    for inc in store["incidents"].values():
        if (inc["enrollment_id"] == e["id"] and inc["status"] == "APPROVED"
                and inc["action_type"] == "OSS"):
            total += Fraction(inc["action_days"], 1)
    e["absence_weight_sum"] = total

    # 3. absence_rate as exact rational; 0.0 when membership_days == 0.
    md = e["membership_days"]
    rate = Fraction(0) if md == 0 else total / md
    e["absence_rate"] = rate

    # 4. absence_posture: >= chronic threshold -> CHRONIC (inclusive boundary),
    #    >= 0.05 -> AT_RISK, else CLEAR.
    chronic = (Fraction(str(spec["chronic_absence_threshold"]))
               if spec else DEFAULT_CHRONIC_THRESHOLD)
    if rate >= chronic:
        e["absence_posture"] = "CHRONIC"
    elif rate >= AT_RISK_THRESHOLD:
        e["absence_posture"] = "AT_RISK"
    else:
        e["absence_posture"] = "CLEAR"

    # 5. FTE variants, each rounded half-up to 3 decimals and capped at 1.0.
    weight = Fraction(str(e["program_weight"]))
    base = Fraction(md, year["instructional_days"]) * weight
    e["fte_adm"] = round3(min(FTE_CAP, base))
    eligible = (e["entry_date"] <= year["count_date"]
                and (e["exit_date"] is None or e["exit_date"] > year["count_date"]))
    e["fte_count_date"] = round3(min(FTE_CAP, weight)) if eligible else Decimal("0.000")
    return e


def create_enrollment_record(student_id, year, grade_level, entry_date,
                             program_code=None, state_program_code=None,
                             program_weight=1.0):
    e = {
        "id": new_id(),
        "student_id": student_id,
        "school_year_id": year["id"],
        "grade_level": grade_level,
        "program_code": program_code,
        "state_program_code": state_program_code,
        "program_weight": program_weight,
        "entry_date": entry_date,
        "exit_date": None,
        "prior_segment_days": 0,
        "membership_days": 0,
        "absence_weight_sum": Fraction(0),
        "absence_rate": Fraction(0),
        "fte_adm": Decimal("0.000"),
        "fte_count_date": Decimal("0.000"),
        "lifecycle": "ACTIVE",
        "absence_posture": "CLEAR",
        "segment_closed": False,
    }
    stamp_new(e)
    store["enrollments"][e["id"]] = e
    recompute_enrollment(e)
    return e


def infer_exit_date(e):
    """Truancy exit inference: first run of `auto_withdraw_streak` consecutive
    calendar days each holding an unexcused full-day (weight 1.0) event in the
    current segment; exit is the attendance_date of the run's Nth day. If no
    run exists, the logical clock's current date."""
    year = store["school_years"][e["school_year_id"]]
    district = district_of_year(year)
    spec = get_published_spec(district["state_code"]) if district else None
    streak = spec["auto_withdraw_streak"] if spec else DEFAULT_AUTO_WITHDRAW_STREAK

    events = [ev for ev in store["attendance_events"].values()
              if ev["enrollment_id"] == e["id"] and ev["attendance_date"] >= e["entry_date"]]
    events.sort(key=lambda ev: (ev["attendance_date"], ev["created_at"], ev.get("_seq", 0)))
    qual_days = sorted({ev["attendance_date"].date() for ev in events
                        if (not ev["is_excused"]) and float(ev["absence_weight"]) == 1.0})
    run = []
    prev = None
    for d in qual_days:
        if prev is not None and (d - prev).days == 1:
            run.append(d)
        else:
            run = [d]
        prev = d
        if len(run) >= streak:
            nth = run[streak - 1]
            return datetime(nth.year, nth.month, nth.day, tzinfo=timezone.utc)
    clk = get_clock()
    return datetime(clk.year, clk.month, clk.day, tzinfo=timezone.utc)


def severity_score(severity_base, action_days, action_type):
    """CAPPED variant (NONE/ISS/OSS) clips at 100; EXPULSION is uncapped."""
    raw = severity_base * action_days
    if action_type == "EXPULSION":
        return raw
    return min(raw, SEVERITY_CAP)


def escalation_priority_for(closes_at):
    """Whole hours from the logical clock to the window close (floor);
    <= 48 hours (inclusive boundary) is URGENT, otherwise STANDARD."""
    clk = get_clock()
    seconds = (closes_at - clk).total_seconds()
    hours = int(seconds // 3600)
    return "URGENT" if hours <= ESCALATION_WINDOW_HOURS else "STANDARD"
