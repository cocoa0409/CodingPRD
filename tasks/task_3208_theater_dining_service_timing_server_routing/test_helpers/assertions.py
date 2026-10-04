"""Entity assertions and domain invariant checkers.

Generic format helpers come from the framework; the field-level contracts and
the cross-field invariants below are this domain's own.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

from .types import (
    AuditoriumStatus, BuildPhase, ShowtimeStatus, ShowtimeMode, ServiceMode,
    ProgrammingEventStatus, PreShowContentStatus, MenuChannel, AvailabilityState,
    ServerRosterStatus, SectionAssignmentStatus, OrderSlipStatus, IdCheckStatus,
    KitchenStation, KitchenTicketStatus, CheckTabStatus, DisturbanceStage,
)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert _is_int(data.get("version")), f"version must be an integer, got {data.get('version')!r}"


def assert_money(value, field_name: str = "cents"):
    """Money is counted in integer cents and nowhere else (PRD §2.8)."""
    assert _is_int(value), f"{field_name} must be an integer number of cents, got {value!r}"
    assert_cost_precision(float(value), 0)


def assert_auditorium(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"], "name must be non-empty"
    assert _is_int(data["seat_capacity"]) and data["seat_capacity"] >= 1, (
        "seat_capacity must be an integer >= 1"
    )
    assert data["status"] in [s.value for s in AuditoriumStatus], (
        f"status must be LIVE|TURNOVER|DARK, got {data.get('status')!r}"
    )
    assert data["service_posture"] in [s.value for s in AuditoriumStatus], (
        f"service_posture must mirror status, got {data.get('service_posture')!r}"
    )
    assert data["build_phase"] in [p.value for p in BuildPhase], (
        f"build_phase must be EMPTY|SETUP|NEARLY_READY|READY, got {data.get('build_phase')!r}"
    )
    assert _is_int(data["kitchen_point_rate"]) and data["kitchen_point_rate"] >= 1
    assert _is_int(data["alcove_point_rate"]) and data["alcove_point_rate"] >= 1


def assert_showtime(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ShowtimeStatus], (
        f"status must be a declared showtime status, got {data.get('status')!r}"
    )
    assert data["mode"] in [m.value for m in ShowtimeMode], (
        f"mode must be DINING_OPEN|DINING_CLOSED, got {data.get('mode')!r}"
    )
    assert data["service_mode"] in [m.value for m in ServiceMode], (
        f"service_mode must be PRE_SHOW|IN_KITCHEN|DARK_PERIOD, got {data.get('service_mode')!r}"
    )
    assert data["content_type"] in ("STANDARD", "SPECIAL_EVENT")
    assert _is_int(data["runtime_minutes"]) and data["runtime_minutes"] >= 1
    for field in ("dining_open_at_utc", "entree_ready_deadline_utc", "dining_close_at_utc"):
        assert is_iso8601_timestamp(data[field]), f"{field} must be an ISO 8601 instant"


def assert_programming_event(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ProgrammingEventStatus]
    assert data["pre_show_content_status"] in [s.value for s in PreShowContentStatus]
    assert _is_int(data["pre_show_content_version"]) and data["pre_show_content_version"] >= 1
    assert _is_int(data["themed_menu_count"]) and data["themed_menu_count"] >= 0
    assert isinstance(data["requires_themed_menu"], bool)


def assert_menu_item(data: dict):
    _assert_common_fields(data)
    assert data["channel"] in [c.value for c in MenuChannel]
    assert data["availability_state"] in [a.value for a in AvailabilityState]
    assert _is_int(data["price_cents"]) and data["price_cents"] >= 0
    assert _is_int(data["prep_minutes"]) and data["prep_minutes"] >= 1
    assert isinstance(data["is_alcoholic"], bool)


def assert_themed_menu_item(data: dict):
    """A themed menu item is a priced attachment: id + created_at only."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert _is_int(data["theme_price_cents"]) and data["theme_price_cents"] >= 0
    assert isinstance(data["is_signature"], bool)
    assert "updated_at" not in data, "a themed menu item carries no updated_at"
    assert "version" not in data, "a themed menu item carries no version"


def assert_server(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert is_valid_uuid(data["home_auditorium_id"])
    assert isinstance(data["ratings"], list)
    assert _is_int(data["lifetime_points"])
    assert isinstance(data["in_rotation"], bool)
    assert data["status"] in [s.value for s in ServerRosterStatus], (
        f"status must be ACTIVE|PENALIZED, got {data.get('status')!r}"
    )
    for field in ("shift_load_projected", "shift_load_final", "rollup_provisional_cents"):
        assert _is_int(data[field]), f"{field} must be an integer"


def assert_section_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in SectionAssignmentStatus]
    assert is_valid_uuid(data["showtime_id"])
    assert is_valid_uuid(data["auditorium_id"])
    assert is_valid_uuid(data["server_id"])
    assert isinstance(data["section_label"], str) and data["section_label"]
    assert _is_int(data["assignment_points"])


def assert_order_slip(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in OrderSlipStatus]
    assert data["channel"] in [c.value for c in MenuChannel]
    assert data["placement_mode"] in ("PRE_SHOW", "SILENT")
    assert data["id_check_status"] in [s.value for s in IdCheckStatus]
    assert isinstance(data["id_check_required"], bool)
    assert isinstance(data["resolved_lines"], list)
    assert _is_int(data["seat_number"]) and data["seat_number"] >= 1
    assert_money(data["subtotal_cents"], "subtotal_cents")


