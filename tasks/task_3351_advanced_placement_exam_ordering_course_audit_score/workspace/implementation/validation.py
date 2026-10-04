"""The ordered validation ladder (PRD section 2.6).

Every request is evaluated against the twenty-nine ranks in ascending order and
the first failing rank wins. Transition endpoints run this gate before any side
effect is applied.
"""

import auth
import core
import machines
from errors import fail


def require_version(payload, field, row):
    """Rank 27 - the four mandatory OCC fields."""
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if value != row["version"]:
        fail("ERR_STALE_VERSION",
             "%s is %s but the current version is %s." % (field, value, row["version"]))


def optional_version(payload, field, row):
    """The optional version members carried by three non-OCC endpoints."""
    if field not in payload or payload[field] is None:
        return
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if value != row["version"]:
        fail("ERR_STALE_VERSION",
             "%s is %s but the current version is %s." % (field, value, row["version"]))


def check_state(row, store_key, to_status):
    """Ranks 7 and 8 - the current status must admit the target status.

    Rank 7 is the from-state check against the machine's declared edges.

    Rank 8's terminal veto is applied only where the machine declares no edge
    for the requested move. The PRD states both a terminal-state list and, in
    the same breath, working transitions out of those states, and the specific
    functional sentences win over the generic rank text:

      PRD 3.5: "a shipment in `SEAL_BROKEN` may be returned by a `PlatformAdmin`
      once every irregularity case created from that seal break has reached
      `CONFIRMED` or `DISMISSED`" and "The machine declares `RECEIVED`,
      `RETURNED` and `SEAL_BROKEN` as its terminal states, and defines one
      further edge out of `SEAL_BROKEN` - to `RETURNED` - for sending
      compromised material back to the program."

      PRD 3.4: "Cancellation and reinstatement bracket the registration's
      terminal state ... Reinstatement is a `PlatformAdmin` reversal available
      only while the owning order is `OPEN` and the current window is
      `REGULAR`; it returns the registration to `REGISTERED`".

      PRD 3.8: "Both brakes are reversible: a withheld score returns to
      `RELEASED` once the withholding request is withdrawn, and a cancelled
      score returns to `AGGREGATED`".

    A terminal state with no declared outgoing edge keeps the original
    behaviour: rank 7 refuses it with `ERR_INVALID_STATE` before rank 8 is
    reached (the pinned first-failing-rank rule).
    """
    field = machines.STATUS_FIELD[store_key]
    current = row[field]
    declared = (current, to_status) in machines.EDGES[store_key]
    if not declared:
        fail("ERR_INVALID_STATE",
             "A %s row in %s cannot move to %s." % (store_key, current, to_status))
    # Rank 8's veto is confined to a terminal state the machine gives no way out
    # of. Every terminal state that does carry a declared outgoing edge is one
    # the PRD documents as a working operation (see above), so it is admitted.
    if current in machines.TERMINAL[store_key] and not machines.has_outgoing_edge(store_key, current):
        fail("ERR_ALREADY_TERMINAL",
             "A %s row in the terminal state %s admits no further transition." % (store_key, current))


def transition_gate(store_key, rid, payload, occ_field=None, actor=None):
    """Ranks 4, 5, 7, 8 and the OCC check, in the pinned order."""
    row = core.require(store_key, rid)                                   # rank 5
    to_status = payload.get("to_status")
    if to_status is None:
        fail("ERR_INVALID_REQUEST", "Field 'to_status' is required.")
    sod_statuses = machines.SOD_STATUSES.get(store_key)
    if sod_statuses and to_status in sod_statuses:                       # rank 4
        auth.check_sod(actor, row.get(machines.SOD_FIELD[store_key]))
    if occ_field:
        require_version(payload, occ_field, row)                         # rank 27
    check_state(row, store_key, to_status)                               # ranks 7, 8
    return row, to_status


def require_fk(store_key, rid, label):
    """Rank 6 - payload foreign keys must resolve."""
    if rid is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % label)
    row = core.get(store_key, rid)
    if row is None:
        fail("ERR_FK_NOT_FOUND", "%s '%s' does not resolve to an existing row." % (label, rid))
    return row


def require_unique(store_key, field, value, scope=None, scope_field=None):
    """Rank 28 - the declared unique constraints."""
    for row in core.rows(store_key):
        if row.get(field) != value:
            continue
        if scope is not None and row.get(scope_field) != scope:
            continue
        fail("ERR_DUPLICATE_RESOURCE", "%s '%s' already exists." % (field, value))


def require_window_open(window):
    """Rank 11 - registrations and submissions need REGULAR or LATE."""
    if window not in ("REGULAR", "LATE"):
        fail("ERR_ORDER_WINDOW_CLOSED",
             "The ordering window at the logical clock is %s." % window)
