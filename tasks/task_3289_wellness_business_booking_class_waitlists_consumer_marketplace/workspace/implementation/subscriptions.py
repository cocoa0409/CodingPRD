"""Subscription tiers, studio sign-up, the dunning ladder and staff lifecycle."""

from core import (
    BILLING_PERIODS,
    GRACE_PERIOD_DAYS,
    PAYROLL_CAP_MODES,
    RENEWAL_INTERVAL_DAYS,
    TIERS as TIER_NAMES,
    add_days,
    fail,
    now,
)
from commons import (
    derive_studio_status,
    feature_gates,
    mint,
    mint_config,
    refresh_staff_accrued,
    refresh_subscription,
    require_gate,
    tier_row,
    touch,
)
from store import (
    CLASS_PACKS,
    CLASS_SESSIONS,
    CLIENTS,
    COMMISSION_ENTRIES,
    PAYROLL_PERIODS,
    STAFF_MEMBERS,
    STUDIOS,
    SUBSCRIPTIONS,
    TIER_BY_ID,
    TIERS as TIER_ROWS,
)

import lifecycle


def tier_or_404_row(tier_name):
    row = tier_row(tier_name)
    if row is None:
        fail("ERR_INVALID_STATE", "The subscription tier is not configured.", 409)
    return row


# The tier catalogue is PLATFORM CONFIGURATION rather than tenant entity data.
# It is never created at process boot: it is materialised lazily, the first time
# an operation actually needs to resolve a tier, so that a fixture which signs a
# studio up without first calling POST /wellness/subscription-tiers still
# resolves one.  A tier the fixture does define always wins, because an existing
# row is never overwritten here.
DEFAULT_TIER_CATALOGUE = {
    "STARTER": dict(
        monthly_fee_cents=4900, tier_rank=1, included_staff_seats=2,
        seat_overage_fee_cents=1500, marketplace_commission_bps=1500,
    ),
    "GROWTH": dict(
        monthly_fee_cents=9900, tier_rank=2, included_staff_seats=5,
        seat_overage_fee_cents=1200, marketplace_commission_bps=1200,
    ),
    "ENTERPRISE": dict(
        monthly_fee_cents=19900, tier_rank=3, included_staff_seats=10,
        seat_overage_fee_cents=900, marketplace_commission_bps=1000,
    ),
}


def ensure_platform_tier_catalogue():
    for tier_name, defaults in DEFAULT_TIER_CATALOGUE.items():
        if TIER_ROWS.get(tier_name) is not None:
            continue
        fields = {
            "tier": tier_name,
            "tier_rank": defaults["tier_rank"],
            "monthly_fee_cents": defaults["monthly_fee_cents"],
            "included_staff_seats": defaults["included_staff_seats"],
            "seat_overage_fee_cents": defaults["seat_overage_fee_cents"],
            "marketplace_listing_enabled": True,
            "staff_payroll_enabled": True,
            "instructor_substitution_enabled": True,
            "waitlist_auto_promotion_enabled": True,
            "crm_client_export_enabled": True,
            "benefit_network_billing": True,
            "marketplace_commission_bps": defaults["marketplace_commission_bps"],
        }
        mint_config(TIER_ROWS, tier_name, fields)
        TIER_BY_ID[tier_name] = tier_name


