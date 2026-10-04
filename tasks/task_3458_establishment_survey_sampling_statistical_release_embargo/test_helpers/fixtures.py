"""Composite setup helpers (fixtures) for the survey-embargo domain.

The runner restarts the server before every test, so every fixture builds
its preconditions from scratch via PRD-declared endpoints only. All helpers
fail loudly with "Setup failed" (not a confusing assertion diff) when a
precondition call is rejected.

Clock discipline: time-gated steps set the logical clock explicitly to an
instant derived from the entity's own window fields, so fixtures never
depend on the caller's clock position. All derived instants are reachable
from the startup reading 2026-09-01T00:00:00Z (and rewinds are legal).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    collection_close_passed_instant,
    collection_open_instant,
)
from .factories import (
    case_advance_payload,
    clock_payload,
    create_benchmark_run_payload,
    create_cycle_payload,
    create_enrollment_payload,
    create_establishment_payload,
    create_factor_set_payload,
    create_notice_payload,
    create_outlet_payload,
    create_program_payload,
    create_release_payload,
    create_report_payload,
    create_sample_frame_payload,
    create_stratum,
    lifecycle_payload,
    make_factor_list,
    notice_advance_payload,
    accreditation_payload,
    release_advance_payload,
    report_advance_payload,
    cycle_advance_payload,
)
from .test_users import (
    ANALYST_USER_ID,
    DISCLOSURE_OFFICER_USER_ID,
    TEST_USERS,
    make_accredited_media_headers,
    make_disclosure_officer_headers,
    make_estimation_analyst_headers,
    make_respondent_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]
COLLECTOR = TEST_USERS["collection_officer_headers"]
ANALYST = TEST_USERS["estimation_analyst_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]


# ---------------------------------------------------------------------------
# Low-level plumbing
# ---------------------------------------------------------------------------
def _setup(resp, what):
    """Lenient setup validator: any 2xx passes; anything else raises a
    descriptive setup error with the response body attached."""
    if resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed at {what}: HTTP {resp.status_code} {resp.text}")
    return get_success_data(resp)


def _paged(resp, what):
    if resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed at {what}: HTTP {resp.status_code} {resp.text}")
    return validate_paginated(resp)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = CLOCK_STARTUP_DEFAULT) -> str:
    """Drive the logical clock (unprefixed endpoint, ProgramAdmin-only).
    Returns the echoed current_utc."""
    data = _setup(api_client.set_clock(clock_payload(to_iso8601), ADMIN),
                  f"set clock to {to_iso8601}")
    return data["current_utc"]


# ---------------------------------------------------------------------------
# Tier 1: programs, frames, establishments, enrollments
# ---------------------------------------------------------------------------
def create_program(code: str = "CES", sample_budget: int = 3, **overrides):
    payload = create_program_payload(code=code, sample_budget=sample_budget, **overrides)
    return _setup(api_client.create_program(payload, ADMIN), f"create program {code}")


def get_program_version(code: str) -> int:
    """Current OCC version of a program, via the list endpoint."""
    rows, _meta = _paged(api_client.list_programs(ADMIN), "list programs")
    for row in rows:
        if row.get("code") == code:
            return row["version"]
    raise AssertionError(f"Setup failed: program {code} not found")


def create_frame(program_code: str, reference_quarter: str = "2026-Q3",
                 strata=None, replaces_frame_id: str = None):
    """Create a DRAFT frame, supplying the program's current OCC version."""
    if strata is None:
        strata = [create_stratum("MANUFACTURING", "SMALL", 100)]
    payload = create_sample_frame_payload(
        program_code=program_code,
        reference_quarter=reference_quarter,
        strata=strata,
        expected_program_version=get_program_version(program_code),
    )
    if replaces_frame_id is not None:
        payload["replaces_frame_id"] = replaces_frame_id
    return _setup(api_client.create_sample_frame(payload, ADMIN),
                  f"create frame {program_code}/{reference_quarter}")


