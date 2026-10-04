"""Composite setup helpers (fixtures).

Every helper builds its preconditions through the public API only. Setup
calls use the lenient get_success_data validator so a failed precondition
surfaces as a clear setup error rather than an assertion failure deep in a
test.

Conventions:
- make_* helpers create exactly one resource and return its data dict.
- refresh_* helpers re-read one resource (ProgramOfficer identity; every role
  may read).
- *_application / setup_* composites chain several calls and return a dict of
  the entities involved (documented per function).
- Names never collide with test_helpers.api_client's module-level endpoint
  functions (which take an explicit `headers` argument); the wrappers here
  bind the correct role identity themselves.
- Entity-backed ownership is threaded correctly: applicant-scoped calls use
  make_applicant_headers(applicant["id"]); reviewer-scoped calls use
  make_reviewer_headers(reviewer["id"]); opaque roles use TEST_USERS.
- The canonical reviewer pool lives at a DIFFERENT institution than the
  applications ("reviewer_institution"), so the institutional-conflict gate
  never fires by accident.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from . import api_client as ac
from . import factories
from .factories import (
    _UNSET,
    DEFAULT_AWARD_START_DATE,
    DEFAULT_MEETING_DATE,
    DEFAULT_OPEN_DATE,
    DEFAULT_RECEIPT_DEADLINE,
    DEFAULT_TRANSFER_EFFECTIVE_DATE,
)
from .test_users import TEST_USERS, make_applicant_headers, make_reviewer_headers

_PO = TEST_USERS["program_officer_headers"]
_RO = TEST_USERS["referral_officer_headers"]
_SRO = TEST_USERS["sro_headers"]
_CM = TEST_USERS["council_member_headers"]
_GO = TEST_USERS["grants_officer_headers"]

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Date arithmetic (domain timestamps render as plain ISO-8601 UTC instants)
# ---------------------------------------------------------------------------

def add_days_iso(iso_utc: str, days: int) -> str:
    """Return the ISO-8601 UTC instant `days` whole days after `iso_utc`."""
    return (datetime.strptime(iso_utc, _ISO_FMT) + timedelta(days=days)).strftime(_ISO_FMT)


def iso_days_between(start_iso: str, end_iso: str) -> int:
    """Whole days from start_iso to end_iso (negative when end precedes start)."""
    delta = datetime.strptime(end_iso, _ISO_FMT) - datetime.strptime(start_iso, _ISO_FMT)
    return delta.days


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (monotonic non-decreasing); returns
    {current_utc: ...}."""
    return get_success_data(ac.set_clock(factories.set_clock_payload(to_iso8601), _PO))


# ---------------------------------------------------------------------------
# Read-through refreshers (ProgramOfficer identity; every role may read)
# ---------------------------------------------------------------------------

def refresh_funding_opportunity(foa_id: str) -> dict:
    return get_success_data(ac.get_funding_opportunity(foa_id, _PO))


def refresh_institute(institute_id: str) -> dict:
    return get_success_data(ac.get_institute(institute_id, _PO))


def refresh_institution(institution_id: str) -> dict:
    return get_success_data(ac.get_institution(institution_id, _PO))


def refresh_applicant(applicant_id: str) -> dict:
    return get_success_data(ac.get_applicant(applicant_id, _PO))


def refresh_application(application_id: str) -> dict:
    return get_success_data(ac.get_application(application_id, _PO))


def refresh_study_section(section_id: str) -> dict:
    return get_success_data(ac.get_study_section(section_id, _PO))


def refresh_reviewer(reviewer_id: str) -> dict:
    return get_success_data(ac.get_reviewer(reviewer_id, _PO))


def refresh_assignment(assignment_id: str) -> dict:
    return get_success_data(ac.get_assignment(assignment_id, _PO))


def refresh_jit_request(jit_request_id: str) -> dict:
    return get_success_data(ac.get_jit_request(jit_request_id, _PO))


