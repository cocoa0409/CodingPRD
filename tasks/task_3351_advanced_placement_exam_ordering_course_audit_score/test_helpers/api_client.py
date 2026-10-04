"""API client: one method per endpoint the PRD publishes under /ap-program."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ap-program"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- schools ----------------
    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    def transition_school(self, school_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/schools/{school_id}/status-transitions", payload or {}, headers
        )

    def list_school_course_audits(self, school_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/schools/{school_id}/course-audits", headers=headers, params=params
        )

    def list_school_irregularity_cases(self, school_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/schools/{school_id}/irregularity-cases",
            headers=headers,
            params=params,
        )

    # ---------------- course audits ----------------
    def create_course_audit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/course-audits", payload, headers)

    def list_course_audits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/course-audits", headers=headers, params=params)

    def transition_course_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/course-audits/{audit_id}/status-transitions", payload or {}, headers
        )

    # ---------------- students ----------------
    def create_student(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    def transition_student(self, student_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/students/{student_id}/status-transitions", payload or {}, headers
        )

    def list_student_registrations(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/students/{student_id}/registrations", headers=headers, params=params
        )

    def list_student_accommodation_requests(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/students/{student_id}/accommodation-requests",
            headers=headers,
            params=params,
        )

    # ---------------- exam orders ----------------
    def create_exam_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exam-orders", payload, headers)

    def list_exam_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exam-orders", headers=headers, params=params)

    def get_exam_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/exam-orders/{order_id}", headers=headers)

    def transition_exam_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exam-orders/{order_id}/status-transitions", payload or {}, headers
        )

    def list_order_registrations(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/exam-orders/{order_id}/registrations", headers=headers, params=params
        )

    def list_order_material_shipments(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/exam-orders/{order_id}/material-shipments",
            headers=headers,
            params=params,
        )

    # ---------------- exam registrations ----------------
    def create_exam_registration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exam-registrations", payload, headers)

    def get_exam_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/exam-registrations/{registration_id}", headers=headers
        )

    def transition_exam_registration(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/exam-registrations/{registration_id}/status-transitions",
            payload or {},
            headers,
        )

    def settle_registration_fees(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exam-registrations/{registration_id}/fees", payload or {}, headers
        )

    def list_registration_alternate_requests(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/exam-registrations/{registration_id}/alternate-exam-requests",
            headers=headers,
            params=params,
        )

    def list_registration_exam_scores(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/exam-registrations/{registration_id}/exam-scores",
            headers=headers,
            params=params,
        )

    def list_registration_irregularity_cases(self, registration_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/exam-registrations/{registration_id}/irregularity-cases",
            headers=headers,
            params=params,
        )

    # ---------------- accommodation requests ----------------
    def create_accommodation_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accommodation-requests", payload, headers)

    def get_accommodation_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/accommodation-requests/{request_id}", headers=headers
        )

    def transition_accommodation_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/accommodation-requests/{request_id}/status-transitions",
            payload or {},
            headers,
        )

    # ---------------- alternate exam requests ----------------
    def create_alternate_exam_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/alternate-exam-requests", payload, headers)

    def transition_alternate_exam_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/alternate-exam-requests/{request_id}/status-transitions",
            payload or {},
            headers,
        )

    # ---------------- material shipments ----------------
    def create_material_shipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/material-shipments", payload, headers)

    def get_material_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/material-shipments/{shipment_id}", headers=headers)

    def transition_material_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/material-shipments/{shipment_id}/status-transitions",
            payload or {},
            headers,
        )

    def append_custody_event(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/material-shipments/{shipment_id}/custody-events", payload, headers
        )

    # ---------------- readers ----------------
    def create_reader(self, payload, headers):
        return self._request("POST", f"{PREFIX}/readers", payload, headers)

    def get_reader(self, reader_id, headers):
        return self._request("GET", f"{PREFIX}/readers/{reader_id}", headers=headers)

    def get_reader_calibration_summary(self, reader_id, headers):
        return self._request(
            "GET", f"{PREFIX}/readers/{reader_id}/calibration-summary", headers=headers
        )

    def list_reader_exam_scores(self, reader_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/readers/{reader_id}/exam-scores", headers=headers, params=params
        )

    def transition_reader(self, reader_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/readers/{reader_id}/status-transitions", payload or {}, headers
        )

    # ---------------- exam scores ----------------
    def create_exam_score(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exam-scores", payload, headers)

    def get_exam_score(self, score_id, headers):
        return self._request("GET", f"{PREFIX}/exam-scores/{score_id}", headers=headers)

    def transition_exam_score(self, score_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exam-scores/{score_id}/status-transitions", payload or {}, headers
        )

    # ---------------- score sends ----------------
    def create_score_send(self, payload, headers):
        return self._request("POST", f"{PREFIX}/score-sends", payload, headers)

    def list_score_sends(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/score-sends", headers=headers, params=params)

    def get_score_send(self, send_id, headers):
        return self._request("GET", f"{PREFIX}/score-sends/{send_id}", headers=headers)

    def transition_score_send(self, send_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/score-sends/{send_id}/status-transitions", payload or {}, headers
        )

    # ---------------- irregularity cases ----------------
    def create_irregularity_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/irregularity-cases", payload, headers)

    def list_irregularity_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/irregularity-cases", headers=headers, params=params)

    def transition_irregularity_case(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/irregularity-cases/{case_id}/status-transitions",
            payload or {},
            headers,
        )


api_client = ApiClient()
