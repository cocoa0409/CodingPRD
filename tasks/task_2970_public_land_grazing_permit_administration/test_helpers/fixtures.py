"""Composite setup helpers — multi-step PRD workflow preambles.

Every helper uses get_success_data() so a setup failure surfaces as a clear
"Setup step failed" assertion rather than a confusing downstream error.

Composite helpers are phased so that a second call never invalidates its own
first hop: helpers that consume a (permit, grazing_year) or (allotment,
assessment_year) slot take that slot as a parameter.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from . import factories as f
from .test_users import (
    make_adjudicator_headers,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
    make_system_admin_headers,
    OFFICER_1,
    SPECIALIST_1,
)

# --- Tier 1: single-call creates -------------------------------------------


def set_clock(current_utc):
    return get_success_data(api_client.set_clock(f.clock_payload(current_utc),
                                                make_system_admin_headers()))


def create_allotment(**overrides):
    return get_success_data(api_client.create_allotment(
        f.allotment_payload(**overrides), make_officer_headers()))


def create_pasture(allotment_id, **overrides):
    return get_success_data(api_client.create_pasture(
        allotment_id, f.pasture_payload(**overrides), make_officer_headers()))


def create_permittee(**overrides):
    return get_success_data(api_client.create_permittee(
        f.permittee_payload(**overrides), make_officer_headers()))


def create_base_property(permittee_id, **overrides):
    return get_success_data(api_client.create_base_property(
        permittee_id, f.base_property_payload(**overrides), make_officer_headers()))


def create_permit(allotment_id, permittee_id, base_property_id, **overrides):
    return get_success_data(api_client.create_permit(
        f.permit_payload(allotment_id, permittee_id, base_property_id, **overrides),
        make_officer_headers()))


def issue_permit(permit_id):
    return get_success_data(api_client.issue_permit(permit_id, make_officer_headers()))


def create_aoi(permit_id, **overrides):
    return get_success_data(api_client.create_aoi(
        f.aoi_payload(permit_id, **overrides), make_specialist_headers()))


def add_use_record(aoi_id, pasture_id, **overrides):
    return get_success_data(api_client.create_use_record(
        aoi_id, f.use_record_payload(pasture_id, **overrides), make_specialist_headers()))


def issue_aoi(aoi_id):
    return get_success_data(api_client.issue_aoi(aoi_id, make_officer_headers()))


def approve_nonuse(aoi_id, nonuse_aums, nonuse_reason="RESOURCE_CONSERVATION"):
    return get_success_data(api_client.approve_nonuse(
        aoi_id, f.nonuse_payload(nonuse_aums, nonuse_reason), make_officer_headers()))


def report_actual_use(use_record_id, **overrides):
    return get_success_data(api_client.report_actual_use(
        use_record_id, f.report_actual_use_payload(**overrides), make_specialist_headers()))


def accept_use_report(aoi_id):
    return get_success_data(api_client.accept_use_report(aoi_id, make_officer_headers()))


def void_aoi(aoi_id, void_reason="Permittee withdrew the grazing application for the year."):
    return get_success_data(api_client.void_aoi(
        aoi_id, f.void_payload(void_reason), make_officer_headers()))


def create_closure_order(allotment_id, **overrides):
    return get_success_data(api_client.create_closure_order(
        f.closure_order_payload(allotment_id, **overrides), make_officer_headers()))


def lift_closure_order(closure_order_id):
    return get_success_data(api_client.lift_closure_order(
        closure_order_id, f.lift_payload(), make_officer_headers()))


def create_trespass_incident(allotment_id, permittee_id=None, **overrides):
    return get_success_data(api_client.create_trespass_incident(
        f.trespass_payload(allotment_id, permittee_id, **overrides), make_specialist_headers()))


def bill_trespass_incident(incident_id):
    return get_success_data(api_client.bill_trespass_incident(incident_id, make_officer_headers()))


def create_project(allotment_id, **overrides):
    return get_success_data(api_client.create_project(
        f.project_payload(allotment_id, **overrides), make_specialist_headers()))


def approve_project(project_id):
    return get_success_data(api_client.approve_project(project_id, make_officer_headers()))


def allocate_cost_share(project_id):
    return get_success_data(api_client.allocate_cost_share(project_id, make_officer_headers()))


def void_bill(bill_id, void_reason="Bill recorded in error during administrative review."):
    return get_success_data(api_client.void_bill(
        bill_id, f.void_payload(void_reason), make_officer_headers()))


def pay_bill(bill_id, amount_cents):
    return get_success_data(api_client.record_payment(
        bill_id, f.payment_payload(amount_cents), make_officer_headers()), 201)


# --- Tier 1 reads ----------------------------------------------------------


def get_allotment(allotment_id):
    return get_success_data(api_client.get_allotment(allotment_id, make_officer_headers()))


def get_pasture(pasture_id):
    return get_success_data(api_client.get_pasture(pasture_id, make_officer_headers()))


def get_permittee(permittee_id):
    return get_success_data(api_client.get_permittee(permittee_id, make_officer_headers()))


def get_base_property(base_property_id):
    return get_success_data(api_client.get_base_property(base_property_id, make_officer_headers()))


def get_permit(permit_id):
    return get_success_data(api_client.get_permit(permit_id, make_officer_headers()))


def get_aoi(aoi_id):
    return get_success_data(api_client.get_aoi(aoi_id, make_officer_headers()))


def get_use_record(use_record_id):
    return get_success_data(api_client.get_use_record(use_record_id, make_officer_headers()))


def get_bill(bill_id):
    return get_success_data(api_client.get_bill(bill_id, make_officer_headers()))


def get_assessment(assessment_id):
    return get_success_data(api_client.get_assessment(assessment_id, make_officer_headers()))


def get_decision(decision_id):
    return get_success_data(api_client.get_decision(decision_id, make_officer_headers()))


def get_appeal(appeal_id):
    return get_success_data(api_client.get_appeal(appeal_id, make_officer_headers()))


def get_closure_order(closure_order_id):
    return get_success_data(api_client.get_closure_order(closure_order_id, make_officer_headers()))


def get_trespass_incident(incident_id):
    return get_success_data(api_client.get_trespass_incident(incident_id, make_officer_headers()))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, make_officer_headers()))


def list_bills(**filters):
    """Bills matching the filters, in created_at ascending order (PRD 2.3)."""
    params = dict(filters)
    params.setdefault("limit", 100)
    items, _meta = validate_paginated(api_client.list_bills(make_officer_headers(), params))
    return items


def bill_of_type(bill_type, **filters):
    """The single non-voided bill of a given type matching the filters."""
    matches = [b for b in list_bills(bill_type=bill_type, **filters)]
    assert matches, "Setup step failed: no %s bill found for %r" % (bill_type, filters)
    return matches[-1]


# --- Tier 2: entity pairs ---------------------------------------------------


def allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                           required_pasture_rotation_count=1, pasture_overrides=None,
                           **allotment_overrides):
    """An allotment plus one pasture at sequence_order 1."""
    allotment = create_allotment(
        total_permitted_aums=total_permitted_aums,
        required_pasture_rotation_count=required_pasture_rotation_count,
        **allotment_overrides)
    pasture = create_pasture(
        allotment["id"], pasture_aum_capacity=pasture_aum_capacity, sequence_order=1,
        **(pasture_overrides or {}))
    return {"allotment": allotment, "pasture": pasture}


def permittee_with_base_property(carrying_capacity_aums=600, base_property_type="LAND",
                                 **permittee_overrides):
    """A permittee plus one qualifying base property."""
    permittee = create_permittee(**permittee_overrides)
    base_property = create_base_property(
        permittee["id"], base_property_type=base_property_type,
        carrying_capacity_aums=carrying_capacity_aums)
    return {"permittee": permittee, "base_property": base_property}


# --- Tier 3: the permit ladder ----------------------------------------------


def issued_permit_setup(total_permitted_aums=1200, pasture_aum_capacity=300,
                        required_pasture_rotation_count=1, carrying_capacity_aums=600,
                        base_property_type="LAND", requested_aums=300,
                        livestock_kind="CATTLE", term_start_date="2026-01-01",
                        term_end_date="2030-12-31", allotment_overrides=None,
                        pasture_overrides=None):
    """Allotment + pasture + permittee + base property + an ISSUED permit."""
    land = allotment_with_pasture(
        total_permitted_aums=total_permitted_aums,
        pasture_aum_capacity=pasture_aum_capacity,
        required_pasture_rotation_count=required_pasture_rotation_count,
        pasture_overrides=pasture_overrides,
        **(allotment_overrides or {}))
    holder = permittee_with_base_property(
        carrying_capacity_aums=carrying_capacity_aums, base_property_type=base_property_type)
    permit = create_permit(
        land["allotment"]["id"], holder["permittee"]["id"], holder["base_property"]["id"],
        requested_aums=requested_aums, livestock_kind=livestock_kind,
        term_start_date=term_start_date, term_end_date=term_end_date)
    permit = issue_permit(permit["id"])
    return {
        "allotment": get_allotment(land["allotment"]["id"]),
        "pasture": land["pasture"],
        "permittee": holder["permittee"],
        "base_property": holder["base_property"],
        "permit": permit,
    }


def drafted_aoi_setup(authorized_aums=300, grazing_year=2026, planned_head_count=100,
                      planned_entry_date="2026-04-01", planned_exit_date="2026-05-01",
                      aoi_overrides=None, use_record_overrides=None, **ladder_overrides):
    """The permit ladder plus a DRAFT instruction carrying one scheduled leg."""
    setup = issued_permit_setup(**ladder_overrides)
    aoi = create_aoi(setup["permit"]["id"], grazing_year=grazing_year,
                     authorized_aums=authorized_aums, **(aoi_overrides or {}))
    use_record = add_use_record(
        aoi["id"], setup["pasture"]["id"], planned_head_count=planned_head_count,
        planned_entry_date=planned_entry_date, planned_exit_date=planned_exit_date,
        livestock_kind=setup["permit"]["livestock_kind"], **(use_record_overrides or {}))
    setup["aoi"] = get_aoi(aoi["id"])
    setup["use_record"] = use_record
    return setup


def issued_aoi_setup(**overrides):
    """The permit ladder plus an ISSUED instruction and its preliminary bill."""
    setup = drafted_aoi_setup(**overrides)
    setup["aoi"] = issue_aoi(setup["aoi"]["id"])
    setup["allotment"] = get_allotment(setup["allotment"]["id"])
    bills = list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE")
    setup["preliminary_bill"] = bills[-1] if bills else None
    return setup


# --- Tier 4: monitoring, decisions and appeals ------------------------------


def finalized_assessment(allotment_id, assessment_year=2026, upland_score=80,
                         riparian_score=80, water_quality_score=80,
                         monitoring_method="INDICATOR_ASSESSMENT",
                         author_user_id=SPECIALIST_1, reviewer_user_id=OFFICER_1,
                         **assessment_overrides):
    """Create, submit and CONCUR-review an assessment so it reaches FINALIZED.

    PRD 3.8 requires a STOCKING_ADJUSTMENT decision to name a finalized
    assessment, and PRD 2.10 requires the reviewer's X-User-ID to differ from
    the author's, so the two identifiers are separate parameters.
    """
    assessment = get_success_data(api_client.create_assessment(
        f.assessment_payload(
            allotment_id, assessment_year=assessment_year, upland_score=upland_score,
            riparian_score=riparian_score, water_quality_score=water_quality_score,
            monitoring_method=monitoring_method, **assessment_overrides),
        make_specialist_headers(author_user_id)))
    get_success_data(api_client.submit_assessment(
        assessment["id"], make_specialist_headers(author_user_id)))
    return get_success_data(api_client.review_assessment(
        assessment["id"], f.review_payload("CONCUR"), make_officer_headers(reviewer_user_id)))


def remanded_assessment(allotment_id, assessment_year=2026, author_user_id=SPECIALIST_1,
                        reviewer_user_id=OFFICER_1, **assessment_overrides):
    """An assessment returned to DRAFT once by a REMAND review."""
    assessment = get_success_data(api_client.create_assessment(
        f.assessment_payload(allotment_id, assessment_year=assessment_year,
                             **assessment_overrides),
        make_specialist_headers(author_user_id)))
    get_success_data(api_client.submit_assessment(
        assessment["id"], make_specialist_headers(author_user_id)))
    return get_success_data(api_client.review_assessment(
        assessment["id"], f.review_payload("REMAND"), make_officer_headers(reviewer_user_id)))


def authored_decision(allotment_id, decision_type="ISSUANCE", author_user_id=SPECIALIST_1,
                      expected_allotment_version=None, **decision_overrides):
    """A DRAFT decision authored against the allotment's current version."""
    if expected_allotment_version is None:
        expected_allotment_version = get_allotment(allotment_id)["version"]
    return get_success_data(api_client.create_decision(
        f.decision_payload(allotment_id, expected_allotment_version,
                           decision_type=decision_type, **decision_overrides),
        make_specialist_headers(author_user_id)))


