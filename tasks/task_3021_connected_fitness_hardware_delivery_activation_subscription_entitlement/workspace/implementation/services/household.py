"""HouseholdUser lifecycle and the stream concurrency ceiling.

Implements the HouseholdUser state machine (SCAFFOLD.yaml section 1.2) plus the
eviction discipline of PRD section 2.5.
"""

import db
from errors import api_error
from services import calc
from services.common import (
    field_enum,
    field_str,
    reject_unknown,
)

USER_ROLES = ("OWNER", "MEMBER")
SUSPEND_REASONS = ("EVICTED_BY_CONCURRENCY", "MEMBERSHIP_CANCELLED", "REACTIVATION_UNPAID")


def create(membership, payload):
    reject_unknown(payload, {"display_name", "email", "role"})
    display_name = field_str(payload, "display_name")
    email = field_str(payload, "email")
    role = field_enum(payload, "role", USER_ROLES, required=False, default="MEMBER")

    if role == "OWNER":
        for row in db.STORE["household_users"].values():
            if row["membership_id"] == membership["id"] and row["role"] == "OWNER":
                raise api_error(
                    "ERR_OWNER_ALREADY_EXISTS",
                    "A membership may hold exactly one OWNER household user.",
                )

    user = db.create("household_users", {
        "membership_id": membership["id"],
        "display_name": display_name,
        "email": email,
        "role": role,
        "status": "PENDING_VERIFICATION",
        "streaming_device_serial": None,
        "suspended_reason": None,
        "verification_token": db.new_token(),
        "verified": False,
        "eviction_count": 0,
    })

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return user


def verify(user, payload):
    reject_unknown(payload, {"verification_token"})
    if user["verified"] is True or user["status"] != "PENDING_VERIFICATION":
        raise api_error(
            "ERR_INVALID_STATE",
            "The verification token has already been consumed.",
        )
    token = field_str(payload, "verification_token")
    if token != user["verification_token"]:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "The supplied verification_token is not the token issued for this user.",
        )

    user["verified"] = True
    user["status"] = "ACTIVE"
    db.touch(user)

    membership = db.require("memberships", user["membership_id"])
    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    return user


def start_stream(user, payload):
    reject_unknown(payload, {"device_serial", "expected_membership_version"})
    device_serial = field_str(payload, "device_serial")

    if user["status"] not in ("ACTIVE", "PENDING_VERIFICATION"):
        raise api_error(
            "ERR_INVALID_STATE",
            "Only an ACTIVE household user may begin streaming.",
        )

    membership = db.require("memberships", user["membership_id"])

    # PRD section 2.12: start-stream is not one of the guarded writes, so a
    # supplied expected_membership_version is compared when present.
    if payload.get("expected_membership_version") is not None:
        expected = payload["expected_membership_version"]
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            raise api_error(
                "ERR_INVALID_REQUEST",
                "Field 'expected_membership_version' must be an integer.",
            )
        if expected != membership["version"]:
            raise api_error(
                "ERR_MEMBERSHIP_STALE_VERSION",
                "expected_membership_version %d does not match the membership's current version %d."
                % (expected, membership["version"]),
            )

    calc.recompute_stream_counters(membership)
    if membership["active_user_count"] + 1 > membership["concurrent_limit_effective"]:
        candidate = calc.eviction_candidate(membership, user["id"])
        if candidate is None:
            raise api_error(
                "ERR_CONCURRENT_LIMIT_EXCEEDED",
                "The stream ceiling would be breached and no non-owner member is available for eviction.",
            )
        candidate["status"] = "SUSPENDED"
        candidate["suspended_reason"] = "EVICTED_BY_CONCURRENCY"
        candidate["streaming_device_serial"] = None
        candidate["eviction_count"] = candidate["eviction_count"] + 1
        db.touch(candidate)

    user["streaming_device_serial"] = device_serial
    db.touch(user)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return user


def suspend(user, payload):
    reject_unknown(payload, {"suspended_reason"})
    reason = field_enum(payload, "suspended_reason", SUSPEND_REASONS)

    user["status"] = "SUSPENDED"
    user["suspended_reason"] = reason
    user["streaming_device_serial"] = None
    db.touch(user)

    membership = db.require("memberships", user["membership_id"])
    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    return user


def unsuspend(user):
    if user["status"] != "SUSPENDED" or user["suspended_reason"] != "EVICTED_BY_CONCURRENCY":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a user suspended for EVICTED_BY_CONCURRENCY may be unsuspended here.",
        )

    membership = db.require("memberships", user["membership_id"])
    calc.recompute_stream_counters(membership)
    if membership["active_user_count"] + 1 > membership["concurrent_limit_effective"]:
        raise api_error(
            "ERR_CONCURRENT_LIMIT_EXCEEDED",
            "Restoring this user would breach the household's effective stream ceiling.",
        )

    user["status"] = "ACTIVE"
    user["suspended_reason"] = None
    db.touch(user)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    return user


def owned_by(caller, user):
    """Ownership check for the entity-backed role."""
    membership = db.STORE["memberships"].get(user["membership_id"])
    if caller.is_owner and membership is not None and membership["id"] != caller.user_id:
        raise api_error("ERR_UNAUTHORIZED")
    return user