def freeze_frame(frame_id: str):
    return _setup(api_client.freeze_sample_frame(frame_id, ADMIN),
                  f"freeze frame {frame_id}")


def create_frozen_frame(program_code: str, reference_quarter: str = "2026-Q3",
                        strata=None, replaces_frame_id: str = None):
    frame = create_frame(program_code, reference_quarter, strata, replaces_frame_id)
    return freeze_frame(frame["id"])


def setup_program_with_frozen_frame(code: str = "CES", sample_budget: int = 3,
                                    strata=None, reference_quarter: str = "2026-Q3",
                                    **program_overrides):
    """Program + frozen frame. Returns (program, frame)."""
    program = create_program(code=code, sample_budget=sample_budget, **program_overrides)
    frame = create_frozen_frame(program["code"], reference_quarter, strata)
    return program, frame


def register_establishment(industry_code: str = "MANUFACTURING",
                           size_class: str = "SMALL", name: str = None,
                           ein: str = None):
    payload = create_establishment_payload(
        ein=ein, name=name or f"Est {industry_code}/{size_class}",
        industry_code=industry_code, size_class=size_class)
    return _setup(api_client.create_establishment(payload, COLLECTOR),
                  f"register establishment {payload['ein']}")


def enroll(establishment_id: str, program_code: str):
    """Create an INVITED enrollment."""
    payload = create_enrollment_payload(establishment_id, program_code)
    return _setup(api_client.create_enrollment(payload, COLLECTOR),
                  f"enroll {establishment_id} in {program_code}")


def lifecycle(enrollment: dict, action: str, as_officer: bool = False):
    """Run one panel lifecycle action. Respondent-scoped actions thread the
    owning establishment id into X-User-ID."""
    headers = COLLECTOR if as_officer else make_respondent_headers(
        enrollment["establishment_id"])
    return _setup(
        api_client.enrollment_lifecycle(enrollment["id"],
                                        lifecycle_payload(action), headers),
        f"lifecycle {action} on enrollment {enrollment['id']}")


def accept_enrollment(enrollment: dict):
    """Owning Respondent accepts the invitation (INVITED -> ENROLLED)."""
    return lifecycle(enrollment, "ACCEPT")


def decline_enrollment(enrollment: dict):
    """Owning Respondent declines the invitation (INVITED -> REFUSED)."""
    return lifecycle(enrollment, "DECLINE")


def setup_enrolled_panel(program_code: str, specs=None, count: int = 3):
    """Establishments + enrollments, each accepted by its owning Respondent.

    specs: list of (industry_code, size_class, n) tuples; defaults to
    `count` MANUFACTURING/SMALL establishments. Returns
    {"establishments": [...], "enrollments": [...]} with every enrollment
    in ENROLLED status.
    """
    if specs is None:
        specs = [("MANUFACTURING", "SMALL", count)]
    establishments, enrollments = [], []
    for industry_code, size_class, n in specs:
        for _ in range(n):
            est = register_establishment(industry_code, size_class)
            enr = enroll(est["id"], program_code)
            enr = accept_enrollment(enr)
            establishments.append(est)
            enrollments.append(enr)
    return {"establishments": establishments, "enrollments": enrollments}


def get_enrollment(enrollment_id: str):
    return _setup(api_client.get_enrollment(enrollment_id, COLLECTOR),
                  f"read enrollment {enrollment_id}")


def count_enrollments(program_code: str, enrollment_status: str = None) -> int:
    params = {"program_code": program_code}
    if enrollment_status is not None:
        params["enrollment_status"] = enrollment_status
    _rows, meta = _paged(api_client.list_enrollments(COLLECTOR, params=params),
                         "count enrollments")
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Tier 2/3: cycles, reports, follow-up cases
# ---------------------------------------------------------------------------
def create_cycle(program_code: str, reference_month: str):
    payload = create_cycle_payload(program_code, reference_month)
    return _setup(api_client.create_cycle(payload, ADMIN),
                  f"create cycle {program_code}/{reference_month}")


