"""Difficulty queue: error-category precedence pairs and inclusive/exclusive
boundary metrics."""
from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    add_days,
    assert_charge,
    create_disclosure_payload,
    create_employer,
    create_complainant,
    create_systemic_case,
    file_charge,
    issue_rts_as_charging_party,
    link_charge,
    make_charging_party_headers,
    read_charge,
    set_clock,
    setup_docketed_charge,
    setup_under_investigation,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_closed_charge_rts_request_state_beats_temporal(api):
    """PRD section 2.8: "On a terminal charge the more specific `ERR_CHARGE_ALREADY_CLOSED` (409) is returned instead, and it outranks the business-temporal checks below — an operation on a closed charge reports its closedness, not a deadline failure."
    PRD section 3.8: "a request against a terminal charge is rejected with `ERR_CHARGE_ALREADY_CLOSED`, which outranks the prematurity check."

    Design: Difficulty/priority_pair_validation_conflict/closed_charge_rts_request_state_beats_temporal
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-08-01")
    charge = base["charge"]
    party = make_charging_party_headers(charge["complainant_id"])

    # Withdrawn at 0 days elapsed: the request violates BOTH the terminal-state
    # gate and the 180-day rule; the state error wins.
    withdrawn = validate_ok(api_client.withdraw_charge(charge["id"], party))
    assert withdrawn["case_status"] == "WITHDRAWN"

    response = api_client.issue_right_to_sue(charge["id"], party)
    validate_error(response, ApiErrorId.ERR_CHARGE_ALREADY_CLOSED)

    notices, _meta = validate_paginated(
        api_client.list_right_to_sue_notices(charge["id"], _DIRECTOR)
    )
    assert notices == []


def test_missing_charge_disclosure_existence_beats_safety(api):
    """PRD section 2.6: "Existence therefore precedes ownership checks, state checks, and confidentiality checks; a read against a non-existent charge returns `ERR_CHARGE_NOT_FOUND` even if the caller could never have been entitled to see it."
    PRD section 2.9: "On a `SEALED` charge, only the legal basis `COURT_ORDER` is permitted; an explicit disclosure attempted with any other basis is rejected with `ERR_DISCLOSURE_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/missing_charge_disclosure_existence_beats_safety
    """
    base = setup_docketed_charge(basis_codes=["SEX"], incident_date="2026-08-01")
    charge = base["charge"]
    systemic = create_systemic_case(title="Seal probe", basis_focus=["SEX"],
                                    commissioner_user_id="com-002")
    expanded = link_charge(systemic, charge, commissioner_user_id="com-002")
    assert expanded["status"] == "EXPANDING"
    assert read_charge(charge["id"])["disclosure_hold"] == "SEALED"

    # The identical payload, two targets: a non-existent id reports the 404
    # existence failure before the sealed-disclosure rule is ever evaluated.
    missing = api_client.create_disclosure(
        UNKNOWN_UUID,
        create_disclosure_payload(legal_basis="FEPA_WORK_SHARE",
                                  target_description="state agency"),
        _DIRECTOR,
    )
    validate_error(missing, ApiErrorId.ERR_CHARGE_NOT_FOUND)

    sealed = api_client.create_disclosure(
        charge["id"],
        create_disclosure_payload(legal_basis="FEPA_WORK_SHARE",
                                  target_description="state agency"),
        _DIRECTOR,
    )
    validate_error(sealed, ApiErrorId.ERR_DISCLOSURE_FORBIDDEN)

    # The safety rule is basis-conditional, not a blanket ban.
    court_order = api_client.create_disclosure(
        charge["id"],
        create_disclosure_payload(legal_basis="COURT_ORDER",
                                  target_description="federal court subpoena"),
        _DIRECTOR,
    )
    validate_created(court_order)


def test_headcount_14_vs_15_jurisdiction(api):
    """PRD section 3.2: "The size screen uses only the `employee_count_at_incident` snapshot — never the employer's current headcount."
    PRD section 3.2: "Every other basis survives when the snapshot headcount is at least 15."
    PRD section 3.2: "The resulting `jurisdiction_outcome` is `DISMISSED_NO_JURISDICTION` when `covered_bases` is empty, `DISMISSED_UNTIMELY` when coverage exists but the charge is late, and `TIMELY_CONFIRMED` otherwise."

    Design: Difficulty/boundary_precision_check/headcount_14_vs_15_jurisdiction
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Boundary Co")
    cp_12 = create_complainant(full_name="Pat Twelve", email="p12@x.com")
    cp_13 = create_complainant(full_name="Pat Thirteen", email="p13@x.com")

    # 14 < 15: the snapshot empties covered_bases -> no jurisdiction.
    charge_14 = file_charge(employer, cp_12, basis_codes=["RACE"],
                            incident_date="2026-06-01", harm_description="fired",
                            employee_count_at_incident=14)
    assert_charge(charge_14)
    assert charge_14["case_status"] == "DISMISSED_NO_JURISDICTION"
    assert charge_14["jurisdiction_outcome"] == "DISMISSED_NO_JURISDICTION"
    assert charge_14["covered_bases"] == []
    assert charge_14["investigation_owner"] == "NONE"

    # The >= 15 comparison is inclusive: exactly 15 keeps jurisdiction.
    charge_15 = file_charge(employer, cp_13, basis_codes=["RACE"],
                            incident_date="2026-06-01", harm_description="fired",
                            employee_count_at_incident=15)
    assert_charge(charge_15)
    assert charge_15["case_status"] == "DOCKETED"
    assert charge_15["jurisdiction_outcome"] == "TIMELY_CONFIRMED"
    assert charge_15["covered_bases"] == ["RACE"]
    assert charge_15["investigation_owner"] == "EEOC"


def test_rts_elapsed_179_vs_180(api):
    """PRD section 3.8: "The charging-party path requires `days_elapsed_since_filing` of at least 180 — a request earlier than that is rejected with `ERR_RTS_PREMATURE` — and produces a notice whose `issuance_basis` is `ELAPSED_180_DAYS`."
    PRD section 3.8: "The notice records its `charge_id`, stamps `issued_date` from the logical clock, and computes `court_filing_deadline` as exactly 90 days after issuance — the charging party's window to file in court."
    PRD section 3.8: "Issuance moves the charge to the terminal `RTS_ISSUED` and closes out enforcement activity: the investigation case, if one exists, moves to `CLOSED` and its `PENDING`/`OVERDUE` evidence requests are `WAIVED`."

    Design: Difficulty/boundary_precision_check/rts_elapsed_179_vs_180
    """
    base = setup_under_investigation(basis_codes=["SEX"],
                                     incident_date="2026-06-01")
    charge = base["charge"]
    party = make_charging_party_headers(charge["complainant_id"])

    # 2027-02-27 is 179 days after the 2026-09-01 receipt: premature.
    set_clock("2027-02-27T00:00:00Z")
    premature = api_client.issue_right_to_sue(charge["id"], party)
    validate_error(premature, ApiErrorId.ERR_RTS_PREMATURE)

    # The gate is inclusive: exactly 180 days issues the notice.
    set_clock("2027-02-28T00:00:00Z")
    notice = issue_rts_as_charging_party(charge)
    assert notice["issuance_basis"] == "ELAPSED_180_DAYS"
    assert notice["issued_date"][:10] == "2027-02-28"
    assert notice["court_filing_deadline"][:10] == add_days("2027-02-28", 90) == "2027-05-29"

    assert read_charge(charge["id"])["case_status"] == "RTS_ISSUED"
