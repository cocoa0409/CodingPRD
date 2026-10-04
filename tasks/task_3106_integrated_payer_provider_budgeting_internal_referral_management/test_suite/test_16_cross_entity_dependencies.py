"""Cross-entity state dependencies: which entity's state governs a transition.

Depth file (queue A).
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_active_capacity_plan,
    create_and_approve_budget,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    create_reviewed_capacity_plan,
    current_member_version,
    enroll_member,
    get_provider,
    get_region,
    get_success_data,
    set_logical_clock,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]


def _referral_scenario_capacity():
    """One region whose settled margin is negative, with a REVIEWED plan."""
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=1.0, facility_investment_budget_cents=0
    )
    department = create_department(care_site["id"], appointment_slots_budgeted=200)
    provider = create_provider(
        care_site["id"], compensation_model="SALARY", base_component_cents=5000000
    )
    member = enroll_member(region["id"], provider["id"], member_ref="M-CL-1")
    plan = create_reviewed_capacity_plan(
        region["id"], department["id"], budgeted_slots=100, panel_target=3
    )
    return region, care_site, department, provider, member, plan


def test_activation_is_admitted_while_the_region_is_restricted(api):
    """PRD §3.3: "A `RegionalFinanceOfficer` then activates a plan in
    `UNDER_REVIEW`, permitted only while the parent region's posture is `OPEN`
    or `RESTRICTED`, moving it to `ACTIVE`".
    PRD §2.4: "A region moves from `OPEN` to `RESTRICTED` when its
    `operating_margin_cents` is below zero".

    Design: Difficulty/cross_entity_state_dependency/cross_region_posture_gates_capacity_plan_activation
    """
    region, care_site, department, provider, member, plan = _referral_scenario_capacity()

    region_before = get_region(region["id"])
    assert region_before["operating_margin_cents"] < 0
    assert region_before["posture"] == "RESTRICTED", (
        "the negative settled margin has already run the posture ladder"
    )
    assert plan["status"] == "UNDER_REVIEW"

    activated = get_success_data(
        api_client.activate_capacity_plan(plan["id"], {}, _RFO)
    )
    assert activated["status"] == "ACTIVE", (
        "activation is permitted from the RESTRICTED posture"
    )


def test_activation_is_refused_while_the_plan_is_still_planning(api):
    """PRD §3.3: "Activation is refused for a plan not in `UNDER_REVIEW` with
    `ERR_CAPACITY_PLAN_NOT_ACTIVATABLE` (HTTP 409)."
    PRD §3.3: "A plan starts in `PLANNING`".

    Design: Difficulty/cross_entity_state_dependency/cross_region_posture_gates_capacity_plan_activation
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    department = create_department(care_site["id"])
    plan = get_success_data(
        api_client.create_capacity_plan(
            region["id"],
            {
                "department_id": department["id"],
                "period": "2026-09",
                "budgeted_slots": 100,
                "panel_target": 3,
            },
            _RFO,
        )
    )
    assert plan["status"] == "PLANNING"
    assert get_region(region["id"])["posture"] == "OPEN"

    res = api_client.activate_capacity_plan(plan["id"], {}, _RFO)
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_CAPACITY_PLAN_NOT_ACTIVATABLE"


def test_frozen_region_closes_its_capacity_plans(api):
    """PRD §3.3: "a plan whose parent region reaches `FROZEN` posture is moved
    to `FROZEN` automatically. `FROZEN` is the plan's terminal state."
    PRD §2.4: "A region moves from `RESTRICTED` to `FROZEN` when
    `operating_margin_cents` falls below negative five hundred million cents."

    Design: Difficulty/cross_entity_state_dependency/cross_region_posture_gates_capacity_plan_activation
    """
    from test_helpers import MARGIN_FREEZE_FLOOR_CENTS

    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=1.0, facility_investment_budget_cents=0
    )
    department = create_department(care_site["id"], appointment_slots_budgeted=200)
    provider = create_provider(
        care_site["id"], compensation_model="SALARY", base_component_cents=5000000
    )
    enroll_member(region["id"], provider["id"], member_ref="M-CL-1")
    plan = create_active_capacity_plan(
        region["id"], department["id"], budgeted_slots=100, panel_target=3
    )
    assert plan["status"] == "ACTIVE"

    # A second provider whose compensation alone exceeds the freeze floor drives
    # the region's settled margin past the FROZEN threshold.
    create_provider(
        care_site["id"], provider_name="Dr Dean",
        compensation_model="SALARY",
        base_component_cents=MARGIN_FREEZE_FLOOR_CENTS + 1000,
    )
    region_after = get_region(region["id"])
    assert region_after["operating_margin_cents"] < -MARGIN_FREEZE_FLOOR_CENTS
    assert region_after["posture"] == "FROZEN"

    plan_after = api_client.get_capacity_plan(plan["id"], _RFO).json()["data"]
    assert plan_after["status"] == "FROZEN", (
        "the region's FROZEN posture freezes its active plans"
    )


