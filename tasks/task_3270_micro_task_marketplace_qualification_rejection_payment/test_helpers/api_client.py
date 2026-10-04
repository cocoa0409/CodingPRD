"""API client: one method per endpoint on the Micro-Task Marketplace surface."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper over the HTTP surface, one method per endpoint."""

    # ─── Requester ───────────────────────────────────────────────────────────
    def create_requester(self, payload, headers):
        return self._request("POST", "/mkt/requesters", payload, headers)

    def get_requester(self, requester_id, headers):
        return self._request("GET", f"/mkt/requesters/{requester_id}", headers=headers)

    def create_deposit(self, requester_id, payload, headers):
        return self._request(
            "POST", f"/mkt/requesters/{requester_id}/deposits", payload, headers
        )

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/mkt/requester-deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/mkt/requester-deposits/{deposit_id}", headers=headers)

    def settle_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/mkt/requester-deposits/{deposit_id}/settle", payload, headers
        )

    def run_abuse_review(self, requester_id, headers):
        return self._request(
            "POST", f"/mkt/requesters/{requester_id}/abuse-review", {}, headers
        )

    def reinstate_requester(self, requester_id, headers):
        return self._request(
            "POST", f"/mkt/requesters/{requester_id}/reinstate", {}, headers
        )

    # ─── Worker ──────────────────────────────────────────────────────────────
    def create_worker(self, payload, headers):
        return self._request("POST", "/mkt/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/mkt/workers/{worker_id}", headers=headers)

    def submit_identity_verification(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/mkt/workers/{worker_id}/identity-verifications", payload, headers
        )

    def list_worker_qualifications(self, headers, params=None):
        return self._request(
            "GET", "/mkt/worker-qualifications", headers=headers, params=params
        )

    def get_worker_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"/mkt/worker-qualifications/{qualification_id}", headers=headers
        )

    def suspend_worker(self, worker_id, headers):
        return self._request("POST", f"/mkt/workers/{worker_id}/suspend", {}, headers)

    def reinstate_worker(self, worker_id, headers):
        return self._request("POST", f"/mkt/workers/{worker_id}/reinstate", {}, headers)

    # ─── QualificationType / Exam / Attempt ──────────────────────────────────
    def create_qualification_type(self, payload, headers):
        return self._request("POST", "/mkt/qualification-types", payload, headers)

    def get_qualification_type(self, qualification_type_id, headers):
        return self._request(
            "GET", f"/mkt/qualification-types/{qualification_type_id}", headers=headers
        )

    def create_exam(self, qualification_type_id, payload, headers):
        return self._request(
            "POST", f"/mkt/qualification-types/{qualification_type_id}/exams", payload, headers
        )

    def list_exams(self, qualification_type_id, headers, params=None):
        return self._request(
            "GET",
            f"/mkt/qualification-types/{qualification_type_id}/exams",
            headers=headers,
            params=params,
        )

    def get_exam(self, exam_id, headers):
        return self._request("GET", f"/mkt/qualification-exams/{exam_id}", headers=headers)

    def submit_exam_attempt(self, exam_id, payload, headers):
        return self._request(
            "POST", f"/mkt/qualification-exams/{exam_id}/attempts", payload, headers
        )

    def list_exam_attempts(self, exam_id, headers, params=None):
        return self._request(
            "GET",
            f"/mkt/qualification-exams/{exam_id}/attempts",
            headers=headers,
            params=params,
        )

    # ─── HIT ─────────────────────────────────────────────────────────────────
    def create_hit(self, payload, headers):
        return self._request("POST", "/mkt/hits", payload, headers)

    def list_hits(self, headers, params=None):
        return self._request("GET", "/mkt/hits", headers=headers, params=params)

    def get_hit(self, hit_id, headers):
        return self._request("GET", f"/mkt/hits/{hit_id}", headers=headers)

    def list_requester_hits(self, requester_id, headers, params=None):
        return self._request(
            "GET", f"/mkt/requesters/{requester_id}/hits", headers=headers, params=params
        )

    def publish_hit(self, hit_id, headers):
        return self._request("POST", f"/mkt/hits/{hit_id}/publish", {}, headers)

    def cancel_hit(self, hit_id, payload, headers):
        return self._request("POST", f"/mkt/hits/{hit_id}/cancel", payload, headers)

    def sweep_expired(self, hit_id, payload, headers):
        return self._request("POST", f"/mkt/hits/{hit_id}/sweep-expired", payload, headers)

    def list_hit_assignments(self, hit_id, headers, params=None):
        return self._request(
            "GET", f"/mkt/hits/{hit_id}/assignments", headers=headers, params=params
        )

    def accept_hit(self, hit_id, payload, headers):
        return self._request("POST", f"/mkt/hits/{hit_id}/assignments", payload, headers)

    # ─── Assignment ──────────────────────────────────────────────────────────
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/mkt/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/mkt/assignments/{assignment_id}", headers=headers)

    def concurrency_check(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/mkt/workers/{worker_id}/assignments/concurrency-check", payload, headers
        )

    def submit_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/mkt/assignments/{assignment_id}/submit", payload, headers
        )

    def return_assignment(self, assignment_id, headers):
        return self._request("POST", f"/mkt/assignments/{assignment_id}/return", {}, headers)

    def approve_assignment(self, assignment_id, headers):
        return self._request("POST", f"/mkt/assignments/{assignment_id}/approve", {}, headers)

    def reject_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/mkt/assignments/{assignment_id}/reject", payload, headers
        )

    def pay_bonus(self, assignment_id, payload, headers):
        return self._request("POST", f"/mkt/assignments/{assignment_id}/bonus", payload, headers)

    def dispute_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/mkt/assignments/{assignment_id}/dispute", payload, headers
        )

    def admin_resolve(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/mkt/assignments/{assignment_id}/admin-resolve", payload, headers
        )

    # ─── Review ──────────────────────────────────────────────────────────────
    def list_requester_reviews(self, requester_id, headers, params=None):
        return self._request(
            "GET", f"/mkt/requesters/{requester_id}/reviews", headers=headers, params=params
        )

    def list_assignment_reviews(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/mkt/assignments/{assignment_id}/reviews", headers=headers, params=params
        )

    # ─── PayoutRequest ───────────────────────────────────────────────────────
    def create_payout(self, worker_id, payload, headers):
        return self._request("POST", f"/mkt/workers/{worker_id}/payouts", payload, headers)

    def list_payouts(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/mkt/workers/{worker_id}/payouts", headers=headers, params=params
        )

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/mkt/payouts/{payout_id}", headers=headers)

    def verify_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/mkt/payouts/{payout_id}/verify", payload, headers)

    def reject_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/mkt/payouts/{payout_id}/reject", payload, headers)

    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/mkt/_clock/set_current_utc", payload, headers)

    def advance_to(self, payload, headers):
        return self._request("POST", "/mkt/_clock/advance_to", payload, headers)


api_client = ApiClient()