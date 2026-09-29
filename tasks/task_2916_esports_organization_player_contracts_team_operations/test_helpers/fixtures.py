"""Composite setup helpers.

The harness restarts the API against an empty database before every test, so
every helper here builds its state from scratch using only endpoints the PRD
declares. Setup calls go through the lenient validator so a broken precondition
reports as a setup failure rather than as a confusing assertion error.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CONTRACT_EFFECTIVE_AT,
    FINANCE_OFFICER_USER_ID,
    LEAGUE_ADMIN_USER_ID,
    TEST_DEFAULTS,
)
from .factories import (
    accept_offer_payload,
    cancel_block_payload,
    counter_offer_payload,
    create_contract_offer_payload,
    create_deliverable_payload,
    create_league_payload,
    create_minor_player_payload,
    create_organization_payload,
    create_player_payload,
    create_practice_block_payload,
    create_prize_distribution_payload,
    create_roster_move_payload,
    create_sponsorship_deal_payload,
    create_team_house_payload,
    decline_offer_payload,
    guardian_consent_payload,
    move_decision_payload,
    reverse_move_payload,
    review_deliverable_payload,
    revise_offer_payload,
    set_clock_payload,
    submit_deliverable_payload,
    suspend_contract_payload,
    void_distribution_payload,
    wellness_report_payload,
)
from .test_users import (
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_guardian_representative_headers,
    make_league_admin_headers,
    make_ops_manager_headers,
    make_performance_support_headers,
    make_player_agent_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
)

# ─── Primitive steps ──────────────────────────────────────────────────────────


def set_clock(current_utc: str, admin_user_id: str = LEAGUE_ADMIN_USER_ID) -> dict:
    """Move the logical clock to an ISO 8601 UTC instant."""
    return get_success_data(
        api_client.set_current_utc(
            set_clock_payload(current_utc), make_league_admin_headers(admin_user_id)
        )
    )


def create_league(admin_user_id: str = LEAGUE_ADMIN_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_league(
            create_league_payload(**overrides), make_league_admin_headers(admin_user_id)
        )
    )


def create_organization(
    league_id: str, admin_user_id: str = LEAGUE_ADMIN_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.create_organization(
            create_organization_payload(league_id, **overrides),
            make_league_admin_headers(admin_user_id),
        )
    )


def create_player(**overrides) -> dict:
    return get_success_data(
        api_client.create_player(create_player_payload(**overrides), make_scout_headers())
    )


def create_minor_player(**overrides) -> dict:
    return get_success_data(
        api_client.create_player(
            create_minor_player_payload(**overrides), make_scout_headers()
        )
    )


def grant_guardian_consent(player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.grant_guardian_consent(
            player_id,
            guardian_consent_payload(**overrides),
            make_guardian_representative_headers(player_id),
        )
    )


def create_minor_player_with_consent(guardian_weekly_cap_minutes=1080, **overrides) -> dict:
    """A minor whose guardian consent is GRANTED, ready to be offered a contract."""
    player = create_minor_player(**overrides)
    return grant_guardian_consent(
        player["id"], guardian_weekly_cap_minutes=guardian_weekly_cap_minutes
    )


def create_team_house(organization_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_team_house(
            organization_id,
            create_team_house_payload(**overrides),
            make_ops_manager_headers(organization_id),
        )
    )


def create_offer(organization_id: str, player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract_offer(
            create_contract_offer_payload(organization_id, player_id, **overrides),
            make_general_manager_headers(organization_id),
        )
    )


def counter_offer(offer_id: str, player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.counter_contract_offer(
            offer_id, counter_offer_payload(**overrides), make_player_agent_headers(player_id)
        )
    )


def revise_offer(offer_id: str, organization_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.revise_contract_offer(
            offer_id,
            revise_offer_payload(**overrides),
            make_general_manager_headers(organization_id),
        )
    )


def accept_offer(offer_id: str, player_id: str, effective_at: str = CONTRACT_EFFECTIVE_AT) -> dict:
    return get_success_data(
        api_client.accept_contract_offer(
            offer_id,
            accept_offer_payload(effective_at),
            make_player_agent_headers(player_id),
        )
    )


def suspend_contract(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.suspend_contract(
            contract_id, suspend_contract_payload(**overrides), make_league_admin_headers()
        )
    )


def file_wellness_report(contract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.file_wellness_report(
            contract_id,
            wellness_report_payload(**overrides),
            make_performance_support_headers(),
        )
    )


def create_practice_block(
    organization_id: str,
    team_house_id: str,
    starts_at: str,
    ends_at: str,
    participant_player_ids,
    block_type: str = "SCRIM",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_practice_block(
            create_practice_block_payload(
                organization_id,
                team_house_id,
                starts_at,
                ends_at,
                participant_player_ids,
                block_type=block_type,
                **overrides,
            ),
            make_coaching_staff_headers(),
        )
    )


def complete_practice_block(block_id: str) -> dict:
    return get_success_data(
        api_client.complete_practice_block(block_id, make_coaching_staff_headers())
    )


def cancel_practice_block(block_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_practice_block(
            block_id, cancel_block_payload(**overrides), make_coaching_staff_headers()
        )
    )


def create_deal(organization_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sponsorship_deal(
            create_sponsorship_deal_payload(organization_id, **overrides),
            make_sponsorship_manager_headers(organization_id),
        )
    )


def activate_deal(deal_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.activate_sponsorship_deal(
            deal_id, make_sponsorship_manager_headers(organization_id)
        )
    )


def read_deal(deal_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.get_sponsorship_deal(
            deal_id, make_sponsorship_manager_headers(organization_id)
        )
    )


def current_deal_version(deal_id: str, organization_id: str) -> int:
    """Read the parent deal's live version for the stale-version token."""
    return read_deal(deal_id, organization_id)["version"]


