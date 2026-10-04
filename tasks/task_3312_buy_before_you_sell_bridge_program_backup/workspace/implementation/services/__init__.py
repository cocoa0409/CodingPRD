"""Shared service helpers: stamping, mutation and serialisation.

Two rules from the PRD drive everything here:

* PRD 2.5 -- every entity carries ``id``, ``created_at``, ``updated_at`` and
  ``version``; ``updated_at`` is refreshed and ``version`` incremented on *any*
  mutation, including a state transition caused by the logical clock or by a
  cascade from another resource.
* PRD 2.7 -- the system never consults wall-clock time.  Server-stamped
  timestamps are therefore read from the logical clock, which is what makes the
  ninety-day qualification windows, the offer exercise windows and the interest
  accrual reproducible.
"""

from store import db
from timeutil import format_iso


def current_time():
    """The current logical-clock instant."""
    return db.logical_clock


def stamp_new(record):
    """Initialise the common fields of a freshly created entity."""
    now = format_iso(current_time())
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_sequence()
    return record


def touch(record):
    """Record a mutation: refresh ``updated_at`` and increment ``version``."""
    record["version"] = int(record.get("version", 1)) + 1
    record["updated_at"] = format_iso(current_time())
    return record


def touch_all(*records):
    for record in records:
        if record is not None:
            touch(record)


def public(record):
    """A response-safe copy: internal bookkeeping keys are stripped."""
    if record is None:
        return None
    return {key: value for key, value in record.items() if not key.startswith("_")}


def public_list(records):
    return [public(record) for record in records]


def create(collection, record):
    """Stamp and store a new entity, returning it.

    The server mints every ``id`` as a plain UUID -- there is no type prefix and
    no natural key (PRD 2.5).
    """
    if not record.get("id"):
        record["id"] = db.new_id()
    stamp_new(record)
    db.put(collection, record)
    return record


def record_of(collection, entity_id):
    return db.get(collection, entity_id)


def money(value):
    """Guard that a value is an int and never a float or string (PRD 2.4)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("monetary values must be integers, got %r" % (value,))
    return value