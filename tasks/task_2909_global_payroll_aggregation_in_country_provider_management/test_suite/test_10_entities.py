"""Resource shape: declared fields, defaults, derived flags and parent references.

These tests read the entities back through the API and check the properties the
specification attaches to a stored row rather than to a workflow.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BANK_ACCOUNT_ENGAGEMENT_MISMATCH,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PROVIDER_NOT_FOUND,
)
from test_helpers.constants import (
    CYCLE_DRAFT,
    CYCLE_RESULTS_APPROVED,
    CTRL_RESIDENCY_ATTESTATION,
    ENGAGEMENT_DRAFT,
    EVIDENCE_TYPE_DOCUMENT_HASH,
    FILING_RESPONSIBILITY_CLIENT,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FILING_TYPE_SOCIAL_INSURANCE,
    INPUT_FILE_RECEIVED,
    PROVIDER_ACTIVE,
    REGION_EU,
    ROLE_COMPLIANCE_AUDITOR,
    SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    SERVICE_GROSS_TO_NET,
    SERVICE_STATUTORY_FILING,
)
from test_helpers.factories import OMIT
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    OPS_HEADERS,
    OPS_USER_ID,
    PLATFORM_ADMIN_HEADERS,
    TREASURY_APPROVER_HEADERS,
)

_UNKNOWN_PROVIDER_ID = "11111111-1111-4111-8111-111111111111"
_UNKNOWN_ENGAGEMENT_ID = "22222222-2222-4222-8222-222222222222"
_EVIDENCE_HASH = "9f2c4ba7d1e05c38"


def test_country_profile_creation_returns_every_declared_field(api):
    """A fully specified country registration echoes each registered term and seeds
    the obligation count the system maintains itself.

    PRD 3.1: "A newly registered country starts with `open_filing_obligation_count` at
    0; the value is maintained by the system and never supplied by a client."

    Design: Corner/entities/country_profile_creation_returns_every_declared_field
    """
    response = api.create_country_profile(
        f.country_profile_payload(), PLATFORM_ADMIN_HEADERS
    )

    country = validate_success(response, 201)
    a.assert_field_values(
        country,
        {
            "country_code": "DE",
            "local_currency": "EUR",
            "data_residency_region": REGION_EU,
            "statutory_filing_deadline_days": 10,
            "materiality_floor_minor": 100000,
            "penalty_daily_rate_minor": 15000,
            "required_filing_types": [
                FILING_TYPE_INCOME_TAX_WITHHOLDING,
                FILING_TYPE_SOCIAL_INSURANCE,
            ],
            "local_holidays": ["2026-09-25"],
            "open_filing_obligation_count": 0,
        },
    )
    a.assert_pct(country["materiality_pct"], 5.00, "materiality_pct")
    a.assert_common_fields(country, expected_version=1)


def test_provider_read_returns_the_stored_entity(api):
    """A provider read exposes the registered terms together with the standing fields
    the specification seeds at registration.

    PRD 3.1: "A freshly registered provider opens with `status` `ACTIVE`, a perfect
    `service_score` of 100.00, `score_variant_applied` set to `ENGAGEMENT_TO_DATE`, and
    `open_penalty_minor` at 0."

    Design: Corner/entities/provider_read_returns_the_stored_entity
    """
    created = fx.create_provider(api)

    provider = validate_success(api.get_provider(created["id"], OPS_HEADERS))
    assert provider["legal_name"] == "EuroPay GmbH", (
        f"expected the stored legal name, got {provider['legal_name']!r}"
    )
    assert provider["statutory_filing_capable"] is True, (
        "a provider carrying STATUTORY_FILING is filing capable, got "
        f"{provider['statutory_filing_capable']}"
    )
    a.assert_provider_standing(
        provider,
        status=PROVIDER_ACTIVE,
        service_score=100.00,
        open_penalty_minor=0,
        score_variant_applied=SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    )


def test_engagement_list_paginates_with_total_count_and_has_more(api):
    """With three engagements stored, a two-row page reports the unwindowed total and
    a further page that completes the collection.

    PRD 2.3: "The `meta` object of a list response carries `limit` and `offset` as they
    were applied, `total_count` giving the number of rows that match the filters before
    the page window is applied, and `has_more`, which is true exactly when the sum of
    `offset` and the number of rows returned in this page is less than `total_count`."

    Design: Corner/entities/engagement_list_paginates_with_total_count_and_has_more
    """
    provider = fx.create_provider(api, service_scope=[SERVICE_GROSS_TO_NET])
    for code in ("DE", "FR", "IT"):
        country = fx.create_country(
            api,
            country_code=code,
            required_filing_types=[FILING_TYPE_INCOME_TAX_WITHHOLDING],
        )
        fx.create_engagement(
            api,
            country["id"],
            provider["id"],
            service_scope=[SERVICE_GROSS_TO_NET],
            filing_responsibility=FILING_RESPONSIBILITY_CLIENT,
        )

    first_page, first_meta = validate_paginated(
        api.list_engagements(OPS_HEADERS, f.pagination_params(limit=2, offset=0))
    )
    assert len(first_page) == 2, f"expected a two-row page, got {len(first_page)}"
    a.assert_pagination_meta(
        first_meta,
        expected_total=3,
        expected_has_more=True,
        expected_limit=2,
        expected_offset=0,
    )

    second_page, second_meta = validate_paginated(
        api.list_engagements(OPS_HEADERS, f.pagination_params(limit=2, offset=2))
    )
    assert len(second_page) == 1, f"expected the tail row, got {len(second_page)}"
    a.assert_pagination_meta(
        second_meta,
        expected_total=3,
        expected_has_more=False,
        expected_limit=2,
        expected_offset=2,
    )
    for engagement in first_page + second_page:
        assert engagement["status"] == ENGAGEMENT_DRAFT, (
            f"an engagement without a residency decision is DRAFT, got {engagement['status']}"
        )


def test_provider_read_with_unknown_id_returns_not_found(api):
    """A well-formed identifier that names no provider is a not-found condition, not
    an empty success.

    PRD 2.8: "Any path identifier or body foreign key that names no row produces the
    matching not-found error — `ERR_COUNTRY_PROFILE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_INPUT_FILE_NOT_FOUND`,
    `ERR_GTN_RUN_NOT_FOUND`, `ERR_BANK_ACCOUNT_NOT_FOUND`,
    `ERR_FUNDING_INSTRUCTION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` or
    `ERR_SLA_INCIDENT_NOT_FOUND` — each with HTTP 404."

    Design: Corner/entities/provider_read_with_unknown_id_returns_not_found
    """
    response = api.get_provider(_UNKNOWN_PROVIDER_ID, OPS_HEADERS)

    validate_error(response, ERR_PROVIDER_NOT_FOUND, 404)


def test_country_profile_missing_required_materiality_pct_returns_invalid_request(api):
    """Omitting a required registration term is a shape failure, and nothing is
    persisted, so the same country code is still free afterwards.

    PRD 2.8: "A missing required field, a field of the wrong JSON type, an enum value
    that is not a declared member of its enumeration, a numeric field outside its
    declared range, or a date or instant that is not valid ISO 8601 all produce
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/country_profile_missing_required_materiality_pct_returns_invalid_request
    """
    response = api.create_country_profile(
        f.country_profile_payload(materiality_pct=OMIT), PLATFORM_ADMIN_HEADERS
    )
    validate_error(response, ERR_INVALID_REQUEST, 422)

    retry = api.create_country_profile(
        f.country_profile_payload(), PLATFORM_ADMIN_HEADERS
    )
    country = validate_success(retry, 201)
    assert country["country_code"] == "DE", (
        f"the code was never taken, got {country['country_code']!r}"
    )


def test_cycle_optional_prior_cycle_id_defaults_to_null(api):
    """A first period leaves the variance baseline unset and opens on every declared
    default.

    PRD 3.3: "A new cycle opens in `status` `DRAFT` with `gross_total_minor` at 0,
    `funded_total_minor` at 0, `filings_confirmed_count` at 0, `hold_reason` null and
    `input_submitter_user_id` null."

    Design: Corner/entities/cycle_optional_prior_cycle_id_defaults_to_null
    """
    ctx = fx.setup_active_engagement(api)

    response = api.create_cycle(f.cycle_payload(ctx["engagement_id"]), OPS_HEADERS)

    cycle = validate_success(response, 201)
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
    a.assert_null_fields(cycle, ["prior_cycle_id", "input_submitter_user_id"])
    a.assert_minor_amount(cycle["gross_total_minor"], 0, "gross_total_minor")
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")
    assert cycle["filings_confirmed_count"] == 0, (
        f"no filing is confirmed yet, got {cycle['filings_confirmed_count']}"
    )


def test_provider_statutory_filing_capable_is_derived_from_service_scope(api):
    """The capability flag is exactly the presence of `STATUTORY_FILING` in the
    declared scope, and clients never set it.

    PRD 3.1: "From the declared scope the system derives `statutory_filing_capable`,
    which is true exactly when `service_scope` contains `STATUTORY_FILING` and false
    otherwise; clients never set it."

    Design: Corner/entities/provider_statutory_filing_capable_is_derived_from_service_scope
    """
    without = fx.create_provider(
        api,
        legal_name="CalcOnly BV",
        service_scope=[SERVICE_GROSS_TO_NET],
        annual_fee_minor=1000000,
        indemnity_cap_pct=20.0,
    )
    with_filing = fx.create_provider(
        api,
        legal_name="FullService BV",
        service_scope=[SERVICE_GROSS_TO_NET, SERVICE_STATUTORY_FILING],
        annual_fee_minor=1000000,
        indemnity_cap_pct=20.0,
    )

    assert without["statutory_filing_capable"] is False, (
        f"a scope without STATUTORY_FILING is not capable, got {without}"
    )
    assert with_filing["statutory_filing_capable"] is True, (
        f"a scope with STATUTORY_FILING is capable, got {with_filing}"
    )
    for provider in (without, with_filing):
        a.assert_provider_standing(
            provider, status=PROVIDER_ACTIVE, service_score=100.00
        )


def test_input_file_system_fields_are_server_minted(api):
    """The extract's identity, version and submission instant all come from the
    server, the last of them from the logical clock.

    PRD 3.4: "A submitted extract opens in `status` `RECEIVED` with `submitted_at`
    stamped from the logical clock, `rejection_code` null and `validated_record_count`
    at 0."

    Design: Corner/entities/input_file_system_fields_are_server_minted
    """
    ctx = fx.setup_draft_cycle(api)
    fx.set_clock(api, "2026-08-05T09:30:00Z")

    response = api.create_input_file(f.input_file_payload(ctx["cycle_id"]), OPS_HEADERS)

    extract = validate_success(response, 201)
    a.assert_common_fields(extract, expected_version=1)
    a.assert_instant_equals(
        extract["submitted_at"], "2026-08-05T09:30:00.000Z", "submitted_at"
    )
    assert extract["status"] == INPUT_FILE_RECEIVED, (
        f"a submitted extract opens in RECEIVED, got {extract['status']}"
    )
    a.assert_null_fields(extract, ["rejection_code"])
    assert extract["validated_record_count"] == 0, (
        f"nothing is validated yet, got {extract['validated_record_count']}"
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    assert cycle["input_submitter_user_id"] == OPS_USER_ID, (
        f"the submitter is stamped on the cycle, got {cycle['input_submitter_user_id']!r}"
    )


def test_engagement_pay_frequency_invalid_enum_returns_invalid_request(api):
    """A value outside the declared frequency enumeration fails at the shape gate,
    before any residency or scope reasoning.

    PRD 3.2: "the `pay_frequency`, one of `WEEKLY`, `BIWEEKLY`, `SEMI_MONTHLY` or
    `MONTHLY`, which constrains the length of every pay period this engagement will
    ever run."

    Design: Corner/entities/engagement_pay_frequency_invalid_enum_returns_invalid_request
    """
    country = fx.create_country(api)
    provider = fx.create_provider(api)

    response = api.create_engagement(
        f.engagement_payload(
            country["id"], provider["id"], pay_frequency="FORTNIGHTLY"
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ERR_INVALID_REQUEST, 422)

    engagements, meta = validate_paginated(api.list_engagements(OPS_HEADERS))
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert engagements == [], f"nothing was persisted, got {engagements}"


def test_audit_evidence_item_is_immutable_and_carries_no_version(api):
    """An audit evidence item is append-only: it carries an identity and a creation
    instant, a first sequence position, and neither a version nor an update instant.

    PRD 2.4: "Audit evidence items are the single exception: because they are
    append-only records of what happened, an audit evidence item carries only `id` and
    `created_at` — it has neither `updated_at` nor `version`, and neither field appears
    in its representation."

    Design: Corner/entities/audit_evidence_item_is_immutable_and_carries_no_version
    """
    ctx = fx.setup_draft_cycle(api)

    response = api.create_audit_evidence(
        f.audit_evidence_payload(
            ctx["cycle_id"],
            CTRL_RESIDENCY_ATTESTATION,
            evidence_type=EVIDENCE_TYPE_DOCUMENT_HASH,
            payload_hash=_EVIDENCE_HASH,
        ),
        AUDITOR_HEADERS,
    )

    item = validate_success(response, 201)
    a.assert_append_only_fields(item)
    assert item["sequence_no"] == 1, (
        f"the first item of the cycle is at position 1, got {item['sequence_no']}"
    )
    a.assert_field_values(
        item,
        {
            "control_ref": CTRL_RESIDENCY_ATTESTATION,
            "evidence_type": EVIDENCE_TYPE_DOCUMENT_HASH,
            "payload_hash": _EVIDENCE_HASH,
            "recorded_by_role": ROLE_COMPLIANCE_AUDITOR,
            "recorded_by_user_id": AUDITOR_USER_ID,
        },
    )

    items, meta = validate_paginated(
        api.list_cycle_audit_evidence(ctx["cycle_id"], AUDITOR_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    assert len(items) == 1, f"exactly one item was recorded, got {len(items)}"


def test_cycle_creation_with_unknown_engagement_id_returns_not_found(api):
    """The parent reference is resolved before any period arithmetic, so an unknown
    engagement is reported as missing rather than as a bad period.

    PRD 2.8: "**Existence of every referenced entity.** Any path identifier or body
    foreign key that names no row produces the matching not-found error"

    Design: Corner/entities/cycle_creation_with_unknown_engagement_id_returns_not_found
    """
    response = api.create_cycle(
        f.cycle_payload(_UNKNOWN_ENGAGEMENT_ID), OPS_HEADERS
    )
    validate_error(response, ERR_ENGAGEMENT_NOT_FOUND, 404)

    cycles, meta = validate_paginated(api.list_cycles(OPS_HEADERS))
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert cycles == [], f"no cycle was opened, got {cycles}"


def test_funding_instruction_naming_another_engagements_account_is_rejected(api):
    """Both rows exist, but they hang off different engagements, so the instruction is
    refused on coherence grounds.

    PRD 3.6: "The named local account must belong to the same engagement as the cycle,
    otherwise `ERR_BANK_ACCOUNT_ENGAGEMENT_MISMATCH` (HTTP 422)."

    Design: Corner/entities/funding_instruction_naming_another_engagements_account_is_rejected
    """
    german = fx.setup_active_engagement(api)
    french_country = fx.create_country(
        api,
        country_code="FR",
        required_filing_types=[FILING_TYPE_INCOME_TAX_WITHHOLDING],
    )
    french_engagement = fx.create_engagement(
        api, french_country["id"], german["provider_id"]
    )
    fx.approve_residency(api, french_engagement["id"], "DPA-FR-2026-01")
    french_account = fx.create_bank_account(
        api, french_engagement["id"], account_ref="FR-ACC-1"
    )
    fx.verify_bank_account(api, french_account["id"])

    ctx = fx.setup_draft_cycle(api, german)
    ctx = fx.setup_validated_extract(api, ctx)
    ctx = fx.setup_locked_cycle(api, ctx)
    ctx = fx.setup_scored_run(api, ctx)
    ctx = fx.setup_results_approved_cycle(api, ctx)

    response = api.create_funding_instruction(
        f.funding_instruction_payload(ctx["cycle_id"], french_account["id"]),
        TREASURY_APPROVER_HEADERS,
    )
    validate_error(response, ERR_BANK_ACCOUNT_ENGAGEMENT_MISMATCH, 422)

    instructions, meta = validate_paginated(
        api.list_funding_instructions(
            TREASURY_APPROVER_HEADERS, {"cycle_id": ctx["cycle_id"]}
        )
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert instructions == [], f"no instruction was drafted, got {instructions}"

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
