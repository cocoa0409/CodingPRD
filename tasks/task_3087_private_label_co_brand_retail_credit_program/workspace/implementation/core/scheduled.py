"""Scheduled effects run by the logical clock (PRD §2.5).

An advance is not merely a counter increment: it runs every effect that falls
due inside the advanced window, in chronological order — promotional expiries,
delinquency marks on missed due dates, and statement close/payment-due dating
on the account's cycle day.
"""
import calendar
from datetime import datetime, timedelta

from . import clock, domain
from .store import store


def _next_month(first_of_month: datetime) -> datetime:
    if first_of_month.month == 12:
        return first_of_month.replace(year=first_of_month.year + 1, month=1)
    return first_of_month.replace(month=first_of_month.month + 1)


def _clamped_close(first_of_month: datetime, cycle_day: int) -> datetime:
    last_day = calendar.monthrange(first_of_month.year, first_of_month.month)[1]
    return first_of_month.replace(day=min(int(cycle_day), last_day))


def _statement_close_instants(cycle_day, window_start: datetime, window_end: datetime):
    """Statement-close instants on the program's cycle day inside the window.

    A cycle_day of 29, 30 or 31 clamps to the last real day of shorter months.
    """
    if not cycle_day:
        return []
    out = []
    cursor = window_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    guard = 0
    while cursor <= window_end and guard < 400:
        close_at = _clamped_close(cursor, cycle_day)
        if window_start < close_at <= window_end:
            out.append(close_at)
        cursor = _next_month(cursor)
        guard += 1
    return out


def run_due_effects(window_start: datetime, window_end: datetime):
    """Fire every scheduled effect falling in (window_start, window_end].

    Promotional expiry is administered explicitly through the plan's own
    transition, which is guarded by the clock having reached the expiry
    instant (PRD §3.4); the advance runs the delinquency marks and the
    statement-close rollups (PRD §2.5).
    """
    events = []

    for account in store.accounts.values():
        if account.get("account_status") != "ACTIVE":
            continue
        due_text = store.payment_due.get(account["id"])
        if not due_text:
            continue
        try:
            due_at = clock.parse(due_text)
        except ValueError:
            continue
        pays_on = due_at + timedelta(days=1)
        if window_start < pays_on <= window_end:
            events.append((pays_on, 1, "delinquency", account))

    for program in store.programs.values():
        for close_at in _statement_close_instants(
            program.get("cycle_day"), window_start, window_end
        ):
            events.append((close_at, 2, "statement_close", program))

    for _, _, kind, entity in sorted(events, key=lambda item: (item[0], item[1])):
        if kind == "delinquency":
            _mark_delinquent(entity)
        elif kind == "statement_close":
            domain.refresh_program(entity)


def _mark_delinquent(account):
    if account.get("account_status") != "ACTIVE":
        return
    if account.get("outstanding_balance_cents", 0) <= 0:
        return
    account["account_status"] = "DELINQUENT"
    account["updated_at"] = clock.now_iso()