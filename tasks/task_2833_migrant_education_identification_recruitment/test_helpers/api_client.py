"""One method per endpoint of the Migrant Education Identification & Recruitment API.

Every path is mounted under the ``/mep`` prefix. Methods return the raw response so a
test can assert on the status code as well as the body.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import Filters, Headers, JsonObject, ResourceId

BASE = "/mep"


class MepApiClient(GenericApiClient):
    """Typed wrapper over the recruitment service's HTTP surface."""

    # ------------------------------------------------------------------ areas
    def create_area(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/areas", payload, headers)

    def get_area(self, area_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/areas/" + str(area_id), None, headers)

    def patch_area(self, area_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request("PATCH", BASE + "/areas/" + str(area_id), payload, headers)

    # -------------------------------------------------------------- recruiters
    def create_recruiter(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/recruiters", payload, headers)

    def get_recruiter(self, recruiter_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/recruiters/" + str(recruiter_id), None, headers
        )

    def patch_recruiter(
        self, recruiter_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "PATCH", BASE + "/recruiters/" + str(recruiter_id), payload, headers
        )

    # ------------------------------------------------- coverage assignments
    def create_assignment(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/recruiter-assignments", payload, headers)

    def get_assignment(self, assignment_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/recruiter-assignments/" + str(assignment_id), None, headers
        )

    def list_assignments(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/recruiter-assignments", None, headers, params=filters
        )

    def activate_assignment(
        self, assignment_id: ResourceId, headers: Headers, payload: JsonObject = None
    ):
        return self._request(
            "POST",
            BASE + "/recruiter-assignments/" + str(assignment_id) + "/activate",
            payload if payload is not None else {},
            headers,
        )

    def close_assignment(
        self, assignment_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "POST",
            BASE + "/recruiter-assignments/" + str(assignment_id) + "/close",
            payload,
            headers,
        )

    # ---------------------------------------------------------------- students
    def create_student(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/students", payload, headers)

    def get_student(self, student_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/students/" + str(student_id), None, headers)

    def list_students(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/students", None, headers, params=filters)

    def patch_student(
        self, student_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "PATCH", BASE + "/students/" + str(student_id), payload, headers
        )

    def get_pfs_assessment(self, student_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/students/" + str(student_id) + "/pfs-assessment", None, headers
        )

    # --------------------------------------------------------- qualifying moves
    def create_move(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/qualifying-moves", payload, headers)

    def get_move(self, move_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/qualifying-moves/" + str(move_id), None, headers
        )

    def list_moves(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/qualifying-moves", None, headers, params=filters
        )

    def adjudicate_move(
        self, move_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "POST",
            BASE + "/qualifying-moves/" + str(move_id) + "/adjudicate",
            payload,
            headers,
        )

    # ------------------------------------------------------- interview records
    def create_interview(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/interview-records", payload, headers)

    def get_interview(self, interview_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/interview-records/" + str(interview_id), None, headers
        )

    def list_interviews(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/interview-records", None, headers, params=filters
        )

    # -------------------------------------------- certificates of eligibility
    def create_coe(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/coes", payload, headers)

    def get_coe(self, coe_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/coes/" + str(coe_id), None, headers)

    def list_coes(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/coes", None, headers, params=filters)

    def patch_coe(self, coe_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request("PATCH", BASE + "/coes/" + str(coe_id), payload, headers)

    def submit_coe(self, coe_id: ResourceId, headers: Headers, payload: JsonObject = None):
        return self._request(
            "POST",
            BASE + "/coes/" + str(coe_id) + "/submit",
            payload if payload is not None else {},
            headers,
        )

    def approve_coe(
        self, coe_id: ResourceId, headers: Headers, payload: JsonObject = None
    ):
        return self._request(
            "POST",
            BASE + "/coes/" + str(coe_id) + "/approve",
            payload if payload is not None else {},
            headers,
        )

    def invalidate_coe(self, coe_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/coes/" + str(coe_id) + "/invalidate", payload, headers
        )

    # --------------------------------------------------------- quality control
    def run_qc_selection(self, headers: Headers, payload: JsonObject = None):
        return self._request(
            "POST",
            BASE + "/qc-selections",
            payload if payload is not None else {},
            headers,
        )

    def get_qc_review(self, review_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/qc-reviews/" + str(review_id), None, headers
        )

    def list_qc_reviews(self, headers: Headers, filters: Filters = None):
        return self._request("GET", BASE + "/qc-reviews", None, headers, params=filters)

    def decide_qc_review(
        self, review_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "POST",
            BASE + "/qc-reviews/" + str(review_id) + "/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------- eligibility terms
    def get_term(self, term_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/eligibility-terms/" + str(term_id), None, headers
        )

    def list_terms(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/eligibility-terms", None, headers, params=filters
        )

    def sweep_terms(self, headers: Headers, payload: JsonObject = None):
        return self._request(
            "POST",
            BASE + "/eligibility-terms/sweep",
            payload if payload is not None else {},
            headers,
        )

    def reidentify_term(
        self, term_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "POST",
            BASE + "/eligibility-terms/" + str(term_id) + "/reidentify",
            payload,
            headers,
        )

    # ------------------------------------------------------- transfer requests
    def create_transfer_request(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/transfer-requests", payload, headers)

    def get_transfer_request(self, request_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/transfer-requests/" + str(request_id), None, headers
        )

    def list_transfer_requests(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/transfer-requests", None, headers, params=filters
        )

    def match_transfer_request(
        self, request_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "POST",
            BASE + "/transfer-requests/" + str(request_id) + "/match",
            payload if payload is not None else {},
            headers,
        )

    def receive_transfer_request(
        self, request_id: ResourceId, headers: Headers, payload: JsonObject = None
    ):
        return self._request(
            "POST",
            BASE + "/transfer-requests/" + str(request_id) + "/receive",
            payload if payload is not None else {},
            headers,
        )

    def reconcile_transfer_request(
        self, request_id: ResourceId, headers: Headers, payload: JsonObject = None
    ):
        return self._request(
            "POST",
            BASE + "/transfer-requests/" + str(request_id) + "/reconcile",
            payload if payload is not None else {},
            headers,
        )

    def reject_transfer_request(
        self, request_id: ResourceId, payload: JsonObject, headers: Headers
    ):
        return self._request(
            "POST",
            BASE + "/transfer-requests/" + str(request_id) + "/reject",
            payload,
            headers,
        )

    # ----------------------------------------------------------- service plans
    def create_plan(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/service-plans", payload, headers)

    def get_plan(self, plan_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/service-plans/" + str(plan_id), None, headers
        )

    def list_plans(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/service-plans", None, headers, params=filters
        )

    def activate_plan(
        self, plan_id: ResourceId, headers: Headers, payload: JsonObject = None
    ):
        return self._request(
            "POST",
            BASE + "/service-plans/" + str(plan_id) + "/activate",
            payload if payload is not None else {},
            headers,
        )

    def close_plan(self, plan_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST",
            BASE + "/service-plans/" + str(plan_id) + "/close",
            payload,
            headers,
        )

    # ------------------------------------------------------ delivered sessions
    def create_delivery(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/service-deliveries", payload, headers)

    def get_delivery(self, delivery_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/service-deliveries/" + str(delivery_id), None, headers
        )

    def list_deliveries(self, headers: Headers, filters: Filters = None):
        return self._request(
            "GET", BASE + "/service-deliveries", None, headers, params=filters
        )

    def reverse_delivery(
        self, delivery_id: ResourceId, headers: Headers, payload: JsonObject = None
    ):
        return self._request(
            "POST",
            BASE + "/service-deliveries/" + str(delivery_id) + "/reverse",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, to_iso8601: str, headers: Headers):
        return self._request(
            "POST",
            BASE + "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )
