"""Domain assertions for the Provost Review API.

The instant helpers exist because §2.4 declares every server-written timestamp
as "an ISO 8601 UTC instant with exactly three fractional digits" while the
design indices and §2.5 quote anchor instants in the bare ``...Z`` form. Comparing
those two spellings as raw strings would fail on formatting rather than on
meaning, so every instant comparison in the suite goes through
``assert_instant_equals``, which normalises both sides to the same UTC instant
first.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Instant handling -------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z") or "+" in text, f"instant must be UTC: {value!r}"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render a datetime as an ISO-8601 UTC instant with three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO-8601 UTC instants denote the same moment."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_precision(actual: Any, label: str = "instant") -> None:
    """§2.4: a server-written instant carries exactly three fractional digits."""
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", actual), (
        f"{label} must be an ISO-8601 UTC instant with exactly three fractional "
        f"digits, got {actual!r}"
    )


def add_days(anchor: str, days: int) -> str:
    """§2.5: a statutory interval is an exact multiple of 24 hours from the anchor."""
    return format_instant(parse_instant(anchor) + timedelta(hours=24 * days))


def add_hours(anchor: str, hours: int) -> str:
    """Shift an instant by whole hours."""
    return format_instant(parse_instant(anchor) + timedelta(hours=hours))


def add_seconds(anchor: str, seconds: int) -> str:
    """Shift an instant by whole seconds."""
    return format_instant(parse_instant(anchor) + timedelta(seconds=seconds))


def assert_iso_date(value: Any, label: str = "date") -> None:
    """§3.4: ``span_start_date`` and ``span_end_date`` are formatted ``YYYY-MM-DD``."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _ISO_DATE_RE.match(value), f"{label} must be YYYY-MM-DD, got {value!r}"


# --- Identity, versioning, audit stamps (§2.4) ------------------------------


def assert_audit_quartet(record: Dict[str, Any], label: str = "record") -> None:
    """A record carrying the full quartet: id, created_at, updated_at, version."""
    assert is_valid_uuid(record.get("id")), (
        f"{label}.id must be a UUID with no prefix, got {record.get('id')!r}"
    )
    assert_instant_precision(record.get("created_at"), f"{label}.created_at")
    assert_instant_precision(record.get("updated_at"), f"{label}.updated_at")
    assert isinstance(record.get("version"), int), f"{label}.version must be an integer"
    assert record["version"] >= 1, f"{label}.version begins at 1"


def assert_append_only_stamps(record: Dict[str, Any], label: str = "record") -> None:
    """§2.4: an append-only record carries only ``id`` and ``created_at``.

    ``updated_at`` and ``version`` are absent from their payloads entirely.
    """
    assert is_valid_uuid(record.get("id")), f"{label}.id must be a UUID"
    assert_instant_precision(record.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in record, (
        f"{label} is append-only: updated_at must be absent entirely"
    )
    assert "version" not in record, (
        f"{label} is append-only: version must be absent entirely"
    )


def assert_version_is(record: Dict[str, Any], expected: int, label: str = "record") -> None:
    assert record.get("version") == expected, (
        f"{label}.version: expected {expected}, got {record.get('version')}"
    )


def assert_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], fields: List[str], label: str = "record"
) -> None:
    """Assert every named field is byte-identical across two reads."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{label}.{field} changed: {before.get(field)!r} -> {after.get(field)!r}"
        )


# --- Envelope (§2.2) --------------------------------------------------------


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """§2.2: ``api_request_id`` starts with ``req_``; the timestamp is ISO-8601 UTC."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_precision(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )


def assert_error_meta_is_minimal(body: Dict[str, Any]) -> None:
    """§2.2: the ``meta`` of an error carries only the two request fields."""
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )


def assert_object_response(body: Dict[str, Any]) -> None:
    assert body["response_type"] == "object", (
        f"expected response_type 'object', got {body['response_type']!r}"
    )


def assert_array_response(body: Dict[str, Any]) -> None:
    assert body["response_type"] == "array", (
        f"expected response_type 'array', got {body['response_type']!r}"
    )


def validate_unpaginated_list(response, expected_status: int = 200):
    """A list response whose ``meta`` need not carry the pagination quartet.

    Used for the array-shaped endpoints the PRD does not describe as paginated
    channels. Returns the data list.
    """
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert_array_response(body)
    data = body["data"]
    assert isinstance(data, list), f"expected an array in data, got {type(data)}"
    return data


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """§2.3: ``limit`` and ``offset`` as applied, ``total_count`` before the window."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_ordered_by(
    rows: List[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    """Assert a list arrived sorted on one field."""
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {field} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


def assert_id_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert the exact identifier sequence a list channel returned."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected id order {expected_ids}, got {actual}"


# --- Rounding disciplines (§2.7) -------------------------------------------


def assert_integer_cents(value: Any, label: str = "amount") -> None:
    """Money is integer cents, never a string and never a float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r} "
        f"({type(value).__name__})"
    )


