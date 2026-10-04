"""Boundary precision: the >= vs > distinction at a numeric threshold, and the
empty-set boundary on the licensed-ratio cap."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    assert_cents,
    assert_fraction,
    make_member_headers,
)
from test_helpers import fixtures


def test_attainment_exactly_half_takes_the_match_tier(api):
    """Attainment 0.4999 stays at match 0; exactly 0.5000 takes the 0.10 tier.

    PRD §3.7: "the attainment is `base_raised_cents` divided by `goal_cents`,
    rounded to four decimal places half-up before tier comparison, and the
    `match_pct` tier is 0 when attainment is below 0.50, 0.10 when attainment is
    exactly 0.50 or above but below 1.00, and 0.25 when attainment is exactly
    1.00 or above. The `matched_raised_cents` is then `base_raised_cents`
    multiplied by one plus the `match_pct`, rounded half-up to integer cents."

    Design: Difficulty/boundary_precision_check/campaign_attainment_exactly_half_gets_match_tier
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))

    # 49,994 / 100,000 = 0.49994 -> rounds to 0.4999 at four decimals: below the tier.
    below = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=49_994, designation="GENERAL"
    )
    get_success_data(api.receive_donation(below["id"], BRANCH_DIRECTOR_HEADERS))
    campaign_below = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(campaign_below["base_raised_cents"], 49_994, "campaign.base_raised_cents at 49994")
    assert_fraction(campaign_below["match_pct"], 0, "campaign.match_pct at attainment 0.4999")
    assert_cents(campaign_below["matched_raised_cents"], 49_994, "campaign.matched at 49994")

    # Six more cents reach exactly 0.5000 attainment: the tier is inclusive.
    penny = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=6, designation="GENERAL"
    )
    get_success_data(api.receive_donation(penny["id"], BRANCH_DIRECTOR_HEADERS))
    campaign_at = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(campaign_at["base_raised_cents"], 50_000, "campaign.base_raised_cents at 50000")
    assert_fraction(campaign_at["match_pct"], 0.10, "campaign.match_pct at attainment 0.5000")
    assert_cents(campaign_at["matched_raised_cents"], 55_000, "campaign.matched at 50000")


