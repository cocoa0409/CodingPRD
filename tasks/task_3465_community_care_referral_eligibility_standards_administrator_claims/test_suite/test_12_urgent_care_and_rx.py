"""Urgent care benefit (copay tiers, fiscal-year rollover, same-day collision)
and prescription fill requests (controlled-substance ban, link-dependent
supply caps, terminal decisions)."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_paginated,
    validate_success,
    assert_urgent_care_visit,
    complete_appointment, create_rx_appointment_payload,
    create_rx_for_appointment, create_rx_for_urgent_visit,
    create_rx_urgent_payload, create_station, create_tpa,
    create_urgent_care_visit_payload, create_veteran, decide_rx,
    decide_rx_payload, make_provider_rep_headers, make_veteran_headers,
    onboard_provider, record_urgent_visit, record_urgent_visits_on_days,
    schedule_appointment, setup_episode,
)

COORD = TEST_USERS["care_coordinator_headers"]
PHARM = TEST_USERS["system_pharmacist_headers"]


def test_urgent_care_copay_epoch_counting_order():
    """PRD §3.8: "The `visit_index_in_fy` is the count of the veteran's other
    `RECORDED` urgent care visits in the same fiscal year — the new visit is
    not yet counted — plus one, so the October 1 reset restarts every veteran's
    annual sequence."
    PRD §3.8: "`LOW` pays 0 cents on every visit; `MID` pays 1500 cents for a
    `visit_index_in_fy` of 3 or less and 3000 cents from the fourth visit of
    the fiscal year onward; `HIGH` pays 3000 cents for a `visit_index_in_fy` of
    3 or less and 4500 cents from the fourth onward."

    Design: Difficulty/combinatorial_formula/urgent_care_copay_epoch_counting_order
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=5)  # MID band

    visits = record_urgent_visits_on_days(
        veteran, ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    )
    for v in visits:
        assert_urgent_care_visit(v)
    assert [v["copay_cents"] for v in visits] == [1500, 1500, 1500, 3000]
    assert [v["visit_index_in_fy"] for v in visits] == [1, 2, 3, 4]
    assert visits[3]["fiscal_year"] == 2026  # September predates the rollover


def test_urgent_care_copay_fiscal_year_rollover_resets_tier():
    """PRD §3.8: "The `visit_date` is taken from the logical clock's calendar
    date at creation, and the visit's `fiscal_year` follows the federal year
    that begins on October 1: when the visit month is October or later the
    fiscal year is the calendar year plus one, otherwise it is the calendar
    year."
    PRD §3.8: "The `visit_index_in_fy` is the count of the veteran's other
    `RECORDED` urgent care visits in the same fiscal year — the new visit is
    not yet counted — plus one, so the October 1 reset restarts every veteran's
    annual sequence."

    Design: Corner/calculations/urgent_care_copay_fiscal_year_rollover_resets_tier
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=5)

    record_urgent_visits_on_days(
        veteran, ["2026-09-01", "2026-09-02", "2026-09-03"]
    )
    u4 = record_urgent_visit(veteran, clock_iso="2026-10-01T08:00:00Z")

    assert u4["fiscal_year"] == 2027  # month >= 10 rolls the FY
    assert u4["visit_index_in_fy"] == 1  # FY2026 priors excluded
    assert u4["copay_cents"] == 1500  # lower tier re-applies after the reset


def test_veteran_same_day_urgent_visit_closed_day_collision():
    """PRD §3.8: "Only one urgent care visit per veteran per calendar date is
    recordable — a second `RECORDED` visit for the same veteran on the same
    `visit_date` is rejected with `ERR_SAME_DAY_URGENT_VISIT` (HTTP 422)."
    PRD §3.8: "The visit's `priority_band` derives from the veteran's
    `priority_group`: `LOW` for groups 1 through 3, `MID` for groups 4 through
    6, `HIGH` for groups 7 and 8."

    Design: Difficulty/resource_temporal_overlap/veteran_same_day_urgent_visit_closed_day_collision
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=2)  # LOW band

    u1 = record_urgent_visit(veteran, clock_iso="2026-09-01T08:00:00Z")
    assert u1["status"] == "RECORDED"
    assert u1["copay_cents"] == 0
    assert u1["visit_date"] == "2026-09-01"

    same_day = api_client.create_urgent_care_visit(
        create_urgent_care_visit_payload(veteran["id"],
                                         facility_name="OtherClinic"),
        make_veteran_headers(veteran["id"]),
    )
    validate_error(same_day, "ERR_SAME_DAY_URGENT_VISIT")

    # The resource frees at midnight, not after 24h or 60 minutes.
    u3 = record_urgent_visit(veteran, facility_name="OtherClinic",
                             clock_iso="2026-09-02T00:30:00Z")
    assert u3["status"] == "RECORDED"
    assert u3["visit_date"] == "2026-09-02"


