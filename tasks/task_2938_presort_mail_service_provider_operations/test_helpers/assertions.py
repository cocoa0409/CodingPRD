"""Domain assertions for the presort bureau API.

Three groups live here:

* shape assertions — identity fields, instant format, list envelopes;
* money and percentage assertions — whole-cent integers, mills integers, and
  two- or four-decimal percentages compared with a tolerance smaller than the
  last specified digit;
* resource-state assertions — a compact way to say "this batch is priced like
  this" or "this permit account's funds add up".

The instant checker here is stricter than a generic ISO 8601 test on purpose:
the contract fixes the serialisation at exactly three fractional digits and a
trailing ``Z``, so a value with six digits or a ``+00:00`` offset is a contract
violation, not a formatting preference. The client canonicalises what it can,
and this checker is what tests use when the exact shape is the thing under test.
"""

import re
from typing import Dict, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_valid_uuid, validate_success

from test_helpers.constants import (
    APPEND_ONLY_COMMON_FIELDS,
    FULL_COMMON_FIELDS,
)

STRICT_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


# ─── Shape assertions ─────────────────────────────────────────────────────


def assert_strict_instant(value, field_name: str = "timestamp") -> None:
    """The value is an ISO 8601 UTC instant with exactly three fractional
    digits and a trailing ``Z``."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert STRICT_INSTANT_RE.match(value), (
        f"{field_name} must be an ISO 8601 UTC instant with exactly three "
        f"fractional digits and a trailing Z, got {value!r}"
    )


def assert_full_identity(resource: Dict, expected_version: Optional[int] = None) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    for field in FULL_COMMON_FIELDS:
        assert field in resource, f"missing identity field {field}: {resource}"
    assert is_valid_uuid(resource["id"]), f"id must be a uuid, got {resource['id']!r}"
    assert_strict_instant(resource["created_at"], "created_at")
    assert_strict_instant(resource["updated_at"], "updated_at")
    assert isinstance(resource["version"], int) and not isinstance(
        resource["version"], bool
    ), f"version must be an integer, got {resource['version']!r}"
    assert resource["version"] >= 1, f"version starts at 1, got {resource['version']}"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_append_only_identity(resource: Dict) -> None:
    """An append-only history record carries only id and created_at."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in resource, f"missing identity field {field}: {resource}"
    assert is_valid_uuid(resource["id"]), f"id must be a uuid, got {resource['id']!r}"
    assert_strict_instant(resource["created_at"], "created_at")
    assert "updated_at" not in resource, (
        f"an append-only record must not carry updated_at: {resource}"
    )
    assert "version" not in resource, (
        f"an append-only record must not carry version: {resource}"
    )


def assert_created_before_or_equal(earlier: Dict, later: Dict) -> None:
    """Creation order is observable through created_at."""
    assert earlier["created_at"] <= later["created_at"], (
        f"expected {earlier['id']} to be created no later than {later['id']}"
    )


def assert_fields(resource: Dict, field_names: Iterable[str]) -> None:
    """Every named field is present on the resource."""
    missing = [name for name in field_names if name not in resource]
    assert not missing, f"missing fields {missing} on {resource}"


def assert_field_values(resource: Dict, expected: Dict) -> None:
    """Every named field holds exactly the expected value."""
    actual = {key: resource.get(key) for key in expected}
    assert actual == expected, f"expected {expected}, got {actual}"


def assert_absent_or_none(resource: Dict, field_names: Iterable[str]) -> None:
    """A field the contract says is not yet set is either missing or null."""
    for name in field_names:
        assert resource.get(name) is None, (
            f"expected {name} to be null, got {resource.get(name)!r}"
        )


# ─── List envelope assertions ─────────────────────────────────────────────


def validate_unpaginated(response, expected_status: int = 200) -> list:
    """A list response whose endpoint takes no limit or offset input.

    The envelope still carries the four pagination fields — the contract makes
    that true of every list response — but the caller cannot influence them, so
    this validator returns just the rows.
    """
    rows = validate_success(response, expected_status)
    assert isinstance(rows, list), f"list data must be an array, got {type(rows)}"
    body = response.json()
    assert body.get("response_type") == "array", (
        f"a list response sets response_type to array, got {body.get('response_type')!r}"
    )
    assert_pagination_meta(body["meta"], len(rows))
    return rows


