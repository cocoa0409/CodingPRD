"""The two version guards, and what a refused write leaves behind.

Both guarded endpoints take an absolute overwrite rather than a delta, so each
one refuses a body prepared against a version some other write has moved past.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents
from test_helpers.constants import (
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIM_HANDLING_SETUP,
    CLAIMANT_TYPE_PROPERTY,
    EVIDENCE_TELEMATICS,
    RESERVE_BASIS_PROVISIONAL_REFRESH,
    RESERVE_STATUS_PROVISIONAL,
    RESERVE_STATUS_REVISED,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    AUDITOR,
    CLAIMS_ADJUSTER,
    COMMITTEE_ONE,
    COMMITTEE_TWO,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_driver,
    build_preserved_evidence,
    build_review_case,
    build_statement,
    build_terminal,
    open_deliberation,
)

PAINESVILLE_MILES = 2.0
MINOR_PROVISIONAL_RESERVE_CENTS = 500_000
PROPERTY_DEMAND_CENTS = 400_000


def _case_in_deliberation_and_a_fresh_claim(api: ApiClient) -> dict:
    """One minor crash carrying both a review case and a claim at once."""
    terminal = build_terminal(
        api,
        name="Painesville Terminal",
        terminal_code="PAI03",
        region_code="OH",
        annual_miles_millions=PAINESVILLE_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6501",
        full_name="Nuno Alcantara",
        cdl_number="OH-CDL-6501",
        hire_date="2014-07-07",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-25T16:00:00Z",
        notified_at="2026-07-25T16:10:00Z",
        location_text="SR-2 at the marina exit",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    build_preserved_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-6501",
        window_start_at="2026-07-25T15:00:00Z",
        window_end_at="2026-07-25T17:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="The boat trailer ahead of me jackknifed.",
        conditions_note=None,
    )
    created_case = build_review_case(
        api, crash["id"], committee_name="Painesville Safety Review Committee"
    )
    opened_case = open_deliberation(api, created_case["id"])
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-26")
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "created_case": created_case,
        "review_case": opened_case,
        "claim": claim,
    }


class TestBothVersionGuardsRefuseAStaleWrite:
    """A refused write mints nothing, and the same body succeeds on a re-read."""

    def test_a_ballot_quoting_an_overtaken_case_version_is_refused(
        self, api: ApiClient
    ):
        """No ballot row, no sequence number, and no version movement.

        PRD: "A mismatch against the case's current `version` is rejected with
        `ERR_REVIEW_CASE_VERSION_STALE` (HTTP 412); no ballot row is created and
        neither `next_vote_sequence` nor `version` moves."

        Design: Corner/complexity_layers/stale_expected_version_is_refused_on_both_occ_write_endpoints
        """
        context = _case_in_deliberation_and_a_fresh_claim(api)
        opened = context["review_case"]
        assert opened["version"] > context["created_case"]["version"]

        first = validate_success(
            api.cast_vote(
                opened["id"],
                factories.vote_payload(
                    opened["version"],
                    vote=BALLOT_DISPOSITION_PREVENTABLE,
                    scores=factories.uniform_criterion_scores(3),
                ),
                COMMITTEE_ONE,
            ),
            201,
        )
        assert first["version"] == opened["version"] + 1
        assert first["next_vote_sequence"] == opened["next_vote_sequence"] + 1

        validate_error(
            api.cast_vote(
                opened["id"],
                factories.vote_payload(
                    opened["version"],
                    vote=BALLOT_DISPOSITION_NON_PREVENTABLE,
                    scores=factories.uniform_criterion_scores(1),
                ),
                COMMITTEE_TWO,
            ),
            ApiErrorId.REVIEW_CASE_VERSION_STALE.value,
            412,
        )

        after = validate_success(api.get_review_case(opened["id"], SAFETY_MANAGER))
        assert after["version"] == first["version"]
        assert after["next_vote_sequence"] == first["next_vote_sequence"]
        assert after["active_vote_count"] == 1

        rows, meta = validate_paginated(
            api.list_votes(opened["id"], AUDITOR, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

        retried = validate_success(
            api.cast_vote(
                opened["id"],
                factories.vote_payload(
                    after["version"],
                    vote=BALLOT_DISPOSITION_NON_PREVENTABLE,
                    scores=factories.uniform_criterion_scores(1),
                ),
                COMMITTEE_TWO,
            ),
            201,
        )
        assert retried["version"] == first["version"] + 1

    def test_a_replayed_claim_version_leaves_the_whole_reserve_untouched(
        self, api: ApiClient
    ):
        """The refusal is safe to retry precisely because nothing moved.

        PRD: "If the supplied value does not equal the claim's current `version`, the
        revision is rejected with `ERR_CLAIM_VERSION_STALE` (HTTP 412), and
        `revised_reserve_cents`, `outstanding_reserve_cents`, `reserve_status` and
        `version` are all left exactly as they were."

        Design: Corner/complexity_layers/stale_expected_version_is_refused_on_both_occ_write_endpoints
        """
        context = _case_in_deliberation_and_a_fresh_claim(api)
        claim = context["claim"]
        assert claim["reserve_status"] == RESERVE_STATUS_PROVISIONAL
        assert claim["handling_status"] == CLAIM_HANDLING_SETUP
        assert_cents(
            claim["provisional_reserve_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )

        revised = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"],
                    basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
                    revision_note="first refresh at the intake multiplier",
                ),
                CLAIMS_ADJUSTER,
            )
        )
        assert revised["version"] == claim["version"] + 1
        assert revised["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(
            revised["revised_reserve_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "revised_reserve_cents",
        )
        assert_cents(
            revised["outstanding_reserve_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )

        validate_error(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"],
                    basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
                    revision_note="prepared from a stale read",
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.CLAIM_VERSION_STALE.value,
            412,
        )

        after = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert after["version"] == revised["version"]
        assert after["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(
            after["revised_reserve_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "revised_reserve_cents",
        )
        assert_cents(
            after["outstanding_reserve_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )

    def test_an_unrelated_write_on_the_claim_makes_a_prepared_revision_stale(
        self, api: ApiClient
    ):
        """The guard is a version guard, not a same-endpoint guard.

        PRD: "Note that settlements, rescissions, counsel assignment, demand creation
        and every cascade that touches the claim also advance `Claim.version`, so a
        revision prepared before any of those has become stale as well."

        Design: Corner/complexity_layers/stale_expected_version_is_refused_on_both_occ_write_endpoints
        """
        context = _case_in_deliberation_and_a_fresh_claim(api)
        claim = context["claim"]
        revised = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"],
                    basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
                    revision_note="first refresh at the intake multiplier",
                ),
                CLAIMS_ADJUSTER,
            )
        )

        validate_success(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Orsolya Balogh",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=PROPERTY_DEMAND_CENTS,
                    represented_by_counsel=False,
                    demand_received_at="2026-07-27T00:00:00Z",
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )

        validate_error(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    revised["version"],
                    basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
                    revision_note="prepared before the demand landed",
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.CLAIM_VERSION_STALE.value,
            412,
        )

        after_demand = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert after_demand["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert after_demand["version"] == revised["version"] + 1

        refreshed = validate_success(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    after_demand["version"],
                    basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
                    revision_note="re-read after the demand",
                ),
                CLAIMS_ADJUSTER,
            )
        )
        assert refreshed["version"] == after_demand["version"] + 1
        assert_cents(
            refreshed["revised_reserve_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "revised_reserve_cents",
        )
