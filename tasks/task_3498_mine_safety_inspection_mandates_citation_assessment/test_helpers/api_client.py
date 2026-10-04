"""API client: one method per endpoint defined in PRD §4.

Every business path is under the ``/msha`` prefix EXCEPT the platform-level
test-driving clock endpoint ``POST /_clock/set_current_utc`` (PRD §4: "The
clock endpoint is a platform-level test-driving surface and lives outside the
/msha prefix."). It is therefore called with its exact unprefixed path.

All methods return the raw ``requests.Response``; tests assert status codes
and envelopes via the validators. Creation endpoints answer 201; all other
successes answer 200 (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_ENDPOINT_PATH


class ApiClient(GenericApiClient):
    # ─── Test-driving clock (outside /msha) ───────────────────────────────
    def set_clock(self, current_utc, headers):
        """POST /_clock/set_current_utc — MSHAAdmin only. Sets the logical
        clock; also flips due APPROVED mine plans to REVISION_DUE."""
        return self._request(
            "POST", CLOCK_ENDPOINT_PATH, {"current_utc": current_utc}, headers
        )

    # ─── Operators ────────────────────────────────────────────────────────
    def create_operator(self, payload, headers):
        return self._request("POST", "/msha/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/msha/operators/{operator_id}", headers=headers)

    def list_operator_mines(self, operator_id, headers, params=None):
        return self._request(
            "GET", f"/msha/operators/{operator_id}/mines", headers=headers, params=params
        )

    # ─── Mines ────────────────────────────────────────────────────────────
    def create_mine(self, payload, headers):
        return self._request("POST", "/msha/mines", payload, headers)

    def get_mine(self, mine_id, headers):
        return self._request("GET", f"/msha/mines/{mine_id}", headers=headers)

    def idle_mine(self, mine_id, headers):
        return self._request("POST", f"/msha/mines/{mine_id}/idle", {}, headers)

    def reactivate_mine(self, mine_id, headers):
        return self._request("POST", f"/msha/mines/{mine_id}/reactivate", {}, headers)

    # ─── Inspectors ───────────────────────────────────────────────────────
    def create_inspector(self, payload, headers):
        return self._request("POST", "/msha/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/msha/inspectors/{inspector_id}", headers=headers)

    # ─── Inspection cycles ────────────────────────────────────────────────
    def create_inspection_cycle(self, mine_id, payload, headers):
        return self._request(
            "POST", f"/msha/mines/{mine_id}/inspection-cycles", payload, headers
        )

    def get_inspection_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/msha/inspection-cycles/{cycle_id}", headers=headers
        )

    def list_inspection_cycles(self, mine_id, headers, params=None):
        return self._request(
            "GET", f"/msha/mines/{mine_id}/inspection-cycles", headers=headers, params=params
        )

    def close_inspection_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/msha/inspection-cycles/{cycle_id}/close", {}, headers
        )

    # ─── Inspections ──────────────────────────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/msha/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/msha/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/msha/inspections", headers=headers, params=params)

    def file_review_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/msha/inspections/{inspection_id}/file-review", {}, headers
        )

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/msha/inspections/{inspection_id}/start", {}, headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/msha/inspections/{inspection_id}/complete", {}, headers
        )

    def reassign_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/msha/inspections/{inspection_id}/reassign", payload, headers
        )

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/msha/inspections/{inspection_id}/cancel", {}, headers)

    # ─── Citations ────────────────────────────────────────────────────────
    def create_citation(self, payload, headers):
        return self._request("POST", "/msha/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/msha/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/msha/citations", headers=headers, params=params)

    def abate_citation(self, citation_id, payload, headers):
        return self._request(
            "POST", f"/msha/citations/{citation_id}/abate", payload, headers
        )

    def verify_citation_abatement(self, citation_id, payload, headers):
        return self._request(
            "POST", f"/msha/citations/{citation_id}/verify-abatement", payload, headers
        )

    def extend_citation_abatement(self, citation_id, payload, headers):
        return self._request(
            "POST", f"/msha/citations/{citation_id}/extend-abatement", payload, headers
        )

    # ─── Imminent-danger orders ───────────────────────────────────────────
    def create_imminent_danger_order(self, payload, headers):
        return self._request("POST", "/msha/imminent-danger-orders", payload, headers)

    def get_imminent_danger_order(self, order_id, headers):
        return self._request(
            "GET", f"/msha/imminent-danger-orders/{order_id}", headers=headers
        )

    def list_imminent_danger_orders(self, headers, params=None):
        return self._request("GET", "/msha/imminent-danger-orders", headers=headers, params=params)

    def confirm_ido_withdrawal(self, order_id, payload, headers):
        return self._request(
            "POST", f"/msha/imminent-danger-orders/{order_id}/confirm-withdrawal",
            payload, headers,
        )

    def verify_ido_abatement(self, order_id, payload, headers):
        return self._request(
            "POST", f"/msha/imminent-danger-orders/{order_id}/verify-abatement",
            payload, headers,
        )

    def terminate_ido(self, order_id, headers):
        return self._request(
            "POST", f"/msha/imminent-danger-orders/{order_id}/terminate", {}, headers
        )

    # ─── Penalty assessments ──────────────────────────────────────────────
    def list_citation_penalty_assessments(self, citation_id, headers, params=None):
        return self._request(
            "GET", f"/msha/citations/{citation_id}/penalty-assessments",
            headers=headers, params=params,
        )

    def finalize_penalty_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/msha/penalty-assessments/{assessment_id}/finalize", {}, headers
        )

    # ─── Contests ─────────────────────────────────────────────────────────
    def create_contest(self, payload, headers):
        return self._request("POST", "/msha/contests", payload, headers)

    def get_contest(self, contest_id, headers):
        return self._request("GET", f"/msha/contests/{contest_id}", headers=headers)

    def list_contests(self, headers, params=None):
        return self._request("GET", "/msha/contests", headers=headers, params=params)

    def docket_contest(self, contest_id, headers):
        return self._request("POST", f"/msha/contests/{contest_id}/docket", {}, headers)

    def decide_contest(self, contest_id, payload, headers):
        return self._request("POST", f"/msha/contests/{contest_id}/decide", payload, headers)

    def withdraw_contest(self, contest_id, headers):
        return self._request("POST", f"/msha/contests/{contest_id}/withdraw", {}, headers)

    # ─── Mine plans ───────────────────────────────────────────────────────
    def submit_mine_plan(self, mine_id, payload, headers):
        return self._request("POST", f"/msha/mines/{mine_id}/mine-plans", payload, headers)

    def get_mine_plan(self, plan_id, headers):
        return self._request("GET", f"/msha/mine-plans/{plan_id}", headers=headers)

    def list_mine_plans(self, headers, params=None):
        return self._request("GET", "/msha/mine-plans", headers=headers, params=params)

    def approve_mine_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/msha/mine-plans/{plan_id}/approve", payload, headers)

    def reject_mine_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/msha/mine-plans/{plan_id}/reject", payload, headers)

    # ─── Accidents ────────────────────────────────────────────────────────
    def report_accident(self, payload, headers):
        return self._request("POST", "/msha/accidents", payload, headers)

    def get_accident(self, accident_id, headers):
        return self._request("GET", f"/msha/accidents/{accident_id}", headers=headers)

    def list_accidents(self, headers, params=None):
        return self._request("GET", "/msha/accidents", headers=headers, params=params)

    def publish_accident_report(self, accident_id, payload, headers):
        return self._request(
            "POST", f"/msha/accidents/{accident_id}/publish-report", payload, headers
        )

    def get_public_accident_report(self, accident_id, headers):
        return self._request(
            "GET", f"/msha/accidents/{accident_id}/public-report", headers=headers
        )

    # ─── Pattern of violations ────────────────────────────────────────────
    def run_pov_screening(self, mine_id, headers):
        return self._request("POST", f"/msha/mines/{mine_id}/pov-screenings", {}, headers)

    def list_pov_screenings(self, mine_id, headers, params=None):
        return self._request(
            "GET", f"/msha/mines/{mine_id}/pov-screenings", headers=headers, params=params
        )

    def issue_pov_notice(self, mine_id, headers):
        return self._request("POST", f"/msha/mines/{mine_id}/pov-notices", {}, headers)


api_client = ApiClient()