def assert_pagination_meta(meta: Dict, item_count: int) -> None:
    """The four pagination fields are present, typed, and internally coherent."""
    for field in ("total_count", "has_more", "limit", "offset"):
        assert field in meta, f"meta must carry {field}, got keys {list(meta)}"
    assert isinstance(meta["total_count"], int) and not isinstance(
        meta["total_count"], bool
    ), "total_count must be an integer"
    assert isinstance(meta["has_more"], bool), "has_more must be a boolean"
    assert isinstance(meta["limit"], int) and not isinstance(
        meta["limit"], bool
    ), "limit must be an integer"
    assert isinstance(meta["offset"], int) and not isinstance(
        meta["offset"], bool
    ), "offset must be an integer"
    assert meta["limit"] >= 1, f"limit must be at least 1, got {meta['limit']}"
    assert meta["offset"] >= 0, f"offset must not be negative, got {meta['offset']}"
    expected_has_more = meta["offset"] + item_count < meta["total_count"]
    assert meta["has_more"] == expected_has_more, (
        f"has_more should be {expected_has_more} for offset {meta['offset']}, "
        f"{item_count} rows returned and total_count {meta['total_count']}"
    )


def assert_row_count(items: Sequence, expected: int, what: str = "rows") -> None:
    assert len(items) == expected, (
        f"expected exactly {expected} {what}, got {len(items)}: "
        f"{[row.get('id') for row in items if isinstance(row, dict)]}"
    )


def find_by_id(items: Sequence[Dict], resource_id: str) -> Dict:
    """The one row in a list carrying this id."""
    matches = [row for row in items if row.get("id") == resource_id]
    assert len(matches) == 1, (
        f"expected exactly one row with id {resource_id}, found {len(matches)}"
    )
    return matches[0]


def ids_of(items: Sequence[Dict]) -> list:
    return [row["id"] for row in items]


# ─── Money, mills and percentage assertions ───────────────────────────────


def assert_whole_cents(value, field_name: str = "amount") -> None:
    """Money crosses the wire as an integer count of whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer count of whole cents, got {value!r}"
    )


def assert_cents(resource: Dict, field_name: str, expected: int) -> None:
    """A money field holds exactly this many whole cents."""
    actual = resource.get(field_name)
    assert_whole_cents(actual, field_name)
    assert actual == expected, (
        f"expected {field_name} to be {expected} cents, got {actual}"
    )


def assert_mills(resource: Dict, field_name: str, expected: int) -> None:
    """A per-piece rate holds exactly this many mills, floored not rounded."""
    actual = resource.get(field_name)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field_name} must be an integer count of mills, got {actual!r}"
    )
    assert actual == expected, (
        f"expected {field_name} to be {expected} mills, got {actual}"
    )


def assert_pct_2dp(resource: Dict, field_name: str, expected: Optional[float]) -> None:
    """A percentage the contract specifies to two decimals."""
    actual = resource.get(field_name)
    if expected is None:
        assert actual is None, f"expected {field_name} to be null, got {actual!r}"
        return
    assert actual is not None, f"expected {field_name} to be {expected}, got null"
    assert abs(float(actual) - expected) < 0.005, (
        f"expected {field_name} to be {expected}, got {actual}"
    )


def assert_pct_4dp(resource: Dict, field_name: str, expected: Optional[float]) -> None:
    """A percentage the contract specifies to four decimals."""
    actual = resource.get(field_name)
    if expected is None:
        assert actual is None, f"expected {field_name} to be null, got {actual!r}"
        return
    assert actual is not None, f"expected {field_name} to be {expected}, got null"
    assert abs(float(actual) - expected) < 0.00005, (
        f"expected {field_name} to be {expected}, got {actual}"
    )


def assert_sum_of_cents(parts: Iterable[int], expected_total: int, what: str = "parts") -> None:
    """Whole-cent parts add up to the whole-cent total with nothing lost."""
    parts = list(parts)
    for part in parts:
        assert_whole_cents(part, what)
    total = sum(parts)
    assert total == expected_total, (
        f"expected {what} {parts} to sum to {expected_total}, got {total}"
    )


# ─── Resource-state assertions ────────────────────────────────────────────


def assert_batch_pricing(
    batch: Dict,
    status: str,
    achieved_tier: str,
    rate_mills: int,
    postage_cents: int,
) -> None:
    """A batch's status and its three priced figures together."""
    assert batch["status"] == status, (
        f"expected batch status {status}, got {batch['status']}"
    )
    assert batch["achieved_tier"] == achieved_tier, (
        f"expected achieved_tier {achieved_tier}, got {batch['achieved_tier']}"
    )
    assert_mills(batch, "rate_mills_per_piece", rate_mills)
    assert_cents(batch, "batch_postage_cents", postage_cents)


