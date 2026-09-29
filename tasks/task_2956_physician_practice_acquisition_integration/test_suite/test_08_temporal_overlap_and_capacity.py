"""Two different flavours of contention over a shared resource.

Payer coverage terms contend over a closed date interval, so terms that merely
touch collide and one day of gap separates them. Credentialing packages contend
over a discrete count of committee seats inside one derived cycle bucket, so each
package is individually viable while the bucket as a whole is full.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CONTRACT_FORM_ASSIGNABLE,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_NOT_REQUESTED,
    PACKAGE_STATUS_DRAFT,
    PACKAGE_STATUS_SUBMITTED,
    PACKAGE_STATUS_WITHDRAWN,
    PAYER_TYPE_COMMERCIAL,
)
from test_helpers.fixtures import (
    INTEGRATION_MANAGER,
    act_on_novation,
    board_review_deal,
    create_acquisition,
    create_package,
    create_payer_contract,
    reset_clock,
    second_physician,
    set_package_status,
)

INCUMBENT_PAYER = "Aetna Choice"
OTHER_PAYER = "Cigna Open Access"
INCUMBENT_EFFECTIVE_ON = "2026-11-01"
INCUMBENT_TERMINATES_ON = "2027-10-31"
# A renewal starting on the incumbent's last day shares exactly one day.
TOUCHING_EFFECTIVE_ON = "2027-10-31"
TOUCHING_TERMINATES_ON = "2028-10-30"
# One day later there is a gap, and the same renewal is admitted.
GAPPED_EFFECTIVE_ON = "2027-11-01"
GAPPED_TERMINATES_ON = "2028-10-31"
EARLIER_EFFECTIVE_ON = "2026-10-01"
EARLIER_TERMINATES_ON = "2026-10-31"


def _acquisition_with_two_incumbent_payers(api: ApiClient):
    """Identical terms for two different payers, both accepted."""
    reset_clock(api)
    acquisition = create_acquisition(api)
    aetna = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=INCUMBENT_PAYER,
        effective_on=INCUMBENT_EFFECTIVE_ON,
        terminates_on=INCUMBENT_TERMINATES_ON,
    )
    cigna = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=OTHER_PAYER,
        notice_days_required=60,
        annual_revenue_share_bps=1_500,
        effective_on=INCUMBENT_EFFECTIVE_ON,
        terminates_on=INCUMBENT_TERMINATES_ON,
    )
    return {"acquisition": acquisition, "aetna": aetna, "cigna": cigna}


def _renewal(api: ApiClient, acquisition_id: str, effective_on: str, terminates_on: str):
    return api.create_payer_contract(
        f.payer_contract_payload(
            acquisition_id,
            payer_name=INCUMBENT_PAYER,
            payer_type=PAYER_TYPE_COMMERCIAL,
            contract_form=CONTRACT_FORM_ASSIGNABLE,
            effective_on=effective_on,
            terminates_on=terminates_on,
        ),
        INTEGRATION_MANAGER,
    )


def test_a_renewal_starting_on_the_incumbents_last_day_collides(api: ApiClient):
    """The term is closed on both endpoints, so a single shared day is an overlap.

    PRD: "Two contracts that merely touch — one terminating on the very day the
    next becomes effective — do collide, and the collision is reported as
    `ERR_PAYER_CONTRACT_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/payer_contract_closed_interval_touching_endpoint_collides
    """
    world = _acquisition_with_two_incumbent_payers(api)

    rejected = _renewal(
        api, world["acquisition"]["id"], TOUCHING_EFFECTIVE_ON, TOUCHING_TERMINATES_ON
    )

    validate_error(rejected, ApiErrorId.PAYER_CONTRACT_INTERVAL_OVERLAP, 409)
    rows = a.assert_total_count(
        api.list_payer_contracts({"acquisition_id": world["acquisition"]["id"]}, INTEGRATION_MANAGER),
        2,
    )
    a.assert_contains_id(rows, world["aetna"]["id"])
    a.assert_contains_id(rows, world["cigna"]["id"])

    incumbent = validate_success(api.get_payer_contract(world["aetna"]["id"], INTEGRATION_MANAGER))
    assert incumbent["terminates_on"] == INCUMBENT_TERMINATES_ON
    assert incumbent["novation_status"] == NOVATION_NOT_REQUESTED


def test_one_day_of_gap_is_enough_to_admit_the_renewal(api: ApiClient):
    """Shifting the same term one day later removes the shared day and passes.

    PRD: "A single day of gap is required: a new term beginning the day after a
    peer's last day is accepted."

    Design: Difficulty/resource_temporal_overlap/payer_contract_closed_interval_touching_endpoint_collides
    """
    world = _acquisition_with_two_incumbent_payers(api)
    validate_error(
        _renewal(api, world["acquisition"]["id"], TOUCHING_EFFECTIVE_ON, TOUCHING_TERMINATES_ON),
        ApiErrorId.PAYER_CONTRACT_INTERVAL_OVERLAP,
        409,
    )

    accepted = validate_success(
        _renewal(api, world["acquisition"]["id"], GAPPED_EFFECTIVE_ON, GAPPED_TERMINATES_ON), 201
    )

    assert accepted["effective_on"] == GAPPED_EFFECTIVE_ON
    assert accepted["terminates_on"] == GAPPED_TERMINATES_ON
    assert accepted["novation_status"] == NOVATION_NOT_REQUESTED
    a.assert_fields_null(accepted, "notice_sent_on", "consent_received_on")
    a.assert_total_count(
        api.list_payer_contracts({"acquisition_id": world["acquisition"]["id"]}, INTEGRATION_MANAGER),
        3,
    )


def test_the_collision_is_scoped_to_the_payer_name_within_one_acquisition(api: ApiClient):
    """A different payer may hold the identical term; only same-payer terms contend.

    PRD: "At creation the server compares the new term against every other
    contract that shares both the `acquisition_id` and the `payer_name` and whose
    `novation_status` is neither `DENIED` nor `TERMINATED` — denied and terminated
    contracts cover nothing and are excluded from the comparison."

    Design: Difficulty/resource_temporal_overlap/payer_contract_closed_interval_touching_endpoint_collides
    """
    world = _acquisition_with_two_incumbent_payers(api)

    assert world["cigna"]["effective_on"] == world["aetna"]["effective_on"]
    assert world["cigna"]["terminates_on"] == world["aetna"]["terminates_on"]
    assert world["cigna"]["payer_name"] == OTHER_PAYER
    assert world["cigna"]["id"] != world["aetna"]["id"]

    by_payer = a.assert_total_count(
        api.list_payer_contracts(
            {"acquisition_id": world["acquisition"]["id"], "payer_name": INCUMBENT_PAYER},
            INTEGRATION_MANAGER,
        ),
        1,
    )
    a.assert_contains_id(by_payer, world["aetna"]["id"])
    a.assert_excludes_id(by_payer, world["cigna"]["id"])


def test_a_term_entirely_before_the_incumbent_does_not_collide(api: ApiClient):
    """Containment, not same-payer exclusivity, is what the check measures.

    PRD: "The term is a closed interval on both endpoints, so two terms collide
    whenever the new `effective_on` is on or before the peer's `terminates_on` and
    the peer's `effective_on` is on or before the new `terminates_on`."

    Design: Difficulty/resource_temporal_overlap/payer_contract_closed_interval_touching_endpoint_collides
    """
    world = _acquisition_with_two_incumbent_payers(api)

    accepted = validate_success(
        _renewal(api, world["acquisition"]["id"], EARLIER_EFFECTIVE_ON, EARLIER_TERMINATES_ON), 201
    )

    assert accepted["effective_on"] == EARLIER_EFFECTIVE_ON
    assert accepted["terminates_on"] == EARLIER_TERMINATES_ON
    a.assert_total_count(
        api.list_payer_contracts(
            {"acquisition_id": world["acquisition"]["id"], "payer_name": INCUMBENT_PAYER},
            INTEGRATION_MANAGER,
        ),
        2,
    )


# ---------------------------------------------------------------------------
# Discrete committee-seat capacity inside one derived cycle bucket
# ---------------------------------------------------------------------------

COMMITTEE_SLOTS = 2
FILING_DATE = "2026-08-03"
AUGUST_CYCLE_KEY = "2026-08-15"
COMMERCIAL_PROJECTED_EFFECTIVE_ON = "2026-11-01"
LATE_FILING_DATE = "2026-08-16"
SEPTEMBER_CYCLE_KEY = "2026-09-01"
LATE_PROJECTED_EFFECTIVE_ON = "2026-11-15"
LATER_CLOSE_ON = "2027-01-01"
# A fourth provider, needed because the three in the helper each already hold a
# live package on the contract and only one live package per provider-and-payer
# pair is admitted.
NPI_D = "1730492857"


def _noticed_contract_with_three_physicians(api: ApiClient, **acq_overrides):
    """A two-seat committee with three drafted packages all in the same cycle."""
    deal = board_review_deal(api, **acq_overrides)
    acquisition_id = deal["acquisition"]["id"]

    contract = create_payer_contract(
        api,
        acquisition_id,
        payer_name=INCUMBENT_PAYER,
        payer_type=PAYER_TYPE_COMMERCIAL,
        contract_form=CONTRACT_FORM_ASSIGNABLE,
        committee_slots_per_cycle=COMMITTEE_SLOTS,
    )
    act_on_novation(api, contract["id"], NOVATION_ACTION_SEND_NOTICE)

    physician_b = second_physician(api, acquisition_id)
    physician_c = second_physician(
        api,
        acquisition_id,
        npi="1922384756",
        full_name="Chandra Oyelaran MD",
        state_license_expires_on="2029-03-31",
    )

    packages = []
    for physician in (deal["physician"], physician_b, physician_c):
        packages.append(
            create_package(
                api, acquisition_id, physician["id"], contract["id"], submitted_on=FILING_DATE
            )
        )
    set_package_status(api, packages[0]["id"], PACKAGE_STATUS_SUBMITTED)
    set_package_status(api, packages[1]["id"], PACKAGE_STATUS_SUBMITTED)

    deal["contract"] = contract
    deal["physician_b"] = physician_b
    deal["physician_c"] = physician_c
    deal["packages"] = packages
    return deal


def _file(api: ApiClient, package_id: str):
    return api.set_credentialing_package_status(
        package_id, f.package_status_payload(PACKAGE_STATUS_SUBMITTED), INTEGRATION_MANAGER
    )


def test_the_third_filing_into_a_two_seat_cycle_is_refused(api: ApiClient):
    """The limit is an aggregate over the bucket, not a property of the package.

    PRD: "And the committee cycle must still have a free seat: strictly fewer than
    the linked contract's `committee_slots_per_cycle` other packages on the same
    `payer_contract_id` may already share this package's `committee_cycle_key` in
    `SUBMITTED`, `IN_REVIEW`, or `APPROVED`, or the filing fails with
    `ERR_COMMITTEE_CYCLE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/credentialing_committee_cycle_aggregate_capacity_exceeded
    """
    deal = _noticed_contract_with_three_physicians(api)
    third = deal["packages"][2]

    rejected = _file(api, third["id"])

    validate_error(rejected, ApiErrorId.COMMITTEE_CYCLE_CAPACITY_EXCEEDED, 409)
    unchanged = validate_success(api.get_credentialing_package(third["id"], INTEGRATION_MANAGER))
    a.assert_status(unchanged, PACKAGE_STATUS_DRAFT)
    assert unchanged["committee_cycle_key"] == AUGUST_CYCLE_KEY


def test_every_contender_lands_in_the_same_cycle_and_is_individually_viable(api: ApiClient):
    """Only the seat count breaches; each package satisfies the lead-time rule alone.

    PRD: "The package's `projected_effective_on` must not fall after
    `target_close_on` extended by the payer's retro-billing window, or the filing
    fails with `ERR_CREDENTIALING_LEAD_TIME_MISSED`; landing exactly on that limit
    is viable and one day past it is not, which means an identical filing date can
    be perfectly viable for a `MEDICARE` contract and fatal for a `COMMERCIAL`
    one."

    Design: Difficulty/resource_temporal_overlap/credentialing_committee_cycle_aggregate_capacity_exceeded
    """
    deal = _noticed_contract_with_three_physicians(api)
    assert deal["acquisition"]["target_close_on"] == COMMERCIAL_PROJECTED_EFFECTIVE_ON

    for package in deal["packages"]:
        assert package["committee_cycle_key"] == AUGUST_CYCLE_KEY
        assert package["projected_effective_on"] == COMMERCIAL_PROJECTED_EFFECTIVE_ON
        assert package["lead_days"] == 90
        assert package["retro_billing_allowed"] is False

    seated = a.assert_total_count(
        api.list_credentialing_packages(
            {"payer_contract_id": deal["contract"]["id"], "status": PACKAGE_STATUS_SUBMITTED},
            INTEGRATION_MANAGER,
        ),
        COMMITTEE_SLOTS,
    )
    a.assert_excludes_id(seated, deal["packages"][2]["id"])


def test_withdrawing_an_occupant_frees_exactly_one_seat(api: ApiClient):
    """The identical filing succeeds once a seat is given back.

    PRD: "`SUBMITTED → WITHDRAWN` and `IN_REVIEW → WITHDRAWN` each free the
    package's seat in its `committee_cycle_key` on the linked payer contract, so a
    subsequent filing into that cycle succeeds where it would previously have
    exceeded capacity."

    Design: Difficulty/resource_temporal_overlap/credentialing_committee_cycle_aggregate_capacity_exceeded
    """
    deal = _noticed_contract_with_three_physicians(api)
    third = deal["packages"][2]
    validate_error(_file(api, third["id"]), ApiErrorId.COMMITTEE_CYCLE_CAPACITY_EXCEEDED, 409)

    withdrawn = set_package_status(api, deal["packages"][1]["id"], PACKAGE_STATUS_WITHDRAWN)
    a.assert_status(withdrawn, PACKAGE_STATUS_WITHDRAWN)

    filed = validate_success(_file(api, third["id"]))
    a.assert_status(filed, PACKAGE_STATUS_SUBMITTED)
    assert filed["committee_cycle_key"] == AUGUST_CYCLE_KEY


def test_seats_are_counted_per_cycle_bucket_not_per_contract(api: ApiClient):
    """A later filing date lands in the next bucket and meets no contention.

    PRD: "The assignment is lower-inclusive: a package with `submitted_on` of
    2026-09-15 belongs to the 2026-09-15 cycle, while one with `submitted_on` of
    2026-09-16 belongs to the 2026-10-01 cycle."

    Design: Difficulty/resource_temporal_overlap/credentialing_committee_cycle_aggregate_capacity_exceeded
    """
    deal = _noticed_contract_with_three_physicians(api, target_close_on=LATER_CLOSE_ON)
    validate_error(
        _file(api, deal["packages"][2]["id"]), ApiErrorId.COMMITTEE_CYCLE_CAPACITY_EXCEEDED, 409
    )

    # A fourth provider is needed for the next bucket: each of the first three
    # already holds a live package on this contract, and PRD forbids a second one
    # — "if another package for the same `physician_id` and `payer_contract_id` is
    # in `DRAFT`, `SUBMITTED`, `IN_REVIEW`, or `APPROVED`, the create is rejected
    # with `ERR_DUPLICATE_CREDENTIALING_PACKAGE`".
    physician_d = second_physician(
        api,
        deal["acquisition"]["id"],
        npi=NPI_D,
        full_name="Delphine Okonkwo MD",
        state_license_expires_on="2029-06-30",
    )
    next_cycle = create_package(
        api,
        deal["acquisition"]["id"],
        physician_d["id"],
        deal["contract"]["id"],
        submitted_on=LATE_FILING_DATE,
    )
    assert next_cycle["committee_cycle_key"] == SEPTEMBER_CYCLE_KEY
    assert next_cycle["projected_effective_on"] == LATE_PROJECTED_EFFECTIVE_ON

    filed = validate_success(_file(api, next_cycle["id"]))
    a.assert_status(filed, PACKAGE_STATUS_SUBMITTED)
