"""Imminent-danger order issuance/termination cascades (PRD sections 2.9, 3.5)."""
import clock
import store
from errors import ApiError, ERR_IDO_ACTIVE_EXISTS


def assert_issuable(mine_id, issued_at):
    """One-active-order rule with closed-interval occupation.

    Rejects when any non-TERMINATED order exists at the mine, or when the new
    issued_at is not strictly after a prior terminated order's terminated_at.
    """
    for order in store.idos.values():
        if order["mine_id"] != mine_id:
            continue
        if order["status"] != "TERMINATED":
            raise ApiError(
                ERR_IDO_ACTIVE_EXISTS,
                "a non-terminated imminent-danger order already exists at this mine",
            )
        if order["terminated_at"] is not None and issued_at <= order["terminated_at"]:
            raise ApiError(
                ERR_IDO_ACTIVE_EXISTS,
                "issuance must be strictly after a prior order's terminated_at",
            )


def halt_cascade(mine):
    """IDO issuance cascade: halt the mine and suspend in-progress inspections."""
    if mine["production_status"] != "HALTED":
        mine["production_status"] = "HALTED"
        store.touch(mine)
    for inspection in store.inspections.values():
        if inspection["mine_id"] == mine["id"] and inspection["status"] == "IN_PROGRESS":
            inspection["status"] = "SUSPENDED"
            store.touch(inspection)


def create_ido(mine, hazard_description, inspection_id, issued_by_inspector_id):
    """Create an ISSUED order and fire the halt cascade immediately."""
    order = store.new_entity(store.idos, {
        "mine_id": mine["id"],
        "inspection_id": inspection_id,
        "issued_by_inspector_id": issued_by_inspector_id,
        "hazard_description": hazard_description,
        "issued_at": clock.now(),
        "miners_withdrawn_count": None,
        "withdrawal_confirmed_at": None,
        "abatement_verified_at": None,
        "verified_by_inspector_id": None,
        "terminated_at": None,
        "status": "ISSUED",
    })
    halt_cascade(mine)
    return order


def terminate_cascade(order):
    """Reverse the halt when the terminating order is the last active one."""
    mine = store.mines.get(order["mine_id"])
    if mine is None:
        return
    remaining = any(
        other["mine_id"] == mine["id"]
        and other["id"] != order["id"]
        and other["status"] != "TERMINATED"
        for other in store.idos.values()
    )
    if remaining:
        return
    if mine["production_status"] != "NORMAL":
        mine["production_status"] = "NORMAL"
        store.touch(mine)
    for inspection in store.inspections.values():
        if inspection["mine_id"] == mine["id"] and inspection["status"] == "SUSPENDED":
            inspection["status"] = "IN_PROGRESS"
            store.touch(inspection)
