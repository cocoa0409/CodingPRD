"""Registry, program, layer and exposure-package creation (PRD §2.5, §2.8, §3.1, §3.2, §3.3).

Queue B — section ``entities``: what a freshly created row exposes before anything
has happened to it — declared defaults, server-owned system fields, computed
premium and score — and which malformed creation requests the request-shape rules
at priorities 5 and 6 refuse outright.
"""
from test_helpers import (
    ADMIN,
    CLOCK,
    LEAD,
    OMIT,
    ApiErrorId,
    api_client,
    assert_capacity_invariants,
    assert_common_fields,
    assert_instant_equals,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_score_equals,
    assert_status,
    create_cedent,
    create_cedent_payload,
    create_exposure_submission_payload,
    create_layer_payload,
    create_program,
    create_program_payload,
    create_quota_share_layer_payload,
    create_reinsurer_payload,
    list_rows,
    make_cedent_underwriter_headers,
    read_program,
    set_clock,
    validate_error,
    validate_success,
)

# The quota-share layer the corner design prices by hand: subject premium base
# 2,000,000,000 at 40.0000% prices at a provisional 800,000,000, which selects
# the 7.5000% volume tier, so the quoted gross premium is 740,000,000.
QS_QUOTED_GROSS_PREMIUM_MINOR = 740_000_000

# The catastrophe layer built from the required inputs alone: 1,250,000,000 at
# 8.0000% with the reinstatement count defaulted to 0 prices at a provisional
# 100,000,000, the first amount in the top tier, so 7.5000% comes off.
CAT_NO_REINSTATEMENT_PREMIUM_MINOR = 92_500_000

# (records 1000, flags 20, years 5, loss completeness 90.0000, report attached)
# scores 40*0.98 + 25*1 + 25*0.9 + 10 = 96.70.
CANONICAL_COMPLETENESS_SCORE = 96.70


def _registered_cedent():
    """Park the clock on the placement instant and register one cedent."""
    set_clock(CLOCK["PLACEMENT_START"])
    return create_cedent()


def _program_created_without_optional_inputs():
    """POST /programs carrying only the seven required inputs (PRD §3.1)."""
    cedent = _registered_cedent()
    response = api_client.create_program(
        create_program_payload(cedent["id"], brokerage_pct=OMIT), LEAD
    )
    return cedent, validate_success(response, 201)


def _quota_share_layer_on_a_draft_program():
    """The canonical quota-share layer filed on a fresh DRAFT program."""
    cedent = _registered_cedent()
    program = create_program(cedent["id"])
    response = api_client.create_layer(
        program["id"], create_quota_share_layer_payload(), LEAD
    )
    return program, response, validate_success(response, 201)


def test_cedent_registration_opens_active_with_both_fiduciary_aggregates_at_zero():
    """A newly registered cedent is ACTIVE, unsuspended and owes nothing either way.

    PRD: "A new cedent opens with `status` set to `ACTIVE` and `suspension_reason`
    null, and with both of its fiduciary aggregates, `settled_receipts_minor` and
    `outstanding_reinstatement_premium_minor`, at 0."

    Design: Corner/entities/cedent_and_reinsurer_creation_returns_system_defaults_and_zero_derived_fields
    """
    set_clock(CLOCK["PLACEMENT_START"])

    response = api_client.create_cedent(create_cedent_payload(), ADMIN)
    cedent = validate_success(response, 201)

    assert response.json()["response_type"] == "object", (
        "a single created resource is returned with response_type object"
    )
    assert_status(cedent, "status", "ACTIVE")
    assert_is_null(cedent, "suspension_reason")
    assert_money_equals(cedent["settled_receipts_minor"], 0, "settled_receipts_minor")
    assert_money_equals(
        cedent["outstanding_reinstatement_premium_minor"],
        0,
        "outstanding_reinstatement_premium_minor",
    )
    assert_common_fields(cedent)
    assert_instant_equals(cedent["created_at"], CLOCK["PLACEMENT_START"], "created_at")
    assert cedent["version"] == 1, f"a created row starts at version 1, got {cedent['version']}"


