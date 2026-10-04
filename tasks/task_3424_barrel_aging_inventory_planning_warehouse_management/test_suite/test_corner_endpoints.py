"""Corner-design translations: response envelopes, deterministic listings,
filters, and foreign-key reverse lookups (PRD §2.2, §2.3, §3.1, §3.2, §3.5).
"""
import re

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    NON_EXISTENT_UUID,
    add_component,
    create_blend_batch,
    create_commissioned_rickhouse,
    create_label_payload,
    create_program,
    create_report,
    create_reservation,
    dump_barrel,
    fill_mature_barrel,
    fill_placed_barrel,
    get_success_data,
    record_evaporation_reading,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_REQUEST_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_success_envelope_has_meta_and_object_type(api, warehouse_manager_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/success_envelope_has_meta_and_object_type
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-P1",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])

    resp = api.get_barrel(barrel["id"], warehouse_manager_headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert _REQUEST_TIMESTAMP_RE.match(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be ISO 8601 UTC with three fractional digits, "
        f"got {meta.get('api_request_timestamp')!r}"
    )
    assert body["response_type"] == "object", "a single-resource read is response_type 'object'"
    assert body["data"]["id"] == barrel["id"]


def test_error_envelope_has_error_id_and_message(api, warehouse_manager_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.8: "Each identifier in the path must resolve to an existing resource
    before the next is examined, and the request is rejected with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve."

    Design: Corner/endpoints/error_envelope_has_error_id_and_message
    """
    set_clock(DEFAULT_CLOCK_ISO)

    resp = api.get_barrel(NON_EXISTENT_UUID, warehouse_manager_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data["error_id"] == "ERR_NOT_FOUND"

    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the error envelope's meta carries only api_request_id and api_request_timestamp"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip(), (
        "data.message must be a non-empty string"
    )


def test_slots_listed_in_floor_row_position_order(api, platform_admin_headers):
    """PRD §3.1: "the full slot grid materializes — exactly the product of
    `floors`, `rows_per_floor`, and `positions_per_row` slots, one per
    combination, enumerated in `floor_index`, then `row_index`, then
    `position_index` ascending order, each index 1-based with `floor_index` 1
    at ground level".
    PRD §3.1: "A rickhouse's slot listing always returns this deterministic
    floor-row-position order."
    PRD §3.1: "exactly 1.00 on the ground floor, 1.05 on the second floor,
    1.10 on the third, and so on."

    Design: Corner/endpoints/slots_listed_in_floor_row_position_order
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=2, positions_per_row=2, name="RH-P3",
    )
    rickhouse_id = ctx["rickhouse"]["id"]

    resp = api.list_rickhouse_slots(rickhouse_id, platform_admin_headers)
    slots, _meta = validate_paginated(resp)

    assert len(slots) == 4, "1 x 2 x 2 grid materializes exactly 4 slots"
    order = [(s["floor_index"], s["row_index"], s["position_index"]) for s in slots]
    assert order == [(1, 1, 1), (1, 1, 2), (1, 2, 1), (1, 2, 2)], (
        f"slot listing must follow floor-row-position ascending order, got {order}"
    )
    for slot in slots:
        assert slot["heat_factor"] == pytest.approx(1.00), (
            "every slot in this grid is on floor 1, so heat_factor is exactly 1.00"
        )


def test_barrels_filtered_by_maturation_status(api, warehouse_manager_headers):
    """PRD §2.3: "Individual list endpoints accept optional filter parameters
    that narrow the result set to exact matches: `expansion_project_id` and
    `posture` on the rickhouse list; `status` on the occupancy lists;
    `maturation_status`, `custody_status`, and `spirit_type` on the barrel
    list; `state` on the barrel-reservation, blend-batch, program-reservation,
    and bonded-report lists; `kind` on the assessment list; and `label_id` on
    the blend-batch list."
    PRD §3.3: "The two evolve independently with a single join gate —
    withdrawal demands the barrel be `DUMPED` first (§3.4)."

    Design: Corner/endpoints/barrels_filtered_by_maturation_status
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-P4",
    )
    barrel_1 = fill_placed_barrel(
        ctx["slots"][0]["id"], fill_volume_liters=100.0, min_maturation_months=12,
    )
    barrel_2 = fill_placed_barrel(
        ctx["slots"][1]["id"], fill_volume_liters=100.0, min_maturation_months=12,
    )
    dumped = dump_barrel(barrel_1["id"])
    assert dumped["maturation_status"] == "DUMPED"

    dumped_data, dumped_meta = validate_paginated(
        api.list_barrels(warehouse_manager_headers, params={"maturation_status": "DUMPED"})
    )
    assert dumped_meta["total_count"] == 1
    assert [b["id"] for b in dumped_data] == [barrel_1["id"]], (
        "the DUMPED filter returns exactly the dumped barrel"
    )

    bonded_data, bonded_meta = validate_paginated(
        api.list_barrels(warehouse_manager_headers, params={"custody_status": "BONDED"})
    )
    assert bonded_meta["total_count"] == 2, (
        "dumping moves maturation only; both barrels remain BONDED in custody"
    )
    assert {b["id"] for b in bonded_data} == {barrel_1["id"], barrel_2["id"]}


def test_blend_components_reverse_lookup(api, master_blender_headers):
    """PRD §3.5: "Each component records its `blend_batch_id`, and a batch's
    components list in `created_at` ascending order."
    PRD §4: "| GET | `/barrel-aging/blend-batches/{id}/components` | List a
    batch's components | Any |"
    PRD §4: "| GET | `/barrel-aging/barrels/{id}/blend-components` | List blend
    components referencing this barrel | Any |"

    Design: Corner/endpoints/blend_components_reverse_lookup
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-P5",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Reverse Lookup", age_statement_years=1, spirit_type="BOURBON"),
            master_blender_headers,
        )
    )
    batch = create_blend_batch(label["id"], "2030-09-01T00:00:00Z")
    component = add_component(batch["id"], barrel["id"], 10.0)

    batch_side, _meta = validate_paginated(
        api.list_blend_components(batch["id"], master_blender_headers)
    )
    assert len(batch_side) == 1, "the batch carries exactly one component"
    assert batch_side[0]["id"] == component["id"]
    assert batch_side[0]["barrel_id"] == barrel["id"]
    assert batch_side[0]["drawn_volume_liters"] == pytest.approx(10.00, abs=0.01)

    barrel_side, _meta = validate_paginated(
        api.list_barrel_blend_components(barrel["id"], master_blender_headers)
    )
    assert len(barrel_side) == 1, "the barrel is referenced by exactly one component"
    assert barrel_side[0]["id"] == component["id"], (
        "both directions resolve to the same component record"
    )
    assert barrel_side[0]["blend_batch_id"] == batch["id"]


