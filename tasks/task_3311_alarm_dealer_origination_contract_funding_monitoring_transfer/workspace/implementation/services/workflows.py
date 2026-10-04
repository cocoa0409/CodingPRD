"""State machines, cascades and workflow orchestration.

Each function below traces to a transition in SCAFFOLD §1.1 state_machines and to
the matching narrative in PRD §3. Rejection ordering follows PRD §2.10.
"""

from datetime import timedelta

import db
from errors import ApiError
from services import calculations as calc
from services import factory, queries
from util import (add_days, add_months, coerce_dt, fmt_ts, month_label, parse_ts,
                  round_half_up, whole_calendar_days, whole_calendar_months)


# ---------------------------------------------------------------------------
# Contract origination
# ---------------------------------------------------------------------------

def first_failing_gate(contract):
    """PRD §3.4 / §2.6 — the origination gates, in the §2.10 fiscal order."""
    if contract["source_channel"] == "DEALER":
        package = db.state.get("dealer_packages", contract.get("dealer_package_id"))
        if package is None or package.get("package_status") != "APPROVED":
            return "ERR_PACKAGE_DECLINED"
        expires_at = parse_ts(package.get("expires_at"))
        if expires_at is not None and db.now() > expires_at:
            return "ERR_FUNDING_WINDOW_EXPIRED"
    if contract.get("credit_score") is None or contract["credit_score"] < calc.CREDIT_FLOOR:
        return "ERR_CREDIT_SCORE_BELOW_FLOOR"
    if contract.get("contract_term_months") is None or contract["contract_term_months"] < calc.TERM_FLOOR:
        return "ERR_TERM_BELOW_FLOOR"
    permitted = calc.EQUIPMENT_PERMITTED.get(contract["source_channel"], set())
    if contract.get("equipment_config_code") not in permitted:
        return "ERR_EQUIPMENT_CONFIG_NOT_PERMITTED"
    account = queries.account_for_contract(contract["id"])
    provisioned = account is not None and account.get("provision_state") == "PROVISIONED"
    if not provisioned and not contract.get("chargeback_exempt"):
        return "ERR_MONITORING_NOT_PROVISIONED"
    return None


def activate_contract(contract):
    """PENDING_VALIDATION -> ACTIVE: the funding fee, the split and the stamps."""
    dealer = db.state.get("dealers", contract.get("dealer_id"))
    calc.funding_fee(contract, dealer)
    if dealer is not None:
        # PRD §2.9 — holdback_reserve_cents is the money the company withholds from
        # what it pays the dealer at funding, so funding credits the dealer's reserve.
        dealer["holdback_reserve_cents"] = dealer.get("holdback_reserve_cents", 0) + contract["holdback_cents"]
    split = calc.equipment_financing_split(contract, persist_equipment=True)
    contract["equipment_payment_cents"] = split["equipment_payment_cents"]
    contract["equipment_financing_disclosed"] = False
    contract["contract_status"] = "ACTIVE"
    contract["activated_at"] = fmt_ts(db.now())
    contract["funded_at"] = fmt_ts(db.now())
    if contract.get("contract_number") is None:
        sequence = 100000 + len(db.state.contracts)
        contract["contract_number"] = "C-%s-%06d" % (db.now().strftime("%Y%m"), sequence)
    customer = db.state.get("customers", contract.get("customer_id"))
    if customer is not None:
        customer["status"] = "ACTIVE"
        db.bump(customer)
    db.bump(contract)
    if contract.get("source_channel") == "DEALER":
        package = db.state.get("dealer_packages", contract.get("dealer_package_id"))
        if package is not None:
            calc.refresh_package_rollups(package)
        if dealer is not None:
            dealer["funded_package_count"] = len(
                [p for p in db.state.dealer_packages.values()
                 if p.get("dealer_id") == dealer["id"] and p.get("package_status") == "FUNDED"]
            )
            db.bump(dealer)
    return contract


def freeze_contract(contract, failure_code):
    """PENDING_VALIDATION -> CANCELLED: freeze the failing gate into the row."""
    contract["validation_failure_code"] = failure_code
    contract["cancelled_from_status"] = "PENDING_VALIDATION"
    contract["cancelled_at"] = fmt_ts(db.now())
    contract["contract_status"] = "CANCELLED"
    db.bump(contract)
    package = db.state.get("dealer_packages", contract.get("dealer_package_id"))
    if package is not None:
        calc.refresh_package_rollups(package)
        db.bump(package)
    return contract


