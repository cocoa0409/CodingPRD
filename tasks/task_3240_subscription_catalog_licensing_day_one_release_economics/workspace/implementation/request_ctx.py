"""Auth, per-endpoint request context and the ordered validation dispatcher.

Ordered rejection precedence (PRD section 2.11):
  1  auth  -> ERR_MISSING_AUTH_HEADER (401)
  2  auth  -> ERR_FORBIDDEN_ROLE (403)
  3  shape -> ERR_INVALID_REQUEST (400)
  4  existence (404)
  5  state (409)
  6  temporal window (409)
  7  referential / eligibility (409)
  8  quota and cap (409)
  99 optimistic concurrency -> ERR_STALE_VERSION (412)
"""
from decimal import Decimal
from flask import request

from clock import tried_instant
from errors import ApiError, HTTP_BY_ERROR, fail

ROLES = ("CatalogAdmin", "CatalogAnalyst", "Subscriber", "Anonymous")
S = "string"
I = "int"
N = "number"
B = "boolean"
D = "datetime"
E = "enum"
A = "array"

_UNSET = object()
RAISE = object()


class Ctx(object):
    def __init__(self, full, required=(), optional=(), enums=None, arrays=None,
                 numbers=None, role=None, roles=(), owner=None, path_ids=(),
                 strict=True):
        self.full = full
        self.specs = []
        for name in required:
            self.specs.append((name, True))
        for name in optional:
            self.specs.append((name, False))
        self.enums = enums or {}
        self.arrays = arrays or {}
        self.numbers = numbers or {}
        self.role = role
        self.roles = roles
        self.owner = owner
        self.path_ids = path_ids
        self.strict = strict
        self.data = {}
        self.raw = {}
        self.extra = {}
        self.actor_id = None
        self.actor_role = None
        self.hooks = {}
        self.checked = {}
        self.declaring = False

    # ---- field access -----------------------------------------------------
    def has(self, name):
        return name in self.raw

    def get(self, name, default=None):
        if name in self.data:
            return self.data[name]
        if name in self.raw:
            return self.raw[name]
        return default

    def int_of(self, name, default=0):
        value = self.get(name, _UNSET)
        if value is _UNSET or value is None:
            return default
        if isinstance(value, bool):
            return default
        if isinstance(value, float) and value == int(value):
            return int(value)
        if isinstance(value, int):
            return value
        return default


def reject_invalid(message):
    fail("ERR_INVALID_REQUEST", message)


def require_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or uid is None or role.strip() == "" or uid.strip() == "":
        fail("ERR_MISSING_AUTH_HEADER",
             "X-User-ID and X-User-Role must both be supplied.")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_MISSING_AUTH_HEADER",
             "X-User-Role must be one of %s." % ", ".join(ROLES))
    return uid.strip(), role


def ctx(roles, owner=None, full=True, strict=True, path_ids=()):
    """Header + role layer (steps 1-2), then build the parameter descriptor."""
    c = Ctx(full, role=None, roles=tuple(roles), owner=owner, path_ids=path_ids,
            strict=strict)
    c.actor_id, c.actor_role = require_auth()
    if c.actor_role not in c.roles:
        fail("ERR_FORBIDDEN_ROLE",
             "Role %s is not permitted on this operation." % c.actor_role)
    return c


# ---------------------------------------------------------------------------
# step 3 helpers called from each endpoint descriptor
# ---------------------------------------------------------------------------
def _declare(c, name, required):
    """Record a field on the endpoint's declared input list."""
    if c.declaring:
        c.specs.append((name, required))
        return True
    return False


def expect_body(c):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        reject_invalid("Request body must be a JSON object.")
    c.raw = dict(body)


def check_presence(c):
    """Priority-3a: every declared required input must be present."""
    for name, required in c.specs:
        if not required:
            continue
        if name not in c.raw or c.raw[name] is None:
            reject_invalid("Field %s is required." % name)
        if isinstance(c.raw[name], str) and c.raw[name] == "":
            reject_invalid("Field %s must not be empty." % name)


def check_undeclared(c):
    """Priority-3b: no undeclared field may be supplied."""
    if not c.strict:
        return
    declared = set(name for name, _required in c.specs)
    for key in c.raw:
        if key not in declared:
            reject_invalid("Field %s is not declared on this operation." % key)


def expect_query(c, allowed):
    for key in request.args:
        if key not in allowed:
            reject_invalid("Query parameter %s is not declared." % key)


def want_int(c, name, lo=None, hi=None, required=False):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if isinstance(value, bool) or not isinstance(value, int):
        reject_invalid("Field %s must be an integer." % name)
    if lo is not None and value < lo:
        reject_invalid("Field %s must be at least %s." % (name, lo))
    if hi is not None and value > hi:
        reject_invalid("Field %s must be at most %s." % (name, hi))
    c.data[name] = value
    return True


def want_num(c, name, lo=None, hi=None, required=False):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject_invalid("Field %s must be numeric." % name)
    dec = Decimal(str(value))
    if lo is not None and dec < Decimal(str(lo)):
        reject_invalid("Field %s must be at least %s." % (name, lo))
    if hi is not None and dec > Decimal(str(hi)):
        reject_invalid("Field %s must be at most %s." % (name, hi))
    c.data[name] = value
    return True


