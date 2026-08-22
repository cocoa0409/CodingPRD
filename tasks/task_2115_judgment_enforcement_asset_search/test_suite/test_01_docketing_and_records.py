"""Opening a file: creditors, debtors, docketed judgments and their record shape."""

from test_helpers import (
    ApiErrorId,
    assert_asset_finding,
    assert_debtor,
    assert_judgment,
    create_asset_finding_payload,
    create_creditor,
    create_debtor,
    create_debtor_payload,
    create_enforcement_action_payload,
    create_judgment,
    create_judgment_payload,
    create_open_finding,
    make_asset_investigator_headers,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_debtor_headers,
    setup_judgment,
    tender_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
INV = make_asset_investigator_headers()


def test_docketing_a_judgment_stamps_the_opening_position(api):
    """PRD §3.1: "Upon docketing, the server stamps the opening position.
    `expires_on` is set to ten calendar years after `entered_on`, where
    calendar-year arithmetic means the same month and day that many years later,
    with the twenty-ninth of February mapping to the twenty-eighth."
    PRD §3.1: "The lifecycle `status` begins at `ACTIVE`, the
    `enforcement_posture` at `NONE`, and the `application_order` at
    `STATUTORY_ORDER`."

    Design: Corner/entities/create_judgment_returns_seeded_balances_and_computed_expiry
    """
    creditor = create_creditor()
    debtor = create_debtor()

    resp = api.create_judgment(
        create_judgment_payload(
            creditor["id"],
            debtor["id"],
            court_case_number="CV-2026-1001",
            state_code="CA",
            original_principal_cents=5_000_000,
            interest_rate_bps=1_000,
            entered_on="2026-01-01",
            filing_costs_cents=45_000,
        ),
        CM,
    )
    judgment = validate_success(resp, 201)
    assert_judgment(judgment)

    assert judgment["expires_on"] == "2036-01-01"
    assert judgment["principal_balance_cents"] == 5_000_000
    assert judgment["costs_balance_cents"] == 45_000
    assert judgment["accrued_interest_cents"] == 290_411
    assert judgment["total_payoff_cents"] == 5_335_411
    assert judgment["status"] == "ACTIVE"
    assert judgment["enforcement_posture"] == "NONE"
    assert judgment["application_order"] == "STATUTORY_ORDER"
    assert judgment["version"] == 1


def test_reading_a_judgment_returns_the_stored_row(api):
    """PRD §3.1: "Docketing the judgment itself binds a creditor and a debtor
    together through `creditor_id` and `debtor_id` and records what the court
    decided."
    PRD §3.1: "`principal_balance_cents` is seeded from `original_principal_cents`
    and `costs_balance_cents` from `filing_costs_cents`, `accrued_interest_cents`
    starts at zero, and the balances are then replayed forward to the current
    clock date so that `total_payoff_cents`, `gross_exposure_cents` and
    `accrued_through_on` are correct from the first read."

    Design: Corner/entities/get_judgment_returns_the_stored_row
    """
    ctx = setup_judgment(court_case_number="CV-2026-1002")

    data = validate_success(
        api.get_judgment(ctx["judgment"]["id"], make_compliance_officer_headers())
    )
    assert_judgment(data)
    assert data["court_case_number"] == "CV-2026-1002"
    assert data["total_payoff_cents"] == 5_335_411


def test_listing_judgments_reports_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before pagination is
    applied) and `has_more` (true when `offset` plus the number of returned rows
    is still less than `total_count`)."

    Design: Corner/entities/list_judgments_paginates_with_total_count_and_has_more
    """
    creditor = create_creditor()
    debtor = create_debtor()
    for _ in range(3):
        create_judgment(
            creditor["id"], debtor["id"],
            original_principal_cents=100_000, interest_rate_bps=0,
        )

    page_one, meta_one = validate_paginated(
        api.list_judgments(CM, {"limit": 2, "offset": 0})
    )
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_one) == 2

    page_two, meta_two = validate_paginated(
        api.list_judgments(CM, {"limit": 2, "offset": 2})
    )
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(page_two) == 1


def test_reading_an_unknown_judgment_id_returns_not_found(api):
    """PRD §2.8: "Every identifier embedded in the URL path resolves to a stored
    row, validated left to right, each reported with its own code:
    `ERR_JUDGMENT_NOT_FOUND`, `ERR_DEBTOR_NOT_FOUND`, `ERR_COUNTY_FILING_NOT_FOUND`,
    `ERR_ASSET_FINDING_NOT_FOUND`, `ERR_ENFORCEMENT_ACTION_NOT_FOUND`,
    `ERR_EXEMPTION_CLAIM_NOT_FOUND`, `ERR_EXAMINATION_NOT_FOUND`,
    `ERR_SETTLEMENT_OFFER_NOT_FOUND`, `ERR_INSTALLMENT_AGREEMENT_NOT_FOUND` or
    `ERR_PAYMENT_NOT_FOUND`."

    Design: Corner/entities/get_judgment_with_unknown_id_returns_not_found
    """
    setup_judgment(original_principal_cents=100_000, interest_rate_bps=0)

    resp = api.get_judgment("00000000-0000-4000-8000-0000000000ff", CM)
    validate_error(resp, ApiErrorId.ERR_JUDGMENT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_docketing_without_entered_on_is_rejected(api):
    """PRD §2.8: "Every non-optional field in the endpoint's input is present and
    carries the declared JSON type — otherwise `ERR_INVALID_REQUEST` and HTTP 400."
    PRD §3.1: "`entered_on`, the calendar date of entry, which is the instant from
    which interest begins to run"

    Design: Corner/entities/create_judgment_missing_required_entered_on_returns_invalid_request
    """
    creditor = create_creditor()
    debtor = create_debtor()

    payload = {
        "creditor_id": creditor["id"],
        "debtor_id": debtor["id"],
        "court_case_number": "CV-2026-1007",
        "state_code": "CA",
        "original_principal_cents": 100_000,
        "interest_rate_bps": 0,
    }
    validate_error(
        api.create_judgment(payload, CM), ApiErrorId.ERR_INVALID_REQUEST.value, 400
    )

    _rows, meta = validate_paginated(api.list_judgments(CM))
    assert meta["total_count"] == 0, "a rejected docketing must not create a row"


def test_registering_a_debtor_applies_the_declared_defaults(api):
    """PRD §3.1: "`head_of_household` is the debtor's household declaration and
    defaults to false when omitted."
    PRD §3.1: "`weekly_disposable_earnings_cents` is the debtor's weekly disposable
    earnings in cents, defaults to 0, and may not be negative."
    PRD §3.1: "Four investigative counters are server-owned: a freshly registered
    debtor has `locate_status` of `UNLOCATED`, a `skip_trace_count` of 0, a
    `no_show_count` of 0, and no `last_skip_trace_on` at all until the first trace
    runs."
    PRD §3.1: "Its `recoverability_score` is 20 on the day it is created — the
    cooperation component alone, since no assets are known and the debtor is not
    yet located — and its `certified_recoverability_score` is null and stays null
    until a writ is first requested against one of that debtor's judgments."

    Design: Corner/entities/create_debtor_applies_declared_defaults
    """
    create_creditor()

    debtor = validate_success(
        api.create_debtor(create_debtor_payload(), CM), 201
    )
    assert_debtor(debtor)
    assert debtor["head_of_household"] is False
    assert debtor["weekly_disposable_earnings_cents"] == 0
    assert debtor["locate_status"] == "UNLOCATED"
    assert debtor["no_show_count"] == 0
    assert debtor["skip_trace_count"] == 0
    assert debtor["recoverability_score"] == 20
    assert debtor.get("certified_recoverability_score") is None


def test_new_asset_finding_opens_with_its_whole_value_available(api):
    """PRD §3.3: "A new finding begins in `OPEN`, with `available_cents`
    initialised to `estimated_value_cents`, `frozen_cents` at 0 and `swept_cents`
    at 0, and its creation recomputes the debtor's preliminary recoverability
    score."

    Design: Corner/entities/asset_finding_available_cents_computed_from_estimated_value
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)

    finding = validate_success(
        api.create_asset_finding(
            create_asset_finding_payload(
                ctx["judgment"]["id"], estimated_value_cents=900_000
            ),
            INV,
        ),
        201,
    )
    assert_asset_finding(finding)
    assert finding["available_cents"] == 900_000
    assert finding["frozen_cents"] == 0
    assert finding["swept_cents"] == 0
    assert finding["status"] == "OPEN"
    assert finding.get("verified_by_user_id") is None