def fund_package_cascade(package):
    """Fund (or freeze) every child still in PENDING_VALIDATION.

    PRD §3.3/§3.4: the gate failures are frozen first, the whole-package posture is
    then evaluated, and only if the posture is FUNDED are the survivors activated —
    a DECLINED posture freezes every remaining pending child instead.
    """
    children = queries.sorted_by_created(queries.children_of_package(package["id"]))

    # 1. Every pending child that fails at least one origination gate is frozen with
    #    the gate's own code.
    for child in children:
        if child.get("contract_status") != "PENDING_VALIDATION":
            continue
        failure = first_failing_gate(child)
        if failure is not None:
            freeze_contract(child, failure)

    # 2. The whole-package verdict.
    posture, holdback = calc.package_funding_posture(package)
    if posture == "DECLINED":
        # The whole-package posture declined: freeze every remaining pending child.
        for child in children:
            if child.get("contract_status") == "PENDING_VALIDATION":
                freeze_contract(child, "ERR_PACKAGE_DECLINED")
        calc.refresh_package_rollups(package)
        return "DECLINED"

    # 3. Survivors are activated only on a FUNDED posture.
    for child in children:
        if child.get("contract_status") == "PENDING_VALIDATION":
            activate_contract(child)
    calc.refresh_package_rollups(package)
    return posture


def observe_package_expiry(package):
    """APPROVED -> EXPIRED, observed opportunistically by a funding write."""
    if package.get("package_status") != "APPROVED":
        return False
    expires_at = coerce_dt(package.get("expires_at"))
    if expires_at is None or not (expires_at < db.now()):
        return False
    package["package_status"] = "EXPIRED"
    package["closed_at"] = fmt_ts(expires_at)
    db.bump(package)
    for child in queries.sorted_by_created(queries.children_of_package(package["id"])):
        if child.get("contract_status") == "PENDING_VALIDATION":
            freeze_contract(child, "ERR_FUNDING_WINDOW_EXPIRED")
    return True


def decline_package_cascade(package):
    """Cascade a package decline to every child still in PENDING_VALIDATION."""
    for child in queries.sorted_by_created(queries.children_of_package(package["id"])):
        if child.get("contract_status") == "PENDING_VALIDATION":
            freeze_contract(child, "ERR_PACKAGE_DECLINED")


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def close_monitoring_account_and_dispatches(contract):
    account = queries.account_for_contract(contract["id"])
    if account is None:
        return None
    if account.get("provision_state") != "CLOSED":
        account["provision_state"] = "CLOSED"
        db.bump(account)
    for dispatch in db.state.dispatch_requests.values():
        if dispatch.get("alarm_event_id") in {
            a["id"] for a in db.state.alarm_events.values()
            if a.get("monitoring_account_id") == account["id"]
        } and dispatch.get("dispatch_status") in ("REQUESTED", "DISPATCHED"):
            dispatch["dispatch_status"] = "CLOSED"
            db.bump(dispatch)
    return account


def cancel_contract(contract, apply_sweep=True, apply_chargeback=True):
    """ACTIVE | DELINQUENT -> CANCELLED (PRD §3.10)."""
    prior_status = contract["contract_status"]
    contract["cancelled_from_status"] = prior_status
    contract["cancelled_at"] = fmt_ts(db.now())
    contract["contract_status"] = "CANCELLED"

    # The subscriber's status follows only when this was their last live contract.
    customer = db.state.get("customers", contract.get("customer_id"))
    if customer is not None and not queries.customer_has_any_other_non_terminal(customer["id"], contract["id"]):
        customer["status"] = "CANCELLED"
        db.bump(customer)

    # Sites: a cancellation vacates the premises.
    for site in queries.sites_for_contract(contract["id"]):
        if site.get("occupancy_status") == "OCCUPIED":
            site["occupancy_status"] = "VACATED"
            db.bump(site)

    close_monitoring_account_and_dispatches(contract)

    dealer = db.state.get("dealers", contract.get("dealer_id"))
    if apply_sweep and contract.get("post_warranty_cents", 0) > calc.POST_WARRANTY_SWEEP_THRESHOLD_CENTS:
        if dealer is not None:
            calc.post_warranty_service_sweep(contract, dealer)

    db.bump(contract)

    # PRD §3.10 / endpoint table: a cancellation runs chargeback_decision, cascading
    # the amount into the dealer's reserve and balance due.
    if apply_chargeback and dealer is not None:
        calc.chargeback_decision(contract, dealer, apply=True)
        db.bump(dealer)
    return contract


# ---------------------------------------------------------------------------
# Attrition
# ---------------------------------------------------------------------------

