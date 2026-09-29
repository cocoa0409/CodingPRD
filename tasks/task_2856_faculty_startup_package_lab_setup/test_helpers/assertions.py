"""Entity assertions and domain invariant checkers for the startup package API."""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AppointmentType,
    CarryforwardPolicy,
    EquipmentOrderStatus,
    FacultyAppointmentStatus,
    FacultyRank,
    LabSpaceStatus,
    NegotiationStatus,
    PackageKind,
    RenovationPhaseStatus,
    RenovationProjectStatus,
    ScopeTier,
    SpaceAssignmentStatus,
    SpaceClass,
    SpendSourceKind,
    SpendStatus,
    SpendTransactionKind,
    StaffAppointmentStatus,
    TrancheCategory,
    TrancheStatus,
    UnitType,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_audit_triple(data: dict, entity: str = "resource") -> None:
    """Every entity but the ledger row carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# --- entity assertions -------------------------------------------------------

def assert_funding_unit(data: dict) -> None:
    assert_audit_triple(data, "FundingUnit")
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit_type"] in _values(UnitType)
    for field in (
        "cost_share_pool_cents",
        "reserved_cents",
        "committed_cents",
        "disbursed_cents",
        "refunded_cents",
        "available_pool_cents",
    ):
        assert isinstance(data[field], int), f"FundingUnit.{field} must be integer cents"
    assert_pool_identity(data)


def assert_faculty(data: dict) -> None:
    assert_audit_triple(data, "Faculty")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["rank"] in _values(FacultyRank)
    assert is_valid_uuid(data["funding_unit_id"])
    assert data["appointment_status"] in _values(FacultyAppointmentStatus)
    assert isinstance(data["retention_round"], int) and data["retention_round"] >= 0


def assert_startup_package(data: dict) -> None:
    assert_audit_triple(data, "StartupPackage")
    assert is_valid_uuid(data["faculty_id"])
    assert data["package_kind"] in _values(PackageKind)
    assert data["negotiation_status"] in _values(NegotiationStatus)
    assert data["spend_status"] in _values(SpendStatus)
    assert (
        data["dept_share_pct"] + data["college_share_pct"] + data["dean_share_pct"] == 100
    ), "the three cost-share percentages must sum to exactly 100"
    assert isinstance(data["proposed_total_cents"], int)
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 1


def assert_commitment_tranche(data: dict) -> None:
    assert_audit_triple(data, "CommitmentTranche")
    assert is_valid_uuid(data["package_id"])
    assert data["category"] in _values(TrancheCategory)
    assert data["carryforward_policy"] in _values(CarryforwardPolicy)
    assert data["status"] in _values(TrancheStatus)
    assert isinstance(data["fiscal_year"], int)
    assert data["amount_cents"] > 0, "a tranche amount_cents is strictly greater than 0"
    assert data["available_on"] < data["expires_on"], (
        "expires_on must be strictly later than available_on"
    )
    assert_tranche_balance_identity(data)


def assert_lab_space(data: dict) -> None:
    assert_audit_triple(data, "LabSpace")
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert isinstance(data["room_number"], str) and data["room_number"]
    assert data["space_class"] in _values(SpaceClass)
    assert data["status"] in _values(LabSpaceStatus)
    assert data["net_sq_ft"] > 0
    assert data["power_kw_capacity"] > 0
    assert data["floor_load_psf"] > 0
    assert data["fume_hood_count"] >= 0
    assert 0 <= data["allocated_share_pct"] <= 100
    assert data["installed_power_kw"] >= 0
    assert data["installed_fume_hoods"] >= 0


def assert_space_assignment(data: dict) -> None:
    assert_audit_triple(data, "SpaceAssignment")
    assert is_valid_uuid(data["space_id"])
    assert is_valid_uuid(data["faculty_id"])
    assert data["status"] in _values(SpaceAssignmentStatus)
    assert 1 <= data["share_pct"] <= 100
    assert is_iso8601_timestamp(data["effective_from"])
    if data.get("effective_to") is not None:
        assert data["effective_from"] < data["effective_to"], (
            "effective_to must be strictly later than effective_from"
        )


def assert_renovation_project(data: dict) -> None:
    assert_audit_triple(data, "RenovationProject")
    assert is_valid_uuid(data["package_id"])
    assert is_valid_uuid(data["space_id"])
    assert data["scope_tier"] in _values(ScopeTier)
    assert data["status"] in _values(RenovationProjectStatus)
    assert data["estimate_cents"] > 0
    assert isinstance(data["rescope_count"], int) and data["rescope_count"] >= 0


def assert_renovation_phase(data: dict) -> None:
    assert_audit_triple(data, "RenovationPhase")
    assert is_valid_uuid(data["project_id"])
    assert data["status"] in _values(RenovationPhaseStatus)
    assert data["sequence_no"] >= 1
    assert data["budget_cents"] > 0
    assert data["planned_start"] <= data["planned_end"], (
        "planned_end must be at or after planned_start"
    )


def assert_equipment_order(data: dict) -> None:
    assert_audit_triple(data, "EquipmentOrder")
    assert is_valid_uuid(data["package_id"])
    assert is_valid_uuid(data["install_space_id"])
    assert data["status"] in _values(EquipmentOrderStatus)
    assert data["quoted_cents"] > 0
    assert data["lead_time_days"] >= 0
    assert data["required_power_kw"] >= 0
    assert data["required_fume_hoods"] >= 0
    assert data["required_floor_load_psf"] > 0
    assert isinstance(data["encumbered_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_staff_appointment(data: dict) -> None:
    assert_audit_triple(data, "StaffAppointment")
    assert is_valid_uuid(data["package_id"])
    assert data["appointment_type"] in _values(AppointmentType)
    assert data["status"] in _values(StaffAppointmentStatus)
    assert 0 < data["fte"] <= 1.0, "fte is strictly greater than 0 and at most 1.00"
    assert data["monthly_cost_cents"] > 0
    assert data["start_date"] <= data["end_date"]
    assert data["committed_months"] >= 1


def assert_spend_transaction(data: dict) -> None:
    """A ledger row carries only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "SpendTransaction.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "SpendTransaction.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        "a SpendTransaction is append-only: updated_at must be absent"
    )
    assert "version" not in data, (
        "a SpendTransaction is append-only: version must be absent"
    )
    assert data["kind"] in _values(SpendTransactionKind)
    assert data["source_kind"] in _values(SpendSourceKind)
    assert data["amount_cents"] > 0, "amount_cents on a row is always a positive magnitude"
    assert_row_shares_sum_to_amount(data)


