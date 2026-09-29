"""One method per endpoint of PRD section 4, plus instant canonicalisation.

Every method returns the raw ``requests.Response`` so a test can assert on the
status code as well as the envelope.  Read endpoints accept a ``params`` mapping
which is forwarded as the query string, so pagination and filtering are
expressed the same way everywhere.

Timestamps are canonicalised in one place — :func:`canonical_instant` — so that
comparing an instant a test computed against an instant the API returned never
turns into an argument about how many fractional digits were printed.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    Non-strings and unparseable strings are returned untouched so that a
    malformed value still fails the assertion that cares about it rather than
    being quietly rewritten here.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:3].ljust(3, "0")
    return f"{match.group('date')}T{match.group('time')}.{frac}Z"


class ApiClient(GenericApiClient):
    """Typed surface over the culinary costing API.

    A read issued without an explicit header set is sent as a ``CostAnalyst``,
    since the PRD authorises all five roles on every read endpoint; writes never
    get a default, so a test that means to exercise a role must name it.
    """

    def _request(self, method, path, payload=None, headers=None, params=None):
        if headers is None and method.upper() == "GET":
            from .test_users import COST_ANALYST

            headers = COST_ANALYST
        if method.upper() == "DELETE" and isinstance(payload, dict):
            # The generic runner client folds a DELETE payload into the query
            # string, but PRD 2.7 makes `expected_recipe_version` a *body*
            # field on DELETE /culinary/recipe-components/{id} ("requires
            # `expected_recipe_version` as a non-optional body field").  Send a
            # real JSON body so the request matches the contract; otherwise a
            # PRD-faithful server correctly reports the field as missing.
            url = f"{self.base_url}{path}"
            return self.session.request(
                "DELETE", url, headers=headers or {}, json=payload, params=params
            )
        return super()._request(method, path, payload, headers, params)

    # ─── raw escape hatch ─────────────────────────────

    def call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """Issue an arbitrary request against a path under the API mount."""
        return self._request(method, path, payload, headers)

    # ─── logical clock ────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def advance_clock_to(self, to_iso8601: str, headers=None):
        return self.set_clock({"to_iso8601": to_iso8601}, headers)

    # ─── units ────────────────────────────────────────

    def create_unit(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/units", payload, headers)

    def get_unit(self, unit_id: str, headers=None):
        return self._request("GET", f"{BASE}/units/{unit_id}", None, headers)

    # ─── ingredients ──────────────────────────────────

    def create_ingredient(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/ingredients/{ingredient_id}", None, headers
        )

    def retire_ingredient(self, ingredient_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/ingredients/{ingredient_id}/retire", payload, headers
        )

    def list_ingredient_prices(self, ingredient_id: str, params=None, headers=None):
        return self._request(
            "GET", f"{BASE}/ingredients/{ingredient_id}/prices", params, headers
        )

    def list_ingredient_count_lines(
        self, ingredient_id: str, params=None, headers=None
    ):
        return self._request(
            "GET", f"{BASE}/ingredients/{ingredient_id}/count-lines", params, headers
        )

    # ─── price feeds ──────────────────────────────────

    def create_price_feed(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/price-feeds", payload, headers)

    def get_price_feed(self, price_feed_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/price-feeds/{price_feed_id}", None, headers
        )

    def add_price_feed_line(
        self, price_feed_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"{BASE}/price-feeds/{price_feed_id}/lines", payload, headers
        )

    def list_price_feed_lines(self, price_feed_id: str, params=None, headers=None):
        return self._request(
            "GET", f"{BASE}/price-feeds/{price_feed_id}/lines", params, headers
        )

    def publish_price_feed(self, price_feed_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/price-feeds/{price_feed_id}/publish", payload, headers
        )

    # ─── recipes ──────────────────────────────────────

    def create_recipe(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/recipes", payload, headers)

    def get_recipe(self, recipe_id: str, headers=None):
        return self._request("GET", f"{BASE}/recipes/{recipe_id}", None, headers)

    def add_recipe_component(
        self, recipe_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"{BASE}/recipes/{recipe_id}/components", payload, headers
        )

    def get_recipe_component(self, recipe_component_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/recipe-components/{recipe_component_id}", None, headers
        )

    def list_recipe_components(self, params=None, headers=None):
        return self._request("GET", f"{BASE}/recipe-components", params, headers)

    def delete_recipe_component(
        self, recipe_component_id: str, payload=None, headers=None
    ):
        # `payload` is a JSON *body* (PRD 2.7 makes expected_recipe_version a
        # non-optional body field on this DELETE), not a query string.
        return self._request(
            "DELETE", f"{BASE}/recipe-components/{recipe_component_id}", payload, headers
        )

    def cost_rollup_recipe(self, recipe_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/recipes/{recipe_id}/cost-rollup", payload, headers
        )

    def get_recipe_allergen_nutrition(self, recipe_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/recipes/{recipe_id}/allergen-nutrition", None, headers
        )

    def submit_recipe_review(self, recipe_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/recipes/{recipe_id}/submit-review", payload, headers
        )

    def activate_recipe(self, recipe_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/recipes/{recipe_id}/activate", payload, headers
        )

    def retire_recipe(self, recipe_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/recipes/{recipe_id}/retire", payload, headers
        )

    def list_prep_guides(self, recipe_id: str, params=None, headers=None):
        return self._request(
            "GET", f"{BASE}/recipes/{recipe_id}/prep-guides", params, headers
        )

    # ─── menu items ───────────────────────────────────

    def create_menu_item(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/menu-items", payload, headers)

    def get_menu_item(self, menu_item_id: str, headers=None):
        return self._request("GET", f"{BASE}/menu-items/{menu_item_id}", None, headers)

    def list_menu_items(self, params=None, headers=None):
        return self._request("GET", f"{BASE}/menu-items", params, headers)

    def plate_cost_menu_item(self, menu_item_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/menu-items/{menu_item_id}/plate-cost", payload, headers
        )

    def activate_menu_item(self, menu_item_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/menu-items/{menu_item_id}/activate", payload, headers
        )

    def list_menu_item_mix_lines(self, menu_item_id: str, params=None, headers=None):
        return self._request(
            "GET", f"{BASE}/menu-items/{menu_item_id}/mix-lines", params, headers
        )

    # ─── price change proposals ───────────────────────

    def create_proposal(self, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/price-change-proposals", payload, headers
        )

    def get_proposal(self, proposal_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/price-change-proposals/{proposal_id}", None, headers
        )

    def list_proposals(self, params=None, headers=None):
        return self._request(
            "GET", f"{BASE}/price-change-proposals", params, headers
        )

    def update_proposal(
        self, proposal_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "PATCH", f"{BASE}/price-change-proposals/{proposal_id}", payload, headers
        )

    def submit_proposal(self, proposal_id: str, headers=None, payload=None):
        return self._request(
            "POST",
            f"{BASE}/price-change-proposals/{proposal_id}/submit",
            payload,
            headers,
        )

    def request_proposal_revision(
        self, proposal_id: str, payload=None, headers=None
    ):
        return self._request(
            "POST",
            f"{BASE}/price-change-proposals/{proposal_id}/request-revision",
            payload,
            headers,
        )

    def approve_proposal(self, proposal_id: str, headers=None, payload=None):
        return self._request(
            "POST",
            f"{BASE}/price-change-proposals/{proposal_id}/approve",
            payload,
            headers,
        )

    def apply_proposal(self, proposal_id: str, headers=None, payload=None):
        return self._request(
            "POST",
            f"{BASE}/price-change-proposals/{proposal_id}/apply",
            payload,
            headers,
        )

    # ─── spec change orders ───────────────────────────

    def create_spec_change_order(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/spec-change-orders", payload, headers)

    def get_spec_change_order(self, spec_change_order_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/spec-change-orders/{spec_change_order_id}", None, headers
        )

    def list_spec_change_orders(self, params=None, headers=None):
        return self._request("GET", f"{BASE}/spec-change-orders", params, headers)

    def submit_spec_change_order(
        self, spec_change_order_id: str, headers=None, payload=None
    ):
        return self._request(
            "POST",
            f"{BASE}/spec-change-orders/{spec_change_order_id}/submit",
            payload,
            headers,
        )

    def approve_spec_change_order(
        self, spec_change_order_id: str, headers=None, payload=None
    ):
        return self._request(
            "POST",
            f"{BASE}/spec-change-orders/{spec_change_order_id}/approve",
            payload,
            headers,
        )

    def reject_spec_change_order(
        self, spec_change_order_id: str, headers=None, payload=None
    ):
        return self._request(
            "POST",
            f"{BASE}/spec-change-orders/{spec_change_order_id}/reject",
            payload,
            headers,
        )

    def propagate_spec_change_order(
        self, spec_change_order_id: str, payload=None, headers=None
    ):
        return self._request(
            "POST",
            f"{BASE}/spec-change-orders/{spec_change_order_id}/propagate",
            payload,
            headers,
        )

    def rollback_spec_change_order(
        self, spec_change_order_id: str, headers=None, payload=None
    ):
        return self._request(
            "POST",
            f"{BASE}/spec-change-orders/{spec_change_order_id}/rollback",
            payload,
            headers,
        )

    # ─── menu period reviews ──────────────────────────

    def create_period_review(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/menu-period-reviews", payload, headers)

    def get_period_review(self, period_review_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/menu-period-reviews/{period_review_id}", None, headers
        )

    def list_period_reviews(self, params=None, headers=None):
        return self._request("GET", f"{BASE}/menu-period-reviews", params, headers)

    def add_mix_line(
        self, period_review_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST",
            f"{BASE}/menu-period-reviews/{period_review_id}/mix-lines",
            payload,
            headers,
        )

    def list_mix_lines(self, period_review_id: str, params=None, headers=None):
        return self._request(
            "GET",
            f"{BASE}/menu-period-reviews/{period_review_id}/mix-lines",
            params,
            headers,
        )

    def add_count_line(
        self, period_review_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST",
            f"{BASE}/menu-period-reviews/{period_review_id}/count-lines",
            payload,
            headers,
        )

    def list_count_lines(self, period_review_id: str, params=None, headers=None):
        return self._request(
            "GET",
            f"{BASE}/menu-period-reviews/{period_review_id}/count-lines",
            params,
            headers,
        )

    def classify_period_review(
        self, period_review_id: str, headers=None, payload=None
    ):
        return self._request(
            "POST",
            f"{BASE}/menu-period-reviews/{period_review_id}/classify",
            payload,
            headers,
        )

    def close_period_review(self, period_review_id: str, headers=None, payload=None):
        return self._request(
            "POST",
            f"{BASE}/menu-period-reviews/{period_review_id}/close",
            payload,
            headers,
        )

    # ─── limited-time offer campaigns ─────────────────

    def create_lto_campaign(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/lto-campaigns", payload, headers)

    def get_lto_campaign(self, lto_campaign_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/lto-campaigns/{lto_campaign_id}", None, headers
        )

    def list_lto_campaigns(self, params=None, headers=None):
        return self._request("GET", f"{BASE}/lto-campaigns", params, headers)

    def cost_lto_campaign(self, lto_campaign_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/lto-campaigns/{lto_campaign_id}/cost", payload, headers
        )

    def launch_lto_campaign(self, lto_campaign_id: str, headers=None, payload=None):
        return self._request(
            "POST", f"{BASE}/lto-campaigns/{lto_campaign_id}/launch", payload, headers
        )

    def close_review_lto_campaign(
        self, lto_campaign_id: str, payload=None, headers=None
    ):
        return self._request(
            "POST",
            f"{BASE}/lto-campaigns/{lto_campaign_id}/close-review",
            payload,
            headers,
        )

    def decide_lto_campaign(self, lto_campaign_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{BASE}/lto-campaigns/{lto_campaign_id}/decide", payload, headers
        )
