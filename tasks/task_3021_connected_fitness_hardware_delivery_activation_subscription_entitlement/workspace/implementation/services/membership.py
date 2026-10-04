"""Membership lifecycle: creation, activation, pause, resume, cancel, reactivate.

Implements the Membership state machine (SCAFFOLD.yaml section 1.2) and the
lifecycle narrative of PRD sections 2.4-2.7 and 3.4.
"""

import clock
import db
from errors import api_error
from services import calc, order as order_service
from services.common import (
    field_datetime,
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)

PLAN_TIERS = ("PLUS", "BUSINESS")

# Device states that a cancellation sweeps into LOCKED (PRD section 3.4).
CANCEL_LOCK_STATES = ("ACTIVE", "LINKED", "DELIVERED", "LOCKED")


def create(payload):
    reject_unknown(
        payload,
        {"household_name", "billing_email", "plan_tier", "monthly_fee_cents",
         "concurrent_limit_override"},
    )
    household_name = field_str(payload, "household_name")
    billing_email = field_str(payload, "billing_email")
    plan_tier = field_enum(payload, "plan_tier", PLAN_TIERS)
    monthly_fee_cents = field_int(payload, "monthly_fee_cents", minimum=0)
    override = field_int(
        payload, "concurrent_limit_override", required=False, default=None, minimum=1
    )

    instant = clock.now()
    membership = db.create("memberships", {
        "household_name": household_name,
        "billing_email": billing_email,
        "plan_tier": plan_tier,
        "monthly_fee_cents": monthly_fee_cents,
        "concurrent_limit_override": override,
        "concurrent_limit_effective": 0,
        # A new membership is PROVISIONAL with posture OPEN, an open safety gate
        # and billing anchors already stamped (PRD section 2.4).
        "active_user_count": 0,
        "billing_cycle_start_at": instant,
        "paid_through_at": instant + clock.days(calc.CYCLE_DAYS),
        "status": "PROVISIONAL",
        "posture": "OPEN",
        "pause_started_at": None,
        "accrued_pause_credit_cents": 0,
        "total_streams_observed": 0,
        "unpaid_financing_count": 0,
        "safety_gate_open": True,
        "attr_frozen_reason": None,
    })
    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    return membership


def owned_devices(membership):
    return [
        row for row in db.STORE["devices"].values()
        if row["membership_id"] == membership["id"]
    ]


def linked_devices(membership):
    return [
        row for row in owned_devices(membership)
        if row["activation_status"] in ("LINKED", "ACTIVE")
    ]


def _reject_terminal(membership):
    if membership["status"] == "TERMINATED":
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The membership has been terminated and admits no further lifecycle action.",
        )


def _check_occ(membership, payload, required):
    """Priority 4: the supplied expected_membership_version must match."""
    expected = field_int(payload, "expected_membership_version", required=required)
    if expected is None:
        return
    if expected != membership["version"]:
        raise api_error(
            "ERR_MEMBERSHIP_STALE_VERSION",
            "expected_membership_version %d does not match the membership's current version %d."
            % (expected, membership["version"]),
        )


def _sweep_devices(membership, from_statuses, locked):
    """Cascade the entitlement latch across the membership's device estate.

    The parent posture is resolved first so that each device's derived
    content_access_allowed is computed from the membership's new posture rather
    than the one it held before this transition.
    """
    calc.recompute_membership(membership, bump=False)
    for row in owned_devices(membership):
        if row["activation_status"] not in from_statuses:
            continue
        if locked:
            row["activation_status"] = "LOCKED"
            row["entitlement_lock"] = True
        else:
            row["activation_status"] = "ACTIVE"
            row["entitlement_lock"] = False
        calc.recompute_device_entitlement(row)
        db.touch(row)


