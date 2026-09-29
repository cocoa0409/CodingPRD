"""Domain assertions for the Fresh-Cut Produce Processing API.

These sit on top of the generic envelope validators. They express the plant's
own rules - pounds carry two decimals, the organic load index carries exactly
three, money is whole cents, the four case counters always sum to the number of
cases packed - so that a failing test names the rule it broke rather than
printing two numbers.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .api_client import canonical_instant


# ── Numeric precision ──────────────────────────────────────────────────────

def _decimal_places(value: Any) -> int:
    """How many decimal places a JSON number actually carries."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a JSON number, got {value!r} of type {type(value).__name__}"
    )
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    return max(0, -int(exponent))


def assert_decimal_places(value: Any, places: int, field: str = "value") -> None:
    """A quantity must not carry more decimal places than its declared scale."""
    actual = _decimal_places(value)
    assert actual <= places, (
        f"{field} {value!r} carries {actual} decimal places, "
        f"but the contract declares {places}"
    )


def assert_pounds(value: Any, field: str = "pounds") -> None:
    """Weights in pounds are stored and returned with two decimal places."""
    assert_decimal_places(value, 2, field)


def assert_percentage(value: Any, field: str = "percentage") -> None:
    """Yield percentages are stored and returned with two decimal places."""
    assert_decimal_places(value, 2, field)


def assert_load_index(value: Any, field: str = "organic_load_index") -> None:
    """The organic load index is carried at exactly three decimal places."""
    assert_decimal_places(value, 3, field)


def assert_one_decimal(value: Any, field: str = "value") -> None:
    """Chlorine, pH, turbidity and pulp temperature carry one decimal place."""
    assert_decimal_places(value, 1, field)


def assert_whole_number(value: Any, field: str = "value") -> None:
    """Oxidation-reduction potential and day counts are whole numbers."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} {value!r} is not a JSON number"
    )
    assert float(value) == int(value), f"{field} {value!r} is not a whole number"


def assert_cents(value: Any, field: str = "cost_cents") -> None:
    """Money is a whole integer number of cents, never a fractional amount."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} {value!r} must be a whole integer number of cents"
    )


# ── Instants and dates ─────────────────────────────────────────────────────

def assert_instant(value: Any, field: str = "timestamp") -> None:
    """A field the contract renders as an ISO 8601 UTC instant."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{field} {value!r} is not an ISO 8601 UTC instant"
    )


def assert_instant_equals(actual: Any, expected: str, field: str = "timestamp") -> None:
    """Two spellings of one instant compare equal regardless of fraction width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field} was {actual!r}, expected the instant {expected!r}"
    )


def assert_calendar_date(value: Any, field: str = "date") -> None:
    """A field the contract renders as a plain calendar date, not an instant."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} {value!r} is not a YYYY-MM-DD calendar date"
    )


# ── Audit fields ───────────────────────────────────────────────────────────

def assert_common_fields(entity: Dict[str, Any], name: str = "entity") -> None:
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id {entity.get('id')!r} is not a UUID"
    assert_instant(entity.get("created_at"), f"{name}.created_at")
    assert_instant(entity.get("updated_at"), f"{name}.updated_at")
    version = entity.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{name}.version {version!r} must be an integer of at least 1"
    )


def assert_append_only_fields(entity: Dict[str, Any], name: str = "reading") -> None:
    """An append-only record carries only id and created_at, with no version."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id {entity.get('id')!r} is not a UUID"
    assert_instant(entity.get("created_at"), f"{name}.created_at")
    assert "updated_at" not in entity, f"{name} must not carry updated_at"
    assert "version" not in entity, f"{name} must not carry version"


def assert_created_equals_updated(entity: Dict[str, Any], name: str = "entity") -> None:
    """A resource that has never been revised reports one instant twice."""
    assert_instant_equals(entity["updated_at"], entity["created_at"], f"{name}.updated_at")


def assert_version_is(entity: Dict[str, Any], expected: int, name: str = "entity") -> None:
    """A revision count that a test pins exactly."""
    assert entity.get("version") == expected, (
        f"{name}.version was {entity.get('version')!r}, expected {expected}"
    )