def refresh_award(award_id: str) -> dict:
    return get_success_data(ac.get_award(award_id, _PO))


def refresh_transfer_request(transfer_id: str) -> dict:
    return get_success_data(ac.get_transfer_request(transfer_id, _PO))


# ---------------------------------------------------------------------------
# Tier 0: single-resource makers (all succeed-path)
# ---------------------------------------------------------------------------

def make_institution(name=_UNSET, human_subjects_certification_expiry=_UNSET,
                     animal_welfare_assurance_expiry=_UNSET) -> dict:
    """Register an institution; certification dates are optional (null means
    not certified) and are omitted from the payload unless supplied."""
    payload = factories.create_institution_payload(
        name=name,
        human_subjects_certification_expiry=human_subjects_certification_expiry,
        animal_welfare_assurance_expiry=animal_welfare_assurance_expiry,
    )
    return get_success_data(ac.create_institution(payload, _PO))


def make_institute(**overrides) -> dict:
    """Create an institute; override any ledger config (appropriation_cents,
    reserve_cents, indirect_cost_rate, select_pay_cap_pct,
    select_pay_extension_percentile)."""
    return get_success_data(ac.create_institute(factories.create_institute_payload(**overrides), _PO))


def make_foa(**overrides) -> dict:
    """Create a funding opportunity (starts OPEN)."""
    return get_success_data(ac.create_funding_opportunity(
        factories.create_funding_opportunity_payload(**overrides), _PO))


def close_foa(foa_id: str) -> dict:
    """Close an OPEN announcement (OPEN -> CLOSED)."""
    return get_success_data(ac.close_funding_opportunity(foa_id, _PO))


def make_applicant(career_stage="ESTABLISHED_INVESTIGATOR", **overrides) -> dict:
    """Register a principal investigator."""
    return get_success_data(ac.create_applicant(
        factories.create_applicant_payload(career_stage=career_stage, **overrides), _PO))


def make_study_section(meeting_date=DEFAULT_MEETING_DATE, application_quota=10, **overrides) -> dict:
    """Create a study section (starts RECRUITING)."""
    return get_success_data(ac.create_study_section(
        factories.create_study_section_payload(
            meeting_date=meeting_date, application_quota=application_quota, **overrides),
        _SRO))


def make_reviewer(institution_id: str, **overrides) -> dict:
    """Recruit a reviewer (starts INVITED)."""
    return get_success_data(ac.create_reviewer(
        factories.create_reviewer_payload(institution_id, **overrides), _SRO))


def respond_to_invitation(reviewer_id: str, decision: str) -> dict:
    """Reviewer answers the recruitment invitation (ACCEPT -> ACTIVE,
    DECLINE -> DECLINED), acting as themselves."""
    return get_success_data(ac.reviewer_respond(
        reviewer_id, factories.reviewer_respond_payload(decision),
        make_reviewer_headers(reviewer_id)))


def make_active_reviewer(institution_id: str, **overrides) -> dict:
    """Recruit a reviewer and accept the invitation; returns ACTIVE reviewer."""
    reviewer = make_reviewer(institution_id, **overrides)
    return respond_to_invitation(reviewer["id"], "ACCEPT")


def declare_conflict(reviewer_id: str, application_id: str) -> dict:
    """Reviewer self-declares a conflict with an application."""
    return get_success_data(ac.reviewer_declare_conflict(
        reviewer_id, factories.declare_conflict_payload(application_id),
        make_reviewer_headers(reviewer_id)))


# ---------------------------------------------------------------------------
# Tier 1: application pipeline (DRAFT -> SUBMITTED -> REFERRED)
# ---------------------------------------------------------------------------

def make_draft_application(foa_id: str, institution_id: str, applicant_id: str, **overrides) -> dict:
    """Create a DRAFT application owned by applicant_id (the applicant identity
    is taken from the request context header, per PRD, so the owner's headers
    are used)."""
    payload = factories.create_application_payload(foa_id, institution_id, **overrides)
    return get_success_data(ac.create_application(payload, make_applicant_headers(applicant_id)))