def test_market_registration_opens_approved_with_its_whole_capacity_available():
    """A newly registered market is APPROVED with nothing committed against it yet.

    PRD: "A new market opens with `security_status` set to `APPROVED`,
    `committed_capacity_minor` at 0 and `available_capacity_minor` equal to its
    `capacity_limit_minor`."

    Design: Corner/entities/cedent_and_reinsurer_creation_returns_system_defaults_and_zero_derived_fields
    """
    set_clock(CLOCK["PLACEMENT_START"])

    response = api_client.create_reinsurer(create_reinsurer_payload(), ADMIN)
    market = validate_success(response, 201)

    assert response.json()["response_type"] == "object", (
        "a single created resource is returned with response_type object"
    )
    assert_status(market, "security_status", "APPROVED")
    assert_money_equals(market["committed_capacity_minor"], 0, "committed_capacity_minor")
    assert_money_equals(
        market["capacity_limit_minor"], 1_000_000_000, "capacity_limit_minor"
    )
    assert_money_equals(
        market["available_capacity_minor"], 1_000_000_000, "available_capacity_minor"
    )
    assert_capacity_invariants(market)
    assert_common_fields(market)
    assert_instant_equals(market["created_at"], CLOCK["PLACEMENT_START"], "created_at")
    assert market["version"] == 1, f"a created row starts at version 1, got {market['version']}"


def test_program_creation_defaults_the_settlement_currency_to_usd():
    """A file opened without a currency settles in USD.

    PRD: "`currency_code` is the three-character uppercase settlement currency and
    defaults to `USD`."

    Design: Corner/entities/program_creation_applies_declared_defaults_for_currency_brokerage_and_signdown
    """
    _cedent, program = _program_created_without_optional_inputs()

    assert program["currency_code"] == "USD", (
        f"the omitted currency_code defaults to USD, got {program['currency_code']!r}"
    )


def test_program_creation_defaults_the_brokerage_retention_to_two_point_five_percent():
    """A file opened without a brokerage rate retains 2.5000 per cent.

    PRD: "`brokerage_pct` is the brokerage the intermediary retains on each signing
    line's share of premium; it lies between 0 and 10 inclusive with up to four
    decimals and defaults to `2.5000`."

    Design: Corner/entities/program_creation_applies_declared_defaults_for_currency_brokerage_and_signdown
    """
    _cedent, program = _program_created_without_optional_inputs()

    assert_pct_equals(program["brokerage_pct"], 2.5000, "brokerage_pct")


def test_program_creation_defaults_the_signdown_method_to_pro_rata():
    """A file opened without an allocation variant signs down PRO_RATA.

    PRD: "`signdown_method` selects which allocation variant applies when a layer is
    oversubscribed, is either `PRO_RATA` or `LEAD_PROTECTED`, and defaults to
    `PRO_RATA`."

    Design: Corner/entities/program_creation_applies_declared_defaults_for_currency_brokerage_and_signdown
    """
    _cedent, program = _program_created_without_optional_inputs()

    assert_status(program, "signdown_method", "PRO_RATA")


def test_program_creation_starts_both_state_dimensions_and_every_money_aggregate_at_zero():
    """A newly opened file is DRAFT and NOT_STARTED with no money and no renewal parent.

    PRD: "Five money aggregates — `gross_written_premium_minor`,
    `brokerage_earned_minor`, `net_remittance_minor`, `rounding_residue_minor` and
    `fiduciary_holding_minor` — all initialise to 0, and `withdrawal_reason` is
    null."

    Design: Corner/entities/program_creation_applies_declared_defaults_for_currency_brokerage_and_signdown
    """
    _cedent, program = _program_created_without_optional_inputs()

    for aggregate in (
        "gross_written_premium_minor",
        "brokerage_earned_minor",
        "net_remittance_minor",
        "rounding_residue_minor",
        "fiduciary_holding_minor",
    ):
        assert_money_equals(program[aggregate], 0, aggregate)
    assert_is_null(program, "withdrawal_reason")
    assert_status(program, "placement_status", "DRAFT")
    assert_status(program, "documentation_status", "NOT_STARTED")
    assert program["disclosure_acknowledged"] is False, (
        "a newly opened file has not had its brokerage acknowledged"
    )
    assert_is_null(program, "prior_program_id")
    assert_common_fields(program)


def test_program_creation_materialises_the_certainty_deadline_thirty_days_after_inception():
    """An inception of 2026-01-01 fixes the contract certainty deadline at 2026-01-31.

    PRD: "At creation the program's `contract_certainty_deadline` is materialised as
    the `inception_date` advanced by thirty days, and `disclosure_acknowledged` is
    false."

    Design: Corner/entities/program_creation_materialises_the_contract_certainty_deadline_thirty_days_after_inception
    """
    cedent = _registered_cedent()

    response = api_client.create_program(create_program_payload(cedent["id"]), LEAD)
    program = validate_success(response, 201)

    assert_instant_equals(
        program["contract_certainty_deadline"],
        CLOCK["CERTAINTY_DEADLINE"],
        "contract_certainty_deadline",
    )
    assert program["disclosure_acknowledged"] is False, (
        "disclosure_acknowledged is false at creation"
    )

    stored = read_program(program["id"])
    assert_instant_equals(
        stored["contract_certainty_deadline"],
        CLOCK["CERTAINTY_DEADLINE"],
        "contract_certainty_deadline on read-back",
    )
    assert_status(stored, "documentation_status", "NOT_STARTED")


