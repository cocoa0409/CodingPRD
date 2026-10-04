"""ExemptionPolicy endpoints (PRD §3.2)."""
from flask import Blueprint

from constants import EXEMPTION_CLASSES, PAYMENT_TYPES, ROLE_TREASURY_SUPERVISOR
from db import STORE, new_entity, touch
from errors import err_invalid_request, err_invalid_state, err_not_found
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_policy
from util import gen_id

bp = Blueprint("policies", __name__)


@bp.post("/exemption-policies")
def create_policy():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    data = validate_body(get_body(), [
        spec_field("payment_type", "enum", required=True, enum=PAYMENT_TYPES),
        spec_field("exemption_class", "enum", required=True, enum=EXEMPTION_CLASSES),
        spec_field("protected_minimum_cents", "int", required=False),
        spec_field("max_offset_pct", "num", required=False),
    ])
    # Conditional-field discipline (PRD §3.2): PARTIAL carries a floor of zero
    # or more and a fraction in (0, 1]; EXEMPT/FULL leave both absent or null.
    if data["exemption_class"] == "PARTIAL":
        if data["protected_minimum_cents"] is None:
            raise err_invalid_request("protected_minimum_cents is required when exemption_class is PARTIAL")
        if data["protected_minimum_cents"] < 0:
            raise err_invalid_request("protected_minimum_cents must be at least 0")
        if data["max_offset_pct"] is None:
            raise err_invalid_request("max_offset_pct is required when exemption_class is PARTIAL")
        if not (0 < data["max_offset_pct"] <= 1):
            raise err_invalid_request("max_offset_pct must be greater than 0 and at most 1")
    else:
        if data["protected_minimum_cents"] is not None:
            raise err_invalid_request("protected_minimum_cents must be absent unless exemption_class is PARTIAL")
        if data["max_offset_pct"] is not None:
            raise err_invalid_request("max_offset_pct must be absent unless exemption_class is PARTIAL")

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "payment_type": data["payment_type"],
        "exemption_class": data["exemption_class"],
        "protected_minimum_cents": data["protected_minimum_cents"],
        "max_offset_pct": data["max_offset_pct"],
        "status": "DRAFT",
    })
    STORE["policies"][ent["id"]] = ent
    return ok(serialize_policy(ent), 201)


@bp.post("/exemption-policies/<string:exemptionPolicyId>/activate")
def activate_policy(exemptionPolicyId):
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    validate_body(get_body(), [])
    policy = STORE["policies"].get(exemptionPolicyId)
    if policy is None:
        raise err_not_found("Exemption policy not found")
    if policy["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT policy can be activated")
    # Activation supersedes: the incumbent ACTIVE policy for the same
    # payment_type is immediately RETIRED (PRD §3.2).
    for other in STORE["policies"].values():
        if (
            other["id"] != policy["id"]
            and other["payment_type"] == policy["payment_type"]
            and other["status"] == "ACTIVE"
        ):
            other["status"] = "RETIRED"
            touch(other)
    policy["status"] = "ACTIVE"
    touch(policy)
    return ok(serialize_policy(policy))
