"""One transport method per endpoint of the fleet interface.

Every method returns the raw HTTP response so a test can assert on the
status code and the envelope.  Path construction lives here and nowhere
else.  ``X-User-ID`` headers are never bound to a real entity id, because
identity in this interface is opaque.
"""

import os
import re

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    # ─── envelope + logical clock ─────────────────────────────────────────

    def health(self, headers):
        return self._request("GET", "/fleet/health", headers=headers)

    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── ServiceTerritory ─────────────────────────────────────────────────

    def create_territory(self, payload, headers):
        return self._request("POST", "/fleet/territories", payload, headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/fleet/territories", headers=headers, params=params)

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"/fleet/territories/{territory_id}", headers=headers
        )

    def mapping_tick(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/mapping-ticks",
            payload,
            headers,
        )

    def validation_run(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/validation-runs",
            payload,
            headers,
        )

    def weather_tier_tick(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/weather-tier-ticks",
            payload,
            headers,
        )

    # ─── DepotSite ────────────────────────────────────────────────────────

    def create_depot(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/fleet/territories/{territory_id}/depots", payload, headers
        )

    def list_depots(self, headers, params=None):
        return self._request("GET", "/fleet/depots", headers=headers, params=params)

    def list_territory_depots(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/depots",
            headers=headers,
            params=params,
        )

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/fleet/depots/{depot_id}", headers=headers)

    def list_depot_vehicles(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/depots/{depot_id}/vehicles", headers=headers, params=params
        )

    def run_depot_ops(self, depot_id, headers):
        return self._request(
            "POST", f"/fleet/depots/{depot_id}/run-depot-ops", {}, headers
        )

    # ─── BaySlot ──────────────────────────────────────────────────────────

    def create_bay_slot(self, depot_id, payload, headers):
        return self._request(
            "POST", f"/fleet/depots/{depot_id}/bay-slots", payload, headers
        )

    def list_bay_slots(self, headers, params=None):
        return self._request("GET", "/fleet/bay-slots", headers=headers, params=params)

    def list_depot_bay_slots(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/depots/{depot_id}/bay-slots", headers=headers, params=params
        )

    def get_bay_slot(self, bay_slot_id, headers):
        return self._request("GET", f"/fleet/bay-slots/{bay_slot_id}", headers=headers)

    def release_bay_slot(self, depot_id, bay_slot_id, headers):
        return self._request(
            "POST",
            f"/fleet/depots/{depot_id}/bay-slots/{bay_slot_id}/release",
            {},
            headers,
        )

    # ─── Vehicle ──────────────────────────────────────────────────────────

    def create_vehicle(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/fleet/territories/{territory_id}/vehicles", payload, headers
        )

    def list_territory_vehicles(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/vehicles",
            headers=headers,
            params=params,
        )

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/fleet/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/fleet/vehicles/{vehicle_id}", headers=headers)

    def stage_vehicle(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/fleet/vehicles/{vehicle_id}/stage", payload, headers
        )

    def return_vehicle_to_service(self, vehicle_id, headers):
        return self._request(
            "POST", f"/fleet/vehicles/{vehicle_id}/return-to-service", {}, headers
        )

    def suspend_vehicle(self, vehicle_id, headers):
        return self._request(
            "POST", f"/fleet/vehicles/{vehicle_id}/suspend", {}, headers
        )

    def clear_vehicle_suspension(self, vehicle_id, headers):
        return self._request(
            "POST", f"/fleet/vehicles/{vehicle_id}/clear-suspension", {}, headers
        )

    def list_vehicle_assistance_sessions(self, vehicle_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/vehicles/{vehicle_id}/assistance-sessions",
            headers=headers,
            params=params,
        )

    # ─── DepotCycle ───────────────────────────────────────────────────────

    def create_cycle(self, depot_id, payload, headers):
        return self._request(
            "POST", f"/fleet/depots/{depot_id}/cycles", payload, headers
        )

    def list_depot_cycles(self, depot_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/depots/{depot_id}/cycles", headers=headers, params=params
        )

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/fleet/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/fleet/cycles/{cycle_id}", headers=headers)

    def schedule_cycle(self, depot_id, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/depots/{depot_id}/cycles/{cycle_id}/schedule",
            payload,
            headers,
        )

    def start_cycle(self, depot_id, cycle_id, headers):
        return self._request(
            "POST", f"/fleet/depots/{depot_id}/cycles/{cycle_id}/start", {}, headers
        )

    def complete_cycle(self, depot_id, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/depots/{depot_id}/cycles/{cycle_id}/complete",
            payload,
            headers,
        )

    def abort_cycle(self, depot_id, cycle_id, headers):
        return self._request(
            "POST", f"/fleet/depots/{depot_id}/cycles/{cycle_id}/abort", {}, headers
        )

    # ─── DemandSignal + DeploymentWave ────────────────────────────────────

    def upsert_demand_signal(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/demand-signals",
            payload,
            headers,
        )

    def list_territory_demand_signals(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/demand-signals",
            headers=headers,
            params=params,
        )

    def list_demand_signals(self, headers, params=None):
        return self._request(
            "GET", "/fleet/demand-signals", headers=headers, params=params
        )

    def get_demand_signal(self, signal_id, headers):
        return self._request(
            "GET", f"/fleet/demand-signals/{signal_id}", headers=headers
        )

    def create_wave(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/deployment-waves",
            payload,
            headers,
        )

    def list_territory_waves(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/deployment-waves",
            headers=headers,
            params=params,
        )

    def list_waves(self, headers, params=None):
        return self._request(
            "GET", "/fleet/deployment-waves", headers=headers, params=params
        )

    def get_wave(self, wave_id, headers):
        return self._request(
            "GET", f"/fleet/deployment-waves/{wave_id}", headers=headers
        )

    def activate_wave(self, territory_id, wave_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/deployment-waves/{wave_id}/activate",
            payload,
            headers,
        )

    def dispatch_wave(self, territory_id, wave_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/deployment-waves/{wave_id}/dispatch",
            {},
            headers,
        )

    def abort_wave(self, territory_id, wave_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/deployment-waves/{wave_id}/abort",
            {},
            headers,
        )

    # ─── ServiceAreaRule + ExclusionZone ──────────────────────────────────

    def create_area_rule(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/fleet/territories/{territory_id}/area-rules", payload, headers
        )

    def list_territory_area_rules(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/area-rules",
            headers=headers,
            params=params,
        )

    def list_area_rules(self, headers, params=None):
        return self._request("GET", "/fleet/area-rules", headers=headers, params=params)

    def get_area_rule(self, rule_id, headers):
        return self._request("GET", f"/fleet/area-rules/{rule_id}", headers=headers)

    def approve_area_rule(self, territory_id, rule_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/area-rules/{rule_id}/approve",
            {},
            headers,
        )

    def retire_area_rule(self, territory_id, rule_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/area-rules/{rule_id}/retire",
            payload,
            headers,
        )

    def create_exclusion_zone(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/exclusion-zones",
            payload,
            headers,
        )

    def list_territory_exclusion_zones(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/exclusion-zones",
            headers=headers,
            params=params,
        )

    def list_exclusion_zones(self, headers, params=None):
        return self._request(
            "GET", "/fleet/exclusion-zones", headers=headers, params=params
        )

    def get_exclusion_zone(self, zone_id, headers):
        return self._request(
            "GET", f"/fleet/exclusion-zones/{zone_id}", headers=headers
        )

    def activate_exclusion_zone(self, territory_id, zone_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/exclusion-zones/{zone_id}/activate",
            {},
            headers,
        )

    # ─── ServiceAreaExpansionRequest ──────────────────────────────────────

    def create_expansion_request(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/expansion-requests",
            payload,
            headers,
        )

    def list_territory_expansion_requests(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/expansion-requests",
            headers=headers,
            params=params,
        )

    def list_expansion_requests(self, headers, params=None):
        return self._request(
            "GET", "/fleet/expansion-requests", headers=headers, params=params
        )

    def get_expansion_request(self, expansion_id, headers):
        return self._request(
            "GET", f"/fleet/expansion-requests/{expansion_id}", headers=headers
        )

    def expansion_mapping_complete(self, expansion_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/expansion-requests/{expansion_id}/mapping-complete",
            payload,
            headers,
        )

    def approve_expansion(self, expansion_id, headers):
        return self._request(
            "POST", f"/fleet/expansion-requests/{expansion_id}/approve", {}, headers
        )

    def reject_expansion(self, expansion_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/expansion-requests/{expansion_id}/reject",
            payload,
            headers,
        )

    # ─── RideRequest ──────────────────────────────────────────────────────

    def create_ride(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/fleet/territories/{territory_id}/ride-requests", payload, headers
        )

    def list_territory_rides(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/ride-requests",
            headers=headers,
            params=params,
        )

    def list_rides(self, headers, params=None):
        return self._request(
            "GET", "/fleet/ride-requests", headers=headers, params=params
        )

    def get_ride(self, ride_id, headers):
        return self._request("GET", f"/fleet/ride-requests/{ride_id}", headers=headers)

    def get_territory_ride(self, territory_id, ride_id, headers):
        return self._request(
            "GET", f"/fleet/territories/{territory_id}/ride-requests/{ride_id}", headers=headers
        )

    def match_ride(self, territory_id, ride_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/ride-requests/{ride_id}/match",
            payload,
            headers,
        )

    def pickup_ride(self, territory_id, ride_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/ride-requests/{ride_id}/pickup",
            payload,
            headers,
        )

    def complete_ride(self, territory_id, ride_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/ride-requests/{ride_id}/complete",
            {},
            headers,
        )

    def cancel_ride(self, territory_id, ride_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/ride-requests/{ride_id}/cancel",
            payload,
            headers,
        )

    def cancel_ride_no_show(self, territory_id, ride_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/ride-requests/{ride_id}/cancel-no-show",
            {},
            headers,
        )

    # ─── PickupLocation + CurbRule ────────────────────────────────────────

    def create_pickup_location(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/pickup-locations",
            payload,
            headers,
        )

    def list_territory_pickup_locations(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/pickup-locations",
            headers=headers,
            params=params,
        )

    def list_pickup_locations(self, headers, params=None):
        return self._request(
            "GET", "/fleet/pickup-locations", headers=headers, params=params
        )

    def get_pickup_location(self, pickup_location_id, headers):
        return self._request(
            "GET", f"/fleet/pickup-locations/{pickup_location_id}", headers=headers
        )

    def list_pickup_location_rides(self, pickup_location_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/pickup-locations/{pickup_location_id}/ride-requests",
            headers=headers,
            params=params,
        )

    def reclassify_pickup_location(self, pickup_location_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/pickup-locations/{pickup_location_id}/reclassify",
            payload,
            headers,
        )

    def create_curb_rule(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/fleet/territories/{territory_id}/curb-rules", payload, headers
        )

    def list_territory_curb_rules(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/curb-rules",
            headers=headers,
            params=params,
        )

    def list_curb_rules(self, headers, params=None):
        return self._request("GET", "/fleet/curb-rules", headers=headers, params=params)

    def get_curb_rule(self, curb_rule_id, headers):
        return self._request(
            "GET", f"/fleet/curb-rules/{curb_rule_id}", headers=headers
        )

    def retire_curb_rule(self, territory_id, curb_rule_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/curb-rules/{curb_rule_id}/retire",
            payload,
            headers,
        )

    # ─── AssistanceSession ────────────────────────────────────────────────

    def create_assistance_session(self, territory_id, ride_id, payload, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/ride-requests/{ride_id}/assistance-sessions",
            payload,
            headers,
        )

    def list_assistance_sessions(self, headers, params=None):
        return self._request(
            "GET", "/fleet/assistance-sessions", headers=headers, params=params
        )

    def get_assistance_session(self, session_id, headers):
        return self._request(
            "GET", f"/fleet/assistance-sessions/{session_id}", headers=headers
        )

    def list_ride_assistance_sessions(self, ride_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/ride-requests/{ride_id}/assistance-sessions",
            headers=headers,
            params=params,
        )

    def acknowledge_session(self, session_id, headers):
        return self._request(
            "POST", f"/fleet/assistance-sessions/{session_id}/acknowledge", {}, headers
        )

    def resolve_session(self, session_id, headers):
        return self._request(
            "POST", f"/fleet/assistance-sessions/{session_id}/resolve", {}, headers
        )

    def escalate_session_unresolved(self, session_id, headers):
        return self._request(
            "POST",
            f"/fleet/assistance-sessions/{session_id}/escalate-unresolved",
            {},
            headers,
        )

    # ─── IncidentReport ───────────────────────────────────────────────────

    def film_incident(self, ride_id, payload, headers):
        return self._request(
            "POST", f"/fleet/ride-requests/{ride_id}/film-incident", payload, headers
        )

    def list_incident_reports(self, headers, params=None):
        return self._request(
            "GET", "/fleet/incident-reports", headers=headers, params=params
        )

    def get_incident_report(self, incident_id, headers):
        return self._request(
            "GET", f"/fleet/incident-reports/{incident_id}", headers=headers
        )

    def list_session_incident_reports(self, session_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/assistance-sessions/{session_id}/incident-reports",
            headers=headers,
            params=params,
        )

    def begin_incident_review(self, incident_id, headers):
        return self._request(
            "POST", f"/fleet/incident-reports/{incident_id}/begin-review", {}, headers
        )

    def close_incident_report(self, incident_id, headers):
        return self._request(
            "POST", f"/fleet/incident-reports/{incident_id}/close", {}, headers
        )

    def void_incident_report(self, incident_id, headers):
        return self._request(
            "POST", f"/fleet/incident-reports/{incident_id}/void", {}, headers
        )

    # ─── RoadsideTeam + RoadsideCase ──────────────────────────────────────

    def create_roadside_team(self, territory_id, payload, headers):
        return self._request(
            "POST", f"/fleet/territories/{territory_id}/roadside-teams", payload, headers
        )

    def list_territory_roadside_teams(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/roadside-teams",
            headers=headers,
            params=params,
        )

    def list_roadside_teams(self, headers, params=None):
        return self._request(
            "GET", "/fleet/roadside-teams", headers=headers, params=params
        )

    def get_roadside_team(self, team_id, headers):
        return self._request(
            "GET", f"/fleet/roadside-teams/{team_id}", headers=headers
        )

    def list_team_roadside_cases(self, team_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/roadside-teams/{team_id}/roadside-cases",
            headers=headers,
            params=params,
        )

    def mark_team_off_shift(self, territory_id, team_id, headers):
        return self._request(
            "POST",
            f"/fleet/territories/{territory_id}/roadside-teams/{team_id}/mark-off-shift",
            {},
            headers,
        )

    def open_roadside_case(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/fleet/vehicles/{vehicle_id}/roadside-cases", payload, headers
        )

    def list_territory_roadside_cases(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/territories/{territory_id}/roadside-cases",
            headers=headers,
            params=params,
        )

    def list_roadside_cases(self, headers, params=None):
        return self._request(
            "GET", "/fleet/roadside-cases", headers=headers, params=params
        )

    def get_roadside_case(self, case_id, headers):
        return self._request(
            "GET", f"/fleet/roadside-cases/{case_id}", headers=headers
        )

    def list_session_roadside_cases(self, session_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleet/assistance-sessions/{session_id}/roadside-cases",
            headers=headers,
            params=params,
        )

    def dispatch_roadside_case(self, case_id, headers):
        return self._request(
            "POST", f"/fleet/roadside-cases/{case_id}/dispatch", {}, headers
        )

    def clear_roadside_case(self, case_id, headers):
        return self._request(
            "POST", f"/fleet/roadside-cases/{case_id}/clear", {}, headers
        )

    def cancel_roadside_case(self, case_id, headers):
        return self._request(
            "POST", f"/fleet/roadside-cases/{case_id}/cancel", {}, headers
        )

    # ─── generic escape hatch for exotic paths ────────────────────────────

    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()