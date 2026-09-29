"""Refusals: uniqueness, conditional field rules, budgets, caps and the auth ladder.

Every case here drives one declared check from the PRD s2.8 ladder to its refusal and
then proves the same request succeeds once the offending input is corrected, so the
refusal is shown to be caused by the rule and not by the surrounding setup.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ATHLETE_ANNUAL_CAP_EXCEEDED,
    ERR_BILLING_INTERVAL_MISMATCH,
    ERR_CHARITY_HOURS_SHORTFALL,
    ERR_COLLECTIVE_NOT_FOUND,
    ERR_DUE_OUTSIDE_CONTRACT_WINDOW,
    ERR_DUPLICATE_IPEDS_CODE,
    ERR_EVIDENCE_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ROLE,
    ERR_MISSING_AUTH_HEADER,
    ERR_REVERSAL_ACROSS_TAX_YEARS,
    ERR_STRUCTURE_CHANGE_LIMIT,
    ERR_TAXPAYER_DOC_REQUIRED,
    ERR_TIER_RANK_DUES_INVERSION,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_error_envelope_shape,
    assert_release_money,
    assert_timestamp_equals,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    collective_payload,
    commitment_payload,
    deal_contract_payload,
    deliverable_payload,
    donor_member_payload,
    entity_structure_payload,
    membership_tier_payload,
    payment_release_payload,
    reversal_payload,
    submission_payload,
    tier_transition_payload,
)
from test_helpers.fixtures import (
    add_evidence,
    build_active_contract,
    build_athlete,
    build_collective,
    build_deliverable,
    build_donor,
    build_funded_collective,
    build_open_tier,
    move_clock,
    read_athlete,
    read_collective,
    read_contract,
    read_deliverable,
    read_donor,
    read_release,
    record_taxpayer_doc,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_director_headers,
    make_headers_unknown_role,
    make_headers_without_auth,
    make_treasury_headers,
)

ABSENT_COLLECTIVE_UUID = "00000000-0000-4000-8000-0000000000aa"


def test_a_second_collective_claiming_the_same_ipeds_code_is_refused(api):
    """Code uniqueness spans all collectives, and a different code onboards fine.

    PRD s3.1: "The `institution_ipeds_code` must be unique across all collectives; a
    second collective claiming the same code is refused with
    `ERR_DUPLICATE_IPEDS_CODE`." PRD s2.8 places that check at priority 10, after shape
    and reference checks, and states that "nothing is written when any check fails".

    Design: Corner/validations/duplicate_institution_ipeds_code_is_rejected
    """
    first = build_collective(
        api,
        "023100",
        name="Unique Collective",
        institution_name="Unique Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )

    duplicate = api.create_collective(
        collective_payload(
            "023100",
            name="Copycat Collective",
            institution_name="Copycat Institution",
            home_state_code="CA",
            association_ruleset="NCAA_2026",
        ),
        make_admin_headers(),
    )
    validate_error(duplicate, ERR_DUPLICATE_IPEDS_CODE, expected_status=409)
    assert_error_envelope_shape(duplicate)

    listed = api.list_collectives(None, make_admin_headers())
    validate_success(listed)
    rows = rows_of(listed)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["name"] == "Unique Collective"

    neighbour = read_data(
        api.create_collective(
            collective_payload(
                "023101",
                name="Neighbour Collective",
                institution_name="Neighbour Institution",
                home_state_code="CA",
                association_ruleset="NCAA_2026",
            ),
            make_admin_headers(),
        ),
        expected_status=201,
    )
    assert neighbour["institution_ipeds_code"] == "023101"
    assert api.list_collectives(None, make_admin_headers()).json()["meta"]["total_count"] == 2


def test_opening_a_richer_tier_priced_below_a_poorer_one_is_refused(api):
    """The inversion is caught at OPEN, not at creation, and the tier stays in DRAFT.

    PRD s3.3: "Monotonicity means the tier's `annual_dues_cents` must be strictly greater
    than the `annual_dues_cents` of every `OPEN` tier in the same collective whose
    `benefit_rank` is lower ... A tier that would price a richer bundle at or below a
    poorer one is refused with `ERR_TIER_RANK_DUES_INVERSION`." PRD s3.3 also fixes that
    "a new tier begins life in `tier_status` `DRAFT`".

    Design: Corner/validations/tier_rank_dues_inversion_is_rejected_on_open
    """
    collective = build_collective(
        api,
        "023200",
        name="Ladder Collective",
        institution_name="Ladder Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )
    rank_one = build_open_tier(api, collective["id"], "T1", 100000, 1)
    assert rank_one["tier_status"] == "OPEN"

    cheaper_richer = read_data(
        api.create_membership_tier(
            collective["id"],
            membership_tier_payload("T2", 50000, 2, tier_name="Cheap Gold"),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert cheaper_richer["tier_status"] == "DRAFT"

    refused = api.transition_membership_tier(
        cheaper_richer["id"], tier_transition_payload("OPEN"), make_director_headers()
    )
    validate_error(refused, ERR_TIER_RANK_DUES_INVERSION, expected_status=422)
    assert_error_envelope_shape(refused)

    stored = read_data(api.get_membership_tier(cheaper_richer["id"], make_director_headers()))
    assert stored["tier_status"] == "DRAFT"
    assert stored["annual_dues_cents"] == 50000

    priced_above = build_open_tier(api, collective["id"], "T3", 150000, 2)
    assert priced_above["tier_status"] == "OPEN"
    assert priced_above["benefit_rank"] == 2


def test_submission_needs_one_documentation_record_before_it_is_accepted(api):
    """The evidence precondition refuses the first submission and no counter moves.

    PRD s3.8: "The deliverable's `evidence_count` must be at least one
    documentation-of-services record, or the request is `ERR_EVIDENCE_INSUFFICIENT`",
    while PRD s2.8 guarantees that "nothing is written when any check fails".

    Design: Corner/validations/submission_without_evidence_fails_then_passes_with_one_record
    """
    funded = build_funded_collective(
        api,
        "023300",
        200000,
        home_state_code="OH",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        tier_code="T2",
        annual_dues_cents=60000,
        benefit_rank=2,
        email="evid@example.com",
        name="Evidence Collective",
        institution_name="Ohio Institution E",
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-evid",
        full_name="Eve Evidence",
        sport="SOFTBALL",
        class_year=2028,
    )
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        100000,
        funding_designation="UNRESTRICTED",
    )
    deliverable = build_deliverable(
        api, contract["id"], "APPEARANCE", 100000, "2026-09-01T00:00:00Z"
    )
    assert deliverable["evidence_count"] == 0
    assert deliverable["submission_count"] == 0

    refused = api.submit_deliverable(
        deliverable["id"], submission_payload("2026-08-05T00:00:00Z"), make_director_headers()
    )
    validate_error(refused, ERR_EVIDENCE_INSUFFICIENT, expected_status=422)
    assert_error_envelope_shape(refused)

    untouched = read_deliverable(api, deliverable["id"])
    assert untouched["status"] == "PENDING"
    assert untouched["submission_count"] == 0
    assert untouched["performed_at"] is None

    add_evidence(api, deliverable["id"], "SIGNED_ATTENDANCE_SHEET", "evid-sheet-1")
    documented = read_deliverable(api, deliverable["id"])
    assert documented["evidence_count"] == 1

    accepted = read_data(
        api.submit_deliverable(
            deliverable["id"],
            submission_payload("2026-08-05T00:00:00Z"),
            make_director_headers(),
        )
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["submission_count"] == 1
    assert accepted["late_flag"] is False
    assert_timestamp_equals(accepted["performed_at"], "2026-08-05T00:00:00Z")


def test_the_charity_hours_rule_binds_only_the_charity_work_kind(api):
    """A social post submits with no hours while the charity row needs the full forty.

    PRD s3.8: "For a `CHARITY_WORK` deliverable, the submitted `charity_hours_tenths`
    must be greater than or equal to `required_charity_hours_tenths`, or the request is
    `ERR_CHARITY_HOURS_SHORTFALL`." PRD s2.8 adds the shape rule that
    "`required_charity_hours_tenths` is strictly greater than zero when
    `deliverable_kind` is `CHARITY_WORK` and exactly zero otherwise".

    Design: Corner/validations/charity_hours_shortfall_applies_only_to_charity_work_deliverables
    """
    funded = build_funded_collective(
        api,
        "023400",
        500000,
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="char@example.com",
        name="Charity Collective",
        institution_name="California Institution E",
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-char",
        full_name="Cara Charity",
        sport="WOMENS_BASKETBALL",
        class_year=2027,
    )
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        200000,
        funding_designation="UNRESTRICTED",
        state_law_citation="CA-AB131",
        association_rule_citation="NCAA-2026-12.5",
    )

    post = build_deliverable(
        api, contract["id"], "SOCIAL_POST", 100000, "2026-09-01T00:00:00Z"
    )
    assert post["required_charity_hours_tenths"] == 0
    charity = build_deliverable(
        api,
        contract["id"],
        "CHARITY_WORK",
        100000,
        "2026-09-01T00:00:00Z",
        required_charity_hours_tenths=40,
    )
    assert charity["required_charity_hours_tenths"] == 40

    add_evidence(api, post["id"], "ANALYTICS_SCREENSHOT", "char-post-1")
    add_evidence(api, charity["id"], "SIGNED_ATTENDANCE_SHEET", "char-sheet-1")

    submitted_post = read_data(
        api.submit_deliverable(
            post["id"], submission_payload("2026-08-05T00:00:00Z"), make_director_headers()
        )
    )
    assert submitted_post["status"] == "SUBMITTED"
    assert submitted_post["submission_count"] == 1

    short = api.submit_deliverable(
        charity["id"],
        submission_payload("2026-08-05T00:00:00Z", charity_hours_tenths=39),
        make_director_headers(),
    )
    validate_error(short, ERR_CHARITY_HOURS_SHORTFALL, expected_status=422)
    stalled = read_deliverable(api, charity["id"])
    assert stalled["status"] == "PENDING"
    assert stalled["submission_count"] == 0

    exact = read_data(
        api.submit_deliverable(
            charity["id"],
            submission_payload("2026-08-05T00:00:00Z", charity_hours_tenths=40),
            make_director_headers(),
        )
    )
    assert exact["status"] == "SUBMITTED"
    assert exact["submission_count"] == 1
    assert exact["charity_hours_tenths"] == 40

    mismatched_kind = api.create_deliverable(
        contract["id"],
        deliverable_payload(
            "SOCIAL_POST", 100000, "2026-09-01T00:00:00Z", required_charity_hours_tenths=40
        ),
        make_director_headers(),
    )
    validate_error(mismatched_kind, ERR_INVALID_REQUEST, expected_status=400)


def test_the_billing_interval_must_match_the_commitment_kind_in_both_directions(api):
    """NONE is wrong for a subscription and MONTHLY is wrong for a pledge.

    PRD s3.4: "The `billing_interval` must be consistent with the `kind`: it must be
    `NONE` when the `kind` is `MAJOR_GIFT_PLEDGE`, and it must be `MONTHLY` or `ANNUAL` —
    never `NONE` — when the `kind` is `RECURRING_SUBSCRIPTION`. An inconsistent pairing is
    refused with `ERR_BILLING_INTERVAL_MISMATCH`." Because nothing is written on a refusal,
    the donor's `version` is still the one both refused calls quoted, and PRD s3.4 states
    that "on success the donor member's `version` rises by exactly 1".

    Design: Corner/validations/monthly_billing_interval_on_major_gift_pledge_is_rejected
    """
    collective = build_collective(
        api,
        "023500",
        name="Interval Collective",
        institution_name="Texas Institution E",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T2", 40000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Ivan Interval",
        email="ivan@example.com",
    )

    pledge_with_interval = api.create_commitment(
        commitment_payload(
            donor["id"],
            "MAJOR_GIFT_PLEDGE",
            300000,
            "MONTHLY",
            expected_donor_member_version=donor["version"],
            installments_total=3,
        ),
        make_director_headers(),
    )
    validate_error(pledge_with_interval, ERR_BILLING_INTERVAL_MISMATCH, expected_status=422)
    assert_error_envelope_shape(pledge_with_interval)

    subscription_without_interval = api.create_commitment(
        commitment_payload(
            donor["id"],
            "RECURRING_SUBSCRIPTION",
            5000,
            "NONE",
            expected_donor_member_version=donor["version"],
        ),
        make_director_headers(),
    )
    validate_error(
        subscription_without_interval, ERR_BILLING_INTERVAL_MISMATCH, expected_status=422
    )

    accepted = read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "RECURRING_SUBSCRIPTION",
                5000,
                "MONTHLY",
                expected_donor_member_version=donor["version"],
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert accepted["kind"] == "RECURRING_SUBSCRIPTION"
    assert accepted["billing_interval"] == "MONTHLY"
    assert accepted["status"] == "ACTIVE"
    assert accepted["installments_total"] == 1

    assert read_donor(api, donor["id"])["version"] == donor["version"] + 1
    listed = api.list_commitments({"donor_member_id": donor["id"]}, make_director_headers())
    assert len(rows_of(listed)) == 1
    refreshed_tier = read_data(api.get_membership_tier(tier["id"], make_director_headers()))
    assert refreshed_tier["active_commitment_count"] == 1


def test_a_third_entity_structure_change_exhausts_the_lifetime_budget(api):
    """Two conversions are allowed; the third is refused with the counter still at two.

    PRD s3.2: "a collective may accept at most **two** entity-structure changes over its
    lifetime, so a third attempt — one made when `structure_change_count` already reads 2 —
    is refused with `ERR_STRUCTURE_CHANGE_LIMIT`", and on a refusal "no part of the
    restructure cascade runs". PRD s3.1 fixes the flag under test as true "if and only if
    `entity_structure` is `NONPROFIT_501C3`".

    Design: Corner/validations/structure_change_limit_reached_after_two_changes
    """
    collective = build_collective(
        api,
        "023600",
        name="Budget Collective",
        institution_name="California Institution F",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    assert collective["charitable_deduction_enabled"] is True
    assert collective["structure_change_count"] == 0
    assert collective["version"] == 1

    first_change = read_data(
        api.patch_entity_structure(
            collective["id"],
            entity_structure_payload("FOR_PROFIT_LLC", expected_collective_version=1),
            make_admin_headers(),
        )
    )
    assert first_change["entity_structure"] == "FOR_PROFIT_LLC"
    assert first_change["charitable_deduction_enabled"] is False
    assert first_change["structure_change_count"] == 1
    assert first_change["version"] == 2

    second_change = read_data(
        api.patch_entity_structure(
            collective["id"],
            entity_structure_payload("DONOR_ADVISED_CONDUIT", expected_collective_version=2),
            make_admin_headers(),
        )
    )
    assert second_change["entity_structure"] == "DONOR_ADVISED_CONDUIT"
    assert second_change["charitable_deduction_enabled"] is False
    assert second_change["structure_change_count"] == 2
    assert second_change["version"] == 3

    third_change = api.patch_entity_structure(
        collective["id"],
        entity_structure_payload("NONPROFIT_501C3", expected_collective_version=3),
        make_admin_headers(),
    )
    validate_error(third_change, ERR_STRUCTURE_CHANGE_LIMIT, expected_status=422)
    assert_error_envelope_shape(third_change)

    unchanged = read_collective(api, collective["id"])
    assert unchanged["entity_structure"] == "DONOR_ADVISED_CONDUIT"
    assert unchanged["charitable_deduction_enabled"] is False
    assert unchanged["structure_change_count"] == 2
    assert unchanged["version"] == 3


def test_the_athlete_cap_is_read_on_the_aggregate_and_admits_the_exact_total(api):
    """Two contracts are summed against the cap, and exactly fifty thousand dollars fits.

    PRD s3.8: "Finally the athlete cap: after the request, the athlete's
    `annual_committed_value_cents` must not be **strictly greater** than 5,000,000 cents,
    that is fifty thousand dollars. A post-creation total of exactly fifty thousand dollars
    is allowed; one cent more is refused with `ERR_ATHLETE_ANNUAL_CAP_EXCEEDED`."

    Design: Corner/validations/athlete_annual_cap_exceeded_by_aggregate_of_two_contracts
    """
    funded = build_funded_collective(
        api,
        "023700",
        6000000,
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        tier_code="T5",
        annual_dues_cents=1000000,
        benefit_rank=5,
        email="cap@example.com",
        name="Cap Collective",
        institution_name="Texas Institution F",
    )
    assert funded["contribution"]["processing_fee_cents"] == 126000
    assert funded["contribution"]["net_amount_cents"] == 5874000
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-capagg",
        full_name="Cap Aggregate",
        sport="FOOTBALL",
        class_year=2028,
    )

    def sign(total_value_cents):
        return api.create_deal_contract(
            deal_contract_payload(
                funded["collective_id"],
                athlete["id"],
                total_value_cents,
                funding_designation="UNRESTRICTED",
            ),
            make_director_headers(),
        )

    first = read_data(sign(3000000), expected_status=201)
    assert first["total_value_cents"] == 3000000
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]), annual_committed_value_cents=3000000
    )

    over_by_one_cent = sign(2000001)
    validate_error(over_by_one_cent, ERR_ATHLETE_ANNUAL_CAP_EXCEEDED, expected_status=422)
    assert_error_envelope_shape(over_by_one_cent)
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]), annual_committed_value_cents=3000000
    )
    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        settled_net_funds_cents=5874000,
        committed_unreleased_cents=3000000,
        funding_posture="OPEN",
    )

    exactly_at_cap = read_data(sign(2000000), expected_status=201)
    assert exactly_at_cap["total_value_cents"] == 2000000
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]), annual_committed_value_cents=5000000
    )
    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        committed_unreleased_cents=5000000,
        funding_posture="OPEN",
    )


def test_a_deliverable_due_instant_must_sit_inside_the_half_open_contract_window(api):
    """The window's start is included and its end is excluded, both enforced.

    PRD s3.8: "The `due_at` must fall inside the parent contract's effective window — at
    or after `effective_start_at` and strictly before `effective_end_at` — or the request
    is refused with `ERR_DUE_OUTSIDE_CONTRACT_WINDOW`."

    Design: Corner/validations/deliverable_due_at_outside_contract_window_is_rejected
    """
    funded = build_funded_collective(
        api,
        "023800",
        200000,
        home_state_code="OH",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        tier_code="T2",
        annual_dues_cents=60000,
        benefit_rank=2,
        email="win@example.com",
        name="Window Collective",
        institution_name="Ohio Institution F",
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-win",
        full_name="Win Window",
        sport="BASEBALL",
        class_year=2028,
    )
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        100000,
        effective_start_at="2026-08-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
        funding_designation="UNRESTRICTED",
    )

    def promise(due_at):
        return api.create_deliverable(
            contract["id"],
            deliverable_payload("APPEARANCE", 50000, due_at),
            make_director_headers(),
        )

    at_the_end = promise("2026-12-31T00:00:00Z")
    validate_error(at_the_end, ERR_DUE_OUTSIDE_CONTRACT_WINDOW, expected_status=422)
    assert_error_envelope_shape(at_the_end)

    just_before_the_start = promise("2026-07-31T23:59:59Z")
    validate_error(just_before_the_start, ERR_DUE_OUTSIDE_CONTRACT_WINDOW, expected_status=422)

    at_the_start = read_data(promise("2026-08-01T00:00:00Z"), expected_status=201)
    assert at_the_start["status"] == "PENDING"
    assert_timestamp_equals(at_the_start["due_at"], "2026-08-01T00:00:00Z")

    listed = api.list_deliverables(contract["id"], None, make_director_headers())
    validate_success(listed)
    assert len(rows_of(listed)) == 1
    assert_contract_money(
        read_contract(api, contract["id"]), deliverable_value_total_cents=50000
    )


def test_a_reversal_is_refused_once_the_clock_has_left_the_release_year(api):
    """The same reversal fails at 2027-01-05 and succeeds at 2026-12-31.

    PRD s3.9: "the calendar year of its `released_at` must equal the current tax year, or
    the reversal is refused with `ERR_REVERSAL_ACROSS_TAX_YEARS`, so that the athlete's tax
    ledger for a closed year is never rewritten." PRD s2.5 permits the clock to be moved
    "backward as well as forward", which is what reopens the year here.

    Design: Corner/validations/reversal_after_the_tax_year_closes_is_rejected
    """
    funded = build_funded_collective(
        api,
        "023900",
        500000,
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="taxy@example.com",
        name="Tax Year Collective",
        institution_name="California Institution G",
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-taxy",
        full_name="Tay Taxyear",
        sport="FOOTBALL",
        class_year=2028,
    )
    record_taxpayer_doc(api, athlete["id"], "W9")
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        200000,
        effective_start_at="2026-08-01T00:00:00Z",
        effective_end_at="2027-06-30T00:00:00Z",
        funding_designation="UNRESTRICTED",
        state_law_citation="CA-AB131",
        association_rule_citation="NCAA-2026-12.5",
    )

    move_clock(api, "2026-12-20T00:00:00Z")
    before_release = read_contract(api, contract["id"])
    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                100000,
                expected_deal_contract_version=before_release["version"],
            ),
            make_treasury_headers("treasury-taxy"),
        ),
        expected_status=201,
    )
    assert_release_money(
        release,
        status="RELEASED",
        requested_amount_cents=100000,
        withholding_basis="NONE",
        withholding_amount_cents=0,
        net_payable_cents=100000,
        reversal_reason="NONE",
    )
    assert_timestamp_equals(release["released_at"], "2026-12-20T00:00:00Z")

    moved = move_clock(api, "2027-01-05T00:00:00Z")
    assert_timestamp_equals(moved["previous_utc"], "2026-12-20T00:00:00Z")
    assert_timestamp_equals(moved["current_utc"], "2027-01-05T00:00:00Z")

    refused = api.reverse_payment_release(
        release["id"],
        reversal_payload("ERRONEOUS_PAYMENT"),
        make_treasury_headers("treasury-taxy"),
    )
    validate_error(refused, ERR_REVERSAL_ACROSS_TAX_YEARS, expected_status=422)
    assert_error_envelope_shape(refused)

    untouched = read_release(api, release["id"])
    assert untouched["status"] == "RELEASED"
    assert untouched["reversal_reason"] == "NONE"
    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        released_total_cents=100000,
        reversed_total_cents=0,
    )

    move_clock(api, "2026-12-31T00:00:00Z")
    reversed_row = read_data(
        api.reverse_payment_release(
            release["id"],
            reversal_payload("ERRONEOUS_PAYMENT"),
            make_treasury_headers("treasury-taxy"),
        )
    )
    assert_release_money(
        reversed_row, status="REVERSED", reversal_reason="ERRONEOUS_PAYMENT"
    )
    assert_contract_dimensions(
        read_contract(api, contract["id"]), payment_status="UNPAID"
    )
    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        released_total_cents=0,
        reversed_total_cents=100000,
    )
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=0,
        tax_year_withheld_cents=0,
        tax_form_required="NONE",
    )


def test_a_nonresident_alien_needs_a_w8ben_before_any_money_moves(api):
    """The refusal writes no release row, and the same request pays once the form is filed.

    PRD s3.9: "Then the nonresident-alien documentation rule: paying an athlete whose
    `tax_person_kind` is `NONRESIDENT_ALIEN` requires `taxpayer_doc_on_file` to be
    `W8BEN`, or the request is `ERR_TAXPAYER_DOC_REQUIRED`." With no treaty claim the same
    paragraph fixes the regime: "in every other nonresident case the `withholding_basis` is
    `NRA_STATUTORY` and `withholding_amount_cents` is the `requested_amount_cents`
    multiplied by 30, divided by 100, with the quotient rounded half up to a whole cent."
    PRD s3.7 then requires `FORM_1042_S` for a nonresident alien with any nonzero payment.

    Design: Corner/validations/nonresident_alien_without_taxpayer_doc_cannot_be_paid
    """
    funded = build_funded_collective(
        api,
        "024000",
        500000,
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="nils@example.com",
        name="Nonresident Collective",
        institution_name="Texas Institution G",
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-nils",
        full_name="Nils Nordic",
        sport="MENS_BASKETBALL",
        class_year=2028,
        tax_person_kind="NONRESIDENT_ALIEN",
    )
    assert athlete["tax_person_kind"] == "NONRESIDENT_ALIEN"
    assert athlete["taxpayer_doc_on_file"] == "NONE"
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        200000,
        funding_designation="UNRESTRICTED",
        state_law_citation="TX-51.9246",
        association_rule_citation="NCAA-2024-12.5",
    )
    version_before = read_contract(api, contract["id"])["version"]

    undocumented = api.create_payment_release(
        payment_release_payload(
            contract["id"],
            "CONTRACT_ADVANCE",
            100000,
            expected_deal_contract_version=version_before,
        ),
        make_treasury_headers("treasury-nra"),
    )
    validate_error(undocumented, ERR_TAXPAYER_DOC_REQUIRED, expected_status=422)
    assert_error_envelope_shape(undocumented)
    assert (
        rows_of(
            api.list_payment_releases(
                {"deal_contract_id": contract["id"]}, make_treasury_headers()
            )
        )
        == []
    )

    certified = record_taxpayer_doc(api, athlete["id"], "W8BEN", treaty_exempt_claimed=False)
    assert certified["taxpayer_doc_on_file"] == "W8BEN"
    assert certified["treaty_exempt_claimed"] is False
    assert read_contract(api, contract["id"])["version"] == version_before

    paid = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                100000,
                expected_deal_contract_version=version_before,
            ),
            make_treasury_headers("treasury-nra"),
        ),
        expected_status=201,
    )
    assert_release_money(
        paid,
        status="RELEASED",
        requested_amount_cents=100000,
        withholding_basis="NRA_STATUTORY",
        withholding_amount_cents=30000,
        net_payable_cents=70000,
        initiated_by_user_id="treasury-nra",
    )
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=100000,
        tax_year_withheld_cents=30000,
        tax_form_required="FORM_1042_S",
    )
    assert_contract_money(
        read_contract(api, contract["id"]), released_total_cents=100000
    )
    assert_contract_dimensions(
        read_contract(api, contract["id"]), payment_status="PARTIALLY_PAID"
    )


def test_a_missing_body_field_outranks_an_unknown_parent_reference(api):
    """The same absent collective_id yields 400 first and 404 only once the body is whole.

    PRD s2.8 orders "5. Request body and query shape — `ERR_INVALID_REQUEST`, on every
    write endpoint and every list endpoint" ahead of "7. Every foreign key supplied in a
    request body references an existing row — the matching not-found code, on donor member
    creation ...", and states that "the **first** violated check decides the response; no
    later check can mask an earlier one".

    Design: Corner/validations/schema_check_precedes_existence_check_returns_invalid_request
    """
    collective = build_collective(
        api,
        "024100",
        name="Ladder Order Collective",
        institution_name="Ohio Institution G",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T1", 20000, 1)

    shape_first = api.create_donor_member(
        donor_member_payload(
            ABSENT_COLLECTIVE_UUID, tier["id"], display_name=None, email=None
        ),
        make_director_headers(),
    )
    validate_error(shape_first, ERR_INVALID_REQUEST, expected_status=400)
    assert_error_envelope_shape(shape_first)

    reference_second = api.create_donor_member(
        donor_member_payload(
            ABSENT_COLLECTIVE_UUID,
            tier["id"],
            display_name="Ghost Donor",
            email="ghost@example.com",
        ),
        make_director_headers(),
    )
    validate_error(reference_second, ERR_COLLECTIVE_NOT_FOUND, expected_status=404)
    assert_error_envelope_shape(reference_second)

    listed = api.list_donor_members(
        {"collective_id": collective["id"]}, make_director_headers()
    )
    validate_success(listed)
    assert rows_of(listed) == []
    assert listed.json()["meta"]["total_count"] == 0


def test_the_three_authentication_checks_fire_in_their_declared_order(api):
    """One valid payload, three header states, three distinct refusals.

    PRD s2.1: "If either header is absent, or if `X-User-ID` is present but empty, the
    request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). If `X-User-Role` is
    present but is not one of the six recognised role names, the request is rejected with
    `ERR_INVALID_ROLE` (HTTP 400). If the role is recognised but is not among the roles
    permitted on the addressed endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." PRD s3.1 restricts onboarding to a `PlatformAdmin`, which is why a
    `TreasuryOfficer` is the third refusal rather than a success.

    Design: Corner/validations/missing_auth_header_returns_401_and_unknown_role_returns_400
    """
    payload = collective_payload(
        "024200",
        name="Auth Ladder Collective",
        institution_name="Texas Institution H",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )

    no_headers = api.create_collective(payload, make_headers_without_auth())
    validate_error(no_headers, ERR_MISSING_AUTH_HEADER, expected_status=401)
    assert_error_envelope_shape(no_headers)

    bogus_role = api.create_collective(payload, make_headers_unknown_role())
    validate_error(bogus_role, ERR_INVALID_ROLE, expected_status=400)
    assert_error_envelope_shape(bogus_role)

    wrong_role = api.create_collective(payload, make_treasury_headers())
    validate_error(wrong_role, ERR_UNAUTHORIZED, expected_status=403)
    assert_error_envelope_shape(wrong_role)

    listed = api.list_collectives(None, make_admin_headers())
    validate_success(listed)
    assert rows_of(listed) == []
    assert listed.json()["meta"]["total_count"] == 0

    accepted = read_data(
        api.create_collective(payload, make_admin_headers()), expected_status=201
    )
    assert accepted["institution_ipeds_code"] == "024200"
