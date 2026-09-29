"""Domain assertions for the trash valet API.

Everything here is derived from the PRD's own field-shape rules: instants
render with exactly three fractional digits (PRD 2.4), money is an integer
count of cents (PRD 2.6), ratios are integer basis points, and every persisted
resource carries `id`, `created_at`, `updated_at` and `version`.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_valid_uuid

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer, halves going up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to two decimal places, halves going up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Shape assertions
# --------------------------------------------------------------------------
def canonical_instant(value):
    """Normalise an instant so sub-second precision differences do not matter.

    Returns a string with exactly three fractional digits and a trailing Z, so
    two renderings of the same moment compare equal regardless of how many
    fractional digits the responses carried.
    """
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"instant must be UTC with a trailing Z: {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant(value, field="timestamp"):
    """Assert an instant renders with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value), (
        f"{field} must render as YYYY-MM-DDTHH:MM:SS.mmmZ, got {value!r}"
    )


def assert_instants_equal(actual, expected, field="timestamp"):
    """Compare two instants after normalising fractional-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {expected!r}, got {actual!r}"
    )


def assert_date(value, field="date"):
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"{field} must render as YYYY-MM-DD, got {value!r}"
    )


def assert_billing_period(value, field="billing_period"):
    assert isinstance(value, str) and _PERIOD_RE.match(value), (
        f"{field} must render as YYYY-MM, got {value!r}"
    )


def assert_money_cents(value, field="amount_cents"):
    """Money is an integer number of cents, never a float or a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r}"
    )


def assert_bps(value, field="bps"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer basis-point value, got {value!r}"
    )
    assert value >= 0, f"{field} must not be negative, got {value!r}"


def assert_common_fields(entity, name="entity"):
    """Every persisted resource exposes id, created_at, updated_at, version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{name} is missing {field}"
    assert is_valid_uuid(entity["id"]), (
        f"{name}.id must be a plain UUID, got {entity['id']!r}"
    )
    assert_instant(entity["created_at"], f"{name}.created_at")
    assert_instant(entity["updated_at"], f"{name}.updated_at")
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{name}.version must be a positive integer, got {entity['version']!r}"
    )


def assert_version_bumped(before, after, by=1, name="entity"):
    """Assert a write advanced the optimistic-concurrency counter."""
    assert after["version"] == before["version"] + by, (
        f"{name}.version expected {before['version'] + by}, got {after['version']}"
    )


def assert_version_unchanged(before, after, name="entity"):
    assert after["version"] == before["version"], (
        f"{name}.version should not have moved from {before['version']}, "
        f"got {after['version']}"
    )


def assert_fields(entity, expected, name="entity"):
    """Assert every key/value pair in `expected` matches `entity`."""
    for key, value in expected.items():
        assert key in entity, f"{name} is missing {key}"
        assert entity[key] == value, (
            f"{name}.{key}: expected {value!r}, got {entity[key]!r}"
        )


# --------------------------------------------------------------------------
# Entity-specific assertions
# --------------------------------------------------------------------------
def assert_night_dimensions(night, verification_status, billing_status):
    """A night's verification and billing dimensions are asserted together."""
    assert night["verification_status"] == verification_status, (
        f"verification_status: expected {verification_status}, "
        f"got {night['verification_status']}"
    )
    assert night["billing_status"] == billing_status, (
        f"billing_status: expected {billing_status}, got {night['billing_status']}"
    )


def assert_night_coverage(night, expected_doors, scanned_doors, coverage_bps):
    assert night["expected_door_count"] == expected_doors, (
        f"expected_door_count: expected {expected_doors}, "
        f"got {night['expected_door_count']}"
    )
    assert night["scanned_door_count"] == scanned_doors, (
        f"scanned_door_count: expected {scanned_doors}, "
        f"got {night['scanned_door_count']}"
    )
    assert night["coverage_bps"] == coverage_bps, (
        f"coverage_bps: expected {coverage_bps}, got {night['coverage_bps']}"
    )


def assert_resident_ledger(resident, outstanding_cents, assessed_this_period_cents=None,
                           collections_status=None):
    assert_money_cents(resident["fines_outstanding_cents"], "fines_outstanding_cents")
    assert resident["fines_outstanding_cents"] == outstanding_cents, (
        f"fines_outstanding_cents: expected {outstanding_cents}, "
        f"got {resident['fines_outstanding_cents']}"
    )
    if assessed_this_period_cents is not None:
        assert resident["fines_assessed_this_period_cents"] == assessed_this_period_cents, (
            f"fines_assessed_this_period_cents: expected "
            f"{assessed_this_period_cents}, "
            f"got {resident['fines_assessed_this_period_cents']}"
        )
    if collections_status is not None:
        assert resident["collections_status"] == collections_status, (
            f"collections_status: expected {collections_status}, "
            f"got {resident['collections_status']}"
        )


