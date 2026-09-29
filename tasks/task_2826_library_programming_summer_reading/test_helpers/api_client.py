"""One client method per endpoint the PRD publishes, plus instant canonicalisation.

The PRD asks for "an ISO 8601 UTC timestamp with exactly three fractional
digits", but a server may legitimately echo an instant back with a
different sub-second width than the literal a test sent. Rather than compare raw
strings, tests compare canonical forms: ``canonicalize_instant`` parses an
instant and re-renders it with exactly three fractional digits and a trailing
``Z``, so ``2026-08-12T14:00:00Z``, ``2026-08-12T14:00:00.000Z`` and
``2026-08-12T14:00:00.000000+00:00`` all compare equal.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE, CLOCK_SET_PATH

_TRAILING_Z = re.compile(r"[Zz]$")


def canonicalize_instant(value: Optional[str]) -> Optional[str]:
    """Re-render an ISO 8601 instant with exactly three fractional digits.

    Returns the input unchanged when it is not parseable as an instant, so a
    failing assertion still shows the server's original text.
    """
    if value is None or not isinstance(value, str):
        return value
    text = _TRAILING_Z.sub("+00:00", value.strip())
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two instants denote the same moment, whatever their width."""
    return canonicalize_instant(left) == canonicalize_instant(right)


