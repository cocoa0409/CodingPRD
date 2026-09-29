"""Cascades A, B and C plus the slot_index recomputation (PRD 2.9)."""
from datetime import timedelta

import calc
import queries
from db import db, now, now_iso, today, touch
from util import add_months, fmt_date, parse_date, parse_instant

LIVE_SLOT_STATUSES = ("BOOKED", "CHECKED_IN", "COMPLETED")


def slot_date(appointment):
    return parse_instant(appointment["start_utc"]).date()


def recompute_slot_indexes(densitometer_id, dates):
    """Positional renumbering of every remaining non-cancelled slot."""
    for target in set(dates):
        siblings = [
            row for row in queries.appointments_of_device(densitometer_id, LIVE_SLOT_STATUSES)
            if slot_date(row) == target
        ]
        siblings.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
        for index, row in enumerate(siblings, start=1):
            if row["slot_index"] != index:
                row["slot_index"] = index
                touch(row)


def decrement_open_orders(patient):
    if patient["open_scheduled_order_count"] > 0:
        patient["open_scheduled_order_count"] -= 1
        touch(patient)


def revert_order_for(appointment, reschedule_required):
    """Send the order behind a cancelled slot back to REQUESTED."""
    order = db.scan_orders.get(appointment["scan_order_id"])
    if order is None or order["status"] != "SCHEDULED":
        return
    live = [
        row for row in queries.appointments_of_order(order["id"], ("BOOKED", "CHECKED_IN"))
        if row["id"] != appointment["id"]
    ]
    if live:
        return
    order["status"] = "REQUESTED"
    if reschedule_required:
        order["reschedule_required"] = True
    touch(order)
    patient = db.patients.get(order["patient_id"])
    if patient is not None:
        decrement_open_orders(patient)


def cancel_appointment(appointment, reason_code, reschedule_required):
    appointment["status"] = "CANCELLED"
    appointment["cancellation_reason_code"] = reason_code
    appointment["cancelled_at_utc"] = now_iso()
    touch(appointment)
    revert_order_for(appointment, reschedule_required)


def cascade_b_qc_hold(device):
    """Cascade B: cancel every imminent booked slot on a device going on hold."""
    horizon = parse_instant(device["qc_hold_started_at"]) + timedelta(
        hours=calc.QC_HOLD_CANCEL_HORIZON_HOURS
    )
    affected = [
        row for row in queries.appointments_of_device(device["id"], ("BOOKED",))
        if parse_instant(row["start_utc"]) < horizon
    ]
    affected.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
    dates = [slot_date(row) for row in affected]
    for row in affected:
        cancel_appointment(row, "DEVICE_QC_HOLD", True)
    recompute_slot_indexes(device["id"], dates)


def cascade_c_approve(event, device):
    """Cascade C: bump the generation and write the correction factor."""
    event["status"] = "APPROVED"
    event["adjudicated_at_utc"] = now_iso()
    touch(event)
    if event["outcome_code"] == "WITHIN_TOLERANCE_NO_FACTOR":
        device["cross_cal_factor"] = calc.D("1.0")
    else:
        device["cross_cal_factor"] = event["proposed_cross_cal_factor"]
    device["calibration_generation"] += 1
    if device["status"] == "CROSS_CAL_PENDING":
        device["status"] = "ACTIVE"
    device["qc_hold_started_at"] = None
    device["qc_hold_reason_code"] = None
    device["consecutive_qc_pass_count"] = 0
    touch(device)


def retire_device(device):
    """PRD 3.2: retirement unwinds the schedule and any open calibration event."""
    device["status"] = "RETIRED"
    touch(device)
    affected = []
    for row in queries.appointments_of_device(device["id"], ("BOOKED", "CHECKED_IN")):
        if row["status"] == "CHECKED_IN":
            in_progress = [
                s for s in queries.sessions_of_appointment(row["id"])
                if s["acquisition_status"] == "IN_PROGRESS"
            ]
            if in_progress:
                continue
        affected.append(row)
    affected.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
    dates = [slot_date(row) for row in affected]
    for row in affected:
        cancel_appointment(row, "DEVICE_QC_HOLD", True)
    recompute_slot_indexes(device["id"], dates)
    for event in queries.events_of_device(device["id"], ("OPEN", "PHANTOM_SET_COMPLETE")):
        event["status"] = "REJECTED"
        event["outcome_code"] = "REJECTED_EXCESSIVE_DRIFT"
        event["adjudicated_at_utc"] = now_iso()
        touch(event)


