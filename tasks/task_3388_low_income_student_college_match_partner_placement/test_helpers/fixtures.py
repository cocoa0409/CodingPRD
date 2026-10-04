"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the PRD's public
endpoints (each test runs against a freshly restarted server). Fixtures use
get_success_data() internally and re-raise setup failures with the request
context attached, so a broken precondition reads as "Setup failed (...)".

Return-shape convention: composite fixtures return a dict keyed by entity
name ("cycle", "college", "student", "application", "match", "aid_package",
"income_verification", "referral", "counselor", "partner", "prep_program",
"outcome_record"; plural keys hold lists).

Identity threading: every ownership-gated call uses the per-instance header
builder with the real entity id (e.g. make_student_headers(student["id"])).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .assertions import describe_response
from .constants import (
    CLOCK_AFTER_RANKING_WINDOW,
    CLOCK_IN_RANKING_WINDOW,
    LOGICAL_CLOCK_DEFAULT,
)
from .factories import (
    checkpoint_payload,
    close_prep_program_payload,
    create_application_payload,
    create_college_payload,
    create_community_partner_payload,
    create_counselor_payload,
    create_cycle_payload,
    create_income_verification_payload,
    create_prep_program_payload,
    create_referral_payload,
    create_student_payload,
    decide_verification_payload,
    ranking_entry,
    release_match_payload,
    regular_decision_payload,
    review_payload,
    set_clock_payload,
    submit_rankings_payload,
)
from .test_users import (
    TEST_USERS,
    make_college_officer_headers,
    make_counselor_headers,
    make_partner_staff_headers,
    make_student_headers,
)
from .types import CYCLE_PHASE_ORDER, CyclePhase

