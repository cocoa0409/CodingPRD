"""Domain assertions shared by the whole suite.

Every helper here takes an already-unwrapped `data` payload (never an
envelope), so no call site ever reaches into `["data"]` twice.
"""

import re
from typing import Any, Dict, Iterable, Optional

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)$"
)


def canonical_instant(value: str) -> str:
    """Normalise an ISO-8601 UTC instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    PRD §2.4 fixes three fractional digits, but a server that emits `...Z`
    with no fraction, or with six digits, is still naming the same instant.
    Timestamp equality is therefore always compared through this normaliser
    rather than by raw string identity.
    """
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"not an ISO-8601 UTC instant: {value!r}"
    date_part, time_part, fraction = match.groups()
    millis = (fraction or "0").ljust(3, "0")[:3]
    return f"{date_part}T{time_part}.{millis}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO-8601 instants name the same moment."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_timestamp_millis(value: Any, label: str = "timestamp") -> None:
    """PRD §2.4: an instant carried with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} is not a string: {value!r}"
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value
    ), f"{label} is not an ISO-8601 UTC instant with three fractional digits: {value!r}"


# ─── Numeric regimes (PRD §2.9) ─────────────────────────────────────────


def assert_rate_equals(actual: Any, expected: float, label: str = "rate") -> None:
    """A 2-decimal-place decimal quantity: a clearance rate or a score."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert abs(float(actual) - float(expected)) < 1e-9, (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_two_decimal_places(value: Any, label: str = "value") -> None:
    """PRD §2.9: rates and the progression score are carried to 2dp."""
    quantised = round(float(value) + 0.0, 2)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} carries more than two decimal places: {value!r}"
    )


def assert_whole_cents(value: Any, label: str = "cents") -> None:
    """PRD §2.9: money is held in whole cents, so always an integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of whole cents, got {value!r}"
    )


def assert_bond_ledger_conserved(venue: Dict[str, Any]) -> None:
    """PRD §2.9: held + released + forfeited == the posted bond, exactly."""
    posted = venue["restoration_bond_cents"]
    released = venue["bond_released_cents"]
    forfeited = venue["bond_forfeited_cents"]
    held = venue["bond_held_cents"]
    for label, amount in (
        ("restoration_bond_cents", posted),
        ("bond_released_cents", released),
        ("bond_forfeited_cents", forfeited),
        ("bond_held_cents", held),
    ):
        assert_whole_cents(amount, label)
    assert held + released + forfeited == posted, (
        "bond ledger is not conserved: "
        f"held {held} + released {released} + forfeited {forfeited} "
        f"!= restoration_bond_cents {posted}"
    )


# ─── Entity-shape assertions (PRD §2.4) ─────────────────────────────────


def assert_version(row: Dict[str, Any], expected: int, label: str = "row") -> None:
    assert row["version"] == expected, (
        f"{label} version: expected {expected}, got {row['version']}"
    )


def assert_no_version_fields(row: Dict[str, Any], label: str = "row") -> None:
    """PRD §2.4: a Division and an ObstacleAttempt carry only id and created_at."""
    assert "version" not in row, f"{label} must not carry a version field: {row!r}"
    assert "updated_at" not in row, f"{label} must not carry updated_at: {row!r}"
    assert "id" in row and "created_at" in row, (
        f"{label} must still carry id and created_at: {row!r}"
    )


def assert_fields_absent(
    row: Dict[str, Any], fields: Iterable[str], label: str = "row"
) -> None:
    for field in fields:
        assert field not in row, f"{label} must not carry {field}: {row!r}"


# ─── State assertions ───────────────────────────────────────────────────


def assert_wave_state(
    wave: Dict[str, Any],
    release_status: Optional[str] = None,
    roster_status: Optional[str] = None,
    hold_reason: Optional[str] = "__unchecked__",
) -> None:
    """Assert either or both of the wave's two orthogonal dimensions."""
    if release_status is not None:
        assert wave["release_status"] == release_status, (
            f"release_status: expected {release_status}, got {wave['release_status']}"
        )
    if roster_status is not None:
        assert wave["roster_status"] == roster_status, (
            f"roster_status: expected {roster_status}, got {wave['roster_status']}"
        )
    if hold_reason != "__unchecked__":
        assert wave["hold_reason"] == hold_reason, (
            f"hold_reason: expected {hold_reason!r}, got {wave['hold_reason']!r}"
        )


