"""Lookup, filtering, ordering and pagination helpers shared by every route."""
import auth
import derive
import envelope
import store
from errors import fail
from validate import pagination, qbool

NOT_FOUND = {
    "Establishment": "ERR_ESTABLISHMENT_NOT_FOUND",
    "Practitioner": "ERR_PRACTITIONER_NOT_FOUND",
    "School": "ERR_SCHOOL_NOT_FOUND",
    "TrainingRecord": "ERR_TRAINING_RECORD_NOT_FOUND",
    "Workstation": "ERR_WORKSTATION_NOT_FOUND",
    "BoothRental": "ERR_BOOTH_RENTAL_NOT_FOUND",
    "Inspection": "ERR_INSPECTION_NOT_FOUND",
    "ViolationCode": "ERR_VIOLATION_CODE_NOT_FOUND",
    "ViolationFinding": "ERR_VIOLATION_FINDING_NOT_FOUND",
    "Citation": "ERR_CITATION_NOT_FOUND",
    "Hearing": "ERR_HEARING_NOT_FOUND",
    "SanitationLog": "ERR_LEDGER_ENTRY_NOT_FOUND",
    "InfectionIncident": "ERR_INFECTION_INCIDENT_NOT_FOUND",
    "LedgerEntry": "ERR_LEDGER_ENTRY_NOT_FOUND",
}


def find(kind, row_id):
    """Resolve a path or body identifier, or raise the entity's own 404."""
    row = store.COLLECTIONS[kind].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(NOT_FOUND[kind], "%s '%s' was not found." % (kind, row_id))
    return row


# ------------------------------------------------------------------ ordering
def sort_multi(rows, keys):
    """Stable multi-key sort; `keys` is a list of (keyfunc, reverse) most-significant first."""
    rows = list(rows)
    for keyfunc, reverse in reversed(keys):
        rows.sort(key=keyfunc, reverse=reverse)
    return rows


def _seq(r):
    return r["_seq"]


def by_created_asc(rows):
    return sort_multi(rows, [(lambda r: (r["created_at"], r["_seq"]), False)])


# ------------------------------------------------------------------ filtering
def filter_rows(rows, args, spec):
    """Apply optional equality filters.  `spec` maps query param -> (field, kind)."""
    for param, (field, kind) in spec.items():
        if param not in args:
            continue
        if kind == "bool":
            wanted = qbool(args, param)
            if wanted is True or wanted is False:
                rows = [r for r in rows if r[field] is wanted]
            else:
                rows = []
        else:
            raw = args.get(param)
            rows = [r for r in rows if r[field] == raw]
    return rows


def listing(rows, keys, serializer, args):
    """Order, count, window and serialize a list response."""
    limit, offset = pagination(args)
    rows = sort_multi(rows, keys)
    total = len(rows)
    window = rows[offset:offset + limit]
    return envelope.ok_list([serializer(r) for r in window], limit, offset, total)


# --------------------------------------------------- fresh derived views
def view_establishment(e):
    derive.compute_establishment(e)
    return derive.ser_establishment(e)


def view_workstation(w):
    derive.compute_workstation(w)
    return derive.ser_workstation(w)


def view_practitioner(p):
    derive.compute_practitioner(p)
    return derive.ser_practitioner(p)


def view_citation(c):
    derive.recompute_citation_outstanding(c)
    return derive.ser_citation(c)


# ------------------------------------------------------------ scope helpers
def scope_establishment(ctx, establishment_id):
    if ctx.is_owner and establishment_id != ctx.user_id:
        auth.deny()


def own_establishments(ctx, rows, field="establishment_id"):
    if ctx.is_owner:
        rows = [r for r in rows if r[field] == ctx.user_id]
    return rows
