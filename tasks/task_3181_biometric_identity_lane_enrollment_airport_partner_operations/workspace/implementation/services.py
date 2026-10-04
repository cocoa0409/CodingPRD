"""Business logic services: risk scoring, cascades, sweeps, pricing, checks.

All constants come from SCAFFOLD/PRD:
  VELOCITY_REJECT_THRESHOLD = 3
  RISK_REVIEW_THRESHOLD = 15
  RISK_BLOCK_THRESHOLD = 20
  AMBASSADOR_SEAT_HOURS = 4
  ESCORT_WINDOW_MINUTES = 15
  BIOMETRIC_RETENTION_DAYS = 30
  PAST_DUE_CANCEL_DAYS = 7
  INDIVIDUAL_PRICE_CENTS = 18900
  FAMILY_BASE_PRICE_CENTS = 18900
  FAMILY_MEMBER_PRICE_CENTS = 9900
  VENUE_MINIMUM_CENTS, VENUE_REVENUE_SHARE, VENUE_BASE_SEAT_CENTS,
  VENUE_PER_EVENT_CENTS, VENUE_EVENT_THRESHOLD  (venue payout constants)
  KIOSK_COMPLETION_WINDOW = 24h
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, fmt_dt, _parse_dt, _parse_date
from errors import ApiError
from models import touch, new_entity

# ---- calc constants ----
VELOCITY_REJECT_THRESHOLD = 3
RISK_REVIEW_THRESHOLD = 15
RISK_BLOCK_THRESHOLD = 20
AMBASSADOR_SEAT_HOURS = 4
ESCORT_WINDOW_MINUTES = 15
BIOMETRIC_RETENTION_DAYS = 30
PAST_DUE_CANCEL_DAYS = 7
INDIVIDUAL_PRICE_CENTS = 18900
FAMILY_BASE_PRICE_CENTS = 18900
FAMILY_MEMBER_PRICE_CENTS = 9900
# Venue payout constants (venue_event_payout variant). The PRD/scaffold name
# the pieces but do not pin numeric values; we pin them here and apply the
# formula exactly as described.
VENUE_MINIMUM_CENTS = 50000
VENUE_REVENUE_SHARE = Decimal("0.20")
VENUE_BASE_SEAT_CENTS = 500
VENUE_PER_EVENT_CENTS = 100000
VENUE_EVENT_THRESHOLD = 5
MAX_RATE = Decimal("0.30")


# ---------- helpers ----------

def round_half_up_2(value):
    """Round a Decimal to 2 places, ROUND_HALF_UP, return Decimal."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_0(value):
    """Round a Decimal to 0 places, ROUND_HALF_UP, return int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_member(member_id):
    m = store.members.get(member_id)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    return m


def member_age_years(member, on_date):
    """Full years between member.date_of_birth and on_date (birthday reached this year counts)."""
    dob = _parse_date(member["date_of_birth"])
    age = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        age -= 1
    return age


def recompute_reject_count_90d(member):
    """Count this member's enrollments that flipped to REJECTED within the trailing 90 logical days.

    We track rejection events with timestamps on the enrollment record
    ('rejected_at'), so the trailing window is recomputed here.
    """
    now = store.now()
    window_start = now - timedelta(days=90)
    count = 0
    for e in store.enrollments.values():
        if e["member_id"] != member["id"]:
            continue
        rat = e.get("rejected_at")
        if rat is None:
            continue
        if _parse_dt(rat) >= window_start:
            count += 1
    member["document_reject_count_90d"] = count
    return count


def mark_enrollment_rejected(enrollment):
    """Flip an enrollment to REJECTED, stamp it, bump the member's reject count."""
    enrollment["status"] = "REJECTED"
    enrollment["rejected_at"] = fmt_dt(store.now())
    touch(enrollment)
    member = store.members.get(enrollment["member_id"])
    if member is not None:
        recompute_reject_count_90d(member)
        touch(member)


def doc_format_ok(document_number):
    """MOD-7 checksum: sum of digits of the numeric portion must be divisible by 7."""
    digits = [c for c in str(document_number) if c.isdigit()]
    total = sum(int(c) for c in digits)
    return total % 7 == 0


def compute_risk(member, enrollment):
    """Return (score, flags) per calc risk_score_update."""
    flags = []
    score = 0
    if member.get("document_reject_count_90d", 0) >= VELOCITY_REJECT_THRESHOLD:
        score += 8
        flags.append("VELOCITY")
    pair = (enrollment["document_number"], member["date_of_birth"])
    if pair in store.watchlist:
        score += 8
        flags.append("WATCHLIST")
    if not doc_format_ok(enrollment["document_number"]):
        score += 4
        flags.append("DOC_FORMAT")
    if enrollment.get("biometric_capture_ok") is False:
        score += 5
        flags.append("SELFIE_MISMATCH")
    return max(score, 0), flags