_ADMIN = TEST_USERS["program_admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]


def _ok(resp, what, expected_status=None):
    """Lenient setup validator: any 2xx passes; failures name the step, the
    URL, and the response body."""
    try:
        return get_success_data(resp, expected_status)
    except AssertionError as exc:
        raise AssertionError(
            f"Setup failed ({what}): {exc}\n{describe_response(resp)}"
        )


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return _ok(api_client.set_current_utc(set_clock_payload(to_iso8601), _ADMIN),
               f"set clock to {to_iso8601}", 200)


def reset_clock() -> dict:
    """Return the logical clock to its PRD default."""
    return set_clock(LOGICAL_CLOCK_DEFAULT)


# ---------------------------------------------------------------------------
# Single-entity creators (each returns the created resource dict)
# ---------------------------------------------------------------------------

def create_cycle(**overrides) -> dict:
    """Create a cycle (starts SETUP). Default windows are the canonical
    Cycle A windows; the application window opens at the clock default."""
    payload = create_cycle_payload(**overrides)
    return _ok(api_client.create_cycle(payload, _ADMIN), "create cycle", 201)


def create_college(**overrides) -> dict:
    payload = create_college_payload(**overrides)
    return _ok(api_client.create_college(payload, _ADMIN), "create college", 201)


def create_colleges(count: int, **common_overrides) -> list:
    """Create `count` colleges; pass name explicitly in common_overrides at
    your peril (names need not be unique, so the shared default is fine)."""
    return [create_college(**common_overrides) for _ in range(count)]


def create_counselor(**overrides) -> dict:
    payload = create_counselor_payload(**overrides)
    return _ok(api_client.create_counselor(payload, _ADMIN), "create counselor", 201)


def create_community_partner(**overrides) -> dict:
    payload = create_community_partner_payload(**overrides)
    return _ok(api_client.create_community_partner(payload, _ADMIN),
               "create community partner", 201)


def create_student(**overrides) -> dict:
    """Self-register a student as Anonymous (unique email per call)."""
    payload = create_student_payload(**overrides)
    return _ok(api_client.create_student(payload, _ANON), "create student", 201)


def create_referral(student_id: str, cycle_id: str, referrer_headers: dict,
                    note: str = "") -> dict:
    """Nominate a student; referrer identity comes from the role headers
    (counselor headers set counselor_id, partner-staff headers set partner_id).
    Only legal while the cycle is RECRUITMENT or APPLICATION_OPEN."""
    payload = create_referral_payload(student_id, cycle_id, note=note)
    return _ok(api_client.create_referral(payload, referrer_headers),
               "create referral", 201)


def create_prep_program(student_id: str, **overrides) -> dict:
    payload = create_prep_program_payload(student_id, **overrides)
    return _ok(api_client.create_prep_program(payload, _ADMIN),
               "create prep program", 201)


def close_prep_program(prep_program_id: str, outcome: str = "COMPLETED") -> dict:
    return _ok(api_client.close_prep_program(
        prep_program_id, close_prep_program_payload(outcome), _ADMIN),
        f"close prep program as {outcome}", 200)


def complete_prep_program(student_id: str, **overrides) -> dict:
    """Create a prep record and close it COMPLETED (confers prep_alum on
    subsequent submits)."""
    prep = create_prep_program(student_id, **overrides)
    return close_prep_program(prep["id"], "COMPLETED")


# ---------------------------------------------------------------------------
# Cycle phase walking (handles the two gated advances)
# ---------------------------------------------------------------------------

def advance_cycle(cycle_id: str) -> dict:
    return _ok(api_client.advance_cycle(cycle_id, _ADMIN), "advance cycle", 200)


def run_match(cycle_id: str) -> dict:
    return _ok(api_client.run_match(cycle_id, _ADMIN), "run match", 200)


def get_cycle(cycle_id: str) -> dict:
    return _ok(api_client.get_cycle(cycle_id, _ADMIN), "get cycle", 200)


def advance_cycle_to_phase(cycle_id: str, target_phase: str) -> dict:
    """Advance one phase at a time until the cycle reaches target_phase.

    Gate handling: crossing RANKING -> MATCH_RUN first moves the clock past
    ranking_closes_at; crossing MATCH_RUN -> REGULAR_DECISION first executes
    the match run (an empty candidate set is a legal run). The caller must
    ensure no UNDER_REVIEW application blocks the RANKING crossing.
    """
    cycle = get_cycle(cycle_id)
    target = target_phase.value if isinstance(target_phase, CyclePhase) else target_phase
    while cycle["phase"] != target:
        order = CYCLE_PHASE_ORDER
        if order.index(cycle["phase"]) >= order.index(target):
            raise ValueError(
                f"Cannot advance from {cycle['phase']} to {target} "
                f"(target is not later in the pipeline)"
            )
        if cycle["phase"] == CyclePhase.RANKING.value:
            set_clock(CLOCK_AFTER_RANKING_WINDOW)
        if (cycle["phase"] == CyclePhase.MATCH_RUN.value
                and not cycle.get("match_run_completed")):
            # The match run is once-per-cycle (a second run is rejected with
            # ERR_MATCH_ALREADY_RUN), so only run it when it has not executed.
            run_match(cycle_id)
        cycle = advance_cycle(cycle_id)
    return cycle


# ---------------------------------------------------------------------------
# Application step helpers (ownership-threaded)
# ---------------------------------------------------------------------------

def create_application(student_id: str, cycle_id: str, **overrides) -> dict:
    payload = create_application_payload(cycle_id, **overrides)
    return _ok(api_client.create_application(payload, make_student_headers(student_id)),
               "create application", 201)


def submit_application(application_id: str, student_id: str) -> dict:
    return _ok(api_client.submit_application(
        application_id, make_student_headers(student_id)),
        "submit application", 200)


def review_application(application_id: str, decision: str = "FINALIST") -> dict:
    return _ok(api_client.review_application(
        application_id, review_payload(decision), _ADMIN),
        f"review application {decision}", 200)


def submit_rankings(application_id: str, student_id: str, entries,
                    expected_application_version: int) -> dict:
    payload = submit_rankings_payload(entries, expected_application_version)
    return _ok(api_client.submit_rankings(
        application_id, payload, make_student_headers(student_id)),
        "submit rankings", 200)


def get_current_rankings(application_id: str, headers=None) -> list:
    # PRD section 2.3 defaults an omitted `limit` to 10, but a ranking list
    # may legally hold up to 12 rows (PRD section 3.4); request the maximum
    # page so the helper always returns the whole current list.
    data, _meta = validate_paginated(
        api_client.get_application_rankings(
            application_id, headers or _ADMIN, params={"limit": 100}))
    return data


def withdraw_application(application_id: str, student_id: str) -> dict:
    return _ok(api_client.withdraw_application(
        application_id, make_student_headers(student_id)),
        "withdraw application", 200)


def create_income_verification(application_id: str, filer_headers: dict,
                               **overrides) -> dict:
    """File verified figures; filer identity comes from the role headers."""
    payload = create_income_verification_payload(application_id, **overrides)
    return _ok(api_client.create_income_verification(payload, filer_headers),
               "create income verification", 201)


def decide_verification(verification_id: str, partner_id: str,
                        decision: str = "VERIFY") -> dict:
    return _ok(api_client.decide_income_verification(
        verification_id, decide_verification_payload(decision),
        make_partner_staff_headers(partner_id)),
        f"decide verification {decision}", 200)


# ---------------------------------------------------------------------------
# Refresh / lookup helpers
# ---------------------------------------------------------------------------

def get_application(application_id: str) -> dict:
    return _ok(api_client.get_application(application_id, _ADMIN),
               "get application", 200)


def get_student(student_id: str) -> dict:
    return _ok(api_client.get_student(student_id, _ADMIN), "get student", 200)


def get_college(college_id: str) -> dict:
    return _ok(api_client.get_college(college_id, _ADMIN), "get college", 200)


def get_aid_package(package_id: str) -> dict:
    return _ok(api_client.get_aid_package(package_id, _ADMIN),
               "get aid package", 200)


def find_match_for_application(application_id: str) -> dict:
    data, _meta = validate_paginated(
        api_client.list_matches(_ADMIN, params={"application_id": application_id}))
    assert len(data) == 1, f"expected exactly one match for {application_id}, got {len(data)}"
    return data[0]


def find_aid_package_for_match(match_id: str) -> dict:
    data, _meta = validate_paginated(
        api_client.list_aid_packages(_ADMIN, params={"match_id": match_id}))
    assert len(data) == 1, f"expected exactly one package for match {match_id}, got {len(data)}"
    return data[0]


def find_aid_packages_for_application(application_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_aid_packages(_ADMIN, params={"application_id": application_id}))
    return data


def list_outcomes_for_cycle(cycle_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_outcomes(_ADMIN, params={"cycle_id": cycle_id}))
    return data


# ---------------------------------------------------------------------------
# Tier 1/2: early-pipeline composite setups
# ---------------------------------------------------------------------------

def setup_application_open(cycle_overrides=None) -> dict:
    """Fresh Cycle A advanced to APPLICATION_OPEN with the clock at the
    default (inside the application window, bounds inclusive)."""
    reset_clock()
    cycle = create_cycle(**(cycle_overrides or {}))
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.APPLICATION_OPEN.value)
    return {"cycle": cycle}