def test_single_resource_retrieval_reads(
    api, distillery_planner_headers, master_blender_headers, warehouse_manager_headers,
):
    """PRD §3.1: "Approval stamps `approved_at` with the current logical clock,
    increments the project's `version`, and cascades: a rickhouse is created in
    `PLANNED` posture with `name`, `region_code`, `floors`, `rows_per_floor`,
    and `positions_per_row` copied from the project, its `expansion_project_id`
    pointing back to the project that spawned it."
    PRD §3.1: "Commissioning stamps `commissioned_at`, increments the project's
    `version`, moves the project to its terminal `COMMISSIONED` state, and
    fires a multi-part cascade".
    PRD §3.5: "A new label is `REGISTERED`; activation by a `MasterBlender`
    moves it `REGISTERED` → `ACTIVE` and increments its `version`."
    PRD §3.1: "exactly 1.00 on the ground floor, 1.05 on the second floor,
    1.10 on the third, and so on."

    Design: Corner/endpoints/single_resource_retrieval_reads
    """
    ctx = create_commissioned_rickhouse(
        floors=2, rows_per_floor=1, positions_per_row=1, name="RH-P6",
        region_code="TN", planned_annual_distillation_liters=70000,
    )
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Read Me", age_statement_years=6, spirit_type="SINGLE_MALT"),
            master_blender_headers,
        )
    )

    project = validate_success(
        api.get_expansion_project(ctx["project"]["id"], distillery_planner_headers)
    )
    assert project["state"] == "COMMISSIONED"
    assert project["planned_annual_distillation_liters"] == 70000
    # Lifecycle stamps record the logical clock at the moment of the call:
    # approval happened at the startup clock 2026-09-01, commissioning once
    # the 24-month (720-day) lag had elapsed, i.e. 2028-08-21 (PRD §2.4
    # calendar arithmetic). PRD pins the stamped instant, not the exact
    # serialization, so the day is asserted.
    assert project["approved_at"] is not None
    assert project["approved_at"].startswith("2026-09-01"), (
        f"approved_at must stamp the approval-day clock, got {project['approved_at']!r}"
    )
    assert project["commissioned_at"] is not None
    assert project["commissioned_at"].startswith("2028-08-21"), (
        "commissioned_at must stamp the commission-day clock "
        f"(approved_at + 24 x 30 days), got {project['commissioned_at']!r}"
    )

    label_read = validate_success(api.get_label(label["id"], master_blender_headers))
    assert label_read["state"] == "REGISTERED"
    assert label_read["age_statement_years"] == 6

    floor_2_slot = ctx["slots"][1]  # 2x1x1 grid lists floor 1 first, floor 2 second
    slot_read = validate_success(
        api.get_warehouse_slot(floor_2_slot["id"], warehouse_manager_headers)
    )
    assert slot_read["id"] == floor_2_slot["id"]
    assert slot_read["floor_index"] == 2
    assert slot_read["heat_factor"] == pytest.approx(1.05), (
        "the second-floor slot computes heat_factor 1.05"
    )


