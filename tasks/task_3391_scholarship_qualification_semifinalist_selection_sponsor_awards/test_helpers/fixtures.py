"""Composite setup helpers for the merit scholarship awards domain.

Every helper builds its preconditions from scratch against a freshly restarted
server: the runner re-launches the API before every test, so the database
starts empty and the logical clock reads 2026-09-01T00:00:00Z (PRD §2.5).

The composites walk the canonical lifecycle chain (PRD §3.1-§3.8):
  create cycle -> open-entries -> school/students -> entries -> close-entries
  -> score -> run-semifinalist-selection -> applications (create / endorse /
  submit / review) -> publish-finalists -> sponsor agreements / colleges ->
  run-award-matching -> accept -> disbursement release -> renewal.

student_specs drive per-student variation. Each spec is a dict, all keys
optional:
  full_name, state_code, graduation_year, citizenship_status,
  enrollment_status        -> Student fields (PRD §3.3)
  parent_sponsor           -> True attaches the ctx sponsor as parent_sponsor_id
  parent_sponsor_id        -> explicit sponsor id
  scores                   -> (reading, writing, math) triple; None opts the
                              entry out of scoring when the composite scores
  apply                    -> how far to drive the application: "create",
                              "endorse", "submit", "confirm" (default),
                              "deny", or None to skip application creation
  gpa_scaled, course_rigor, confirming_selection_index -> application fields
  first_choice_college     -> True attaches the ctx college as
                              first_choice_college_id
  first_choice_college_id  -> explicit college id
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_amendment_payload,
    create_college_institution_payload,
    create_corporate_sponsor_payload,
    create_entry_payload,
    create_finalist_application_payload,
    create_program_cycle_payload,
    create_renewal_decision_payload,
    create_renewal_verification_payload,
    create_review_payload,
    create_school_payload,
    create_score_payload,
    create_sponsor_agreement_payload,
    create_student_payload,
)
from .test_users import (
    TEST_USERS,
    make_college_admin_headers,
    make_school_official_headers,
    make_sponsor_admin_headers,
    make_student_headers,
)

PA = TEST_USERS["program_admin_headers"]

_DEFAULT_SCORES = (
    TEST_DEFAULTS["SCORE_READING"],
    TEST_DEFAULTS["SCORE_WRITING"],
    TEST_DEFAULTS["SCORE_MATH"],
)


# ---------------------------------------------------------------------------
# Tier 1: single-call actions (lenient setup validator throughout)
# ---------------------------------------------------------------------------

def create_cycle(**overrides):
    """Create a cycle in SETUP with its StateAllocation children (PRD §3.1)."""
    return get_success_data(api.create_program_cycle(create_program_cycle_payload(**overrides), PA))


def open_entries(cycle_id):
    return get_success_data(api.open_entries(cycle_id, PA))


def close_entries(cycle_id):
    """ENTRY_OPEN -> ENTRY_CLOSED; computes the provisional allocation (PRD §3.2)."""
    return get_success_data(api.close_entries(cycle_id, PA))


def run_semifinalist_selection(cycle_id):
    """ENTRY_CLOSED -> SEMIFINALISTS_SELECTED; returns {selected_total,
    states_finalized} (PRD §3.4)."""
    return get_success_data(api.run_semifinalist_selection(cycle_id, PA))


def publish_finalists(cycle_id):
    return get_success_data(api.publish_finalists(cycle_id, PA))


def run_award_matching(cycle_id):
    """Runs the matching waterfall once; returns {awards_created,
    national_granted, corporate_granted, college_granted} (PRD §3.7)."""
    return get_success_data(api.run_award_matching(cycle_id, PA))


def advance_clock(to_iso8601):
    """Advance the logical clock; returns {current_utc, expired_offer_ids}
    (PRD §2.5)."""
    return get_success_data(api.set_clock(to_iso8601, PA))


def create_school(**overrides):
    return get_success_data(api.create_school(create_school_payload(**overrides), PA))


def create_student(school_id, **overrides):
    return get_success_data(api.create_student(create_student_payload(school_id, **overrides), PA))


def create_corporate_sponsor(**overrides):
    return get_success_data(api.create_corporate_sponsor(create_corporate_sponsor_payload(**overrides), PA))


def create_college_institution(**overrides):
    return get_success_data(api.create_college_institution(create_college_institution_payload(**overrides), PA))


def create_sponsor_agreement(sponsor_id, cycle_id, **overrides):
    """Sponsor-scoped creation: the acting SponsorAdmin's X-User-ID is the
    sponsor id (PRD §2.1)."""
    payload = create_sponsor_agreement_payload(cycle_id, **overrides)
    return get_success_data(
        api.create_sponsor_agreement(sponsor_id, payload, make_sponsor_admin_headers(sponsor_id))
    )


def amend_sponsor_agreement(agreement_id, sponsor_id, expected_sponsor_agreement_version, **fields):
    """OCC-guarded amend by the owning sponsor (PRD §2.7, §3.6). Returns the
    new ACTIVE agreement."""
    payload = create_amendment_payload(expected_sponsor_agreement_version, **fields)
    return get_success_data(
        api.amend_sponsor_agreement(agreement_id, payload, make_sponsor_admin_headers(sponsor_id))
    )


def create_entry(student_id, cycle_id, **overrides):
    """Entry creation by the owning student (PRD §3.3)."""
    payload = create_entry_payload(student_id, cycle_id, **overrides)
    return get_success_data(api.create_entry(payload, make_student_headers(student_id)))


def score_entry(entry_id, reading_score, writing_score, math_score):
    payload = create_score_payload(
        reading_score=reading_score, writing_score=writing_score, math_score=math_score
    )
    return get_success_data(api.score_entry(entry_id, payload, PA))


def create_application(entry_id, student_id, **overrides):
    """Application creation by the owning student (PRD §3.5)."""
    payload = create_finalist_application_payload(entry_id, **overrides)
    return get_success_data(api.create_finalist_application(payload, make_student_headers(student_id)))


def endorse_application(application_id, school_id):
    """Endorsement by the official of the student's school (PRD §3.5)."""
    return get_success_data(
        api.endorse_application(application_id, make_school_official_headers(school_id))
    )


