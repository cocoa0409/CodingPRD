"""Queue B / calculations: month clamping, suit window day 45, market day 75."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, make_applicant, make_reference_product, make_application,
    add_be_study, submit_application, list_cycles, setup_submitted,
    make_listed_patent, add_certification, send_notice,
    approve_application, list_awards, make_innovator_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_goal_date_month_end_clamping():
    """PRD section 2.4: "adding calendar months preserves the day-of-month,
    and when that day does not exist in the target month the result clamps to
    the month's last day — adding ten calendar months to 2027-01-31 yields
    2027-11-30."

    Design: Corner/calculations/goal_date_month_end_clamping
    """
    applicant = make_applicant(legal_name="Clamp Generics")
    rld = make_reference_product(brand_name="Clampex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    set_clock("2027-01-31T00:00:00Z")
    submit_application(app["id"], applicant["id"])

    cycle = list_cycles(app["id"])[0]
    assert cycle["opened_date"] == "2027-01-31"
    assert cycle["goal_date"] == "2027-11-30", (
        f"November has no 31st, so the goal clamps: {cycle['goal_date']}")


def test_suit_filed_on_day_45_creates_stay_but_day_46_window_closed():
    """PRD section 3.4: "an `event_date` that is on or after the `notice_date`,
    on or before the `suit_deadline` — the forty-fifth day is inclusive — and
    not later than the current logical date" and "`stay_until` is set to the
    date 30 calendar months after the notice date under the month-clamping
    convention"; "by the time the clock has moved past the deadline the notice
    has already left `NOTICE_SENT`, so the attempt fails as
    `ERR_INVALID_STATE`."

    Design: Corner/calculations/suit_filed_on_day_45_creates_stay_but_day_46_window_closed
    """
    ac = make_applicant(legal_name="Suit Window Co")
    owner = "innovator-ops-65"
    rld1 = make_reference_product(brand_name="SuitexOne", patent_owner_user_id=owner)
    rld2 = make_reference_product(brand_name="SuitexTwo", patent_owner_user_id=owner)
    pat1 = make_listed_patent(rld1, patent_number="US8888001")
    pat2 = make_listed_patent(rld2, patent_number="US8888002")

    certs = {}
    for rld, pat, analyte in ((rld1, pat1, "suitexone"), (rld2, pat2, "suitextwo")):
        app = make_application(rld["id"], ac["id"])
        add_be_study(app["id"], ac["id"], analyte=analyte)
        certs[rld["id"]] = add_certification(app["id"], ac["id"], pat["id"])
        submit_application(app["id"], ac["id"])

    set_clock("2026-09-10T00:00:00Z")
    n1 = send_notice(certs[rld1["id"]]["id"], ac["id"])
    n2 = send_notice(certs[rld2["id"]]["id"], ac["id"])
    assert n1["suit_deadline"] == "2026-10-25"

    set_clock("2026-10-25T00:00:00Z")
    suit = validate_success(api_client.create_litigation_event(n1["id"], {
        "event_type": "SUIT_FILED", "event_date": "2026-10-25"},
        make_innovator_headers(owner)), 200)
    assert suit["status"] == "SUIT_FILED"
    assert suit["stay_until"] == "2029-03-10", "notice 2026-09-10 + 30 months"

    set_clock("2026-10-26T00:00:00Z")
    late = api_client.create_litigation_event(n2["id"], {
        "event_type": "SUIT_FILED", "event_date": "2026-10-26"},
        make_innovator_headers(owner))
    validate_error(late, ApiErrorId.ERR_INVALID_STATE)
    assert late.status_code == 409, (
        "the clock passing the deadline already moved the notice to NO_SUIT_FILED")


def test_failure_to_market_forfeits_award_at_day_75_boundary():
    """PRD section 3.8: "the clock passing `marketing_deadline` with no first
    marketing recorded (`MARKETING_NOT_COMMENCED_75D`) — marketing recorded
    exactly on the deadline day is timely" and "`marketing_deadline` is
    computed as the calendar date 75 days after the approval date."

    Design: Corner/calculations/failure_to_market_forfeits_award_at_day_75_boundary
    """
    ctx = setup_submitted(with_facility=True, patent_expiry="2030-01-01",
                          cert_type="PARAGRAPH_IV_CHALLENGE")
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    set_clock("2026-09-05T00:00:00Z")
    send_notice(ctx["cert"]["id"], ac_id)

    set_clock("2026-12-01T00:00:00Z")
    approve_application(app_id)
    awards = list_awards(application_id=app_id)
    assert awards[0]["status"] == "AWARDED"
    assert awards[0]["marketing_deadline"] == "2027-02-14", "approval 2026-12-01 + 75 days"
    award_id = awards[0]["id"]

    set_clock("2027-02-14T00:00:00Z")
    award = validate_success(api_client.get_exclusivity_award(award_id, REVIEWER), 200)
    assert award["status"] == "AWARDED", "the deadline day itself is still timely"

    set_clock("2027-02-15T00:00:00Z")
    award = validate_success(api_client.get_exclusivity_award(award_id, REVIEWER), 200)
    assert award["status"] == "FORFEITED"
    assert award["forfeiture_reason"] == "MARKETING_NOT_COMMENCED_75D"