def cycle_action(cycle_id: str, action: str, headers):
    return _setup(api_client.advance_cycle(cycle_id, cycle_advance_payload(action), headers),
                  f"cycle {cycle_id} action {action}")


def open_collection(cycle: dict, at: str = None):
    """Set the clock to the collection open instant (cycle field, or derived
    from reference_month) and OPEN_COLLECTION."""
    set_clock(at or cycle.get("collection_open_at")
              or collection_open_instant(cycle["reference_month"]))
    return cycle_action(cycle["id"], "OPEN_COLLECTION", COLLECTOR)


def close_collection(cycle: dict, at: str = None):
    """Set the clock past the collection close and CLOSE_COLLECTION. This
    also system-creates follow-up cases for silent ENROLLED enrollments."""
    set_clock(at or collection_close_passed_instant(cycle["reference_month"]))
    return cycle_action(cycle["id"], "CLOSE_COLLECTION", COLLECTOR)


def compute_estimates(cycle_id: str):
    return cycle_action(cycle_id, "COMPUTE_ESTIMATES", ANALYST)


def certify_cycle(cycle_id: str, analyst_user_id: str = ANALYST_USER_ID):
    """CERTIFY with a deliberate certifier id (recorded for the
    segregation-of-duties check)."""
    return _setup(
        api_client.advance_cycle(
            cycle_id, cycle_advance_payload("CERTIFY"),
            make_estimation_analyst_headers(analyst_user_id)),
        f"certify cycle {cycle_id}")


def reopen_revision(cycle_id: str):
    return cycle_action(cycle_id, "REOPEN_REVISION", ANALYST)


def submit_report(enrollment: dict, cycle_id: str, employment: int):
    """Owning Respondent submits a report electronically."""
    payload = create_report_payload(enrollment["id"], cycle_id, employment)
    return _setup(
        api_client.create_report(
            payload, make_respondent_headers(enrollment["establishment_id"])),
        f"submit report enrollment={enrollment['id']} cycle={cycle_id}")


def report_action(report_id: str, action: str, headers, return_reason: str = None):
    payload = report_advance_payload(action, return_reason=return_reason)
    return _setup(api_client.advance_report(report_id, payload, headers),
                  f"report {report_id} action {action}")


def accept_report(report_id: str):
    return report_action(report_id, "ACCEPT", COLLECTOR)


def return_report(report_id: str, return_reason: str = "correction needed"):
    return report_action(report_id, "RETURN", COLLECTOR,
                         return_reason=return_reason)


def resubmit_report(report_id: str, enrollment: dict):
    """Owning Respondent resubmits a RETURNED report."""
    return report_action(report_id, "SUBMIT",
                         make_respondent_headers(enrollment["establishment_id"]))


def collect_cycle(program_code: str, reference_month: str, enrollments,
                  employment_by_enrollment_id: dict, compute: bool = True):
    """Open the cycle, submit+accept one report per mapped enrollment
    (unmapped enrollments stay silent), then close collection. When compute
    is true, also run the estimation pass. Returns the cycle dict in
    PROCESSING (estimates computed when compute=True)."""
    cycle = create_cycle(program_code, reference_month)
    cycle = open_collection(cycle)
    for enr in enrollments:
        employment = employment_by_enrollment_id.get(enr["id"])
        if employment is None:
            continue
        report = submit_report(enr, cycle["id"], employment)
        accept_report(report["id"])
    cycle = close_collection(cycle)
    if compute:
        cycle = compute_estimates(cycle["id"])
    return cycle


def setup_certified_cycle(program_code: str, reference_month: str, enrollments,
                          employment_by_enrollment_id: dict,
                          analyst_user_id: str = ANALYST_USER_ID):
    """Full collection pipeline through CERTIFIED. Returns the cycle."""
    cycle = collect_cycle(program_code, reference_month, enrollments,
                          employment_by_enrollment_id, compute=True)
    return certify_cycle(cycle["id"], analyst_user_id)


