"""The deterministic order in which competing refusals surface (PRD 2.10).

State gates are named before temporal arithmetic; environmental safety gates
are named before fiscal gates; role authorization precedes every state check.
When two checks could reject the same request, the earlier one wins.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_OPEN_CAPITAL_PROJECT,
    ERR_OPEN_ENVIRONMENTAL_INCIDENT,
    ERR_SEASON_NOT_OPEN,
    ERR_STAY_OUTSIDE_SEASON,
)
from test_helpers.assertions import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
)
from test_helpers.fixtures import (
    active_contract,
    authorize_project,
    bookable_inventory,
    contract_version,
    create_project,
    report_incident,
    set_clock,
)
from test_helpers.test_users import FRONT_DESK, OFFICER, RATE_MANAGER


class TestSeasonStateBeatsStayArithmetic:
    """A reservation against a CLOSED season never reaches stay arithmetic."""

    def _closed_season_scenario(self, client):
        scenario = bookable_inventory(client)
        # Advance past the season close: the season auto-transitions to
        # CLOSED and the approved filing expires.
        set_clock(client, "2027-09-02T00:00:00Z")
        return scenario

    def test_closed_season_and_out_of_season_stay_surface_the_state_error(
        self, client
    ):
        """PRD 3.3: "Several gates apply at intake, evaluated after the
        generic existence and state checks. The season must be `PLANNED` or
        `OPEN`, else `ERR_SEASON_NOT_OPEN`." and, named after it, "The stay
        must lie entirely inside the season — from `open_date` through
        `close_date` — or the request is rejected with
        `ERR_STAY_OUTSIDE_SEASON`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_late_revision_filing
        """
        scenario = self._closed_season_scenario(client)
        season = get_success_data(client.get_season(
            scenario["contract"]["id"], scenario["season"]["id"],
            headers=FRONT_DESK,
        ))
        assert season["status"] == C.SEASON_CLOSED
        contract_id = scenario["contract"]["id"]
        payload = f.reservation_payload(
            scenario["season"]["id"], scenario["room_class"]["id"],
            contract_version(client, contract_id, headers=FRONT_DESK),
            guest_ref="g-late",
            check_in_date="2027-10-01T00:00:00Z",
            check_out_date="2027-10-03T00:00:00Z",
        )
        response = client.create_reservation(
            contract_id, payload, headers=FRONT_DESK
        )
        # Both the state gate and the temporal gate are tripped; the state
        # gate is named first in PRD 3.3's intake-gate ordering.
        validate_error(response, ERR_SEASON_NOT_OPEN)

    def test_temporal_error_still_surfaces_when_the_season_state_allows(
        self, client
    ):
        """PRD 3.3: "The stay must lie entirely inside the season — from
        `open_date` through `close_date` — or the request is rejected with
        `ERR_STAY_OUTSIDE_SEASON`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_late_revision_filing
        """
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        payload = f.reservation_payload(
            scenario["season"]["id"], scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-outside",
            check_in_date="2027-10-01T00:00:00Z",
            check_out_date="2027-10-03T00:00:00Z",
        )
        response = client.create_reservation(
            contract_id, payload, headers=FRONT_DESK
        )
        validate_error(response, ERR_STAY_OUTSIDE_SEASON)


class TestEnvironmentalGateBeatsFiscalGate:
    """Transition initiation names safety before capital/fiscal gates."""

    def _both_gates_failing(self, client):
        contract, _season, _lines = active_contract(client)
        contract_id = contract["id"]
        project = create_project(
            client, contract_id, authorized_cost_cents=500000,
            title="Boiler replacement", asset_ref="BLDG-3",
        )
        authorize_project(client, contract_id, project["id"])
        report_incident(
            client, contract_id,
            protocol=C.PROTOCOL_WASTE, severity=C.SEVERITY_MAJOR,
            occurred_at="2027-07-15T00:00:00Z",
            description="Dumpster overflow near wildlife corridor",
        )
        return contract_id

    def test_initiating_with_both_failures_surfaces_the_environmental_error(
        self, client
    ):
        """PRD 2.10: "Only then are business rules evaluated, in this relative
        order: environmental safety gates, temporal window rules, cross-entity
        state requirements (a registered study, an open season, an active room
        class, an authorized service line), then hard business constraints
        such as the rate cap, the lottery window, housing capacity, and
        fiscal gates such as duplicate periods and cost overruns, then
        segregation of duties, and finally the optimistic-concurrency version
        check."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_transition_gates
        """
        contract_id = self._both_gates_failing(client)
        response = client.initiate_transition(contract_id, headers=OFFICER)
        validate_error(response, ERR_OPEN_ENVIRONMENTAL_INCIDENT)

    def test_with_the_incident_closed_the_fiscal_gate_surfaces(self, client):
        """PRD 3.9: "every capital project on the contract that is still
        `PROPOSED`, `AUTHORIZED`, or `COMPLETED` must first be brought to
        `APPROVED` or `EXPENDED` — a live project anywhere in the pipeline
        blocks initiation with `ERR_OPEN_CAPITAL_PROJECT`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_transition_gates
        """
        contract, _season, _lines = active_contract(client)
        contract_id = contract["id"]
        project = create_project(client, contract_id)
        authorize_project(client, contract_id, project["id"])
        response = client.initiate_transition(contract_id, headers=OFFICER)
        validate_error(response, ERR_OPEN_CAPITAL_PROJECT)




class TestRoleCheckPrecedesStateCheck:
    """Authorization is evaluated before any target-state check."""

    def test_wrong_role_on_an_already_active_contract_gets_403(self, client):
        """PRD 2.10: "Authentication comes first: missing or invalid
        `X-User-ID` or `X-User-Role` headers are rejected before anything
        else, and a role not permitted for the operation is rejected second."

        Design: Corner/validations/role_check_precedes_state_check
        """
        contract, _season, _lines = active_contract(client)
        response = client.activate_contract(contract["id"], headers=RATE_MANAGER)
        validate_error(response, ERR_INSUFFICIENT_PERMISSIONS)
        reread = get_success_data(client.get_contract(
            contract["id"], headers=OFFICER
        ))
        assert reread["status"] == C.CONTRACT_ACTIVE
        assert reread["version"] == contract["version"], (
            "a rejected activation must not advance the contract version"
        )