def run_attrition_sweep(sweep_month):
    now = db.now()
    sweep = factory.make_attrition_sweep(sweep_month)
    sweep["ran_at"] = fmt_ts(now)

    contracts = queries.sorted_by_created(list(db.state.contracts.values()))
    for contract in contracts:
        if contract.get("contract_status") != "ACTIVE":
            continue
        activated_at = parse_ts(contract.get("activated_at"))
        if activated_at is None:
            continue
        cohort = month_label(coerce_dt(contract.get("activated_at")))
        if cohort > sweep_month:
            continue
        hold_until = coerce_dt(contract.get("monitoring_hold_until"))
        if hold_until is not None and hold_until > now:
            continue
        sweep["flagged_contract_ids"].append(contract["id"])
        sweep["delinquent_count"] += 1
        contract["contract_status"] = "DELINQUENT"
        contract["monitoring_hold_until"] = fmt_ts(now)
        contract["attrition_checked_at"] = fmt_ts(now)
        db.bump(contract)
        factory.make_attrition_flag(sweep["id"], contract["id"], cohort)
        account = queries.account_for_contract(contract["id"])
        if account is not None and account.get("provision_state") == "PROVISIONED":
            account["provision_state"] = "SUSPENDED"
            db.bump(account)

    # The same pass then looks for recoveries, again in created_at order.
    for contract in queries.sorted_by_created(list(db.state.contracts.values())):
        if contract.get("contract_status") != "DELINQUENT":
            continue
        if queries.open_service_required(contract["id"]) is not None:
            contract["contract_status"] = "ACTIVE"
            db.bump(contract)
            sweep["resumed_count"] += 1

    sweep["evaluated_count"] = len([
        c for c in db.state.contracts.values()
        if coerce_dt(c.get("activated_at")) is not None
        and month_label(coerce_dt(c.get("activated_at"))) == sweep_month
    ])
    db.bump(sweep)
    return sweep


# ---------------------------------------------------------------------------
# Alarms, dispatch
# ---------------------------------------------------------------------------

def account_was_provisioned_at(account, instant):
    """The alarm's counting flag asks whether the account was PROVISIONED at occurred_at."""
    if account is None:
        return False
    if account.get("provision_state") not in ("PROVISIONED", "SUSPENDED", "CLOSED"):
        return False
    return True


def record_verification(alarm, outcome):
    account = db.state.get("monitoring_accounts", alarm.get("monitoring_account_id"))
    alarm["verification_outcome"] = outcome
    alarm["verified_at"] = fmt_ts(db.now())
    alarm["counted_for_window_total"] = True
    if outcome == "VERIFIED":
        alarm["counted_for_false_alarm"] = account_was_provisioned_at(account, alarm.get("occurred_at"))
    else:
        alarm["counted_for_false_alarm"] = False
    db.bump(alarm)
    return alarm


def entered_instant(alarm):
    return coerce_dt(alarm.get("entered_at_utc")) or coerce_dt(alarm.get("occurred_at"))


def within_verified_window(alarm):
    occurred_at = coerce_dt(alarm.get("occurred_at"))
    entered = entered_instant(alarm)
    if occurred_at is None or entered is None:
        return False
    return (occurred_at - timedelta(seconds=calc.VERIFIED_WINDOW_BEFORE_SECONDS)
            <= entered
            <= occurred_at + timedelta(seconds=calc.VERIFIED_WINDOW_AFTER_SECONDS))


def within_abort_window(alarm):
    entered = entered_instant(alarm)
    if entered is None:
        return False
    return db.now() < entered + timedelta(seconds=calc.ABORT_WINDOW_SECONDS)


def mass_cancel_count(alarm):
    """SCAFFOLD ERR_MASS_CANCEL_BLOCKED: the count of ABORTED or CLOSED dispatches
    for the alarm's monitoring ACCOUNT at or after the alarm's `occurred_at`.

    A closed REQUESTED dispatch counts exactly like an aborted DISPATCHED one, and
    the limit is three.
    """
    if alarm is None:
        return 0
    account_id = alarm.get("monitoring_account_id")
    alarm_occurred_at = coerce_dt(alarm.get("occurred_at"))
    alarm_ids = {a["id"] for a in db.state.alarm_events.values()
                 if a.get("monitoring_account_id") == account_id}
    count = 0
    for dispatch in db.state.dispatch_requests.values():
        if dispatch.get("alarm_event_id") not in alarm_ids:
            continue
        if dispatch.get("dispatch_status") not in ("ABORTED", "CLOSED"):
            continue
        requested_at = coerce_dt(dispatch.get("requested_at"))
        if alarm_occurred_at is not None and requested_at is not None and requested_at < alarm_occurred_at:
            continue
        count += 1
    return count


def maybe_raise_reduction_action(account):
    """A verification that pushes the recomputed ratio past the cap raises SERVICE_REQUIRED."""
    if account is None:
        return None
    reading = calc.false_alarm_ratio(account)
    if reading["ratio_percent"] > float(calc.KNOWN_ALARM_RATE_CAP_PERCENT):
        existing = queries.open_service_required_account(account["id"])
        if existing is None:
            return factory.make_reduction_action(account["id"], "SERVICE_REQUIRED")
    return None


