"""Corner probes against the validation tiers: credentials, uniqueness, schema,
composition, temporal windows and age gates."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    headers_without_role,
    make_member_headers,
)
from test_helpers import factories, fixtures


def test_missing_role_header_is_unauthenticated(api):
    """No X-User-Role at all is a 401, ahead of every other check.

    PRD §2.1: "A request missing `X-User-Role`, carrying a role string the API
    does not declare, or omitting `X-User-ID` when the role is entity-backed is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    response = api.list_branches(headers_without_role("someone"))
    validate_error(response, "ERR_UNAUTHENTICATED")


def test_duplicate_member_email_is_rejected_across_branches(api):
    """Member email is unique across the whole association.

    PRD §3.1: "People enter the system as `Member` records registered by
    `FrontDesk`, `BranchDirector`, or `AssociationAdmin` staff, with
    `full_name`, an `email` that must be unique across the association (a
    duplicate is `ERR_DUPLICATE_EMAIL`, HTTP 409)"

    Design: Corner/validations/duplicate_member_email_rejected
    """
    world = fixtures.setup_association_and_branch(api)
    branch_up = fixtures.create_branch(api, world["association"]["id"], code="UP", name="Uptown")

    fixtures.create_member(api, world["branch"]["id"], full_name="First User", email="dup@x.com")
    response = api.create_member(
        factories.member_payload(branch_up["id"], full_name="Second User", email="dup@x.com", birth_date="1995-05-05"),
        FRONT_DESK_HEADERS,
    )
    validate_error(response, "ERR_DUPLICATE_EMAIL")


def test_application_without_documentation_is_rejected(api):
    """An empty documentation array fails schema validation with the dedicated 400.

    PRD §3.4: "At least one such document kind is required; an empty or
    unrecognized documentation array is rejected with
    `ERR_DOCUMENTATION_MISSING` (HTTP 400)."

    Design: Corner/validations/scholarship_submit_without_documentation_rejected
    """
    world = fixtures.setup_membership(api)
    response = api.create_application(
        factories.application_payload(
            world["branch"]["id"],
            world["membership"]["id"],
            world["member"]["id"],
            household_size=2,
            annual_income_cents=1_500_000,
            documentation=[],
        ),
        make_member_headers(world["member"]["id"]),
    )
    validate_error(response, "ERR_DOCUMENTATION_MISSING")

    rows, meta = validate_paginated(
        api.list_applications(
            BRANCH_DIRECTOR_HEADERS, {"membership_id": world["membership"]["id"]}
        )
    )
    assert rows == [] and meta["total_count"] == 0


