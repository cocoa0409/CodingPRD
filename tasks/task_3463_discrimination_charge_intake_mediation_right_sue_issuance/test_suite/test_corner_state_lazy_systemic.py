"""Corner queue: lazy clock-driven transitions and the systemic-case
compound lifecycle."""
from test_helpers import (
    TEST_USERS,
    create_employer,
    create_complainant,
    create_systemic_case,
    file_charge,
    issue_rts_as_charging_party,
    link_charge,
    make_charging_party_headers,
    read_charge,
    schedule_session,
    set_clock,
    setup_in_mediation,
    setup_under_investigation,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]
_MEDIATOR = TEST_USERS["mediator_headers"]


def test_rts_notice_expires_after_deadline(api):
    """PRD section 2.4: "A `RightToSueNotice` flips from `ISSUED` to `EXPIRED` on read once the logical clock is strictly after its `court_filing_deadline` — on the exact deadline date the notice is still `ISSUED`."

    Design: Corner/state_machines/rts_notice_expires_after_deadline
    """
    base = setup_under_investigation(basis_codes=["SEX"],
                                     incident_date="2026-06-01")
    charge = base["charge"]

    # Issued 2027-02-28 (exactly 180 days after receipt): deadline +90 days.
    set_clock("2027-02-28T00:00:00Z")
    notice = issue_rts_as_charging_party(charge)
    assert notice["court_filing_deadline"][:10] == "2027-05-29"

    # Inclusive at the deadline date: still ISSUED on 2027-05-29.
    set_clock("2027-05-29T00:00:00Z")
    at_deadline, _meta = validate_paginated(
        api_client.list_right_to_sue_notices(charge["id"], _DIRECTOR)
    )
    assert at_deadline[0]["status"] == "ISSUED"

    # Strictly past the deadline: EXPIRED on read, with no write in between.
    set_clock("2027-05-30T00:00:00Z")
    past_deadline, _meta2 = validate_paginated(
        api_client.list_right_to_sue_notices(charge["id"], _DIRECTOR)
    )
    assert past_deadline[0]["status"] == "EXPIRED"


def test_session_held_lazy_transition(api):
    """PRD section 2.4: "A `MediationSession` flips from `SCHEDULED` to `HELD` on read once the logical clock passes its `scheduled_end`."

    Design: Corner/state_machines/session_held_lazy_transition
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    mediation = base["mediation_case"]

    set_clock("2027-01-05T00:00:00Z")
    session = schedule_session(mediation, "med-010",
                               scheduled_start="2027-01-10T10:00:00Z",
                               scheduled_end="2027-01-10T11:00:00Z")
    assert session["status"] == "SCHEDULED"

    # One second past scheduled_end: the read flips it, no write occurred.
    set_clock("2027-01-10T11:00:01Z")
    rows, _meta = validate_paginated(
        api_client.list_mediation_sessions(mediation["id"], _MEDIATOR)
    )
    assert rows[0]["id"] == session["id"]
    assert rows[0]["status"] == "HELD"


def test_systemic_lifecycle_auto_transitions(api):
    """PRD section 3.9: "The first link moves the case `OPENED` → `EXPANDING`."
    PRD section 3.9: "The case becomes `CONSOLIDATED` once at least 3 linked charges are non-terminal and at least 2 of those non-terminal charges share a basis with `basis_focus` — that is, the intersection of the charge's `basis_codes` with the case's `basis_focus` is non-empty."
    PRD section 3.9: "The case becomes `RESOLVED` automatically once at least one charge is linked and no linked charge remains non-terminal."
    PRD section 3.9: "Resolution lifts the seal: every linked charge's `disclosure_hold` returns from `SEALED` to `NONE`."
    PRD section 3.9: "The case's `linked_charge_count` counts every linked charge regardless of those charges' statuses."

    Design: Corner/state_machines/systemic_lifecycle_auto_transitions
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Sys Co")
    cp_1 = create_complainant(full_name="Casey 21", email="c21@x.com")
    cp_2 = create_complainant(full_name="Casey 22", email="c22@x.com")
    cp_3 = create_complainant(full_name="Casey 23", email="c23@x.com")
    charge_1 = file_charge(employer, cp_1, basis_codes=["RACE"],
                           incident_date="2026-06-01", harm_description="c1",
                           employee_count_at_incident=40)
    charge_2 = file_charge(employer, cp_2, basis_codes=["RACE"],
                           incident_date="2026-06-02", harm_description="c2",
                           employee_count_at_incident=40)
    charge_3 = file_charge(employer, cp_3, basis_codes=["AGE"],
                           incident_date="2026-06-03", harm_description="c3",
                           employee_count_at_incident=40)

    systemic = create_systemic_case(title="Pattern probe", basis_focus=["RACE"],
                                    commissioner_user_id="com-003")
    assert systemic["status"] == "OPENED"

    # Two non-terminal links sharing RACE but only 2 linked: still EXPANDING.
    assert link_charge(systemic, charge_1, commissioner_user_id="com-003")["status"] == "EXPANDING"
    assert link_charge(systemic, charge_2, commissioner_user_id="com-003")["status"] == "EXPANDING"

    # Third link: 3 non-terminal linked, 2 sharing RACE -> CONSOLIDATED.
    consolidated = link_charge(systemic, charge_3, commissioner_user_id="com-003")
    assert consolidated["status"] == "CONSOLIDATED"
    assert consolidated["linked_charge_count"] == 3

    # Drive every linked charge terminal; the last withdrawal resolves the
    # case in the same transaction, lifting its own seal.
    for charge in (charge_1, charge_2):
        withdrawn = validate_ok(
            api_client.withdraw_charge(
                charge["id"], make_charging_party_headers(charge["complainant_id"])
            )
        )
        assert withdrawn["case_status"] == "WITHDRAWN"
    last = validate_ok(
        api_client.withdraw_charge(
            charge_3["id"], make_charging_party_headers(charge_3["complainant_id"])
        )
    )
    assert last["case_status"] == "WITHDRAWN"
    assert last["disclosure_hold"] == "NONE"  # auto-resolve lifted the seal

    # The lift is visible on every linked charge; terminal charges stay counted.
    assert read_charge(charge_1["id"])["disclosure_hold"] == "NONE"
    assert read_charge(charge_2["id"])["disclosure_hold"] == "NONE"