def reevaluate_order(order, patient, policy):
    """Cascade A link three: re-run the frequency test on an existing order."""
    requested = parse_date(order["requested_scan_date"])
    verdict, earliest = calc.frequency_eligibility(patient, policy, requested)
    changed = (
        order["frequency_eligibility"] != verdict
        or order["earliest_allowed_date"] != earliest
    )
    order["frequency_eligibility"] = verdict
    order["earliest_allowed_date"] = earliest
    order["payer_floor_months"] = calc.payer_floor_months(policy, order["indication"])
    if verdict in ("INELIGIBLE_TOO_SOON", "INELIGIBLE_LIFETIME_CAP"):
        was_scheduled = order["status"] == "SCHEDULED"
        order["status"] = "DENIED"
        order["denial_reason_code"] = (
            "INTERVAL_REVISED_BY_REPORT" if verdict == "INELIGIBLE_TOO_SOON"
            else "LIFETIME_CAP_EXCEEDED"
        )
        touch(order)
        dates = []
        for appointment in queries.appointments_of_order(order["id"], ("BOOKED",)):
            appointment["status"] = "CANCELLED"
            appointment["cancellation_reason_code"] = "ORDER_DENIED"
            appointment["cancelled_at_utc"] = now_iso()
            touch(appointment)
            dates.append((appointment["densitometer_id"], slot_date(appointment)))
        for densitometer_id, day in dates:
            recompute_slot_indexes(densitometer_id, [day])
        if was_scheduled:
            decrement_open_orders(patient)
        return True
    if changed:
        touch(order)
    return False


def cascade_a_finalize(report, session, patient, actor):
    """Cascade A: four links, each caused by the one before it."""
    report["status"] = "FINALIZED"
    report["finalized_at_utc"] = now_iso()
    report["finalized_by_user_id"] = actor
    touch(report)
    session["acquisition_status"] = "ARCHIVED"
    touch(session)

    patient["lifetime_screening_scan_count"] += 1
    patient["last_finalized_report_id"] = report["id"]
    if patient["baseline_report_id"] is None:
        patient["baseline_report_id"] = report["id"]
    patient["current_screening_interval_months"] = report["recommended_interval_months"]
    scan_date = parse_instant(session["submitted_at_utc"]).date()
    patient["next_eligible_scan_date"] = fmt_date(
        add_months(scan_date, report["recommended_interval_months"])
    )
    touch(patient)

    policy = queries.policy_of(patient)
    for order in queries.orders_of_patient(patient["id"], ("REQUESTED", "SCHEDULED")):
        reevaluate_order(order, patient, policy)


def compensate_amendment(patient):
    """PRD 3.8: re-derive the patient tallies after an amendment."""
    if patient["lifetime_screening_scan_count"] > 0:
        patient["lifetime_screening_scan_count"] -= 1
    remaining = queries.finalized_reports_of_patient(patient["id"])
    if not remaining:
        patient["baseline_report_id"] = None
        patient["last_finalized_report_id"] = None
        patient["current_screening_interval_months"] = None
        patient["next_eligible_scan_date"] = None
        touch(patient)
        return
    ordered = sorted(
        remaining,
        key=lambda row: (row["finalized_at_utc"], row["created_at"], row["_seq"]),
    )
    baseline = ordered[0]
    latest = ordered[-1]
    patient["baseline_report_id"] = baseline["id"]
    patient["last_finalized_report_id"] = latest["id"]
    patient["current_screening_interval_months"] = latest["recommended_interval_months"]
    latest_session = db.scan_sessions.get(latest["scan_session_id"])
    if latest_session is not None and latest_session["submitted_at_utc"] is not None:
        scan_date = parse_instant(latest_session["submitted_at_utc"]).date()
        patient["next_eligible_scan_date"] = fmt_date(
            add_months(scan_date, latest["recommended_interval_months"])
        )
    else:
        patient["next_eligible_scan_date"] = None
    touch(patient)