def get_cell_estimates(cycle_id: str, industry_code: str = None,
                       size_class: str = None):
    params = {"cycle_id": cycle_id}
    if industry_code is not None:
        params["industry_code"] = industry_code
    if size_class is not None:
        params["size_class"] = size_class
    rows, _meta = _paged(api_client.list_cell_estimates(ANALYST, params=params),
                         f"list cell estimates for cycle {cycle_id}")
    return rows


def get_single_cell(cycle_id: str, industry_code: str, size_class: str):
    rows = get_cell_estimates(cycle_id, industry_code, size_class)
    if len(rows) != 1:
        raise AssertionError(
            f"Setup failed: expected exactly one cell for {industry_code}/{size_class} "
            f"in cycle {cycle_id}, got {len(rows)}")
    return rows[0]


def find_case(enrollment_id: str, cycle_id: str):
    """The follow-up case opened for (enrollment, cycle) at cycle close."""
    params = {"enrollment_id": enrollment_id, "cycle_id": cycle_id}
    rows, _meta = _paged(api_client.list_follow_up_cases(COLLECTOR, params=params),
                         f"find case for enrollment {enrollment_id}")
    if len(rows) != 1:
        raise AssertionError(
            f"Setup failed: expected exactly one case for enrollment "
            f"{enrollment_id} in cycle {cycle_id}, got {len(rows)}")
    return rows[0]


def record_contact(case_id: str, contact_minutes: int, at: str,
                   channel: str = "EMAIL"):
    """Set the clock, then RECORD_CONTACT (spacing and budget rules apply)."""
    set_clock(at)
    payload = case_advance_payload("RECORD_CONTACT",
                                   contact_minutes=contact_minutes,
                                   channel=channel)
    return _setup(api_client.advance_follow_up_case(case_id, payload, COLLECTOR),
                  f"record contact on case {case_id}")


def void_contact(case_id: str, contact_seq: int):
    payload = case_advance_payload("VOID_CONTACT", contact_seq=contact_seq)
    return _setup(api_client.advance_follow_up_case(case_id, payload, COLLECTOR),
                  f"void contact {contact_seq} on case {case_id}")


def escalate_case(case_id: str):
    payload = case_advance_payload("ESCALATE")
    return _setup(api_client.advance_follow_up_case(case_id, payload, COLLECTOR),
                  f"escalate case {case_id}")


def close_case(case_id: str, outcome: str):
    payload = case_advance_payload("CLOSE", outcome=outcome)
    return _setup(api_client.advance_follow_up_case(case_id, payload, COLLECTOR),
                  f"close case {case_id} as {outcome}")


def get_case(case_id: str):
    return _setup(api_client.get_follow_up_case(case_id, COLLECTOR),
                  f"read case {case_id}")


# ---------------------------------------------------------------------------
# Tier 4: factor sets, benchmarks, notices
# ---------------------------------------------------------------------------
def create_factor_set(program_code: str, industry_code: str = "MANUFACTURING",
                      size_class: str = "SMALL", year: int = 2026,
                      month_overrides: dict = None):
    """Create a PROVISIONAL factor set (supersedes any prior set for the
    same series+year). month_overrides: {1..12: factor}."""
    payload = create_factor_set_payload(
        program_code, industry_code, size_class, year,
        factors=make_factor_list(month_overrides))
    return _setup(api_client.create_factor_set(payload, METHODOLOGIST),
                  f"create factor set {program_code}/{industry_code}/{size_class}/{year}")


def finalize_factor_set(set_id: str, at: str):
    """Finalize is gated on clock >= Jan 1 of year+1; caller supplies the
    instant so the fixture works for both the reject and pass sides."""
    set_clock(at)
    return _setup(api_client.finalize_factor_set(set_id, METHODOLOGIST),
                  f"finalize factor set {set_id}")


