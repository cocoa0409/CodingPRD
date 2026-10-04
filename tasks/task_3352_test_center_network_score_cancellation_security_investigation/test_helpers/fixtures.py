"""Composite setup helpers.

Every function drives the live API end to end and returns plain dicts (the
`data` payloads of successful responses). Setup calls use the lenient
get_success_data validator so a failing precondition surfaces as a clear
"Setup step failed" error. Each helper builds its preconditions from scratch
because the harness restarts the server before every test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADMIN_1_ID,
    ADMIN_2_ID,
    ANALYST_1_ID,
    CLOCK_PAST_RESPONSE_DEADLINE,
    CLOCK_TEST_DAY_AFTER,
    CLOCK_TEST_DAY_MORNING,
    DEFAULT_TOTAL_SCORED_ITEMS,
    DOC_EXPIRY_VALID,
    PASSING_AUDIT_FINDINGS,
    RAWS_PROVISIONAL_97,
    SESSION_END_TIME,
    SESSION_START_TIME,
    TEST_DATE,
)
from .factories import (
    adjudicate_case_payload,
    complete_audit_payload,
    create_accommodation_request_payload,
    create_audit_payload,
    create_check_in_payload,
    create_examinee_payload,
    create_irregularity_payload,
    create_registration_payload,
    create_score_entry_payload,
    create_score_report_payload,
    create_session_payload,
    create_staff_payload,
    create_test_center_payload,
    decide_accommodation_payload,
    resolve_irregularity_payload,
    respond_case_payload,
    run_analysis_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_center_manager_headers,
    make_examinee_headers,
    make_proctor_headers,
    make_program_admin_headers,
    make_score_analyst_headers,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


# --- Tier 1/2: centers, audits, staff, sessions, examinees ---

def create_center(name="Test Center", facility_seat_capacity=20, equipment_list=None):
    resp = api_client.create_test_center(
        create_test_center_payload(
            name=name,
            facility_seat_capacity=facility_seat_capacity,
            equipment_list=equipment_list,
        ),
        _ADMIN,
    )
    return get_success_data(resp, 201)


def schedule_audit(center_id, scheduled_date="2026-09-05", audit_type="ANNOUNCED"):
    resp = api_client.create_audit(
        center_id, create_audit_payload(scheduled_date, audit_type), _ADMIN
    )
    return get_success_data(resp, 201)


def complete_audit(audit_id, findings=None):
    resp = api_client.complete_audit(
        audit_id,
        complete_audit_payload(**(findings or PASSING_AUDIT_FINDINGS)),
        _AUDITOR,
    )
    return get_success_data(resp, 200)


def get_center(center_id):
    return get_success_data(api_client.get_test_center(center_id, _ADMIN), 200)


def create_authorized_center(name="Center", facility_seat_capacity=20):
    """Center + one passing ANNOUNCED audit (findings 1,1,2,0 -> 82 PASSED)."""
    center = create_center(name=name, facility_seat_capacity=facility_seat_capacity)
    audit = schedule_audit(center["id"])
    complete_audit(audit["id"])
    return get_center(center["id"])


def add_staff(center_id, full_name, staff_role, certification_level="BASIC"):
    resp = api_client.create_staff(
        center_id,
        create_staff_payload(full_name, staff_role, certification_level),
        _ADMIN,
    )
    return get_success_data(resp, 201)


def create_session(center_id, **overrides):
    resp = api_client.create_session(
        center_id, create_session_payload(**overrides), _ADMIN
    )
    return get_success_data(resp, 201)


def get_session(session_id):
    return get_success_data(api_client.get_session(session_id, _ADMIN), 200)


def publish_session(session_id, manager_id):
    resp = api_client.publish_session(
        session_id, make_center_manager_headers(manager_id)
    )
    return get_success_data(resp, 200)


def create_published_session(center_id, manager_id, **overrides):
    """Create + publish a session; returns the fresh PUBLISHED session dict."""
    session = create_session(center_id, **overrides)
    publish_session(session["id"], manager_id)
    return get_session(session["id"])


def assign_proctor(session_id, staff_id, manager_id):
    resp = api_client.assign_proctor(
        session_id, {"staff_id": staff_id}, make_center_manager_headers(manager_id)
    )
    return get_success_data(resp, 200)


def create_examinee(
    full_name="Ex Aminee",
    id_document_number="P0001",
    id_document_type="PASSPORT",
    id_document_expiry=DOC_EXPIRY_VALID,
    date_of_birth="2000-01-15",
):
    resp = api_client.create_examinee(
        create_examinee_payload(
            full_name=full_name,
            date_of_birth=date_of_birth,
            id_document_type=id_document_type,
            id_document_number=id_document_number,
            id_document_expiry=id_document_expiry,
        ),
        _ADMIN,
    )
    return get_success_data(resp, 201)


def get_examinee(examinee_id):
    return get_success_data(api_client.get_examinee(examinee_id, _ADMIN), 200)


# --- Registration ---

def register_examinee(session_id, examinee_id):
    """Read the current session version, then register the examinee (OCC)."""
    version = get_session(session_id)["version"]
    resp = api_client.create_registration(
        session_id,
        create_registration_payload(examinee_id, version),
        make_examinee_headers(examinee_id),
    )
    return get_success_data(resp, 201)


def register_new_examinee(session_id, full_name="Ex", id_document_number="P0001",
                          **examinee_kw):
    examinee = create_examinee(
        full_name=full_name, id_document_number=id_document_number, **examinee_kw
    )
    registration = register_examinee(session_id, examinee["id"])
    return examinee, registration


def get_registration(registration_id):
    return get_success_data(api_client.get_registration(registration_id, _ADMIN), 200)


# --- Test-day lifecycle ---

def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN)
    return get_success_data(resp, 200)


def lock_session(session_id, manager_id, at=CLOCK_TEST_DAY_MORNING):
    """Set the clock to the session's test date morning, then lock."""
    set_clock(at)
    resp = api_client.lock_session(session_id, make_center_manager_headers(manager_id))
    return get_success_data(resp, 200)


