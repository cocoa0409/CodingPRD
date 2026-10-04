"""Field-delivery services: measurements, reconciliations, claims, determinations."""

import calc
import db
from errors import ApiError
from services import get_project
from util import dec, parse_iso

DETERMINATION_TYPES = ("TIME_EXTENSION", "COST_EQUITABLE_ADJUSTMENT", "QUANTITY_ADJUSTMENT",
                       "REJECTED")
OPEN_CLAIM_STATUSES = ("REPORTED", "DOCUMENTED", "UNDER_REVIEW")


# ---------------------------------------------------------------------------
# ProgressMeasurement
# ---------------------------------------------------------------------------

def create_measurement(item, payload):
    quantity = payload.get("measured_quantity")
    if quantity is None or isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "measured_quantity is required.", 400)
    quantity = dec(quantity)
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "measured_quantity must be strictly greater than zero.", 400)
    measured_at = parse_iso(payload.get("measured_at"))

    expected = payload.get("expected_bid_item_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_bid_item_version is required.", 400)
    if expected != item["version"]:
        raise ApiError("ERR_STALE_BID_ITEM_VERSION",
                       "The pay item has moved on since version %s was observed." % expected, 412)

    record = db.create("measurement", {
        "bid_item_id": item["id"],
        "measured_quantity": float(quantity),
        "measured_at": measured_at,
        "measurement_status": "DRAFT",
        "applied_unit_price_cents": 0,
        "payable_amount_cents": 0,
    })
    db.touch(item)
    return record


def approve_measurement(measurement):
    item = db.find("bid_item", measurement["bid_item_id"])
    if measurement["measurement_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT measurement may be approved.", 409)
    if item is None or item["item_status"] != "ACTIVE":
        raise ApiError("ERR_ITEM_NOT_ACTIVE",
                       "The measurement's pay item is not in ACTIVE status.", 409)

    measurement["measurement_status"] = "APPROVED"
    calc.recalc_item(item)
    rate = calc.applied_rate_cents(item)
    measurement["applied_unit_price_cents"] = rate
    measurement["payable_amount_cents"] = calc.payable_amount_cents(measurement, rate)
    db.touch(measurement)

    project = get_project(item["project_id"])
    calc.refresh_reconciliation(project)
    db.touch(project)
    return measurement


