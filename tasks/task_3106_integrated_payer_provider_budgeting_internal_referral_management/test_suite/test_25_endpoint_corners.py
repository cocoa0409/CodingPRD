"""Corner coverage: individual endpoint behaviours.

Breadth file (queue B).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_appointment_payload,
    create_capacity_plan_payload,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    create_referral_payload,
    create_regional_budget,
    current_member_version,
    enroll_member,
    get_success_data,
    set_clock_payload,
    set_logical_clock,
    set_metric_outcome,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]
_QRB = TEST_USERS["quality_review_board_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


def _region_for_occ():
    """Region with a site, department, provider and an approved budget."""
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    return region, care_site, department, provider


def _two_department_region():
    region = create_open_region()
    care_site = create_care_site(region["id"])
    primary = create_department(
        care_site["id"], specialty="PRIMARY_CARE", appointment_slots_budgeted=200
    )
    cardiology = create_department(
        care_site["id"], specialty="CARDIOLOGY", appointment_slots_budgeted=100,
        wait_threshold_days=21,
    )
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    return region, care_site, primary, cardiology, provider, member


def test_referral_list_filters_by_target_department(api):
    """PRD §4: "| GET | `/referrals` | List Referrals with filters | All roles
    |"
    PRD §2.3: "List endpoints also accept the per-resource filter parameters
    named in §3".

    Design: Corner/endpoints/referral_list_filters_by_target_department
    """
    set_logical_clock()
    region, care_site, primary, cardiology, provider, member = _two_department_region()

    to_primary = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], primary["id"], primary["id"], member["version"],
                service_code="PRIMARY_CARE",
            ),
            _AS,
        )
    )
    to_cardiology = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], primary["id"], cardiology["id"],
                current_member_version(member["id"]),
                service_code="CARDIOLOGY",
            ),
            _AS,
        )
    )

    filtered = api_client.list_referrals(_UR, {"target_department_id": cardiology["id"]})
    rows = filtered.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == to_cardiology["id"]

    other = api_client.list_referrals(_UR, {"target_department_id": primary["id"]})
    assert len(other.json()["data"]) == 1
    assert other.json()["data"][0]["id"] == to_primary["id"]

    assert len(api_client.list_referrals(_UR).json()["data"]) == 2


def test_quality_metric_get_returns_the_metric_with_its_scored_outcome(api):
    """PRD §4: "| PATCH | `/_outcome-targets/{id}` | Set a QualityMetric's
    measured value and scored outcome directly | `PlatformAdmin` |"
    PRD §3.10: "A metric starts in `MEASURING` with `measured_value` at zero."

    Design: Corner/endpoints/quality_metric_get_returns_the_metric_with_its_scored_outcome
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"])

    metric = get_success_data(
        api_client.create_quality_metric(
            region["id"],
            {
                "metric_code": "QUALITY_COMPOSITE",
                "period": "2026-09",
                "target_value": 80,
                "accountable_provider_id": provider["id"],
            },
            _QRB,
        )
    )
    assert metric["measured_value"] == 0

    # The test-driving capability writes the supplied outcome fields directly.
    set_metric_outcome(metric["id"], 90, 90)

    res = api_client.get_quality_metric(metric["id"], _QRB)
    assert res.status_code == 200, res.text
    fetched = res.json()["data"]
    assert fetched["measured_value"] == 90
    assert fetched["weighted_component_score"] == 90
    assert fetched["accountable_provider_id"] == provider["id"]
    assert fetched["period"] == "2026-09"


def test_the_logical_clock_reads_its_startup_instant_before_any_set_call(api):
    """PRD §2.11: "The clock's startup value is exactly
    `2026-09-01T00:00:00Z`, and it holds that instant until changed."
    PRD §3.4: "`wait_days` is the number of calendar days from the booking
    instant to `start_utc`, expressed to one decimal place."

    Design: Corner/endpoints/clock_default_reads_2026_09_01_before_any_set_call
    """
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(
        care_site["id"], appointment_slots_budgeted=100, wait_threshold_days=14
    )
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    member = enroll_member(region["id"], provider["id"])

    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], member["version"],
            appointment_type="ROUTINE", start_utc="2026-09-10T00:00:00Z",
        ),
        _AS,
    )
    assert res.status_code == 201, res.text
    appointment = res.json()["data"]
    assert appointment["wait_days"] == 9.0, (
        "the wait is measured from the fixed startup clock rather than wall-clock time"
    )
    assert appointment["access_status"] == "WITHIN_ACCESS_TARGET"


