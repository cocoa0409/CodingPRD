"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch. These helpers do that walking through the public
API only - no direct data writes - and return the created rows the test then
asserts against.

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import CLOCK_STARTUP_DEFAULT
from .test_users import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    make_member_headers,
)


# ═══ Tier 1: standing reference data ═══════════════════════════════════════

def set_clock(api: ApiClient, current_utc: str = CLOCK_STARTUP_DEFAULT) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ASSOCIATION_ADMIN_HEADERS))


def create_association(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_association(f.association_payload(**overrides), ASSOCIATION_ADMIN_HEADERS))


def create_branch(api: ApiClient, association_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_branch(f.branch_payload(association_id, **overrides), ASSOCIATION_ADMIN_HEADERS)
    )


def create_category(api: ApiClient, branch_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_category(f.category_payload(branch_id, **overrides), BRANCH_DIRECTOR_HEADERS)
    )


def create_member(api: ApiClient, home_branch_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_member(f.member_payload(home_branch_id, **overrides), FRONT_DESK_HEADERS)
    )


def create_space(api: ApiClient, branch_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_space(f.space_payload(branch_id, **overrides), BRANCH_DIRECTOR_HEADERS)
    )


def create_program(api: ApiClient, branch_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_program(f.program_payload(branch_id, **overrides), PROGRAM_COORDINATOR_HEADERS)
    )


def create_session(api: ApiClient, program_id: str, space_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_session(f.session_payload(program_id, space_id, **overrides), PROGRAM_COORDINATOR_HEADERS)
    )


def create_campaign(api: ApiClient, association_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_campaign(f.campaign_payload(association_id, **overrides), ASSOCIATION_ADMIN_HEADERS)
    )


def create_donation(api: ApiClient, campaign_id: str, branch_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_donation(f.donation_payload(campaign_id, branch_id, **overrides), BRANCH_DIRECTOR_HEADERS)
    )


def create_reservation(api: ApiClient, space_id: str, headers, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_reservation(f.reservation_payload(space_id, **overrides), headers))


def create_registration(api: ApiClient, session_id: str, member_id: str, headers=None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_registration(
            f.registration_payload(session_id, member_id, **overrides),
            headers or FRONT_DESK_HEADERS,
        )
    )


# ═══ Tier 2: entity hierarchy ══════════════════════════════════════════════

def setup_association_and_branch(api: ApiClient, **branch_overrides: Any) -> Dict[str, Any]:
    """Clock pinned at the startup instant; one association and one branch."""
    set_clock(api)
    assoc = create_association(api)
    branch = create_branch(api, assoc["id"], **branch_overrides)
    return {"association": assoc, "branch": branch}


def setup_branch_with_category(api: ApiClient, **category_overrides: Any) -> Dict[str, Any]:
    """Association + branch + one category (defaults: ADULT, dues 8000, no joining fee)."""
    world = setup_association_and_branch(api)
    category = create_category(api, world["branch"]["id"], **category_overrides)
    world["category"] = category
    return world


def setup_membership(api: ApiClient, **category_overrides: Any) -> Dict[str, Any]:
    """Association + branch + category + one member holding an ACTIVE membership."""
    world = setup_branch_with_category(api, **category_overrides)
    member = create_member(api, world["branch"]["id"])
    membership = get_success_data(
        api.create_membership(
            f.membership_payload(world["branch"]["id"], world["category"]["id"], member["id"]),
            FRONT_DESK_HEADERS,
        )
    )
    world.update({"member": member, "membership": membership})
    return world


def setup_funded_pool(
    api: ApiClient,
    amount_cents: int = 200_000,
    designation: str = "SCHOLARSHIP",
    **category_overrides: Any,
) -> Dict[str, Any]:
    """Membership world plus an ACTIVE campaign with one RECEIVED donation.

    The branch's scholarship pool holds ``amount_cents`` when the designation
    is SCHOLARSHIP; otherwise the gift only raises the campaign totals.
    """
    world = setup_membership(api, **category_overrides)
    campaign = create_campaign(api, world["association"]["id"], goal_cents=4_000_000)
    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    donation = create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=amount_cents, designation=designation
    )
    get_success_data(api.receive_donation(donation["id"], BRANCH_DIRECTOR_HEADERS))
    world.update({"campaign": campaign, "donation": donation})
    return world


# ═══ Tier 3: scholarship lifecycle shortcuts ═══════════════════════════════

def submit_application(
    api: ApiClient,
    world: Dict[str, Any],
    household_size: int = 1,
    annual_income_cents: int = 1_000_000,
    documentation: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File an application for the world's membership as the applying member."""
    return get_success_data(
        api.create_application(
            f.application_payload(
                world["branch"]["id"],
                world["membership"]["id"],
                world["member"]["id"],
                household_size=household_size,
                annual_income_cents=annual_income_cents,
                documentation=documentation,
                **overrides,
            ),
            make_member_headers(world["member"]["id"]),
        )
    )


def setup_application_under_review(
    api: ApiClient,
    household_size: int = 1,
    annual_income_cents: int = 1_000_000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Membership world + an application already moved to UNDER_REVIEW."""
    world = setup_membership(api, **kwargs)
    application = submit_application(
        api, world, household_size=household_size, annual_income_cents=annual_income_cents
    )
    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    world["application"] = application
    return world


def setup_approved_award(
    api: ApiClient,
    pool_cents: int = 200_000,
    household_size: int = 1,
    annual_income_cents: int = 1_000_000,
    **category_overrides: Any,
) -> Dict[str, Any]:
    """Funded pool + membership + an APPROVED application on that membership.

    With the defaults (income 1,000,000 on a one-person household against an
    AMI of 5,000,000) the ratio is 0.2000 and the award is 0.75.
    """
    world = setup_funded_pool(api, amount_cents=pool_cents, **category_overrides)
    application = submit_application(
        api, world, household_size=household_size, annual_income_cents=annual_income_cents
    )
    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(
        api.approve_application(
            application["id"],
            {"expected_membership_version": membership["version"]},
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    world["application"] = get_success_data(
        api.get_application(application["id"], BRANCH_DIRECTOR_HEADERS)
    )
    world["membership"] = get_success_data(
        api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS)
    )
    return world


# ═══ Tier 4: program/session scenarios ═════════════════════════════════════

def setup_session_scenario(
    api: ApiClient,
    clock: str = "2026-09-10T00:00:00Z",
    session_overrides: Optional[Dict[str, Any]] = None,
    **program_overrides: Any,
) -> Dict[str, Any]:
    """Association + branch + space + program + session, clock advanced so the
    session is inside its registration window (REG_OPEN with the defaults)."""
    world = setup_association_and_branch(api)
    space = create_space(api, world["branch"]["id"], name="Studio 1", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = create_program(api, world["branch"]["id"], **program_overrides)
    session = create_session(api, program["id"], space["id"], **(session_overrides or {}))
    set_clock(api, clock)
    world.update({"space": space, "program": program, "session": session})
    return world


# ═══ Tier 5: misc ══════════════════════════════════════════════════════════

def first_draft_of(api: ApiClient, membership_id: str) -> Dict[str, Any]:
    """The first REGULAR draft the membership's activation created."""
    rows, _meta = _list(api.list_membership_drafts(membership_id, BRANCH_DIRECTOR_HEADERS))
    assert rows, f"membership {membership_id} has no drafts at setup time"
    regular = [r for r in rows if r.get("kind") == "REGULAR"]
    return (regular or rows)[0]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)