def test_household_cap_blocks_a_child_on_a_two_adult_category(api):
    """Ages derive from birth_date at join time; a dependent over the cap is a 409.

    PRD §3.2: "Household composition is validated against the category caps at
    join time. Adults are members aged at least 18, dependents are younger than
    18, both derived from each member's `birth_date`; a roster whose adult count
    exceeds `max_adults` or whose dependent count exceeds `max_dependents` is
    rejected with `ERR_HOUSEHOLD_CAP_EXCEEDED`."

    Design: Corner/validations/household_cap_exceeded_blocks_family_join
    """
    world = fixtures.setup_branch_with_category(
        api, name="Two Adult", household_type="TWO_ADULT", monthly_dues_cents=12_000,
        max_adults=2, max_dependents=0, joining_fee_cents=5_000,
    )
    adult = fixtures.create_member(api, world["branch"]["id"], full_name="Adult A", email="a@x.com", birth_date="1990-01-01")
    child = fixtures.create_member(api, world["branch"]["id"], full_name="Kid K", email="k@x.com", birth_date="2020-06-01")

    response = api.create_membership(
        factories.membership_payload(
            world["branch"]["id"], world["category"]["id"], adult["id"],
            member_ids=[adult["id"], child["id"]],
        ),
        FRONT_DESK_HEADERS,
    )
    validate_error(response, "ERR_HOUSEHOLD_CAP_EXCEEDED")

    rows, meta = validate_paginated(
        api.list_memberships(BRANCH_DIRECTOR_HEADERS, {"branch_id": world["branch"]["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_hold_window_bounds_thirty_and_one_eighty_days(api):
    """A 20-day hold and a 200-day hold both fail the window rule; the row stays ACTIVE.

    PRD §3.3: "The hold duration — `hold_until` measured from the current date —
    must be at least 30 days and at most 180 days, and `hold_until` must be in
    the future, else the request is rejected with `ERR_HOLD_WINDOW_INVALID`."

    Design: Corner/validations/hold_shorter_than_30_days_rejected
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]
    member_headers = make_member_headers(world["member"]["id"])

    validate_error(
        api.hold_membership(membership["id"], {"hold_until": "2026-09-21"}, member_headers),
        "ERR_HOLD_WINDOW_INVALID",
    )
    validate_error(
        api.hold_membership(membership["id"], {"hold_until": "2027-03-20"}, member_headers),
        "ERR_HOLD_WINDOW_INVALID",
    )

    current = get_success_data(api.get_membership(membership["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "ACTIVE"


def test_participant_age_outside_the_gate_is_rejected(api):
    """Age is computed at the session's start_on; a 30-year-old cannot join a
    program capped at 12.

    PRD §3.5: "The participant's age at the session's `start_on` must fall
    within the program's `min_age` to `max_age` inclusive, else
    `ERR_PARTICIPANT_AGE_INVALID`."

    Design: Corner/validations/participant_age_outside_gate_rejected
    """
    world = fixtures.setup_session_scenario(
        api, name="Kids Swim", base_fee_cents=5_000, member_priority_days=0, min_age=3, max_age=12
    )
    grown = fixtures.create_member(
        api, world["branch"]["id"], full_name="Grown Greg", email="g@x.com", birth_date="1996-01-01"
    )
    response = api.create_registration(
        factories.registration_payload(
            world["session"]["id"], grown["id"],
            participant_name="Grown Greg", participant_birth_date="1996-01-01",
        ),
        make_member_headers(grown["id"]),
    )
    validate_error(response, "ERR_PARTICIPANT_AGE_INVALID")

    session = get_success_data(api.get_session(world["session"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert session["enrolled_count"] == 0
    assert session["waitlist_count"] == 0


def test_member_only_program_rejects_non_members_and_welcomes_sibling_members(api):
    """member_only bars NON_MEMBER and RECIPROCITY_VISITOR; an ASSOCIATION_MEMBER
    from a sibling branch registers at the flat member fee.

    PRD §3.5: "A `member_only` program rejects `NON_MEMBER` and
    `RECIPROCITY_VISITOR` registrants with `ERR_MEMBER_ONLY_PROGRAM` regardless
    of window."
    PRD §3.8: "Home members of the association visiting a sibling branch are
    treated more warmly: an `ACTIVE` or `ON_HOLD` membership at any branch of
    the same association classifies the registrant as `ASSOCIATION_MEMBER`,
    paying the flat member `base_fee_cents` without surcharge, though the
    assistance discount applies only when the membership sits at the session's
    own branch."

    Design: Corner/validations/member_only_program_rejects_non_member
    """
    fixtures.set_clock(api)
    assoc = fixtures.create_association(api)
    branch_dt = fixtures.create_branch(api, assoc["id"], code="DT", name="Downtown")
    branch_up = fixtures.create_branch(api, assoc["id"], code="UP", name="Uptown", branch_goal_cents=500_000)

    space = fixtures.create_space(api, branch_dt["id"], name="Studio 1", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = fixtures.create_program(
        api, branch_dt["id"], name="Members Yoga", kind="SPORTS", base_fee_cents=2_000,
        member_priority_days=0, member_only=True,
    )
    session = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-20", end_on="2026-09-20",
        time_start="07:00", time_end="08:00", capacity=10,
    )

    category_up = fixtures.create_category(api, branch_up["id"], monthly_dues_cents=9_000)
    walkin = fixtures.create_member(api, branch_dt["id"], full_name="Walkin Will", email="w@x.com", birth_date="1992-02-02")
    sibling = fixtures.create_member(api, branch_up["id"], full_name="Sibling Sue", email="s@x.com", birth_date="1991-01-01")
    get_success_data(
        api.create_membership(
            factories.membership_payload(branch_up["id"], category_up["id"], sibling["id"]),
            FRONT_DESK_HEADERS,
        )
    )

    fixtures.set_clock(api, "2026-09-10T00:00:00Z")

    response = api.create_registration(
        factories.registration_payload(
            session["id"], walkin["id"], participant_name="Walkin Will", participant_birth_date="1992-02-02"
        ),
        make_member_headers(walkin["id"]),
    )
    validate_error(response, "ERR_MEMBER_ONLY_PROGRAM")

    accepted = get_success_data(
        api.create_registration(
            factories.registration_payload(
                session["id"], sibling["id"], participant_name="Sibling Sue", participant_birth_date="1991-01-01"
            ),
            make_member_headers(sibling["id"]),
        )
    )
    assert accepted["registrant_class"] == "ASSOCIATION_MEMBER"
    assert accepted["fee_charged_cents"] == 2_000
