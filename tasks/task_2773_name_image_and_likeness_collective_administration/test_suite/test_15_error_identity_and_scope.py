"""Error identity: each refusal names its own cause, and each rule keeps its own scope.

The point of every case here is discrimination — two neighbouring rules must not collapse
into one code, and a per-collective scope must not silently become a global one.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_COLLECTIVE_NOT_FOUND,
    ERR_DONOR_MEMBER_NOT_FOUND,
    ERR_DUPLICATE_MEMBER_HANDLE,
    ERR_DUPLICATE_TIER_CODE,
    ERR_FUNDING_DESIGNATION_MISMATCH,
    ERR_INSUFFICIENT_DESIGNATED_FUNDS,
    ERR_MEMBERSHIP_TIER_NOT_FOUND,
    ERR_RELEASE_NOT_RELEASED,
    ERR_STRUCTURE_UNCHANGED,
)
from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contribution_money,
    assert_error_envelope_shape,
    assert_release_money,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    athlete_payload,
    commitment_payload,
    contribution_payload,
    donor_member_payload,
    entity_structure_payload,
    membership_tier_payload,
    payment_release_payload,
    reversal_payload,
)
from test_helpers.fixtures import (
    build_active_contract,
    build_athlete,
    build_collective,
    build_donor,
    build_funded_collective,
    build_open_tier,
    read_athlete,
    read_collective,
    read_contract,
    read_release,
    record_taxpayer_doc,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_director_headers,
    make_treasury_headers,
)

GHOST_TIER_UUID = "00000000-0000-4000-8000-0000000000b1"
GHOST_DONOR_UUID = "00000000-0000-4000-8000-0000000000b2"
GHOST_COLLECTIVE_UUID = "00000000-0000-4000-8000-0000000000b3"


def test_three_unknown_body_references_yield_three_different_codes(api):
    """Priority 7 names the missing entity, and it outranks the stale-version guard.

    PRD s2.8, priority 7: "Every foreign key supplied in a request body references an
    existing row — the matching not-found code, on donor member creation, commitment
    creation, contribution creation, athlete creation, individual contract creation, payment
    release creation and communication log creation", which sits above priority 21, "Parent
    stale-version guards".

    Design: Corner/errors/unknown_body_foreign_keys_each_return_their_own_not_found_code
    """
    collective = build_collective(
        api,
        "025100",
        name="Fk Collective",
        institution_name="Fk Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T1", 20000, 1)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Fk Donor", email="fk@example.com"
    )

    missing_tier = api.create_donor_member(
        donor_member_payload(
            collective["id"],
            GHOST_TIER_UUID,
            display_name="Fk Ghost",
            email="ghost@example.com",
        ),
        make_director_headers(),
    )
    validate_error(missing_tier, ERR_MEMBERSHIP_TIER_NOT_FOUND, expected_status=404)
    assert_error_envelope_shape(missing_tier)

    missing_donor = api.create_commitment(
        commitment_payload(
            GHOST_DONOR_UUID,
            "MAJOR_GIFT_PLEDGE",
            100000,
            "NONE",
            expected_donor_member_version=donor["version"],
        ),
        make_director_headers(),
    )
    validate_error(missing_donor, ERR_DONOR_MEMBER_NOT_FOUND, expected_status=404)

    missing_collective = api.create_athlete(
        athlete_payload(
            GHOST_COLLECTIVE_UUID,
            "ath-fk",
            full_name="Fk Athlete",
            sport="FOOTBALL",
            class_year=2028,
        ),
        make_director_headers(),
    )
    validate_error(missing_collective, ERR_COLLECTIVE_NOT_FOUND, expected_status=404)

    listed = api.list_donor_members(
        {"collective_id": collective["id"]}, make_director_headers()
    )
    validate_success(listed)
    assert [row["id"] for row in rows_of(listed)] == [donor["id"]]


def test_tier_code_and_member_handle_uniqueness_are_scoped_to_one_collective(api):
    """The same code and the same email are free in a second collective, refused in the first.

    PRD s3.3: "The `tier_code` must be unique among that collective's tiers **including
    tiers that have already been closed** ... a collision is `ERR_DUPLICATE_TIER_CODE`", and
    "The `email` must be unique within the collective — a duplicate is
    `ERR_DUPLICATE_MEMBER_HANDLE`."

    Design: Corner/errors/duplicate_tier_code_and_duplicate_member_handle_return_distinct_codes
    """
    alpha = build_collective(
        api,
        "025200",
        name="Dup Collective A",
        institution_name="Dup Institution A",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    beta = build_collective(
        api,
        "025300",
        name="Dup Collective B",
        institution_name="Dup Institution B",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )
    alpha_tier = build_open_tier(api, alpha["id"], "T1", 20000, 1)
    build_donor(
        api, alpha["id"], alpha_tier["id"], display_name="Dup Donor", email="dup@example.com"
    )

    beta_tier = build_open_tier(api, beta["id"], "T1", 25000, 1)
    assert beta_tier["tier_code"] == "T1"
    beta_donor = build_donor(
        api, beta["id"], beta_tier["id"], display_name="Dup Donor B", email="dup@example.com"
    )
    assert beta_donor["email"] == "dup@example.com"

    code_clash = api.create_membership_tier(
        alpha["id"],
        membership_tier_payload("T1", 30000, 2, tier_name="Dup Clash"),
        make_director_headers(),
    )
    validate_error(code_clash, ERR_DUPLICATE_TIER_CODE, expected_status=409)
    assert_error_envelope_shape(code_clash)

    handle_clash = api.create_donor_member(
        donor_member_payload(
            alpha["id"],
            alpha_tier["id"],
            display_name="Dup Clash Donor",
            email="dup@example.com",
        ),
        make_director_headers(),
    )
    validate_error(handle_clash, ERR_DUPLICATE_MEMBER_HANDLE, expected_status=409)
    assert_error_envelope_shape(handle_clash)

    alpha_tiers = api.list_membership_tiers(alpha["id"], None, make_director_headers())
    validate_success(alpha_tiers)
    assert [row["id"] for row in rows_of(alpha_tiers)] == [alpha_tier["id"]]


def test_resubmitting_the_stored_structure_is_its_own_error_and_costs_nothing(api):
    """The no-op conversion is refused without spending a change or a version.

    PRD s3.2: "Finally the change must actually be a change: submitting the
    `entity_structure` the collective already holds is refused with
    `ERR_STRUCTURE_UNCHANGED`." Because that refusal writes nothing, PRD s2.8 guarantees the
    counter and version are untouched, which the follow-up conversion quoting the same
    version then demonstrates.

    Design: Corner/errors/unchanged_entity_structure_returns_its_own_dedicated_error
    """
    collective = build_collective(
        api,
        "025400",
        name="Unchanged Collective",
        institution_name="Unchanged Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        entity_structure="NONPROFIT_501C3",
    )
    assert collective["entity_structure"] == "NONPROFIT_501C3"
    assert collective["structure_change_count"] == 0
    original_version = collective["version"]
    original_effective_at = collective["structure_effective_at"]

    no_op = api.patch_entity_structure(
        collective["id"],
        entity_structure_payload(
            "NONPROFIT_501C3", expected_collective_version=original_version
        ),
        make_admin_headers(),
    )
    validate_error(no_op, ERR_STRUCTURE_UNCHANGED, expected_status=422)
    assert_error_envelope_shape(no_op)

    untouched = read_collective(api, collective["id"])
    assert untouched["entity_structure"] == "NONPROFIT_501C3"
    assert untouched["structure_change_count"] == 0
    assert untouched["version"] == original_version
    assert untouched["structure_effective_at"] == original_effective_at

    real_change = read_data(
        api.patch_entity_structure(
            collective["id"],
            entity_structure_payload(
                "FOR_PROFIT_LLC", expected_collective_version=original_version
            ),
            make_admin_headers(),
        )
    )
    assert real_change["entity_structure"] == "FOR_PROFIT_LLC"
    assert real_change["structure_change_count"] == 1
    assert real_change["version"] == original_version + 1
    assert real_change["charitable_deduction_enabled"] is False


def test_a_release_can_only_be_reversed_once(api):
    """The second reversal is refused and the reversed ledger is not double counted.

    PRD s3.9: "The release's `status` must be `RELEASED` — a queued, voided or already-reversed
    row is refused with `ERR_RELEASE_NOT_RELEASED`", and "a reversed release contributes nothing
    to either figure" on the athlete's tax ledger. PRD s2.10 puts the money on the reversed side:
    "`reversed_total_cents` is the corresponding sum over releases with status `REVERSED`."

    Design: Corner/errors/second_reversal_of_a_reversed_release_returns_release_not_released
    """
    funded = build_funded_collective(
        api,
        "025500",
        500000,
        home_state_code="OH",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="twice@example.com",
        name="Twice Collective",
        institution_name="Twice Institution",
    )
    assert_contribution_money(
        funded["contribution"], processing_fee_cents=12530, net_amount_cents=487470
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-twice",
        full_name="Twice Athlete",
        sport="FOOTBALL",
        class_year=2028,
    )
    record_taxpayer_doc(api, athlete["id"], "W9")
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        200000,
        funding_designation="UNRESTRICTED",
    )

    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                90000,
                expected_deal_contract_version=read_contract(api, contract["id"])["version"],
            ),
            make_treasury_headers("treasury-twice"),
        ),
        expected_status=201,
    )
    first_reversal = read_data(
        api.reverse_payment_release(
            release["id"],
            reversal_payload("ERRONEOUS_PAYMENT"),
            make_treasury_headers("treasury-twice"),
        )
    )
    assert first_reversal["status"] == "REVERSED"

    replayed = api.reverse_payment_release(
        release["id"],
        reversal_payload("CLAWBACK"),
        make_treasury_headers("treasury-twice"),
    )
    validate_error(replayed, ERR_RELEASE_NOT_RELEASED, expected_status=409)
    assert_error_envelope_shape(replayed)

    stored = read_release(api, release["id"])
    assert_release_money(
        stored, status="REVERSED", reversal_reason="ERRONEOUS_PAYMENT"
    )
    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        settled_net_funds_cents=487470,
        released_total_cents=0,
        reversed_total_cents=90000,
    )
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=0,
        tax_year_withheld_cents=0,
        tax_form_required="NONE",
    )


def test_designation_mismatch_and_pool_shortfall_are_told_apart(api):
    """With no charity money the draw is a mismatch; with 48520 of it the bound is inclusive.

    PRD s3.9: "Then the designation match: a release may only draw on contributions carrying
    the same `designation` as the contract's `funding_designation`, so a contract whose
    designation has no matching settled contributions at all cannot be paid and is refused with
    `ERR_FUNDING_DESIGNATION_MISMATCH`. Then the designated-pool ceiling: the
    `requested_amount_cents` must not exceed the collective's unreleased settled net funds
    carrying that designation ... a shortfall is `ERR_INSUFFICIENT_DESIGNATED_FUNDS`." The
    487470 cents of unrestricted cash never enters either comparison.

    Design: Corner/errors/designation_mismatch_and_insufficient_designated_funds_are_distinct_errors
    """
    funded = build_funded_collective(
        api,
        "025600",
        500000,
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="desig@example.com",
        name="Designation Collective",
        institution_name="Designation Institution",
    )
    assert_contribution_money(
        funded["contribution"], processing_fee_cents=12530, net_amount_cents=487470
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-desig",
        full_name="Desig Athlete",
        sport="WOMENS_BASKETBALL",
        class_year=2028,
    )
    record_taxpayer_doc(api, athlete["id"], "W9")
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        100000,
        funding_designation="CHARITY_PROGRAM",
        state_law_citation="CA-AB131",
        association_rule_citation="NCAA-2026-12.5",
    )
    contract_version = read_contract(api, contract["id"])["version"]

    def draw(requested_amount_cents):
        return api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                requested_amount_cents,
                expected_deal_contract_version=contract_version,
            ),
            make_treasury_headers("treasury-desig"),
        )

    no_charity_money = draw(40000)
    validate_error(no_charity_money, ERR_FUNDING_DESIGNATION_MISMATCH, expected_status=422)
    assert_error_envelope_shape(no_charity_money)
    assert (
        rows_of(
            api.list_payment_releases(
                {"deal_contract_id": contract["id"]}, make_treasury_headers()
            )
        )
        == []
    )

    charity_gift = read_data(
        api.create_contribution(
            contribution_payload(
                funded["donor_id"],
                50000,
                designation="CHARITY_PROGRAM",
                processor_outcome="APPROVE",
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        charity_gift, processing_fee_cents=1480, net_amount_cents=48520, status="SETTLED"
    )

    one_cent_over = draw(48521)
    validate_error(one_cent_over, ERR_INSUFFICIENT_DESIGNATED_FUNDS, expected_status=422)
    assert (
        rows_of(
            api.list_payment_releases(
                {"deal_contract_id": contract["id"]}, make_treasury_headers()
            )
        )
        == []
    )

    exactly_the_pool = read_data(draw(48520), expected_status=201)
    assert_release_money(
        exactly_the_pool,
        status="RELEASED",
        requested_amount_cents=48520,
        net_payable_cents=48520,
    )

    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        settled_net_funds_cents=535990,
        released_total_cents=48520,
    )