def assert_batch_ledger(
    batch: Dict, member_job_count: int, total_piece_count: int, container_count: int
) -> None:
    """A batch's three roll-up counters together."""
    assert_field_values(
        batch,
        {
            "member_job_count": member_job_count,
            "total_piece_count": total_piece_count,
            "container_count": container_count,
        },
    )


def assert_permit_funds(
    permit: Dict, balance_cents: int, reserved_cents: int
) -> None:
    """A permit account's two money fields together."""
    assert_cents(permit, "balance_cents", balance_cents)
    assert_cents(permit, "reserved_cents", reserved_cents)


def assert_funds_conserved(permit: Dict, total_funded_cents: int) -> None:
    """Balance plus reserved equals everything ever funded."""
    assert_cents(permit, "balance_cents", permit["balance_cents"])
    assert_cents(permit, "reserved_cents", permit["reserved_cents"])
    total = permit["balance_cents"] + permit["reserved_cents"]
    assert total == total_funded_cents, (
        f"expected balance {permit['balance_cents']} plus reserved "
        f"{permit['reserved_cents']} to equal {total_funded_cents}, got {total}"
    )


def assert_job_state(
    job: Dict,
    status: str,
    accepted_piece_count: Optional[int] = None,
    rework_count: Optional[int] = None,
    postage_due_cents: Optional[int] = None,
    commingle_batch_id: Optional[str] = "__unchecked__",
) -> None:
    """A mail job's status plus whichever of its counters the caller names."""
    assert job["status"] == status, (
        f"expected job status {status}, got {job['status']}"
    )
    if accepted_piece_count is not None:
        assert job["accepted_piece_count"] == accepted_piece_count, (
            f"expected accepted_piece_count {accepted_piece_count}, "
            f"got {job['accepted_piece_count']}"
        )
    if rework_count is not None:
        assert job["rework_count"] == rework_count, (
            f"expected rework_count {rework_count}, got {job['rework_count']}"
        )
    if postage_due_cents is not None:
        assert_cents(job, "postage_due_cents", postage_due_cents)
    if commingle_batch_id != "__unchecked__":
        assert job["commingle_batch_id"] == commingle_batch_id, (
            f"expected commingle_batch_id {commingle_batch_id!r}, "
            f"got {job['commingle_batch_id']!r}"
        )


def assert_statement_figures(
    statement: Dict,
    status: str,
    declared_postage_cents: int,
    adjustment_cents: int,
    verified_postage_cents: int,
    verification_error_count: int,
    revision_index: Optional[int] = None,
) -> None:
    """A postage statement's status plus its four money and count figures."""
    assert statement["status"] == status, (
        f"expected statement status {status}, got {statement['status']}"
    )
    assert_cents(statement, "declared_postage_cents", declared_postage_cents)
    assert_cents(statement, "adjustment_cents", adjustment_cents)
    assert_cents(statement, "verified_postage_cents", verified_postage_cents)
    assert statement["verification_error_count"] == verification_error_count, (
        f"expected verification_error_count {verification_error_count}, "
        f"got {statement['verification_error_count']}"
    )
    if revision_index is not None:
        assert statement["revision_index"] == revision_index, (
            f"expected revision_index {revision_index}, "
            f"got {statement['revision_index']}"
        )


