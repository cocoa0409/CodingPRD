"""Corner tests — agent lifecycle, salary components and status transitions (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    create_closed_transaction,
    create_survey,
    set_clock,
    agent_version,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_agent_read_round_trips_its_salary_components_and_defaults():
    """PRD §3.2: "supplying `region_id`, `full_name`, `agent_kind`, `home_zip`, `base_salary_cents`, and optionally `benefits_cents` and `expense_allowance_cents`, which default to 0".
    PRD §3.2: "`salary_commitment_cents` is the sum of the `base_salary_cents`, the `bonus_cents`, the `benefits_cents` and the `expense_allowance_cents`".

    Design: Corner/entities/agent_get_round_trips_salary_benefits_and_expense_fields
    """
    region = create_region()
    create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    associate = get_success_data(api_client.create_agent(
        {"region_id": region["id"], "full_name": "Ann Associate", "agent_kind": "ASSOCIATE",
         "home_zip": "98102", "base_salary_cents": 6_000_000},
        PLATFORM_ADMIN,
    ))

    fetched = get_success_data(api_client.get_agent(associate["id"], PLATFORM_ADMIN))
    assert fetched["full_name"] == "Ann Associate", fetched
    assert fetched["agent_kind"] == "ASSOCIATE", fetched
    assert fetched["base_salary_cents"] == 6_000_000, fetched
    assert fetched["benefits_cents"] == 0, fetched
    assert fetched["expense_allowance_cents"] == 0, fetched
    assert fetched["salary_commitment_cents"] == 6_000_000, fetched
    assert fetched["home_zip"] == "98102", fetched


def test_agent_derived_referral_fee_bps_is_capped_at_the_declared_ceiling():
    """PRD §3.2: "`referral_fee_bps` is the smaller of 2500 and the integer nearest to one basis point for every 10,000 cents of the `base_salary_cents` — an agent whose salaried base reaches 20,000,000 cents lands exactly on the cap."

    Design: Corner/calculations/agent_referral_fee_bps_is_capped_at_the_declared_ceiling
    """
    region = create_region()
    standard = create_lead_agent(region["id"], full_name="Ada Lead",
                                 home_zip="98101", base_salary_cents=8_000_000)
    capped = create_lead_agent(region["id"], full_name="Capped Lead",
                               home_zip="98102", base_salary_cents=30_000_000)

    assert standard["referral_fee_bps"] == 800, standard
    assert capped["referral_fee_bps"] == 2500, capped

    fresh = get_success_data(api_client.get_agent(capped["id"], PLATFORM_ADMIN))
    assert fresh["referral_fee_bps"] == 2500, fresh


def test_agent_status_write_with_a_stale_version_is_refused():
    """PRD §2.7: "If the agent's version has advanced, the benefits and salary fields the caller merged into are stale and the request is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/calculations/agent_referral_fee_bps_is_capped_at_the_declared_ceiling
    """
    region = create_region()
    standard = create_lead_agent(region["id"], home_zip="98101", base_salary_cents=8_000_000)
    observed = agent_version(standard["id"])

    resp = api_client.set_agent_status(
        standard["id"],
        {"new_status": "ON_LEAVE", "expected_agent_version": observed - 1},
        PLATFORM_ADMIN,
    )
    data = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert data["error_id"] == "ERR_STALE_VERSION", data

    unchanged = get_success_data(api_client.get_agent(standard["id"], PLATFORM_ADMIN))
    assert unchanged["referral_fee_bps"] == 800, unchanged
    assert unchanged["status"] == "ACTIVE", unchanged


def test_on_leave_status_zeroes_the_bonus_but_keeps_the_salary_commitment():
    """PRD §3.2: "An agent whose `status` is `ON_LEAVE` is not eligible."
    PRD §3.2: "a leave makes the agent ineligible, so the bonus collapses".
    PRD §3.2: "`salary_commitment_cents` is the sum of the `base_salary_cents`, the `bonus_cents`, the `benefits_cents` and the `expense_allowance_cents`".

    Design: Corner/endpoints/agent_status_change_to_on_leave_zeroes_bonus_and_keeps_salary_commitment
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"], base_salary_cents=8_000_000,
                             benefits_cents=500_000, expense_allowance_cents=200_000)
    # Three closed transactions clear the <3-close eligibility gate so a bonus
    # is actually in play.
    for _ in range(3):
        _client, tx = create_closed_transaction(region, lead, contract_price_cents=75_000_000)
        create_survey(tx["id"], lead["id"], score=5)

    before = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert before["bonus_cents"] > 0, before

    get_success_data(api_client.set_agent_status(
        lead["id"],
        {"new_status": "ON_LEAVE", "expected_agent_version": before["version"]},
        PLATFORM_ADMIN,
    ))

    after = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert after["status"] == "ON_LEAVE", after
    assert after["bonus_pct"] == 0, after
    assert after["bonus_cents"] == 0, after
    assert after["salary_commitment_cents"] == 8_000_000 + 500_000 + 200_000, after


def test_agent_versions_advance_by_one_on_a_status_write():
    """PRD §2.4: "`version`, an integer that starts at 1 and increments by exactly 1 on every mutation of the row or of any derived field stored on it."

    Design: Corner/endpoints/agent_status_change_to_on_leave_zeroes_bonus_and_keeps_salary_commitment
    """
    region = create_region(target_client_ratio=8.0)
    lead = create_lead_agent(region["id"], base_salary_cents=8_000_000,
                             benefits_cents=500_000, expense_allowance_cents=200_000)
    # Three closed transactions clear the <3-close eligibility gate so a bonus
    # is actually in play.
    for _ in range(3):
        _client, tx = create_closed_transaction(region, lead, contract_price_cents=75_000_000)
        create_survey(tx["id"], lead["id"], score=5)

    before = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    written = get_success_data(api_client.set_agent_status(
        lead["id"],
        {"new_status": "ON_LEAVE", "expected_agent_version": before["version"]},
        PLATFORM_ADMIN,
    ))
    assert written["version"] == before["version"] + 1, written