"""RBAC: the six roles, per-row ownership for the entity-backed two, and duty segregation."""

from test_helpers import (
    ADMIN_HEADERS,
    AGREEMENT_COUNTERED,
    AGREEMENT_PROPOSED,
    AGREEMENT_SIGNED,
    AUDITOR_HEADERS,
    CERT_ENV_A,
    CERTIFICATION_TESTING,
    CHANNEL_KIND_DIRECT,
    CHANNEL_KIND_NDC_AGGREGATOR,
    CONTENT_TIER_FULL,
    CONTENT_TIER_STANDARD,
    DECISION_CERTIFY,
    DISTRIBUTION_MANAGER_HEADERS,
    DISTRIBUTION_MANAGER_USER_ID,
    FILING_ACTIVE,
    NEGOTIATION_ACCEPT,
    NEGOTIATION_COUNTER,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    OTHER_DISTRIBUTION_MANAGER_USER_ID,
    PARTNER_TYPE_TRAVEL_AGENCY,
    PRICING_ANALYST_HEADERS,
    READINESS_PROVISIONAL,
    TEST_SCHEDULED,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    technology_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_START = "2026-08-03T09:00:00.000Z"


def _corner_channel(api):
    return fx.create_ndc_channel(api, with_surcharge_rules=False)


def _corner_agency(api):
    return fx.create_alpha_agency(
        api, partner_name="Alpha Corner Travel", iata_code="55555550"
    )


def _tango(api):
    return fx.create_tech_partner(
        api, partner_name="Tango Corner Systems", iata_code="55555551"
    )


def test_each_role_carries_out_the_writes_its_own_mandate_names(api):
    """PRD §2.1: "**`Agency`** — a travel agency or corporate booking channel acting under its own
    incentive agreement. Counters negotiations, constructs and publishes offers, creates orders and
    opens servicing requests."
    PRD §2.1: "**`TechnologyPartner`** — an aggregator or technology provider driving connectivity
    certification. Opens certifications, schedules connectivity tests and reports their outcomes; it
    can never take the airline's certification decision."
    PRD §3.3: "A `COUNTER` is the agency's move and advances `PROPOSED → COUNTERED`: it may be
    performed only by the `Agency` whose `X-User-ID` equals the agreement's `partner_id`, it
    increases `negotiation_round` by 1, and it replaces `proposed_incentive_pct` with the countered
    value."
    PRD §3.8: "Scheduling increases the certification's `reserved_test_minutes` by
    `duration_minutes` and increases the certification's `version` by 1; the test's `score` starts
    null and its `status` starts at `SCHEDULED`, with `certification_id` bound to the owning
    certification."

    Design: Corner/rbac/corner_each_role_performs_its_own_declared_operations
    """
    # PlatformAdmin: channel and partner registration.
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    tech = _tango(api)
    assert channel["channel_kind"] == CHANNEL_KIND_NDC_AGGREGATOR
    assert agency["partner_type"] == PARTNER_TYPE_TRAVEL_AGENCY

    # PricingAnalyst: filing a fare and driving it to ACTIVE.
    filing = fx.create_active_filing(api)
    assert filing["status"] == FILING_ACTIVE

    # DistributionManager: opening the incentive agreement.
    agreement = fx.open_agreement(api, agency["id"], channel["id"], agency["version"])
    assert agreement["status"] == AGREEMENT_PROPOSED

    # Agency: countering the airline's proposal on its own agreement.
    countered = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_COUNTER,
        headers=agency_headers(agency["id"]),
        proposed_incentive_pct=0.030,
    )
    assert countered["status"] == AGREEMENT_COUNTERED
    assert countered["negotiation_round"] == 1
    assert countered["proposed_incentive_pct"] == 0.030

    # TechnologyPartner: opening a certification and reserving a test slot.
    certification = fx.open_certification(
        api, tech["id"], channel["id"], env_code=CERT_ENV_A
    )
    scheduled = fx.schedule_test(
        api,
        certification["id"],
        tech["id"],
        "SHOP_SEARCH",
        TEST_START,
        duration_minutes=60,
        is_mandatory=True,
    )
    assert scheduled["status"] == TEST_SCHEDULED
    assert fx.read_certification(api, certification["id"])["reserved_test_minutes"] == 60

    # ComplianceAuditor: the read-only role sees the aggregate it must review.
    audited = validate_success(
        api.get_agency_agreement(agreement["id"], headers=AUDITOR_HEADERS)
    )
    assert audited["id"] == agreement["id"]
    assert audited["status"] == AGREEMENT_COUNTERED