def add_deliverable(deal_id: str, organization_id: str, contract_id: str, **overrides) -> dict:
    """Place one deliverable, threading the deal's current version as the token."""
    expected_deal_version = overrides.pop(
        "expected_deal_version", current_deal_version(deal_id, organization_id)
    )
    return get_success_data(
        api_client.create_deliverable_assignment(
            deal_id,
            create_deliverable_payload(contract_id, expected_deal_version, **overrides),
            make_sponsorship_manager_headers(organization_id),
        )
    )


def submit_deliverable(assignment_id: str, player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.submit_deliverable_assignment(
            assignment_id,
            submit_deliverable_payload(**overrides),
            make_player_agent_headers(player_id),
        )
    )


def review_deliverable(
    assignment_id: str, organization_id: str, decision: str = "APPROVE", **overrides
) -> dict:
    return get_success_data(
        api_client.review_deliverable_assignment(
            assignment_id,
            review_deliverable_payload(decision, **overrides),
            make_sponsorship_manager_headers(organization_id),
        )
    )


def create_distribution(
    organization_id: str,
    league_id: str,
    finance_user_id: str = FINANCE_OFFICER_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_prize_distribution(
            create_prize_distribution_payload(organization_id, league_id, **overrides),
            make_finance_officer_headers(finance_user_id),
        )
    )


def calculate_distribution(
    distribution_id: str, finance_user_id: str = FINANCE_OFFICER_USER_ID
) -> dict:
    return get_success_data(
        api_client.calculate_prize_distribution(
            distribution_id, make_finance_officer_headers(finance_user_id)
        )
    )


def approve_distribution(distribution_id: str, admin_user_id: str = LEAGUE_ADMIN_USER_ID) -> dict:
    return get_success_data(
        api_client.approve_prize_distribution(
            distribution_id, make_league_admin_headers(admin_user_id)
        )
    )


def void_distribution(
    distribution_id: str, finance_user_id: str = FINANCE_OFFICER_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.void_prize_distribution(
            distribution_id,
            void_distribution_payload(**overrides),
            make_finance_officer_headers(finance_user_id),
        )
    )


def read_organization(organization_id: str) -> dict:
    return get_success_data(
        api_client.get_organization(
            organization_id, make_general_manager_headers(organization_id)
        )
    )


def current_organization_version(organization_id: str) -> int:
    """Read the organization's live version for the stale-version token."""
    return read_organization(organization_id)["version"]


def file_roster_move(
    organization_id: str,
    player_id: str,
    move_type: str,
    contract_id: str,
    **overrides,
) -> dict:
    expected_organization_version = overrides.pop(
        "expected_organization_version", current_organization_version(organization_id)
    )
    return get_success_data(
        api_client.create_roster_move(
            create_roster_move_payload(
                organization_id,
                player_id,
                move_type,
                contract_id,
                expected_organization_version,
                **overrides,
            ),
            make_general_manager_headers(organization_id),
        )
    )


