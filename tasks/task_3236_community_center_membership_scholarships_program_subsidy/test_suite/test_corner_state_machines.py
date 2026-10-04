"""Corner probes against the state machines: invalid transitions, terminal
lockdown, waitlist promotion order, clock-driven windows, delinquency."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    assert_cents,
    make_member_headers,
)
from test_helpers import factories, fixtures


def test_approve_from_submitted_is_invalid_state(api):
    """Approval is declared only from UNDER_REVIEW; a fresh application rejects it.

    PRD §3.4: "A `BranchDirector` moves the application `SUBMITTED` →
    `UNDER_REVIEW` (a review attempt from any other status is `ERR_INVALID_STATE`)."
    PRD §3.4: "the final `income_ratio` is recomputed from the verified inputs
    and must yield an `award_pct` among 0.25, 0.50, or 0.75"

    Design: Corner/state_machines/approve_from_submitted_returns_invalid_state
    """
    world = fixtures.setup_membership(api)
    application = fixtures.submit_application(api, world)
    assert application["status"] == "SUBMITTED"

    response = api.approve_application(
        application["id"],
        {"expected_membership_version": world["membership"]["version"]},
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(response, "ERR_INVALID_STATE")

    current = get_success_data(api.get_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "SUBMITTED"
    branch = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch["scholarship_pool_obligated_cents"], 0, "branch.pool_obligated")


def test_cancelled_membership_is_terminal_for_all_actions(api):
    """Once CANCELLED, resume and reinstate are rejected and the row never moves.

    PRD §3.3: "Cancellation is terminal, releases any approved award exactly as
    lapse does, resets the membership's `assistance_pct` to 0, and decrements
    the branch's `active_membership_count`."
    PRD §3.3: "A `BranchDirector` may reinstate a `LAPSED` membership within 90
    days of `lapsed_on` — attempting it later, or while any draft of the
    membership remains `FAILED` and unsettled, is rejected with
    `ERR_REINSTATE_WINDOW_PASSED`."

    Design: Corner/state_machines/cancelled_membership_is_terminal_for_all_actions
    """
    world = fixtures.setup_membership(api)
    member_headers = make_member_headers(world["member"]["id"])
    membership = world["membership"]

    get_success_data(api.cancel_membership(membership["id"], member_headers))

    resume_response = api.resume_membership(membership["id"], member_headers)
    assert resume_response.status_code == 409
    assert resume_response.json()["data"]["error_id"] in ("ERR_INVALID_STATE", "ERR_ALREADY_TERMINAL")

    reinstate_response = api.reinstate_membership(membership["id"], BRANCH_DIRECTOR_HEADERS)
    assert reinstate_response.status_code == 409
    assert reinstate_response.json()["data"]["error_id"] in (
        "ERR_INVALID_STATE",
        "ERR_ALREADY_TERMINAL",
        "ERR_REINSTATE_WINDOW_PASSED",
    )

    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "CANCELLED"


def test_waitlist_promotion_is_fifo_and_positions_compact(api):
    """Cancelling the only REGISTERED seat promotes the lowest waitlist position,
    computes the promoted fee at promotion time, and compacts the rest.

    PRD §3.5: "Cancellation decrements `enrolled_count`, then promotes the
    head-of-line waitlisted registration — the lowest `waitlist_position`, with
    ties broken by earliest `created_at`, never by id — to `REGISTERED`,
    computing its `fee_charged_cents` at promotion time, incrementing
    `enrolled_count`, decrementing `waitlist_count`, nulling its
    `waitlist_position`, and shifting every remaining waitlisted position down
    by one."

    Design: Corner/state_machines/waitlist_promotion_is_fifo_with_created_at_tiebreak
    """
    world = fixtures.setup_session_scenario(
        api,
        session_overrides={"capacity": 1},
        base_fee_cents=4_000,
        member_priority_days=0,
    )
    members = [
        fixtures.create_member(
            api, world["branch"]["id"], full_name=name, email=email, birth_date="1990-01-01"
        )
        for name, email in (("A One", "a@x.com"), ("B Two", "b@x.com"), ("C Three", "c@x.com"))
    ]
    registrations = [
        get_success_data(
            api.create_registration(
                factories.registration_payload(
                    world["session"]["id"], member["id"], participant_name=member["full_name"]
                ),
                FRONT_DESK_HEADERS,
            )
        )
        for member in members
    ]
    reg_a, reg_b, reg_c = registrations
    assert reg_a["status"] == "REGISTERED"
    assert reg_b["status"] == "WAITLISTED" and reg_b["waitlist_position"] == 1
    assert reg_c["status"] == "WAITLISTED" and reg_c["waitlist_position"] == 2

    get_success_data(
        api.cancel_registration(reg_a["id"], make_member_headers(members[0]["id"]))
    )

    promoted = get_success_data(api.get_registration(reg_b["id"], BRANCH_DIRECTOR_HEADERS))
    assert promoted["status"] == "REGISTERED"
    assert promoted["waitlist_position"] is None
    # Non-member gross: 4000 * 1.5 = 6000, computed at promotion time.
    assert_cents(promoted["fee_charged_cents"], 6_000, "promoted.fee_charged_cents")

    shifted = get_success_data(api.get_registration(reg_c["id"], BRANCH_DIRECTOR_HEADERS))
    assert shifted["status"] == "WAITLISTED"
    assert shifted["waitlist_position"] == 1

    session = get_success_data(api.get_session(world["session"]["id"], PROGRAM_COORDINATOR_HEADERS))
    assert session["enrolled_count"] == 1
    assert session["waitlist_count"] == 1


def test_session_status_follows_the_logical_clock(api):
    """The session lifecycle flips purely on clock boundaries with no action calls.

    PRD §2.6: "a session flips from `SCHEDULED` to `REG_OPEN` when the clock
    reaches `member_opens_on`, from `REG_OPEN` to `REG_CLOSED` at the end of its
    `start_on` day, and from `REG_CLOSED` to `COMPLETED` once the clock passes
    `end_on`"
    PRD §3.5: "Two system-computed dates govern enrollment: `public_opens_on` is
    the `start_on` date minus 14 days, and `member_opens_on` is
    `member_priority_days` earlier still"

    Design: Corner/state_machines/clock_driven_session_window_transitions
    """
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name="Studio 1", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = fixtures.create_program(
        api, world["branch"]["id"], name="Hoops", kind="SPORTS", base_fee_cents=4_000, member_priority_days=3
    )
    session = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-20", end_on="2026-09-21",
        time_start="18:00", time_end="19:00", capacity=10,
    )

    def status():
        return get_success_data(api.get_session(session["id"], PROGRAM_COORDINATOR_HEADERS))["status"]

    # member_opens_on = 2026-09-03; public_opens_on = 2026-09-06; start_on 2026-09-20; end_on 2026-09-21.
    assert status() == "SCHEDULED"
    fixtures.set_clock(api, "2026-09-04T00:00:00Z")
    assert status() == "REG_OPEN"
    fixtures.set_clock(api, "2026-09-21T00:00:00Z")
    assert status() == "REG_CLOSED"
    fixtures.set_clock(api, "2026-09-22T00:00:00Z")
    assert status() == "COMPLETED"


def test_third_failure_flips_delinquent_and_45_days_lapses(api):
    """Failures one and two sit in RETRY_PENDING; the third is DELINQUENT; 46
    days later the membership is LAPSED; the attempt cap rejects a fourth fail.

    PRD §3.3: "Recording a failed collection attempt — a `BranchDirector` or
    `AssociationAdmin` action — is legal while the draft is `PENDING` or
    `FAILED` and its `attempt_count` is below 3. Each failure increments
    `attempt_count` and sets the draft's `status` to `FAILED`. When the count
    reaches 3, the membership's `draft_status` flips to `DELINQUENT` and
    `delinquent_since` records the current date; before that threshold the draft
    dimension sits in `RETRY_PENDING`."
    PRD §2.6: "a membership lapses after its draft status has remained
    `DELINQUENT` for 45 consecutive days"

    Design: Corner/state_machines/draft_fail_three_times_flips_delinquent_and_45_days_lapses
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]
    draft = fixtures.first_draft_of(api, membership["id"])

    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    midway = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert midway["status"] == "ACTIVE"
    assert midway["draft_status"] == "RETRY_PENDING"

    get_success_data(api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS))
    delinquent = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert delinquent["draft_status"] == "DELINQUENT"
    assert delinquent["delinquent_since"] == "2026-09-01"

    # A fourth fail on the same FAILED draft is rejected: attempt_count is at 3.
    fourth = api.fail_draft(draft["id"], BRANCH_DIRECTOR_HEADERS)
    assert fourth.status_code == 409

    # 46 days of consecutive delinquency: the membership lapses.
    fixtures.set_clock(api, "2026-10-17T00:00:00Z")
    lapsed = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert lapsed["status"] == "LAPSED"
    assert lapsed["lapsed_on"] is not None
