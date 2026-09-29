"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the ``/catalog-circulation`` prefix.

This module also owns ISO 8601 canonicalisation. The PRD requires every
timestamp to be an ISO 8601 UTC string with exactly three fractional-second
digits, but comparing a timestamp the test supplied against a timestamp the
service echoed back must not fail merely because one side wrote
``2026-09-15T00:00:00Z`` and the other ``2026-09-15T00:00:00.000Z``. Use
``canonical_timestamp`` / ``timestamps_equal`` for every such comparison.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/catalog-circulation"

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_timestamp(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Accepts a bare date, a second-precision instant, a millisecond instant,
    or a microsecond instant, with or without the trailing ``Z``. Returns the
    input unchanged when it is not a recognisable instant (so an assertion
    failure still shows the raw server value).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value.strip())
    if not match:
        return value
    year, month, day, hour, minute, second, frac, _tz = match.groups()
    hour = hour or "00"
    minute = minute or "00"
    second = second or "00"
    millis = (frac or "").ljust(3, "0")[:3]
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}.{millis}Z"


def timestamps_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 instants denote the same moment."""
    return canonical_timestamp(left) == canonical_timestamp(right)


def iso_utc(date_str: str, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """Build a canonical instant from a ``YYYY-MM-DD`` calendar date."""
    year, month, day = (int(part) for part in date_str.split("-"))
    stamp = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def shift_days(instant: str, days: int) -> str:
    """Return the canonical instant ``days`` whole days after ``instant``."""
    canonical = canonical_timestamp(instant)
    base = datetime.strptime(canonical, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    moved = base + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


class ApiClient(GenericApiClient):
    """One method per endpoint the PRD declares."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    def ingest_online_orders(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_online-orders/ingest", payload, headers
        )

    # -------------------------------------------------------------- seasons
    def create_season(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/seasons/{season_id}", headers=headers
        )

    # ----------------------------------------------------- suppression rules
    def create_suppression_rule(self, season_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/seasons/{season_id}/suppression-rules",
            payload,
            headers,
        )

    def list_suppression_rules(self, season_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/seasons/{season_id}/suppression-rules",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------- housefile segments
    def create_segment(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/housefile-segments", payload, headers
        )

    def update_segment(self, segment_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/housefile-segments/{segment_id}", payload, headers
        )

    def get_segment(self, segment_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/housefile-segments/{segment_id}", headers=headers
        )

    def list_segments(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/housefile-segments", headers=headers, params=params
        )

    def list_segment_contact_events(self, segment_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/housefile-segments/{segment_id}/contact-events",
            headers=headers,
            params=params,
        )

    # --------------------------------------------- prospect list rentals
    def create_rental(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/prospect-list-rentals", payload, headers
        )

    def get_rental(self, rental_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/prospect-list-rentals/{rental_id}", headers=headers
        )

    def list_season_rentals(self, season_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/seasons/{season_id}/prospect-list-rentals",
            headers=headers,
            params=params,
        )

    def model_rental(self, rental_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/prospect-list-rentals/{rental_id}/model",
            payload,
            headers,
        )

    def order_rental(self, rental_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/prospect-list-rentals/{rental_id}/order",
            payload,
            headers,
        )

    def deliver_rental(self, rental_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/prospect-list-rentals/{rental_id}/deliver",
            payload,
            headers,
        )

    def cancel_rental(self, rental_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/prospect-list-rentals/{rental_id}/cancel",
            payload,
            headers,
        )

    # ---------------------------------------------------- circulation plans
    def create_plan(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/circulation-plans", payload, headers
        )

    def get_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/circulation-plans/{plan_id}", headers=headers
        )

    def list_season_plans(self, season_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/seasons/{season_id}/circulation-plans",
            headers=headers,
            params=params,
        )

    def get_plan_profitability(self, plan_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/circulation-plans/{plan_id}/profitability",
            headers=headers,
        )

    def cost_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/circulation-plans/{plan_id}/cost", payload, headers
        )

    def submit_plan_for_review(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/circulation-plans/{plan_id}/submit-review",
            payload,
            headers,
        )

    def request_plan_revision(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/circulation-plans/{plan_id}/request-revision",
            payload,
            headers,
        )

    def approve_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/circulation-plans/{plan_id}/approve",
            payload,
            headers,
        )

    def cancel_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/circulation-plans/{plan_id}/cancel", payload, headers
        )

    # ------------------------------------------------------ merge-purge runs
    def create_merge_purge_run(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/circulation-plans/{plan_id}/merge-purge-runs",
            payload,
            headers,
        )

    def list_merge_purge_runs(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/circulation-plans/{plan_id}/merge-purge-runs",
            headers=headers,
            params=params,
        )

    # ---------------------------------------------------------------- drops
    def create_drop(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/circulation-plans/{plan_id}/drops", payload, headers
        )

    def list_plan_drops(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/circulation-plans/{plan_id}/drops",
            headers=headers,
            params=params,
        )

    def get_drop(self, drop_id, headers):
        return self._request("GET", f"{API_PREFIX}/drops/{drop_id}", headers=headers)

    def update_drop(self, drop_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/drops/{drop_id}", payload, headers
        )

    def allocate_drop(self, drop_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/allocate", payload, headers
        )

    def presort_drop(self, drop_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/presort", payload, headers
        )

    def mail_drop(self, drop_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/mail", payload, headers
        )

    def deliver_drop(self, drop_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/deliver", payload, headers
        )

    # ----------------------------------------------------- circulation lines
    def create_line(self, drop_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/circulation-lines", payload, headers
        )

    def get_line(self, line_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/circulation-lines/{line_id}", headers=headers
        )

    def list_lines(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/circulation-lines", headers=headers, params=params
        )

    def void_line(self, line_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/circulation-lines/{line_id}/void", payload, headers
        )

    # -------------------------------------------------------- page placements
    def create_page_placement(self, drop_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/page-placements", payload, headers
        )

    def list_page_placements(self, drop_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/drops/{drop_id}/page-placements",
            headers=headers,
            params=params,
        )

    def delete_page_placement(self, placement_id, headers):
        return self._request(
            "DELETE", f"{API_PREFIX}/page-placements/{placement_id}", headers=headers
        )

    # ------------------------------------------------------- presort batches
    def create_presort_batch(self, drop_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/presort-batches", payload, headers
        )

    def list_presort_batches(self, drop_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/drops/{drop_id}/presort-batches",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------------- contact events
    def create_contact_event(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/contact-events", payload, headers
        )

    def list_drop_contact_events(self, drop_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/drops/{drop_id}/contact-events",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ test cells
    def create_test_cell(self, line_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/circulation-lines/{line_id}/test-cells",
            payload,
            headers,
        )

    def list_test_cells(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/circulation-lines/{line_id}/test-cells",
            headers=headers,
            params=params,
        )

    def get_test_cell(self, cell_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/test-cells/{cell_id}", headers=headers
        )

    def measure_test_cell(self, cell_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/test-cells/{cell_id}/measure", payload, headers
        )

    # -------------------------------------------------------- matchback runs
    def create_matchback_run(self, drop_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drops/{drop_id}/matchback-runs", payload, headers
        )

    def list_matchback_runs(self, drop_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/drops/{drop_id}/matchback-runs",
            headers=headers,
            params=params,
        )

    def finalize_matchback_run(self, run_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/matchback-runs/{run_id}/finalize",
            payload,
            headers,
        )


api_client = ApiClient()