def test_quota_share_layer_creation_prices_the_top_tier_discount_into_the_gross_premium():
    """2,000,000,000 at 40.0000% prices provisionally at 800,000,000 and quotes at 740,000,000.

    PRD: "Fourth, `quoted_gross_premium_minor` is the provisional premium multiplied
    by one minus the tier discount percentage divided by one hundred, rounded half up
    to whole minor units."

    Design: Corner/entities/layer_creation_prices_the_quota_share_premium_and_seeds_placement_counters_at_zero
    """
    _program, response, layer = _quota_share_layer_on_a_draft_program()

    assert response.json()["response_type"] == "object", (
        "a single created resource is returned with response_type object"
    )
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        QS_QUOTED_GROSS_PREMIUM_MINOR,
        "quoted_gross_premium_minor",
    )
    assert_status(layer, "status", "OPEN")


def test_layer_creation_seeds_every_placement_counter_at_zero_and_no_peril_exclusions():
    """A new layer carries no written lines, no erosion, no losses and an empty exclusion list.

    PRD: "A new layer opens with status `OPEN`, with `written_line_total_pct` and
    `signed_line_total_pct` at `0.0000`, with `limit_eroded_minor`,
    `reinstatements_used` and `incurred_ceded_minor` at 0, and with `loss_ratio_pct`,
    `provisional_ceding_commission_minor`, `final_ceding_commission_minor` and
    `ceding_commission_delta_minor` all null."

    Design: Corner/entities/layer_creation_prices_the_quota_share_premium_and_seeds_placement_counters_at_zero
    """
    program, _response, layer = _quota_share_layer_on_a_draft_program()

    assert_status(layer, "status", "OPEN")
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    assert_money_equals(layer["limit_eroded_minor"], 0, "limit_eroded_minor")
    assert layer["reinstatements_used"] == 0, (
        f"reinstatements_used starts at 0, got {layer['reinstatements_used']!r}"
    )
    assert_money_equals(layer["incurred_ceded_minor"], 0, "incurred_ceded_minor")
    for null_field in (
        "loss_ratio_pct",
        "provisional_ceding_commission_minor",
        "final_ceding_commission_minor",
        "ceding_commission_delta_minor",
    ):
        assert_is_null(layer, null_field)
    assert layer["program_id"] == program["id"], (
        "the layer belongs to the program in the URL it was filed under"
    )
    assert layer["excluded_perils"] == [], (
        f"the omitted excluded_perils defaults to an empty list, got {layer['excluded_perils']!r}"
    )


def test_exposure_package_creation_scores_the_four_weighted_components_to_two_decimals():
    """(1000, 20, 5, 90.0000, attached) scores 40*0.98 + 25 + 22.5 + 10 = 96.70.

    PRD: "The four weighted components are added together and the resulting raw total
    is rounded half up to two decimal places to give `completeness_score`."

    Design: Corner/entities/exposure_submission_creation_scores_completeness_and_starts_in_draft
    """
    cedent = _registered_cedent()
    program = create_program(cedent["id"])

    response = api_client.create_exposure_submission(
        program["id"],
        create_exposure_submission_payload(),
        make_cedent_underwriter_headers(cedent["id"]),
    )
    submission = validate_success(response, 201)

    assert_score_equals(
        submission["completeness_score"],
        CANONICAL_COMPLETENESS_SCORE,
        "completeness_score",
    )
    assert_status(submission, "status", "DRAFT")


def test_exposure_package_creation_starts_in_draft_with_the_signoff_fields_still_null():
    """A filed package has no actuarial verdict on it yet and advances nothing.

    PRD: "The package is created in status `DRAFT`, its `program_id` is taken from the
    program it is created under, and its `actuary_signoff_user_id`, `signed_off_at` and
    `review_note` all start null."

    Design: Corner/entities/exposure_submission_creation_scores_completeness_and_starts_in_draft
    """
    cedent = _registered_cedent()
    program = create_program(cedent["id"])

    response = api_client.create_exposure_submission(
        program["id"],
        create_exposure_submission_payload(),
        make_cedent_underwriter_headers(cedent["id"]),
    )
    submission = validate_success(response, 201)

    assert_status(submission, "status", "DRAFT")
    assert_is_null(submission, "actuary_signoff_user_id")
    assert_is_null(submission, "signed_off_at")
    assert_is_null(submission, "review_note")
    assert submission["program_id"] == program["id"], (
        "program_id is taken from the program the package was created under"
    )
    assert_common_fields(submission)
    assert_status(read_program(program["id"]), "placement_status", "DRAFT")


