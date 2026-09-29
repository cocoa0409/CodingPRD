"""
HTTP client for the Plant Breeding Variety Trials API.

One method per endpoint in the PRD's routing table. Paths are absolute with no
version or tenant prefix, exactly as the PRD writes them.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Any) -> Any:
    """
    Normalise an ISO-8601 instant to the PRD's wire shape.

    PRD 2.5: "Instants are written `YYYY-MM-DDTHH:MM:SSZ` — UTC, second
    precision, no fractional seconds". Tests compare canonicalised instants so
    that a server emitting extra sub-second digits is not mistaken for a
    semantic defect; the width itself is asserted separately where the PRD
    states it.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    return match.group(1) + "Z"


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the breeding programme API."""

    # ─── Programmes and objectives (PRD 3.1) ──────────

    def create_program(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/breeding-programs", payload, headers)

    def get_program(self, program_id: str, headers) -> requests.Response:
        return self._request("GET", f"/breeding-programs/{program_id}", None, headers)

    def close_program(self, program_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/breeding-programs/{program_id}/close", payload or {}, headers
        )

    def create_objective(
        self, program_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/breeding-programs/{program_id}/objectives", payload, headers
        )

    def list_objectives(self, program_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/breeding-programs/{program_id}/objectives", params, headers
        )

    def get_objective(self, objective_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/breeding-objectives/{objective_id}", None, headers
        )

    def list_program_trial_series(
        self, program_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"/breeding-programs/{program_id}/trial-series", params, headers
        )

    def get_pipeline_report(self, program_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/breeding-programs/{program_id}/pipeline-report", None, headers
        )

    # ─── Nursery and crossing blocks (PRD 3.2, 3.3) ───

    def create_nursery_block(self, payload, headers) -> requests.Response:
        return self._request("POST", "/nursery-blocks", payload, headers)

    def get_nursery_block(self, block_id: str, headers) -> requests.Response:
        return self._request("GET", f"/nursery-blocks/{block_id}", None, headers)

    def create_crossing_block(self, payload, headers) -> requests.Response:
        return self._request("POST", "/crossing-blocks", payload, headers)

    def get_crossing_block(self, block_id: str, headers) -> requests.Response:
        return self._request("GET", f"/crossing-blocks/{block_id}", None, headers)

    def list_crossing_blocks(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/crossing-blocks", params, headers)

    def pollinate_crossing_block(
        self, block_id: str, payload, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/crossing-blocks/{block_id}/pollinate", payload, headers
        )

    def create_progeny(self, block_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/crossing-blocks/{block_id}/progenies", payload, headers
        )

    # ─── Breeding lines (PRD 3.2) ─────────────────────

    def create_line(self, payload, headers) -> requests.Response:
        return self._request("POST", "/breeding-lines", payload, headers)

    def get_line(self, line_id: str, headers) -> requests.Response:
        return self._request("GET", f"/breeding-lines/{line_id}", None, headers)

    def list_lines(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/breeding-lines", params, headers)

    # ─── Nursery plantings (PRD 3.3) ──────────────────

    def create_planting(self, payload, headers) -> requests.Response:
        return self._request("POST", "/nursery-plantings", payload, headers)

    def get_planting(self, planting_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/nursery-plantings/{planting_id}", None, headers
        )

    def list_plantings(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/nursery-plantings", params, headers)

    def plant_planting(self, planting_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/nursery-plantings/{planting_id}/plant", payload or {}, headers
        )

    def harvest_planting(self, planting_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/nursery-plantings/{planting_id}/harvest", payload, headers
        )

    # ─── Trial sites, series, entries (PRD 3.5, 3.6) ──

    def create_site(self, payload, headers) -> requests.Response:
        return self._request("POST", "/trial-sites", payload, headers)

    def get_site(self, site_id: str, headers) -> requests.Response:
        return self._request("GET", f"/trial-sites/{site_id}", None, headers)

    def create_series(self, payload, headers) -> requests.Response:
        return self._request("POST", "/trial-series", payload, headers)

    def get_series(self, series_id: str, headers) -> requests.Response:
        return self._request("GET", f"/trial-series/{series_id}", None, headers)

    def create_entry(self, series_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/trial-series/{series_id}/entries", payload, headers
        )

    def plant_series(self, series_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/trial-series/{series_id}/plant", payload or {}, headers
        )

    def close_series(self, series_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/trial-series/{series_id}/close", payload or {}, headers
        )

    def create_analysis(self, series_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/trial-series/{series_id}/analyses", payload, headers
        )

    def list_analyses(self, series_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/trial-series/{series_id}/analyses", params, headers
        )

    def get_entry(self, entry_id: str, headers) -> requests.Response:
        return self._request("GET", f"/trial-entries/{entry_id}", None, headers)

    def list_entries(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/trial-entries", params, headers)

    def create_observation(self, entry_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/trial-entries/{entry_id}/observations", payload, headers
        )

    def list_observations(self, entry_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/trial-entries/{entry_id}/observations", params, headers
        )

    def finalize_entry(self, entry_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/trial-entries/{entry_id}/finalize", payload or {}, headers
        )

    def withdraw_entry(self, entry_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/trial-entries/{entry_id}/withdraw", payload, headers
        )

    def invalidate_entry(self, entry_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/trial-entries/{entry_id}/invalidate", payload or {}, headers
        )

    # ─── Advancement decisions (PRD 3.8) ──────────────

    def create_decision(self, payload, headers) -> requests.Response:
        return self._request("POST", "/advancement-decisions", payload, headers)

    def get_decision(self, decision_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/advancement-decisions/{decision_id}", None, headers
        )

    def list_decisions(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/advancement-decisions", params, headers)

    # ─── Stewardship agreements (PRD 3.9) ─────────────

    def create_agreement(self, line_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/breeding-lines/{line_id}/stewardship-agreements", payload, headers
        )

    def list_line_agreements(self, line_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/breeding-lines/{line_id}/stewardship-agreements", params, headers
        )

    def get_agreement(self, agreement_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/stewardship-agreements/{agreement_id}", None, headers
        )

    def submit_agreement(self, agreement_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/stewardship-agreements/{agreement_id}/submit", payload or {}, headers
        )

    def review_agreement(self, agreement_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/stewardship-agreements/{agreement_id}/review", payload, headers
        )

    def suspend_agreement(self, agreement_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/stewardship-agreements/{agreement_id}/suspend", payload, headers
        )

    # ─── Seed increase lots (PRD 3.9) ─────────────────

    def create_lot(self, payload, headers) -> requests.Response:
        return self._request("POST", "/seed-increase-lots", payload, headers)

    def get_lot(self, lot_id: str, headers) -> requests.Response:
        return self._request("GET", f"/seed-increase-lots/{lot_id}", None, headers)

    def list_line_lots(self, line_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/breeding-lines/{line_id}/seed-increase-lots", params, headers
        )

    def start_lot_production(self, lot_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/seed-increase-lots/{lot_id}/start-production", payload or {}, headers
        )

    def complete_lot(self, lot_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/seed-increase-lots/{lot_id}/complete", payload or {}, headers
        )

    def cancel_lot(self, lot_id: str, headers, payload=None) -> requests.Response:
        return self._request(
            "POST", f"/seed-increase-lots/{lot_id}/cancel", payload or {}, headers
        )

    # ─── Backcross projects (PRD 3.4) ─────────────────

    def create_backcross(self, payload, headers) -> requests.Response:
        return self._request("POST", "/backcross-projects", payload, headers)

    def get_backcross(self, project_id: str, headers) -> requests.Response:
        return self._request("GET", f"/backcross-projects/{project_id}", None, headers)

    def list_backcrosses(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/backcross-projects", params, headers)

    def marker_cycle(self, project_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/backcross-projects/{project_id}/marker-cycle", payload, headers
        )

    # ─── Logical clock (PRD 2.5) ──────────────────────

    def set_clock(self, current_utc: str, headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Convenience readers ──────────────────────────

    def line_version(self, line_id: str, headers) -> int:
        """Read a line's current `version` for an optimistic-concurrency write."""
        return self.get_line(line_id, headers).json()["data"]["version"]

    def series_version(self, series_id: str, headers) -> int:
        """Read a series' current `version` for an optimistic-concurrency write."""
        return self.get_series(series_id, headers).json()["data"]["version"]
