"""Gates that read a different entity than the one being written.

PRD 3.4 refuses an acceptance while any displacement study on the lead is still
PENDING, and PRD 3.8 refuses to post a charge whose parent contract is not
SIGNED; in both cases nothing about the written row's own state explains the
refusal.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    AnalysisStatus,
    AnalysisVariant,
    ApiErrorId,
    CancellationReason,
    ChargeStatus,
    ContractStatus,
    LeadStatus,
    QuoteStatus,
    assert_ancillary_charge,
    assert_group_contract,
    assert_lead,
    assert_rate_quote,
    assert_receivable_identity,
    decide_displacement_analysis,
    factories as F,
    read_contract,
    read_lead,
    seed_ancillary_charge,
    seed_displacement_analysis,
    seed_proposed_quote,
    seed_signed_contract,
    validate_error,
    validate_success,
)


def _proposed_quote_with_pending_sibling(api):
    """A PROPOSED quote on a QUOTED lead that also carries a second, still
    PENDING displacement study requested mid-negotiation (PRD 3.3)."""
    world = seed_proposed_quote(api)
    world["sibling_analysis"] = seed_displacement_analysis(
        api, world, analysis_variant=AnalysisVariant.HISTORICAL_BASED
    )
    return world


def test_accept_is_refused_while_a_sibling_study_is_still_pending(api):
    """The quote is acceptable in every respect except a sibling entity.

    PRD 3.4 admits an acceptance only when "no DisplacementAnalysis of the
    quote's lead is still PENDING", so the second study blocks a PROPOSED,
    unexpired quote accepted by the owning contact; the pending re-study does
    not itself move the lead, which stays QUOTED.

    Design: Difficulty/cross_entity_state_dependency/quote_accept_gated_on_no_pending_displacement_analysis
    """
    world = _proposed_quote_with_pending_sibling(api)

    validate_error(
        api.accept_rate_quote(world["quote_id"], world["group_contact"]),
        ApiErrorId.DISPLACEMENT_NOT_APPROVED,
        409,
    )

    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.QUOTED)
    assert_rate_quote(
        validate_success(api.get_rate_quote(world["quote_id"], world["group_contact"])),
        status=QuoteStatus.PROPOSED,
    )


def test_approving_the_sibling_study_unblocks_the_identical_accept(api):
    """Deciding the other study is the only change the acceptance needed.

    PRD 3.3 leaves a lead that is already QUOTED where it is when a study is
    approved, and PRD 3.4 then accepts the quote, moves the lead to WON and
    keeps the inventory hold in place until signature.

    Design: Difficulty/cross_entity_state_dependency/quote_accept_gated_on_no_pending_displacement_analysis
    """
    world = _proposed_quote_with_pending_sibling(api)
    validate_error(
        api.accept_rate_quote(world["quote_id"], world["group_contact"]),
        ApiErrorId.DISPLACEMENT_NOT_APPROVED,
        409,
    )

    decide_displacement_analysis(api, world, world["sibling_analysis"]["id"])

    for analysis_id in (world["analysis_id"], world["sibling_analysis"]["id"]):
        assert (
            validate_success(
                api.get_displacement_analysis(analysis_id, CONTRACT_ADMIN)
            )["status"]
            == AnalysisStatus.APPROVED
        )

    accepted = validate_success(
        api.accept_rate_quote(world["quote_id"], world["group_contact"])
    )

    assert_rate_quote(accepted, status=QuoteStatus.ACCEPTED, hold_placed=True)
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.WON)


def _signed_contract_with_quoted_charge(api):
    """A SIGNED contract carrying one QUOTED banquet charge of 500000 cents gross,
    which the BANQUET discount of 10 percent nets down to 450000 (PRD 3.8)."""
    world = seed_signed_contract(api)
    world["charge"] = seed_ancillary_charge(
        api, world["contract_id"], gross_amount_cents=500000
    )
    return world


def test_a_charge_cannot_post_once_its_contract_has_left_signed(api):
    """The charge is well formed; its parent contract is the obstacle.

    PRD 3.8 admits a posting only when "the charge to be QUOTED and the contract
    to be SIGNED", so a still-QUOTED charge whose contract has meanwhile been
    cancelled is refused. PRD 3.8 also keeps that charge out of every ledger
    movement, since ancillary_posted_cents "is the sum of net_amount_cents over
    the contract's charges whose status is POSTED; QUOTED and VOIDED charges are
    excluded", so the contract's ancillary ledger stays empty either way.

    Design: Difficulty/cross_entity_state_dependency/ancillary_charge_post_gated_on_contract_signed
    """
    world = _signed_contract_with_quoted_charge(api)

    assert_ancillary_charge(
        world["charge"], net_amount_cents=450000, status=ChargeStatus.QUOTED
    )

    validate_success(
        api.cancel_contract(
            world["contract_id"],
            F.cancel_contract_payload(
                cancellation_reason=CancellationReason.CLIENT_CANCEL,
                note="Programme moved to a competitor",
            ),
            CONTRACT_ADMIN,
        )
    )

    validate_error(
        api.post_ancillary_charge(world["charge"]["id"], ACCOUNTING_CLERK),
        ApiErrorId.CONTRACT_INVALID_STATE,
        409,
    )

    contract = read_contract(api, world["contract_id"])
    assert_group_contract(
        contract, status=ContractStatus.CANCELLED, ancillary_posted_cents=0
    )
    assert_receivable_identity(contract)


def test_the_countersigned_contract_lets_the_same_charge_post(api):
    """A SIGNED parent is exactly what the posting needed.

    PRD 3.8: posting moves the charge QUOTED -> POSTED and on success "the
    contract's ancillary_posted_cents increases by the charge's
    net_amount_cents and the contract's receivable is recomputed", so the
    450000-cent net lands on the contract the countersignature produced.

    Design: Difficulty/cross_entity_state_dependency/ancillary_charge_post_gated_on_contract_signed
    """
    world = _signed_contract_with_quoted_charge(api)

    posted = validate_success(
        api.post_ancillary_charge(world["charge"]["id"], ACCOUNTING_CLERK)
    )

    assert_ancillary_charge(
        posted, status=ChargeStatus.POSTED, net_amount_cents=450000
    )
    contract = read_contract(api, world["contract_id"])
    assert_group_contract(
        contract,
        status=ContractStatus.SIGNED,
        ancillary_posted_cents=450000,
        receivable_total_cents=450000,
    )
    assert_receivable_identity(contract)