def test_judgment_identity_fields_are_server_minted(api):
    """PRD §2.4: "Every stored object carries an `id` that the server mints as a
    UUID at creation time."
    PRD §2.4: "Identifiers are bare UUIDs with no type prefix and no embedded
    semantics; clients must never parse them."
    PRD §2.4: "Every object also carries `created_at` and `updated_at`, both ISO
    8601 UTC timestamps with three fractional digits, and a `version` that starts
    at 1 when the row is created and increments by exactly 1 on every mutation of
    that row."

    Design: Corner/entities/judgment_system_fields_are_server_minted
    """
    from test_helpers import assert_iso_millis_timestamp, BARE_UUID_RE

    creditor = create_creditor()
    debtor = create_debtor()
    judgment = validate_success(
        api.create_judgment(
            create_judgment_payload(
                creditor["id"], debtor["id"],
                court_case_number="CV-2026-1009",
                original_principal_cents=100_000, interest_rate_bps=0,
            ),
            CM,
        ),
        201,
    )

    assert BARE_UUID_RE.match(judgment["id"]), "id must be a bare RFC 4122 UUID"
    assert "_" not in judgment["id"], "id must carry no type prefix"
    assert judgment["version"] == 1
    assert_iso_millis_timestamp(judgment["created_at"], "created_at")
    assert_iso_millis_timestamp(judgment["updated_at"], "updated_at")