def pay_measurement(measurement):
    item = db.find("bid_item", measurement["bid_item_id"])
    if measurement["measurement_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED measurement may be marked payable.", 409)
    project = get_project(item["project_id"]) if item else None
    reconciliation = calc.non_closed_reconciliation(project) if project else None
    if reconciliation is not None and reconciliation["reconciliation_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "The reconciliation is no longer OPEN; no new money may be added.", 409)

    measurement["measurement_status"] = "PAYABLE"
    db.touch(measurement)
    if project is not None:
        calc.refresh_reconciliation(project)
        db.touch(project)
    return measurement


def void_measurement(measurement):
    item = db.find("bid_item", measurement["bid_item_id"])
    if measurement["measurement_status"] not in ("APPROVED", "PAYABLE"):
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED or PAYABLE measurement may be voided.", 409)
    project = get_project(item["project_id"]) if item else None
    reconciliation = calc.non_closed_reconciliation(project) if project else None
    if reconciliation is not None and reconciliation["reconciliation_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE",
                       "A closed reconciliation has frozen the quantities it settled.", 409)

    measurement["measurement_status"] = "VOIDED"
    measurement["payable_amount_cents"] = 0
    db.touch(measurement)
    if item is not None:
        calc.recalc_item(item)
    if project is not None:
        calc.refresh_reconciliation(project)
        db.touch(project)
    return measurement


# ---------------------------------------------------------------------------
# QuantityReconciliation
# ---------------------------------------------------------------------------

def open_reconciliation(project):
    for existing in db.RECONCILIATIONS.values():
        if existing["project_id"] == project["id"] and existing["reconciliation_status"] != "CLOSED":
            raise ApiError("ERR_RECONCILIATION_ALREADY_OPEN",
                           "The project already holds a reconciliation that is not CLOSED.", 409)

    record = db.create("reconciliation", {
        "project_id": project["id"],
        "reconciliation_status": "OPEN",
        "overrun_item_count": 0,
        "underrun_item_count": 0,
        "net_adjustment_cents": 0,
        "final_contract_value_cents": project["contract_value_cents"],
        "retention_held_cents": 0,
        "pace_basis_retention_cents": 0,
        "retention_released_cents": 0,
        "closeout_status": "NONE",
    })
    calc.refresh_reconciliation(project)
    return record


def finalize_reconciliation(project, reconciliation, expected_project_version):
    if expected_project_version is None or isinstance(expected_project_version, bool) \
            or not isinstance(expected_project_version, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_project_version is required.", 400)
    if expected_project_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION",
                       "The project has moved on since version %s was observed."
                       % expected_project_version, 412)
    if reconciliation["reconciliation_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "The reconciliation is not OPEN.", 409)

    # The gate is evaluated while the reconciliation is still OPEN, so the
    # running ledger's OPEN-phase population applies (PRD 3.8).  The switch to
    # the APPROVED-only population happens only once the finalization succeeds.
    for item in calc.included_items(project):
        _, variance, _ = calc.item_ledger(item, statuses=calc.OPEN_PHASE_STATUSES)
        crosses = (variance > dec(item["overrun_threshold_pct"])
                   or variance < (-dec(item["underrun_threshold_pct"])))
        if crosses and not calc.has_final_renegotiated_rate(item):
            raise ApiError("ERR_QUANTITY_RENEGOTIATION_REQUIRED",
                           "Pay item %s crosses a variance band with no final renegotiated rate."
                           % item["item_code"], 422)

    for condition in db.CONDITIONS.values():
        if condition["project_id"] == project["id"] and condition["condition_status"] in OPEN_CLAIM_STATUSES:
            raise ApiError("ERR_OPEN_CLAIM_BLOCKS_CLOSEOUT",
                           "An open differing site condition blocks closeout.", 422)

    for measurement in calc.project_measurements(project):
        if measurement["measurement_status"] == "DRAFT":
            raise ApiError("ERR_MEASUREMENTS_PENDING",
                           "A progress measurement on the project is still DRAFT.", 422)

    reconciliation["reconciliation_status"] = "FINALIZED"
    reconciliation["closeout_status"] = "PENDING_RETENTION"
    calc.refresh_reconciliation(project)
    project["contract_value_cents"] = reconciliation["final_contract_value_cents"]
    project["retention_balance_cents"] = (
        reconciliation["retention_held_cents"] - reconciliation["retention_released_cents"]
    )
    db.touch(reconciliation)
    db.touch(project)
    return reconciliation


def release_retention(project, reconciliation):
    if reconciliation["reconciliation_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Retention has already been released.", 409)
    if reconciliation["reconciliation_status"] != "FINALIZED":
        raise ApiError("ERR_RETENTION_NOT_RELEASABLE",
                       "Retention may only be released once the reconciliation is FINALIZED.", 422)

    reconciliation["reconciliation_status"] = "CLOSED"
    reconciliation["retention_released_cents"] = reconciliation["retention_held_cents"]
    reconciliation["closeout_status"] = "CLOSED"
    project["retention_balance_cents"] = 0
    db.touch(reconciliation)

    items = calc.project_items(project)
    for item in items:
        if item["item_status"] == "ACTIVE":
            item["item_status"] = "CLOSED"
            measured, variance, renegotiation = calc.item_ledger(item)
            item["measured_quantity"] = float(measured)
            item["variance_pct"] = calc.f2(variance)
            item["renegotiation_required"] = bool(renegotiation)
            db.touch(item)
    items = calc.project_items(project)
    if items and all(i["item_status"] == "CLOSED" for i in items):
        project["project_status"] = "COMPLETE"
        project["claim_window_open"] = False

    touched_sureties = set()
    for commitment in db.COMMITMENTS.values():
        if commitment["project_id"] == project["id"] and commitment["commitment_status"] in ("RESERVED", "ACTIVE"):
            commitment["commitment_status"] = "RELEASED"
            commitment["released_at"] = db.clock()
            db.touch(commitment)
            touched_sureties.add(commitment["surety_id"])
    for bond in db.BONDS.values():
        if bond["project_id"] == project["id"] and bond["bond_status"] == "ISSUED":
            bond["bond_status"] = "RELEASED"
            bond["released_at"] = db.clock()
            bond["capacity_consumed_cents"] = 0
            db.touch(bond)
            touched_sureties.add(bond["surety_id"])
    for surety_id in touched_sureties:
        surety = db.find("surety", surety_id)
        if surety is not None:
            calc.recalc_surety(surety)
    db.touch(project)
    return reconciliation


# ---------------------------------------------------------------------------
# DifferingSiteCondition
# ---------------------------------------------------------------------------

def report_condition(payload):
    project = get_project(payload.get("project_id"))
    reported_at = parse_iso(payload.get("reported_at"))
    claimed = payload.get("claimed_amount_cents")
    if claimed is None:
        claimed = 0
    if isinstance(claimed, bool) or not isinstance(claimed, int) or claimed < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "claimed_amount_cents must be an integer of zero or greater.", 400)
    if not project["claim_window_open"]:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED",
                       "The project's claim window is not open.", 422)

    record = db.create("condition", {
        "project_id": project["id"],
        "condition_status": "REPORTED",
        "reported_at": reported_at,
        "documentation_complete": False,
        "notice_days_elapsed": 0,
        "claimed_amount_cents": claimed,
        "claim_window_engaged": False,
    })
    record["notice_days_elapsed"] = calc.notice_days_elapsed(record)
    return record