# ── Envelope shape ─────────────────────────────────────────────────────────

def assert_error_body_shape(response: Any, expected_error_id: str) -> Dict[str, Any]:
    """An error carries exactly error_id and message, plus the two meta fields."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"response_type was {body.get('response_type')!r}, expected 'error'"
    )
    data = body.get("data")
    assert isinstance(data, dict), f"error data must be an object, got {data!r}"
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data carried {sorted(data.keys())}, expected exactly "
        f"['error_id', 'message']"
    )
    assert data["error_id"] == expected_error_id, (
        f"error_id was {data['error_id']!r}, expected {expected_error_id!r}"
    )
    assert isinstance(data["message"], str) and data["message"], "error message must be non-empty"
    meta = body.get("meta")
    assert isinstance(meta, dict), f"error meta must be an object, got {meta!r}"
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta carried {sorted(meta.keys())}, expected only the two "
        f"request fields"
    )
    assert_request_meta(meta)
    return data


def assert_request_meta(meta: Dict[str, Any]) -> None:
    """Every envelope carries a prefixed request id and a millisecond instant."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id {request_id!r} must be a string prefixed 'req_'"
    )
    stamp = meta.get("api_request_timestamp")
    assert_instant(stamp, "meta.api_request_timestamp")
    assert "." in stamp and stamp.endswith("Z") and len(stamp.split(".")[1]) == 4, (
        f"api_request_timestamp {stamp!r} must carry three fractional digits"
    )


def assert_object_envelope(response: Any) -> Dict[str, Any]:
    """A single-resource read: response_type 'object' with a well-formed meta."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type was {body.get('response_type')!r}, expected 'object'"
    )
    assert_request_meta(body.get("meta", {}))
    return body["data"]


# ── Collection pages ───────────────────────────────────────────────────────

def assert_page(
    response: Any,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
    expected_count: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """A paginated collection page, with any of its counters pinned by a test."""
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count was {meta['total_count']}, expected {expected_total}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more was {meta['has_more']!r}, expected {expected_has_more!r}"
        )
    if expected_count is not None:
        assert len(rows) == expected_count, (
            f"the page carried {len(rows)} rows, expected {expected_count}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"limit was {meta['limit']}, expected {expected_limit}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset was {meta['offset']}, expected {expected_offset}"
        )
    return rows


def assert_empty_page(response: Any) -> None:
    """A filter that matches nothing returns no rows and a zero total."""
    assert_page(response, expected_total=0, expected_has_more=False, expected_count=0)


def assert_ordered_by(
    rows: Sequence[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    """A collection's declared default ordering, read off the rows themselves."""
    values = [row[field] for row in rows]
    canonical = [
        canonical_instant(v) if isinstance(v, str) and "T" in v else v for v in values
    ]
    expected = sorted(canonical, reverse=descending)
    assert canonical == expected, (
        f"rows were ordered {values!r} on {field}, which is not "
        f"{'descending' if descending else 'ascending'}"
    )


def assert_field_sequence(
    rows: Sequence[Dict[str, Any]], field: str, expected: Sequence[Any]
) -> None:
    """The exact ordered values a page must present in one field."""
    actual = [row[field] for row in rows]
    assert actual == list(expected), (
        f"{field} sequence was {actual!r}, expected {list(expected)!r}"
    )