def test_asset_finding_with_an_unknown_asset_type_is_rejected(api):
    """PRD §2.8: "Every enum-typed input carries a value from that field's declared
    set — otherwise `ERR_INVALID_ENUM` and HTTP 400."
    PRD §3.3: "`asset_type` is one of `REAL_PROPERTY`, `BANK_ACCOUNT`,
    `EMPLOYMENT` or `VEHICLE`"

    Design: Corner/entities/create_asset_finding_with_invalid_enum_asset_type_rejected
    """
    ctx = setup_judgment(original_principal_cents=100_000, interest_rate_bps=0)

    resp = api.create_asset_finding(
        create_asset_finding_payload(
            ctx["judgment"]["id"],
            asset_type="CRYPTO_WALLET",
            institution_name="Cold Storage",
            identifier_last4="0001",
        ),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 400)


def test_docketing_with_zero_principal_is_rejected(api):
    """PRD §2.8: "Monetary and count inputs satisfy their sign constraints —
    otherwise `ERR_NON_POSITIVE_AMOUNT` and HTTP 400. `original_principal_cents`,
    `amount_cents`, `claimed_amount_cents`, `installment_count` and `hits_count`
    must be strictly greater than zero; `fee_cents`, `filing_costs_cents`,
    `estimated_value_cents`, `weekly_disposable_earnings_cents` and
    `interest_rate_bps` must be zero or greater."

    Design: Corner/entities/create_judgment_with_zero_principal_rejected
    """
    creditor = create_creditor()
    debtor = create_debtor()

    resp = api.create_judgment(
        create_judgment_payload(
            creditor["id"], debtor["id"],
            court_case_number="CV-2026-1011",
            original_principal_cents=0,
            interest_rate_bps=1_000,
            filing_costs_cents=0,
        ),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_NON_POSITIVE_AMOUNT.value, 400)