def create_benchmark_run(program_code: str, benchmark_month: str,
                         admin_cell_counts):
    payload = create_benchmark_run_payload(program_code, benchmark_month,
                                           admin_cell_counts)
    return _setup(api_client.create_benchmark_run(payload, METHODOLOGIST),
                  f"create benchmark run {program_code}/{benchmark_month}")


def apply_benchmark_run(run_id: str):
    return _setup(api_client.apply_benchmark_run(run_id, METHODOLOGIST),
                  f"apply benchmark run {run_id}")


def create_notice(program_code: str, title: str, effective_from: str,
                  scope: str = "ALL_SERIES",
                  reconstruction_factor_ppm: int = 1_000_000, series=None):
    payload = create_notice_payload(
        program_code, title, effective_from, scope=scope,
        reconstruction_factor_ppm=reconstruction_factor_ppm, series=series)
    return _setup(api_client.create_notice(payload, METHODOLOGIST),
                  f"create notice {title!r}")


def notice_action(notice_id: str, action: str):
    return _setup(
        api_client.advance_notice(notice_id, notice_advance_payload(action),
                                  METHODOLOGIST),
        f"notice {notice_id} action {action}")


# ---------------------------------------------------------------------------
# Tier 5: releases, outlets, grants, bulletins
# ---------------------------------------------------------------------------
def create_release(cycle_id: str, release_at: str):
    payload = create_release_payload(cycle_id, release_at)
    return _setup(api_client.create_release(payload, RELEASE_MANAGER),
                  f"create release for cycle {cycle_id}")


def get_release(release_id: str):
    return _setup(api_client.get_release(release_id, RELEASE_MANAGER),
                  f"read release {release_id}")


def release_version(release_id: str) -> int:
    return get_release(release_id)["version"]


def advance_release(release_id: str, action: str, headers,
                    new_release_at: str = None):
    """OCC-aware release advance: reads the current version itself."""
    payload = release_advance_payload(
        action, expected_release_version=release_version(release_id),
        new_release_at=new_release_at)
    return _setup(api_client.advance_release(release_id, payload, headers),
                  f"release {release_id} action {action}")


def approve_disclosure(release_id: str,
                       officer_user_id: str = DISCLOSURE_OFFICER_USER_ID):
    """DisclosureOfficer approves; defaults to an officer distinct from the
    standard certifier id."""
    return advance_release(release_id, "APPROVE_DISCLOSURE",
                           make_disclosure_officer_headers(officer_user_id))


def reject_disclosure(release_id: str,
                      officer_user_id: str = DISCLOSURE_OFFICER_USER_ID):
    return advance_release(release_id, "REJECT_DISCLOSURE",
                           make_disclosure_officer_headers(officer_user_id))


def open_embargo(release_id: str, at: str = None):
    """Set the clock to the release's embargo_open_at (or `at`) and open the
    embargo, minting one grant per ACCREDITED outlet."""
    release = get_release(release_id)
    set_clock(at or release["embargo_open_at"])
    return advance_release(release_id, "OPEN_EMBARGO", RELEASE_MANAGER)


def publish_release(release_id: str, at: str = None):
    """Set the clock to release_at (or `at`) and publish; the cycle moves
    CERTIFIED -> PUBLISHED."""
    release = get_release(release_id)
    set_clock(at or release["release_at"])
    return advance_release(release_id, "PUBLISH", RELEASE_MANAGER)


def postpone_release(release_id: str):
    return advance_release(release_id, "POSTPONE", RELEASE_MANAGER)


def reschedule_release(release_id: str, new_release_at: str):
    return advance_release(release_id, "RESCHEDULE", RELEASE_MANAGER,
                           new_release_at=new_release_at)


def default_release_at(after_instant: str, days: int = 10) -> str:
    """A release_at comfortably past the 3-day pre-announcement lead."""
    return _fmt(_parse(after_instant) + timedelta(days=days))