def submit_application(application_id, student_id):
    """Submit (or resubmit) by the owning student; the response carries the
    post-submit version needed by the OCC-guarded review (PRD §2.7, §3.5)."""
    return get_success_data(
        api.submit_application(application_id, make_student_headers(student_id))
    )


def review_application(application_id, decision, expected_finalist_application_version,
                       return_reason=None):
    overrides = {}
    if return_reason is not None:
        overrides["return_reason"] = return_reason
    payload = create_review_payload(
        decision, expected_finalist_application_version, **overrides
    )
    return get_success_data(api.review_application(application_id, payload, PA))


def accept_award(award_id, student_id):
    """Acceptance by the recipient student (PRD §3.8)."""
    return get_success_data(api.accept_award(award_id, make_student_headers(student_id)))


def decline_award(award_id, student_id):
    """Decline by the recipient student (PRD §3.8)."""
    return get_success_data(api.decline_award(award_id, make_student_headers(student_id)))


def release_disbursement(disbursement_id):
    return get_success_data(api.release_disbursement(disbursement_id, PA))


def create_renewal(award_id, college_id, **overrides):
    """Renewal verification submitted by the funding college (PRD §3.8)."""
    payload = create_renewal_verification_payload(**overrides)
    return get_success_data(
        api.create_renewal_verification(award_id, payload, make_college_admin_headers(college_id))
    )


def decide_renewal(verification_id, decision):
    """Program decision on a SUBMITTED verification (PRD §3.8)."""
    return get_success_data(
        api.decide_renewal_verification(verification_id, create_renewal_decision_payload(decision), PA)
    )


