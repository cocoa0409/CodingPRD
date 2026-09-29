"""
Entity-shape and domain-invariant assertions.

Every rule encoded here is stated in the PRD: the common audit fields of
§2.4, the observation exception, the seed ledger identity of §3.9 and the
three-source plot commitment of §3.1.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant

# Tolerances matched to the PRD's declared precisions (§2.6).
TOL_2DP = 0.005
TOL_3DP = 0.0005
TOL_4DP = 0.00005


def approx2(expected: float):
    """Compare a value the PRD rounds half up to two decimals."""
    return pytest.approx(expected, abs=TOL_2DP)


def approx3(expected: float):
    """Compare a value the PRD rounds half up to three decimals."""
    return pytest.approx(expected, abs=TOL_3DP)


def approx4(expected: float):
    """Compare a value the PRD rounds half up to four decimals."""
    return pytest.approx(expected, abs=TOL_4DP)


def assert_decimal_places(value: float, places: int, field: str = "value") -> None:
    """Assert a number carries no more than `places` decimal places."""
    assert value == pytest.approx(round(float(value), places), abs=10 ** -(places + 3)), (
        f"{field}={value!r} carries more than {places} decimal places"
    )


# ─── Common audit fields (PRD 2.4) ────────────────────

def assert_identity(data: Dict[str, Any]) -> None:
    """`id` is a server-generated UUID and `created_at` is an instant."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not an ISO 8601 instant: {data.get('created_at')!r}"
    )


def assert_versioned(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Assert the §2.4 versioned-resource shape: id, created_at, updated_at and an
    integer `version` starting at 1.
    """
    assert_identity(data)
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at is not an ISO 8601 instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_no_version_fields(data: Dict[str, Any]) -> None:
    """
    PRD 2.4: a phenotype observation "carries `id` and `created_at` only, and
    both `updated_at` and `version` are absent from its representation."
    """
    assert_identity(data)
    assert "version" not in data, "PhenotypeObservation must not expose version"
    assert "updated_at" not in data, "PhenotypeObservation must not expose updated_at"


def assert_instant_shape(value: str) -> None:
    """PRD 2.5 pins instants at `YYYY-MM-DDTHH:MM:SSZ`."""
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    assert canonical_instant(value) == value, (
        f"instant {value!r} is not second-precision `YYYY-MM-DDTHH:MM:SSZ`"
    )


def assert_date_only(value: str, field: str = "date") -> None:
    """PRD 2.5 pins calendar fields at exactly ten characters, `YYYY-MM-DD`."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field}={value!r} is not a ten-character YYYY-MM-DD date"
    )


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """PRD 2.2: every success envelope carries the two meta identifiers."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert isinstance(meta["api_request_timestamp"], str), (
        "meta.api_request_timestamp must be a string"
    )


# ─── Per-entity assertions ────────────────────────────

def _check(data: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    for field, want in expected.items():
        assert field in data, f"{label} is missing field {field!r}"
        got = data[field]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=TOL_2DP), (
                f"{label}.{field}: expected {want}, got {got}"
            )
        else:
            assert got == want, f"{label}.{field}: expected {want!r}, got {got!r}"


def assert_program(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "BreedingProgram")


def assert_objective(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "BreedingObjective")


def assert_nursery_block(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "NurseryBlock")


def assert_crossing_block(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "CrossingBlock")


def assert_line(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "BreedingLine")


def assert_planting(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "NurseryPlanting")


def assert_site(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "TrialSite")


def assert_series(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "TrialSeries")


def assert_entry(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "TrialEntry")


def assert_observation(data: Dict[str, Any], **expected) -> None:
    assert_no_version_fields(data)
    _check(data, expected, "PhenotypeObservation")


def assert_analysis(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "TrialSeriesAnalysis")


def assert_decision(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "AdvancementDecision")


def assert_agreement(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "StewardshipAgreement")


def assert_lot(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "SeedIncreaseLot")


def assert_backcross(data: Dict[str, Any], **expected) -> None:
    assert_versioned(data)
    _check(data, expected, "BackcrossProject")


# ─── Domain invariants ────────────────────────────────

def assert_seed_ledger_balances(line: Dict[str, Any]) -> None:
    """
    PRD 3.9 ledger identity: `seed_inventory_g` plus `reserved_seed_g` plus
    `consumed_seed_g` equals `cumulative_seed_produced_g` at every moment.
    """
    total = (
        line["seed_inventory_g"] + line["reserved_seed_g"] + line["consumed_seed_g"]
    )
    assert total == line["cumulative_seed_produced_g"], (
        "seed ledger does not balance: "
        f"{line['seed_inventory_g']} + {line['reserved_seed_g']} + "
        f"{line['consumed_seed_g']} != {line['cumulative_seed_produced_g']}"
    )


def assert_plot_budget_consistent(program: Dict[str, Any]) -> None:
    """
    PRD 3.1: "`plot_budget_remaining` is `total_plot_budget` less
    `committed_plot_count`."
    """
    assert (
        program["plot_budget_remaining"]
        == program["total_plot_budget"] - program["committed_plot_count"]
    ), (
        "plot_budget_remaining does not equal total_plot_budget less "
        f"committed_plot_count: {program['plot_budget_remaining']} vs "
        f"{program['total_plot_budget']} - {program['committed_plot_count']}"
    )


def assert_cash_budget_consistent(report: Dict[str, Any]) -> None:
    """
    PRD 3.1: `budget_remaining_usd` is the programme's `total_budget_usd` less
    its `committed_budget_usd`.
    """
    assert report["budget_remaining_usd"] == approx2(
        report["total_budget_usd"] - report["committed_budget_usd"]
    ), (
        "budget_remaining_usd does not reconcile: "
        f"{report['budget_remaining_usd']} vs {report['total_budget_usd']} - "
        f"{report['committed_budget_usd']}"
    )


def assert_site_capacity_consistent(site: Dict[str, Any]) -> None:
    """
    PRD 3.5: `available_plot_count` is the site's capacity less its daily peak.
    """
    assert (
        site["available_plot_count"]
        == site["total_plot_capacity"] - site["peak_committed_plot_count"]
    ), (
        "available_plot_count does not equal total_plot_capacity less "
        f"peak_committed_plot_count: {site['available_plot_count']} vs "
        f"{site['total_plot_capacity']} - {site['peak_committed_plot_count']}"
    )


def assert_ordered_desc(values, label: str = "series") -> None:
    """Assert a numeric sequence is in non-increasing order."""
    for earlier, later in zip(values, values[1:]):
        assert earlier >= later, f"{label} is not ordered descending: {values}"


def assert_ordered_asc(values, label: str = "series") -> None:
    """Assert a sequence is in non-decreasing order."""
    for earlier, later in zip(values, values[1:]):
        assert earlier <= later, f"{label} is not ordered ascending: {values}"
