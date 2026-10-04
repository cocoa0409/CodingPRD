"""Scheduled (clock-driven) transitions.

Advancing the logical clock evaluates every scheduled transition whose deadline
has been reached: port cutover, migration eligibility / scheduling / cutover,
promotional vesting and reservation expiry (PRD 2.4, 3.8).
"""

import calculations
import clock
import models
import services
import storage


def _line(line_id):
    return storage.db.get("subscriber_lines", line_id)


def _account_of_line(line):
    if line is None:
        return None
    return storage.db.get("accounts", line["account_id"])


# ---------------------------------------------------------------------------
def port_cutovers():
    """ACCEPTED_PENDING_CUTOVER -> PORTED, with the four ordered hops."""
    for request in storage.db.all("port_requests"):
        if request["request_state"] != "ACCEPTED_PENDING_CUTOVER":
            continue
        due = clock.parse_instant(request["requested_cutover_at"])
        if due is None or clock.now() < due:
            continue
        line = _line(request["subscriber_line_id"])
        if line is None:
            continue

        # hop 1
        request["cutover_completed_at"] = clock.fmt_now()
        request["request_state"] = "PORTED"
        models.touch(request)
        line["service_status"] = "ACTIVE"
        line["number_status"] = "PORTED_IN"

        # hop 2
        if line["line_opened_at"] is None:
            line["line_opened_at"] = clock.fmt_now()

        # hop 3
        models.recompute_line_tenure(line)
        models.touch(line)

        # hop 4
        for schedule in storage.db.all("promo_credit_schedules"):
            if schedule["subscriber_line_id"] != line["id"]:
                continue
            if schedule["schedule_state"] != "PROVISIONAL":
                continue
            if line["retention_cycle_count"] >= schedule["retention_requirement_cycles"]:
                schedule["schedule_state"] = "ACTIVE"
                models.touch(schedule)

        account = _account_of_line(line)
        if account is not None and account["account_status"] != "OPEN":
            account["account_status"] = "OPEN"
            models.recompute_account_counters(account["id"])
            models.touch(account)


# ---------------------------------------------------------------------------
def _migration_evaluate(migration):
    """Route an ELIGIBILITY_CHECK migration to APPROVED or BLOCKED."""
    line = _line(migration["subscriber_line_id"])
    if line is None:
        return
    protected = models.has_active_protection(line["id"])
    open_ports = models.open_port_requests_on(line["id"])
    account = _account_of_line(line)

    migration["migration_state"] = "BLOCKED" if (protected or open_ports) else "APPROVED"
    if migration["migration_state"] == "BLOCKED":
        line["number_status"] = "UNASSIGNED"
        models.touch(line)
        if protected and account is not None and account["account_status"] != "SUSPENDED":
            account["account_status"] = "SUSPENDED"
            models.touch(account)
    else:
        line["number_status"] = "RESERVED"
        models.touch(line)
    models.touch(migration)


def migration_progress():
    """Evaluate eligibility, then schedule, then complete -- per PRD 3.3."""
    for migration in storage.db.all("migration_requests"):
        if migration["migration_state"] == "ELIGIBILITY_CHECK":
            _migration_evaluate(migration)

    for migration in storage.db.all("migration_requests"):
        if migration["migration_state"] != "APPROVED":
            continue
        due = clock.parse_instant(migration["requested_cutover_at"])
        if due is not None and clock.now() >= due:
            migration["migration_state"] = "CUTOVER_SCHEDULED"
            models.touch(migration)

    for migration in storage.db.all("migration_requests"):
        if migration["migration_state"] != "CUTOVER_SCHEDULED":
            continue
        due = clock.parse_instant(migration["requested_cutover_at"])
        if due is None or clock.now() < due:
            continue
        _migration_complete(migration)


