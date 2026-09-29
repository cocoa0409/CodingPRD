"""Authentication, authorization, operator identity and ownership (PRD 2.1).

Ladder rungs 1 (authentication), 2 (authorization), 3 (operator identity
resolution) and 6 (ownership) all live here.
"""
from flask import request

import config
import store
from errors import fail


class Actor(object):
    def __init__(self, user_id, role, business=None):
        self.user_id = user_id
        self.role = role
        self.business = business

    @property
    def is_operator(self):
        return self.role == config.ROLE_OPERATOR

    @property
    def is_admin(self):
        return self.role == config.ROLE_DISTRICT_ADMIN

    @property
    def anonymous(self):
        return self.role is None


def authenticate(allowed_roles, public=False):
    """Run rungs 1, 2 and 3 and return the resolved Actor."""
    user_id = request.headers.get(config.HEADER_USER_ID)
    role = request.headers.get(config.HEADER_USER_ROLE)

    if public and not role:
        # One of the ten public reads: the header requirement is waived entirely
        # and ERR_UNAUTHENTICATED cannot arise.
        return Actor(user_id or None, None)

    if not public:
        if user_id is None or user_id == "" or role is None or role == "":
            fail("ERR_UNAUTHENTICATED", "Both %s and %s are required." % (
                config.HEADER_USER_ID, config.HEADER_USER_ROLE))
        if role not in config.ALL_ROLES:
            fail("ERR_UNAUTHENTICATED", "Unknown role %r." % role)
    else:
        if role not in config.ALL_ROLES:
            # Cannot be ERR_UNAUTHENTICATED here; an unusable role simply is not
            # in the operation's authorized list.
            fail("ERR_FORBIDDEN_ROLE", "Role %r may not perform this operation." % role)

    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %r may not perform this operation." % role)

    business = None
    if role == config.ROLE_OPERATOR:
        if user_id:
            business = store.state.businesses.get(user_id)
            if business is None:
                fail("ERR_OPERATOR_IDENTITY_UNKNOWN",
                     "No lodging business is registered under %r." % user_id)
        elif not public:
            fail("ERR_OPERATOR_IDENTITY_UNKNOWN", "No lodging business identity supplied.")

    return Actor(user_id or None, role, business)


def require_owner(actor, lodging_business_id):
    """Rung 6.  Only LodgingOperator is constrained; the administrator is exempt."""
    if actor.is_operator and actor.user_id != lodging_business_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting operator does not own this resource.")


def require_action_role(role, allowed, message):
    """Dispute-proceeding role split, enforced as an authorization decision."""
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", message)