def release_notification(notification_id):
    return get_success_data(api.release_notification(notification_id, PA))


# ---------------------------------------------------------------------------
# Tier 2: read helpers (ProgramAdmin is authorized on every read endpoint)
# ---------------------------------------------------------------------------

def get_cycle(cycle_id):
    return get_success_data(api.get_program_cycle(cycle_id, PA))


def get_entry(entry_id):
    return get_success_data(api.get_entry(entry_id, PA))


def get_application(application_id):
    return get_success_data(api.get_finalist_application(application_id, PA))


def get_award(award_id):
    return get_success_data(api.get_award(award_id, PA))


def get_agreement(agreement_id):
    return get_success_data(api.get_sponsor_agreement(agreement_id, PA))


def get_college(college_id):
    return get_success_data(api.get_college_institution(college_id, PA))


def get_student(student_id):
    return get_success_data(api.get_student(student_id, PA))


def list_state_allocations(cycle_id, **params):
    """Sorted state_code ascending by the server (PRD §2.3)."""
    data, _meta = validate_paginated(api.list_state_allocations(cycle_id, PA, params=params or None))
    return data


def list_students(**params):
    data, _meta = validate_paginated(api.list_students(PA, params=params or None))
    return data


def list_entries(**params):
    data, _meta = validate_paginated(api.list_entries(PA, params=params or None))
    return data


def list_applications(**params):
    data, _meta = validate_paginated(api.list_finalist_applications(PA, params=params or None))
    return data


def list_sponsor_agreements(**params):
    data, _meta = validate_paginated(api.list_sponsor_agreements(PA, params=params or None))
    return data


def list_cycle_awards(cycle_id, **params):
    """All awards of a cycle, sorted created_at ascending (PRD §2.3)."""
    query = {"cycle_id": cycle_id}
    query.update(params)
    data, _meta = validate_paginated(api.list_awards(PA, params=query))
    return data


def find_award(student_id, cycle_id):
    """The single award of one student in one cycle (one award per finalist
    per cycle is a hard rule, PRD §3.7); None when unmatched."""
    awards = list_cycle_awards(cycle_id, student_id=student_id)
    assert len(awards) <= 1, f"expected at most one award for student {student_id}, got {len(awards)}"
    return awards[0] if awards else None


def list_award_disbursements(award_id):
    """Sorted term_index ascending by the server (PRD §2.3)."""
    data, _meta = validate_paginated(api.list_award_disbursements(award_id, PA))
    return data


def list_award_renewals(award_id):
    data, _meta = validate_paginated(api.list_award_renewal_verifications(award_id, PA))
    return data


def list_notifications(student_id, **params):
    """Sorted sequence_number ascending by the server (PRD §2.3, §3.9)."""
    data, _meta = validate_paginated(
        api.list_student_notifications(student_id, PA, params=params or None)
    )
    return data


# ---------------------------------------------------------------------------
# Tier 3: lifecycle stage composites
# ---------------------------------------------------------------------------

def _specs(student_specs):
    return list(student_specs) if student_specs is not None else [{}]


def _set_aliases(ctx):
    """Singular conveniences: the FIRST created student/entry/application/
    award, for the (common) single-subject scenarios."""
    if ctx.get("students"):
        ctx["student"] = ctx["students"][0]
    if ctx.get("entries"):
        ctx["entry"] = ctx["entries"][0]
    apps = [a for a in ctx.get("applications", []) if a is not None]
    if apps:
        ctx["application"] = apps[0]
    if ctx.get("awards"):
        ctx["award"] = ctx["awards"][0]
    return ctx


