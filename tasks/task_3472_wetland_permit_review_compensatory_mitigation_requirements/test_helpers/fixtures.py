"""Composite setup helpers (PRD §3 workflows).

The harness restarts the API server before every test, so every fixture
builds its preconditions from scratch against an empty database. All helpers
use `get_success_data` so a broken setup fails loudly with the server's
error instead of a confusing downstream assertion.

Identity threading (PRD §2.1/§2.9): after a fixture creates an Applicant,
every ownership-gated call uses `make_applicant_headers(applicant["id"])`.
Opaque-role calls use the canonical operator ids from test_users so the two
segregation-of-duties gates behave deterministically (decision engineer
de-9 != screener rev-1; confirming officer eo-2 != opener eo-1).

Clock discipline (PRD §2.5): the logical clock starts at exactly
2026-09-01T00:00:00Z and only moves forward via POST /_clock/set_current_utc.
Fixtures that need a later instant compute it from timestamps captured in
earlier responses (e.g. `notice_published_date`), never from module state.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import expected_coverage_interval, iso_add_days
from .constants import (
    DEFAULT_BUY_CREDITS,
    DEFAULT_IMPACT_ACRES,
    DEFAULT_IMPACT_RESOURCE_TYPE,
)
from .factories import (
    create_agency_comment_payload,
    create_applicant_payload,
    create_application_payload,
    create_credit_transaction_payload,
    create_enforcement_case_payload,
    create_jd_payload,
    create_mitigation_bank_payload,
    create_mitigation_plan_payload,
    create_site_payload,
    create_alternatives_analysis_payload,
    create_appeal_payload,
    decide_appeal_payload,
    impact_line,
    patch_application_payload,
    patch_mitigation_plan_payload,
    pay_in_lieu_fee_payload,
    publish_notice_payload,
    render_decision_payload,
    resolve_comment_payload,
    review_aa_payload,
    review_plan_payload,
    review_report_payload,
    screening_payload,
    set_resolution_payload,
    submit_application_payload,
    submit_monitoring_report_payload,
)
from .test_users import (
    AGENCY_REVIEWER_USER_ID,
    DECISION_ENGINEER_USER_ID,
    DISTRICT_ENGINEER_USER_ID,
    OFFICER_CONFIRMER_USER_ID,
    OFFICER_OPENER_USER_ID,
    REVIEWER_USER_ID,
    TEST_USERS,
    make_agency_reviewer_headers,
    make_applicant_headers,
    make_district_engineer_headers,
    make_enforcement_officer_headers,
    make_reviewer_headers,
)
from .types import (
    AppealOutcome,
    DecisionOutcome,
    Mechanism,
    Pathway,
    PlanVerdict,
    ReportOutcome,
    ResolutionTrack,
    AaVerdict,
    ScreeningAction,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_REVIEWER = TEST_USERS["reviewer_headers"]
_DE = TEST_USERS["district_engineer_headers"]


# ===========================================================================
# Tier 0: platform clock (PRD §2.5)
# ===========================================================================
def set_clock(to_iso8601: str) -> str:
    """Advance the logical clock (SystemAdmin-only, outside the API prefix).
    Returns the confirmed current_utc."""
    resp = api_client.set_clock(to_iso8601, _ADMIN)
    return get_success_data(resp)["current_utc"]


def advance_clock_days(from_iso8601: str, days: int) -> str:
    """Advance the clock to `from_iso8601 + days` and return the new value."""
    return set_clock(iso_add_days(from_iso8601, days))


# ===========================================================================
# Tier 1: base record chain — applicants, sites, determinations (PRD §3.1)
# ===========================================================================
def create_applicant(**overrides) -> dict:
    resp = api_client.create_applicant(create_applicant_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def create_site(applicant: dict, **overrides) -> dict:
    resp = api_client.create_site(create_site_payload(applicant["id"], **overrides), _ADMIN)
    return get_success_data(resp)


def create_jd(site: dict, reviewer_headers=None, **overrides) -> dict:
    """Create a jurisdictional determination in DRAFT (Reviewer)."""
    resp = api_client.create_jd(
        create_jd_payload(site["id"], **overrides), reviewer_headers or _REVIEWER
    )
    return get_success_data(resp)


def issue_jd(jd: dict, engineer_headers=None) -> dict:
    """Issue a DRAFT determination (DistrictEngineer)."""
    resp = api_client.issue_jd(jd["id"], engineer_headers or _DE)
    return get_success_data(resp)


def create_and_issue_jd(site: dict, **overrides) -> dict:
    return issue_jd(create_jd(site, **overrides))


def setup_applicant_and_site(**site_overrides) -> tuple:
    """One registered applicant with one waters site. Returns (applicant, site)."""
    applicant = create_applicant()
    site = create_site(applicant, **site_overrides)
    return applicant, site


def setup_site_with_issued_jd(site_overrides=None, jd_overrides=None) -> tuple:
    """Applicant + site + an ISSUED APPROVED JURISDICTIONAL determination.
    Returns (applicant, site, jd)."""
    applicant, site = setup_applicant_and_site(**(site_overrides or {}))
    jd = create_and_issue_jd(site, **(jd_overrides or {}))
    return applicant, site, jd


# ===========================================================================
# Tier 2: application walk (PRD §3.3)
# ===========================================================================
def create_application(site: dict, jd: dict, applicant: dict, **overrides) -> dict:
    """Create a DRAFT application; applicant_id is set from X-User-ID."""
    resp = api_client.create_application(
        create_application_payload(site["id"], jd["id"], **overrides),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def patch_application(app: dict, applicant: dict, expected_version, **fields) -> dict:
    resp = api_client.patch_application(
        app["id"],
        patch_application_payload(expected_version, **fields),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def submit_application(app: dict, applicant: dict, new_jd_id=None) -> dict:
    resp = api_client.submit_application(
        app["id"],
        make_applicant_headers(applicant["id"]),
        payload=submit_application_payload(new_jd_id),
    )
    return get_success_data(resp)


def screen_application(app: dict, action, reviewer_headers=None, return_reason=None) -> dict:
    resp = api_client.screening_application(
        app["id"],
        screening_payload(action, return_reason=return_reason),
        reviewer_headers or _REVIEWER,
    )
    return get_success_data(resp)


def submit_and_screen_begin(app: dict, applicant: dict, reviewer_headers=None) -> dict:
    """DRAFT/RETURNED_TO_APPLICANT -> SUBMITTED -> SCREENING."""
    screen_headers = reviewer_headers or _REVIEWER
    app = submit_application(app, applicant)
    return screen_application(app, ScreeningAction.BEGIN.value, screen_headers)


def walk_application_to_alternatives_review(app: dict, applicant: dict,
                                            reviewer_headers=None) -> dict:
    """Individual pathways: DRAFT -> SUBMITTED -> SCREENING -> ALTERNATIVES_REVIEW."""
    screen_headers = reviewer_headers or _REVIEWER
    app = submit_and_screen_begin(app, applicant, screen_headers)
    return screen_application(app, ScreeningAction.APPROVE.value, screen_headers)


def walk_general_application_to_decision_pending(app: dict, applicant: dict,
                                                 reviewer_headers=None) -> dict:
    """General pathways: DRAFT -> SUBMITTED -> SCREENING -> DECISION_PENDING;
    the streamlined path skips alternatives review, public notice, and the
    public interest review entirely (PRD §3.3)."""
    screen_headers = reviewer_headers or _REVIEWER
    app = submit_and_screen_begin(app, applicant, screen_headers)
    return screen_application(app, ScreeningAction.APPROVE.value, screen_headers)


def setup_application_in_alternatives_review(app_overrides=None, site_overrides=None,
                                             jd_overrides=None) -> dict:
    """Applicant + site + issued JD + INDIVIDUAL application in
    ALTERNATIVES_REVIEW. Returns a context dict."""
    applicant, site, jd = setup_site_with_issued_jd(site_overrides, jd_overrides)
    app = create_application(site, jd, applicant, **(app_overrides or {}))
    app = walk_application_to_alternatives_review(app, applicant)
    return {"applicant": applicant, "site": site, "jd": jd, "app": app}


# ===========================================================================
# Tier 2: alternatives analysis and the LEDPA gate (PRD §3.4)
# ===========================================================================
def create_aa(app: dict, applicant: dict, **overrides) -> dict:
    resp = api_client.create_alternatives_analysis(
        create_alternatives_analysis_payload(app["id"], **overrides),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def patch_aa(aa: dict, applicant: dict, **fields) -> dict:
    """Revise a REVISION_REQUESTED analysis; returns it to SUBMITTED."""
    resp = api_client.patch_alternatives_analysis(
        aa["id"], fields, make_applicant_headers(applicant["id"])
    )
    return get_success_data(resp)


def review_aa(aa: dict, verdict=AaVerdict.ACCEPT.value, reviewer_headers=None,
              revision_notes=None) -> dict:
    resp = api_client.review_alternatives_analysis(
        aa["id"],
        review_aa_payload(verdict, revision_notes=revision_notes),
        reviewer_headers or _REVIEWER,
    )
    return get_success_data(resp)


def setup_aa_accepted(ctx: dict = None, aa_overrides=None, **setup_overrides) -> dict:
    """Application in ALTERNATIVES_REVIEW with its analysis ACCEPTED."""
    if ctx is None:
        ctx = setup_application_in_alternatives_review(**setup_overrides)
    aa = create_aa(ctx["app"], ctx["applicant"], **(aa_overrides or {}))
    ctx["aa"] = review_aa(aa)
    return ctx


# ===========================================================================
# Tier 3: public notice, agency comments, public interest review (PRD §3.5)
# ===========================================================================
def publish_notice(app: dict, comment_period_days=30, reviewer_headers=None) -> dict:
    """ALTERNATIVES_REVIEW -> PUBLIC_NOTICE_OPEN (requires the analysis
    ACCEPTED and notice_status NONE)."""
    resp = api_client.publish_notice(
        app["id"],
        reviewer_headers or _REVIEWER,
        payload=publish_notice_payload(comment_period_days),
    )
    return get_success_data(resp)


def close_comment_period(app: dict, extra_days=1) -> str:
    """Advance the clock strictly past notice_published_date +
    comment_period_days so notice_status flips to COMMENT_PERIOD_CLOSED
    (PRD §2.5 step 1: strictly-greater comparison). Returns the new clock."""
    published = app["notice_published_date"]
    period = app["comment_period_days"]
    return set_clock(iso_add_days(published, period + extra_days))


def advance_to_decision(app: dict, reviewer_headers=None) -> dict:
    """PUBLIC_NOTICE_OPEN -> DECISION_PENDING; computes and stores the public
    interest review (PRD §3.5)."""
    resp = api_client.advance_to_decision(app["id"], reviewer_headers or _REVIEWER)
    return get_success_data(resp)


def setup_application_public_notice_open(ctx: dict = None, comment_period_days=30,
                                         **setup_overrides) -> dict:
    """Application in PUBLIC_NOTICE_OPEN with the notice just published."""
    if ctx is None or "aa" not in ctx:
        ctx = setup_aa_accepted(ctx, **setup_overrides)
    ctx["app"] = publish_notice(ctx["app"], comment_period_days)
    return ctx


def setup_application_decision_pending(ctx: dict = None, comment_period_days=30,
                                       **setup_overrides) -> dict:
    """Application at DECISION_PENDING with pir_score/pir_outcome stored:
    notice published, comment period closed by a clock advance, then advanced
    to decision. Default scenario (2.0 FORESTED_WETLAND acres, 2 steps, cost
    750000, no comments, no plan) scores 17.25 FAVORABLE."""
    ctx = setup_application_public_notice_open(ctx, comment_period_days, **setup_overrides)
    close_comment_period(ctx["app"])
    ctx["app"] = advance_to_decision(ctx["app"])
    return ctx


def file_comment(app: dict, agency="EPA", comment_type="ADVISORY",
                 comment_text="Advisory comment", agency_user_id=AGENCY_REVIEWER_USER_ID) -> dict:
    resp = api_client.create_agency_comment(
        create_agency_comment_payload(
            app["id"], agency=agency, comment_type=comment_type,
            comment_text=comment_text,
        ),
        make_agency_reviewer_headers(agency_user_id),
    )
    return get_success_data(resp)


def resolve_comment(comment: dict, resolution_text="Resolved on the record",
                    reviewer_headers=None) -> dict:
    resp = api_client.resolve_agency_comment(
        comment["id"], resolve_comment_payload(resolution_text),
        reviewer_headers or _REVIEWER,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: mitigation plans, banks, credit transactions (PRD §3.6)
# ===========================================================================
def create_plan(app: dict, applicant: dict, mechanism=Mechanism.BANK_CREDITS.value,
                **overrides) -> dict:
    """Create a DRAFT plan. Individual pathways require the analysis ACCEPTED;
    general pathways require the application in DECISION_PENDING."""
    resp = api_client.create_mitigation_plan(
        create_mitigation_plan_payload(app["id"], mechanism=mechanism, **overrides),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def patch_plan(plan: dict, applicant: dict, expected_version, **fields) -> dict:
    resp = api_client.patch_mitigation_plan(
        plan["id"],
        patch_mitigation_plan_payload(expected_version, **fields),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def submit_plan(plan: dict, applicant: dict) -> dict:
    resp = api_client.submit_mitigation_plan(
        plan["id"], make_applicant_headers(applicant["id"])
    )
    return get_success_data(resp)


def review_plan(plan: dict, verdict=PlanVerdict.APPROVE.value, reviewer_headers=None,
                revision_notes=None) -> dict:
    resp = api_client.review_mitigation_plan(
        plan["id"],
        review_plan_payload(verdict, revision_notes=revision_notes),
        reviewer_headers or _REVIEWER,
    )
    return get_success_data(resp)


def setup_plan_approved(app: dict, applicant: dict,
                        mechanism=Mechanism.BANK_CREDITS.value, **overrides) -> dict:
    """Plan carried DRAFT -> SUBMITTED -> APPROVED."""
    plan = create_plan(app, applicant, mechanism=mechanism, **overrides)
    plan = submit_plan(plan, applicant)
    return review_plan(plan)


def _bank_maps_for_resource_types(resource_types, capacity=20.0, price=30000.0):
    return (
        {t: capacity for t in resource_types},
        {t: price for t in resource_types},
    )


def create_bank(resource_types=None, capacity=20.0, price=30000.0, **overrides) -> dict:
    """Register a bank in PENDING_APPROVAL (SystemAdmin). By default covers
    the given resource types (or FORESTED_WETLAND) at 20 capacity / 30000."""
    if "credit_capacity" not in overrides or "base_price_per_credit" not in overrides:
        cap_map, price_map = _bank_maps_for_resource_types(
            resource_types or [DEFAULT_IMPACT_RESOURCE_TYPE], capacity, price
        )
        overrides.setdefault("credit_capacity", cap_map)
        overrides.setdefault("base_price_per_credit", price_map)
    resp = api_client.create_mitigation_bank(
        create_mitigation_bank_payload(**overrides), _ADMIN
    )
    return get_success_data(resp)


def approve_bank(bank: dict, engineer_headers=None) -> dict:
    resp = api_client.approve_mitigation_bank(bank["id"], engineer_headers or _DE)
    return get_success_data(resp)


def suspend_bank(bank: dict, engineer_headers=None) -> dict:
    resp = api_client.suspend_mitigation_bank(bank["id"], engineer_headers or _DE)
    return get_success_data(resp)


def setup_operational_bank(resource_types=None, capacity=20.0, price=30000.0,
                           **overrides) -> dict:
    """Bank registered and approved to OPERATIONAL."""
    return approve_bank(create_bank(resource_types, capacity, price, **overrides))


def reserve_credits(bank: dict, plan: dict, applicant: dict,
                    resource_type=DEFAULT_IMPACT_RESOURCE_TYPE,
                    credits=DEFAULT_BUY_CREDITS) -> dict:
    """Create a RESERVED credit transaction; holds bank inventory immediately."""
    resp = api_client.create_credit_transaction(
        create_credit_transaction_payload(
            bank["id"], plan["id"], resource_type=resource_type, credits=credits
        ),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def purchase_credits(txn: dict, applicant: dict) -> dict:
    """RESERVED -> PURCHASED; stamps the tier-adjusted price (PRD §3.6)."""
    resp = api_client.purchase_credit_transaction(
        txn["id"], make_applicant_headers(applicant["id"])
    )
    return get_success_data(resp)


def release_credits(txn: dict, applicant: dict) -> dict:
    resp = api_client.release_credit_transaction(
        txn["id"], make_applicant_headers(applicant["id"])
    )
    return get_success_data(resp)


def reserve_and_purchase(bank: dict, plan: dict, applicant: dict,
                         resource_type=DEFAULT_IMPACT_RESOURCE_TYPE,
                         credits=DEFAULT_BUY_CREDITS) -> dict:
    txn = reserve_credits(bank, plan, applicant, resource_type, credits)
    return purchase_credits(txn, applicant)


def secure_plan(plan: dict, applicant: dict) -> dict:
    """APPROVED -> CREDITS_SECURED via secure-credits (BANK_CREDITS,
    PERMITTEE_RESPONSIBLE, COMBINATION)."""
    resp = api_client.secure_credits(plan["id"], make_applicant_headers(applicant["id"]))
    return get_success_data(resp)


def pay_ilf_fee(plan: dict, applicant: dict, amount_dollars) -> dict:
    """APPROVED -> CREDITS_SECURED via exact in-lieu fee payment."""
    resp = api_client.pay_in_lieu_fee(
        plan["id"],
        pay_in_lieu_fee_payload(amount_dollars),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def setup_secured_bank_credits_plan(ctx: dict, buy_credits=DEFAULT_BUY_CREDITS,
                                    resource_type=DEFAULT_IMPACT_RESOURCE_TYPE,
                                    bank_overrides=None) -> dict:
    """Given a context whose app is far enough along to hold a plan (analysis
    ACCEPTED for individual pathways, DECISION_PENDING for general), carry a
    BANK_CREDITS plan to CREDITS_SECURED: plan APPROVED, OPERATIONAL in-basin
    bank, `buy_credits` purchased, then secure-credits. Adds plan/bank/txn to
    the context."""
    applicant = ctx["applicant"]
    plan = setup_plan_approved(ctx["app"], applicant, Mechanism.BANK_CREDITS.value)
    bank = setup_operational_bank(
        resource_types=[resource_type], **(bank_overrides or {})
    )
    txn = reserve_and_purchase(bank, plan, applicant, resource_type, buy_credits)
    plan = secure_plan(plan, applicant)
    ctx.update({"plan": plan, "bank": bank, "txn": txn})
    return ctx


def setup_secured_prm_plan(ctx: dict, stewardship_entity_name="Piney Branch Stewardship LLC",
                           long_term_stewardship_secured=True,
                           financial_assurance_dollars=None) -> dict:
    """PERMITTEE_RESPONSIBLE plan to CREDITS_SECURED. When
    financial_assurance_dollars is None, the plan is created, the
    server-computed assurance_required_dollars is read back, and the plan is
    edited (OCC-guarded) to post exactly that amount before review — the PRD
    never publishes the assurance formula, so fixtures must not hardcode it."""
    applicant = ctx["applicant"]
    plan = create_plan(
        ctx["app"], applicant, Mechanism.PERMITTEE_RESPONSIBLE.value,
        stewardship_entity_name=stewardship_entity_name,
        long_term_stewardship_secured=long_term_stewardship_secured,
    )
    if financial_assurance_dollars is None:
        financial_assurance_dollars = plan["assurance_required_dollars"]
    plan = patch_plan(
        plan, applicant, plan["version"],
        financial_assurance_dollars=financial_assurance_dollars,
    )
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    plan = secure_plan(plan, applicant)
    ctx["plan"] = plan
    return ctx


def setup_secured_ilf_plan(ctx: dict) -> dict:
    """IN_LIEU_FEE plan to CREDITS_SECURED by paying the exact computed fee."""
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant, Mechanism.IN_LIEU_FEE.value)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    plan = pay_ilf_fee(plan, applicant, plan["ilf_fee_due_dollars"])
    ctx["plan"] = plan
    return ctx


# ===========================================================================
# Tier 4: decision, issuance, permit lifecycle (PRD §3.7, §3.8)
# ===========================================================================
def render_decision(app: dict, outcome=DecisionOutcome.ISSUE.value,
                    decision_rationale=None, engineer_headers=None) -> dict:
    """DistrictEngineer decision from DECISION_PENDING. The default decider
    (de-9) never equals the default screening reviewer (rev-1), so the
    segregation-of-duties gate passes (PRD §2.9)."""
    resp = api_client.render_decision(
        app["id"],
        render_decision_payload(outcome, decision_rationale),
        engineer_headers or make_district_engineer_headers(DECISION_ENGINEER_USER_ID),
    )
    return get_success_data(resp)


def withdraw_application(app: dict, applicant: dict) -> dict:
    resp = api_client.withdraw_application(
        app["id"], make_applicant_headers(applicant["id"])
    )
    return get_success_data(resp)


def get_permit_for_application(app: dict, headers=None) -> dict:
    """The permit created by render-decision ISSUE for this application."""
    resp = api_client.list_permits(
        headers or _REVIEWER, params={"application_id": app["id"]}
    )
    rows = get_success_data(resp)
    assert len(rows) == 1, f"expected exactly one permit for application {app['id']}"
    return rows[0]


def get_reports_for_permit(permit: dict, headers=None) -> list:
    """Reports of the permit, sorted by period_index ascending (PRD §2.3)."""
    resp = api_client.list_monitoring_reports(
        headers or _REVIEWER, params={"permit_id": permit["id"], "limit": 100}
    )
    return get_success_data(resp)


def get_cases_for_applicant(applicant: dict, headers=None) -> list:
    resp = api_client.list_enforcement_cases(
        headers or _REVIEWER, params={"responsible_applicant_id": applicant["id"]}
    )
    return get_success_data(resp)


def setup_issued_permit(pathway=Pathway.INDIVIDUAL.value, impacts=None,
                        estimated_cost_dollars=750000.0,
                        mechanism=Mechanism.BANK_CREDITS.value,
                        buy_credits=DEFAULT_BUY_CREDITS,
                        resource_type=DEFAULT_IMPACT_RESOURCE_TYPE,
                        comment_period_days=30) -> dict:
    """Full individual-pathway lifecycle through issuance (PRD §3.3-§3.7):
    applicant + site + issued JD, application walked SUBMITTED -> SCREENING ->
    ALTERNATIVES_REVIEW, analysis ACCEPTED, notice published and closed by the
    clock, advance-to-decision, plan carried to CREDITS_SECURED, then
    render-decision ISSUE by a decision engineer distinct from the screener.
    Returns a context dict with applicant, site, jd, app (ISSUED), aa, plan
    (ACTIVE), bank, txn, permit, reports (5 DUE)."""
    applicant, site, jd = setup_site_with_issued_jd()
    impacts = impacts or [impact_line(resource_type, DEFAULT_IMPACT_ACRES)]
    app = create_application(
        site, jd, applicant, pathway=pathway, impacts=impacts,
        estimated_cost_dollars=estimated_cost_dollars,
    )
    app = walk_application_to_alternatives_review(app, applicant)
    ctx = {"applicant": applicant, "site": site, "jd": jd, "app": app}
    ctx = setup_aa_accepted(ctx)
    ctx = setup_application_public_notice_open(ctx, comment_period_days)
    close_comment_period(ctx["app"])
    ctx["app"] = advance_to_decision(ctx["app"])
    if mechanism == Mechanism.BANK_CREDITS.value:
        ctx = setup_secured_bank_credits_plan(
            ctx, buy_credits=buy_credits, resource_type=resource_type
        )
    elif mechanism == Mechanism.IN_LIEU_FEE.value:
        ctx = setup_secured_ilf_plan(ctx)
    elif mechanism == Mechanism.PERMITTEE_RESPONSIBLE.value:
        ctx = setup_secured_prm_plan(ctx)
    else:
        raise ValueError(f"unsupported mechanism for setup_issued_permit: {mechanism}")
    ctx["app"] = render_decision(ctx["app"])
    ctx["permit"] = get_permit_for_application(ctx["app"])
    ctx["reports"] = get_reports_for_permit(ctx["permit"])
    return ctx


def setup_issued_general_permit(impacts=None, general_permit_code="NWP-39",
                                estimated_cost_dollars=80000.0) -> dict:
    """Full general-pathway lifecycle through issuance (PRD §3.3, §3.7):
    DRAFT -> SUBMITTED -> SCREENING -> DECISION_PENDING -> ISSUED with no
    analysis, notice, or public interest review. Intended for impacts at or
    below the 0.10-acre mitigation trigger (no plan needed)."""
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["EMERGENT_MARSH", "STREAM"]}
    )
    impacts = impacts or [impact_line("EMERGENT_MARSH", 0.05)]
    app = create_application(
        site, jd, applicant, pathway=Pathway.GENERAL.value,
        impacts=impacts, general_permit_code=general_permit_code,
        estimated_cost_dollars=estimated_cost_dollars,
    )
    app = walk_general_application_to_decision_pending(app, applicant)
    ctx = {"applicant": applicant, "site": site, "jd": jd, "app": app}
    ctx["app"] = render_decision(ctx["app"])
    ctx["permit"] = get_permit_for_application(ctx["app"])
    return ctx


def commence_permit(permit: dict, applicant: dict) -> dict:
    """ISSUED -> ACTIVE (PRD §3.8)."""
    resp = api_client.commence_work(
        permit["id"], make_applicant_headers(applicant["id"])
    )
    return get_success_data(resp)


def setup_active_permit(**overrides) -> dict:
    """Issued permit commenced to ACTIVE. Adds nothing else."""
    ctx = setup_issued_permit(**overrides)
    ctx["permit"] = commence_permit(ctx["permit"], ctx["applicant"])
    return ctx


def submit_report(report: dict, permit: dict, applicant: dict,
                  coverage_start=None, coverage_end=None,
                  findings_text="Monitoring findings") -> dict:
    """Submit a DUE/OVERDUE/DEFICIENT report. Default coverage is the zero-gap
    interval for the report's period_index (PRD §3.8)."""
    if coverage_start is None or coverage_end is None:
        coverage_start, coverage_end = expected_coverage_interval(
            permit["issue_date"], report["period_index"]
        )
    resp = api_client.submit_monitoring_report(
        report["id"],
        submit_monitoring_report_payload(coverage_start, coverage_end,
                                         findings_text=findings_text),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def review_report(report: dict, outcome=ReportOutcome.ACCEPTED.value,
                  deficiency_notes=None, reviewer_headers=None) -> dict:
    resp = api_client.review_monitoring_report(
        report["id"],
        review_report_payload(outcome, deficiency_notes=deficiency_notes),
        reviewer_headers or _REVIEWER,
    )
    return get_success_data(resp)


def submit_and_accept_report(report: dict, permit: dict, applicant: dict) -> dict:
    report = submit_report(report, permit, applicant)
    return review_report(report, ReportOutcome.ACCEPTED.value)


def setup_completed_monitoring(**overrides) -> dict:
    """Active permit with all five reports submitted and accepted; the fifth
    acceptance moves the plan ACTIVE -> COMPLETED (PRD §3.8)."""
    ctx = setup_active_permit(**overrides)
    accepted = []
    for report in ctx["reports"]:
        accepted.append(submit_and_accept_report(report, ctx["permit"], ctx["applicant"]))
    ctx["reports"] = accepted
    resp = api_client.get_mitigation_plan(ctx["plan"]["id"], _REVIEWER)
    ctx["plan"] = get_success_data(resp)
    return ctx


def setup_closed_permit(**overrides) -> dict:
    """Full lifecycle through permit CLOSED (5 ACCEPTED reports + COMPLETED
    plan, then DistrictEngineer close)."""
    ctx = setup_completed_monitoring(**overrides)
    resp = api_client.close_permit(ctx["permit"]["id"], _DE)
    ctx["permit"] = get_success_data(resp)
    return ctx


def setup_suspended_permit_by_breach(**overrides) -> dict:
    """Permit SUSPENDED by the monitoring-breach cascade (PRD §3.8, §2.5 step
    4): an ACTIVE permit whose first report stays DUE past due_date + 60 days
    flips OVERDUE and suspends the permit, auto-opening a MONITORING_BREACH
    enforcement case. Returns the context plus `breach_case`."""
    ctx = setup_active_permit(**overrides)
    first_due = ctx["reports"][0]["due_date"]
    # Strictly greater than due_date + 60 days (PRD §2.5 step 4).
    set_clock(iso_add_days(first_due, 61))
    resp = api_client.get_permit(ctx["permit"]["id"], _REVIEWER)
    ctx["permit"] = get_success_data(resp)
    cases = get_cases_for_applicant(ctx["applicant"])
    breach = [c for c in cases if c["case_source"] == "MONITORING_BREACH"]
    assert len(breach) == 1, "expected exactly one MONITORING_BREACH case"
    ctx["breach_case"] = breach[0]
    return ctx


# ===========================================================================
# Tier 4: appeals and the suspension cascade (PRD §3.2)
# ===========================================================================
def file_appeal(jd: dict, applicant: dict, grounds_text=None) -> dict:
    resp = api_client.create_appeal(
        create_appeal_payload(
            jd["id"], **({"grounds_text": grounds_text} if grounds_text else {})
        ),
        make_applicant_headers(applicant["id"]),
    )
    return get_success_data(resp)


def decide_appeal(appeal: dict, outcome=AppealOutcome.SUSTAINED.value,
                  decision_rationale="Decided on the record",
                  engineer_headers=None) -> dict:
    resp = api_client.decide_appeal(
        appeal["id"],
        decide_appeal_payload(outcome, decision_rationale),
        engineer_headers or make_district_engineer_headers(DISTRICT_ENGINEER_USER_ID),
    )
    return get_success_data(resp)


def setup_suspended_application(app_overrides=None) -> dict:
    """Application in SUSPENDED_PENDING_JD: its JD was reversed by a SUSTAINED
    appeal (PRD §3.2). Returns applicant, site, jd (REVERSED), appeal, app."""
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    app = create_application(site, jd, applicant, **(app_overrides or {}))
    app = submit_application(app, applicant)
    appeal = file_appeal(jd, applicant)
    appeal = decide_appeal(appeal, AppealOutcome.SUSTAINED.value,
                           "Delineation error confirmed on remand")
    resp = api_client.get_application(app["id"], _REVIEWER)
    app = get_success_data(resp)
    resp = api_client.get_jd(jd["id"], _REVIEWER)
    jd = get_success_data(resp)
    return {"applicant": applicant, "site": site, "jd": jd, "appeal": appeal, "app": app}


# ===========================================================================
# Tier 4: enforcement cases and after-the-fact resolution (PRD §3.9)
# ===========================================================================
def create_case(site: dict, applicant: dict, unauthorized_fill_acres=2.0,
                description="Unpermitted fill placed in forested wetland",
                opener_user_id=OFFICER_OPENER_USER_ID) -> dict:
    """Open a MANUAL enforcement case; the opener is recorded for the
    segregation-of-duties gate."""
    resp = api_client.create_enforcement_case(
        create_enforcement_case_payload(
            site["id"], applicant["id"],
            unauthorized_fill_acres=unauthorized_fill_acres,
            description=description,
        ),
        make_enforcement_officer_headers(opener_user_id),
    )
    return get_success_data(resp)


def confirm_case(case: dict, confirmer_user_id=OFFICER_CONFIRMER_USER_ID) -> dict:
    """OPENED -> VIOLATION_CONFIRMED; must be a different officer than the
    opener (PRD §2.9). Starts penalty accrual."""
    resp = api_client.confirm_violation(
        case["id"], make_enforcement_officer_headers(confirmer_user_id)
    )
    return get_success_data(resp)


def set_resolution_restoration(case: dict, officer_user_id=OFFICER_CONFIRMER_USER_ID) -> dict:
    """VIOLATION_CONFIRMED -> RESOLUTION_PENDING on the RESTORATION track;
    deadline = clock + 90 days."""
    resp = api_client.set_resolution(
        case["id"],
        set_resolution_payload(ResolutionTrack.RESTORATION.value),
        make_enforcement_officer_headers(officer_user_id),
    )
    return get_success_data(resp)


def set_resolution_atf(case: dict, app: dict,
                       officer_user_id=OFFICER_CONFIRMER_USER_ID) -> dict:
    """VIOLATION_CONFIRMED -> RESOLUTION_PENDING on the AFTER_THE_FACT_PERMIT
    track; the application's enforcement_case_id must name this case."""
    resp = api_client.set_resolution(
        case["id"],
        set_resolution_payload(
            ResolutionTrack.AFTER_THE_FACT_PERMIT.value, atf_application_id=app["id"]
        ),
        make_enforcement_officer_headers(officer_user_id),
    )
    return get_success_data(resp)


def verify_restoration(case: dict, officer_user_id=OFFICER_CONFIRMER_USER_ID) -> dict:
    """RESOLUTION_PENDING -> CLOSED on the RESTORATION track with the
    good-faith half penalty offset."""
    resp = api_client.verify_restoration(
        case["id"], make_enforcement_officer_headers(officer_user_id)
    )
    return get_success_data(resp)


def grant_extension(case: dict, engineer_headers=None) -> dict:
    """DEFAULTED -> RESOLUTION_PENDING; one-time +60-day extension."""
    resp = api_client.grant_extension(case["id"], engineer_headers or _DE)
    return get_success_data(resp)


def setup_case_opened(unauthorized_fill_acres=2.0) -> tuple:
    """Applicant + site + an OPENED enforcement case. Returns
    (applicant, site, case)."""
    applicant, site = setup_applicant_and_site(
        resource_types_present=["FORESTED_WETLAND"]
    )
    case = create_case(site, applicant, unauthorized_fill_acres)
    return applicant, site, case


def setup_case_confirmed(unauthorized_fill_acres=2.0) -> tuple:
    """Case carried OPENED -> VIOLATION_CONFIRMED by a second officer."""
    applicant, site, case = setup_case_opened(unauthorized_fill_acres)
    case = confirm_case(case)
    return applicant, site, case


def setup_case_restoration_pending(unauthorized_fill_acres=2.0) -> tuple:
    """Case on the RESTORATION track in RESOLUTION_PENDING."""
    applicant, site, case = setup_case_confirmed(unauthorized_fill_acres)
    case = set_resolution_restoration(case)
    return applicant, site, case


def get_case(case: dict, headers=None) -> dict:
    resp = api_client.get_enforcement_case(case["id"], headers or _REVIEWER)
    return get_success_data(resp)


# ===========================================================================
# Tier 5: after-the-fact issuance (PRD §3.9 + §3.7)
# ===========================================================================
def setup_atf_application_linked(unauthorized_fill_acres=2.0, impacts=None,
                                 estimated_cost_dollars=750000.0,
                                 pathway=Pathway.ATF_INDIVIDUAL.value) -> dict:
    """Two-way ATF linkage established (PRD §3.9): issued JD, enforcement case
    confirmed and set to the AFTER_THE_FACT_PERMIT track pointing at a DRAFT
    ATF application whose enforcement_case_id names the case. Returns
    applicant, site, jd, case (RESOLUTION_PENDING), app (DRAFT)."""
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    case = create_case(site, applicant, unauthorized_fill_acres)
    case = confirm_case(case)
    impacts = impacts or [impact_line(DEFAULT_IMPACT_RESOURCE_TYPE, DEFAULT_IMPACT_ACRES)]
    app = create_application(
        site, jd, applicant, pathway=pathway, impacts=impacts,
        estimated_cost_dollars=estimated_cost_dollars,
        enforcement_case_id=case["id"],
    )
    case = set_resolution_atf(case, app)
    return {"applicant": applicant, "site": site, "jd": jd, "case": case, "app": app}


def setup_issued_atf_permit(unauthorized_fill_acres=2.0,
                            buy_credits=9.0,
                            resource_type=DEFAULT_IMPACT_RESOURCE_TYPE,
                            impacts=None,
                            estimated_cost_dollars=750000.0) -> dict:
    """Full after-the-fact individual lifecycle through issuance (PRD §3.9,
    §3.7): the linked case closes RESOLUTION_PENDING -> CLOSED with the full
    accrued penalty (no good-faith offset on the ATF track). Default buy of
    9.0 credits covers the 9.00 ATF provisional requirement for 2.0
    FORESTED_WETLAND acres (2.0 * 3.0 * 1.5)."""
    ctx = setup_atf_application_linked(
        unauthorized_fill_acres, impacts, estimated_cost_dollars
    )
    applicant = ctx["applicant"]
    app = walk_application_to_alternatives_review(ctx["app"], applicant)
    ctx["app"] = app
    ctx = setup_aa_accepted(ctx)
    ctx = setup_application_public_notice_open(ctx)
    close_comment_period(ctx["app"])
    ctx["app"] = advance_to_decision(ctx["app"])
    ctx = setup_secured_bank_credits_plan(
        ctx, buy_credits=buy_credits, resource_type=resource_type
    )
    ctx["app"] = render_decision(ctx["app"])
    ctx["permit"] = get_permit_for_application(ctx["app"])
    ctx["reports"] = get_reports_for_permit(ctx["permit"])
    ctx["case"] = get_case(ctx["case"])
    return ctx