def proposed_decision(allotment_id, **overrides):
    """A decision carried through environmental review into PROPOSED."""
    author_user_id = overrides.pop("author_user_id", SPECIALIST_1)
    decision = authored_decision(allotment_id, author_user_id=author_user_id, **overrides)
    return get_success_data(api_client.complete_environmental_review(
        decision["id"], f.environmental_review_payload(),
        make_specialist_headers(author_user_id)))


def signed_decision(allotment_id, signer_user_id=OFFICER_1, **overrides):
    """A decision signed into decision_status FINAL by an officer who is not its author."""
    decision = proposed_decision(allotment_id, **overrides)
    return get_success_data(api_client.finalize_decision(
        decision["id"], f.finalize_payload(), make_officer_headers(signer_user_id)))


def effective_decision(allotment_id, signer_user_id=OFFICER_1, **overrides):
    """A decision put into effect by the same officer who signed it (PRD 2.10)."""
    decision = signed_decision(allotment_id, signer_user_id=signer_user_id, **overrides)
    return get_success_data(api_client.make_decision_effective(
        decision["id"], make_officer_headers(signer_user_id)))


def effective_stocking_adjustment(allotment_id, adjustment_pct, assessment_id=None,
                                  assessment_year=2026, signer_user_id=OFFICER_1,
                                  author_user_id=SPECIALIST_1, nepa_level="CX"):
    """A STOCKING_ADJUSTMENT decision in EFFECTIVE, with its justifying assessment.

    The assessment is scored 80/80/80 so its determination is MEETING and the
    rangeland standards gate of PRD 2.6 priority 10 stays open. The allotment
    version is re-read after finalization because concurrence bumps it.
    """
    if assessment_id is None:
        assessment_id = finalized_assessment(
            allotment_id, assessment_year=assessment_year,
            author_user_id=author_user_id,
            reviewer_user_id=(OFFICER_1 if signer_user_id != OFFICER_1 else signer_user_id))["id"]
    return effective_decision(
        allotment_id, decision_type="STOCKING_ADJUSTMENT", assessment_id=assessment_id,
        adjustment_pct=adjustment_pct, nepa_level=nepa_level,
        author_user_id=author_user_id, signer_user_id=signer_user_id)


def filed_appeal(decision_id, appellant_permittee_id, stay_requested=False, **overrides):
    """An appeal filed by the affected permittee itself (PRD 3.9)."""
    return get_success_data(api_client.file_appeal(
        decision_id, f.appeal_payload(appellant_permittee_id, stay_requested, **overrides),
        make_permittee_headers(appellant_permittee_id)), 201)


def docketed_appeal(decision_id, appellant_permittee_id, stay_requested=False,
                    adjudicator_user_id=None, **overrides):
    """An appeal taken up by an adjudicator, so appeal_status is UNDER_REVIEW."""
    appeal = filed_appeal(decision_id, appellant_permittee_id, stay_requested, **overrides)
    headers = (make_adjudicator_headers(adjudicator_user_id) if adjudicator_user_id
               else make_adjudicator_headers())
    return get_success_data(api_client.docket_appeal(appeal["id"], headers))


def decide_appeal(appeal_id, appeal_outcome, adjudicator_user_id=None):
    headers = (make_adjudicator_headers(adjudicator_user_id) if adjudicator_user_id
               else make_adjudicator_headers())
    return get_success_data(api_client.decide_appeal(
        appeal_id, f.appeal_decision_payload(appeal_outcome), headers))
