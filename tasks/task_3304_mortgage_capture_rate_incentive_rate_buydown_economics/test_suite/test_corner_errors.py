"""Corner coverage - reaching each error identifier the catalogue declares."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, CLOSING_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def scored_application(api, *, income: int, debt: int):
    """A pending contract holding one submitted third-party application."""
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    application = fixtures.create_application(
        api, world["ct1"], lender_entity_code="THIRD_PARTY_LENDER",
        qualifying_income_cents=income, monthly_debt_cents=debt,
    )
    world.update({"application": application, "la1": application["id"]})
    return world


def test_an_application_below_the_score_floor_cannot_qualify(api):
    """A weak profile scores under the floor and qualification is refused on that rung.

    PRD §2.10: "Priority 9 requires that the application's `qualification_score` be at
    least the floor of 620; failure yields `ERR_QUALIFICATION_SCORE_BELOW_FLOOR` at
    HTTP 422".
    PRD §3.3: "Qualification by a `MortgageBanker` moves the application from
    `SUBMITTED` to `QUALIFIED` and is permitted only when the application is currently
    `SUBMITTED`, its `qualification_score` is at least the floor of 620".
    Design: Corner/errors/error_qualification_score_below_floor_is_triggerable
    """
    # Income 1_200_000 and debt 500_000 give 300 + 24 + 60 + max(0, 250 - 104) = 530, under
    # the floor of 620, while dti_bps is 10000 * 500000 // 1200000 = 4166, inside the 4500
    # ceiling, so the score rung is the only one that can fire.
    world = scored_application(api, income=1_200_000, debt=500_000)
    application = fixtures.read_application(api, world["la1"])
    assert application["qualification_score"] < 620, (
        f"the profile is meant to sit under the floor, got {application['qualification_score']}"
    )

    refused = api.qualify_loan_application(world["la1"], BANKER_HEADERS)
    validate_error(refused, "ERR_QUALIFICATION_SCORE_BELOW_FLOOR", 422)


def test_the_refused_qualification_leaves_the_application_submitted(api):
    """The application stays where it was, so the gate had no partial effect.

    PRD §2.10: "Priority 8 requires that the application's `dti_bps` not exceed the
    qualifying ceiling of 4500 basis points; failure yields `ERR_DTI_CEILING_EXCEEDED`
    at HTTP 422".
    PRD §3.3: "Both gates are enforced by the ladder: a score below the floor yields
    `ERR_QUALIFICATION_SCORE_BELOW_FLOOR` at HTTP 422".
    Design: Corner/errors/error_qualification_score_below_floor_is_triggerable
    """
    # Income at the two-hundred-thousand-dollar mark and debt at the one-hundred-thousand
    # mark: the score is 300 + 0 + 0 + 0 = 300, far below the floor, while the ratio is
    # 10000 * 10000 // 200000 = 500 basis points, comfortably inside the 4500 ceiling, so
    # the score rung is the only one that can fire.
    world = scored_application(api, income=200_000, debt=100_000)
    api.qualify_loan_application(world["la1"], BANKER_HEADERS)

    application = fixtures.read_application(api, world["la1"])
    assert application["application_status"] == "SUBMITTED", application["application_status"]
    assert application["uw_precedence"] == "SUBMITTED_NOT_REQUESTED", (
        application["uw_precedence"]
    )


def test_a_debt_ratio_above_the_ceiling_cannot_qualify(api):
    """A ratio above 4500 basis points is refused on its own rung.

    PRD §3.3: "The same rule simultaneously computes `dti_bps` as monthly debt
    multiplied by ten thousand, floored over qualifying income".
    PRD §2.10: "Priority 8 requires that the application's `dti_bps` not exceed the
    qualifying ceiling of 4500 basis points; failure yields `ERR_DTI_CEILING_EXCEEDED`
    at HTTP 422, and the check applies to qualification."
    Design: Corner/errors/error_dti_ceiling_exceeded_is_triggerable
    """
    world = scored_application(api, income=2_000_000, debt=980_000)
    application = fixtures.read_application(api, world["la1"])
    assert application["dti_bps"] == 4900, (
        f"(980_000 * 10000) // 2_000_000 is 4900, got {application['dti_bps']}"
    )

    refused = api.qualify_loan_application(world["la1"], BANKER_HEADERS)
    validate_error(refused, "ERR_DTI_CEILING_EXCEEDED", 422)


def relock_ready_world(api):
    """A contract holding one active lock whose application stays qualified across expiries.

    The community is built from scratch so the long-lived pool this test funds the lock
    from is the community's only commitment (PRD section 3.6 refuses an overlapping
    window, and PRD section 3.5 requires the clock to lie inside the chosen window).
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(api)
    buyer = fixtures.create_buyer(api)
    world = {"cm1": community["id"], "b1": buyer["id"]}
    site = fixtures.create_home_site(api, world["cm1"])
    commitment = fixtures.create_commitment(
        api, world["cm1"], commitment_code="LONG",
        commitment_start_iso="2026-09-01T00:00:00Z",
        commitment_end_iso="2032-01-01T00:00:00Z", committed_units=9,
    )
    world.update({"hs1": site["id"], "fc1": commitment["id"]})

    contract = fixtures.create_contract(api, world["hs1"], world["b1"])
    world.update({"ct1": contract["id"]})
    application = fixtures.create_application(api, world["ct1"])
    application = get_success_data(api.qualify_loan_application(application["id"], BANKER_HEADERS))
    world.update({"la1": application["id"]})

    lock = get_success_data(
        api.create_rate_lock(
            world["la1"],
            f.rate_lock_payload(world["fc1"], lock_days=30,
                                expected_application_version=application["version"]),
            BANKER_HEADERS,
        )
    )
    world.update({"lk1": lock["id"]})
    return world


