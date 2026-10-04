"""Layered access governance: grant creation, the adding-layers rule, sharing
scope reconciliation and audit grading (PRD §2.10, §3.7).

The layered-access resolution walks an environment's non-revoked grants for one
operator and accumulates a set of layer names:
  * PROFILE       - any grant with principal_type == PROFILE
  * PERMISSION_SET- any grant with principal_type == PERMISSION_SET
  * SHARING       - any grant whose (non-empty) object_prefix matches the
                    namespace of a non-UNINSTALLED installation in the same
                    environment
An operator overreaches when the layer sum is strictly greater than the
standard budget of 2 — exactly three accumulated layers are required.
"""

import db
from services import common

PROFILE = "PROFILE"
PERMISSION_SET = "PERMISSION_SET"
SHARING = "SHARING"

ADMIN_STANDARD_ACCESS_LAYER_BUDGET = 2
ACCESS_LAYER_BLOCK_DENOMINATOR_ADMIN = 3
ACCESS_LAYER_BLOCK_DENOMINATOR_STANDARD = 2
AUDIT_GRADE_BLOCKED_MIN = 3

ACTING_ADMIN_ROLES = ("PlatformAdmin",)


def grants_of(environment_id, user_id=None, include_revoked=False):
    rows = []
    for grant in db.permission_assignments.values():
        if grant["environment_id"] != environment_id:
            continue
        if not include_revoked and grant.get("revoked"):
            continue
        if user_id is not None and grant["user_id"] != user_id:
            continue
        rows.append(grant)
    return rows


def layer_set(environment_id, user_id):
    """The distinct layers an operator holds in the environment (§3.7)."""
    grants = grants_of(environment_id, user_id)
    layers = set()
    if any(g["principal_type"] == PROFILE for g in grants):
        layers.add(PROFILE)
    if any(g["principal_type"] == PERMISSION_SET for g in grants):
        layers.add(PERMISSION_SET)
    namespaces = common.installed_namespaces(environment_id)
    if any(
        g.get("object_prefix", "") != "" and g.get("object_prefix") in namespaces
        for g in grants
    ):
        layers.add(SHARING)
    return layers


def layer_sum(environment_id, user_id):
    return len(layer_set(environment_id, user_id))


def overreaches(environment_id, user_id, budget=ADMIN_STANDARD_ACCESS_LAYER_BUDGET):
    """Overreach is strictly greater than the standard access-layer budget."""
    return layer_sum(environment_id, user_id) > budget


def in_scope_users(environment_id):
    """The operators addressed by the environment's non-revoked grants."""
    users = []
    for grant in grants_of(environment_id):
        if grant["user_id"] not in users:
            users.append(grant["user_id"])
    return users


def create_grant(actor, env, b):
    from validate import optional_string, require_enum, require_string

    principal_type = require_enum(b, "principal_type", (PROFILE, PERMISSION_SET))
    principal_name = require_string(b, "principal_name")
    user_id = require_string(b, "user_id")
    object_prefix = optional_string(b, "object_prefix", default="")

    grant = db.create(
        db.permission_assignments,
        {
            "environment_id": env["id"],
            "principal_type": principal_type,
            "principal_name": principal_name,
            "user_id": user_id,
            "object_prefix": object_prefix,
            "sharing_rule_scope": "PRIVATE",
            "revoked": False,
        },
    )
    # The grant operation recomputes sharing_rule_scope for every non-revoked
    # grant of the environment (§3.7).
    recompute_sharing_scopes(env, mode="NAMESPACE_READ")
    db.touch(env)
    return grant


def recompute_sharing_scopes(env, mode="NAMESPACE_READ"):
    """Re-derive PermissionAssignment.sharing_rule_scope from installed state.

    Two derivation modes are declared, and both are driven by a cascade:

    * the managed-package installation cascade derives NAMESPACE_READ for the
      grants it scopes to the installed namespace (a grant is counted toward
      the sharing layer only when its non-empty object_prefix equals the
      namespace of a non-UNINSTALLED installation in the same environment);
    * the applied-release cascade re-derives ORG_WIDE for every non-revoked
      grant of the environment (PRD §2.7, §3.3, §3.4).
    """
    namespaces = common.installed_namespaces(env["id"])
    for grant in db.permission_assignments.values():
        if grant["environment_id"] != env["id"]:
            continue
        if grant.get("revoked"):
            continue
        if mode == "ORG_WIDE":
            scope = "ORG_WIDE"
        else:
            prefix = grant.get("object_prefix", "")
            scope = "NAMESPACE_READ" if (prefix != "" and prefix in namespaces) else "PRIVATE"
        if grant.get("sharing_rule_scope") != scope:
            grant["sharing_rule_scope"] = scope
            db.touch(grant)


def audit_overreach_count(environment_id, scope_ids):
    """The number of in-scope OPERATORS judged to overreach (PRD §2.10).

    The count is over distinct operators, not over assignment rows — an
    operator whose access overreaches is counted once however many of their
    grants are in scope.
    """
    operators = []
    for assignment_id in scope_ids:
        assignment = db.permission_assignments.get(assignment_id)
        if assignment is None:
            continue
        if assignment["user_id"] not in operators:
            operators.append(assignment["user_id"])
    return sum(1 for user in operators if overreaches(environment_id, user))


def audit_grade(overreach_count):
    if overreach_count >= AUDIT_GRADE_BLOCKED_MIN:
        return "BLOCKED"
    if overreach_count >= 1:
        return "ATTENTION"
    return "PASS"


def assignment_entries(environment_id, scope_ids):
    """One {assignment_id, user_id, overreach} entry per reviewed assignment."""
    entries = []
    for assignment_id in scope_ids:
        assignment = db.permission_assignments.get(assignment_id)
        if assignment is None:
            continue
        entries.append(
            {
                "assignment_id": assignment_id,
                "user_id": assignment["user_id"],
                "overreach": overreaches(environment_id, assignment["user_id"]),
            }
        )
    return entries