def submit_draft_application(application_id: str, applicant_id: str) -> dict:
    """Submit a DRAFT application as its owner; returns SUBMITTED application."""
    return get_success_data(ac.submit_application(application_id, make_applicant_headers(applicant_id)))


def withdraw_own_application(application_id: str, applicant_id: str) -> dict:
    """Withdraw as the owning applicant; returns WITHDRAWN application."""
    return get_success_data(ac.withdraw_application(application_id, make_applicant_headers(applicant_id)))


def refer_application_current_version(application_id: str, study_section_id: str, institute_id: str,
                                      expected_application_version=None,
                                      override_assignment_request=_UNSET) -> dict:
    """Refer a SUBMITTED (or REFERRED) application as the ReferralOfficer.
    When expected_application_version is None the application's current
    version is read first (fresh OCC expectation). Returns the REFERRED
    application."""
    if expected_application_version is None:
        expected_application_version = refresh_application(application_id)["version"]
    payload = factories.referral_payload(
        study_section_id, institute_id, expected_application_version,
        override_assignment_request=override_assignment_request,
    )
    return get_success_data(ac.refer_application(application_id, payload, _RO))


def create_submitted_application(foa_id: str, institution_id: str, applicant_id: str, **overrides) -> dict:
    """Create + submit; returns the SUBMITTED application."""
    app = make_draft_application(foa_id, institution_id, applicant_id, **overrides)
    return submit_draft_application(app["id"], applicant_id)


def create_referred_application(foa_id: str, institution_id: str, applicant_id: str,
                                study_section_id: str, institute_id: str, **overrides) -> dict:
    """Create + submit + refer; returns the REFERRED application."""
    app = create_submitted_application(foa_id, institution_id, applicant_id, **overrides)
    return refer_application_current_version(app["id"], study_section_id, institute_id,
                                             expected_application_version=app["version"])


# ---------------------------------------------------------------------------
# Tier 2: review pipeline (assignments, convene, critiques, release)
# ---------------------------------------------------------------------------

def assign_reviewer(application_id: str, reviewer_id: str, role: str = "PRIMARY") -> dict:
    """Create an assignment as the SRO; returns the ASSIGNED assignment.
    Creating the first live assignment flips the application to UNDER_REVIEW."""
    return get_success_data(ac.create_assignment(
        factories.create_assignment_payload(application_id, reviewer_id, role), _SRO))


def respond_to_assignment(assignment_id: str, reviewer_id: str, decision: str) -> dict:
    """Reviewer responds to their own assignment (ACCEPT/DECLINE)."""
    return get_success_data(ac.assignment_respond(
        assignment_id, factories.assignment_respond_payload(decision),
        make_reviewer_headers(reviewer_id)))


def create_accepted_assignment(application_id: str, reviewer_id: str, role: str = "PRIMARY") -> dict:
    """Create an assignment and accept it; returns the ACCEPTED assignment."""
    assignment = assign_reviewer(application_id, reviewer_id, role)
    return respond_to_assignment(assignment["id"], reviewer_id, "ACCEPT")


def convene_section(section_id: str) -> dict:
    """Convene the review meeting (RECRUITING -> MEETING_HELD)."""
    return get_success_data(ac.convene_study_section(section_id, _SRO))


def file_critique(assignment_id: str, reviewer_id: str, overall_impact_score: int = 3,
                  significance_score=None, innovation_score=None, approach_score=None,
                  investigator_score=None, environment_score=None) -> dict:
    """Reviewer submits a critique on their own ACCEPTED assignment. Criterion
    scores default to the overall value. Returns CRITIQUE_SUBMITTED assignment."""
    payload = factories.critique_payload(
        overall_impact_score=overall_impact_score,
        significance_score=significance_score,
        innovation_score=innovation_score,
        approach_score=approach_score,
        investigator_score=investigator_score,
        environment_score=environment_score,
    )
    return get_success_data(ac.submit_critique(assignment_id, payload, make_reviewer_headers(reviewer_id)))


