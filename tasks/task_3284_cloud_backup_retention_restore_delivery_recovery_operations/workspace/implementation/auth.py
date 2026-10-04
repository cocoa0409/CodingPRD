"""Auth header parsing and RBAC resolution (PRD 2.1, 2.9, 3).

Two mandatory headers: `X-User-ID` and `X-User-Role`.  A request that omits
either, or that names a role outside the declared five, fails level 1 with
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.  A role that is not permitted for
the operation -- or an AccountOwner reaching for an account it does not own --
fails level 2 with ERR_UNAUTHORIZED.

Level 2 precedes the existence check (level 3), so a role that may not perform
the operation is refused with 403 even when the referenced resource is absent.
"""

from errors import (APIError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    ERR_UNAUTHORIZED)
import constants as K


class Caller(object):
    def __init__(self, user_id, role, rank):
        self.user_id = user_id
        self.role = role
        self.rank = rank

    @property
    def is_account_owner(self):
        return self.role == "AccountOwner"

    def owns(self, account_id):
        """PRD 2.1: the AccountOwner's X-User-ID is the acting Account id."""
        return self.user_id == account_id


def parse(headers):
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise APIError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       "X-User-ID header is required")
    if not role or not isinstance(role, str) or role not in K.ROLES:
        raise APIError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       "X-User-Role header must name one of: " + ", ".join(K.ROLES))
    return Caller(user_id.strip(), role, K.RANK[role])


def authorize(caller, role_cap, lease, owned_account_id=None):
    """Level 2.  `role_cap` is the minimum CAPS rank for a write, or None for a
    read gated by `lease` against LEASE."""
    if role_cap is None:
        if K.LEASE[caller.role] < lease:
            raise APIError(ERR_UNAUTHORIZED,
                           "role %s is not permitted for this operation" % caller.role)
    else:
        if K.CAPS[caller.role] < role_cap:
            raise APIError(ERR_UNAUTHORIZED,
                           "role %s is not permitted for this operation" % caller.role)
    if caller.is_account_owner and owned_account_id is not None:
        if not caller.owns(owned_account_id):
            raise APIError(ERR_UNAUTHORIZED,
                           "AccountOwner does not own the referenced account")


def require(caller, allowed, owned_account_id=None):
    """Level 2 against the endpoint's declared role set.

    The declared set is the union of SCAFFOLD 1.5 `roles` and SCAFFOLD 1.7's
    exclusive/shared operations; PRD 2.1 makes role exclusivity strict, so
    membership in the set is the test.  `owned_account_id` carries the
    AccountOwner cross-account check -- PRD 2.1 says the AccountOwner is
    confined to its own account throughout every restore, retention and
    shipment workflow.
    """
    if caller.role not in allowed:
        raise APIError(ERR_UNAUTHORIZED,
                       "role %s is not permitted for this operation" % caller.role)
    if caller.is_account_owner and owned_account_id is not None:
        if not caller.owns(owned_account_id):
            raise APIError(ERR_UNAUTHORIZED,
                           "AccountOwner does not own the referenced account")


def require_exact(caller, only_role, owned_account_id=None):
    """For the two capabilities an endpoint names verbatim (the clock and the
    storage fabric are SystemOperator-only; deletion adjudication and account
    closure are ComplianceOfficer-only)."""
    if caller.role != only_role:
        raise APIError(ERR_UNAUTHORIZED,
                       "role %s is not permitted for this operation" % caller.role)
    if caller.is_account_owner and owned_account_id is not None:
        if not caller.owns(owned_account_id):
            raise APIError(ERR_UNAUTHORIZED,
                           "AccountOwner does not own the referenced account")


# --- read role sets ---------------------------------------------------------
# Union of SCAFFOLD 1.5 `roles` with SCAFFOLD 1.7's shared_operations.  PRD 3.2
# and 3.3 explicitly open agent / set / group reads to AccountOwner ("these
# filters ... are available to BackupOperator, SystemOperator,
# ComplianceOfficer, and AccountOwner alike"), and PRD 3.4 opens retention
# change lists to AccountOwner; PRD 2.1 keeps AccountOwner out of the
# storage-fabric reads.
R_ACCOUNT_CREATE = ("AccountOwner", "SystemOperator")
R_ACCOUNT_LIST = ("SystemOperator", "ComplianceOfficer")
R_ACCOUNT_GET = ("AccountOwner", "SystemOperator", "ComplianceOfficer", "RetentionOfficer")
R_ACCOUNT_MUTATE = ("SystemOperator", "ComplianceOfficer")
R_GROUP_CREATE = ("AccountOwner", "SystemOperator")
R_GROUP_READ = ("AccountOwner", "SystemOperator", "RetentionOfficer", "BackupOperator")
R_GROUP_MUTATE = ("RetentionOfficer",)
R_POLICY_CREATE = ("RetentionOfficer",)
R_POLICY_READ = ("RetentionOfficer", "AccountOwner", "ComplianceOfficer")
R_AGENT_CREATE = ("BackupOperator",)
R_AGENT_READ = ("BackupOperator", "SystemOperator", "ComplianceOfficer", "AccountOwner")
R_AGENT_MUTATE = ("BackupOperator", "SystemOperator")
R_SET_CREATE = ("BackupOperator",)
R_SET_READ = ("BackupOperator", "SystemOperator", "ComplianceOfficer", "AccountOwner")
R_SET_MUTATE = ("BackupOperator", "ComplianceOfficer")
R_VERSION_READ = ("BackupOperator", "SystemOperator", "ComplianceOfficer", "AccountOwner")
R_RESTORE_CREATE = ("AccountOwner",)
R_RESTORE_READ = ("AccountOwner", "SystemOperator", "ComplianceOfficer")
R_RESTORE_OWNER = ("AccountOwner",)
R_RESTORE_SYSTEM = ("SystemOperator",)
R_SHIPMENT_READ = ("SystemOperator", "AccountOwner", "ComplianceOfficer")
R_SHIPMENT_SYSTEM = ("SystemOperator",)
R_SHIPMENT_OWNER = ("AccountOwner",)
R_PERIOD_CREATE = ("SystemOperator",)
R_PERIOD_READ = ("SystemOperator", "AccountOwner")
R_RC_CREATE = ("RetentionOfficer",)
R_RC_READ = ("RetentionOfficer", "ComplianceOfficer", "AccountOwner", "SystemOperator")
R_RC_MUTATE = ("RetentionOfficer",)
R_DELETION_CREATE = ("ComplianceOfficer", "AccountOwner")
R_DELETION_READ = ("ComplianceOfficer", "AccountOwner", "SystemOperator")
R_DELETION_MUTATE = ("ComplianceOfficer",)
R_POD_CREATE = ("SystemOperator",)
R_POD_READ = ("SystemOperator", "ComplianceOfficer")
R_POD_MUTATE = ("SystemOperator",)