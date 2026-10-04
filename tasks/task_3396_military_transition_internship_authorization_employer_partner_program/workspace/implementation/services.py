from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants
import db
from util import round2, serialize, fmt_date


def touch(entity):
    """A mutation event on an entity: refresh updated_at and bump version by 1."""
    entity["updated_at"] = db.now()
    entity["version"] += 1


def recompute_filled_count(opening):
    opening["filled_count"] = sum(
        1
        for m in db.store.matches.values()
        if m["employer_opening_id"] == opening["id"]
        and m["match_status"] in constants.NON_TERMINAL_MATCH_STATUSES
    )


def recompute_active_match_count(member):
    member["active_match_count"] = sum(
        1
        for m in db.store.matches.values()
        if m["service_member_id"] == member["id"]
        and m["match_status"] in constants.NON_TERMINAL_MATCH_STATUSES
    )


def recompute_ratios(match):
    objectives = match["learning_objectives"]
    if not objectives:
        match["resolution_ratio"] = 1.0
        match["mastery_ratio"] = 1.0
        return
    resolved = sum(1 for o in objectives if o["status"] in ("ACHIEVED", "EXCUSED"))
    total_hours = sum(o["weight_hours"] for o in objectives)
    achieved_hours = sum(o["weight_hours"] for o in objectives if o["status"] == "ACHIEVED")
    match["resolution_ratio"] = round2(resolved / len(objectives))
    match["mastery_ratio"] = round2(achieved_hours / total_hours) if total_hours > 0 else 1.0


def serialize_member(member):
    out = serialize(member)
    out["days_until_separation"] = (member["separation_date"] - db.now().date()).days
    return out


def _sorted(entities):
    # created_at ASC; _seq (insertion order) is the deterministic tiebreak, never id.
    return sorted(entities, key=lambda e: e["_seq"])


# ---------------------------------------------------------------- cascades ---

def cascade_member_separated(member):
    """Caller has already flipped service_status -> SEPARATED and touched the member.
    Voids PROPOSED/INSTALLATION_APPROVED matches, terminates ACTIVE ones (SEPARATION),
    recomputes affected opening ledgers and the member's own ledger."""
    affected_opening_ids = []
    mine = [m for m in db.store.matches.values() if m["service_member_id"] == member["id"]]
    for m in _sorted(mine):
        if m["match_status"] in ("PROPOSED", "INSTALLATION_APPROVED"):
            m["match_status"] = "MATCH_VOIDED"
            touch(m)
        elif m["match_status"] == "ACTIVE":
            m["match_status"] = "TERMINATED_EARLY"
            m["termination_reason"] = "SEPARATION"
            touch(m)
        else:
            continue
        if m["employer_opening_id"] not in affected_opening_ids:
            affected_opening_ids.append(m["employer_opening_id"])
    for oid in affected_opening_ids:
        opening = db.store.openings.get(oid)
        if opening is not None:
            before = opening["filled_count"]
            recompute_filled_count(opening)
            if opening["filled_count"] != before:
                touch(opening)
    recompute_active_match_count(member)


def cascade_opening_closed(opening):
    """Caller set status -> CLOSED. Voids PROPOSED/INSTALLATION_APPROVED matches on this
    opening (ACTIVE matches are in flight and unaffected), recomputes ledgers.
    Caller touches the opening itself."""
    affected_member_ids = []
    mine = [m for m in db.store.matches.values() if m["employer_opening_id"] == opening["id"]]
    for m in _sorted(mine):
        if m["match_status"] in ("PROPOSED", "INSTALLATION_APPROVED"):
            m["match_status"] = "MATCH_VOIDED"
            touch(m)
            if m["service_member_id"] not in affected_member_ids:
                affected_member_ids.append(m["service_member_id"])
    recompute_filled_count(opening)
    for mid in affected_member_ids:
        member = db.store.members.get(mid)
        if member is not None:
            before = member["active_match_count"]
            recompute_active_match_count(member)
            if member["active_match_count"] != before:
                touch(member)


