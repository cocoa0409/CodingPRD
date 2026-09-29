"""Every calculation and every derived-value recomputation (PRD 2.8-2.11, 3.x).

All money-style and score-style numbers are Decimals carried to two places with
round-half-up; clamping always happens before rounding (PRD 2.8).
"""
from decimal import Decimal, ROUND_HALF_UP

from . import store

TWO = Decimal("0.01")
ZERO = Decimal("0.00")


def r2(value):
    """Round half up to two decimals."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# enumerations and constants
# ---------------------------------------------------------------------------
ELEMENT_CODES = (
    "STUDENT_NAME", "GRADE_LEVEL", "PARENT_CONTACT", "STUDENT_ID", "EMAIL", "DOB",
    "GEOLOCATION", "BEHAVIORAL_TELEMETRY", "PHOTO_VIDEO", "IEP_STATUS",
    "HEALTH_RECORD", "BIOMETRIC", "DISCIPLINE_RECORD",
)

TIER_BY_ELEMENT = {
    "STUDENT_NAME": 1, "GRADE_LEVEL": 1, "PARENT_CONTACT": 1,
    "STUDENT_ID": 2, "EMAIL": 2, "DOB": 2,
    "GEOLOCATION": 3, "BEHAVIORAL_TELEMETRY": 3, "PHOTO_VIDEO": 3,
    "IEP_STATUS": 4, "HEALTH_RECORD": 4, "BIOMETRIC": 4, "DISCIPLINE_RECORD": 4,
}

APPLICATION_CATEGORIES = (
    "INSTRUCTIONAL_CONTENT", "ASSESSMENT", "COMMUNICATION", "ANALYTICS", "ADMINISTRATIVE",
)

MAX_TIER_BY_CATEGORY = {
    "INSTRUCTIONAL_CONTENT": 2,
    "COMMUNICATION": 3,
    "ANALYTICS": 3,
    "ASSESSMENT": 4,
    "ADMINISTRATIVE": 4,
}

TIER_RETENTION_CAP = {1: 1825, 2: 1825, 3: 730, 4: 365}

SSO_PROTOCOLS = ("NONE", "SAML2", "OIDC", "LTI13")
ACCESSIBILITY_LEVELS = ("NONE", "WCAG21_A", "WCAG21_AA", "WCAG21_AAA")
DELETION_METHODS = ("HARD_DELETE", "ANONYMIZE", "AGGREGATE_ONLY")
FRAMEWORKS = ("FERPA", "COPPA", "PPRA", "STATE_ADDENDUM")
INCIDENT_TYPES = ("BREACH", "SUBPROCESSOR_CHANGE", "RETENTION_VIOLATION", "UNAUTHORIZED_DISCLOSURE")
TELEMETRY_SOURCES = ("NETWORK_DNS", "BROWSER_EXTENSION", "MDM_INVENTORY")
CREDENTIAL_LEVELS = ("JUNIOR", "SENIOR", "LEAD")

VENDOR_STATUSES = ("REGISTERED", "UNDER_REVIEW", "APPROVED", "CONDITIONAL", "REJECTED", "SUSPENDED")
POSTURES = ("CLEAR", "WATCH", "RESTRICTED", "FROZEN")
SUBPROCESSOR_STATUSES = ("DISCLOSED", "VERIFIED", "FLAGGED", "REMOVED")
APPLICATION_STATUSES = ("CANDIDATE", "IN_REVIEW", "APPROVED", "APPROVED_WITH_CONDITIONS", "BLOCKED")
VISIBILITIES = ("HIDDEN", "VISIBLE")
REQUEST_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "TRIAGED_FOR_REVIEW", "DENIED",
                    "CLOSED_APPROVED", "CLOSED_BLOCKED")
PRIORITY_BANDS = ("LOW", "STANDARD", "HIGH")
REVIEW_STATUSES = ("SCREENING", "FINDINGS_ISSUED", "REMEDIATION_SUBMITTED", "CLEARED",
                   "CONDITIONAL", "BLOCKED")
COMMITMENT_STATUSES = ("PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED")
CATALOG_STATUSES = ("PUBLISHED", "EXPIRING_SOON", "EXPIRED", "SUSPENDED_HOLD", "REVOKED", "SUPERSEDED")
DETECTION_CLASSIFICATIONS = ("AUTHORIZED", "EXPIRED_AUTHORIZATION", "UNAUTHORIZED", "UNKNOWN_DOMAIN")
DETECTION_STATUSES = ("NEW", "CONFIRMED_AUTHORIZED", "BLOCKED", "WHITELISTED", "ESCALATED")
RESPONSE_STATUSES = ("REPORTED", "CONTAINED", "REMEDIATED", "ESCALATED")
NOTIFICATION_STATUSES = ("PENDING", "SENT", "OVERDUE", "SENT_LATE")
SEVERITIES = ("LOW", "MODERATE", "HIGH", "CRITICAL")

JUSTIFICATION_MIN_CHARS = 120
JUSTIFICATION_MED_CHARS = 240
JUSTIFICATION_LONG_CHARS = 400
REVISION_ROUND_MAX = 2
FINDINGS_ROUND_MAX = 3
REMEDIATION_WINDOW_HOURS = 336
REAUTHORIZATION_LEAD_DAYS = 30
RETENTION_SOFT_CAP_DAYS = 365
PURPOSE_MIN_CHARS = 40
POSTURE_WATCH_THRESHOLD = Decimal("45")
INCIDENT_WINDOW_HOURS = 72
INCIDENT_COOLING_BUFFER_HOURS = 72

TIER_WEIGHT = {1: Decimal("1.00"), 2: Decimal("2.50"), 3: Decimal("6.00"), 4: Decimal("13.00")}
DELETION_MULTIPLIER = {
    "HARD_DELETE": Decimal("1.00"),
    "ANONYMIZE": Decimal("1.15"),
    "AGGREGATE_ONLY": Decimal("1.45"),
}
BAND_MULTIPLIER = {"HIGH": Decimal("1.20"), "STANDARD": Decimal("1.10"), "LOW": Decimal("0.85")}
SEVERITY_WEIGHT = {"LOW": 3, "MODERATE": 8, "HIGH": 18, "CRITICAL": 30}
STATUTORY_MAX_HOURS = {"CRITICAL": 24, "HIGH": 48, "MODERATE": 72, "LOW": 168}
CLASS_BASE = {
    "AUTHORIZED": Decimal("0"),
    "EXPIRED_AUTHORIZATION": Decimal("25"),
    "UNAUTHORIZED": Decimal("45"),
    "UNKNOWN_DOMAIN": Decimal("30"),
}

OPEN_REQUEST_STATUSES = ("SUBMITTED", "RETURNED", "TRIAGED_FOR_REVIEW")
NON_TERMINAL_REVIEW_STATUSES = ("SCREENING", "FINDINGS_ISSUED", "REMEDIATION_SUBMITTED")
TERMINAL_REVIEW_STATUSES = ("CLEARED", "CONDITIONAL", "BLOCKED")
OPEN_INCIDENT_STATUSES = ("REPORTED", "CONTAINED", "ESCALATED")
LIVE_INCIDENT_SCOPE = ("REPORTED", "CONTAINED", "ESCALATED", "REMEDIATED")
ACTIVE_WINDOW_STATUSES = ("PUBLISHED", "EXPIRING_SOON", "SUSPENDED_HOLD")
VISIBLE_STATUSES = ("PUBLISHED", "EXPIRING_SOON")


# ---------------------------------------------------------------------------
# child-collection accessors
# ---------------------------------------------------------------------------
def vendor_subprocessors(vendor_id):
    return [s for s in store.subprocessors.values() if s["vendor_id"] == vendor_id]


def vendor_applications(vendor_id):
    return [a for a in store.applications.values() if a["vendor_id"] == vendor_id]


def vendor_incidents(vendor_id):
    return [i for i in store.incidents.values() if i["vendor_id"] == vendor_id]


def review_commitments(review_id):
    return store.ordered([c for c in store.commitments.values() if c["review_id"] == review_id])


def application_reviews(application_id):
    return store.ordered([r for r in store.reviews.values() if r["application_id"] == application_id])


def application_commitments(application_id):
    review_ids = {r["id"] for r in store.reviews.values() if r["application_id"] == application_id}
    return store.ordered([c for c in store.commitments.values() if c["review_id"] in review_ids])


def application_entries(application_id):
    return store.ordered([e for e in store.catalog_entries.values()
                          if e["application_id"] == application_id])


def application_requests(application_id):
    return store.ordered([r for r in store.requests.values()
                          if r["application_id"] == application_id])


def teacher_requests(teacher_id):
    return [r for r in store.requests.values() if r["requester_teacher_id"] == teacher_id]


def analyst_reviews(analyst_id):
    return [r for r in store.reviews.values() if r["assigned_analyst_id"] == analyst_id]


def vendor_entries(vendor_id):
    app_ids = {a["id"] for a in vendor_applications(vendor_id)}
    return store.ordered([e for e in store.catalog_entries.values()
                          if e["application_id"] in app_ids])


# ---------------------------------------------------------------------------
# element / commitment calculations (PRD 3.4)
# ---------------------------------------------------------------------------
def element_sensitivity_tier(element_code):
    return TIER_BY_ELEMENT[element_code]


def application_max_permitted_tier(category):
    return MAX_TIER_BY_CATEGORY[category]


def retention_multiplier(days):
    if days <= 90:
        return Decimal("1.00")
    if days <= 365:
        return Decimal("1.25")
    if days <= 730:
        return Decimal("1.60")
    return Decimal("2.10")


def commitment_element_points(tier, retention_days, deletion_method):
    """Per-element contribution, rounded to two decimals BEFORE any summation."""
    return r2(TIER_WEIGHT[tier] * retention_multiplier(retention_days)
              * DELETION_MULTIPLIER[deletion_method])


def commitment_is_minimized(commitment, application):
    return (commitment["sensitivity_tier"] <= application["max_permitted_tier"]
            and commitment["retention_days"] <= RETENTION_SOFT_CAP_DAYS
            and commitment["deletion_method"] != "AGGREGATE_ONLY"
            and len(commitment["justified_purpose"]) >= PURPOSE_MIN_CHARS)


def exposed_sensitivity_points(application_id):
    """Sum of already-rounded element_points over ACCEPTED rows, created_at ASC."""
    total = ZERO
    for c in application_commitments(application_id):
        if c["status"] == "ACCEPTED":
            total = total + c["element_points"]
    return r2(total)


# ---------------------------------------------------------------------------
# request priority (PRD 3.2)
# ---------------------------------------------------------------------------
def request_priority_score(grade_band_low, grade_band_high, student_count_estimate,
                          instructional_justification):
    span = grade_band_high - grade_band_low + 1
    length = len(instructional_justification)
    if length >= JUSTIFICATION_LONG_CHARS:
        bonus = Decimal("15")
    elif length >= JUSTIFICATION_MED_CHARS:
        bonus = Decimal("8")
    else:
        bonus = Decimal("0")
    raw = Decimal(20) * Decimal(span) + Decimal("0.01") * Decimal(student_count_estimate) + bonus
    # The band is a function of the RAW score only and is never re-derived from
    # the multiplied score.
    if raw >= Decimal("60"):
        band = "HIGH"
    elif raw >= Decimal("30"):
        band = "STANDARD"
    else:
        band = "LOW"
    return r2(raw * BAND_MULTIPLIER[band]), band


# ---------------------------------------------------------------------------
# vendor risk score and posture (PRD 3.1, 2.9)
# ---------------------------------------------------------------------------
def contractual_penalty(breach_notification_hours):
    if breach_notification_hours <= 72:
        return Decimal("0")
    if breach_notification_hours <= 168:
        return Decimal("10")
    return Decimal("25")


def incident_decay(incident):
    """Whole-day age between detected_at and the logical clock, partial discarded."""
    delta = store.clock() - incident["detected_at"]
    age_days = int(delta.total_seconds() // 86400)
    if age_days <= 90:
        return Decimal("1")
    if age_days <= 365:
        return Decimal("0.5")
    return ZERO


def vendor_risk_score(vendor, variant="live"):
    scope = LIVE_INCIDENT_SCOPE if variant == "live" else OPEN_INCIDENT_STATUSES

    load = ZERO
    for app in vendor_applications(vendor["id"]):
        if app["status"] in ("IN_REVIEW", "APPROVED", "APPROVED_WITH_CONDITIONS"):
            load = load + app["exposed_sensitivity_points"]
    sensitivity_load = r2(load * Decimal("0.5"))

    foreign = ZERO
    for sub in vendor_subprocessors(vendor["id"]):
        if sub["status"] in ("DISCLOSED", "VERIFIED", "FLAGGED") and sub["country_code"] != "US":
            foreign = foreign + Decimal("10")

    contractual = contractual_penalty(vendor["breach_notification_hours"])

    incident_load = ZERO
    for inc in vendor_incidents(vendor["id"]):
        if inc["response_status"] in scope:
            incident_load = (incident_load
                             + Decimal(SEVERITY_WEIGHT[inc["severity"]]) * incident_decay(inc))

    total = sensitivity_load + foreign + contractual + incident_load
    if total > Decimal("100"):
        total = Decimal("100")
    return r2(total)


def vendor_privacy_posture(vendor):
    """PRD 2.9 first-match-wins ladder."""
    incidents = vendor_incidents(vendor["id"])
    if vendor["status"] == "SUSPENDED":
        return "FROZEN"
    for inc in incidents:
        if inc["notification_status"] == "OVERDUE":
            return "FROZEN"
    for inc in incidents:
        if inc["severity"] == "CRITICAL" and inc["response_status"] == "REPORTED":
            return "FROZEN"
    if vendor["flagged_subprocessor_count"] > 0:
        return "RESTRICTED"
    for inc in incidents:
        if inc["response_status"] in OPEN_INCIDENT_STATUSES:
            return "RESTRICTED"
    if vendor["risk_score"] >= POSTURE_WATCH_THRESHOLD:
        return "WATCH"
    return "CLEAR"


# ---------------------------------------------------------------------------
# compliance scoring (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
def _framework_points(review):
    covered = sum(1 for f in FRAMEWORKS if f in review["framework_set"])
    return Decimal(covered) * Decimal(30) / Decimal(4)


def _minimization_points(rows):
    if not rows:
        return ZERO
    good = sum(1 for c in rows if c["is_minimized"])
    return Decimal(good) * Decimal(25) / Decimal(len(rows))


def _retention_points(rows):
    if not rows:
        return ZERO
    if all(c["retention_days"] <= 365 and c["deletion_method"] != "AGGREGATE_ONLY" for c in rows):
        factor = Decimal("1.0")
    elif all(c["retention_days"] <= 730 for c in rows):
        factor = Decimal("0.5")
    else:
        factor = ZERO
    return Decimal(15) * factor


def _subprocessor_points(vendor):
    if not vendor["subprocessor_disclosure_complete"]:
        factor = ZERO
    elif vendor["flagged_subprocessor_count"] > 0:
        factor = ZERO
    elif any(s["status"] in ("DISCLOSED", "VERIFIED")
             and s["sub_breach_notification_hours"] > vendor["breach_notification_hours"]
             for s in vendor_subprocessors(vendor["id"])):
        factor = Decimal("0.5")
    else:
        factor = Decimal("1.0")
    return Decimal(15) * factor


def _accessibility_points(application):
    level = application["accessibility_conformance_level"]
    vpat = application["vpat_on_file"]
    if level in ("WCAG21_AA", "WCAG21_AAA") and vpat:
        factor = Decimal("1.0")
    elif level == "WCAG21_A" and vpat:
        factor = Decimal("0.5")
    else:
        factor = ZERO
    return Decimal(10) * factor


def _sso_points(application):
    if application["sso_protocol"] in ("SAML2", "OIDC", "LTI13") and application["sso_verified"]:
        return Decimal(5)
    return ZERO


def compliance_score(review, vendor, application, variant):
    if variant == "provisional":
        rows = [c for c in review_commitments(review["id"])
                if c["status"] in ("PROPOSED", "ACCEPTED")]
        findings = review["open_findings_count"]
        addendum_penalty = ZERO
    else:
        rows = [c for c in review_commitments(review["id"]) if c["status"] == "ACCEPTED"]
        findings = review["unresolved_findings_count"]
        addendum_penalty = ZERO if vendor["signed_state_addendum"] else Decimal(20)

    base = (_framework_points(review)
            + _minimization_points(rows)
            + _retention_points(rows)
            + _subprocessor_points(vendor)
            + _accessibility_points(application)
            + _sso_points(application))

    penalty = (Decimal(8) * Decimal(findings)
               + Decimal(12) * Decimal(vendor["flagged_subprocessor_count"])
               + addendum_penalty)

    value = base - penalty
    if value < ZERO:
        value = ZERO
    if value > Decimal("100"):
        value = Decimal("100")
    return r2(value)


# ---------------------------------------------------------------------------
# incidents (PRD 3.9)
# ---------------------------------------------------------------------------
def incident_severity(affected_student_count, max_data_tier):
    if affected_student_count >= 1000 or max_data_tier == 4:
        return "CRITICAL"
    if affected_student_count >= 100:
        return "HIGH"
    if affected_student_count >= 10:
        return "MODERATE"
    return "LOW"


def notification_due_at(detected_at, severity, breach_notification_hours):
    allowance = min(breach_notification_hours, STATUTORY_MAX_HOURS[severity])
    return detected_at + store.hours(allowance)


def incident_bare_window(incident):
    start = incident["detected_at"]
    end = incident["contained_at"] or (start + store.hours(INCIDENT_WINDOW_HOURS))
    return start, end


def incident_window_conflict(vendor_id, start, end):
    """Closed intervals; only the EXISTING row is widened by the cooling buffer."""
    buffer = store.hours(INCIDENT_COOLING_BUFFER_HOURS)
    for inc in vendor_incidents(vendor_id):
        if inc["response_status"] not in LIVE_INCIDENT_SCOPE:
            continue
        other_start, other_end = incident_bare_window(inc)
        if start <= other_end + buffer and end >= other_start - buffer:
            return inc
    return None


# ---------------------------------------------------------------------------
# telemetry detections (PRD 3.8)
# ---------------------------------------------------------------------------
def _widest(entries):
    """Greatest expires_at, ties broken by the earlier created_at."""
    best = None
    for entry in store.ordered(entries):
        if best is None or entry["expires_at"] > best["expires_at"]:
            best = entry
    return best


def detection_classification(application_id, observed_at):
    if application_id is None:
        return "UNKNOWN_DOMAIN", None
    entries = application_entries(application_id)
    inside = [e for e in entries
              if e["status"] in VISIBLE_STATUSES
              and e["effective_from"] <= observed_at < e["expires_at"]]
    if inside:
        return "AUTHORIZED", _widest(inside)["id"]
    lapsed = [e for e in entries
              if e["status"] in ("PUBLISHED", "EXPIRING_SOON", "EXPIRED", "SUPERSEDED")
              and e["expires_at"] <= observed_at]
    if lapsed:
        return "EXPIRED_AUTHORIZATION", _widest(lapsed)["id"]
    return "UNAUTHORIZED", None


def detection_exposure_score(classification, distinct_user_count, session_count):
    total = (Decimal("0.4") * Decimal(distinct_user_count)
             + Decimal("0.05") * Decimal(session_count)
             + CLASS_BASE[classification])
    if total > Decimal("100"):
        total = Decimal("100")
    return r2(total)


# ---------------------------------------------------------------------------
# catalog (PRD 3.7)
# ---------------------------------------------------------------------------
def reauthorization_due_at(expires_at):
    return expires_at - store.days(REAUTHORIZATION_LEAD_DAYS)


def window_overlap(application_id, effective_from, expires_at, exclude_ids=()):
    """Half-open, zero buffer; only siblings in an active window status count."""
    for entry in application_entries(application_id):
        if entry["id"] in exclude_ids:
            continue
        if entry["status"] not in ACTIVE_WINDOW_STATUSES:
            continue
        if effective_from < entry["expires_at"] and entry["effective_from"] < expires_at:
            return entry
    return None


def catalog_visibility(application_id):
    for entry in application_entries(application_id):
        if entry["status"] in VISIBLE_STATUSES:
            return "VISIBLE"
    return "HIDDEN"


# ---------------------------------------------------------------------------
# full-recomputation helpers (PRD 2.10) -- never incremental
# ---------------------------------------------------------------------------
def recount_teacher_requests(teacher, force=False):
    count = sum(1 for r in teacher_requests(teacher["id"])
                if r["status"] in OPEN_REQUEST_STATUSES)
    store.apply(teacher, {"open_request_count": count}, force=force)


def resum_analyst_minutes(analyst, force=False):
    total = sum(r["estimated_minutes"] for r in analyst_reviews(analyst["id"])
                if r["status"] in NON_TERMINAL_REVIEW_STATUSES)
    store.apply(analyst, {"allocated_review_minutes": total}, force=force)


def analyst_allocated_minutes(analyst_id):
    return sum(r["estimated_minutes"] for r in analyst_reviews(analyst_id)
               if r["status"] in NON_TERMINAL_REVIEW_STATUSES)


def recompute_application_exposure(application, force=False):
    store.apply(application,
                {"exposed_sensitivity_points": exposed_sensitivity_points(application["id"])},
                force=force)


def recompute_application_visibility(application, force=False):
    return store.apply(application,
                       {"catalog_visibility": catalog_visibility(application["id"])},
                       force=force)


def recompute_vendor(vendor, force=False, counts=False, reauthorization=False):
    """risk_score is always recomputed before privacy_posture (PRD 2.10)."""
    changes = {}
    if counts:
        changes["open_incident_count"] = sum(
            1 for i in vendor_incidents(vendor["id"])
            if i["response_status"] in OPEN_INCIDENT_STATUSES)
        changes["flagged_subprocessor_count"] = sum(
            1 for s in vendor_subprocessors(vendor["id"]) if s["status"] == "FLAGGED")
    if changes:
        for key, value in changes.items():
            vendor[key] = value
    if reauthorization:
        vendor["reauthorization_risk_score"] = vendor_risk_score(vendor, "reauthorization")
    vendor["risk_score"] = vendor_risk_score(vendor, "live")
    vendor["privacy_posture"] = vendor_privacy_posture(vendor)
    store.bump(vendor)


def recount_vendor_flags(vendor):
    vendor["flagged_subprocessor_count"] = sum(
        1 for s in vendor_subprocessors(vendor["id"]) if s["status"] == "FLAGGED")


def recount_vendor_incidents(vendor):
    vendor["open_incident_count"] = sum(
        1 for i in vendor_incidents(vendor["id"])
        if i["response_status"] in OPEN_INCIDENT_STATUSES)