def assert_member_allocation(
    member: Dict,
    contributed_piece_count: int,
    share_basis_pct: Optional[float],
    allocated_postage_cents: int,
    allocated_adjustment_cents: int,
) -> None:
    """A batch member's contribution, share and two allocated figures."""
    assert member["contributed_piece_count"] == contributed_piece_count, (
        f"expected contributed_piece_count {contributed_piece_count}, "
        f"got {member['contributed_piece_count']}"
    )
    assert_pct_4dp(member, "share_basis_pct", share_basis_pct)
    assert_cents(member, "allocated_postage_cents", allocated_postage_cents)
    assert_cents(member, "allocated_adjustment_cents", allocated_adjustment_cents)


def assert_container_state(
    container: Dict,
    status: str,
    qualifies: bool,
    placard_id: Optional[str],
    sequence_index: Optional[int] = None,
) -> None:
    """A sort container's status, qualification and placard together."""
    assert container["status"] == status, (
        f"expected container status {status}, got {container['status']}"
    )
    assert container["qualifies"] is qualifies, (
        f"expected qualifies {qualifies}, got {container['qualifies']!r}"
    )
    assert container["placard_id"] == placard_id, (
        f"expected placard_id {placard_id!r}, got {container['placard_id']!r}"
    )
    if sequence_index is not None:
        assert container["sequence_index"] == sequence_index, (
            f"expected sequence_index {sequence_index}, "
            f"got {container['sequence_index']}"
        )


def assert_service_level_index(
    index: Dict,
    record_count: int,
    on_time_count: int,
    zone_weighted_index: Optional[float],
    piece_weighted_index: Optional[float],
) -> None:
    """The two service-level indices and the population they were built from."""
    assert index["record_count"] == record_count, (
        f"expected record_count {record_count}, got {index['record_count']}"
    )
    assert index["on_time_count"] == on_time_count, (
        f"expected on_time_count {on_time_count}, got {index['on_time_count']}"
    )
    assert_pct_2dp(index, "zone_weighted_index", zone_weighted_index)
    assert_pct_2dp(index, "piece_weighted_index", piece_weighted_index)


def assert_invoice_figures(
    invoice: Dict,
    status: str,
    billed_piece_count: int,
    included_job_count: int,
    postage_cents: int,
    adjustment_cents: int,
    service_fee_cents: int,
    total_cents: int,
) -> None:
    """An invoice's status, its two counts and its four money figures."""
    assert invoice["status"] == status, (
        f"expected invoice status {status}, got {invoice['status']}"
    )
    assert invoice["billed_piece_count"] == billed_piece_count, (
        f"expected billed_piece_count {billed_piece_count}, "
        f"got {invoice['billed_piece_count']}"
    )
    assert invoice["included_job_count"] == included_job_count, (
        f"expected included_job_count {included_job_count}, "
        f"got {invoice['included_job_count']}"
    )
    assert_cents(invoice, "postage_cents", postage_cents)
    assert_cents(invoice, "adjustment_cents", adjustment_cents)
    assert_cents(invoice, "service_fee_cents", service_fee_cents)
    assert_cents(invoice, "total_cents", total_cents)
    assert (
        postage_cents + adjustment_cents + service_fee_cents == total_cents
    ), "invoice total must be postage plus adjustment plus service fee"


def assert_unchanged(before: Dict, after: Dict, *fields: str) -> None:
    """Named fields hold the same values they held before a rejected call."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"expected {field} to be unchanged at {before.get(field)!r}, "
            f"got {after.get(field)!r}"
        )


def assert_version_unchanged(before: Dict, after: Dict) -> None:
    """A rejected write leaves the optimistic-concurrency version alone."""
    assert before["version"] == after["version"], (
        f"expected version to stay {before['version']}, got {after['version']}"
    )


def assert_no_content(response) -> None:
    """A successful deletion answers 204 and carries no body at all."""
    assert response.status_code == 204, (
        f"expected 204 No Content, got {response.status_code}: {response.text}"
    )
    assert response.text == "", (
        f"expected an empty body on a 204, got {response.text!r}"
    )
