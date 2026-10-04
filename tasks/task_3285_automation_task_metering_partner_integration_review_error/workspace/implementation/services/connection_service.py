"""Connection lifecycle: refresh, reauthorize, disconnect (PRD §3.6)."""
from calc import endpoint_coverage
from clock import Clock
from common import require_owner
from db import db
from errors import ApiError
from models import touch


def _epoch(account_id):
    return db.epoch_steps.setdefault(account_id, {"OPENING": False, "CLOSING": False})


def occupy_step(account_id, step):
    """An account holds at most one OPENING and one CLOSING step per epoch."""
    if step not in ("OPENING", "CLOSING"):
        return
    state = _epoch(account_id)
    if state.get(step):
        raise ApiError("ERR_DUPLICATE_EPOCH_STEP")
    state[step] = True


def close_epoch(account_id, step):
    """CLOSING also releases the OPENING occupation (PRD §3.6)."""
    if step != "CLOSING":
        return
    state = _epoch(account_id)
    if state.get("CLOSING"):
        raise ApiError("ERR_DUPLICATE_EPOCH_STEP")
    state["CLOSING"] = True
    state["OPENING"] = False


def _snapshots_pinning(connection_id):
    return [wv for wv in db.workflow_versions.values()
            if wv["connection_id"] == connection_id]


def refresh(connection, charge):
    if connection["status"] != "TOKEN_EXPIRED":
        raise ApiError("ERR_CONNECTION_INVALID_STATE")
    require_owner(connection)
    if connection["refresh_count"] > 4:
        # The lifetime cap is spent: the sixth refresh forces reauthorization.
        _to_reauth(connection)
        raise ApiError("ERR_TOKEN_REFRESH_CAP_EXHAUSTED")
    occupy_step(connection["account_id"], charge)
    connection["status"] = "CONNECTED"
    connection["refresh_count"] += 1
    connection["token_expires_at"] = Clock.iso_now_plus(3600)
    touch(connection)
    return connection


def _to_reauth(connection):
    connection["status"] = "REAUTH_REQUIRED"
    connection["reauth_requested_at"] = Clock.iso_now()
    touch(connection)
    for snapshot in _snapshots_pinning(connection["id"]):
        if snapshot["status"] == "CURRENT":
            snapshot["status"] = "MIGRATION_REQUIRED"
            touch(snapshot)


def reauthorize(connection, charge):
    if connection["status"] != "REAUTH_REQUIRED":
        raise ApiError("ERR_CONNECTION_INVALID_STATE")
    require_owner(connection)
    close_epoch(connection["account_id"], charge)
    connection["status"] = "CONNECTED"
    connection["reauth_requested_at"] = None
    connection["refresh_count"] = 0
    touch(connection)
    for snapshot in _snapshots_pinning(connection["id"]):
        if snapshot["status"] == "MIGRATION_REQUIRED":
            snapshot["status"] = "CURRENT"
            touch(snapshot)
    return connection


def disconnect(connection, charge):
    require_owner(connection)
    if connection["status"] != "CONNECTED":
        raise ApiError("ERR_CONNECTION_INVALID_STATE")
    close_epoch(connection["account_id"], charge)
    connection["status"] = "DISCONNECTED"
    touch(connection)
    return connection