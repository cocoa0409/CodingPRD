"""Entity serialisation. Only scaffold-declared fields are exposed."""
from store import db
from util import as_number, fmt_instant

RAW = "raw"
INSTANT = "instant"
NUMBER = "number"

AUDIT = [("created_at", INSTANT), ("updated_at", INSTANT), ("version", RAW)]

ANALYST_SPEC = [
    ("id", RAW),
    ("full_name", RAW),
    ("disciplines", RAW),
    ("competency_level", RAW),
    ("weekly_capacity_hours", NUMBER),
    ("training_hours_per_week", NUMBER),
    ("employment_status", RAW),
    ("qualification_state", RAW),
    ("consecutive_pt_failures", RAW),
    ("assigned_casework_hours", NUMBER),
    ("probation_entered_at_utc", INSTANT),
    ("suspended_at_utc", INSTANT),
] + AUDIT

METHOD_SPEC = [
    ("id", RAW),
    ("name", RAW),
    ("discipline", RAW),
    ("standard_hours_per_item", NUMBER),
    ("min_competency_level", RAW),
    ("max_items_per_request", RAW),
    ("is_consumptive", RAW),
    ("accreditation_scope_code", RAW),
    ("validation_status", RAW),
    ("validation_study_item_count", RAW),
    ("precision_cv_pct", NUMBER),
    ("validated_at_utc", INSTANT),
    ("validation_expires_at_utc", INSTANT),
    ("retired_at_utc", INSTANT),
    ("retirement_reason", RAW),
] + AUDIT

CASE_SPEC = [
    ("id", RAW),
    ("agency_case_number", RAW),
    ("submitting_agency", RAW),
    ("offense_category", RAW),
    ("violent_crime_flag", RAW),
    ("suspect_in_custody", RAW),
    ("statutory_deadline_utc", INSTANT),
    ("court_date_utc", INSTANT),
    ("received_at_utc", INSTANT),
    ("priority_score", NUMBER),
    ("priority_class", RAW),
    ("priority_override_class", RAW),
    ("priority_override_reason", RAW),
    ("workflow_status", RAW),
    ("discovery_status", RAW),
    ("discovery_requested_at_utc", INSTANT),
    ("discovery_due_utc", INSTANT),
    ("discovery_requesting_party", RAW),
    ("open_examination_request_count", RAW),
    ("released_examination_request_count", RAW),
    ("accepted_at_utc", INSTANT),
    ("reported_at_utc", INSTANT),
    ("gross_turnaround_days", NUMBER),
    ("net_turnaround_days", NUMBER),
    ("rejection_reason", RAW),
] + AUDIT

EVIDENCE_ITEM_SPEC = [
    ("id", RAW),
    ("case_id", RAW),
    ("item_number", RAW),
    ("item_description", RAW),
    ("item_type", RAW),
    ("seal_intact", RAW),
    ("custody_status", RAW),
    ("checkout_count", RAW),
    ("logged_at_utc", INSTANT),
] + AUDIT

EXAMINATION_REQUEST_SPEC = [
    ("id", RAW),
    ("case_id", RAW),
    ("evidence_item_id", RAW),
    ("method_id", RAW),
    ("assigned_analyst_id", RAW),
    ("discipline", RAW),
    ("item_count", RAW),
    ("estimated_hours", NUMBER),
    ("actual_hours_logged", NUMBER),
    ("status", RAW),
    ("revision_round", RAW),
    ("requested_at_utc", INSTANT),
    ("released_at_utc", INSTANT),
    ("vendor_custody_days", NUMBER),
] + AUDIT

ASSIGNMENT_SPEC = [
    ("id", RAW),
    ("examination_request_id", RAW),
    ("analyst_id", RAW),
    ("estimated_hours", NUMBER),
    ("assignment_reason", RAW),
    ("status", RAW),
    ("superseded_by_assignment_id", RAW),
    ("assigned_at_utc", INSTANT),
    ("closed_at_utc", INSTANT),
] + AUDIT

REVIEW_RECORD_SPEC = [
    ("id", RAW),
    ("examination_request_id", RAW),
    ("reviewer_analyst_id", RAW),
    ("reviewer_operator_id", RAW),
    ("review_type", RAW),
    ("decision", RAW),
    ("rationale", RAW),
    ("revision_round_snapshot", RAW),
    ("recorded_at_utc", INSTANT),
    ("created_at", INSTANT),
]

