"""Difficulty queue A — priority_pair_validation_conflict instances."""

from test_helpers import (
    ApiErrorId,
    create_approved_recipient,
    create_consent_payload,
    get_success_data,
    make_admin_headers,
    make_consumer_headers,
    validate_error,
    validate_paginated,
)


def _strict_recipient_on_balance_only_tier(api):
    stack = create_approved_recipient(
        api,
        name="DualFail",
        minimization_policy="STRICT",
        tier_scopes=["BALANCE"],
        rate_class="LOW",
        tier_name="BalOnly",
    )
    return stack["recipient"]


def test_minimization_violation_reported_when_tier_also_fails(api):
    """PRD §3.4: "A requested scope that is both forbidden by policy and
    absent from the tier surfaces as `ERR_SCOPE_VIOLATES_MINIMIZATION`,
    because the minimization check is evaluated first."

    Design: Difficulty/priority_pair_validation_conflict/conflict_safety_minimization_beats_constraint_tier
    """
    recipient = _strict_recipient_on_balance_only_tier(api)

    resp = api.create_consent(
        recipient["id"],
        create_consent_payload(
            consumer_ref="cons_i",
            data_scopes=["ASSETS"],
            expected_recipient_version=recipient["version"],
        ),
        make_consumer_headers("cons_i"),
    )
    error = validate_error(resp, ApiErrorId.ERR_SCOPE_VIOLATES_MINIMIZATION)
    assert error["error_id"] != ApiErrorId.ERR_SCOPE_EXCEEDS_TIER, (
        "tier coverage must not mask the earlier minimization failure"
    )


def test_minimization_conflict_persists_no_consent(api):
    """PRD §3.2: "`STRICT` forbids the `IDENTITY`, `INCOME`, and `ASSETS`
    scopes outright."
    PRD §3.4: "Second, tier coverage: every requested scope must appear in the
    `scopes_included` of the recipient's currently `ACTIVE` tier assignment;
    any scope the tier does not cover is rejected with
    `ERR_SCOPE_EXCEEDS_TIER`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_safety_minimization_beats_constraint_tier
    """
    recipient = _strict_recipient_on_balance_only_tier(api)
    admin = make_admin_headers()

    resp = api.create_consent(
        recipient["id"],
        create_consent_payload(
            consumer_ref="cons_i",
            data_scopes=["ASSETS"],
            expected_recipient_version=recipient["version"],
        ),
        make_consumer_headers("cons_i"),
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_VIOLATES_MINIMIZATION)

    consents, meta = validate_paginated(api.list_recipient_consents(recipient["id"], admin))
    assert meta["total_count"] == 0, "a rejected capture must not persist any consent"