def test_exposure_package_program_id_follows_the_url_and_not_a_hijacking_body_field():
    """A body naming the sibling MARINE program cannot move the package off the PROPERTY file.

    PRD: "The package is created in status `DRAFT`, its `program_id` is taken from the
    program it is created under, and its `actuary_signoff_user_id`, `signed_off_at` and
    `review_note` all start null."

    Design: Corner/entities/exposure_submission_system_fields_are_server_generated_and_client_input_ignored
    """
    cedent = _registered_cedent()
    program = create_program(cedent["id"])
    other_program = create_program(
        cedent["id"],
        program_name="Northwind Marine 2026",
        line_of_business="MARINE",
        estimated_premium_income_minor=500_000_000,
    )

    response = api_client.create_exposure_submission(
        program["id"],
        create_exposure_submission_payload(
            program_id=other_program["id"],
            status="SIGNED_OFF",
            completeness_score=12.00,
        ),
        make_cedent_underwriter_headers(cedent["id"]),
    )
    submission = validate_success(response, 201)

    assert submission["program_id"] == program["id"], (
        "program_id is taken from the URL, not from the body"
    )
    assert submission["program_id"] != other_program["id"], (
        "the hijacking body program_id is ignored"
    )
    hijacked_rows = list_rows(
        api_client.list_program_exposure_submissions(other_program["id"], LEAD)
    )
    assert len(hijacked_rows) == 0, (
        f"the sibling program holds no package, got {len(hijacked_rows)} rows"
    )


def test_exposure_package_status_and_score_are_recomputed_over_the_supplied_values():
    """A body claiming SIGNED_OFF and a score of 12.00 still yields DRAFT at 96.70.

    PRD: "A `completeness_score` is computed on creation, recomputed whenever the
    cedent revises the package, and recomputed again when the package is submitted for
    review, so the score an actuary sees is always current."

    Design: Corner/entities/exposure_submission_system_fields_are_server_generated_and_client_input_ignored
    """
    cedent = _registered_cedent()
    program = create_program(cedent["id"])

    response = api_client.create_exposure_submission(
        program["id"],
        create_exposure_submission_payload(status="SIGNED_OFF", completeness_score=12.00),
        make_cedent_underwriter_headers(cedent["id"]),
    )
    submission = validate_success(response, 201)

    assert_status(submission, "status", "DRAFT")
    assert_score_equals(
        submission["completeness_score"],
        CANONICAL_COMPLETENESS_SCORE,
        "completeness_score",
    )
    assert submission["version"] == 1, (
        f"a created row starts at version 1, got {submission['version']}"
    )
    assert_instant_equals(
        submission["created_at"], CLOCK["PLACEMENT_START"], "created_at"
    )


def test_layer_create_omitting_the_subject_premium_base_is_a_request_shape_violation():
    """The premium formula's own input has no default, so leaving it out is ERR_VALIDATION.

    PRD: "On every POST and PATCH endpoint, each input field that has no declared
    default must be present and non-null (priority 5); enum values must be declared
    members, numbers must respect their declared range and decimal width, monetary
    values must be integers in minor units, percentages must carry at most four
    decimals, datetimes must be ISO-8601 UTC instants with exactly three fractional
    digits, and arrays must contain only declared members (priority 6)."

    Design: Corner/entities/layer_create_missing_a_required_input_returns_validation
    """
    cedent = _registered_cedent()
    program = create_program(cedent["id"])
    version_before = program["version"]

    response = api_client.create_layer(
        program["id"], create_layer_payload(subject_premium_base_minor=OMIT), LEAD
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows = list_rows(api_client.list_program_layers(program["id"], LEAD))
    assert len(rows) == 0, f"the rejected layer was not created, got {len(rows)} rows"
    assert read_program(program["id"])["version"] == version_before, (
        "a rejected layer creation leaves the program's version untouched"
    )


def test_layer_create_omitting_only_the_defaulted_inputs_succeeds_on_the_declared_defaults():
    """A catastrophe layer built from the required inputs alone applies all six defaults.

    PRD: "Six further inputs are optional and carry defaults."

    Design: Corner/entities/layer_create_missing_a_required_input_returns_validation
    """
    cedent = _registered_cedent()
    program = create_program(cedent["id"])

    response = api_client.create_layer(
        program["id"],
        create_layer_payload(
            reinstatements_total=OMIT, reinstatement_premium_pct=OMIT, sublimit_minor=OMIT
        ),
        LEAD,
    )
    layer = validate_success(response, 201)

    assert_pct_equals(layer["cession_pct"], 0.0000, "cession_pct")
    assert layer["reinstatements_total"] == 0, (
        f"reinstatements_total defaults to 0, got {layer['reinstatements_total']!r}"
    )
    assert_pct_equals(
        layer["reinstatement_premium_pct"], 100.0000, "reinstatement_premium_pct"
    )
    assert_money_equals(layer["sublimit_minor"], 0, "sublimit_minor")
    assert_pct_equals(layer["ceding_commission_pct"], 0.0000, "ceding_commission_pct")
    assert layer["excluded_perils"] == [], (
        f"excluded_perils defaults to an empty list, got {layer['excluded_perils']!r}"
    )
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        CAT_NO_REINSTATEMENT_PREMIUM_MINOR,
        "quoted_gross_premium_minor",
    )


