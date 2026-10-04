"""In-memory data store. The store starts empty on every boot."""

STORES = {
    "agencies": {},
    "calendar_windows": {},
    "staff": {},
    "contracts": {},
    "phases": {},
    "milestones": {},
    "criteria": {},
    "workflow_processes": {},
    "decisions": {},
    "migration_batches": {},
    "migration_records": {},
    "reconciliation_reports": {},
    "interfaces": {},
    "certifications": {},
    "uat_cycles": {},
    "uat_sessions": {},
    "training_sessions": {},
    "training_enrollments": {},
    "unavailability_windows": {},
    "go_live_events": {},
    "support_transitions": {},
    "support_tickets": {},
    "maintenance_agreements": {},
    "audit_log": {},
}

# Order-preserving insertion sequences for stable listing (created_at sort).
SEQ = {name: 0 for name in STORES}


def put(store_name, obj):
    store = STORES[store_name]
    SEQ[store_name] += 1
    obj["_seq"] = SEQ[store_name]
    store[obj["id"]] = obj
    return obj


def get(store_name, obj_id):
    return STORES[store_name].get(obj_id)


def all_items(store_name):
    return sorted(STORES[store_name].values(), key=lambda o: o["_seq"])


def filter_items(store_name, **conds):
    out = []
    for o in all_items(store_name):
        ok = True
        for k, v in conds.items():
            if o.get(k) != v:
                ok = False
                break
        if ok:
            out.append(o)
    return out
