"""Field-shape validation helpers (PRD §2.7 blanket ERR_INVALID_REQUEST rules).

All of these raise ERR_INVALID_REQUEST (400): missing required field, type
mismatch, enum member outside the declared set, empty species_classes,
quantity_lbs <= 0, grounds < 10 chars, abatement_evidence < 20 chars, and
malformed timestamps. Interval *semantics* (end > start, inside window) live
at pipeline tier 7 and are checked in the route handlers, not here.
"""
from errors import raise_err, ERR_INVALID_REQUEST
from store import _parse_iso

SPECIES_ENUM = ("CATTLE", "SWINE", "POULTRY", "SHEEP")
REGULATION_FAMILIES = ("SANITATION", "HACCP", "HUMANE", "LABELING", "OTHER")
ACTION_TYPES = ("NOTICE_OF_INTENDED_ENFORCEMENT", "WITHHOLD_MARKS", "SUSPENSION", "WITHDRAWAL")
BASES = ("NR_LINKAGE", "EGREGIOUS_HUMANE", "CATEGORY_3_PATHOGEN", "ADMINISTRATIVE")
SEVERITIES = ("EGREGIOUS", "NON_EGREGIOUS")
PATHOGENS = ("SALMONELLA", "CAMPYLOBACTER")
LABEL_CLAIMS = ("GRASS_FED", "NO_ANTIBIOTICS", "ORGANIC", "BREED_SPECIFIC")
REASON_CODES = ("PATHOGEN", "MISBRANDING", "FOREIGN_MATTER")
RECALL_CLASSES = ("CLASS_I", "CLASS_II", "CLASS_III")
CHECK_OUTCOMES = ("EFFECTIVE", "INEFFECTIVE")
SHIFT_TYPES = ("SLAUGHTER", "PROCESSING")


def _fail(message):
    raise_err(ERR_INVALID_REQUEST, message)


def require_present(body, field):
    if field not in body or body[field] is None:
        _fail("missing required field: %s" % field)
    return body[field]


def require_string(body, field, min_len=None):
    val = require_present(body, field)
    if not isinstance(val, str):
        _fail("field %s must be a string" % field)
    if min_len is not None and len(val) < min_len:
        _fail("field %s must be at least %d characters" % (field, min_len))
    return val


def optional_string(body, field):
    val = body.get(field)
    if val is None:
        return None
    if not isinstance(val, str):
        _fail("field %s must be a string" % field)
    return val


def require_bool(body, field):
    val = require_present(body, field)
    if not isinstance(val, bool):
        _fail("field %s must be a boolean" % field)
    return val


def require_int(body, field, minimum=None):
    val = require_present(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        _fail("field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        _fail("field %s must be >= %d" % (field, minimum))
    return val


def require_number(body, field, gt=None):
    val = require_present(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _fail("field %s must be a number" % field)
    if gt is not None and not (val > gt):
        _fail("field %s must be greater than %s" % (field, gt))
    return val


def require_enum(body, field, members):
    val = require_present(body, field)
    if not isinstance(val, str) or val not in members:
        _fail("field %s must be one of %s" % (field, ", ".join(members)))
    return val


def require_string_array(body, field, members=None, non_empty=False):
    val = require_present(body, field)
    if not isinstance(val, list):
        _fail("field %s must be an array" % field)
    if non_empty and len(val) == 0:
        _fail("field %s must not be empty" % field)
    for item in val:
        if not isinstance(item, str):
            _fail("field %s must contain only strings" % field)
        if members is not None and item not in members:
            _fail("field %s contains a value outside %s" % (field, ", ".join(members)))
    return val


def require_timestamp(body, field):
    """Parse a client timestamp. Unparseable input is a field-shape failure."""
    val = require_present(body, field)
    if not isinstance(val, str):
        _fail("field %s must be an ISO 8601 timestamp string" % field)
    try:
        return _parse_iso(val)
    except (ValueError, TypeError):
        _fail("field %s is not a valid ISO 8601 timestamp" % field)


def not_future(dt, field):
    """Pipeline tier 7: observation timestamps must not pass the logical clock."""
    from errors import raise_err as _raise, ERR_FUTURE_OBSERVATION
    from store import clock_now

    if dt > clock_now():
        _raise(ERR_FUTURE_OBSERVATION, "%s is after the logical clock" % field)
