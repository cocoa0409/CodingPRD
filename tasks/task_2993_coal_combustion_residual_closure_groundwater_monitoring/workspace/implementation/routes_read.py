"""All read endpoints (PRD 1.5 reads)."""
from flask import Blueprint

import calc
import common
import derive
import envelope
import store
from guards import authenticate

bp = Blueprint("reads", __name__)

STAFF = ("UtilityAdmin", "ComplianceOfficer", "Regulator")
UNIT_READERS = STAFF + ("ProfessionalEngineer", "Hydrogeologist",
                        "StatisticalReviewer")
MONITORING_READERS = STAFF + ("Hydrogeologist", "StatisticalReviewer")
STATS_READERS = STAFF + ("StatisticalReviewer", "Hydrogeologist")
ENGINEER_READERS = STAFF + ("ProfessionalEngineer",)
PUBLIC_READERS = STAFF + ("PublicViewer",)


def _page(rows, serializer):
    limit, offset = envelope.page_params()
    return envelope.listing(store.ordered(rows), limit, offset, serializer)


# ------------------------------------------------------------------- units
@bp.get("/ccr/units/<unit_id>")
def get_unit(unit_id):
    authenticate(UNIT_READERS)
    return envelope.ok(derive.unit(common.get_unit(unit_id)))


@bp.get("/ccr/units")
def list_units():
    authenticate(UNIT_READERS)
    limit, offset = envelope.page_params()
    rows = list(store.units.values())
    for row in rows:
        derive.refresh_unit(row)
    rows = common.apply_filters(rows, ("plant_code", "unit_type", "closure_state",
                                       "compliance_posture",
                                       "monitoring_program_id"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.unit)


@bp.get("/ccr/units/<unit_id>/compliance-summary")
def compliance_summary(unit_id):
    authenticate(("UtilityAdmin", "ComplianceOfficer", "Regulator",
                  "PublicViewer"))
    unit = common.get_unit(unit_id)
    derive.refresh_unit(unit)
    program = calc.unit_program(unit["id"])
    if program is not None:
        derive.refresh_program(program)
    plan = common.approved_plan(unit["id"])
    open_ssi = len([e for e in store.statistical_evaluations.values()
                    if e["program_id"] == (program["id"] if program else None)
                    and e["verdict"] in ("SSI", "SSL_EXCEEDANCE")
                    and e["status"] != "ASD_ACCEPTED"])
    return envelope.ok({
        "unit_id": unit["id"],
        "unit_code": unit["unit_code"],
        "closure_state": unit["closure_state"],
        "cap_integrity_state": unit["cap_integrity_state"],
        "compliance_posture": unit["compliance_posture"],
        "location_restriction_verdict": unit["location_restriction_verdict"],
        "governing_stability_verdict": unit["governing_stability_verdict"],
        "monitoring_phase": program["phase"] if program else None,
        "sampling_frequency": program["sampling_frequency"] if program else None,
        "next_sampling_due_date": (program["next_sampling_due_date"]
                                   if program else None),
        "open_ssi_count": open_ssi,
        "closure_deadline_date": unit["closure_deadline_date"],
        "granted_extension_months": unit["granted_extension_months"],
        "post_closure_care_end_date": unit["post_closure_care_end_date"],
        "ash_in_place_tons": unit["ash_in_place_tons"],
        "in_place_pv_usd_cents": plan["in_place_pv_usd_cents"] if plan else None,
        "removal_pv_usd_cents": plan["removal_pv_usd_cents"] if plan else None,
        "in_place_nominal_usd_cents": (plan["in_place_nominal_usd_cents"]
                                       if plan else None),
        "removal_nominal_usd_cents": (plan["removal_nominal_usd_cents"]
                                      if plan else None),
        "recommended_method": plan["recommended_method"] if plan else None,
        "overdue_posting_types": unit["overdue_posting_types"],
        "late_posting_count": unit["late_posting_count"],
        "ash_mass_balance_ok": unit["ash_mass_balance_ok"],
    })


# ----------------------------------------------------------- professionals
@bp.get("/ccr/professionals/<professional_id>")
def get_professional(professional_id):
    authenticate(STAFF)
    return envelope.ok(derive.professional(
        common.get_body_professional(professional_id)))


@bp.get("/ccr/professionals")
def list_professionals():
    authenticate(STAFF)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.professionals.values(),
                                ("discipline", "license_state", "license_status"))
    return envelope.listing(store.ordered(rows), limit, offset,
                            derive.professional)


# ------------------------------------------------------- stability assessments
@bp.get("/ccr/stability-assessments/<record_id>")
def get_stability(record_id):
    authenticate(ENGINEER_READERS)
    record = store.stability_assessments.get(record_id)
    if record is None:
        common.get_unit(record_id)
    return envelope.ok(derive.stability(record))


@bp.get("/ccr/stability-assessments")
def list_stability():
    authenticate(ENGINEER_READERS)
    limit, offset = envelope.page_params()
    for unit in store.units.values():
        calc.governing_stability_verdict(unit["id"])
    rows = common.apply_filters(store.stability_assessments.values(),
                                ("unit_id", "certifying_professional_id",
                                 "verdict"),
                                ("superseded",))
    return envelope.listing(store.ordered(rows), limit, offset, derive.stability)


# ------------------------------------------------------------------- wells
@bp.get("/ccr/wells/<well_id>")
def get_well(well_id):
    authenticate(MONITORING_READERS)
    return envelope.ok(derive.well(common.get_well(well_id)))


