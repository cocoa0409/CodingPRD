"""Dispute workflow: filing, escalation, resolution, withdrawal."""
from test_helpers import (
    ApiErrorId,
    attested_report,
    create_and_submit_report,
    create_dispute_payload,
    create_report_payload,
    eng_headers,
    lender_headers,
    make_actor_ids,
    own_headers,
    performance_contract,
    reset_clock,
    validate_error,
    validate_success,
)


def test_savings_report_dispute_cycle_returns_to_attested(api):
    """PRD §3.7: "the dispute moves to `RESOLVED`, and the report returns
    from `DISPUTED` to `ATTESTED` with its `verified_savings_cents` set to the
    resolution figure and its `shortfall_cents` recomputed accordingly."
    PRD §3.7: "The filing creates a dispute notice in `OPEN` state with
    `filed_by_role` derived from the caller: `OWNER` for an owner rep, `ESCO`
    for an engineer"

    Design: Difficulty/non_linear_state_machine/savings_report_dispute_cycle_returns_to_attested
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    report = attested_report(cid, eng_id, owner_id)
    assert report["verified_savings_cents"] == 240000
    dispute = validate_success(
        api.file_dispute(cid, report["id"], create_dispute_payload(
            report_id=report["id"], claimed_savings_cents=260000),
                         eng_headers(eng_id)),
        201,
    )
    assert dispute["filed_by_role"] == "ESCO"
    assert dispute["status"] == "OPEN"
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["status"] == "DISPUTED"
    escalated = validate_success(
        api.escalate_dispute(cid, dispute["id"], own_headers(owner_id))
    )
    assert escalated["status"] == "ESCALATED"
    resolved = validate_success(
        api.resolve_dispute(cid, dispute["id"],
                            {"resolution_savings_cents": 255000},
                            lender_headers())
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_savings_cents"] == 255000
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["status"] == "ATTESTED"
    assert report["verified_savings_cents"] == 255000
    assert report["shortfall_cents"] == 0
    # RESOLVED is terminal: a second resolve is rejected.
    response = api.resolve_dispute(cid, dispute["id"],
                                   {"resolution_savings_cents": 1},
                                   lender_headers())
    validate_error(response, ApiErrorId.ERR_DISPUTE_NOT_OPEN.value, 409)


def test_dispute_cycle_recomputes_shortfall_from_resolution(api):
    """PRD §3.7: "the report returns from `DISPUTED` to `ATTESTED` with its
    `verified_savings_cents` set to the resolution figure and its
    `shortfall_cents` recomputed accordingly."
    PRD §3.5: "the report's `shortfall_cents` is then the larger of zero and
    the contract's `guaranteed_annual_savings_cents` minus the
    `verified_savings_cents`."

    Design: Difficulty/non_linear_state_machine/savings_report_dispute_cycle_returns_to_attested
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    report = attested_report(cid, eng_id, owner_id)
    dispute = validate_success(
        api.file_dispute(cid, report["id"], create_dispute_payload(
            report_id=report["id"], claimed_savings_cents=100000),
                         eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.resolve_dispute(cid, dispute["id"],
                            {"resolution_savings_cents": 200000},
                            lender_headers())
    )
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["verified_savings_cents"] == 200000
    assert report["shortfall_cents"] == 250000 - 200000


def test_dispute_withdrawn_by_non_filer_side_rejected(api):
    """PRD §3.7: "The filer — and only the filer's side — may withdraw an
    open dispute: an `OWNER`-filed dispute is withdrawn by an `OwnerRep`, an
    `ESCO`-filed dispute by an `ESCOEngineer`, and a withdrawal attempted by
    the wrong side fails with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §3.7: "the report then returns to the state it held before the
    dispute — `SUBMITTED` if the dispute was filed pre-attestation,
    `ATTESTED` if filed afterward."

    Design: Corner/state_machines/dispute_withdrawn_by_non_filer_side_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    report = create_and_submit_report(cid, eng_id)
    dispute = validate_success(
        api.file_dispute(cid, report["id"], create_dispute_payload(
            report_id=report["id"], claimed_savings_cents=200000),
                         own_headers(owner_id)),
        201,
    )
    assert dispute["filed_by_role"] == "OWNER"
    response = api.withdraw_dispute(cid, dispute["id"], eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    dispute = validate_success(
        api.get_dispute(cid, dispute["id"], eng_headers(eng_id))
    )
    assert dispute["status"] == "OPEN"
    withdrawn = validate_success(
        api.withdraw_dispute(cid, dispute["id"], own_headers(owner_id))
    )
    assert withdrawn["status"] == "WITHDRAWN"
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["status"] == "SUBMITTED"