# ---------------------------------------------------------------------------
# POST /memberships/{membershipId}/activate
# ---------------------------------------------------------------------------
def activate(membership, payload):
    reject_unknown(payload, {"expected_membership_version"})
    _check_occ(membership, payload, required=True)
    _reject_terminal(membership)
    calc.recompute_stream_counters(membership)

    if membership["status"] != "PROVISIONAL":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a PROVISIONAL membership may be activated.",
        )
    if membership["active_user_count"] < 1:
        raise api_error(
            "ERR_INVALID_STATE",
            "Activation requires at least one household user counting toward active_user_count.",
        )
    if not linked_devices(membership):
        raise api_error(
            "ERR_INVALID_STATE",
            "Activation requires at least one device on the membership in LINKED or ACTIVE.",
        )

    instant = clock.now()
    membership["status"] = "ACTIVE"
    membership["billing_cycle_start_at"] = instant
    membership["paid_through_at"] = instant + clock.days(calc.CYCLE_DAYS)
    calc.recompute_membership(membership, bump=False)

    for row in owned_devices(membership):
        if row["activation_status"] == "LINKED":
            row["activation_status"] = "ACTIVE"
            row["entitlement_lock"] = False
            calc.recompute_device_entitlement(row)
            db.touch(row)

    order_service.close_activated_orders(membership)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


# ---------------------------------------------------------------------------
# POST /memberships/{membershipId}/pause
# ---------------------------------------------------------------------------
def pause(membership, payload):
    reject_unknown(payload, {"pause_start_at", "pause_end_at", "expected_membership_version"})
    _check_occ(membership, payload, required=True)
    _reject_terminal(membership)

    if membership["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_STATE", "Only an ACTIVE membership may be paused.")

    # Priority 7 (business_temporal) is evaluated before priority 10
    # (business_fiscal), so the pause-length ceiling outranks the unpaid
    # financing block.
    pause_start_at = field_datetime(payload, "pause_start_at")
    pause_end_at = field_datetime(payload, "pause_end_at")
    span = pause_end_at - pause_start_at
    if span.total_seconds() <= 0 or span > clock.days(calc.MAX_PAUSE_DAYS):
        raise api_error(
            "ERR_PAUSE_WINDOW_INVALID",
            "The pause window must end after it starts and span at most %d days."
            % calc.MAX_PAUSE_DAYS,
        )

    calc.recompute_stream_counters(membership)
    if membership["unpaid_financing_count"] >= 1:
        raise api_error(
            "ERR_UNPAID_FINANCING_BLOCK",
            "A household carrying a DELINQUENT or DEFAULTED plan may not pause.",
        )

    membership["status"] = "PAUSED"
    membership["pause_started_at"] = clock.now()
    membership["accrued_pause_credit_cents"] = calc.pause_proration(membership, "UNUSED_DAYS")

    _sweep_devices(membership, ("ACTIVE",), True)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


# ---------------------------------------------------------------------------
# POST /memberships/{membershipId}/resume
# ---------------------------------------------------------------------------
def resume(membership, payload):
    reject_unknown(payload, {"expected_membership_version"})
    # PRD section 2.12: resume accepts expected_membership_version without
    # being one of the guarded set, so it is compared when supplied.
    _check_occ(membership, payload, required=False)
    _reject_terminal(membership)

    if membership["status"] != "PAUSED":
        raise api_error("ERR_INVALID_STATE", "Only a PAUSED membership may be resumed.")

    calc.recompute_stream_counters(membership)
    if membership["active_user_count"] < 1:
        raise api_error(
            "ERR_INVALID_STATE",
            "Resuming requires at least one household user counting toward active_user_count.",
        )
    if membership["unpaid_financing_count"] >= 1:
        raise api_error(
            "ERR_UNPAID_FINANCING_BLOCK",
            "A household carrying a DELINQUENT or DEFAULTED plan may not resume.",
        )

    credit = membership["accrued_pause_credit_cents"]
    if credit:
        membership["paid_through_at"] = membership["paid_through_at"] + clock.days(
            calc.pause_credit_to_days(credit, membership["monthly_fee_cents"])
        )
    membership["accrued_pause_credit_cents"] = 0
    membership["pause_started_at"] = None
    membership["status"] = "ACTIVE"

    _sweep_devices(membership, ("LOCKED",), False)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


