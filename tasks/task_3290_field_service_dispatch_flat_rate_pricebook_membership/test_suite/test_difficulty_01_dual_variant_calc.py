"""Depth tests for dual-variant calculations.

Covers the membership revenue-recognition split on the agreement domain and the
campaign attribution split on the marketing domain.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_technician_headers,
)
from test_helpers import fixtures as F

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]
CS = TEST_USERS["customer_service_headers"]


# =====================================================================
# membership_recognition_missed_visit_divergence
# =====================================================================
def _setup_four_visit_agreement_two_completed_one_missed():
    """Agreement 100000 cents, four visits; visits 1 and 2 completed through their own
    appointments, then the clock advances so visit 3 flips to MISSED."""
    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"],
        daily_capacity_hours=40,
        shift_segments=[{"start_utc": "2026-09-01T00:00:00Z", "end_utc": "2026-12-31T00:00:00Z"}],
    )
    task = F.create_task(code="HVAC-TUNE", estimated_hours=1.0, flat_rate_cents=5000)
    plan = F.create_plan()
    agreement = F.sell_agreement(branch["id"], plan["id"], tech_id=technician["id"])
    F.record_payment(agreement["id"], 30000)

    dates = {
        1: "2026-10-01T00:00:00Z",
        2: "2026-11-01T00:00:00Z",
        3: "2026-12-01T00:00:00Z",
        4: "2027-03-01T00:00:00Z",
    }
    visit_ids = {}
    for seq, date in dates.items():
        visit_ids[seq] = F.schedule_visit(agreement["id"], seq, date)["id"]

    for seq, window in ((1, ("2026-10-01T09:00:00Z", "2026-10-01T11:00:00Z")),
                        (2, ("2026-11-01T09:00:00Z", "2026-11-01T11:00:00Z"))):
        appointment = F.book_appointment(
            branch["id"],
            window_start_utc=window[0],
            window_end_utc=window[1],
            membership_agreement_id=agreement["id"],
            membership_visit_sequence_number=seq,
        )
        F.add_line(appointment["id"], code="HVAC-TUNE")
        F.dispatch_two_calls(appointment["id"])

    api_client.set_clock({"to_iso8601": "2027-02-01T00:00:00Z"}, ADMIN)
    return branch, technician, plan, agreement, visit_ids


def test_membership_recognition_denominator_includes_missed_visits(api):
    """PRD §3.8: "The base denominator counts every row in the input set."
    PRD §3.8: "The numerator is the count of those rows whose `status` is `COMPLETED`."
    PRD §3.8: "an agreement worth 100000 cents with two of four owed visits completed
    recognises 50000 cents under the base variant, because the missed visits inflate
    the denominator without contributing to the numerator".

    Design: Difficulty/dual_variant_calc/membership_recognition_missed_visit_divergence
    """
    branch, technician, plan, agreement, visit_ids = _setup_four_visit_agreement_two_completed_one_missed()

    visits = F.list_visits(agreement["id"])
    by_status = {}
    for visit in visits:
        by_status.setdefault(visit["status"], []).append(visit)

    assert len(by_status.get("COMPLETED", [])) == 2, (
        f"expected two completed visits, got {by_status.get('COMPLETED')}"
    )
    assert len(by_status.get("MISSED", [])) == 1, (
        f"expected one missed visit, got {by_status.get('MISSED')}"
    )
    assert len(by_status.get("SCHEDULED", [])) == 1, (
        f"expected one still-scheduled visit, got {by_status.get('SCHEDULED')}"
    )

    refreshed = F.get_agreement(agreement["id"])
    assert refreshed["status"] == "OVERDUE", (
        f"a missed visit must push the agreement to OVERDUE, got {refreshed['status']}"
    )
    assert refreshed["visits_fulfilled_count"] == 2, (
        f"expected visits_fulfilled_count 2, got {refreshed['visits_fulfilled_count']}"
    )
    assert (
        refreshed["revenue_recognized_cents"] + refreshed["unearned_revenue_balance_cents"]
        == refreshed["annual_price_cents"]
    ), "recognised plus unearned must sum to the annual price"


def test_membership_recognition_two_of_four_admits_only_the_named_variant_values(api):
    """PRD §3.8: "an agreement worth 100000 cents with two of four owed visits completed
    recognises 50000 cents under the base variant".
    PRD §3.8: "under the variant that drops missed visits from the denominator the same
    agreement recognises 66667 cents and carries an unearned balance of 33333 rather
    than 50000."

    The two figures the PRD names for this exact agreement are the only
    PRD-consistent values, so the recognised amount must be one of them.

    Design: Difficulty/dual_variant_calc/membership_recognition_missed_visit_divergence
    """
    branch, technician, plan, agreement, visit_ids = _setup_four_visit_agreement_two_completed_one_missed()

    refreshed = F.get_agreement(agreement["id"])
    recognised = refreshed["revenue_recognized_cents"]
    unearned = refreshed["unearned_revenue_balance_cents"]

    assert recognised in (50000, 66667), (
        "two completed of four owed visits on a 100000-cent agreement recognises 50000 "
        f"under the base denominator and 66667 under the missed-excluding one, got {recognised}"
    )
    expected_unearned = 100000 - recognised
    assert unearned == expected_unearned, (
        f"unearned balance must be the annual price minus the recognised figure, "
        f"expected {expected_unearned}, got {unearned}"
    )
    assert unearned in (50000, 33333), (
        f"the paired unearned balances are 50000 and 33333, got {unearned}"
    )


# =====================================================================
# campaign_attribution_visit_waterfall_divergence
# =====================================================================
def _setup_campaign_with_one_incomplete_member_booking():
    """Campaign with two attributed appointments: one linked to a never-completed
    membership visit, one a non-member booking."""
    branch = F.create_branch()
    campaign = F.create_campaign(spend_cents=50000)
    plan = F.create_plan()
    agreement = F.sell_agreement(branch["id"], plan["id"])
    F.record_payment(agreement["id"], 30000)
    F.schedule_visit(agreement["id"], 1, "2026-12-01T00:00:00Z")

    call = F.create_call_record(campaign["id"])
    member_booking = F.book_appointment(
        branch["id"],
        customer_name="Ada",
        window_start_utc="2026-12-01T09:00:00Z",
        window_end_utc="2026-12-01T11:00:00Z",
        campaign_id=campaign["id"],
        call_record_id=call["id"],
        membership_agreement_id=agreement["id"],
        membership_visit_sequence_number=1,
    )
    plain_booking = F.book_appointment(
        branch["id"],
        customer_name="Bo",
        window_start_utc="2026-12-02T09:00:00Z",
        window_end_utc="2026-12-02T11:00:00Z",
        campaign_id=campaign["id"],
    )
    return branch, campaign, agreement, member_booking, plain_booking


def test_campaign_attribution_chronological_counts_every_attributed_booking(api):
    """PRD §3.12: "The `campaign_attribution_revenue` calculation builds a booking history
    from every `Appointment` whose `campaign_id` equals the campaign's id".
    PRD §3.12: "Under the chronological variant the job count is the count of the whole
    attributed booking history, whether or not the underlying visit completed."

    Design: Difficulty/dual_variant_calc/campaign_attribution_visit_waterfall_divergence
    """
    branch, campaign, agreement, member_booking, plain_booking = (
        _setup_campaign_with_one_incomplete_member_booking()
    )

    response = api_client.get_campaign(
        campaign["id"], DISPATCHER, params={"include_attribution": True}
    )
    data = validate_success(response)
    assert data["attributed_job_count"] == 2, (
        "both attributed bookings count under the chronological history, "
        f"got {data['attributed_job_count']}"
    )
    assert data["attributed_revenue_cents"] == 0, (
        "neither booking completed, so no sold revenue is attributed"
    )


def test_campaign_attribution_waterfall_drops_the_incomplete_member_booking(api):
    """PRD §3.12: "an appointment survives the narrower count when its
    `membership_agreement_id` is absent, or when some `MembershipVisit` exists on that
    agreement at its `sequence_number` whose `status` is `COMPLETED`."
    PRD §3.12: "whenever any attributed appointment maps to an incomplete membership
    visit, the waterfall variant's job count, its revenue and its cost per acquisition
    are all strictly smaller than the chronological variant's".

    Design: Difficulty/dual_variant_calc/campaign_attribution_visit_waterfall_divergence
    """
    branch, campaign, agreement, member_booking, plain_booking = (
        _setup_campaign_with_one_incomplete_member_booking()
    )

    response = api_client.get_campaign(
        campaign["id"],
        DISPATCHER,
        params={"include_attribution": True, "attribution_variant": "visit_completion_waterfall"},
    )
    data = validate_success(response)
    assert data["attributed_job_count"] == 1, (
        "only the booking with no membership visit survives the waterfall count, "
        f"got {data['attributed_job_count']}"
    )

    # The member booking's visit is still SCHEDULED, never completed.
    visits = F.list_visits(agreement["id"])
    assert [v["status"] for v in visits] == ["SCHEDULED"], (
        f"the named visit must still be incomplete, got {visits}"
    )