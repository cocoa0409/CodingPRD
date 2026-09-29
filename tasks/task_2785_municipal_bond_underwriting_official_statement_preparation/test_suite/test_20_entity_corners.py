"""Entity-level corners: persistence, defaults, shape rejection and the graph.

Every test here translates exactly one instance of the CORNER design index's
``entities`` section. Four families live in this file:

* **persistence and computed fields** -- a creation echoes its inputs and carries
  the derived ``disclosure_risk_score`` and section ``word_count``, and a read by
  id returns exactly what the write stored;
* **declared defaults** -- what a freshly created deal, maturity, issuer and
  continuing-disclosure undertaking look like before any event moves them, where
  the defaults are deliberately not all false;
* **request shape** -- a missing required field, a system-assigned field supplied
  as input, and three enum/case/range violations, each reporting
  ``ERR_INVALID_REQUEST`` and persisting nothing;
* **the entity graph** -- each aggregate's own 404 code, the parent-before-child
  resolution order, the two edges that must stay inside one deal, and the
  Deal-to-Firm junction that is deliberately allowed to fan out.

No figure is spelled inline: enum literals come from ``test_helpers.types``,
bounds and the canonical worked issue from ``test_helpers.constants``, error ids
from ``test_helpers.api_errors``, and every derived number from an
``expected_*``/``word_count`` helper that restates the PRD formula once.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLOSING_DOCUMENT_NOT_FOUND,
    ERR_CROSS_DEAL_REFERENCE,
    ERR_DEAL_NOT_FOUND,
    ERR_ENHANCEMENT_NOT_FOUND,
    ERR_FIRM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ISSUER_NOT_FOUND,
    ERR_MATURITY_DATE_UNALIGNED,
    ERR_OFFICIAL_STATEMENT_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_PERIOD_NOT_FOUND,
    ERR_PRESENTATION_NOT_FOUND,
    ERR_RATING_ENGAGEMENT_NOT_FOUND,
    ERR_REFUNDED_TRANCHE_INVALID,
    ERR_SECTION_NOT_FOUND,
    ERR_TRANCHE_NOT_FOUND,
    ERR_UNDERTAKING_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_money,
    assert_pagination,
    assert_sorted_by,
    assert_version,
    expected_risk_score,
    ids_of,
    word_count,
)
from test_helpers.constants import (
    CANONICAL_EXPECTED_PAR_USD,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    LIABILITY_PCT_TOTAL,
    PRIOR_COUNT_MAX,
    TRANCHE_1_MATURITY_DATE,
    plus_days,
)
from test_helpers.test_users import (
    BOND_COUNSEL_DRAFTER_HEADERS,
    BOND_COUNSEL_DRAFTER_ID,
    make_advisor_headers,
    make_issuer_official_headers,
)
from test_helpers.types import (
    DealStatus,
    DisclosureClearance,
    EnhancementStatus,
    EntityType,
    FirmType,
    GrossSpreadBasis,
    HandoffStatus,
    MemberRole,
    MemberStatus,
    ReviewStatus,
    SaleMethod,
    SectionType,
    UndertakingStatus,
)

# --- The design index's named participants -----------------------------------
FAIRHAVEN_NAME = "City of Fairhaven"
ASHBURY_NAME = "City of Ashbury"
PORT_AUTHORITY_NAME = "Fairhaven Port Authority"
TOWNSHIP_NAME = "Fairhaven Township"
UNDERWRITER_NAME = "Alpha Underwriting"
OHIO_STATE_CODE = "OH"

# --- The scored issuer of the creation instance (PRD section 3.1) -------------
ONE_LATE_ANNUAL_FILING = 1
NO_LATE_EVENT_NOTICES = 0
# 12 for the one late annual filing + 0 late event notices + 25 for the material
# event + the CITY surcharge of 5. Cross-checked against expected_risk_score so a
# missing surcharge (37) or a dropped material-event weight (17) both fail.
FAIRHAVEN_RISK_SCORE = 42
# A clean-record CITY carries the surcharge and nothing else.
CLEAN_CITY_RISK_SCORE = 5

# --- Shape violations of the type-constraint instance (PRD section 3.1) -------
# Right length, right letters, wrong case.
MIXED_CASE_STATE_CODE = "Oh"
# Not one of the five listed entity_type members.
UNLISTED_ENTITY_TYPE = "TOWNSHIP"
# One past the declared maximum of 0 through 20.
OVER_MAX_PRIOR_COUNT = PRIOR_COUNT_MAX + 1
# Both fields are server-assigned on a deal, so either one is an unknown input.
SYSTEM_ASSIGNED_DEAL_STATUS = DealStatus.PRICED
SYSTEM_ASSIGNED_TAKEDOWN_PER_BOND_USD = 5.000

# --- The ten-word risk factor prose of the word-count instance (section 3.4) --
RISK_FACTOR_TITLE = "Risk Factors"
RISK_FACTOR_BODY_TEXT = "Ad valorem tax collections may decline in future fiscal years"
RISK_FACTOR_WORD_COUNT = 10

# --- The pagination window of the listing instance (PRD section 2.3) ---------
PAGE_LIMIT = 2
SECOND_PAGE_OFFSET = 2
ISSUER_POPULATION = 3
CITY_POPULATION = 2
# The API renders query booleans as strings; PRD section 2.3 filters on the
# literal true.
FILTER_TRUE = "true"

# A maturity date one month past the semiannual anniversary the deal's dated_date
# defines, so it would report ERR_MATURITY_DATE_UNALIGNED at tier 15 if the body
# were ever examined (PRD section 3.2). August has thirty-one days.
UNALIGNED_MATURITY_DATE = plus_days(TRANCHE_1_MATURITY_DATE, 31)

# The three system counters and nine pricing fields of PRD section 3.2.
DEAL_ZERO_COUNTERS = (
    "par_amount_usd",
    "credit_enhancement_premium_usd",
    "par_allotted_total_usd",
)
DEAL_FALSE_BRANCH_FLAGS = ("requires_g17_letter", "requires_notice_of_sale")
DEAL_NULL_PRICING_FIELDS = (
    "takedown_per_bond_usd",
    "management_fee_per_bond_usd",
    "expenses_per_bond_usd",
    "winning_bid_price_pct",
    "issue_price_total_usd",
    "gross_spread_total_usd",
    "gross_spread_per_bond_usd",
    "net_proceeds_to_issuer_usd",
    "arbitrage_yield_pct",
)

ISSUER_INPUT_FIELDS = (
    "name",
    "state_code",
    "entity_type",
    "prior_late_annual_filings",
    "prior_late_event_notices",
    "has_prior_material_event",
    "is_bank_qualified_eligible",
)
FIRM_INPUT_FIELDS = ("name", "firm_type", "msrb_registration_id")


def _deal_for_one_maturity(client, ctx=None, **deal_overrides):
    """Participants plus a DRAFT deal authorising a single 5,000,000 maturity."""
    ctx = ctx or fx.participants(client)
    deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
        **deal_overrides,
    )
    ctx.deal = deal
    ctx.deal_id = deal["id"]
    return ctx


def _first_maturity_payload(**overrides):
    """Sequence one, 5,000,000, maturing on a semiannual anniversary."""
    return f.tranche_payload(
        1,
        TRANCHE_1_MATURITY_DATE,
        principal_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
        **overrides,
    )


def _assert_echoes_inputs(row, payload, fields, label):
    """Every named input came back byte-identical to what was sent."""
    for field in fields:
        assert row[field] == payload[field], (
            f"{label}.{field}: expected the stored input {payload[field]!r}, "
            f"got {row[field]!r}"
        )


def test_issuer_creation_echoes_its_inputs_and_scores_disclosure_risk(
    client, compliance
):
    """PRD 3.1: "Finally the issuer's governmental character contributes a surcharge determined by `entity_type`: a `STATE` adds nothing, a `CITY` or a `COUNTY` adds five, a `SCHOOL_DISTRICT` adds ten, and an `AUTHORITY` adds fifteen."

    Design: Corner/entities/issuer_creation_returns_persisted_and_computed_fields
    """
    payload = f.issuer_payload(
        name=FAIRHAVEN_NAME,
        state_code=OHIO_STATE_CODE,
        entity_type=EntityType.CITY,
        prior_late_annual_filings=ONE_LATE_ANNUAL_FILING,
        prior_late_event_notices=NO_LATE_EVENT_NOTICES,
        has_prior_material_event=True,
        is_bank_qualified_eligible=True,
    )

    issuer = validate_success(client.create_issuer(payload, compliance), 201)

    # All seven inputs are echoed verbatim, the two booleans as true booleans.
    _assert_echoes_inputs(issuer, payload, ISSUER_INPUT_FIELDS, "issuer")
    assert issuer["has_prior_material_event"] is True
    assert issuer["is_bank_qualified_eligible"] is True

    # The score is computed at registration, not supplied.
    assert "disclosure_risk_score" not in payload
    assert issuer["disclosure_risk_score"] == expected_risk_score(
        EntityType.CITY,
        prior_late_annual_filings=ONE_LATE_ANNUAL_FILING,
        prior_late_event_notices=NO_LATE_EVENT_NOTICES,
        has_prior_material_event=True,
    )
    assert issuer["disclosure_risk_score"] == FAIRHAVEN_RISK_SCORE

    assert_common_fields(issuer, "issuer")
    assert_version(issuer, 1, "issuer")

    # The same row is what a read by id returns.
    stored = validate_success(client.get_issuer(issuer["id"], compliance), 200)
    assert stored == issuer


def test_firm_retrieval_returns_the_stored_row(client, compliance):
    """PRD 3.1: "The optional `is_suspended` flag defaults to false; a suspended firm remains readable and listable but is barred from every new engagement as described in section 2.8."

    Design: Corner/entities/firm_retrieval_returns_the_stored_row
    """
    payload = f.firm_payload(FirmType.UNDERWRITER, name=UNDERWRITER_NAME)
    created = validate_success(client.create_firm(payload, compliance), 201)

    firm = validate_success(client.get_firm(created["id"], compliance), 200)

    assert firm["id"] == created["id"]
    _assert_echoes_inputs(firm, payload, FIRM_INPUT_FIELDS, "firm")
    assert firm["firm_type"] == FirmType.UNDERWRITER

    # Never supplied on the create call, so this is the field default.
    assert "is_suspended" not in payload
    assert firm["is_suspended"] is False

    assert_common_fields(firm, "firm")
    assert_version(firm, 1, "firm")


def test_issuer_listing_holds_total_count_steady_while_has_more_flips(
    client, compliance
):
    """PRD 2.3: "`total_count` reports the number of rows matching the request's filters before the pagination window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned window."

    Design: Corner/entities/issuer_listing_paginates_with_total_count_and_has_more
    """
    fx.register_issuer(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    fx.register_issuer(client, name=ASHBURY_NAME, state_code=OHIO_STATE_CODE)
    fx.register_issuer(
        client,
        name=PORT_AUTHORITY_NAME,
        state_code=OHIO_STATE_CODE,
        entity_type=EntityType.AUTHORITY,
    )

    first_page, first_meta = validate_paginated(
        client.list_issuers(compliance, limit=PAGE_LIMIT, offset=DEFAULT_OFFSET)
    )
    assert len(first_page) == PAGE_LIMIT
    assert_pagination(
        first_meta,
        total_count=ISSUER_POPULATION,
        has_more=True,
        limit=PAGE_LIMIT,
        offset=DEFAULT_OFFSET,
    )

    second_page, second_meta = validate_paginated(
        client.list_issuers(compliance, limit=PAGE_LIMIT, offset=SECOND_PAGE_OFFSET)
    )
    assert len(second_page) == ISSUER_POPULATION - PAGE_LIMIT
    assert_pagination(
        second_meta,
        total_count=ISSUER_POPULATION,
        has_more=False,
        limit=PAGE_LIMIT,
        offset=SECOND_PAGE_OFFSET,
    )

    # The window moved but the population did not, and the two pages partition it.
    assert set(ids_of(first_page)).isdisjoint(ids_of(second_page))
    assert len(set(ids_of(first_page) + ids_of(second_page))) == ISSUER_POPULATION


def test_issuer_listing_applies_the_default_window_under_a_filter(client, compliance):
    """PRD 2.3: "`limit` bounds the number of rows returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."

    Design: Corner/entities/issuer_listing_paginates_with_total_count_and_has_more
    """
    fairhaven = fx.register_issuer(
        client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE
    )
    ashbury = fx.register_issuer(client, name=ASHBURY_NAME, state_code=OHIO_STATE_CODE)
    fx.register_issuer(
        client,
        name=PORT_AUTHORITY_NAME,
        state_code=OHIO_STATE_CODE,
        entity_type=EntityType.AUTHORITY,
    )

    cities, meta = validate_paginated(
        client.list_issuers(compliance, entity_type=EntityType.CITY)
    )

    # Neither limit nor offset was sent, so both defaults apply.
    assert_pagination(
        meta,
        total_count=CITY_POPULATION,
        has_more=False,
        limit=DEFAULT_LIMIT,
        offset=DEFAULT_OFFSET,
    )
    assert len(cities) == CITY_POPULATION
    assert set(ids_of(cities)) == {fairhaven["id"], ashbury["id"]}
    assert all(row["entity_type"] == EntityType.CITY for row in cities)


def test_deal_maturity_listing_narrows_to_the_callable_maturity(client):
    """PRD 3.2: "Maturities can be listed under their deal in schedule order with optional `is_callable` and `is_insured` filters, listed across deals with optional `deal_id` and `refunded_tranche_id` filters, and read individually with both price variants and their allotment counters exposed."

    Design: Corner/entities/maturity_tranche_listing_filters_on_is_callable
    """
    ctx = fx.participants(client)
    deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_EXPECTED_PAR_USD,
    )
    non_callable = fx.add_tranche(
        client, deal["id"], ctx.advisor_headers, f.canonical_tranche_1_payload()
    )
    callable_maturity = fx.add_tranche(
        client, deal["id"], ctx.advisor_headers, f.canonical_tranche_2_payload()
    )
    assert non_callable["is_callable"] is False
    assert callable_maturity["is_callable"] is True

    filtered, filtered_meta = validate_paginated(
        client.list_deal_maturity_tranches(
            deal["id"], ctx.advisor_headers, is_callable=FILTER_TRUE
        )
    )
    # total_count is filter-aware, so a silently ignored filter is caught here.
    assert_pagination(filtered_meta, total_count=1, has_more=False)
    assert ids_of(filtered) == [callable_maturity["id"]]

    everything, everything_meta = validate_paginated(
        client.list_deal_maturity_tranches(deal["id"], ctx.advisor_headers)
    )
    assert_pagination(everything_meta, total_count=2, has_more=False)
    assert_sorted_by(everything, "sequence_number", label="maturity schedule")
    assert ids_of(everything) == [non_callable["id"], callable_maturity["id"]]


def test_deal_creation_applies_every_declared_default(client):
    """PRD 3.2: "Its `status` is `DRAFT`, its `sale_method` and its `gross_spread_basis` are both `UNDETERMINED`, its `disclosure_clearance` is `PENDING`, its `post_issuance_handoff_status` is `NOT_STARTED`, and its `version` is 1."

    Design: Corner/entities/deal_creation_applies_declared_defaults
    """
    issuer = fx.register_issuer(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    issuer_headers = make_issuer_official_headers(issuer["id"])

    # Only the five required inputs: no advisor, no record_retention_years.
    payload = f.deal_payload(issuer["id"])
    assert "municipal_advisor_firm_id" not in payload
    assert "record_retention_years" not in payload

    deal = validate_success(client.create_deal(payload, issuer_headers), 201)

    assert deal["status"] == DealStatus.DRAFT
    assert deal["sale_method"] == SaleMethod.UNDETERMINED
    assert deal["gross_spread_basis"] == GrossSpreadBasis.UNDETERMINED
    assert deal["disclosure_clearance"] == DisclosureClearance.PENDING
    assert deal["post_issuance_handoff_status"] == HandoffStatus.NOT_STARTED

    for field in DEAL_ZERO_COUNTERS:
        assert_money(deal[field], 0, f"deal.{field}")
    for field in DEAL_FALSE_BRANCH_FLAGS:
        assert deal[field] is False, f"deal.{field} must start false"
    for field in DEAL_NULL_PRICING_FIELDS:
        assert deal[field] is None, f"deal.{field} must await the pricing event"
    assert deal["cancellation_reason"] is None

    # The optional inputs default to null rather than to a fabricated value.
    assert deal["municipal_advisor_firm_id"] is None
    assert deal["record_retention_years"] is None

    assert_common_fields(deal, "deal")
    assert_version(deal, 1, "deal")


def test_omitted_issuer_compliance_inputs_fall_back_to_zero_and_false(
    client, compliance
):
    """PRD 3.1: "`prior_late_annual_filings` counts annual financial reports filed after the undertaking deadline in the last five years; it is an integer from 0 through 20 and defaults to 0."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_field_defaults
    """
    payload = f.issuer_payload(name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    for optional in (
        "prior_late_annual_filings",
        "prior_late_event_notices",
        "has_prior_material_event",
        "is_bank_qualified_eligible",
    ):
        assert optional not in payload

    issuer = validate_success(client.create_issuer(payload, compliance), 201)

    # The two counters default to the integer zero, not to null.
    assert issuer["prior_late_annual_filings"] == 0
    assert issuer["prior_late_event_notices"] == 0
    assert issuer["has_prior_material_event"] is False
    assert issuer["is_bank_qualified_eligible"] is False

    # A clean record still carries the CITY surcharge.
    assert issuer["disclosure_risk_score"] == expected_risk_score(EntityType.CITY)
    assert issuer["disclosure_risk_score"] == CLEAN_CITY_RISK_SCORE


def test_omitted_call_feature_leaves_the_maturity_non_callable(client):
    """PRD 3.2: "When `is_callable` is false, both `first_call_date` and `call_price_pct` must be absent, and both remain null on the stored row."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_field_defaults
    """
    ctx = _deal_for_one_maturity(client)
    payload = _first_maturity_payload()
    for optional in ("is_callable", "is_insured", "first_call_date", "call_price_pct"):
        assert optional not in payload

    tranche = validate_success(
        client.create_maturity_tranche(ctx.deal_id, payload, ctx.advisor_headers), 201
    )

    assert tranche["is_callable"] is False
    assert tranche["is_insured"] is False
    assert tranche["first_call_date"] is None
    assert tranche["call_price_pct"] is None
    assert tranche["price_to_call_pct"] is None
    assert tranche["periods_to_call"] is None
    assert tranche["is_priced_to_call"] is False


def test_omitted_audited_financials_flag_defaults_to_true(client):
    """PRD 3.4: "It captures `annual_report_due_days`, the number of days after each fiscal year end by which the annual report must be filed, which must be at least 120 and at most 270; `material_event_notice_days`, the number of days after a reportable event by which the notice must be filed, which must be at least 1 and at most 10, since Rule 15c2-12 caps material event notices at ten business days; `dissemination_agent`, the name of the agent responsible for filings with EMMA (one to one hundred twenty characters, not blank); and the optional `audited_financials_included`, which defaults to true and states whether audited financial statements form part of the annual report commitment."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_field_defaults
    """
    ctx = _deal_for_one_maturity(client)
    payload = f.undertaking_payload()
    assert "audited_financials_included" not in payload

    undertaking = validate_success(
        client.create_undertaking(ctx.deal_id, payload, BOND_COUNSEL_DRAFTER_HEADERS),
        201,
    )

    # This default is true, unlike every other omitted boolean in this instance.
    assert undertaking["audited_financials_included"] is True
    assert undertaking["status"] == UndertakingStatus.DRAFT


def test_deal_creation_without_tax_status_is_rejected_and_persists_nothing(
    client, compliance
):
    """PRD 2.5: "On every endpoint that accepts a body: every required field is present and non-null, every field matches its declared type, every enum field carries a listed member, every string satisfies its length bounds, every number satisfies its range bounds, every datetime is a valid ISO 8601 UTC instant, and no unknown top-level field is present."

    Design: Corner/entities/deal_creation_missing_required_field_rejected
    """
    issuer = fx.register_issuer(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    issuer_headers = make_issuer_official_headers(issuer["id"])

    payload = f.deal_payload(issuer["id"])
    # tax_status has an input source and no default, unlike the two optional
    # inputs whose absence PRD section 3.2 permits.
    del payload["tax_status"]

    validate_error(client.create_deal(payload, issuer_headers), ERR_INVALID_REQUEST)

    deals, meta = validate_paginated(client.list_deals(compliance, issuer_id=issuer["id"]))
    assert deals == []
    assert_pagination(meta, total_count=0, has_more=False)


def test_section_word_count_is_computed_from_the_body_prose(client):
    """PRD 3.4: "The server sets `review_status` to `DRAFT`, records `authored_by_user_id` from `X-User-ID`, leaves `approved_by_user_id` null, and computes `word_count` as the number of whitespace-delimited tokens in `body_text`, recomputing it on every write that changes the prose."

    Design: Corner/entities/section_word_count_is_computed_from_body_text
    """
    ctx = _deal_for_one_maturity(client)
    statement = fx.start_official_statement(
        client,
        ctx.deal_id,
        BOND_COUNSEL_DRAFTER_HEADERS,
        reader_headers=ctx.advisor_headers,
    )

    payload = f.section_payload(
        SectionType.RISK_FACTOR,
        title=RISK_FACTOR_TITLE,
        body_text=RISK_FACTOR_BODY_TEXT,
        is_material_risk=True,
    )
    assert "word_count" not in payload

    section = validate_success(
        client.create_section(statement["id"], payload, BOND_COUNSEL_DRAFTER_HEADERS),
        201,
    )

    assert word_count(RISK_FACTOR_BODY_TEXT) == RISK_FACTOR_WORD_COUNT
    assert section["word_count"] == word_count(payload["body_text"])
    assert section["word_count"] == RISK_FACTOR_WORD_COUNT

    assert section["review_status"] == ReviewStatus.DRAFT
    # Taken from the header, never from a request field.
    assert "authored_by_user_id" not in payload
    assert section["authored_by_user_id"] == BOND_COUNSEL_DRAFTER_ID
    assert section["approved_by_user_id"] is None
    assert section["parent_section_id"] is None


def test_deal_creation_rejects_system_assigned_fields_supplied_as_input(
    client, compliance
):
    """PRD 2.5: "On every endpoint that accepts a body: every required field is present and non-null, every field matches its declared type, every enum field carries a listed member, every string satisfies its length bounds, every number satisfies its range bounds, every datetime is a valid ISO 8601 UTC instant, and no unknown top-level field is present."

    Design: Corner/entities/system_and_computed_fields_in_the_body_are_input_ignored
    """
    issuer = fx.register_issuer(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    issuer_headers = make_issuer_official_headers(issuer["id"])

    # status is server-assigned at creation, so it is an unknown top-level field
    # here rather than a value the server may adopt.
    validate_error(
        client.create_deal(
            f.deal_payload(issuer["id"], status=SYSTEM_ASSIGNED_DEAL_STATUS),
            issuer_headers,
        ),
        ERR_INVALID_REQUEST,
    )

    # takedown_per_bond_usd is written by the pricing event, never by creation.
    validate_error(
        client.create_deal(
            f.deal_payload(
                issuer["id"],
                takedown_per_bond_usd=SYSTEM_ASSIGNED_TAKEDOWN_PER_BOND_USD,
            ),
            issuer_headers,
        ),
        ERR_INVALID_REQUEST,
    )

    # Neither body was partially adopted: a permissive server would have echoed
    # PRICED back on a persisted row.
    deals, meta = validate_paginated(client.list_deals(compliance, issuer_id=issuer["id"]))
    assert deals == []
    assert_pagination(meta, total_count=0, has_more=False)


def test_issuer_enum_case_and_range_violations_all_report_invalid_request(
    client, compliance
):
    """PRD 3.1: "Registering a governmental issuer is open to an `IssuerOfficial`, a `MunicipalAdvisor`, or a `ComplianceOfficer`, and takes the issuer's legal `name` (one to one hundred sixty characters, not blank), its two-letter `state_code` (exactly two uppercase letters), and its `entity_type`, which is one of `CITY`, `COUNTY`, `SCHOOL_DISTRICT`, `AUTHORITY`, or `STATE`."

    Design: Corner/entities/issuer_enum_and_numeric_range_constraints_enforced
    """
    assert UNLISTED_ENTITY_TYPE not in EntityType.ALL
    assert MIXED_CASE_STATE_CODE.upper() == OHIO_STATE_CODE
    assert OVER_MAX_PRIOR_COUNT > PRIOR_COUNT_MAX

    # An unlisted enum member.
    validate_error(
        client.create_issuer(
            f.issuer_payload(
                name=TOWNSHIP_NAME,
                state_code=OHIO_STATE_CODE,
                entity_type=UNLISTED_ENTITY_TYPE,
            ),
            compliance,
        ),
        ERR_INVALID_REQUEST,
    )

    # The right two letters in the wrong case: a length-only check would pass it.
    validate_error(
        client.create_issuer(
            f.issuer_payload(name=FAIRHAVEN_NAME, state_code=MIXED_CASE_STATE_CODE),
            compliance,
        ),
        ERR_INVALID_REQUEST,
    )

    # One past the declared maximum of the counter.
    validate_error(
        client.create_issuer(
            f.issuer_payload(
                name=FAIRHAVEN_NAME,
                state_code=OHIO_STATE_CODE,
                prior_late_annual_filings=OVER_MAX_PRIOR_COUNT,
            ),
            compliance,
        ),
        ERR_INVALID_REQUEST,
    )

    issuers, meta = validate_paginated(client.list_issuers(compliance))
    assert issuers == []
    assert_pagination(meta, total_count=0, has_more=False)


def test_root_entity_lookups_report_their_own_not_found_codes(client, compliance):
    """PRD 2.5: "On every endpoint with a path parameter, the identifier in the path names an existing row of the expected entity."

    Design: Corner/entities/root_entity_lookups_report_their_own_not_found_codes
    """
    # One well-formed but unknown identifier, three root aggregates, three codes.
    validate_error(client.get_issuer(NON_EXISTENT_UUID, compliance), ERR_ISSUER_NOT_FOUND)
    validate_error(client.get_firm(NON_EXISTENT_UUID, compliance), ERR_FIRM_NOT_FOUND)
    validate_error(client.get_deal(NON_EXISTENT_UUID, compliance), ERR_DEAL_NOT_FOUND)


def test_deal_child_lookups_report_their_own_not_found_codes(client, compliance):
    """PRD 2.5: "On every endpoint with a path parameter, the identifier in the path names an existing row of the expected entity."

    Design: Corner/entities/deal_child_lookups_report_their_own_not_found_codes
    """
    # PRD section 2.5 resolves the acting identity at tier 3, before path
    # existence at tier 4, so the two IssuerOfficial actions below need a real
    # issuer behind X-User-ID for the 404 to be the observable failure.
    issuer = fx.register_issuer(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    issuer_headers = make_issuer_official_headers(issuer["id"])

    validate_error(
        client.get_maturity_tranche(NON_EXISTENT_UUID, compliance), ERR_TRANCHE_NOT_FOUND
    )
    # CreditEnhancement has no read-by-id route, so its own 404 is reached
    # through the commit action -- and the action's existence check must fire
    # before its tier-11 state check.
    validate_error(
        client.commit_credit_enhancement(NON_EXISTENT_UUID, None, issuer_headers),
        ERR_ENHANCEMENT_NOT_FOUND,
    )
    validate_error(
        client.get_official_statement(NON_EXISTENT_UUID, compliance),
        ERR_OFFICIAL_STATEMENT_NOT_FOUND,
    )
    validate_error(
        client.get_os_section(NON_EXISTENT_UUID, compliance), ERR_SECTION_NOT_FOUND
    )
    validate_error(
        client.activate_undertaking(NON_EXISTENT_UUID, None, issuer_headers),
        ERR_UNDERTAKING_NOT_FOUND,
    )
    validate_error(
        client.get_rating_engagement(NON_EXISTENT_UUID, compliance),
        ERR_RATING_ENGAGEMENT_NOT_FOUND,
    )
    validate_error(
        client.get_presentation(NON_EXISTENT_UUID, compliance), ERR_PRESENTATION_NOT_FOUND
    )


def test_order_book_and_closing_document_lookups_report_not_found(client, compliance):
    """PRD 2.5: "On every endpoint with a path parameter, the identifier in the path names an existing row of the expected entity."

    Design: Corner/entities/order_book_and_closing_document_lookups_report_not_found
    """
    # A ComplianceOfficer is authorised on all three routes, so a 403 in place of
    # any of these 404s would mean the existence check ran behind the wrong gate.
    validate_error(
        client.get_order_period(NON_EXISTENT_UUID, compliance), ERR_ORDER_PERIOD_NOT_FOUND
    )
    validate_error(client.get_order(NON_EXISTENT_UUID, compliance), ERR_ORDER_NOT_FOUND)
    validate_error(
        client.get_closing_document(NON_EXISTENT_UUID, compliance),
        ERR_CLOSING_DOCUMENT_NOT_FOUND,
    )


def test_tranche_creation_under_an_unknown_deal_reports_deal_not_found(client):
    """PRD 2.10: "The same precedence governs creation: when a child is created under a parent, the parent's existence is established before any field of the child is examined, and before any business rule of the child is evaluated."

    Design: Corner/entities/tranche_creation_requires_an_existing_parent_deal
    """
    advisor_firm = fx.register_advisor_firm(client)
    advisor_headers = make_advisor_headers(advisor_firm["id"])

    # The body carries a maturity_date one month off the semiannual anniversary,
    # which would be ERR_MATURITY_DATE_UNALIGNED if the child's fields were read.
    payload = f.tranche_payload(
        1,
        UNALIGNED_MATURITY_DATE,
        principal_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )

    response = client.create_maturity_tranche(
        NON_EXISTENT_UUID, payload, advisor_headers
    )
    error = validate_error(response, ERR_DEAL_NOT_FOUND)
    assert error["error_id"] != ERR_MATURITY_DATE_UNALIGNED


def _two_deals_one_maturity_each(client):
    """One issuer, two DRAFT deals, one 5,000,000 maturity on each."""
    ctx = fx.participants(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    ctx.deal_a = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    ctx.deal_b = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    ctx.tranche_a = fx.add_tranche(
        client, ctx.deal_a["id"], ctx.advisor_headers, _first_maturity_payload()
    )
    ctx.tranche_b = fx.add_tranche(
        client, ctx.deal_b["id"], ctx.advisor_headers, _first_maturity_payload()
    )
    return ctx


def test_enhancement_may_not_insure_a_tranche_of_another_deal(client):
    """PRD 3.3: "That list must hold between one and forty distinct maturity identifiers, and every identifier in it must belong to the same deal as the enhancement; a duplicated identifier, an empty list, or a `premium_bps` outside the range of one through two hundred reports `ERR_ENHANCEMENT_ALREADY_COMMITTED`, while an identifier belonging to another deal reports `ERR_CROSS_DEAL_REFERENCE` at the earlier integrity tier."

    Design: Corner/entities/enhancement_may_not_insure_a_tranche_of_another_deal
    """
    ctx = _two_deals_one_maturity_each(client)

    # The referenced maturity exists and shares the issuer, so this is neither a
    # 404 nor an ownership failure -- only the deal boundary is crossed.
    validate_error(
        client.create_credit_enhancement(
            ctx.deal_b["id"],
            f.enhancement_payload([ctx.tranche_a["id"]]),
            ctx.advisor_headers,
        ),
        ERR_CROSS_DEAL_REFERENCE,
    )

    rejected_state, rejected_meta = validate_paginated(
        client.list_deal_credit_enhancements(ctx.deal_b["id"], ctx.advisor_headers)
    )
    assert rejected_state == []
    assert_pagination(rejected_meta, total_count=0, has_more=False)

    # The identical call against the deal's own maturity is accepted.
    enhancement = validate_success(
        client.create_credit_enhancement(
            ctx.deal_b["id"],
            f.enhancement_payload([ctx.tranche_b["id"]]),
            ctx.advisor_headers,
        ),
        201,
    )
    assert enhancement["status"] == EnhancementStatus.PROPOSED
    assert enhancement["insured_tranche_ids"] == [ctx.tranche_b["id"]]


def test_refunding_tranche_rejects_a_prior_deal_that_is_not_closed(client):
    """PRD 3.2: "The referenced maturity must belong to a deal whose `status` is `CLOSED`, must not already be named as the `refunded_tranche_id` of some other maturity, and must not be the maturity itself; any of those three failures reports `ERR_REFUNDED_TRANCHE_INVALID`."

    Design: Corner/entities/refunding_tranche_rejects_a_prior_deal_that_is_not_closed
    """
    ctx = fx.participants(client, name=FAIRHAVEN_NAME, state_code=OHIO_STATE_CODE)
    prior_deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    prior_maturity = fx.add_tranche(
        client, prior_deal["id"], ctx.advisor_headers, _first_maturity_payload()
    )
    refunding_deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )

    # A different deal of the same issuer, so the tier-9 integrity rule is
    # satisfied and only refunding eligibility can fail.
    assert prior_deal["id"] != refunding_deal["id"]
    assert prior_deal["issuer_id"] == refunding_deal["issuer_id"]

    validate_error(
        client.create_maturity_tranche(
            refunding_deal["id"],
            _first_maturity_payload(refunded_tranche_id=prior_maturity["id"]),
            ctx.advisor_headers,
        ),
        ERR_REFUNDED_TRANCHE_INVALID,
    )

    # The refunded deal never reached CLOSED, which is the whole reason.
    assert fx.read_deal(client, prior_deal["id"], ctx.advisor_headers)["status"] == (
        DealStatus.DRAFT
    )
    _, meta = validate_paginated(
        client.list_deal_maturity_tranches(refunding_deal["id"], ctx.advisor_headers)
    )
    assert_pagination(meta, total_count=0, has_more=False)


def test_one_firm_holds_syndicate_seats_on_two_deals(client, compliance):
    """PRD 3.6: "Uniqueness is enforced three ways — a firm may not hold more than one seat on the deal that is not `RESIGNED`, a deal may have at most one `SENIOR_MANAGER`, and `priority_rank` may not collide among `ACTIVE` members — and all three report `ERR_DUPLICATE_SYNDICATE_MEMBER`."

    Design: Corner/entities/one_firm_holds_syndicate_seats_on_two_deals
    """
    ctx = _two_deals_one_maturity_each(client)
    seat_payload = f.syndicate_member_payload(
        ctx.underwriter_firm_id,
        MemberRole.SENIOR_MANAGER,
        liability_pct=LIABILITY_PCT_TOTAL,
        takedown_share_pct=LIABILITY_PCT_TOTAL,
        priority_rank=1,
    )

    seat_a = validate_success(
        client.create_syndicate_member(
            ctx.deal_a["id"], dict(seat_payload), ctx.advisor_headers
        ),
        201,
    )
    # The same firm, role and priority_rank on a second deal: uniqueness is
    # scoped per deal, so this is not a duplicate.
    seat_b = validate_success(
        client.create_syndicate_member(
            ctx.deal_b["id"], dict(seat_payload), ctx.advisor_headers
        ),
        201,
    )
    assert seat_b["id"] != seat_a["id"]

    for seat in (seat_a, seat_b):
        assert seat["status"] == MemberStatus.ACTIVE
        assert seat["firm_id"] == ctx.underwriter_firm_id
        assert seat["member_role"] == MemberRole.SENIOR_MANAGER
        # Neither deal has submitted its structure, so par_amount_usd is still 0.
        assert_money(seat["liability_par_usd"], 0, "member.liability_par_usd")

    firm_side, firm_meta = validate_paginated(
        client.list_firm_syndicate_memberships(
            ctx.underwriter_firm_id, compliance, status=MemberStatus.ACTIVE
        )
    )
    assert_pagination(firm_meta, total_count=2, has_more=False)
    assert set(ids_of(firm_side)) == {seat_a["id"], seat_b["id"]}

    deal_side, deal_meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_a["id"], ctx.advisor_headers)
    )
    assert_pagination(deal_meta, total_count=1, has_more=False)
    assert ids_of(deal_side) == [seat_a["id"]]

    assert_money(
        fx.read_deal(client, ctx.deal_a["id"], ctx.advisor_headers)["par_amount_usd"],
        0,
        "deal.par_amount_usd",
    )
