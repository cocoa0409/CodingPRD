"""Domain constants, lookups, calculations and cascading reconciliations."""
from decimal import Decimal

from errors import ApiError
from store import by_created, db, new_row, touch
from util import add_days, dec, fractional_days, q2, qcents, whole_day_floor

# ---------------------------------------------------------------- enumerations
DISCIPLINES = ("BIOLOGY", "CHEMISTRY", "LATENT_PRINTS", "TRACE", "DIGITAL")
ITEM_TYPES = (
    "BIOLOGICAL", "CHEMICAL", "FIREARM", "LATENT_LIFT",
    "DIGITAL_DEVICE", "TRACE_MEDIA",
)
OFFENSE_CATEGORIES = (
    "HOMICIDE", "SEXUAL_ASSAULT", "AGG_ASSAULT", "ROBBERY",
    "BURGLARY", "DRUG_OFFENSE", "PROPERTY_CRIME", "OTHER",
)
EMPLOYMENT_STATUSES = ("ACTIVE", "ON_LEAVE", "SEPARATED")
QUALIFICATION_STATES = ("QUALIFIED", "PROBATION", "SUSPENDED", "DECERTIFIED")
PRIORITY_CLASSES = ("P1_STATUTORY", "P2_VIOLENT", "P3_ROUTINE")
CASE_WORKFLOW_STATUSES = (
    "SUBMITTED", "ACCEPTED", "IN_PROGRESS", "AWAITING_ASSIGNMENT",
    "REPORTED", "REJECTED",
)
DISCOVERY_STATUSES = ("NONE", "RECEIVED", "FULFILLED", "DENIED")
CUSTODY_STATUSES = ("IN_VAULT", "IN_ANALYSIS", "RETURNED", "CONSUMED")
REQUEST_STATUSES = (
    "QUEUED", "ASSIGNED", "IN_ANALYSIS", "TECH_REVIEW", "DISAGREEMENT",
    "ADMIN_REVIEW", "OUTSOURCED", "RELEASED", "CANCELLED",
)
ASSIGNMENT_STATUSES = ("ACTIVE", "SUPERSEDED", "RELEASED", "COMPLETED")
ASSIGNMENT_REASONS = ("MANUAL", "AUTO_BALANCED")
REVIEW_TYPES = ("TECHNICAL", "ADMINISTRATIVE", "DISAGREEMENT_RESOLUTION")
METHOD_STATUSES = ("DRAFT", "VALIDATED", "RETIRED")
PT_STATUSES = ("ASSIGNED", "SUBMITTED", "SCORED")
PT_RESULTS = ("PASS", "INCONCLUSIVE", "FAIL")
VENDOR_STATUSES = ("ACTIVE", "SUSPENDED")
ENGAGEMENT_STATUSES = ("AWARDED", "AT_VENDOR", "RETURNED", "CANCELLED")
NC_SOURCES = (
    "TECHNICAL_DISAGREEMENT", "PT_FAILURE", "PT_INCONCLUSIVE",
    "ACCREDITATION_AUDIT", "INTERNAL_QA", "DEADLINE_MISS", "VENDOR_VARIANCE",
)
NC_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
NC_STATUSES = ("OPEN", "ROOT_CAUSE_SUBMITTED", "CAPA_APPROVED", "CLOSED", "VOIDED")
ROOT_CAUSE_CATEGORIES = (
    "TRAINING", "METHOD_DEFICIENCY", "EQUIPMENT", "DOCUMENTATION",
    "WORKLOAD", "VENDOR",
)
COURT_EVENT_STATUSES = ("SCHEDULED", "CONFIRMED", "TESTIFIED", "CANCELLED")

ER_ACTIVE_SET = (
    "ASSIGNED", "IN_ANALYSIS", "TECH_REVIEW", "DISAGREEMENT",
    "ADMIN_REVIEW", "OUTSOURCED",
)
ER_TERMINAL_SET = ("RELEASED", "CANCELLED")
ER_HOLD_SET = ("ASSIGNED", "IN_ANALYSIS")
LIVE_NC_STATUSES = ("OPEN", "ROOT_CAUSE_SUBMITTED", "CAPA_APPROVED")

