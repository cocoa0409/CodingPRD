"""Auth header extraction, role checks and ownership helpers.

Header names and role spellings are taken verbatim from PRD §2.1 and the
scaffold's auth validations (priorities 1-3):

  priority 1  X-User-Role present and one of PlatformAdmin|Account|Recipient
              -> ERR_UNAUTHENTICATED (401)
  priority 2  X-User-ID present and non-empty when X-User-Role is entity_backed
              (Account, Recipient) -> ERR_UNAUTHENTICATED (401)
  priority 3  acting role listed in the endpoint's roles -> ERR_FORBIDDEN (403)

Identity semantics (PRD §2.1):
  PlatformAdmin  X-User-ID is an opaque operator id, never matched to an entity
  Account        X-User-ID is Account.id (sender_account_id / owning_account_id
                 / account_id is the owned field)
  Recipient      X-User-ID is Recipient.id, and the recipient may act only on
                 the Recipient row it names
"""

from flask import request

from db import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
)

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ACCOUNT = "Account"
ROLE_RECIPIENT = "Recipient"

DECLARED_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ACCOUNT, ROLE_RECIPIENT)

# Roles whose X-User-ID names a persisted entity (scaffold §1.7 identity field).
ENTITY_BACKED_ROLES = (ROLE_ACCOUNT, ROLE_RECIPIENT)

HEADER_ROLE = "X-User-Role"
HEADER_USER_ID = "X-User-ID"


class Actor:
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_admin(self):
        return self.role == ROLE_PLATFORM_ADMIN

    @property
    def is_account(self):
        return self.role == ROLE_ACCOUNT

    @property
    def is_recipient(self):
        return self.role == ROLE_RECIPIENT

    def __repr__(self):
        return "Actor(%r, %r)" % (self.role, self.user_id)


def authenticate(allowed_roles):
    """Run validations 1-3 for an endpoint declaring `allowed_roles`."""
    raw_role = request.headers.get(HEADER_ROLE)
    if raw_role is None or raw_role.strip() == "" or raw_role not in DECLARED_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED[0],
            "X-User-Role header is missing, empty, or not one of "
            "PlatformAdmin, Account, Recipient",
            ERR_UNAUTHENTICATED[1],
        )

    raw_user_id = request.headers.get(HEADER_USER_ID)
    if raw_role in ENTITY_BACKED_ROLES:
        if raw_user_id is None or raw_user_id.strip() == "":
            raise ApiError(
                ERR_UNAUTHENTICATED[0],
                "X-User-ID header is required and must be non-empty for role %s"
                % raw_role,
                ERR_UNAUTHENTICATED[1],
            )
    actor = Actor(raw_role, (raw_user_id or "").strip())

    if raw_role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN[0],
            "role %s may not perform this operation" % raw_role,
            ERR_FORBIDDEN[1],
        )
    return actor


def owned_by_account(actor, resource_account_id):
    """Ownership gate for the Account role (PRD §2.4).

    PlatformAdmin is never compared to an entity id. A mismatching Account
    caller is refused with ERR_FORBIDDEN, the only 403 the ladder offers for a
    permission failure that is not segregated-duties.
    """
    if actor.is_account and resource_account_id is not None:
        if actor.user_id != resource_account_id:
            raise ApiError(
                ERR_FORBIDDEN[0],
                "account %s does not own this resource" % actor.user_id,
                ERR_FORBIDDEN[1],
            )


def acting_account_id(actor):
    """The Account.id named by an Account-role caller."""
    return actor.user_id


def envelope_of_account(actor, envelope):
    owned_by_account(actor, envelope.get("sender_account_id"))
    return envelope


def find_envelope(envelope_id):
    return db.envelope(envelope_id)


def find_account(account_id):
    return db.account(account_id)