# ---------------------------------------------------------------------------
# POST /memberships/{membershipId}/cancel
# ---------------------------------------------------------------------------
def cancel(membership, payload):
    reject_unknown(payload, {"expected_membership_version"})
    _check_occ(membership, payload, required=True)
    _reject_terminal(membership)

    previous_status = membership["status"]
    if previous_status not in ("ACTIVE", "PAUSED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "A membership may only be cancelled from ACTIVE or PAUSED.",
        )

    # From ACTIVE the credit is recomputed on the remaining-days basis; from
    # PAUSED the credit banked at pause time is preserved verbatim, including
    # its round-up (PRD section 3.4).
    if previous_status == "ACTIVE":
        membership["accrued_pause_credit_cents"] = calc.pause_proration(
            membership, "REMAINING_DAYS"
        )

    membership["status"] = "CANCELLED"
    membership["attr_frozen_reason"] = None

    _sweep_devices(membership, CANCEL_LOCK_STATES, True)

    for user in db.STORE["household_users"].values():
        if user["membership_id"] != membership["id"]:
            continue
        if user["status"] in ("ACTIVE", "PENDING_VERIFICATION"):
            user["status"] = "SUSPENDED"
            user["suspended_reason"] = "MEMBERSHIP_CANCELLED"
            user["streaming_device_serial"] = None
            db.touch(user)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


# ---------------------------------------------------------------------------
# POST /memberships/{membershipId}/reactivate
# ---------------------------------------------------------------------------
def reactivate(membership, payload):
    reject_unknown(payload, {"expected_membership_version"})
    _check_occ(membership, payload, required=True)
    _reject_terminal(membership)

    if membership["status"] != "CANCELLED":
        raise api_error("ERR_INVALID_STATE", "Only a CANCELLED membership may be reactivated.")

    # Users suspended by the cancellation come back to ACTIVE, so they count
    # toward the post-reactivation household.
    returning = sum(
        1
        for user in db.STORE["household_users"].values()
        if user["membership_id"] == membership["id"]
        and (
            user["status"] in ("ACTIVE", "PENDING_VERIFICATION")
            or (user["status"] == "SUSPENDED"
                and user["suspended_reason"] == "MEMBERSHIP_CANCELLED")
        )
    )
    if returning < 1:
        raise api_error(
            "ERR_INVALID_STATE",
            "Reactivation requires at least one household user counting as active afterwards.",
        )

    calc.recompute_stream_counters(membership)
    if membership["unpaid_financing_count"] >= 1:
        raise api_error(
            "ERR_UNPAID_FINANCING_BLOCK",
            "Reactivation is refused while any financing plan is DELINQUENT or DEFAULTED.",
        )

    instant = clock.now()
    membership["status"] = "REACTIVATED"
    membership["billing_cycle_start_at"] = instant
    membership["paid_through_at"] = instant + clock.days(calc.CYCLE_DAYS)
    membership["accrued_pause_credit_cents"] = 0

    _sweep_devices(membership, ("LOCKED",), False)

    for user in db.STORE["household_users"].values():
        if user["membership_id"] != membership["id"]:
            continue
        if user["status"] == "SUSPENDED" and user["suspended_reason"] == "MEMBERSHIP_CANCELLED":
            user["status"] = "ACTIVE"
            user["suspended_reason"] = None
            db.touch(user)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


# ---------------------------------------------------------------------------
# System transitions
# ---------------------------------------------------------------------------
def settle_reactivated(membership):
    """REACTIVATED → ACTIVE (automatic; the waypoint settles into the lifecycle)."""
    membership["status"] = "ACTIVE"
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


def terminate(membership):
    """CANCELLED → TERMINATED, decommissioning the estate."""
    membership["status"] = "TERMINATED"
    calc.recompute_membership(membership, bump=False)

    for row in owned_devices(membership):
        row["activation_status"] = "DECOMMISSIONED"
        row["entitlement_lock"] = True
        calc.recompute_device_entitlement(row)
        db.touch(row)

    for user in db.STORE["household_users"].values():
        if user["membership_id"] != membership["id"]:
            continue
        if user["status"] == "SUSPENDED":
            user["status"] = "REMOVED"
            user["streaming_device_serial"] = None
            db.touch(user)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return membership


def summary(membership):
    """Computed read of the membership aggregate (no version bump)."""
    calc.recompute_stream_counters(membership)
    calc.apply_delinquency_derivatives(membership)
    calc.recompute_posture(membership)
    return membership