def _clean(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop unset query parameters so a filter is either sent or absent."""
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


class LibraryApiClient(GenericApiClient):
    """Typed access to the library programming and summer reading endpoints."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", CLOCK_SET_PATH, {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Branches and rooms
    # ------------------------------------------------------------------
    def create_branch(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/branches", payload, headers)

    def get_branch(self, branch_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/branches/{branch_id}", None, headers)

    def create_room(
        self, branch_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/branches/{branch_id}/rooms", payload, headers
        )

    def get_room(self, room_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/rooms/{room_id}", None, headers)

    def list_rooms(
        self,
        headers,
        branch_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/rooms",
            _clean(
                {
                    "branch_id": branch_id,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    # ------------------------------------------------------------------
    # Inventory lots
    # ------------------------------------------------------------------
    def create_inventory_lot(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/inventory-lots/{lot_id}", None, headers)

    def list_inventory_lots(
        self,
        headers,
        branch_id: Optional[str] = None,
        category: Optional[str] = None,
        sku: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/inventory-lots",
            _clean(
                {
                    "branch_id": branch_id,
                    "category": category,
                    "sku": sku,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/programs", payload, headers)

    def get_program(self, program_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/programs/{program_id}", None, headers)

    def list_programs(
        self,
        headers,
        branch_id: Optional[str] = None,
        challenge_id: Optional[str] = None,
        operational_status: Optional[str] = None,
        compliance_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/programs",
            _clean(
                {
                    "branch_id": branch_id,
                    "challenge_id": challenge_id,
                    "operational_status": operational_status,
                    "compliance_status": compliance_status,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    def schedule_program(
        self, program_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/schedule", payload or {}, headers
        )

    def confirm_program(self, program_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/confirm", {}, headers
        )

    def register(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/registrations", payload, headers
        )

    def close_out_program(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/close-out", payload, headers
        )

    def weather_close_program(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/weather-close", payload, headers
        )

    def cancel_program(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Room reservations
    # ------------------------------------------------------------------
    def create_reservation(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/reservations", payload, headers
        )

    def get_reservation(self, reservation_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/reservations/{reservation_id}", None, headers
        )

    def list_reservations(
        self,
        headers,
        program_id: Optional[str] = None,
        room_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/reservations",
            _clean(
                {
                    "program_id": program_id,
                    "room_id": room_id,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    def confirm_reservation(self, reservation_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reservations/{reservation_id}/confirm", {}, headers
        )

    # ------------------------------------------------------------------
    # Presenters and screening
    # ------------------------------------------------------------------
    def create_presenter(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/presenters", payload, headers)

    def get_presenter(self, presenter_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/presenters/{presenter_id}", None, headers)

    def request_screening(
        self, presenter_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/presenters/{presenter_id}/screening-requests",
            payload,
            headers,
        )

    def record_screening_result(
        self, presenter_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/presenters/{presenter_id}/screening-results",
            payload,
            headers,
        )

    def adjudicate_screening(
        self, presenter_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/presenters/{presenter_id}/adjudications",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Presenter contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/contracts/{contract_id}", None, headers)

    def list_contracts(
        self,
        headers,
        presenter_id: Optional[str] = None,
        program_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/contracts",
            _clean(
                {
                    "presenter_id": presenter_id,
                    "program_id": program_id,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    def offer_contract(
        self, contract_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/offer", payload, headers
        )

    def counter_contract(
        self, contract_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/counter", payload, headers
        )

    def execute_contract(self, contract_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/execute", {}, headers
        )

    # ------------------------------------------------------------------
    # Reading challenges and incentive tiers
    # ------------------------------------------------------------------
    def create_challenge(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/reading-challenges", payload, headers)

    def get_challenge(self, challenge_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/reading-challenges/{challenge_id}", None, headers
        )

    def open_challenge(self, challenge_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reading-challenges/{challenge_id}/open", {}, headers
        )

    def reconcile_challenge(self, challenge_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reading-challenges/{challenge_id}/reconcile", {}, headers
        )

    def create_incentive_tier(
        self, challenge_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/reading-challenges/{challenge_id}/incentive-tiers",
            payload,
            headers,
        )

    def get_incentive_tier(self, tier_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/incentive-tiers/{tier_id}", None, headers
        )

    def list_incentive_tiers(
        self,
        headers,
        challenge_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/incentive-tiers",
            _clean(
                {"challenge_id": challenge_id, "limit": limit, "offset": offset}
            ),
            headers,
        )

    # ------------------------------------------------------------------
    # Participants and the reading ledger
    # ------------------------------------------------------------------
    def create_participant(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{BASE}/participants", payload, headers)

    def get_participant(self, participant_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/participants/{participant_id}", None, headers
        )

    def list_participants(
        self,
        headers,
        challenge_id: Optional[str] = None,
        home_branch_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/participants",
            _clean(
                {
                    "challenge_id": challenge_id,
                    "home_branch_id": home_branch_id,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    def create_log_entry(
        self, participant_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/participants/{participant_id}/log-entries",
            payload,
            headers,
        )

    def create_log_correction(
        self, participant_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/participants/{participant_id}/log-corrections",
            payload,
            headers,
        )

    def get_log_entry(self, entry_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/log-entries/{entry_id}", None, headers)

    def list_log_entries(
        self,
        headers,
        participant_id: Optional[str] = None,
        entry_type: Optional[str] = None,
        corrected_entry_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/log-entries",
            _clean(
                {
                    "participant_id": participant_id,
                    "entry_type": entry_type,
                    "corrected_entry_id": corrected_entry_id,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    # ------------------------------------------------------------------
    # Tier awards
    # ------------------------------------------------------------------
    def get_tier_award(self, award_id: str, headers) -> requests.Response:
        return self._request("GET", f"{BASE}/tier-awards/{award_id}", None, headers)

    def list_tier_awards(
        self,
        headers,
        participant_id: Optional[str] = None,
        tier_id: Optional[str] = None,
        lot_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/tier-awards",
            _clean(
                {
                    "participant_id": participant_id,
                    "tier_id": tier_id,
                    "lot_id": lot_id,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                }
            ),
            headers,
        )

    # ------------------------------------------------------------------
    # Raw pagination access, for out-of-bounds parameter checks
    # ------------------------------------------------------------------
    def list_raw(
        self, collection_path: str, headers, params: Dict[str, Any]
    ) -> requests.Response:
        """Send a listing request with the query parameters exactly as given."""
        return self._request("GET", f"{BASE}{collection_path}", params, headers)


def sorted_award_ids(awards: List[Dict[str, Any]]) -> List[str]:
    """Award identifiers in the order the listing returned them."""
    return [award["id"] for award in awards]
