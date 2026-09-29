"""Domain assertions.

The generic envelope validators come from the shared runner package and are
re-exported here so that a test file has a single import site.  Everything
added on top encodes a promise the PRD makes about *this* domain: the
three-fractional-digit timestamp form, the point/cent exactness rules of
section 2.6, the seat-inventory identity of section 2.9, and the four-key
ranking order of section 3.5.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import (  # noqa: F401  (re-exported)
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .constants import (
    LIMIT_DEFAULT,
    OFFSET_MIN,
    POINTS_PLACES,
    RATIO_PLACES,
    round_half_up,
)

# ─── Timestamps ───────────────────────────────────────────────────────────


def assert_three_fractional_digits(value, label="timestamp"):
    """PRD 2.4: ISO 8601 UTC with exactly three fractional-second digits."""
    assert isinstance(value, str), "{0} must be a string, got {1!r}".format(
        label, value
    )
    assert value.endswith("Z"), "{0} must be UTC and end in Z: {1!r}".format(
        label, value
    )
    assert "." in value, "{0} must carry fractional seconds: {1!r}".format(
        label, value
    )
    fraction = value[value.index(".") + 1 : -1]
    assert len(fraction) == 3, (
        "{0} must carry exactly three fractional digits, got {1!r}".format(
            label, value
        )
    )
    assert fraction.isdigit(), "{0} fractional part must be digits: {1!r}".format(
        label, value
    )


def assert_instant(actual, expected, label="instant"):
    """Compare two ISO 8601 instants on value, not on spelling."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        "{0}: expected {1!r}, got {2!r}".format(label, expected, actual)
    )


# ─── Points, cents and ratios ─────────────────────────────────────────────


def as_decimal(value):
    """Coerce a JSON number (or numeric string) to an exact Decimal."""
    return Decimal(str(value))


def assert_points(actual, expected, label="points"):
    """PRD 2.6: points are decimal quantities carried to exactly 2 places."""
    assert actual is not None, "{0} is missing".format(label)
    assert not isinstance(actual, str), (
        "{0} must be a JSON number, not a string: {1!r}".format(label, actual)
    )
    assert not isinstance(actual, bool), "{0} must be numeric: {1!r}".format(
        label, actual
    )
    quantized = as_decimal(actual).quantize(POINTS_PLACES)
    assert quantized == as_decimal(expected).quantize(POINTS_PLACES), (
        "{0}: expected {1}, got {2}".format(label, expected, actual)
    )


def assert_cents(actual, expected, label="cents"):
    """PRD 2.6: every field whose name ends in _cents is an integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "{0} must be an integer number of cents, got {1!r}".format(label, actual)
    )
    assert actual == expected, "{0}: expected {1}, got {2}".format(
        label, expected, actual
    )


def assert_ratio(actual, expected, label="ratio"):
    """PRD 2.6: ratios are rounded half up to 4 decimal places."""
    assert actual is not None, "{0} is missing".format(label)
    quantized = as_decimal(actual).quantize(RATIO_PLACES)
    assert quantized == as_decimal(expected).quantize(RATIO_PLACES), (
        "{0}: expected {1}, got {2}".format(label, expected, actual)
    )


def assert_points_scale(value, label="points"):
    """The rendered value must not carry more than 2 decimal places."""
    text = str(value)
    if "." in text:
        assert len(text.split(".")[1]) <= 2, (
            "{0} carries more than 2 decimal places: {1!r}".format(label, value)
        )


# ─── Common resource properties ───────────────────────────────────────────


def assert_common_fields(resource, label="resource"):
    """PRD 2.4: id, created_at, updated_at and version on a versioned row."""
    assert is_valid_uuid(resource.get("id")), (
        "{0}.id must be a UUID string: {1!r}".format(label, resource.get("id"))
    )
    assert_three_fractional_digits(
        resource.get("created_at"), "{0}.created_at".format(label)
    )
    assert_three_fractional_digits(
        resource.get("updated_at"), "{0}.updated_at".format(label)
    )
    version = resource.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        "{0}.version must be an integer: {1!r}".format(label, version)
    )
    assert version >= 1, "{0}.version starts at 1, got {1}".format(label, version)


def assert_append_only_fields(entry, label="point ledger entry"):
    """PRD 2.4: a point-ledger entry has neither updated_at nor version."""
    assert is_valid_uuid(entry.get("id")), (
        "{0}.id must be a UUID string: {1!r}".format(label, entry.get("id"))
    )
    assert_three_fractional_digits(
        entry.get("created_at"), "{0}.created_at".format(label)
    )
    assert "updated_at" not in entry or entry["updated_at"] is None, (
        "{0} must not carry updated_at: {1!r}".format(label, entry.get("updated_at"))
    )
    assert "version" not in entry or entry["version"] is None, (
        "{0} must not carry version: {1!r}".format(label, entry.get("version"))
    )


def assert_version_unchanged(new_resource, old_version, label="resource"):
    assert new_resource.get("version") == old_version, (
        "{0}.version should still be {1}, got {2}".format(
            label, old_version, new_resource.get("version")
        )
    )


# ─── Collections ──────────────────────────────────────────────────────────


def validate_list(response):
    """Every list endpoint in this service is paginated (PRD 2.3)."""
    return validate_paginated(response)


def assert_page_meta(meta, total_count=None, limit=None, offset=None, has_more=None):
    """PRD 2.3: meta carries limit, offset, total_count and has_more."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, "meta must carry {0!r}, got {1!r}".format(key, meta)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "meta.total_count: expected {0}, got {1}".format(
                total_count, meta["total_count"]
            )
        )
    if limit is not None:
        assert meta["limit"] == limit, "meta.limit: expected {0}, got {1}".format(
            limit, meta["limit"]
        )
    if offset is not None:
        assert meta["offset"] == offset, "meta.offset: expected {0}, got {1}".format(
            offset, meta["offset"]
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            "meta.has_more: expected {0}, got {1}".format(has_more, meta["has_more"])
        )