PROFICIENCY_TEST_SPEC = [
    ("id", RAW),
    ("analyst_id", RAW),
    ("method_id", RAW),
    ("test_cycle", RAW),
    ("due_utc", INSTANT),
    ("status", RAW),
    ("submitted_at_utc", INSTANT),
    ("score_pct", NUMBER),
    ("result", RAW),
    ("late_submission", RAW),
    ("scored_at_utc", INSTANT),
] + AUDIT

VENDOR_SPEC = [
    ("id", RAW),
    ("name", RAW),
    ("accredited_disciplines", RAW),
    ("accreditation_expires_at_utc", INSTANT),
    ("concurrent_case_capacity", RAW),
    ("unit_price_cents", RAW),
    ("rush_surcharge_pct", NUMBER),
    ("contract_ceiling_cents", RAW),
    ("encumbered_cents", RAW),
    ("spent_cents", RAW),
    ("status", RAW),
    ("suspension_reason", RAW),
] + AUDIT

VENDOR_ENGAGEMENT_SPEC = [
    ("id", RAW),
    ("examination_request_id", RAW),
    ("vendor_id", RAW),
    ("window_start_utc", INSTANT),
    ("window_end_utc", INSTANT),
    ("rush_flag", RAW),
    ("item_count", RAW),
    ("base_amount_cents", RAW),
    ("rush_surcharge_cents", RAW),
    ("tier_basis_cents", RAW),
    ("volume_discount_pct", NUMBER),
    ("discount_amount_cents", RAW),
    ("award_amount_cents", RAW),
    ("final_invoice_cents", RAW),
    ("variance_cents", RAW),
    ("status", RAW),
    ("awarded_at_utc", INSTANT),
    ("shipped_at_utc", INSTANT),
    ("returned_at_utc", INSTANT),
    ("custody_days", NUMBER),
    ("cancellation_reason", RAW),
] + AUDIT

NONCONFORMANCE_SPEC = [
    ("id", RAW),
    ("examination_request_id", RAW),
    ("analyst_id", RAW),
    ("source", RAW),
    ("severity", RAW),
    ("description", RAW),
    ("status", RAW),
    ("root_cause_category", RAW),
    ("corrective_action_plan", RAW),
    ("capa_rejection_count", RAW),
    ("opened_at_utc", INSTANT),
    ("due_utc", INSTANT),
    ("closed_at_utc", INSTANT),
    ("overdue", RAW),
] + AUDIT

COURT_EVENT_SPEC = [
    ("id", RAW),
    ("examination_request_id", RAW),
    ("analyst_id", RAW),
    ("court_name", RAW),
    ("docket_number", RAW),
    ("start_utc", INSTANT),
    ("end_utc", INSTANT),
    ("notice_days", RAW),
    ("subpoena_received", RAW),
    ("status", RAW),
    ("testimony_note", RAW),
    ("cancellation_reason", RAW),
] + AUDIT


def render(row, spec):
    out = {}
    for name, kind in spec:
        value = row.get(name)
        if kind == INSTANT:
            out[name] = fmt_instant(value)
        elif kind == NUMBER:
            out[name] = as_number(value)
        else:
            out[name] = value
    return out


def analyst(row):
    return render(row, ANALYST_SPEC)


def method(row):
    return render(row, METHOD_SPEC)


def case(row):
    return render(row, CASE_SPEC)


def evidence_item(row):
    return render(row, EVIDENCE_ITEM_SPEC)


def examination_request(row):
    return render(row, EXAMINATION_REQUEST_SPEC)


def assignment(row):
    return render(row, ASSIGNMENT_SPEC)


def review_record(row):
    return render(row, REVIEW_RECORD_SPEC)


def proficiency_test(row):
    return render(row, PROFICIENCY_TEST_SPEC)


def vendor(row):
    return render(row, VENDOR_SPEC)


def vendor_engagement(row):
    return render(row, VENDOR_ENGAGEMENT_SPEC)


def nonconformance(row):
    """overdue is recomputed against the logical clock at read time."""
    body = render(row, NONCONFORMANCE_SPEC)
    body["overdue"] = is_overdue(row)
    return body


def is_overdue(row):
    if row["status"] in ("CLOSED", "VOIDED"):
        return False
    if row.get("due_utc") is None:
        return False
    return db.now() > row["due_utc"]


def court_event(row):
    return render(row, COURT_EVENT_SPEC)
