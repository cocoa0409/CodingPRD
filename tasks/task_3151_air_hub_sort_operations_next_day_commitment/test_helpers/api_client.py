"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, current_utc: str, headers: dict):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # ─── Hub ───────────────────────────────────────────────────────────────
    def create_hub(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/hubs", payload, headers)

    def list_hubs(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/hubs", headers=headers, params=params)

    def get_hub(self, hub_id: str, headers: dict):
        return self._request("GET", f"/airhub/hubs/{hub_id}", headers=headers)

    def declare_contingency(self, hub_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/hubs/{hub_id}/declare-contingency",
                             payload or {}, headers)

    def clear_contingency(self, hub_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/hubs/{hub_id}/clear-contingency",
                             payload or {}, headers)

    def ground_stop(self, hub_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/hubs/{hub_id}/ground-stop",
                             payload or {}, headers)

    def run_ops(self, hub_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/hubs/{hub_id}/run-ops", payload, headers)

    def volume_override(self, hub_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/hubs/{hub_id}/volume-override", payload, headers)

    def get_refund_summary(self, hub_id: str, headers: dict):
        return self._request("GET", f"/airhub/hubs/{hub_id}/refund-summary", headers=headers)

    def get_triage(self, hub_id: str, headers: dict):
        return self._request("GET", f"/airhub/hubs/{hub_id}/triage", headers=headers)

    # ─── ArrivalBank ───────────────────────────────────────────────────────
    def create_bank(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/banks", payload, headers)

    def list_banks(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/banks", headers=headers, params=params)

    def get_bank(self, bank_id: str, headers: dict):
        return self._request("GET", f"/airhub/banks/{bank_id}", headers=headers)

    def begin_bank_unload(self, bank_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/banks/{bank_id}/begin-unload",
                             payload or {}, headers)

    def abandon_bank(self, bank_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/banks/{bank_id}/abandon",
                             payload or {}, headers)

    # ─── Aircraft ──────────────────────────────────────────────────────────
    def create_aircraft(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/aircraft", payload, headers)

    def list_aircraft(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id: str, headers: dict):
        return self._request("GET", f"/airhub/aircraft/{aircraft_id}", headers=headers)

    def depart_origin(self, aircraft_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/depart-origin",
                             payload or {}, headers)

    def land_aircraft(self, aircraft_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/land", payload, headers)

    def begin_aircraft_unload(self, aircraft_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/begin-unload",
                             payload or {}, headers)

    def complete_aircraft_unload(self, aircraft_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/complete-unload",
                             payload, headers)

    def cancel_aircraft(self, aircraft_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/cancel", payload, headers)

    def divert_maintenance(self, aircraft_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/divert-maintenance",
                             payload or {}, headers)

    def reinstate_aircraft(self, aircraft_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/aircraft/{aircraft_id}/reinstate",
                             payload or {}, headers)

    # ─── Package ───────────────────────────────────────────────────────────
    def create_package(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/packages", payload, headers)

    def list_packages(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/packages", headers=headers, params=params)

    def get_package(self, package_id: str, headers: dict):
        return self._request("GET", f"/airhub/packages/{package_id}", headers=headers)

    def list_package_failures(self, package_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/airhub/packages/{package_id}/failures",
                             headers=headers, params=params)

    def induct_package(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/induct", payload, headers)

    def reject_induction(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/reject-induction",
                             payload or {}, headers)

    def primary_sort(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/primary-sort",
                             payload, headers)

    def secondary_sort(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/secondary-sort",
                             payload, headers)

    def reclaim_lane(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/reclaim-lane",
                             payload or {}, headers)

    def route_irregular(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/route-irregular",
                             payload, headers)

    def resolve_irregular(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/resolve-irregular",
                             payload or {}, headers)

    def route_hazmat(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/route-hazmat",
                             payload, headers)

    def resolve_hazmat(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/resolve-hazmat",
                             payload or {}, headers)

    def downgrade_commitment(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/downgrade-commitment",
                             payload, headers)

    def ground_downgrade(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/ground-downgrade",
                             payload or {}, headers)

    def diverge_package(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/diverge",
                             payload or {}, headers)

    def upgrade_hold(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/upgrade-hold",
                             payload or {}, headers)

    def clear_reroute(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/clear-reroute",
                             payload or {}, headers)

    def clear_upgrade_hold(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/clear-upgrade-hold",
                             payload or {}, headers)

    def void_package(self, package_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/packages/{package_id}/void",
                             payload or {}, headers)

    def claim_indemnity(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/claim-indemnity",
                             payload, headers)

    def assign_aircraft(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/packages/{package_id}/assign-aircraft",
                             payload, headers)

    # ─── SortLane ──────────────────────────────────────────────────────────
    def create_lane(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/lanes", payload, headers)

    def list_lanes(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/lanes", headers=headers, params=params)

    def get_lane(self, lane_id: str, headers: dict):
        return self._request("GET", f"/airhub/lanes/{lane_id}", headers=headers)

    def get_concourse_width(self, headers: dict, params: dict):
        return self._request("GET", "/airhub/lanes/concourse-width",
                             headers=headers, params=params)

    def close_lane(self, lane_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/lanes/{lane_id}/close", payload or {}, headers)

    def reopen_lane(self, lane_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/lanes/{lane_id}/reopen", payload or {}, headers)

    # ─── LoadMove ──────────────────────────────────────────────────────────
    def create_move(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/moves", payload, headers)

    def list_moves(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/moves", headers=headers, params=params)

    def get_move(self, move_id: str, headers: dict):
        return self._request("GET", f"/airhub/moves/{move_id}", headers=headers)

    def plan_load(self, move_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/moves/{move_id}/plan-load", payload or {}, headers)

    def begin_loading(self, move_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/moves/{move_id}/begin-loading", payload or {}, headers)

    def complete_load(self, move_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/moves/{move_id}/complete-load", payload or {}, headers)

    def replan_move(self, move_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/moves/{move_id}/replan", payload or {}, headers)

    def cancel_move(self, move_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/moves/{move_id}/cancel", payload or {}, headers)

    def load_package(self, move_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/moves/{move_id}/load-package", payload, headers)

    def unload_package(self, move_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/moves/{move_id}/unload-package", payload, headers)

    def assign_buildup(self, move_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/moves/{move_id}/assign-buildup", payload, headers)

    def set_move_tier(self, move_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/moves/{move_id}/set-tier", payload, headers)

    def set_gateway_requirements(self, move_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/moves/{move_id}/gateway-requirements",
                             payload, headers)

    # ─── Buildup ───────────────────────────────────────────────────────────
    def create_buildup(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/buildups", payload, headers)

    def list_buildups(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/buildups", headers=headers, params=params)

    def get_buildup(self, buildup_id: str, headers: dict):
        return self._request("GET", f"/airhub/buildups/{buildup_id}", headers=headers)

    def seal_buildup(self, buildup_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/buildups/{buildup_id}/seal", payload, headers)

    def unseal_buildup(self, buildup_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/buildups/{buildup_id}/unseal",
                             payload or {}, headers)

    def cancel_buildup(self, buildup_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/buildups/{buildup_id}/cancel",
                             payload or {}, headers)

    def set_buildup_tier(self, buildup_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/buildups/{buildup_id}/set-tier", payload, headers)

    # ─── GroundFeeder ──────────────────────────────────────────────────────
    def create_feeder(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/feeders", payload, headers)

    def list_feeders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/feeders", headers=headers, params=params)

    def get_feeder(self, feeder_id: str, headers: dict):
        return self._request("GET", f"/airhub/feeders/{feeder_id}", headers=headers)

    def begin_staging(self, feeder_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/feeders/{feeder_id}/begin-staging",
                             payload or {}, headers)

    def stage_package(self, feeder_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/feeders/{feeder_id}/stage-package",
                             payload, headers)

    def begin_feeder_loading(self, feeder_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/feeders/{feeder_id}/begin-loading",
                             payload or {}, headers)

    def depart_feeder(self, feeder_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/feeders/{feeder_id}/depart",
                             payload or {}, headers)

    def cancel_feeder(self, feeder_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/feeders/{feeder_id}/cancel",
                             payload or {}, headers)

    # ─── LaborShift ────────────────────────────────────────────────────────
    def create_shift(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/shifts", payload, headers)

    def list_shifts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/shifts", headers=headers, params=params)

    def get_shift(self, shift_id: str, headers: dict):
        return self._request("GET", f"/airhub/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/shifts/{shift_id}/cancel",
                             payload or {}, headers)

    def complete_shift(self, shift_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/shifts/{shift_id}/complete",
                             payload or {}, headers)

    def forecast_volume(self, shift_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/shifts/{shift_id}/forecast-volume",
                             payload, headers)

    # ─── OpsRun ────────────────────────────────────────────────────────────
    def list_ops_runs(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/ops-runs", headers=headers, params=params)

    def get_ops_run(self, ops_run_id: str, headers: dict):
        return self._request("GET", f"/airhub/ops-runs/{ops_run_id}", headers=headers)

    def advance_ops_run(self, ops_run_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/ops-runs/{ops_run_id}/advance",
                             payload or {}, headers)

    def release_ops_run(self, ops_run_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/ops-runs/{ops_run_id}/release",
                             payload or {}, headers)

    # ─── ServiceFailure + claims ───────────────────────────────────────────
    def create_failure(self, payload: dict, headers: dict):
        return self._request("POST", "/airhub/failures", payload, headers)

    def list_failures(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/failures", headers=headers, params=params)

    def get_failure(self, failure_id: str, headers: dict):
        return self._request("GET", f"/airhub/failures/{failure_id}", headers=headers)

    def finalize_failure(self, failure_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/failures/{failure_id}/finalize",
                             payload or {}, headers)

    def dispute_failure(self, failure_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/failures/{failure_id}/dispute",
                             payload or {}, headers)

    def reopen_failure(self, failure_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/failures/{failure_id}/reopen",
                             payload or {}, headers)

    def void_failure(self, failure_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/airhub/failures/{failure_id}/void",
                             payload or {}, headers)

    def append_claim(self, failure_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/airhub/failures/{failure_id}/claims", payload, headers)

    def list_failure_claims(self, failure_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/airhub/failures/{failure_id}/claims",
                             headers=headers, params=params)

    def list_claims(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/airhub/service-failure-claims",
                             headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: dict):
        return self._request("GET", f"/airhub/service-failure-claims/{claim_id}", headers=headers)


api_client = ApiClient()


def raw_request(client: ApiClient, method: str, path: str,
                payload: Any = None, headers: Optional[Dict[str, str]] = None,
                params: Optional[dict] = None):
    """Escape hatch for endpoints with no dedicated method (e.g. header-less probes)."""
    return client._request(method, path, payload, headers, params)