def setup_entry_open(student_specs=None, cycle_overrides=None, school_overrides=None,
                     sponsor_overrides=None):
    """Fresh database -> cycle in ENTRY_OPEN with a school, students, and one
    SUBMITTED entry per spec (PRD §3.1, §3.3).

    A corporate sponsor is created when sponsor_overrides is not None, or when
    any spec sets parent_sponsor: true (it is then wired onto that student).
    Returns the ctx dict: cycle, school, students, entries, and optionally
    sponsor.
    """
    specs = _specs(student_specs)
    ctx = {}
    ctx["cycle"] = create_cycle(**(cycle_overrides or {}))
    if sponsor_overrides is not None or any(s.get("parent_sponsor") for s in specs):
        ctx["sponsor"] = create_corporate_sponsor(**(sponsor_overrides or {}))
    open_entries(ctx["cycle"]["id"])
    ctx["school"] = create_school(**(school_overrides or {}))
    students, entries = [], []
    for spec in specs:
        stu_overrides = {
            key: spec[key]
            for key in ("full_name", "state_code", "graduation_year",
                        "citizenship_status", "enrollment_status")
            if key in spec
        }
        if spec.get("parent_sponsor"):
            stu_overrides["parent_sponsor_id"] = ctx["sponsor"]["id"]
        elif "parent_sponsor_id" in spec:
            stu_overrides["parent_sponsor_id"] = spec["parent_sponsor_id"]
        student = create_student(ctx["school"]["id"], **stu_overrides)
        students.append(student)
        entries.append(create_entry(student["id"], ctx["cycle"]["id"]))
    ctx["students"] = students
    ctx["entries"] = entries
    return _set_aliases(ctx)


def setup_entry_closed(student_specs=None, cycle_overrides=None, school_overrides=None,
                       sponsor_overrides=None, score=True):
    """-> ENTRY_CLOSED. When score is True, every entry whose spec does not
    opt out (scores: None) is scored, defaulting to the canonical (37, 37, 38)
    triple -> selection_index 224 (PRD §3.4)."""
    ctx = setup_entry_open(
        student_specs=student_specs,
        cycle_overrides=cycle_overrides,
        school_overrides=school_overrides,
        sponsor_overrides=sponsor_overrides,
    )
    close_entries(ctx["cycle"]["id"])
    if score:
        for spec, entry in zip(_specs(student_specs), ctx["entries"]):
            scores = spec.get("scores", _DEFAULT_SCORES)
            if scores is not None:
                ctx_entry = score_entry(entry["id"], *scores)
                entry.update(ctx_entry)
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return ctx


def setup_semifinalists_selected(student_specs=None, cycle_overrides=None,
                                 school_overrides=None, sponsor_overrides=None):
    """-> SEMIFINALISTS_SELECTED: scores every entry and runs the selection
    (PRD §3.4). Entries come back refreshed (SELECTED_SEMIFINALIST or
    NOT_SELECTED)."""
    ctx = setup_entry_closed(
        student_specs=student_specs,
        cycle_overrides=cycle_overrides,
        school_overrides=school_overrides,
        sponsor_overrides=sponsor_overrides,
        score=True,
    )
    ctx["selection_result"] = run_semifinalist_selection(ctx["cycle"]["id"])
    ctx["entries"] = [get_entry(e["id"]) for e in ctx["entries"]]
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return _set_aliases(ctx)


def _drive_application(ctx, spec, student, entry):
    """Create the spec's application and walk it to the requested level:
    create -> endorse -> submit -> review(CONFIRM|DENY) (PRD §3.5)."""
    level = spec.get("apply", "confirm")
    if level is None:
        return None
    overrides = {
        key: spec[key]
        for key in ("gpa_scaled", "course_rigor", "confirming_selection_index")
        if key in spec
    }
    if spec.get("first_choice_college"):
        assert ctx.get("college"), (
            "Setup failed: spec sets first_choice_college but the composite "
            "created no college (pass college_overrides)"
        )
        overrides["first_choice_college_id"] = ctx["college"]["id"]
    elif "first_choice_college_id" in spec:
        overrides["first_choice_college_id"] = spec["first_choice_college_id"]
    app = create_application(entry["id"], student["id"], **overrides)
    if level == "create":
        return app
    app = endorse_application(app["id"], ctx["school"]["id"])
    if level == "endorse":
        return app
    app = submit_application(app["id"], student["id"])
    if level == "submit":
        return app
    if level == "confirm":
        return review_application(app["id"], "CONFIRM", app["version"])
    if level == "deny":
        return review_application(app["id"], "DENY", app["version"])
    raise ValueError(f"unknown apply level {level!r}")


