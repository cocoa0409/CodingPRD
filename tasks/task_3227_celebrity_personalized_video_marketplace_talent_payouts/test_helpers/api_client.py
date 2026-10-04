"""API client: one transport method per endpoint in PRD section 4.

Every method returns the raw ``requests.Response`` so a test can assert on
the status code and the envelope directly.  The ``/marketplace`` prefix and
the shape of each path live here and nowhere else.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client.

    The base class picks the target up from ``API_BASE_URL`` which the test
    runner injects; nothing here needs to override it.
    """

    # ─── Logical clock (test-driving endpoint) ────────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", API_PREFIX + CLOCK_PATH, {"to_iso8601": to_iso8601}, headers
        )

    # ─── Talents ──────────────────────────────────────────────────────────

    def create_talent(self, payload, headers=None):
        return self._request("POST", API_PREFIX + "/talents", payload, headers)

    def get_talent(self, talent_id, headers=None):
        return self._request(
            "GET", API_PREFIX + "/talents/{0}".format(talent_id), headers=headers
        )

    def list_talents(self, headers=None, params=None):
        return self._request(
            "GET", API_PREFIX + "/talents", headers=headers, params=params
        )

    def submit_identity(self, talent_id, identity_document_ref, headers=None):
        payload = {"identity_document_ref": identity_document_ref}
        return self._request(
            "POST",
            API_PREFIX + "/talents/{0}/identity/submit".format(talent_id),
            payload,
            headers,
        )

    def set_rates(self, talent_id, payload, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/talents/{0}/rates".format(talent_id),
            payload,
            headers,
        )

    def pause_talent(self, talent_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/talents/{0}/pause".format(talent_id),
            headers=headers,
        )

    def resume_talent(self, talent_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/talents/{0}/resume".format(talent_id),
            headers=headers,
        )

    def get_pricing_suggestion(self, talent_id, headers=None):
        return self._request(
            "GET",
            API_PREFIX + "/talents/{0}/pricing-suggestion".format(talent_id),
            headers=headers,
        )

    def force_pricing_suggestion(self, talent_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/talents/{0}/pricing-suggestion".format(talent_id),
            headers=headers,
        )

    # ─── Tax documents ────────────────────────────────────────────────────

    def submit_tax_document(self, talent_id, payload, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/talents/{0}/tax-documents".format(talent_id),
            payload,
            headers,
        )

    def list_tax_documents(self, talent_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/talents/{0}/tax-documents".format(talent_id),
            headers=headers,
            params=params,
        )

    def review_tax_document(self, tax_document_id, decision, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/tax-documents/{0}/review".format(tax_document_id),
            {"decision": decision},
            headers,
        )

    # ─── Admin talent lifecycle ───────────────────────────────────────────

    def activate_talent(self, talent_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/talents/{0}/activate".format(talent_id),
            headers=headers,
        )

    def reject_identity(self, talent_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/talents/{0}/reject-identity".format(talent_id),
            headers=headers,
        )

    def suspend_talent(self, talent_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/talents/{0}/suspend".format(talent_id),
            headers=headers,
        )

    # ─── Buyers ───────────────────────────────────────────────────────────

    def create_buyer(self, payload, headers=None):
        return self._request("POST", API_PREFIX + "/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers=None):
        return self._request(
            "GET", API_PREFIX + "/buyers/{0}".format(buyer_id), headers=headers
        )

    def list_buyers(self, headers=None, params=None):
        return self._request(
            "GET", API_PREFIX + "/buyers", headers=headers, params=params
        )

    # ─── Orders ───────────────────────────────────────────────────────────

    def create_order(self, payload, headers=None):
        return self._request("POST", API_PREFIX + "/orders", payload, headers)

    def get_order(self, order_id, headers=None):
        return self._request(
            "GET", API_PREFIX + "/orders/{0}".format(order_id), headers=headers
        )

    def list_orders(self, headers=None, params=None):
        return self._request(
            "GET", API_PREFIX + "/orders", headers=headers, params=params
        )

    def screening_attest(self, order_id, screening_token, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/screening-attest".format(order_id),
            {"screening_token": screening_token},
            headers,
        )

    def screening_decline(self, order_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/screening-decline".format(order_id),
            headers=headers,
        )

    def accept_order(self, order_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/accept".format(order_id),
            headers=headers,
        )

    def decline_order(self, order_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/decline".format(order_id),
            headers=headers,
        )

    def confirm_order(self, order_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/confirm".format(order_id),
            headers=headers,
        )

    # ─── Videos ───────────────────────────────────────────────────────────

    def upload_video(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/videos".format(order_id),
            payload,
            headers,
        )

    def list_videos(self, order_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/orders/{0}/videos".format(order_id),
            headers=headers,
            params=params,
        )

    def moderate_video(self, video_id, decision, flagged_reason=None, headers=None):
        payload = {"decision": decision}
        if flagged_reason is not None:
            payload["flagged_reason"] = flagged_reason
        return self._request(
            "POST",
            API_PREFIX + "/admin/videos/{0}/moderate".format(video_id),
            payload,
            headers,
        )

    # ─── Re-record requests ───────────────────────────────────────────────

    def request_rerecord(self, order_id, notes, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/re-record-requests".format(order_id),
            {"notes": notes},
            headers,
        )

    def list_rerecord_requests(self, order_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/orders/{0}/re-record-requests".format(order_id),
            headers=headers,
            params=params,
        )

    # ─── Disputes ─────────────────────────────────────────────────────────

    def open_dispute(self, order_id, reason, expected_order_version, headers=None):
        payload = {
            "reason": reason,
            "expected_order_version": expected_order_version,
        }
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/disputes".format(order_id),
            payload,
            headers,
        )

    def list_disputes(self, order_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/orders/{0}/disputes".format(order_id),
            headers=headers,
            params=params,
        )

    def resolve_dispute(self, dispute_id, outcome, resolution_notes=None, headers=None):
        payload = {"outcome": outcome}
        if resolution_notes is not None:
            payload["resolution_notes"] = resolution_notes
        return self._request(
            "POST",
            API_PREFIX + "/admin/disputes/{0}/resolve".format(dispute_id),
            payload,
            headers,
        )

    # ─── License grants ───────────────────────────────────────────────────

    def create_license_grant(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/orders/{0}/license-grants".format(order_id),
            payload,
            headers,
        )

    def list_license_grants(self, order_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/orders/{0}/license-grants".format(order_id),
            headers=headers,
            params=params,
        )

    # ─── Payouts and payout lines ─────────────────────────────────────────

    def get_payout(self, payout_id, headers=None):
        return self._request(
            "GET", API_PREFIX + "/payouts/{0}".format(payout_id), headers=headers
        )

    def list_payout_lines_of_payout(self, payout_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/payouts/{0}/payout-lines".format(payout_id),
            headers=headers,
            params=params,
        )

    def get_payout_line(self, payout_line_id, headers=None):
        return self._request(
            "GET",
            API_PREFIX + "/payout-lines/{0}".format(payout_line_id),
            headers=headers,
        )

    def list_payout_lines(self, headers=None, params=None):
        return self._request(
            "GET", API_PREFIX + "/payout-lines", headers=headers, params=params
        )

    def list_talent_payouts(self, talent_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/talents/{0}/payouts".format(talent_id),
            headers=headers,
            params=params,
        )

    def list_talent_payout_lines(self, talent_id, headers=None, params=None):
        return self._request(
            "GET",
            API_PREFIX + "/talents/{0}/payout-lines".format(talent_id),
            headers=headers,
            params=params,
        )

    # ─── Admin sweeps and payout lifecycle ────────────────────────────────

    def deadline_sweep(self, to_iso8601, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/deadline-sweep",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def verification_sweep(self, to_iso8601, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/verification-sweep",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def payout_sweep(self, period_start, period_end, headers=None, params=None):
        payload = {"period_start": period_start, "period_end": period_end}
        return self._request(
            "POST",
            API_PREFIX + "/admin/payout-sweep",
            payload,
            headers,
            params=params,
        )

    def initiate_payout(self, payout_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/payouts/{0}/initiate".format(payout_id),
            headers=headers,
        )

    def complete_payout(self, payout_id, headers=None):
        return self._request(
            "POST",
            API_PREFIX + "/admin/payouts/{0}/complete".format(payout_id),
            headers=headers,
        )


api_client = ApiClient()
