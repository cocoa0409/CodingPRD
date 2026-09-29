"""Derived state: training currency, contact eligibility, eligibility
projection, club posture and the four lazily evaluated clock transitions.

Nothing here is ever asserted by a caller (PRD section 1, second design
commitment): every value below is recomputed from its inputs.
"""

import calc
import clock
import store


# ---------------------------------------------------------------- measures --
def has_measure(member_id, statuses):
    return any(m["status"] in statuses for m in store.measures_of(member_id))


# --------------------------------------------------------------- horizons --
def required_courses(member):
    """Every published course whose required_for_tiers holds the member's
    CURRENT required_tier."""
    tier = member["required_tier"]
    return [c for c in store.TRAINING_COURSES.values() if tier in c["required_for_tiers"]]


def screening_expiry(member):
    """Latest expires_at among the member's ADJUDICATED clearing orders."""
    best = None
    for o in store.orders_of(member["id"]):
        if o["status"] != "ADJUDICATED":
            continue
        if o["disposition"] not in ("CLEAR", "NON_DISQUALIFYING_RECORD"):
            continue
        if o["expires_at"] is None:
            continue
        if best is None or o["expires_at"] > best:
            best = o["expires_at"]
    return best


def per_course_expiry(member, course, statuses):
    best = None
    for a in store.assignments_of(member["id"]):
        if a["course_code"] != course["code"] or a["status"] not in statuses:
            continue
        if a["status"] == "COMPLETED":
            base = a["completed_at"]
        else:
            base = a["due_at"]
        exp = clock.plus_days(base, course["validity_days"])
        if exp is None:
            continue
        if best is None or exp > best:
            best = exp
    return best


def training_expiry(member, statuses):
    """Null when any required course lacks a candidate assignment, otherwise
    the earliest per-course expiry."""
    courses = required_courses(member)
    if not courses:
        return None
    earliest = None
    for c in courses:
        exp = per_course_expiry(member, c, statuses)
        if exp is None:
            return None
        if earliest is None or exp < earliest:
            earliest = exp
    return earliest


VARIANT_STATUSES = {
    "AUDIT_SNAPSHOT": ("COMPLETED",),
    "RENEWAL_FORWARD": ("COMPLETED", "IN_PROGRESS"),
}


def projection(member, variant="AUDIT_SNAPSHOT"):
    s_exp = screening_expiry(member)
    t_exp = training_expiry(member, VARIANT_STATUSES[variant])
    if s_exp is None or t_exp is None:
        projected = None
    else:
        projected = s_exp if s_exp <= t_exp else t_exp
    return {"screening_expiry": s_exp, "training_expiry": t_exp, "projected": projected}


def stamp_eligible_through(member):
    member["eligible_through"] = projection(member, "AUDIT_SNAPSHOT")["projected"]


# ------------------------------------------------------- member derivation --
def training_status(member):
    exp = training_expiry(member, ("COMPLETED",))
    if exp is None:
        return "NEVER"
    if clock.now() >= exp:
        return "LAPSED"
    return "CURRENT"


def contact_eligibility(member):
    """Three clauses, top to bottom, first match wins (PRD section 3.4)."""
    if member["screening_status"] == "DISQUALIFIED" or has_measure(member["id"], ("PERMANENT",)):
        return "PROHIBITED"
    if (has_measure(member["id"], ("ACTIVE",))
            or member["screening_status"] in ("UNSCREENED", "SCREENING_ORDERED", "FLAGGED", "EXPIRED")
            or member["training_status"] in ("NEVER", "LAPSED")):
        return "RESTRICTED"
    return "ELIGIBLE"


def records_retained_through(member):
    """Later of eligible_through + 7 years and the latest case closure + 7."""
    horizons = []
    if member["eligible_through"] is not None:
        horizons.append(clock.plus_years(member["eligible_through"], calc.RETENTION_YEARS))
    closures = [c["closed_at"] for c in store.cases_of_member(member["id"]) if c.get("closed_at")]
    if closures:
        horizons.append(clock.plus_years(max(closures), calc.RETENTION_YEARS))
    if not horizons:
        return None
    return max(horizons)