def test_rx_controlled_substance_rejected():
    """PRD §3.8: "Safety gates bind the requester: controlled substances are
    never fillable through this channel, so a request with
    `controlled_substance` true is rejected with `ERR_CONTROLLED_RX_NOT_ALLOWED`
    (HTTP 422); the submitting provider must be `CREDENTIALED` (else
    `ERR_PROVIDER_NOT_CREDENTIALED`); and an appointment-linked request must
    name one of the caller's own appointments (else `ERR_OWNERSHIP_MISMATCH`)
    that has already been `COMPLETED` (a lifecycle state gate, else
    `ERR_INVALID_STATE`)."

    Design: Corner/validations/rx_controlled_substance_rejected
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=2)
    visit = record_urgent_visit(veteran, clock_iso="2026-09-01T08:00:00Z")
    tpa = create_tpa()
    provider = onboard_provider(tpa)

    resp = api_client.create_prescription_fill_request(
        create_rx_urgent_payload(visit["id"], medication_name="oxycodone 5mg",
                                 days_supply=5, controlled_substance=True),
        make_provider_rep_headers(provider["id"]),
    )
    validate_error(resp, "ERR_CONTROLLED_RX_NOT_ALLOWED")

    _rx, meta = validate_paginated(
        api_client.list_prescription_fill_requests(
            COORD, params={"urgent_care_visit_id": visit["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_rx_days_supply_cap_depends_on_link_type():
    """PRD §3.8: "The supply cap follows the link type: at most 14 days of
    supply when urgent-care-linked and at most 90 days when appointment-linked,
    with an excess rejected as `ERR_DAYS_SUPPLY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/rx_days_supply_cap_depends_on_link_type
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=2)
    visit = record_urgent_visit(veteran, clock_iso="2026-09-01T08:00:00Z")
    env = setup_episode(station=station, veteran=veteran, authorized_visits=1)
    appt = schedule_appointment(env["authorization"])
    appt = complete_appointment(appt, env["provider"])
    provider = env["provider"]

    # Urgent-care-linked: cap 14.
    resp_urgent = api_client.create_prescription_fill_request(
        create_rx_urgent_payload(visit["id"], days_supply=15),
        make_provider_rep_headers(provider["id"]),
    )
    validate_error(resp_urgent, "ERR_DAYS_SUPPLY_EXCEEDED")

    # Appointment-linked: cap 90 inclusive.
    ok = create_rx_for_appointment(appt, provider, days_supply=90)
    assert ok["status"] == "REQUESTED"

    resp_appt = api_client.create_prescription_fill_request(
        create_rx_appointment_payload(appt["id"],
                                      medication_name="atorvastatin 20mg",
                                      days_supply=91),
        make_provider_rep_headers(provider["id"]),
    )
    validate_error(resp_appt, "ERR_DAYS_SUPPLY_EXCEEDED")


def test_rx_decide_twice_returns_invalid_state():
    """PRD §3.8: "Only a `REQUESTED` request can be decided, else
    `ERR_INVALID_STATE`; a refusal must carry a `refusal_reason`, else
    `ERR_INVALID_REQUEST`."
    PRD §3.8: "Either decision stamps `decided_at`, a refusal records its
    `refusal_reason`, and both `FILLED` and `REFUSED` are terminal."

    Design: Corner/state_machines/rx_decide_twice_returns_invalid_state
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=2)
    visit = record_urgent_visit(veteran, clock_iso="2026-09-01T08:00:00Z")
    tpa = create_tpa()
    provider = onboard_provider(tpa)

    rx = create_rx_for_urgent_visit(visit, provider)
    filled = decide_rx(rx["id"], "FILLED")
    assert filled["status"] == "FILLED"

    resp = api_client.decide_prescription_fill_request(
        rx["id"], decide_rx_payload("REFUSED", refusal_reason="duplicate"),
        PHARM,
    )
    validate_error(resp, "ERR_INVALID_STATE")
    still = api_client.get_prescription_fill_request(rx["id"], COORD)
    assert validate_success(still, 200)["status"] == "FILLED"
