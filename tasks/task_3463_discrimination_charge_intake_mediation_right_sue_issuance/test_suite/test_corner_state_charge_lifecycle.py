"""Corner queue: charge and determination lifecycle transitions (withdraw,
amend, review cycle, approval cascades, terminal lockdown)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_days,
    amend_charge_payload,
    cause_determination_payload,
    draft_determination,
    issue_rts_as_director,
    make_charging_party_headers,
    make_investigator_headers,
    read_charge,
    review_determination,
    setup_conciliation,
    setup_docketed_charge,
    setup_gathering,
    setup_pending_review,
    submit_determination,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_withdraw_blocked_during_determination_review(api):
    """PRD section 3.3: "The caller's `X-User-ID` must equal the charge's `complainant_id`, and withdrawal is allowed from exactly the four amend-eligible states, with the cleanup shaped by the state left behind."
    PRD section 2.8: "**State preconditions** — the target resource is in a state that forbids the transition: `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/withdraw_blocked_during_determination_review
    """
    base = setup_pending_review(outcome="NO_CAUSE",
                                investigator_user_id="inv-022")
    charge = base["charge"]
    assert read_charge(charge["id"])["case_status"] == "DETERMINATION_REVIEW"

    # DETERMINATION_REVIEW is non-terminal but unlisted: withdrawal is frozen
    # while the determination is under review.
    blocked = api_client.withdraw_charge(
        charge["id"], make_charging_party_headers(charge["complainant_id"])
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
    assert read_charge(charge["id"])["case_status"] == "DETERMINATION_REVIEW"


def test_amend_blocked_during_conciliation(api):
    """PRD section 3.3: "Amendment is blocked in `DETERMINATION_REVIEW` and `CONCILIATION` (rejected with `ERR_INVALID_STATE`) and on terminal charges (rejected with `ERR_CHARGE_ALREADY_CLOSED`)."
    PRD section 2.8: "Every request passes through a fixed validation pipeline, and the first failing check wins — its error is returned and later checks are not evaluated."

    Design: Corner/state_machines/amend_blocked_during_conciliation
    """
    base = setup_conciliation(investigator_user_id="inv-023",
                              director_user_id="dir-006")
    charge = base["charge"]
    assert charge["case_status"] == "CONCILIATION"

    # The state gate (pipeline step 6) precedes the OCC check (step 10), so a
    # correct expected_charge_version does not rescue the call.
    blocked = api_client.amend_charge(
        charge["id"],
        amend_charge_payload(expected_charge_version=charge["version"],
                             harm_description="revised allegations"),
        make_charging_party_headers(charge["complainant_id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
    assert read_charge(charge["id"])["case_status"] == "CONCILIATION"


def test_amend_incident_flips_charge_to_untimely(api):
    """PRD section 3.3: "Amending `incident_date` re-runs the full timeliness screening of §3.2 against the recomputed `filing_deadline_date`. When the re-screening yields `DISMISSED_UNTIMELY`, the charge flips to that terminal state, its `investigation_owner` becomes `NONE`, and the dismissal cascade resolves everything in flight: any `OFFERED` or `ACTIVE` mediation case for the charge is moved to `DECLINED` (with its still-`SCHEDULED` sessions moved to `CANCELLED` when one was active), the investigation case — if one exists — is moved to `CLOSED`, and its `PENDING` or `OVERDUE` evidence requests are moved to `WAIVED`."
    PRD section 3.3: "A successful amendment increments the charge's `version` by 1."

    Design: Corner/state_machines/amend_incident_flips_charge_to_untimely
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]

    # Moving the incident to 2025-01-01 recomputes the FL (180-day) deadline to
    # 2025-06-30, before the 2026-09-01 receipt: the charge flips terminal.
    amended = validate_ok(
        api_client.amend_charge(
            charge["id"],
            amend_charge_payload(expected_charge_version=charge["version"],
                                 incident_date="2025-01-01"),
            make_charging_party_headers(charge["complainant_id"]),
        )
    )
    assert amended["case_status"] == "DISMISSED_UNTIMELY"
    assert amended["jurisdiction_outcome"] == "DISMISSED_UNTIMELY"
    assert amended["filing_deadline_date"][:10] == add_days("2025-01-01", 180) == "2025-06-30"
    assert amended["investigation_owner"] == "NONE"
    assert amended["version"] == charge["version"] + 1


