"""Calculation rules, derived-field recomputation, the transparency log and
the cascades.  Every aggregate is produced by full re-aggregation over the
current rows, never by applying an incremental delta (PRD 2.11).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from store import db, now, new_id, touch, ordered, base_record

# ---------------------------------------------------------------------------
# story_risk_index
# ---------------------------------------------------------------------------

SEVERE_SOURCE_CAP = 3
ELEVATED_SOURCE_CAP = 5
RISK_CAP = Decimal("100.00")
TIER_HIGH_AT = Decimal("40.00")
TIER_ELEVATED_AT = Decimal("20.00")

CENT = Decimal("0.01")


def _round2(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _sourcing_base(story_id):
    severe = 0
    elevated = 0
    for a in db.source_approvals.values():
        if a["story_id"] != story_id or a["status"] != "APPROVED":
            continue
        if a["harm_risk"] == "SEVERE":
            severe += 1
        elif a["harm_risk"] == "ELEVATED":
            elevated += 1
    return 4 * min(severe, SEVERE_SOURCE_CAP) + 2 * min(elevated, ELEVATED_SOURCE_CAP)


def _lead_multiplier(story):
    journalist = db.journalists.get(story["lead_journalist_id"])
    points = journalist["penalty_points"] if journalist else 0
    if points >= 6:
        return Decimal("1.25")
    if points >= 3:
        return Decimal("1.10")
    return Decimal("1.00")


def _risk_from_subtotal(subtotal, multiplier):
    # Pinned order: subtotal, then the multiplier, then the cap, then the rounding.
    product = Decimal(subtotal) * multiplier
    capped = product if product < RISK_CAP else RISK_CAP
    return _round2(capped)


def _claim_load(story):
    return 3 * story["defamation_claim_count"] + 2 * story["privacy_subject_count"]


def _doc_penalty(story):
    return 5 if story["unverified_document_count"] > 0 else 0


def severe_adjudicated_corrections(story_id):
    total = 0
    for c in db.corrections.values():
        if c["story_id"] != story_id:
            continue
        if c["status"] not in ("ADJUDICATED", "RESOLVED"):
            continue
        if c["adjudicated_severity_band"] in ("MAJOR", "SEVERE"):
            total += 1
    return total


def risk_index_estimate(story):
    subtotal = _sourcing_base(story["id"]) + _claim_load(story) + _doc_penalty(story)
    return _risk_from_subtotal(subtotal, _lead_multiplier(story))


def risk_index_actual(story):
    claim = _claim_load(story) + 6 * severe_adjudicated_corrections(story["id"])
    doc = _doc_penalty(story) + 7 * story["revoked_anonymous_source_count"]
    subtotal = _sourcing_base(story["id"]) + claim + doc
    return _risk_from_subtotal(subtotal, _lead_multiplier(story))


def risk_tier_of(estimate):
    if estimate >= TIER_HIGH_AT:
        return "HIGH"
    if estimate >= TIER_ELEVATED_AT:
        return "ELEVATED"
    return "STANDARD"


def recompute_estimate(story):
    """Recompute risk_index_estimate and risk_tier.  Never touches the version."""
    story["risk_index_estimate"] = risk_index_estimate(story)
    story["risk_tier"] = risk_tier_of(story["risk_index_estimate"])


def recompute_actual(story):
    """Recompute risk_index_actual, but only once it has come into existence."""
    if story["risk_index_actual"] is not None:
        story["risk_index_actual"] = risk_index_actual(story)


# ---------------------------------------------------------------------------
# correction_severity_score
# ---------------------------------------------------------------------------

CATEGORY_WEIGHT = {"FACTUAL": 6, "QUOTE": 5, "NUMERIC": 4, "IDENTIFICATION": 8, "CONTEXT": 3}
PLACEMENT_SURCHARGE = {"TRIVIAL": 0, "MINOR": 1, "MAJOR": 2, "SEVERE": 3}


def severity_score(category, reach, subject_flag):
    """Returns (score, band).  The band comes from `raw` only and is never
    re-derived from the final score."""
    category_points = CATEGORY_WEIGHT[category]
    subject_bonus = 4 if subject_flag else 0
    if reach >= 100000:
        reach_points = 6
    elif reach >= 10000:
        reach_points = 4
    elif reach >= 1000:
        reach_points = 2
    else:
        reach_points = 0
    raw = category_points + subject_bonus + reach_points
    if raw >= 16:
        band = "SEVERE"
    elif raw >= 11:
        band = "MAJOR"
    elif raw >= 6:
        band = "MINOR"
    else:
        band = "TRIVIAL"
    return raw + PLACEMENT_SURCHARGE[band], band


def placement_for(outcome_type, band):
    if outcome_type == "NO_ACTION":
        return None
    if outcome_type == "UPDATE":
        return "INLINE"
    if outcome_type == "CLARIFICATION":
        return "END_OF_STORY"
    if outcome_type == "EDITORS_NOTE":
        return "TOP_OF_STORY"
    # CORRECTION
    if band in ("MAJOR", "SEVERE"):
        return "TOP_OF_STORY"
    return "END_OF_STORY"


# ---------------------------------------------------------------------------
# correction_response_due_at
# ---------------------------------------------------------------------------

BAND_FACTOR = {
    "TRIVIAL": Decimal("1.0"),
    "MINOR": Decimal("1.0"),
    "MAJOR": Decimal("0.5"),
    "SEVERE": Decimal("0.25"),
}
SUBMITTER_BUMP = {"SUBJECT": -12, "READER": 0, "INTERNAL": 24}
MIN_DUE_HOURS = 4


def response_due_at(sla_hours, provisional_band, submitter_type, at_instant):
    product = Decimal(sla_hours) * BAND_FACTOR[provisional_band]
    ceiled = int(product.to_integral_value(rounding=ROUND_CEILING))
    due_hours = ceiled + SUBMITTER_BUMP[submitter_type]
    if due_hours < MIN_DUE_HOURS:
        due_hours = MIN_DUE_HOURS
    return at_instant + timedelta(hours=due_hours)


def breach_flag(correction):
    if correction["status"] not in ("INTAKE", "INVESTIGATING", "AWAITING_SUBJECT"):
        return False
    due = correction["response_due_at"]
    if due is None:
        return False
    return now() > due


# ---------------------------------------------------------------------------
# desk_training_compliance_index
# ---------------------------------------------------------------------------


def _completed_required(journalist_id, required):
    codes = set()
    for t in db.training_records.values():
        if t["journalist_id"] == journalist_id:
            codes.add(t["module_code"])
    return len(codes & set(required))


def recompute_journalist_training(journalist):
    newsroom = db.newsrooms.get(journalist["newsroom_id"])
    required = newsroom["required_module_codes"] if newsroom else []
    count = _completed_required(journalist["id"], required)
    current = bool(required) and count == len(required)
    changed = (journalist["completed_required_module_count"] != count
               or journalist["training_current"] != current)
    journalist["completed_required_module_count"] = count
    journalist["training_current"] = current
    return changed


def training_compliance_index(newsroom):
    required = newsroom["required_module_codes"]
    cohort = ordered([j for j in db.journalists.values()
                      if j["newsroom_id"] == newsroom["id"]])
    if not cohort:
        return Decimal("0.00")
    total = Decimal(0)
    for j in cohort:
        count = _completed_required(j["id"], required)
        # STEP 1 -- round EACH journalist's ratio to 2 decimals first.
        total += _round2(Decimal(count) / Decimal(len(required)))
    # STEP 2 -- average the ROUNDED ratios, scale, round again.
    return _round2((total / Decimal(len(cohort))) * Decimal(100))


def recompute_compliance_index(newsroom):
    value = training_compliance_index(newsroom)
    changed = newsroom["training_compliance_index"] != value
    newsroom["training_compliance_index"] = value
    return changed


# ---------------------------------------------------------------------------
# reviewer_minute_ledger
# ---------------------------------------------------------------------------


def duration_minutes(starts_at, ends_at):
    seconds = (ends_at - starts_at).total_seconds()
    return int(seconds // 60)


def reserved_minutes(reviewer_id):
    total = 0
    for a in db.assignments.values():
        if a["reviewer_id"] == reviewer_id and a["status"] == "SCHEDULED":
            total += a["duration_minutes"]
    return total


def recompute_reviewer(reviewer):
    """Full re-aggregation of the ledger; a ledger operation is a mutation."""
    reserved = reserved_minutes(reviewer["id"])
    reviewer["reserved_minutes"] = reserved
    reviewer["available_minutes"] = reviewer["weekly_capacity_minutes"] - reserved
    touch(reviewer)


def recompute_reviewers(reviewer_ids):
    for reviewer in ordered([db.reviewers[r] for r in set(reviewer_ids)
                             if r in db.reviewers]):
        recompute_reviewer(reviewer)


# ---------------------------------------------------------------------------
# journalist_penalty_points
# ---------------------------------------------------------------------------

SEVERITY_POINTS = {"MINOR": 2, "SERIOUS": 5, "EGREGIOUS": 9}
FABRICATION_SURCHARGE = 3
REPEAT_SURCHARGE = 2
SUSPENSION_AT = 12


def prior_sustained_count(journalist_id, exclude_id=None):
    """Investigations of the subject already SUSTAINED with decided_at strictly
    earlier than the logical clock's current reading."""
    instant = now()
    count = 0
    for i in db.investigations.values():
        if exclude_id is not None and i["id"] == exclude_id:
            continue
        if i["journalist_id"] != journalist_id or i["status"] != "SUSTAINED":
            continue
        if i["decided_at"] is not None and i["decided_at"] < instant:
            count += 1
    return count