# --- domain invariants -------------------------------------------------------

def assert_pool_identity(unit: dict) -> None:
    """available_pool_cents is cost_share_pool_cents less reserved_cents."""
    assert unit["available_pool_cents"] == unit["cost_share_pool_cents"] - unit["reserved_cents"], (
        "available_pool_cents must equal cost_share_pool_cents less reserved_cents, "
        f"got {unit['available_pool_cents']} vs "
        f"{unit['cost_share_pool_cents']} - {unit['reserved_cents']}"
    )


def assert_tranche_balance_identity(tranche: dict) -> None:
    """amount + carried_in == available + encumbered + disbursed + carried_out
    + expired + recaptured, with zero tolerance."""
    left = tranche["amount_cents"] + tranche["carried_in_cents"]
    right = (
        tranche["available_balance_cents"]
        + tranche["encumbered_cents"]
        + tranche["disbursed_cents"]
        + tranche["carried_out_cents"]
        + tranche["expired_cents"]
        + tranche["recaptured_cents"]
    )
    assert left == right, (
        "tranche balance identity broken: "
        f"amount {tranche['amount_cents']} + carried_in {tranche['carried_in_cents']} "
        f"= {left} but the six terms sum to {right}"
    )


def assert_row_shares_sum_to_amount(row: dict) -> None:
    total = row["dept_share_cents"] + row["college_share_cents"] + row["dean_share_cents"]
    assert total == row["amount_cents"], (
        f"the three funder shares must sum to amount_cents exactly: "
        f"{row['dept_share_cents']} + {row['college_share_cents']} + "
        f"{row['dean_share_cents']} = {total} != {row['amount_cents']}"
    )


def assert_row_shares(row: dict, dept_share_cents: int, college_share_cents: int,
                      dean_share_cents: int) -> None:
    assert row["dept_share_cents"] == dept_share_cents, (
        f"expected dept_share_cents {dept_share_cents}, got {row['dept_share_cents']}"
    )
    assert row["college_share_cents"] == college_share_cents, (
        f"expected college_share_cents {college_share_cents}, got {row['college_share_cents']}"
    )
    assert row["dean_share_cents"] == dean_share_cents, (
        f"expected dean_share_cents {dean_share_cents}, got {row['dean_share_cents']}"
    )
    assert_row_shares_sum_to_amount(row)