@bp.get("/ccr/wells")
def list_wells():
    authenticate(MONITORING_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.wells.values(),
                                ("unit_id", "well_role", "well_status"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.well)


# ------------------------------------------------------- monitoring programs
@bp.get("/ccr/monitoring-programs/<program_id>")
def get_program(program_id):
    authenticate(MONITORING_READERS)
    return envelope.ok(derive.program(common.get_program(program_id)))


@bp.get("/ccr/monitoring-programs")
def list_programs():
    authenticate(MONITORING_READERS)
    limit, offset = envelope.page_params()
    rows = list(store.programs.values())
    for row in rows:
        derive.refresh_program(row)
    rows = common.apply_filters(rows, ("unit_id", "phase", "network_certified_by",
                                       "last_validated_event_id"),
                               ("network_certified",))
    return envelope.listing(store.ordered(rows), limit, offset, derive.program)


# ---------------------------------------------------------- sampling events
@bp.get("/ccr/sampling-events/<event_id>")
def get_event(event_id):
    authenticate(MONITORING_READERS)
    return envelope.ok(derive.event(common.get_event(event_id)))


@bp.get("/ccr/sampling-events")
def list_events():
    authenticate(MONITORING_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.sampling_events.values(),
                                ("program_id", "submitted_by_professional_id",
                                 "status", "event_type"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.event)


# -------------------------------------------------------- analytical results
@bp.get("/ccr/analytical-results/<result_id>")
def get_result(result_id):
    authenticate(MONITORING_READERS)
    return envelope.ok(derive.result(common.get_result(result_id)))


@bp.get("/ccr/analytical-results")
def list_results():
    authenticate(MONITORING_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.analytical_results.values(),
                                ("sampling_event_id", "well_id",
                                 "parameter_code", "detection_flag"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.result)


# --------------------------------------------------- statistical evaluations
@bp.get("/ccr/statistical-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    authenticate(STATS_READERS)
    return envelope.ok(derive.evaluation(common.get_evaluation(evaluation_id)))


@bp.get("/ccr/statistical-evaluations")
def list_evaluations():
    authenticate(STATS_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(
        store.statistical_evaluations.values(),
        ("program_id", "compliance_well_id", "reviewing_professional_id",
         "asd_certifying_professional_id", "comparison_source_event_id",
         "verdict", "status"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.evaluation)


# ------------------------------------------------------------- closure plans
@bp.get("/ccr/closure-plans/<plan_id>")
def get_plan(plan_id):
    authenticate(ENGINEER_READERS)
    return envelope.ok(derive.plan(common.get_plan(plan_id)))


@bp.get("/ccr/closure-plans")
def list_plans():
    authenticate(ENGINEER_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.closure_plans.values(),
                                ("unit_id", "engineering_certified_by",
                                 "cost_certified_by", "status",
                                 "selected_method"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.plan)


# -------------------------------------------------------- extension requests
@bp.get("/ccr/extension-requests/<request_id>")
def get_extension(request_id):
    authenticate(STAFF)
    return envelope.ok(derive.extension(common.get_extension(request_id)))


@bp.get("/ccr/extension-requests")
def list_extensions():
    authenticate(STAFF)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.extension_requests.values(),
                                ("unit_id", "status", "justification_category"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.extension)


# ----------------------------------------------------------- reuse agreements
@bp.get("/ccr/reuse-agreements/<agreement_id>")
def get_agreement(agreement_id):
    authenticate(ENGINEER_READERS)
    return envelope.ok(derive.agreement(common.get_agreement(agreement_id)))


@bp.get("/ccr/reuse-agreements")
def list_agreements():
    authenticate(ENGINEER_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.reuse_agreements.values(),
                                ("unit_id", "qualified_by", "status",
                                 "product_type"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.agreement)


# ------------------------------------------------------------ reuse shipments
@bp.get("/ccr/reuse-shipments/<shipment_id>")
def get_shipment(shipment_id):
    authenticate(STAFF)
    return envelope.ok(derive.shipment(common.get_shipment(shipment_id)))


@bp.get("/ccr/reuse-shipments")
def list_shipments():
    authenticate(STAFF)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.reuse_shipments.values(),
                                ("agreement_id", "status"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.shipment)


# ------------------------------------------------------------ cap inspections
@bp.get("/ccr/cap-inspections/<inspection_id>")
def get_inspection(inspection_id):
    authenticate(ENGINEER_READERS)
    record = store.cap_inspections.get(inspection_id)
    if record is None:
        common.get_unit(inspection_id)
    return envelope.ok(derive.inspection(record))


@bp.get("/ccr/cap-inspections")
def list_inspections():
    authenticate(ENGINEER_READERS)
    limit, offset = envelope.page_params()
    rows = common.apply_filters(store.cap_inspections.values(),
                                ("unit_id", "inspecting_professional_id",
                                 "verdict"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.inspection)


# ------------------------------------------------------------ public postings
@bp.get("/ccr/public-postings/<posting_id>")
def get_posting(posting_id):
    authenticate(PUBLIC_READERS)
    return envelope.ok(derive.posting(common.get_posting(posting_id)))


@bp.get("/ccr/public-postings")
def list_postings():
    authenticate(PUBLIC_READERS)
    limit, offset = envelope.page_params()
    for unit in store.units.values():
        calc.refresh_postings(unit)
    rows = common.apply_filters(store.public_postings.values(),
                                ("unit_id", "posting_type", "status"))
    return envelope.listing(store.ordered(rows), limit, offset, derive.posting)