def investigation_points(severity, allegation_type, prior_count):
    points = SEVERITY_POINTS[severity]
    if allegation_type == "FABRICATION":
        points += FABRICATION_SURCHARGE
    if prior_count >= 1:
        points += REPEAT_SURCHARGE
    return points


def sum_sustained_points(journalist_id):
    total = 0
    for i in db.investigations.values():
        if i["journalist_id"] == journalist_id and i["status"] == "SUSTAINED":
            total += i["penalty_points"]
    return total


def recompute_journalist_points(journalist):
    """Returns (changed, previous_employment_status)."""
    points = sum_sustained_points(journalist["id"])
    status = "SUSPENDED" if points >= SUSPENSION_AT else "ACTIVE"
    previous = journalist["employment_status"]
    changed = journalist["penalty_points"] != points or previous != status
    journalist["penalty_points"] = points
    journalist["employment_status"] = status
    return changed, previous


def disclosure_obligation_for(allegation_type, severity):
    if allegation_type == "FABRICATION":
        return "RETRACTION_REVIEW" if severity == "EGREGIOUS" else "CORRECTION"
    return "EDITORS_NOTE"


# ---------------------------------------------------------------------------
# ConflictDisclosure -> Journalist.restricted_beats
# ---------------------------------------------------------------------------


