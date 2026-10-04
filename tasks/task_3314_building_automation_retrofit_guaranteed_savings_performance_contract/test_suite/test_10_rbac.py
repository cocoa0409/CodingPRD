"""Role-based access control denials."""
from test_helpers import (
    ApiErrorId,
    add_approved_baseline,
    create_and_submit_report,
    create_contract_payload,
    eng_headers,
    lender_headers,
    make_actor_ids,
    own_headers,
    performance_contract,
    reset_clock,
    validate_error,
    validate_success,
)


def test_esco_engineer_cannot_approve_baseline(api):
    """PRD §3.1: "An `OwnerRep` then approves or rejects the submitted
    baseline."
    PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to call the target endpoint, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/esco_engineer_cannot_approve_baseline
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract = validate_success(
        api.create_contract(create_contract_payload(), eng_headers(eng_id)), 201
    )
    cid = contract["id"]
    from test_helpers import create_baseline_payload
    baseline = validate_success(
        api.create_baseline(cid, create_baseline_payload(), eng_headers(eng_id)),
        201,
    )
    validate_success(api.submit_baseline(cid, baseline["id"], eng_headers(eng_id)))
    response = api.approve_baseline(cid, baseline["id"], eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    baseline = validate_success(
        api.get_baseline(cid, baseline["id"], eng_headers(eng_id))
    )
    assert baseline["status"] == "SUBMITTED"


def test_owner_rep_cannot_create_contract(api):
    """PRD §3.1: "An `ESCOEngineer` opens a performance contract by providing
    the `facility_name`, the guarantee length in `contract_term_years`"
    PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to call the target endpoint, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/owner_rep_cannot_create_contract
    """
    reset_clock()
    _eng_id, owner_id = make_actor_ids()
    response = api.create_contract(
        create_contract_payload(facility_name="Owner Attempt"),
        own_headers(owner_id),
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)


def test_lender_officer_cannot_attest_report(api):
    """PRD §3.5: "An `OwnerRep` attests a submitted report
    (`ERR_REPORT_NOT_SUBMITTED` otherwise), moving it to `ATTESTED`"
    PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to call the target endpoint, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/lender_officer_cannot_attest_report
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    report = create_and_submit_report(cid, eng_id)
    response = api.attest_report(cid, report["id"], lender_headers())
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["status"] == "SUBMITTED"