def release_scores(section_id: str) -> dict:
    """Release scores (MEETING_HELD -> SCORES_RELEASED); computes impact scores
    and both percentile variants for the section and its activity-code pool."""
    return get_success_data(ac.release_section_scores(section_id, _SRO))


def assign_panel(application_id: str, reviewer_institution_id: str, reviewers=None) -> dict:
    """Attach a PRIMARY + SECONDARY reviewer pair (both accepted) to a REFERRED
    application. Reviewers default to two fresh ACTIVE reviewers affiliated
    with reviewer_institution_id (different from the applicant institution, so
    no institutional conflict). Returns {"assignments": [primary, secondary],
    "reviewers": [r1, r2]}. The application ends UNDER_REVIEW."""
    if reviewers is None:
        reviewers = [make_active_reviewer(reviewer_institution_id),
                     make_active_reviewer(reviewer_institution_id)]
    primary = assign_reviewer(application_id, reviewers[0]["id"], "PRIMARY")
    secondary = assign_reviewer(application_id, reviewers[1]["id"], "SECONDARY")
    primary = respond_to_assignment(primary["id"], reviewers[0]["id"], "ACCEPT")
    secondary = respond_to_assignment(secondary["id"], reviewers[1]["id"], "ACCEPT")
    return {"assignments": [primary, secondary], "reviewers": reviewers}


def critique_panel(panel: dict, specs) -> list:
    """Submit critiques for a panel returned by assign_panel.

    specs: a list parallel to panel["assignments"]; each entry is either None
    (leave that assignment ACCEPTED — used to hold an application under the
    scoring quorum) or a dict of file_critique keyword arguments (e.g.
    {"overall_impact_score": 2, "approach_score": 2}).
    Returns the list of submitted critique assignments (skipped entries omitted).
    """
    submitted = []
    for assignment, reviewer, spec in zip(panel["assignments"], panel["reviewers"], specs):
        if spec is None:
            continue
        submitted.append(file_critique(assignment["id"], reviewer["id"], **spec))
    return submitted


# ---------------------------------------------------------------------------
# Tier 3: council review, payline, select pay
# ---------------------------------------------------------------------------

def record_council_review(application_id: str, recommendation: str,
                          priority_alignment_score=_UNSET,
                          portfolio_balance_note=_UNSET) -> dict:
    """Record an advisory-council review. priority_alignment_score defaults to
    4 for FUND (required there) and is omitted for DEFER/NOT_FUND."""
    if priority_alignment_score is _UNSET:
        priority_alignment_score = 4 if recommendation == "FUND" else _UNSET
    payload = factories.council_review_payload(
        application_id, recommendation,
        priority_alignment_score=priority_alignment_score,
        portfolio_balance_note=portfolio_balance_note,
    )
    return get_success_data(ac.create_council_review(payload, _CM))


def publish_payline(institute_id: str, base_payline_percentile,
                    expected_institute_version=None) -> dict:
    """Publish a base payline (OCC on institute version; read fresh when not
    supplied). Returns the updated institute."""
    if expected_institute_version is None:
        expected_institute_version = refresh_institute(institute_id)["version"]
    payload = factories.payline_decision_payload(base_payline_percentile, expected_institute_version)
    return get_success_data(ac.publish_payline_decision(institute_id, payload, _PO))


def select_pay(application_id: str, rationale=_UNSET) -> dict:
    """Grants-officer select-pay decision; returns the application (JIT_PENDING)."""
    return get_success_data(ac.select_pay_application(
        application_id, factories.select_pay_payload(rationale=rationale), _GO))


# ---------------------------------------------------------------------------
# Tier 4: JIT, award issuance
# ---------------------------------------------------------------------------