def assert_entry_state(
    entry: Dict[str, Any],
    progress_status: Optional[str] = None,
    result_status: Optional[str] = None,
) -> None:
    """Assert either or both of the entry's two orthogonal dimensions."""
    if progress_status is not None:
        assert entry["progress_status"] == progress_status, (
            f"progress_status: expected {progress_status}, "
            f"got {entry['progress_status']}"
        )
    if result_status is not None:
        assert entry["result_status"] == result_status, (
            f"result_status: expected {result_status}, got {entry['result_status']}"
        )


def assert_obstacle_staffing(
    obstacle: Dict[str, Any],
    staffing_state: Optional[str] = None,
    confirmed_marshal_count: Optional[int] = None,
    effective_rate: Optional[float] = None,
    design_rate: Optional[float] = None,
) -> None:
    if staffing_state is not None:
        assert obstacle["staffing_state"] == staffing_state, (
            f"staffing_state: expected {staffing_state}, "
            f"got {obstacle['staffing_state']}"
        )
    if confirmed_marshal_count is not None:
        assert obstacle["confirmed_marshal_count"] == confirmed_marshal_count, (
            "confirmed_marshal_count: expected "
            f"{confirmed_marshal_count}, got {obstacle['confirmed_marshal_count']}"
        )
    if effective_rate is not None:
        assert_rate_equals(
            obstacle["effective_clearance_rate_per_min"],
            effective_rate,
            "effective_clearance_rate_per_min",
        )
    if design_rate is not None:
        assert_rate_equals(
            obstacle["design_clearance_rate_per_min"],
            design_rate,
            "design_clearance_rate_per_min",
        )


def assert_course_capacities(
    course: Dict[str, Any],
    design_capacity_pph: Optional[int] = None,
    bottleneck_capacity_pph: Optional[int] = None,
    scheduled_capacity_total: Optional[int] = None,
    readiness_posture: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    if design_capacity_pph is not None:
        assert course["design_capacity_pph"] == design_capacity_pph, (
            f"design_capacity_pph: expected {design_capacity_pph}, "
            f"got {course['design_capacity_pph']}"
        )
    if bottleneck_capacity_pph is not None:
        assert course["bottleneck_capacity_pph"] == bottleneck_capacity_pph, (
            f"bottleneck_capacity_pph: expected {bottleneck_capacity_pph}, "
            f"got {course['bottleneck_capacity_pph']}"
        )
    if scheduled_capacity_total is not None:
        assert course["scheduled_capacity_total"] == scheduled_capacity_total, (
            f"scheduled_capacity_total: expected {scheduled_capacity_total}, "
            f"got {course['scheduled_capacity_total']}"
        )
    if readiness_posture is not None:
        assert course["readiness_posture"] == readiness_posture, (
            f"readiness_posture: expected {readiness_posture}, "
            f"got {course['readiness_posture']}"
        )
    if status is not None:
        assert course["status"] == status, (
            f"course status: expected {status}, got {course['status']}"
        )


def assert_timing(
    entry: Dict[str, Any],
    provisional_penalty_seconds: Optional[int] = None,
    provisional_elapsed_seconds: Optional[int] = None,
    official_penalty_seconds: Optional[int] = None,
    official_elapsed_seconds: Optional[int] = None,
) -> None:
    """PRD §2.9: elapsed times are whole seconds, exact and never rounded."""
    expectations = {
        "provisional_penalty_seconds": provisional_penalty_seconds,
        "provisional_elapsed_seconds": provisional_elapsed_seconds,
        "official_penalty_seconds": official_penalty_seconds,
        "official_elapsed_seconds": official_elapsed_seconds,
    }
    for field, expected in expectations.items():
        if expected is None:
            continue
        actual = entry[field]
        assert isinstance(actual, int) and not isinstance(actual, bool), (
            f"{field} must be a whole number of seconds, got {actual!r}"
        )
        assert actual == expected, f"{field}: expected {expected}, got {actual}"


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    return [row["id"] for row in rows]
