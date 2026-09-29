"""Compensating actions and the quantities they must conserve.

Two ledgers are recomputed in full rather than patched: a project's collected
funds with its four allocation buckets, and an installer's committed crew days.
Both are exercised here by performing an action and then its exact compensating
action, and comparing the after value against the captured before value.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["design_consultant_headers"]
ADMIN = TEST_USERS["manufacturer_admin_headers"]

# A single SKY_BLUE deck priced as a FIRM quote: 64350 x 1.07 rounded once at
# the end is 68855, freight is 48000 + 1250, and the total is 118105.
QUOTE_SUBTOTAL_CENTS = 68855
QUOTE_FREIGHT_CENTS = 49250
QUOTE_TOTAL_CENTS = 118105

# The three bucket targets that quote supplies, in strict fill order.
TARGET_PERMIT_FREIGHT_CENTS = 49250
TARGET_SURFACING_CENTS = 13771
TARGET_STRUCTURE_CENTS = 55084

PLEDGE_A_CENTS = 60000
PLEDGE_B_CENTS = 58105

# (funds, permit_freight, surfacing, structure, contingency)
BUCKETS_AFTER_FIRST_COLLECT = (60000, 49250, 10750, 0, 0)
BUCKETS_AFTER_SECOND_COLLECT = (118105, 49250, 13771, 55084, 0)
BUCKETS_DRAINED = (0, 0, 0, 0, 0)


def _fund_state(project_id: str) -> tuple:
    """Read the project's collected funds and its four buckets as one tuple."""
    project = fx.get_project(project_id)
    a.assert_project(project)
    a.assert_allocation_invariant(project)
    for field in (
        "funds_collected_cents",
        "alloc_permit_freight_cents",
        "alloc_surfacing_cents",
        "alloc_structure_cents",
        "alloc_contingency_cents",
    ):
        a.assert_cents(project[field], field)
    return (
        project["funds_collected_cents"],
        project["alloc_permit_freight_cents"],
        project["alloc_surfacing_cents"],
        project["alloc_structure_cents"],
        project["alloc_contingency_cents"],
    )


def _get_pledge(pledge_id: str) -> dict:
    """Re-read one pledge row directly, since a refusal must not be unwrapped."""
    return validate_success(api_client.get_pledge(pledge_id, ADMIN), 200)


def _setup_quoted_project_with_two_pledges() -> dict:
    """A deck-only DESIGN_APPROVED project, an ISSUED FIRM quote, two pledges."""
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Larkspur Green"}
    )
    scenario["deck_placement"] = fx.create_validated_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    scenario["rendering"] = fx.issue_rendering(
        scenario["project"]["id"], scenario["standard"]["id"]
    )
    scenario = fx.setup_design_approved_project(scenario=scenario)
    scenario["quote"] = fx.issue_quote(
        scenario["project"]["id"], scenario["rendering"]["id"], variant="FIRM"
    )
    scenario["pledge_a"] = fx.create_pledge(
        scenario["project"]["id"], amount_cents=PLEDGE_A_CENTS, pledged_at="2026-08-01"
    )
    scenario["pledge_b"] = fx.create_pledge(
        scenario["project"]["id"], amount_cents=PLEDGE_B_CENTS, pledged_at="2026-08-01"
    )
    return scenario


def _assert_quote_supplies_the_targets(quote: dict) -> None:
    """The bucket targets are read off the quote, so pin the quote first."""
    a.assert_quote(quote)
    assert quote["subtotal_cents"] == QUOTE_SUBTOTAL_CENTS, (
        f"expected {QUOTE_SUBTOTAL_CENTS}, got {quote['subtotal_cents']} "
        "for subtotal_cents"
    )
    assert quote["freight_cents"] == QUOTE_FREIGHT_CENTS, (
        f"expected {QUOTE_FREIGHT_CENTS}, got {quote['freight_cents']} "
        "for freight_cents"
    )
    assert quote["total_cents"] == QUOTE_TOTAL_CENTS, (
        f"expected {QUOTE_TOTAL_CENTS}, got {quote['total_cents']} for total_cents"
    )