def check_in_admit(registration_id, examinee, proctor_id, biometric_sample="bio-s"):
    """Check in with the examinee's own document data -> ADMITTED."""
    resp = api_client.check_in(
        registration_id,
        create_check_in_payload(
            examinee["id_document_number"],
            examinee["id_document_expiry"],
            biometric_sample,
        ),
        make_proctor_headers(proctor_id),
    )
    return get_success_data(resp, 201)


def administer_session(session_id, manager_id, at=CLOCK_TEST_DAY_AFTER):
    """Set the clock past end_time, then close administration."""
    set_clock(at)
    resp = api_client.administer_session(
        session_id, make_center_manager_headers(manager_id)
    )
    return get_success_data(resp, 200)


# --- Scoring ---

def enter_score(registration_id, section_raws=None, prior_best_scaled_score=30,
                matched_responses_count=0,
                total_scored_items=DEFAULT_TOTAL_SCORED_ITEMS, same_form=True,
                adjacent_seated=False, analyst_id=ANALYST_1_ID):
    resp = api_client.create_score_entry(
        registration_id,
        create_score_entry_payload(
            section_raws=section_raws,
            prior_best_scaled_score=prior_best_scaled_score,
            matched_responses_count=matched_responses_count,
            total_scored_items=total_scored_items,
            same_form=same_form,
            adjacent_seated=adjacent_seated,
        ),
        make_score_analyst_headers(analyst_id),
    )
    return get_success_data(resp, 201)


def run_score_analysis(session_id, analyst_id=ANALYST_1_ID):
    resp = api_client.run_score_analysis(
        run_analysis_payload(session_id), make_score_analyst_headers(analyst_id)
    )
    return get_success_data(resp, 200)


def get_score_record(score_record_id):
    return get_success_data(
        api_client.get_score_record(score_record_id, TEST_USERS["score_analyst_headers"]),
        200,
    )


# --- Tier 3/4: full scenario builders ---

