"""Resource serialization and derived-field recomputation."""

import clock
import calculations
import storage


# ---------------------------------------------------------------------------
# Serializers -- field names come from the scaffold's entity tables
# ---------------------------------------------------------------------------
def account_out(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "account_type": a["account_type"],
        "account_status": a["account_status"],
        "tax_id_last4": a["tax_id_last4"],
        "credit_class": a["credit_class"],
        "payment_history_score": a["payment_history_score"],
        "active_line_count": a["active_line_count"],
        "reserved_mdn_count": a["reserved_mdn_count"],
        "deposit_required_cents": a["deposit_required_cents"],
        "existing_deposit_cents": a["existing_deposit_cents"],
        "promo_credited_cents": a["promo_credited_cents"],
        "promo_clawed_back_cents": a["promo_clawed_back_cents"],
        "net_promo_credit_cents": a["net_promo_credit_cents"],
    }


def line_out(line):
    return {
        "id": line["id"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
        "account_id": line["account_id"],
        "mdn": line["mdn"],
        "billing_mode": line["billing_mode"],
        "service_status": line["service_status"],
        "number_status": line["number_status"],
        "port_protection_status": line["port_protection_status"],
        "line_opened_at": line["line_opened_at"],
        "loyalty_tenure_months": line["loyalty_tenure_months"],
        "retention_cycle_count": line["retention_cycle_count"],
        "promo_eligibility_state": line["promo_eligibility_state"],
        "cancellation_effective_at": line["cancellation_effective_at"],
    }


def port_request_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "subscriber_line_id": r["subscriber_line_id"],
        "losing_carrier_code": r["losing_carrier_code"],
        "account_number_at_losing_carrier": r["account_number_at_losing_carrier"],
        "transfer_pin": r["transfer_pin"],
        "requested_cutover_at": r["requested_cutover_at"],
        "request_state": r["request_state"],
        "rejection_count": r["rejection_count"],
        "last_rejection_code": r["last_rejection_code"],
        "rejections": list(r["rejections"]),
        "last_rejection_at": r["last_rejection_at"],
        "submitted_at": r["submitted_at"],
        "supersedes_port_request_id": r["supersedes_port_request_id"],
        "cutover_completed_at": r["cutover_completed_at"],
    }


def promo_out(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "subscriber_line_id": s["subscriber_line_id"],
        "promo_code": s["promo_code"],
        "monthly_credit_cents": s["monthly_credit_cents"],
        "installment_months": s["installment_months"],
        "retention_requirement_cycles": s["retention_requirement_cycles"],
        "schedule_state": s["schedule_state"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "provisional_total_cents": s["provisional_total_cents"],
        "vested_total_cents": s["vested_total_cents"],
        "cycles_elapsed": s["cycles_elapsed"],
    }


def plan_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "subscriber_line_id": p["subscriber_line_id"],
        "device_model": p["device_model"],
        "device_price_cents": p["device_price_cents"],
        "down_payment_cents": p["down_payment_cents"],
        "installment_months": p["installment_months"],
        "monthly_installment_cents": p["monthly_installment_cents"],
        "remaining_balance_cents": p["remaining_balance_cents"],
        "plan_state": p["plan_state"],
        "financed_at": p["financed_at"],
        "upgrade_eligible_at": p["upgrade_eligible_at"],
        "trade_in_credit_cents": p["trade_in_credit_cents"],
    }


def assessment_out(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "installment_plan_id": t["installment_plan_id"],
        "parent_plan_id": t["parent_plan_id"],
        "device_model": t["device_model"],
        "declared_condition": t["declared_condition"],
        "graded_condition": t["graded_condition"],
        "assessment_state": t["assessment_state"],
        "estimated_credit_cents": t["estimated_credit_cents"],
        "final_credit_cents": t["final_credit_cents"],
        "grade_delta_cents": t["grade_delta_cents"],
        "submitted_at": t["submitted_at"],
        "graded_at": t["graded_at"],
    }


def reservation_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "account_id": r["account_id"],
        "mdn": r["mdn"],
        "pool_code": r["pool_code"],
        "reservation_state": r["reservation_state"],
        "reserved_at": r["reserved_at"],
        "reserved_until": r["reserved_until"],
        "hold_days": r["hold_days"],
        "committed_line_id": r["committed_line_id"],
    }


def migration_out(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "subscriber_line_id": m["subscriber_line_id"],
        "source_billing_mode": m["source_billing_mode"],
        "target_billing_mode": m["target_billing_mode"],
        "migration_state": m["migration_state"],
        "carried_mdn": m["carried_mdn"],
        "prepaid_balance_cents": m["prepaid_balance_cents"],
        "device_balance_cents": m["device_balance_cents"],
        "proration_credit_cents": m["proration_credit_cents"],
        "requested_cutover_at": m["requested_cutover_at"],
        "cutover_completed_at": m["cutover_completed_at"],
    }


def addition_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "account_id": r["account_id"],
        "parent_account_id": r["parent_account_id"],
        "line_count": r["line_count"],
        "requested_mdn": r["requested_mdn"],
        "determined_credit_class": r["determined_credit_class"],
        "required_deposit_cents": r["required_deposit_cents"],
        "request_state": r["request_state"],
        "decision_note": r["decision_note"],
        "submitted_at": r["submitted_at"],
    }


