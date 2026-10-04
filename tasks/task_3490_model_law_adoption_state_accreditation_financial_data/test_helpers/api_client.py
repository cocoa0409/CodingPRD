"""API client: one method per endpoint of the model-law / accreditation API.

Every path is mounted under the ``/naic`` prefix, including the logical-clock
endpoint ``POST /naic/_clock/set_current_utc``.

Two ways to call, deliberately kept interchangeable:

- ``ApiClient`` — an explicit client class (instantiate directly, or via
  ``create_api_client(base_url=...)``).
- The module itself — ``api_client`` is a shared module-level instance, and a
  module-level ``__getattr__`` delegates every endpoint-method name to it, so
  ``import test_helpers.api_client as ac`` followed by ``ac.create_state(...)``
  works exactly like calling the instance. The package ``__init__`` never
  rebinds the name ``api_client`` to the instance, so the submodule always
  survives ``import ... as`` intact.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonObject, Params, ResourceId

BASE = "/naic"


class ApiClient(GenericApiClient):
    """Typed wrapper over the API's HTTP surface."""

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload: JsonObject, headers: Headers):
        """POST /naic/_clock/set_current_utc — payload carries to_iso8601."""
        return self._request("POST", BASE + "/_clock/set_current_utc", payload, headers)

    # -------------------------------------------------------------- model acts
    def create_model_act(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/model-acts", payload, headers)

    def get_model_act(self, act_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/model-acts/" + str(act_id), headers=headers)

    def close_ballot(self, act_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/model-acts/" + str(act_id) + "/close-ballot", {}, headers
        )

    def publish_model_act(self, act_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/model-acts/" + str(act_id) + "/publish", {}, headers
        )

    def cast_ballot(self, act_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/model-acts/" + str(act_id) + "/ballots", payload, headers
        )

    def list_ballots(self, act_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/model-acts/" + str(act_id) + "/ballots",
            headers=headers, params=params,
        )

    def list_exposure_drafts(self, act_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/model-acts/" + str(act_id) + "/exposure-drafts",
            headers=headers, params=params,
        )

    def list_adoptions(self, act_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/model-acts/" + str(act_id) + "/adoptions",
            headers=headers, params=params,
        )

    # ---------------------------------------------------------- exposure drafts
    def create_exposure_draft(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/exposure-drafts", payload, headers)

    def close_exposure_draft(self, draft_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/exposure-drafts/" + str(draft_id) + "/close", {}, headers
        )

    # ------------------------------------------------------------------- states
    def create_state(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/states", payload, headers)

    def get_state(self, state_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/states/" + str(state_id), headers=headers)

    def list_reviews(self, state_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/states/" + str(state_id) + "/reviews",
            headers=headers, params=params,
        )

    # ---------------------------------------------------------------- adoptions
    def create_adoption(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/adoptions", payload, headers)

    def certify_adoption(self, adoption_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/adoptions/" + str(adoption_id) + "/certify", payload, headers
        )

    # ------------------------------------------------------------- reviews
    def create_review(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/reviews", payload, headers)

    def issue_findings(self, review_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/reviews/" + str(review_id) + "/issue-findings",
            payload, headers,
        )

    def finalize_review(self, review_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/reviews/" + str(review_id) + "/finalize", {}, headers
        )

    # ----------------------------------------------------------------- insurers
    def create_insurer(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/insurers", payload, headers)

    def get_insurer(self, insurer_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/insurers/" + str(insurer_id), headers=headers)

    def list_filings(self, insurer_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/insurers/" + str(insurer_id) + "/filings",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------ filings
    def create_filing(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/filings", payload, headers)

    def get_filing(self, filing_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/filings/" + str(filing_id), headers=headers)

    def submit_filing(self, filing_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/filings/" + str(filing_id) + "/submit", {}, headers
        )

    def validate_filing(self, filing_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/filings/" + str(filing_id) + "/validate", {}, headers
        )

    def list_rbc_reports(self, filing_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/filings/" + str(filing_id) + "/rbc-reports",
            headers=headers, params=params,
        )

    # ---------------------------------------------------------------- producers
    def create_producer(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/producers", payload, headers)

    def get_producer(self, producer_id: ResourceId, headers: Headers):
        return self._request("GET", BASE + "/producers/" + str(producer_id), headers=headers)

    def list_licenses(self, producer_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/producers/" + str(producer_id) + "/licenses",
            headers=headers, params=params,
        )

    # ----------------------------------------------------------------- licenses
    def create_license(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/licenses", payload, headers)

    def issue_license(self, license_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/licenses/" + str(license_id) + "/issue", {}, headers
        )

    def revoke_license(self, license_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/licenses/" + str(license_id) + "/revoke", {}, headers
        )

    # ----------------------------------------------------- market conduct calls
    def create_market_conduct_call(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/market-conduct-calls", payload, headers)

    def get_market_conduct_call(self, call_id: ResourceId, headers: Headers):
        return self._request(
            "GET", BASE + "/market-conduct-calls/" + str(call_id), headers=headers
        )

    def create_response(self, call_id: ResourceId, payload: JsonObject, headers: Headers):
        return self._request(
            "POST", BASE + "/market-conduct-calls/" + str(call_id) + "/responses",
            payload, headers,
        )

    def list_responses(self, call_id: ResourceId, headers: Headers, params: Params = None):
        return self._request(
            "GET", BASE + "/market-conduct-calls/" + str(call_id) + "/responses",
            headers=headers, params=params,
        )

    def close_call(self, call_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/market-conduct-calls/" + str(call_id) + "/close", {}, headers
        )

    # ------------------------------------------------------- valuation standards
    def create_valuation_standard(self, payload: JsonObject, headers: Headers):
        return self._request("POST", BASE + "/valuation-standards", payload, headers)

    def activate_valuation_standard(self, standard_id: ResourceId, headers: Headers):
        return self._request(
            "POST", BASE + "/valuation-standards/" + str(standard_id) + "/activate",
            {}, headers,
        )


def create_api_client(base_url: str = None) -> ApiClient:
    """Explicit factory: a fresh client, optionally pinned to a base URL."""
    return ApiClient(base_url)


# Shared module-level instance. Constructing it performs no network I/O; the
# base URL is read from the environment the runner injects before pytest starts.
api_client = ApiClient()


def __getattr__(name: str):
    """Module-level convenience surface: delegate endpoint-method lookups to the
    shared ``api_client`` instance so the module is callable like a client."""
    attr = getattr(api_client, name, None)
    if callable(attr):
        return attr
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
