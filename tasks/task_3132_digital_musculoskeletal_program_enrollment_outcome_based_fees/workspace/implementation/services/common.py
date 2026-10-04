"""Derived-field recomputation shared across resources.

Everything here reads the live tables and the logical clock, and writes stored
derived quantities on the records it is handed.  Version/timestamp bumps are
left to the calling endpoint or cascade so that each scaffold-declared
"increments X.version by 1" fires exactly once.
"""

from db import STORE, create, new_record
from utils import cents, d, round1, round2, week_of

# --- exercise sessions ------------------------------------------------------


def sessions_of(enrollment_id):
    return [s for s in STORE.all("ExerciseSession")
            if s["enrollment_id"] == enrollment_id]


def measurements_of(enrollment_id, statuses=None):
    rows = [m for m in STORE.all("OutcomeMeasurement")
            if m["enrollment_id"] == enrollment_id]
    if statuses is not None:
        rows = [m for m in rows if m["measurement_status"] in statuses]
    rows.sort(key=lambda m: (m["measurement_week"], m["created_at"], m["id"]))
    return rows


def claim_lines_of(enrollment_id):
    return [c for c in STORE.all("ClaimLine")
            if c["enrollment_id"] == enrollment_id]


def outreach_of(enrollment_id):
    return [o for o in STORE.all("OutreachContact")
            if o["enrollment_id"] == enrollment_id]


def track_of(enrollment):
    return STORE.get("ProgramTrack", enrollment.get("program_track_id"))


def member_of(enrollment):
    return STORE.get("Member", enrollment.get("member_id"))


# --- weeks ------------------------------------------------------------------


def weeks_active(enrollment):
    """Whole weeks the enrollment has been active (PRD §3.2): the lattice distance
    from the week it activated in to the week the clock now sits in.  A member who
    activated in the current week has a count of 0."""
    enrolled_week = enrollment.get("enrolled_week")
    if enrolled_week is None:
        return 0
    return week_of(STORE.clock) - enrolled_week


def current_pain_score(enrollment):
    """The member's latest recorded pain score, else their baseline."""
    rows = measurements_of(
        enrollment["id"], statuses=("RECORDED", "FINALIZED")
    )
    if rows:
        return d(rows[-1]["pain_score"])
    member = member_of(enrollment)
    if member is not None:
        return d(member["baseline_pain_score"])
    return d(0)


# --- adherence --------------------------------------------------------------


def adherence_inclusion(enrollment):
    """Sessions of THIS enrollment in [enrolled_week, current week)."""
    if enrollment["enrollment_status"] == "DROPPED":
        return []
    enrolled_week = enrollment.get("enrolled_week")
    if enrolled_week is None:
        return []
    week = week_of(STORE.clock)
    return [s for s in sessions_of(enrollment["id"])
            if enrolled_week <= s["session_week"] < week]


def adherence_rate(enrollment):
    included = adherence_inclusion(enrollment)
    denominator = sum(d(s["adherence_denominator"]) for s in included)
    if denominator == 0:
        return 0.0
    numerator = sum(d(s["adherence_numerator"]) for s in included)
    return round2(numerator / denominator)


def recompute_adherence(enrollment):
    """Recompute adherence_rate and its scored-through week."""
    enrollment["adherence_rate"] = adherence_rate(enrollment)
    enrollment["adherence_scored_through_week"] = week_of(STORE.clock)


def recompute_weeks_active(enrollment):
    enrollment["weeks_active"] = weeks_active(enrollment)


def recompute_milestone(enrollment):
    track = track_of(enrollment)
    if track is None:
        enrollment["projected_engagement_milestone"] = 0
        return
    reached = (
        enrollment["weeks_active"] >= 1
        and d(enrollment["adherence_rate"]) >= d(track["min_adherence_rate"])
    )
    enrollment["projected_engagement_milestone"] = 1 if reached else 0


def recompute_projection(enrollment):
    """adherence + weeks_active + milestone (the session-completion bundle)."""
    recompute_adherence(enrollment)
    recompute_weeks_active(enrollment)
    recompute_milestone(enrollment)


# --- attrition risk ---------------------------------------------------------


def consecutive_missed(enrollment):
    enrolled_week = enrollment.get("enrolled_week")
    if enrolled_week is None:
        return 0
    by_week = {}
    for session in sessions_of(enrollment["id"]):
        by_week.setdefault(session["session_week"], []).append(session)
    week = week_of(STORE.clock) - 1
    run = 0
    while week >= enrolled_week:
        rows = by_week.get(week)
        if not rows:
            break
        if all(row["session_status"] == "MISSED" for row in rows):
            run += 1
            week -= 1
        else:
            break
    return run


def failed_outreach_count(enrollment):
    rows = [o for o in outreach_of(enrollment["id"])
            if 1 <= o["contact_week"] <= 4 and o["outreach_status"] == "FAILED"]
    return len(rows)


