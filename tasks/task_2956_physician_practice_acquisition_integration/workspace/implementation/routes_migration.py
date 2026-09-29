"""POST /ehr-migration-batches and the progress action (PRD section 3.7)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

TERMINAL_BATCH_STATES = ("RECONCILED", "ABORTED")


def create_batch():
    validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    batch_label = validate.req_str(body, "batch_label")
    source_system = validate.req_enum(body, "source_system", enums.SOURCE_SYSTEMS)
    chart_type = validate.req_enum(body, "chart_type", enums.CHART_TYPES)
    record_count = validate.req_int(body, "record_count", minimum=0)
    contains_minor = validate.opt_bool(body, "contains_minor_records", False)
    youngest = validate.opt_int(body, "youngest_patient_age_years", None,
                                minimum=0, maximum=17)
    last_encounter_on = validate.req_date(body, "last_encounter_on")

    # Rank 3 intra-body constraint.
    if contains_minor and youngest is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "youngest_patient_age_years is required when "
                       "contains_minor_records is true.")

    # Rank 5, then rank 9, then rank 15.
    acquisition = store.require("acquisitions", acquisition_id)
    for peer in store.where("ehr_migration_batches",
                            acquisition_id=acquisition_id,
                            batch_label=batch_label):
        raise ApiError("ERR_DUPLICATE_BATCH_LABEL",
                       "Batch label '%s' already exists on this acquisition."
                       % batch_label)
    services.check_freeze(acquisition)

    retention_years = calc.legacy_retention_years(chart_type, contains_minor,
                                                  youngest)
    row = {
        "acquisition_id": acquisition_id,
        "batch_label": batch_label,
        "source_system": source_system,
        "chart_type": chart_type,
        "record_count": record_count,
        "contains_minor_records": contains_minor,
        "youngest_patient_age_years": youngest,
        "last_encounter_on": clock.format_date(last_encounter_on),
        "validated_count": 0,
        "defect_count": 0,
        "unprocessed_count": record_count,
        "match_rate_bps": 0,
        "retention_years": retention_years,
        "legacy_purge_eligible_on": clock.format_date(
            calc.legacy_purge_eligible_on(last_encounter_on, retention_years)),
        "retry_count": 0,
        "status": "STAGED",
    }
    store.insert("ehr_migration_batches", row)
    return services.respond_created(row)


def batch_progress(entity_id):
    user_id, role = validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    action = validate.req_enum(body, "action", machines.BATCH_ACTIONS)
    validated_count = validate.opt_int(body, "validated_count", 0, minimum=0)
    defect_count = validate.opt_int(body, "defect_count", 0, minimum=0)
    note = validate.opt_str(body, "note")

    batch = store.require("ehr_migration_batches", entity_id)
    acquisition = store.require("acquisitions", batch["acquisition_id"])
    from_state = batch["status"]

    # Rank 14, then rank 15.
    machines.resolve(machines.BATCH_STATUS, from_state, action, role)
    services.check_freeze(acquisition)

    if action == "EXTRACT":
        # Rank 27.
        if batch["record_count"] <= 0:
            raise ApiError("ERR_EMPTY_MIGRATION_BATCH",
                           "An empty batch has no defined match rate and cannot "
                           "be extracted.")
        set_field(batch, "status", "EXTRACTED")
    elif action == "LOAD":
        set_field(batch, "status", "LOADED")
    elif action == "RECONCILE":
        _reconcile(batch, acquisition, validated_count, defect_count, note)
    elif action == "REQUEUE":
        set_field(batch, "status", "STAGED")
        set_field(batch, "validated_count", 0)
        set_field(batch, "defect_count", 0)
        set_field(batch, "unprocessed_count", batch["record_count"])
        set_field(batch, "match_rate_bps", 0)
    elif action == "ABORT":
        set_field(batch, "status", "ABORTED")
        services.recompute_posture(acquisition)

    return services.respond(batch)


def _reconcile(batch, acquisition, validated_count, defect_count, note):
    # Rank 28: conservation is enforced on input.
    if validated_count + defect_count > batch["record_count"]:
        raise ApiError("ERR_MIGRATION_COUNT_INVALID",
                       "validated_count plus defect_count exceeds record_count.")

    rate = calc.ehr_match_rate_bps(validated_count, batch["record_count"])
    set_field(batch, "validated_count", validated_count)
    set_field(batch, "defect_count", defect_count)
    set_field(batch, "unprocessed_count",
              batch["record_count"] - validated_count - defect_count)
    set_field(batch, "match_rate_bps", rate)

    if rate >= calc.RECONCILE_MIN_BPS:
        set_field(batch, "status", "RECONCILED")
        peers = store.where("ehr_migration_batches",
                            acquisition_id=acquisition["id"])
        if all(p["status"] in TERMINAL_BATCH_STATES for p in peers):
            services.cascade_complete_task(acquisition, "IT_DATA_MIGRATION")
        services.recompute_posture(acquisition)
    elif batch["retry_count"] < calc.MAX_MIGRATION_RETRIES:
        set_field(batch, "status", "FAILED")
        set_field(batch, "retry_count", batch["retry_count"] + 1)
    else:
        set_field(batch, "status", "ABORTED")
        set_field(batch, "retry_count", batch["retry_count"] + 1)
        reason = note if note else (
            "Reconciliation match rate %d bps is below the %d bps floor."
            % (rate, calc.RECONCILE_MIN_BPS))
        services.cascade_fail_task(acquisition, "IT_DATA_MIGRATION", reason)
        services.recompute_posture(acquisition)


def register(app):
    app.add_url_rule("/ehr-migration-batches", "create_batch", create_batch,
                     methods=["POST"])
    app.add_url_rule("/ehr-migration-batches/<entity_id>/progress",
                     "batch_progress", batch_progress, methods=["POST"])