def test_determination_return_resubmit_cycle(api):
    """PRD section 3.6: "A `RETURN` decision requires a `return_reason` (which must conversely be null on an approval); it stamps `reviewed_by_user_id`, moves the determination to `RETURNED`, and sends the charge back `DETERMINATION_REVIEW` → `UNDER_INVESTIGATION` for further work."
    PRD section 3.6: "A determination sent back by review may be submitted again: the same submission moves `RETURNED` → `PENDING_REVIEW`, so the cycle can repeat."

    Design: Corner/state_machines/determination_return_resubmit_cycle
    """
    base = setup_pending_review(outcome="NO_CAUSE",
                                basis_codes=["DISABILITY"],
                                investigator_user_id="inv-024")
    charge = base["charge"]
    determination = base["determination"]
    case_id = base["investigation_case_id"]

    returned = review_determination(
        determination["id"], "RETURN", director_user_id="dir-007",
        return_reason="interview the supervisor first",
    )
    assert returned["status"] == "RETURNED"
    assert returned["reviewed_by_user_id"] == "dir-007"
    assert read_charge(charge["id"])["case_status"] == "UNDER_INVESTIGATION"

    resubmitted = submit_determination(determination["id"], "inv-024")
    assert resubmitted["status"] == "PENDING_REVIEW"
    assert read_charge(charge["id"])["case_status"] == "DETERMINATION_REVIEW"

    # Resubmission reuses the draft: still exactly one determination row.
    rows, _meta = validate_paginated(
        api_client.list_determinations(case_id, _DIRECTOR)
    )
    assert len(rows) == 1 and rows[0]["id"] == determination["id"]


def test_second_draft_determination_rejected(api):
    """PRD section 3.6: "at most one non-terminal determination may exist per investigation: drafting a second while one sits in `DRAFT`, `PENDING_REVIEW`, or `RETURNED` is rejected with `ERR_DETERMINATION_EXISTS`."

    Design: Corner/state_machines/second_draft_determination_rejected
    """
    base = setup_gathering(investigator_user_id="inv-025")
    case_id = base["investigation_case_id"]
    draft_determination(case_id, "inv-025", outcome="NO_CAUSE",
                        rationale="first draft")

    second = api_client.create_determination(
        case_id,
        cause_determination_payload(
            rationale="second draft", back_pay_cents=1_000, front_pay_cents=0,
            compensatory_damages_cents=0, punitive_damages_cents=0,
            harm_start_date="2026-06-01",
        ),
        make_investigator_headers("inv-025"),
    )
    validate_error(second, ApiErrorId.ERR_DETERMINATION_EXISTS)


def test_no_cause_approval_auto_issues_rts(api):
    """PRD section 3.6: "Approving a `NO_CAUSE` or `UNABLE_TO_DETERMINE` determination instead closes the charge into `CLOSED_NO_CAUSE` and auto-issues a `RightToSueNotice` with `issuance_basis` `AUTO_ON_DISMISSAL`, `requested_by_role` recorded as `system`, `issued_date` stamped from the clock, and `court_filing_deadline` set 90 days out."
    PRD section 3.6: "Either approval cascade also closes the investigation case and moves its `PENDING`/`OVERDUE` evidence requests to `WAIVED`."

    Design: Corner/state_machines/no_cause_approval_auto_issues_rts
    """
    base = setup_pending_review(outcome="NO_CAUSE",
                                investigator_user_id="inv-026")
    charge = base["charge"]
    case_id = base["investigation_case_id"]

    review_determination(base["determination"]["id"], "APPROVE",
                         director_user_id="dir-008")
    assert read_charge(charge["id"])["case_status"] == "CLOSED_NO_CAUSE"

    notices, _meta = validate_paginated(
        api_client.list_right_to_sue_notices(charge["id"], _DIRECTOR)
    )
    assert len(notices) == 1
    notice = notices[0]
    assert notice["issuance_basis"] == "AUTO_ON_DISMISSAL"
    assert notice["requested_by_role"] == "system"
    assert notice["issued_date"][:10] == "2026-09-01"
    assert notice["court_filing_deadline"][:10] == add_days("2026-09-01", 90) == "2026-11-30"

    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["status"] == "CLOSED"
    requests, _meta2 = validate_paginated(
        api_client.list_evidence_requests(case_id, _DIRECTOR)
    )
    assert requests[0]["status"] == "WAIVED"


def test_amend_on_terminal_charge_rejected(api):
    """PRD section 3.3: "Amendment is blocked in `DETERMINATION_REVIEW` and `CONCILIATION` (rejected with `ERR_INVALID_STATE`) and on terminal charges (rejected with `ERR_CHARGE_ALREADY_CLOSED`)."
    PRD section 3.8: "The Director may issue at discretion from any non-terminal, non-conciliating status, producing `issuance_basis` `DIRECTOR_DISCRETION`."

    Design: Corner/state_machines/amend_on_terminal_charge_rejected
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]

    # The Director path is unconditional: issuance at 0 days elapsed.
    notice = issue_rts_as_director(charge)
    assert notice["issuance_basis"] == "DIRECTOR_DISCRETION"
    assert read_charge(charge["id"])["case_status"] == "RTS_ISSUED"

    blocked = api_client.amend_charge(
        charge["id"],
        amend_charge_payload(expected_charge_version=charge["version"],
                             harm_description="too late"),
        make_charging_party_headers(charge["complainant_id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_CHARGE_ALREADY_CLOSED)
