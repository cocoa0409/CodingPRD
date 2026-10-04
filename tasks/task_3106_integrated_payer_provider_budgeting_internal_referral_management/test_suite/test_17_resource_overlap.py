"""Resource overlap: provider-schedule instants and department aggregate occupancy.

Depth file (queue A).
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_appointment_payload,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    enroll_member,
    get_department,
    set_logical_clock,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]


def _overlap_scenario(slots, member_count):
    set_logical_clock("2026-09-01T00:00:00Z")
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(
        care_site["id"], appointment_slots_budgeted=slots, wait_threshold_days=14
    )
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    members = [
        enroll_member(
            region["id"], provider["id"], member_ref=f"M-OV-{i}", risk_score=1.0
        )
        for i in range(member_count)
    ]
    return region, department, provider, members


def test_adjacent_appointments_do_not_overlap(api):
    """PRD §3.4: "that range runs from `start_utc` inclusive to `start_utc` plus
    `duration_minutes` exclusive."
    PRD §3.4: "A booking is likewise refused with `ERR_PROVIDER_SCHEDULE_OVERLAP`
    (HTTP 409) when the named provider already holds a non-cancelled appointment
    on the same calendar day whose half-open instant range intersects the
    requested one".

    Design: Difficulty/resource_temporal_overlap/overlap_provider_schedule_intersection_semantics
    """
    region, department, provider, members = _overlap_scenario(slots=100, member_count=3)

    first = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[0]["id"], members[0]["version"],
            start_utc="2026-09-08T09:00:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert first.status_code == 201, first.text

    # [09:00, 09:20) and [09:20, 09:40) are adjacent: the end is exclusive.
    second = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[1]["id"], members[1]["version"],
            start_utc="2026-09-08T09:20:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["fulfillment_status"] == "SCHEDULED"


def test_intersecting_appointments_are_refused(api):
    """PRD §3.4: "A booking is likewise refused with `ERR_PROVIDER_SCHEDULE_OVERLAP`
    (HTTP 409) when the named provider already holds a non-cancelled appointment
    on the same calendar day whose half-open instant range intersects the
    requested one".
    PRD §2.11: "The system does not read wall-clock time for any business
    decision."

    Design: Difficulty/resource_temporal_overlap/overlap_provider_schedule_intersection_semantics
    """
    region, department, provider, members = _overlap_scenario(slots=100, member_count=3)

    first = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[0]["id"], members[0]["version"],
            start_utc="2026-09-08T09:00:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert first.status_code == 201, first.text

    # [09:15, 09:35) intersects [09:00, 09:20).
    third = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[2]["id"], members[2]["version"],
            start_utc="2026-09-08T09:15:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert third.status_code == 409, third.text
    assert third.json()["data"]["error_id"] == "ERR_PROVIDER_SCHEDULE_OVERLAP"


def test_a_rejected_overlap_leaves_the_provider_schedule_untouched(api):
    """PRD §3.4: "A booking is likewise refused with `ERR_PROVIDER_SCHEDULE_OVERLAP`
    (HTTP 409) when the named provider already holds a non-cancelled appointment
    on the same calendar day whose half-open instant range intersects the
    requested one".
    PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Difficulty/resource_temporal_overlap/overlap_provider_schedule_intersection_semantics
    """
    region, department, provider, members = _overlap_scenario(slots=100, member_count=3)

    # Two adjacent appointments: [09:00, 09:20) and [09:20, 09:40).
    for index in range(2):
        ok = api_client.book_appointment(
            create_appointment_payload(
                department["id"], provider["id"], members[index]["id"],
                members[index]["version"],
                start_utc=f"2026-09-08T09:{20 * index:02d}:00Z", duration_minutes=20,
            ),
            _AS,
        )
        assert ok.status_code == 201, ok.text

    # [09:30, 09:50) intersects the second appointment's range.
    rejected = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[2]["id"], members[2]["version"],
            start_utc="2026-09-08T09:30:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert rejected.status_code == 409

    listing = api_client.list_appointments(_AS, {"provider_id": provider["id"]})
    scheduled = [
        a for a in listing.json()["data"]
        if a["fulfillment_status"] not in ("CANCELLED",)
    ]
    assert len(scheduled) == 2, "the provider still holds exactly two appointments"


def test_aggregate_slot_occupancy_collides_without_an_instant_overlap(api):
    """PRD §3.4: "refused when the department's `appointment_slots_committed`
    plus one would exceed its `appointment_slots_budgeted` — both cases
    returning `ERR_DEPARTMENT_CAPACITY_EXHAUSTED` (HTTP 409)."
    PRD §3.4: "A booking is likewise refused with `ERR_PROVIDER_SCHEDULE_OVERLAP`
    (HTTP 409) when the named provider already holds a non-cancelled appointment
    on the same calendar day whose half-open instant range intersects the
    requested one".

    Design: Difficulty/resource_temporal_overlap/overlap_department_slot_aggregate_capacity_semantics
    """
    region, department, provider, members = _overlap_scenario(slots=1, member_count=2)

    first = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[0]["id"], members[0]["version"],
            start_utc="2026-09-08T09:00:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert first.status_code == 201, first.text
    assert get_department(department["id"])["appointment_slots_committed"] == 1

    # 14:00 does not intersect [09:00, 09:20), so the rejection is on aggregate
    # occupancy rather than on instants.
    second = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[1]["id"], members[1]["version"],
            start_utc="2026-09-08T14:00:00Z", duration_minutes=20,
        ),
        _AS,
    )
    assert second.status_code == 409, second.text
    assert second.json()["data"]["error_id"] == "ERR_DEPARTMENT_CAPACITY_EXHAUSTED", (
        "aggregate occupancy is distinct from the instant-intersection rule"
    )


def test_a_full_department_moves_to_constrained(api):
    """PRD §3.4: "if that reaches `appointment_slots_budgeted` the department
    moves from `OPEN` to `CONSTRAINED`."
    PRD §3.3: "Departments move among `OPEN`, `CONSTRAINED` and `CLOSED`".

    Design: Difficulty/resource_temporal_overlap/overlap_department_slot_aggregate_capacity_semantics
    """
    region, department, provider, members = _overlap_scenario(slots=1, member_count=2)
    assert get_department(department["id"])["status"] == "OPEN"

    api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[0]["id"], members[0]["version"],
            start_utc="2026-09-08T09:00:00Z", duration_minutes=20,
        ),
        _AS,
    )
    after = get_department(department["id"])
    assert after["appointment_slots_committed"] == after["appointment_slots_budgeted"] == 1
    assert after["status"] == "CONSTRAINED"