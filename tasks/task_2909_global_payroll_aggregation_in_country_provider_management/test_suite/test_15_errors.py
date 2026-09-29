"""Declared failure modes: the guard that fires, the status it carries, and the
absence of any side effect behind it.

Authentication before authorization before existence, a role that is not on the
endpoint's list, the two guards on hand-recorded audit evidence, a strict
temporal comparison, an empty extract, incoherent run totals and an account in
the wrong currency.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CURRENCY_MISMATCH,
    ERR_DUPLICATE_EVIDENCE_CONTROL,
    ERR_EMPTY_INPUT_FILE,
    ERR_GTN_TOTALS_INCONSISTENT,
    ERR_INCIDENT_FUTURE_DATED,
    ERR_MANUAL_CONTROL_NOT_ALLOWED,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    CTRL_INPUT_INTEGRITY,
    CTRL_RESIDENCY_ATTESTATION,
    CYCLE_DRAFT,
    CYCLE_INPUTS_LOCKED,
    EVIDENCE_TYPE_DOCUMENT_HASH,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    INCIDENT_OPEN,
    INPUT_FILE_VALIDATED,
    PROVIDER_ACTIVE,
    ROLE_GLOBAL_PAYROLL_OPS,
    SEV2,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_HEADERS,
    OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    headers_with_empty_user_id,
)

_SINGLE_FILING_COUNTRY = {"required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING]}
_UNKNOWN_PROVIDER_ID = "33333333-3333-4333-8333-333333333333"
_SYSTEM_CONTROL_HASH = "0011223344556677"
_ATTESTATION_HASH = "aaaabbbbccccdddd"
_INCIDENT_CLOCK = "2026-08-01T00:00:00Z"
_ONE_MS_AHEAD_OF_THE_CLOCK = "2026-08-01T00:00:00.001Z"


def test_request_with_an_empty_user_id_header_is_unauthenticated(api):
    """The role header is present and authorized, but the acting principal is the empty
    string, so the request never reaches the resource it names.

    PRD 2.1: "Every request to every endpoint, including read-only ones, must carry two
    headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming
    the role that principal is acting under. If either header is absent or empty, the
    request fails with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing
    occurs."

    PRD 2.1: "Authentication is checked before authorization, and both are checked
    before the existence of any referenced resource."

    Design: Corner/errors/request_missing_x_user_id_header_returns_unauthenticated
    """
    provider = fx.create_provider(api)
    anonymous = headers_with_empty_user_id(ROLE_GLOBAL_PAYROLL_OPS)

    response = api.get_provider(provider["id"], anonymous)
    validate_error(response, ERR_UNAUTHENTICATED, 401)

    unknown = api.get_provider(_UNKNOWN_PROVIDER_ID, anonymous)
    validate_error(unknown, ERR_UNAUTHENTICATED, 401)

    identified = validate_success(api.get_provider(provider["id"], OPS_HEADERS))
    assert identified["id"] == provider["id"], (
        f"an identified principal reads the same row, got {identified}"
    )
    a.assert_provider_standing(
        identified, status=PROVIDER_ACTIVE, service_score=100.00, open_penalty_minor=0
    )


def test_platform_admin_may_not_lock_the_cycle_inputs(api):
    """Every business precondition of the lock is met, but `PlatformAdmin` is not on the
    endpoint's role list, so nothing is locked and no obligation is minted.

    PRD 2.1: "If both headers are present but the named role is not authorized for the
    endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 3.4: "**Locking inputs** is the act that ends the input phase, and only
    `GlobalPayrollOps` may perform it."

    Design: Corner/errors/platform_admin_cannot_lock_cycle_inputs
    """
    ctx = fx.setup_validated_extract(api, country_overrides=_SINGLE_FILING_COUNTRY)
    assert ctx["input_file"]["status"] == INPUT_FILE_VALIDATED, (
        f"the cycle carries a validated extract, got {ctx['input_file']['status']}"
    )

    response = api.lock_inputs(ctx["cycle_id"], PLATFORM_ADMIN_HEADERS)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
    filings, meta = validate_paginated(
        api.list_filings(OPS_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert filings == [], f"no obligation was minted, got {filings}"

    locked = validate_success(api.lock_inputs(ctx["cycle_id"], OPS_HEADERS))
    a.assert_cycle_state(locked, CYCLE_INPUTS_LOCKED)


def test_hand_recording_a_system_minted_control_is_refused(api):
    """The auditor is the right role and the cycle is open, but the control named is one
    the system mints for itself, so the attestation is refused.

    PRD 3.9: "The `control_ref` must be `CTRL_RESIDENCY_ATTESTATION`; every other
    control is the system's to mint, and naming one manually is rejected with
    `ERR_MANUAL_CONTROL_NOT_ALLOWED` (HTTP 422)."

    PRD 3.9: "Only `CTRL_RESIDENCY_ATTESTATION` is recorded by hand, and only a
    `ComplianceAuditor` may record it."

    Design: Corner/errors/audit_evidence_for_a_system_minted_control_is_rejected
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.create_audit_evidence(
        f.audit_evidence_payload(
            ctx["cycle_id"],
            CTRL_INPUT_INTEGRITY,
            evidence_type=EVIDENCE_TYPE_DOCUMENT_HASH,
            payload_hash=_SYSTEM_CONTROL_HASH,
        ),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_MANUAL_CONTROL_NOT_ALLOWED, 422)

    items, meta = validate_paginated(
        api.list_cycle_audit_evidence(ctx["cycle_id"], AUDITOR_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert items == [], f"the refused attestation recorded nothing, got {items}"
    a.assert_cycle_state(fx.read_cycle(api, ctx["cycle_id"]), CYCLE_DRAFT)


def test_second_attestation_for_the_same_control_is_refused(api):
    """The first residency attestation is accepted; a second one for the same cycle is
    a duplicate of an already-evidenced control and leaves the first item untouched.

    PRD 3.9: "And the control must not already be evidenced for that cycle, otherwise
    `ERR_DUPLICATE_EVIDENCE_CONTROL` (HTTP 409)."

    PRD 3.9: "Finally each item carries `sequence_no`, a 1-based append position within
    its cycle assigned in ascending `created_at` order, so the evidence file reads as a
    chronological narrative."

    Design: Corner/errors/duplicate_evidence_control_ref_on_one_cycle_is_rejected
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    first = fx.record_evidence(api, ctx["cycle_id"], CTRL_RESIDENCY_ATTESTATION)
    assert first["sequence_no"] == 1, (
        f"the first item sits at position 1, got {first['sequence_no']}"
    )

    response = api.create_audit_evidence(
        f.audit_evidence_payload(
            ctx["cycle_id"],
            CTRL_RESIDENCY_ATTESTATION,
            evidence_type=EVIDENCE_TYPE_DOCUMENT_HASH,
            payload_hash=_SYSTEM_CONTROL_HASH,
        ),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_EVIDENCE_CONTROL, 409)

    items, meta = validate_paginated(
        api.list_cycle_audit_evidence(ctx["cycle_id"], AUDITOR_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    a.assert_field_values(
        items[0],
        {
            "id": first["id"],
            "control_ref": CTRL_RESIDENCY_ATTESTATION,
            "payload_hash": _ATTESTATION_HASH,
            "sequence_no": 1,
        },
    )
    a.assert_append_only_fields(items[0])


def test_future_dated_incident_is_refused_while_the_clock_instant_itself_is_accepted(api):
    """One millisecond after the logical clock is strictly in the future and refused;
    the very same report at exactly the clock instant is accepted.

    PRD 3.8: "Two guards apply in order: `occurred_at` must not be strictly after the
    current logical clock, and a future-dated incident is rejected with
    `ERR_INCIDENT_FUTURE_DATED` (HTTP 422)"

    Design: Corner/errors/future_dated_incident_is_rejected
    """
    ctx = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)
    fx.set_clock(api, _INCIDENT_CLOCK)

    response = api.create_incident(
        f.incident_payload(
            ctx["engagement_id"], SEV2, occurred_at=_ONE_MS_AHEAD_OF_THE_CLOCK
        ),
        OPS_HEADERS,
    )
    validate_error(response, ERR_INCIDENT_FUTURE_DATED, 422)

    incidents, meta = validate_paginated(
        api.list_incidents(CONTROLLER_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert incidents == [], f"nothing was recorded, got {incidents}"
    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_ACTIVE, service_score=100.00, open_penalty_minor=0
    )

    accepted = validate_success(
        api.create_incident(
            f.incident_payload(ctx["engagement_id"], SEV2, occurred_at=_INCIDENT_CLOCK),
            OPS_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == INCIDENT_OPEN, (
        f"a raised incident opens in OPEN, got {accepted['status']}"
    )
    a.assert_instant_equals(
        accepted["occurred_at"], "2026-08-01T00:00:00.000Z", "occurred_at"
    )


def test_extract_describing_no_employee_records_is_refused(api):
    """An extract of zero records passes every residency, state and cutoff check and
    then fails the emptiness check, so the cycle records neither extract nor submitter.

    PRD 3.4: "And a `record_count` of zero is rejected with `ERR_EMPTY_INPUT_FILE`
    (HTTP 422); any accepted extract describes at least one employee record."

    Design: Corner/errors/empty_input_file_is_rejected
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.create_input_file(
        f.input_file_payload(ctx["cycle_id"], record_count=0),
        OPS_HEADERS,
    )
    validate_error(response, ERR_EMPTY_INPUT_FILE, 422)

    extracts, meta = validate_paginated(
        api.list_cycle_input_files(ctx["cycle_id"], OPS_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert extracts == [], f"nothing was stored, got {extracts}"

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
    a.assert_null_fields(cycle, ["input_submitter_user_id"])


def test_run_whose_net_exceeds_its_gross_is_refused(api):
    """The gross matches the declared gross exactly, so the tolerance check passes and
    the coherence check is the one that reports; no run is persisted.

    PRD 3.5: "And last, the internal coherence constraint: `net_minor` must not be
    greater than `gross_minor`, otherwise `ERR_GTN_TOTALS_INCONSISTENT` (HTTP 422)."

    Design: Corner/errors/gtn_run_with_net_above_gross_is_rejected
    """
    ctx = fx.setup_locked_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.create_gtn_run(
        f.gtn_run_payload(
            ctx["cycle_id"],
            ctx["input_file_id"],
            ctx["cycle_version"],
            gross_minor=10000000,
            net_minor=10500000,
        ),
        ctx["provider_headers"],
    )
    validate_error(response, ERR_GTN_TOTALS_INCONSISTENT, 422)

    runs, meta = validate_paginated(
        api.list_gtn_runs(CONTROLLER_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert runs == [], f"no results were recorded, got {runs}"

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)
    a.assert_minor_amount(cycle["gross_total_minor"], 0, "gross_total_minor")


def test_bank_account_in_a_currency_other_than_the_countrys_is_refused(api):
    """The account's residency region is correct, so the safety rule passes and the
    currency rule reports: a USD account cannot settle a German payroll.

    PRD 3.1: "`account_currency` must equal the `local_currency` of the engagement's
    country."

    PRD 3.1: "the currency rule is evaluated afterwards, at the referential-coherence
    rank, and yields `ERR_CURRENCY_MISMATCH` (HTTP 422)"

    Design: Corner/errors/bank_account_in_the_wrong_currency_is_rejected
    """
    ctx = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)
    country = fx.read_country(api, ctx["country_id"])
    assert country["local_currency"] == "EUR", (
        f"the country settles in euro, got {country['local_currency']!r}"
    )

    response = api.create_bank_account(
        f.bank_account_payload(
            ctx["engagement_id"], account_ref="DE-ACC-USD", account_currency="USD"
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ERR_CURRENCY_MISMATCH, 422)

    accounts, meta = validate_paginated(
        api.list_engagement_bank_accounts(ctx["engagement_id"], PLATFORM_ADMIN_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert accounts == [], f"no account was registered, got {accounts}"