def dropout_risk(enrollment):
    missed = consecutive_missed(enrollment)
    failed = failed_outreach_count(enrollment)
    rate = d(enrollment["adherence_rate"])
    active = enrollment["weeks_active"]
    raw = (
        12 * missed
        + 15 * failed
        + (40 if rate < d("0.35") else 0)
        + (20 if active >= 4 and rate < d("0.50") else 0)
    )
    return min(100, raw), week_of(STORE.clock)


def recompute_risk(enrollment):
    score, as_of = dropout_risk(enrollment)
    enrollment["dropout_risk_score"] = score
    enrollment["dropout_risk_as_of_week"] = as_of
    enrollment["coach_escalation_required"] = score >= 60
    if enrollment["coach_escalation_required"]:
        member = member_of(enrollment)
        if member is not None:
            member["coach_escalated"] = True



# --- outcome measurements ---------------------------------------------------


def window_range(enrollment, rank):
    enrolled_week = enrollment.get("enrolled_week")
    if enrolled_week is None:
        enrolled_week = 0
    start = enrolled_week + 4 * (rank - 1)
    return start, start + 3


def existing_rank(enrollment, measurement_week, exclude_id=None):
    """A rank already claimed by a live/replacement measurement, else None."""
    for row in measurements_of(enrollment["id"]):
        if row["id"] == exclude_id:
            continue
        if row["window_start_week"] is None:
            continue
        if row["window_start_week"] <= measurement_week <= row["window_end_week"]:
            return row["claim_window_rank"]
    return None


def next_rank(enrollment, exclude_id=None):
    ranks = [m["claim_window_rank"] for m in measurements_of(enrollment["id"])
             if m["id"] != exclude_id]
    return (max(ranks) + 1) if ranks else 1


def seed_window(enrollment, measurement):
    """Stamp the claim-window anchor and the baselines for a new measurement.

    The accepted window ranges are the enrollment's existing measurement
    windows, so an enrollment that records corrections into an already-open
    range is held to the same four-week block.  Every other recording opens a
    fresh four-week window anchored at its own measurement week, so a
    measurement booked mid-window is still anchored (and bounded) by its own
    week rather than silently re-pointed at an earlier measurement's claims.
    """
    prior = [m for m in measurements_of(enrollment["id"])
             if m["id"] != measurement["id"]]
    rank = existing_rank(
        enrollment, measurement["measurement_week"], exclude_id=measurement["id"]
    )
    if rank is None:
        rank = next_rank(enrollment, exclude_id=measurement["id"])
    # The window is anchored on the enrollment, not on the measurement: rank N of
    # an enrollment that activated in week W spans [W + 4*(N-1), W + 4*(N-1) + 3]
    # (PRD 3.6 / SCAFFOLD outcome_measurement).
    start, end = window_range(enrollment, rank)
    source = prior[-1:] if prior else []
    measurement["claim_window_rank"] = rank
    measurement["window_start_week"] = start
    measurement["window_end_week"] = end
    if source:
        measurement["baseline_pain_score"] = source[-1]["pain_score"]
        measurement["baseline_function_score"] = source[-1]["function_score"]
    else:
        member = member_of(enrollment)
        measurement["baseline_pain_score"] = (
            member["baseline_pain_score"] if member else 0
        )
        measurement["baseline_function_score"] = (
            member["baseline_function_score"] if member else 0
        )
    return measurement


def measurement_deltas(measurement):
    measurement["pain_delta_points"] = round1(
        d(measurement["baseline_pain_score"]) - d(measurement["pain_score"])
    )
    measurement["function_delta_points"] = round1(
        d(measurement["function_score"]) - d(measurement["baseline_function_score"])
    )


def window_engagement_rate(enrollment, measurement):
    """The enrollment's adherence as recomputed within the measurement window."""
    enrolled_week = enrollment.get("enrolled_week")
    if enrolled_week is None:
        return 0.0
    if enrollment["enrollment_status"] == "DROPPED":
        return 0.0
    start, end = measurement["window_start_week"], measurement["window_end_week"]
    included = [s for s in sessions_of(enrollment["id"])
                if start <= s["session_week"] <= end]
    denominator = sum(d(s["adherence_denominator"]) for s in included)
    if denominator == 0:
        return 0.0
    numerator = sum(d(s["adherence_numerator"]) for s in included)
    return round2(numerator / denominator)


def _severity_weight(track, severity):
    weights = (track or {}).get("severity_weights") or {}
    low = d(weights.get("LOW", 0))
    high = d(weights.get("HIGH", 0))
    # The map carries exactly LOW and HIGH; MODERATE collates to LOW.  The
    # selection over the window's evaluation weeks takes the maximum in
    # collation order, which for a HIGH line is its own week's HIGH weight.
    return high if severity == "HIGH" else low