def assert_two_decimal_places(value: Any, label: str = "value") -> None:
    """FTE quantities and the composite score are carried to two decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r}"
    )
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        f"{label} must be carried to two decimal places, got {value!r}"
    )


def assert_decimal_equals(actual: Any, expected: float, label: str = "value") -> None:
    """Compare a two-decimal figure without float noise."""
    assert actual is not None, f"{label} must not be null"
    assert Decimal(str(actual)) == Decimal(str(expected)), (
        f"{label}: expected {expected}, got {actual}"
    )


# --- Program-shaped assertions ---------------------------------------------


def assert_program_registration_defaults(program: Dict[str, Any]) -> None:
    """§2.7: the figures a newly registered program starts with."""
    assert program["lifecycle_state"] == "ACTIVE"
    assert program["catalog_status"] == "LISTED"
    assert program["snapshot_count"] == 0
    assert program["composite_score"] is None
    assert program["cost_per_credit_hour_rolling_cents"] is None
    assert program["cost_per_credit_hour_latest_cents"] is None
    assert program["viability_band"] == "INSUFFICIENT_DATA"
    assert program["discontinuation_override"] is False
    assert program["consolidated_into_program_id"] is None
    assert program["catalog_status_pre_decision"] is None
    for field in (
        "faculty_fte_baseline",
        "active_fte_total",
        "reassigned_fte_total",
        "separated_fte_total",
        "assigned_pool_fte",
        "retained_teach_out_fte",
        "reducible_fte",
        "deferred_fte",
    ):
        assert_decimal_equals(program[field], 0.00, f"program.{field}")


def assert_axes(
    program: Dict[str, Any],
    lifecycle_state: Optional[str] = None,
    catalog_status: Optional[str] = None,
) -> None:
    """§2.6: the two axes advance independently on the same row."""
    if lifecycle_state is not None:
        assert program["lifecycle_state"] == lifecycle_state, (
            f"lifecycle_state: expected {lifecycle_state}, "
            f"got {program['lifecycle_state']}"
        )
    if catalog_status is not None:
        assert program["catalog_status"] == catalog_status, (
            f"catalog_status: expected {catalog_status}, "
            f"got {program['catalog_status']}"
        )


def assert_viability(
    program: Dict[str, Any],
    rolling_cents: Optional[int],
    latest_cents: Optional[int],
    composite: Optional[float],
    band: str,
) -> None:
    """The four figures §3.1 and §3.2 derive from the rolling window."""
    assert program["cost_per_credit_hour_rolling_cents"] == rolling_cents, (
        f"cost_per_credit_hour_rolling_cents: expected {rolling_cents}, "
        f"got {program['cost_per_credit_hour_rolling_cents']}"
    )
    assert program["cost_per_credit_hour_latest_cents"] == latest_cents, (
        f"cost_per_credit_hour_latest_cents: expected {latest_cents}, "
        f"got {program['cost_per_credit_hour_latest_cents']}"
    )
    if composite is None:
        assert program["composite_score"] is None, (
            f"composite_score: expected null, got {program['composite_score']}"
        )
    else:
        assert_decimal_equals(program["composite_score"], composite, "composite_score")
    assert program["viability_band"] == band, (
        f"viability_band: expected {band}, got {program['viability_band']}"
    )


def assert_waterfall(
    program: Dict[str, Any],
    baseline: Optional[float] = None,
    assigned_pool: Optional[float] = None,
    retained: Optional[float] = None,
    reducible: Optional[float] = None,
    severance_cap_cents: Optional[int] = None,
    liability_cents: Optional[int] = None,
    deferred: Optional[float] = None,
    active: Optional[float] = None,
    reassigned: Optional[float] = None,
    separated: Optional[float] = None,
) -> None:
    """§3.11: the staffing reduction waterfall's outputs."""
    pairs = [
        ("faculty_fte_baseline", baseline),
        ("assigned_pool_fte", assigned_pool),
        ("retained_teach_out_fte", retained),
        ("reducible_fte", reducible),
        ("deferred_fte", deferred),
        ("active_fte_total", active),
        ("reassigned_fte_total", reassigned),
        ("separated_fte_total", separated),
    ]
    for field, expected in pairs:
        if expected is not None:
            assert_decimal_equals(program[field], expected, f"program.{field}")
    if severance_cap_cents is not None:
        assert program["severance_budget_cap_cents"] == severance_cap_cents, (
            f"severance_budget_cap_cents: expected {severance_cap_cents}, "
            f"got {program['severance_budget_cap_cents']}"
        )
    if liability_cents is not None:
        assert program["staffing_liability_cents"] == liability_cents, (
            f"staffing_liability_cents: expected {liability_cents}, "
            f"got {program['staffing_liability_cents']}"
        )