# ---------------------------------------------------------------------------
# Assumption
# ---------------------------------------------------------------------------

def complete_assumption(request_row):
    contract = db.state.get("contracts", request_row["contract_id"])
    outgoing_id = contract.get("customer_id")
    incoming_id = request_row.get("incoming_customer_id")
    outgoing = db.state.get("customers", outgoing_id)
    incoming = db.state.get("customers", incoming_id)

    owner = queries.current_owner_for_contract(contract["id"])
    if owner is not None:
        owner["ownership_status"] = "SUPERSEDED"
        owner["ended_at"] = fmt_ts(db.now())
        db.bump(owner)

    contract["customer_id"] = incoming_id
    contract["contract_status"] = "ASSUMED"
    contract["assumption_count"] = contract.get("assumption_count", 0) + 1
    db.bump(contract)

    factory.make_contract_owner(contract["id"], incoming_id, request_row["id"])

    if outgoing is not None:
        outgoing["status"] = "ASSUMED"
        db.bump(outgoing)
    if incoming is not None:
        db.bump(incoming)

    account = queries.account_for_contract(contract["id"])
    if account is not None:
        account["provision_state"] = "PROVISIONED"
        db.bump(account)

    for site in queries.sites_for_contract(contract["id"]):
        if site.get("occupancy_status") == "OCCUPIED":
            site["occupancy_status"] = "VACATED"
            db.bump(site)

    request_row["completed_at"] = fmt_ts(db.now())
    request_row["request_status"] = "COMPLETED"
    db.bump(request_row)
    return request_row


# ---------------------------------------------------------------------------
# Rescission
# ---------------------------------------------------------------------------

def decide_rescission(request_row, outcome, approver_id):
    contract = db.state.get("contracts", request_row["contract_id"])
    if outcome == "DECLINED":
        request_row["request_status"] = "DECLINED"
        request_row["decided_at"] = fmt_ts(db.now())
        db.bump(request_row)
        return request_row

    # APPROVED
    if request_row.get("request_status") != "REQUESTED":
        raise ApiError("ERR_RESCISSION_WINDOW_CLOSED")
    funded_at = coerce_dt(contract.get("funded_at"))
    if funded_at is None or db.now() > add_days(funded_at, calc.RESCISSION_WINDOW_DAYS):
        raise ApiError("ERR_RESCISSION_WINDOW_CLOSED")
    if approver_id == request_row.get("operator_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_REQUIRED")

    dealer = db.state.get("dealers", contract.get("dealer_id"))
    calc.equipment_and_rescission_refund_floor(contract, dealer)
    if dealer is not None:
        db.bump(dealer)

    request_row["request_status"] = "APPROVED"
    request_row["approved_by"] = approver_id
    request_row["approved_at"] = fmt_ts(db.now())
    db.bump(request_row)

    if contract.get("contract_status") in ("ACTIVE", "DELINQUENT"):
        cancel_contract(contract, apply_sweep=False, apply_chargeback=False)
    return request_row


# ---------------------------------------------------------------------------
# Service windows
# ---------------------------------------------------------------------------

def _windows_overlap(start_a, minutes_a, start_b, minutes_b):
    end_a = start_a + timedelta(minutes=minutes_a)
    end_b = start_b + timedelta(minutes=minutes_b)
    return start_a < end_b and start_b < end_a


def technician_overlap(visit, technician_id, scheduled_at, minutes):
    visit_id = visit["id"] if visit is not None else None
    for other in db.state.service_visits.values():
        if other["id"] == visit_id:
            continue
        if other.get("technician_id") != technician_id:
            continue
        if other.get("visit_status") == "CANCELLED":
            continue
        other_start = coerce_dt(other.get("scheduled_at"))
        if other_start is None:
            continue
        other_minutes = other.get("allowed_duration_minutes", 60) or 60
        if _windows_overlap(scheduled_at, minutes, other_start, other_minutes):
            return True
    return False


def engineer_overlap(installation, engineer_id, scheduled_at, minutes):
    installation_id = installation["id"] if installation is not None else None
    for other in db.state.installations.values():
        if other["id"] == installation_id:
            continue
        if other.get("installation_engineer_id") != engineer_id:
            continue
        if other.get("install_status") == "FAILED":
            continue
        other_start = coerce_dt(other.get("scheduled_at"))
        if other_start is None:
            continue
        other_minutes = other.get("duration_minutes", 180) or 180
        if _windows_overlap(scheduled_at, minutes, other_start, other_minutes):
            return True
    return False


def warranty_status_at(contract, scheduled_at):
    activated_at = coerce_dt(contract.get("activated_at"))
    if activated_at is None:
        return False
    end = add_months(activated_at, contract.get("warranty_months", 6))
    return coerce_dt(scheduled_at) <= end