def test_cedent_create_with_an_undeclared_financial_rating_is_rejected():
    """A financial_rating of "AA" is not one of the four declared members.

    PRD: "On every POST and PATCH endpoint, each input field that has no declared
    default must be present and non-null (priority 5); enum values must be declared
    members, numbers must respect their declared range and decimal width, monetary
    values must be integers in minor units, percentages must carry at most four
    decimals, datetimes must be ISO-8601 UTC instants with exactly three fractional
    digits, and arrays must contain only declared members (priority 6)."

    Design: Corner/entities/out_of_range_and_undeclared_enum_values_are_rejected_with_validation
    """
    cedent = _registered_cedent()

    response = api_client.create_cedent(
        create_cedent_payload(name="Southwind Mutual", financial_rating="AA"), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows = list_rows(api_client.list_cedents(ADMIN))
    assert len(rows) == 1, f"only the valid cedent exists, got {len(rows)} rows"
    assert rows[0]["id"] == cedent["id"], "the rejected registration created no row"


def test_program_create_with_an_underwriting_year_below_the_declared_floor_is_rejected():
    """An underwriting_year of 2019 falls outside the declared 2020 to 2035 range.

    PRD: "A `BrokerPlacementLead` opens a treaty placement file by supplying the
    `cedent_id` of the ceding insurer, a `program_name` of 1 to 120 characters, a
    `line_of_business` of `PROPERTY`, `CASUALTY`, `MARINE` or `MOTOR`, an
    `underwriting_year` between 2020 and 2035 inclusive, an `inception_date` and an
    `expiry_date`, and the cedent-declared `estimated_premium_income_minor` for the
    whole program as an integer greater than zero."

    Design: Corner/entities/out_of_range_and_undeclared_enum_values_are_rejected_with_validation
    """
    cedent = _registered_cedent()

    response = api_client.create_program(
        create_program_payload(
            cedent["id"],
            program_name="Northwind Property 2019",
            underwriting_year=2019,
            inception_date="2019-01-01T00:00:00.000Z",
            expiry_date="2020-01-01T00:00:00.000Z",
            brokerage_pct=OMIT,
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 0, f"the rejected program was not created, got {len(rows)} rows"


def test_program_create_with_a_brokerage_carrying_five_decimals_is_rejected():
    """A brokerage_pct of 2.55555 carries one decimal more than percentages allow.

    PRD: "All percentages carry at most four decimal places, and a percentage supplied
    with more than four decimals is a request-shape violation."

    Design: Corner/entities/out_of_range_and_undeclared_enum_values_are_rejected_with_validation
    """
    cedent = _registered_cedent()

    response = api_client.create_program(
        create_program_payload(cedent["id"], brokerage_pct=2.55555), LEAD
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 0, f"the rejected program was not created, got {len(rows)} rows"


def test_program_create_with_an_instant_missing_its_fractional_digits_is_rejected():
    """An inception_date of "2026-01-01T00:00:00Z" carries no fractional digits at all.

    PRD: "Instants supplied to the API and returned by it are ISO 8601 UTC timestamps
    with exactly three fractional digits, and instants are compared at millisecond
    resolution."

    Design: Corner/entities/out_of_range_and_undeclared_enum_values_are_rejected_with_validation
    """
    cedent = _registered_cedent()

    response = api_client.create_program(
        create_program_payload(
            cedent["id"], inception_date="2026-01-01T00:00:00Z", brokerage_pct=OMIT
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 0, f"the rejected program was not created, got {len(rows)} rows"
