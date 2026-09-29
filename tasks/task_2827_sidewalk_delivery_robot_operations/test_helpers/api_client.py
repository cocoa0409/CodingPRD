"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------- service zones
    def create_service_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    def list_service_zones(self, headers, params=None):
        return self._request("GET", "/service-zones", headers=headers, params=params)

    def get_service_zone(self, zone_id, headers):
        return self._request("GET", f"/service-zones/{zone_id}", headers=headers)

    def get_zone_economics(self, zone_id, headers):
        return self._request("GET", f"/service-zones/{zone_id}/economics", headers=headers)

    def zone_permit_transition(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/service-zones/{zone_id}/permit-transitions", payload, headers
        )

    # ------------------------------------------------------ sidewalk segments
    def create_sidewalk_segment(self, payload, headers):
        return self._request("POST", "/sidewalk-segments", payload, headers)

    def list_sidewalk_segments(self, headers, params=None):
        return self._request("GET", "/sidewalk-segments", headers=headers, params=params)

    def get_sidewalk_segment(self, segment_id, headers):
        return self._request("GET", f"/sidewalk-segments/{segment_id}", headers=headers)

    def segment_transition(self, segment_id, payload, headers):
        return self._request(
            "POST", f"/sidewalk-segments/{segment_id}/transitions", payload, headers
        )

    # ------------------------------------------------------- segment closures
    def create_segment_closure(self, payload, headers):
        return self._request("POST", "/segment-closures", payload, headers)

    def list_segment_closures(self, headers, params=None):
        return self._request("GET", "/segment-closures", headers=headers, params=params)

    def get_segment_closure(self, closure_id, headers):
        return self._request("GET", f"/segment-closures/{closure_id}", headers=headers)

    def closure_transition(self, closure_id, payload, headers):
        return self._request(
            "POST", f"/segment-closures/{closure_id}/transitions", payload, headers
        )

    # -------------------------------------------------------------- merchants
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def merchant_integration_transition(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/merchants/{merchant_id}/integration-transitions", payload, headers
        )

    # ----------------------------------------------------------------- robots
    def create_robot(self, payload, headers):
        return self._request("POST", "/robots", payload, headers)

    def list_robots(self, headers, params=None):
        return self._request("GET", "/robots", headers=headers, params=params)

    def get_robot(self, robot_id, headers):
        return self._request("GET", f"/robots/{robot_id}", headers=headers)

    def robot_duty_transition(self, robot_id, payload, headers):
        return self._request("POST", f"/robots/{robot_id}/duty-transitions", payload, headers)

    def robot_health_transition(self, robot_id, payload, headers):
        return self._request("POST", f"/robots/{robot_id}/health-transitions", payload, headers)

    def ingest_telemetry(self, robot_id, payload, headers):
        return self._request("POST", f"/robots/{robot_id}/telemetry", payload, headers)

    # ------------------------------------------------------------- depot bays
    def create_depot_bay(self, payload, headers):
        return self._request("POST", "/depot-bays", payload, headers)

    def list_depot_bays(self, headers, params=None):
        return self._request("GET", "/depot-bays", headers=headers, params=params)

    def get_depot_bay(self, bay_id, headers):
        return self._request("GET", f"/depot-bays/{bay_id}", headers=headers)

    # -------------------------------------------------------- bay reservations
    def create_bay_reservation(self, payload, headers):
        return self._request("POST", "/bay-reservations", payload, headers)

    def list_bay_reservations(self, headers, params=None):
        return self._request("GET", "/bay-reservations", headers=headers, params=params)

    def get_bay_reservation(self, reservation_id, headers):
        return self._request("GET", f"/bay-reservations/{reservation_id}", headers=headers)

    def bay_reservation_transition(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/bay-reservations/{reservation_id}/transitions", payload, headers
        )

    # -------------------------------------------------------- delivery orders
    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def get_delivery_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def cancel_delivery_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-orders/{order_id}/cancel", payload or {}, headers
        )

    def issue_order_remedy(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/remedy", payload, headers)

    # ------------------------------------------------------- delivery missions
    def create_delivery_mission(self, payload, headers):
        return self._request("POST", "/delivery-missions", payload, headers)

    def list_delivery_missions(self, headers, params=None):
        return self._request("GET", "/delivery-missions", headers=headers, params=params)

    def get_delivery_mission(self, mission_id, headers):
        return self._request("GET", f"/delivery-missions/{mission_id}", headers=headers)

    def load_delivery_mission(self, mission_id, payload, headers):
        return self._request("POST", f"/delivery-missions/{mission_id}/load", payload, headers)

    def mission_transition(self, mission_id, payload, headers):
        return self._request(
            "POST", f"/delivery-missions/{mission_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------ route plans
    def create_route_plan(self, payload, headers):
        return self._request("POST", "/route-plans", payload, headers)

    def list_route_plans(self, headers, params=None):
        return self._request("GET", "/route-plans", headers=headers, params=params)

    def get_route_plan(self, plan_id, headers):
        return self._request("GET", f"/route-plans/{plan_id}", headers=headers)

    def route_plan_transition(self, plan_id, payload, headers):
        return self._request("POST", f"/route-plans/{plan_id}/transitions", payload, headers)

    # ----------------------------------------------------- intervention events
    def create_intervention_event(self, payload, headers):
        return self._request("POST", "/intervention-events", payload, headers)

    def list_intervention_events(self, headers, params=None):
        return self._request("GET", "/intervention-events", headers=headers, params=params)

    def get_intervention_event(self, event_id, headers):
        return self._request("GET", f"/intervention-events/{event_id}", headers=headers)

    def intervention_transition(self, event_id, payload, headers):
        return self._request(
            "POST", f"/intervention-events/{event_id}/transitions", payload, headers
        )

    # -------------------------------------------------------- incident reports
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def get_incident_report(self, report_id, headers):
        return self._request("GET", f"/incident-reports/{report_id}", headers=headers)

    def incident_transition(self, report_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{report_id}/transitions", payload, headers
        )


api_client = ApiClient()