def assert_order_slip_id_axis_consistency(data: dict):
    """The identification flag and status must agree (PRD §3.3)."""
    if data["id_check_required"]:
        assert data["id_check_status"] != IdCheckStatus.NOT_REQUIRED.value, (
            "an alcohol-bearing slip cannot be NOT_REQUIRED"
        )
    else:
        assert data["id_check_status"] == IdCheckStatus.NOT_REQUIRED.value, (
            "a slip with no alcoholic line must read NOT_REQUIRED"
        )


def assert_kitchen_ticket(data: dict):
    _assert_common_fields(data)
    assert data["station"] in [s.value for s in KitchenStation]
    assert data["status"] in [s.value for s in KitchenTicketStatus]
    assert _is_int(data["point_cost"]) and data["point_cost"] >= 0
    assert _is_int(data["sequence_position"]) and data["sequence_position"] >= 0
    assert isinstance(data["allergen_substitution"], bool)
    assert is_iso8601_timestamp(data["fire_at_utc"])
    assert is_iso8601_timestamp(data["projected_delivery_at_utc"])


def assert_check_tab(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in CheckTabStatus]
    assert_money(data["original_cents"], "original_cents")
    assert_money(data["refunded_cents"], "refunded_cents")
    assert data["original_cents"] >= 0
    assert data["refunded_cents"] >= 0
    reason = data.get("reason_code")
    assert reason in (
        "EJECTION_NO_TALKING", "EJECTION_NO_TEXTING",
        "SERVICE_COMP_FAILURE", "SERVICE_DELAY", None,
    ), f"reason_code must be a declared refund reason or null, got {reason!r}"


def assert_disturbance_event(data: dict):
    """A disturbance report is append-only: id + created_at, plus stage_version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["kind"] in ("NO_TALKING", "NO_TEXTING")
    assert data["stage"] in [s.value for s in DisturbanceStage]
    assert _is_int(data["stage_version"]) and data["stage_version"] >= 1
    assert is_iso8601_timestamp(data["occurred_at_utc"])
    assert "updated_at" not in data, "a disturbance report carries no updated_at"
    assert "version" not in data, "a disturbance report carries no version"


# ─── Domain invariants ────────────────────────────────────────────────

def assert_check_tab_zero_balance_invariant(data: dict):
    """When a refund completes, original_cents - refunded_cents is exactly zero."""
    if data["status"] == CheckTabStatus.REFUNDED.value:
        assert data["original_cents"] - data["refunded_cents"] == 0, (
            "a REFUNDED tab must settle at exactly zero, "
            f"got {data['original_cents']} - {data['refunded_cents']}"
        )
    assert data["refunded_cents"] <= data["original_cents"], (
        "a refund may never push refunded_cents above original_cents"
    )


def assert_capacity_snapshot(data: dict):
    """The read model's own shape, with the bands on their declared vocabulary."""
    assert data["capacity_band"] in ("NORMAL", "LATE", "BLOCKED"), (
        f"capacity_band must be NORMAL|LATE|BLOCKED, got {data.get('capacity_band')!r}"
    )
    assert data["projection_variant"] in ("wave_projection", "final_projection"), (
        f"projection_variant must declare which projection ran, got {data.get('projection_variant')!r}"
    )
    assert _is_int(data["entree_load_points"])
    assert _is_int(data["beverage_load_points"])
    assert _is_int(data["load_pct"])
    assert _is_int(data["entry_stage"]) and data["entry_stage"] >= 0


def assert_server_rollup_invariant(data: dict):
    """A server's provisional rollup is a sum of non-negative tab figures."""
    assert data["rollup_provisional_cents"] >= 0, (
        "rollup_provisional_cents is a sum of original_cents values and cannot be negative"
    )


def assert_fire_budget_invariant(tickets: list, kitchen_point_rate: int,
                                 entree_fire_at: str) -> None:
    """sum(ceil(point_cost / rate)) == last_fire_at_utc - ENTRÉE_FIRE_AT (PRD §3.5).

    Only tickets still occupying a position (QUEUED or PREPARING) count.
    """
    import math
    from datetime import datetime, timedelta

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    cohort = [
        t for t in tickets
        if t["status"] in (KitchenTicketStatus.QUEUED.value, KitchenTicketStatus.PREPARING.value)
    ]
    if not cohort:
        return
    total_minutes = sum(math.ceil(t["point_cost"] / kitchen_point_rate) for t in cohort)

    anchor = datetime.strptime(entree_fire_at, fmt)
    final = max(cohort, key=lambda t: t["fire_at_utc"])
    completion = datetime.strptime(final["fire_at_utc"], fmt) + timedelta(
        minutes=math.ceil(final["point_cost"] / kitchen_point_rate)
    )
    span_minutes = (completion - anchor).total_seconds() / 60
    assert span_minutes == total_minutes, (
        "fire capacity was created or destroyed: "
        f"the cohort costs {total_minutes} line minutes but the span from the "
        f"anchor to the final member's completion is {span_minutes}"
    )