def decide_roster_move(
    move_id: str, decision: str = "APPROVE", admin_user_id: str = LEAGUE_ADMIN_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.decide_roster_move(
            move_id,
            move_decision_payload(decision, **overrides),
            make_league_admin_headers(admin_user_id),
        )
    )


def execute_roster_move(move_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.execute_roster_move(
            move_id, make_general_manager_headers(organization_id)
        )
    )


def reverse_roster_move(move_id: str, admin_user_id: str = LEAGUE_ADMIN_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.reverse_roster_move(
            move_id, reverse_move_payload(**overrides), make_league_admin_headers(admin_user_id)
        )
    )


# ─── Composite state builders ─────────────────────────────────────────────────

OFFER_CLOCK = "2026-08-04T00:00:00Z"
ACCEPT_CLOCK = "2026-08-05T00:00:00Z"

SECOND_PLAYER = {
    "full_name": "Marek Rus",
    "birth_date": "2000-03-02",
    "region_code": "CZ",
    "association_member": True,
    "education_enrollment_status": "NOT_ENROLLED",
}

SECOND_OFFER_TERMS = {
    "base_salary_cents": TEST_DEFAULTS["SECOND_BASE_SALARY_CENTS"],
    "term_months": 12,
    "prize_split_player_pct_bp": 4500,
    "streaming_hours_per_week": 12,
    "tax_residency_code": "KR",
    "signing_bonus_cents": 0,
    "buyout_multiplier_bp": 5000,
}


def setup_league_and_org(league_overrides=None, org_overrides=None) -> dict:
    """One league plus one organization inside it. Returns a context dict."""
    league = create_league(**(league_overrides or {}))
    org = create_organization(league["id"], **(org_overrides or {}))
    return {
        "league": league,
        "org": org,
        "gm_headers": make_general_manager_headers(org["id"]),
        "ops_headers": make_ops_manager_headers(org["id"]),
        "sponsor_headers": make_sponsorship_manager_headers(org["id"]),
    }


def setup_signed_player(
    league_overrides=None,
    org_overrides=None,
    player_overrides=None,
    offer_overrides=None,
    effective_at: str = CONTRACT_EFFECTIVE_AT,
    offer_clock: str = OFFER_CLOCK,
    accept_clock: str = ACCEPT_CLOCK,
    with_team_house: bool = False,
    house_overrides=None,
) -> dict:
    """League + organization + one adult player under an ACTIVE contract.

    The clock is moved to ``offer_clock`` before the offer is sent and to
    ``accept_clock`` before it is accepted, so the offer is inside its response
    window and the contract's effective_at is inside the season.
    """
    ctx = setup_league_and_org(league_overrides, org_overrides)
    if with_team_house:
        ctx["house"] = create_team_house(ctx["org"]["id"], **(house_overrides or {}))
    ctx["player"] = create_player(**(player_overrides or {}))
    set_clock(offer_clock)
    ctx["offer"] = create_offer(
        ctx["org"]["id"], ctx["player"]["id"], **(offer_overrides or {})
    )
    set_clock(accept_clock)
    ctx["contract"] = accept_offer(
        ctx["offer"]["id"], ctx["player"]["id"], effective_at=effective_at
    )
    ctx["agent_headers"] = make_player_agent_headers(ctx["player"]["id"])
    return ctx