def recompute_restricted_beats(journalist):
    beats = []
    for d in ordered([d for d in db.disclosures.values()
                      if d["journalist_id"] == journalist["id"]
                      and d["status"] == "RESTRICTION_IMPOSED"]):
        for beat in d["restricted_beats"]:
            if beat not in beats:
                beats.append(beat)
    changed = journalist["restricted_beats"] != beats
    journalist["restricted_beats"] = beats
    return changed


# ---------------------------------------------------------------------------
# newsroom_standards_posture
# ---------------------------------------------------------------------------

LOCKDOWN_MULTIPLIER = 2


def open_high_severity_count(newsroom_id):
    high_severity_corrections = 0
    for c in db.corrections.values():
        if c["status"] != "ADJUDICATED":
            continue
        if c["adjudicated_severity_band"] not in ("MAJOR", "SEVERE"):
            continue
        story = db.stories.get(c["story_id"])
        if story is not None and story["newsroom_id"] == newsroom_id:
            high_severity_corrections += 1
    open_investigations = 0
    for i in db.investigations.values():
        if i["status"] not in ("OPENED", "EVIDENCE_REVIEW", "RESPONSE_PENDING"):
            continue
        if i["severity"] not in ("SERIOUS", "EGREGIOUS"):
            continue
        journalist = db.journalists.get(i["journalist_id"])
        if journalist is not None and journalist["newsroom_id"] == newsroom_id:
            open_investigations += 1
    return high_severity_corrections + open_investigations


def posture_for(count, threshold):
    if count >= LOCKDOWN_MULTIPLIER * threshold:
        return "LOCKDOWN"
    if count >= threshold:
        return "HEIGHTENED"
    return "OPEN"


def recompute_posture(newsroom):
    """Recompute open_high_severity_count and standards_posture, emitting a
    POSTURE_CHANGED transparency event whenever the posture value changes."""
    count = open_high_severity_count(newsroom["id"])
    posture = posture_for(count, newsroom["high_severity_open_threshold"])
    previous = newsroom["standards_posture"]
    changed = newsroom["open_high_severity_count"] != count or previous != posture
    newsroom["open_high_severity_count"] = count
    newsroom["standards_posture"] = posture
    if changed:
        touch(newsroom)
    if previous != posture:
        emit_audit(newsroom["id"], "POSTURE_CHANGED", "Newsroom", newsroom["id"],
                   "system", None,
                   "Newsroom standards posture changed from %s to %s." % (previous, posture))
    return changed


# ---------------------------------------------------------------------------
# Transparency log
# ---------------------------------------------------------------------------


def emit_audit(newsroom_id, event_type, subject_type, subject_id, actor_role,
               actor_user_id, summary):
    event = base_record(with_version=False)
    event.update({
        "newsroom_id": newsroom_id,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "summary": summary,
        "occurred_at": now(),
    })
    db.audit_events[event["id"]] = event
    return event


def newsroom_of_story(story):
    return db.newsrooms.get(story["newsroom_id"]) if story else None


def newsroom_of_journalist(journalist):
    return db.newsrooms.get(journalist["newsroom_id"]) if journalist else None


# ---------------------------------------------------------------------------
# Assignment cascade (PRD 3.4: bookings leave SCHEDULED without anyone asking)
# ---------------------------------------------------------------------------


def close_review_assignments(review_id, new_status):
    """Move every SCHEDULED booking of a review to COMPLETED or CANCELLED and
    re-aggregate each affected reviewer's ledger exactly once."""
    affected = []
    for assignment in ordered(list(db.assignments.values())):
        if assignment["review_id"] == review_id and assignment["status"] == "SCHEDULED":
            assignment["status"] = new_status
            touch(assignment)
            affected.append(assignment["reviewer_id"])
    recompute_reviewers(affected)
    return affected