def test_acknowledging_a_raised_alert_clears_the_open_count(api):
    """PRD §2.12: "Acknowledging an alert moves it to `ACKNOWLEDGED` and
    refreshes the owning region's `open_alert_count`, which counts only the
    alerts still in `RAISED` status."
    PRD §2.12: "Alerts are raised with `status` `RAISED` and carry the
    logical-clock instant in `raised_at`."

    Design: Corner/endpoints/alert_acknowledge_moves_status_to_acknowledged
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(
        care_site["id"], appointment_slots_budgeted=100, wait_threshold_days=14
    )
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    first = enroll_member(region["id"], provider["id"], member_ref="M-AL-1")
    second = enroll_member(region["id"], provider["id"], member_ref="M-AL-2")
    plan = get_success_data(
        api_client.create_capacity_plan(
            region["id"],
            create_capacity_plan_payload(
                department["id"], budgeted_slots=1, panel_target=1
            ),
            _RFO,
        )
    )
    get_success_data(api_client.review_capacity_plan(plan["id"], {}, _AS))
    get_success_data(api_client.activate_capacity_plan(plan["id"], {}, _RFO))

    # Booking the first slot reaches the plan's budgeted supply.
    api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], first["id"],
            current_member_version(first["id"]), start_utc="2026-09-10T09:00:00Z",
        ),
        _AS,
    )
    # Booking the second slot pushes the plan past its budgeted supply, which
    # runs the region's capacity posture branch.
    api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], second["id"],
            current_member_version(second["id"]), start_utc="2026-09-11T09:00:00Z",
        ),
        _AS,
    )

    raised = api_client.list_region_alerts(region["id"], _RFO, {"status": "RAISED"})
    rows = raised.json()["data"]
    assert rows, "the capacity posture hop raises an alert"
    for row in rows:
        acked = get_success_data(
            api_client.acknowledge_alert(row["id"], {}, _RFO)
        )
        assert acked["status"] == "ACKNOWLEDGED"

    region_after = api_client.get_region(region["id"], _RFO).json()["data"]
    assert region_after["open_alert_count"] == 0
    remaining = api_client.list_region_alerts(region["id"], _RFO, {"status": "RAISED"})
    assert remaining.json()["data"] == []


def test_reopening_a_closed_budget_lands_on_reopened(api):
    """PRD §3.7: "The committee may reopen either an `APPROVED` or a `CLOSED`
    budget to `REOPENED`. `CLOSED` is the terminal state, though `REOPENED`
    budgets can be resubmitted."
    PRD §3.7: "A `RegionalFinanceOfficer` closes an `APPROVED` budget to
    `CLOSED`."

    Design: Corner/endpoints/budget_reopen_from_closed_returns_the_period_to_reopened
    """
    set_logical_clock()
    region = create_open_region()
    budget = create_regional_budget(region["id"])
    get_success_data(api_client.submit_budget(budget["id"], {}, _RFO))
    get_success_data(api_client.approve_budget(budget["id"], {}, _BAC))
    closed = get_success_data(api_client.close_budget(budget["id"], {}, _RFO))
    assert closed["status"] == "CLOSED"

    reopened = get_success_data(api_client.reopen_budget(budget["id"], {}, _BAC))
    assert reopened["status"] == "REOPENED", (
        "reopening never lands directly on APPROVED"
    )

    resubmitted = get_success_data(api_client.submit_budget(budget["id"], {}, _RFO))
    assert resubmitted["status"] == "SUBMITTED"


def test_appointment_read_with_an_unknown_id_reports_appointment_not_found(api):
    """PRD §2.5: "Each resource has its own not-found identifier, and the full
    set is enumerated in §5."
    PRD §5: "`ERR_APPOINTMENT_NOT_FOUND` | 404".

    Design: Corner/errors/appointment_get_unknown_id_returns_appointment_not_found
    """
    set_logical_clock()
    res = api_client.get_appointment(NON_EXISTENT_UUID, _AS)
    assert res.status_code == 404, res.text
    assert res.json()["data"]["error_id"] == "ERR_APPOINTMENT_NOT_FOUND"


def test_every_member_scoped_child_create_shares_the_stale_version_contract(api):
    """PRD §2.9: "In all four cases a supplied `expected_member_version` that
    does not equal the member's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the write does not occur."
    PRD §2.9: "Two further member-scoped writes require the same field for the
    same reason — terminating a member's coverage and correcting a member's risk
    score both take `expected_member_version` as a non-optional input."

    Design: Corner/errors/stale_member_version_on_any_child_create_returns_stale_version
    """
    set_logical_clock()
    region, care_site, department, provider = _region_for_occ()
    member = enroll_member(region["id"], provider["id"], member_ref="M-OCC-2")
    stale = current_member_version(member["id"]) - 1

    referral = api_client.create_referral(
        create_referral_payload(
            member["id"], department["id"], department["id"], stale
        ),
        _AS,
    )
    assert referral.status_code == 412, referral.text
    assert referral.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    appointment = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], stale,
            start_utc="2026-09-10T09:00:00Z",
        ),
        _AS,
    )
    assert appointment.status_code == 412, appointment.text
    assert appointment.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    transfer = api_client.create_member_transfer(
        {
            "member_id": member["id"],
            "from_region_id": region["id"],
            "to_region_id": region["id"],
            "effective_utc": "2026-10-01T00:00:00Z",
            "expected_member_version": stale,
        },
        _RFO,
    )
    assert transfer.status_code == 412, transfer.text
    assert transfer.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    claim = api_client.submit_outside_service_claim(
        region["id"],
        {
            "member_id": member["id"],
            "vendor_name": "Test Vendor",
            "service_code": "RADIOLOGY",
            "claim_type": "CONTRACTED",
            "emergency_flag": False,
            "billed_amount_cents": 420000,
            "provider_type": "NON_CONTRACTED",
            "claim_line_number": 1,
            "emergency_inject_once": False,
            "derived_claim_type": "CONTRACTED",
            "expected_member_version": stale,
        },
        _RFO,
    )
    assert claim.status_code == 412, claim.text
    assert claim.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    assert api_client.list_referrals(_UR, {"member_id": member["id"]}).json()["data"] == []
    assert api_client.list_appointments(_AS, {"member_id": member["id"]}).json()["data"] == []