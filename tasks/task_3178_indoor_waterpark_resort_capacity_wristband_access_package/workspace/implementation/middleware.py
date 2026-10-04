"""Authentication header extraction and role checking."""

from flask import request

import errors

RECOGNISED_ROLES = (
    "platform_ops",
    "FrontDesk",
    "AquaticsManager",
    "GateAttendant",
    "Group",
    "Anonymous",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_group(self):
        return self.role == "Group"


def authenticate():
    """PRD 2.1: both headers required; unknown role refused."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    if user_id == "" or role == "":
        raise errors.unauthenticated()
    if role not in RECOGNISED_ROLES:
        raise errors.unauthenticated()
    return Caller(user_id, role)


def require(caller, *roles):
    if caller.role not in roles:
        raise errors.forbidden()


def require_group_ownership(caller, parent_id):
    """PRD 2.1: a Group may only touch resources its own GroupBooking owns."""
    if caller.is_group and caller.user_id != parent_id:
        raise errors.ownership_mismatch()