def fetch_jit_request(application_id: str) -> dict:
    """Return the application's (single) auto-created JIT request."""
    items = get_success_data(ac.list_application_jit_requests(application_id, _GO))
    assert isinstance(items, list) and len(items) == 1, (
        f"expected exactly one JIT request for application {application_id}, got {items!r}"
    )
    return items[0]


def submit_own_jit_items(jit_request_id: str, applicant_id: str, items_submitted=_UNSET) -> dict:
    """Owning applicant submits JIT items (default: the always-required pair
    OTHER_SUPPORT + BUDGET_JUSTIFICATION). Returns the SUBMITTED JIT request."""
    payload = factories.jit_submit_items_payload(items_submitted=items_submitted)
    return get_success_data(ac.submit_jit_items(
        jit_request_id, payload, make_applicant_headers(applicant_id)))


def adjudicate_jit(jit_request_id: str, decision: str, budget_cut_pct=_UNSET,
                   return_reason=_UNSET) -> dict:
    """Grants officer adjudicates a SUBMITTED JIT package (ACCEPT/RETURN)."""
    payload = factories.jit_adjudicate_payload(
        decision, budget_cut_pct=budget_cut_pct, return_reason=return_reason)
    return get_success_data(ac.adjudicate_jit_request(jit_request_id, payload, _GO))


def award_application(application_id: str, start_date=DEFAULT_AWARD_START_DATE) -> dict:
    """Issue the award for a JIT_COMPLETE application; returns the Award."""
    return get_success_data(ac.issue_award(application_id, factories.award_payload(start_date), _GO))


# ---------------------------------------------------------------------------
# Tier 5: post-award administration
# ---------------------------------------------------------------------------

def file_progress_report(award_id: str, applicant_id: str, period_year: int,
                         actual_expenditure_cents: int, publications_count: int = 0) -> dict:
    """Owning applicant files the progress report for the award's current period."""
    payload = factories.progress_report_payload(period_year, actual_expenditure_cents, publications_count)
    return get_success_data(ac.create_progress_report(
        award_id, payload, make_applicant_headers(applicant_id)))


def accept_report(report_id: str) -> dict:
    """Grants officer accepts a SUBMITTED report (disburses, advances period)."""
    return get_success_data(ac.accept_progress_report(report_id, _GO))


def request_modification(award_id: str, caller_headers: dict, type: str,
                         amount_cents=_UNSET, from_period=_UNSET,
                         new_end_date=_UNSET, reason=_UNSET) -> dict:
    """Request an award modification. caller_headers decides the role split:
    applicant headers for CARRYOVER | NO_COST_EXTENSION, grants-officer
    headers for TERMINATION."""
    payload = factories.award_modification_payload(
        type, amount_cents=amount_cents, from_period=from_period,
        new_end_date=new_end_date, reason=reason)
    return get_success_data(ac.create_award_modification(award_id, payload, caller_headers))


def decide_modification(modification_id: str, decision: str, denial_reason=_UNSET) -> dict:
    """Grants officer approves/denies a PENDING_APPROVAL modification."""
    payload = factories.modification_adjudicate_payload(decision, denial_reason=denial_reason)
    return get_success_data(ac.adjudicate_modification(modification_id, payload, _GO))


def propose_transfer(award_id: str, applicant_id: str, to_institution_id: str,
                     effective_date=DEFAULT_TRANSFER_EFFECTIVE_DATE) -> dict:
    """Owning applicant proposes a change-of-institution transfer (PROPOSED)."""
    payload = factories.transfer_request_payload(to_institution_id, effective_date)
    return get_success_data(ac.create_transfer_request(
        award_id, payload, make_applicant_headers(applicant_id)))


def relinquish_transfer_request(transfer_id: str) -> dict:
    """Grants officer relinquishes a PROPOSED transfer; computes the proration
    variant and relinquished amount. Returns the RELINQUISHED transfer."""
    return get_success_data(ac.relinquish_transfer(transfer_id, _GO))