def compute_funder_split(amount_cents: int, dept_share_pct: int, college_share_pct: int,
                         dean_share_pct: int) -> tuple:
    """The largest-fractional-part-first split of one transaction amount, with
    ties broken by the fixed ordering department, then college, then dean."""
    pcts = [dept_share_pct, college_share_pct, dean_share_pct]
    bases = [(amount_cents * pct) // 100 for pct in pcts]
    remainders = [(amount_cents * pct) % 100 for pct in pcts]
    leftover = amount_cents - sum(bases)
    order = sorted(range(3), key=lambda i: (-remainders[i], i))
    for i in order[:leftover]:
        bases[i] += 1
    return tuple(bases)


def assert_unit_balances(unit: dict, reserved_cents=None, committed_cents=None,
                         disbursed_cents=None, refunded_cents=None) -> None:
    if reserved_cents is not None:
        assert unit["reserved_cents"] == reserved_cents, (
            f"expected reserved_cents {reserved_cents}, got {unit['reserved_cents']}"
        )
    if committed_cents is not None:
        assert unit["committed_cents"] == committed_cents, (
            f"expected committed_cents {committed_cents}, got {unit['committed_cents']}"
        )
    if disbursed_cents is not None:
        assert unit["disbursed_cents"] == disbursed_cents, (
            f"expected disbursed_cents {disbursed_cents}, got {unit['disbursed_cents']}"
        )
    if refunded_cents is not None:
        assert unit["refunded_cents"] == refunded_cents, (
            f"expected refunded_cents {refunded_cents}, got {unit['refunded_cents']}"
        )
    assert_pool_identity(unit)


def assert_tranche_balances(tranche: dict, available_balance_cents=None,
                            encumbered_cents=None, disbursed_cents=None,
                            expired_cents=None, recaptured_cents=None,
                            carried_in_cents=None, carried_out_cents=None,
                            status=None) -> None:
    expectations = {
        "available_balance_cents": available_balance_cents,
        "encumbered_cents": encumbered_cents,
        "disbursed_cents": disbursed_cents,
        "expired_cents": expired_cents,
        "recaptured_cents": recaptured_cents,
        "carried_in_cents": carried_in_cents,
        "carried_out_cents": carried_out_cents,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert tranche[field] == expected, (
                f"expected tranche {field} {expected}, got {tranche[field]}"
            )
    if status is not None:
        assert tranche["status"] == status, (
            f"expected tranche status {status}, got {tranche['status']}"
        )
    assert_tranche_balance_identity(tranche)


def rows_of_kind(rows: list, kind: str) -> list:
    return [row for row in rows if row["kind"] == kind]


def assert_no_rows_of_kind(rows: list, kind: str) -> None:
    matches = rows_of_kind(rows, kind)
    assert not matches, f"expected no {kind} row, found {len(matches)}"


def assert_power_kw(actual, expected) -> None:
    """Power is carried to two decimal places."""
    assert float(actual) == pytest.approx(float(expected), abs=0.005), (
        f"expected installed/capacity power {expected} kW, got {actual}"
    )


def assert_spend_down_ratio(actual, expected) -> None:
    """spend_down_ratio is rounded half up to four decimal places."""
    assert float(actual) == pytest.approx(float(expected), abs=0.00005), (
        f"expected spend_down_ratio {expected}, got {actual}"
    )


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant so 00:00:00Z and 00:00:00.000Z compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"expected a UTC instant ending in Z, got {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = frac.rstrip("0")
        body = f"{head}.{frac}" if frac else head
    return body + "Z"


def assert_instant_equals(actual, expected: str) -> None:
    """Compare two instants regardless of how many fractional digits are carried."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_date_equals(actual, expected: str) -> None:
    """Calendar-date fields are plain YYYY-MM-DD strings."""
    assert actual == expected, f"expected date {expected}, got {actual}"


def rows_for_source(rows: list, source_id: str) -> list:
    """The ledger rows a given order, appointment or project produced."""
    return [row for row in rows if row.get("source_id") == source_id]


def assert_row_amount_and_shares(row: dict, amount_cents: int, dept: int,
                                 college: int, dean: int) -> None:
    assert row["amount_cents"] == amount_cents, (
        f"expected row amount_cents {amount_cents}, got {row['amount_cents']}"
    )
    assert_row_shares(row, dept, college, dean)


def assert_balance_identity_for_all(tranches: list) -> None:
    """The tranche balance identity holds for every tranche with zero tolerance."""
    for tranche in tranches:
        assert_tranche_balance_identity(tranche)
