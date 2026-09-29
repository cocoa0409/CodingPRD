"""The four parent-version guards, each with a real interleaving behind it.

PRD 2.7 names the write that carries each token and the drift that invalidates
it; PRD 2.8 places the guard at priority 8, and PRD 2.5 keeps a refused write
from moving the version it was checked against. Each test therefore reads the
parent, lets a second writer move it, and only then submits the stale token -
then retries with a refreshed one and identical business content.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    REVENUE_MANAGER,
    REVENUE_MANAGER_ALT,
    SALES_MANAGER,
    AnalysisStatus,
    AnalysisVariant,
    ApiErrorId,
    ChargeCategory,
    ChargeStatus,
    ContractStatus,
    LeadStatus,
    QuoteStatus,
    ReconciliationStatus,
    assert_ancillary_charge,
    assert_block_night,
    assert_displacement_analysis,
    assert_group_contract,
    assert_lead,
    assert_rate_quote,
    assert_reconciliation,
    assert_room_block,
    block_version,
    constants as C,
    contract_version,
    factories as F,
    lead_version,
    night_on,
    read_block,
    read_contract,
    read_lead,
    seed_ancillary_charge,
    seed_cleared_lead,
    seed_cut_off_master,
    seed_displacement_analysis,
    seed_open_master_block,
    seed_qualified_lead,
    seed_signed_contract,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_HISTORICAL = {"analysis_variant": AnalysisVariant.HISTORICAL_BASED}


def test_a_quote_drafted_from_a_stale_lead_view_is_refused_and_writes_nothing(api):
    """The drift moves the version without moving the status, so only 2.7 can see it.

    PRD 2.7 requires expected_lead_version on a quote draft and refuses a
    mismatch with ERR_STALE_LEAD_VERSION, because "a newly drafted quote
    legitimately supersedes a DRAFT quote already sitting on the lead, so a writer
    working from a stale view of the lead would silently discard a sibling quote
    it never saw". The interleaving here is the re-study PRD 3.3 allows against
    already-cleared business: it advances the lead's version while leaving the
    negotiation stage at CLEARED, so a status-based guard sees nothing wrong. PRD
    2.5 then says the refused write leaves no trace, and the retry with the
    refreshed token carries identical business content, which rules out any other
    reason for the first refusal. Drafting a quote is not one of the writes PRD
    3.2 lists as advancing the lead, so the token does not move again.

    Design: Corner/cross_cutting_complexity_layers/a_quote_written_from_a_stale_lead_view_is_refused_and_a_refreshed_one_is_not
    """
    world = seed_cleared_lead(api)
    stale = lead_version(api, world["lead_id"])
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.CLEARED, version=4)

    seed_displacement_analysis(api, world, **_HISTORICAL)
    refreshed = lead_version(api, world["lead_id"])
    assert refreshed == stale + 1, (
        f"the re-study moved the lead from {stale} to {refreshed}"
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.CLEARED)

    body = F.rate_quote_payload(world["lead_id"], world["package_id"], stale)
    validate_error(
        api.create_rate_quote(body, SALES_MANAGER),
        ApiErrorId.STALE_LEAD_VERSION,
        412,
    )
    _, meta = validate_paginated(
        api.list_rate_quotes(SALES_MANAGER, lead_id=world["lead_id"])
    )
    assert meta["total_count"] == 0, "the refused draft created no quote row"

    assert_rate_quote(
        validate_success(
            api.create_rate_quote(
                F.rate_quote_payload(
                    world["lead_id"], world["package_id"], refreshed
                ),
                SALES_MANAGER,
            ),
            201,
        ),
        status=QuoteStatus.DRAFT,
        negotiation_round=1,
    )
    assert lead_version(api, world["lead_id"]) == refreshed, (
        "drafting a quote does not itself advance the lead"
    )


def test_a_decision_from_a_stale_lead_view_leaves_the_study_untouched(api):
    """A 412 on a four-precondition transition must stamp absolutely nothing.

    PRD 2.7 warns that "requesting an additional study under the other series
    variant advances the lead's version, and clearing the lead from a stale view
    would approve a displacement picture the decider never inspected". The
    decision is the write with the most side effects in PRD 3.3 - the analysis
    status, its decided_by_user_id, the lead's own status - so a guard evaluated
    after any of them would leave observable damage behind its own 412. PRD 2.5
    also keeps the refusal from advancing the lead. The refreshed retry then
    clears the lead even though the second study is still PENDING, since PRD 3.3
    moves the stage on the first approval.

    Design: Corner/cross_cutting_complexity_layers/a_displacement_decision_from_a_stale_lead_view_is_refused_and_leaves_the_study_pending
    """
    world = seed_qualified_lead(api)
    analysis = seed_displacement_analysis(api, world)
    stale = lead_version(api, world["lead_id"])
    assert stale == 3, f"capture, qualification and the first study: {stale}"

    seed_displacement_analysis(api, world, **_HISTORICAL)

    validate_error(
        api.decide_displacement_analysis(
            analysis["id"],
            F.decide_payload(decision="APPROVE", expected_lead_version=stale),
            REVENUE_MANAGER_ALT,
        ),
        ApiErrorId.STALE_LEAD_VERSION,
        412,
    )

    assert_displacement_analysis(
        validate_success(
            api.get_displacement_analysis(analysis["id"], REVENUE_MANAGER)
        ),
        status=AnalysisStatus.PENDING,
        decided_by_user_id=None,
    )
    refreshed = lead_version(api, world["lead_id"])
    assert_lead(
        read_lead(api, world["lead_id"]),
        status=LeadStatus.DISPLACEMENT_REVIEW,
        version=4,
    )

    assert_displacement_analysis(
        validate_success(
            api.decide_displacement_analysis(
                analysis["id"],
                F.decide_payload(decision="APPROVE", expected_lead_version=refreshed),
                REVENUE_MANAGER_ALT,
            )
        ),
        status=AnalysisStatus.APPROVED,
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.CLEARED, version=5)


_TWO_ON_TWO_NIGHTS = F.allotment_plan(("2026-11-09", 2), ("2026-11-10", 2))


def test_a_sub_block_from_a_stale_parent_view_carves_out_nothing(api):
    """The rooms it asks for are free, so only the token can explain the refusal.

    PRD 2.7 guards a sub-block with expected_parent_block_version because "every
    sub-block carves rooms out of the parent's per-night allotment and bumps the
    parent's version, so a writer holding a stale parent version is reasoning
    about unallocated rooms that are already taken". Here the stale token and the
    capacity rule of PRD 3.6 point in the same direction, which makes the order of
    the two checks the whole point: PRD 2.8 puts the version guard at priority 8
    and the sub-block capacity rule at priority 30, so the answer is the 412 - and
    the second attempt with a refreshed token proves the two rooms it wanted were
    available all along. PRD 2.5 keeps the refused write from carving anything or
    from moving the parent.

    Design: Corner/cross_cutting_complexity_layers/a_sub_block_written_from_a_stale_parent_view_is_refused_and_carves_out_nothing
    """
    world = seed_signed_contract(api)
    master_id = world["master_block_id"]
    stale = block_version(api, master_id)

    first = validate_success(
        api.create_room_block(
            F.sub_block_payload(
                master_id, stale, name="SUB-A", nightly_allotments=_TWO_ON_TWO_NIGHTS
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert_room_block(first, parent_block_id=master_id, is_master=False)

    validate_error(
        api.create_room_block(
            F.sub_block_payload(
                master_id, stale, name="SUB-B", nightly_allotments=_TWO_ON_TWO_NIGHTS
            ),
            CONTRACT_ADMIN,
        ),
        ApiErrorId.STALE_BLOCK_VERSION,
        412,
    )

    _, meta = validate_paginated(
        api.list_room_blocks(CONTRACT_ADMIN, parent_block_id=master_id)
    )
    assert meta["total_count"] == 1, "the refused write created no second sub-block"
    refreshed = block_version(api, master_id)
    assert refreshed == stale + 1, f"only SUB-A moved the parent: {refreshed}"
    assert_block_night(
        night_on(api, master_id, "2026-11-09"), rooms_sub_allocated=2, rooms_open=2
    )

    validate_success(
        api.create_room_block(
            F.sub_block_payload(
                master_id,
                refreshed,
                name="SUB-B",
                nightly_allotments=_TWO_ON_TWO_NIGHTS,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )

    assert_block_night(
        night_on(api, master_id, "2026-11-09"), rooms_sub_allocated=4, rooms_open=0
    )
    assert_room_block(read_block(api, master_id), version=refreshed + 1)


def test_a_settlement_opened_from_a_stale_contract_view_is_refused(api):
    """The drift is a ledger event on another entity, invisible to the lifecycle.

    PRD 2.7 guards the settlement with expected_contract_version because "an
    attrition waiver or a newly posted ancillary charge bumps the contract's
    version, so a stale writer would settle on numbers that no longer hold" - and
    PRD 3.9 repeats it: "the settlement numbers were read from a contract, and if
    that contract moved in the meantime the figures are stale". The drift here
    never touches the contract's own status, which stays SIGNED throughout.
    Creating the charge is not the drift either: PRD 3.8 starts a charge in QUOTED,
    "outside the settlement input set until it is posted", so the ledger and the
    version both move only on the post. The refreshed retry then opens a DRAFT
    that already carries the 450000 the post added.

    Design: Corner/cross_cutting_complexity_layers/a_reconciliation_opened_from_a_stale_contract_view_is_refused
    """
    world = seed_open_master_block(api)
    seed_cut_off_master(api, world)
    set_clock(api, C.POST_DEPARTURE_CLOCK)
    charge = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
    )
    stale = contract_version(api, world["contract_id"])
    assert_group_contract(
        read_contract(api, world["contract_id"]),
        status=ContractStatus.SIGNED,
        ancillary_posted_cents=0,
    )

    assert_ancillary_charge(
        validate_success(api.post_ancillary_charge(charge["id"], ACCOUNTING_CLERK)),
        status=ChargeStatus.POSTED,
    )
    posted = read_contract(api, world["contract_id"])
    assert_group_contract(
        posted, status=ContractStatus.SIGNED, ancillary_posted_cents=450000
    )
    refreshed = posted["version"]
    assert refreshed == stale + 1, (
        f"posting moved the contract from {stale} to {refreshed}"
    )

    validate_error(
        api.create_reconciliation(
            world["contract_id"], F.reconciliation_payload(stale), ACCOUNTING_CLERK
        ),
        ApiErrorId.STALE_CONTRACT_VERSION,
        412,
    )
    _, meta = validate_paginated(
        api.list_contract_reconciliations(world["contract_id"], ACCOUNTING_CLERK)
    )
    assert meta["total_count"] == 0, "no draft settlement was left behind"

    assert_reconciliation(
        validate_success(
            api.create_reconciliation(
                world["contract_id"],
                F.reconciliation_payload(refreshed),
                ACCOUNTING_CLERK,
            ),
            201,
        ),
        status=ReconciliationStatus.DRAFT,
        ancillary_net_cents=450000,
    )
