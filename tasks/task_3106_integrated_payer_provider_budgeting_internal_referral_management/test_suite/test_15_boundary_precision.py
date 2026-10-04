"""Boundary precision: the access-target equality case and the slot edge.

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
    get_department,
    get_success_data,
    set_logical_clock,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]


def _booking_scenario(wait_threshold_days, slots, member_count):
    set_logical_clock("2026-09-01T00:00:00Z")
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(
        care_site["id"], appointment_slots_budgeted=slots,
        wait_threshold_days=wait_threshold_days,
    )
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    members = [
        get_success_data(
            api_client.create_member(
                region["id"],
                {
                    "member_ref": f"M-W-{i}",
                    "attributed_provider_id": provider["id"],
                    "plan_product": "COMMERCIAL_HMO",
                    "benefit_tier": "TIER_1",
                    "risk_score": 1.0,
                    "coverage_effective_date": "2026-09-01T00:00:00Z",
                },
                _RFO,
            )
        )
        for i in range(member_count)
    ]
    return region, care_site, department, provider, members


def test_wait_exactly_at_the_threshold_is_a_breach(api):
    """PRD §3.4: "`access_status` is `BREACHED_ACCESS_TARGET` when `wait_days`
    is at least the department's `wait_threshold_days`, and
    `WITHIN_ACCESS_TARGET` otherwise".
    PRD §3.4: "the comparison is inclusive at the boundary, so a wait exactly
    equal to the threshold is a breach while a wait one tenth of a day shorter
    is not."

    Design: Difficulty/boundary_precision_check/boundary_access_wait_days_equality_is_a_breach
    """
    region, care_site, department, provider, members = _booking_scenario(
        wait_threshold_days=21, slots=100, member_count=1
    )
    member = members[0]

    # 2026-09-01T00:00:00Z -> 2026-09-22T00:00:00Z is exactly 21.0 days.
    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], member["version"],
            appointment_type="ROUTINE", start_utc="2026-09-22T00:00:00Z",
        ),
        _AS,
    )
    assert res.status_code == 201, res.text
    appointment = res.json()["data"]
    assert appointment["wait_days"] == 21.0
    assert appointment["access_status"] == "BREACHED_ACCESS_TARGET", (
        "equality at the threshold is a breach"
    )


def test_wait_one_tenth_below_the_threshold_is_within_target(api):
    """PRD §3.4: "`wait_days` is the number of calendar days from the booking
    instant to `start_utc`, expressed to one decimal place."
    PRD §2.8: "`wait_days` carries one decimal place".

    Design: Difficulty/boundary_precision_check/boundary_access_wait_days_equality_is_a_breach
    """
    region, care_site, department, provider, members = _booking_scenario(
        wait_threshold_days=21, slots=100, member_count=1
    )
    member = members[0]

    # 2026-09-01T00:00:00Z -> 2026-09-21T21:36:00Z is exactly 20.9 days.
    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], member["version"],
            appointment_type="ROUTINE", start_utc="2026-09-21T21:36:00Z",
        ),
        _AS,
    )
    assert res.status_code == 201, res.text
    appointment = res.json()["data"]
    assert appointment["wait_days"] == 20.9
    assert appointment["access_status"] == "WITHIN_ACCESS_TARGET", (
        "a tenth of a day under the threshold is inside the access target"
    )
    assert 20.9 < 21


def test_the_second_booking_fills_the_budgeted_supply(api):
    """PRD §3.4: "A booking is refused when the department's `status` is
    `CLOSED`, and refused when the department's `appointment_slots_committed`
    plus one would exceed its `appointment_slots_budgeted`".
    PRD §3.4: "The department's `appointment_slots_committed` increments by one,
    and if that reaches `appointment_slots_budgeted` the department moves from
    `OPEN` to `CONSTRAINED`."

    Design: Difficulty/boundary_precision_check/boundary_department_supply_rejects_the_committed_plus_one_booking
    """
    region, care_site, department, provider, members = _booking_scenario(
        wait_threshold_days=14, slots=2, member_count=2
    )
    first = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[0]["id"], members[0]["version"],
            start_utc="2026-09-08T09:00:00Z",
        ),
        _AS,
    )
    assert first.status_code == 201, first.text

    second = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[1]["id"], members[1]["version"],
            start_utc="2026-09-08T10:00:00Z",
        ),
        _AS,
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["fulfillment_status"] == "SCHEDULED"

    after = get_department(department["id"])
    assert after["appointment_slots_committed"] == 2
    assert after["appointment_slots_committed"] == after["appointment_slots_budgeted"]
    assert after["status"] == "CONSTRAINED"


def test_booking_past_the_budgeted_supply_is_refused(api):
    """PRD §3.4: "both cases returning `ERR_DEPARTMENT_CAPACITY_EXHAUSTED`
    (HTTP 409)."
    PRD §3.4: "refused when the department's `appointment_slots_committed` plus
    one would exceed its `appointment_slots_budgeted`".

    Design: Difficulty/boundary_precision_check/boundary_department_supply_rejects_the_committed_plus_one_booking
    """
    region, care_site, department, provider, members = _booking_scenario(
        wait_threshold_days=14, slots=2, member_count=3
    )
    for index, member in enumerate(members[:2]):
        ok = api_client.book_appointment(
            create_appointment_payload(
                department["id"], provider["id"], member["id"], member["version"],
                start_utc=f"2026-09-08T{9 + index:02d}:00:00Z",
            ),
            _AS,
        )
        assert ok.status_code == 201, ok.text

    third = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], members[2]["id"], members[2]["version"],
            start_utc="2026-09-09T09:00:00Z",
        ),
        _AS,
    )
    assert third.status_code == 409, third.text
    assert third.json()["data"]["error_id"] == "ERR_DEPARTMENT_CAPACITY_EXHAUSTED"

    after = get_department(department["id"])
    assert after["appointment_slots_committed"] == 2, (
        "the refused booking leaves the committed count untouched"
    )