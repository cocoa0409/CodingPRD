"""Corner — consistency model: immediate visibility after accept.

Design: Corner/consistency_model
"""
from test_helpers import (
    TEST_USERS, create_offer_payload, get_success_data, setup_film,
    setup_territory, validate_paginated, validate_success,
)

ACQ = TEST_USERS["acq_exec_headers"]
ACQ2 = TEST_USERS["acq_exec_2_headers"]


class TestImmediateConsistencyOnAccept:
    def test_immediate_consistency_on_accept(self, api):
        """PRD §3.3: "The deal's three derived spend fields —
        `pa_spent_theatrical_cents`, `pa_spent_awards_cents`, and
        `pa_shortfall_cents` — begin at zero."
        PRD §3.7: "`pa_shortfall_cents` is recomputed as the greater of zero
        and the difference between `prints_advertising_commit_cents` and the
        sum of `pa_spent_theatrical_cents` plus `pa_spent_awards_cents`."
        PRD §3.3: "For each pair in the Cartesian product of the offer's
        `requested_territory_codes` and `requested_windows`, a `RightsGrant`
        is created on the deal in `GRANTED` status."

        Design: Corner/consistency_model/immediate_consistency_on_accept
        """
        setup_territory(code="US")
        film = setup_film()
        offer = get_success_data(api.create_offer(
            film["id"],
            create_offer_payload(prints_advertising_commit_cents=5_000_000),
            ACQ2,
        ))
        film_now = get_success_data(api.get_film(film["id"], ACQ))
        deal = validate_success(api.accept_offer(
            film["id"], offer["id"],
            {"expected_film_version": film_now["version"]}, ACQ,
        ), expected_status=201)

        # Derived fields are populated on the accept response itself
        assert deal["pa_spent_theatrical_cents"] == 0
        assert deal["pa_spent_awards_cents"] == 0
        # max(0, 5,000,000 - (0 + 0)) = 5,000,000
        assert deal["pa_shortfall_cents"] == 5_000_000

        # Rights grants are visible immediately — no async reconciliation
        grants, meta = validate_paginated(
            api.list_deal_rights_grants(deal["id"], ACQ)
        )
        assert len(grants) == 1
        assert grants[0]["territory_code"] == "US"
        assert grants[0]["window"] == "THEATRICAL"
        assert grants[0]["status"] == "GRANTED"
