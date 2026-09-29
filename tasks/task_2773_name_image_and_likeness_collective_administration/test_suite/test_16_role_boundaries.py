"""Role boundaries: exclusive operations, entity-backed ownership and duty separation.

PRD s2.1 fixes the six roles and the three-step auth ladder, PRD s2.8 places the role
check at priority 3 and the athlete ownership check at priority 4, and PRD s2.11 fixes
the segregation-of-duties comparison between two recorded X-User-ID strings.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_FORBIDDEN_RESOURCE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_deliverable_scoring,
    assert_error_envelope_shape,
    assert_release_money,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    compliance_decision_payload,
    compliance_submission_payload,
    deal_contract_payload,
    evidence_payload,
    payment_release_payload,
)
from test_helpers.fixtures import (
    add_evidence,
    build_active_contract,
    build_athlete,
    build_collective,
    build_deliverable,
    build_draft_contract,
    build_funded_collective,
    read_athlete,
    read_collective,
    read_contract,
    read_deliverable,
    record_taxpayer_doc,
    review_work,
    submit_work,
)
from test_helpers.test_users import (
    make_athlete_headers,
    make_director_headers,
    make_reviewer_headers,
    make_treasury_headers,
)


def test_the_reviewer_and_the_director_hold_disjoint_exclusive_operations(api):
    """Neither role can borrow the other's endpoint, and both refusals are priority 3.

    PRD s2.1: "`InstitutionReviewer` represents the institution's compliance office: it
    is the only role permitted to adjudicate a contract disclosure, and it may otherwise
    only read", while "`CollectiveDirector` runs fundraising and contracting — tiers,
    donors, commitments, contributions, athletes, individual and roster-wide contracts,
    deliverables and communication records". PRD s2.8 places "The presented role appears
    in the addressed endpoint's permitted roles — `ERR_UNAUTHORIZED`, on every endpoint"
    at priority 3, and PRD s3.8 confirms that "Adjudication belongs to the
    `InstitutionReviewer` alone".

    Design: Corner/rbac/institution_reviewer_cannot_create_a_deal_contract
    """
    collective = build_collective(
        api,
        "025700",
        name="Rbac Collective",
        institution_name="Rbac Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2024",
    )
    athlete = build_athlete(
        api, collective["id"], "ath-rbac", full_name="Rbac Athlete", sport="FOOTBALL"
    )
    contract = build_draft_contract(api, collective["id"], athlete["id"], 100000)

    submitted = read_data(
        api.submit_compliance_packet(
            contract["id"],
            compliance_submission_payload("OH-3345.56", "NCAA-2024-12.5"),
            make_director_headers(),
        )
    )
    assert submitted["disclosure_status"] == "DISCLOSURE_PENDING"

    # The contracting endpoint is closed to the adjudicating role.
    reviewer_create = api.create_deal_contract(
        deal_contract_payload(collective["id"], athlete["id"], 50000),
        make_reviewer_headers(),
    )
    validate_error(reviewer_create, ERR_UNAUTHORIZED, expected_status=403)
    assert_error_envelope_shape(reviewer_create)

    # And the adjudicating endpoint is closed to the contracting role.
    director_decision = api.decide_compliance(
        contract["id"], compliance_decision_payload("ACCEPT"), make_director_headers()
    )
    validate_error(director_decision, ERR_UNAUTHORIZED, expected_status=403)
    assert_error_envelope_shape(director_decision)

    accepted = read_data(
        api.decide_compliance(
            contract["id"], compliance_decision_payload("ACCEPT"), make_reviewer_headers()
        )
    )
    assert accepted["disclosure_status"] == "DISCLOSURE_ACCEPTED"
    assert_contract_dimensions(accepted, lifecycle_status="DRAFT")

    listed = api.list_deal_contracts(
        {"collective_id": collective["id"]}, make_director_headers()
    )
    rows = rows_of(listed)
    assert len(rows) == 1
    assert rows[0]["id"] == contract["id"]
    assert listed.json()["meta"]["total_count"] == 1

    # Every GET is shared with the reviewer, so only the writes are exclusive.
    reviewer_read = read_data(api.get_deal_contract(contract["id"], make_reviewer_headers()))
    assert reviewer_read["id"] == contract["id"]
    assert reviewer_read["disclosure_status"] == "DISCLOSURE_ACCEPTED"


def _two_athletes_each_with_one_deliverable(api):
    """Two ENROLLED athletes, one 50000-cent ACTIVE contract each, one APPEARANCE each.

    The collective is funded with a 500000-cent gift so that the 100000 cents of
    committed value keeps `funding_posture` at OPEN and only the ownership rule can
    refuse anything (PRD s2.10).
    """
    funded = build_funded_collective(
        api,
        "025800",
        500000,
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        email="ownership@example.com",
        name="Ownership Collective",
        institution_name="Ownership Institution",
    )
    collective_id = funded["collective_id"]
    owner = build_athlete(
        api, collective_id, "ath-own", full_name="Owner Athlete", sport="FOOTBALL"
    )
    other = build_athlete(
        api, collective_id, "ath-other", full_name="Other Athlete", sport="FOOTBALL"
    )

    own_contract = build_active_contract(api, collective_id, owner["id"], 50000)
    other_contract = build_active_contract(api, collective_id, other["id"], 50000)
    assert own_contract["disclosure_status"] == "DISCLOSURE_NOT_REQUIRED"
    assert other_contract["disclosure_status"] == "DISCLOSURE_NOT_REQUIRED"

    own_deliverable = build_deliverable(
        api, own_contract["id"], "APPEARANCE", 50000, "2026-09-01T00:00:00Z"
    )
    other_deliverable = build_deliverable(
        api, other_contract["id"], "APPEARANCE", 50000, "2026-09-01T00:00:00Z"
    )
    assert_collective_ledger(
        read_collective(api, collective_id),
        settled_net_funds_cents=487470,
        committed_unreleased_cents=100000,
        funding_posture="OPEN",
    )
    return {
        "collective_id": collective_id,
        "own_deliverable_id": own_deliverable["id"],
        "other_deliverable_id": other_deliverable["id"],
    }


def test_an_athlete_may_only_document_their_own_deliverable(api):
    """The same body succeeds on the caller's own deliverable and is 403 on a peer's.

    PRD s2.1: "When `X-User-Role` is `Athlete`, `X-User-ID` must equal the
    `portal_user_id` of the acting `Athlete` row; ownership checks compare that handle
    against the athlete named by the `athlete_id` of the deal contract that owns the
    addressed deliverable ... any other deliverable yields `ERR_FORBIDDEN_RESOURCE`
    (HTTP 403). The `Athlete` role is additionally barred from every donor-facing read —
    the donor member, commitment and contribution reads, both in detail and list form —
    ... each such attempt is `ERR_UNAUTHORIZED`." PRD s2.8 separates the two, placing
    ownership at priority 4 and the endpoint role table at priority 3.

    Design: Corner/rbac/athlete_cannot_touch_another_athletes_deliverable
    """
    ctx = _two_athletes_each_with_one_deliverable(api)
    trespass = evidence_payload("PHOTO_SET", "trespass")

    forbidden = api.add_evidence(
        ctx["other_deliverable_id"], trespass, make_athlete_headers("ath-own")
    )
    validate_error(forbidden, ERR_FORBIDDEN_RESOURCE, expected_status=403)
    assert_error_envelope_shape(forbidden)
    assert_deliverable_scoring(
        read_deliverable(api, ctx["other_deliverable_id"]),
        status="PENDING",
        evidence_count=0,
    )

    # The identical body on the caller's own deliverable is accepted.
    own = read_data(
        api.add_evidence(
            ctx["own_deliverable_id"], trespass, make_athlete_headers("ath-own")
        ),
        expected_status=201,
    )
    assert_deliverable_scoring(own, status="PENDING", evidence_count=1)

    donor_read = api.list_donor_members(
        {"collective_id": ctx["collective_id"]}, make_athlete_headers("ath-own")
    )
    validate_error(donor_read, ERR_UNAUTHORIZED, expected_status=403)

    # A handle matching no athlete row owns nothing, so it is priority 4 as well.
    unknown_handle = api.add_evidence(
        ctx["own_deliverable_id"], trespass, make_athlete_headers("ath-ghost")
    )
    validate_error(unknown_handle, ERR_FORBIDDEN_RESOURCE, expected_status=403)
    assert_deliverable_scoring(
        read_deliverable(api, ctx["own_deliverable_id"]), evidence_count=1
    )


def test_the_verifier_of_a_deliverable_may_not_initiate_its_payout(api):
    """Priority 22 compares handles, not roles, and only for a DELIVERABLE_PAYOUT.

    PRD s2.11: "When a payment release with `release_kind` of `DELIVERABLE_PAYOUT` is
    created, the caller's `X-User-ID` is compared against the `verified_by_user_id`
    recorded on the named deliverable when a compliance officer verified or waived it. If
    the two strings are equal, the release is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)." PRD s3.9 scopes it: "for a `DELIVERABLE_PAYOUT`, the caller's
    `X-User-ID` must differ from the named deliverable's `verified_by_user_id`", and PRD
    s2.1 explains that both handles are opaque, since "a compliance officer's
    `X-User-ID` is stored as `verified_by_user_id` on a deliverable ... and a treasury
    officer's `X-User-ID` is stored as `initiated_by_user_id` on every payment release".

    Design: Corner/rbac/same_user_cannot_verify_a_deliverable_and_initiate_its_payout
    """
    funded = build_funded_collective(
        api,
        "025900",
        500000,
        home_state_code="CA",
        association_ruleset="NCAA_2026",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="sod@example.com",
        name="Sod Collective",
        institution_name="Sod Institution",
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-sod",
        full_name="Sod Athlete",
        sport="WOMENS_BASKETBALL",
    )
    record_taxpayer_doc(api, athlete["id"], "W9")
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        200000,
        funding_designation="UNRESTRICTED",
        state_law_citation="CA-AB131",
        association_rule_citation="NCAA-2026-12.5",
    )
    deliverable = build_deliverable(
        api, contract["id"], "APPEARANCE", 120000, "2026-09-01T00:00:00Z"
    )
    add_evidence(api, deliverable["id"], "SIGNED_ATTENDANCE_SHEET", "sod-sheet")
    submit_work(api, deliverable["id"], "2026-08-05T00:00:00Z")
    verified = review_work(api, deliverable["id"], "VERIFY", "dual-agent")
    assert_deliverable_scoring(
        verified,
        status="VERIFIED",
        payout_basis="STRICT_UNIT_BASIS",
        payout_eligible_cents=120000,
        late_flag=False,
        verified_by_user_id="dual-agent",
    )

    contract_version = read_contract(api, contract["id"])["version"]
    payout = payment_release_payload(
        contract["id"],
        "DELIVERABLE_PAYOUT",
        120000,
        expected_deal_contract_version=contract_version,
        deliverable_id=deliverable["id"],
    )

    self_dealing = api.create_payment_release(payout, make_treasury_headers("dual-agent"))
    validate_error(self_dealing, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    assert_error_envelope_shape(self_dealing)
    assert (
        rows_of(
            api.list_payment_releases(
                {"deal_contract_id": contract["id"]}, make_treasury_headers()
            )
        )
        == []
    )
    assert read_contract(api, contract["id"])["version"] == contract_version

    # The identical body, quoting the very same version, succeeds for another handle.
    released = read_data(
        api.create_payment_release(payout, make_treasury_headers("treasury-clean")),
        expected_status=201,
    )
    assert_release_money(
        released,
        status="RELEASED",
        requested_amount_cents=120000,
        withholding_basis="NONE",
        withholding_amount_cents=0,
        net_payable_cents=120000,
        reversal_reason="NONE",
        initiated_by_user_id="treasury-clean",
    )

    paid = read_contract(api, contract["id"])
    assert_contract_money(paid, total_value_cents=200000, released_total_cents=120000)
    assert_contract_dimensions(
        paid, lifecycle_status="ACTIVE", payment_status="PARTIALLY_PAID"
    )

    # A CONTRACT_ADVANCE names no deliverable, so priority 22 never engages.
    advance = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                50000,
                expected_deal_contract_version=paid["version"],
            ),
            make_treasury_headers("dual-agent"),
        ),
        expected_status=201,
    )
    assert_release_money(
        advance,
        status="RELEASED",
        requested_amount_cents=50000,
        net_payable_cents=50000,
        initiated_by_user_id="dual-agent",
    )

    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        settled_net_funds_cents=487470,
        committed_unreleased_cents=30000,
        released_total_cents=170000,
        reversed_total_cents=0,
        funding_posture="OPEN",
    )
    athlete_row = read_athlete(api, athlete["id"])
    assert athlete_row["tax_year_gross_paid_cents"] == 170000
    assert athlete_row["tax_year_withheld_cents"] == 0
    assert athlete_row["tax_form_required"] == "FORM_1099_NEC"