def setup_draft_application(app_overrides=None, cycle_overrides=None) -> dict:
    """Cycle in APPLICATION_OPEN + one student with a DRAFT application."""
    ctx = setup_application_open(cycle_overrides)
    student = create_student()
    application = create_application(student["id"], ctx["cycle"]["id"],
                                     **(app_overrides or {}))
    ctx.update({"student": student, "application": application})
    return ctx


def setup_submitted_application(app_overrides=None, cycle_overrides=None) -> dict:
    """Cycle still in APPLICATION_OPEN + application moved DRAFT ->
    UNDER_REVIEW by a successful submit."""
    ctx = setup_draft_application(app_overrides, cycle_overrides)
    application = submit_application(ctx["application"]["id"], ctx["student"]["id"])
    ctx["application"] = application
    ctx["application_version"] = application["version"]
    return ctx


def setup_finalist_application(app_overrides=None, cycle_overrides=None) -> dict:
    """Cycle advanced to REVIEW + application decided FINALIST.
    Returns application_version (the version after review) for OCC tokens."""
    ctx = setup_submitted_application(app_overrides, cycle_overrides)
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"], CyclePhase.REVIEW.value)
    application = review_application(ctx["application"]["id"], "FINALIST")
    ctx.update({"cycle": cycle, "application": application,
                "application_version": application["version"]})
    return ctx


