"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so a test can assert on the
status code and on the envelope, rather than on a pre-digested value.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def _accounts():
    return API_PREFIX + "/accounts"


def _nested(account_id, segment, resource_id=None):
    base = "{0}/{1}/{2}".format(_accounts(), account_id, segment)
    if resource_id is None:
        return base
    return "{0}/{1}".format(base, resource_id)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client.

    PRD section 1 requires X-User-ID / X-User-Role on every request, reads
    included. Tests that exercise a mutation assert role-specific behavior
    and pass headers explicitly; bare reads only observe state, so a bare
    ``get`` defaults to PlatformAdmin headers — PRD section 2.1 grants
    PlatformAdmin read access to every resource.
    """

    def get(self, path, headers=None, params=None, **kwargs):
        if headers is None:
            from .test_users import ADMIN

            headers = ADMIN
        return super().get(path, headers=headers, params=params, **kwargs)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Accounts ─────────────────────────────────────────────────────────

    def create_account(self, payload, headers=None):
        return self.post(_accounts(), json=payload, headers=headers)

    def get_account(self, account_id, headers=None):
        return self.get(
            "{0}/{1}".format(_accounts(), account_id), headers=headers
        )

    def list_accounts(self, headers=None, params=None):
        return self.get(_accounts(), headers=headers, params=params)

    def suspend_account(self, account_id, payload, headers=None):
        return self.post(
            "{0}/{1}/suspend".format(_accounts(), account_id),
            json=payload,
            headers=headers,
        )

    def reinstate_account(self, account_id, headers=None):
        return self.post(
            "{0}/{1}/reinstate".format(_accounts(), account_id),
            json={},
            headers=headers,
        )

    def close_account(self, account_id, headers=None):
        return self.post(
            "{0}/{1}/close".format(_accounts(), account_id),
            json={},
            headers=headers,
        )

    def run_ops(self, account_id, headers=None):
        return self.post(
            "{0}/{1}/run_ops".format(_accounts(), account_id),
            json={},
            headers=headers,
        )

    def list_ops_runs(self, account_id, headers=None, params=None):
        return self.get(
            "{0}/{1}/ops_runs".format(_accounts(), account_id),
            headers=headers,
            params=params,
        )

    def get_ops_run(self, ops_run_id, headers=None):
        return self.get(
            "{0}/ops_runs/{1}".format(API_PREFIX, ops_run_id), headers=headers
        )

    # ─── Brands ───────────────────────────────────────────────────────────

    def create_brand(self, account_id, payload, headers=None):
        return self.post(
            _nested(account_id, "brands"), json=payload, headers=headers
        )

    def get_brand(self, account_id, brand_id, headers=None):
        return self.get(_nested(account_id, "brands", brand_id), headers=headers)

    def get_brand_by_id(self, brand_id, headers=None):
        return self.get(
            "{0}/brands/{1}".format(API_PREFIX, brand_id), headers=headers
        )

    def list_brands(self, account_id, headers=None, params=None):
        return self.get(_nested(account_id, "brands"), headers=headers, params=params)

    def submit_brand(self, account_id, brand_id, headers=None):
        return self.post(
            _nested(account_id, "brands", brand_id) + "/submit",
            json={},
            headers=headers,
        )

    def verify_brand(self, account_id, brand_id, headers=None):
        return self.post(
            _nested(account_id, "brands", brand_id) + "/verify",
            json={},
            headers=headers,
        )

    def fail_brand(self, account_id, brand_id, headers=None):
        return self.post(
            _nested(account_id, "brands", brand_id) + "/fail",
            json={},
            headers=headers,
        )

    def revoke_brand(self, account_id, brand_id, payload, headers=None):
        return self.post(
            _nested(account_id, "brands", brand_id) + "/revoke",
            json=payload,
            headers=headers,
        )

    def list_brand_campaigns(self, account_id, brand_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "brands", brand_id) + "/campaigns",
            headers=headers,
            params=params,
        )

    def list_brand_consent_records(
        self, account_id, brand_id, headers=None, params=None
    ):
        return self.get(
            _nested(account_id, "brands", brand_id) + "/consent_records",
            headers=headers,
            params=params,
        )

    # ─── Campaigns ────────────────────────────────────────────────────────

    def create_campaign(self, account_id, payload, headers=None):
        return self.post(
            _nested(account_id, "campaigns"), json=payload, headers=headers
        )

    def get_campaign(self, account_id, campaign_id, headers=None):
        return self.get(
            _nested(account_id, "campaigns", campaign_id), headers=headers
        )

    def get_campaign_by_id(self, campaign_id, headers=None):
        return self.get(
            "{0}/campaigns/{1}".format(API_PREFIX, campaign_id), headers=headers
        )

    def list_campaigns(self, account_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "campaigns"), headers=headers, params=params
        )

    def submit_campaign(self, account_id, campaign_id, payload=None, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/submit",
            json=payload or {},
            headers=headers,
        )

    def approve_campaign(self, account_id, campaign_id, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/approve",
            json={},
            headers=headers,
        )

    def reject_campaign(self, account_id, campaign_id, payload, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/reject",
            json=payload,
            headers=headers,
        )

    def suspend_campaign(self, account_id, campaign_id, payload, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/suspend",
            json=payload,
            headers=headers,
        )

    def reactivate_campaign(self, account_id, campaign_id, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/reactivate",
            json={},
            headers=headers,
        )

    def deactivate_campaign(self, account_id, campaign_id, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/deactivate",
            json={},
            headers=headers,
        )

    def list_campaign_numbers(self, account_id, campaign_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "campaigns", campaign_id) + "/numbers",
            headers=headers,
            params=params,
        )

    def list_campaign_messages(self, account_id, campaign_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "campaigns", campaign_id) + "/messages",
            headers=headers,
            params=params,
        )

    def list_campaign_feedback_events(
        self, account_id, campaign_id, headers=None, params=None
    ):
        return self.get(
            _nested(account_id, "campaigns", campaign_id) + "/feedback_events",
            headers=headers,
            params=params,
        )

    def create_snapshot(self, account_id, campaign_id, payload, headers=None):
        return self.post(
            _nested(account_id, "campaigns", campaign_id) + "/snapshots",
            json=payload,
            headers=headers,
        )

    def get_snapshot(self, account_id, campaign_id, snapshot_id, headers=None):
        return self.get(
            _nested(account_id, "campaigns", campaign_id)
            + "/snapshots/{0}".format(snapshot_id),
            headers=headers,
        )

    def list_snapshots(self, account_id, campaign_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "campaigns", campaign_id) + "/snapshots",
            headers=headers,
            params=params,
        )

    # ─── Sender numbers ───────────────────────────────────────────────────

    def create_number(self, account_id, payload, headers=None):
        return self.post(
            _nested(account_id, "numbers"), json=payload, headers=headers
        )

    def get_number(self, account_id, number_id, headers=None):
        return self.get(_nested(account_id, "numbers", number_id), headers=headers)

    def get_number_by_id(self, number_id, headers=None):
        return self.get(
            "{0}/numbers/{1}".format(API_PREFIX, number_id), headers=headers
        )

    def list_numbers(self, account_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "numbers"), headers=headers, params=params
        )

    def activate_number(self, account_id, number_id, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/activate",
            json={},
            headers=headers,
        )

    def complete_port(self, account_id, number_id, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/complete_port",
            json={},
            headers=headers,
        )

    def fail_port(self, account_id, number_id, payload, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/fail_port",
            json=payload,
            headers=headers,
        )

    def attach_number(self, account_id, number_id, payload, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/attach",
            json=payload,
            headers=headers,
        )

    def detach_number(self, account_id, number_id, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/detach",
            json={},
            headers=headers,
        )

    def reinstate_number(self, account_id, number_id, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/reinstate",
            json={},
            headers=headers,
        )

    def release_number(self, account_id, number_id, headers=None):
        return self.post(
            _nested(account_id, "numbers", number_id) + "/release",
            json={},
            headers=headers,
        )

    def list_number_messages(self, account_id, number_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "numbers", number_id) + "/messages",
            headers=headers,
            params=params,
        )

    # ─── Consent records ──────────────────────────────────────────────────

    def create_consent_record(self, account_id, payload, headers=None):
        return self.post(
            _nested(account_id, "consent_records"), json=payload, headers=headers
        )

    def get_consent_record(self, account_id, consent_id, headers=None):
        return self.get(
            _nested(account_id, "consent_records", consent_id), headers=headers
        )

    def list_consent_records(self, account_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "consent_records"), headers=headers, params=params
        )

    def revoke_consent(self, account_id, consent_id, headers=None):
        return self.post(
            _nested(account_id, "consent_records", consent_id) + "/revoke",
            json={},
            headers=headers,
        )

    # ─── Messages ─────────────────────────────────────────────────────────

    def send_message(self, account_id, payload, headers=None):
        return self.post(
            _nested(account_id, "messages"), json=payload, headers=headers
        )

    def get_message(self, account_id, message_id, headers=None):
        return self.get(
            _nested(account_id, "messages", message_id), headers=headers
        )

    def get_message_by_id(self, message_id, headers=None):
        return self.get(
            "{0}/messages/{1}".format(API_PREFIX, message_id), headers=headers
        )

    def list_messages(self, account_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "messages"), headers=headers, params=params
        )

    def report_delivery_outcome(self, account_id, message_id, payload, headers=None):
        return self.post(
            _nested(account_id, "messages", message_id) + "/delivery_outcome",
            json=payload,
            headers=headers,
        )

    def retry_message(self, account_id, message_id, headers=None):
        return self.post(
            _nested(account_id, "messages", message_id) + "/retry",
            json={},
            headers=headers,
        )

    def cancel_message(self, account_id, message_id, headers=None):
        return self.post(
            _nested(account_id, "messages", message_id) + "/cancel",
            json={},
            headers=headers,
        )

    # ─── Feedback events ──────────────────────────────────────────────────

    def create_feedback_event(self, account_id, payload, headers=None):
        return self.post(
            _nested(account_id, "feedback_events"), json=payload, headers=headers
        )

    def list_feedback_events(self, account_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "feedback_events"), headers=headers, params=params
        )

    # ─── Charges ──────────────────────────────────────────────────────────

    def list_charges(self, account_id, headers=None, params=None):
        return self.get(
            _nested(account_id, "charges"), headers=headers, params=params
        )
