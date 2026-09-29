"""Creation-time constraints and the precedence of the validation ladder (PRD §2.8, §3.1, §3.3).

Queue B — section ``validations``: the two counterparty registries and the treaty
period, the layer coherence rule sitting above the sublimit rule, the shape /
existence / own-state band boundaries, the submission → quote → firm-order
constraints, the lead-line cardinality rule and the release-time brokerage check.
"""
from test_helpers import (
    ACCOUNTANT,
    ADMIN,
    CLOCK,
    LEAD,
    OMIT,
    UNUSED_UUID,
    ApiErrorId,
    api_client,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    create_cedent,
    create_cedent_payload,
    create_disclosure,
    create_layer_payload,
    create_market_submission_payload,
    create_program,
    create_program_payload,
    create_quota_share_layer_payload,
    create_quote_payload,
    create_reinsurer,
    create_reinsurer_payload,
    create_xol_layer_payload,
    current_layer_version,
    decide_disclosure,
    disclose,
    disclosure_decision_payload,
    firm_order_payload,
    list_rows,
    make_reinsurer_underwriter_headers,
    place_lines,
    quote_on,
    read_cedent,
    read_disclosure,
    read_layer,
    read_market_submission,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    refresh,
    release_line,
    set_clock,
    setup_draft_program,
    setup_program_in_market,
    setup_submission_ready_program,
    sign_down,
    submit_to_market,
    suspend_cedent,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# Registry and program creation (PRD §3.1)
# --------------------------------------------------------------------------
# The prior year that a 2027 renewal must NOT be able to cite: 2027 - 1 is 2026,
# not 2025, even though the cedent and the line of business match exactly.
PRIOR_YEAR_PROGRAM = {
    "program_name": "Northwind Property 2025",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2025,
    "inception_date": "2025-01-01T00:00:00.000Z",
    "expiry_date": "2026-01-01T00:00:00.000Z",
    "estimated_premium_income_minor": 1_600_000_000,
}
# An empty half-open interval: expiry lands exactly on inception, so [t, t) covers
# nothing. The underwriting year still agrees with the inception year.
EMPTY_PERIOD_PROGRAM = {
    "program_name": "Empty Period",
    "line_of_business": "MARINE",
    "underwriting_year": 2026,
    "inception_date": "2026-06-01T00:00:00.000Z",
    "expiry_date": "2026-06-01T00:00:00.000Z",
    "estimated_premium_income_minor": 100_000_000,
}
RENEWAL_TWO_YEARS_ON = {
    "program_name": "Northwind Property 2027",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2027,
    "inception_date": "2027-01-01T00:00:00.000Z",
    "expiry_date": "2028-01-01T00:00:00.000Z",
    "estimated_premium_income_minor": 2_000_000_000,
}


def _registry_with_a_2025_property_program():
    """One cedent, one market and one 2025 PROPERTY program to renew against."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    market = create_reinsurer()
    prior = create_program(cedent["id"], **PRIOR_YEAR_PROGRAM)
    return {"cedent": cedent, "market": market, "prior": prior}


def test_a_second_cedent_may_not_reuse_a_registered_name():
    """Re-registering "Northwind Mutual" from another domicile is refused at 409.

    PRD: "Registering a name that already exists, compared without regard to
    letter case, is refused with `ERR_DUPLICATE_NAME`."

    Design: Corner/validations/registry_and_program_creation_rejects_duplicate_names_bad_periods_and_prior_mismatch
    """
    ctx = _registry_with_a_2025_property_program()

    response = api_client.create_cedent(
        create_cedent_payload(
            name="Northwind Mutual", domicile_code="GBLON", financial_rating="B_PLUS"
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_NAME.value)

    rows = list_rows(api_client.list_cedents(ADMIN))
    assert len(rows) == 1, f"the refused registration must not create a row, got {len(rows)}"
    cedent = read_cedent(ctx["cedent"]["id"])
    assert cedent["name"] == "Northwind Mutual", "the surviving cedent keeps its name"
    assert cedent["domicile_code"] == "USNYC", "the refused payload did not overwrite the domicile"


def test_a_second_market_may_not_reuse_a_registered_name():
    """The uniqueness rule guards the market register with the same error id.

    PRD: "Its `name` is likewise 1 to 120 characters and unique across the market
    register, and it carries a `security_rating` of `AAA`, `AA`, `A`, `BBB` or
    `BB`, a `capacity_limit_minor` that is an integer greater than zero and
    expresses the aggregate the market will expose per aggregation window in
    minor units, and a `max_line_pct` greater than 0 and at most 100 with up to
    four decimal places, being the largest line the market will write on any
    single layer."

    Design: Corner/validations/registry_and_program_creation_rejects_duplicate_names_bad_periods_and_prior_mismatch
    """
    ctx = _registry_with_a_2025_property_program()

    response = api_client.create_reinsurer(
        create_reinsurer_payload(
            name="Alpha Re",
            security_rating="A",
            capacity_limit_minor=500_000_000,
            max_line_pct=50.0000,
            lead_authorised=OMIT,
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_NAME.value)

    rows = list_rows(api_client.list_reinsurers(ADMIN))
    assert len(rows) == 1, f"the refused registration must not create a row, got {len(rows)}"
    market = read_reinsurer(ctx["market"]["id"])
    assert_status(market, "security_rating", "AA")
    assert_money_equals(market["capacity_limit_minor"], 1_000_000_000, "capacity_limit_minor")
    assert_pct_equals(market["max_line_pct"], 100.0000, "max_line_pct")


def test_a_treaty_period_whose_expiry_lands_on_its_inception_is_empty():
    """[2026-06-01, 2026-06-01) covers no instant at all, so creation is refused.

    PRD: "The `expiry_date` must be strictly after the `inception_date`, and the
    UTC calendar year of the `inception_date` must equal the `underwriting_year`;
    either failure is reported as `ERR_TREATY_PERIOD_INVALID`."

    Design: Corner/validations/registry_and_program_creation_rejects_duplicate_names_bad_periods_and_prior_mismatch
    """
    ctx = _registry_with_a_2025_property_program()

    response = api_client.create_program(
        create_program_payload(ctx["cedent"]["id"], **EMPTY_PERIOD_PROGRAM), LEAD
    )
    validate_error(response, ApiErrorId.ERR_TREATY_PERIOD_INVALID.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"only the 2025 program may exist, got {len(rows)}"
    assert rows[0]["id"] == ctx["prior"]["id"], "the surviving row is the 2025 program"


def test_a_renewal_must_cite_the_immediately_preceding_underwriting_year():
    """A 2027 program citing the 2025 prior is refused even though cedent and class match.

    PRD: "When `prior_program_id` is supplied it must reference a program of the
    same `cedent_id` and the same `line_of_business` whose `underwriting_year` is
    exactly one less than this program's; any deviation is
    `ERR_RENEWAL_PRIOR_MISMATCH`."

    Design: Corner/validations/registry_and_program_creation_rejects_duplicate_names_bad_periods_and_prior_mismatch
    """
    ctx = _registry_with_a_2025_property_program()

    response = api_client.create_program(
        create_program_payload(
            ctx["cedent"]["id"], prior_program_id=ctx["prior"]["id"], **RENEWAL_TWO_YEARS_ON
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_RENEWAL_PRIOR_MISMATCH.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"the refused renewal must not create a program, got {len(rows)}"
    prior = read_program(ctx["prior"]["id"])
    assert prior["underwriting_year"] == 2025, "the cited prior is untouched by the refusal"


# --------------------------------------------------------------------------
# Layer structural coherence versus the sublimit rule (PRD §3.3)
# --------------------------------------------------------------------------
# A quota-share layer carrying a retention beneath it AND a sublimit above its
# own limit: two structural defects at priorities 52 and 53 in one payload.
QS_ATTACHED_WITH_OVERSIZED_SUBLIMIT = {
    "layer_label": "QS with a retention",
    "attachment_minor": 500_000_000,
    "limit_minor": 50_000_000,
    "sublimit_minor": 90_000_000,
}
# The same payload with the priority-52 defect repaired: attachment back at zero.
QS_COHERENT_WITH_OVERSIZED_SUBLIMIT = {
    "layer_label": "QS with a retention",
    "attachment_minor": 0,
    "limit_minor": 50_000_000,
    "sublimit_minor": 90_000_000,
}
# A quota-share rate that disagrees with its own cession percentage.
QS_RATE_OFF_CESSION = {"layer_label": "QS rate off cession", "base_rate_pct": 35.0000}
# An excess layer that tries to carry ceding commission.
XOL_WITH_CEDING_COMMISSION = {
    "layer_label": "XL with commission",
    "attachment_minor": 1_000_000_000,
    "limit_minor": 500_000_000,
    "ceding_commission_pct": 20.0000,
}


def test_layer_structure_is_judged_before_the_sublimit_on_a_doubly_invalid_layer():
    """A quota-share layer with both a retention and an oversized sublimit reports the structure.

    PRD: "A `QUOTA_SHARE` layer requires an `attachment_minor` of exactly zero, a
    `cession_pct` strictly greater than zero, and a `base_rate_pct` exactly equal
    to its `cession_pct`."

    Design: Corner/validations/layer_structure_rule_outranks_the_sublimit_rule_on_a_doubly_invalid_layer
    """
    ctx = setup_draft_program(with_layer=False)

    response = api_client.create_layer(
        ctx["program"]["id"],
        create_quota_share_layer_payload(**QS_ATTACHED_WITH_OVERSIZED_SUBLIMIT),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_LAYER_STRUCTURE_INVALID.value)

    rows = list_rows(api_client.list_program_layers(ctx["program"]["id"], LEAD))
    assert len(rows) == 0, f"the refused layer must not be created, got {len(rows)}"


def test_repairing_the_retention_lets_the_sublimit_rule_surface():
    """With the attachment back at zero the same 90,000,000 sublimit over a 50,000,000 limit is reported.

    PRD: "Separately, a `sublimit_minor` greater than `limit_minor` is refused
    with `ERR_SUBLIMIT_EXCEEDS_LIMIT`."

    Design: Corner/validations/layer_structure_rule_outranks_the_sublimit_rule_on_a_doubly_invalid_layer
    """
    ctx = setup_draft_program(with_layer=False)

    response = api_client.create_layer(
        ctx["program"]["id"],
        create_quota_share_layer_payload(**QS_COHERENT_WITH_OVERSIZED_SUBLIMIT),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_SUBLIMIT_EXCEEDS_LIMIT.value)

    rows = list_rows(api_client.list_program_layers(ctx["program"]["id"], LEAD))
    assert len(rows) == 0, f"the refused layer must not be created, got {len(rows)}"


def test_a_quota_share_rate_that_disagrees_with_its_cession_is_incoherent():
    """A 35.0000% rate on a 40.0000% cession is refused even with every other field sound.

    PRD: "A layer must be internally consistent with its own type, and an
    incoherent structure is refused with `ERR_LAYER_STRUCTURE_INVALID`."

    Design: Corner/validations/layer_structure_rule_outranks_the_sublimit_rule_on_a_doubly_invalid_layer
    """
    ctx = setup_draft_program(with_layer=False)

    response = api_client.create_layer(
        ctx["program"]["id"], create_quota_share_layer_payload(**QS_RATE_OFF_CESSION), LEAD
    )
    validate_error(response, ApiErrorId.ERR_LAYER_STRUCTURE_INVALID.value)

    rows = list_rows(api_client.list_program_layers(ctx["program"]["id"], LEAD))
    assert len(rows) == 0, f"the refused layer must not be created, got {len(rows)}"


def test_an_excess_layer_may_not_carry_ceding_commission():
    """A 500,000,000 xs 1,000,000,000 excess layer at 20.0000% commission is incoherent.

    PRD: "An `EXCESS_OF_LOSS` or `CATASTROPHE` layer requires an
    `attachment_minor` strictly greater than zero, a `cession_pct` of exactly
    zero, and a `ceding_commission_pct` of exactly zero — excess layers carry no
    ceding commission."

    Design: Corner/validations/layer_structure_rule_outranks_the_sublimit_rule_on_a_doubly_invalid_layer
    """
    ctx = setup_draft_program(with_layer=False)

    response = api_client.create_layer(
        ctx["program"]["id"], create_xol_layer_payload(**XOL_WITH_CEDING_COMMISSION), LEAD
    )
    validate_error(response, ApiErrorId.ERR_LAYER_STRUCTURE_INVALID.value)

    rows = list_rows(api_client.list_program_layers(ctx["program"]["id"], LEAD))
    assert len(rows) == 0, f"the refused layer must not be created, got {len(rows)}"


def test_a_sublimit_equal_to_the_limit_is_admitted_and_one_unit_more_is_not():
    """1,000,000,001 over a 1,000,000,000 limit is refused; exactly 1,000,000,000 opens the layer.

    PRD: "`sublimit_minor` is a per-event sublimit that must be either zero or no
    greater than `limit_minor`, and defaults to 0; a zero means there is no
    sublimit and the full `limit_minor` applies."

    Design: Corner/validations/layer_structure_rule_outranks_the_sublimit_rule_on_a_doubly_invalid_layer
    """
    ctx = setup_draft_program(with_layer=False)

    over = api_client.create_layer(
        ctx["program"]["id"], create_layer_payload(sublimit_minor=1_000_000_001), LEAD
    )
    validate_error(over, ApiErrorId.ERR_SUBLIMIT_EXCEEDS_LIMIT.value)
    assert (
        len(list_rows(api_client.list_program_layers(ctx["program"]["id"], LEAD))) == 0
    ), "one minor unit over the limit creates nothing"

    exact = api_client.create_layer(
        ctx["program"]["id"], create_layer_payload(sublimit_minor=1_000_000_000), LEAD
    )
    layer = validate_success(exact, 201)
    assert_status(layer, "status", "OPEN")
    assert_money_equals(layer["sublimit_minor"], 1_000_000_000, "sublimit_minor")
    assert_money_equals(layer["limit_minor"], 1_000_000_000, "limit_minor")
    assert_money_equals(
        layer["quoted_gross_premium_minor"], 97_125_000, "quoted_gross_premium_minor"
    )

    rows = list_rows(api_client.list_program_layers(ctx["program"]["id"], LEAD))
    assert len(rows) == 1, f"only the coherent layer survives, got {len(rows)}"


# --------------------------------------------------------------------------
# Band boundaries: shape, existence, own state, regulatory safety (PRD §2.8)
# --------------------------------------------------------------------------
# An underwriting year supplied as prose rather than an integer. Paired with a
# body cedent_id that resolves to nothing, the shape defect at priority 6 must
# be the one reported, ahead of the existence check at priority 8.
YEAR_AS_PROSE = "twenty-twenty-six"


def test_a_malformed_underwriting_year_is_reported_ahead_of_an_unresolvable_cedent():
    """A prose underwriting_year plus an unknown cedent_id reports the shape defect at 400.

    PRD: "On every POST and PATCH endpoint, each input field that has no declared
    default must be present and non-null (priority 5); enum values must be
    declared members, numbers must respect their declared range and decimal
    width, monetary values must be integers in minor units, percentages must
    carry at most four decimals, datetimes must be ISO-8601 UTC instants with
    exactly three fractional digits, and arrays must contain only declared
    members (priority 6)."

    Design: Corner/validations/validation_shape_check_outranks_existence_state_and_business_checks
    """
    ctx = setup_draft_program()
    suspend_cedent(ctx["cedent"]["id"])

    response = api_client.create_program(
        create_program_payload(
            UNUSED_UUID,
            program_name="Shape Before Existence",
            underwriting_year=YEAR_AS_PROSE,
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"only the setup program may exist, got {len(rows)}"


def test_repairing_the_year_lets_the_unresolvable_cedent_surface():
    """With a well-formed 2027 year the unknown cedent_id is reported at 404 instead.

    PRD: "A `{cedent_id}` path segment or a body `cedent_id` must resolve to an
    existing cedent, else `ERR_CEDENT_NOT_FOUND` — this guards `GET
    /cedents/{cedent_id}`, `POST /cedents/{cedent_id}/suspension`, `GET
    /cedents/{cedent_id}/programs` and `POST /programs` (priority 8)."

    Design: Corner/validations/validation_shape_check_outranks_existence_state_and_business_checks
    """
    ctx = setup_draft_program()
    suspend_cedent(ctx["cedent"]["id"])

    response = api_client.create_program(
        create_program_payload(
            UNUSED_UUID,
            program_name="Shape Before Existence",
            underwriting_year=2027,
            inception_date="2027-01-01T00:00:00.000Z",
            expiry_date="2028-01-01T00:00:00.000Z",
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_CEDENT_NOT_FOUND.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"only the setup program may exist, got {len(rows)}"


def test_going_to_market_on_an_unknown_program_reports_the_path_segment():
    """The existence band answers before any state or safety rule can be reached.

    PRD: "A `{program_id}` segment must resolve on every `/programs/{program_id}...`
    endpoint, else `ERR_PROGRAM_NOT_FOUND` (priority 10)."

    Design: Corner/validations/validation_shape_check_outranks_existence_state_and_business_checks
    """
    ctx = setup_draft_program()
    suspend_cedent(ctx["cedent"]["id"])

    response = api_client.go_to_market(UNUSED_UUID, LEAD)
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "DRAFT")


def test_a_draft_program_reports_its_own_state_before_its_cedents_suspension():
    """Own state at priority 21 beats the suspended-cedent rule at priority 39.

    PRD: "Each entity's own status must admit the requested action: the program's
    `placement_status` (priority 21, `ERR_PROGRAM_STATE_INVALID`), the program's
    `documentation_status` against the filed `document_type` (priority 22,
    `ERR_DOCUMENT_SEQUENCE_INVALID`), the exposure submission's status (priority
    23, `ERR_SUBMISSION_STATE_INVALID`), the layer's status (priority 24,
    `ERR_LAYER_STATE_INVALID`), the market submission's status (priority 25,
    `ERR_MARKET_SUBMISSION_CLOSED`), the quote's status (priority 26,
    `ERR_QUOTE_STATE_INVALID`), the signing line's status (priority 27,
    `ERR_SIGNING_LINE_STATE_INVALID`), the disclosure's status (priority 28,
    `ERR_DISCLOSURE_STATE_INVALID`), the fiduciary transaction's status (priority
    29, `ERR_TRANSACTION_STATE_INVALID`), the advocacy's status (priority 30,
    `ERR_ADVOCACY_STATE_INVALID`) and the dispute's status (priority 31,
    `ERR_DISPUTE_STATE_INVALID`)."

    Design: Corner/validations/validation_shape_check_outranks_existence_state_and_business_checks
    """
    ctx = setup_draft_program()
    suspend_cedent(ctx["cedent"]["id"])
    before = read_program(ctx["program"]["id"])

    response = api_client.go_to_market(ctx["program"]["id"], LEAD)
    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID.value)

    cedent = read_cedent(ctx["cedent"]["id"])
    assert_status(cedent, "status", "SUSPENDED")
    after = read_program(ctx["program"]["id"])
    assert_status(after, "placement_status", "DRAFT")
    assert after["version"] == before["version"], (
        f"a refused release must not bump the version, {before['version']} -> {after['version']}"
    )
    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"only the setup program may exist, got {len(rows)}"


def test_a_submission_ready_program_reports_its_cedents_suspension():
    """Once the placement state admits release, the regulatory rule is the survivor.

    PRD: "The owning cedent's `status` must be `ACTIVE`; a suspended cedent blocks
    the release with `ERR_CEDENT_SUSPENDED`."

    Design: Corner/validations/validation_shape_check_outranks_existence_state_and_business_checks
    """
    ctx = setup_submission_ready_program()
    suspend_cedent(ctx["cedent"]["id"])
    before = read_program(ctx["program"]["id"])

    response = api_client.go_to_market(ctx["program"]["id"], LEAD)
    validate_error(response, ApiErrorId.ERR_CEDENT_SUSPENDED.value)

    after = read_program(ctx["program"]["id"])
    assert_status(after, "placement_status", "SUBMISSION_READY")
    assert after["version"] == before["version"], (
        f"a refused release must not bump the version, {before['version']} -> {after['version']}"
    )


# --------------------------------------------------------------------------
# Submissions, quotes and firm orders across three entities (PRD §3.4, §3.5)
# --------------------------------------------------------------------------
# Alpha may lead, Bravo may not. Both can write the whole layer, so the
# line-versus-offer gate is reached before the max-line gate.
LEAD_AND_FOLLOWER_MARKETS = [
    {
        "name": "Alpha Re",
        "max_line_pct": 100.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 1_000_000_000,
    },
    {
        "name": "Bravo Re",
        "max_line_pct": 100.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 1_000_000_000,
    },
]
# The follower's terms: a 40.0000 line at 8.5000 on line.
FOLLOWER_QUOTE = {"offered_line_pct": 40.0000, "quoted_rate_pct": 8.5000}


def _in_market_with_a_lead_and_a_follower():
    """One CAT layer in market with a lead-authorised Alpha and a follower-only Bravo."""
    ctx = setup_program_in_market(market_specs=LEAD_AND_FOLLOWER_MARKETS)
    ctx["alpha"], ctx["bravo"] = ctx["reinsurers"][0], ctx["reinsurers"][1]
    return ctx


def test_a_live_submission_blocks_a_second_offer_of_the_same_layer_to_the_same_market():
    """Alpha already holds a SENT submission on the layer, so a second one is refused.

    PRD: "And there must be no other market submission for the same layer and the
    same market still sitting in `SENT` or `QUOTED`, else
    `ERR_DUPLICATE_MARKET_SUBMISSION` — a market that has already declined or
    whose submission has expired may be approached again."

    Design: Corner/validations/market_submission_and_quote_constraints_bind_across_three_entities
    """
    ctx = _in_market_with_a_lead_and_a_follower()
    first = submit_to_market(ctx["layer"]["id"], ctx["alpha"]["id"])
    assert_status(first, "status", "SENT")

    response = api_client.create_market_submission(
        ctx["layer"]["id"], create_market_submission_payload(ctx["alpha"]["id"]), LEAD
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_MARKET_SUBMISSION.value)

    assert_status(read_market_submission(first["id"]), "status", "SENT")


def test_a_market_without_lead_authorisation_may_not_quote_as_lead():
    """Bravo's 40.0000 line at 8.5000 is refused as lead and accepted as a follower.

    PRD: "And setting `is_lead` to true requires the quoting market to have
    `lead_authorised` true **and** `security_status` exactly `APPROVED`; a
    `RESTRICTED` market may follow but never lead, and either failure is
    `ERR_LEAD_NOT_AUTHORISED`."

    Design: Corner/validations/market_submission_and_quote_constraints_bind_across_three_entities
    """
    ctx = _in_market_with_a_lead_and_a_follower()
    submit_to_market(ctx["layer"]["id"], ctx["alpha"]["id"])
    ms_b = submit_to_market(ctx["layer"]["id"], ctx["bravo"]["id"])
    bravo_headers = make_reinsurer_underwriter_headers(ctx["bravo"]["id"])

    as_lead = api_client.create_quote(
        ms_b["id"], create_quote_payload(is_lead=True, **FOLLOWER_QUOTE), bravo_headers
    )
    validate_error(as_lead, ApiErrorId.ERR_LEAD_NOT_AUTHORISED.value)
    assert_status(read_market_submission(ms_b["id"]), "status", "SENT")

    as_follower = api_client.create_quote(
        ms_b["id"], create_quote_payload(is_lead=False, **FOLLOWER_QUOTE), bravo_headers
    )
    quote = validate_success(as_follower, 201)
    assert_status(quote, "status", "QUOTED")
    assert quote["is_lead"] is False, "the accepted quote is a follower quote"
    assert_pct_equals(quote["offered_line_pct"], 40.0000, "offered_line_pct")
    assert_status(read_market_submission(ms_b["id"]), "status", "QUOTED")


def test_a_quoted_submission_admits_neither_a_further_offer_nor_a_further_quote():
    """Bravo's QUOTED submission blocks a re-offer at 409 and a second quote at 409.

    PRD: "The submission must still be in status `SENT`, else
    `ERR_MARKET_SUBMISSION_CLOSED`."

    Design: Corner/validations/market_submission_and_quote_constraints_bind_across_three_entities
    """
    ctx = _in_market_with_a_lead_and_a_follower()
    ms_b = submit_to_market(ctx["layer"]["id"], ctx["bravo"]["id"])
    bravo_headers = make_reinsurer_underwriter_headers(ctx["bravo"]["id"])
    quote_on(ms_b["id"], ctx["bravo"]["id"], is_lead=False, **FOLLOWER_QUOTE)

    re_offer = api_client.create_market_submission(
        ctx["layer"]["id"], create_market_submission_payload(ctx["bravo"]["id"]), LEAD
    )
    validate_error(re_offer, ApiErrorId.ERR_DUPLICATE_MARKET_SUBMISSION.value)

    second_quote = api_client.create_quote(
        ms_b["id"], create_quote_payload(is_lead=False, **FOLLOWER_QUOTE), bravo_headers
    )
    validate_error(second_quote, ApiErrorId.ERR_MARKET_SUBMISSION_CLOSED.value)

    assert_status(read_market_submission(ms_b["id"]), "status", "QUOTED")


def test_a_firm_order_may_not_exceed_the_line_the_market_offered():
    """Firm-ordering 45.0000 against a 40.0000 offer is refused and creates no line.

    PRD: "Then `accepted_line_pct` must be no greater than the quote's
    `offered_line_pct` — the broker may firm-order less than a market offered but
    never more — else `ERR_LINE_EXCEEDS_OFFER`."

    Design: Corner/validations/market_submission_and_quote_constraints_bind_across_three_entities
    """
    ctx = _in_market_with_a_lead_and_a_follower()
    ms_b = submit_to_market(ctx["layer"]["id"], ctx["bravo"]["id"])
    quote = quote_on(ms_b["id"], ctx["bravo"]["id"], is_lead=False, **FOLLOWER_QUOTE)
    layer_version = current_layer_version(ctx["layer"]["id"])

    response = api_client.firm_order(
        quote["id"], firm_order_payload(45.0000, layer_version), LEAD
    )
    validate_error(response, ApiErrorId.ERR_LINE_EXCEEDS_OFFER.value)

    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_status(layer, "status", "IN_MARKET")
    assert_status(read_quote(quote["id"]), "status", "QUOTED")


def test_the_layer_version_survives_a_refused_firm_order_and_admits_the_reduced_line():
    """The same token that was refused at 45.0000 places 40.0000 and part-fills the layer.

    PRD: "The first hop creates a signing line whose `layer_id`, `quote_id` and
    `reinsurer_id` identify the layer, the quote and the market, whose
    `written_line_pct` is copied from the `accepted_line_pct` just accepted and is
    **never mutated again**, whose `signed_line_pct` is null, and whose status is
    `PROVISIONAL`."

    Design: Corner/validations/market_submission_and_quote_constraints_bind_across_three_entities
    """
    ctx = _in_market_with_a_lead_and_a_follower()
    ms_b = submit_to_market(ctx["layer"]["id"], ctx["bravo"]["id"])
    quote = quote_on(ms_b["id"], ctx["bravo"]["id"], is_lead=False, **FOLLOWER_QUOTE)
    layer_version = current_layer_version(ctx["layer"]["id"])

    refused = api_client.firm_order(
        quote["id"], firm_order_payload(45.0000, layer_version), LEAD
    )
    validate_error(refused, ApiErrorId.ERR_LINE_EXCEEDS_OFFER.value)

    accepted = api_client.firm_order(
        quote["id"], firm_order_payload(40.0000, layer_version), LEAD
    )
    line = validate_success(accepted, 201)
    assert_pct_equals(line["written_line_pct"], 40.0000, "written_line_pct")
    assert_status(line, "status", "PROVISIONAL")
    assert_is_null(line, "signed_line_pct")

    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 40.0000, "written_line_total_pct")
    assert_status(layer, "status", "PARTIALLY_PLACED")


# --------------------------------------------------------------------------
# LEAD_PROTECTED sign-down needs exactly one lead line (PRD §3.6)
# --------------------------------------------------------------------------
# Two lead-authorised markets and one follower. Each market's max_line_pct is set
# to exactly the line it writes, so equality carries every firm order.
TWO_LEADS_AND_A_FOLLOWER = [
    {
        "name": "Alpha Re",
        "max_line_pct": 60.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 1_000_000_000,
    },
    {
        "name": "Bravo Re",
        "max_line_pct": 30.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 1_000_000_000,
    },
    {
        "name": "Charlie Re",
        "max_line_pct": 50.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 1_000_000_000,
    },
]


def _lead_protected_layer_with_two_lead_lines():
    """60 lead + 30 lead + 50 follower = 140.0000 written on one LEAD_PROTECTED layer."""
    ctx = setup_program_in_market(
        market_specs=TWO_LEADS_AND_A_FOLLOWER,
        program_overrides={"signdown_method": "LEAD_PROTECTED"},
    )
    place_lines(
        ctx,
        [
            {"market_index": 0, "accepted_line_pct": 60.0000,
             "offered_line_pct": 100.0000, "is_lead": True},
            {"market_index": 1, "accepted_line_pct": 30.0000,
             "offered_line_pct": 100.0000, "is_lead": True},
            {"market_index": 2, "accepted_line_pct": 50.0000,
             "offered_line_pct": 100.0000, "is_lead": False},
        ],
    )
    return refresh(ctx)


def test_lead_protected_signdown_refuses_a_layer_carrying_two_lead_lines():
    """Two PROVISIONAL lead lines are not "at least one" — the allocation is refused.

    PRD: "Because `LEAD_PROTECTED` depends on there being a lead, that method
    additionally requires exactly one `PROVISIONAL` line on the layer whose quote
    is a lead line, else `ERR_LEAD_LINE_MISSING`."

    Design: Corner/validations/lead_protected_signdown_needs_exactly_one_lead_line_not_at_least_one
    """
    ctx = _lead_protected_layer_with_two_lead_lines()
    assert_pct_equals(ctx["layer"]["written_line_total_pct"], 140.0000, "written_line_total_pct")
    assert_status(ctx["layer"], "status", "OVERSUBSCRIBED")
    assert_status(ctx["program"], "placement_status", "FIRM_ORDER")

    response = api_client.sign_down_layer(ctx["layer"]["id"], LEAD)
    validate_error(response, ApiErrorId.ERR_LEAD_LINE_MISSING.value)

    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "OVERSUBSCRIBED")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    for line in ctx["signing_lines"]:
        assert_status(read_signing_line(line["id"]), "status", "PROVISIONAL")


def test_releasing_the_second_lead_line_leaves_the_layer_oversubscribed():
    """Handing Bravo's 30.0000 back drops the written total to 110.0000, still above 100.

    PRD: "The line's status becomes `RELEASED` with `release_reason` set to
    `WITHDRAWN_BY_BROKER`."

    Design: Corner/validations/lead_protected_signdown_needs_exactly_one_lead_line_not_at_least_one
    """
    ctx = _lead_protected_layer_with_two_lead_lines()

    released = release_line(ctx["signing_lines"][1]["id"])
    assert_status(released, "status", "RELEASED")
    assert_status(released, "release_reason", "WITHDRAWN_BY_BROKER")
    assert_status(read_quote(ctx["quotes"][1]["id"]), "status", "LAPSED")

    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 110.0000, "written_line_total_pct")
    assert_status(layer, "status", "OVERSUBSCRIBED")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")


def test_lead_protected_signdown_admits_the_layer_once_exactly_one_lead_remains():
    """With Bravo gone, Alpha keeps 60.0000 whole and Charlie takes the residual 40.0000.

    PRD: "Under `LEAD_PROTECTED`, the line whose quote carried `is_lead` true keeps
    its `written_line_pct` completely untouched, and the followers share only what
    is left over — each follower's raw share is its `written_line_pct` multiplied
    by the difference between `100.0000` and the lead's written line, divided by
    the sum of the followers' written lines — with the floor-and-residue pass
    running over the followers alone and the residue closing against that reduced
    target rather than against `100.0000`."

    Design: Corner/validations/lead_protected_signdown_needs_exactly_one_lead_line_not_at_least_one
    """
    ctx = _lead_protected_layer_with_two_lead_lines()
    release_line(ctx["signing_lines"][1]["id"])

    layer = sign_down(ctx["layer"]["id"])
    assert_status(layer, "status", "SIGNED_DOWN")
    assert_pct_equals(layer["signed_line_total_pct"], 100.0000, "signed_line_total_pct")

    alpha_line = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_pct_equals(alpha_line["signed_line_pct"], 60.0000, "Alpha signed_line_pct")
    assert_money_equals(
        alpha_line["committed_capacity_minor"], 600_000_000, "Alpha committed_capacity_minor"
    )
    assert_status(alpha_line, "status", "SIGNED")

    charlie_line = read_signing_line(ctx["signing_lines"][2]["id"])
    assert_pct_equals(charlie_line["signed_line_pct"], 40.0000, "Charlie signed_line_pct")
    assert_money_equals(
        charlie_line["committed_capacity_minor"], 400_000_000, "Charlie committed_capacity_minor"
    )
    assert_status(charlie_line, "status", "SIGNED")

    bravo_line = read_signing_line(ctx["signing_lines"][1]["id"])
    assert_status(bravo_line, "status", "RELEASED")
    assert_is_null(bravo_line, "signed_line_pct")


# --------------------------------------------------------------------------
# The brokerage disclosure: drafted freely, checked at release (PRD §3.6)
# --------------------------------------------------------------------------
# 3.0000 against the program's own 2.5000 — a draft the register accepts and the
# release refuses.
MISMATCHED_DISCLOSURE = {"brokerage_pct": 3.0000}
# The terms that do match the deal the cedent is getting.
MATCHING_DISCLOSURE = {
    "brokerage_pct": 2.5000,
    "contingent_commission_pct": 0.7500,
    "market_service_fee_minor": 50_000,
}
REJECTION_NOTE = "Contingent commission needs explaining"


def _released_disclosure(ctx):
    """A matching disclosure drafted by the accountant and released to the cedent."""
    disclosure = create_disclosure(ctx["program"]["id"], **MATCHING_DISCLOSURE)
    return disclose(disclosure["id"])


def test_a_draft_disclosure_cannot_be_decided_by_the_cedent():
    """A 3.0000 draft is created without complaint but the cedent may not decide on it.

    PRD: "The deciding `CedentUnderwriter` must be the program's own cedent, since
    a `decision` on another cedent's disclosure is `ERR_FOREIGN_RESOURCE`, and the
    disclosure must be `DISCLOSED`."

    Design: Corner/validations/brokerage_disclosure_pct_is_checked_at_disclosure_not_at_creation
    """
    ctx = setup_program_in_market()
    disclosure = create_disclosure(ctx["program"]["id"], **MISMATCHED_DISCLOSURE)
    assert_status(disclosure, "status", "DRAFT")
    assert_pct_equals(disclosure["brokerage_pct"], 3.0000, "brokerage_pct")
    assert_is_null(disclosure, "disclosed_by_user_id")
    assert_is_null(disclosure, "acknowledged_by_user_id")
    assert_is_null(disclosure, "decision_note")

    response = api_client.decide_brokerage_disclosure(
        disclosure["id"], disclosure_decision_payload("ACKNOWLEDGE"), ctx["cedent_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_STATE_INVALID.value)

    assert_status(read_disclosure(disclosure["id"]), "status", "DRAFT")
    program = read_program(ctx["program"]["id"])
    assert program["disclosure_acknowledged"] is False, "no disclosure has been acknowledged"


def test_releasing_a_disclosure_whose_pct_is_not_the_programs_own_is_refused():
    """The 3.0000 draft fails only at release, when it is compared with the program's 2.5000.

    PRD: "Releasing the draft to the cedent requires the disclosure to be in
    `DRAFT` — anything else is `ERR_DISCLOSURE_STATE_INVALID` — requires the
    program's `placement_status` to be `IN_MARKET` or `FIRM_ORDER`, and requires
    the disclosed `brokerage_pct` to equal the program's own `brokerage_pct` at
    the moment of release, else `ERR_DISCLOSURE_PCT_MISMATCH`: the document the
    cedent sees must be the deal the cedent is actually getting."

    Design: Corner/validations/brokerage_disclosure_pct_is_checked_at_disclosure_not_at_creation
    """
    ctx = setup_program_in_market()
    disclosure = create_disclosure(ctx["program"]["id"], **MISMATCHED_DISCLOSURE)

    response = api_client.disclose_brokerage(disclosure["id"], ACCOUNTANT)
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_PCT_MISMATCH.value)

    after = read_disclosure(disclosure["id"])
    assert_status(after, "status", "DRAFT")
    assert_is_null(after, "disclosed_by_user_id")


def test_a_matching_disclosure_is_released_and_stamped_with_the_accountant():
    """2.5000 with a 0.7500 contingent and a 50,000 service fee releases to the cedent.

    PRD: "Release stamps `disclosed_by_user_id` with the acting accountant's
    identity, moves the status to `DISCLOSED` and increments the disclosure's
    `version`."

    Design: Corner/validations/brokerage_disclosure_pct_is_checked_at_disclosure_not_at_creation
    """
    ctx = setup_program_in_market()
    drafted = create_disclosure(ctx["program"]["id"], **MATCHING_DISCLOSURE)

    disclosure = disclose(drafted["id"])
    assert_status(disclosure, "status", "DISCLOSED")
    assert disclosure["disclosed_by_user_id"] == ACCOUNTANT["X-User-ID"], (
        f"expected the acting accountant, got {disclosure['disclosed_by_user_id']}"
    )
    assert_pct_equals(disclosure["brokerage_pct"], 2.5000, "brokerage_pct")
    assert_pct_equals(
        disclosure["contingent_commission_pct"], 0.7500, "contingent_commission_pct"
    )
    assert_money_equals(
        disclosure["market_service_fee_minor"], 50_000, "market_service_fee_minor"
    )
    assert disclosure["version"] > drafted["version"], (
        f"release increments the version, {drafted['version']} -> {disclosure['version']}"
    )


def test_a_disclosed_disclosure_cannot_be_released_a_second_time():
    """Only a DRAFT may be released, so re-releasing the DISCLOSED document is refused.

    PRD: "Releasing the draft to the cedent requires the disclosure to be in
    `DRAFT` — anything else is `ERR_DISCLOSURE_STATE_INVALID` — requires the
    program's `placement_status` to be `IN_MARKET` or `FIRM_ORDER`, and requires
    the disclosed `brokerage_pct` to equal the program's own `brokerage_pct` at
    the moment of release, else `ERR_DISCLOSURE_PCT_MISMATCH`: the document the
    cedent sees must be the deal the cedent is actually getting."

    Design: Corner/validations/brokerage_disclosure_pct_is_checked_at_disclosure_not_at_creation
    """
    ctx = setup_program_in_market()
    disclosure = _released_disclosure(ctx)

    response = api_client.disclose_brokerage(disclosure["id"], ACCOUNTANT)
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_STATE_INVALID.value)

    assert_status(read_disclosure(disclosure["id"]), "status", "DISCLOSED")


def test_a_rejected_disclosure_may_be_released_again_with_its_decision_cleared():
    """REJECT records the cedent and the note, and the re-release wipes both back to null.

    PRD: "`REJECTED` is deliberately **not** terminal: the accountant can correct
    the terms and release the same disclosure again, which takes it from
    `REJECTED` back to `DISCLOSED`, clearing `acknowledged_by_user_id` and
    `decision_note` back to null and re-checking the `brokerage_pct` match and the
    program state."

    Design: Corner/validations/brokerage_disclosure_pct_is_checked_at_disclosure_not_at_creation
    """
    ctx = setup_program_in_market()
    disclosure = _released_disclosure(ctx)

    rejected = decide_disclosure(
        disclosure["id"], ctx["cedent"]["id"], decision="REJECT", decision_note=REJECTION_NOTE
    )
    assert_status(rejected, "status", "REJECTED")
    assert rejected["acknowledged_by_user_id"] == ctx["cedent"]["id"], (
        f"the deciding cedent is stamped, got {rejected['acknowledged_by_user_id']}"
    )
    assert rejected["decision_note"] == REJECTION_NOTE, "the rejection note is recorded verbatim"
    program = read_program(ctx["program"]["id"])
    assert program["disclosure_acknowledged"] is False, "a rejection acknowledges nothing"

    re_released = disclose(disclosure["id"])
    assert_status(re_released, "status", "DISCLOSED")
    assert_is_null(re_released, "acknowledged_by_user_id")
    assert_is_null(re_released, "decision_note")


def test_acknowledging_a_disclosure_is_terminal_and_unblocks_binding():
    """ACKNOWLEDGE sets the program flag and closes the disclosure to any further decision.

    PRD: "`ACKNOWLEDGE` moves the disclosure to `ACKNOWLEDGED`, which is terminal,
    and sets the program's `disclosure_acknowledged` flag to true — the flag that
    unblocks binding."

    Design: Corner/validations/brokerage_disclosure_pct_is_checked_at_disclosure_not_at_creation
    """
    ctx = setup_program_in_market()
    disclosure = _released_disclosure(ctx)

    acknowledged = decide_disclosure(
        disclosure["id"], ctx["cedent"]["id"], decision="ACKNOWLEDGE"
    )
    assert_status(acknowledged, "status", "ACKNOWLEDGED")
    program = read_program(ctx["program"]["id"])
    assert program["disclosure_acknowledged"] is True, "the acknowledgement unblocks binding"

    response = api_client.decide_brokerage_disclosure(
        disclosure["id"], disclosure_decision_payload("REJECT"), ctx["cedent_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_STATE_INVALID.value)

    assert_status(read_disclosure(disclosure["id"]), "status", "ACKNOWLEDGED")
    assert read_program(ctx["program"]["id"])["disclosure_acknowledged"] is True, (
        "the refused second decision leaves the flag set"
    )
