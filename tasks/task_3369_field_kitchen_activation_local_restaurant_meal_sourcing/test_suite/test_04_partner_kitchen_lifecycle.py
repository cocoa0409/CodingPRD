"""Local restaurant activation: the parallel contract and production cycles."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_incident,
    create_partner_kitchen,
    get_kitchen,
    make_kitchen_operator_headers,
    setup_producing_partner_kitchen,
    transition_partner_kitchen,
    validate_error,
    TEST_USERS,
)

PARTNER = TEST_USERS["partnership_lead_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_suspending_a_producing_kitchen_forces_the_production_axis_into_cooldown(api):
    """PRD §3.3: "Suspension has a cross-dimension consequence: if the
    kitchen's `production_status` is anything other than `IDLE`, the kitchen is
    forced into `COOLDOWN` and `cooldown_until` is set to the current
    logical-clock instant plus 8 hours, so a restaurant that was mid-production
    is given a cooling-off period before it can cook again."

    Design: Difficulty/non_linear_state_machine/partner_kitchen_parallel_contract_and_production_dimensions
    """
    incident, kitchen = setup_producing_partner_kitchen()
    assert kitchen["production_status"] == "PRODUCING"

    suspended = transition_partner_kitchen(kitchen["id"], "CONTRACT", "SUSPENDED")
    assert suspended["contract_status"] == "SUSPENDED"
    assert suspended["production_status"] == "COOLDOWN"
    assert suspended["cooldown_until"] is not None


def test_cooldown_expiry_returns_the_kitchen_to_idle_and_reinstatement_restores_it(api):
    """PRD §3.3: "from `COOLDOWN` it returns to `IDLE` only once the logical
    clock is at or after `cooldown_until`, at which point `cooldown_until` is
    cleared."
    PRD §3.3: "Reinstatement runs from `SUSPENDED` back to `CONTRACTED` and
    requires `vetting_score` of at least 60, so a kitchen cannot be brought
    back on a stale or failing score."

    Design: Difficulty/non_linear_state_machine/partner_kitchen_parallel_contract_and_production_dimensions
    """
    incident, kitchen = setup_producing_partner_kitchen()
    transition_partner_kitchen(kitchen["id"], "CONTRACT", "SUSPENDED")

    api_client.set_current_utc("2026-09-01T20:00:00Z", ADMIN)
    idle = transition_partner_kitchen(
        kitchen["id"], "PRODUCTION", "IDLE",
        headers=make_kitchen_operator_headers(kitchen["id"]),
    )
    assert idle["production_status"] == "IDLE"
    assert idle["cooldown_until"] is None

    reinstated = transition_partner_kitchen(
        kitchen["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    assert reinstated["contract_status"] == "CONTRACTED"
    assert reinstated["production_status"] == "IDLE"


def test_vetting_requires_a_verified_bank_account(api):
    """PRD §3.3: "A restaurant may only move from `PROSPECT` to `VETTING` if
    `bank_verified` is true; without a verified payout account the attempt is
    rejected with `ERR_BANK_NOT_VERIFIED`."

    Design: Corner/validations/partner_kitchen_vetting_chain_rejections
    """
    incident = create_incident()
    restaurant = create_partner_kitchen(incident["id"], bank_verified=False)
    refused = api_client.transition_partner_kitchen(
        restaurant["id"], {"dimension": "CONTRACT", "to_state": "VETTING"}, PARTNER
    )
    validate_error(refused, ApiErrorId.ERR_BANK_NOT_VERIFIED)
    assert get_kitchen(restaurant["id"])["contract_status"] == "PROSPECT"


def test_contracting_requires_a_vetting_score_of_at_least_sixty(api):
    """PRD §3.3: "the move from `VETTING` to `CONTRACTED` requires that
    `vetting_score` to be at least 60, failing which the request is rejected
    with `ERR_VETTING_SCORE_TOO_LOW`."

    Design: Corner/validations/partner_kitchen_vetting_chain_rejections
    """
    incident = create_incident()
    restaurant = create_partner_kitchen(incident["id"])
    transition_partner_kitchen(restaurant["id"], "CONTRACT", "VETTING")
    refused = api_client.transition_partner_kitchen(
        restaurant["id"],
        {"dimension": "CONTRACT", "to_state": "CONTRACTED", "vetting_score": 55},
        PARTNER,
    )
    validate_error(refused, ApiErrorId.ERR_VETTING_SCORE_TOO_LOW)
    assert get_kitchen(restaurant["id"])["contract_status"] == "VETTING"


def test_cooldown_blocks_reopening_a_production_window(api):
    """PRD §3.3: "A kitchen may move from `IDLE` to `PRODUCING` only when its
    `contract_status` is `CONTRACTED` and the current logical-clock instant is
    at or after `cooldown_until`, or `cooldown_until` is null; a kitchen still
    inside its cooling-off window is rejected with `ERR_COOLDOWN_ACTIVE`."

    Design: Corner/validations/cooldown_active_blocks_production_restart
    """
    incident = create_incident()
    restaurant = create_partner_kitchen(incident["id"])
    transition_partner_kitchen(restaurant["id"], "CONTRACT", "VETTING")
    transition_partner_kitchen(
        restaurant["id"], "CONTRACT", "CONTRACTED", vetting_score=72
    )
    operator = make_kitchen_operator_headers(restaurant["id"])
    transition_partner_kitchen(
        restaurant["id"], "PRODUCTION", "PRODUCING", headers=operator
    )
    transition_partner_kitchen(restaurant["id"], "CONTRACT", "SUSPENDED")

    refused = api_client.transition_partner_kitchen(
        restaurant["id"],
        {"dimension": "PRODUCTION", "to_state": "IDLE"},
        operator,
    )
    validate_error(refused, ApiErrorId.ERR_COOLDOWN_ACTIVE)
    row = get_kitchen(restaurant["id"])
    assert row["production_status"] == "COOLDOWN"
    assert row["cooldown_until"] is not None