def test_the_relock_limit_is_reached_after_two_previous_relocks(api):
    """A deterministic clock sequence exhausts both allowed revivals.

    PRD §2.10: "Priority 15 requires that the target lock's `relock_count` be below the
    maximum of two; failure yields `ERR_RELOCK_LIMIT_REACHED` at HTTP 409".
    PRD §3.5: "A lock that has already been relocked twice is refused with
    `ERR_RELOCK_LIMIT_REACHED` at HTTP 409".
    Design: Corner/errors/error_relock_limit_reached_is_triggerable_after_two_relocks
    """
    world = relock_ready_world(api)

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    first = get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    assert first["relock_count"] == 1, first["relock_count"]

    fixtures.set_clock(api, "2026-11-10T00:00:00Z")
    second = get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    assert second["relock_count"] == 2, second["relock_count"]

    fixtures.set_clock(api, "2026-12-15T00:00:00Z")
    refused = api.relock_rate_lock(world["lk1"], BANKER_HEADERS)
    validate_error(refused, "ERR_RELOCK_LIMIT_REACHED", 409)


def test_the_refused_third_relock_leaves_the_counter_and_the_posture_alone(api):
    """The counter stays at two and the lock stays where the clock left it.

    PRD §3.5: "A revival returns the lock to `ACTIVE`, increments `relock_count` by one".
    PRD §2.13: "Setting the clock forward applies every clock-driven transition in one
    pass: a rate lock whose `lock_expires_iso` has passed moves from `ACTIVE` to `EXPIRED`".
    Design: Corner/errors/error_relock_limit_reached_is_triggerable_after_two_relocks
    """
    world = relock_ready_world(api)
    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    fixtures.set_clock(api, "2026-11-10T00:00:00Z")
    get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    fixtures.set_clock(api, "2026-12-15T00:00:00Z")
    api.relock_rate_lock(world["lk1"], BANKER_HEADERS)

    lock = fixtures.read_rate_lock(api, world["lk1"])
    assert lock["relock_count"] == 2, (
        f"the refused revival does not move the witness, got {lock['relock_count']}"
    )
    assert lock["lock_status"] == "EXPIRED", lock["lock_status"]


def test_a_buyer_default_in_an_unmapped_state_selects_no_statute(api):
    """The statute selector has no mapped basis for the retention, so the cancel fails.

    PRD §3.8: "a buyer residing anywhere else yields no statute at all — that last case
    is a failure, surfacing as `ERR_FORFEITURE_STATUTE_UNDETERMINED` at HTTP 409".
    PRD §3.8: "The statute is selected from two facts and nothing else: the cancelled
    contract's `cancellation_reason` and the buyer's `state_code`."
    Design: Corner/errors/error_forfeiture_statute_undetermined_on_unmapped_state
    """
    world = fixtures.seed_reference_data(api)
    buyer = fixtures.create_buyer(api, state_code="OH")
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], buyer["id"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    refused = api.cancel_contract(world["ct1"], "BUYER_DEFAULT", SALES_HEADERS)
    validate_error(refused, "ERR_FORFEITURE_STATUTE_UNDETERMINED", 409)


def test_the_unmapped_cancellation_leaves_no_half_cancelled_state(api):
    """The contract stays pending and no settlement row is written.

    PRD §3.8: "Exactly one statute is selected per contract, so no tie-break arises".
    PRD §3.4: "The contract moves to `CANCELLED` with that reason recorded, its home
    site returns from `UNDER_CONTRACT` to `AVAILABLE`".
    Design: Corner/errors/error_forfeiture_statute_undetermined_on_unmapped_state
    """
    world = fixtures.seed_reference_data(api)
    buyer = fixtures.create_buyer(api, state_code="OH")
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], buyer["id"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})
    api.cancel_contract(world["ct1"], "BUYER_DEFAULT", SALES_HEADERS)

    after = fixtures.read_contract(api, world["ct1"])
    assert after["contract_status"] == "PENDING", after["contract_status"]

    settlements, _ = fixtures.rows(
        api.list_contract_deposit_forfeitures(world["ct1"], world["closing_headers"])
    )
    assert settlements == [], f"the aborted cancellation settled nothing, got {settlements}"


