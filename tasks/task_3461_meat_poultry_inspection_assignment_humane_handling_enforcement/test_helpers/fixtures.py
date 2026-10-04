"""Composite setup helpers that walk the API to a wanted state.

The harness restarts the API server before every test, so each test starts
against an empty database and builds the world it needs through the public
API only. These helpers encapsulate the multi-step chains so tests can focus
on assertions.

Organisation:

  Tier 1  Clock and single-entity creation (grant chain pieces, inspectors)
  Tier 2  Granted-establishment chain and shift-window hierarchy
  Tier 3  Lifecycle shortcuts (verified coverage, labels in review, recalls
          with classes, suspension via egregious confirmation)
  Tier 4  Threshold targeting (escalation counts, pathogen categorization,
          effectiveness-check batches)
  Tier 5  Terminal / cycle states (closed recalls, vacated records)

Setup calls use the lenient ``get_success_data`` reader so a failure inside a
fixture surfaces as a clear setup error, not a confusing assertion failure.

Identity threading: every ownership-pinned call derives its headers from the
entity just created (``make_establishment_manager_headers(est["id"])``,
``make_inspector_headers(insp["id"])``), never from a shared constant.
Segregation-of-duties paths take a DISTINCT reviewer inspector id.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_START_ISO
from .test_users import (
    DISTRICT_MANAGER_HEADERS,
    LABEL_OFFICER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    RECALL_COORDINATOR_HEADERS,
    make_establishment_manager_headers,
    make_inspector_headers,
    make_supervisory_reviewer_headers,
)


# ═══ Tier 1: clock and single-entity creation ═══════════════════════════════

def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock via the platform endpoint (which sits OUTSIDE
    the /inspection prefix) and return what the write reported.

    Date-sensitive setup must call this FIRST and then derive every
    observation/collection/check timestamp from the value set here — never
    from wall-clock time. The boot value is 2026-09-01T00:00:00Z (PRD §2.4).
    """
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), PROGRAM_ADMINISTRATOR_HEADERS))