class TestPledgeRefundConservesTheWaterfall:
    """Collect, collect, refund, refund — five checkpoints on one project."""

    def test_first_bucket_fills_completely_before_the_second_receives_anything(self):
        """60000 cents fills permits and freight, then spills 10750 into surfacing.

        PRD: "`alloc_permit_freight_cents` receives the smaller of the remaining funds and the first target, and that amount leaves the remaining funds."

        Design: Difficulty/compensating_invariant/pledge_collect_then_refund_conserves_project_funds_and_allocations
        """
        scenario = _setup_quoted_project_with_two_pledges()
        project_id = scenario["project"]["id"]
        _assert_quote_supplies_the_targets(scenario["quote"])
        assert TARGET_PERMIT_FREIGHT_CENTS == QUOTE_FREIGHT_CENTS, (
            "the first target is the quote's freight"
        )

        fx.collect_pledge(scenario["pledge_a"]["id"])
        assert _fund_state(project_id) == BUCKETS_AFTER_FIRST_COLLECT, (
            f"expected {BUCKETS_AFTER_FIRST_COLLECT}, got {_fund_state(project_id)} "
            f"after collecting {PLEDGE_A_CENTS} cents"
        )

        fx.collect_pledge(scenario["pledge_b"]["id"])
        assert _fund_state(project_id) == BUCKETS_AFTER_SECOND_COLLECT, (
            f"expected {BUCKETS_AFTER_SECOND_COLLECT}, got {_fund_state(project_id)} "
            f"after collecting a further {PLEDGE_B_CENTS} cents"
        )
        assert (
            TARGET_SURFACING_CENTS + TARGET_STRUCTURE_CENTS == QUOTE_SUBTOTAL_CENTS
        ), "the surfacing and structure targets must sum to the subtotal exactly"

    def test_four_buckets_sum_to_funds_collected_at_every_checkpoint(self):
        """The invariant survives two collections and two refunds.

        PRD: "The invariant that must hold after every collection and every refund is that the four buckets sum to exactly `funds_collected_cents` — no cent is created and none is lost."

        Design: Difficulty/compensating_invariant/pledge_collect_then_refund_conserves_project_funds_and_allocations
        """
        scenario = _setup_quoted_project_with_two_pledges()
        project_id = scenario["project"]["id"]

        opening = _fund_state(project_id)
        assert opening == BUCKETS_DRAINED, (
            f"expected {BUCKETS_DRAINED}, got {opening} before any collection"
        )

        fx.collect_pledge(scenario["pledge_a"]["id"])
        assert _fund_state(project_id)[0] == 60000, (
            f"expected 60000, got {_fund_state(project_id)[0]} for funds_collected_cents"
        )

        fx.collect_pledge(scenario["pledge_b"]["id"])
        assert _fund_state(project_id)[0] == 118105, (
            f"expected 118105, got {_fund_state(project_id)[0]} "
            "for funds_collected_cents"
        )

        fx.refund_pledge(scenario["pledge_b"]["id"])
        assert _fund_state(project_id)[0] == 60000, (
            f"expected 60000, got {_fund_state(project_id)[0]} "
            "for funds_collected_cents after the second pledge was refunded"
        )

        fx.refund_pledge(scenario["pledge_a"]["id"])
        assert _fund_state(project_id)[0] == 0, (
            f"expected 0, got {_fund_state(project_id)[0]} "
            "for funds_collected_cents once both pledges are refunded"
        )

    def test_refunding_the_second_collection_restores_the_earlier_split(self):
        """The buckets return to their exact post-first-collect values.

        PRD: "Because the recompute is total rather than incremental, refunding a collected pledge restores the buckets to exactly their pre-collection values — the buckets drain in reverse fill order purely as a consequence of the recompute, with no drift."

        Design: Difficulty/compensating_invariant/pledge_collect_then_refund_conserves_project_funds_and_allocations
        """
        scenario = _setup_quoted_project_with_two_pledges()
        project_id = scenario["project"]["id"]

        fx.collect_pledge(scenario["pledge_a"]["id"])
        before = _fund_state(project_id)
        assert before == BUCKETS_AFTER_FIRST_COLLECT, (
            f"expected {BUCKETS_AFTER_FIRST_COLLECT}, got {before} "
            "before the compensating pair"
        )

        fx.collect_pledge(scenario["pledge_b"]["id"])
        assert _fund_state(project_id) == BUCKETS_AFTER_SECOND_COLLECT, (
            f"expected {BUCKETS_AFTER_SECOND_COLLECT}, "
            f"got {_fund_state(project_id)} once both pledges are collected"
        )

        refunded = fx.refund_pledge(scenario["pledge_b"]["id"])
        a.assert_pledge(refunded)
        assert refunded["status"] == "REFUNDED", (
            f"expected REFUNDED, got {refunded['status']} for the refunded pledge"
        )

        after = _fund_state(project_id)
        assert after == before, (
            f"expected the buckets to return to {before}, got {after} "
            "after the collect-then-refund pair"
        )

        untouched = _get_pledge(scenario["pledge_a"]["id"])
        assert untouched["status"] == "COLLECTED", (
            f"expected COLLECTED, got {untouched['status']} "
            "for the pledge that was never refunded"
        )

    def test_refunding_every_collected_pledge_drains_all_four_buckets(self):
        """The first bucket drains too, rather than staying stuck at its target.

        PRD: "A successful refund sets the pledge's `status` to `REFUNDED` and recomputes `funds_collected_cents` and the four buckets from scratch."

        Design: Difficulty/compensating_invariant/pledge_collect_then_refund_conserves_project_funds_and_allocations
        """
        scenario = _setup_quoted_project_with_two_pledges()
        project_id = scenario["project"]["id"]

        fx.collect_pledge(scenario["pledge_a"]["id"])
        fx.collect_pledge(scenario["pledge_b"]["id"])
        fx.refund_pledge(scenario["pledge_b"]["id"])
        fx.refund_pledge(scenario["pledge_a"]["id"])

        assert _fund_state(project_id) == BUCKETS_DRAINED, (
            f"expected {BUCKETS_DRAINED}, got {_fund_state(project_id)} "
            "once every collected pledge has been refunded"
        )

    def test_fundraising_never_expires_the_issued_quote(self):
        """Neither a collection nor a refund is one of the five expiry reasons.

        PRD: "Quotes expire from `ISSUED` for five distinct reasons, and all five must be implemented: a newer quote is issued for the same project, a sibling quote is accepted, a community review closes below threshold, the project is cancelled, or hop four of a standard supersession fires."

        Design: Difficulty/compensating_invariant/pledge_collect_then_refund_conserves_project_funds_and_allocations
        """
        scenario = _setup_quoted_project_with_two_pledges()
        quote_id = scenario["quote"]["id"]

        fx.collect_pledge(scenario["pledge_a"]["id"])
        fx.collect_pledge(scenario["pledge_b"]["id"])
        fx.refund_pledge(scenario["pledge_b"]["id"])
        fx.refund_pledge(scenario["pledge_a"]["id"])

        quote = fx.get_quote(quote_id)
        assert quote["status"] == "ISSUED", (
            f"expected ISSUED, got {quote['status']} after the fundraising traffic"
        )
        assert quote["total_cents"] == QUOTE_TOTAL_CENTS, (
            f"expected {QUOTE_TOTAL_CENTS}, got {quote['total_cents']} for total_cents"
        )

    def test_collecting_and_refunding_leave_the_design_state_alone(self):
        """Money moves; the design lifecycle does not.

        PRD: "On success the pledge's `status` becomes `COLLECTED`, the project's `funds_collected_cents` and all four allocation buckets are recomputed from scratch, and both the pledge's and the project's `version` are incremented by one."

        Design: Difficulty/compensating_invariant/pledge_collect_then_refund_conserves_project_funds_and_allocations
        """
        scenario = _setup_quoted_project_with_two_pledges()
        project_id = scenario["project"]["id"]
        assert fx.get_project(project_id)["design_status"] == "DESIGN_APPROVED", (
            "expected DESIGN_APPROVED, got "
            f"{fx.get_project(project_id)['design_status']} before any collection"
        )

        for step in (
            lambda: fx.collect_pledge(scenario["pledge_a"]["id"]),
            lambda: fx.collect_pledge(scenario["pledge_b"]["id"]),
            lambda: fx.refund_pledge(scenario["pledge_b"]["id"]),
            lambda: fx.refund_pledge(scenario["pledge_a"]["id"]),
        ):
            step()
            project = fx.get_project(project_id)
            assert project["design_status"] == "DESIGN_APPROVED", (
                f"expected DESIGN_APPROVED, got {project['design_status']} "
                "after a fundraising operation"
            )