def decide_transfer_request(transfer_id: str, decision: str, decline_reason=_UNSET) -> dict:
    """Grants officer accepts (successor-award cascade) or declines a
    RELINQUISHED transfer."""
    payload = factories.transfer_decide_payload(decision, decline_reason=decline_reason)
    return get_success_data(ac.decide_transfer(transfer_id, payload, _GO))


def fetch_successor_award(transfer_id: str) -> dict:
    """Return the successor award created by an accepted transfer."""
    items = get_success_data(ac.list_awards(_GO, params={"originating_transfer_id": transfer_id}))
    assert isinstance(items, list) and len(items) == 1, (
        f"expected exactly one successor award for transfer {transfer_id}, got {items!r}"
    )
    return items[0]


# ---------------------------------------------------------------------------
# Composite setups
# ---------------------------------------------------------------------------

def make_review_context(**overrides) -> dict:
    """Base registry + configuration for a scenario.

    Returns {"institution", "reviewer_institution", "institute", "foa"}:
    - institution: the applicant-side institution (applications are filed
      against it); certification overrides via
      human_subjects_certification_expiry / animal_welfare_assurance_expiry,
      name override via institution_name.
    - reviewer_institution: a second institution used to affiliate reviewers,
      so reviewer.institution_id never matches an application's
      institution_id (institutional COI) unless a test arranges it on purpose.
    - institute: funding institute (ledger config via overrides:
      appropriation_cents, reserve_cents, indirect_cost_rate,
      select_pay_cap_pct, select_pay_extension_percentile).
    - foa: funding opportunity (budget/page/activity config via overrides:
      activity_code, research_strategy_page_limit, min_direct_cents_per_year,
      max_direct_cents_per_year, max_years, open_date, receipt_deadline).
    """
    institute_keys = {
        "appropriation_cents", "reserve_cents", "indirect_cost_rate",
        "select_pay_cap_pct", "select_pay_extension_percentile", "name",
    }
    foa_keys = {
        "activity_code", "research_strategy_page_limit", "min_direct_cents_per_year",
        "max_direct_cents_per_year", "max_years", "open_date", "receipt_deadline",
        "pa_number", "title",
    }
    institution_kwargs = {}
    for key in ("human_subjects_certification_expiry", "animal_welfare_assurance_expiry",
                    "institution_name"):
        if key in overrides:
            institution_kwargs[key] = overrides[key]
    if "institution_name" in institution_kwargs:
        institution_kwargs["name"] = institution_kwargs.pop("institution_name")

    institute_overrides = {k: v for k, v in overrides.items() if k in institute_keys}
    foa_overrides = {k: v for k, v in overrides.items() if k in foa_keys}

    institution = make_institution(**institution_kwargs)
    reviewer_institution = make_institution(name=factories.unique_name("Reviewer College"))
    institute = make_institute(**institute_overrides)
    foa = make_foa(**foa_overrides)
    return {
        "institution": institution,
        "reviewer_institution": reviewer_institution,
        "institute": institute,
        "foa": foa,
    }


def add_referred_application(context: dict, section: dict, applicant=None,
                             career_stage="ESTABLISHED_INVESTIGATOR", **app_overrides) -> dict:
    """Create an applicant (unless given) plus a fresh application, submit it,
    and refer it to `section` and the context institute. Returns
    {"application": REFERRED application, "applicant": applicant}."""
    if applicant is None:
        applicant = make_applicant(career_stage=career_stage)
    application = create_referred_application(
        context["foa"]["id"], context["institution"]["id"], applicant["id"],
        section["id"], context["institute"]["id"], **app_overrides)
    return {"application": application, "applicant": applicant}


