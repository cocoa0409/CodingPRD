"""Pigment batches, certification decisions, and the recall cascade (PRD 3.2)."""
from datetime import timedelta

from flask import request

from calculations import (
    classify_severity, recompute_spec, rerun_waterfall,
)
from constants import (
    OPS_ROLES, ROLE_QUALITY_ASSURANCE, ROLE_SOURCING_MANAGER,
)
from envelope import ok, paginate
from errors import ApiError
from store import STORE, fmt_dt
from validation import (
    apply_filters, auth, body, get_or_404, new_entity, opt_str, pagination_params,
    req_enum, req_num, req_str, require_role, touch,
)


def serialize_batch(b):
    return {
        "id": b["id"],
        "pigment_name": b["pigment_name"],
        "supplier_name": b["supplier_name"],
        "hazard_class": b["hazard_class"],
        "received_quantity_kg": b["received_quantity_kg"],
        "certification_mark": b["certification_mark"],
        "status": b["status"],
        "created_by_user_id": b["created_by_user_id"],
        "certified_by_user_id": b["certified_by_user_id"],
        "rejection_reason": b["rejection_reason"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_recall_case(case):
    return {
        "id": case["id"],
        "pigment_batch_id": case["pigment_batch_id"],
        "affected_run_count": case["affected_run_count"],
        "affected_units": case["affected_units"],
        "severity": case["severity"],
        "cooling_until": case["cooling_until"],
        "status": case["status"],
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "version": case["version"],
    }


def create_batch():
    user_id, role = auth()
    require_role(role, {ROLE_SOURCING_MANAGER, ROLE_QUALITY_ASSURANCE})
    data = body()
    pigment_name = req_str(data, "pigment_name")
    supplier_name = req_str(data, "supplier_name")
    hazard_class = req_enum(data, "hazard_class", ("STANDARD", "SENSITIVE", "RESTRICTED"))
    quantity = req_num(data, "received_quantity_kg")
    certification_mark = req_enum(data, "certification_mark", ("ACMI_AP", "ACMI_CL", "NONE"))
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "received_quantity_kg must be > 0")
    batch = new_entity({
        "pigment_name": pigment_name,
        "supplier_name": supplier_name,
        "hazard_class": hazard_class,
        "received_quantity_kg": quantity,
        "certification_mark": certification_mark,
        "status": "QUARANTINE",
        "created_by_user_id": user_id,
        "certified_by_user_id": None,
        "rejection_reason": None,
    })
    STORE.batches[batch["id"]] = batch
    return ok(serialize_batch(batch), status=201)


def get_batch(batch_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    batch = get_or_404(STORE.batches, batch_id)
    return ok(serialize_batch(batch))


def _short_committed_allocations(spec):
    """Recall shorting: COMMITTED -> SHORTED newest-first until committed demand
    fits the remaining non-quarantined lot supply (PRD section 3.2)."""
    lots = [lot for lot in STORE.lots.values()
            if STORE.runs[lot["production_run_id"]]["assortment_spec_id"] == spec["id"]]
    capacity = sum(lot["boxes_on_hand"] + lot["boxes_committed"]
                   for lot in lots if lot["status"] != "QUARANTINED")
    committed = [a for a in STORE.allocations.values()
                 if a["assortment_spec_id"] == spec["id"] and a["status"] == "COMMITTED"]
    committed.sort(key=lambda a: (a["created_at"], a["request_seq"]), reverse=True)
    demand = sum(a["allocated_boxes_final"] for a in committed)
    for alloc in committed:
        if demand <= capacity:
            break
        alloc["status"] = "SHORTED"
        touch(alloc)
        demand -= alloc["allocated_boxes_final"]


def apply_recall_cascade(batch):
    """Retro-rejection cascade: runs -> lots -> allocations -> licensed lines.

    Creates the RecallCase (OPEN) and returns it.
    """
    affected_run_count = 0
    affected_units = 0
    quarantined_color_ids = set()
    affected_spec_ids = set()
    consuming = [r for r in STORE.runs.values() if r["pigment_batch_id"] == batch["id"]]
    consuming.sort(key=lambda r: r["_seq"])
    for run in consuming:
        spec = STORE.specs[run["assortment_spec_id"]]
        if run["stage"] == "PLANNED":
            run["stage"] = "CANCELLED"
            touch(run)
            affected_run_count += 1
            affected_units += run["planned_boxes"] * spec["box_size"]
            affected_spec_ids.add(spec["id"])
        elif run["stage"] in ("MOLDING", "LABELING", "PACKING", "ON_HOLD"):
            run["stage"] = "QUARANTINED"
            touch(run)
            affected_run_count += 1
            affected_units += run["planned_boxes"] * spec["box_size"]
            affected_spec_ids.add(spec["id"])
            for entry in spec["entries"]:
                quarantined_color_ids.add(entry["color_id"])
        elif run["stage"] == "COMPLETED":
            run["stage"] = "QUARANTINED"
            touch(run)
            affected_run_count += 1
            affected_units += run["boxes_produced"] * spec["box_size"]
            affected_spec_ids.add(spec["id"])
            for entry in spec["entries"]:
                quarantined_color_ids.add(entry["color_id"])
            for lot in STORE.lots.values():
                if lot["production_run_id"] == run["id"] and lot["status"] != "QUARANTINED":
                    lot["status"] = "QUARANTINED"
                    touch(lot)
        # CANCELLED / QUARANTINED runs are already terminal: not affected.
    # Short committed allocations per affected spec, then reconcile + waterfall.
    for spec_id in affected_spec_ids:
        spec = STORE.specs[spec_id]
        recompute_spec(spec)
        _short_committed_allocations(spec)
        recompute_spec(spec)
        rerun_waterfall(spec)
    # Suspend APPROVED licensed lines whose formula color is on a quarantined run.
    for line in STORE.lines.values():
        if line["status"] != "APPROVED":
            continue
        formula = STORE.formulas.get(line["formula_id"])
        if formula is not None and formula["color_id"] in quarantined_color_ids:
            line["status"] = "SUSPENDED"
            touch(line)
    # Create the recall case itself.
    severity, cooling_days = classify_severity(affected_units, batch["hazard_class"])
    case = new_entity({
        "pigment_batch_id": batch["id"],
        "affected_run_count": affected_run_count,
        "affected_units": affected_units,
        "severity": severity,
        "cooling_until": fmt_dt(STORE.clock_dt + timedelta(days=cooling_days)),
        "status": "OPEN",
        "_affected_color_ids": sorted(quarantined_color_ids),
    })
    STORE.recall_cases[case["id"]] = case
    return case


def certification_decision(batch_id):
    user_id, role = auth()
    require_role(role, {ROLE_QUALITY_ASSURANCE})
    data = body()
    decision = req_enum(data, "decision", ("CERTIFY", "REJECT"))
    reason = opt_str(data, "reason")
    batch = get_or_404(STORE.batches, batch_id)
    # State gate (stage 6): REJECTED is terminal.
    if batch["status"] == "REJECTED":
        raise ApiError("ERR_BATCH_TERMINAL")
    if batch["status"] == "CERTIFIED" and decision == "CERTIFY":
        raise ApiError("ERR_BATCH_TERMINAL", "batch is already CERTIFIED")
    # Segregation of duties (stage 7): decider must not be the registrar.
    if user_id == batch["created_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")
    if decision == "CERTIFY":
        # Certification-mark rule (stage 7) for non-STANDARD hazard classes.
        if batch["hazard_class"] in ("SENSITIVE", "RESTRICTED") \
                and batch["certification_mark"] != "ACMI_AP":
            raise ApiError("ERR_CERTIFICATION_MARK_REQUIRED")
        batch["status"] = "CERTIFIED"
        batch["certified_by_user_id"] = user_id
        touch(batch)
    else:
        was_certified = batch["status"] == "CERTIFIED"
        batch["status"] = "REJECTED"
        batch["rejection_reason"] = reason
        touch(batch)
        if was_certified:
            consuming = [r for r in STORE.runs.values()
                         if r["pigment_batch_id"] == batch["id"]]
            if consuming:
                apply_recall_cascade(batch)
    return ok(serialize_batch(batch))


def list_recall_cases(batch_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    get_or_404(STORE.batches, batch_id)
    limit, offset = pagination_params()
    items = [c for c in STORE.recall_cases.values() if c["pigment_batch_id"] == batch_id]
    items = apply_filters(items, [("status", request.args.get("status"))])
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_recall_case(c) for c in page], response_type="array", pagination=meta)


def register(app):
    app.add_url_rule("/crayon-works/pigment-batches", view_func=create_batch, methods=["POST"])
    app.add_url_rule("/crayon-works/pigment-batches/<batch_id>", view_func=get_batch, methods=["GET"])
    app.add_url_rule("/crayon-works/pigment-batches/<batch_id>/certification-decision",
                     view_func=certification_decision, methods=["POST"])
    app.add_url_rule("/crayon-works/pigment-batches/<batch_id>/recall-cases",
                     view_func=list_recall_cases, methods=["GET"])