# ---------------------------------------------------------------- constants
SEVERITY_POINTS = {
    "HOMICIDE": 40, "SEXUAL_ASSAULT": 36, "AGG_ASSAULT": 30, "ROBBERY": 26,
    "BURGLARY": 16, "DRUG_OFFENSE": 12, "PROPERTY_CRIME": 8, "OTHER": 4,
}
CUSTODY_POINTS = 15
VIOLENT_MULTIPLIER = Decimal("1.10")
SCORE_CAP = Decimal("100.00")
P1_DEADLINE_DAYS = 30
VIOLENT_CATEGORIES = ("HOMICIDE", "SEXUAL_ASSAULT", "AGG_ASSAULT", "ROBBERY")

METHOD_ITEM_TYPE_MATRIX = {
    "BIOLOGY": ("BIOLOGICAL",),
    "CHEMISTRY": ("CHEMICAL",),
    "LATENT_PRINTS": ("LATENT_LIFT", "FIREARM"),
    "TRACE": ("TRACE_MEDIA",),
    "DIGITAL": ("DIGITAL_DEVICE",),
}

MIN_VALIDATION_STUDY_ITEMS = 12
MAX_VALIDATION_CV_PCT = Decimal("5.00")
UTILIZATION_CEILING_PCT = Decimal("100.00")
PROBATION_TRAINING_MINIMUM = Decimal("8.00")
PT_PASS_THRESHOLD = Decimal("90.00")
PT_INCONCLUSIVE_THRESHOLD = Decimal("70.00")
PT_SUSPENSION_THRESHOLD = 2
CAPA_SLA_DAYS = {"MINOR": 60, "MAJOR": 30, "CRITICAL": 10}
CAPA_ESCALATION_THRESHOLD = 2
SEVERITY_ESCALATION = {"MINOR": "MAJOR", "MAJOR": "CRITICAL", "CRITICAL": "CRITICAL"}
DISCOVERY_RESPONSE_DAYS = 30
TECHNICAL_DISAGREEMENT_SLA_DAYS = 30
VENDOR_VARIANCE_TOLERANCE_PCT = Decimal("0.10")
VOLUME_TIERS = (
    (500000, Decimal("0.12")),
    (250000, Decimal("0.08")),
    (100000, Decimal("0.04")),
)
MIN_TESTIMONY_NOTICE_DAYS = 7
TRAVEL_BUFFER_MINUTES = 60
PRIORITY_WEIGHTS = {
    "P1_STATUTORY": Decimal("1.50"),
    "P2_VIOLENT": Decimal("1.25"),
    "P3_ROUTINE": Decimal("1.00"),
}
BACKLOG_OUTSOURCING_THRESHOLD = Decimal("45.00")


