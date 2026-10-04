"""Cross-entity state dependencies: one entity's state gates another's action."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    assert_cents,
    make_member_headers,
)
from test_helpers import factories, fixtures


def test_donation_receive_is_gated_by_campaign_active(api):
    """The same receive call fails while the campaign is DRAFT and succeeds
    after activation.

    PRD §3.7: "Receipt is the money-arrives moment, performed by a
    `BranchDirector` or `AssociationAdmin` and legal only while the campaign is
    `ACTIVE`; receiving against a draft or closed campaign is
    `ERR_CAMPAIGN_NOT_ACTIVE`."
    PRD §3.7: "A pledge sits in `PLEDGED` status and affects nothing — no
    campaign totals move and no branch pool is credited."

    Design: Difficulty/cross_entity_state_dependency/donation_receive_gated_by_campaign_active
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    donation = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=10_000, designation="GENERAL"
    )

    validate_error(api.receive_donation(donation["id"], BRANCH_DIRECTOR_HEADERS), "ERR_CAMPAIGN_NOT_ACTIVE")

    # The failed receive changed nothing.
    donation_now = get_success_data(api.get_donation(donation["id"], BRANCH_DIRECTOR_HEADERS))
    assert donation_now["status"] == "PLEDGED"
    campaign_now = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(campaign_now["base_raised_cents"], 0, "campaign.base_raised_cents while DRAFT")

    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    received = get_success_data(api.receive_donation(donation["id"], BRANCH_DIRECTOR_HEADERS))
    assert received["status"] == "RECEIVED"
    campaign_now = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(campaign_now["base_raised_cents"], 10_000, "campaign.base_raised_cents after receive")


def test_receive_after_close_is_still_gated_by_campaign_state(api):
    """The gate holds on both sides of ACTIVE: a pledge left over at close can
    never be received.

    PRD §3.7: "Receipt is the money-arrives moment, performed by a
    `BranchDirector` or `AssociationAdmin` and legal only while the campaign is
    `ACTIVE`; receiving against a draft or closed campaign is
    `ERR_CAMPAIGN_NOT_ACTIVE`."
    PRD §3.7: "Donations still `PLEDGED` at close remain `PLEDGED` but can no
    longer be received."

    Design: Difficulty/cross_entity_state_dependency/donation_receive_gated_by_campaign_active
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    donation = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=10_000, designation="GENERAL"
    )

    campaign_now = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    get_success_data(
        api.close_campaign(
            campaign["id"],
            {"expected_campaign_version": campaign_now["version"]},
            ASSOCIATION_ADMIN_HEADERS,
        )
    )

    validate_error(api.receive_donation(donation["id"], BRANCH_DIRECTOR_HEADERS), "ERR_CAMPAIGN_NOT_ACTIVE")
    donation_now = get_success_data(api.get_donation(donation["id"], BRANCH_DIRECTOR_HEADERS))
    assert donation_now["status"] == "PLEDGED"


def test_registration_window_follows_session_status_and_priority_window(api):
    """Registration legality tracks the session's clock-driven status and the
    sub-window inside REG_OPEN.

    PRD §3.5: "Registration is only accepted while the session is `REG_OPEN`;
    before the window opens or after it closes the attempt is
    `ERR_REGISTRATION_WINDOW_CLOSED`, and a session already closed to the
    waitlist rejects with `ERR_SESSION_FULL`."
    PRD §3.5: "During the member-priority window only `HOME_MEMBER` registrants
    are accepted — everyone else is turned away with `ERR_MEMBER_PRIORITY_ONLY`."
    PRD §3.5: "Two system-computed dates govern enrollment: `public_opens_on` is
    the `start_on` date minus 14 days, and `member_opens_on` is
    `member_priority_days` earlier still, so the member-priority window runs
    from `member_opens_on` up to but not including `public_opens_on`."

    Design: Difficulty/cross_entity_state_dependency/registration_gated_by_session_reg_open_and_member_priority
    """
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name="Studio 1", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = fixtures.create_program(
        api, world["branch"]["id"], name="Hoops", kind="SPORTS", base_fee_cents=4_000, member_priority_days=3
    )
    session = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-20", end_on="2026-09-20",
        time_start="18:00", time_end="19:00", capacity=10,
    )
    category = fixtures.create_category(api, world["branch"]["id"])

    home = fixtures.create_member(api, world["branch"]["id"], full_name="Home Heather", email="h@x.com")
    get_success_data(
        api.create_membership(
            factories.membership_payload(world["branch"]["id"], category["id"], home["id"]),
            make_member_headers(home["id"]),
        )
    )
    walkin = fixtures.create_member(
        api, world["branch"]["id"], full_name="Walkin Will", email="w@x.com", birth_date="1992-02-02"
    )

    def register(member):
        return api.create_registration(
            {
                "session_id": session["id"],
                "member_id": member["id"],
                "participant_name": member["full_name"],
                "participant_birth_date": member["birth_date"],
            },
            make_member_headers(member["id"]),
        )

    # member_opens_on = 2026-09-20 - 14 - 3 = 2026-09-03; public_opens_on = 2026-09-06.
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    validate_error(register(walkin), "ERR_REGISTRATION_WINDOW_CLOSED")

    fixtures.set_clock(api, "2026-09-04T00:00:00Z")
    validate_error(register(walkin), "ERR_MEMBER_PRIORITY_ONLY")

    home_registration = get_success_data(register(home))
    assert home_registration["status"] == "REGISTERED"
    assert home_registration["registrant_class"] == "HOME_MEMBER"

    fixtures.set_clock(api, "2026-09-07T00:00:00Z")
    walkin_registration = get_success_data(register(walkin))
    assert walkin_registration["status"] == "REGISTERED"
    assert walkin_registration["registrant_class"] == "NON_MEMBER"
    assert_cents(walkin_registration["fee_charged_cents"], 6_000, "registration.fee_charged_cents")


def test_registration_after_close_registration_is_rejected(api):
    """Closing registration by hand ends the window regardless of the clock.

    PRD §3.5: "Registration is only accepted while the session is `REG_OPEN`;
    before the window opens or after it closes the attempt is
    `ERR_REGISTRATION_WINDOW_CLOSED`, and a session already closed to the
    waitlist rejects with `ERR_SESSION_FULL`."
    PRD §3.5: "`REG_OPEN` → `REG_CLOSED` at the end of the `start_on` day, or
    earlier when a `ProgramCoordinator` or `BranchDirector` closes registration
    by hand"

    Design: Difficulty/cross_entity_state_dependency/registration_gated_by_session_reg_open_and_member_priority
    """
    world = fixtures.setup_session_scenario(
        api, base_fee_cents=4_000, member_priority_days=3
    )
    walkin = fixtures.create_member(
        api, world["branch"]["id"], full_name="Walkin Will", email="w@x.com", birth_date="1992-02-02"
    )

    # REG_OPEN with the public window running; then close by hand.
    get_success_data(api.close_registration(world["session"]["id"], PROGRAM_COORDINATOR_HEADERS))
    validate_error(
        api.create_registration(
            {
                "session_id": world["session"]["id"],
                "member_id": walkin["id"],
                "participant_name": "Walkin Will",
                "participant_birth_date": "1992-02-02",
            },
            make_member_headers(walkin["id"]),
        ),
        "ERR_REGISTRATION_WINDOW_CLOSED",
    )