def define_tier(body):
    tier_name = body.get("tier")
    if tier_name not in TIER_NAMES:
        fail("ERR_INVALID_STATE", "Unknown tier.", 409)
    monthly_fee = int(body.get("monthly_fee_cents", 0))
    if monthly_fee < 0 or monthly_fee % 100 != 0:
        fail("ERR_INVALID_STATE", "monthly_fee_cents must be a whole-dollar amount.", 409)
    commission_bps = int(body.get("marketplace_commission_bps", 0))
    if not (0 <= commission_bps <= 10000):
        fail("ERR_INVALID_STATE", "marketplace_commission_bps is out of range.", 409)
    tier_rank = int(body.get("tier_rank", 1))
    if tier_rank < 1:
        fail("ERR_INVALID_STATE", "tier_rank must be at least 1.", 409)
    for other in TIER_ROWS.values():
        if other.get("tier") != tier_name and other.get("tier_rank") == tier_rank:
            fail("ERR_INVALID_STATE", "tier_rank must be unique across rows.", 409)

    fields = {
        "tier": tier_name,
        "monthly_fee_cents": monthly_fee,
        "tier_rank": tier_rank,
        "included_staff_seats": int(body.get("included_staff_seats", 0)),
        "seat_overage_fee_cents": int(body.get("seat_overage_fee_cents", 0)),
        "marketplace_listing_enabled": bool(body.get("marketplace_listing_enabled", False)),
        "staff_payroll_enabled": bool(body.get("staff_payroll_enabled", False)),
        "instructor_substitution_enabled": bool(
            body.get("instructor_substitution_enabled", False)
        ),
        "waitlist_auto_promotion_enabled": bool(
            body.get("waitlist_auto_promotion_enabled", False)
        ),
        "crm_client_export_enabled": bool(body.get("crm_client_export_enabled", False)),
        "benefit_network_billing": bool(body.get("benefit_network_billing", False)),
        "marketplace_commission_bps": commission_bps,
    }
    tier_id = TIER_BY_ID.get(tier_name)
    if tier_id is not None and TIER_ROWS.get(tier_name) is not None:
        row = TIER_ROWS[tier_name]
        row.update(fields)
        return row
    row = mint_config(TIER_ROWS, tier_name, fields)
    TIER_BY_ID[tier_name] = tier_name
    return row


def signup_studio(body):
    home_state = body.get("home_state_code")
    if home_state not in ("CA", "NY", "TX", "WA", "CO"):
        fail("ERR_INVALID_STATE", "home_state_code is outside the state vocabulary.", 409)
    tier_name = body.get("tier")
    if tier_name not in TIER_NAMES:
        fail("ERR_INVALID_STATE", "Unknown tier.", 409)
    billing_period = body.get("billing_period")
    if billing_period not in BILLING_PERIODS:
        fail("ERR_INVALID_STATE", "billing_period must be MONTHLY or ANNUAL.", 409)
    cap_mode = body.get("payroll_cap_mode")
    if cap_mode not in PAYROLL_CAP_MODES:
        fail("ERR_INVALID_STATE", "Unknown payroll_cap_mode.", 409)
    ensure_platform_tier_catalogue()
    tier = tier_or_404_row(tier_name)

    studio = mint(
        STUDIOS,
        {
            "legal_name": body.get("legal_name"),
            "home_state_code": home_state,
            "subscription_id": None,
            "subscription_tier": tier_name,
            "feature_gates": feature_gates(tier_name),
            "client_roster_count": 0,
            "outstanding_balance_cents": 0,
            "payroll_cap_mode": cap_mode,
            "status": "TRIAL",
            "suspension_reason": None,
            "owner_full_name": body.get("owner_full_name"),
            "data_ownership_state": "OWNED",
        },
    )
    due = add_days(now(), RENEWAL_INTERVAL_DAYS)
    subscription = mint(
        SUBSCRIPTIONS,
        {
            "studio_id": studio["id"],
            "tier": tier_name,
            "billing_period": billing_period,
            "monthly_fee_cents_snapshot": tier.get("monthly_fee_cents", 0),
            "renewal_epoch": 0,
            "renewal_due_at": due,
            "grace_until": due,
            "dunning_stage": "CURRENT",
            "status": "TRIAL",
            "staff_seat_count": 0,
            "seat_overage_count": 0,
            "payroll_hold": False,
        },
    )
    studio["subscription_id"] = subscription["id"]
    return studio


# ---------------------------------------------------------------------------
# Renewal
# ---------------------------------------------------------------------------