def setup_ranking_submitted(college_count=1, college_overrides=None,
                            app_overrides=None, with_prep=False,
                            with_referral=False, referrer="counselor") -> dict:
    """Full chain to a RANKING_SUBMITTED application:

    clock default -> cycle to RECRUITMENT -> colleges (+ optional counselor /
    partner / referral / completed prep program) -> APPLICATION_OPEN ->
    student + application (+ optional cited referral) -> submit -> REVIEW ->
    FINALIST -> RANKING -> clock inside the ranking window -> one accepted
    ranking list naming the colleges in order.

    Returns keys: cycle, college (first), colleges, student, application
    (RANKING_SUBMITTED), application_version (post-submit-rankings version),
    ranking_entries; plus counselor/partner/referral/prep_program when the
    corresponding flags are on. The cycle is left in RANKING with the clock
    at CLOCK_IN_RANKING_WINDOW.
    """
    reset_clock()
    cycle = create_cycle()
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.RECRUITMENT.value)
    colleges = [create_college(**(college_overrides or {}))
                for _ in range(college_count)]

    counselor = partner = referral = prep_program = None
    student = create_student()
    if with_referral:
        if referrer == "counselor":
            counselor = create_counselor()
            referral = create_referral(student["id"], cycle["id"],
                                       make_counselor_headers(counselor["id"]))
        else:
            partner = create_community_partner()
            referral = create_referral(student["id"], cycle["id"],
                                       make_partner_staff_headers(partner["id"]))
    if with_prep:
        prep_program = complete_prep_program(student["id"])

    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.APPLICATION_OPEN.value)
    if referral is not None:
        app_overrides = dict(app_overrides or {}, referral_id=referral["id"])
    application = create_application(student["id"], cycle["id"],
                                     **(app_overrides or {}))
    application = submit_application(application["id"], student["id"])
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.REVIEW.value)
    application = review_application(application["id"], "FINALIST")
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.RANKING.value)
    set_clock(CLOCK_IN_RANKING_WINDOW)
    entries = [ranking_entry(c["id"], i + 1) for i, c in enumerate(colleges)]
    application = submit_rankings(application["id"], student["id"], entries,
                                  application["version"])
    ctx = {
        "cycle": cycle,
        "college": colleges[0],
        "colleges": colleges,
        "student": student,
        "application": application,
        "application_version": application["version"],
        "ranking_entries": get_current_rankings(application["id"]),
    }
    if counselor is not None:
        ctx["counselor"] = counselor
    if partner is not None:
        ctx["partner"] = partner
    if referral is not None:
        ctx["referral"] = referral
    if prep_program is not None:
        ctx["prep_program"] = prep_program
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle composite setups
# ---------------------------------------------------------------------------

def setup_matched(college_overrides=None, app_overrides=None,
                  with_referral=False) -> dict:
    """Full pipeline through the binding match run.

    One student ranks one college (default: 1-slot NO_LOAN, coa 8,000,000,
    min_academic_index 0); the clock moves past ranking_closes_at, the cycle
    reaches MATCH_RUN, and the run executes.

    Returns keys: cycle (MATCH_RUN, match_run_completed true), college,
    student, application (MATCHED), match (BINDING), aid_package
    (PROVISIONAL, guaranteed_full_need true); plus counselor/referral when
    with_referral is on.
    """
    ctx = setup_ranking_submitted(college_count=1,
                                  college_overrides=college_overrides,
                                  app_overrides=app_overrides,
                                  with_referral=with_referral)
    set_clock(CLOCK_AFTER_RANKING_WINDOW)
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"], CyclePhase.MATCH_RUN.value)
    result = run_match(cycle["id"])
    application = get_application(ctx["application"]["id"])
    match = find_match_for_application(application["id"])
    aid_package = find_aid_package_for_match(match["id"])
    ctx.update({
        "cycle": get_cycle(cycle["id"]),
        "college": get_college(ctx["college"]["id"]),
        "application": application,
        "match": match,
        "aid_package": aid_package,
        "run_match_result": result,
    })
    return ctx


