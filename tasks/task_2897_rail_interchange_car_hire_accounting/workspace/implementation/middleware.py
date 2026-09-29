"""Authentication, role authorisation, path resolution and party standing.

Implements PRD section 2.8 steps 1-5 (role present, role known, role
authorised, acting railroad resolves, path identifiers left to right) and the
helpers used by step 9 (party standing) and step 18 (suspension).
"""
import functools

from flask import g, request

import db
from errors import fail


def _resolve_identity(roles):
    role = request.headers.get(db.HEADER_ROLE)
    # step 1 -- the role header must be present and non-empty
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    # step 2 -- it must name one of the five roles
    if role not in db.ALL_ROLES:
        fail("ERR_UNKNOWN_ROLE")
    # step 3 -- the role must appear on this endpoint's list
    if role not in roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    g.role = role
    g.actor_id = request.headers.get(db.HEADER_USER)
    g.actor = None
    g.acting_road_id = None
    # step 4 -- the four entity backed roles must resolve to a railroad
    if role in db.ENTITY_BACKED_ROLES:
        actor_id = g.actor_id
        if actor_id is None or actor_id.strip() == "" or actor_id not in db.railroads:
            fail("ERR_ACTING_RAILROAD_UNKNOWN")
        g.actor = db.railroads[actor_id]
        g.acting_road_id = actor_id


def endpoint(roles, path_params=None, exempt=False):
    """Wrap a Flask view with the global evaluation prefix.

    ``path_params`` is an ordered list of ``(url_kwarg, store_kind)`` pairs.
    They are resolved left to right so the leftmost missing identifier is the
    one reported (PRD section 2.8 step 5).  Resolved rows are handed to the
    view as positional arguments in the same order.
    """
    params = path_params or []

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            if exempt:
                g.role = request.headers.get(db.HEADER_ROLE)
                g.actor_id = request.headers.get(db.HEADER_USER)
                g.actor = None
                g.acting_road_id = None
            else:
                _resolve_identity(roles)
            rows = []
            for name, kind in params:
                rows.append(db.lookup(kind, kwargs.get(name)))
            return fn(*rows)

        return wrapper

    return decorator


def is_admin():
    return g.role == db.ROLE_ADMIN


def acting():
    return g.acting_road_id


# --------------------------------------------------------------------------
# step 9 -- party standing
# --------------------------------------------------------------------------


def require_party(*road_ids):
    """The acting railroad must be one of the named roads.

    The ClearinghouseAdmin identity is opaque and is treated as a party to
    everything (PRD section 2.1).
    """
    if is_admin():
        return
    allowed = {r for r in road_ids if r}
    if g.acting_road_id not in allowed:
        fail("ERR_NOT_A_PARTY_TO_RESOURCE")


def party_car(car):
    require_party(car["owner_road_id"], car["current_handling_road_id"])


def party_movement(movement):
    require_party(movement["handling_road_id"], movement["owner_road_id"])


def party_cycle(cycle):
    require_party(cycle["payer_road_id"], cycle["payee_road_id"])


def party_claim(claim):
    require_party(claim["filed_by_road_id"], claim["against_road_id"])


def party_dispute(dispute):
    require_party(dispute["filed_by_road_id"], dispute["respondent_road_id"])


def party_bill(bill):
    require_party(bill["billing_road_id"], bill["responsible_road_id"])


def party_correction(correction):
    require_party(correction["filed_by_road_id"], correction["counterparty_road_id"])


def party_ledger(entry):
    require_party(entry["debit_road_id"], entry["credit_road_id"])


# --------------------------------------------------------------------------
# step 18 -- suspension
# --------------------------------------------------------------------------


def require_active(*road_ids):
    seen = set()
    for road_id in road_ids:
        if not road_id or road_id in seen:
            continue
        seen.add(road_id)
        road = db.railroads.get(road_id)
        if road is not None and road["status"] == "SUSPENDED":
            fail("ERR_RAILROAD_SUSPENDED")


def require_acting_active():
    require_active(g.acting_road_id)
