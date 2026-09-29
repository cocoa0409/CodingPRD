"""Endpoint behaviour: creations, action endpoints, filtered bulk actions and
computed nested reads.

The accounts sub-resource round-trips through its status filter, the verify
action is the only door into `VERIFIED`, the filing sweep touches nothing that is
not yet due, release-hold is conditional on the cause it was raised for, and the
cycle's evidence list is a computed read of what the workflow minted.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CYCLE_ENGAGEMENT_MISMATCH, ERR_HOLD_CAUSE_ACTIVE
from test_helpers.constants import (
    BANK_ACCOUNT_PENDING_VERIFICATION,
    BANK_ACCOUNT_VERIFIED,
    CTRL_FUNDING_DUAL_AUTH,
    CTRL_INPUT_INTEGRITY,
    CTRL_VARIANCE_REVIEW,
    CYCLE_DRAFT,
    CYCLE_FUNDED,
    CYCLE_ON_HOLD,
    ENGAGEMENT_ACTIVE,
    EVIDENCE_TYPE_SYSTEM_ATTESTATION,
    FILING_PENDING,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    HOLD_REASON_PROVIDER_PROBATION,
    PENALTY_NONE,
    PROVIDER_ACTIVE,
    PROVIDER_PROBATION,
    REGION_EU,
    SEV1,
    SEV2,
    SYSTEM_RECORDED_BY_ROLE,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_HEADERS,
    OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)

_SINGLE_FILING_COUNTRY = {"required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING]}
_BEFORE_DUE_CLOCK = "2026-09-05T10:00:00Z"


def _accounts_with_status(api, engagement_id, status):
    return validate_paginated(
        api.list_engagement_bank_accounts(
            engagement_id, PLATFORM_ADMIN_HEADERS, {"status": status}
        )
    )


def test_bank_account_creation_round_trips_through_the_status_filter(api):
    """The created account carries every registered term and opens awaiting
    verification, and the engagement-scoped list finds it under that status only.

    PRD 3.1: "Each account carries an `account_ref` of 1 to 40 characters that must be
    unique within its engagement — reusing a reference within the same engagement is
    rejected with `ERR_DUPLICATE_ACCOUNT_REF` (HTTP 409) — together with
    `account_currency`, exactly three uppercase letters, and `residency_region`, one of
    the five regions."

    PRD 3.1: "A newly registered account opens in `status` `PENDING_VERIFICATION`, and
    no funding may be released from it in that state."

    PRD 3.1: "The accounts of one engagement are readable as a nested sub-resource
    list, optionally narrowed by `status`."

    Design: Corner/endpoints/bank_account_create_then_list_round_trip
    """
    ctx = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.create_bank_account(
        f.bank_account_payload(ctx["engagement_id"]), PLATFORM_ADMIN_HEADERS
    )

    account = validate_success(response, 201)
    a.assert_field_values(
        account,
        {
            "status": BANK_ACCOUNT_PENDING_VERIFICATION,
            "account_ref": "DE-ACC-1",
            "account_currency": "EUR",
            "residency_region": REGION_EU,
            "settlement_window_hours": 24,
            "buffer_hours": 12,
        },
    )
    a.assert_minor_amount(account["daily_cap_minor"], 20000000, "daily_cap_minor")

    pending, pending_meta = _accounts_with_status(
        api, ctx["engagement_id"], BANK_ACCOUNT_PENDING_VERIFICATION
    )
    a.assert_pagination_meta(pending_meta, expected_total=1, expected_has_more=False)
    assert [row["id"] for row in pending] == [account["id"]], (
        f"the filter finds exactly the new account, got {pending}"
    )

    verified, verified_meta = _accounts_with_status(
        api, ctx["engagement_id"], BANK_ACCOUNT_VERIFIED
    )
    a.assert_pagination_meta(verified_meta, expected_total=0, expected_has_more=False)
    assert verified == [], f"nothing is verified yet, got {verified}"


def test_verify_action_moves_the_account_to_verified(api):
    """Verification is an action endpoint, and it is the only route to `VERIFIED`; the
    write bumps the version and the status filter follows the account across.

    PRD 3.1: "Bank verification is a separate `PlatformAdmin` act that moves the
    account `PENDING_VERIFICATION → VERIFIED` and changes nothing else."

    PRD 2.4: "and `version`, an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of that row."

    Design: Corner/endpoints/bank_account_verify_moves_pending_verification_to_verified
    """
    ctx = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)
    account = fx.create_bank_account(api, ctx["engagement_id"])
    assert account["status"] == BANK_ACCOUNT_PENDING_VERIFICATION, (
        f"the account opens unverified, got {account['status']}"
    )

    verified = validate_success(
        api.verify_bank_account(account["id"], PLATFORM_ADMIN_HEADERS)
    )

    assert verified["status"] == BANK_ACCOUNT_VERIFIED, (
        f"the action moves the account to VERIFIED, got {verified['status']}"
    )
    a.assert_common_fields(verified, expected_version=2)

    rows, meta = _accounts_with_status(
        api, ctx["engagement_id"], BANK_ACCOUNT_VERIFIED
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    assert rows[0]["id"] == account["id"], (
        f"the verified account is the same row, got {rows[0]}"
    )


def test_filing_sweep_before_the_deadline_changes_nothing(api):
    """The sweep is filtered, not blanket: run five days before the shared deadline it
    leaves both obligations pending, unpenalized and uncounted against the provider.

    PRD 3.7: "The sweep examines every filing of the cycle still in `PENDING` and, for
    each whose `due_at` now lies before the current logical clock, moves it `PENDING →
    LATE` and assesses the penalty."

    PRD 3.7: "Finally, every provider-responsible filing that went late also raises a
    service-level incident for the cycle's engagement with `incident_type`
    `FILING_MISS`, `severity` `SEV2` and `status` `OPEN`"

    Design: Corner/endpoints/filing_sweep_before_the_due_instant_returns_an_empty_result
    """
    ctx = fx.setup_results_approved_cycle(api)
    fx.set_clock(api, _BEFORE_DUE_CLOCK)

    validate_success(api.filing_sweep(ctx["cycle_id"], CONTROLLER_HEADERS))

    filings = fx.filings_of_cycle(api, ctx["cycle_id"])
    assert len(filings) == 2, f"the country minted two obligations, got {len(filings)}"
    for filing in filings:
        assert filing["status"] == FILING_PENDING, (
            f"a filing that is not yet due stays PENDING, got {filing['status']}"
        )
        assert filing["penalty_status"] == PENALTY_NONE, (
            f"no penalty is assessed, got {filing['penalty_status']}"
        )
        assert filing["late_days"] == 0, (
            f"nothing is late, got {filing['late_days']}"
        )

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == 2, (
        "both obligations are still live, got "
        f"{country['open_filing_obligation_count']}"
    )
    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_ACTIVE, service_score=100.00, open_penalty_minor=0
    )

    incidents, meta = validate_paginated(
        api.list_incidents(CONTROLLER_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert incidents == [], f"no filing miss was raised, got {incidents}"


def test_release_hold_is_refused_while_the_probation_persists(api):
    """The hold may only be lifted once its cause is gone: while the provider is still
    on probation the call is refused, and once both findings are remediated it carries.

    PRD 3.3: "a held cycle stays held until `GlobalPayrollOps` or a `PayrollController`
    explicitly releases it, which moves the cycle `ON_HOLD → DRAFT` and clears
    `hold_reason` back to null."

    PRD 3.3: "That release is only permitted while both causes of the hold are healthy
    again — the engaged provider must be back to `ACTIVE` and the engagement must be
    back to `ACTIVE` — and an attempt made while either is still unhealthy is rejected
    with `ERR_HOLD_CAUSE_ACTIVE` (HTTP 409)."

    Design: Corner/endpoints/release_hold_is_rejected_while_the_provider_is_still_on_probation
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    first = fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    second = fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_PROBATION, service_score=50.00
    )

    response = api.release_hold(ctx["cycle_id"], OPS_HEADERS)
    validate_error(response, ERR_HOLD_CAUSE_ACTIVE, 409)
    a.assert_cycle_state(
        fx.read_cycle(api, ctx["cycle_id"]),
        CYCLE_ON_HOLD,
        HOLD_REASON_PROVIDER_PROBATION,
    )

    fx.remediate_incident(api, first["id"])
    fx.remediate_incident(api, second["id"], remediation_ref="REM-0002")
    recovered = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        recovered, status=PROVIDER_ACTIVE, service_score=100.00, open_penalty_minor=0
    )
    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_ACTIVE, (
        f"remediation returns the engagement to ACTIVE, got {engagement['status']}"
    )

    released = validate_success(api.release_hold(ctx["cycle_id"], OPS_HEADERS))
    a.assert_cycle_state(released, CYCLE_DRAFT)


