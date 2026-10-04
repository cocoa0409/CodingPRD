from datetime import timedelta

from core import (
    STORE, CLOCK, now, touch, stamp_new, stamp_new_lean, new_id, fmt_dt, fmt_date, parse_dt,
    ApiError, err_invalid_state,
    HOLD_TTL_MINUTES, LOCK_MINUTES_BEFORE_START, NO_SHOW_GRACE_MINUTES,
    CANCELLATION_WINDOW_MINUTES, STRIKE_WINDOW_DAYS, SUSPENSION_THRESHOLD,
    SUSPENSION_DAYS, REJOIN_WAIT_DAYS, FLAG_LEVEL, POINTS_PER_DOLLAR,
    ADMISSION_POINTS, STUDIO_CONTRACT_RATE_CENTS, DEFAULT_DISPLACEMENT_CAP_PCT,
    WEEK_DAYS, CYCLE_DAYS, CHECKIN_EARLY_MINUTES, CHECKIN_LATE_MINUTES,
)


# ================= Week / cycle arithmetic =================

def week_index_at(sub, when):
    """0-based program-week index of `when` for a subscription (clamped >= 0)."""
    anchor = parse_dt(sub["cycle_anchor_date"] + "T00:00:00Z")
    delta_days = (when - anchor).total_seconds() / 86400.0
    if delta_days < 0:
        return 0
    return int(delta_days // WEEK_DAYS)


def week_start(sub, k):
    anchor = parse_dt(sub["cycle_anchor_date"] + "T00:00:00Z")
    return anchor + timedelta(days=WEEK_DAYS * k)


def week_end(sub, k):
    return week_start(sub, k + 1)


def bucket_posture(bucket):
    if bucket.get("force_expired"):
        return "EXPIRED"
    sub = STORE["subscriptions"][bucket["subscription_id"]]
    if now() >= week_end(sub, bucket["week_index"]):
        return "EXPIRED"
    if credits_available(bucket) <= 0:
        return "EXHAUSTED"
    return "OPEN"


def credits_available(bucket):
    return max(0, bucket["base_granted"] + bucket["rollover_in"] - bucket["credits_used"])


def create_bucket(sub, k):
    """Create bucket for week k (must not exist). Applies grant + rollover rules."""
    plan = STORE["plans"][sub["plan_id"]]
    prev = find_bucket(sub["id"], k - 1)
    rollover_in = 0
    if prev is not None:
        rollover_in = max(
            0,
            min(prev["base_granted"] + prev["rollover_in"] - prev["credits_used"],
                plan["max_rollover_credits"]),
        )
    paused = sub["status"] == "PAUSED"
    base_granted = 0 if paused else plan["weekly_reservation_quota"]
    bucket = {
        "subscription_id": sub["id"],
        "week_index": k,
        "base_granted": base_granted,
        "rollover_in": rollover_in,
        "credits_used": 0,
        "force_expired": False,
    }
    stamp_new(bucket)
    STORE["buckets"][bucket["id"]] = bucket
    return bucket


def find_bucket(subscription_id, week_index):
    for b in STORE["buckets"].values():
        if b["subscription_id"] == subscription_id and b["week_index"] == week_index:
            return b
    return None


def ensure_buckets_up_to(sub, target_index):
    """Lazily materialize buckets from the highest existing week through target_index."""
    existing = [b for b in STORE["buckets"].values() if b["subscription_id"] == sub["id"]]
    highest = max((b["week_index"] for b in existing), default=-1)
    for k in range(highest + 1, target_index + 1):
        create_bucket(sub, k)


# ================= Strike window / suspension ladder =================

def expire_strikes_for_member(member_id):
    """Lazy expiry of out-of-window strikes for one member."""
    n = now()
    for s in STORE["strikes"].values():
        if s["member_id"] == member_id and s["status"] == "ACTIVE" and parse_dt(s["expires_at"]) <= n:
            s["status"] = "EXPIRED"
            touch(s)


def expire_strikes_all():
    n = now()
    for s in STORE["strikes"].values():
        if s["status"] == "ACTIVE" and parse_dt(s["expires_at"]) <= n:
            s["status"] = "EXPIRED"
            touch(s)


def active_strike_count(member_id):
    n = now()
    return sum(
        1 for s in STORE["strikes"].values()
        if s["member_id"] == member_id and s["status"] == "ACTIVE"
        and parse_dt(s["expires_at"]) > n
    )


def loyalty_balance(member_id):
    return sum(e["points"] for e in STORE["ledger"].values() if e["member_id"] == member_id)


def member_view(member):
    expire_strikes_for_member(member["id"])
    out = dict(member)
    out["loyalty_points_balance"] = loyalty_balance(member["id"])
    out["no_show_strikes_active"] = active_strike_count(member["id"])
    out.pop("_suspension_paused", None)
    return out


def suspend_member(member):
    """Member ACTIVE -> SUSPENDED with full cascade."""
    n = now()
    member["status"] = "SUSPENDED"
    suspended_until = n + timedelta(days=SUSPENSION_DAYS)
    member["suspended_until"] = fmt_dt(suspended_until)
    touch(member)
    # Cascade link 1: cancel HELD/CONFIRMED reservations, refund only if bucket OPEN
    for r in list(STORE["reservations"].values()):
        if r["member_id"] == member["id"] and r["status"] in ("HELD", "CONFIRMED"):
            cancel_reservation_system(r, refund_postures=("OPEN",))
    # Cascade link 2: force-pause ACTIVE subscription aligned to suspension
    for sub in STORE["subscriptions"].values():
        if sub["member_id"] == member["id"] and sub["status"] == "ACTIVE":
            sub["status"] = "PAUSED"
            sub["paused_at"] = fmt_dt(n)
            sub["pause_resume_at"] = member["suspended_until"]
            sub["_suspension_paused"] = True
            touch(sub)


def unsuspend_member(member):
    """Member SUSPENDED -> ACTIVE; suspension-driven pause auto-resumes."""
    member["status"] = "ACTIVE"
    old_until = member.get("suspended_until")
    member["suspended_until"] = None
    touch(member)
    for sub in STORE["subscriptions"].values():
        if (
            sub["member_id"] == member["id"]
            and sub["status"] == "PAUSED"
            and sub.get("pause_resume_at") is not None
            and old_until is not None
            and sub["pause_resume_at"] == old_until
            and sub.get("_suspension_paused")
        ):
            resume_subscription(sub, suspension_resume=True)


# ================= Subscription transitions =================

def resume_subscription(sub, suspension_resume=False):
    """PAUSED -> ACTIVE, clearing pause fields and applying mid-week top-up."""
    n = now()
    sub.pop("_suspension_paused", None)
    sub["status"] = "ACTIVE"
    sub["paused_at"] = None
    sub["pause_resume_at"] = None
    touch(sub)
    # Mid-week top-up: resume always restores the full weekly quota for the
    # current week (ceil((7-d)/7) == 1 for d in 0..6), credited to base_granted.
    plan = STORE["plans"][sub["plan_id"]]
    k = week_index_at(sub, n)
    ensure_buckets_up_to(sub, k)
    bucket = find_bucket(sub["id"], k)
    if bucket is not None and not bucket.get("force_expired") and n < week_end(sub, k):
        # Only top up if the bucket was granted at zero because of a pause,
        # i.e. base_granted below the plan quota for a live week.
        if bucket["base_granted"] < plan["weekly_reservation_quota"]:
            bucket["base_granted"] += plan["weekly_reservation_quota"] - bucket["base_granted"]
            touch(bucket)


def cancel_subscription(sub):
    """ACTIVE|PAUSED -> CANCELLED with cascades."""
    n = now()
    sub["status"] = "CANCELLED"
    sub["cancelled_at"] = fmt_dt(n)
    sub["rejoin_locked_until"] = fmt_dt(n + timedelta(days=REJOIN_WAIT_DAYS))
    sub["paused_at"] = None
    sub["pause_resume_at"] = None
    sub.pop("_suspension_paused", None)
    touch(sub)
    # Cascade: cancel HELD/CONFIRMED reservations with refund per rule
    for r in list(STORE["reservations"].values()):
        if r["subscription_id"] == sub["id"] and r["status"] in ("HELD", "CONFIRMED"):
            cancel_reservation_system(r, refund_postures=("OPEN", "EXHAUSTED"))
    # Every bucket of the cancelled subscription -> EXPIRED
    for b in STORE["buckets"].values():
        if b["subscription_id"] == sub["id"] and not b.get("force_expired"):
            b["force_expired"] = True
            touch(b)


def subscription_view(sub):
    out = dict(sub)
    out["current_cycle_index"] = current_cycle_index(sub)
    out.pop("_suspension_paused", None)
    return out


def current_cycle_index(sub):
    anchor = parse_dt(sub["cycle_anchor_date"] + "T00:00:00Z")
    delta_days = (now() - anchor).total_seconds() / 86400.0
    if delta_days < 0:
        return 0
    return int(delta_days // CYCLE_DAYS)


def sync_pause_cycle(sub):
    """Reset pause_count_in_cycle when the clock has crossed into a new cycle."""
    idx = current_cycle_index(sub)
    if idx != sub.get("_pause_cycle_index"):
        sub["_pause_cycle_index"] = idx
        sub["pause_count_in_cycle"] = 0


# ================= Reservation transitions =================

def bucket_view(bucket):
    out = dict(bucket)
    out["credits_available"] = credits_available(bucket)
    out["posture"] = bucket_posture(bucket)
    out.pop("force_expired", None)
    return out


def release_seat(reservation):
    showtime = STORE["showtimes"].get(reservation["showtime_id"])
    if showtime is not None and showtime["seats_held_subscription"] > 0:
        showtime["seats_held_subscription"] -= 1
        touch(showtime)


def refund_credit(reservation, allowed_postures):
    """Refund per cancellation_credit_refund. Returns True if refunded."""
    if not reservation.get("credit_consumed"):
        return False
    bucket = STORE["buckets"].get(reservation["bucket_id"])
    if bucket is None:
        return False
    if bucket_posture(bucket) in allowed_postures:
        if bucket["credits_used"] > 0:
            bucket["credits_used"] -= 1
            touch(bucket)
        reservation["credit_consumed"] = False
        return True
    return False


def cancel_reservation_system(reservation, refund_postures):
    """System-cascade cancel: no deadline check; refund per posture rule."""
    refund_credit(reservation, refund_postures)
    reservation["status"] = "CANCELLED"
    release_seat(reservation)
    touch(reservation)


def expire_hold(reservation):
    """HELD -> EXPIRED auto sweep; always refunds if bucket not EXPIRED."""
    refund_credit(reservation, ("OPEN", "EXHAUSTED"))
    reservation["status"] = "EXPIRED"
    release_seat(reservation)
    touch(reservation)


def sweep_no_show(reservation):
    """CONFIRMED -> NO_SHOW with the full no-show cascade."""
    n = now()
    reservation["status"] = "NO_SHOW"
    release_seat(reservation)
    touch(reservation)
    member = STORE["members"].get(reservation["member_id"])
    # Strike appended
    strike = {
        "member_id": reservation["member_id"],
        "reservation_id": reservation["id"],
        "issued_at": fmt_dt(n),
        "expires_at": fmt_dt(n + timedelta(days=STRIKE_WINDOW_DAYS)),
        "status": "ACTIVE",
        "reversal_reason": None,
    }
    stamp_new(strike)
    STORE["strikes"][strike["id"]] = strike
    # Suspension ladder
    if member is not None and member["status"] == "ACTIVE":
        if active_strike_count(member["id"]) >= SUSPENSION_THRESHOLD:
            suspend_member(member)


# ================= Showtime / member derived views =================

def showtime_view(showtime):
    out = dict(showtime)
    auditorium = STORE["auditoriums"].get(showtime["auditorium_id"])
    seat_count = auditorium["seat_count"] if auditorium else 0
    out["seats_available"] = seat_count - showtime["seats_held_subscription"] - showtime["seats_held_paid"]
    return out


def future_reservation_count(member_id):
    n = now()
    count = 0
    for r in STORE["reservations"].values():
        if r["member_id"] == member_id and r["status"] in ("HELD", "CONFIRMED"):
            st = STORE["showtimes"].get(r["showtime_id"])
            if st is not None and parse_dt(st["starts_at"]) > n:
                count += 1
    return count


def effective_future_cap(member, plan):
    cap = plan["max_future_reservations"]
    if active_strike_count(member["id"]) == FLAG_LEVEL:
        cap = cap // 2
    return cap


# ================= Loyalty =================

def active_subscription_plan(member_id):
    """Return the plan of the member's ACTIVE subscription, else None."""
    for sub in STORE["subscriptions"].values():
        if sub["member_id"] == member_id and sub["status"] == "ACTIVE":
            return STORE["plans"].get(sub["plan_id"])
    return None


def append_ledger(member_id, kind, points, source_id=None, note=None):
    entry = {
        "member_id": member_id,
        "kind": kind,
        "points": points,
        "source_id": source_id,
        "note": note,
    }
    stamp_new_lean(entry)
    STORE["ledger"][entry["id"]] = entry
    return entry


def admission_points_for(member_id):
    plan = active_subscription_plan(member_id)
    multiplier = plan["loyalty_points_multiplier_pct"] if plan else 100
    return (ADMISSION_POINTS * multiplier) // 100


# ================= Settlement =================

def report_lines(report_id):
    return [l for l in STORE["lines"].values() if l["report_id"] == report_id]


def report_view(report):
    out = dict(report)
    lines = report_lines(report["id"])
    if report["status"] in ("DRAFT", "DISPUTED"):
        out["total_admissions"] = len(lines)
        out["total_subscription_admissions"] = sum(1 for l in lines if l["line_kind"] == "SUBSCRIPTION")
        out["total_gross_cents"] = sum(l["reported_value_cents"] for l in lines)
    else:
        out["total_admissions"] = report.get("frozen_total_admissions", 0)
        out["total_subscription_admissions"] = report.get("frozen_total_subscription_admissions", 0)
        out["total_gross_cents"] = report.get("frozen_total_gross_cents", 0)
    for k in ("frozen_total_admissions", "frozen_total_subscription_admissions", "frozen_total_gross_cents"):
        out.pop(k, None)
    return out


def line_valuation(showtime, line_kind):
    if line_kind == "PAID":
        value = showtime["base_price_cents"]
        if showtime["format"] != "STANDARD":
            value += showtime["premium_surcharge_cents"]
        return value
    return STUDIO_CONTRACT_RATE_CENTS


# ================= Clock advancement =================

def advance_clock(new_now):
    """Set the logical clock forward and fire all due time-based transitions."""
    if new_now < now():
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must not move the clock backward")
    CLOCK["now"] = new_now
    n = now()

    # 1. Hold expiry: HELD reservations older than HOLD_TTL_MINUTES
    for r in list(STORE["reservations"].values()):
        if r["status"] == "HELD":
            created = parse_dt(r["created_at"])
            if created + timedelta(minutes=HOLD_TTL_MINUTES) <= n:
                expire_hold(r)

    # 2. No-show sweep: CONFIRMED reservations whose grace elapsed.
    # PRD §3.5: swept "once the clock passes starts_at plus 30 minutes of
    # grace" — strictly after, so the inclusive check-in upper bound at
    # exactly starts_at+30m still sees the reservation CONFIRMED.
    for r in list(STORE["reservations"].values()):
        if r["status"] == "CONFIRMED":
            st = STORE["showtimes"].get(r["showtime_id"])
            if st is not None:
                starts = parse_dt(st["starts_at"])
                if starts + timedelta(minutes=NO_SHOW_GRACE_MINUTES) < n:
                    sweep_no_show(r)

    # 3. Showtime locking and completion
    for st in list(STORE["showtimes"].values()):
        starts = parse_dt(st["starts_at"])
        if st["status"] == "ON_SALE":
            if starts - timedelta(minutes=LOCK_MINUTES_BEFORE_START) <= n:
                st["status"] = "LOCKED"
                touch(st)
        if st["status"] == "LOCKED":
            complete_at = starts + timedelta(minutes=st["runtime_minutes"] + NO_SHOW_GRACE_MINUTES)
            if complete_at <= n:
                st["status"] = "COMPLETED"
                touch(st)
                for r in list(STORE["reservations"].values()):
                    if r["showtime_id"] == st["id"] and r["status"] == "CONFIRMED":
                        sweep_no_show(r)
                for r in list(STORE["reservations"].values()):
                    if r["showtime_id"] == st["id"] and r["status"] == "HELD":
                        expire_hold(r)

    # 4. Suspension lifts
    for member in list(STORE["members"].values()):
        if member["status"] == "SUSPENDED" and member.get("suspended_until"):
            if parse_dt(member["suspended_until"]) <= n:
                unsuspend_member(member)

    # 5. Pause auto-resume
    for sub in list(STORE["subscriptions"].values()):
        if sub["status"] == "PAUSED" and sub.get("pause_resume_at"):
            if parse_dt(sub["pause_resume_at"]) <= n:
                resume_subscription(sub)

    # 6. Strike expiry (eager sweep)
    expire_strikes_all()

    # 7. Week rollovers: materialize buckets up to the current week per subscription
    for sub in list(STORE["subscriptions"].values()):
        if sub["status"] in ("ACTIVE", "PAUSED"):
            ensure_buckets_up_to(sub, week_index_at(sub, n))