# ---------------------------------------------------------------- lookups
def _lookup(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def find_analyst(row_id):
    return _lookup(db.analysts, row_id, "ERR_ANALYST_NOT_FOUND")


def find_method(row_id):
    return _lookup(db.methods, row_id, "ERR_METHOD_NOT_FOUND")


def find_case(row_id):
    return _lookup(db.cases, row_id, "ERR_CASE_NOT_FOUND")


def find_evidence_item(row_id):
    return _lookup(db.evidence_items, row_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")


def find_examination_request(row_id):
    return _lookup(db.examination_requests, row_id, "ERR_EXAM_REQUEST_NOT_FOUND")


def find_assignment(row_id):
    return _lookup(db.assignments, row_id, "ERR_ASSIGNMENT_NOT_FOUND")


def find_review_record(row_id):
    return _lookup(db.review_records, row_id, "ERR_REVIEW_RECORD_NOT_FOUND")


def find_proficiency_test(row_id):
    return _lookup(db.proficiency_tests, row_id, "ERR_PROFICIENCY_TEST_NOT_FOUND")


def find_vendor(row_id):
    return _lookup(db.vendors, row_id, "ERR_VENDOR_NOT_FOUND")


def find_vendor_engagement(row_id):
    return _lookup(db.vendor_engagements, row_id, "ERR_VENDOR_ENGAGEMENT_NOT_FOUND")


def find_nonconformance(row_id):
    return _lookup(db.nonconformances, row_id, "ERR_NONCONFORMANCE_NOT_FOUND")


def find_court_event(row_id):
    return _lookup(db.court_events, row_id, "ERR_COURT_EVENT_NOT_FOUND")


def requests_of_case(case_id):
    return [r for r in db.examination_requests.values() if r["case_id"] == case_id]


def items_of_case(case_id):
    return by_created([
        r for r in db.evidence_items.values() if r["case_id"] == case_id
    ])


def assignments_of_request(request_id):
    return by_created([
        a for a in db.assignments.values()
        if a["examination_request_id"] == request_id
    ])


def assignments_of_analyst(analyst_id):
    return by_created([
        a for a in db.assignments.values() if a["analyst_id"] == analyst_id
    ])


def active_assignment_of_request(request_id):
    for row in assignments_of_request(request_id):
        if row["status"] == "ACTIVE":
            return row
    return None


def engagements_of_request(request_id):
    return by_created([
        e for e in db.vendor_engagements.values()
        if e["examination_request_id"] == request_id
    ])


def engagements_of_vendor(vendor_id):
    return by_created([
        e for e in db.vendor_engagements.values() if e["vendor_id"] == vendor_id
    ])


def records_of_request(request_id):
    return by_created([
        r for r in db.review_records.values()
        if r["examination_request_id"] == request_id
    ])


def findings_of_request(request_id):
    return by_created([
        r for r in db.nonconformances.values()
        if r["examination_request_id"] == request_id
    ])


def has_live_nonconformance(analyst_id, excluding=None):
    for row in db.nonconformances.values():
        if row["analyst_id"] != analyst_id:
            continue
        if excluding is not None and row["id"] == excluding:
            continue
        if row["status"] in LIVE_NC_STATUSES:
            return True
    return False


# ---------------------------------------------------------------- priority
def compute_days_to(case, field):
    moment = case.get(field)
    if moment is None:
        return None
    return whole_day_floor(case["received_at_utc"], moment)


def deadline_points(days):
    if days is None:
        return 0
    if days <= 14:
        return 30
    if days <= 30:
        return 22
    if days <= 60:
        return 14
    if days <= 120:
        return 6
    return 0


def court_points(days):
    if days is None:
        return 0
    if days <= 30:
        return 10
    if days <= 60:
        return 5
    return 0


def compute_priority_score(case):
    """The pinned five-step scoring model of PRD section 3.1."""
    days_deadline = compute_days_to(case, "statutory_deadline_utc")
    days_court = compute_days_to(case, "court_date_utc")
    points_deadline = deadline_points(days_deadline)
    points_court = court_points(days_court)
    base_points = SEVERITY_POINTS[case["offense_category"]]
    if case["suspect_in_custody"]:
        base_points += CUSTODY_POINTS
    multiplier = VIOLENT_MULTIPLIER if case["violent_crime_flag"] else Decimal("1.00")
    weighted_base = q2(Decimal(base_points) * multiplier)
    stronger = max(points_deadline, points_court)
    weaker = min(points_deadline, points_court)
    temporal = q2(Decimal(stronger) + Decimal(weaker) * Decimal("0.50"))
    total = q2(weighted_base + temporal)
    if total > SCORE_CAP:
        total = SCORE_CAP
    return total


def derive_priority_class(case):
    """Override wins, then statutory proximity, then violence."""
    if case.get("priority_override_class") is not None:
        return case["priority_override_class"]
    days_deadline = compute_days_to(case, "statutory_deadline_utc")
    if days_deadline is not None and days_deadline <= P1_DEADLINE_DAYS:
        return "P1_STATUTORY"
    if case["violent_crime_flag"]:
        return "P2_VIOLENT"
    return "P3_ROUTINE"


# ---------------------------------------------------------------- case rollup
def case_recompute(case):
    """CASE_RECOMPUTE of PRD section 2.10."""
    if case["workflow_status"] not in ("ACCEPTED", "IN_PROGRESS", "AWAITING_ASSIGNMENT"):
        return case
    rows = requests_of_case(case["id"])
    if rows:
        if any(r["status"] in ER_ACTIVE_SET for r in rows):
            case["workflow_status"] = "IN_PROGRESS"
        elif any(r["status"] == "QUEUED" for r in rows):
            case["workflow_status"] = "AWAITING_ASSIGNMENT"
        else:
            case["workflow_status"] = "IN_PROGRESS"
    case["open_examination_request_count"] = len(
        [r for r in rows if r["status"] not in ER_TERMINAL_SET]
    )
    case["released_examination_request_count"] = len(
        [r for r in rows if r["status"] == "RELEASED"]
    )
    touch(case)
    return case


# ---------------------------------------------------------------- workload
def available_hours(analyst):
    figure = dec(analyst["weekly_capacity_hours"]) - dec(analyst["training_hours_per_week"])
    if figure < 0:
        figure = Decimal("0.00")
    return q2(figure)


def projected_load_hours(analyst):
    total = Decimal("0")
    for row in db.assignments.values():
        if row["analyst_id"] == analyst["id"] and row["status"] == "ACTIVE":
            total += dec(row["estimated_hours"])
    return q2(total)


def realized_load_hours(analyst):
    total = Decimal("0")
    for row in db.assignments.values():
        if row["analyst_id"] != analyst["id"]:
            continue
        if row["status"] not in ("ACTIVE", "COMPLETED"):
            continue
        request_row = db.examination_requests.get(row["examination_request_id"])
        logged = None
        if request_row is not None:
            logged = request_row.get("actual_hours_logged")
        if logged is not None:
            total += dec(logged)
        else:
            total += dec(row["estimated_hours"])
    return q2(total)


def utilization_pct(load, available):
    if available == Decimal("0.00"):
        return Decimal("0.00")
    return q2(load / available * Decimal(100))


def active_assignment_count(analyst_id):
    return len([
        a for a in db.assignments.values()
        if a["analyst_id"] == analyst_id and a["status"] == "ACTIVE"
    ])


def workload_document(analyst):
    available = available_hours(analyst)
    projected = projected_load_hours(analyst)
    realized = realized_load_hours(analyst)
    training = dec(analyst["training_hours_per_week"])
    if training == Decimal("0.00"):
        ratio = Decimal("0.00")
    else:
        ratio = q2(projected / training)
    return {
        "analyst_id": analyst["id"],
        "available_hours": available,
        "projected_load_hours": projected,
        "projected_utilization_pct": utilization_pct(projected, available),
        "realized_load_hours": realized,
        "realized_utilization_pct": utilization_pct(realized, available),
        "casework_training_ratio": ratio,
        "active_assignment_count": active_assignment_count(analyst["id"]),
        "assigned_casework_hours": q2(analyst["assigned_casework_hours"]),
    }


def post_assignment_utilization(analyst, extra_hours):
    """The capacity gate figure of PRD section 3.4."""
    available = available_hours(analyst)
    if available == Decimal("0.00"):
        return None
    projected = projected_load_hours(analyst)
    return q2((projected + dec(extra_hours)) / available * Decimal(100))


def capacity_admits(analyst, extra_hours):
    figure = post_assignment_utilization(analyst, extra_hours)
    if figure is None:
        return False
    return figure <= UTILIZATION_CEILING_PCT


def add_casework_hours(analyst, hours):
    analyst["assigned_casework_hours"] = q2(
        dec(analyst["assigned_casework_hours"]) + dec(hours)
    )
    touch(analyst)


def subtract_casework_hours(analyst, hours):
    figure = q2(dec(analyst["assigned_casework_hours"]) - dec(hours))
    if figure < Decimal("0.00"):
        figure = Decimal("0.00")
    analyst["assigned_casework_hours"] = figure
    touch(analyst)


# ---------------------------------------------------------------- releases
def _release_assignment(analyst, row):
    request_row = db.examination_requests.get(row["examination_request_id"])
    row["status"] = "RELEASED"
    row["closed_at_utc"] = db.now()
    touch(row)
    subtract_casework_hours(analyst, row["estimated_hours"])
    if request_row is not None:
        request_row["assigned_analyst_id"] = None
        request_row["status"] = "QUEUED"
        touch(request_row)
        case_row = db.cases.get(request_row["case_id"])
        if case_row is not None:
            case_recompute(case_row)


def probation_release(analyst):
    """PROBATION_RELEASE of PRD section 2.10."""
    for row in assignments_of_analyst(analyst["id"]):
        if row["status"] != "ACTIVE":
            continue
        request_row = db.examination_requests.get(row["examination_request_id"])
        if request_row is None:
            continue
        case_row = db.cases.get(request_row["case_id"])
        if case_row is None:
            continue
        if case_row["priority_class"] not in ("P1_STATUTORY", "P2_VIOLENT"):
            continue
        _release_assignment(analyst, row)


def full_release(analyst):
    """FULL_RELEASE of PRD section 2.10 - no queue-class filter."""
    for row in assignments_of_analyst(analyst["id"]):
        if row["status"] != "ACTIVE":
            continue
        _release_assignment(analyst, row)


# ---------------------------------------------------------------- qualification
def enter_probation(analyst):
    """QUALIFIED -> PROBATION with the probation release cascade."""
    if analyst["qualification_state"] != "QUALIFIED":
        return False
    analyst["qualification_state"] = "PROBATION"
    analyst["probation_entered_at_utc"] = db.now()
    touch(analyst)
    probation_release(analyst)
    return True


def restore_to_qualified(analyst, excluding=None):
    """PROBATION -> QUALIFIED once no finding against the examiner is live."""
    if analyst is None or analyst["qualification_state"] != "PROBATION":
        return False
    if has_live_nonconformance(analyst["id"], excluding=excluding):
        return False
    analyst["qualification_state"] = "QUALIFIED"
    analyst["consecutive_pt_failures"] = 0
    analyst["probation_entered_at_utc"] = None
    touch(analyst)
    return True


def is_bench_eligible(analyst, case_row):
    """Eligible to hold or resume bench work on this case."""
    if analyst is None:
        return False
    if analyst["employment_status"] != "ACTIVE":
        return False
    if analyst["qualification_state"] == "QUALIFIED":
        return True
    if analyst["qualification_state"] == "PROBATION":
        if case_row is None:
            return False
        return (
            case_row["priority_class"] == "P3_ROUTINE"
            and dec(analyst["training_hours_per_week"]) >= PROBATION_TRAINING_MINIMUM
        )
    return False


# ---------------------------------------------------------------- hold reopening
def reopen_hold(request_row):
    """REOPEN_HOLD of PRD section 2.10. Returns 'REOPEN' or 'REQUEUE'."""
    case_row = db.cases.get(request_row["case_id"])
    candidates = [
        a for a in assignments_of_request(request_row["id"])
        if a["status"] == "COMPLETED"
    ]
    candidate = None
    if candidates:
        newest = max(a["assigned_at_utc"] for a in candidates)
        tied = [a for a in candidates if a["assigned_at_utc"] == newest]
        candidate = sorted(tied, key=lambda a: (a["created_at"], a["_seq"]))[0]
    analyst = None
    if request_row.get("assigned_analyst_id") is not None:
        analyst = db.analysts.get(request_row["assigned_analyst_id"])
    if candidate is not None and is_bench_eligible(analyst, case_row):
        candidate["status"] = "ACTIVE"
        candidate["closed_at_utc"] = None
        touch(candidate)
        add_casework_hours(analyst, candidate["estimated_hours"])
        request_row["status"] = "IN_ANALYSIS"
        touch(request_row)
        item = db.evidence_items.get(request_row["evidence_item_id"])
        if item is not None:
            item["custody_status"] = "IN_ANALYSIS"
            item["checkout_count"] = item["checkout_count"] + 1
            touch(item)
        if case_row is not None:
            case_recompute(case_row)
        return "REOPEN"
    request_row["assigned_analyst_id"] = None
    request_row["status"] = "QUEUED"
    touch(request_row)
    if case_row is not None:
        case_recompute(case_row)
    return "REQUEUE"


# ---------------------------------------------------------------- findings
def open_nonconformance(source, severity, description,
                        examination_request_id=None, analyst_id=None,
                        sla_days=None):
    opened = db.now()
    days = sla_days if sla_days is not None else CAPA_SLA_DAYS[severity]
    row = new_row()
    row.update({
        "examination_request_id": examination_request_id,
        "analyst_id": analyst_id,
        "source": source,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "root_cause_category": None,
        "corrective_action_plan": None,
        "capa_rejection_count": 0,
        "opened_at_utc": opened,
        "due_utc": add_days(opened, days),
        "closed_at_utc": None,
        "overdue": False,
    })
    db.nonconformances[row["id"]] = row
    return row


# ---------------------------------------------------------------- turnaround
def merged_vendor_custody_seconds(case_id):
    """Merge the RETURNED custody windows of a case as closed intervals."""
    windows = []
    for request_row in requests_of_case(case_id):
        for engagement in engagements_of_request(request_row["id"]):
            if engagement["status"] != "RETURNED":
                continue
            if engagement.get("returned_at_utc") is None:
                continue
            windows.append((
                engagement["awarded_at_utc"],
                engagement["returned_at_utc"],
                engagement["created_at"],
                engagement["_seq"],
            ))
    windows.sort(key=lambda w: (w[0], w[2], w[3]))
    total = 0
    current_start = None
    current_end = None
    for start, end, _created, _seq in windows:
        if current_start is None:
            current_start, current_end = start, end
            continue
        if start <= current_end:
            if end > current_end:
                current_end = end
            continue
        total += int((current_end - current_start).total_seconds())
        current_start, current_end = start, end
    if current_start is not None:
        total += int((current_end - current_start).total_seconds())
    return total


def compute_turnaround(case):
    gross = fractional_days(case["received_at_utc"], case["reported_at_utc"])
    vendor_seconds = merged_vendor_custody_seconds(case["id"])
    vendor_days = q2(Decimal(vendor_seconds) / Decimal(86400))
    net = q2(gross - vendor_days)
    if net < Decimal("0.00"):
        net = Decimal("0.00")
    return gross, net


def refresh_vendor_custody_days(request_row):
    total = Decimal("0")
    for engagement in engagements_of_request(request_row["id"]):
        if engagement["status"] == "RETURNED" and engagement.get("custody_days") is not None:
            total += dec(engagement["custody_days"])
    request_row["vendor_custody_days"] = q2(total)


# ---------------------------------------------------------------- vendor pricing
def price_award(vendor, item_count, rush_flag):
    """The pinned six-step chain of PRD section 3.7."""
    base = int(vendor["unit_price_cents"]) * int(item_count)
    if rush_flag:
        surcharge = qcents(Decimal(base) * dec(vendor["rush_surcharge_pct"]))
    else:
        surcharge = 0
    tier_basis = base + surcharge
    discount_pct = Decimal("0.00")
    for floor_cents, pct in VOLUME_TIERS:
        if tier_basis >= floor_cents:
            discount_pct = pct
            break
    discount = qcents(Decimal(tier_basis) * discount_pct)
    award = tier_basis - discount
    return {
        "base_amount_cents": base,
        "rush_surcharge_cents": surcharge,
        "tier_basis_cents": tier_basis,
        "volume_discount_pct": discount_pct,
        "discount_amount_cents": discount,
        "award_amount_cents": award,
    }


def windows_intersect_closed(start_a, end_a, start_b, end_b):
    """Closed at both ends: touching endpoints do intersect."""
    return not (end_a < start_b or start_a > end_b)


def occupying_engagements(vendor_id):
    return [
        e for e in engagements_of_vendor(vendor_id)
        if e["status"] in ("AWARDED", "AT_VENDOR")
    ]


# ---------------------------------------------------------------- backlog
def backlog_report(as_of, discipline):
    population = [
        r for r in db.examination_requests.values()
        if r["status"] not in ER_TERMINAL_SET
    ]
    if discipline is not None:
        population = [r for r in population if r["discipline"] == discipline]
    open_count = len(population)
    buckets = [0, 0, 0, 0]
    p1_open = 0
    weighted_total = Decimal("0")
    for request_row in population:
        age = fractional_days(request_row["requested_at_utc"], as_of)
        case_row = db.cases.get(request_row["case_id"])
        priority_class = case_row["priority_class"] if case_row else "P3_ROUTINE"
        if priority_class == "P1_STATUTORY":
            p1_open += 1
        weighted_total += q2(age * PRIORITY_WEIGHTS[priority_class])
        if age < Decimal("30.00"):
            buckets[0] += 1
        elif age < Decimal("60.00"):
            buckets[1] += 1
        elif age < Decimal("90.00"):
            buckets[2] += 1
        else:
            buckets[3] += 1
    if open_count == 0:
        index = Decimal("0.00")
    else:
        index = q2(weighted_total / Decimal(open_count))
    return {
        "as_of_utc": as_of,
        "open_request_count": open_count,
        "backlog_index": index,
        "bucket_0_29_count": buckets[0],
        "bucket_30_59_count": buckets[1],
        "bucket_60_89_count": buckets[2],
        "bucket_90_plus_count": buckets[3],
        "p1_open_count": p1_open,
        "outsourcing_recommended": index >= BACKLOG_OUTSOURCING_THRESHOLD,
    }
