"""HTTP client with one method per endpoint of the audio post-production API.

Every method returns the raw ``requests.Response`` so tests can assert on the
transport status as well as on the envelope. Domain instants are normalised on
the way out with :func:`canonical_instant` so a caller may pass either a
``datetime`` or a string and always send whole-second ISO-8601 UTC.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Any) -> Any:
    """Return an instant as whole-second ISO-8601 UTC with a trailing Z.

    Accepts a ``datetime``, a string already in that shape, or a string that
    carries fractional seconds or a ``+00:00`` offset. Anything else — including
    a deliberately malformed instant used to exercise schema validation — is
    passed through untouched.
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str):
        return value
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_INSTANT_FIELDS = (
    "current_utc",
    "delivery_deadline_utc",
    "window_start_utc",
    "window_end_utc",
    "expires_at_utc",
)


def _normalise_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return payload
    normalised = dict(payload)
    for field in _INSTANT_FIELDS:
        if field in normalised and normalised[field] is not None:
            normalised[field] = canonical_instant(normalised[field])
    return normalised


class ApiClient(GenericApiClient):
    """One method per endpoint declared by the requirements document."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", _normalise_payload(payload), headers
        )

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock", None, headers)

    # ------------------------------------------------------------------
    # Platform specifications
    # ------------------------------------------------------------------

    def create_platform_spec(self, payload, headers=None):
        return self._request("POST", "/platform-specs", _normalise_payload(payload), headers)

    def get_platform_spec(self, spec_id, headers=None):
        return self._request("GET", f"/platform-specs/{spec_id}", None, headers)

    # ------------------------------------------------------------------
    # Mix stages
    # ------------------------------------------------------------------

    def create_mix_stage(self, payload, headers=None):
        return self._request("POST", "/mix-stages", _normalise_payload(payload), headers)

    def get_mix_stage(self, stage_id, headers=None):
        return self._request("GET", f"/mix-stages/{stage_id}", None, headers)

    # ------------------------------------------------------------------
    # Mixers
    # ------------------------------------------------------------------

    def create_mixer(self, payload, headers=None):
        return self._request("POST", "/mixers", _normalise_payload(payload), headers)

    def get_mixer(self, mixer_id, headers=None):
        return self._request("GET", f"/mixers/{mixer_id}", None, headers)

    # ------------------------------------------------------------------
    # Voice talent
    # ------------------------------------------------------------------

    def create_voice_talent(self, payload, headers=None):
        return self._request("POST", "/voice-talents", _normalise_payload(payload), headers)

    def get_voice_talent(self, talent_id, headers=None):
        return self._request("GET", f"/voice-talents/{talent_id}", None, headers)

    # ------------------------------------------------------------------
    # Library assets
    # ------------------------------------------------------------------

    def create_library_asset(self, payload, headers=None):
        return self._request("POST", "/library-assets", _normalise_payload(payload), headers)

    def get_library_asset(self, asset_id, headers=None):
        return self._request("GET", f"/library-assets/{asset_id}", None, headers)

    def list_library_assets(self, headers=None, params=None):
        return self._request("GET", "/library-assets", None, headers, params)

    def revoke_library_asset(self, asset_id, payload, headers=None):
        return self._request(
            "POST", f"/library-assets/{asset_id}/revoke", _normalise_payload(payload), headers
        )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create_project(self, payload, headers=None):
        return self._request("POST", "/projects", _normalise_payload(payload), headers)

    def get_project(self, project_id, headers=None):
        return self._request("GET", f"/projects/{project_id}", None, headers)

    def list_projects(self, headers=None, params=None):
        return self._request("GET", "/projects", None, headers, params)

    def picture_lock(self, project_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/projects/{project_id}/picture-lock",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def break_picture_lock(self, project_id, payload, headers=None):
        return self._request(
            "POST",
            f"/projects/{project_id}/break-picture-lock",
            _normalise_payload(payload),
            headers,
        )

    def get_project_ledger(self, project_id, headers=None):
        return self._request("GET", f"/projects/{project_id}/ledger", None, headers)

    def create_archive_package(self, project_id, payload, headers=None):
        return self._request(
            "POST",
            f"/projects/{project_id}/archive-packages",
            _normalise_payload(payload),
            headers,
        )

    def list_archive_packages(self, project_id, headers=None, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/archive-packages", None, headers, params
        )

    # ------------------------------------------------------------------
    # Stem packages, music cues and the conform pass
    # ------------------------------------------------------------------

    def create_stem_package(self, payload, headers=None):
        return self._request("POST", "/stem-packages", _normalise_payload(payload), headers)

    def get_stem_package(self, stem_package_id, headers=None):
        return self._request("GET", f"/stem-packages/{stem_package_id}", None, headers)

    def list_stem_packages(self, headers=None, params=None):
        return self._request("GET", "/stem-packages", None, headers, params)

    def create_music_cue(self, stem_package_id, payload, headers=None):
        return self._request(
            "POST",
            f"/stem-packages/{stem_package_id}/music-cues",
            _normalise_payload(payload),
            headers,
        )

    def list_music_cues(self, stem_package_id, headers=None, params=None):
        return self._request(
            "GET", f"/stem-packages/{stem_package_id}/music-cues", None, headers, params
        )

    def conform_stem_package(self, stem_package_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/stem-packages/{stem_package_id}/conform",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    # ------------------------------------------------------------------
    # Asset usages
    # ------------------------------------------------------------------

    def create_asset_usage(self, payload, headers=None):
        return self._request("POST", "/asset-usages", _normalise_payload(payload), headers)

    def get_asset_usage(self, usage_id, headers=None):
        return self._request("GET", f"/asset-usages/{usage_id}", None, headers)

    def list_asset_usages(self, headers=None, params=None):
        return self._request("GET", "/asset-usages", None, headers, params)

    # ------------------------------------------------------------------
    # ADR sessions
    # ------------------------------------------------------------------

    def create_adr_session(self, payload, headers=None):
        return self._request("POST", "/adr-sessions", _normalise_payload(payload), headers)

    def get_adr_session(self, session_id, headers=None):
        return self._request("GET", f"/adr-sessions/{session_id}", None, headers)

    def list_adr_sessions(self, headers=None, params=None):
        return self._request("GET", "/adr-sessions", None, headers, params)

    def confirm_adr_session(self, session_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/adr-sessions/{session_id}/confirm",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def record_adr_session(self, session_id, payload, headers=None):
        return self._request(
            "POST", f"/adr-sessions/{session_id}/record", _normalise_payload(payload), headers
        )

    def cancel_adr_session(self, session_id, payload, headers=None):
        return self._request(
            "POST", f"/adr-sessions/{session_id}/cancel", _normalise_payload(payload), headers
        )

    # ------------------------------------------------------------------
    # Mix stage bookings
    # ------------------------------------------------------------------

    def create_mix_booking(self, payload, headers=None):
        return self._request("POST", "/mix-bookings", _normalise_payload(payload), headers)

    def get_mix_booking(self, booking_id, headers=None):
        return self._request("GET", f"/mix-bookings/{booking_id}", None, headers)

    def list_mix_bookings(self, headers=None, params=None):
        return self._request("GET", "/mix-bookings", None, headers, params)

    def confirm_mix_booking(self, booking_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/mix-bookings/{booking_id}/confirm",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def start_mix_booking(self, booking_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/mix-bookings/{booking_id}/start",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def complete_mix_booking(self, booking_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/mix-bookings/{booking_id}/complete",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def client_signoff_mix_booking(self, booking_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/mix-bookings/{booking_id}/client-signoff",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def release_mix_booking(self, booking_id, payload, headers=None):
        return self._request(
            "POST", f"/mix-bookings/{booking_id}/release", _normalise_payload(payload), headers
        )

    # ------------------------------------------------------------------
    # Deliverables and the QC loop
    # ------------------------------------------------------------------

    def create_deliverable(self, payload, headers=None):
        return self._request("POST", "/deliverables", _normalise_payload(payload), headers)

    def get_deliverable(self, deliverable_id, headers=None):
        return self._request("GET", f"/deliverables/{deliverable_id}", None, headers)

    def list_deliverables(self, headers=None, params=None):
        return self._request("GET", "/deliverables", None, headers, params)

    def qc_submit(self, deliverable_id, payload, headers=None):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/qc-submit", _normalise_payload(payload), headers
        )

    def qc_evaluate(self, deliverable_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/deliverables/{deliverable_id}/qc-evaluate",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def list_qc_reports(self, deliverable_id, headers=None, params=None):
        return self._request(
            "GET", f"/deliverables/{deliverable_id}/qc-reports", None, headers, params
        )

    def remediate_deliverable(self, deliverable_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/deliverables/{deliverable_id}/remediate",
            _normalise_payload(payload if payload is not None else {}),
            headers,
        )

    def deliver_deliverable(self, deliverable_id, payload, headers=None):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/deliver", _normalise_payload(payload), headers
        )
