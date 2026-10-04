"""Composite setup helpers: multi-step fixture chains used across the suite.

Every fixture builds its preconditions from scratch against a freshly restarted
server (the harness relaunches the server before each test), so the logical
clock always starts at 2026-09-01T00:00:00Z (PRD §2.4) and is pinned here.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_alignment_payload,
    create_audit_finding_payload,
    create_course_session_payload,
    create_guidelines_version_payload,
    create_instructor_payload,
    create_monitoring_payload,
    create_quality_audit_payload,
    create_roster_entry_payload,
    create_site_payload,
    create_teaching_evaluation_payload,
    create_training_center_payload,
)
from .test_users import (
    TEST_USERS,
    make_faculty_headers,
    make_instructor_headers,
)

ADMIN = TEST_USERS["national_admin_headers"]
TC = TEST_USERS["tc_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
QA = TEST_USERS["qa_auditor_headers"]

CLOCK_START = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource progression
# ---------------------------------------------------------------------------

def set_clock_start():
    """Pin the logical clock at the documented startup instant."""
    get_success_data(api_client.set_clock(CLOCK_START, ADMIN))


def create_center(**overrides):
    """Create a PROVISIONAL training center. Returns the center dict."""
    set_clock_start()
    return get_success_data(api_client.create_training_center(
        create_training_center_payload(**overrides), ADMIN))


def create_legacy_certified_instructor(center_id, *, is_faculty=False,
                                       discipline="BLS", full_name="Lena Legacy",
                                       email="lena@x.example"):
    """NationalAdmin legacy bootstrap: instructor created directly CERTIFIED
    (PRD §3.2). Returns the instructor dict."""
    instr = get_success_data(api_client.create_instructor(
        create_instructor_payload(
            center_id, full_name=full_name, email=email, discipline=discipline,
            legacy_certified=True),
        ADMIN))
    if is_faculty:
        instr = get_success_data(api_client.grant_faculty(instr["id"], ADMIN))
    return instr


def center_version(center_id, headers=None):
    return get_success_data(
        api_client.get_training_center(center_id, headers or TC))["version"]


def align_center_site(center_id, site_id, headers=None):
    """Align one site against the center's current version (OCC, PRD §2.10)."""
    v = center_version(center_id, headers)
    return get_success_data(api_client.align_site(
        site_id, {"expected_training_center_version": v}, TC))


