"""Cross-cutting layers: the four stale-version guards and the disclosure window edge.

PRD s2.7 lists the four operations that echo a parent version, PRD s2.8 places all three
stale-version codes together at priority 21, and PRD s3.8 freezes a contract's
disclosure_due_at at creation.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_COLLECTIVE_FUNDING_FROZEN,
    ERR_NO_ELIGIBLE_ATHLETES,
    ERR_STALE_COLLECTIVE_VERSION,
    ERR_STALE_CONTRACT_VERSION,
    ERR_STALE_DONOR_VERSION,
)
from test_helpers.assertions import (
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_error_envelope_shape,
    assert_timestamp_equals,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    commitment_payload,
    compliance_decision_payload,
    compliance_submission_payload,
    entity_structure_payload,
    payment_release_payload,
    roster_allocation_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_draft_contract,
    build_funded_collective,
    build_open_tier,
    move_clock,
    read_collective,
    read_contract,
    read_donor,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def test_replaying_a_consumed_donor_version_is_refused_with_precondition_failed(api):
    """One accepted commitment consumes the donor version the caller read.

    PRD s2.7: "`POST /nil/commitments` requires `expected_donor_member_version`, carrying
    the client's last observed `version` of the target `DonorMember`. If that integer does
    not equal the donor member's current stored `version`, the request is rejected with
    `ERR_STALE_DONOR_VERSION` (HTTP 412) and nothing is written. On success the donor
    member's `version` is incremented by exactly 1."

    Design: Corner/cross-cutting complexity layers/stale_expected_donor_member_version_on_commitment_create_returns_412
    """
    collective = build_collective(
        api,
        "026000",
        name="Occ Donor Collective",
        institution_name="Occ Donor Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T2", 60000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Occ Donor",
        email="occd@example.com",
    )
    first_version = donor["version"]
    assert first_version == 1

    read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "RECURRING_SUBSCRIPTION",
                5000,
                "MONTHLY",
                expected_donor_member_version=first_version,
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    second_version = read_donor(api, donor["id"])["version"]
    assert second_version == 2

    replay = api.create_commitment(
        commitment_payload(
            donor["id"],
            "RECURRING_SUBSCRIPTION",
            7000,
            "MONTHLY",
            expected_donor_member_version=first_version,
        ),
        make_director_headers(),
    )
    validate_error(replay, ERR_STALE_DONOR_VERSION, expected_status=412)
    assert_error_envelope_shape(replay)

    listed = api.list_commitments({"donor_member_id": donor["id"]}, make_director_headers())
    assert len(rows_of(listed)) == 1
    assert read_donor(api, donor["id"])["version"] == 2

    # The identical body with the current version is accepted.
    retried = read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "RECURRING_SUBSCRIPTION",
                7000,
                "MONTHLY",
                expected_donor_member_version=second_version,
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert retried["amount_cents"] == 7000
    assert read_donor(api, donor["id"])["version"] == 3


def test_a_stale_collective_version_stops_the_restructure_before_any_cascade(api):
    """The version guard runs first among the three restructure checks.

    PRD s2.7: "`PATCH /nil/collectives/{id}/entity-structure` requires
    `expected_collective_version`. A mismatch with the collective's current `version` is
    rejected with `ERR_STALE_COLLECTIVE_VERSION` (HTTP 412), and no part of the
    restructure cascade runs." PRD s3.2 confirms the ordering: "The stale-version guard of
    s2.7 comes first among them in the ordering of s2.8: a mismatch between
    `expected_collective_version` and the collective's stored `version` yields
    `ERR_STALE_COLLECTIVE_VERSION` and no part of the cascade runs."

    Design: Corner/cross-cutting complexity layers/stale_expected_collective_version_on_entity_structure_patch_returns_412
    """
    collective = build_collective(
        api,
        "026100",
        name="Occ Structure Collective",
        institution_name="Occ Structure Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        entity_structure="NONPROFIT_501C3",
    )
    first_version = collective["version"]
    assert first_version == 1

    changed = read_data(
        api.patch_entity_structure(
            collective["id"],
            entity_structure_payload("FOR_PROFIT_LLC", first_version),
            make_admin_headers(),
        )
    )
    second_version = changed["version"]
    assert second_version == 2
    assert changed["structure_change_count"] == 1
    assert changed["entity_structure"] == "FOR_PROFIT_LLC"

    stale = api.patch_entity_structure(
        collective["id"],
        entity_structure_payload("DONOR_ADVISED_CONDUIT", first_version),
        make_admin_headers(),
    )
    validate_error(stale, ERR_STALE_COLLECTIVE_VERSION, expected_status=412)
    assert_error_envelope_shape(stale)

    untouched = read_collective(api, collective["id"])
    assert untouched["entity_structure"] == "FOR_PROFIT_LLC"
    assert untouched["structure_change_count"] == 1
    assert untouched["version"] == 2
    assert untouched["charitable_deduction_enabled"] is False

    # Only the echoed version differed, so the same body now lands.
    accepted = read_data(
        api.patch_entity_structure(
            collective["id"],
            entity_structure_payload("DONOR_ADVISED_CONDUIT", second_version),
            make_admin_headers(),
        )
    )
    assert accepted["entity_structure"] == "DONOR_ADVISED_CONDUIT"
    assert accepted["structure_change_count"] == 2
    assert accepted["version"] == 3


def test_a_stale_collective_version_outranks_the_empty_roster_rule(api):
    """The same batch reports 412 on a stale version and 422 once the version is right.

    PRD s2.7: "`POST /nil/deal-contracts/roster-allocations` requires
    `expected_collective_version` ... A mismatch with the collective's current `version` is
    rejected with `ERR_STALE_COLLECTIVE_VERSION` (HTTP 412) and no contract is minted."
    PRD s2.8 places "Parent stale-version guards" at priority 21, ahead of the "Funding
    posture gate on roster allocation" at 24, and PRD s3.8 supplies the later refusal: "If
    the input set resolves to no athlete at all, the batch is refused with
    `ERR_NO_ELIGIBLE_ATHLETES`."

    Design: Corner/cross-cutting complexity layers/stale_expected_collective_version_on_roster_allocation_returns_412
    """
    collective = build_collective(
        api,
        "026200",
        name="Occ Roster Collective",
        institution_name="Occ Roster Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
        entity_structure="NONPROFIT_501C3",
    )
    first_version = collective["version"]
    second_version = read_data(
        api.patch_entity_structure(
            collective["id"],
            entity_structure_payload("FOR_PROFIT_LLC", first_version),
            make_admin_headers(),
        )
    )["version"]
    assert second_version == first_version + 1

    def batch(expected_version):
        return api.create_roster_allocation(
            roster_allocation_payload(
                collective["id"],
                "OCC-1",
                "FOOTBALL",
                300000,
                "EQUAL_SHARE",
                "2026-09-01T00:00:00Z",
                "2026-12-01T00:00:00Z",
                expected_collective_version=expected_version,
            ),
            make_director_headers(),
        )

    stale = batch(first_version)
    validate_error(stale, ERR_STALE_COLLECTIVE_VERSION, expected_status=412)
    assert_error_envelope_shape(stale)

    # With the current version the very same batch reaches the roster rule instead.
    empty = batch(second_version)
    validate_error(empty, ERR_NO_ELIGIBLE_ATHLETES, expected_status=422)

    assert (
        rows_of(
            api.list_deal_contracts({"allocation_batch_code": "OCC-1"}, make_director_headers())
        )
        == []
    )
    assert read_collective(api, collective["id"])["version"] == second_version


def test_a_stale_contract_version_outranks_the_frozen_treasury(api):
    """Activation consumes the draft version, and the guard fires before the posture gate.

    PRD s2.7: "`POST /nil/payment-releases` requires `expected_deal_contract_version` ... A
    mismatch with the contract's current `version` is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412) and no release row is created." PRD s2.8 orders
    "Parent stale-version guards" at priority 21 ahead of the "Funding posture gate on
    payment release creation" at 25, and PRD s2.10 supplies that later refusal: "Creating a
    payment release is refused with `ERR_COLLECTIVE_FUNDING_FROZEN` while the pre-request
    posture is `FROZEN`."

    Design: Corner/cross-cutting complexity layers/stale_expected_deal_contract_version_on_payment_release_returns_412
    """
    collective = build_collective(
        api,
        "026300",
        name="Occ Release Collective",
        institution_name="Occ Release Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    athlete = build_athlete(
        api, collective["id"], "ath-occ", full_name="Occ Athlete", sport="FOOTBALL"
    )
    draft = build_draft_contract(
        api, collective["id"], athlete["id"], 50000, funding_designation="UNRESTRICTED"
    )
    assert draft["version"] == 1
    assert draft["disclosure_status"] == "DISCLOSURE_NOT_REQUIRED"

    activated = read_data(api.activate_deal_contract(draft["id"], {}, make_director_headers()))
    assert activated["version"] == 2
    assert_contract_dimensions(activated, lifecycle_status="ACTIVE")

    def advance(expected_version):
        return api.create_payment_release(
            payment_release_payload(
                draft["id"],
                "CONTRACT_ADVANCE",
                10000,
                expected_deal_contract_version=expected_version,
            ),
            make_treasury_headers("treasury-occ"),
        )

    stale = advance(1)
    validate_error(stale, ERR_STALE_CONTRACT_VERSION, expected_status=412)
    assert_error_envelope_shape(stale)

    # The empty treasury is the next refusal, which is what proves the 412 came first.
    frozen = advance(2)
    validate_error(frozen, ERR_COLLECTIVE_FUNDING_FROZEN, expected_status=409)

    assert (
        rows_of(
            api.list_payment_releases({"deal_contract_id": draft["id"]}, make_treasury_headers())
        )
        == []
    )
    assert read_contract(api, draft["id"])["version"] == 2
    assert_collective_ledger(
        read_collective(api, collective["id"]),
        settled_net_funds_cents=0,
        committed_unreleased_cents=50000,
        released_total_cents=0,
        funding_posture="FROZEN",
    )


def test_the_disclosure_window_boundary_is_inclusive_to_the_second(api):
    """Two identical packets differ by one second of clock and land on different states.

    PRD s3.8: "A contract whose `total_value_cents` is at least 60,000 cents — six hundred
    dollars or more — starts in `disclosure_status` `DISCLOSURE_PENDING` with a
    `disclosure_due_at` equal to its `created_at` plus 168 hours, that is seven days on the
    logical clock." Filing "always stamps `disclosure_submitted_at` with the current logical
    clock reading ... when the clock reads at or before `disclosure_due_at`, the dimension
    lands on `DISCLOSURE_PENDING` ... when the clock reads strictly after
    `disclosure_due_at`, the dimension moves to `DISCLOSURE_LATE`". PRD s3.8 also holds that
    "Accepting a late filing is still an acceptance".

    Design: Corner/cross-cutting complexity layers/disclosure_submitted_after_the_window_is_recorded_as_late
    """
    funded = build_funded_collective(
        api,
        "026400",
        500000,
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        designation="UNRESTRICTED",
        email="late@example.com",
        name="Late Collective",
        institution_name="Late Institution",
    )
    athlete = build_athlete(
        api, funded["collective_id"], "ath-late", full_name="Late Athlete", sport="FOOTBALL"
    )
    on_time = build_draft_contract(api, funded["collective_id"], athlete["id"], 100000)
    late = build_draft_contract(api, funded["collective_id"], athlete["id"], 100000)
    assert_timestamp_equals(on_time["disclosure_due_at"], "2026-08-08T00:00:00Z")
    assert_timestamp_equals(late["disclosure_due_at"], "2026-08-08T00:00:00Z")
    assert on_time["disclosure_status"] == "DISCLOSURE_PENDING"
    assert late["disclosure_status"] == "DISCLOSURE_PENDING"

    packet = compliance_submission_payload("CA-AB131", "NCAA-2026-12.5")

    move_clock(api, "2026-08-08T00:00:00Z")
    filed_on_time = read_data(
        api.submit_compliance_packet(on_time["id"], packet, make_director_headers())
    )
    assert filed_on_time["disclosure_status"] == "DISCLOSURE_PENDING"
    assert_timestamp_equals(filed_on_time["disclosure_submitted_at"], "2026-08-08T00:00:00Z")

    move_clock(api, "2026-08-08T00:00:01Z")
    filed_late = read_data(
        api.submit_compliance_packet(late["id"], packet, make_director_headers())
    )
    assert filed_late["disclosure_status"] == "DISCLOSURE_LATE"
    assert_timestamp_equals(filed_late["disclosure_submitted_at"], "2026-08-08T00:00:01Z")
    assert_timestamp_equals(filed_late["disclosure_due_at"], "2026-08-08T00:00:00Z")
    assert filed_late["disclosure_return_count"] == 0

    cleared = read_data(
        api.decide_compliance(
            late["id"], compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        )
    )
    assert cleared["disclosure_status"] == "DISCLOSURE_ACCEPTED"
    assert_contract_dimensions(cleared, lifecycle_status="DRAFT")
    assert_timestamp_equals(cleared["disclosure_due_at"], "2026-08-08T00:00:00Z")
