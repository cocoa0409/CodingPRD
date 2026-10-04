"""Corner coverage of the state machines: activation and revocation signer
gates, terminal loan states, the match protocol, sanction state guards and the
reconciliation run lifecycle."""
import pytest

from test_helpers import (
    ADMIN,
    QA_CREATOR,
    QA_SETTLER,
    add_finding,
    add_signer,
    api_client,
    create_active_member,
    create_member,
    create_signer_payload,
    create_transfer_payload,
    issue_review,
    list_sanctions,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    read_loan,
    register_loan,
    set_clock,
    settle_review,
    setup_two_member_pair,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_member_activation_requires_active_signer(api):
    """PRD §3.1: "Moving a member from `PENDING_ACTIVATION` to `ACTIVE` requires
    that the member have at least one `ACTIVE` signer; an activation attempt
    against a signerless member is refused with `ERR_NO_AUTHORIZED_SIGNER`."

    Design: Corner/state_machines/member_activation_requires_active_signer
    """
    a = create_member(org_id="1000000")

    resp = api.activate_member(a["id"], ADMIN)
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_NO_AUTHORIZED_SIGNER")

    add_signer(a["id"])
    activated = validate_success(api.activate_member(a["id"], ADMIN))
    assert activated["status"] == "ACTIVE", activated


def test_revoke_last_active_signer_of_active_member_rejected(api):
    """PRD §3.1: "Revocation carries one protective refusal: revoking the last
    `ACTIVE` signer of an `ACTIVE` member would strand an operational member
    with no capacity to act, so it is rejected with `ERR_NO_AUTHORIZED_SIGNER`.
    Members in `PENDING_ACTIVATION` or `SUSPENDED` may legitimately have zero
    active signers, and `TERMINATED` members always do (see §3.7)."

    Design: Corner/state_machines/revoke_last_active_signer_of_active_member_rejected
    """
    a = create_member(org_id="1000000")
    signer = add_signer(a["id"])
    validate_success(api.activate_member(a["id"], ADMIN))

    resp = api.revoke_signer(a["id"], signer["id"], ADMIN)
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_NO_AUTHORIZED_SIGNER")
    still = validate_success(api.get_signer(signer["id"], ADMIN))
    assert still["status"] == "ACTIVE", still

    # While the member is SUSPENDED the same revocation is legal.
    validate_success(api.suspend_member(a["id"], ADMIN))
    revoked = validate_success(api.revoke_signer(a["id"], signer["id"], ADMIN))
    assert revoked["status"] == "REVOKED", revoked


def test_loan_foreclose_from_terminal_assigned_out_rejected(api):
    """PRD §3.3: "When the flag is set, the loan does not pass through an
    in-registry foreclosure state at all: it transitions directly from `ACTIVE`
    to `INACTIVE_ASSIGNED_OUT`, its `assigned_out_at` is stamped with the
    current clock, and from that instant it leaves every future transfer and
    reconciliation inclusion set — the registry records the exit but no longer
    tracks the loan's rights."
    PRD §3.3: "A loan that is not `ACTIVE` cannot be foreclosed at all
    (`ERR_LOAN_NOT_ACTIVE`)."

    Design: Corner/state_machines/loan_foreclose_from_terminal_assigned_out_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    rows, _ = validate_paginated(api.list_signers(a["id"], ADMIN))
    signer_id = rows[0]["id"]
    loan = register_loan(a["id"], property_state="NY", loan_amount_cents=50000000)

    assigned = validate_success(
        api.foreclose_loan(
            loan["id"], {"signer_id": signer_id, "assignment_out": True},
            member_rep(a["id"]),
        )
    )
    assert assigned["status"] == "INACTIVE_ASSIGNED_OUT", assigned
    assert assigned["assigned_out_at"] == "2026-01-05T00:00:00Z", assigned

    resp = api.satisfy_loan(loan["id"], member_rep(a["id"]))
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_LOAN_NOT_ACTIVE")


def test_rescind_from_active_loan_rejected(api):
    """PRD §3.3: "a rescission attempted against a loan that is not
    `FORECLOSING` fails with `ERR_LOAN_NOT_FORECLOSING`, and one attempted by a
    non-holder fails with `ERR_NOT_RIGHTS_HOLDER`."

    Design: Corner/state_machines/rescind_from_active_loan_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    resp = api.rescind_foreclosure(loan["id"], member_rep(a["id"]))
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_LOAN_NOT_FORECLOSING")
    assert read_loan(loan["id"])["status"] == "ACTIVE"


def test_transfer_match_confirm_by_wrong_member_rejected(api):
    """PRD §3.4: "The from-side member — and only that member — answers the
    match. Confirming the match requires the acting member to be the transfer's
    `from_member_id` (anyone else draws `ERR_NOT_MATCH_PARTY`, HTTP 403) and the
    match to still be `PENDING` (`ERR_MATCH_NOT_PENDING`); confirmation moves
    the match to `MATCHED`."

    Design: Corner/state_machines/transfer_match_confirm_by_wrong_member_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loan = register_loan(a["id"], loan_amount_cents=50000000)
    tr = validate_success(
        api.create_transfer(
            create_transfer_payload(loan["id"], b["id"], loan["version"],
                                    idempotency_key="k-mc-1"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )

    # The to-side member is not the match party.
    resp = api.match_confirm(tr["id"], member_rep(b["id"]))
    assert resp.status_code == 403, resp.text
    validate_error(resp, "ERR_NOT_MATCH_PARTY")

    confirmed = validate_success(api.match_confirm(tr["id"], member_rep(a["id"])))
    assert confirmed["status"] == "MATCHED", confirmed

    # A second confirmation hits the state guard.
    resp2 = api.match_confirm(tr["id"], member_rep(a["id"]))
    assert resp2.status_code == 409, resp2.text
    validate_error(resp2, "ERR_MATCH_NOT_PENDING")


def test_sanction_appeal_then_pay_from_appealed_is_invalid(api):
    """PRD §2.9: "a sanction must be `ASSESSED` to appeal or pay
    (`ERR_SANCTION_NOT_APPEALABLE`) and `APPEALED` to adjudicate
    (`ERR_SANCTION_NOT_APPEALED`)"
    PRD §2.9: "All are HTTP 409."

    Design: Corner/state_machines/sanction_appeal_then_pay_from_appealed_is_invalid
    """
    set_clock("2026-01-05T00:00:00Z")
    d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
    loan = register_loan(d["id"], loan_amount_cents=40000000)
    review = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                         period_end="2026-03-31T00:00:00Z")
    add_finding(review["id"], loan["id"], field_name="PROPERTY_STATE",
                expected_value="TX", actual_value="TN", severity="MAJOR")
    issue_review(review["id"])
    settle_review(review["id"])
    sanction = list_sanctions(review_id=review["id"])[0]
    validate_success(api.appeal_sanction(sanction["id"], member_rep(d["id"])))

    # Pay requires ASSESSED; the sanction is APPEALED.
    resp_pay = api.pay_sanction(sanction["id"], member_rep(d["id"]))
    assert resp_pay.status_code == 409, resp_pay.text
    validate_error(resp_pay, "ERR_SANCTION_NOT_APPEALABLE")

    # A second appeal also requires ASSESSED.
    resp_appeal = api.appeal_sanction(sanction["id"], member_rep(d["id"]))
    assert resp_appeal.status_code == 409, resp_appeal.text
    validate_error(resp_appeal, "ERR_SANCTION_NOT_APPEALABLE")

    after = validate_success(api.get_sanction(sanction["id"], ADMIN))
    assert after["status"] == "APPEALED", after


def test_sor_run_supersede_cancels_prior_and_completes_when_last_exception_resolved(api):
    """PRD §3.8: "Submission is superseding: any prior `OPEN` run for the same
    member immediately flips to `CANCELLED`, and that older run's still-open
    exceptions are marked `RESOLVED` with their `detail` set to note they were
    superseded, so no orphan open exceptions survive the change of batch."
    PRD §3.8: "If the diff produced no exceptions at all, the run skips its open
    life entirely and completes immediately to `COMPLETED`."

    Design: Corner/state_machines/sor_run_supersede_cancels_prior_and_completes_when_last_exception_resolved
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    loan = register_loan(a["id"], loan_amount_cents=50000000)
    assert loan["min"] == "100000000000000016", loan

    # First run with empty records: one REGISTRY_ONLY exception, run OPEN.
    run1 = validate_success(
        api.create_sor_run({"records": []}, member_rep(a["id"])),
        expected_status=201,
    )
    assert run1["status"] == "OPEN", run1

    # Second run whose single record matches: supersedes run1, completes itself.
    run2 = validate_success(
        api.create_sor_run(
            {"records": [{"min": loan["min"], "servicer_org_id": "1000000",
                          "investor_org_id": "1000000"}]},
            member_rep(a["id"]),
        ),
        expected_status=201,
    )
    assert run2["status"] == "COMPLETED", run2
    assert run2["matched_count"] == 1, run2
    assert run2["match_rate"] == pytest.approx(1.0), run2

    run1_after = validate_success(api.get_sor_run(run1["id"], ADMIN))
    assert run1_after["status"] == "CANCELLED", run1_after

    exceptions, _ = validate_paginated(
        api.list_sor_exceptions(ADMIN, params={"run_id": run1["id"]})
    )
    assert len(exceptions) == 1, exceptions
    assert exceptions[0]["status"] == "RESOLVED", exceptions
    assert "superseded" in exceptions[0]["detail"], exceptions
