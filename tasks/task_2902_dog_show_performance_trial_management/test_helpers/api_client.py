"""API client: one method per endpoint of the Dog Show Trials API.

Every endpoint is mounted beneath the `/dog-shows` prefix and every collection is
flat: parentage between resources travels in request bodies, not in nested paths.

The module also provides ISO-8601 canonicalisation so that a server writing
`2026-08-10T09:00:00Z` and a server writing `2026-08-10T09:00:00.000Z` compare
equal in tests: the PRD requires exactly three fractional digits, but tests must
not fail merely on sub-second width when the instant itself is right.
"""

import re
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/dog-shows"

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(?:Z|\+00:00)$"
)


def canonical_timestamp(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    Returns the input unchanged when it is not a recognisable UTC instant, so
    format assertions elsewhere still see the raw server value.
    """
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


def timestamps_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    """Compare two instants ignoring sub-second width differences."""
    return canonical_timestamp(actual) == canonical_timestamp(expected)


class ApiClient(GenericApiClient):
    """One method per endpoint row of the PRD's endpoint table."""

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Clubs ────────────────────────────────────────────────────────────────

    def create_club(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clubs", payload, headers)

    def get_club(self, club_id, headers):
        return self._request("GET", f"{PREFIX}/clubs/{club_id}", headers=headers)

    # ─── Judges ───────────────────────────────────────────────────────────────

    def create_judge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/judges", payload, headers)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"{PREFIX}/judges/{judge_id}", headers=headers)

    def record_dog_measurement(self, dog_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dogs/{dog_id}/measurement", payload, headers
        )

    # ─── Handlers ─────────────────────────────────────────────────────────────

    def create_handler(self, payload, headers):
        return self._request("POST", f"{PREFIX}/handlers", payload, headers)

    def get_handler(self, handler_id, headers):
        return self._request("GET", f"{PREFIX}/handlers/{handler_id}", headers=headers)

    # ─── Shows ────────────────────────────────────────────────────────────────

    def create_show(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shows", payload, headers)

    def get_show(self, show_id, headers):
        return self._request("GET", f"{PREFIX}/shows/{show_id}", headers=headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shows", headers=headers, params=params)

    def submit_show(self, show_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shows/{show_id}/submit", payload or {}, headers
        )

    def approve_show(self, show_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shows/{show_id}/approve", payload or {}, headers
        )

    def return_show(self, show_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shows/{show_id}/return", payload, headers
        )

    def open_show_day(self, show_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shows/{show_id}/open-day", payload or {}, headers
        )

    def close_show(self, show_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shows/{show_id}/close", payload or {}, headers
        )

    def record_temperature_reading(self, show_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shows/{show_id}/temperature-readings", payload, headers
        )

    def list_show_registry_filings(self, show_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/shows/{show_id}/registry-filings",
            headers=headers, params=params,
        )

    # ─── Panel slots ──────────────────────────────────────────────────────────

    def create_panel_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/panel-slots", payload, headers)

    def get_panel_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/panel-slots/{slot_id}", headers=headers)

    def list_panel_slots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/panel-slots", headers=headers, params=params
        )

    def respond_to_panel_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/panel-slots/{slot_id}/respond", payload, headers
        )

    # ─── Classes ──────────────────────────────────────────────────────────────

    def create_class(self, payload, headers):
        return self._request("POST", f"{PREFIX}/classes", payload, headers)

    def get_class(self, class_id, headers):
        return self._request("GET", f"{PREFIX}/classes/{class_id}", headers=headers)

    def list_classes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/classes", headers=headers, params=params)

    def assign_judge_to_class(self, class_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/classes/{class_id}/assign-judge", payload, headers
        )

    def close_class_entries(self, class_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/classes/{class_id}/close-entries", payload or {}, headers
        )

    def complete_class(self, class_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/classes/{class_id}/complete", payload, headers
        )

    # ─── Dogs ─────────────────────────────────────────────────────────────────

    def create_dog(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dogs", payload, headers)

    def get_dog(self, dog_id, headers):
        return self._request("GET", f"{PREFIX}/dogs/{dog_id}", headers=headers)

    def list_dogs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dogs", headers=headers, params=params)

    # ─── Entries ──────────────────────────────────────────────────────────────

    def create_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/entries", headers=headers, params=params)

    def confirm_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/confirm", payload or {}, headers
        )

    def check_in_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/check-in", payload, headers
        )

    def declare_season(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/entries/{entry_id}/declare-season", payload or {}, headers
        )

    def list_entry_performance_runs(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/entries/{entry_id}/performance-runs",
            headers=headers, params=params,
        )

    # ─── Ring blocks ──────────────────────────────────────────────────────────

    def create_ring_block(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ring-blocks", payload, headers)

    def get_ring_block(self, block_id, headers):
        return self._request("GET", f"{PREFIX}/ring-blocks/{block_id}", headers=headers)

    def list_ring_blocks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ring-blocks", headers=headers, params=params
        )

    def publish_ring_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/ring-blocks/{block_id}/publish", payload or {}, headers
        )

    def reschedule_ring_block(self, block_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ring-blocks/{block_id}/reschedule", payload, headers
        )

    # ─── Performance runs ─────────────────────────────────────────────────────

    def create_performance_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/performance-runs", payload, headers)

    # ─── Protests ─────────────────────────────────────────────────────────────

    def create_protest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"{PREFIX}/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/protests", headers=headers, params=params)

    def begin_protest_review(self, protest_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/begin-review", payload or {}, headers
        )

    def request_protest_evidence(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/request-evidence", payload, headers
        )

    def resubmit_protest_evidence(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/resubmit-evidence", payload, headers
        )

    def decide_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/decide", payload, headers
        )

    # ─── Registry filings ─────────────────────────────────────────────────────

    def create_registry_filing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/registry-filings", payload, headers)

    def get_registry_filing(self, filing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/registry-filings/{filing_id}", headers=headers
        )

    def adjudicate_registry_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registry-filings/{filing_id}/adjudicate", payload, headers
        )


api_client = ApiClient()
