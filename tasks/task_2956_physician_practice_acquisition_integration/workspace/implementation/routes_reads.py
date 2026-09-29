"""The twenty-four GET endpoints: one list and one read per collection."""

import enums
import envelope
import machines
import serialize
import store
import validate

FILTERS = {
    "acquisitions": {
        "deal_status": machines.DEAL_STATUS_VALUES,
        "compliance_clearance": machines.CLEARANCE_VALUES,
        "readiness_posture": enums.READINESS_POSTURES,
        "specialty": enums.SPECIALTIES,
        "structure": enums.STRUCTURES,
    },
    "physicians": {
        "acquisition_id": None,
        "employment_status": enums.EMPLOYMENT_STATUSES,
        "specialty": enums.SPECIALTIES,
        "board_certified": "bool",
    },
    "valuation_opinions": {
        "acquisition_id": None,
        "opinion_type": enums.OPINION_TYPES,
        "method": enums.VALUATION_METHODS,
        "status": machines.OPINION_STATUS_VALUES,
        "is_pinned": "bool",
    },
    "compensation_plans": {
        "acquisition_id": None,
        "physician_id": None,
        "status": machines.PLAN_STATUS_VALUES,
        "model_type": enums.MODEL_TYPES,
        "benchmark_basis": enums.BENCHMARK_BASES,
    },
    "payer_contracts": {
        "acquisition_id": None,
        "payer_type": enums.PAYER_TYPES,
        "payer_name": None,
        "novation_status": machines.NOVATION_VALUES,
        "contract_form": enums.CONTRACT_FORMS,
    },
    "credentialing_packages": {
        "acquisition_id": None,
        "physician_id": None,
        "payer_contract_id": None,
        "status": machines.PACKAGE_STATUS_VALUES,
        "committee_cycle_key": None,
        "retro_billing_allowed": "bool",
    },
    "ehr_migration_batches": {
        "acquisition_id": None,
        "status": machines.BATCH_STATUS_VALUES,
        "chart_type": enums.CHART_TYPES,
        "source_system": enums.SOURCE_SYSTEMS,
        "contains_minor_records": "bool",
    },
    "staff_transition_offers": {
        "acquisition_id": None,
        "status": machines.OFFER_STATUS_VALUES,
        "role_code": enums.ROLE_CODES,
        "wage_floor_applied": "bool",
    },
    "billing_conversions": {
        "acquisition_id": None,
        "status": machines.CONVERSION_STATUS_VALUES,
        "conversion_type": enums.CONVERSION_TYPES,
    },
    "readiness_tasks": {
        "acquisition_id": None,
        "status": machines.TASK_STATUS_VALUES,
        "task_code": enums.TASK_CODES,
        "domain": enums.TASK_DOMAINS,
        "is_blocking": "bool",
    },
    "liability_items": {
        "acquisition_id": None,
        "category": enums.LIABILITY_CATEGORIES,
        "disposition": machines.DISPOSITION_VALUES,
    },
    "performance_reports": {
        "acquisition_id": None,
        "physician_id": None,
        "applied_comp_plan_id": None,
        "period_start_on": None,
    },
}

# collection path -> (kind, roles)
COLLECTIONS = (
    ("/acquisitions", "acquisitions", enums.ROLES_ACQUISITION_READ, "acquisitionId"),
    ("/physicians", "physicians", enums.ROLES_PHYSICIAN_READ, "physicianId"),
    ("/valuation-opinions", "valuation_opinions", enums.ROLES_OPINION_READ, "opinionId"),
    ("/compensation-plans", "compensation_plans", enums.ROLES_PLAN_READ, "planId"),
    ("/payer-contracts", "payer_contracts", enums.ROLES_INTEGRATION_READ, "contractId"),
    ("/credentialing-packages", "credentialing_packages", enums.ROLES_PACKAGE_READ, "packageId"),
    ("/ehr-migration-batches", "ehr_migration_batches", enums.ROLES_INTEGRATION_READ, "batchId"),
    ("/staff-transition-offers", "staff_transition_offers", enums.ROLES_INTEGRATION_READ, "offerId"),
    ("/billing-conversions", "billing_conversions", enums.ROLES_INTEGRATION_READ, "conversionId"),
    ("/readiness-tasks", "readiness_tasks", enums.ROLES_INTEGRATION_READ, "taskId"),
    ("/liability-items", "liability_items", enums.ROLES_LIABILITY_READ, "itemId"),
    ("/performance-reports", "performance_reports", enums.ROLES_REPORT_READ, "reportId"),
)


def _make_list(kind, roles):
    spec = FILTERS[kind]

    def handler():
        validate.gate(roles)
        limit, offset = validate.pagination_args()
        criteria = validate.filters(spec)
        rows = store.ordered(store.where(kind, **criteria))
        page, pagination = envelope.paginate(rows, limit, offset)
        return envelope.array_response(serialize.dump_all(page), pagination)

    return handler


def _make_read(kind, roles):
    def handler(entity_id):
        validate.gate(roles)
        row = store.require(kind, entity_id)
        return envelope.object_response(serialize.dump(row))

    return handler


def register(app):
    for path, kind, roles, param in COLLECTIONS:
        app.add_url_rule(path, "list_" + kind, _make_list(kind, roles),
                         methods=["GET"])
        app.add_url_rule(path + "/<entity_id>", "read_" + kind,
                         _make_read(kind, roles), methods=["GET"])
