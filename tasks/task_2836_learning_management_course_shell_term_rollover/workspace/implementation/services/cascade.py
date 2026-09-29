"""Multi-record cascades.  Every cascade walks its children in created_at
ascending order and runs to completion inside the triggering request
(PRD 2.8)."""

from decimal import Decimal

from db import by_created, db, mark, now, set_field
from services import compute

ZERO = Decimal("0.00")

UNPUBLISH_TOOL_REASON = "tool placement blocked"


def term_of(shell):
    return db.terms[shell["term_id"]]


def unpublish_shell(shell, reason):
    """PUBLISHED -> PROVISIONED.  Callers own the posture gate; the
    system-driven form bypasses it deliberately (PRD 3.3 / 3.7)."""
    set_field(shell, "provisioning_state", "PROVISIONED")
    set_field(shell, "unpublish_reason", reason)
    mark(shell)
    compute.recompute_shell(shell)
    compute.recompute_term(term_of(shell))


def conclude_shell(shell):
    """PROVISIONED/PUBLISHED -> CONCLUDED.  Completes the shell's ACTIVE
    enrollments in created_at ascending order (PRD 3.3)."""
    set_field(shell, "provisioning_state", "CONCLUDED")
    mark(shell)
    for enrollment in by_created([
        e for e in db.enrollments.values()
        if e["shell_id"] == shell["id"] and e["enrollment_state"] == "ACTIVE"
    ]):
        set_field(enrollment, "enrollment_state", "COMPLETED")
        mark(enrollment)
    compute.recompute_shell(shell)
    compute.recompute_term(term_of(shell))


def remove_placement(placement):
    """REQUESTED/ACTIVE/BLOCKED -> REMOVED with origin-specific bookkeeping
    (PRD 3.7)."""
    origin = placement["placement_state"]
    set_field(placement, "placement_state", "REMOVED")
    mark(placement)
    shell = db.shells.get(placement["shell_id"])
    tool = db.tools.get(placement["tool_id"])
    if origin == "ACTIVE" and tool is not None:
        compute.rescore_tool(tool)
    if shell is not None:
        compute.recompute_shell(shell)


def archive_shell(shell):
    """CONCLUDED -> ARCHIVED.  Removes every live placement of the shell in
    created_at ascending order (PRD 3.3)."""
    set_field(shell, "provisioning_state", "ARCHIVED")
    mark(shell)
    for placement in by_created([
        p for p in db.placements.values()
        if p["shell_id"] == shell["id"]
        and p["placement_state"] in ("REQUESTED", "ACTIVE", "BLOCKED")
    ]):
        remove_placement(placement)
    compute.recompute_shell(shell)
    compute.recompute_term(term_of(shell))


def purge_shell(shell):
    """ARCHIVED -> PURGED.  Soft delete: the row stays readable by identifier
    (PRD 3.3)."""
    set_field(shell, "provisioning_state", "PURGED")
    mark(shell)
    for item in by_created([i for i in db.items.values()
                            if i["shell_id"] == shell["id"]]):
        set_field(item, "copy_state", "SKIPPED")
        set_field(item, "storage_mb", ZERO)
    compute.recompute_shell(shell)
    compute.recompute_term(term_of(shell))
    compute.recompute_rollover_pct(term_of(shell))
    compute.recompute_chargeback(db.people.get(shell["owner_person_id"]))


def block_placement(placement, reason):
    """Drives a placement into BLOCKED and runs the protective unpublish that
    follows when the owning shell loses publish readiness (PRD 3.7)."""
    origin = placement["placement_state"]
    set_field(placement, "placement_state", "BLOCKED")
    set_field(placement, "blocked_reason", reason)
    mark(placement)
    shell = db.shells.get(placement["shell_id"])
    tool = db.tools.get(placement["tool_id"])
    if origin == "ACTIVE" and tool is not None:
        compute.recompute_tool_placements(tool)
    if shell is None:
        return
    compute.recompute_shell(shell)
    if not shell["publish_readiness"] and shell["provisioning_state"] == "PUBLISHED":
        unpublish_shell(shell, UNPUBLISH_TOOL_REASON)


def block_tool_placements(tool, reason):
    for placement in by_created([
        p for p in db.placements.values()
        if p["tool_id"] == tool["id"]
        and p["placement_state"] in ("REQUESTED", "ACTIVE")
    ]):
        block_placement(placement, reason)
    compute.rescore_tool(tool)


def drop_enrollment(enrollment, shell, term):
    """ACTIVE -> DROPPED plus the freed-seat waitlist cascade (PRD 3.4)."""
    set_field(enrollment, "enrollment_state", "DROPPED")
    set_field(enrollment, "dropped_at", now())
    mark(enrollment)
    compute.recompute_shell(shell)
    return compute.run_capacity(shell, term, promote=True)