def test_no_role_may_reach_across_into_another_roles_write(api):
    """PRD §2.10: "2. **Authorization** — the role is one of the six, the role is listed for the
    endpoint, and for the entity-backed roles the `X-User-ID` ownership comparison of §2.1 holds
    (`ERR_UNAUTHORIZED`, 403)."
    PRD §2.1: "**`PricingAnalyst`** — files and re-files fares, publishes ancillary products, and
    defines bundles. May suspend or withdraw filings but has no authority over commercial
    agreements."
    PRD §2.1: "**`ComplianceAuditor`** — a strictly read-only regulatory reviewer. Inspects
    disclosure acknowledgements, negotiated-fare traceability and distribution cost per booking, and
    may never perform a mutating operation."
    PRD §2.10: "6. **Optimistic concurrency** — the submitted expected-version field equals the
    parent's current `version` (`ERR_STALE_PARTNER_VERSION` or `ERR_STALE_FARE_FILING_VERSION`, 412),
    on `POST /agency-agreements` and `POST /fare-filings/{id}/revisions` respectively."

    Design: Corner/rbac/corner_roles_are_denied_the_operations_that_belong_to_other_roles
    """
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    tech = _tango(api)
    certification = fx.open_certification(
        api, tech["id"], channel["id"], env_code=CERT_ENV_A
    )

    # The analyst has no authority over agreements, and rung 2 speaks before rung 6.
    analyst_write = api.create_agency_agreement(
        f.agreement_payload(agency["id"], channel["id"], 99),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(analyst_write, ApiErrorId.UNAUTHORIZED)
    assert (
        analyst_write.json()["data"]["error_id"] != ApiErrorId.STALE_PARTNER_VERSION
    )

    # Filing fares belongs to the analyst, not to the commercial manager.
    manager_write = api.create_fare_filing(
        f.fare_filing_payload(fare_basis_code="YDENY01"),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(manager_write, ApiErrorId.UNAUTHORIZED)

    # The auditor may never mutate anything, content policy included.
    auditor_write = api.patch_channel_content_policy(
        channel["id"],
        f.content_policy_payload(content_tier=CONTENT_TIER_FULL),
        headers=AUDITOR_HEADERS,
    )
    validate_error(auditor_write, ApiErrorId.UNAUTHORIZED)

    # Channel registration is the platform operator's alone.
    agency_write = api.create_channel(
        f.channel_payload(channel_code="AGENCY_MADE", channel_kind=CHANNEL_KIND_DIRECT),
        headers=agency_headers(agency["id"]),
    )
    validate_error(agency_write, ApiErrorId.UNAUTHORIZED)

    # A technology partner runs the tests but never awards itself the certificate.
    partner_write = api.post_certification_decision(
        certification["id"],
        f.decision_payload(DECISION_CERTIFY, READINESS_PROVISIONAL),
        headers=technology_partner_headers(tech["id"]),
    )
    validate_error(partner_write, ApiErrorId.UNAUTHORIZED)

    # Five refusals, nothing written.
    _rows, meta = validate_paginated(
        api.list_agency_agreements(
            headers=ADMIN_HEADERS, params={"partner_id": agency["id"]}
        )
    )
    assert meta["total_count"] == 0
    _rows, meta = validate_paginated(api.list_fare_filings(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0

    unmoved = fx.read_channel(api, channel["id"])
    assert unmoved["content_tier"] == CONTENT_TIER_STANDARD
    assert unmoved["version"] == 1
    assert fx.read_certification(api, certification["id"])["status"] == CERTIFICATION_TESTING


def test_the_agency_role_is_authorised_row_by_row_not_wholesale(api):
    """PRD §2.1: "When `X-User-Role` is `Agency`, `X-User-ID` is the `id` of the acting
    `DistributionPartner`; ownership checks on any resource that references a `DistributionPartner`
    compare the resource's `partner_id` to `X-User-ID`, and a mismatch is `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD §2.1: "The negotiation workflow makes this concrete: an `Agency` recording a counter-offer on
    an agreement must be the very partner the agreement names, and if the acting `X-User-ID` differs
    from the agreement's `partner_id` the call fails with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/corner_agency_cannot_act_on_another_partners_agreement
    """
    channel = _corner_channel(api)
    alpha = _corner_agency(api)
    beta = fx.create_agency_partner(
        api,
        partner_name="Beta Corner Travel",
        iata_code="55555553",
        home_country="FR",
    )
    agreement = fx.open_agreement(api, alpha["id"], channel["id"], alpha["version"])

    # Beta holds the Agency role, but not on this row.
    intruder = api.create_negotiation_round(
        agreement["id"],
        f.negotiation_payload(NEGOTIATION_COUNTER, proposed_incentive_pct=0.040),
        headers=agency_headers(beta["id"]),
    )
    validate_error(intruder, ApiErrorId.UNAUTHORIZED)

    untouched = fx.read_agreement(api, agreement["id"])
    assert untouched["status"] == AGREEMENT_PROPOSED
    assert untouched["negotiation_round"] == 0
    assert untouched["version"] == 1

    # The very same request from the named partner is accepted.
    countered = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_COUNTER,
        headers=agency_headers(alpha["id"]),
        proposed_incentive_pct=0.030,
    )
    assert countered["status"] == AGREEMENT_COUNTERED
    assert countered["negotiation_round"] == 1
    assert countered["proposed_incentive_pct"] == 0.030


def test_the_proposer_cannot_countersign_its_own_proposal(api):
    """PRD §3.3: "`ACCEPT` signs the deal, `PROPOSED → SIGNED`, and it is the single operation in
    this service under segregation of duties: the `DistributionManager` performing it must have an
    `X-User-ID` different from the value stored in `proposed_by_user_id`, and an attempt by the
    proposer to sign its own proposal is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.1: "Authorization is not the same as segregation of duties. A single operation in this
    service additionally requires that two *different* human operators be involved: accepting an
    agency agreement."
    PRD §3.3: "On signing, `agreed_incentive_pct` is frozen to whatever `proposed_incentive_pct`
    currently holds — the frozen figure, not the mutable one, is what the accrual calculation uses
    forever after — `signed_by_user_id` records the accepting operator, and `version` increases by
    1."

    Design: Corner/rbac/corner_same_manager_cannot_propose_and_accept_one_agreement
    """
    channel = _corner_channel(api)
    agency = _corner_agency(api)
    agreement = fx.open_agreement(api, agency["id"], channel["id"], agency["version"])
    assert agreement["proposed_by_user_id"] == DISTRIBUTION_MANAGER_USER_ID

    self_signed = api.create_negotiation_round(
        agreement["id"],
        f.negotiation_payload(NEGOTIATION_ACCEPT),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    # Both operators hold the role, so this is a duty failure and not an authorization failure.
    validate_error(self_signed, ApiErrorId.SEGREGATION_OF_DUTIES)
    assert self_signed.json()["data"]["error_id"] != ApiErrorId.UNAUTHORIZED

    unsigned = fx.read_agreement(api, agreement["id"])
    assert unsigned["status"] == AGREEMENT_PROPOSED
    assert unsigned["agreed_incentive_pct"] is None
    assert unsigned["version"] == 1

    signed = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_ACCEPT,
        headers=OTHER_DISTRIBUTION_MANAGER_HEADERS,
    )
    assert signed["status"] == AGREEMENT_SIGNED
    assert signed["agreed_incentive_pct"] == 0.025
    assert signed["signed_by_user_id"] == OTHER_DISTRIBUTION_MANAGER_USER_ID