def test_filtered_lists_and_reverse_lookups(
    api, warehouse_manager_headers, master_blender_headers,
    program_director_headers, bonded_preparer_headers,
):
    """PRD §2.3: "Individual list endpoints accept optional filter parameters
    that narrow the result set to exact matches: `expansion_project_id` and
    `posture` on the rickhouse list; `status` on the occupancy lists;
    `maturation_status`, `custody_status`, and `spirit_type` on the barrel
    list; `state` on the barrel-reservation, blend-batch, program-reservation,
    and bonded-report lists; `kind` on the assessment list; and `label_id` on
    the blend-batch list."
    PRD §3.2: "The system opens a slot occupancy on the named slot with
    `move_reason` `INITIAL_FILL`, stamping `start_at` with the current clock
    and leaving `end_at` null — a null `end_at` is exactly what makes an
    occupancy's `status` `OPEN` rather than `CLOSED`, and occupancy intervals
    are half-open: `start_at` inclusive, `end_at` exclusive."

    Design: Corner/endpoints/filtered_lists_and_reverse_lookups
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-P7",
    )
    slot = ctx["slots"][0]
    barrel = fill_mature_barrel(slot["id"])
    reading = record_evaporation_reading(barrel["id"], 199.0)
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Filter Me", age_statement_years=1, spirit_type="BOURBON"),
            master_blender_headers,
        )
    )
    batch = create_blend_batch(label["id"], "2030-09-01T00:00:00Z")
    program = create_program(
        name="Reverse Me", min_quality_score=0,
        required_barrel_count=1, reservation_window_days=45,
    )
    reservation = create_reservation(program["id"], barrel["id"])
    report = create_report("2028-08-01T00:00:00Z", "2028-12-01T00:00:00Z")

    occupancies, _meta = validate_paginated(
        api.list_slot_occupancies(slot["id"], warehouse_manager_headers)
    )
    assert len(occupancies) == 1, "the slot holds exactly one occupancy"
    assert occupancies[0]["barrel_id"] == barrel["id"]
    assert occupancies[0]["status"] == "OPEN"
    assert occupancies[0]["move_reason"] == "INITIAL_FILL"

    assessments, _meta = validate_paginated(
        api.list_barrel_assessments(barrel["id"], warehouse_manager_headers)
    )
    assert len(assessments) == 1
    assert assessments[0]["id"] == reading["id"]
    assert assessments[0]["kind"] == "EVAPORATION_READING"
    assert assessments[0]["measured_volume_liters"] == pytest.approx(199.00, abs=0.01)

    reservations, _meta = validate_paginated(
        api.list_barrel_reservations(barrel["id"], program_director_headers)
    )
    assert len(reservations) == 1
    assert reservations[0]["id"] == reservation["id"]
    assert reservations[0]["state"] == "ACTIVE"

    batches, _meta = validate_paginated(
        api.list_blend_batches(master_blender_headers, params={"label_id": label["id"]})
    )
    assert [b["id"] for b in batches] == [batch["id"]], (
        "the label_id filter returns exactly the batch proposed under that label"
    )

    reports, _meta = validate_paginated(
        api.list_bonded_reports(bonded_preparer_headers, params={"state": "OPEN"})
    )
    assert [r["id"] for r in reports] == [report["id"]], (
        "the state=OPEN filter returns exactly the open report"
    )
