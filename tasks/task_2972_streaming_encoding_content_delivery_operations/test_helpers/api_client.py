"""Typed HTTP client: one method per endpoint of PRD §4.

Every method returns the raw ``requests.Response`` so that tests can assert
status codes and error envelopes themselves.

Instant canonicalisation: PRD §2.4 stores every timestamp as "ISO 8601 UTC with
exactly three fractional digits", while the design literals in this suite are
written in the compact ``2026-08-01T00:00:00Z`` form.  ``canonical_instant``
reduces both spellings to a single comparable form so no test has to reason
about sub-second width, and ``instants_equal`` compares two instants at the
millisecond resolution PRD §2.8 pins for instant comparisons.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant of any fractional-second width."""
    assert isinstance(value, str), f"instant must be a string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: str) -> str:
    """Return an instant in the PRD's storage spelling: three fractional digits."""
    parsed = parse_instant(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def instants_equal(left: str, right: str) -> bool:
    """Compare two instants at millisecond resolution (PRD §2.8)."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per row of the PRD §4 endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock and availability sweep (§2.5)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_availability_sweep(self, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", "/availability-sweep", payload or {}, headers)

    # ------------------------------------------------------------------
    # Titles (§3.1, §3.6)
    # ------------------------------------------------------------------
    def create_title(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/titles/{title_id}", None, headers)

    def list_titles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/titles", None, headers, params=params)

    def patch_title(self, title_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/titles/{title_id}", payload, headers)

    def takedown_title(self, title_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/titles/{title_id}/takedown", payload, headers)

    def create_availability_window(
        self, title_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/titles/{title_id}/availability-windows", payload, headers
        )

    def list_availability_windows(
        self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/titles/{title_id}/availability-windows", None, headers, params=params
        )

    def list_title_mezzanine_assets(
        self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/titles/{title_id}/mezzanine-assets", None, headers, params=params
        )

    def cancel_availability_window(
        self, window_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/availability-windows/{window_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Mezzanine assets and quality control (§3.2)
    # ------------------------------------------------------------------
    def create_mezzanine_asset(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/mezzanine-assets", payload, headers)

    def get_mezzanine_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mezzanine-assets/{asset_id}", None, headers)

    def run_qc(self, asset_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/mezzanine-assets/{asset_id}/qc-runs", payload or {}, headers
        )

    def request_remediation(
        self, asset_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"/mezzanine-assets/{asset_id}/remediation-request",
            payload or {},
            headers,
        )

    def resubmit_mezzanine_asset(
        self, asset_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mezzanine-assets/{asset_id}/resubmit", payload, headers
        )

    def list_qc_reports(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/mezzanine-assets/{asset_id}/qc-reports", None, headers, params=params
        )

    # ------------------------------------------------------------------
    # Encoding ladders (§3.3, §3.4)
    # ------------------------------------------------------------------
    def create_encoding_ladder(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/encoding-ladders", payload, headers)

    def get_encoding_ladder(self, ladder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/encoding-ladders/{ladder_id}", None, headers)

    def list_encoding_ladders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/encoding-ladders", None, headers, params=params)

    def validate_encoding_ladder(
        self, ladder_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/encoding-ladders/{ladder_id}/validate", payload or {}, headers
        )

    def lock_encoding_ladder(
        self, ladder_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/encoding-ladders/{ladder_id}/lock", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Device profiles (§3.3)
    # ------------------------------------------------------------------
    def create_device_profile(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/device-profiles", payload, headers)

    def list_device_profiles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/device-profiles", None, headers, params=params)

    # ------------------------------------------------------------------
    # DRM packages, entitlement rules and playback entitlement (§3.5)
    # ------------------------------------------------------------------
    def create_drm_package(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/drm-packages", payload, headers)

    def get_drm_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/drm-packages/{package_id}", None, headers)

    def list_drm_packages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/drm-packages", None, headers, params=params)

    def package_drm_package(
        self, package_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/drm-packages/{package_id}/package", payload or {}, headers
        )

    def revoke_drm_package(
        self, package_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/drm-packages/{package_id}/revoke", payload or {}, headers
        )

    def create_entitlement_rule(
        self, package_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/drm-packages/{package_id}/entitlement-rules", payload, headers
        )

    def list_entitlement_rules(
        self, package_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/drm-packages/{package_id}/entitlement-rules",
            None,
            headers,
            params=params,
        )

    def create_playback_entitlement_check(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/playback-entitlement-checks", payload, headers)

    # ------------------------------------------------------------------
    # CDN vendors, routing policies and playback metrics (§3.7)
    # ------------------------------------------------------------------
    def create_cdn_vendor(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/cdn-vendors", payload, headers)

    def get_cdn_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cdn-vendors/{vendor_id}", None, headers)

    def patch_cdn_vendor(self, vendor_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/cdn-vendors/{vendor_id}", payload, headers)

    def create_routing_policy(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/routing-policies", payload, headers)

    def get_routing_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/routing-policies/{policy_id}", None, headers)

    def list_routing_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/routing-policies", None, headers, params=params)

    def resteer_routing_policy(
        self, policy_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/routing-policies/{policy_id}/resteer", payload or {}, headers
        )

    def create_playback_metric(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/playback-metrics", payload, headers)

    def get_playback_metric(self, metric_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/playback-metrics/{metric_id}", None, headers)

    def list_playback_metrics(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/playback-metrics", None, headers, params=params)

    # ------------------------------------------------------------------
    # Live-event reservations (§3.8)
    # ------------------------------------------------------------------
    def create_live_reservation(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/live-reservations", payload, headers)

    def get_live_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/live-reservations/{reservation_id}", None, headers)

    def list_live_reservations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/live-reservations", None, headers, params=params)

    def arm_live_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/live-reservations/{reservation_id}/arm", payload or {}, headers
        )

    def failover_live_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/live-reservations/{reservation_id}/failover", payload or {}, headers
        )

    def cancel_live_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/live-reservations/{reservation_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Reprocessing jobs (§3.9)
    # ------------------------------------------------------------------
    def create_reprocess_job(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/reprocess-jobs", payload, headers)

    def get_reprocess_job(self, job_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reprocess-jobs/{job_id}", None, headers)

    def list_reprocess_jobs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/reprocess-jobs", None, headers, params=params)

    def run_reprocess_job(self, job_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/reprocess-jobs/{job_id}/run", payload or {}, headers
        )

    def abort_reprocess_job(self, job_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/reprocess-jobs/{job_id}/abort", payload, headers)

    # ------------------------------------------------------------------
    # Generic escape hatches for tests that must address a raw path
    # ------------------------------------------------------------------
    def get_path(
        self, path: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", path, None, headers, params=params)

    def post_path(self, path: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", path, payload, headers)

    def patch_path(self, path: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", path, payload, headers)


__all__: List[str] = [
    "ApiClient",
    "canonical_instant",
    "instants_equal",
    "parse_instant",
]