def cascade_employer_revoked(employer):
    """Caller set authorization_status -> REVOKED. Closes OPEN openings, voids
    PROPOSED/INSTALLATION_APPROVED matches, terminates ACTIVE ones (EMPLOYER_REVOKED),
    recomputes ledgers. Caller touches the employer itself."""
    affected_member_ids = []
    own_openings = [o for o in db.store.openings.values() if o["employer_id"] == employer["id"]]
    closed_now = set()
    for o in _sorted(own_openings):
        if o["status"] == "OPEN":
            o["status"] = "CLOSED"
            closed_now.add(o["id"])
    mine = [m for m in db.store.matches.values() if m["employer_id"] == employer["id"]]
    for m in _sorted(mine):
        if m["match_status"] in ("PROPOSED", "INSTALLATION_APPROVED"):
            m["match_status"] = "MATCH_VOIDED"
        elif m["match_status"] == "ACTIVE":
            m["match_status"] = "TERMINATED_EARLY"
            m["termination_reason"] = "EMPLOYER_REVOKED"
        else:
            continue
        touch(m)
        if m["service_member_id"] not in affected_member_ids:
            affected_member_ids.append(m["service_member_id"])
    for o in own_openings:
        before = o["filled_count"]
        recompute_filled_count(o)
        if o["id"] in closed_now or o["filled_count"] != before:
            touch(o)
    for mid in affected_member_ids:
        member = db.store.members.get(mid)
        if member is not None:
            before = member["active_match_count"]
            recompute_active_match_count(member)
            if member["active_match_count"] != before:
                touch(member)


# ------------------------------------------------------------------ sweeps ---

def run_sweeps():
    """Pinned order: (1) employer lapse, (2) member separation, (3) match auto-start.
    Within each sweep entities process in created_at ASC (insertion order)."""
    clock_date = db.now().date()

    employers_lapsed = 0
    for e in _sorted(db.store.employers.values()):
        if (
            e["authorization_status"] == "AUTHORIZED"
            and e["next_review_due_date"] is not None
            and clock_date > e["next_review_due_date"].date()
        ):
            e["authorization_status"] = "AUTHORIZATION_LAPSED"
            touch(e)
            employers_lapsed += 1

    members_separated = 0
    for m in _sorted(db.store.members.values()):
        if m["service_status"] == "ACTIVE_DUTY" and m["separation_date"] <= clock_date:
            m["service_status"] = "SEPARATED"
            touch(m)
            members_separated += 1
            cascade_member_separated(m)

    matches_activated = 0
    for m in _sorted(db.store.matches.values()):
        if m["match_status"] == "INSTALLATION_APPROVED" and m["start_date"] <= clock_date:
            member = db.store.members.get(m["service_member_id"])
            if member is not None and member["service_status"] == "ACTIVE_DUTY":
                m["match_status"] = "ACTIVE"
                touch(m)
                matches_activated += 1

    return employers_lapsed, members_separated, matches_activated


# ------------------------------------------------------------ calculations ---

def compute_compliance_score(findings):
    """Per-finding deduction rounded half-up to 2dp FIRST, then summed, then capped
    at AUDIT_BASE_SCORE. score = base - capped total."""
    seen = {}
    total = Decimal("0")
    repeat = Decimal(str(constants.REPEAT_MULTIPLIER))
    for f in findings:
        code = f["finding_code"]
        prior = seen.get(code, 0)
        seen[code] = prior + 1
        base = Decimal(str(constants.SEVERITY_BASE[f["severity"]]))
        deduction = (base * (Decimal("1") + repeat * prior)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total += deduction
    base_score = Decimal(str(constants.AUDIT_BASE_SCORE))
    total_deduction = min(total, base_score)
    score = (base_score - total_deduction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)


def hiring_rate(employer, variant, cohort_start, cohort_end):
    clock_date = db.now().date()
    completed = [
        m
        for m in _sorted(db.store.matches.values())
        if m["employer_id"] == employer["id"] and m["match_status"] == "COMPLETED"
    ]
    if variant == "COHORT":
        window_start, window_end = cohort_start, cohort_end

        def in_window(m):
            member = db.store.members.get(m["service_member_id"])
            if member is None:
                return False
            sep = member["separation_date"]
            return window_start <= sep <= window_end

    else:  # ROLLING (default)
        window_end = clock_date
        window_start = clock_date - timedelta(days=constants.ROLLING_HIRING_WINDOW_DAYS)

        def in_window(m):
            ca = m["completed_at"]
            if ca is None:
                return False
            return window_start <= ca.date() <= window_end

    completions = [m for m in completed if in_window(m)]
    converted = 0
    for m in completions:
        cr = next(
            (c for c in db.store.conversions.values() if c["internship_match_id"] == m["id"]),
            None,
        )
        if cr is not None and cr["hired"]:
            converted += 1
    count = len(completions)
    if count == 0:
        rate = 0.0
    else:
        rate = float(
            (Decimal(100 * converted) / Decimal(count)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
    return {
        "employer_id": employer["id"],
        "variant": variant,
        "window_start_date": fmt_date(window_start),
        "window_end_date": fmt_date(window_end),
        "completed_count": count,
        "converted_count": converted,
        "hiring_rate_pct": rate,
    }
