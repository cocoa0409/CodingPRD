"""Route handlers: price comparisons and the substantiation registry."""

from clock import now, parse_iso
from errors import fail, success_payload
from lifecycle import derive as derive_comparison, mark_ever_substantiated
from registry import find, get, of_parent, ordered_by_created, resolve_comparison_of_order
from resources import blank_record, internal_of, touch
from store import store

SOURCE_KINDS = ("RETAIL_SURVEY", "BENEFIT_INDEX", "MANUFACTURER_NOTICE")
ENABLEABLE_STATES = ("FRESH", "REFRESH_REQUIRED", "STALE")
REFRESHABLE_STATES = ("REFRESH_REQUIRED", "STALE", "BLOCKED")


def _object(record):
    return success_payload(record, "object")


def _array(ctx, records):
    return success_payload(records, "array", ctx.pagination(len(records)))


def _comparison_of(order):
    for comparison in store.comparisons.values():
        if comparison.get("order_id") == order.get("id"):
            return comparison
    return None


def _int_or_none(value):
    from resources import _as_int

    if isinstance(value, bool):
        return None
    return _as_int(value)


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

def list_order_comparisons(ctx, order_id):
    order = find("orders", order_id)
    prescription = get("prescriptions", order.get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    records = ordered_by_created(of_parent("comparisons", "order_id", order_id))
    clock = now()
    for comparison in records:
        # PRD §3.9: the lifecycle rule governs the comparison's state; the
        # "logical clock evaluation" transitions are re-derived on read.
        comparison["typical_retail_price_cents"] = order.get("retail_reference_price_cents")
        comparison["benefit_covered_price_cents"] = order.get("insured_reference_price_cents")
        derive_comparison(comparison, order, clock=clock)
    return _array(ctx, records), 200


def list_comparisons(ctx):
    records = list(store.comparisons.values())
    order_id = ctx.query("order_id")
    if order_id:
        records = [rec for rec in records if rec.get("order_id") == order_id]
    clock = now()
    for comparison in records:
        order = get("orders", comparison.get("order_id"))
        if order is None:
            continue
        comparison["typical_retail_price_cents"] = order.get("retail_reference_price_cents")
        comparison["benefit_covered_price_cents"] = order.get("insured_reference_price_cents")
        derive_comparison(comparison, order, clock=clock)
    return _array(ctx, ordered_by_created(records)), 200


def comparison_message(ctx, order_id):
    order = find("orders", order_id)
    prescription = get("prescriptions", order.get("prescription_id"))
    ctx.guard_ownership((prescription or {}).get("patient_id"))
    comparison = _comparison_of(order)
    if comparison is None:
        fail("ERR_RESOURCE_NOT_FOUND", "The order carries no comparison record.")
    clock = now()
    comparison["typical_retail_price_cents"] = order.get("retail_reference_price_cents")
    comparison["benefit_covered_price_cents"] = order.get("insured_reference_price_cents")
    derive_comparison(comparison, order, clock=clock)
    if comparison.get("state") == "BLOCKED" or comparison.get("substantiated") is not True:
        fail("ERR_COMPARISON_UNSUBSTANTIATED")

    patient_price = int(order.get("patient_price_cents") or 0)
    retail = int(order.get("retail_reference_price_cents") or 0)
    benefit = int(order.get("insured_reference_price_cents") or 0)
    return _object(
        {
            "order_id": order.get("id"),
            "comparison_id": comparison.get("id"),
            "order_status": order.get("status"),
            "patient_price_cents": order.get("patient_price_cents"),
            "typical_retail_price_cents": order.get("retail_reference_price_cents"),
            "benefit_covered_price_cents": order.get("insured_reference_price_cents"),
            "retail_delta_cents": retail - patient_price,
            "benefit_delta_cents": benefit - patient_price,
            "state": comparison.get("state"),
            "status": comparison.get("status"),
            "substantiated": comparison.get("substantiated"),
            "substantiation_digest": comparison.get("substantiation_digest"),
        }
    ), 200


def refresh_comparison(ctx, order_id, comparison_id):
    order, comparison = resolve_comparison_of_order(order_id, comparison_id)
    state = comparison.get("state")
    if state not in REFRESHABLE_STATES:
        fail("ERR_INVALID_STATE", "A comparison at %s admits no refresh." % state)
    clock = now()
    # A refresh is the operator action that re-derives a comparison's figures
    # and digest; re-running it on an already-live comparison is an idempotent
    # re-derivation rather than a state violation.
    if not _live_substantiation(order.get("id"), clock):
        fail("ERR_INVALID_STATE", "No ENABLED unexpired substantiation exists for this order.")

    comparison["typical_retail_price_cents"] = order.get("retail_reference_price_cents")
    comparison["benefit_covered_price_cents"] = order.get("insured_reference_price_cents")
    comparison["substantiated"] = True
    comparison["status"] = "SUBSTANTIATED"
    mark_ever_substantiated(comparison)
    derive_comparison(comparison, order, clock=clock, force=True)
    touch(comparison)
    return _object(comparison), 200


def _live_substantiation(order_id, clock):
    for record in of_parent("substantiations", "order_id", order_id):
        if record.get("status") != "ENABLED":
            continue
        valid_until = parse_iso(record.get("valid_until"))
        if valid_until is not None and valid_until > clock:
            return True
    return False


def list_order_substantiations(ctx, order_id):
    find("orders", order_id)
    records = ordered_by_created(of_parent("substantiations", "order_id", order_id))
    return _array(ctx, records), 200


# ---------------------------------------------------------------------------
# Substantiation registry
# ---------------------------------------------------------------------------

def create_substantiation(ctx):
    record = blank_record()
    order_id = ctx.text("order_id")
    find("orders", order_id)
    record["order_id"] = order_id
    source_kind = ctx.text("source_kind")
    if source_kind not in SOURCE_KINDS:
        fail("ERR_INVALID_STATE", "source_kind must be RETAIL_SURVEY, BENEFIT_INDEX or MANUFACTURER_NOTICE.")
    record["source_kind"] = source_kind
    record["source_reference"] = ctx.text("source_reference")
    observed_at = parse_iso(ctx.text("observed_at"))
    valid_until = parse_iso(ctx.text("valid_until"))
    if observed_at is None or valid_until is None:
        fail("ERR_INVALID_AMOUNT", "observed_at and valid_until must be ISO 8601 instants.")
    record["observed_at"] = ctx.text("observed_at")
    record["valid_until"] = ctx.text("valid_until")
    record["status"] = "PENDING"
    store.substantiations[record["id"]] = internal_of("substantiations", record)
    return _object(record), 201


def get_substantiation(ctx, substantiation_id):
    return _object(find("substantiations", substantiation_id)), 200


def list_substantiations(ctx):
    records = list(store.substantiations.values())
    order_id = ctx.query("order_id")
    if order_id:
        records = [rec for rec in records if rec.get("order_id") == order_id]
    return _array(ctx, ordered_by_created(records)), 200


def enable_substantiation(ctx, order_id):
    order = find("orders", order_id)
    substantiation_id = ctx.text("substantiation_id")
    record = find("substantiations", substantiation_id)

    # OCC follows existence and precedes state validation (PRD §2.12). The token
    # is mandatory on this endpoint (PRD §2.9, "Neither token is optional on its
    # endpoint"), so an omitted field is refused as stale rather than admitted.
    expected_version = ctx.key("expected_order_version")
    if expected_version is None or _int_or_none(expected_version) != int(order.get("version") or 1):
        fail("ERR_STALE_VERSION")

    if record.get("order_id") != order.get("id"):
        fail("ERR_SUBSTANTIATION_ORDER_MISMATCH")
    if record.get("status") != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING substantiation may be enabled.")

    comparison = _comparison_of(order)
    if comparison is None:
        fail("ERR_RESOURCE_NOT_FOUND", "The order carries no comparison record.")
    if comparison.get("state") not in ENABLEABLE_STATES:
        fail("ERR_INVALID_STATE", "The order's comparison does not admit enablement.")

    clock = now()
    valid_until = parse_iso(record.get("valid_until"))
    if valid_until is None or valid_until <= clock:
        fail("ERR_SUBSTANTIATION_EXPIRED")
    observed_at = parse_iso(record.get("observed_at"))
    if observed_at is None or observed_at > clock:
        fail("ERR_INVALID_STATE", "The substantiation has not yet been observed.")

    record["status"] = "ENABLED"
    touch(record)
    comparison["substantiated"] = True
    comparison["status"] = "SUBSTANTIATED"
    mark_ever_substantiated(comparison)
    derive_comparison(comparison, order, clock=clock, force=True)
    touch(comparison)
    touch(order)
    return _object(record), 200


def disable_substantiation(ctx, order_id):
    order = find("orders", order_id)
    substantiation_id = ctx.text("substantiation_id")
    record = find("substantiations", substantiation_id)
    if record.get("order_id") != order.get("id"):
        fail("ERR_SUBSTANTIATION_ORDER_MISMATCH")
    if record.get("status") != "ENABLED":
        fail("ERR_INVALID_STATE", "Only an ENABLED substantiation may be disabled.")

    record["status"] = "DISABLED"
    touch(record)
    comparison = _comparison_of(order)
    if comparison is not None:
        comparison["typical_retail_price_cents"] = order.get("retail_reference_price_cents")
        comparison["benefit_covered_price_cents"] = order.get("insured_reference_price_cents")
        derive_comparison(comparison, order, clock=now(), force=True)
        touch(comparison)
    return _object(record), 200