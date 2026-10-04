"""Lookup helpers: path resolution, container resolution and row retrieval.

PRD §2.11 fixes left-to-right resolution: the first segment that does not
correspond to an existing row is the one whose not-found error is returned.
"""

from db import STORE
from errors import fail


def member(mid):
    row = STORE.members.get(mid)
    if row is None:
        fail("ERR_MEMBER_NOT_FOUND", "No member exists with id %s." % mid)
    return row


def account(aid):
    row = STORE.accounts.get(aid)
    if row is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "No account exists with id %s." % aid)
    return row


def membership(mid):
    row = STORE.memberships.get(mid)
    if row is None:
        fail("ERR_MEMBERSHIP_NOT_FOUND", "No membership exists with id %s." % mid)
    return row


def pod(pid):
    row = STORE.pods.get(pid)
    if row is None:
        fail("ERR_POD_NOT_FOUND", "No pod exists with id %s." % pid)
    return row


def vehicle(vid):
    row = STORE.vehicles.get(vid)
    if row is None:
        fail("ERR_VEHICLE_NOT_FOUND", "No vehicle exists with id %s." % vid)
    return row


def reservation(rid):
    row = STORE.reservations.get(rid)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND", "No reservation exists with id %s." % rid)
    return row


def incident(iid):
    row = STORE.incidents.get(iid)
    if row is None:
        fail("ERR_INCIDENT_NOT_FOUND", "No incident exists with id %s." % iid)
    return row


def maintenance_order(oid):
    row = STORE.maintenance_orders.get(oid)
    if row is None:
        fail("ERR_MAINTENANCE_ORDER_NOT_FOUND", "No maintenance order exists with id %s." % oid)
    return row


def access_event(eid):
    row = STORE.access_events.get(eid)
    if row is None:
        fail("ERR_ACCESS_EVENT_NOT_FOUND", "No access event exists with id %s." % eid)
    return row


def fuel_transaction(tid):
    row = STORE.fuel_transactions.get(tid)
    if row is None:
        fail("ERR_FUEL_TRANSACTION_NOT_FOUND", "No fuel-card transaction exists with id %s." % tid)
    return row


def driving_report(rid):
    row = STORE.driving_reports.get(rid)
    if row is None:
        fail("ERR_INVALID_REQUEST", "No driving-record report exists with id %s." % rid)
    return row


def signal(sid):
    row = STORE.community_signals.get(sid)
    if row is None:
        fail("ERR_INVALID_REQUEST", "No community signal exists with id %s." % sid)
    return row