def document_condition(condition, payload):
    if condition["condition_status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REPORTED condition may be documented.", 409)
    project = get_project(condition["project_id"])
    if not project["claim_window_open"]:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED",
                       "The project's claim window is not open.", 422)
    urls = payload.get("documentation_package_urls")
    if not isinstance(urls, list) or len(urls) == 0:
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE",
                       "documentation_package_urls must be a non-empty array.", 422)

    condition["condition_status"] = "DOCUMENTED"
    condition["documentation_complete"] = True
    condition["notice_days_elapsed"] = calc.notice_days_elapsed(condition)
    db.touch(condition)
    return condition


def submit_claim(condition):
    if condition["condition_status"] != "DOCUMENTED":
        raise ApiError("ERR_INVALID_STATE", "Only a DOCUMENTED condition may be submitted.", 409)
    if not condition["documentation_complete"]:
        raise ApiError("ERR_INVALID_STATE", "The claim package is not complete.", 409)
    project = get_project(condition["project_id"])
    if project["project_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The project's delivery dimension is not ACTIVE.", 409)

    condition["notice_days_elapsed"] = calc.notice_days_elapsed(condition)
    if condition["notice_days_elapsed"] > calc.NOTICE_LIMIT_DAYS:
        raise ApiError("ERR_NOTICE_PERIOD_EXPIRED",
                       "The thirty-day notice period has expired.", 422)
    if condition["claimed_amount_cents"] <= 0:
        raise ApiError("ERR_CLAIM_AMOUNT_REQUIRED",
                       "A claim for nothing is not a claim; claimed_amount_cents must be positive.",
                       422)

    condition["condition_status"] = "UNDER_REVIEW"
    db.touch(condition)
    db.touch(project)
    return condition


def return_for_documentation(condition):
    if condition["condition_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only a claim UNDER_REVIEW may be returned.", 409)
    condition["condition_status"] = "DOCUMENTED"
    condition["documentation_complete"] = False
    db.touch(condition)
    return condition