def subscription_price_cents(plan, discount):
    """price_cents = round(base * discount_factor, 0); both plans pin to discounted base."""
    base = INDIVIDUAL_PRICE_CENTS if plan == "INDIVIDUAL" else FAMILY_BASE_PRICE_CENTS
    factor = Decimal(1)
    if discount is not None:
        factor = Decimal(100 - int(discount["percent_off"])) / Decimal(100)
    return round_half_up_0(Decimal(base) * factor)


def invoice_amount_cents(subscription):
    """Invoice total: discounted base + per-dependant lines, each line rounded half-up first."""
    discount = None
    if subscription.get("partner_discount_id"):
        discount = store.partner_discounts.get(subscription["partner_discount_id"])
    factor = Decimal(1)
    if discount is not None:
        factor = Decimal(100 - int(discount["percent_off"])) / Decimal(100)
    base = INDIVIDUAL_PRICE_CENTS if subscription["plan"] == "INDIVIDUAL" else FAMILY_BASE_PRICE_CENTS
    discounted_base = round_half_up_0(Decimal(base) * factor)
    total = discounted_base
    if subscription["plan"] == "FAMILY":
        group = find_family_group_for_subscription(subscription["id"])
        dependants = 0
        if group is not None:
            dependants = max(0, group["slots_used"] - 1)
        for _ in range(dependants):
            total += round_half_up_0(Decimal(FAMILY_MEMBER_PRICE_CENTS) * factor)
    return total


def find_family_group_for_subscription(subscription_id):
    for g in store.family_groups.values():
        if g["primary_subscription_id"] == subscription_id and g["status"] == "ACTIVE":
            return g
    return None


def active_agreement_for_airport(airport_id):
    """Return the airport's DRAFT-or-ACTIVE agreement if one exists."""
    for a in store.partner_agreements.values():
        if a["airport_id"] == airport_id and a["status"] in ("DRAFT", "ACTIVE"):
            return a
    return None


def agreement_by_status(airport_id, statuses):
    for a in store.partner_agreements.values():
        if a["airport_id"] == airport_id and a["status"] in statuses:
            return a
    return None


def recompute_lane_capacity(agreement):
    """lane_capacity = sum of capacity_hours across the agreement's OPEN or MAINTENANCE lanes."""
    total = 0
    for lane in store.lanes.values():
        if lane["agreement_id"] == agreement["id"] and lane["status"] in ("OPEN", "MAINTENANCE"):
            total += lane["capacity_hours"]
    agreement["lane_capacity"] = total
    return total


# ---------- cascades ----------

def cascade_member_termination(member, actor):
    """Full termination cascade (dispute-confirmed or admin termination)."""
    member["status"] = "TERMINATED"
    # cancel subscription with voluntary-cancel semantics
    sub = None
    if member.get("subscription_id"):
        sub = store.subscriptions.get(member["subscription_id"])
    if sub is not None and sub["status"] in ("ACTIVE", "PAST_DUE"):
        cancel_subscription(sub, actor=actor, retention_note="Member terminated")
    # detach from family group
    fg_id = member.get("family_group_id")
    if fg_id:
        group = store.family_groups.get(fg_id)
        if group is not None and group["status"] == "ACTIVE":
            group["slots_used"] = max(0, group["slots_used"] - 1)
            touch(group)
        member["family_group_id"] = None
    # retention scheduling (only if cancel_subscription didn't already schedule)
    if not member.get("deletion_due_at"):
        schedule_retention(member, actor, note="Member terminated")
    touch(member)


def schedule_retention(member, actor, note):
    member["deletion_due_at"] = fmt_dt(store.now() + timedelta(days=BIOMETRIC_RETENTION_DAYS))
    append_retention_log(member["id"], "DELETION_SCHEDULED", actor, note)


def append_retention_log(member_id, action, actor, note):
    entry = new_entity(with_version=False)
    entry["member_id"] = member_id
    entry["action"] = action
    entry["actor_user_id"] = actor
    entry["note"] = note
    store.biometric_retention_logs[entry["id"]] = entry
    return entry


