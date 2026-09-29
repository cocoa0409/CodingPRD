"""Depreciation policy: draft, two-man activation and supersession (PRD 3.2)."""

from flask import Blueprint

import calc
import serialize
import validate
from auth import ALL_ROLES, authorize
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, parse_instant, store, touch

bp = Blueprint("policy", __name__)


@bp.route("/fleet/depreciation-policies", methods=["POST"])
def draft_policy():
    actor, _role = authorize(("FleetController",))
    payload = validate.body()

    # rank 6: body foreign keys in the declared input order
    segment = validate.body_fk(payload, "segment_id", "segment")
    superseded = validate.body_fk(payload, "supersedes_policy_id", "policy")

    # rank 7
    validate.s_id(payload, "segment_id")
    name = validate.s_str(payload, "name")
    monthly_pct = validate.s_num(payload, "monthly_depreciation_pct", gt=0, lt=1)
    mileage_cents = validate.s_int(payload, "mileage_depreciation_cents_per_km", ge=0)
    floor_pct = validate.s_num(payload, "floor_residual_pct", gt=0, lt=1)
    effective_from, _dt = validate.s_instant(payload, "effective_from")
    if "supersedes_policy_id" in payload and payload["supersedes_policy_id"] is not None:
        validate.s_id(payload, "supersedes_policy_id")

    # rank 18
    if superseded is not None:
        if (
            superseded["segment_id"] != segment["id"]
            or superseded["status"] != "ACTIVE"
        ):
            raise ApiError(
                "ERR_SUPERSEDE_TARGET_MISMATCH",
                "supersedes_policy_id must name an ACTIVE policy on the same segment.",
            )

    row = base_row()
    row.update({
        "segment_id": segment["id"],
        "supersedes_policy_id": superseded["id"] if superseded is not None else None,
        "name": name,
        "monthly_depreciation_pct": monthly_pct,
        "mileage_depreciation_cents_per_km": mileage_cents,
        "floor_residual_pct": floor_pct,
        "effective_from": effective_from,
        "created_by_user_id": actor,
        "activated_by_user_id": None,
        "status": "DRAFT",
    })
    store.policies[row["id"]] = row
    return created(serialize.policy(row))


@bp.route("/fleet/depreciation-policies/<policy_id>", methods=["GET"])
def read_policy(policy_id):
    authorize(ALL_ROLES)
    return ok(serialize.policy(validate.load("policy", policy_id)))


@bp.route("/fleet/depreciation-policies", methods=["GET"])
def list_policies():
    authorize(ALL_ROLES)
    return collect(
        store.policies.values(),
        [
            ("segment_id", "segment_id", "str"),
            ("supersedes_policy_id", "supersedes_policy_id", "str"),
            ("status", "status", "str"),
        ],
        serialize.policy,
    )


@bp.route("/fleet/depreciation-policies/<policy_id>/activate", methods=["POST"])
def activate_policy(policy_id):
    actor, _role = authorize(("FleetController",))
    policy = validate.load("policy", policy_id)

    if policy["status"] != "DRAFT":
        raise ApiError("ERR_POLICY_NOT_DRAFT", "Only a DRAFT policy may be activated.")

    effective = parse_instant(policy["effective_from"])
    if effective is not None and effective > store.now():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The policy's effective_from is still in the future.",
        )

    if actor == policy["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The activating operator must differ from created_by_user_id.",
        )

    current = calc.active_policy(policy["segment_id"])
    if current is not None:
        if policy["supersedes_policy_id"] != current["id"]:
            raise ApiError(
                "ERR_SUPERSEDE_TARGET_MISMATCH",
                "supersedes_policy_id must name the segment's currently ACTIVE policy.",
            )
    elif policy["supersedes_policy_id"] is not None:
        raise ApiError(
            "ERR_SUPERSEDE_TARGET_MISMATCH",
            "No ACTIVE policy exists for the segment, so supersedes_policy_id must be null.",
        )

    policy["activated_by_user_id"] = actor
    policy["status"] = "ACTIVE"
    touch(policy)
    if current is not None:
        current["status"] = "SUPERSEDED"
        touch(current)
    return ok(serialize.policy(policy))