def test_audit_evidence_read_returns_the_system_controls_in_mint_order(api):
    """Driving one period to funded mints exactly three system controls, and the read
    returns them in mint order with the control filter narrowing to one.

    PRD 3.9: "Finally each item carries `sequence_no`, a 1-based append position within
    its cycle assigned in ascending `created_at` order, so the evidence file reads as a
    chronological narrative."

    PRD 3.9: "Four of the five controls are minted by the system at the moment the
    control is actually exercised: `CTRL_INPUT_INTEGRITY` when an HR extract first
    validates for the cycle, `CTRL_VARIANCE_REVIEW` when the gross-to-net results are
    approved, `CTRL_FUNDING_DUAL_AUTH` when funding is released under two distinct
    treasury signatures, and `CTRL_FILING_CONFIRMATION` when the last non-`VOIDED`
    filing of the cycle is confirmed."

    Design: Corner/endpoints/audit_evidence_read_returns_the_system_minted_controls_in_sequence
    """
    ctx = fx.setup_funded_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)

    items, meta = validate_paginated(
        api.list_cycle_audit_evidence(
            ctx["cycle_id"], AUDITOR_HEADERS, f.pagination_params(limit=10, offset=0)
        )
    )

    a.assert_pagination_meta(meta, expected_total=3, expected_has_more=False)
    assert [item["sequence_no"] for item in items] == [1, 2, 3], (
        f"the positions are 1, 2 and 3, got {[i['sequence_no'] for i in items]}"
    )
    assert [item["control_ref"] for item in items] == [
        CTRL_INPUT_INTEGRITY,
        CTRL_VARIANCE_REVIEW,
        CTRL_FUNDING_DUAL_AUTH,
    ], f"the controls are in mint order, got {[i['control_ref'] for i in items]}"
    for item in items:
        assert item["recorded_by_role"] == SYSTEM_RECORDED_BY_ROLE, (
            f"a system control is recorded by SYSTEM, got {item['recorded_by_role']}"
        )
        assert item["evidence_type"] == EVIDENCE_TYPE_SYSTEM_ATTESTATION, (
            f"expected a system attestation, got {item['evidence_type']}"
        )

    narrowed, narrowed_meta = validate_paginated(
        api.list_cycle_audit_evidence(
            ctx["cycle_id"], AUDITOR_HEADERS, {"control_ref": CTRL_FUNDING_DUAL_AUTH}
        )
    )
    a.assert_pagination_meta(narrowed_meta, expected_total=1, expected_has_more=False)
    assert narrowed[0]["control_ref"] == CTRL_FUNDING_DUAL_AUTH, (
        f"the filter narrows to the release control, got {narrowed[0]}"
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_FUNDED)
    a.assert_minor_amount(cycle["funded_total_minor"], 9543206, "funded_total_minor")