def create_outlet(name: str = "Wire Service", outlet_code: str = None):
    payload = create_outlet_payload(name=name, outlet_code=outlet_code)
    return _setup(api_client.create_outlet(payload, RELEASE_MANAGER),
                  f"create outlet {name!r}")


def outlet_action(outlet_id: str, action: str):
    return _setup(
        api_client.outlet_accreditation(outlet_id, accreditation_payload(action),
                                        RELEASE_MANAGER),
        f"outlet {outlet_id} action {action}")


def create_accredited_outlet(name: str = "Wire Service", outlet_code: str = None):
    outlet = create_outlet(name, outlet_code)
    return outlet_action(outlet["id"], "ACCREDIT")


def list_grants(release_event_id: str = None, media_outlet_id: str = None,
                grant_status: str = None):
    params = {}
    if release_event_id is not None:
        params["release_event_id"] = release_event_id
    if media_outlet_id is not None:
        params["media_outlet_id"] = media_outlet_id
    if grant_status is not None:
        params["grant_status"] = grant_status
    rows, meta = _paged(api_client.list_grants(RELEASE_MANAGER, params=params),
                        "list grants")
    return rows


def grant_for_outlet(release_event_id: str, media_outlet_id: str):
    rows = list_grants(release_event_id=release_event_id,
                       media_outlet_id=media_outlet_id)
    if len(rows) != 1:
        raise AssertionError(
            f"Setup failed: expected one grant for outlet {media_outlet_id} on "
            f"release {release_event_id}, got {len(rows)}")
    return rows[0]


def get_grant(grant_id: str):
    return _setup(api_client.get_grant(grant_id, RELEASE_MANAGER),
                  f"read grant {grant_id}")


def read_bulletin(grant_id: str, media_outlet_id: str):
    """AccreditedMedia reads the bulletin through its own grant (ISSUED ->
    ACCESSED on first success)."""
    return _setup(
        api_client.get_bulletin(grant_id,
                                make_accredited_media_headers(media_outlet_id)),
        f"read bulletin for grant {grant_id}")


def report_breach(grant_id: str):
    return _setup(api_client.report_breach(grant_id, RELEASE_MANAGER),
                  f"report breach on grant {grant_id}")


def setup_embargoed_release(cycle_id: str, release_at: str,
                            num_outlets: int = 1,
                            officer_user_id: str = DISCLOSURE_OFFICER_USER_ID):
    """Given a CERTIFIED cycle: create+accredit outlets, create the release,
    approve disclosure, and open the embargo. Returns
    {"release": ..., "outlets": [...], "grants": [...]}."""
    outlets = [create_accredited_outlet(name=f"Outlet {i + 1}")
               for i in range(num_outlets)]
    release = create_release(cycle_id, release_at)
    release = approve_disclosure(release["id"], officer_user_id)
    release = open_embargo(release["id"])
    grants = list_grants(release_event_id=release["id"])
    return {"release": release, "outlets": outlets, "grants": grants}


def setup_published_release(program_code: str, reference_month: str,
                            enrollments, employment_by_enrollment_id: dict,
                            release_at: str = None,
                            analyst_user_id: str = ANALYST_USER_ID,
                            officer_user_id: str = DISCLOSURE_OFFICER_USER_ID,
                            num_outlets: int = 1):
    """Full pipeline: collection -> CERTIFIED -> release approved, embargo
    opened, PUBLISHED. Returns
    {"cycle": ..., "release": ..., "outlets": [...], "grants": [...]}."""
    cycle = setup_certified_cycle(program_code, reference_month, enrollments,
                                  employment_by_enrollment_id, analyst_user_id)
    if release_at is None:
        release_at = default_release_at(
            collection_close_passed_instant(reference_month))
    staged = setup_embargoed_release(cycle["id"], release_at,
                                     num_outlets=num_outlets,
                                     officer_user_id=officer_user_id)
    release = publish_release(staged["release"]["id"])
    return {"cycle": cycle, "release": release,
            "outlets": staged["outlets"], "grants": staged["grants"]}