def _migration_complete(migration):
    line = _line(migration["subscriber_line_id"])
    if line is None:
        return
    account = _account_of_line(line)

    # hop 1
    migration["cutover_completed_at"] = clock.fmt_now()
    migration["migration_state"] = "CUTOVER_COMPLETE"
    line["billing_mode"] = "POSTPAID"
    line["number_status"] = "ASSIGNED"

    # hop 2
    migration["carried_mdn"] = line["mdn"]
    device_balance = sum(
        plan["remaining_balance_cents"]
        for plan in storage.db.all("device_installment_plans")
        if plan["subscriber_line_id"] == line["id"]
    )
    migration["device_balance_cents"] = device_balance

    # hop 3
    active_count = account["active_line_count"] if account else 0
    migration["proration_credit_cents"] = calculations.migration_proration_credit(
        active_count,
        migration["prepaid_balance_cents"],
        device_balance,
        clock.now(),
    )

    for plan in storage.db.all("device_installment_plans"):
        if plan["subscriber_line_id"] == line["id"] and plan["plan_state"] != "CONVERTED":
            plan["plan_state"] = "CONVERTED"
            models.touch(plan)

    models.recompute_line_tenure(line)
    models.touch(line)
    models.touch(migration)


# ---------------------------------------------------------------------------
def promo_progress():
    """Refresh cycle counters and the vested running total, then vest due schedules.

    PRD 3.4: the vested total "credits only the cycles the line has actually
    completed inside the window, so it is 1 000 cents multiplied by
    `cycles_elapsed`" — the chronological variant. It therefore tracks
    `cycles_elapsed` on every clock advance, not only at vesting.
    """
    for schedule in storage.db.all("promo_credit_schedules"):
        if schedule["schedule_state"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        start = clock.parse_instant(schedule["window_start"])
        elapsed = calculations.promo_cycles_elapsed(start, clock.now())
        vested = calculations.promo_vested_total(elapsed)
        if (elapsed != schedule["cycles_elapsed"]
                or vested != schedule["vested_total_cents"]):
            schedule["cycles_elapsed"] = elapsed
            schedule["vested_total_cents"] = vested
            models.touch(schedule)

    for schedule in storage.db.all("promo_credit_schedules"):
        if schedule["schedule_state"] != "ACTIVE":
            continue
        end = clock.parse_instant(schedule["window_end"])
        if end is None or clock.now() < end:
            continue
        start = clock.parse_instant(schedule["window_start"])
        schedule["cycles_elapsed"] = calculations.promo_cycles_elapsed(start, clock.now())
        schedule["vested_total_cents"] = calculations.promo_vested_total(
            schedule["cycles_elapsed"]
        )
        schedule["schedule_state"] = "VESTED"
        models.touch(schedule)

        line = _line(schedule["subscriber_line_id"])
        if line is not None:
            line["promo_eligibility_state"] = "VESTED"
            models.touch(line)
            account = _account_of_line(line)
            if account is not None:
                models.recompute_promo_ledger(account["id"])


# ---------------------------------------------------------------------------
def reservation_expiries():
    for reservation in storage.db.all("number_reservations"):
        if reservation["reservation_state"] != "HELD":
            continue
        until = clock.parse_instant(reservation["reserved_until"])
        if until is None or clock.now() < until:
            continue
        reservation["reservation_state"] = "EXPIRED"
        models.touch(reservation)
        models.recompute_account_counters(reservation["account_id"])


# ---------------------------------------------------------------------------
def installment_upgrade_eligibility():
    """A financed plan becomes upgrade-eligible once the clock reaches the date.

    Plans already CONVERTED by a migration are excluded from the evaluation.
    """
    for plan in storage.db.all("device_installment_plans"):
        if plan["plan_state"] != "ACTIVE":
            continue
        eligible = clock.parse_instant(plan["upgrade_eligible_at"])
        if eligible is None or clock.now() < eligible:
            continue
        services.recompute_plan(plan)


# ---------------------------------------------------------------------------
def run_all():
    """Evaluate every scheduled transition reached by the new clock reading."""
    port_cutovers()
    migration_progress()
    promo_progress()
    installment_upgrade_eligibility()
    reservation_expiries()