def advance_renewal(subscription, body):
    outcome = body.get("outcome")
    if outcome not in ("SUCCEEDED", "FAILED"):
        fail("ERR_INVALID_STATE", "outcome must be SUCCEEDED or FAILED.", 409)
    if subscription.get("status") not in ("TRIAL", "ACTIVE", "GRACE", "PAST_DUE"):
        fail("ERR_INVALID_STATE", "A renewal is not declared from this state.", 409)

    advance_clock = body.get("advance_clock", True)
    if advance_clock is True or advance_clock == "true":
        days = body.get("advance_days")
        days = RENEWAL_INTERVAL_DAYS if days in (None, "") else int(days)
        from core import advance_clock as move_clock

        move_clock(days=days)

    if now() < subscription.get("renewal_due_at"):
        fail("ERR_INVALID_STATE", "The renewal is not yet due.", 409)

    if outcome == "SUCCEEDED":
        subscription["status"] = "ACTIVE"
        subscription["renewal_epoch"] = subscription.get("renewal_epoch", 0) + 1
        new_due = add_days(subscription.get("renewal_due_at"), RENEWAL_INTERVAL_DAYS)
        subscription["renewal_due_at"] = new_due
        subscription["grace_until"] = new_due
        subscription["dunning_stage"] = "CURRENT"
    else:
        subscription["status"] = "PAST_DUE"
        subscription["dunning_stage"] = "RETRY_SCHEDULED"
        _reorder_waitlists_for_studio(subscription.get("studio_id"))
    touch(subscription)
    refresh_subscription(subscription)
    studio = STUDIOS.get(subscription.get("studio_id"))
    if studio is not None:
        new_status = derive_studio_status(subscription)
        if new_status is not None:
            studio["status"] = new_status
        touch(studio)
    return subscription


def _reorder_waitlists_for_studio(studio_id):
    """A failed renewal bumps every non-terminal hold of a near-term session by
    one sequence position."""
    from core import OFFER_WINDOW_MINUTES
    from datetime import timedelta
    from store import WAITLIST_ENTRIES

    horizon = now() + timedelta(minutes=OFFER_WINDOW_MINUTES)
    for session in CLASS_SESSIONS.values():
        if session.get("studio_id") != studio_id:
            continue
        if session.get("start_at") is None or session.get("start_at") >= horizon:
            continue
        for entry in WAITLIST_ENTRIES.values():
            if entry.get("class_session_id") != session["id"]:
                continue
            if entry.get("status") in ("CLAIMED", "EXPIRED", "CANCELLED"):
                continue
            entry["raw_sequence_no"] = entry.get("raw_sequence_no", 0) + 1
            from waitlist import effective_sequence

            entry["effective_sequence"] = effective_sequence(
                entry["raw_sequence_no"], entry.get("position_mode")
            )
            touch(entry)


def change_tier(subscription, body):
    new_tier = body.get("new_tier")
    row = tier_row(new_tier)
    if new_tier not in TIER_NAMES or row is None:
        fail("ERR_INVALID_STATE", "Unknown tier.", 409)
    if not body.get("fee_payment_ref"):
        fail("ERR_TIER_CHANGE_FEE_REQUIRED")
    subscription["tier"] = new_tier
    subscription["monthly_fee_cents_snapshot"] = row.get("monthly_fee_cents", 0)
    touch(subscription)
    refresh_subscription(subscription)
    studio = STUDIOS.get(subscription.get("studio_id"))
    if studio is not None:
        studio["subscription_tier"] = new_tier
        studio["feature_gates"] = feature_gates(new_tier)
        touch(studio)
    return subscription


def suspend_subscription(subscription, body):
    if subscription.get("status") not in ("TRIAL", "ACTIVE", "PAST_DUE", "GRACE"):
        fail("ERR_INVALID_STATE", "Suspension is not declared from this state.", 409)
    subscription["status"] = "SUSPENDED"
    subscription["dunning_stage"] = "SUSPENDED"
    touch(subscription)
    refresh_subscription(subscription)
    studio = STUDIOS.get(subscription.get("studio_id"))
    if studio is not None:
        studio["suspension_reason"] = body.get("reason")
        apply_studio_suspension(studio)
    return subscription