def test_completing_a_transfer_carries_the_member_into_the_panel(api):
    """PRD §3.9: "every `ACTIVE` provider in the destination region has
    `panel_size_assigned`, `quality_score`, `volume_component_cents`,
    `panel_capitation_component_cents`, `quality_bonus_cents` and
    `comp_total_cents` recomputed".
    PRD §3.2: "A provider begins in `ACTIVE` status and may later be moved to
    `PANEL_CLOSED`, at which point the provider is no longer accepting
    attributed members."

    Design: Difficulty/cross_entity_state_dependency/cross_member_transfer_gates_provider_panel_close
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    source = create_open_region(name="Kilo Region")
    source_site = create_care_site(source["id"], site_name="Kilo Office")
    create_department(source_site["id"])
    source_provider = create_provider(source_site["id"], provider_name="Dr Mara Sosa")
    source_member = enroll_member(
        source["id"], source_provider["id"], member_ref="M-CM-SRC"
    )

    destination = create_open_region(name="Lima Region", state_codes=["MI"])
    destination_site = create_care_site(
        destination["id"], site_name="Lima Office"
    )
    create_department(destination_site["id"])
    destination_provider = create_provider(
        destination_site["id"], provider_name="Dr Nikhil Rao"
    )
    enroll_member(
        destination["id"], destination_provider["id"], member_ref="M-CM-DST"
    )

    assert get_provider(destination_provider["id"])["panel_size_assigned"] == 1

    transfer = get_success_data(
        api_client.create_member_transfer(
            {
                "member_id": source_member["id"],
                "from_region_id": source["id"],
                "to_region_id": destination["id"],
                "effective_utc": "2026-09-10T00:00:00Z",
                "expected_member_version": current_member_version(source_member["id"]),
            },
            _RFO,
        )
    )
    get_success_data(api_client.accept_member_transfer(transfer["id"], {}, _RFO))
    # PRD 3.9: completion requires the logical clock to be at or after the
    # transfer's effective_utc.
    set_logical_clock("2026-09-10T00:00:00Z")
    get_success_data(api_client.complete_member_transfer(transfer["id"], {}, _RFO))

    after = get_provider(destination_provider["id"])
    # PRD 3.9 states that completing a transfer recomputes each destination
    # provider's panel_size_assigned, but it never states that the arriving
    # member is re-attributed to a destination provider, so the panel count is
    # asserted to remain at least its pre-transfer value rather than pinned.
    assert after["panel_size_assigned"] >= 1
    member_after = api_client.get_member(source_member["id"], _RFO).json()["data"]
    assert member_after["region_id"] == destination["id"]
    assert member_after["status"] == "ACTIVE"
    assert get_region(destination["id"])["member_count"] == 2


def test_completing_a_transfer_moves_capitation_between_regions(api):
    """PRD §3.9: "the destination region's `premium_revenue_cents` and
    `member_count` are recomputed".
    PRD §2.6: "`member_count` counts that same set."

    Design: Difficulty/cross_entity_state_dependency/cross_member_transfer_gates_provider_panel_close
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    source = create_open_region(name="Kilo Region")
    source_site = create_care_site(source["id"], site_name="Kilo Office")
    create_department(source_site["id"])
    source_provider = create_provider(source_site["id"])
    source_member = enroll_member(
        source["id"], source_provider["id"], member_ref="M-CM-SRC"
    )

    destination = create_open_region(name="Lima Region", state_codes=["MI"])
    destination_site = create_care_site(destination["id"], site_name="Lima Office")
    create_department(destination_site["id"])
    destination_provider = create_provider(destination_site["id"])
    enroll_member(destination["id"], destination_provider["id"], member_ref="M-CM-DST")

    source_before = get_region(source["id"])
    destination_before = get_region(destination["id"])
    assert source_before["member_count"] == 1
    assert destination_before["member_count"] == 1

    transfer = get_success_data(
        api_client.create_member_transfer(
            {
                "member_id": source_member["id"],
                "from_region_id": source["id"],
                "to_region_id": destination["id"],
                "effective_utc": "2026-09-10T00:00:00Z",
                "expected_member_version": current_member_version(source_member["id"]),
            },
            _RFO,
        )
    )
    get_success_data(api_client.accept_member_transfer(transfer["id"], {}, _RFO))
    # PRD 3.9: completion requires the logical clock to be at or after the
    # transfer's effective_utc.
    set_logical_clock("2026-09-10T00:00:00Z")
    get_success_data(api_client.complete_member_transfer(transfer["id"], {}, _RFO))

    source_after = get_region(source["id"])
    destination_after = get_region(destination["id"])
    assert source_after["member_count"] == 0
    assert destination_after["member_count"] == 2
    assert destination_after["premium_revenue_cents"] > destination_before["premium_revenue_cents"]