def cancel_subscription(subscription, actor, retention_note="Subscription cancelled"):
    """Voluntary-cancel semantics: family group dissolved, discount detached,
    retention scheduled on the member, DUE invoices voided."""
    subscription["status"] = "CANCELLED"
    touch(subscription)
    # dissolve family group
    group = find_family_group_for_subscription(subscription["id"])
    if group is not None:
        dissolve_family_group(group)
    # detach discount (redemptions_used NOT decremented)
    if subscription.get("partner_discount_id"):
        subscription["partner_discount_id"] = None
    # retention scheduling on the member
    member = store.members.get(subscription["member_id"])
    if member is not None:
        schedule_retention(member, actor, note=retention_note)
        touch(member)
    # void outstanding invoices
    for inv in store.subscription_invoices.values():
        if inv["subscription_id"] == subscription["id"] and inv["status"] == "DUE":
            inv["status"] = "VOID"
            touch(inv)


def dissolve_family_group(group):
    group["status"] = "DISSOLVED"
    for m in store.members.values():
        if m.get("family_group_id") == group["id"]:
            m["family_group_id"] = None
            touch(m)
    group["slots_used"] = 0
    touch(group)


def reject_draft_enrollments(member):
    """Suspend cascade: all in-flight DRAFT enrollments of the member -> REJECTED."""
    for e in store.enrollments.values():
        if e["member_id"] == member["id"] and e["status"] == "DRAFT":
            mark_enrollment_rejected(e)


def _apply_plan_now(subscription):
    """Apply the subscription's current plan: recompute price and create a
    FamilyGroup if the (new) plan is FAMILY and no active group exists."""
    discount = None
    if subscription.get("partner_discount_id"):
        discount = store.partner_discounts.get(subscription["partner_discount_id"])
    subscription["price_cents"] = subscription_price_cents(subscription["plan"], discount)
    if subscription["plan"] == "FAMILY":
        if find_family_group_for_subscription(subscription["id"]) is None:
            create_family_group(subscription)


def create_family_group(subscription):
    group = new_entity()
    group["primary_subscription_id"] = subscription["id"]
    group["slots_total"] = 3
    group["slots_used"] = 1
    group["status"] = "ACTIVE"
    store.family_groups[group["id"]] = group
    member = store.members.get(subscription["member_id"])
    if member is not None:
        member["family_group_id"] = group["id"]
        touch(member)
    return group


def member_activation_on_completion(member):
    """Member PENDING_ENROLLMENT -> ACTIVE with subscription initialization."""
    member["status"] = "ACTIVE"
    if member.get("verification_level") in (None,):
        member["verification_level"] = "NONE"
    if member.get("verification_level") == "NONE":
        member["verification_level"] = "BIOMETRIC_ID"
    touch(member)
    sub = None
    if member.get("subscription_id"):
        sub = store.subscriptions.get(member["subscription_id"])
    if sub is not None:
        now = store.now()
        sub["status"] = "ACTIVE"
        sub["current_period_start"] = fmt_dt(now)
        sub["current_period_end"] = fmt_dt(now + timedelta(days=30))
        touch(sub)


# ---------- daily sweep ----------

def run_daily_sweep():
    """Runs when the logical clock crosses a date boundary."""
    now = store.now()
    # past-due cancellation: clock >= past_due_since + 7 days
    for sub in list(store.subscriptions.values()):
        if sub["status"] == "PAST_DUE" and sub.get("past_due_since"):
            deadline = _parse_dt(sub["past_due_since"]) + timedelta(days=PAST_DUE_CANCEL_DAYS)
            if now >= deadline:
                cancel_subscription(sub, actor="system", retention_note="Past-due cancellation")
    # escort expiry: PENDING and clock > expires_at
    for lv in list(store.lane_verifications.values()):
        if lv["escort_status"] == "PENDING" and now > _parse_dt(lv["expires_at"]):
            lv["escort_status"] = "EXPIRED"
            touch(lv)
    # retention purge: clock > deletion_due_at (strictly after)
    for member in list(store.members.values()):
        due = member.get("deletion_due_at")
        if due and now > _parse_dt(due):
            member["deletion_due_at"] = None
            store.purged_members.add(member["id"])
            append_retention_log(member["id"], "DELETED", "system", "Retention period elapsed")
            touch(member)
    # agreement expiry: ACTIVE and clock >= effective_to
    for ag in list(store.partner_agreements.values()):
        if ag["status"] == "ACTIVE" and ag.get("effective_to") and now >= _parse_dt(ag["effective_to"]):
            ag["status"] = "EXPIRED"
            touch(ag)
            close_all_lanes_of_agreement(ag)


def close_all_lanes_of_agreement(agreement):
    for lane in store.lanes.values():
        if lane["agreement_id"] == agreement["id"] and lane["status"] in ("PLANNED", "OPEN", "MAINTENANCE"):
            lane["status"] = "CLOSED"
            touch(lane)
    agreement["lane_capacity"] = 0