# --- Conserved quantities (§2.11) ------------------------------------------


def assert_seat_conservation(
    guarantees: List[Dict[str, Any]], students: List[Dict[str, Any]]
) -> None:
    """§2.11: committed seats on non-waived guarantees equal seats held by
    students who have not withdrawn."""
    supply = sum(
        g["seats_committed"] for g in guarantees if g["status"] != "WAIVED"
    )
    demand = sum(
        s["committed_seat_count"]
        for s in students
        if s["advising_status"] != "WITHDRAWN"
    )
    assert supply == demand, (
        f"seat conservation broken: guarantees hold {supply} committed seats "
        f"but students hold {demand}"
    )


def assert_fte_partition(program: Dict[str, Any], appointments: List[Dict[str, Any]]) -> None:
    """§2.11: the baseline is the sum over every appointment in any state, and the
    three buckets partition it."""
    baseline = sum(Decimal(str(a["fte"])) for a in appointments)
    assert Decimal(str(program["faculty_fte_baseline"])) == baseline, (
        f"faculty_fte_baseline: expected {baseline}, "
        f"got {program['faculty_fte_baseline']}"
    )
    active_states = {
        "ASSIGNED",
        "TEACH_OUT_RETAINED",
        "REASSIGNMENT_PROPOSED",
        "NOTICE_ISSUED",
    }
    active = sum(
        Decimal(str(a["fte"])) for a in appointments if a["state"] in active_states
    )
    reassigned = sum(
        Decimal(str(a["fte"])) for a in appointments if a["state"] == "REASSIGNED"
    )
    separated = sum(
        Decimal(str(a["fte"])) for a in appointments if a["state"] == "SEPARATED"
    )
    assert Decimal(str(program["active_fte_total"])) == active, (
        f"active_fte_total: expected {active}, got {program['active_fte_total']}"
    )
    assert Decimal(str(program["reassigned_fte_total"])) == reassigned, (
        f"reassigned_fte_total: expected {reassigned}, "
        f"got {program['reassigned_fte_total']}"
    )
    assert Decimal(str(program["separated_fte_total"])) == separated, (
        f"separated_fte_total: expected {separated}, "
        f"got {program['separated_fte_total']}"
    )
    assigned_pool = sum(
        Decimal(str(a["fte"])) for a in appointments if a["state"] == "ASSIGNED"
    )
    assert Decimal(str(program["assigned_pool_fte"])) == assigned_pool, (
        f"assigned_pool_fte: expected {assigned_pool}, "
        f"got {program['assigned_pool_fte']}"
    )


def assert_plan_ledger(
    plan: Dict[str, Any],
    guaranteed_seat_total: Optional[int] = None,
    committed_seat_total: Optional[int] = None,
    required_seat_total: Optional[int] = None,
    seat_shortfall: Optional[int] = None,
    at_risk_student_count: Optional[int] = None,
    open_student_count: Optional[int] = None,
    substituted_guarantee_count: Optional[int] = None,
    waived_guarantee_count: Optional[int] = None,
) -> None:
    """§3.9: the plan's derived seat and student aggregates."""
    pairs = [
        ("guaranteed_seat_total", guaranteed_seat_total),
        ("committed_seat_total", committed_seat_total),
        ("required_seat_total", required_seat_total),
        ("seat_shortfall", seat_shortfall),
        ("at_risk_student_count", at_risk_student_count),
        ("open_student_count", open_student_count),
        ("substituted_guarantee_count", substituted_guarantee_count),
        ("waived_guarantee_count", waived_guarantee_count),
    ]
    for field, expected in pairs:
        if expected is not None:
            assert plan[field] == expected, (
                f"plan.{field}: expected {expected}, got {plan[field]}"
            )


def assert_projection(
    student: Dict[str, Any],
    variant: str,
    terms_remaining: int,
    completion_term_index: Optional[int],
    at_risk: bool,
    required_seat_count: Optional[int] = None,
) -> None:
    """§3.10: the projection a student's advising status selects."""
    assert student["projection_variant"] == variant, (
        f"projection_variant: expected {variant}, got {student['projection_variant']}"
    )
    assert student["projected_terms_remaining"] == terms_remaining, (
        f"projected_terms_remaining: expected {terms_remaining}, "
        f"got {student['projected_terms_remaining']}"
    )
    assert student["projected_completion_term_index"] == completion_term_index, (
        f"projected_completion_term_index: expected {completion_term_index}, "
        f"got {student['projected_completion_term_index']}"
    )
    assert student["at_risk"] is at_risk, (
        f"at_risk: expected {at_risk}, got {student['at_risk']}"
    )
    if required_seat_count is not None:
        assert student["required_seat_count"] == required_seat_count, (
            f"required_seat_count: expected {required_seat_count}, "
            f"got {student['required_seat_count']}"
        )