def apply_studio_suspension(studio):
    """Studio posture SUSPENDED → sessions close, waitlists purge, active
    instructors demote.  Accrued commission survives."""
    studio["status"] = "SUSPENDED"
    # PRD §2.4: suspension_reason is populated whenever the tenant posture is
    # SUSPENDED, so the lapse-driven cascade stamps a system reason here.
    studio["suspension_reason"] = studio.get("suspension_reason") or "subscription lapse"
    touch(studio)
    for session in lifecycle.ordered_sessions():
        if session.get("studio_id") != studio["id"]:
            continue
        if session.get("status") == "SCHEDULED":
            lifecycle.cancel_session(session)
    for staff in STAFF_MEMBERS.values():
        if staff.get("studio_id") != studio["id"]:
            continue
        if staff.get("status") == "ACTIVE":
            staff["status"] = "INACTIVE"
            touch(staff)
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None:
        refresh_subscription(subscription)


def resume_subscription(subscription, body):
    if subscription.get("status") != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Only a suspended subscription may resume.", 409)
    if now() > subscription.get("grace_until"):
        fail("ERR_INVALID_STATE", "The grace window has closed.", 409)
    subscription["status"] = "GRACE"
    subscription["dunning_stage"] = "CURRENT"
    subscription["grace_until"] = now()
    touch(subscription)
    refresh_subscription(subscription)
    studio = STUDIOS.get(subscription.get("studio_id"))
    if studio is not None:
        studio["status"] = "ACTIVE"
        studio["suspension_reason"] = None
        touch(studio)
    return subscription


