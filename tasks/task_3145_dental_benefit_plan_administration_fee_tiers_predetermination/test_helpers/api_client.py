"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so a test may assert on the
status code and on the envelope, rather than on a pre-digested value.  The
``/dental`` prefix and the shape of each path live here and nowhere else.

``canonical_instant`` exists because the PRD promises ISO 8601 UTC
timestamps with three fractional digits; any expected instant a test
carries is normalised through it before comparison so a server rendering
the same instant with a different fractional width is compared on value
rather than on spelling.
"""

import os
import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    # ─── Plans ────────────────────────────────────────────────────────────

    def create_plan(self, payload, headers=None):
        return self.post(API_PREFIX + "/plans", json=payload, headers=headers)

    def list_plans(self, headers=None, params=None):
        return self.get(API_PREFIX + "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers=None):
        return self.get("{0}/plans/{1}".format(API_PREFIX, plan_id), headers=headers)

    def activate_plan(self, plan_id, headers=None):
        return self.post(
            "{0}/plans/{1}/activate".format(API_PREFIX, plan_id), json={}, headers=headers
        )

    def suspend_plan(self, plan_id, headers=None):
        return self.post(
            "{0}/plans/{1}/suspend".format(API_PREFIX, plan_id), json={}, headers=headers
        )

    def retire_plan(self, plan_id, headers=None):
        return self.post(
            "{0}/plans/{1}/retire".format(API_PREFIX, plan_id), json={}, headers=headers
        )

    # ─── Providers ────────────────────────────────────────────────────────

    def create_provider(self, payload, headers=None):
        return self.post(API_PREFIX + "/providers", json=payload, headers=headers)

    def list_providers(self, headers=None, params=None):
        return self.get(API_PREFIX + "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers=None):
        return self.get(
            "{0}/providers/{1}".format(API_PREFIX, provider_id), headers=headers
        )

    def terminate_provider(self, provider_id, headers=None):
        return self.post(
            "{0}/providers/{1}/terminate".format(API_PREFIX, provider_id),
            json={},
            headers=headers,
        )

    # ─── Fee schedules ────────────────────────────────────────────────────

    def create_fee_schedule(self, payload, headers=None):
        return self.post(API_PREFIX + "/fee-schedules", json=payload, headers=headers)

    def list_fee_schedules(self, headers=None, params=None):
        return self.get(API_PREFIX + "/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, schedule_id, headers=None):
        return self.get(
            "{0}/fee-schedules/{1}".format(API_PREFIX, schedule_id), headers=headers
        )

    def list_fee_schedule_entries(self, schedule_id, headers=None, params=None):
        return self.get(
            "{0}/fee-schedules/{1}/entries".format(API_PREFIX, schedule_id),
            headers=headers,
            params=params,
        )

    def activate_fee_schedule(self, schedule_id, headers=None):
        return self.post(
            "{0}/fee-schedules/{1}/activate".format(API_PREFIX, schedule_id),
            json={},
            headers=headers,
        )

    def retire_fee_schedule(self, schedule_id, headers=None):
        return self.post(
            "{0}/fee-schedules/{1}/retire".format(API_PREFIX, schedule_id),
            json={},
            headers=headers,
        )

    # ─── Limitation rules ─────────────────────────────────────────────────

    def create_limitation_rule(self, plan_id, payload, headers=None):
        return self.post(
            "{0}/plans/{1}/limitation-rules".format(API_PREFIX, plan_id),
            json=payload,
            headers=headers,
        )

    def list_limitation_rules(self, plan_id, headers=None, params=None):
        return self.get(
            "{0}/plans/{1}/limitation-rules".format(API_PREFIX, plan_id),
            headers=headers,
            params=params,
        )

    def get_limitation_rule(self, rule_id, headers=None):
        return self.get(
            "{0}/limitation-rules/{1}".format(API_PREFIX, rule_id), headers=headers
        )

    # ─── Subscribers and dependents ───────────────────────────────────────

    def create_subscriber(self, payload, headers=None):
        return self.post(API_PREFIX + "/subscribers", json=payload, headers=headers)

    def list_subscribers(self, headers=None, params=None):
        return self.get(API_PREFIX + "/subscribers", headers=headers, params=params)

    def get_subscriber(self, subscriber_id, headers=None):
        return self.get(
            "{0}/subscribers/{1}".format(API_PREFIX, subscriber_id), headers=headers
        )

    def terminate_subscriber(self, subscriber_id, headers=None):
        return self.post(
            "{0}/subscribers/{1}/terminate".format(API_PREFIX, subscriber_id),
            json={},
            headers=headers,
        )

    def create_dependent(self, subscriber_id, payload, headers=None):
        return self.post(
            "{0}/subscribers/{1}/dependents".format(API_PREFIX, subscriber_id),
            json=payload,
            headers=headers,
        )

    def list_dependents(self, subscriber_id, headers=None, params=None):
        return self.get(
            "{0}/subscribers/{1}/dependents".format(API_PREFIX, subscriber_id),
            headers=headers,
            params=params,
        )

    def get_dependent(self, dependent_id, headers=None):
        return self.get(
            "{0}/dependents/{1}".format(API_PREFIX, dependent_id), headers=headers
        )

    def terminate_dependent(self, dependent_id, headers=None):
        return self.post(
            "{0}/dependents/{1}/terminate".format(API_PREFIX, dependent_id),
            json={},
            headers=headers,
        )

    # ─── Accumulators ─────────────────────────────────────────────────────

    def list_subscriber_accumulators(self, subscriber_id, headers=None, params=None):
        return self.get(
            "{0}/subscribers/{1}/accumulators".format(API_PREFIX, subscriber_id),
            headers=headers,
            params=params,
        )

    def list_dependent_accumulators(self, dependent_id, headers=None, params=None):
        return self.get(
            "{0}/dependents/{1}/accumulators".format(API_PREFIX, dependent_id),
            headers=headers,
            params=params,
        )

    # ─── Predeterminations ────────────────────────────────────────────────

    def create_predetermination(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/predeterminations", json=payload, headers=headers
        )

    def list_predeterminations(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/predeterminations", headers=headers, params=params
        )

    def get_predetermination(self, predet_id, headers=None):
        return self.get(
            "{0}/predeterminations/{1}".format(API_PREFIX, predet_id), headers=headers
        )

    def assign_predetermination(self, predet_id, payload, headers=None):
        return self.post(
            "{0}/predeterminations/{1}/assign".format(API_PREFIX, predet_id),
            json=payload,
            headers=headers,
        )

    def reassign_predetermination(self, predet_id, payload, headers=None):
        return self.post(
            "{0}/predeterminations/{1}/reassign".format(API_PREFIX, predet_id),
            json=payload,
            headers=headers,
        )

    def approve_predetermination(self, predet_id, payload, headers=None):
        return self.post(
            "{0}/predeterminations/{1}/approve".format(API_PREFIX, predet_id),
            json=payload,
            headers=headers,
        )

    def deny_predetermination(self, predet_id, headers=None):
        return self.post(
            "{0}/predeterminations/{1}/deny".format(API_PREFIX, predet_id),
            json={},
            headers=headers,
        )

    def withdraw_predetermination(self, predet_id, headers=None):
        return self.post(
            "{0}/predeterminations/{1}/withdraw".format(API_PREFIX, predet_id),
            json={},
            headers=headers,
        )

    # ─── Claims, lines, attachments ───────────────────────────────────────

    def create_claim(self, payload, headers=None):
        return self.post(API_PREFIX + "/claims", json=payload, headers=headers)

    def list_claims(self, headers=None, params=None):
        return self.get(API_PREFIX + "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers=None):
        return self.get("{0}/claims/{1}".format(API_PREFIX, claim_id), headers=headers)

    def list_claim_lines(self, claim_id, headers=None, params=None):
        return self.get(
            "{0}/claims/{1}/lines".format(API_PREFIX, claim_id),
            headers=headers,
            params=params,
        )

    def get_claim_line(self, line_id, headers=None):
        return self.get(
            "{0}/claim-lines/{1}".format(API_PREFIX, line_id), headers=headers
        )

    def list_claim_line_attachments(self, line_id, headers=None, params=None):
        return self.get(
            "{0}/claim-lines/{1}/attachments".format(API_PREFIX, line_id),
            headers=headers,
            params=params,
        )

    def create_claim_attachment(self, claim_id, payload, headers=None):
        return self.post(
            "{0}/claims/{1}/attachments".format(API_PREFIX, claim_id),
            json=payload,
            headers=headers,
        )

    def list_claim_attachments(self, claim_id, headers=None, params=None):
        return self.get(
            "{0}/claims/{1}/attachments".format(API_PREFIX, claim_id),
            headers=headers,
            params=params,
        )

    def cob_confirm_claim(self, claim_id, payload, headers=None):
        return self.post(
            "{0}/claims/{1}/cob-confirm".format(API_PREFIX, claim_id),
            json=payload,
            headers=headers,
        )

    def pay_claim(self, claim_id, headers=None):
        return self.post(
            "{0}/claims/{1}/pay".format(API_PREFIX, claim_id), json={}, headers=headers
        )

    def void_claim(self, claim_id, payload, headers=None):
        return self.post(
            "{0}/claims/{1}/void".format(API_PREFIX, claim_id),
            json=payload,
            headers=headers,
        )


api_client = ApiClient()