def test_incident_naming_a_cycle_of_another_engagement_is_refused(api):
    """Both referenced rows exist, but the optional cycle belongs to the other
    country's engagement, so the link is refused and nothing is recorded.

    PRD 3.8: "and when `cycle_id` is supplied it must name a cycle of the same
    engagement, otherwise `ERR_CYCLE_ENGAGEMENT_MISMATCH` (HTTP 422)."

    Design: Corner/endpoints/incident_naming_a_cycle_of_another_engagement_is_rejected
    """
    german = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)
    french_country = fx.create_country(
        api, country_code="FR", **_SINGLE_FILING_COUNTRY
    )
    french_engagement = fx.create_engagement(
        api, french_country["id"], german["provider_id"]
    )
    fx.approve_residency(api, french_engagement["id"], "DPA-FR-2026-01")
    french_cycle = fx.create_cycle(api, french_engagement["id"])

    response = api.create_incident(
        f.incident_payload(
            german["engagement_id"],
            SEV2,
            cycle_id=french_cycle["id"],
            note="raised against the wrong country cycle",
        ),
        OPS_HEADERS,
    )
    validate_error(response, ERR_CYCLE_ENGAGEMENT_MISMATCH, 422)

    incidents, meta = validate_paginated(api.list_incidents(CONTROLLER_HEADERS))
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert incidents == [], f"no incident was recorded, got {incidents}"

    provider = fx.read_provider(api, german["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_ACTIVE, service_score=100.00
    )
