"""Creation, defaults, computed fields, listing and retrieval of the base entities."""
from test_helpers import (
    FILING_FY2025,
    create_filing_record_payload,
    create_methodology_version_payload,
    create_organization,
    create_organization_payload,
    is_iso8601_timestamp,
    organization_version,
    read_filing,
    read_organization,
    setup_scored_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_registration_populates_the_five_rollup_fields_empty(api, admin_headers):
    """A charity registered today has no publication history, so its trend reads the
    NOT_APPLICABLE sentinel rather than UNCHANGED.

    PRD §3.3: "`latest_published_score` and `latest_published_grade` mirror the `published_score` and `published_grade` of that organization's `PublicationRecord` with the highest `sequence_number`, and both start null."

    PRD §3.3: "`trend_direction` is the `change_direction` of that same highest-sequence record, with a `FIRST_PUBLICATION` value mapped to `NOT_APPLICABLE`, and takes the values `NOT_APPLICABLE`, `IMPROVED`, `UNCHANGED` and `DECLINED`; it starts at `NOT_APPLICABLE`."

    Design: Corner/entities/organization_creation_returns_201_with_empty_rollups
    """
    create_organization()

    payload = create_organization_payload(
        legal_name="Northgate Youth Services",
        ein="555555555",
        org_type="MEMBERSHIP_ASSOCIATION",
        fiscal_year_end_month=6,
        contact_email="admin@northgateyouth.org",
    )
    created = validate_success(api.create_organization(payload, admin_headers), 201)

    assert created["legal_name"] == "Northgate Youth Services"
    assert created["ein"] == "555555555"
    assert created["org_type"] == "MEMBERSHIP_ASSOCIATION"
    assert created["fiscal_year_end_month"] == 6
    assert created["contact_email"] == "admin@northgateyouth.org"
    assert created["latest_published_score"] is None
    assert created["latest_published_grade"] is None
    assert created["published_cycle_count"] == 0
    assert created["substantiated_complaint_count"] == 0
    assert created["trend_direction"] == "NOT_APPLICABLE"
    assert created["transition_grace_until"] is None

    stored = read_organization(created["id"], admin_headers)
    assert stored["id"] == created["id"]
    assert stored["trend_direction"] == "NOT_APPLICABLE"
    assert stored["published_cycle_count"] == 0


def test_the_three_optional_methodology_inputs_take_their_documented_defaults(
    api, admin_headers
):
    """Omitting the floor, the comment period and the transition period yields 40.0, 30
    and 90, while a version that supplied them keeps what it supplied.

    PRD §3.1: "Three further inputs are optional and take documented defaults when omitted: `dimension_floor_score`, the minimum normalized score every included dimension must reach for the two highest grades, defaults to 40.0 and may be set anywhere from 0.00 to 100.00; `comment_period_days` defaults to 30 and is constrained to 7 through 120; and `transition_period_days` defaults to 90 and is constrained to 0 through 365."

    PRD §3.1: "A freshly drafted version has `status` `DRAFT`, a `comment_count` of 0 and an `unresolved_comment_count` of 0, and all of `comment_open_at`, `comment_deadline_at`, `comment_closed_at`, `adopted_at`, `retired_at`, `effective_from` and `effective_until` are null."

    Design: Corner/entities/methodology_version_defaults_applied_when_optional_fields_omitted
    """
    explicit = validate_success(
        api.create_methodology_version(
            create_methodology_version_payload(
                version_label="M0",
                weight_financial_health=0.25,
                weight_accountability=0.25,
                weight_transparency=0.25,
                weight_impact=0.25,
                dimension_floor_score=55.0,
                comment_period_days=7,
                transition_period_days=45,
            ),
            admin_headers,
        ),
        201,
    )

    payload = create_methodology_version_payload()
    payload.pop("dimension_floor_score")
    defaulted = validate_success(
        api.create_methodology_version(payload, admin_headers), 201
    )

    assert float(defaulted["dimension_floor_score"]) == 40.0
    assert defaulted["comment_period_days"] == 30
    assert defaulted["transition_period_days"] == 90
    assert defaulted["status"] == "DRAFT"
    assert defaulted["comment_count"] == 0
    assert defaulted["unresolved_comment_count"] == 0
    for field in (
        "supersedes_version_id",
        "comment_open_at",
        "comment_closed_at",
        "comment_deadline_at",
        "adopted_at",
        "retired_at",
        "effective_from",
        "effective_until",
        "revision_note",
    ):
        assert defaulted[field] is None, f"{field} should start null"

    unchanged = validate_success(
        api.get_methodology_version(explicit["id"], admin_headers)
    )
    assert float(unchanged["dimension_floor_score"]) == 55.0
    assert unchanged["comment_period_days"] == 7
    assert unchanged["transition_period_days"] == 45


def test_a_flattering_publication_history_supplied_at_registration_is_ignored_not_refused(
    api, admin_headers
):
    """The charity cannot register itself with a 99.99 score and three published cycles:
    the unknown keys are dropped and the roll-ups stay empty.

    PRD §2.8: "**Body well-formedness.** On every endpoint that takes a request body: every required input field is present, every enum value falls inside its declared set, every integer declared non-negative is non-negative, every timestamp is a valid ISO 8601 UTC instant, and any unknown field is silently ignored rather than rejected."

    PRD §3.3: "Six roll-up fields on an organization are maintained by the system and never written by a client."

    Design: Corner/entities/organization_rollup_fields_input_ignored
    """
    create_organization()

    payload = create_organization_payload(
        legal_name="Summit Aid Trust",
        ein="555555555",
        contact_email="hello@summitaid.org",
        latest_published_score=99.99,
        latest_published_grade="ACCREDITED",
        published_cycle_count=3,
        trend_direction="IMPROVED",
        substantiated_complaint_count=7,
    )
    created = validate_success(api.create_organization(payload, admin_headers), 201)

    assert created["latest_published_score"] is None
    assert created["latest_published_grade"] is None
    assert created["published_cycle_count"] == 0
    assert created["substantiated_complaint_count"] == 0
    assert created["trend_direction"] == "NOT_APPLICABLE"

    stored = read_organization(created["id"], admin_headers)
    assert stored["latest_published_score"] is None
    assert stored["published_cycle_count"] == 0
    assert stored["substantiated_complaint_count"] == 0


def test_a_filing_that_omits_contributions_is_refused_and_spends_no_version(
    api, analyst_headers
):
    """The fundraising denominator is mandatory with no default, so a filing without it
    is refused outright rather than stored with a zero.

    PRD §3.3: "Eight monetary figures are mandatory and are all expressed in whole cents, each of which must be zero or greater: `total_expense_cents`, `program_expense_cents`, `fundraising_expense_cents`, `admin_expense_cents`, `contributions_cents`, `total_revenue_cents`, `net_assets_cents` and `total_liabilities_cents`."

    Design: Corner/entities/filing_record_missing_required_contributions_returns_invalid_request
    """
    organization = create_organization()
    version_before = organization_version(organization["id"])

    payload = create_filing_record_payload(organization["id"], version_before)
    payload.pop("contributions_cents")
    response = api.create_filing_record(payload, analyst_headers)
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api.list_organization_filing_records(organization["id"], analyst_headers)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert organization_version(organization["id"]) == version_before


def test_an_unrecognised_org_type_and_a_thirteenth_month_are_both_refused_at_the_door(
    api, admin_headers
):
    """Neither an org type outside the five declared values nor a fiscal month of 13 is
    stored, because both feed calculations with no defined behaviour for them.

    PRD §3.3: "It takes a `legal_name` of 1 to 200 non-blank characters, an `ein` — the charity's public tax identifier, exactly nine digits, unique across every registered organization, with a collision refused as `ERR_DUPLICATE_EIN` — an `org_type` drawn from `PUBLIC_CHARITY`, `PRIVATE_FOUNDATION`, `RELIGIOUS_CONGREGATION`, `DONOR_ADVISED_SPONSOR` and `MEMBERSHIP_ASSOCIATION`, a `fiscal_year_end_month` between 1 and 12 naming the calendar month in which the charity closes its books, and a `contact_email` that must contain an at-sign and which is the address that receives publication change notifications."

    Design: Corner/entities/organization_create_invalid_enum_org_type_rejected
    """
    create_organization()

    bad_enum = api.create_organization(
        create_organization_payload(
            legal_name="Cooperative Care Network",
            ein="555555555",
            org_type="COOPERATIVE",
            contact_email="info@coopcare.org",
        ),
        admin_headers,
    )
    validate_error(bad_enum, "ERR_INVALID_REQUEST", 400)

    bad_month = api.create_organization(
        create_organization_payload(
            legal_name="Thirteenth Month Trust",
            ein="666666666",
            fiscal_year_end_month=13,
            contact_email="info@13month.org",
        ),
        admin_headers,
    )
    validate_error(bad_month, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(api.list_organizations(admin_headers))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_the_three_optional_cent_amounts_default_to_zero_and_the_derived_fields_are_derived(
    api, analyst_headers
):
    """A filing that reports no grants, member services or joint cost stores integer
    zeros, and its precedence and origin come from the source kind and the acting role.

    PRD §3.3: "Three more are optional and default to 0 when omitted: `grants_paid_cents`, the grants this charity paid onward to other organizations; `membership_services_cents`, member-services spend; and `joint_cost_allocated_cents`, the joint costs allocated out of fundraising appeals and into program services."

    PRD §3.3: "`origin` records how the row arrived: `ORG_PORTAL` when the submitter was an `OrganizationRep`, `ANALYST_ENTRY` when it was a `RatingAnalyst`, and `CORRECTION_APPLIED` for the replacement rows the correction and appeal machinery synthesizes."

    PRD §3.3: "`validated_at`, `rejection_code` and `superseded_at` all start null, and the submission advances the parent organization's `version` counter by one."

    Design: Corner/entities/filing_record_optional_cent_amounts_default_to_zero
    """
    organization = create_organization()
    created = validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"], organization_version(organization["id"])
            ),
            analyst_headers,
        ),
        201,
    )

    assert created["grants_paid_cents"] == 0
    assert created["membership_services_cents"] == 0
    assert created["joint_cost_allocated_cents"] == 0
    assert created["source_precedence"] == 1
    assert created["origin"] == "ANALYST_ENTRY"
    assert created["status"] == "RECEIVED"
    assert created["validated_at"] is None
    assert created["rejection_code"] is None
    assert created["superseded_at"] is None

    stored = read_filing(created["id"], analyst_headers)
    assert stored["grants_paid_cents"] == 0
    assert stored["membership_services_cents"] == 0
    assert stored["joint_cost_allocated_cents"] == 0