def test_attainment_exactly_full_takes_the_top_match_tier(api):
    """Attainment 0.9999 takes the 0.10 tier; exactly 1.0000 takes 0.25.

    PRD §3.7: "the `match_pct` tier is 0 when attainment is below 0.50, 0.10
    when attainment is exactly 0.50 or above but below 1.00, and 0.25 when
    attainment is exactly 1.00 or above."

    Design: Difficulty/boundary_precision_check/campaign_attainment_exactly_half_gets_match_tier
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))

    # 99,994 / 100,000 = 0.99994 -> rounds to 0.9999 at four decimals: the 0.10 tier.
    below = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=99_994, designation="GENERAL"
    )
    get_success_data(api.receive_donation(below["id"], BRANCH_DIRECTOR_HEADERS))
    campaign_below = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_fraction(campaign_below["match_pct"], 0.10, "campaign.match_pct at attainment 0.9999")
    assert_cents(campaign_below["matched_raised_cents"], 109_993, "campaign.matched at 99994")

    penny = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=6, designation="GENERAL"
    )
    get_success_data(api.receive_donation(penny["id"], BRANCH_DIRECTOR_HEADERS))
    campaign_at = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(campaign_at["base_raised_cents"], 100_000, "campaign.base_raised_cents at 100000")
    assert_fraction(campaign_at["match_pct"], 0.25, "campaign.match_pct at attainment 1.0000")
    assert_cents(campaign_at["matched_raised_cents"], 125_000, "campaign.matched at 100000")


def test_unstaffed_licensed_childcare_accepts_zero_children(api):
    """An unstaffed licensed session has a statutory cap of zero: every
    registration waitlists even though raw seats remain.

    PRD §3.5: "For a licensed-childcare program the statutory cap is the
    program's `licensed_children_per_staff` multiplied by the number of assigned
    staff, and the effective capacity is the smaller of the session capacity and
    that statutory cap; an unstaffed licensed session therefore accepts zero
    children and every registration waitlists."
    PRD §3.5: "When the enrolled count plus one fits within effective capacity
    the registration is `REGISTERED` and `enrolled_count` rises; otherwise it
    becomes `WAITLISTED` with `waitlist_position` one past the current
    `waitlist_count` — waitlisting is a normal outcome, not an error."

    Design: Difficulty/boundary_precision_check/unstaffed_licensed_childcare_accepts_zero_registrations
    """
    world = fixtures.setup_session_scenario(
        api,
        session_overrides={"capacity": 10},
        name="Toddler Care",
        kind="CHILDCARE",
        base_fee_cents=30_000,
        member_priority_days=0,
        is_licensed_childcare=True,
        licensed_children_per_staff=4,
        max_age=5,
    )
    parent = fixtures.create_member(
        api, world["branch"]["id"], full_name="Parent One", email="p1@x.com", birth_date="1990-01-01"
    )

    registration = get_success_data(
        api.create_registration(
            {
                "session_id": world["session"]["id"],
                "member_id": parent["id"],
                "participant_name": "Kid One",
                "participant_birth_date": "2023-03-01",
            },
            make_member_headers(parent["id"]),
        )
    )
    assert registration["status"] == "WAITLISTED"
    assert registration["waitlist_position"] == 1

    session = get_success_data(api.get_session(world["session"]["id"], PROGRAM_COORDINATOR_HEADERS))
    assert session["enrolled_count"] == 0
    assert session["waitlist_count"] == 1

    # One staff member raises the statutory cap to 4 and promotes the head of line.
    get_success_data(
        api.assign_staff(world["session"]["id"], {"staff_member_ids": [parent["id"]]}, PROGRAM_COORDINATOR_HEADERS)
    )
    promoted = get_success_data(api.get_registration(registration["id"], BRANCH_DIRECTOR_HEADERS))
    assert promoted["status"] == "REGISTERED"
    session = get_success_data(api.get_session(world["session"]["id"], PROGRAM_COORDINATOR_HEADERS))
    assert session["enrolled_count"] == 1
    assert session["waitlist_count"] == 0


def test_licensed_session_registers_up_to_the_statutory_cap(api):
    """With one staff member and ratio 4 the statutory cap is 4, smaller than
    the raw capacity 10: the fifth registration waitlists.

    PRD §3.5: "For a licensed-childcare program the statutory cap is the
    program's `licensed_children_per_staff` multiplied by the number of assigned
    staff, and the effective capacity is the smaller of the session capacity and
    that statutory cap"

    Design: Difficulty/boundary_precision_check/unstaffed_licensed_childcare_accepts_zero_registrations
    """
    world = fixtures.setup_session_scenario(
        api,
        session_overrides={"capacity": 10},
        name="Toddler Care",
        kind="CHILDCARE",
        base_fee_cents=30_000,
        member_priority_days=0,
        is_licensed_childcare=True,
        licensed_children_per_staff=4,
        max_age=5,
    )
    staffer = fixtures.create_member(
        api, world["branch"]["id"], full_name="Staff Sue", email="staff@x.com", birth_date="1985-05-05"
    )
    get_success_data(
        api.assign_staff(
            world["session"]["id"], {"staff_member_ids": [staffer["id"]]}, PROGRAM_COORDINATOR_HEADERS
        )
    )

    registrations = []
    for index in range(5):
        parent = fixtures.create_member(
            api,
            world["branch"]["id"],
            full_name=f"Parent {index}",
            email=f"parent{index}@x.com",
            birth_date="1990-01-01",
        )
        registrations.append(
            get_success_data(
                api.create_registration(
                    {
                        "session_id": world["session"]["id"],
                        "member_id": parent["id"],
                        "participant_name": f"Kid {index}",
                        "participant_birth_date": "2023-03-01",
                    },
                    make_member_headers(parent["id"]),
                )
            )
        )

    for registration in registrations[:4]:
        assert registration["status"] == "REGISTERED", "the first four children fit the statutory cap"
    assert registrations[4]["status"] == "WAITLISTED", "the fifth child exceeds ratio 4 x 1 staff"
    assert registrations[4]["waitlist_position"] == 1

    session = get_success_data(api.get_session(world["session"]["id"], PROGRAM_COORDINATOR_HEADERS))
    assert session["enrolled_count"] == 4
    assert session["waitlist_count"] == 1