def want_bool(c, name, required=False):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if not isinstance(value, bool):
        reject_invalid("Field %s must be a boolean." % name)
    c.data[name] = value
    return True


def want_str(c, name, allowed=None, required=False, sample=None):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if not isinstance(value, str) or value == "":
        reject_invalid("Field %s must be a non-empty string." % name)
    if allowed is not None and value not in allowed:
        reject_invalid("Field %s must be one of %s." % (name, ", ".join(allowed)))
    c.data[name] = value
    if sample is not None:
        c.enums[name] = sample
    return True


def want_instant(c, name, required=False):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if not isinstance(value, str):
        reject_invalid("Field %s must be an ISO 8601 UTC instant." % name)
    parsed = tried_instant(value)
    if parsed is None:
        reject_invalid("Field %s must be an ISO 8601 UTC instant." % name)
    c.data[name] = parsed
    return True


def want_tier_list(c, name, required=False, allow_empty=False):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if not isinstance(value, list):
        reject_invalid("Field %s must be an array." % name)
    if not value and not allow_empty:
        reject_invalid("Field %s must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in ("ESSENTIAL", "PREMIUM", "ULTIMATE"):
            reject_invalid("Field %s names an unknown tier." % name)
    if len(set(value)) != len(value):
        reject_invalid("Field %s must not repeat a tier." % name)
    c.data[name] = list(value)
    return True


def want_platform_set(c, name, required=False):
    if _declare(c, name, required):
        return name in c.raw
    if not c.has(name):
        if required:
            reject_invalid("Field %s is required." % name)
        return False
    value = c.raw[name]
    if not isinstance(value, list) or not value:
        reject_invalid("Field %s must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in ("CONSOLE", "PC", "CLOUD"):
            reject_invalid("Field %s names an unknown platform." % name)
    if len(set(value)) != len(value):
        reject_invalid("Field %s must not repeat a platform." % name)
    c.data[name] = list(value)
    return True


def want_windows(c, name):
    if _declare(c, name, False):
        return name in c.raw
    if not c.has(name):
        return False
    value = c.raw[name]
    if not isinstance(value, list):
        reject_invalid("Field %s must be an array." % name)
    prepared = []
    for item in value:
        if not isinstance(item, dict):
            reject_invalid("Every maintenance window must be an object.")
        # PRD 3.1: a region is created "with a `maintenance_windows` list ... one
        # `CatalogMaintenance` row is instantiated per submitted window". The
        # window's `region_code` is the enclosing region's, so the submitted
        # shape carries only the start, end and reduction (PRD 2.7).
        for key in ("maintenance_start", "maintenance_end",
                    "capacity_reduction_pct"):
            if key not in item or item[key] is None:
                reject_invalid("Every maintenance window needs %s." % key)
        for key in item:
            if key not in ("region_code", "maintenance_start", "maintenance_end",
                           "capacity_reduction_pct", "allow_overlap"):
                reject_invalid("Field %s is not declared on a maintenance window." % key)
        start = item["maintenance_start"]
        end = item["maintenance_end"]
        if not isinstance(start, str) or tried_instant(start) is None:
            reject_invalid("maintenance_start must be an ISO 8601 UTC instant.")
        if not isinstance(end, str) or tried_instant(end) is None:
            reject_invalid("maintenance_end must be an ISO 8601 UTC instant.")
        pct = item["capacity_reduction_pct"]
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            reject_invalid("capacity_reduction_pct must be numeric.")
        dec = Decimal(str(pct))
        if dec < 0 or dec > 1:
            reject_invalid("capacity_reduction_pct must lie between 0 and 1.")
        if "allow_overlap" in item and not isinstance(item["allow_overlap"], bool):
            reject_invalid("allow_overlap must be a boolean.")
        prepared.append({
            # The enclosing region supplies this; a submitted window never does.
            "region_code": item.get("region_code"),
            "maintenance_start": tried_instant(start),
            "maintenance_end": tried_instant(end),
            "capacity_reduction_pct": pct,
            "allow_overlap": bool(item.get("allow_overlap", False)),
        })
    c.data[name] = prepared
    return True


def run(c, shape, on_resolve=None, on_state=None, on_temporal=None,
        on_eligibility=None, on_fiscal=None):
    """Run the ordered check layers. Raises ApiError on the first failure.

    Layer 3 runs in three passes so PRD 2.11's ordering holds inside the layer:
    a declaration pass (which records the endpoint's declared input list), the
    presence and undeclared-field passes, then the enum and range pass. Layers
    4-8 are the callbacks supplied by each endpoint, so precedence is enforced
    in one place instead of being re-derived per route.
    """
    expect_body(c)
    c.declaring = True
    shape(c)
    c.declaring = False
    check_presence(c)
    check_undeclared(c)
    shape(c)
    for name, _r in c.specs:
        if name not in c.raw:
            c.raw[name] = None
        if name not in c.data:
            c.data[name] = c.raw[name]
    chain = (on_resolve, on_state, on_temporal, on_eligibility, on_fiscal)
    for hook in chain:
        if hook is not None:
            hook(c)
    return c


def guard(rule, error_id, message):
    """Wrap a boolean rule as a layer check."""
    def step(c):
        if not rule(c):
            fail(error_id, message)
    return step
