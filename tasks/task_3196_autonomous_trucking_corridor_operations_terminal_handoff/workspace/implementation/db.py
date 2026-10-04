"""In-memory entity store.

Storage is deliberately in-memory only — Python dicts keyed by id — with no
SQLite file, no JSON dump on disk and no /tmp cache, so that a fresh `start.sh`
invocation wipes every byte of state (PRD §2.10 "Every entity in this system is
addressable by an `id` that the server mints as a plain UUID").

Nothing is seeded here. Every dict starts empty; every entity a caller needs is
constructed through a declared endpoint (§4).
"""

import threading

_lock = threading.RLock()

TABLES = (
    # §1.1 entity tables, in declaration order
    "corridors",
    "terminals",
    "driver_prospects",
    "state_authorities",
    "launch_readiness_checks",
    "run_plans",
    "carriers",
    "shipper_commitments",
    "terminal_service_windows",
    "remote_support_assignments",
    "incident_reports",
    "regulatory_engagements",
    "safety_cases",
    "maintenance_programs",
    "multi_day_holds",
    "driver_transitions",
    "ledger_checkpoints",
    "fleet_units",
    "run_plan_chassis",
    "shipping_instructions",
    "container_units",
    "run_plan_haulers",
    "security_records",
    "clause_variants",
    "agreement_codes",
)

_store = {name: {} for name in TABLES}

# Rows written for the first time during the current request.  §2.10: "`version`
# is a plain integer starting at 1 and incrementing by exactly 1 on every
# mutation" — deriving a new row's initial computed fields is part of the
# creation, not a further mutation of an existing resource, so a freshly created
# row answers `version == 1`.  The set is cleared at the start and the end of
# every request by app.py.
_fresh_ids = set()

# Side maps kept outside the entity tables so that no bookkeeping field leaks
# into a resource representation.
sides = {
    # Transition enrolment ids that scored RIDE_ALONG_VERIFIED on a run plan.
    # §3.4: "every driver transition attached to the run that has reached
    # RIDE_ALONG_VERIFIED increments the commitment's verified_ride_along_count".
    "run_ride_along_transitions": {},   # RunPlan.id -> [DriverTransition.id]
    # Container units a service window was requested for, in order.
    # §3.10: "A booking opens as a ShippingInstruction created against a
    # run_plan_id ... with the container_unit_ids to be attached."
    "instruction_units": {},            # ShippingInstruction.id -> [ContainerUnit.id]
    # Container units released during a rejection.
    # §3.10: "returns each container in INGATED or LOADED to PENDING".
    "declined_window_units": {},
}


def reset():
    """Wipe every table. Called once at boot by app.py."""
    with _lock:
        for name in TABLES:
            _store[name].clear()
        for key in sides:
            sides[key].clear()
        _fresh_ids.clear()


def open_request():
    """Mark the start of a request: no row is 'fresh' yet."""
    _fresh_ids.clear()


def close_request():
    """Mark the end of a request: every row written during it is now existing."""
    _fresh_ids.clear()


def note_fresh(row):
    _fresh_ids.add(row["id"])


def is_fresh(row):
    return row.get("id") in _fresh_ids


def t(name):
    return _store[name]


def put(name, row):
    with _lock:
        _store[name][row["id"]] = row
    return row


def get(name, rid):
    return _store[name].get(rid)


def delete(name, rid):
    with _lock:
        return _store[name].pop(rid, None)


def all_rows(name):
    return list(_store[name].values())


def where(name, **cond):
    out = []
    for row in _store[name].values():
        if all(row.get(k) == v for k, v in cond.items()):
            out.append(row)
    return out


def by(name, field, value):
    return [row for row in _store[name].values() if row.get(field) == value]


def touch(row, clock_iso):
    """§2.10: `updated_at` refreshes and `version` increments by exactly 1 on
    every mutation, including recomputes the server performs on its own behalf.

    A row that was written for the first time during this request is still at
    version 1: deriving its initial computed fields is part of the creation, not
    a subsequent mutation of an existing resource.
    """
    row["updated_at"] = clock_iso
    if is_fresh(row):
        return
    row["version"] = int(row.get("version", 1)) + 1


def sort_created(rows):
    """§2.3: list results are ordered by creation timestamp ascending."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))