def add_reviewed_application(context: dict, section: dict, critique_specs=None,
                             applicant=None, career_stage="ESTABLISHED_INVESTIGATOR",
                             convene=True, **app_overrides) -> dict:
    """add_referred_application + an accepted PRIMARY/SECONDARY panel.

    critique_specs: optional list parallel to the panel's assignments; each
    entry is None (skip) or file_critique kwargs. Convening the section is
    required before critiques, so when critique_specs is given (or convene is
    True) the section is convened first. NOTE: convening moves the section to
    MEETING_HELD, after which no further referrals/assignments to it are
    possible — for multi-application sections, add all applications with
    convene=False and convene once at the end (see score_section).
    Returns {"application", "applicant", "panel"}."""
    base = add_referred_application(context, section, applicant=applicant,
                                    career_stage=career_stage, **app_overrides)
    panel = assign_panel(base["application"]["id"], context["reviewer_institution"]["id"])
    if critique_specs is not None:
        convene_section(section["id"])
        critique_panel(panel, critique_specs)
    elif convene:
        convene_section(section["id"])
    base["panel"] = panel
    return base


def score_section(section: dict, reviewed_apps: list, critique_specs_list) -> list:
    """Convene a section, submit each application's critiques, release scores.

    reviewed_apps: list of dicts from add_reviewed_application(..., convene=False).
    critique_specs_list: parallel list; each entry is a critique_panel specs
    list (entries None or file_critique kwargs).
    Returns the refreshed applications (post-release)."""
    convene_section(section["id"])
    for entry, specs in zip(reviewed_apps, critique_specs_list):
        critique_panel(entry["panel"], specs)
    release_scores(section["id"])
    return [refresh_application(entry["application"]["id"]) for entry in reviewed_apps]


def setup_scored_application(overall_impact_score: int = 3, approach_score=None,
                             career_stage="ESTABLISHED_INVESTIGATOR",
                             context=None, context_kwargs=None, **app_overrides) -> dict:
    """Full review pipeline for one application, scored by a PRIMARY+SECONDARY
    pair whose critiques share the given overall (and optional approach) score:
    the application's impact_score lands at overall_impact_score * 10.

    context: a pre-built make_review_context() dict, or None to build one.
    context_kwargs: forwarded to make_review_context when context is None
    (e.g. {"indirect_cost_rate": 0.55, "appropriation_cents": 40_000_000}).
    Remaining kwargs are application overrides (direct_cents_per_year,
    requested_years, research_strategy_page_count, human_subjects_involved,
    vertebrate_animals_involved, ...).

    Returns {"context", "section", "applicant", "application", "panel"} with
    the application refreshed in its post-release (SCORED) state."""
    context = context or make_review_context(**(context_kwargs or {}))
    section = make_study_section()
    entry = add_reviewed_application(context, section, career_stage=career_stage,
                                     convene=False, **app_overrides)
    spec = {"overall_impact_score": overall_impact_score}
    if approach_score is not None:
        spec["approach_score"] = approach_score
    (application,) = score_section(section, [entry], [[dict(spec), dict(spec)]])
    return {
        "context": context,
        "section": section,
        "applicant": entry["applicant"],
        "application": application,
        "panel": entry["panel"],
    }


def setup_council_reviewed_application(recommendation: str = "FUND",
                                       priority_alignment_score=_UNSET, **kwargs) -> dict:
    """SCORED application + one council review (default FUND ->
    COUNCIL_REVIEWED). Adds "council_review"; refreshes "application"."""
    scenario = setup_scored_application(**kwargs)
    review = record_council_review(
        scenario["application"]["id"], recommendation,
        priority_alignment_score=priority_alignment_score)
    scenario["council_review"] = review
    scenario["application"] = refresh_application(scenario["application"]["id"])
    return scenario