# Job A runs 2026-08-06..08 with a crew of 4 (12 crew-days) and job B runs
# 2026-08-10..11 with a crew of 2 (4 crew-days), so the ledger reads 16.
JOB_A_START = "2026-08-06"
JOB_A_END = "2026-08-08"
JOB_A_CREW = 4
JOB_A_CREW_DAYS = 12
JOB_B_START = "2026-08-10"
JOB_B_END = "2026-08-11"
JOB_B_CREW = 2
JOB_B_CREW_DAYS = 4
BOTH_JOBS_CREW_DAYS = 16

# 2026-08-07..09 with a crew of 3 is 9 crew-days, and it intersects job A.
REBOOK_START = "2026-08-07"
REBOOK_END = "2026-08-09"
REBOOK_CREW = 3
REBOOK_CREW_DAYS = 9


def _setup_installer_with_two_bookings() -> dict:
    """An ORDERED project whose installer holds both phased bookings."""
    scenario = fx.setup_job_scheduled(
        job_overrides={
            "scheduled_start_date": JOB_A_START,
            "scheduled_end_date": JOB_A_END,
            "crew_size": JOB_A_CREW,
        }
    )
    scenario["job_b"] = fx.book_second_job(
        scenario, JOB_B_START, JOB_B_END, crew_size=JOB_B_CREW
    )
    return scenario