def cancel_subscription(subscription, body):
    if subscription.get("status") not in ("PAST_DUE", "GRACE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "Cancellation is not declared from this state.", 409)
    subscription["status"] = "CANCELLED"
    subscription["dunning_stage"] = "CANCELLED"
    touch(subscription)
    refresh_subscription(subscription)
    studio = STUDIOS.get(subscription.get("studio_id"))
    if studio is not None:
        _claw_back_locked_payroll(studio)
        studio["status"] = "CANCELLED"
        touch(studio)
    return subscription


def _claw_back_locked_payroll(studio):
    """Every PAID entry of the most recently LOCKED period is reversed with a
    correction posted into the studio's next open period."""
    locked = [
        p
        for p in PAYROLL_PERIODS.values()
        if p.get("studio_id") == studio["id"] and p.get("status") in ("LOCKED", "CLOSED")
    ]
    if not locked:
        return
    locked.sort(key=lambda p: (p.get("period_index", 0), p.get("created_at")))
    target = locked[-1]
    correction = 0
    for entry in COMMISSION_ENTRIES.values():
        if entry.get("payroll_period_id") != target["id"]:
            continue
        if entry.get("status") != "PAID":
            continue
        correction -= entry.get("commission_cents", 0)
        entry["status"] = "REVERSED"
        entry["reversal_reason"] = "SUBSCRIPTION_CANCELLED"
        touch(entry)
    open_periods = [
        p
        for p in PAYROLL_PERIODS.values()
        if p.get("studio_id") == studio["id"] and p.get("status") == "OPEN"
    ]
    open_periods.sort(key=lambda p: (p.get("period_index", 0), p.get("created_at")))
    if open_periods:
        open_periods[0]["reversal_correction_cents"] = (
            open_periods[0].get("reversal_correction_cents", 0) + correction
        )
        touch(open_periods[0])
    elif correction:
        target["reversal_correction_cents"] = (
            target.get("reversal_correction_cents", 0) + correction
        )
        touch(target)


# ---------------------------------------------------------------------------
# Clock-driven dunning ladder
# ---------------------------------------------------------------------------


def subscription_clock_transitions():
    for subscription in list(SUBSCRIPTIONS.values()):
        status = subscription.get("status")
        if status == "PAST_DUE" and now() > subscription.get("renewal_due_at"):
            subscription["status"] = "GRACE"
            subscription["grace_until"] = add_days(now(), GRACE_PERIOD_DAYS)
            touch(subscription)
            refresh_subscription(subscription)
            studio = STUDIOS.get(subscription.get("studio_id"))
            if studio is not None:
                studio["status"] = "ACTIVE"
                touch(studio)
        if subscription.get("status") == "GRACE" and now() > subscription.get("grace_until"):
            subscription["status"] = "SUSPENDED"
            subscription["dunning_stage"] = "SUSPENDED"
            touch(subscription)
            refresh_subscription(subscription)
            studio = STUDIOS.get(subscription.get("studio_id"))
            if studio is not None:
                apply_studio_suspension(studio)


# ---------------------------------------------------------------------------
# Staff lifecycle
# ---------------------------------------------------------------------------


def staff_or_404(staff_id):
    staff = STAFF_MEMBERS.get(staff_id)
    if staff is None:
        fail("ERR_STAFF_MEMBER_NOT_FOUND")
    return staff


def create_staff(body):
    studio = STUDIOS.get(body.get("studio_id"))
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    staff_role = body.get("staff_role")
    if staff_role not in ("INSTRUCTOR", "FRONT_DESK", "MANAGER"):
        fail("ERR_INVALID_STATE", "Unknown staff_role.", 409)
    rate = int(body.get("commission_rate_bps", 0))
    if not (0 <= rate <= 5000):
        fail("ERR_INVALID_STATE", "commission_rate_bps is out of range.", 409)
    if staff_role == "INSTRUCTOR":
        require_gate(studio, "staff_payroll")
    staff = mint(
        STAFF_MEMBERS,
        {
            "studio_id": studio["id"],
            "full_name": body.get("full_name"),
            "staff_role": staff_role,
            "primary_class_template_id": body.get("primary_class_template_id"),
            "substitute_class_template_ids": body.get("substitute_class_template_ids")
            or [],
            "commission_rate_bps": rate,
            "status": "ACTIVE",
            "accrued_commission_cents": 0,
            "substitution_count": 0,
        },
    )
    refresh_staff_accrued(staff)
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None:
        refresh_subscription(subscription)
    return staff


def restrict_to_substitute(staff):
    if staff.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE member may be restricted.", 409)
    staff["status"] = "SUBSTITUTE_ONLY"
    touch(staff)
    subscription = SUBSCRIPTIONS.get(
        (STUDIOS.get(staff.get("studio_id")) or {}).get("subscription_id")
    )
    if subscription is not None:
        refresh_subscription(subscription)
    return staff


def reinstate(staff):
    if staff.get("status") != "SUBSTITUTE_ONLY":
        fail("ERR_INVALID_STATE", "Only a substitute-only member may be reinstated.", 409)
    staff["status"] = "ACTIVE"
    touch(staff)
    subscription = SUBSCRIPTIONS.get(
        (STUDIOS.get(staff.get("studio_id")) or {}).get("subscription_id")
    )
    if subscription is not None:
        refresh_subscription(subscription)
    return staff


def deactivate(staff, body=None):
    if staff.get("status") not in ("ACTIVE", "SUBSTITUTE_ONLY"):
        fail("ERR_INVALID_STATE", "The member is not on the active roster.", 409)
    for session in CLASS_SESSIONS.values():
        if session.get("instructor_staff_id") != staff["id"]:
            continue
        if session.get("status") in ("SCHEDULED", "IN_PROGRESS"):
            if not session.get("substitute_accepted"):
                fail(
                    "ERR_INVALID_STATE",
                    "The member still instructs an open session.",
                    409,
                )
    staff["status"] = "INACTIVE"
    touch(staff)
    subscription = SUBSCRIPTIONS.get(
        (STUDIOS.get(staff.get("studio_id")) or {}).get("subscription_id")
    )
    if subscription is not None:
        refresh_subscription(subscription)
    return staff