def open_cure_blocked_world(api):
    """A cancelled contract whose settlement is proposed but whose cure window is open.

    The affiliated-business disclosure is delivered and acknowledged before the
    rate-buydown allocation, because PRD section 3.7 refuses that allocation until the
    obligation is met; a rate-buydown terms form is then delivered and left issued so
    the deal carries an open cure window when it is cancelled for a rate shock.
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    aba = fixtures.deliver_disclosure(api, world["ct1"])
    world.update({"d0": aba["id"]})
    fixtures.acknowledge(api, world["d0"], world["b1"])

    allocation = fixtures.allocate(api, world["ct1"], "RATE_BUYDOWN", 6_000_000)
    world.update({"al1": allocation["id"]})

    terms = fixtures.deliver_disclosure(
        api, world["ct1"], disclosure_type="RATE_BUYDOWN_TERMS"
    )
    world.update({"d1": terms["id"]})

    settlement = get_success_data(
        api.cancel_contract(world["ct1"], "RATE_SHOCK", SALES_HEADERS)
    )
    world.update({"cancelled": settlement})
    return world


def test_finalising_a_settlement_under_an_open_cure_window_is_refused(api):
    """The unexpired cure obligation blocks the accounting seal.

    PRD §3.8: "A settlement that violates the posture or cure requirements is refused
    with `ERR_FORFEITURE_NOT_PROPOSED` at HTTP 409."
    PRD §2.10: "`ERR_FORFEITURE_NOT_PROPOSED` at HTTP 409 when a settlement is finalized
    in the wrong posture or while a blocking cure window is still unexpired."
    Design: Corner/errors/error_forfeiture_not_proposed_when_an_open_cure_window_blocks_finalisation
    """
    world = open_cure_blocked_world(api)

    settlements, _ = fixtures.rows(
        api.list_contract_deposit_forfeitures(world["ct1"], world["closing_headers"])
    )
    assert len(settlements) == 1, f"the cancellation proposed one settlement, got {len(settlements)}"
    proposed = settlements[0]
    assert proposed["forfeiture_status"] == "PROPOSED", proposed["forfeiture_status"]

    refused = api.finalize_deposit_forfeiture(proposed["id"], CLOSING_HEADERS)
    validate_error(refused, "ERR_FORFEITURE_NOT_PROPOSED", 409)


def test_the_blocked_finalisation_retains_nothing_and_leaves_the_deal_cancelled(api):
    """Neither the deposit nor the contract posture moves while the seal is refused.

    PRD §3.8: "Finalisation moves the settlement to `FINALIZED`, writes the forfeited
    amount to the contract's `deposit_held_cents`, moves the buyer to the terminal
    `WITHDRAWN` posture".
    PRD §3.8: "A proposal that is still open when the deal is reinstated is voided rather
    than finalised, moving from `PROPOSED` to its terminal `VOIDED` posture".
    Design: Corner/errors/error_forfeiture_not_proposed_when_an_open_cure_window_blocks_finalisation
    """
    world = open_cure_blocked_world(api)
    settlements, _ = fixtures.rows(
        api.list_contract_deposit_forfeitures(world["ct1"], world["closing_headers"])
    )
    api.finalize_deposit_forfeiture(settlements[0]["id"], CLOSING_HEADERS)

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "CANCELLED", contract["contract_status"]
    assert contract["deposit_held_cents"] == 0, (
        f"the blocked seal moved no money, got {contract['deposit_held_cents']}"
    )

    settlement = fixtures.read_forfeiture(api, settlements[0]["id"])
    assert settlement["forfeiture_status"] == "PROPOSED", (
        f"the proposal stays open, got {settlement['forfeiture_status']}"
    )