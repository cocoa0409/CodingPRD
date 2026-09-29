"""ReportingCycle ledger, posture gating and the reopen cascade."""
from db import store, touch
from errors import fail
from svc_common import (checks_of, components_of, files_of, publications_of,
                        restatements_of)

FROZEN_POSTURES = ("FROZEN", "ARCHIVED")


def recompute_ledger(cycle):
    """calculations.cycle_active_record_count. The caller owns the single version bump."""
    total = 0
    count = 0
    for f in files_of(cycle["id"]):
        if f["status"] in ("ACTIVE", "LOCKED"):
            total += f["record_count"]
        if f["status"] != "SUPERSEDED":
            count += 1
    cycle["active_record_count"] = total
    cycle["frozen_file_count"] = count


def require_not_frozen(cycle):
    """Priority 6: pre-freeze work is refused once the cycle is FROZEN or ARCHIVED."""
    if cycle["snapshot_posture"] in FROZEN_POSTURES:
        fail("ERR_CYCLE_FROZEN", "the governing reporting cycle is frozen")


def require_frozen(cycle):
    """Priority 8: post-freeze work requires FROZEN or ARCHIVED."""
    if cycle["snapshot_posture"] not in FROZEN_POSTURES:
        fail("ERR_CYCLE_NOT_FROZEN", "the governing reporting cycle is not frozen")


def require_posture(cycle, allowed):
    """Priority 9: every remaining posture mismatch."""
    if cycle["snapshot_posture"] not in allowed:
        fail("ERR_INVALID_CYCLE_STATE",
             "the reporting cycle posture %s does not permit this operation"
             % cycle["snapshot_posture"])


def require_not_archived(cycle):
    """Priority 9: no mutation of any child of an ARCHIVED cycle."""
    if cycle["snapshot_posture"] == "ARCHIVED":
        fail("ERR_INVALID_CYCLE_STATE", "the reporting cycle is archived")


def void_checks(component):
    """Void every non-VOIDED EditCheck of the component, in sequence_no ASC order."""
    for check in checks_of(component["id"]):
        if check["status"] in ("OPEN", "EXPLAINED", "REJECTED", "ACCEPTED", "WAIVED"):
            check["status"] = "VOIDED"
            touch(check)


def cascade_publications(component):
    """Levels below a decertification: visit publications, then void their restatements.

    Visiting is versioning: every visited row advances its version even when its
    status value does not change. WITHDRAWN rows are terminal and never visited.
    """
    for pub in publications_of(component["id"]):
        if pub["publication_status"] == "WITHDRAWN":
            continue
        pub["publication_status"] = "RESTATEMENT_PENDING"
        touch(pub)
        for req in restatements_of(pub["id"]):
            if req["status"] == "SUBMITTED":
                req["status"] = "VOIDED"
                touch(req)


def cascade_reopen(cycle):
    """L2-L4 of the cycle reopen cascade (PRD 2.7 rule 1)."""
    for component in components_of(cycle["id"]):
        if component["prep_status"] != "CERTIFIED":
            continue
        component["prep_status"] = "DRAFT"
        component["certified_by_user_id"] = None
        component["certification_statement"] = None
        component["edit_status"] = "NOT_RUN"
        component["fatal_open_count"] = 0
        void_checks(component)
        touch(component)
        cascade_publications(component)


def bubble_archive(cycle):
    """FROZEN -> ARCHIVED once every component of the cycle is SUBMITTED (PRD 2.7)."""
    if cycle["snapshot_posture"] != "FROZEN":
        return
    rows = components_of(cycle["id"])
    if not rows:
        return
    if all(c["prep_status"] == "SUBMITTED" for c in rows):
        cycle["snapshot_posture"] = "ARCHIVED"
        touch(cycle)


def cycle_by_code(cycle_code):
    for c in store.cycles.values():
        if c["cycle_code"] == cycle_code:
            return c
    return None
