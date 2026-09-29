"""Typed HTTP client exposing one method per declared wind-ops endpoint.

Every method returns the raw ``requests.Response`` so that tests may assert on
status codes and on the response envelope.  Listing methods pass their filters
and pagination controls as query parameters.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

Headers = Dict[str, str]
Payload = Dict[str, Any]


def _params(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset filters so that omitted controls fall back to their defaults."""
    return {k: v for k, v in kwargs.items() if v is not None}


class WindOpsApiClient(GenericApiClient):
    """Thin wrapper over the wind-ops HTTP surface."""

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/_clock/set_current_utc",
            json={"current_utc": current_utc},
            headers=headers,
        )

    def patch(
        self,
        path: str,
        json: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request("PATCH", path, payload=json, headers=headers)

    # ------------------------------------------------------------------
    # Wind farms
    # ------------------------------------------------------------------
    def create_farm(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/farms", json=payload, headers=headers)

    def get_farm(self, farm_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/farms/{farm_id}", headers=headers)

    def list_farms(
        self,
        headers: Headers,
        region_code: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/farms",
            headers=headers,
            params=_params(region_code=region_code, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Turbine models
    # ------------------------------------------------------------------
    def create_turbine_model(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/turbine-models", json=payload, headers=headers)

    def get_turbine_model(self, model_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/turbine-models/{model_id}", headers=headers)

    def list_turbine_models(
        self,
        headers: Headers,
        model_code: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/turbine-models",
            headers=headers,
            params=_params(model_code=model_code, limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Turbines
    # ------------------------------------------------------------------
    def create_turbine(
        self, farm_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/farms/{farm_id}/turbines", json=payload, headers=headers
        )

    def get_turbine(self, turbine_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/turbines/{turbine_id}", headers=headers)

    def list_turbines(
        self,
        headers: Headers,
        wind_farm_id: Optional[str] = None,
        turbine_model_id: Optional[str] = None,
        availability_state: Optional[str] = None,
        curtailment_state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/turbines",
            headers=headers,
            params=_params(
                wind_farm_id=wind_farm_id,
                turbine_model_id=turbine_model_id,
                availability_state=availability_state,
                curtailment_state=curtailment_state,
                limit=limit,
                offset=offset,
            ),
        )

    def scada_sync(
        self, turbine_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/turbines/{turbine_id}/scada-sync", json=payload, headers=headers
        )

    def decommission_turbine(
        self, turbine_id: str, decommission_reason: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/turbines/{turbine_id}/decommission",
            json={"decommission_reason": decommission_reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Fault code rules
    # ------------------------------------------------------------------
    def create_fault_code_rule(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/fault-code-rules", json=payload, headers=headers)

    def get_fault_code_rule(self, rule_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/fault-code-rules/{rule_id}", headers=headers)

    def list_fault_code_rules(
        self,
        headers: Headers,
        severity_class: Optional[str] = None,
        fault_code: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/fault-code-rules",
            headers=headers,
            params=_params(
                severity_class=severity_class,
                fault_code=fault_code,
                limit=limit,
                offset=offset,
            ),
        )

    def patch_fault_code_rule(
        self, rule_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.patch(
            f"{API_PREFIX}/fault-code-rules/{rule_id}", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Fault events
    # ------------------------------------------------------------------
    def raise_fault_event(
        self, turbine_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/turbines/{turbine_id}/fault-events", json=payload, headers=headers
        )

    def get_fault_event(self, event_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/fault-events/{event_id}", headers=headers)

    def list_fault_events(
        self,
        headers: Headers,
        turbine_id: Optional[str] = None,
        fault_code_rule_id: Optional[str] = None,
        triage_state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/fault-events",
            headers=headers,
            params=_params(
                turbine_id=turbine_id,
                fault_code_rule_id=fault_code_rule_id,
                triage_state=triage_state,
                limit=limit,
                offset=offset,
            ),
        )

    def triage_fault_event(
        self, event_id: str, disposition: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/fault-events/{event_id}/triage",
            json={"disposition": disposition},
            headers=headers,
        )

    def remote_reset(
        self, event_id: str, reset_outcome: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/fault-events/{event_id}/remote-reset",
            json={"reset_outcome": reset_outcome},
            headers=headers,
        )

    def close_fault_event(self, event_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/fault-events/{event_id}/close", json={}, headers=headers
        )

    # ------------------------------------------------------------------
    # Crews
    # ------------------------------------------------------------------
    def create_crew(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/crews", json=payload, headers=headers)

    def get_crew(self, crew_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/crews/{crew_id}", headers=headers)

    def list_crews(
        self,
        headers: Headers,
        wind_farm_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/crews",
            headers=headers,
            params=_params(
                wind_farm_id=wind_farm_id, status=status, limit=limit, offset=offset
            ),
        )

    # ------------------------------------------------------------------
    # Weather windows
    # ------------------------------------------------------------------
    def create_weather_window(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/weather-windows", json=payload, headers=headers)

    def get_weather_window(self, window_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/weather-windows/{window_id}", headers=headers)

    def list_weather_windows(
        self,
        headers: Headers,
        wind_farm_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/weather-windows",
            headers=headers,
            params=_params(
                wind_farm_id=wind_farm_id, state=state, limit=limit, offset=offset
            ),
        )

    def confirm_weather_window(self, window_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/weather-windows/{window_id}/confirm", json={}, headers=headers
        )

    # ------------------------------------------------------------------
    # Work orders
    # ------------------------------------------------------------------
    def create_work_order(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/work-orders", json=payload, headers=headers)

    def get_work_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/work-orders/{order_id}", headers=headers)

    def list_work_orders(
        self,
        headers: Headers,
        turbine_id: Optional[str] = None,
        fault_event_id: Optional[str] = None,
        blade_damage_id: Optional[str] = None,
        parent_work_order_id: Optional[str] = None,
        crew_id: Optional[str] = None,
        weather_window_id: Optional[str] = None,
        state: Optional[str] = None,
        work_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/work-orders",
            headers=headers,
            params=_params(
                turbine_id=turbine_id,
                fault_event_id=fault_event_id,
                blade_damage_id=blade_damage_id,
                parent_work_order_id=parent_work_order_id,
                crew_id=crew_id,
                weather_window_id=weather_window_id,
                state=state,
                work_type=work_type,
                limit=limit,
                offset=offset,
            ),
        )

    def submit_work_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/work-orders/{order_id}/submit", json={}, headers=headers
        )

    def request_revision(
        self, order_id: str, revision_note: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/work-orders/{order_id}/request-revision",
            json={"revision_note": revision_note},
            headers=headers,
        )

    def schedule_work_order(
        self, order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/work-orders/{order_id}/schedule", json=payload, headers=headers
        )

    def start_work_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/work-orders/{order_id}/start", json={}, headers=headers
        )

    def complete_work_order(
        self, order_id: str, actual_hours: float, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/work-orders/{order_id}/complete",
            json={"actual_hours": actual_hours},
            headers=headers,
        )

    def cancel_work_order(
        self, order_id: str, cancellation_reason: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/work-orders/{order_id}/cancel",
            json={"cancellation_reason": cancellation_reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Crane mobilizations
    # ------------------------------------------------------------------
    def create_crane_mobilization(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/crane-mobilizations", json=payload, headers=headers)

    def get_crane_mobilization(self, crane_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/crane-mobilizations/{crane_id}", headers=headers)

    def list_crane_mobilizations(
        self,
        headers: Headers,
        wind_farm_id: Optional[str] = None,
        state: Optional[str] = None,
        crane_class: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/crane-mobilizations",
            headers=headers,
            params=_params(
                wind_farm_id=wind_farm_id,
                state=state,
                crane_class=crane_class,
                limit=limit,
                offset=offset,
            ),
        )

    def demobilize_crane(self, crane_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/crane-mobilizations/{crane_id}/demobilize", json={}, headers=headers
        )

    # ------------------------------------------------------------------
    # Spare parts
    # ------------------------------------------------------------------
    def create_spare_part(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/spare-parts", json=payload, headers=headers)

    def get_spare_part(self, part_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/spare-parts/{part_id}", headers=headers)

    def list_spare_parts(
        self,
        headers: Headers,
        component_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/spare-parts",
            headers=headers,
            params=_params(
                component_type=component_type, status=status, limit=limit, offset=offset
            ),
        )

    def receive_spare_part(
        self, part_id: str, quantity_received: int, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/spare-parts/{part_id}/receipts",
            json={"quantity_received": quantity_received},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Component replacements
    # ------------------------------------------------------------------
    def create_component_replacement(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/component-replacements", json=payload, headers=headers
        )

    def get_component_replacement(
        self, replacement_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/component-replacements/{replacement_id}", headers=headers
        )

    def list_component_replacements(
        self,
        headers: Headers,
        work_order_id: Optional[str] = None,
        spare_part_id: Optional[str] = None,
        crane_mobilization_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/component-replacements",
            headers=headers,
            params=_params(
                work_order_id=work_order_id,
                spare_part_id=spare_part_id,
                crane_mobilization_id=crane_mobilization_id,
                state=state,
                limit=limit,
                offset=offset,
            ),
        )

    def reserve_crane(
        self, replacement_id: str, crane_mobilization_id: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/component-replacements/{replacement_id}/reserve-crane",
            json={"crane_mobilization_id": crane_mobilization_id},
            headers=headers,
        )

    def plan_uptower(self, replacement_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/component-replacements/{replacement_id}/plan-uptower",
            json={},
            headers=headers,
        )

    def execute_replacement(self, replacement_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/component-replacements/{replacement_id}/execute",
            json={},
            headers=headers,
        )

    def cancel_replacement(
        self, replacement_id: str, cancellation_reason: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/component-replacements/{replacement_id}/cancel",
            json={"cancellation_reason": cancellation_reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Blade damages
    # ------------------------------------------------------------------
    def record_blade_damage(
        self, turbine_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/turbines/{turbine_id}/blade-damages", json=payload, headers=headers
        )

    def get_blade_damage(self, damage_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/blade-damages/{damage_id}", headers=headers)

    def list_blade_damages(
        self,
        headers: Headers,
        turbine_id: Optional[str] = None,
        repair_priority_band: Optional[str] = None,
        state: Optional[str] = None,
        inspection_method: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/blade-damages",
            headers=headers,
            params=_params(
                turbine_id=turbine_id,
                repair_priority_band=repair_priority_band,
                state=state,
                inspection_method=inspection_method,
                limit=limit,
                offset=offset,
            ),
        )

    def prioritize_blade_damage(self, damage_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/blade-damages/{damage_id}/prioritize", json={}, headers=headers
        )

    def waive_blade_damage(
        self, damage_id: str, waiver_rationale: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/blade-damages/{damage_id}/waive",
            json={"waiver_rationale": waiver_rationale},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Service agreements
    # ------------------------------------------------------------------
    def create_service_agreement(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post(f"{API_PREFIX}/service-agreements", json=payload, headers=headers)

    def get_service_agreement(self, agreement_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/service-agreements/{agreement_id}", headers=headers)

    def list_service_agreements(
        self,
        headers: Headers,
        wind_farm_id: Optional[str] = None,
        state: Optional[str] = None,
        availability_basis: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/service-agreements",
            headers=headers,
            params=_params(
                wind_farm_id=wind_farm_id,
                state=state,
                availability_basis=availability_basis,
                limit=limit,
                offset=offset,
            ),
        )

    def settle_agreement(self, agreement_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/service-agreements/{agreement_id}/settle", json={}, headers=headers
        )

    def finalize_agreement(self, agreement_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/service-agreements/{agreement_id}/finalize", json={}, headers=headers
        )

    # ------------------------------------------------------------------
    # Curtailment orders
    # ------------------------------------------------------------------
    def create_curtailment_order(
        self, turbine_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/turbines/{turbine_id}/curtailment-orders",
            json=payload,
            headers=headers,
        )

    def get_curtailment_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self.get(f"{API_PREFIX}/curtailment-orders/{order_id}", headers=headers)

    def list_curtailment_orders(
        self,
        headers: Headers,
        turbine_id: Optional[str] = None,
        reason: Optional[str] = None,
        state: Optional[str] = None,
        compensable: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/curtailment-orders",
            headers=headers,
            params=_params(
                turbine_id=turbine_id,
                reason=reason,
                state=state,
                compensable=compensable,
                limit=limit,
                offset=offset,
            ),
        )

    def activate_curtailment_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/curtailment-orders/{order_id}/activate", json={}, headers=headers
        )

    def release_curtailment_order(
        self, order_id: str, released_at: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/curtailment-orders/{order_id}/release",
            json={"released_at": released_at},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Landowner settlements
    # ------------------------------------------------------------------
    def create_landowner_settlement(
        self, farm_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/farms/{farm_id}/landowner-settlements",
            json=payload,
            headers=headers,
        )

    def get_landowner_settlement(
        self, settlement_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/landowner-settlements/{settlement_id}", headers=headers
        )

    def list_landowner_settlements(
        self,
        headers: Headers,
        wind_farm_id: Optional[str] = None,
        parcel_code: Optional[str] = None,
        state: Optional[str] = None,
        royalty_basis: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> requests.Response:
        return self.get(
            f"{API_PREFIX}/landowner-settlements",
            headers=headers,
            params=_params(
                wind_farm_id=wind_farm_id,
                parcel_code=parcel_code,
                state=state,
                royalty_basis=royalty_basis,
                limit=limit,
                offset=offset,
            ),
        )

    def approve_landowner_settlement(
        self, settlement_id: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/landowner-settlements/{settlement_id}/approve",
            json={},
            headers=headers,
        )

    def void_landowner_settlement(
        self, settlement_id: str, void_reason: str, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"{API_PREFIX}/landowner-settlements/{settlement_id}/void",
            json={"void_reason": void_reason},
            headers=headers,
        )
