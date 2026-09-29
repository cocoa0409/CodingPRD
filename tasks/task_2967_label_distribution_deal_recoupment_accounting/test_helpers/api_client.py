"""
Endpoint client for the Label Distribution Recoupment API.

One method per row of PRD Section 4. Every method returns the raw
``requests.Response`` so tests can assert on status codes and error envelopes.

Two things this client does that the generic base class cannot:

1. **Exact percentage text.** PRD Section 2.6 says "A value of 0.15 is not an
   acceptable substitute for 0.1500: the request-validation rank rejects a
   percentage that is not written with four decimals". A Python float cannot
   express that difference - ``json.dumps(0.1500)`` emits ``0.15``. So any
   ``decimal.Decimal`` appearing anywhere in a payload is serialised as a bare
   JSON number carrying its own exact digits: ``Decimal("0.1500")`` goes out as
   ``0.1500`` and ``Decimal("0.15")`` goes out as ``0.15``. Percentages are
   therefore always passed as Decimals (see ``factories.pct``).

2. **Timestamp canonicalisation.** ``canonical_instant`` normalises an ISO 8601
   UTC instant to exactly three fractional digits so that a comparison never
   fails merely because one side wrote ``...T00:00:00Z`` and the other wrote
   ``...T00:00:00.000Z``.
"""

import json
import re
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

# ---------------------------------------------------------------------------
# JSON body serialisation that preserves written decimal places
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"^__PRDBENCH_DEC_(\d+)__$")