def setup_jit_pending_application(base_payline_percentile=100.0, **kwargs) -> dict:
    """COUNCIL_REVIEWED application funded by a payline publication (default
    base 100.0 funds any council-reviewed candidate). The application lands
    JIT_PENDING with an auto-created ISSUED JIT request.
    Adds "institute" (refreshed) and "jit_request"."""
    scenario = setup_council_reviewed_application(recommendation="FUND", **kwargs)
    institute = publish_payline(scenario["context"]["institute"]["id"], base_payline_percentile)
    scenario["institute"] = institute
    scenario["application"] = refresh_application(scenario["application"]["id"])
    scenario["jit_request"] = fetch_jit_request(scenario["application"]["id"])
    return scenario


def setup_jit_complete_application(budget_cut_pct=0, items_submitted=_UNSET, **kwargs) -> dict:
    """JIT_PENDING application carried through item submission and an ACCEPT
    adjudication; lands JIT_COMPLETE with budget_cut_pct recorded."""
    scenario = setup_jit_pending_application(**kwargs)
    jit = scenario["jit_request"]
    submit_own_jit_items(jit["id"], scenario["applicant"]["id"], items_submitted=items_submitted)
    scenario["jit_request"] = adjudicate_jit(jit["id"], "ACCEPT", budget_cut_pct=budget_cut_pct)
    scenario["application"] = refresh_application(scenario["application"]["id"])
    return scenario


def setup_active_award(start_date=DEFAULT_AWARD_START_DATE, **kwargs) -> dict:
    """Full funding pipeline through award issuance. Adds "award" (ACTIVE) and
    refreshes "application" (AWARDED) and "institute" (committed)."""
    scenario = setup_jit_complete_application(**kwargs)
    award = award_application(scenario["application"]["id"], start_date)
    scenario["award"] = award
    scenario["application"] = refresh_application(scenario["application"]["id"])
    scenario["institute"] = refresh_institute(scenario["context"]["institute"]["id"])
    return scenario


def setup_award_with_accepted_report(actual_expenditure_cents=12_000_000,
                                     publications_count=1, period_year=None,
                                     **kwargs) -> dict:
    """Active award plus one ACCEPTED progress report (default: 12,000,000
    cents against the award's current period). Adds "report"; refreshes
    "award" (current_period advanced) and "institute" (disbursal booked)."""
    scenario = setup_active_award(**kwargs)
    award = scenario["award"]
    report = file_progress_report(
        award["id"], scenario["applicant"]["id"],
        period_year if period_year is not None else award["current_period"],
        actual_expenditure_cents, publications_count)
    scenario["report"] = accept_report(report["id"])
    scenario["award"] = refresh_award(award["id"])
    scenario["institute"] = refresh_institute(scenario["context"]["institute"]["id"])
    return scenario


def setup_proposed_transfer(to_institution=None,
                            effective_date=DEFAULT_TRANSFER_EFFECTIVE_DATE,
                            with_report_cents=_UNSET, **kwargs) -> dict:
    """Active award (optionally with one accepted report of with_report_cents,
    which selects the LEDGER_ACTUALS proration variant at relinquish) plus a
    PROPOSED transfer to a second institution.
    Adds "to_institution" and "transfer"."""
    if with_report_cents is _UNSET:
        scenario = setup_active_award(**kwargs)
    else:
        scenario = setup_award_with_accepted_report(
            actual_expenditure_cents=with_report_cents, **kwargs)
    if to_institution is None:
        to_institution = make_institution(name=factories.unique_name("Receiving Institution"))
    transfer = propose_transfer(
        scenario["award"]["id"], scenario["applicant"]["id"],
        to_institution["id"], effective_date)
    scenario["to_institution"] = to_institution
    scenario["transfer"] = transfer
    return scenario


def setup_relinquished_transfer(**kwargs) -> dict:
    """PROPOSED transfer carried through relinquishment: the proration variant
    and relinquished amount are computed. "transfer" is RELINQUISHED."""
    scenario = setup_proposed_transfer(**kwargs)
    scenario["transfer"] = relinquish_transfer_request(scenario["transfer"]["id"])
    return scenario
