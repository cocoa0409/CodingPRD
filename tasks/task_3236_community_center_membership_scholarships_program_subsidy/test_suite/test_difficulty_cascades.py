"""Transitive cascades: one action rippling through three entities."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    assert_branch_pool_invariants,
    assert_cents,
    make_member_headers,
)
from test_helpers import factories, fixtures


def _setup_session_with_roster(api):
    """Session in REG_OPEN with capacity 1: one REGISTERED, one WAITLISTED."""
    world = fixtures.setup_session_scenario(
        api, session_overrides={"capacity": 1}, base_fee_cents=5_000, member_priority_days=0
    )
    first = fixtures.create_member(api, world["branch"]["id"], full_name="Reg One", email="one@x.com")
    second = fixtures.create_member(api, world["branch"]["id"], full_name="Reg Two", email="two@x.com")
    reg_first = get_success_data(
        api.create_registration(
            factories.registration_payload(world["session"]["id"], first["id"], participant_name="Reg One"),
            FRONT_DESK_HEADERS,
        )
    )
    reg_second = get_success_data(
        api.create_registration(
            factories.registration_payload(world["session"]["id"], second["id"], participant_name="Reg Two"),
            FRONT_DESK_HEADERS,
        )
    )
    assert reg_first["status"] == "REGISTERED"
    assert reg_second["status"] == "WAITLISTED"
    world.update({"reg_first": reg_first, "reg_second": reg_second})
    return world


def test_session_cancel_cascades_through_registrations_to_reservation(api):
    """One session cancel refunds the roster, expires the waitlist, and releases
    the linked program reservation.

    PRD §3.5: "Cancelling a session, whether `SCHEDULED` or `REG_OPEN`, cascades
    broadly: every `REGISTERED` registration becomes `REFUNDED` and
    `enrolled_count` drops to zero, every `WAITLISTED` registration becomes
    `EXPIRED` and `waitlist_count` drops to zero, and any linked program
    reservation for the session in `REQUESTED` or `APPROVED` status is
    `CANCELLED`, releasing the space."

    Design: Difficulty/transitive_cascade/session_cancel_cascades_through_registrations_to_reservation
    """
    world = _setup_session_with_roster(api)

    # Linked PROGRAM reservation, approved, on the same space.
    reservation = fixtures.create_reservation(
        api,
        world["space"]["id"],
        PROGRAM_COORDINATOR_HEADERS,
        reservation_type="PROGRAM",
        start_at="2026-09-20T09:00:00Z",
        end_at="2026-09-20T10:00:00Z",
        session_id=world["session"]["id"],
    )
    get_success_data(api.approve_reservation(reservation["id"], BRANCH_DIRECTOR_HEADERS))

    cancelled = get_success_data(api.cancel_session(world["session"]["id"], PROGRAM_COORDINATOR_HEADERS))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["enrolled_count"] == 0
    assert cancelled["waitlist_count"] == 0

    reg_first = get_success_data(api.get_registration(world["reg_first"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert reg_first["status"] == "REFUNDED"
    reg_second = get_success_data(api.get_registration(world["reg_second"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert reg_second["status"] == "EXPIRED"
    reservation = get_success_data(api.get_reservation(reservation["id"], BRANCH_DIRECTOR_HEADERS))
    assert reservation["status"] == "CANCELLED"




def test_membership_cancel_cascades_through_award_to_branch_pool(api):
    """Cancelling an awarded membership expires the application, and the expiry
    releases the pool obligation.

    PRD §3.3: "Cancellation is terminal, releases any approved award exactly as
    lapse does, resets the membership's `assistance_pct` to 0, and decrements
    the branch's `active_membership_count`."
    PRD §3.4: "Expiry releases the obligation: the branch's
    `scholarship_pool_obligated_cents` decreases by `award_obligation_cents`,
    raising the available pool accordingly."

    Design: Difficulty/transitive_cascade/membership_cancel_cascades_through_award_to_branch_pool
    """
    world = fixtures.setup_approved_award(api, pool_cents=200_000)

    before = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(before["scholarship_pool_obligated_cents"], 72_000, "branch.pool_obligated before")
    assert_cents(before["scholarship_pool_available_cents"], 128_000, "branch.pool_available before")

    cancelled = get_success_data(
        api.cancel_membership(world["membership"]["id"], make_member_headers(world["member"]["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["assistance_pct"] == 0

    application = get_success_data(api.get_application(world["application"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert application["status"] == "EXPIRED"

    after = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(after["scholarship_pool_obligated_cents"], 0, "branch.pool_obligated after")
    assert_cents(after["scholarship_pool_available_cents"], 200_000, "branch.pool_available after")
    assert_cents(after["active_membership_count"], 0, "branch.active_membership_count after")
    assert_branch_pool_invariants(after)


def test_held_membership_cancel_releases_the_award_identically(api):
    """The cascade is identical from ON_HOLD as from ACTIVE.

    PRD §3.3: "A `Member` or `BranchDirector` may cancel from either `ACTIVE` or
    `ON_HOLD`. Cancellation is terminal, releases any approved award exactly as
    lapse does, resets the membership's `assistance_pct` to 0, and decrements
    the branch's `active_membership_count`."

    Design: Difficulty/transitive_cascade/membership_cancel_cascades_through_award_to_branch_pool
    """
    world = fixtures.setup_approved_award(api, pool_cents=200_000)
    member_headers = make_member_headers(world["member"]["id"])

    get_success_data(api.hold_membership(world["membership"]["id"], {"hold_until": "2026-11-15"}, member_headers))
    held = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert held["status"] == "ON_HOLD"

    cancelled = get_success_data(api.cancel_membership(world["membership"]["id"], member_headers))
    assert cancelled["status"] == "CANCELLED"

    application = get_success_data(api.get_application(world["application"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert application["status"] == "EXPIRED"

    branch = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch["scholarship_pool_obligated_cents"], 0, "branch.pool_obligated after cancel")
    assert_cents(branch["scholarship_pool_available_cents"], 200_000, "branch.pool_available after cancel")
    assert_cents(branch["active_membership_count"], 0, "branch.active_membership_count after cancel")