def assert_default_page_meta(meta, total_count=None):
    """The declared defaults: limit 10, offset 0."""
    assert_page_meta(
        meta, total_count=total_count, limit=LIMIT_DEFAULT, offset=OFFSET_MIN
    )


def assert_ascending(rows, key, label=None):
    """The rows are non-decreasing on key - the default list ordering."""
    label = label or key
    values = [row[key] for row in rows]
    assert values == sorted(values), (
        "rows must be ordered by {0} ascending, got {1!r}".format(label, values)
    )


def assert_ids_in_order(rows, expected_ids, label="rows"):
    assert [row["id"] for row in rows] == list(expected_ids), (
        "{0}: expected id order {1!r}, got {2!r}".format(
            label, list(expected_ids), [row["id"] for row in rows]
        )
    )


def assert_only_ids(rows, expected_ids, label="rows"):
    """Set comparison - the filter selected exactly these rows."""
    assert {row["id"] for row in rows} == set(expected_ids), (
        "{0}: expected ids {1!r}, got {2!r}".format(
            label, sorted(expected_ids), sorted(row["id"] for row in rows)
        )
    )


# ─── Point ledger ─────────────────────────────────────────────────────────


def find_ledger_entries(entries, entry_type=None, variant=None, donor_id=None):
    """Filter a ledger page down to one component of one variant."""
    selected = list(entries)
    if entry_type is not None:
        selected = [e for e in selected if e.get("entry_type") == entry_type]
    if variant is not None:
        selected = [e for e in selected if e.get("variant") == variant]
    if donor_id is not None:
        selected = [e for e in selected if e.get("donor_id") == donor_id]
    return selected


def assert_ledger_component(
    entries, entry_type, variant, expected_points, donor_id=None
):
    """Exactly one row for this component and variant, carrying these points."""
    selected = find_ledger_entries(
        entries, entry_type=entry_type, variant=variant, donor_id=donor_id
    )
    assert len(selected) == 1, (
        "expected exactly one {0}/{1} ledger row, found {2}".format(
            entry_type, variant, len(selected)
        )
    )
    assert_points(
        selected[0].get("points"),
        expected_points,
        "{0}/{1} points".format(entry_type, variant),
    )
    return selected[0]


# ─── Sections and seats ───────────────────────────────────────────────────


def assert_seat_inventory_identity(section, label="section"):
    """PRD 2.9: available + committed + decommissioned == seat_row_count."""
    total = (
        section["seats_available"]
        + section["seats_committed_count"]
        + section["decommissioned_seat_count"]
    )
    assert total == section["seat_row_count"], (
        "{0}: seats_available {1} + seats_committed_count {2} + "
        "decommissioned_seat_count {3} must equal seat_row_count {4}".format(
            label,
            section["seats_available"],
            section["seats_committed_count"],
            section["decommissioned_seat_count"],
            section["seat_row_count"],
        )
    )


