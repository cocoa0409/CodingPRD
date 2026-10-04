"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the runner restarts the API server before every individual test,
so each test starts against an empty database. Setup calls use the lenient
get_success_data() validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adoption_payload,
    create_agreement_payload,
    create_cell_payload,
    create_class_plan_payload,
    create_circular_payload,
    create_department_payload,
    create_filing_payload,
    create_finding_payload,
    create_form_payload,
    create_insurer_payload,
    create_revision_payload,
    create_statistical_plan_payload,
    create_submission_payload,
    create_variant_payload,
)
from .test_users import TEST_USERS, make_insurer_headers, make_regulator_headers

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive creates
# ---------------------------------------------------------------------------

def make_department(state_code="TX", objection_window_days=30, max_lcm_deviation_pct=25):
    """Register a state department. Returns the department dict."""
    resp = api_client.create_department(
        create_department_payload(
            state_code=state_code,
            department_name=f"{state_code} Department of Insurance",
            objection_window_days=objection_window_days,
            max_lcm_deviation_pct=max_lcm_deviation_pct,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def make_insurer():
    """Register an ACTIVE member insurer (quality_score_bps starts at 10000)."""
    resp = api_client.create_insurer(create_insurer_payload(), ADMIN)
    return get_success_data(resp)


def make_active_plan():
    """Create a statistical plan and activate it (DRAFT -> ACTIVE)."""
    resp = api_client.create_statistical_plan(create_statistical_plan_payload(), ADMIN)
    plan = get_success_data(resp)
    resp = api_client.activate_statistical_plan(plan["id"], ADMIN)
    return get_success_data(resp)


def make_agreement(insurer_id, coverage_start="2026-01-01T00:00:00Z",
                   coverage_end="2027-12-31T00:00:00Z", royalty_rate_bps=250):
    """Create an ACTIVE license agreement for the insurer."""
    resp = api_client.create_agreement(
        create_agreement_payload(
            insurer_id,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            royalty_rate_bps=royalty_rate_bps,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock (BureauAdmin only)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: submissions
# ---------------------------------------------------------------------------

def make_submission(insurer_id, plan_id, **overrides):
    """InsurerUser submits a statistical batch (lands RECEIVED)."""
    resp = api_client.create_submission(
        create_submission_payload(insurer_id, plan_id, **overrides),
        make_insurer_headers(insurer_id),
    )
    return get_success_data(resp)


def begin_edit(submission_id):
    resp = api_client.begin_edit(submission_id, ADMIN)
    return get_success_data(resp)


def add_finding(submission_id, severity="ERROR", edit_code=None, affected_records=1):
    payload = create_finding_payload(severity=severity, affected_records=affected_records)
    if edit_code is not None:
        payload["edit_code"] = edit_code
    resp = api_client.create_finding(submission_id, payload, ADMIN)
    return get_success_data(resp)


def dispose(submission_id, payload=None):
    resp = api_client.dispose_submission(submission_id, ADMIN, payload=payload)
    return get_success_data(resp)


def setup_insurer_with_active_plan():
    """One ACTIVE insurer + one ACTIVE statistical plan. Returns (insurer, plan)."""
    insurer = make_insurer()
    plan = make_active_plan()
    return insurer, plan


def make_disposed_submission(insurer_id, plan_id, findings=(), submission_overrides=None):
    """Create a submission, begin edit, record the given findings
    (list of (severity, affected_records)), and dispose. Returns the disposed
    submission dict."""
    sub = make_submission(insurer_id, plan_id, **(submission_overrides or {}))
    begin_edit(sub["id"])
    for idx, (severity, affected) in enumerate(findings):
        add_finding(sub["id"], severity=severity, edit_code=f"F-{idx}", affected_records=affected)
    return dispose(sub["id"])


# ---------------------------------------------------------------------------
# Tier 3: filings
# ---------------------------------------------------------------------------

def make_draft_filing(cells=(create_cell_payload(),), filing_overrides=None):
    """Create a filing and add the given cells. Returns the filing dict."""
    resp = api_client.create_filing(create_filing_payload(**(filing_overrides or {})), ADMIN)
    filing = get_success_data(resp)
    for cell in cells:
        api_client.create_cell(filing["id"], cell, ADMIN)
    return get_success_data(api_client.get_filing(filing["id"], ADMIN))


def make_reviewed_filing(cells=None, filing_overrides=None, submit_admin=None):
    """Filing carried DRAFT -> IN_ACTUARIAL_REVIEW -> REVIEWED (actuary completes).

    Returns the REVIEWED filing dict (including indicated_change_pct).
    """
    filing = make_draft_filing(
        cells=cells if cells is not None else [create_cell_payload()],
        filing_overrides=filing_overrides,
    )
    api_client.submit_filing_review(filing["id"], submit_admin or ADMIN)
    resp = api_client.complete_filing_review(filing["id"], ACTUARY)
    return get_success_data(resp)


def make_filed_filing(cells=None, filing_overrides=None, department_overrides=None):
    """Filing carried to FILED. Creates the state department first.

    Returns (filing, department).
    """
    overrides = filing_overrides or {}
    dept_overrides = department_overrides or {}
    dept = make_department(
        state_code=overrides.get("state_code", "TX"),
        **dept_overrides,
    )
    filing = make_reviewed_filing(cells=cells, filing_overrides=overrides)
    resp = api_client.file_filing(filing["id"], ADMIN)
    return get_success_data(resp), dept


def make_effective_filing(cells=None, filing_overrides=None, department_overrides=None,
                          advance_clock_to="2026-10-02T00:00:00Z"):
    """Filing carried to EFFECTIVE: filed at the default clock (2026-09-01) with a
    30-day objection window, then the clock advanced past the window and finalize
    called. Returns (filing, department)."""
    filing, dept = make_filed_filing(
        cells=cells, filing_overrides=filing_overrides, department_overrides=department_overrides
    )
    if advance_clock_to:
        set_clock(advance_clock_to)
    resp = api_client.finalize_filing(filing["id"], ADMIN)
    return get_success_data(resp), dept


def make_objected_filing(cells=None, filing_overrides=None, department_overrides=None,
                         objection_code="R-01", objection_text="Objected"):
    """Filing carried to OBJECTED: FILED at the default clock, then objected
    within the window by the matching-department RegulatorAnalyst.

    Returns (filing_after_objection, department, objection).
    """
    filing, dept = make_filed_filing(
        cells=cells, filing_overrides=filing_overrides, department_overrides=department_overrides
    )
    resp = api_client.raise_objection(
        filing["id"],
        {"department_id": dept["id"], "objection_code": objection_code, "objection_text": objection_text},
        make_regulator_headers(dept["id"]),
    )
    objection = get_success_data(resp)
    filing = get_success_data(api_client.get_filing(filing["id"], ADMIN))
    return filing, dept, objection


# ---------------------------------------------------------------------------
# Tier 4: adoptions
# ---------------------------------------------------------------------------

def make_adoption(insurer_id, filing, multiplier_pct=110):
    """Create a PENDING adoption against the given (EFFECTIVE) filing, pinning
    the filing's current version. Returns the adoption dict."""
    resp = api_client.create_adoption(
        create_adoption_payload(insurer_id, filing["id"], filing["version"],
                                multiplier_pct=multiplier_pct),
        make_insurer_headers(insurer_id),
    )
    return get_success_data(resp)


def setup_adoption_scenario(multiplier_pct=110, cells=None, filing_overrides=None,
                            department_overrides=None, agreement_overrides=None):
    """Full adoption-ready scenario: TX department, ACTIVE insurer with a
    covering ACTIVE agreement, EFFECTIVE filing, one PENDING adoption.

    Returns dict(insurer, agreement, filing, department, adoption).
    """
    insurer = make_insurer()
    agreement = make_agreement(insurer["id"], **(agreement_overrides or {}))
    filing, dept = make_effective_filing(
        cells=cells, filing_overrides=filing_overrides, department_overrides=department_overrides
    )
    adoption = make_adoption(insurer["id"], filing, multiplier_pct=multiplier_pct)
    return {
        "insurer": insurer,
        "agreement": agreement,
        "filing": filing,
        "department": dept,
        "adoption": adoption,
    }


def authorize(adoption_id):
    resp = api_client.authorize_adoption(adoption_id, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: forms, variants, circulars
# ---------------------------------------------------------------------------

def make_form_with_variants(variant_overrides_list=None, form_overrides=None):
    """Create a form and add the given variants. Returns (form, [variants])."""
    resp = api_client.create_form(create_form_payload(**(form_overrides or {})), ADMIN)
    form = get_success_data(resp)
    variants = []
    for vo in (variant_overrides_list or [{}]):
        r = api_client.create_variant(form["id"], create_variant_payload(**vo), ADMIN)
        variants.append(get_success_data(r))
    return form, variants


def make_approved_form(variant_overrides_list=None, form_overrides=None):
    """Form carried DRAFTING -> IN_REVIEW -> APPROVED with all variants CLEARED.

    Returns (form, [variants]).
    """
    form, variants = make_form_with_variants(variant_overrides_list, form_overrides)
    api_client.submit_form_review(form["id"], ADMIN)
    for v in variants:
        api_client.clear_variant(v["id"], ACTUARY)
    resp = api_client.approve_form(form["id"], ACTUARY)
    form = get_success_data(resp)
    variants = [get_success_data(api_client.get_variant(v["id"], ADMIN)) for v in variants]
    return form, variants


def make_published_form_with_scheduled_variant(implementation_date="2026-11-01T00:00:00Z",
                                               variant_overrides_list=None,
                                               form_overrides=None):
    """APPROVED form published via circular; CLEARED variants land SCHEDULED.

    Returns dict(form, variants, circular).
    """
    form, variants = make_approved_form(variant_overrides_list, form_overrides)
    resp = api_client.create_circular(
        create_circular_payload(implementation_date=implementation_date, form_ids=[form["id"]]),
        ADMIN,
    )
    circular = get_success_data(resp)
    resp = api_client.publish_circular(circular["id"], ADMIN)
    circular = get_success_data(resp)
    form = get_success_data(api_client.get_form(form["id"], ADMIN))
    variants = [get_success_data(api_client.get_variant(v["id"], ADMIN)) for v in variants]
    return {"form": form, "variants": variants, "circular": circular}


# ---------------------------------------------------------------------------
# Tier 6: class plans
# ---------------------------------------------------------------------------

def make_class_plan(line_of_business="COMMERCIAL_PROPERTY"):
    resp = api_client.create_class_plan(
        create_class_plan_payload(line_of_business=line_of_business), ADMIN
    )
    return get_success_data(resp)


def make_staged_revision(plan_id, class_count=12, activates_at="2026-08-01T00:00:00Z"):
    resp = api_client.create_revision(
        plan_id, create_revision_payload(class_count=class_count, activates_at=activates_at), ADMIN
    )
    return get_success_data(resp)


def make_activated_plan(activates_at="2026-08-01T00:00:00Z"):
    """Class plan with one revision ACTIVATED (activates_at in the past relative
    to the default logical clock). Returns (plan, revision)."""
    plan = make_class_plan()
    rev = make_staged_revision(plan["id"], activates_at=activates_at)
    resp = api_client.activate_revision(rev["id"], ADMIN)
    rev = get_success_data(resp)
    plan = get_success_data(api_client.get_class_plan(plan["id"], ADMIN))
    return plan, rev
