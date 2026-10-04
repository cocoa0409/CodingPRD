"""Date/time, parsing, working-day, and pagination helpers."""
import re
import uuid
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from db import db, iso_utc, now_utc
from errors import ApiError, ERR_INVALID_REQUEST

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 timestamp; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 string")
    m = _ISO_RE.match(value)
    if not m:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_date(dt: datetime, tz_name: str) -> date:
    return dt.astimezone(ZoneInfo(tz_name)).date()


def is_working_day(d: date, terminal_id: str, contract: dict, terminal: dict) -> bool:
    """Working day per PRD §3.2: not Sunday, not a terminal holiday, not Saturday
    unless the contract's saturday_counts_as_free_day is true."""
    # Python weekday(): Monday=0 ... Sunday=6
    if d.weekday() == 6:  # Sunday
        return False
    if d.weekday() == 5 and not contract.get("saturday_counts_as_free_day", False):
        return False
    for h in db.holidays.values():
        # Per PRD §3.2: holiday_date is a UTC calendar date whose time component
        # is ignored — compare against UTC date directly, not terminal-local.
        if h["terminal_id"] == terminal_id and h["holiday_date"].date() == d:
            return False
    return True


def slot_day_is_operating(d: date, terminal: dict) -> bool:
    """Slots exist on terminal working days — not Sundays, not holidays, and
    weekends closed when gate_closed_weekends is true."""
    if d.weekday() == 6:
        return False
    if terminal.get("gate_closed_weekends", True) and d.weekday() == 5:
        return False
    for h in db.holidays.values():
        if h["terminal_id"] == terminal["id"] and h["holiday_date"].date() == d:
            return False
    return True


def hold_day_set(container: dict, kind: str, terminal_tz: str):
    """Return set of local dates on which the container carried an active hold
    of the relevant family for the given accrual phase.

    kind = "DEMURRAGE" -> CUSTOMS_HOLD / USDA_HOLD
    kind = "DETENTION" -> CHASSIS_SHORTAGE
    A day d is excluded when placed_date <= d < released_date (if released),
    i.e. the placed day is a hold day; the release day is not.
    """
    codes = {"CUSTOMS_HOLD", "USDA_HOLD"} if kind == "DEMURRAGE" else {"CHASSIS_SHORTAGE"}
    days = set()
    for h in container.get("hold_flags", []):
        if h["code"] not in codes:
            continue
        placed_d = local_date(h["placed_ts"], terminal_tz)
        if h.get("released_ts"):
            released_d = local_date(h["released_ts"], terminal_tz)
        else:
            # Active hold: covers placed day forward without bound; we include
            # a generous horizon so the accrual window is covered.
            released_d = placed_d + timedelta(days=3700)
        d = placed_d
        while d < released_d:
            days.add(d)
            d += timedelta(days=1)
    return days


def compute_accrual(container: dict, contract: dict, terminal: dict, kind: str,
                    end_local_date: date):
    """Compute billable days and amount for one accrual family.

    Returns (billable_days, amount_cents, window_from_date, window_to_date).
    window dates are `date` objects or None when no billable days.
    """
    tz = terminal["timezone"]
    if kind == "DEMURRAGE":
        anchor_ts = container["available_ts"]
        free_days = contract["demurrage_free_days"]
        schedule = contract["demurrage_rate_schedule"]
    else:
        anchor_ts = container["gate_out_ts"]
        free_days = contract["detention_free_days"]
        schedule = contract["detention_rate_schedule"]
    anchor_d = local_date(anchor_ts, tz)
    hold_days = hold_day_set(container, kind, tz)

    # Walk calendar days strictly after the anchor, up to end_local_date.
    free_remaining = free_days
    billable_dates = []
    d = anchor_d + timedelta(days=1)
    # Hard bound the scan to avoid infinite loops on degenerate input.
    limit_d = max(end_local_date, anchor_d) + timedelta(days=3700)
    while d <= limit_d:
        if d in hold_days:
            d += timedelta(days=1)
            continue
        if is_working_day(d, terminal["id"], contract, terminal):
            if free_remaining > 0:
                free_remaining -= 1
            else:
                if d <= end_local_date:
                    billable_dates.append(d)
                else:
                    break
        d += timedelta(days=1)

    n = len(billable_dates)
    amount = 0
    for k in range(1, n + 1):
        amount += marginal_rate(kind, schedule, k)
    window_from = billable_dates[0] if billable_dates else None
    window_to = billable_dates[-1] if billable_dates else None
    return n, amount, window_from, window_to


