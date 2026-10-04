"""The create endpoints' declared required fields and computed-field discipline.

The PRD gives the implementer only two anchors for "a required field was
omitted" and "a computed field was supplied":

  - PRD §3.1/§3.3/§3.5 name the fields each creation call must carry, so
    omitting one leaves the book the settlement divides undefined.
  - PRD §2.5 states that a computed field is "a mutation" the server performs,
    which is why a client-supplied value for one is discarded rather than stored.

Both are weaker than the design index's phrasing, so these tests are kept
deliberately narrow: they assert the error family and the resulting state, never
the exact identifier the two PRD readings could differ on.
"""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, ADMIN, set_clock, create_franchisee, create_store, create_agreement,
    setup_store_with_agreement, refresh_store,
)

# The status codes the PRD fixes for the two families these tests exercise.
REQUIRED_FIELD_STATUSES = (400, 409)
UNKNOWN_FIELD_STATUSES = (201, 400)


class TestSettlementCreateTrailingAverage:
    """The trailing average is a named input of the opening call."""

    def test_opening_a_settlement_without_the_trailing_average_does_not_persist_one(self):
        """PRD §3.3: "A settlement is one store's week. The back office opens it
        by naming the `store_id` and the `franchisee_id`, and by bounding the
        week with an inclusive `period_start` and an exclusive `period_end`."
        PRD §3.3: "`provisional_gross_profit_cents` — the figure the provisional
        variant divides — is the settlement's `trailing_avg_gross_profit_cents`,
        the operator's trailing four-week average, plus `rebate_credit_cents`".

        Design: Corner/entities/settlement_create_missing_trailing_average_returns_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T00:00:00Z")
        store_id = context["store"]["id"]
        version_before = refresh_store(store_id)["version"]

        # The payload named by §3.3 carries no trailing average at all.
        response = api_client.create_settlement({
            "store_id": store_id,
            "franchisee_id": context["franchisee"]["id"],
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2026-09-08T00:00:00Z",
            "expected_store_version": version_before,
        }, ADMIN)

        assert response.status_code in REQUIRED_FIELD_STATUSES, (
            "an opening call that leaves the provisional base undefined must not succeed"
        )
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"].startswith("ERR_")

        listed, meta = validate_paginated(
            api_client.list_settlements(ADMIN, {"store_id": store_id}))
        assert meta["total_count"] == 0
        assert refresh_store(store_id)["version"] == version_before


class TestComputedFieldsAreNotClientInput:
    """A computed field is a server-side mutation, never an accepted input."""

    def test_supplying_the_computed_split_fields_on_create_does_not_store_them(self):
        """PRD §2.5: "Any derived or computed field on a resource is likewise a
        mutation: recomputing it updates `updated_at` and increments `version` on
        the resource that holds it."
        PRD §3.4: "The `provisional` flag flips to false at this moment and the
        net settlement is frozen; from here the split variant in force is the
        final variant".

        Design: Corner/entities/settlement_create_computed_split_fields_are_ignored_input
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T00:00:00Z")
        store_id = context["store"]["id"]
        version = refresh_store(store_id)["version"]

        response = api_client.create_settlement({
            "store_id": store_id,
            "franchisee_id": context["franchisee"]["id"],
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2026-09-08T00:00:00Z",
            "trailing_avg_gross_profit_cents": 1_000_000,
            "expected_store_version": version,
            # Computed fields a client has no business supplying.
            "gross_profit_cents": 99_999_999,
            "franchisee_split_cents": 88_888_888,
        }, ADMIN)

        assert response.status_code in UNKNOWN_FIELD_STATUSES, (
            "supplying a computed field is either refused or discarded, never stored"
        )
        if response.status_code == 400:
            body = response.json()
            assert body["response_type"] == "error"
            return

        settlement = validate_success(response, 201)
        assert settlement["status"] == "OPEN"
        assert settlement["provisional"] is True
        assert settlement["gross_profit_cents"] == 0
        assert settlement["franchisee_split_cents"] == 0
        assert settlement["gross_profit_cents"] != 99_999_999
        assert settlement["franchisee_split_cents"] != 88_888_888
        # Only the server's own recomputations ever write those fields.
        assert settlement["version"] == 1