def _committed_crew_days(scenario: dict) -> int:
    installer = fx.get_installer(scenario["installer"]["id"])
    a.assert_installer(installer)
    return installer["committed_crew_days"]


class TestJobCancellationConservesTheCrewDayLedger:
    """Two bookings, two cancellations, and the ledger walks back to zero."""

    def test_cancelling_each_job_restores_the_pre_booking_total(self):
        """16 crew-days unwind to 12 and then to 0, in the reverse booking order.

        PRD: "Because it is a full recompute, cancelling a job restores `committed_crew_days` to exactly the value it held before that job was created."

        Design: Difficulty/compensating_invariant/job_schedule_then_cancel_conserves_installer_committed_crew_days
        """
        scenario = _setup_installer_with_two_bookings()
        job_a = fx.get_job(scenario["job"]["id"])
        a.assert_booked_crew_days(job_a)
        assert job_a["booked_crew_days"] == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS}, got {job_a['booked_crew_days']} "
            "for the first booking's booked_crew_days"
        )
        assert scenario["job_b"]["booked_crew_days"] == JOB_B_CREW_DAYS, (
            f"expected {JOB_B_CREW_DAYS}, got {scenario['job_b']['booked_crew_days']} "
            "for the second booking's booked_crew_days"
        )
        assert _committed_crew_days(scenario) == BOTH_JOBS_CREW_DAYS, (
            f"expected {BOTH_JOBS_CREW_DAYS} committed crew days with both bookings "
            f"live, got {_committed_crew_days(scenario)}"
        )

        cancelled_b = fx.cancel_job(scenario["job_b"]["id"])
        a.assert_installation_job(cancelled_b)
        assert cancelled_b["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled_b['status']} for the second booking"
        )
        assert _committed_crew_days(scenario) == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS} committed crew days once the second booking "
            f"is cancelled, got {_committed_crew_days(scenario)}"
        )

        fx.cancel_job(scenario["job"]["id"])
        assert _committed_crew_days(scenario) == 0, (
            "expected 0 committed crew days once both bookings are cancelled, got "
            f"{_committed_crew_days(scenario)}"
        )

    def test_a_cancelled_job_keeps_its_own_booked_crew_days(self):
        """The aggregate excludes the cancelled job; the job's own field survives.

        PRD: "An installer's `committed_crew_days` is the sum of `booked_crew_days` over every job booked with that installer whose `status` is **not** one of `AUDIT_PASSED`, `AUDIT_FAILED` or `CANCELLED`; a finished or cancelled job no longer occupies the calendar."

        Design: Difficulty/compensating_invariant/job_schedule_then_cancel_conserves_installer_committed_crew_days
        """
        scenario = _setup_installer_with_two_bookings()
        before = _committed_crew_days(scenario)
        assert before == BOTH_JOBS_CREW_DAYS, (
            f"expected {BOTH_JOBS_CREW_DAYS}, got {before} before the cancellation"
        )

        fx.cancel_job(scenario["job_b"]["id"])

        cancelled_b = fx.get_job(scenario["job_b"]["id"])
        assert cancelled_b["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled_b['status']} for the second booking"
        )
        assert cancelled_b["booked_crew_days"] == JOB_B_CREW_DAYS, (
            f"expected {JOB_B_CREW_DAYS}, got {cancelled_b['booked_crew_days']} "
            "for the cancelled booking's own booked_crew_days"
        )
        a.assert_booked_crew_days(cancelled_b)
        assert _committed_crew_days(scenario) == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS} committed crew days, got "
            f"{_committed_crew_days(scenario)} once one of the two jobs is cancelled"
        )

    def test_cancellation_frees_the_calendar_for_a_previously_refused_window(self):
        """2026-08-07..09 is refused while job A lives and accepted once it dies.

        PRD: "Four admission checks then run against the installer's **other** jobs whose status is not one of the three excluded ones."

        Design: Difficulty/compensating_invariant/job_schedule_then_cancel_conserves_installer_committed_crew_days
        """
        scenario = _setup_installer_with_two_bookings()
        payload = f.job_payload(
            scenario["order"]["id"],
            scenario["installer"]["id"],
            scheduled_start_date=REBOOK_START,
            scheduled_end_date=REBOOK_END,
            crew_size=REBOOK_CREW,
        )

        refused = api_client.create_installation_job(payload, CONSULTANT)
        validate_error(refused, ApiErrorId.ERR_INSTALLER_BOOKING_CONFLICT.value, 409)

        fx.cancel_job(scenario["job_b"]["id"])
        fx.cancel_job(scenario["job"]["id"])
        assert _committed_crew_days(scenario) == 0, (
            "expected 0 committed crew days once both bookings are cancelled, got "
            f"{_committed_crew_days(scenario)}"
        )

        accepted = validate_success(
            api_client.create_installation_job(payload, CONSULTANT), 201
        )
        a.assert_installation_job(accepted)
        assert accepted["status"] == "SCHEDULED", (
            f"expected SCHEDULED, got {accepted['status']} for the re-booked window"
        )
        assert accepted["booked_crew_days"] == REBOOK_CREW_DAYS, (
            f"expected {REBOOK_CREW_DAYS}, got {accepted['booked_crew_days']} "
            "for a crew of 3 over three inclusive days"
        )
        assert _committed_crew_days(scenario) == REBOOK_CREW_DAYS, (
            f"expected {REBOOK_CREW_DAYS} committed crew days after the re-booking, "
            f"got {_committed_crew_days(scenario)}"
        )

    def test_cancelling_bookings_leaves_the_project_and_order_untouched(self):
        """The compensating action touches the job and the installer, nothing else.

        PRD: "Cancelling a job is the exact compensating action for creating one: it is permitted while the job's `status` is `SCHEDULED` or `IN_PROGRESS`, sets `status` to `CANCELLED`, recomputes `committed_crew_days` back to its pre-booking value, and increments both the job's and the installer's `version` by one."

        Design: Difficulty/compensating_invariant/job_schedule_then_cancel_conserves_installer_committed_crew_days
        """
        scenario = _setup_installer_with_two_bookings()
        project_id = scenario["project"]["id"]
        order_id = scenario["order"]["id"]

        for job_key in ("job_b", "job"):
            fx.cancel_job(scenario[job_key]["id"])
            project = fx.get_project(project_id)
            assert project["design_status"] == "ORDERED", (
                f"expected ORDERED, got {project['design_status']} "
                "after cancelling a booking"
            )
            order = fx.get_order(order_id)
            a.assert_order(order)
            assert order["production_status"] == "CREATED", (
                f"expected CREATED, got {order['production_status']} "
                "after cancelling a booking"
            )

        assert _committed_crew_days(scenario) == 0, (
            "expected 0 committed crew days once both bookings are cancelled, got "
            f"{_committed_crew_days(scenario)}"
        )