def test_drafting_against_an_unknown_asset_finding_is_not_found(api):
    """PRD §2.8: "Every foreign key supplied in the request body resolves,
    validated in this field order: `creditor_id`, `debtor_id`, `judgment_id`,
    `asset_finding_id`, `enforcement_action_id`, `responds_to_offer_id`,
    `installment_agreement_id`."

    Design: Corner/entities/create_enforcement_action_with_unknown_finding_returns_not_found
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)

    resp = api.create_enforcement_action(
        create_enforcement_action_payload(
            ctx["judgment"]["id"],
            "00000000-0000-4000-8000-0000000000aa",
            ctx["judgment"]["version"],
        ),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_FINDING_NOT_FOUND.value, 404)


def test_asset_findings_are_discovered_by_filtering_on_their_judgment(api):
    """PRD §2.3: "Asset findings accept `judgment_id`, `asset_type`, `status` and
    `source`."
    PRD §2: "Collections are mounted flat at the root — there is no nesting in URL
    paths, and a child object is always discovered by filtering its own collection
    on the foreign key it carries."

    Design: Corner/entities/list_asset_findings_filtered_by_judgment_id_returns_only_that_judgments_children
    """
    creditor = create_creditor()
    debtor = create_debtor()
    judgment_a = create_judgment(
        creditor["id"], debtor["id"], interest_rate_bps=0, filing_costs_cents=0
    )
    judgment_b = create_judgment(
        creditor["id"], debtor["id"], interest_rate_bps=0, filing_costs_cents=0
    )

    finding_a = create_open_finding(
        judgment_a["id"], asset_type="VEHICLE", institution_name="CA DMV",
        identifier_last4="AAA1", estimated_value_cents=500_000,
    )
    finding_b1 = create_open_finding(judgment_b["id"], estimated_value_cents=900_000)
    finding_b2 = create_open_finding(
        judgment_b["id"], asset_type="REAL_PROPERTY",
        institution_name="LA County Recorder", identifier_last4="0042",
        estimated_value_cents=2_000_000,
    )

    rows, meta = validate_paginated(
        api.list_asset_findings(INV, {"judgment_id": judgment_b["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {finding_b1["id"], finding_b2["id"]}
    assert finding_a["id"] not in {row["id"] for row in rows}


def test_the_cascade_created_agreement_is_found_only_by_a_filtered_list(api):
    """PRD §3.7: "This agreement is never created directly by a client and is
    discoverable only by listing agreements and filtering on `judgment_id` or
    `settlement_offer_id`."
    PRD §3.7: "First an installment agreement is created in status `ACTIVE`,
    carrying the accepted offer's `judgment_id` and `settlement_offer_id`, with
    `total_cents` copied from the offer's `amount_cents`, `installment_count`
    copied from the offer, `monthly_cents` equal to `total_cents` divided by
    `installment_count` rounded up to a whole cent, `final_installment_cents`
    equal to `total_cents` less `monthly_cents` multiplied by one fewer than
    `installment_count`, `first_due_on` set to 30 days after the current clock
    date, `application_order_concession` copied from the offer, and
    `paid_to_date_cents`, `missed_count` and `reinstatement_count` all at 0."

    Design: Corner/entities/cascade_created_installment_agreement_is_reachable_only_by_filtered_list
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    offer = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR",
        kind="INSTALLMENT",
        amount_cents=3_000_000,
        installment_count=12,
    )
    assert offer["min_acceptable_cents"] == 3_000_000

    validate_success(api.accept_settlement_offer(offer["id"], CM))

    rows, meta = validate_paginated(
        api.list_installment_agreements(CM, {"settlement_offer_id": offer["id"]})
    )
    assert meta["total_count"] == 1
    agreement = rows[0]
    assert agreement["status"] == "ACTIVE"
    assert agreement["total_cents"] == 3_000_000
    assert agreement["monthly_cents"] == 250_000
    assert agreement["judgment_id"] == ctx["judgment"]["id"]