def setup_finalists_selected(student_specs=None, cycle_overrides=None,
                             school_overrides=None, sponsor_overrides=None,
                             college_overrides=None, publish=True):
    """-> applications driven per spec, then publish-finalists (PRD §3.5).

    The college (when college_overrides is not None) is created after the
    selection run and before applications so specs can name it first choice.
    publish=False stops with the cycle still SEMIFINALISTS_SELECTED (for
    scenarios whose trigger is the publish itself or a mid-review state).
    ctx["applications"] is aligned with the specs (None where apply is None).
    """
    specs = _specs(student_specs)
    ctx = setup_semifinalists_selected(
        student_specs=student_specs,
        cycle_overrides=cycle_overrides,
        school_overrides=school_overrides,
        sponsor_overrides=sponsor_overrides,
    )
    if college_overrides is not None:
        ctx["college"] = create_college_institution(**college_overrides)
    ctx["applications"] = [
        _drive_application(ctx, spec, student, entry)
        for spec, student, entry in zip(specs, ctx["students"], ctx["entries"])
    ]
    if publish:
        publish_finalists(ctx["cycle"]["id"])
        ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return _set_aliases(ctx)


def setup_matching_run(student_specs=None, cycle_overrides=None, school_overrides=None,
                       sponsor_overrides=None, college_overrides=None,
                       agreement_overrides=None):
    """-> FINALISTS_SELECTED with the matching waterfall executed once
    (PRD §3.7). When agreement_overrides is not None the sponsor's agreement
    is created (sponsor auto-created when needed) before the run. Returns ctx
    with matching_result and the freshly listed awards."""
    if agreement_overrides is not None and sponsor_overrides is None:
        sponsor_overrides = {}
    ctx = setup_finalists_selected(
        student_specs=student_specs,
        cycle_overrides=cycle_overrides,
        school_overrides=school_overrides,
        sponsor_overrides=sponsor_overrides,
        college_overrides=college_overrides,
    )
    if agreement_overrides is not None:
        ctx["agreement"] = create_sponsor_agreement(
            ctx["sponsor"]["id"], ctx["cycle"]["id"], **agreement_overrides
        )
    ctx["matching_result"] = run_award_matching(ctx["cycle"]["id"])
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    ctx["awards"] = list_cycle_awards(ctx["cycle"]["id"])
    return _set_aliases(ctx)


# ---------------------------------------------------------------------------
# Tier 4: award lifecycle (accept -> disburse -> renew)
# ---------------------------------------------------------------------------

def accept_all_awards(ctx):
    """Accept every OFFERED award of the cycle as its own recipient
    (PRD §3.8); returns the accepted awards in created_at order."""
    accepted = []
    for award in list_cycle_awards(ctx["cycle"]["id"]):
        if award["recipient_status"] == "OFFERED":
            accepted.append(accept_award(award["id"], award["student_id"]))
    return accepted


def _refresh_award_state(ctx):
    ctx["awards"] = [get_award(a["id"]) for a in ctx["awards"]]
    ctx["disbursements"] = {a["id"]: list_award_disbursements(a["id"]) for a in ctx["awards"]}
    return _set_aliases(ctx)


def setup_accepted_awards(student_specs=None, **kwargs):
    """Matching run + every granted award accepted; disbursement schedules
    generated (year-1 terms SCHEDULED, later years HELD, PRD §3.8).
    ctx["disbursements"] maps award id -> term list (term_index ascending)."""
    ctx = setup_matching_run(student_specs=student_specs, **kwargs)
    ctx["awards"] = accept_all_awards(ctx)
    assert ctx["awards"], "Setup failed: matching granted no awards to accept"
    return _refresh_award_state(ctx)


