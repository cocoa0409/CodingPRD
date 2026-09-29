"""
Domain assertions.

These wrap the repeated structural checks so that a test body reads as the
business claim it is making. Timestamp comparisons go through canonical_ts() so
that a difference in sub-second spelling is never mistaken for a difference in
instant.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_ts

# Records that are append-only logs: an id and a created_at, with no updated_at
# and no version.
APPEND_ONLY_FIELDS_ABSENT = ("updated_at", "version")


def assert_timestamps_equal(actual: Optional[str], expected: Optional[str], label: str = "timestamp") -> None:
    """Compare two ISO-8601 instants ignoring sub-second spelling differences."""
    assert canonical_ts(actual) == canonical_ts(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_mutable_record_shape(record: Dict[str, Any], label: str = "record") -> None:
    """
    A mutable record carries a server-minted UUID id, ISO-8601 created_at and
    updated_at, and an integer version.
    """
    assert is_valid_uuid(record.get("id")), f"{label}.id must be a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{label}.created_at must be an ISO-8601 timestamp: {record.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(record.get("updated_at")), (
        f"{label}.updated_at must be an ISO-8601 timestamp: {record.get('updated_at')!r}"
    )
    assert isinstance(record.get("version"), int), f"{label}.version must be an integer"
    assert record["version"] >= 1, f"{label}.version starts at 1"


def assert_append_only_record_shape(record: Dict[str, Any], label: str = "log row") -> None:
    """
    An append-only log row carries only an id and a created_at: updated_at and
    version are absent from it.
    """
    assert is_valid_uuid(record.get("id")), f"{label}.id must be a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{label}.created_at must be an ISO-8601 timestamp: {record.get('created_at')!r}"
    )
    for field in APPEND_ONLY_FIELDS_ABSENT:
        assert field not in record, f"{label} must not carry {field}: {record!r}"


def assert_version_is(record: Dict[str, Any], expected: int, label: str = "record") -> None:
    assert record.get("version") == expected, (
        f"{label}.version expected {expected}, got {record.get('version')}"
    )


def assert_fields(record: Dict[str, Any], expected: Dict[str, Any], label: str = "record") -> None:
    """Assert an exact match on each named field, one failure message per field."""
    for field, value in expected.items():
        assert field in record, f"{label} is missing field {field}"
        assert record[field] == value, (
            f"{label}.{field} expected {value!r}, got {record[field]!r}"
        )


def assert_all_none(record: Dict[str, Any], fields: List[str], label: str = "record") -> None:
    for field in fields:
        assert record.get(field) is None, (
            f"{label}.{field} must be null, got {record.get(field)!r}"
        )


def assert_money_integer(record: Dict[str, Any], *fields: str, label: str = "record") -> None:
    """Every monetary field is an integer number of cents, never a string or float."""
    for field in fields:
        value = record.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label}.{field} must be an integer number of cents, got {value!r}"
        )


def assert_all_money_fields_integer(record: Dict[str, Any], label: str = "record") -> None:
    """Every key ending in _cents on the record holds an integer."""
    for field, value in record.items():
        if field.endswith("_cents") and value is not None:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{label}.{field} must be an integer number of cents, got {value!r}"
            )


# ── Domain identities the specification says must always hold ──
def assert_wage_identity(settlement: Dict[str, Any]) -> None:
    """
    Gross pay always equals taxable wages plus non-taxable per diem, on every
    statement the system produces.
    """
    gross = settlement["gross_pay_cents"]
    taxable = settlement["taxable_wages_cents"]
    non_taxable = settlement["per_diem_non_taxable_cents"]
    assert gross == taxable + non_taxable, (
        f"gross_pay_cents {gross} must equal taxable_wages_cents {taxable} "
        f"plus per_diem_non_taxable_cents {non_taxable}"
    )


def assert_gross_decomposition(settlement: Dict[str, Any]) -> None:
    """
    gross_pay_cents is the sum of linehaul_total_cents, accessorial_total_cents
    and the signed retro_correction_total_cents.
    """
    total = (
        settlement["linehaul_total_cents"]
        + settlement["accessorial_total_cents"]
        + settlement["retro_correction_total_cents"]
    )
    assert settlement["gross_pay_cents"] == total, (
        f"gross_pay_cents {settlement['gross_pay_cents']} must equal linehaul "
        f"{settlement['linehaul_total_cents']} + accessorial "
        f"{settlement['accessorial_total_cents']} + retro "
        f"{settlement['retro_correction_total_cents']}"
    )


def assert_net_decomposition(settlement: Dict[str, Any]) -> None:
    """
    deduction_total_cents is escrow_deduction_cents plus advance_recovery_cents,
    and net_pay_cents is gross_pay_cents less deduction_total_cents.
    """
    deductions = (
        settlement["escrow_deduction_cents"] + settlement["advance_recovery_cents"]
    )
    assert settlement["deduction_total_cents"] == deductions, (
        f"deduction_total_cents {settlement['deduction_total_cents']} must equal escrow "
        f"{settlement['escrow_deduction_cents']} + advance recovery "
        f"{settlement['advance_recovery_cents']}"
    )
    expected_net = settlement["gross_pay_cents"] - settlement["deduction_total_cents"]
    assert settlement["net_pay_cents"] == expected_net, (
        f"net_pay_cents {settlement['net_pay_cents']} must equal gross "
        f"{settlement['gross_pay_cents']} less deductions "
        f"{settlement['deduction_total_cents']}"
    )


def assert_settlement_totals_consistent(settlement: Dict[str, Any]) -> None:
    """All three header identities at once."""
    assert_gross_decomposition(settlement)
    assert_wage_identity(settlement)
    assert_net_decomposition(settlement)


def assert_escrow_ledger_reconciles(
    transactions: List[Dict[str, Any]], balance_cents: int
) -> None:
    """
    The escrow account is an append-only ledger, so the driver's current
    escrow_balance_cents is the signed sum of every entry ever appended, and the
    balance_after_cents of the newest entry agrees with it.
    """
    signed_sum = sum(txn["amount_cents"] for txn in transactions)
    assert signed_sum == balance_cents, (
        f"ledger signed sum {signed_sum} must equal escrow_balance_cents {balance_cents}"
    )
    if transactions:
        assert transactions[-1]["balance_after_cents"] == balance_cents, (
            f"newest entry balance_after_cents "
            f"{transactions[-1]['balance_after_cents']} must equal the driver balance "
            f"{balance_cents}"
        )


def assert_advance_principal_conserved(advance: Dict[str, Any]) -> None:
    """An advance's recovered and outstanding amounts always sum to its principal."""
    total = advance["recovered_cents"] + advance["outstanding_cents"]
    assert total == advance["amount_cents"], (
        f"recovered_cents {advance['recovered_cents']} plus outstanding_cents "
        f"{advance['outstanding_cents']} must equal amount_cents "
        f"{advance['amount_cents']}"
    )


def assert_sequences_ascending_from_one(lines: List[Dict[str, Any]]) -> None:
    """
    Settlement-line sequence numbers are assigned ascending from 1, and the line
    collection is ordered by sequence ascending.
    """
    sequences = [line["sequence"] for line in lines]
    assert sequences == sorted(sequences), f"lines must be ordered by sequence: {sequences}"
    assert sequences == list(range(1, len(sequences) + 1)), (
        f"sequences must run 1..{len(sequences)}: {sequences}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Collections are sorted by created_at ascending unless stated otherwise."""
    stamps = [canonical_ts(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered by created_at ascending: {stamps}"


def find_line(lines: List[Dict[str, Any]], line_type: str) -> Optional[Dict[str, Any]]:
    """The single line of the given type, or None when the statement carries none."""
    matches = [line for line in lines if line["line_type"] == line_type]
    assert len(matches) <= 1, f"expected at most one {line_type} line, got {len(matches)}"
    return matches[0] if matches else None


def lines_of_type(lines: List[Dict[str, Any]], line_type: str) -> List[Dict[str, Any]]:
    return [line for line in lines if line["line_type"] == line_type]
