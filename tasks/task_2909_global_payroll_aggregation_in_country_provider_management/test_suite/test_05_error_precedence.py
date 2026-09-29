"""Requests that violate two rules at once and must report the higher one.

Each pair sets up a request whose lower-ranked rule is also violated, so an
implementation that evaluates the guards in the wrong order returns a plausible
but incorrect error identifier.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BANK_ACCOUNT_NOT_VERIFIED,
    ERR_DATA_RESIDENCY_VIOLATION,
)
from test_helpers.constants import (
    CYCLE_DRAFT,
    CYCLE_RESULTS_APPROVED,
    FUNDING_APPROVED,
    REGION_US,
)
from test_helpers.test_users import OPS_HEADERS, TREASURY_RELEASER_HEADERS


def _unverified_account_over_cap(api):
    """An approved instruction whose destination is unverified and far over its cap."""
    ctx = fx.setup_active_engagement(api)
    ctx = fx.setup_draft_cycle(api, ctx)
    ctx = fx.setup_validated_extract(api, ctx)
    ctx = fx.setup_locked_cycle(api, ctx)
    ctx = fx.setup_scored_run(api, ctx)
    ctx = fx.setup_results_approved_cycle(api, ctx)

    account = fx.create_bank_account(
        api, ctx["engagement_id"], account_ref="DE-ACC-CAP", daily_cap_minor=1000000
    )
    ctx = dict(ctx)
    ctx["bank_account_id"] = account["id"]
    ctx = fx.setup_drafted_funding(api, ctx)
    return fx.setup_approved_funding(api, ctx)


def _late_extract_out_of_region(api):
    """A cycle past its cutoff, fed an extract from a region it never agreed to."""
    ctx = fx.setup_draft_cycle(api)
    fx.set_clock(api, "2026-08-27T00:00:00Z")
    response = api.create_input_file(
        f.input_file_payload(
            ctx["cycle_id"], residency_region_of_transfer=REGION_US
        ),
        OPS_HEADERS,
    )
    return ctx, response


def test_unverified_destination_outranks_the_daily_cap_on_release(api):
    """The account-state guard is reached before the fiscal cap, so the release
    reports the unverified destination and not the exceeded cap.

    PRD 3.6: "The destination account must be in `VERIFIED`; releasing to an account
    still in `PENDING_VERIFICATION` is rejected with `ERR_BANK_ACCOUNT_NOT_VERIFIED`
    (HTTP 409)."

    PRD 2.8: "Where several rules could reject the same request, exactly one error is
    returned: the one belonging to the highest-precedence rule that the request
    violates."

    Design: Difficulty/priority_pair_validation_conflict/funding_release_state_error_precedes_fiscal_cap_error
    """
    ctx = _unverified_account_over_cap(api)

    response = api.release_funding_instruction(
        ctx["funding_id"], TREASURY_RELEASER_HEADERS
    )
    validate_error(response, ERR_BANK_ACCOUNT_NOT_VERIFIED, 409)


def test_refused_release_commits_nothing_anywhere(api):
    """The refusal is total: the instruction keeps its approval, the cycle is still
    only approved and the engagement's treasury commitment is untouched.

    PRD 2.12: "An engagement's `treasury_committed_minor` must always equal the sum
    of `funded_source_minor` over the funding instructions whose cycle belongs to
    that engagement and whose status is `RELEASED`, expressed in whole
    funding-currency minor units with no rounding anywhere in the aggregate."

    Design: Difficulty/priority_pair_validation_conflict/funding_release_state_error_precedes_fiscal_cap_error
    """
    ctx = _unverified_account_over_cap(api)

    api.release_funding_instruction(ctx["funding_id"], TREASURY_RELEASER_HEADERS)

    funding = fx.read_funding(api, ctx["funding_id"])
    assert funding["status"] == FUNDING_APPROVED, (
        f"the instruction is still merely approved, got {funding['status']}"
    )
    a.assert_null_fields(funding, ["releaser_user_id"])

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    a.assert_minor_amount(
        engagement["treasury_committed_minor"], 0, "treasury_committed_minor"
    )


def test_residency_violation_outranks_the_passed_input_cutoff(api):
    """An extract that is both out of region and past the cutoff reports the
    residency violation, which sits higher on the ladder.

    PRD 3.4: "The extract's `residency_region_of_transfer` must equal the
    engagement's contracted residency region, otherwise
    `ERR_DATA_RESIDENCY_VIOLATION` (HTTP 422) — an extract may not be moved into a
    region the country relationship has not agreed to."

    PRD 2.8: "So, for example, a request that both violates residency and names a
    state that forbids the operation reports the residency error, and a request that
    is both unauthorized for its actor and out of temporal window reports the
    authorization error."

    Design: Difficulty/priority_pair_validation_conflict/input_file_residency_error_precedes_cutoff_error
    """
    ctx, response = _late_extract_out_of_region(api)

    validate_error(response, ERR_DATA_RESIDENCY_VIOLATION, 422)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_instant_equals(
        cycle["input_cutoff_at"], "2026-08-26T17:00:00.000Z", "input_cutoff_at"
    )


def test_rejected_extract_is_not_recorded_against_the_cycle(api):
    """Nothing survives the rejection: the cycle keeps its draft state and still has
    no submitter, and its extract collection is empty.

    PRD 3.4: "The submission has one further effect that reaches beyond the extract:
    the acting `X-User-ID` is written onto the cycle as `input_submitter_user_id`,
    replacing whatever was there before."

    Design: Difficulty/priority_pair_validation_conflict/input_file_residency_error_precedes_cutoff_error
    """
    ctx, _ = _late_extract_out_of_region(api)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
    a.assert_null_fields(cycle, ["input_submitter_user_id"])

    extracts, meta = validate_paginated(
        api.list_cycle_input_files(ctx["cycle_id"], OPS_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert extracts == [], f"no extract should have been stored, got {extracts}"