def release_first_terms(ctx):
    """Release term 1 of every accepted award (due at the acceptance date, so
    no clock advance is needed); flips each recipient ACCEPTED -> ENROLLED on
    the first release (PRD §3.8)."""
    for award_id, terms in ctx["disbursements"].items():
        release_disbursement(terms[0]["id"])
    return _refresh_award_state(ctx)


def setup_enrolled_awards(student_specs=None, **kwargs):
    """Every matched award accepted and its first term released -> recipient
    ENROLLED (PRD §3.8)."""
    ctx = setup_accepted_awards(student_specs=student_specs, **kwargs)
    return release_first_terms(ctx)


def setup_renewal_submitted(student_specs=None, award_index=0, renewal_overrides=None, **kwargs):
    """Enrolled awards + a SUBMITTED renewal verification for the next
    academic year of ctx["awards"][award_index], submitted by the funding
    college (PRD §3.8). Requires college-funded awards."""
    ctx = setup_enrolled_awards(student_specs=student_specs, **kwargs)
    award = ctx["awards"][award_index]
    assert award["college_id"], "Setup failed: renewal requires a COLLEGE_SPONSORED award"
    ctx["renewal"] = create_renewal(
        award["id"], award["college_id"], **(renewal_overrides or {})
    )
    ctx["renewals"] = list_award_renewals(award["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: terminal state (cycle completion bubble-up)
# ---------------------------------------------------------------------------

def setup_awards_completed(student_specs=None, cycle_overrides=None, **kwargs):
    """Single-payment award(s) fully disbursed so the cycle bubbles
    FINALISTS_SELECTED -> AWARDS_COMPLETED (PRD §3.8). Defaults the cycle to
    one national slot; any remaining SCHEDULED term is released after
    advancing the logical clock to its scheduled date."""
    overrides = {"national_award_slots": 1}
    overrides.update(cycle_overrides or {})
    ctx = setup_enrolled_awards(student_specs=student_specs, cycle_overrides=overrides, **kwargs)
    remaining = {}
    for award in ctx["awards"]:
        for term in list_award_disbursements(award["id"]):
            if term["status"] == "SCHEDULED":
                remaining.setdefault(term["scheduled_date"], []).append(term["id"])
    for date in sorted(remaining):
        target = date if "T" in date else f"{date}T00:00:00Z"
        advance_clock(target)
        for term_id in remaining[date]:
            release_disbursement(term_id)
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return _refresh_award_state(ctx)


__all__ = [
    # Tier 1 actions
    "create_cycle",
    "open_entries",
    "close_entries",
    "run_semifinalist_selection",
    "publish_finalists",
    "run_award_matching",
    "advance_clock",
    "create_school",
    "create_student",
    "create_corporate_sponsor",
    "create_college_institution",
    "create_sponsor_agreement",
    "amend_sponsor_agreement",
    "create_entry",
    "score_entry",
    "create_application",
    "endorse_application",
    "submit_application",
    "review_application",
    "accept_award",
    "decline_award",
    "release_disbursement",
    "create_renewal",
    "decide_renewal",
    "release_notification",
    # Tier 2 reads
    "get_cycle",
    "get_entry",
    "get_application",
    "get_award",
    "get_agreement",
    "get_college",
    "get_student",
    "list_state_allocations",
    "list_students",
    "list_entries",
    "list_applications",
    "list_sponsor_agreements",
    "list_cycle_awards",
    "find_award",
    "list_award_disbursements",
    "list_award_renewals",
    "list_notifications",
    # Tier 3-5 composites
    "setup_entry_open",
    "setup_entry_closed",
    "setup_semifinalists_selected",
    "setup_finalists_selected",
    "setup_matching_run",
    "accept_all_awards",
    "release_first_terms",
    "setup_accepted_awards",
    "setup_enrolled_awards",
    "setup_renewal_submitted",
    "setup_awards_completed",
]
