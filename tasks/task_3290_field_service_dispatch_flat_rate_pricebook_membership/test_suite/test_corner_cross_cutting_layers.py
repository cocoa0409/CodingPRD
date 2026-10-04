"""Breadth tests for the cross-cutting layers: optimistic concurrency on repricing,
the overdue sweep's cascading effects, and scoped derived-field reconciliation.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_a_second_reprice_with_a_spent_version_is_refused(api):
    """PRD §2.7: "That request must carry `expected_pricebook_task_version` as a
    non-optional body field, carrying the client's last observed `version` of the
    `PricebookTask` revision the appointment's lines were quoted from. If the supplied
    value differs from the current `version` of a `PricebookTask` revision referenced by
    this appointment's lines — because the pricebook row has since advanced — the reprice is
    rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.4: "every line's `flat_rate_cents` is reset to the `flat_rate_cents` of the
    highest published revision of its code".

    Design: Corner/cross_cutting_layers/reprice_rejects_stale_pricebook_version
    """
    branch = F.create_branch()
    F.hire_technician(
        branch["id"],
        shift_segments=[{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-10T18:00:00Z"}],
        daily_capacity_hours=8,
    )
    first_revision = F.create_task(
        code="HVAC-COIL", display_name="Coil Clean", estimated_hours=1.0,
        flat_rate_cents=100000, status="PUBLISHED",
    )

    appointment = F.book_appointment(branch["id"])
    F.add_line(appointment["id"], code="HVAC-COIL")
    second_revision = F.create_task(
        code="HVAC-COIL", display_name="Coil Clean v2", estimated_hours=1.0,
        flat_rate_cents=120000, status="PUBLISHED",
    )
    # The line is (re)drawn against revision 2, which becomes the revision this
    # appointment's line references; observation is what makes the stale check bite.
    # The sold line is what gives the recomputed quote a labour base to stand on.
    F.add_line(appointment["id"], code="HVAC-COIL", status="SOLD")
    # PRD §3.4: repricing is an explicit Dispatcher action "against an appointment
    # that is still `SCHEDULED`", so the appointment is repriced before dispatch.

    first = validate_success(
        api_client.reprice_appointment(
            appointment["id"],
            {"expected_pricebook_task_version": second_revision["version"]},
            DISPATCHER,
        )
    )
    assert first["quoted_price_cents"] == 120000, (
        f"the reprice draws the highest published revision, got {first['quoted_price_cents']}"
    )

    # The first reprice advanced the referenced revision's version, so replaying the
    # same observed version is now stale.
    validate_error(
        api_client.reprice_appointment(
            appointment["id"],
            {"expected_pricebook_task_version": second_revision["version"]},
            DISPATCHER,
        ),
        "ERR_STALE_VERSION",
    )


def test_the_overdue_sweep_propagates_to_the_branch_count(api):
    """PRD §3.9: "Every `MembershipVisit` whose `scheduled_date` is strictly earlier than
    the new reading and whose `status` is `SCHEDULED` transitions to `MISSED`. Every
    `MembershipAgreement` whose `status` is `ACTIVE` and which now carries a `MISSED` visit
    transitions to `OVERDUE`. And the `membership_count_active` of every affected branch is
    recomputed."

    Design: Corner/cross_cutting_layers/visit_overdue_cascade_updates_branch_membership_count
    """
    branch, plan, agreement, visits = F.setup_membership(
        visit_dates=["2026-10-01T00:00:00Z"]
    )
    active = F.get_branch(branch["id"])
    assert active["membership_count_active"] == 1, (
        "an ACTIVE agreement counts toward the branch's active members"
    )

    api_client.set_clock({"to_iso8601": "2026-11-15T00:00:00Z"}, ADMIN)

    assert F.list_visits(agreement["id"])[0]["status"] == "MISSED"
    assert F.get_agreement(agreement["id"])["status"] == "OVERDUE"
    assert F.get_branch(branch["id"])["membership_count_active"] == 0, (
        "the clock advance must propagate all the way to the branch aggregate"
    )


def test_revenue_recognition_on_one_agreement_leaves_another_untouched(api):
    """PRD §3.8: "Revenue is recognised forward-looking against the visits the plan owes."
    PRD §3.8: "the agreement's `revenue_recognized_cents` is its `annual_price_cents`
    multiplied by the completed count and divided by the base denominator".

    Design: Corner/cross_cutting_layers/affiliation_resale_of_visits_is_scoped_not_global
    """
    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"],
        shift_segments=[{"start_utc": "2026-09-01T00:00:00Z", "end_utc": "2026-10-20T18:00:00Z"}],
        daily_capacity_hours=40,
    )
    F.create_task(code="HVAC-TUNE", estimated_hours=1.0, flat_rate_cents=5000)
    plan = F.create_plan(
        included_service_visit_count=4, maintenance_visit_interval_days=30
    )

    first = F.sell_agreement(branch["id"], plan["id"], tech_id=technician["id"], homeowner_name="Ada")
    F.record_payment(first["id"], 30000)
    second = F.sell_agreement(branch["id"], plan["id"], tech_id=technician["id"], homeowner_name="Bo")
    F.record_payment(second["id"], 30000)

    F.schedule_visit(second["id"], 1, "2026-11-01T00:00:00Z")
    F.schedule_visit(first["id"], 1, "2026-10-01T00:00:00Z")

    appointment = F.book_appointment(
        branch["id"],
        window_start_utc="2026-10-01T09:00:00Z",
        window_end_utc="2026-10-01T11:00:00Z",
        membership_agreement_id=first["id"],
        membership_visit_sequence_number=1,
    )
    F.add_line(appointment["id"], code="HVAC-TUNE")
    F.dispatch_two_calls(appointment["id"])

    first_visits = F.list_visits(first["id"])
    assert first_visits[0]["status"] == "COMPLETED"
    assert first_visits[0]["completed_appointment_id"] == appointment["id"]

    second_visits = F.list_visits(second["id"])
    assert [v["status"] for v in second_visits] == ["SCHEDULED"], (
        "no derivation may cross the agreement boundary, "
        f"got {[v['status'] for v in second_visits]}"
    )
    assert F.get_agreement(second["id"])["revenue_recognized_cents"] == 0, (
        "the untouched agreement recognises nothing"
    )