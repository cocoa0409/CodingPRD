"""Research access intervals and the authentication/authorization pipeline:
closed visit-interval conflicts, the visit-vs-loan cross-check, the 401/403
gates and their ordering against existence and state checks (PRD §3.8, §2.1,
§2.5, §2.8)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    NO_HEADERS,
    UNREGISTERED_USER_ID,
    ApiErrorId,
    cancel_pass,
    create_agreed_loan,
    create_object,
    create_research_request,
    create_timed_museum,
    decide_research_request,
    get_object,
    make_borrower_rep_headers,
    make_committee_chair_headers,
    make_docent_headers,
    make_public_headers,
    make_registrar_headers,
    make_security_screener_headers,
    make_visitor_services_headers,
    reserve_pass,
    reset_clock,
    validate_error,
    validate_success,
)


def test_research_closed_interval_conflict(api):
    """PRD §3.8: "The visit interval must not intersect any other already-`APPROVED` research visit for the same object: because visit intervals are closed, two visits conflict whenever each starts on or before the other's last day — a second visit beginning exactly on the day the first visit ends is a conflict, in deliberate contrast to the half-open loan windows — and a violation is rejected with `ERR_RESEARCH_VISIT_CONFLICT`."

    Design: Corner/errors/research_closed_interval_conflict
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0040", title="Research Object A", declared_value_cents=1000000
    )
    req_a = create_research_request(
        obj["id"], scholar_user_id="scholar-a", scholar_name="Scholar A",
        research_topic="Textile dyes",
        visit_start_date="2026-10-05", visit_end_date="2026-10-07",
    )
    decide_research_request(req_a["id"], "APPROVED")
    # B starts on A's last day: a shared boundary day is a conflict.
    req_b = create_research_request(
        obj["id"], scholar_user_id="scholar-b", scholar_name="Scholar B",
        research_topic="Weave patterns",
        visit_start_date="2026-10-07", visit_end_date="2026-10-09",
    )
    # C starts one full day after A ends: clean.
    req_c = create_research_request(
        obj["id"], scholar_user_id="scholar-c", scholar_name="Scholar C",
        research_topic="Dye chromatography",
        visit_start_date="2026-10-08", visit_end_date="2026-10-10",
    )
    resp_b = api.decide_research_access_request(
        req_b["id"], "APPROVED", headers=make_registrar_headers()
    )
    validate_error(resp_b, ApiErrorId.ERR_RESEARCH_VISIT_CONFLICT)
    after_b = validate_success(
        api.get_research_access_request(req_b["id"], headers=make_registrar_headers())
    )
    assert after_b["status"] == "REQUESTED", "a rejected approval leaves the request REQUESTED"
    decided_c = decide_research_request(req_c["id"], "APPROVED")
    assert decided_c["status"] == "APPROVED"