def test_the_organization_listing_counts_the_filter_not_the_page(api, public_headers):
    """Paging two at a time across three charities reports the same total on both pages
    while `has_more` flips, and a type filter shrinks the total itself.

    PRD §2.3: "For list responses the `meta` object carries all four pagination fields: `limit` and `offset` echo the effective values actually applied, `total_count` is the number of rows matching the filters before the window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/organization_listing_paginates_with_total_count_and_has_more
    """
    create_organization()
    association = create_organization(
        legal_name="Northgate Youth Services",
        ein="555555555",
        org_type="MEMBERSHIP_ASSOCIATION",
        fiscal_year_end_month=6,
        contact_email="admin@northgateyouth.org",
    )
    create_organization(
        legal_name="Riverbend Shelter",
        ein="666666666",
        contact_email="info@riverbend.org",
    )

    page1, meta1 = validate_paginated(
        api.list_organizations(public_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_organizations(public_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["offset"] == 2
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["id"] != page1[0]["id"]

    filtered, meta3 = validate_paginated(
        api.list_organizations(
            public_headers, params={"org_type": "MEMBERSHIP_ASSOCIATION"}
        )
    )
    assert [row["id"] for row in filtered] == [association["id"]]
    assert meta3["total_count"] == 1
    assert meta3["has_more"] is False


def test_a_newborn_cycle_reads_back_with_its_pin_already_locked_and_every_figure_null(api):
    """The charity's own representative reads the cycle and sees the methodology pin
    already taken, with nothing scored yet.

    PRD §3.5: "A newborn cycle sits in `DATA_COLLECTION` with `correction_round` at 0, `methodology_pin_locked` already true, `publishing_reviewer_user_id` null, and every timing and score field null: `review_opened_at`, `correction_deadline_at`, `appeal_deadline_at`, `published_at`, `program_expense_ratio`, `fundraising_efficiency`, `months_of_reserve`, `data_completeness_pct`, `weighted_sum_provisional`, `provisional_composite_score`, `provisional_grade`, `weighted_sum_final`, `final_composite_score`, `grade`, `standards_penalty_points` and `withdrawal_reason`."

    PRD §3.5: "Its `failed_standard_count` and `accountability_penalty_points` start at 0."

    Design: Corner/entities/rating_cycle_retrieval_returns_stored_workflow_fields
    """
    scenario = setup_scored_cycle(
        filings=[(2025, FILING_FY2025)], evaluate=False, score=False
    )
    cycle = validate_success(
        api.get_rating_cycle(scenario["cycle"]["id"], scenario["org_rep_headers"])
    )

    assert cycle["id"] == scenario["cycle"]["id"]
    assert cycle["organization_id"] == scenario["organization"]["id"]
    assert cycle["methodology_version_id"] == scenario["methodology"]["id"]
    assert cycle["fiscal_year"] == 2025
    assert cycle["assigned_analyst_user_id"] == scenario["analyst_user_id"]
    assert is_iso8601_timestamp(cycle["period_start"])
    assert is_iso8601_timestamp(cycle["period_end"])
    assert cycle["status"] == "DATA_COLLECTION"
    assert cycle["correction_round"] == 0
    assert cycle["methodology_pin_locked"] is True
    assert cycle["failed_standard_count"] == 0
    assert cycle["accountability_penalty_points"] == 0
    for field in (
        "publishing_reviewer_user_id",
        "review_opened_at",
        "correction_deadline_at",
        "appeal_deadline_at",
        "published_at",
        "withdrawal_reason",
        "program_expense_ratio",
        "fundraising_efficiency",
        "months_of_reserve",
        "data_completeness_pct",
        "weighted_sum_provisional",
        "provisional_composite_score",
        "provisional_grade",
        "weighted_sum_final",
        "final_composite_score",
        "grade",
    ):
        assert cycle[field] is None, f"{field} should be null on a newborn cycle"