def create_establishment(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register an establishment; born UNGRANTED x INACTIVE at version 1."""
    return get_success_data(
        api.create_establishment(f.establishment_payload(**overrides), PROGRAM_ADMINISTRATOR_HEADERS)
    )


def get_establishment(api: ApiClient, establishment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_establishment(establishment_id, DISTRICT_MANAGER_HEADERS))


def create_inspector(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Onboard an inspector; born ACTIVE."""
    return get_success_data(
        api.create_inspector(f.inspector_payload(**overrides), PROGRAM_ADMINISTRATOR_HEADERS)
    )


def create_inspector_pair(api: ApiClient, species_qualifications: Optional[List[str]] = None) -> Dict[str, Any]:
    """Two ACTIVE inspectors: an issuer/reporter and a distinct reviewer.

    Segregation of duties (PRD §3.5/§3.9) requires the SupervisoryReviewer's
    X-User-ID to differ from the issuing/reporting inspector, so appeal
    decisions and humane-event confirmations use ``pair["reviewer"]``.
    """
    quals = list(species_qualifications) if species_qualifications is not None else ["CATTLE"]
    issuer = create_inspector(api, full_name="Ina Inspector", species_qualifications=quals)
    reviewer = create_inspector(api, full_name="Sue Supervisor", species_qualifications=quals)
    return {"issuer": issuer, "reviewer": reviewer}


# ── Grant application chain ──────────────────────────────────────────────────

def create_grant_application(api: ApiClient, establishment_id: str, **overrides: Any) -> Dict[str, Any]:
    """Submit a grant application as the establishment itself (ownership-pinned);
    born SUBMITTED with all three findings PENDING."""
    return get_success_data(
        api.create_grant_application(
            f.grant_application_payload(establishment_id, **overrides),
            make_establishment_manager_headers(establishment_id),
        )
    )


def begin_grant_review(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.begin_grant_review(application_id, DISTRICT_MANAGER_HEADERS))


def record_adequacy(api: ApiClient, application_id: str, dimension: str, finding: str) -> Dict[str, Any]:
    """Record one adequacy finding; dimension FACILITY|SANITATION|HACCP."""
    return get_success_data(
        api.record_adequacy(application_id, f.adequacy_payload(dimension, finding), DISTRICT_MANAGER_HEADERS)
    )


def record_all_adequate(api: ApiClient, application_id: str) -> Dict[str, Any]:
    """Record ADEQUATE on all three findings (the grant precondition)."""
    application = None
    for dimension in ("FACILITY", "SANITATION", "HACCP"):
        application = record_adequacy(api, application_id, dimension, "ADEQUATE")
    return application


def decide_grant(api: ApiClient, application_id: str, decision: str = "GRANT") -> Dict[str, Any]:
    return get_success_data(
        api.decide_grant_application(application_id, f.grant_decision_payload(decision), DISTRICT_MANAGER_HEADERS)
    )


# ═══ Tier 2: granted establishment + shift-window hierarchy ═════════════════

def create_granted_establishment(
    api: ApiClient,
    *,
    clock: Optional[str] = None,
    name: str = "Granted Plant",
    species_classes: Optional[List[str]] = None,
    slaughter_capable: bool = True,
) -> Dict[str, Any]:
    """Full grant chain: register -> apply -> begin-review -> all three
    findings ADEQUATE -> decide GRANT. The grant decision moves the
    establishment to GRANTED x ACTIVE in the same request.

    Pass ``clock`` to move the logical clock before building (the fixture
    calls set_clock first, so every later timestamp derives from it).

    Returns {"establishment", "application", "manager_headers"} where
    ``establishment`` is re-read after the grant (fresh version)."""
    if clock is not None:
        set_clock(api, clock)
    est = create_establishment(api, name=name, species_classes=species_classes, slaughter_capable=slaughter_capable)
    est_id = est["id"]
    application = create_grant_application(api, est_id)
    begin_grant_review(api, application["id"])
    record_all_adequate(api, application["id"])
    application = decide_grant(api, application["id"], "GRANT")
    est = get_establishment(api, est_id)
    return {
        "establishment": est,
        "application": application,
        "manager_headers": make_establishment_manager_headers(est_id),
    }


def create_shift_window(api: ApiClient, establishment_id: str, **overrides: Any) -> Dict[str, Any]:
    """Plan a shift window as the establishment itself (ownership-pinned);
    born PLANNED with both gap fields null."""
    return get_success_data(
        api.create_shift_window(
            f.shift_window_payload(establishment_id, **overrides),
            make_establishment_manager_headers(establishment_id),
        )
    )


def get_shift_window(api: ApiClient, shift_window_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shift_window(shift_window_id, PROGRAM_ADMINISTRATOR_HEADERS))


def setup_granted_with_window(
    api: ApiClient,
    *,
    clock: Optional[str] = None,
    name: str = "Granted Plant",
    species_classes: Optional[List[str]] = None,
    slaughter_capable: bool = True,
    start_utc: str = f.DEFAULT_SHIFT_START,
    end_utc: str = f.DEFAULT_SHIFT_END,
    shift_type: str = "SLAUGHTER",
    planned_line_count: int = 1,
) -> Dict[str, Any]:
    """Granted establishment plus one PLANNED shift window.

    Returns {"establishment", "application", "manager_headers", "window"}."""
    base = create_granted_establishment(
        api, clock=clock, name=name, species_classes=species_classes, slaughter_capable=slaughter_capable
    )
    window = create_shift_window(
        api,
        base["establishment"]["id"],
        start_utc=start_utc,
        end_utc=end_utc,
        shift_type=shift_type,
        planned_line_count=planned_line_count,
    )
    base["window"] = window
    return base


def add_assignment(
    api: ApiClient,
    shift_window_id: str,
    inspector_id: str,
    *,
    line_index: int = 1,
    start_utc: str = f.DEFAULT_SHIFT_START,
    end_utc: str = f.DEFAULT_SHIFT_END,
    expected_shift_window_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a SCHEDULED assignment (ProgramAdministrator).

    The window's version increments by 1 on every assignment creation, so when
    ``expected_shift_window_version`` is omitted this helper re-reads the
    window and stacks on the fresh version. Pass an explicit (stale) version
    only when exercising the OCC rejection itself."""
    if expected_shift_window_version is None:
        expected_shift_window_version = get_shift_window(api, shift_window_id)["version"]
    return get_success_data(
        api.create_assignment(
            shift_window_id,
            f.assignment_payload(
                inspector_id,
                line_index,
                start_utc,
                end_utc,
                expected_shift_window_version,
            ),
            PROGRAM_ADMINISTRATOR_HEADERS,
        )
    )


def confirm_assignment(api: ApiClient, assignment_id: str, inspector_id: str) -> Dict[str, Any]:
    """The assigned inspector confirms their own presence (X-User-ID must equal
    the assignment's inspector_id)."""
    return get_success_data(
        api.confirm_assignment(assignment_id, make_inspector_headers(inspector_id))
    )


def cancel_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.cancel_assignment(assignment_id, PROGRAM_ADMINISTRATOR_HEADERS))


def verify_coverage(api: ApiClient, shift_window_id: str, inspector_id: str) -> Dict[str, Any]:
    """An Inspector recomputes both gap fields and drives the window to
    VERIFIED_COVERED (final gap 0) or COVERAGE_GAP_FLAGGED (final gap > 0)."""
    return get_success_data(
        api.verify_coverage(shift_window_id, make_inspector_headers(inspector_id))
    )


def create_and_confirm_assignment(
    api: ApiClient,
    shift_window_id: str,
    inspector_id: str,
    *,
    line_index: int = 1,
    start_utc: str = f.DEFAULT_SHIFT_START,
    end_utc: str = f.DEFAULT_SHIFT_END,
) -> Dict[str, Any]:
    """Create an assignment and confirm it; returns the CONFIRMED assignment."""
    assignment = add_assignment(
        api, shift_window_id, inspector_id, line_index=line_index, start_utc=start_utc, end_utc=end_utc
    )
    return confirm_assignment(api, assignment["id"], inspector_id)


# ═══ Tier 3: lifecycle shortcuts ═════════════════════════════════════════════

def setup_verified_covered_window(
    api: ApiClient,
    *,
    clock: Optional[str] = None,
    species_classes: Optional[List[str]] = None,
    slaughter_capable: bool = True,
    start_utc: str = f.DEFAULT_SHIFT_START,
    end_utc: str = f.DEFAULT_SHIFT_END,
    shift_type: str = "SLAUGHTER",
    planned_line_count: int = 1,
) -> Dict[str, Any]:
    """Granted establishment + window + one full-coverage CONFIRMED assignment
    on line 1 + verify-coverage. With default arguments (1 line fully covered)
    the window lands VERIFIED_COVERED.

    Returns {"establishment", "application", "manager_headers", "window",
             "inspector", "assignment", "verified_window"}."""
    base = setup_granted_with_window(
        api,
        clock=clock,
        species_classes=species_classes,
        slaughter_capable=slaughter_capable,
        start_utc=start_utc,
        end_utc=end_utc,
        shift_type=shift_type,
        planned_line_count=planned_line_count,
    )
    quals = list(base["establishment"]["species_classes"])
    inspector = create_inspector(api, species_qualifications=quals)
    assignment = create_and_confirm_assignment(
        api,
        base["window"]["id"],
        inspector["id"],
        line_index=1,
        start_utc=start_utc,
        end_utc=end_utc,
    )
    verified = verify_coverage(api, base["window"]["id"], inspector["id"])
    base.update({"inspector": inspector, "assignment": assignment, "verified_window": verified})
    return base


# ── Noncompliance records ────────────────────────────────────────────────────

def issue_nr(
    api: ApiClient,
    establishment_id: str,
    inspector_id: str,
    *,
    regulation_family: str = "SANITATION",
    description: str = "noncompliance observation",
    observed_at: str = f.DEFAULT_OBSERVED_AT,
    shift_window_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue an NR as the given inspector (X-User-ID pinned to the issuer);
    born OPEN with issued_at stamped from the logical clock."""
    return get_success_data(
        api.create_noncompliance_record(
            f.nr_payload(
                establishment_id,
                inspector_id,
                regulation_family=regulation_family,
                description=description,
                observed_at=observed_at,
                shift_window_id=shift_window_id,
            ),
            make_inspector_headers(inspector_id),
        )
    )


def respond_to_nr(
    api: ApiClient, record_id: str, establishment_id: str, response_text: str = "corrective action taken"
) -> Dict[str, Any]:
    """The establishment answers its own NR (ownership-pinned)."""
    return get_success_data(
        api.respond_to_nr(
            record_id,
            f.nr_response_payload(response_text),
            make_establishment_manager_headers(establishment_id),
        )
    )


def verify_nr(api: ApiClient, record_id: str, inspector_id: str, outcome: str) -> Dict[str, Any]:
    """Inspector verification: outcome VERIFY -> VERIFIED, ESCALATE -> ESCALATED."""
    return get_success_data(
        api.verify_nr_response(record_id, f.verify_response_payload(outcome), make_inspector_headers(inspector_id))
    )


def escalate_nr(api: ApiClient, record_id: str, inspector_id: str) -> Dict[str, Any]:
    return verify_nr(api, record_id, inspector_id, "ESCALATE")


def get_nr(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_noncompliance_record(record_id, DISTRICT_MANAGER_HEADERS))


def list_nrs(api: ApiClient, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api.list_noncompliance_records(DISTRICT_MANAGER_HEADERS, params=params))
    return rows


# ── Enforcement actions ──────────────────────────────────────────────────────

def create_enforcement_action(
    api: ApiClient,
    establishment_id: str,
    *,
    action_type: str,
    basis: str,
    regulation_family: Optional[str] = None,
    expected_establishment_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Propose an enforcement action (DistrictManager); born PROPOSED with
    auto_created false. Re-reads the establishment for a fresh OCC version
    unless one is supplied explicitly (stale-version probes)."""
    if expected_establishment_version is None:
        expected_establishment_version = get_establishment(api, establishment_id)["version"]
    return get_success_data(
        api.create_enforcement_action(
            establishment_id,
            f.enforcement_action_payload(
                action_type,
                basis,
                expected_establishment_version,
                regulation_family=regulation_family,
            ),
            DISTRICT_MANAGER_HEADERS,
        )
    )


def list_enforcement_actions(api: ApiClient, establishment_id: str) -> List[Dict[str, Any]]:
    """All enforcement actions of the establishment, created_at ascending."""
    rows, _meta = validate_paginated(api.list_enforcement_actions(establishment_id, DISTRICT_MANAGER_HEADERS))
    return rows


def activate_enforcement(api: ApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_enforcement_action(action_id, DISTRICT_MANAGER_HEADERS))


def lift_enforcement(api: ApiClient, action_id: str, abatement_evidence: Optional[str] = None) -> Dict[str, Any]:
    """Lift an IN_EFFECT action; default evidence satisfies the 20-char minimum."""
    payload = f.lift_payload() if abatement_evidence is None else f.lift_payload(abatement_evidence)
    return get_success_data(api.lift_enforcement_action(action_id, payload, DISTRICT_MANAGER_HEADERS))


# ── Humane handling events ───────────────────────────────────────────────────

def report_humane_event(
    api: ApiClient,
    establishment_id: str,
    reporter_id: str,
    *,
    species: str = "CATTLE",
    severity: str = "NON_EGREGIOUS",
    observed_at: str = f.DEFAULT_OBSERVED_AT,
    description: str = "humane handling observation",
) -> Dict[str, Any]:
    """Report an observation as the given inspector (X-User-ID pinned to the
    reporter); born REPORTED."""
    return get_success_data(
        api.create_humane_event(
            f.humane_event_payload(
                establishment_id,
                reporter_id,
                species=species,
                severity=severity,
                observed_at=observed_at,
                description=description,
            ),
            make_inspector_headers(reporter_id),
        )
    )


def confirm_humane_event(api: ApiClient, event_id: str, reviewer_id: str) -> Dict[str, Any]:
    """SupervisoryReviewer confirmation; reviewer_id must differ from the
    event's reported_by_inspector_id (segregation of duties)."""
    return get_success_data(
        api.confirm_humane_event(event_id, make_supervisory_reviewer_headers(reviewer_id))
    )


def dismiss_humane_event(api: ApiClient, event_id: str, reviewer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.dismiss_humane_event(event_id, make_supervisory_reviewer_headers(reviewer_id))
    )


def suspend_establishment_via_egregious_event(
    api: ApiClient,
    establishment: Dict[str, Any],
    reporter_id: str,
    reviewer_id: str,
    *,
    species: Optional[str] = None,
    observed_at: str = f.DEFAULT_OBSERVED_AT,
    description: str = "egregious humane handling event",
) -> Dict[str, Any]:
    """Immediate-suspension chain: report an EGREGIOUS event, confirm it as a
    DIFFERENT reviewer. Confirmation auto-creates an IN_EFFECT SUSPENSION
    (basis EGREGIOUS_HUMANE, auto_created true) whose cascade suspends the
    establishment, blocks PLANNED/COVERAGE_GAP_FLAGGED windows and holds
    UNDER_REVIEW label applications.

    Returns {"event", "enforcement_action", "establishment"} with the
    establishment re-read after the cascade."""
    est_id = establishment["id"]
    species = species or establishment["species_classes"][0]
    event = report_humane_event(
        api, est_id, reporter_id, species=species, severity="EGREGIOUS",
        observed_at=observed_at, description=description,
    )
    event = confirm_humane_event(api, event["id"], reviewer_id)
    action = next(
        a
        for a in list_enforcement_actions(api, est_id)
        if a["action_type"] == "SUSPENSION" and a["basis"] == "EGREGIOUS_HUMANE" and a["status"] == "IN_EFFECT"
    )
    return {
        "event": event,
        "enforcement_action": action,
        "establishment": get_establishment(api, est_id),
    }


# ── Pathogen samples ─────────────────────────────────────────────────────────

def collect_pathogen_sample(
    api: ApiClient,
    establishment_id: str,
    inspector_id: str,
    *,
    pathogen: str = "SALMONELLA",
    collected_at: str = f.DEFAULT_COLLECTED_AT,
) -> Dict[str, Any]:
    """Log a sample as the collecting inspector (X-User-ID pinned); the
    establishment must hold a grant. Born with result PENDING."""
    return get_success_data(
        api.create_pathogen_sample(
            f.pathogen_sample_payload(
                establishment_id, inspector_id, pathogen=pathogen, collected_at=collected_at
            ),
            make_inspector_headers(inspector_id),
        )
    )


def collect_pathogen_samples(
    api: ApiClient,
    establishment_id: str,
    inspector_id: str,
    pathogen: str,
    count: int,
    *,
    first_collected_at: str = f.DEFAULT_COLLECTED_AT,
    step_minutes: int = 30,
) -> List[Dict[str, Any]]:
    """Collect ``count`` PENDING samples of one pathogen, their collection
    times stepping forward from ``first_collected_at`` (default base is
    strictly before the boot clock, so no step count used by the test plan
    crosses it)."""
    return [
        collect_pathogen_sample(
            api,
            establishment_id,
            inspector_id,
            pathogen=pathogen,
            collected_at=f.iso_add_minutes(first_collected_at, i * step_minutes),
        )
        for i in range(count)
    ]


def record_sample_result(api: ApiClient, sample_id: str, inspector_id: str, result: str) -> Dict[str, Any]:
    """Record POSITIVE or NEGATIVE on a PENDING sample; stamps resulted_at from
    the logical clock and recomputes the establishment's pathogen_category."""
    return get_success_data(
        api.record_sample_result(sample_id, f.record_result_payload(result), make_inspector_headers(inspector_id))
    )


def categorize_pathogen(
    api: ApiClient,
    establishment_id: str,
    inspector_id: str,
    pathogen: str,
    *,
    positives: int,
    negatives: int,
    first_collected_at: str = f.DEFAULT_COLLECTED_AT,
) -> List[Dict[str, Any]]:
    """Collect ``positives + negatives`` samples of one pathogen and record
    the first ``positives`` as POSITIVE, the rest NEGATIVE. With a total of at
    least 10 results the establishment's category is recomputed per the
    positive-rate thresholds. Returns the samples in creation order."""
    samples = collect_pathogen_samples(
        api,
        establishment_id,
        inspector_id,
        pathogen,
        positives + negatives,
        first_collected_at=first_collected_at,
    )
    for i, sample in enumerate(samples):
        record_sample_result(api, sample["id"], inspector_id, "POSITIVE" if i < positives else "NEGATIVE")
    return samples


# ── Label applications ───────────────────────────────────────────────────────

def submit_label_application(
    api: ApiClient,
    establishment_id: str,
    *,
    product_name: str = "Test Product",
    label_claim: str = "BREED_SPECIFIC",
    documentation_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Submit a label application as the establishment itself
    (ownership-pinned); born SUBMITTED with revision_count 0."""
    return get_success_data(
        api.create_label_application(
            f.label_application_payload(
                establishment_id,
                product_name=product_name,
                label_claim=label_claim,
                documentation_refs=documentation_refs,
            ),
            make_establishment_manager_headers(establishment_id),
        )
    )


def begin_label_review(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.begin_label_review(application_id, LABEL_OFFICER_HEADERS))


def decide_label(api: ApiClient, application_id: str, decision: str) -> Dict[str, Any]:
    """LabelOfficer decision: APPROVE | REJECT | RETURN, from UNDER_REVIEW."""
    return get_success_data(
        api.decide_label_application(application_id, f.label_decision_payload(decision), LABEL_OFFICER_HEADERS)
    )


def resubmit_label(
    api: ApiClient,
    application_id: str,
    establishment_id: str,
    documentation_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Resubmit a RETURNED application as its establishment (ownership-pinned,
    barred while the establishment is SUSPENDED); bumps revision_count."""
    return get_success_data(
        api.resubmit_label_application(
            application_id,
            f.label_resubmit_payload(documentation_refs),
            make_establishment_manager_headers(establishment_id),
        )
    )


def create_label_in_review(
    api: ApiClient,
    establishment_id: str,
    *,
    product_name: str = "Review Product",
    label_claim: str = "BREED_SPECIFIC",
    documentation_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A label application walked to UNDER_REVIEW (the status the suspension
    cascade holds)."""
    label = submit_label_application(
        api, establishment_id, product_name=product_name,
        label_claim=label_claim, documentation_refs=documentation_refs,
    )
    return begin_label_review(api, label["id"])


def create_approved_label(
    api: ApiClient,
    establishment_id: str,
    *,
    product_name: str = "Approved Product",
    label_claim: str = "BREED_SPECIFIC",
    documentation_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A label application walked SUBMITTED -> UNDER_REVIEW -> APPROVED. The
    default claim BREED_SPECIFIC needs exactly 1 documentation reference."""
    label = create_label_in_review(
        api, establishment_id, product_name=product_name,
        label_claim=label_claim, documentation_refs=documentation_refs,
    )
    return decide_label(api, label["id"], "APPROVE")


def list_label_applications(api: ApiClient, establishment_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(api.list_label_applications(establishment_id, LABEL_OFFICER_HEADERS))
    return rows


# ── Recalls ──────────────────────────────────────────────────────────────────

def create_recall(api: ApiClient, establishment_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a recall case (RecallCoordinator); born INITIATED with recall_class
    null, both requirement fields unset and counters at 0. Recall creation is
    NOT grant-gated, so this works on a freshly registered establishment."""
    return get_success_data(
        api.create_recall(f.recall_payload(establishment_id, **overrides), RECALL_COORDINATOR_HEADERS)
    )


def get_recall(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_recall(recall_id, RECALL_COORDINATOR_HEADERS))


def determine_recall_class(api: ApiClient, recall_id: str, recall_class: str) -> Dict[str, Any]:
    """DistrictManager classification; defined from INITIATED and
    CLOSED_INEFFECTIVE. Sets required_min_checks / required_effectiveness_ratio
    from the class (10/0.95, 5/0.80, 4/0.75)."""
    return get_success_data(
        api.determine_recall_class(recall_id, f.determine_class_payload(recall_class), DISTRICT_MANAGER_HEADERS)
    )


def record_effectiveness_check(
    api: ApiClient,
    recall_id: str,
    *,
    consignee_name: str = "Depot A",
    outcome: str = "EFFECTIVE",
    checked_at: str = f.DEFAULT_CHECKED_AT,
) -> Dict[str, Any]:
    """Record one append-only check; requires the recall to be
    CLASS_DETERMINED (else ERR_RECALL_CLASS_REQUIRED)."""
    return get_success_data(
        api.record_effectiveness_check(
            recall_id,
            f.effectiveness_check_payload(
                consignee_name=consignee_name, outcome=outcome, checked_at=checked_at
            ),
            RECALL_COORDINATOR_HEADERS,
        )
    )


def record_effectiveness_checks(
    api: ApiClient,
    recall_id: str,
    outcomes: List[str],
    *,
    first_checked_at: str = f.DEFAULT_CHECKED_AT,
    step_minutes: int = 60,
) -> List[Dict[str, Any]]:
    """Record one check per outcome ("EFFECTIVE"/"INEFFECTIVE"), stepping the
    check times forward from a base that lies before the boot clock."""
    return [
        record_effectiveness_check(
            api,
            recall_id,
            consignee_name=f"Depot {i + 1}",
            outcome=outcome,
            checked_at=f.iso_add_minutes(first_checked_at, i * step_minutes),
        )
        for i, outcome in enumerate(outcomes)
    ]


def close_recall(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    """Close a CLASS_DETERMINED recall; the outcome is computed from the
    effectiveness criteria, not chosen."""
    return get_success_data(api.close_recall(recall_id, RECALL_COORDINATOR_HEADERS))


def create_class_determined_recall(
    api: ApiClient, establishment_id: str, recall_class: str, **overrides: Any
) -> Dict[str, Any]:
    """A recall walked INITIATED -> CLASS_DETERMINED with the given class."""
    recall = create_recall(api, establishment_id, **overrides)
    return determine_recall_class(api, recall["id"], recall_class)


# ── Appeals ──────────────────────────────────────────────────────────────────

def file_appeal(
    api: ApiClient,
    record_id: str,
    establishment_id: str,
    *,
    grounds: Optional[str] = None,
) -> Dict[str, Any]:
    """File an appeal as the cited establishment (ownership-pinned); the
    appeal is born FILED and the record moves to APPEALED, recording its prior
    status in status_before_appeal."""
    payload = f.appeal_payload(record_id) if grounds is None else f.appeal_payload(record_id, grounds)
    return get_success_data(
        api.create_appeal(payload, make_establishment_manager_headers(establishment_id))
    )


def decide_appeal(api: ApiClient, appeal_id: str, reviewer_id: str, outcome: str) -> Dict[str, Any]:
    """SupervisoryReviewer decision: AFFIRM | REMAND | VACATE. reviewer_id must
    differ from the record's issued_by_inspector_id (segregation of duties).
    Every decision stamps decided_by_reviewer_id and decided_at."""
    return get_success_data(
        api.decide_appeal(
            appeal_id, f.appeal_decision_payload(outcome), make_supervisory_reviewer_headers(reviewer_id)
        )
    )


# ═══ Tier 4: accumulation / threshold targeting ═════════════════════════════

def issue_and_escalate_nrs(
    api: ApiClient,
    establishment_id: str,
    inspector_id: str,
    family: str,
    count: int,
    *,
    observed_at_base: str = f.DEFAULT_OBSERVED_AT,
    step_minutes: int = 60,
) -> List[Dict[str, Any]]:
    """Issue ``count`` NRs in one regulation family and ESCALATE each, driving
    the family's qualifying-NR count. The 3rd escalation within the trailing
    90 days auto-creates a PROPOSED SUSPENSION (basis NR_LINKAGE); this helper
    is typically called with count 2 (below threshold) so the test itself
    performs the threshold-crossing escalation. Returns the NRs in order."""
    records = []
    for i in range(count):
        record = issue_nr(
            api,
            establishment_id,
            inspector_id,
            regulation_family=family,
            description=f"{family.lower()} finding {i + 1}",
            observed_at=f.iso_add_minutes(observed_at_base, i * step_minutes),
        )
        records.append(escalate_nr(api, record["id"], inspector_id))
    return records


def suspend_and_lift_via_egregious_event(
    api: ApiClient,
    establishment: Dict[str, Any],
    reporter_id: str,
    reviewer_id: str,
    *,
    observed_at: str = f.DEFAULT_OBSERVED_AT,
) -> Dict[str, Any]:
    """One full suspension cycle: egregious confirmation suspends the
    establishment, then the auto-created SUSPENSION is lifted with abatement
    evidence, returning inspection_status to ACTIVE while suspension_count
    stays at 1. Returns the suspend dict plus the lifted action."""
    cycle = suspend_establishment_via_egregious_event(
        api, establishment, reporter_id, reviewer_id, observed_at=observed_at
    )
    lifted = lift_enforcement(api, cycle["enforcement_action"]["id"])
    cycle["enforcement_action"] = lifted
    cycle["establishment"] = get_establishment(api, establishment["id"])
    return cycle


# ═══ Tier 5: terminal / cycle states ═════════════════════════════════════════

def create_closed_recall(
    api: ApiClient,
    establishment_id: str,
    recall_class: str,
    outcomes: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    """A recall carried to a closed terminal state: classify, record the given
    check outcomes, then close. The closing status is computed by the rule:
    CLOSED_EFFECTIVE iff the rounded ratio meets the class requirement
    (equality closes effective), else CLOSED_INEFFECTIVE. Example:
    CLASS_III with ["EFFECTIVE", "EFFECTIVE", "INEFFECTIVE", "INEFFECTIVE"]
    closes CLOSED_INEFFECTIVE (0.50 < 0.75)."""
    recall = create_class_determined_recall(api, establishment_id, recall_class, **overrides)
    record_effectiveness_checks(api, recall["id"], outcomes)
    return close_recall(api, recall["id"])


def create_vacated_nr(
    api: ApiClient,
    establishment_id: str,
    issuer_id: str,
    reviewer_id: str,
    *,
    regulation_family: str = "SANITATION",
) -> Dict[str, Any]:
    """An NR pushed to its VACATED terminal state via appeal: issue (OPEN) ->
    appeal (APPEALED) -> decide VACATE. A vacated record drops out of
    open_nr_count, escalation counts and both risk scores.
    Returns {"record", "appeal"}."""
    record = issue_nr(api, establishment_id, issuer_id, regulation_family=regulation_family)
    appeal = file_appeal(api, record["id"], establishment_id)
    appeal = decide_appeal(api, appeal["id"], reviewer_id, "VACATE")
    return {"record": get_nr(api, record["id"]), "appeal": appeal}