def blocking_reasons(member):
    reasons = []
    if member["screening_status"] == "DISQUALIFIED":
        reasons.append("SCREENING_DISQUALIFIED")
    if has_measure(member["id"], ("PERMANENT",)):
        reasons.append("PERMANENT_MEASURE")
    if has_measure(member["id"], ("ACTIVE",)):
        reasons.append("ACTIVE_INTERIM_MEASURE")
    if member["screening_status"] != "CLEARED" and member["screening_status"] != "DISQUALIFIED":
        reasons.append("SCREENING_NOT_CURRENT")
    if member["training_status"] != "CURRENT":
        reasons.append("TRAINING_NOT_CURRENT")
    if member["membership_status"] != "ACTIVE":
        reasons.append("MEMBERSHIP_NOT_ACTIVE")
    return reasons


def recompute_member(member):
    member["training_status"] = training_status(member)
    member["contact_eligibility"] = contact_eligibility(member)
    member["active_assignment_count"] = len([
        a for a in store.coach_assignments_of_member(member["id"]) if a["status"] == "ACTIVE"
    ])
    member["records_retained_through"] = records_retained_through(member)


# --------------------------------------------------------- club derivation --
def compliance_posture(club):
    if club["sanction_status"] in ("SUSPENDED", "TERMINATED"):
        return "FROZEN"
    if club["critical_open_finding_count"] >= calc.CRITICAL_FREEZE_THRESHOLD:
        return "FROZEN"
    if club["open_finding_count"] >= calc.RESTRICT_FINDING_THRESHOLD:
        return "RESTRICTED"
    if club["restricted_member_count"] >= 1:
        return "RESTRICTED"
    return "OPEN"


def recompute_club(club):
    open_count = 0
    critical_count = 0
    for audit in store.audits_of_club(club["id"]):
        for f in store.findings_of_audit(audit["id"]):
            if f["status"] == "OPEN":
                open_count += 1
                if f["severity"] == "CRITICAL":
                    critical_count += 1
    club["open_finding_count"] = open_count
    club["critical_open_finding_count"] = critical_count
    restricted = set()
    active = 0
    for a in store.coach_assignments_of_club(club["id"]):
        if a["status"] == "ACTIVE":
            active += 1
        if a["status"] in ("ACTIVE", "SUSPENDED"):
            m = store.MEMBERS.get(a["member_id"])
            if m is not None and m["contact_eligibility"] in ("RESTRICTED", "PROHIBITED"):
                restricted.add(m["id"])
    club["active_assignment_count"] = active
    club["restricted_member_count"] = len(restricted)
    club["compliance_posture"] = compliance_posture(club)


def recompute_audit(audit):
    findings = store.findings_of_audit(audit["id"])
    audit["finding_total_count"] = len(findings)
    audit["open_finding_count"] = len([f for f in findings if f["status"] == "OPEN"])
    audit["remediated_finding_count"] = len([f for f in findings if f["status"] == "REMEDIATED"])
    audit["waived_finding_count"] = len([f for f in findings if f["status"] == "WAIVED"])


# ------------------------------------------------- lazily evaluated lapses --
def sync():
    """Apply the four clock-driven transitions of PRD section 2.5 and refresh
    every derived value. Called at the start of every request and again before
    a mutating handler serializes its response."""
    now = clock.now()
    for a in store.TRAINING_ASSIGNMENTS.values():
        if a["status"] == "ASSIGNED" and a["due_at"] is not None and now >= a["due_at"]:
            a["status"] = "EXPIRED"
            store.touch(a)
    for a in store.COACH_ASSIGNMENTS.values():
        if a["status"] == "ACTIVE" and a["season_end"] is not None and now >= a["season_end"]:
            a["status"] = "EXPIRED"
            store.touch(a)
    for m in store.MEMBERS.values():
        if (m["screening_status"] == "CLEARED" and m["screening_expires_at"] is not None
                and now >= m["screening_expires_at"]):
            m["screening_status"] = "EXPIRED"
            store.touch(m)
        if (m["membership_status"] == "ACTIVE" and m["eligible_through"] is not None
                and now >= m["eligible_through"]):
            m["membership_status"] = "LAPSED"
            store.touch(m)
    recompute_all()


def recompute_all():
    for m in store.MEMBERS.values():
        recompute_member(m)
    for a in store.CLUB_AUDITS.values():
        recompute_audit(a)
    for c in store.CLUBS.values():
        recompute_club(c)