def deny_condition(condition):
    if condition["condition_status"] not in OPEN_CLAIM_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "The claim has already reached a terminal state.", 409)
    condition["condition_status"] = "DENIED"
    db.touch(condition)
    return condition


def issue_determination(condition, payload):
    determination_type = payload.get("determination_type")
    target_bid_item_id = payload.get("target_bid_item_id")
    rate = payload.get("determined_unit_rate_cents")
    days = payload.get("days_granted")
    if rate is None:
        rate = 0
    if days is None:
        days = 0
    if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "determined_unit_rate_cents must be an integer of zero or greater.", 400)
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ApiError("ERR_INVALID_REQUEST", "days_granted must be an integer of zero or greater.", 400)

    project = get_project(condition["project_id"])
    target_item = None
    if determination_type == "QUANTITY_ADJUSTMENT":
        if not target_bid_item_id:
            raise ApiError("ERR_INVALID_REQUEST",
                           "target_bid_item_id is required for a QUANTITY_ADJUSTMENT.", 400)
        target_item = db.find("bid_item", target_bid_item_id)
        if target_item is None or target_item["project_id"] != project["id"]:
            raise ApiError("ERR_BID_ITEM_NOT_FOUND",
                           "No pay item %s belongs to this project." % target_bid_item_id, 404)

    if condition["condition_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_UNDER_REVIEW",
                       "A determination may only be issued on a claim UNDER_REVIEW.", 422)

    record = db.create("determination", {
        "condition_id": condition["id"],
        "determination_type": determination_type,
        "target_bid_item_id": target_bid_item_id if determination_type == "QUANTITY_ADJUSTMENT" else None,
        "determined_unit_rate_cents": rate,
        "days_granted": days,
        "entitles_adjustment": determination_type in ("COST_EQUITABLE_ADJUSTMENT",
                                                      "QUANTITY_ADJUSTMENT"),
        "determination_status": "ISSUED",
        "issued_at": db.clock(),
    })
    condition["condition_status"] = "DETERMINED"
    db.touch(condition)

    if determination_type == "QUANTITY_ADJUSTMENT" and target_item is not None:
        for measurement in calc.item_measurements(target_item):
            if measurement["measurement_status"] == "VOIDED":
                continue
            measurement["applied_unit_price_cents"] = rate
            if measurement["measurement_status"] in ("APPROVED", "PAYABLE"):
                measurement["payable_amount_cents"] = calc.payable_amount_cents(measurement, rate)
            db.touch(measurement)

    calc.refresh_reconciliation(project)
    reconciliation = calc.non_closed_reconciliation(project)
    if reconciliation is not None:
        project["contract_value_cents"] = reconciliation["final_contract_value_cents"]
        project["retention_balance_cents"] = (
            reconciliation["retention_held_cents"] - reconciliation["retention_released_cents"]
        )
    db.touch(project)
    return record


def finalize_determination(determination):
    if determination["determination_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED determination may be finalized.", 409)
    condition = db.find("condition", determination["condition_id"])
    project = get_project(condition["project_id"]) if condition else None

    if determination["determination_type"] == "QUANTITY_ADJUSTMENT" and project is not None:
        for other in db.DETERMINATIONS.values():
            if other["id"] == determination["id"]:
                continue
            if other["determination_status"] != "FINAL":
                continue
            if other["determination_type"] != "QUANTITY_ADJUSTMENT":
                continue
            other_condition = db.find("condition", other["condition_id"])
            if other_condition is not None and other_condition["project_id"] == project["id"]:
                raise ApiError("ERR_INVALID_STATE",
                               "A quantity adjustment determination on this project is already FINAL.",
                               409)

    determination["determination_status"] = "FINAL"
    db.touch(determination)
    if determination["determination_type"] == "QUANTITY_ADJUSTMENT" and condition is not None:
        condition["claim_window_engaged"] = True
        db.touch(condition)
    if project is not None:
        db.touch(project)
    return determination