def marginal_rate(kind: str, schedule: str, k: int) -> int:
    if kind == "DEMURRAGE":
        if schedule == "STANDARD":
            if k <= 3:
                return 15000
            if k <= 7:
                return 30000
            return 45000
        # EXTENDED_TIERED
        if k <= 5:
            return 12000
        if k <= 10:
            return 24000
        if k <= 15:
            return 36000
        return 50000
    else:
        if schedule == "STANDARD":
            if k <= 4:
                return 9000
            if k <= 9:
                return 18000
            return 27000
        if k <= 6:
            return 7000
        if k <= 13:
            return 15000
        return 22000


def aging_bucket(invoice: dict) -> str:
    if invoice["balance_due_cents"] == 0:
        return "CURRENT"
    due = invoice["due_at"]
    current = now_utc()
    days_past_due = (current.date() - due.date()).days
    if days_past_due <= 0:
        return "CURRENT"
    if days_past_due <= 30:
        return "DAYS_1_30"
    if days_past_due <= 60:
        return "DAYS_31_60"
    return "DAYS_61_PLUS"


def recompute_invoice_derived(invoice: dict):
    """Recompute credit_total, paid_total, balance_due from waivers/payments."""
    credit_total = sum(
        w["amount_cents"] for w in db.waivers.values()
        if w["invoice_id"] == invoice["id"] and w["status"] == "APPLIED"
    )
    paid_total = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["invoice_id"] == invoice["id"] and p["status"] == "SETTLED"
    )
    invoice["credit_total_cents"] = credit_total
    invoice["paid_total_cents"] = paid_total
    invoice["balance_due_cents"] = (
        invoice["gross_amount_cents"] - credit_total - paid_total
    )
    invoice["aging_bucket"] = aging_bucket(invoice)


def recompute_account_outstanding(account_id: str):
    acct = db.accounts.get(account_id)
    if not acct:
        return
    total = 0
    for inv in db.invoices.values():
        if inv["customer_account_id"] == account_id and inv["status"] in (
            "ISSUED", "PARTIALLY_PAID", "DISPUTED"
        ):
            recompute_invoice_derived(inv)
            total += inv["balance_due_cents"]
    acct["outstanding_balance_cents"] = total


def aging_posture_sweep():
    """Per PRD §2.7 — runs on every clock advance and after every
    payment/credit mutation."""
    for acct in db.accounts.values():
        exposure = 0
        for inv in db.invoices.values():
            if inv["customer_account_id"] != acct["id"]:
                continue
            if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
                continue
            recompute_invoice_derived(inv)
            if inv["aging_bucket"] == "DAYS_61_PLUS":
                exposure += inv["balance_due_cents"]
        counter = db.consecutive_61_plus.get(acct["id"], 0)
        if exposure > 0:
            counter += 1
        else:
            counter = 0
        db.consecutive_61_plus[acct["id"]] = counter
        if counter >= 7 and acct["status"] == "ACTIVE":
            acct["status"] = "SUSPENDED"
            acct["credit_hold"] = True
            touch(acct)
        elif exposure == 0 and acct["status"] == "SUSPENDED":
            acct["status"] = "ACTIVE"
            acct["credit_hold"] = False
            touch(acct)


def dispute_escalation_sweep():
    current = now_utc()
    for dsp in db.disputes.values():
        if dsp["status"] in ("SUBMITTED", "UNDER_REVIEW") and not dsp["escalated"]:
            if current > dsp["sla_due_at"]:
                dsp["escalated"] = True
                touch(dsp)


def contract_expiry_sweep():
    current_date = now_utc().date()
    for ctr in db.contracts.values():
        if ctr["status"] == "ACTIVE" and current_date > ctr["effective_to"].date():
            ctr["status"] = "EXPIRED"
            touch(ctr)


def touch(entity: dict):
    entity["updated_at"] = iso_utc(now_utc())
    entity["version"] = entity.get("version", 1) + 1


def new_common():
    return {
        "id": str(uuid.uuid4()),
        "created_at": iso_utc(now_utc()),
        "updated_at": iso_utc(now_utc()),
        "version": 1,
    }


def new_ledger():
    return {"id": str(uuid.uuid4()), "created_at": iso_utc(now_utc())}


def parse_pagination(args):
    """limit/offset with defaults; bounds-checked per PRD §2.3."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset
