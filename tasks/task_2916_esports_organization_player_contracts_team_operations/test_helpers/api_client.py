"""API client: one method per endpoint declared by the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so that equal instants compare equal.

    The PRD requires UTC instants with a trailing ``Z``; it does not pin the
    number of fractional-second digits on stored fields, so ``...T00:00:00Z``,
    ``...T00:00:00.0Z`` and ``...T00:00:00.000Z`` denote the same instant.
    Comparisons in the suite go through this function so that a difference in
    fractional-second width is never mistaken for a wrong value.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        body = text[:-1]
        suffix = "Z"
    else:
        body = text
        suffix = ""
    if "." in body:
        head, frac = body.split(".", 1)
        frac = frac.rstrip("0")
        body = head if frac == "" else f"{head}.{frac}"
    return f"{body}{suffix}"


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Leagues ──────────────────────────────────────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def update_league(self, league_id, payload, headers):
        return self._request("PATCH", f"/leagues/{league_id}", payload, headers)

    def list_league_organizations(self, league_id, headers, params=None):
        return self._request(
            "GET", f"/leagues/{league_id}/organizations", headers=headers, params=params
        )

    # ─── Organizations ────────────────────────────────────────────────────────
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, organization_id, headers):
        return self._request("GET", f"/organizations/{organization_id}", headers=headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/organizations", headers=headers, params=params)

    def update_organization(self, organization_id, payload, headers):
        return self._request(
            "PATCH", f"/organizations/{organization_id}", payload, headers
        )

    def get_organization_roster(self, organization_id, headers, params=None):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/roster",
            headers=headers,
            params=params,
        )

    def list_organization_team_houses(self, organization_id, headers, params=None):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/team-houses",
            headers=headers,
            params=params,
        )

    def list_organization_sponsorship_deals(self, organization_id, headers, params=None):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/sponsorship-deals",
            headers=headers,
            params=params,
        )

    def get_organization_cap_summary(self, organization_id, headers):
        return self._request(
            "GET", f"/organizations/{organization_id}/cap-summary", headers=headers
        )

    # ─── Players ──────────────────────────────────────────────────────────────
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def list_players(self, headers, params=None):
        return self._request("GET", "/players", headers=headers, params=params)

    def update_player(self, player_id, payload, headers):
        return self._request("PATCH", f"/players/{player_id}", payload, headers)

    def grant_guardian_consent(self, player_id, payload, headers):
        return self._request(
            "POST", f"/players/{player_id}/guardian-consent", payload, headers
        )

    # ─── Contract offers ──────────────────────────────────────────────────────
    def create_contract_offer(self, payload, headers):
        return self._request("POST", "/contract-offers", payload, headers)

    def get_contract_offer(self, offer_id, headers):
        return self._request("GET", f"/contract-offers/{offer_id}", headers=headers)

    def list_contract_offers(self, headers, params=None):
        return self._request("GET", "/contract-offers", headers=headers, params=params)

    def counter_contract_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/contract-offers/{offer_id}/counter", payload, headers
        )

    def revise_contract_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/contract-offers/{offer_id}/revise", payload, headers
        )

    def accept_contract_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/contract-offers/{offer_id}/accept", payload, headers
        )

    def decline_contract_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/contract-offers/{offer_id}/decline", payload, headers
        )

    # ─── Player contracts ─────────────────────────────────────────────────────
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def suspend_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/suspend", payload, headers
        )

    def file_wellness_report(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/wellness-report", payload, headers
        )

    def get_contract_obligation_summary(self, contract_id, headers):
        return self._request(
            "GET", f"/contracts/{contract_id}/obligation-summary", headers=headers
        )

    def list_contract_prize_allocations(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/contracts/{contract_id}/prize-allocations",
            headers=headers,
            params=params,
        )

    # ─── Team houses ──────────────────────────────────────────────────────────
    def create_team_house(self, organization_id, payload, headers):
        return self._request(
            "POST", f"/organizations/{organization_id}/team-houses", payload, headers
        )

    def get_team_house(self, team_house_id, headers):
        return self._request("GET", f"/team-houses/{team_house_id}", headers=headers)

    def update_team_house(self, team_house_id, payload, headers):
        return self._request("PATCH", f"/team-houses/{team_house_id}", payload, headers)

    # ─── Practice blocks ──────────────────────────────────────────────────────
    def create_practice_block(self, payload, headers):
        return self._request("POST", "/practice-blocks", payload, headers)

    def get_practice_block(self, block_id, headers):
        return self._request("GET", f"/practice-blocks/{block_id}", headers=headers)

    def list_practice_blocks(self, headers, params=None):
        return self._request("GET", "/practice-blocks", headers=headers, params=params)

    def complete_practice_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/practice-blocks/{block_id}/complete", payload, headers
        )

    def cancel_practice_block(self, block_id, payload, headers):
        return self._request(
            "POST", f"/practice-blocks/{block_id}/cancel", payload, headers
        )

    # ─── Sponsorship deals ────────────────────────────────────────────────────
    def create_sponsorship_deal(self, payload, headers):
        return self._request("POST", "/sponsorship-deals", payload, headers)

    def get_sponsorship_deal(self, deal_id, headers):
        return self._request("GET", f"/sponsorship-deals/{deal_id}", headers=headers)

    def list_sponsorship_deals(self, headers, params=None):
        return self._request("GET", "/sponsorship-deals", headers=headers, params=params)

    def activate_sponsorship_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/sponsorship-deals/{deal_id}/activate", payload, headers
        )

    def create_deliverable_assignment(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/sponsorship-deals/{deal_id}/deliverables", payload, headers
        )

    def list_deal_deliverables(self, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/sponsorship-deals/{deal_id}/deliverables",
            headers=headers,
            params=params,
        )

    # ─── Deliverable assignments ──────────────────────────────────────────────
    def get_deliverable_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/deliverable-assignments/{assignment_id}", headers=headers
        )

    def list_deliverable_assignments(self, headers, params=None):
        return self._request(
            "GET", "/deliverable-assignments", headers=headers, params=params
        )

    def submit_deliverable_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/deliverable-assignments/{assignment_id}/submit", payload, headers
        )

    def review_deliverable_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/deliverable-assignments/{assignment_id}/review", payload, headers
        )

    # ─── Prize distributions ──────────────────────────────────────────────────
    def create_prize_distribution(self, payload, headers):
        return self._request("POST", "/prize-distributions", payload, headers)

    def get_prize_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/prize-distributions/{distribution_id}", headers=headers
        )

    def list_prize_distributions(self, headers, params=None):
        return self._request(
            "GET", "/prize-distributions", headers=headers, params=params
        )

    def calculate_prize_distribution(self, distribution_id, headers, payload=None):
        return self._request(
            "POST", f"/prize-distributions/{distribution_id}/calculate", payload, headers
        )

    def approve_prize_distribution(self, distribution_id, headers, payload=None):
        return self._request(
            "POST", f"/prize-distributions/{distribution_id}/approve", payload, headers
        )

    def void_prize_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/prize-distributions/{distribution_id}/void", payload, headers
        )

    def list_prize_allocations(self, distribution_id, headers, params=None):
        return self._request(
            "GET",
            f"/prize-distributions/{distribution_id}/allocations",
            headers=headers,
            params=params,
        )

    # ─── Roster moves ─────────────────────────────────────────────────────────
    def create_roster_move(self, payload, headers):
        return self._request("POST", "/roster-moves", payload, headers)

    def get_roster_move(self, move_id, headers):
        return self._request("GET", f"/roster-moves/{move_id}", headers=headers)

    def list_roster_moves(self, headers, params=None):
        return self._request("GET", "/roster-moves", headers=headers, params=params)

    def decide_roster_move(self, move_id, payload, headers):
        return self._request("POST", f"/roster-moves/{move_id}/decision", payload, headers)

    def execute_roster_move(self, move_id, headers, payload=None):
        return self._request("POST", f"/roster-moves/{move_id}/execute", payload, headers)

    def reverse_roster_move(self, move_id, payload, headers):
        return self._request("POST", f"/roster-moves/{move_id}/reverse", payload, headers)


api_client = ApiClient()
