"""Endpoint contracts: envelopes, paging windows, filters and the logical clock.

Each test drives one collection or one computed read through the surface the PRD
declares for it — the pagination window and its meta block, the append and
activation guards on a template revision, the zero shapes of the computed reads on
an empty input set, the mutually exclusive requisition links, the acknowledge
fan-out, and the clock endpoint that re-opens the daily inspection requirement.
"""

import pytest

from test_helpers import (
    ADMIN,
    MANAGER,
    OPERATOR,
    TECHNICIAN,
    api_client,
    assert_bulletin,
    assert_bulletin_action,
    assert_bulletin_risk_shape,
    assert_capacity_impact_shape,
    assert_checklist_item,
    assert_daily_inspection,
    assert_instant_equals,
    assert_inspection_template,
    assert_object_envelope,
    assert_part_requisition,
    assert_shop_bay,
    factories,
    fixtures,
    make_maintenance_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"
CLOCK_START_DATE = "2026-08-01"


def test_the_bay_list_pages_in_created_at_order_and_refuses_a_limit_of_zero():
    """PRD §2.3: "`limit` caps the number of rows returned; when it is omitted it
    defaults to 10, and a supplied value must be at least 1 and at most 100."

    Design: Corner/endpoints/shop_bay_list_honours_limit_offset_and_reports_total_count_and_has_more
    """
    alpha = fixtures.create_shop_bay("Bay Alpha", 1)
    bravo = fixtures.create_shop_bay("Bay Bravo", 2)
    charlie = fixtures.create_shop_bay("Bay Charlie", 3)

    first_page, first_meta = validate_paginated(
        api_client.list_shop_bays(MANAGER, params={"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in first_page] == [alpha["id"], bravo["id"]], (
        "shop bays are ordered by created_at ascending"
    )
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3, (
        "total_count counts every row matching the filters before pagination"
    )
    assert first_meta["has_more"] is True, "one row remains beyond the first page"

    second_page, second_meta = validate_paginated(
        api_client.list_shop_bays(MANAGER, params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in second_page] == [charlie["id"]]
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "the page ends on the last row"

    defaulted, default_meta = validate_paginated(api_client.list_shop_bays(MANAGER))
    assert [row["id"] for row in defaulted] == [
        alpha["id"],
        bravo["id"],
        charlie["id"],
    ]
    assert default_meta["limit"] == 10, "limit defaults to 10 when omitted"
    assert default_meta["offset"] == 0, "offset defaults to 0 when omitted"
    assert default_meta["total_count"] == 3
    assert default_meta["has_more"] is False

    validate_error(
        api_client.list_shop_bays(MANAGER, params={"limit": 0}),
        "ERR_INVALID_REQUEST",
        400,
    )

    read_back = validate_success(api_client.get_shop_bay(bravo["id"], MANAGER))
    assert_shop_bay(read_back)
    assert read_back["name"] == "Bay Bravo"
    assert read_back["concurrent_slot_capacity"] == 2
    assert read_back["booked_order_count"] == 0, "no work order has booked this bay"
    assert read_back["version"] == 1


def test_an_active_revision_refuses_further_lines_and_a_second_activation():
    """PRD §3.1: "Checklist lines are appended to a revision one at a time, and only
    while that revision is still `DRAFT` — appending to a revision that is `ACTIVE` or
    `SUPERSEDED` is refused with `ERR_TEMPLATE_STATE_INVALID`."

    Design: Corner/endpoints/active_template_refuses_item_appends_and_reactivation_while_sequence_numbers_stay_unique_per_template
    """
    attraction = fixtures.create_attraction(
        name="Template Guard Ride",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="TG-1",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=400,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    live = fixtures.create_template(
        attraction["id"], effective_from_date=CLOCK_START_DATE
    )
    first_line = fixtures.append_line(
        live["id"],
        1,
        severity_class="ESSENTIAL",
        description="Check air pressure at the brake",
    )
    fixtures.activate_template(live["id"], attraction["id"])
    draft = fixtures.create_template(attraction["id"], effective_from_date="2026-09-01")

    validate_error(
        api_client.append_checklist_item(
            live["id"],
            factories.append_checklist_item_payload(
                2, "Check the chain lift tension", "ADVISORY"
            ),
            ADMIN,
        ),
        "ERR_TEMPLATE_STATE_INVALID",
        409,
    )
    live_after_refusal = validate_success(
        api_client.get_inspection_template(live["id"], ADMIN)
    )
    assert_inspection_template(live_after_refusal)
    assert live_after_refusal["status"] == "ACTIVE"
    assert live_after_refusal["item_count"] == 1, "the refused append moved no counter"

    current = fixtures.read_attraction(attraction["id"])
    validate_error(
        api_client.activate_inspection_template(
            live["id"],
            factories.activate_inspection_template_payload(current["version"]),
            ADMIN,
        ),
        "ERR_TEMPLATE_STATE_INVALID",
        409,
    )
    assert fixtures.read_attraction(attraction["id"])["active_template_id"] == live[
        "id"
    ], "the pointer still names the revision that was already live"

    second_line = validate_success(
        api_client.append_checklist_item(
            draft["id"],
            factories.append_checklist_item_payload(
                1,
                "Verify restraint release handle",
                "SAFETY_CRITICAL",
                requires_photo=True,
            ),
            ADMIN,
        ),
        201,
    )
    assert_checklist_item(second_line)
    assert second_line["template_id"] == draft["id"]
    assert second_line["sequence_no"] == 1, (
        "sequence numbers are unique within a template, not across the attraction"
    )
    assert second_line["severity_class"] == "SAFETY_CRITICAL"
    assert second_line["requires_photo"] is True, (
        "the documentation flag is carried onto the result row as supplied"
    )

    validate_error(
        api_client.append_checklist_item(
            draft["id"],
            factories.append_checklist_item_payload(
                1, "Duplicate walk order", "ADVISORY"
            ),
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    draft_after = validate_success(
        api_client.get_inspection_template(draft["id"], ADMIN)
    )
    assert draft_after["status"] == "DRAFT"
    assert draft_after["item_count"] == 1, "the duplicate sequence number was rejected"

    assert (
        validate_success(api_client.get_checklist_item(first_line["id"], ADMIN))[
            "requires_photo"
        ]
        is False
    ), "requires_photo defaults to false when omitted"


def test_the_three_computed_reads_report_declared_zeroes_on_an_empty_input_set():
    """PRD §3.6: "When the evaluated set is empty, both scores are 0.00 and
    `divergence` is 0.00."

    Design: Corner/endpoints/computed_reads_return_declared_zero_shapes_on_empty_input_sets
    """
    attraction = fixtures.create_attraction(
        name="Empty Set Ride",
        park_area="KIDS_COVE",
        manufacturer="Chance",
        model_code="ES-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=600,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    bulletin = fixtures.create_bulletin(
        "BR-EMPTY-1",
        manufacturer="Chance",
        model_code="ZZ-9",
        severity="MANDATORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-10-01",
    )

    capacity_response = api_client.get_capacity_impact(attraction["id"], MANAGER)
    assert_object_envelope(capacity_response)
    capacity = validate_success(capacity_response)
    assert_capacity_impact_shape(capacity)
    assert capacity["attraction_id"] == attraction["id"]
    assert capacity["window_start_date"] == CLOCK_START_DATE
    assert capacity["window_end_date"] == CLOCK_START_DATE
    assert capacity["event_count"] == 0, "no downtime event has ever been opened"
    assert capacity["settled_guest_slots_lost"] == pytest.approx(0.00, abs=0.01)
    assert capacity["provisional_guest_slots_lost"] == pytest.approx(0.00, abs=0.01)
    assert capacity["divergence_guest_slots"] == pytest.approx(0.00, abs=0.01)

    readiness_response = api_client.get_dispatch_readiness(attraction["id"], OPERATOR)
    assert_object_envelope(readiness_response)
    readiness = validate_success(readiness_response)
    assert readiness["attraction_id"] == attraction["id"]
    assert readiness["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert readiness["certified_operator_count"] == 0
    assert readiness["essential_fail_count"] == 0
    assert readiness["dispatch_readiness_index"] == pytest.approx(0.00, abs=0.01), (
        "the certified set is empty so no division is attempted"
    )

    risk_response = api_client.get_bulletin_risk(bulletin["id"], MANAGER)
    assert_object_envelope(risk_response)
    risk = validate_success(risk_response)
    assert_bulletin_risk_shape(risk)
    assert risk["bulletin_id"] == bulletin["id"]
    assert risk["evaluated_action_count"] == 0, "the bulletin was never acknowledged"
    assert risk["deferred_action_count"] == 0
    assert risk["fleet_aggregate_score"] == pytest.approx(0.00, abs=0.01)
    assert risk["per_unit_max_score"] == pytest.approx(0.00, abs=0.01)
    assert risk["divergence"] == pytest.approx(0.00, abs=0.01)

    stored = validate_success(api_client.get_bulletin(bulletin["id"], MANAGER))
    assert_bulletin(stored)
    assert stored["status"] == "ISSUED", "a computed read persists nothing"
    assert stored["action_total_count"] == 0


def test_a_requisition_takes_one_link_at_most_and_only_from_its_own_attraction():
    """PRD §3.5: "Supplying both on the same request is refused with
    `ERR_INVALID_REQUEST`, and so is supplying a `downtime_event_id` or
    `bulletin_action_id` that belongs to a different attraction than the requisition's
    own `attraction_id`."

    Design: Corner/endpoints/requisition_link_fields_are_mutually_exclusive_and_must_share_the_attraction
    """
    own = fixtures.create_attraction(
        name="Link Ride A",
        park_area="FRONTIER",
        manufacturer="Chance",
        model_code="RQ-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    other = fixtures.create_attraction(
        name="Link Ride B",
        park_area="FRONTIER",
        manufacturer="Mack",
        model_code="RQ-2",
        ride_class="WATER",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    own_event = fixtures.open_downtime(
        own["id"], started_at="2026-08-01T09:00:00.000Z", cause_category="MECHANICAL"
    )
    foreign_event = fixtures.open_downtime(
        other["id"], started_at="2026-08-01T09:30:00.000Z", cause_category="ELECTRICAL"
    )
    bulletin = fixtures.create_bulletin(
        "BR-LINK-1",
        manufacturer="Chance",
        model_code="RQ-1",
        severity="MANDATORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-10-01",
    )
    fixtures.acknowledge_bulletin(bulletin["id"])
    action = fixtures.list_bulletin_actions(bulletin["id"])[0]
    assert action["attraction_id"] == own["id"]

    validate_error(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(
                own["id"],
                quantity=2,
                unit_cost_cents=150000,
                part_number="PN-BOTH",
                downtime_event_id=own_event["id"],
                bulletin_action_id=action["id"],
            ),
            TECHNICIAN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(
                own["id"],
                quantity=2,
                unit_cost_cents=150000,
                part_number="PN-FOREIGN",
                downtime_event_id=foreign_event["id"],
            ),
            TECHNICIAN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    _, refusal_meta = validate_paginated(
        api_client.list_part_requisitions(MANAGER, params={"attraction_id": own["id"]})
    )
    assert refusal_meta["total_count"] == 0, "neither refusal created a row"

    requisition = validate_success(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(
                own["id"],
                quantity=2,
                unit_cost_cents=150000,
                part_number="PN-OK",
                downtime_event_id=own_event["id"],
            ),
            TECHNICIAN,
        ),
        201,
    )
    assert_part_requisition(requisition)
    assert requisition["status"] == "REQUESTED"
    assert requisition["total_cost_cents"] == 300000
    assert requisition["downtime_event_id"] == own_event["id"]
    assert requisition["bulletin_action_id"] is None, "a requisition may carry one link"
    assert (
        fixtures.read_attraction(own["id"])["parts_budget_committed_cents"] == 0
    ), "nothing is committed while a requisition is merely REQUESTED"

    reserved = validate_success(
        api_client.reserve_part_requisition(requisition["id"], MANAGER)
    )
    assert reserved["status"] == "RESERVED"
    assert (
        fixtures.read_attraction(own["id"])["parts_budget_committed_cents"] == 300000
    )

    linked, linked_meta = validate_paginated(
        api_client.list_part_requisitions(
            MANAGER, params={"downtime_event_id": own_event["id"]}
        )
    )
    assert linked_meta["total_count"] == 1
    assert [row["id"] for row in linked] == [requisition["id"]]

    assert_bulletin_action(action)
    assert (
        validate_success(api_client.get_bulletin_action(action["id"], MANAGER))[
            "required_part_received"
        ]
        is True
    ), "no requisition references this action, so the flag reads true"


def test_acknowledging_fans_out_to_the_matching_manufacturer_and_model_only():
    """PRD §3.6: "Acknowledgement stamps `acknowledged_at` with the current logical
    clock instant and `acknowledged_by_user_id` with the acting badge, and then fans
    out: the server creates one fleet action with `status` `PENDING` for **every**
    attraction whose `manufacturer` equals the bulletin's `manufacturer` and whose
    `model_code` equals the bulletin's `model_code` — both must match — creating them
    in order of the attractions' `created_at` ascending."

    Design: Corner/endpoints/bulletin_acknowledge_fans_out_only_to_the_matching_manufacturer_and_model
    """
    kiddie = fixtures.create_attraction(
        name="Fanout Kiddie",
        park_area="KIDS_COVE",
        manufacturer="Chance",
        model_code="BK-1",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=300,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    family = fixtures.create_attraction(
        name="Fanout Family",
        park_area="KIDS_COVE",
        manufacturer="Chance",
        model_code="BK-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=500,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    outsider = fixtures.create_attraction(
        name="Fanout Outsider",
        park_area="KIDS_COVE",
        manufacturer="Chance",
        model_code="BK-9",
        ride_class="FAMILY",
        theoretical_hourly_capacity=500,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    bulletin = fixtures.create_bulletin(
        "BR-FAN-1",
        manufacturer="Chance",
        model_code="BK-1",
        severity="MANDATORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-10-01",
    )

    acknowledged = validate_success(
        api_client.acknowledge_bulletin(
            bulletin["id"], make_maintenance_manager_headers("mgr-7")
        )
    )
    assert_bulletin(acknowledged)
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == "mgr-7"
    assert_instant_equals(
        acknowledged["acknowledged_at"], CLOCK_START, "acknowledged_at"
    )
    assert acknowledged["action_total_count"] == 2, (
        "only the two units matching both manufacturer and model_code are enrolled"
    )
    assert acknowledged["action_verified_count"] == 0

    actions, actions_meta = validate_paginated(
        api_client.list_bulletin_actions(MANAGER, params={"bulletin_id": bulletin["id"]})
    )
    assert actions_meta["total_count"] == 2
    assert [row["attraction_id"] for row in actions] == [kiddie["id"], family["id"]], (
        "fleet actions are ordered by created_at ascending"
    )
    for action in actions:
        assert_bulletin_action(action)
        assert action["bulletin_id"] == bulletin["id"]
        assert action["status"] == "PENDING"

    _, outsider_meta = validate_paginated(
        api_client.list_bulletin_actions(
            MANAGER,
            params={"bulletin_id": bulletin["id"], "attraction_id": outsider["id"]},
        )
    )
    assert outsider_meta["total_count"] == 0, "the other model code was not enrolled"

    risk = validate_success(api_client.get_bulletin_risk(bulletin["id"], MANAGER))
    assert_bulletin_risk_shape(risk)
    assert risk["evaluated_action_count"] == 2
    assert risk["deferred_action_count"] == 0
    assert risk["escalation_factor"] == pytest.approx(1.00, abs=0.01)
    assert risk["fleet_aggregate_score"] == pytest.approx(28.00, abs=0.01), (
        "40 x 0.6 x 1.0 and 40 x 0.8 x 1.0 average to 28.00 with no overdue points"
    )
    assert risk["per_unit_max_score"] == pytest.approx(32.00, abs=0.01)
    assert risk["divergence"] == pytest.approx(4.00, abs=0.01)

    validate_error(
        api_client.acknowledge_bulletin(
            bulletin["id"], make_maintenance_manager_headers("mgr-7")
        ),
        "ERR_BULLETIN_STATE_INVALID",
        409,
    )
    assert (
        validate_success(api_client.get_bulletin(bulletin["id"], MANAGER))[
            "action_total_count"
        ]
        == 2
    ), "the refused second acknowledgement fanned out nothing"


def test_moving_the_clock_to_a_new_date_reopens_the_inspection_requirement():
    """PRD §2.4: "A `ParkOpsAdmin` moves the clock by calling
    `POST /_clock/set_current_utc` with a single field `to_iso8601` carrying the instant
    to move to."

    Design: Corner/endpoints/clock_endpoint_starts_at_the_declared_instant_and_moving_the_date_reopens_the_inspection_requirement
    """
    attraction = fixtures.create_attraction(
        name="Clock Ride",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="CK-1",
        ride_class="WATER",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    bundle = fixtures.inspection_signed_off(
        ("ADVISORY",),
        outcomes=["PASS"],
        service_date=CLOCK_START_DATE,
        attraction=attraction,
    )
    inspection = bundle["inspection"]

    before = fixtures.read_attraction(attraction["id"])
    assert before["operational_posture"] == "OPEN", (
        "the clock starts at the declared instant, so today's walk is already signed off"
    )
    assert before["last_signed_off_service_date"] == CLOCK_START_DATE

    validate_error(
        api_client.set_clock(factories.set_clock_payload("not-a-timestamp"), ADMIN),
        "ERR_INVALID_REQUEST",
        400,
    )
    assert (
        fixtures.read_attraction(attraction["id"])["operational_posture"] == "OPEN"
    ), "a malformed instant left the clock where it was"

    moved = validate_success(
        api_client.set_clock(
            factories.set_clock_payload("2026-08-02T06:00:00.000Z"), ADMIN
        )
    )
    assert_instant_equals(moved["current_utc"], "2026-08-02T06:00:00.000Z", "current_utc")

    after = fixtures.read_attraction(attraction["id"])
    assert after["operational_posture"] == "CLOSED_PENDING_INSPECTION", (
        "the new service date has no signed-off inspection of its own"
    )
    assert after["last_signed_off_service_date"] == CLOCK_START_DATE, (
        "the stamp records the date walked, not the date read"
    )
    stored = validate_success(
        api_client.get_daily_inspection(inspection["id"], TECHNICIAN)
    )
    assert_daily_inspection(stored)
    assert stored["status"] == "SIGNED_OFF"
    assert stored["service_date"] == CLOCK_START_DATE

    again = validate_success(
        api_client.set_clock(
            factories.set_clock_payload("2026-08-02T06:00:00.000Z"), ADMIN
        )
    )
    assert_instant_equals(again["current_utc"], "2026-08-02T06:00:00.000Z", "current_utc")
    assert (
        fixtures.read_attraction(attraction["id"])["operational_posture"]
        == "CLOSED_PENDING_INSPECTION"
    ), "re-setting the same instant derives the same posture"
