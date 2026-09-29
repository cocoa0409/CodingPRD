"""PRD 2.1 -- authentication headers, the five roles and ownership narrowing."""

from flask import g, request

import store
from errors import fail

ROLES = (
    "RegulatorOps",
    "PooledPlanProvider",
    "AdoptingEmployer",
    "ServiceProvider",
    "IndependentAuditor",
)

# The two opaque operator identities: X-User-ID is never compared to any
# entity's id and no ownership check narrows what they may reach.
OPAQUE_ROLES = ("RegulatorOps", "IndependentAuditor")

ANY_ROLE = ROLES


def identify():
    """Priorities 1 and 2 of the ladder. Runs before the body is ever parsed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid == "" or role == "":
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE")
    g.user_id = uid
    g.role = role
    return uid, role


def authorize(*allowed):
    """Priority 3: a valid role that is not authorised for the endpoint."""
    if g.role not in allowed:
        fail("ERR_UNAUTHORIZED")


def acting_service_provider():
    """The ServiceProvider row the entity-backed X-User-ID denotes."""
    return store.get("service_providers", g.user_id)


def acting_employer():
    return store.get("employers", g.user_id)


def own(plan=None, employer=None, service_provider=None, named_provider_id=None):
    """Priority 4: ownership, checked after role authorisation and before any
    state or business rule.

    `plan` is the plan document the addressed resource descends from,
    `employer` the adopting employer it descends from (when it has one), and
    `named_provider_id` the service-provider identifier a resource names when
    the acting ServiceProvider must be exactly that firm.
    """
    role = g.role
    uid = g.user_id
    if role in OPAQUE_ROLES:
        return
    if role == "PooledPlanProvider":
        if plan is None or plan.get("pooled_plan_provider_id") != uid:
            fail("ERR_NOT_RESOURCE_OWNER")
        return
    if role == "AdoptingEmployer":
        if employer is not None:
            if employer["id"] != uid:
                fail("ERR_NOT_RESOURCE_OWNER")
            return
        me = acting_employer()
        if me is None:
            fail("ERR_NOT_RESOURCE_OWNER")
        if plan is None or me["plan_document_id"] != plan["id"]:
            fail("ERR_NOT_RESOURCE_OWNER")
        return
    if role == "ServiceProvider":
        me = acting_service_provider()
        if me is None:
            fail("ERR_NOT_RESOURCE_OWNER")
        if named_provider_id is not None:
            if named_provider_id != uid:
                fail("ERR_NOT_RESOURCE_OWNER")
            return
        if plan is None or me["plan_document_id"] != plan["id"]:
            fail("ERR_NOT_RESOURCE_OWNER")
        return
    fail("ERR_NOT_RESOURCE_OWNER")


def own_if(plan=None, employer=None, service_provider=None,
           named_provider_id=None):
    """Ownership, skipped when the parent could not be resolved because the
    body foreign key was a shape defect -- priority 7 reports that instead."""
    if plan is None and employer is None:
        return
    own(plan=plan, employer=employer, service_provider=service_provider,
        named_provider_id=named_provider_id)


def own_provider(provider):
    """Ownership on a PooledPlanProvider row itself."""
    role = g.role
    if role in OPAQUE_ROLES:
        return
    if role == "PooledPlanProvider":
        if provider["id"] != g.user_id:
            fail("ERR_NOT_RESOURCE_OWNER")
        return
    fail("ERR_NOT_RESOURCE_OWNER")


def is_plan_recordkeeper(plan):
    """The acting firm must be engaged on the plan with provider_type RECORDKEEPER."""
    me = acting_service_provider()
    if me is None:
        return False
    if me["plan_document_id"] != plan["id"]:
        return False
    return me["provider_type"] == "RECORDKEEPER"


def touch():
    if not hasattr(g, "touch_set"):
        g.touch_set = store.Touch()
    return g.touch_set