def setup_bookable_session(name="Center", total_seats=5,
                           reserved_accommodation_seats=0, with_proctor=False,
                           assign=False, **session_overrides):
    """AUTHORIZED center + manager (+proctor) + PUBLISHED session.

    Returns dict(center, manager, proctor, session, examinees, registrations).
    """
    center = create_authorized_center(name=name)
    manager = add_staff(center["id"], f"Mgr {name}", "CENTER_MANAGER", "ADVANCED")
    proctor = (
        add_staff(center["id"], f"Proc {name}", "PROCTOR", "BASIC")
        if with_proctor
        else None
    )
    session = create_published_session(
        center["id"], manager["id"],
        total_seats=total_seats,
        reserved_accommodation_seats=reserved_accommodation_seats,
        **session_overrides,
    )
    if assign and proctor is not None:
        assign_proctor(session["id"], proctor["id"], manager["id"])
        session = get_session(session["id"])
    return {
        "center": center,
        "manager": manager,
        "proctor": proctor,
        "session": session,
        "examinees": [],
        "registrations": [],
    }


def setup_administered_session(score_specs, name="Center", total_seats=10,
                               reserved_accommodation_seats=0, assign=False):
    """AUTHORIZED center, PUBLISHED session, one examinee per score spec:
    registered CONFIRMED, ADMITTED on test day; session ADMINISTERED; each
    spec's ScoreRecord entered (PENDING_ANALYSIS). Returns the context dict
    with added keys examinees, registrations, score_records.
    """
    ctx = setup_bookable_session(
        name=name, total_seats=total_seats,
        reserved_accommodation_seats=reserved_accommodation_seats,
        with_proctor=True, assign=assign,
    )
    session_id = ctx["session"]["id"]
    for i, spec in enumerate(score_specs):
        examinee, registration = register_new_examinee(
            session_id,
            full_name=spec.get("full_name", f"Ex {name} {i + 1}"),
            id_document_number=spec.get("id_document_number", f"PD{i:04d}"),
            id_document_type=spec.get("id_document_type", "PASSPORT"),
            id_document_expiry=spec.get("id_document_expiry", DOC_EXPIRY_VALID),
        )
        ctx["examinees"].append(examinee)
        ctx["registrations"].append(registration)
    lock_session(session_id, ctx["manager"]["id"])
    for examinee, registration in zip(ctx["examinees"], ctx["registrations"]):
        check_in_admit(
            registration["id"], examinee, ctx["proctor"]["id"],
            biometric_sample=f"bio-{registration['id'][:8]}",
        )
    administer_session(session_id, ctx["manager"]["id"])
    score_records = []
    for registration, spec in zip(ctx["registrations"], score_specs):
        score_records.append(enter_score(
            registration["id"],
            section_raws=spec["section_raws"],
            prior_best_scaled_score=spec["prior_best_scaled_score"],
            matched_responses_count=spec.get("matched_responses_count", 0),
            total_scored_items=spec.get("total_scored_items",
                                        DEFAULT_TOTAL_SCORED_ITEMS),
            same_form=spec.get("same_form", True),
            adjacent_seated=spec.get("adjacent_seated", False),
        ))
    ctx["score_records"] = score_records
    ctx["session"] = get_session(session_id)
    return ctx


def setup_analyzed_session(score_specs, analyst_id=ANALYST_1_ID, **kw):
    """setup_administered_session + the score-analysis run. Adds run_output."""
    ctx = setup_administered_session(score_specs, **kw)
    ctx["run_output"] = run_score_analysis(ctx["session"]["id"], analyst_id=analyst_id)
    ctx["session"] = get_session(ctx["session"]["id"])
    return ctx


# --- Score review cases ---

def list_review_cases(registration_id):
    return get_success_data(
        api_client.list_review_cases(registration_id, _ADMIN), 200
    )


def get_only_review_case(registration_id):
    cases = list_review_cases(registration_id)
    assert len(cases) == 1, f"expected exactly one review case, got {len(cases)}"
    return cases[0]


def fresh_case_version(registration_id):
    """Read path for a case's current version (PRD §2.7)."""
    return get_only_review_case(registration_id)["version"]


def notify_case(case_id, analyst_id=ANALYST_1_ID):
    resp = api_client.notify_case(case_id, make_score_analyst_headers(analyst_id))
    return get_success_data(resp, 200)


def respond_to_case(case_id, examinee_id, response_text="Written response."):
    resp = api_client.respond_case(
        case_id, respond_case_payload(response_text), make_examinee_headers(examinee_id)
    )
    return get_success_data(resp, 200)