def protection_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "subscriber_line_id": c["subscriber_line_id"],
        "protection_type": c["protection_type"],
        "verified_identity": c["verified_identity"],
        "case_state": c["case_state"],
        "set_at": c["set_at"],
        "cleared_at": c["cleared_at"],
        "reason_code": c["reason_code"],
    }


def catalog_out(c):
    # Static reference table: id + created_at only, no updated_at / version.
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "rejection_code": c["rejection_code"],
        "description": c["description"],
        "guidance_text": c["guidance_text"],
        "resubmission_allowed": c["resubmission_allowed"],
        "retry_after_hours": c["retry_after_hours"],
        "requires_action_by": c["requires_action_by"],
    }


def config_out(cfg):
    return {
        "id": cfg["id"],
        "created_at": cfg["created_at"],
        "updated_at": cfg["updated_at"],
        "version": cfg["version"],
        "ops_run_epoch": cfg["ops_run_epoch"],
        "last_ops_run_at": cfg["last_ops_run_at"],
        "last_line_cancellation_deadline": cfg["last_line_cancellation_deadline"],
        "line_cancellation_grace_hours": cfg["line_cancellation_grace_hours"],
        "promo_window_buffer_days": cfg["promo_window_buffer_days"],
    }


OUT = {
    "Account": account_out,
    "SubscriberLine": line_out,
    "PortRequest": port_request_out,
    "PromoCreditSchedule": promo_out,
    "DeviceInstallmentPlan": plan_out,
    "TradeInAssessment": assessment_out,
    "NumberReservation": reservation_out,
    "MigrationRequest": migration_out,
    "LineAdditionRequest": addition_out,
    "PortProtectionCase": protection_out,
    "RejectionCodeCatalog": catalog_out,
    "SystemConfig": config_out,
}


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------
def touch(record):
    """One modification: bump version and restamp updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = clock.fmt_now()
    return record


def active_lines_of(account_id):
    return [
        line
        for line in storage.db.all("subscriber_lines")
        if line["account_id"] == account_id and line["service_status"] == "ACTIVE"
    ]


def active_line_count(account_id):
    return len(active_lines_of(account_id))


def held_reservations_of(account_id):
    return [
        r
        for r in storage.db.all("number_reservations")
        if r["account_id"] == account_id and r["reservation_state"] == "HELD"
    ]


def recompute_account_counters(account_id):
    """Refresh active_line_count / reserved_mdn_count / credit class and deposit.

    Bumps the account's version only when one of the derived values actually
    changes, so a recomputation that alters nothing is not recorded as a
    modification.
    """
    account = storage.db.get("accounts", account_id)
    if account is None:
        return None
    before = (
        account["active_line_count"],
        account["reserved_mdn_count"],
        account["credit_class"],
        account["deposit_required_cents"],
    )
    account["active_line_count"] = active_line_count(account_id)
    account["reserved_mdn_count"] = len(held_reservations_of(account_id))
    klass, deposit = calculations.credit_class_determination(
        account["payment_history_score"], account["active_line_count"], 0
    )
    account["credit_class"] = klass
    account["deposit_required_cents"] = deposit
    after = (
        account["active_line_count"],
        account["reserved_mdn_count"],
        account["credit_class"],
        account["deposit_required_cents"],
    )
    if before != after:
        touch(account)
    return account


def recompute_promo_ledger(account_id):
    account = storage.db.get("accounts", account_id)
    if account is None:
        return None
    account["net_promo_credit_cents"] = (
        account["promo_credited_cents"] - account["promo_clawed_back_cents"]
    )
    touch(account)
    return account


def recompute_line_tenure(line):
    """Loyalty tenure in whole months and completed billing cycles since opening."""
    if line.get("line_opened_at"):
        opened = clock.parse_instant(line["line_opened_at"])
        line["loyalty_tenure_months"] = clock.months_between(opened, clock.now())
        line["retention_cycle_count"] = clock.completed_cycles(opened, clock.now())
    else:
        line["loyalty_tenure_months"] = 0
        line["retention_cycle_count"] = 0
    return line


def has_active_protection(line_id):
    for case in storage.db.all("port_protection_cases"):
        if case["subscriber_line_id"] == line_id and case["case_state"] == "ACTIVE":
            return True
    return False


def open_port_requests_on(line_id):
    return [
        r
        for r in storage.db.all("port_requests")
        if r["subscriber_line_id"] == line_id
        and r["request_state"] in ("PENDING", "RESUBMITTED")
    ]


def mdn_held_reserved(mdn, exclude_line_id=None):
    for line in storage.db.all("subscriber_lines"):
        if line["id"] == exclude_line_id:
            continue
        if line["mdn"] == mdn and line["number_status"] == "RESERVED":
            return line
    return None


def mdn_conflicting(mdn):
    for line in storage.db.all("subscriber_lines"):
        if line["mdn"] == mdn and line["number_status"] in (
            "ASSIGNED",
            "RESERVED",
            "PORTED_IN",
        ):
            return line
    return None