def encode_body(payload: Any) -> Optional[str]:
    """Serialise a payload to JSON text, emitting Decimals with exact digits."""
    if payload is None:
        return None

    literals: Dict[str, str] = {}

    def _default(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            token = "__PRDBENCH_DEC_%d__" % len(literals)
            literals[token] = format(obj, "f")
            return token
        raise TypeError(
            "Cannot JSON-serialise %r of type %s" % (obj, type(obj).__name__)
        )

    text = json.dumps(payload, default=_default)
    for token, literal in literals.items():
        text = text.replace('"%s"' % token, literal)
    return text


def encode_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Render query parameters, keeping Decimal digits exact and booleans lowercase."""
    if params is None:
        return None
    out: Dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, Decimal):
            out[key] = format(value, "f")
        elif isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Instant canonicalisation
# ---------------------------------------------------------------------------

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    ``2026-08-01T00:00:00Z``, ``2026-08-01T00:00:00.0Z`` and
    ``2026-08-01T00:00:00.000000Z`` all canonicalise to
    ``2026-08-01T00:00:00.000Z``. A value that does not parse is returned
    unchanged so the caller's assertion reports the raw text.
    """
    if value is None:
        return None
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    day, clock, frac, offset = match.groups()
    if offset not in (None, "Z", "z", "+00:00", "+0000", "-00:00", "-0000"):
        # A non-UTC offset is itself a violation; surface the raw text.
        return value
    frac = (frac or "")[:3].ljust(3, "0")
    return "%sT%s.%sZ" % (day, clock, frac)


class ApiClient(GenericApiClient):
    """One method per PRD Section 4 endpoint row."""

    # -- transport ---------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        url = "%s%s" % (self.base_url, path)
        sent_headers = dict(headers or {})
        upper = method.upper()

        if upper in ("GET", "DELETE"):
            return self.session.request(
                method,
                url,
                headers=sent_headers,
                params=encode_params(payload if payload is not None else params),
            )

        body = encode_body(payload)
        if body is not None:
            sent_headers.setdefault("Content-Type", "application/json")
        return self.session.request(
            method,
            url,
            headers=sent_headers,
            data=body,
            params=encode_params(params),
        )

    # -- clock (PRD 2.5) ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- distributors ------------------------------------------------------
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", "/distributors/%s" % distributor_id, None, headers)

    # -- artists -----------------------------------------------------------
    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", "/artists/%s" % artist_id, None, headers)

    # -- distribution deals ------------------------------------------------
    def create_deal(self, payload, headers):
        return self._request("POST", "/distribution-deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", "/distribution-deals/%s" % deal_id, None, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/distribution-deals", params, headers)

    def execute_deal(self, deal_id, payload, headers):
        return self._request(
            "POST", "/distribution-deals/%s/execute" % deal_id, payload, headers
        )

    def terminate_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", "/distribution-deals/%s/terminate" % deal_id, payload, headers
        )

    def expire_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", "/distribution-deals/%s/expire" % deal_id, payload, headers
        )

    def enter_post_term_collection(self, deal_id, headers, payload=None):
        return self._request(
            "POST",
            "/distribution-deals/%s/enter-post-term-collection" % deal_id,
            payload,
            headers,
        )

    def close_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", "/distribution-deals/%s/close" % deal_id, payload, headers
        )

    def get_recoupment_summary(self, deal_id, headers, variant=None):
        params = {"variant": variant} if variant is not None else None
        return self._request(
            "GET",
            "/distribution-deals/%s/recoupment-summary" % deal_id,
            params,
            headers,
        )

    # -- releases ----------------------------------------------------------
    def create_release(self, payload, headers):
        return self._request("POST", "/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", "/releases/%s" % release_id, None, headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/releases", params, headers)

    def release_to_market(self, release_id, payload, headers):
        return self._request(
            "POST", "/releases/%s/release" % release_id, payload, headers
        )

    def list_release_revenue_lines(self, release_id, headers, params=None):
        return self._request(
            "GET", "/releases/%s/dsp-revenue-lines" % release_id, params, headers
        )

    # -- artist agreements -------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/artist-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", "/artist-agreements/%s" % agreement_id, None, headers
        )

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/artist-agreements", params, headers)

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", "/artist-agreements/%s/activate" % agreement_id, payload, headers
        )

    def propose_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            "/artist-agreements/%s/propose-amendment" % agreement_id,
            payload,
            headers,
        )

    def resolve_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            "/artist-agreements/%s/resolve-amendment" % agreement_id,
            payload,
            headers,
        )

    # -- marketing spends --------------------------------------------------
    def create_spend(self, payload, headers):
        return self._request("POST", "/marketing-spends", payload, headers)

    def get_spend(self, spend_id, headers):
        return self._request("GET", "/marketing-spends/%s" % spend_id, None, headers)

    def list_spends(self, headers, params=None):
        return self._request("GET", "/marketing-spends", params, headers)

    def submit_spend(self, spend_id, headers, payload=None):
        return self._request(
            "POST", "/marketing-spends/%s/submit" % spend_id, payload, headers
        )

    def decide_spend(self, spend_id, payload, headers):
        return self._request(
            "POST", "/marketing-spends/%s/decide" % spend_id, payload, headers
        )

    def settle_spend(self, spend_id, payload, headers):
        return self._request(
            "POST", "/marketing-spends/%s/settle" % spend_id, payload, headers
        )

    # -- stream rate cards -------------------------------------------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/stream-rate-cards", payload, headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/stream-rate-cards", params, headers)

    # -- dsp revenue reports -----------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/dsp-revenue-reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request(
            "GET", "/dsp-revenue-reports/%s" % report_id, None, headers
        )

    def list_reports(self, headers, params=None):
        return self._request("GET", "/dsp-revenue-reports", params, headers)

    def append_line(self, report_id, payload, headers):
        return self._request(
            "POST", "/dsp-revenue-reports/%s/lines" % report_id, payload, headers
        )

    def list_report_lines(self, report_id, headers, params=None):
        return self._request(
            "GET", "/dsp-revenue-reports/%s/lines" % report_id, params, headers
        )

    def submit_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", "/dsp-revenue-reports/%s/submit" % report_id, payload, headers
        )

    def accept_report(self, report_id, payload, headers):
        return self._request(
            "POST", "/dsp-revenue-reports/%s/accept" % report_id, payload, headers
        )

    def dispute_report(self, report_id, payload, headers):
        return self._request(
            "POST", "/dsp-revenue-reports/%s/dispute" % report_id, payload, headers
        )

    # -- physical runs -----------------------------------------------------
    def create_run(self, payload, headers):
        return self._request("POST", "/physical-runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", "/physical-runs/%s" % run_id, None, headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/physical-runs", params, headers)

    def manufacture_run(self, run_id, payload, headers):
        return self._request(
            "POST", "/physical-runs/%s/manufacture" % run_id, payload, headers
        )

    def ship_run(self, run_id, payload, headers):
        return self._request(
            "POST", "/physical-runs/%s/ship" % run_id, payload, headers
        )

    def record_returns(self, run_id, payload, headers):
        return self._request(
            "POST", "/physical-runs/%s/record-returns" % run_id, payload, headers
        )

    def liquidate_reserve(self, run_id, payload, headers):
        return self._request(
            "POST", "/physical-runs/%s/liquidate-reserve" % run_id, payload, headers
        )

    def void_liquidation(self, run_id, payload, headers):
        return self._request(
            "POST", "/physical-runs/%s/void-liquidation" % run_id, payload, headers
        )

    # -- artist statements -------------------------------------------------
    def create_statement(self, payload, headers):
        return self._request("POST", "/artist-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", "/artist-statements/%s" % statement_id, None, headers
        )

    def list_statements(self, headers, params=None):
        return self._request("GET", "/artist-statements", params, headers)

    def prepare_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", "/artist-statements/%s/prepare" % statement_id, payload, headers
        )

    def issue_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", "/artist-statements/%s/issue" % statement_id, payload, headers
        )

    def object_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", "/artist-statements/%s/object" % statement_id, payload, headers
        )

    def resolve_objection(self, statement_id, payload, headers):
        return self._request(
            "POST",
            "/artist-statements/%s/resolve-objection" % statement_id,
            payload,
            headers,
        )

    def finalize_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", "/artist-statements/%s/finalize" % statement_id, payload, headers
        )

    def request_audit(self, statement_id, payload, headers):
        return self._request(
            "POST", "/artist-statements/%s/request-audit" % statement_id, payload, headers
        )

    def conclude_audit(self, statement_id, payload, headers):
        return self._request(
            "POST",
            "/artist-statements/%s/conclude-audit" % statement_id,
            payload,
            headers,
        )