def assert_row_ids(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """The exact set of rows a filter must select, order-insensitively."""
    actual = sorted(row["id"] for row in rows)
    assert actual == sorted(expected_ids), (
        f"the page selected {actual!r}, expected {sorted(expected_ids)!r}"
    )


# ── Plant invariants ───────────────────────────────────────────────────────

def assert_case_counters_conserved(run: Dict[str, Any]) -> None:
    """The four case counters always sum to the number of cases packed."""
    available = run["cases_available"]
    on_hold = run["cases_on_hold"]
    shipped = run["cases_shipped"]
    destroyed = run["cases_destroyed"]
    total = available + on_hold + shipped + destroyed
    assert total == run["cases_produced"], (
        f"case counters {available}+{on_hold}+{shipped}+{destroyed} sum to {total}, "
        f"but cases_produced is {run['cases_produced']}"
    )


def assert_case_counters(
    run: Dict[str, Any],
    available: int,
    on_hold: int,
    shipped: int,
    destroyed: int,
) -> None:
    """All four case counters pinned at once, then checked for conservation."""
    assert (
        run["cases_available"],
        run["cases_on_hold"],
        run["cases_shipped"],
        run["cases_destroyed"],
    ) == (available, on_hold, shipped, destroyed), (
        "case counters were "
        f"available={run['cases_available']}, on_hold={run['cases_on_hold']}, "
        f"shipped={run['cases_shipped']}, destroyed={run['cases_destroyed']}; "
        f"expected available={available}, on_hold={on_hold}, "
        f"shipped={shipped}, destroyed={destroyed}"
    )
    assert_case_counters_conserved(run)


def assert_cost_waterfall(
    cases: Sequence[Dict[str, Any]],
    total_run_cost_cents: int,
    per_case_cost_cents: int,
) -> None:
    """Per-case costs sum back to the run total, the remainder spread one cent
    at a time over the lowest case sequences."""
    assert_cents(total_run_cost_cents, "total_run_cost_cents")
    assert_cents(per_case_cost_cents, "per_case_cost_cents")
    remainder = total_run_cost_cents - per_case_cost_cents * len(cases)
    for case in cases:
        expected = per_case_cost_cents + (1 if case["case_sequence"] <= remainder else 0)
        assert_cents(case["allocated_cost_cents"], "allocated_cost_cents")
        assert case["allocated_cost_cents"] == expected, (
            f"case_sequence {case['case_sequence']} was allocated "
            f"{case['allocated_cost_cents']} cents, expected {expected}"
        )


def assert_cost_totals(
    run: Dict[str, Any],
    total_run_cost_cents: Optional[int] = None,
    per_case_cost_cents: Optional[int] = None,
    cost_remainder_cents: Optional[int] = None,
) -> None:
    """The run's three money figures, each whole cents and mutually consistent."""
    for name in ("total_run_cost_cents", "per_case_cost_cents", "cost_remainder_cents"):
        assert_cents(run[name], name)
    assert (
        run["per_case_cost_cents"] * run["cases_produced"] + run["cost_remainder_cents"]
        == run["total_run_cost_cents"]
    ), (
        f"per_case_cost_cents {run['per_case_cost_cents']} over "
        f"{run['cases_produced']} cases plus a remainder of "
        f"{run['cost_remainder_cents']} does not reconstruct "
        f"total_run_cost_cents {run['total_run_cost_cents']}"
    )
    assert 0 <= run["cost_remainder_cents"] < run["cases_produced"], (
        f"cost_remainder_cents {run['cost_remainder_cents']} must be less than "
        f"the case count {run['cases_produced']}"
    )
    if total_run_cost_cents is not None:
        assert run["total_run_cost_cents"] == total_run_cost_cents, (
            f"total_run_cost_cents was {run['total_run_cost_cents']}, "
            f"expected {total_run_cost_cents}"
        )
    if per_case_cost_cents is not None:
        assert run["per_case_cost_cents"] == per_case_cost_cents, (
            f"per_case_cost_cents was {run['per_case_cost_cents']}, "
            f"expected {per_case_cost_cents}"
        )
    if cost_remainder_cents is not None:
        assert run["cost_remainder_cents"] == cost_remainder_cents, (
            f"cost_remainder_cents was {run['cost_remainder_cents']}, "
            f"expected {cost_remainder_cents}"
        )


def assert_wash_chemistry(
    system: Dict[str, Any],
    weighted_load_lb: Optional[float] = None,
    organic_load_index: Optional[float] = None,
    target_free_chlorine_ppm: Optional[Any] = None,
    status: Optional[str] = None,
) -> None:
    """A wash system's derived chemistry, at its declared precisions."""
    assert_pounds(system["weighted_load_lb"], "weighted_load_lb")
    assert_load_index(system["organic_load_index"], "organic_load_index")
    if weighted_load_lb is not None:
        assert system["weighted_load_lb"] == weighted_load_lb, (
            f"weighted_load_lb was {system['weighted_load_lb']}, expected {weighted_load_lb}"
        )
    if organic_load_index is not None:
        assert system["organic_load_index"] == organic_load_index, (
            f"organic_load_index was {system['organic_load_index']}, expected {organic_load_index}"
        )
    if target_free_chlorine_ppm is not None:
        actual = system["target_free_chlorine_ppm"]
        assert actual == target_free_chlorine_ppm, (
            f"target_free_chlorine_ppm was {actual}, expected {target_free_chlorine_ppm}"
        )
        assert_one_decimal(actual, "target_free_chlorine_ppm")
    if status is not None:
        assert system["status"] == status, (
            f"wash system status was {system['status']!r}, expected {status!r}"
        )


def assert_reading_derivations(
    reading: Dict[str, Any],
    organic_load_index_at_reading: float,
    target_free_chlorine_ppm_at_reading: Optional[float],
    topup_ppm_required: float,
    below_target: bool,
) -> None:
    """The four frozen figures a wash-water reading captures and never revises."""
    assert_load_index(reading["organic_load_index_at_reading"])
    assert reading["organic_load_index_at_reading"] == organic_load_index_at_reading, (
        f"organic_load_index_at_reading was {reading['organic_load_index_at_reading']}, "
        f"expected {organic_load_index_at_reading}"
    )
    assert reading["target_free_chlorine_ppm_at_reading"] == target_free_chlorine_ppm_at_reading, (
        f"target_free_chlorine_ppm_at_reading was "
        f"{reading['target_free_chlorine_ppm_at_reading']}, "
        f"expected {target_free_chlorine_ppm_at_reading}"
    )
    assert reading["topup_ppm_required"] == topup_ppm_required, (
        f"topup_ppm_required was {reading['topup_ppm_required']}, expected {topup_ppm_required}"
    )
    assert_one_decimal(reading["topup_ppm_required"], "topup_ppm_required")
    assert reading["below_target"] is below_target, (
        f"below_target was {reading['below_target']!r}, expected {below_target!r}"
    )


def assert_shelf_life(
    run: Dict[str, Any],
    provisional_days: Optional[int] = None,
    provisional_code_date: Optional[str] = None,
    final_days: Optional[Any] = None,
    final_code_date: Optional[Any] = None,
) -> None:
    """The two shelf-life forms and their code dates, pinned where a test cares."""
    if provisional_days is not None:
        assert run["provisional_shelf_life_days"] == provisional_days, (
            f"provisional_shelf_life_days was {run['provisional_shelf_life_days']}, "
            f"expected {provisional_days}"
        )
        assert_whole_number(run["provisional_shelf_life_days"], "provisional_shelf_life_days")
    if provisional_code_date is not None:
        assert_calendar_date(run["provisional_code_date"], "provisional_code_date")
        assert run["provisional_code_date"] == provisional_code_date, (
            f"provisional_code_date was {run['provisional_code_date']!r}, "
            f"expected {provisional_code_date!r}"
        )
    if final_days is not None:
        assert run["final_shelf_life_days"] == final_days, (
            f"final_shelf_life_days was {run['final_shelf_life_days']}, expected {final_days}"
        )
    if final_code_date is not None:
        assert run["final_code_date"] == final_code_date, (
            f"final_code_date was {run['final_code_date']!r}, expected {final_code_date!r}"
        )


def assert_risk_scores(
    lot: Dict[str, Any],
    preharvest: Optional[int] = None,
    trailing: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """A grower lot's two risk scores and the status they adjudicate."""
    if preharvest is not None:
        assert lot["preharvest_risk_score"] == preharvest, (
            f"preharvest_risk_score was {lot['preharvest_risk_score']}, expected {preharvest}"
        )
    if trailing is not None:
        assert lot["trailing_risk_score"] == trailing, (
            f"trailing_risk_score was {lot['trailing_risk_score']}, expected {trailing}"
        )
    if status is not None:
        assert lot["status"] == status, (
            f"grower lot status was {lot['status']!r}, expected {status!r}"
        )
