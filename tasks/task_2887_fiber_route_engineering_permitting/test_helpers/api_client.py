"""One method per PRD operation.

Every collection in this system is mounted as a top-level path segment: there are
no nested creation paths, so parentage travels in the request body through
foreign-key fields.  The reverse-navigation listings hang off the parent and are
read-only.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Thin, total surface over the Fiber Route Engineering & Permitting API."""

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def create_route(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post("/routes", json=payload, headers=headers)

    def list_routes(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self.get("/routes", headers=headers, params=params)

    def get_route(self, route_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"/routes/{route_id}", headers=headers)

    def adjust_route_budget(
        self, route_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/routes/{route_id}/budget-adjustments", json=payload, headers=headers)

    def lock_route_scope(
        self, route_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/routes/{route_id}/lock-scope", json=payload or {}, headers=headers)

    def list_route_segments(
        self, route_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/routes/{route_id}/segments", headers=headers, params=params)

    def list_route_design_packages(
        self, route_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/routes/{route_id}/design-packages", headers=headers, params=params)

    def list_route_as_built_records(
        self, route_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/routes/{route_id}/as-built-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Segments
    # ------------------------------------------------------------------

    def create_segment(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post("/segments", json=payload, headers=headers)

    def get_segment(self, segment_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"/segments/{segment_id}", headers=headers)

    def list_downstream_segments(
        self, segment_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(
            f"/segments/{segment_id}/downstream-segments", headers=headers, params=params
        )

    def list_segment_walkouts(
        self, segment_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/segments/{segment_id}/walkouts", headers=headers, params=params)

    def list_segment_pole_attachment_applications(
        self, segment_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(
            f"/segments/{segment_id}/pole-attachment-applications",
            headers=headers,
            params=params,
        )

    def list_segment_permit_applications(
        self, segment_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(
            f"/segments/{segment_id}/permit-applications", headers=headers, params=params
        )

    def list_segment_splice_points(
        self, segment_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/segments/{segment_id}/splice-points", headers=headers, params=params)

    def select_construction_method(
        self, segment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/segments/{segment_id}/construction-method", json=payload, headers=headers
        )

    def request_bid_ready_estimate(
        self, segment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/segments/{segment_id}/bid-ready-estimate", json=payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Field walkouts and pole observations
    # ------------------------------------------------------------------

    def create_walkout(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post("/walkouts", json=payload, headers=headers)

    def get_walkout(self, walkout_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"/walkouts/{walkout_id}", headers=headers)

    def list_pole_observations(
        self, walkout_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/walkouts/{walkout_id}/pole-observations", headers=headers, params=params)

    def create_pole_observation(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post("/pole-observations", json=payload, headers=headers)

    def submit_walkout(
        self, walkout_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/walkouts/{walkout_id}/submit", json=payload or {}, headers=headers)

    def review_walkout(
        self, walkout_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/walkouts/{walkout_id}/review", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Pole attachment applications
    # ------------------------------------------------------------------

    def create_pole_attachment_application(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post("/pole-attachment-applications", json=payload, headers=headers)

    def get_pole_attachment_application(
        self, application_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"/pole-attachment-applications/{application_id}", headers=headers)

    def list_make_ready_items(
        self, application_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(
            f"/pole-attachment-applications/{application_id}/make-ready-items",
            headers=headers,
            params=params,
        )

    def submit_pole_attachment_application(
        self, application_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/pole-attachment-applications/{application_id}/submit",
            json=payload or {},
            headers=headers,
        )

    def respond_as_pole_owner(
        self, application_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/pole-attachment-applications/{application_id}/owner-response",
            json=payload,
            headers=headers,
        )

    def accept_make_ready(
        self, application_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/pole-attachment-applications/{application_id}/accept-make-ready",
            json=payload or {},
            headers=headers,
        )

    def withdraw_pole_attachment_application(
        self, application_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/pole-attachment-applications/{application_id}/withdraw",
            json=payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Permit applications
    # ------------------------------------------------------------------

    def create_permit_application(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post("/permit-applications", json=payload, headers=headers)

    def get_permit_application(
        self, permit_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"/permit-applications/{permit_id}", headers=headers)

    def submit_permit_application(
        self, permit_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/permit-applications/{permit_id}/submit", json=payload or {}, headers=headers
        )

    def review_permit_application(
        self, permit_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/permit-applications/{permit_id}/review", json=payload, headers=headers
        )

    def claim_deemed_decision(
        self, permit_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/permit-applications/{permit_id}/deemed-decision",
            json=payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Moratorium windows
    # ------------------------------------------------------------------

    def create_moratorium_window(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post("/moratorium-windows", json=payload, headers=headers)

    def list_moratorium_windows(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get("/moratorium-windows", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Design packages and splice points
    # ------------------------------------------------------------------

    def create_design_package(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post("/design-packages", json=payload, headers=headers)

    def get_design_package(self, design_id: str, headers: Headers = None) -> requests.Response:
        return self.get(f"/design-packages/{design_id}", headers=headers)

    def list_design_splice_points(
        self, design_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self.get(f"/design-packages/{design_id}/splice-points", headers=headers, params=params)

    def create_splice_point(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post("/splice-points", json=payload, headers=headers)

    def void_splice_point(
        self, splice_point_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/splice-points/{splice_point_id}/void", json=payload or {}, headers=headers)

    def submit_design_for_review(
        self, design_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/design-packages/{design_id}/submit-for-review", json=payload or {}, headers=headers
        )

    def stamp_design_package(
        self, design_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/design-packages/{design_id}/stamp", json=payload or {}, headers=headers)

    def return_design_to_draft(
        self, design_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self.post(
            f"/design-packages/{design_id}/return-to-draft", json=payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # As-built records
    # ------------------------------------------------------------------

    def create_as_built_record(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post("/as-built-records", json=payload, headers=headers)

    def get_as_built_record(
        self, as_built_id: str, headers: Headers = None
    ) -> requests.Response:
        return self.get(f"/as-built-records/{as_built_id}", headers=headers)

    def certify_as_built_record(
        self, as_built_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self.post(f"/as-built-records/{as_built_id}/certify", json=payload, headers=headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self.post("/_clock/set_current_utc", json=payload, headers=headers)


api_client = ApiClient()