def window_lines(enrollment, start_week, end_week, include_superseded=False):
    """Claim lines of this enrollment inside [start_week, end_week].

    The default reading takes only the current, non-superseded instances.  The
    billing-time re-evaluation instead substitutes each line's superseded
    instance in place of its current one, so a superseded family contributes
    its withdrawn/older instance rather than the replacement (SCAFFOLD 1.3).
    """
    rows = [c for c in claim_lines_of(enrollment["id"])
            if start_week <= c["claim_service_week"] <= end_week]
    if not include_superseded:
        return [c for c in rows if not c["claim_superseded"] and not c["claim_withdrawn"]]
    families = {}
    for line in rows:
        families.setdefault((line["claim_service_week"], line["claim_source"]), []).append(line)
    out = []
    for family in families.values():
        family.sort(key=lambda c: c["line_instance_version"])
        superseded = [c for c in family if c["claim_superseded"] or c["claim_withdrawn"]]
        out.append(superseded[0] if superseded else family[-1])
    return out


def attributed_savings(enrollment, measurement, include_superseded=False, rate=None,
                       lines=None):
    """Severity-weighted, adherence-weighted savings for one window."""
    track = track_of(enrollment)
    start, end = measurement["window_start_week"], measurement["window_end_week"]
    if lines is None:
        lines = window_lines(enrollment, start, end, include_superseded)
    lines = sorted(lines, key=lambda c: (
        c["claim_service_week"], c["created_at"], c["id"]
    ))
    if rate is None:
        rate = window_engagement_rate(enrollment, measurement)
    total = d(0)
    for line in lines:
        total += (
            d(line["amount_cents"])
            * _severity_weight(track, line["claim_severity"])
            * d(rate)
        )
    return cents(total)


def recompute_measurement_savings(enrollment, measurement):
    """Version-pinned reading: writes the measurement's attributed savings."""
    measurement["attributed_savings_cents"] = attributed_savings(
        enrollment, measurement
    )


def recompute_enrollment_savings(enrollment):
    total = 0
    for row in measurements_of(
        enrollment["id"], statuses=("RECORDED", "FINALIZED")
    ):
        total += int(row.get("attributed_savings_cents") or 0)
    enrollment["attributed_savings_cents"] = total


def recompute_windows_containing(enrollment, service_week):
    """Recompute every RECORDED measurement of this enrollment whose window
    contains the given claim-service week, on the version-pinned reading."""
    touched = []
    for row in measurements_of(enrollment["id"], statuses=("RECORDED",)):
        if row["window_start_week"] <= service_week <= row["window_end_week"]:
            recompute_measurement_savings(enrollment, row)
            touched.append(row)
    if touched:
        recompute_enrollment_savings(enrollment)
    return touched


# --- factory ----------------------------------------------------------------


def enrollment_row(member, eligibility_file_id, status, review_pending_since=None):
    return {
        "member_id": member["id"],
        "eligibility_file_id": eligibility_file_id,
        "program_track_id": None,
        "enrollment_status": status,
        "clinical_review_outcome": None,
        "clinical_reviewing_clinician_id": None,
        "review_pending_since": review_pending_since,
        "enrolled_at": None,
        "enrolled_week": None,
        "completed_week": None,
        "dropout_week": None,
        "transition_reason": None,
        "pending_transition_clinician_id": None,
        "weeks_active": 0,
        "adherence_rate": 0.0,
        "adherence_scored_through_week": None,
        "pain_reduction_points": 0.0,
        "function_gain_points": 0.0,
        "dropout_risk_score": 0,
        "dropout_risk_as_of_week": None,
        "coach_escalation_required": False,
        "consult_cancellation_count": 0,
        "projected_engagement_milestone": 0,
        "attributed_savings_cents": 0,
        "measurement_count": 0,
    }


def create_enrollment(member, eligibility_file_id, status,
                      review_pending_since=None):
    return create(
        "Enrollment",
        enrollment_row(member, eligibility_file_id, status, review_pending_since),
    )


__all__ = [
    "adherence_rate",
    "attributed_savings",
    "claim_lines_of",
    "consecutive_missed",
    "create_enrollment",
    "current_pain_score",
    "dropout_risk",
    "enrollment_row",
    "failed_outreach_count",
    "measurement_deltas",
    "measurements_of",
    "next_rank",
    "outreach_of",
    "recompute_adherence",
    "recompute_enrollment_savings",
    "recompute_measurement_savings",
    "recompute_milestone",
    "recompute_projection",
    "recompute_risk",
    "recompute_weeks_active",
    "recompute_windows_containing",
    "seed_window",
    "sessions_of",
    "track_of",
    "weeks_active",
    "window_engagement_rate",
    "window_range",
]