def create_guidelines_version_active(code="G2025", **overrides):
    """Create + activate a guidelines version. Returns the ACTIVE version."""
    gv = get_success_data(api_client.create_guidelines_version(
        create_guidelines_version_payload(code=code, **overrides), ADMIN))
    return get_success_data(
        api_client.activate_guidelines_version(gv["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: center/site/faculty hierarchy
# ---------------------------------------------------------------------------

def create_center_with_faculty(**overrides):
    """Center + legacy faculty with an ACTIVE as_faculty alignment.

    Returns (center, faculty)."""
    center = create_center(**overrides)
    faculty = create_legacy_certified_instructor(
        center["id"], is_faculty=True, full_name="Fiona Faculty",
        email="fiona@x.example")
    get_success_data(api_client.create_alignment(
        center["id"],
        create_alignment_payload(faculty["id"], as_faculty=True), TC))
    return center, faculty


def create_center_with_aligned_site(*, capacity_students=24, **overrides):
    """Center + faculty oversight + one ALIGNED site (not yet activated).

    Returns (center, faculty, site)."""
    center, faculty = create_center_with_faculty(**overrides)
    site = get_success_data(api_client.create_site(
        center["id"],
        create_site_payload(capacity_students=capacity_students), TC))
    align_center_site(center["id"], site["id"])
    return center, faculty, site


def create_active_center(**overrides):
    """Center + faculty + one ALIGNED site + activation to ACTIVE.

    Returns (center, faculty, site)."""
    center, faculty, site = create_center_with_aligned_site(**overrides)
    center = get_success_data(
        api_client.activate_training_center(center["id"], ADMIN))
    return center, faculty, site


def certify_candidate(center_id, faculty_id, *, discipline="BLS",
                      full_name="Carl Candidate", email="carl@x.example",
                      eval_scores=(4, 5)):
    """Walk a CANDIDATE instructor through monitoring + evaluations +
    certification. Returns the CERTIFIED instructor dict."""
    cand = get_success_data(api_client.create_instructor(
        create_instructor_payload(
            center_id, full_name=full_name, email=email, discipline=discipline),
        ADMIN))
    fac = make_faculty_headers(faculty_id)
    get_success_data(api_client.monitor_instructor(
        cand["id"], create_monitoring_payload(
            course_type_observed=f"{discipline}_PROVIDER"), fac))
    for i, score in enumerate(eval_scores):
        get_success_data(api_client.create_teaching_evaluation(
            cand["id"],
            create_teaching_evaluation_payload(
                score=score, notes=f"Observation {i + 1}."), fac))
    return get_success_data(api_client.certify_instructor(cand["id"], TC))


def align_instructor(center_id, instructor_id, as_faculty=False):
    return get_success_data(api_client.create_alignment(
        center_id,
        create_alignment_payload(instructor_id, as_faculty=as_faculty), TC))


# ---------------------------------------------------------------------------
# Tier 3: full teaching scenario
# ---------------------------------------------------------------------------

def setup_teaching_scenario(*, discipline="BLS", course_type="BLS_PROVIDER",
                            capacity=6, activate=True, guidelines=True,
                            site_capacity=24):
    """ACTIVE center + ALIGNED site + ACTIVE G2025 + a certified, aligned
    session-lead instructor.

    Returns a dict with keys: center, faculty, site, guidelines_version,
    lead."""
    center, faculty, site = create_active_center(
        capacity_students=site_capacity)
    gv = create_guidelines_version_active() if guidelines else None
    lead = certify_candidate(center["id"], faculty["id"], discipline=discipline)
    align_instructor(center["id"], lead["id"])
    return {
        "center": center,
        "faculty": faculty,
        "site": site,
        "guidelines_version": gv,
        "lead": lead,
    }


def create_scheduled_session(ctx, *, capacity=6, start_at="2026-10-10T14:00:00Z",
                             end_at="2026-10-10T18:00:00Z", **overrides):
    """Create a SCHEDULED session inside a teaching scenario context."""
    payload = create_course_session_payload(
        ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
        ctx["guidelines_version"]["id"],
        capacity=capacity, start_at=start_at, end_at=end_at, **overrides)
    return get_success_data(
        api_client.create_course_session(payload, COORD))


def enroll_student(session_id, name="Sam Student", email="sam@x.example",
                   **overrides):
    return get_success_data(api_client.add_roster_entry(
        session_id,
        create_roster_entry_payload(
            student_name=name, student_email=email, **overrides),
        COORD))


def start_session(session_id, headers=None):
    return get_success_data(
        api_client.start_session(session_id, headers or COORD))


def record_passing_evaluation(entry_id, lead_id, *, passed=5, failed=0):
    """Record an all-passing checklist evaluation as the session lead.

    With at least 5 passed and 0 failed items the score is 100, which clears
    both the initial (84.00) and retest (90.00) thresholds."""
    items = [{"item_code": f"I{i + 1:02d}", "critical": i == 0, "passed": True}
             for i in range(passed)]
    items += [{"item_code": f"X{i + 1:02d}", "critical": False, "passed": False}
              for i in range(failed)]
    return get_success_data(api_client.create_skills_evaluation(
        entry_id, {"items": items}, make_instructor_headers(lead_id)))


def complete_session(session_id, lead_id):
    return get_success_data(api_client.complete_session(
        session_id, make_instructor_headers(lead_id)))


def setup_completed_session_with_cards(num_students=1):
    """Full lifecycle: session with num_students PASSED entries, completed,
    cards issued. Returns a dict with ctx plus session, entries, cards."""
    ctx = setup_teaching_scenario()
    session = create_scheduled_session(ctx)
    entries = []
    for i in range(num_students):
        entries.append(enroll_student(
            session["id"], name=f"Student {i + 1}", email=f"s{i + 1}@x.example"))
    start_session(session["id"])
    for entry in entries:
        record_passing_evaluation(entry["id"], ctx["lead"]["id"])
    session = complete_session(session["id"], ctx["lead"]["id"])
    cards = []
    for entry in entries:
        card_rows = get_success_data(
            api_client.list_roster_entry_cards(entry["id"], TC))
        cards.extend(card_rows)
    return {**ctx, "session": session, "entries": entries, "cards": cards}


# ---------------------------------------------------------------------------
# Tier 4: renewal window scenarios
# ---------------------------------------------------------------------------

def setup_renewal_ready_instructor(num_completed_sessions=2):
    """Legacy-certified instructor with `num_completed_sessions` COMPLETED
    sessions inside the trailing 24-month window. Returns ctx including the
    instructor as 'lead'."""
    center, faculty, site = create_active_center()
    gv = create_guidelines_version_active()
    lead = create_legacy_certified_instructor(
        center["id"], full_name="Carl Certified", email="carl@x.example")
    align_instructor(center["id"], lead["id"])
    ctx = {"center": center, "faculty": faculty, "site": site,
           "guidelines_version": gv, "lead": lead}
    for i in range(num_completed_sessions):
        session = create_scheduled_session(
            ctx, start_at=f"2026-10-{10 + i:02d}T14:00:00Z",
            end_at=f"2026-10-{10 + i:02d}T18:00:00Z")
        entry = enroll_student(session["id"])
        start_session(session["id"])
        record_passing_evaluation(entry["id"], lead["id"])
        complete_session(session["id"], lead["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: audits / terminal states
# ---------------------------------------------------------------------------

def open_audit(center_id):
    """Open a QualityAudit against the center at its current version."""
    v = center_version(center_id, QA)
    return get_success_data(api_client.create_quality_audit(
        create_quality_audit_payload(center_id, v), QA))


def close_audit_corrective(audit_id):
    return get_success_data(api_client.close_audit(
        audit_id, {"outcome": "CORRECTIVE_ACTION"}, QA))


def suspend_center(center_id):
    return get_success_data(api_client.suspend_training_center(center_id, QA))


def revoke_center(center_id):
    return get_success_data(api_client.revoke_training_center(center_id, ADMIN))


def create_finding(audit_id, **overrides):
    return get_success_data(api_client.create_audit_finding(
        audit_id, create_audit_finding_payload(**overrides), QA))