def setup_two_signed_players(
    league_overrides=None,
    org_overrides=None,
    first_offer_overrides=None,
    second_offer_overrides=None,
    effective_at: str = CONTRACT_EFFECTIVE_AT,
    offer_clock: str = OFFER_CLOCK,
    accept_clock: str = ACCEPT_CLOCK,
    with_team_house: bool = False,
    house_overrides=None,
) -> dict:
    """One organization holding two ACTIVE contracts on two distinct players."""
    ctx = setup_league_and_org(league_overrides, org_overrides)
    if with_team_house:
        ctx["house"] = create_team_house(ctx["org"]["id"], **(house_overrides or {}))
    ctx["player_one"] = create_player()
    ctx["player_two"] = create_player(**SECOND_PLAYER)
    set_clock(offer_clock)
    ctx["offer_one"] = create_offer(
        ctx["org"]["id"], ctx["player_one"]["id"], **(first_offer_overrides or {})
    )
    second_terms = dict(SECOND_OFFER_TERMS)
    second_terms.update(second_offer_overrides or {})
    ctx["offer_two"] = create_offer(ctx["org"]["id"], ctx["player_two"]["id"], **second_terms)
    set_clock(accept_clock)
    ctx["contract_one"] = accept_offer(
        ctx["offer_one"]["id"], ctx["player_one"]["id"], effective_at=effective_at
    )
    ctx["contract_two"] = accept_offer(
        ctx["offer_two"]["id"], ctx["player_two"]["id"], effective_at=effective_at
    )
    ctx["agent_one_headers"] = make_player_agent_headers(ctx["player_one"]["id"])
    ctx["agent_two_headers"] = make_player_agent_headers(ctx["player_two"]["id"])
    return ctx


def setup_signed_minor(
    league_overrides=None,
    org_overrides=None,
    player_overrides=None,
    guardian_weekly_cap_minutes=1080,
    offer_overrides=None,
    effective_at: str = CONTRACT_EFFECTIVE_AT,
    offer_clock: str = OFFER_CLOCK,
    accept_clock: str = ACCEPT_CLOCK,
    with_team_house: bool = False,
    house_overrides=None,
) -> dict:
    """A minor with GRANTED guardian consent under an ACTIVE contract."""
    ctx = setup_league_and_org(league_overrides, org_overrides)
    if with_team_house:
        ctx["house"] = create_team_house(ctx["org"]["id"], **(house_overrides or {}))
    minor = create_minor_player(**(player_overrides or {}))
    ctx["player"] = grant_guardian_consent(
        minor["id"], guardian_weekly_cap_minutes=guardian_weekly_cap_minutes
    )
    terms = {
        "base_salary_cents": TEST_DEFAULTS["MINOR_BASE_SALARY_CENTS"],
        "prize_split_player_pct_bp": 4200,
        "streaming_hours_per_week": 5,
    }
    terms.update(offer_overrides or {})
    set_clock(offer_clock)
    ctx["offer"] = create_offer(ctx["org"]["id"], ctx["player"]["id"], **terms)
    set_clock(accept_clock)
    ctx["contract"] = accept_offer(
        ctx["offer"]["id"], ctx["player"]["id"], effective_at=effective_at
    )
    ctx["agent_headers"] = make_player_agent_headers(ctx["player"]["id"])
    ctx["guardian_headers"] = make_guardian_representative_headers(ctx["player"]["id"])
    return ctx


def setup_active_deal(organization_id: str, **overrides) -> dict:
    """A sponsorship deal walked from DRAFT to ACTIVE."""
    deal = create_deal(organization_id, **overrides)
    return activate_deal(deal["id"], organization_id)


def setup_held_blocks(
    organization_id: str,
    team_house_id: str,
    player_ids,
    intervals,
    complete_at: str,
    block_type: str = "SCRIM",
) -> list:
    """Book every (starts_at, ends_at) interval, then complete them all.

    ``complete_at`` moves the clock past the last interval so completion is
    admissible; the blocks come back HELD.
    """
    blocks = []
    for starts_at, ends_at in intervals:
        blocks.append(
            create_practice_block(
                organization_id,
                team_house_id,
                starts_at,
                ends_at,
                player_ids,
                block_type=block_type,
            )
        )
    set_clock(complete_at)
    return [complete_practice_block(block["id"]) for block in blocks]


def decline_offer(offer_id: str, player_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.decline_contract_offer(
            offer_id, decline_offer_payload(**overrides), make_player_agent_headers(player_id)
        )
    )


# ─── Read-side helpers ────────────────────────────────────────────────────────


def read_contract(contract_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.get_contract(contract_id, make_general_manager_headers(organization_id))
    )


def read_obligation_summary(contract_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.get_contract_obligation_summary(
            contract_id, make_general_manager_headers(organization_id)
        )
    )


def read_cap_summary(organization_id: str) -> dict:
    return get_success_data(
        api_client.get_organization_cap_summary(
            organization_id, make_general_manager_headers(organization_id)
        )
    )


def read_player(player_id: str) -> dict:
    return get_success_data(api_client.get_player(player_id, make_scout_headers()))


