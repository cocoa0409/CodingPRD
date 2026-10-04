"""Business logic: fees, engraving sync, reminders, audit, cascades, disclosure."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

# ---------------------------------------------------------------------------
# Constants per SCAFFOLD §1.3
# ---------------------------------------------------------------------------
BASE_STANDARD_CENTS = 4000
BASE_PREMIUM_CENTS = 7500
BASE_LIFETIME_CENTS = 50000
TERM_MONTHS_STANDARD = 12
TERM_MONTHS_PREMIUM = 24
DEPENDENT_FACTOR = Decimal("0.5")
COGNITIVE_SURCHARGE_CENTS = 1000
PREMIUM_ORDER_DISCOUNT_PCT = Decimal("0.15")
LIFETIME_ORDER_DISCOUNT_PCT = Decimal("0.25")
RENEWAL_LEAD_DAYS = 30
RECORD_UPDATE_CYCLE_DAYS = 180
DAILY_ACCESS_SOFT_CAP = 10

SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Timestamp based on the logical clock (ISO 8601 with 3 fractional digits).

    The logical clock stores a coarse string (e.g. '2026-09-01T00:00:00Z'); we
    use it as the base for created_at values so everything is logically
    consistent. Precision is normalized to milliseconds.
    """
    return _normalize_ts(db.logical_now())


def _normalize_ts(s):
    dt = parse_dt(s)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string to aware datetime."""
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def logical_date():
    return parse_dt(db.logical_now()).date()


def add_months(d, months):
    """Add months to a date, clamping to month end."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    days_in_month = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, month=m, day=min(d.day, days_in_month))


def age_on(dob, on_date):
    return on_date.year - dob.year - (
        (on_date.month, on_date.day) < (dob.month, dob.day)
    )


def bump_member(member):
    member["version"] += 1
    member["updated_at"] = now_ts()


def append_audit(member_id, actor_role, actor_id, action, detail=None):
    ev = {
        "id": new_id(),
        "created_at": now_ts(),
        "member_id": member_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "detail": detail or {},
    }
    db.audit_events[ev["id"]] = ev
    return ev


def has_active_guardian_link(member_id):
    return any(
        gl
        for gl in db.guardian_links.values()
        if gl["member_id"] == member_id and gl["status"] == "ACTIVE"
    )


def recompute_cognitive(member):
    """has_cognitive_condition = any VERIFIED item with condition_kind == COGNITIVE."""
    flag = any(
        it
        for it in db.record_items.values()
        if it["member_id"] == member["id"]
        and it["status"] == "VERIFIED"
        and it.get("condition_kind") == "COGNITIVE"
    )
    member["has_cognitive_condition"] = flag


# ---------------------------------------------------------------------------
# Membership fee (§3.1)
# ---------------------------------------------------------------------------
def compute_membership_fee(member):
    tier = member["membership_tier"]
    if tier == "STANDARD":
        base = BASE_STANDARD_CENTS
    elif tier == "PREMIUM":
        base = BASE_PREMIUM_CENTS
    else:
        base = BASE_LIFETIME_CENTS
    fee = base
    if has_active_guardian_link(member["id"]):
        fee = int(
            (Decimal(base) * DEPENDENT_FACTOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    if member.get("has_cognitive_condition"):
        fee += COGNITIVE_SURCHARGE_CENTS
    return fee


def term_months(tier):
    if tier == "STANDARD":
        return TERM_MONTHS_STANDARD
    if tier == "PREMIUM":
        return TERM_MONTHS_PREMIUM
    return None


# ---------------------------------------------------------------------------
# Reminders (§3.7)
# ---------------------------------------------------------------------------
def create_reminder(member_id, kind, due_on):
    r = {
        "id": new_id(),
        "created_at": now_ts(),
        "member_id": member_id,
        "reminder_kind": kind,
        "due_on": due_on,
        "sent_on": None,
        "status": "PENDING",
    }
    db.reminders[r["id"]] = r
    return r


def cancel_pending_reminders(member_id, kinds=None):
    for r in db.reminders.values():
        if r["member_id"] == member_id and r["status"] == "PENDING":
            if kinds is None or r["reminder_kind"] in kinds:
                r["status"] = "CANCELLED"


def reanchor_renewal_reminder(member):
    cancel_pending_reminders(member["id"], {"RENEWAL"})
    if member["membership_tier"] != "LIFETIME" and member["expires_on"]:
        due = (parse_date(member["expires_on"]) - timedelta(days=RENEWAL_LEAD_DAYS)).isoformat()
        create_reminder(member["id"], "RENEWAL", due)


def reanchor_record_update_reminder(member):
    """due_on = max(created_at) over items in {VERIFIED, PENDING_VERIFICATION} + 180 days."""
    cancel_pending_reminders(member["id"], {"RECORD_UPDATE"})
    items = [
        it
        for it in db.record_items.values()
        if it["member_id"] == member["id"]
        and it["status"] in ("VERIFIED", "PENDING_VERIFICATION")
    ]
    if items:
        last = max(parse_dt(it["created_at"]) for it in items)
    else:
        last = parse_dt(member["created_at"])
    due = (last.date() + timedelta(days=RECORD_UPDATE_CYCLE_DAYS)).isoformat()
    create_reminder(member["id"], "RECORD_UPDATE", due)


# ---------------------------------------------------------------------------
# Engraving sync (§3.5)
# ---------------------------------------------------------------------------
def generate_engraving_text(member, product):
    items = [
        it
        for it in db.record_items.values()
        if it["member_id"] == member["id"] and it["status"] == "VERIFIED"
    ]
    items.sort(key=lambda it: (SEVERITY_RANK[it["severity"]], it["created_at"]))
    labels = [it["label"] for it in items]
    text = " | ".join(labels)
    max_chars = product["max_engrave_chars"]
    while labels and len(text) > max_chars:
        labels.pop()  # drop lowest-severity (tail) line
        text = " | ".join(labels)
    return text


def resync_pending_sync_orders(member):
    """On record change: re-sync all PENDING SYNC_WITH_RECORD orders."""
    for o in db.orders.values():
        if (
            o["member_id"] == member["id"]
            and o["status"] == "PENDING"
            and o["engrave_mode"] == "SYNC_WITH_RECORD"
        ):
            product = db.products[o["product_id"]]
            o["engraving_text"] = generate_engraving_text(member, product)
            o["synced_revision"] = member["record_revision"]
            o["updated_at"] = now_ts()
            o["version"] += 1


def bump_record_revision(member):
    member["record_revision"] += 1


def handle_record_change(member):
    """Common side effects for record item create/verify/supersede."""
    bump_record_revision(member)
    recompute_cognitive(member)
    reanchor_record_update_reminder(member)
    resync_pending_sync_orders(member)


# ---------------------------------------------------------------------------
# Order pricing (§3.4)
# ---------------------------------------------------------------------------
def compute_order_price(member, product, engrave_mode):
    base = product["base_price_cents"]
    tier = member["membership_tier"]
    if tier == "PREMIUM":
        return int(
            (Decimal(base) * (Decimal(1) - PREMIUM_ORDER_DISCOUNT_PCT)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    if tier == "LIFETIME":
        if engrave_mode == "SYNC_WITH_RECORD" and not member["first_lifetime_sync_order_consumed"]:
            return 0
        return int(
            (Decimal(base) * (Decimal(1) - LIFETIME_ORDER_DISCOUNT_PCT)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return base