def test_a_counter_offer_is_reachable_through_responds_to_offer_id(api):
    """PRD §3.7: "`round_number` is 1 for an opening offer and one more than the
    parent offer's `round_number` for a counter, and a counter whose `round_number`
    would exceed 4 is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — four rounds
    is the whole negotiation."
    PRD §3.7: "The parent offer must still be `OPEN`, and tendering the counter
    moves it `OPEN → COUNTERED` and stamps its `decided_at` with the current
    logical instant."
    PRD §2.3: "Settlement offers accept `judgment_id`, the self-referential
    `responds_to_offer_id`, and `status`."

    Design: Corner/entities/self_referential_counter_offer_chain_reachable_by_responds_to_offer_id
    """
    ctx = setup_judgment(interest_rate_bps=0, filing_costs_cents=0)
    opening = tender_offer(
        ctx["judgment"]["id"], CM, offered_by="CREDITOR", amount_cents=4_000_000
    )
    assert opening["round_number"] == 1

    counter = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR",
        amount_cents=3_500_000,
        responds_to_offer_id=opening["id"],
    )
    assert counter["round_number"] == 2

    rows, meta = validate_paginated(
        api.list_settlement_offers(CM, {"responds_to_offer_id": opening["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == counter["id"]

    assert validate_success(
        api.get_settlement_offer(opening["id"], CM)
    )["status"] == "COUNTERED"
    assert validate_success(
        api.get_settlement_offer(counter["id"], CM)
    )["status"] == "OPEN"
    assert validate_success(
        api.get_judgment(ctx["judgment"]["id"], CM)
    )["open_offer_count"] == 1


def test_fresh_rows_start_in_their_declared_initial_states(api):
    """PRD §2.10: "The first is `status`, the lifecycle axis, which starts at
    `ACTIVE` and ends at either `SATISFIED` or `EXPIRED`; both of those are
    terminal and nothing revives a judgment from them."
    PRD §3.2: "The `CaseManager` drafts one filing per county, naming the
    `judgment_id` it docketed, the `county_code` of the recorder — a code such as
    `CA-LOS-ANGELES` — the two-letter `state_code` of that county's state, the
    `filing_type`, which is either `ABSTRACT_OF_JUDGMENT` or `JUDGMENT_LIEN`, and
    the `fee_cents` the recorder will charge, which may not be negative. A new
    filing is born in `DRAFT`."
    PRD §3.4: "A new examination begins with `status` of `SCHEDULED`,
    `subpoena_status` of `NOT_ISSUED`, `continuance_count` of 0, and
    `subpoena_service_deadline_on` set to the calendar date of `scheduled_at` less
    10 days."

    Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states
    """
    from test_helpers import create_county_filing_payload, create_examination_payload

    creditor = create_creditor()
    debtor = create_debtor()

    judgment = validate_success(
        api.create_judgment(
            create_judgment_payload(
                creditor["id"], debtor["id"], interest_rate_bps=0, filing_costs_cents=0
            ),
            CM,
        ),
        201,
    )
    assert judgment["status"] == "ACTIVE"
    assert judgment["enforcement_posture"] == "NONE"

    filing = validate_success(
        api.create_county_filing(
            create_county_filing_payload(
                judgment["id"], filing_type="JUDGMENT_LIEN", fee_cents=3_500
            ),
            CM,
        ),
        201,
    )
    assert filing["status"] == "DRAFT"

    examination = validate_success(
        api.create_examination(
            create_examination_payload(
                judgment["id"], scheduled_at="2026-09-01T15:00:00Z"
            ),
            CM,
        ),
        201,
    )
    assert examination["status"] == "SCHEDULED"
    assert examination["subpoena_status"] == "NOT_ISSUED"
    assert examination["continuance_count"] == 0


def test_a_case_number_is_unique_within_its_state_but_not_across_states(api):
    """PRD §3.1: "A `court_case_number` must be unique within its `state_code`
    across every judgment in the system — the same docket number in two different
    states is perfectly normal, but a repeat within one state is rejected with
    `ERR_DUPLICATE_CASE_NUMBER`."

    Design: Corner/validations/duplicate_case_number_rejected_within_a_state_but_allowed_across_states
    """
    creditor = create_creditor()
    debtor = create_debtor()
    create_judgment(
        creditor["id"], debtor["id"],
        court_case_number="CV-2026-4008",
        state_code="CA",
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    validate_error(
        api.create_judgment(
            create_judgment_payload(
                creditor["id"], debtor["id"],
                court_case_number="CV-2026-4008",
                state_code="CA",
                original_principal_cents=100_000,
                interest_rate_bps=0,
                filing_costs_cents=0,
            ),
            CM,
        ),
        ApiErrorId.ERR_DUPLICATE_CASE_NUMBER.value,
        409,
    )

    across_states = validate_success(
        api.create_judgment(
            create_judgment_payload(
                creditor["id"], debtor["id"],
                court_case_number="CV-2026-4008",
                state_code="NV",
                original_principal_cents=100_000,
                interest_rate_bps=0,
                filing_costs_cents=0,
            ),
            CM,
        ),
        201,
    )
    assert across_states["state_code"] == "NV"

    _rows, meta = validate_paginated(api.list_judgments(CM))
    assert meta["total_count"] == 2