def setup_finalized_package(decision="VERIFY", verification_overrides=None,
                            college_overrides=None, app_overrides=None) -> dict:
    """A matched package taken through verification and finalization.

    A counselor files the verification (default figures 6,200,000 / 500,000 /
    size 4 — within ten percent of the default reported income, so VERIFY
    lands VERIFIED) and an unrelated community partner decides it; the
    segregation rule is satisfied because the decider neither submitted the
    record nor referred the application.

    Returns the setup_matched context plus: counselor, partner,
    income_verification, aid_package (FINALIZED).
    """
    ctx = setup_matched(college_overrides=college_overrides,
                        app_overrides=app_overrides)
    counselor = create_counselor()
    partner = create_community_partner()
    verification = create_income_verification(
        ctx["application"]["id"],
        make_counselor_headers(counselor["id"]),
        **(verification_overrides or {}))
    verification = decide_verification(verification["id"], partner["id"], decision)
    package = _ok(api_client.finalize_aid_package(
        ctx["aid_package"]["id"],
        make_college_officer_headers(ctx["college"]["id"])),
        "finalize aid package", 200)
    ctx.update({
        "counselor": counselor,
        "partner": partner,
        "income_verification": verification,
        "aid_package": package,
        "aid_package_version": package["version"],
    })
    return ctx


def setup_released_match(reason="extenuating circumstances", **kwargs) -> dict:
    """A BINDING match administratively released; the context carries the
    post-cascade state of every affected entity.

    Extra keys: match (RELEASED), aid_package (VOID), application
    (REGULAR_POOL, matched_college_id null), college (slot returned),
    student (stage FINALIST).
    """
    ctx = setup_matched(**kwargs)
    match = _ok(api_client.release_match(
        ctx["match"]["id"], release_match_payload(reason), _ADMIN),
        "release match", 200)
    ctx.update({
        "match": match,
        "aid_package": get_aid_package(ctx["aid_package"]["id"]),
        "application": get_application(ctx["application"]["id"]),
        "college": get_college(ctx["college"]["id"]),
        "student": get_student(ctx["student"]["id"]),
    })
    return ctx


def setup_regular_pool_application(college_overrides=None,
                                   app_overrides=None) -> dict:
    """A finalist who never submits a ranking, carried by the RANKING ->
    MATCH_RUN advance into REGULAR_POOL. The cycle is left in MATCH_RUN."""
    ctx = setup_finalist_application(app_overrides=app_overrides)
    college = create_college(**(college_overrides or {}))
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"], CyclePhase.RANKING.value)
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.MATCH_RUN.value)
    application = get_application(ctx["application"]["id"])
    ctx.update({"cycle": cycle, "college": college, "application": application})
    return ctx


def setup_admitted_regular(college_overrides=None, app_overrides=None) -> dict:
    """A REGULAR_POOL application admitted by a college officer during
    REGULAR_DECISION; the ADMIT creates its non-guaranteed PROVISIONAL
    package in the same motion.

    Extra keys: application (ADMITTED_REGULAR), aid_package (PROVISIONAL,
    guaranteed_full_need false, match_id null).
    """
    ctx = setup_regular_pool_application(college_overrides, app_overrides)
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"],
                                   CyclePhase.REGULAR_DECISION.value)
    application = _ok(api_client.regular_decision(
        ctx["application"]["id"], regular_decision_payload("ADMIT"),
        make_college_officer_headers(ctx["college"]["id"])),
        "regular-decision ADMIT", 200)
    packages = find_aid_packages_for_application(application["id"])
    assert len(packages) == 1, (
        f"expected exactly one package after ADMIT, got {len(packages)}")
    ctx.update({"cycle": cycle, "application": application,
                "aid_package": packages[0]})
    return ctx


def setup_enrolled_match(**kwargs) -> dict:
    """A BINDING match enrolled by the college's officer during
    REGULAR_DECISION, creating the ENROLLED_Y1 outcome record.

    Extra keys: match (ENROLLED), application (ENROLLED), outcome_record,
    college (enrolled_count bumped).
    """
    ctx = setup_matched(**kwargs)
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"],
                                   CyclePhase.REGULAR_DECISION.value)
    match = _ok(api_client.enroll_match(
        ctx["match"]["id"], make_college_officer_headers(ctx["college"]["id"])),
        "enroll match", 200)
    records = [r for r in list_outcomes_for_cycle(cycle["id"])
               if r["match_id"] == match["id"]]
    assert len(records) == 1, f"expected one outcome record, got {len(records)}"
    ctx.update({
        "cycle": cycle,
        "match": match,
        "application": get_application(ctx["application"]["id"]),
        "outcome_record": records[0],
        "college": get_college(ctx["college"]["id"]),
    })
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: multi-student accumulation setups
# ---------------------------------------------------------------------------