def test_research_visit_vs_loan_window_conflict(api):
    """PRD §3.8: "Finally, the visit interval must not intersect any `AGREED` or `ACTIVE` loan window for the object: a conflict exists when the visit starts before the loan's end date and the loan's start date falls on or before the visit's last day, and a violation is rejected with `ERR_OBJECT_RESERVED_FOR_LOAN`."

    Design: Corner/errors/research_visit_vs_loan_window_conflict
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0041", title="Research Object B", declared_value_cents=40000000
    )
    create_agreed_loan(
        obj["id"], borrower_institution="Research Blocking Museum",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=40000000, coverage_type="INSURANCE", courier_required=False,
    )
    # [2026-11-15, 2026-11-20] sits inside the AGREED window [2026-10-01, 2026-12-01).
    req_1 = create_research_request(
        obj["id"], scholar_user_id="scholar-d", scholar_name="Scholar D",
        research_topic="Mid-loan visit",
        visit_start_date="2026-11-15", visit_end_date="2026-11-20",
    )
    # 2026-12-01 == the loan's exclusive end date: the half-open window is clear.
    req_2 = create_research_request(
        obj["id"], scholar_user_id="scholar-e", scholar_name="Scholar E",
        research_topic="Post-loan visit",
        visit_start_date="2026-12-01", visit_end_date="2026-12-05",
    )
    resp_1 = api.decide_research_access_request(
        req_1["id"], "APPROVED", headers=make_registrar_headers()
    )
    validate_error(resp_1, ApiErrorId.ERR_OBJECT_RESERVED_FOR_LOAN)
    decided_2 = decide_research_request(req_2["id"], "APPROVED")
    assert decided_2["status"] == "APPROVED"
    assert get_object(obj["id"])["status"] == "IN_COLLECTION", (
        "the AGREED loan never activated, so the object never left"
    )


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    reset_clock()
    resp = api.create_museum(
        {
            "museum_code": "NOAUTH", "display_name": "No Auth Museum",
            "requires_timed_pass": False, "quarter_hour_pass_quota": 10,
            "daily_pass_quota": 100, "screening_rate_per_quarter_hour": 20,
        },
        headers=NO_HEADERS,
    )
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error.get("message"), "the error envelope must carry a human-readable message"


def test_validation_priority_role_beats_state(api):
    """PRD §2.8: "When several checks would fail, the earliest check in this order produces the error, and later checks are never evaluated:"
    PRD §2.8: "2. **Authorization and ownership** — the role appears in the endpoint's authorized list, and ownership rules hold (a member acting as themself, a docent acting as themself, a group organizer acting as the recorded creator, a curator submitting only their own review), else `ERR_UNAUTHORIZED_ROLE`." (ordered before item 5)
    PRD §2.8: "5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`."

    Design: Corner/validations/validation_priority_role_beats_state
    """
    reset_clock()
    museum = create_timed_museum(
        quarter_hour_pass_quota=5, daily_pass_quota=20, screening_rate_per_quarter_hour=4
    )
    pass_ = reserve_pass(
        museum["id"], creator_user_id="visitor-o", visitor_name="Owner Visitor",
        visit_date="2026-09-20", entry_quarter_hour=2,
    )
    cancel_pass(pass_)  # now CANCELLED — a state in which cancel has no transition
    # A SecurityScreener is not in the cancel endpoint's roles list at all, so
    # the role gate (item 2) beats the state gate (item 5).
    resp = api.cancel_timed_entry_pass(
        pass_["id"], headers=make_security_screener_headers()
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = validate_success(
        api.get_timed_entry_pass(pass_["id"], headers=make_visitor_services_headers())
    )
    assert after["status"] == "CANCELLED"


def test_rbac_role_denials(api):
    """PRD §2.1: "If the named role is not in the endpoint's authorized roles list, or an ownership rule is violated, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.8: "When several checks would fail, the earliest check in this order produces the error, and later checks are never evaluated:" — authorization (item 2) precedes path existence (item 3), so even a bogus resource id earns 403 here.

    Design: Corner/rbac/rbac_role_denials
    """
    reset_clock()
    # Public may not create museums (PlatformAdmin only).
    e1 = api.create_museum(
        {
            "museum_code": "DENY", "display_name": "Denied Museum",
            "requires_timed_pass": False, "quarter_hour_pass_quota": 10,
            "daily_pass_quota": 100, "screening_rate_per_quarter_hour": 20,
        },
        headers=make_public_headers("visitor-deny"),
    )
    validate_error(e1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    # A Docent may not refund tickets (VisitorServices only) — the role check
    # fires before the 404 the nonexistent ticket id would otherwise earn.
    e2 = api.refund_ticket(
        NON_EXISTENT_UUID, headers=make_docent_headers(UNREGISTERED_USER_ID)
    )
    validate_error(e2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    # A BorrowerRep may not decide condition reports (LoansOfficer only).
    e3 = api.decide_condition_report(
        NON_EXISTENT_UUID, "ACCEPTED", headers=make_borrower_rep_headers()
    )
    validate_error(e3, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    # A CommitteeChair may not submit reviews (Curator only).
    e4 = api.submit_collection_review(
        NON_EXISTENT_UUID, headers=make_committee_chair_headers("chair-deny")
    )
    validate_error(e4, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_ticket_get_not_found_returns_404(api):
    """PRD §2.5: "A missing path-referenced or body-referenced resource yields `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/ticket_get_not_found_returns_404
    """
    reset_clock()
    resp = api.get_ticket(NON_EXISTENT_UUID, headers=make_visitor_services_headers())
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error.get("message"), "the error envelope must carry a human-readable message"
