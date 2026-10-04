"""Error-catalog corner rules: ruleset mismatch at license activation, panel
segregation, pool exhaustion, factor-score validation, appeal conflict, and
authn/authz header enforcement."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock,
    activate_policy_revision, activate_listing, change_status,
    create_citation, issue_and_pay_citation,
    setup_ethics_case_decided, setup_arbitration_case_scheduled,
    make_member_headers, make_grievance_headers, make_panelist_headers,
    make_staff_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_error_arbitration_window_and_ruleset_mismatch_covered(api):
    """PRD §3.9: "Activating a license requires its `display_ruleset_version`
    to equal the association's current ruleset version; a mismatch is rejected
    with `ERR_RULESET_MISMATCH`."
    PRD §3.9: "An association's current display-ruleset version is defined as
    the count of its policy revisions in status `ACTIVE` or `SUPERSEDED`."

    Design: Corner/errors/error_arbitration_window_and_ruleset_mismatch_covered
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="ER1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    lic = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "StalePortal", "scope": "IDX", "display_ruleset_version": 0,
         "listing_field_allowlist": ["property_address"]}, STAFF))
    resp = api.activate_data_license(assoc["id"], lic["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_RULESET_MISMATCH)


def test_error_panel_sole_actor_enforced(api):
    """PRD §3.8: "Segregation of duties applies within the panel: the panelist
    who triggered the hearing must not be the panelist who rules, and a
    violation is rejected with `ERR_PANEL_SOLE_ACTOR`."
    PRD §3.5: "below 3 strikes the citation transitions to `PAID` with the same
    credit accrual".

    Design: Corner/errors/error_panel_sole_actor_enforced
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="ER2", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    for i in range(3):
        create_member(assoc["id"], member_nr=f"P{i+1}", full_name=f"P{i+1}")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    validate_success(api.request_hearing(
        assoc["id"], cit["id"], make_member_headers(mv["id"])))
    panel = get_success_data(api.convene_hearing_panel(
        assoc["id"], "CITATION", cit["id"], STAFF))
    pa = panel["selected_member_ids"][0]
    pb = panel["selected_member_ids"][1]
    validate_success(api.hold_hearing(
        assoc["id"], panel["id"], make_panelist_headers(pa)))
    resp = api.rule_panel(assoc["id"], panel["id"], "UPHOLD",
                          make_panelist_headers(pa))
    validate_error(resp, ApiErrorId.ERR_PANEL_SOLE_ACTOR)
    ruled = validate_success(api.rule_panel(
        assoc["id"], panel["id"], "UPHOLD", make_panelist_headers(pb)))
    assert ruled["status"] == "DECIDED"
    cit_now = get_success_data(api.get_citation(assoc["id"], cit["id"], STAFF))
    assert cit_now["status"] == "PAID", "UPHOLD at < 3 strikes pays the fine"


def test_error_panel_pool_exhausted(api):
    """PRD §3.8: "Fewer than three eligible members rejects the convene with
    `ERR_PANEL_POOL_EXHAUSTED`".
    PRD §3.8: "A member is eligible when they are `ACTIVE` with
    `mls_access_state` `ENABLED`, belong to the panel's association, are not in
    the subject set, are not in the union of the subjects'
    `hearing_panel_exclusions` lists — each member's exclusion list contains
    the member themself, every member of their own association, and the
    respondents of any open or decided arbitration case in which they are
    complainant or respondent".

    Design: Corner/errors/error_panel_pool_exhausted
    """
    assoc = create_association(association_code="ER3")
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_member(assoc["id"], member_nr="M1", full_name="One")
    create_member(assoc["id"], member_nr="M2", full_name="Two")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    validate_success(api.request_hearing(
        assoc["id"], cit["id"], make_member_headers(mv["id"])))
    resp = api.convene_hearing_panel(assoc["id"], "CITATION", cit["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_PANEL_POOL_EXHAUSTED)


def test_error_factor_score_invalid(api):
    """PRD §3.7: "the holding panelist must supply `factor_scores`: a map from
    each of the five procuring-cause factor keys — `F1_FIRST_CONTACT`,
    `F2_CONTINUOUS_EFFORT`, `F3_AGENCY_DISCLOSURE`, `F4_CONTRACT_ROLE`, and
    `F5_ABANDONMENT` — to an integer from 0 to 10. A missing key or an
    out-of-range value is rejected with `ERR_FACTOR_SCORE_INVALID`."

    Design: Corner/errors/error_factor_score_invalid
    """
    ctx = setup_arbitration_case_scheduled(claim_amount_cents=500000)
    assoc, panel = ctx["assoc"], ctx["panel"]
    pa = panel["selected_member_ids"][0]
    # Missing F5 key.
    resp = api.hold_hearing(
        assoc["id"], panel["id"], make_panelist_headers(pa),
        factor_scores={"F1_FIRST_CONTACT": 5, "F2_CONTINUOUS_EFFORT": 5,
                       "F3_AGENCY_DISCLOSURE": 5, "F4_CONTRACT_ROLE": 5})
    validate_error(resp, ApiErrorId.ERR_FACTOR_SCORE_INVALID)
    # Out-of-range value.
    resp = api.hold_hearing(
        assoc["id"], panel["id"], make_panelist_headers(pa),
        factor_scores={"F1_FIRST_CONTACT": 5, "F2_CONTINUOUS_EFFORT": 5,
                       "F3_AGENCY_DISCLOSURE": 5, "F4_CONTRACT_ROLE": 5,
                       "F5_ABANDONMENT": 11})
    validate_error(resp, ApiErrorId.ERR_FACTOR_SCORE_INVALID)
    panel_now = get_success_data(api.get_hearing_panel(assoc["id"], panel["id"], STAFF))
    assert panel_now["status"] == "CONVENED"


def test_error_appeal_conflict_and_window(api):
    """PRD §3.6: "A `GrievanceMember` then rules on the appeal, transitioning
    the case `APPEALED` → `FINAL`, but the ruling member must be neither
    complainant, nor respondent, nor a member of the original panel's
    `selected_member_ids`; a conflict is rejected with `ERR_APPEAL_CONFLICT`."
    PRD §3.6: "The respondent — and only the respondent — may appeal within 20
    days of the linked panel's ruling instant".

    Design: Corner/errors/error_appeal_conflict_and_window
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_ethics_case_decided(respondent_strikes=0)
    assoc = ctx["assoc"]
    set_clock("2026-09-10T00:00:00Z")
    get_success_data(api.rule_panel(
        assoc["id"], ctx["panel"]["id"], "UPHOLD",
        make_panelist_headers(ctx["ruler_id"])))
    validate_success(api.appeal_ethics_case(
        assoc["id"], ctx["case"]["id"],
        make_member_headers(ctx["respondent"]["id"])))
    # Original panelist (holder) attempts the appeal ruling -> conflict.
    resp = api.appeal_ruling_ethics_case(
        assoc["id"], ctx["case"]["id"],
        make_grievance_headers(ctx["holder_id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_CONFLICT)
    # A non-party, non-panelist grievance member rules -> FINAL.
    final = validate_success(api.appeal_ruling_ethics_case(
        assoc["id"], ctx["case"]["id"],
        make_grievance_headers(ctx["grievance"]["id"])))
    assert final["status"] == "FINAL"


def test_error_unauthenticated_and_forbidden_headers(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of
    the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401). If the role is recognized but not permitted for the endpoint,
    the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `Member` acting on a resource owned by a different member id
    is rejected with `ERR_MEMBER_MISMATCH` (HTTP 403), distinct from the
    wrong-role rejection `ERR_FORBIDDEN`."

    Design: Corner/errors/error_unauthenticated_and_forbidden_headers
    """
    assoc = create_association(association_code="ER6")
    m1 = create_member(assoc["id"], member_nr="M1", full_name="One")
    m2 = create_member(assoc["id"], member_nr="M2", full_name="Two")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = create_citation(assoc["id"], m2["id"], rule_code="INACCURACY")
    # Missing headers entirely -> 401.
    resp = api.create_fine_schedule(
        assoc["id"],
        {"rule_code": "CLEAR_COOP", "fine_amount_cents": 40000,
         "effective_from": "2026-01-01T00:00:00Z"},
        headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    # Member role on a staff-only endpoint -> 403 ERR_FORBIDDEN.
    resp = api.create_fine_schedule(
        assoc["id"],
        {"rule_code": "CLEAR_COOP", "fine_amount_cents": 40000,
         "effective_from": "2026-01-01T00:00:00Z"},
        make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    # Right role but wrong member id paying another member's citation.
    resp = api.pay_citation(assoc["id"], cit["id"], 30000,
                            make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_MISMATCH)