def read_practice_block(block_id: str) -> dict:
    return get_success_data(
        api_client.get_practice_block(block_id, make_coaching_staff_headers())
    )


def read_offer(offer_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.get_contract_offer(offer_id, make_general_manager_headers(organization_id))
    )


def read_deliverable(assignment_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.get_deliverable_assignment(
            assignment_id, make_sponsorship_manager_headers(organization_id)
        )
    )


def read_distribution(distribution_id: str, finance_user_id: str = FINANCE_OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.get_prize_distribution(
            distribution_id, make_finance_officer_headers(finance_user_id)
        )
    )


def read_allocations(distribution_id: str, finance_user_id: str = FINANCE_OFFICER_USER_ID):
    body = api_client.list_prize_allocations(
        distribution_id, make_finance_officer_headers(finance_user_id)
    )
    return get_success_data(body)


def read_roster_move(move_id: str, organization_id: str) -> dict:
    return get_success_data(
        api_client.get_roster_move(move_id, make_general_manager_headers(organization_id))
    )


# ─── Deal / deliverable lifecycle composites ─────────────────────────────────


def setup_deal_with_deliverable(
    organization_id: str,
    contract_id: str,
    deal_overrides=None,
    deliverable_overrides=None,
) -> dict:
    """ACTIVE deal carrying one ASSIGNED deliverable against ``contract_id``."""
    deal = setup_active_deal(organization_id, **(deal_overrides or {}))
    assignment = add_deliverable(
        deal["id"], organization_id, contract_id, **(deliverable_overrides or {})
    )
    return {"deal": deal, "assignment": assignment}


def setup_fulfilled_deal(
    organization_id: str,
    contract_ids,
    player_ids,
    deal_overrides=None,
) -> dict:
    """A deal whose required deliverables are all APPROVED, so it is FULFILLED.

    ``contract_ids`` and ``player_ids`` are positionally paired: one deliverable
    is placed per contract, submitted by that player's agent and approved.
    """
    overrides = {"deliverable_count_required": len(contract_ids)}
    overrides.update(deal_overrides or {})
    deal = setup_active_deal(organization_id, **overrides)
    assignments = []
    for contract_id, player_id in zip(contract_ids, player_ids):
        assignment = add_deliverable(deal["id"], organization_id, contract_id)
        submit_deliverable(assignment["id"], player_id)
        assignments.append(review_deliverable(assignment["id"], organization_id, "APPROVE"))
    return {
        "deal": read_deal(deal["id"], organization_id),
        "assignments": assignments,
    }


# ─── Prize distribution composites ───────────────────────────────────────────


def setup_calculated_distribution(
    organization_id: str, league_id: str, **overrides
) -> dict:
    """A distribution walked from DRAFT to CALCULATED."""
    distribution = create_distribution(organization_id, league_id, **overrides)
    return calculate_distribution(distribution["id"])


def setup_approved_distribution(
    organization_id: str, league_id: str, **overrides
) -> dict:
    """A distribution walked from DRAFT through CALCULATED to APPROVED.

    Calculation is filed by one FinanceOfficer and approval by a LeagueAdmin, so
    the two sign-offs never share an identity.
    """
    distribution = setup_calculated_distribution(organization_id, league_id, **overrides)
    return approve_distribution(distribution["id"])


# ─── Roster move composites ──────────────────────────────────────────────────


def setup_pending_move(
    organization_id: str, player_id: str, move_type: str, contract_id: str, **overrides
) -> dict:
    """A filed roster move sitting in PENDING."""
    return file_roster_move(organization_id, player_id, move_type, contract_id, **overrides)


def setup_approved_move(
    organization_id: str, player_id: str, move_type: str, contract_id: str, **overrides
) -> dict:
    """A roster move filed and then APPROVED by the league."""
    move = file_roster_move(organization_id, player_id, move_type, contract_id, **overrides)
    return decide_roster_move(move["id"], "APPROVE")


def setup_executed_move(
    organization_id: str, player_id: str, move_type: str, contract_id: str, **overrides
) -> dict:
    """A roster move filed, approved and then EXECUTED so its effects have landed."""
    move = setup_approved_move(
        organization_id, player_id, move_type, contract_id, **overrides
    )
    return execute_roster_move(move["id"], organization_id)