def assert_property_rollups(prop, pending_fine_revenue_cents=None,
                            delinquent_resident_count=None, escalation_level=None,
                            status=None):
    if pending_fine_revenue_cents is not None:
        assert_money_cents(
            prop["pending_fine_revenue_cents"], "pending_fine_revenue_cents"
        )
        assert prop["pending_fine_revenue_cents"] == pending_fine_revenue_cents, (
            f"pending_fine_revenue_cents: expected {pending_fine_revenue_cents}, "
            f"got {prop['pending_fine_revenue_cents']}"
        )
    if delinquent_resident_count is not None:
        assert prop["delinquent_resident_count"] == delinquent_resident_count, (
            f"delinquent_resident_count: expected {delinquent_resident_count}, "
            f"got {prop['delinquent_resident_count']}"
        )
    if escalation_level is not None:
        assert prop["escalation_level"] == escalation_level, (
            f"escalation_level: expected {escalation_level}, "
            f"got {prop['escalation_level']}"
        )
    if status is not None:
        assert prop["status"] == status, (
            f"property status: expected {status}, got {prop['status']}"
        )


def assert_fine_amounts(fine, base_cents, escalation_multiplier, amount_cents,
                        uncapped_amount_cents, seasonal_uplift_applied=None):
    assert_money_cents(fine["base_cents"], "base_cents")
    assert_money_cents(fine["amount_cents"], "amount_cents")
    assert_money_cents(fine["uncapped_amount_cents"], "uncapped_amount_cents")
    assert fine["base_cents"] == base_cents, (
        f"base_cents: expected {base_cents}, got {fine['base_cents']}"
    )
    assert float(fine["escalation_multiplier"]) == float(escalation_multiplier), (
        f"escalation_multiplier: expected {escalation_multiplier}, "
        f"got {fine['escalation_multiplier']}"
    )
    assert fine["amount_cents"] == amount_cents, (
        f"amount_cents: expected {amount_cents}, got {fine['amount_cents']}"
    )
    assert fine["uncapped_amount_cents"] == uncapped_amount_cents, (
        f"uncapped_amount_cents: expected {uncapped_amount_cents}, "
        f"got {fine['uncapped_amount_cents']}"
    )
    if seasonal_uplift_applied is not None:
        assert fine["seasonal_uplift_applied"] is seasonal_uplift_applied, (
            f"seasonal_uplift_applied: expected {seasonal_uplift_applied}, "
            f"got {fine['seasonal_uplift_applied']!r}"
        )


def assert_statement_waterfall(statement, gross_cents, sla_credit_rate_bps,
                               credit_cents, share_cents, net_cents,
                               missed_service_bps=None, scheduled_night_count=None,
                               missed_equivalent_nights=None):
    """Assert the four settlement steps and the ratios that key them."""
    for field in (
        "gross_passthrough_cents",
        "missed_service_credit_cents",
        "property_revenue_share_cents",
        "net_due_from_property_cents",
    ):
        assert_money_cents(statement[field], field)
    assert statement["gross_passthrough_cents"] == gross_cents, (
        f"gross_passthrough_cents: expected {gross_cents}, "
        f"got {statement['gross_passthrough_cents']}"
    )
    assert statement["sla_credit_rate_bps"] == sla_credit_rate_bps, (
        f"sla_credit_rate_bps: expected {sla_credit_rate_bps}, "
        f"got {statement['sla_credit_rate_bps']}"
    )
    assert statement["missed_service_credit_cents"] == credit_cents, (
        f"missed_service_credit_cents: expected {credit_cents}, "
        f"got {statement['missed_service_credit_cents']}"
    )
    assert statement["property_revenue_share_cents"] == share_cents, (
        f"property_revenue_share_cents: expected {share_cents}, "
        f"got {statement['property_revenue_share_cents']}"
    )
    assert statement["net_due_from_property_cents"] == net_cents, (
        f"net_due_from_property_cents: expected {net_cents}, "
        f"got {statement['net_due_from_property_cents']}"
    )
    assert (
        statement["net_due_from_property_cents"]
        == statement["gross_passthrough_cents"]
        - statement["missed_service_credit_cents"]
        - statement["property_revenue_share_cents"]
    ), "net must be gross minus credit minus revenue share, exactly"
    if missed_service_bps is not None:
        assert statement["missed_service_bps"] == missed_service_bps, (
            f"missed_service_bps: expected {missed_service_bps}, "
            f"got {statement['missed_service_bps']}"
        )
    if scheduled_night_count is not None:
        assert statement["scheduled_night_count"] == scheduled_night_count, (
            f"scheduled_night_count: expected {scheduled_night_count}, "
            f"got {statement['scheduled_night_count']}"
        )
    if missed_equivalent_nights is not None:
        assert float(statement["missed_equivalent_nights"]) == float(
            missed_equivalent_nights
        ), (
            f"missed_equivalent_nights: expected {missed_equivalent_nights}, "
            f"got {statement['missed_equivalent_nights']}"
        )


def find_by_id(items, entity_id):
    """Return the item in a listing whose id matches, or None."""
    for item in items:
        if item.get("id") == entity_id:
            return item
    return None


def ids_of(items):
    return [item.get("id") for item in items]