def adjudicate_case(case_id, outcome, rationale, expected_case_version,
                    admin_id=ADMIN_2_ID):
    resp = api_client.adjudicate_case(
        case_id,
        adjudicate_case_payload(outcome, rationale, expected_case_version),
        make_program_admin_headers(admin_id),
    )
    return get_success_data(resp, 200)


def send_report(score_record_id, institution_code="MIT2026", analyst_id=ANALYST_1_ID):
    resp = api_client.create_score_report(
        score_record_id,
        create_score_report_payload(institution_code),
        make_score_analyst_headers(analyst_id),
    )
    return get_success_data(resp, 201)


def list_reports(score_record_id):
    return get_success_data(
        api_client.list_score_reports(
            score_record_id, TEST_USERS["score_analyst_headers"]
        ),
        200,
    )


# A single record: raw_total 94, provisional 97, session mean 94.00, so the
# equated score stays 97; prior 50 -> gain 47 >= 30 -> ANOMALOUS_GAIN case.
GAIN_FLAG_SPEC = {
    "section_raws": RAWS_PROVISIONAL_97,
    "prior_best_scaled_score": 50,
    "matched_responses_count": 0,
    "total_scored_items": DEFAULT_TOTAL_SCORED_ITEMS,
    "same_form": True,
    "adjacent_seated": False,
}

# A clean record: provisional/scaled 30, gain 0, no similarity -> RELEASED.
CLEAN_SCORE_SPEC = {
    "section_raws": [10, 10, 10],
    "prior_best_scaled_score": 30,
    "matched_responses_count": 0,
    "total_scored_items": DEFAULT_TOTAL_SCORED_ITEMS,
    "same_form": True,
    "adjacent_seated": False,
}


def setup_open_gain_case(name="Center", analyst_id=ANALYST_1_ID):
    """Gain-flagged case opened by the analysis run (flagged_by == analyst_id).

    Clock is left at CLOCK_TEST_DAY_AFTER after the run.
    Returns ctx with case, score_record, registration, examinee, session.
    """
    ctx = setup_analyzed_session([dict(GAIN_FLAG_SPEC)], name=name,
                                 analyst_id=analyst_id)
    ctx["case"] = get_only_review_case(ctx["registrations"][0]["id"])
    ctx["score_record"] = get_score_record(ctx["score_records"][0]["id"])
    ctx["registration"] = ctx["registrations"][0]
    ctx["examinee"] = ctx["examinees"][0]
    return ctx


def setup_exposure_case(name="Center", institution_codes=(), respond=False,
                        expire_window=False):
    """Clean RELEASED score; optional reports sent; assigned proctor files a
    CONTENT_EXPOSURE report; admin-1 substantiates it -> case OPENED with
    flagged_by == admin-1 and the score UNDER_REVIEW; then notify, and
    optionally respond / advance the clock past the response deadline.
    """
    ctx = setup_analyzed_session([dict(CLEAN_SCORE_SPEC)], name=name, assign=True)
    ctx["score_record"] = get_score_record(ctx["score_records"][0]["id"])
    ctx["registration"] = ctx["registrations"][0]
    ctx["examinee"] = ctx["examinees"][0]
    ctx["reports"] = [
        send_report(ctx["score_record"]["id"], code) for code in institution_codes
    ]
    irr_resp = api_client.create_irregularity_report(
        ctx["session"]["id"],
        create_irregularity_payload(
            registration_id=ctx["registration"]["id"],
            category="CONTENT_EXPOSURE",
            severity="HIGH",
            narrative="Pre-knowledge of secure items",
        ),
        make_proctor_headers(ctx["proctor"]["id"]),
    )
    ctx["irregularity"] = get_success_data(irr_resp, 201)
    resolve_resp = api_client.resolve_irregularity_report(
        ctx["irregularity"]["id"],
        resolve_irregularity_payload("SUBSTANTIATED"),
        make_program_admin_headers(ADMIN_1_ID),
    )
    get_success_data(resolve_resp, 200)
    case = get_only_review_case(ctx["registration"]["id"])
    notify_case(case["id"])
    if respond:
        respond_to_case(case["id"], ctx["examinee"]["id"])
    if expire_window:
        set_clock(CLOCK_PAST_RESPONSE_DEADLINE)
    ctx["case"] = get_only_review_case(ctx["registration"]["id"])
    return ctx