def setup_matched_students(count: int, college_overrides=None,
                           app_overrides_list=None) -> dict:
    """`count` students each matched to one college with `count` slots.

    app_overrides_list, when given, must have exactly `count` entries and is
    applied per student in creation order — use distinct gpa_scaled /
    test_score values to control the academic_index processing order (ties
    fall back to created_at ascending).

    Returns keys: cycle (MATCH_RUN), college, students, applications
    (all MATCHED), matches, aid_packages. List order is creation order.
    """
    if app_overrides_list is not None:
        assert len(app_overrides_list) == count
    overrides = dict(college_overrides or {})
    overrides.setdefault("match_slots", count)

    reset_clock()
    cycle = create_cycle()
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.RECRUITMENT.value)
    college = create_college(**overrides)
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.APPLICATION_OPEN.value)

    students, applications = [], []
    for i in range(count):
        student = create_student()
        app_ov = (app_overrides_list[i] if app_overrides_list else {}) or {}
        application = create_application(student["id"], cycle["id"], **app_ov)
        applications.append(submit_application(application["id"], student["id"]))
        students.append(student)

    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.REVIEW.value)
    versions = []
    for application in applications:
        reviewed = review_application(application["id"], "FINALIST")
        versions.append(reviewed["version"])

    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.RANKING.value)
    set_clock(CLOCK_IN_RANKING_WINDOW)
    for student, application, version in zip(students, applications, versions):
        submit_rankings(application["id"], student["id"],
                        [ranking_entry(college["id"], 1)], version)

    set_clock(CLOCK_AFTER_RANKING_WINDOW)
    cycle = advance_cycle_to_phase(cycle["id"], CyclePhase.MATCH_RUN.value)
    result = run_match(cycle["id"])

    matches, packages, refreshed_apps = [], [], []
    for application in applications:
        app = get_application(application["id"])
        match = find_match_for_application(app["id"])
        matches.append(match)
        packages.append(find_aid_package_for_match(match["id"]))
        refreshed_apps.append(app)

    return {
        "cycle": get_cycle(cycle["id"]),
        "college": get_college(college["id"]),
        "students": students,
        "applications": refreshed_apps,
        "matches": matches,
        "aid_packages": packages,
        "run_match_result": result,
    }


def setup_enrolled_matches(count=4, college_overrides=None,
                           app_overrides_list=None) -> dict:
    """`count` matched students all enrolled (REGULAR_DECISION phase), each
    producing an ENROLLED_Y1 outcome record. The cycle is left in
    REGULAR_DECISION; advance it to OUTCOME_TRACKING before checkpointing.

    Extra key: outcome_records (creation order per list endpoint).
    """
    ctx = setup_matched_students(count, college_overrides, app_overrides_list)
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"],
                                   CyclePhase.REGULAR_DECISION.value)
    officer = make_college_officer_headers(ctx["college"]["id"])
    enrolled_matches = []
    for match in ctx["matches"]:
        enrolled_matches.append(
            _ok(api_client.enroll_match(match["id"], officer), "enroll match", 200))
    ctx["matches"] = enrolled_matches
    ctx["cycle"] = cycle
    ctx["outcome_records"] = list_outcomes_for_cycle(cycle["id"])
    assert len(ctx["outcome_records"]) == count, (
        f"expected {count} outcome records, got {len(ctx['outcome_records'])}")
    return ctx


def checkpoint_outcome_record(outcome_id: str, to_status: str,
                              college_id: str = None,
                              credits_completed=None) -> dict:
    """File an outcome checkpoint as the owning college's officer when
    college_id is given, else as ProgramAdmin."""
    headers = (make_college_officer_headers(college_id) if college_id
               else _ADMIN)
    return _ok(api_client.checkpoint_outcome(
        outcome_id, checkpoint_payload(to_status, credits_completed), headers),
        f"checkpoint {to_status}", 200)