def assert_seat_inventory(
    section,
    seats_available=None,
    seats_committed_count=None,
    decommissioned_seat_count=None,
    assigned_seat_count=None,
    underwater_seat_count=None,
    seat_row_count=None,
    label="section",
):
    expectations = {
        "seats_available": seats_available,
        "seats_committed_count": seats_committed_count,
        "decommissioned_seat_count": decommissioned_seat_count,
        "assigned_seat_count": assigned_seat_count,
        "underwater_seat_count": underwater_seat_count,
        "seat_row_count": seat_row_count,
    }
    for key, expected in expectations.items():
        if expected is not None:
            assert section.get(key) == expected, (
                "{0}.{1}: expected {2}, got {3}".format(
                    label, key, expected, section.get(key)
                )
            )
    assert_seat_inventory_identity(section, label=label)


# ─── Donors and ranking ───────────────────────────────────────────────────


def assert_donor_points(
    donor,
    provisional_points=None,
    certified_base_points=None,
    certified_points=None,
    transferred_points_in=None,
    transferred_points_out=None,
    dispute_adjustment_points=None,
    cumulative_giving_cents=None,
    consecutive_giving_years=None,
    rank_position=None,
    label="donor",
):
    point_fields = {
        "provisional_points": provisional_points,
        "certified_base_points": certified_base_points,
        "certified_points": certified_points,
        "transferred_points_in": transferred_points_in,
        "transferred_points_out": transferred_points_out,
        "dispute_adjustment_points": dispute_adjustment_points,
    }
    for key, expected in point_fields.items():
        if expected is not None:
            assert_points(donor.get(key), expected, "{0}.{1}".format(label, key))
    if cumulative_giving_cents is not None:
        assert_cents(
            donor.get("cumulative_giving_cents"),
            cumulative_giving_cents,
            "{0}.cumulative_giving_cents".format(label),
        )
    if consecutive_giving_years is not None:
        assert donor.get("consecutive_giving_years") == consecutive_giving_years, (
            "{0}.consecutive_giving_years: expected {1}, got {2}".format(
                label, consecutive_giving_years, donor.get("consecutive_giving_years")
            )
        )
    if rank_position is not None:
        assert donor.get("rank_position") == rank_position, (
            "{0}.rank_position: expected {1}, got {2}".format(
                label, rank_position, donor.get("rank_position")
            )
        )


def assert_certified_points_identity(donor, label="donor"):
    """PRD 3.3: certified_points = base + in - out + adjustment, floored at 0."""
    derived = (
        as_decimal(donor["certified_base_points"])
        + as_decimal(donor["transferred_points_in"])
        - as_decimal(donor["transferred_points_out"])
        + as_decimal(donor["dispute_adjustment_points"])
    )
    derived = round_half_up(derived)
    if derived < Decimal("0"):
        derived = Decimal("0.00")
    assert_points(
        donor["certified_points"], derived, "{0}.certified_points".format(label)
    )


def assert_ranked_order(donors, label="ranked pool"):
    """PRD 3.5: certified_points DESC, giving DESC, streak DESC, created_at ASC."""
    keys = [
        (
            -as_decimal(donor["certified_points"]),
            -donor["cumulative_giving_cents"],
            -donor["consecutive_giving_years"],
            donor["created_at"],
        )
        for donor in donors
    ]
    assert keys == sorted(keys), "{0} is not in the four-key order".format(label)
    for index, donor in enumerate(donors, start=1):
        assert donor["rank_position"] == index, (
            "{0}: donor at position {1} carries rank_position {2}".format(
                label, index, donor["rank_position"]
            )
        )


# ─── Envelope shape (PRD 2.2) ─────────────────────────────────────────────


def assert_meta_request_stamps(meta, label="meta"):
    """PRD 2.2: every meta carries an api_request_id and a timestamp."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        "{0}.api_request_id: expected a string starting with 'req_', got {1!r}".format(
            label, request_id
        )
    )
    assert_three_fractional_digits(
        meta.get("api_request_timestamp"), "{0}.api_request_timestamp".format(label)
    )


def assert_envelope(response, response_type, label="response"):
    """Check the top-level envelope shape and return the parsed body."""
    body = response.json()
    assert body.get("response_type") == response_type, (
        "{0}.response_type: expected {1!r}, got {2!r}".format(
            label, response_type, body.get("response_type")
        )
    )
    assert_meta_request_stamps(body.get("meta") or {}, "{0}.meta".format(label))
    return body


def assert_object_envelope(response, label="response"):
    return assert_envelope(response, "object", label)


def assert_array_envelope(response, label="response"):
    return assert_envelope(response, "array", label)


def assert_error_envelope(response, label="response"):
    body = assert_envelope(response, "error", label)
    assert "error_id" in (body.get("data") or {}), (
        "{0}.data.error_id is missing".format(label)
    )
    return body
