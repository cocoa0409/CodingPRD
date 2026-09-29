"""Role-gate probes: which hands may act, whose rows a rancher may reach, what an absent or blank
or entity-less identity earns, and where the person-based segregation check sits relative to the
role gate and the state machine.

Every refusal here is checked to have written nothing, and each is paired with the one call that the
same endpoint does accept, so a role gate that is too wide and one that is too narrow both fail.
"""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ApiErrorId,
    OFFICER_1,
    OFFICER_2,
    SPECIALIST_1,
    api_client,
    assert_aums,
    assert_pct,
    make_adjudicator_headers,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
    make_system_admin_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    bill_of_type,
    create_allotment,
    create_base_property,
    create_pasture,
    create_permit,
    create_permittee,
    get_allotment,
    get_assessment,
    get_bill,
    get_decision,
    issue_permit,
    signed_decision,
)


def _total(response):
    """The filtered total_count of a paginated list response."""
    items, meta = validate_paginated(response)
    return meta["total_count"]


def test_an_appeal_is_filed_by_the_permittee_role_alone_and_only_in_its_own_name():
    """Three refusals and one acceptance on the same FINAL suspension. The affected permittee naming
    the bystander in the payload is refused because the appellant is never inferred; the authoring
    specialist and the deciding officer are refused because filing belongs to the Permittee role
    alone, and neither refusal is the segregation code, since the role gate answers first. Only the
    fourth attempt lands, and it takes the decision FINAL -> STAYED. The reads that follow show the
    same scope rule: the affected permittee cannot read the bystander's row but can read its own, and
    a filtered list returns an empty page rather than a refusal.

    PRD 2.1: "Concretely, a `Permittee` actor may read and act only on its own permits, its own
    annual operating instructions, the use records beneath them, its own bills and its own appeals;
    touching another permittee's row is the same `ERR_UNAUTHORIZED` failure as presenting an unknown
    identity."
    PRD 2.1: "Appeal filing is exclusive to this role, and the `appellant_permittee_id` carried in
    the filing payload must equal the acting `X-User-ID` — the server never infers the appellant
    silently, and a mismatch is `ERR_UNAUTHORIZED`."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES`, HTTP 403, on assessment
    review, decision signature and appeal decision, exactly as specified in §2.10."
    PRD 2.10: "An identifier whose `X-User-Role` is not listed for the operation fails at priority 3
    with `ERR_UNAUTHORIZED` even when that identifier is also the authoring hand — the role gate
    simply gets there first."
    PRD 3.9: "An **appeal case** is the permittee's remedy against a decision, and it is filed by the
    affected `Permittee` alone."
    PRD 3.9: "The new case lands in `appeal_status` `FILED` with `remand_count` 0 and
    `adjudicator_id` null."
    PRD 3.9: "When `stay_requested` is true **and** the decision is in `decision_status` `FINAL` —
    signed but not yet in effect — the petition is granted at filing: `stay_granted` becomes true and
    the decision moves `FINAL → STAYED`, which freezes it completely."
    PRD 3.9: "Appeals are fetched individually with their `stay_granted`, `remand_count` and
    `adjudicator_id` visible, and listed with filters on `decision_id`, `appellant_permittee_id`,
    `appeal_status` and `stay_granted`."

    Design: Corner/rbac/corner_only_the_affected_permittee_may_appeal_and_other_roles_are_rejected
    """
    allotment = create_allotment(name="Coyote Springs Allotment", admin_unit_code="QB-174",
                                 acres=9000, total_permitted_aums=500,
                                 required_pasture_rotation_count=1)
    create_pasture(allotment["id"], name="Coyote North", pasture_aum_capacity=500,
                   sequence_order=1)
    affected = create_permittee(name="Affected Cattle Co",
                               contact_email="affected.qb174@example.com")
    bystander = create_permittee(name="Bystander Sheep Co",
                                contact_email="bystander.qb174@example.com")
    prop = create_base_property(affected["id"], carrying_capacity_aums=400,
                                legal_description="T33N R60E Sec 14 NE")
    permit = issue_permit(create_permit(allotment["id"], affected["id"], prop["id"],
                                       requested_aums=100)["id"])
    decision = signed_decision(
        allotment["id"], decision_type="SUSPENSION", permit_id=permit["id"],
        rationale="Repeated unauthorized use warrants suspension of the permit.")
    assert decision["decision_status"] == "FINAL"

    on_behalf = "Filing on behalf of a neighbouring operator who did not sign this statement."
    validate_error(api_client.file_appeal(
        decision["id"], f.appeal_payload(bystander["id"], True,
                                         statement_of_reasons=on_behalf),
        make_permittee_headers(affected["id"])), ApiErrorId.ERR_UNAUTHORIZED, 403)

    for headers, reasons in (
            (make_specialist_headers(),
             "The authoring specialist attempts to appeal the document it wrote itself."),
            (make_officer_headers(),
             "The deciding officer attempts to appeal its own signature.")):
        refused = api_client.file_appeal(
            decision["id"], f.appeal_payload(affected["id"], True,
                                             statement_of_reasons=reasons), headers)
        body = validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert body["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES, (
            "the role gate at priority 3 answers before the person check at priority 4")

    filed = get_success_data(api_client.file_appeal(
        decision["id"], f.appeal_payload(
            affected["id"], True,
            statement_of_reasons=("The suspension rests on unauthorized use that was billed to a "
                                  "neighbouring operator, not to this ranch.")),
        make_permittee_headers(affected["id"])), 201)
    assert filed["appeal_status"] == "FILED"
    assert filed["stay_granted"] is True
    assert filed["remand_count"] == 0
    assert filed["adjudicator_id"] is None
    assert filed["appellant_permittee_id"] == affected["id"]
    assert get_decision(decision["id"])["decision_status"] == "STAYED"

    validate_error(api_client.get_permittee(bystander["id"],
                                           make_permittee_headers(affected["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    own = get_success_data(api_client.get_permittee(affected["id"],
                                                    make_permittee_headers(affected["id"])))
    assert own["id"] == affected["id"]

    assert _total(api_client.list_appeals(
        make_permittee_headers(bystander["id"]),
        {"appellant_permittee_id": bystander["id"]})) == 0, (
        "a scoped list read returns an empty page, not a refusal")
    assert _total(api_client.list_appeals(
        make_adjudicator_headers(), {"decision_id": decision["id"]})) == 1, (
        "exactly one appeal survived the three refusals")


def test_the_specialists_authoring_writes_are_refused_to_every_other_role():
    """The six authoring operations are refused to the deciding officer, to a real permittee, to the
    adjudicator and to the system administrator alike, and the refusal is the role code even when the
    path names an assessment or a decision that was never minted — the role gate at priority 3 runs
    ahead of the existence lookup at priority 5. Nothing survives: all four registries are empty for
    this allotment, and the refused authorship left the allotment's version exactly where it was, so
    a refusal is not a silent write. The identical assessment body sent by a specialist is accepted.

    PRD 2.1: "The same code and status are returned when the role named in `X-User-Role` is not among
    the roles authorised for the requested operation, and when a rancher reaches for a record that
    belongs to somebody else."
    PRD 2.1: "A `RangeSpecialist` is field and resource staff who author the technical record:
    rangeland health assessments, decision documents, trespass detections and range improvement
    proposals, plus the drafting and scheduling of annual operating instructions."
    PRD 2.1: "This role authors but never approves."
    PRD 2.1: "An `AppealsAdjudicator` is the independent administrative judge who dockets and decides
    appeals."
    PRD 2.1: "A `SystemAdmin` exists solely to drive the service's logical clock and holds no
    business authority whatsoever."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."
    PRD 3.7: "The new row lands in `assessment_status` `DRAFT` with `remand_count` 0,
    `composite_score`, `determination` and `recommended_reduction_pct` all still unwritten —
    `recommended_reduction_pct` reading its default of 0 — and `author_user_id` set to the creating
    specialist's `X-User-ID`."
    PRD 3.7: "Assessments are listed with filters on `allotment_id`, `assessment_year`,
    `monitoring_method`, `assessment_status` and `determination`."
    PRD 3.8: "Authorship itself bumps the allotment's `version`, which means two decisions authored
    back to back against the same allotment cannot both quote the same `expected_allotment_version`;
    the second author must re-read the allotment first."
    PRD 3.11: "A `RangeSpecialist` records the incident with `allotment_id`, `permittee_id`,
    `detected_at`, `head_count`, `livestock_kind`, `unauthorized_days` and `willfulness`."
    PRD 4: "| POST | `/rangeland-health-assessments` | Open a rangeland health assessment for an
    allotment and monitoring year. | `RangeSpecialist` |"
    PRD 4: "| POST | `/rangeland-health-assessments/{assessmentId}/submit` | Submit a drafted
    assessment for field review. | `RangeSpecialist` |"
    PRD 4: "| POST | `/permit-decisions` | Author a decision document against an allotment at a given
    `expected_allotment_version`. | `RangeSpecialist` |"
    PRD 4: "| POST | `/permit-decisions/{decisionId}/complete-environmental-review` | Record the
    environmental findings and propose the decision. | `RangeSpecialist` |"
    PRD 4: "| POST | `/trespass-incidents` | Record detected unauthorized use and snapshot the
    permittee's prior billed count. | `RangeSpecialist` |"
    PRD 4: "| POST | `/range-improvement-projects` | Propose a range improvement project with its
    cost split and maintenance duty. | `RangeSpecialist` |"

    Design: Corner/rbac/corner_range_specialist_exclusives_rejected_for_every_other_role
    """
    allotment = create_allotment(name="Tule Flat Allotment", admin_unit_code="QB-175", acres=7000,
                                 total_permitted_aums=300, required_pasture_rotation_count=1)
    version_before = get_allotment(allotment["id"])["version"]
    rancher = create_permittee(name="Tule Flat Grazing LLC",
                              contact_email="tule.qb175@example.com")
    permittee_headers = make_permittee_headers(rancher["id"])
    # Every body below is shape-valid and date-coherent, so priorities 1 and 2 cannot answer first.
    assessment_body = f.assessment_payload(allotment["id"], upland_score=60, riparian_score=60,
                                           water_quality_score=60)
    trespass_body = f.trespass_payload(allotment["id"], permittee_id=rancher["id"], head_count=20,
                                       unauthorized_days=10, willfulness="NON_WILLFUL")

    refusals = [
        ("the officer opens an assessment",
         api_client.create_assessment(assessment_body, make_officer_headers())),
        ("the officer submits an assessment that was never minted",
         api_client.submit_assessment(NON_EXISTENT_UUID, make_officer_headers())),
        # An ISSUANCE decision must carry a non-null permit_id to be shape-valid, but the id itself
        # is only looked up at priority 6, which the role gate never lets the request reach.
        ("the officer authors its own decision", api_client.create_decision(
            f.decision_payload(allotment["id"], version_before,
                               permit_id=NON_EXISTENT_UUID,
                               rationale="The officer attempts to author its own decision."),
            make_officer_headers())),
        ("the permittee records the environmental findings",
         api_client.complete_environmental_review(
             NON_EXISTENT_UUID, f.environmental_review_payload(), permittee_headers)),
        ("the permittee reports its own trespass",
         api_client.create_trespass_incident(trespass_body, permittee_headers)),
        ("the administrator reports a trespass",
         api_client.create_trespass_incident(trespass_body, make_system_admin_headers())),
        ("the adjudicator proposes a project", api_client.create_project(
            f.project_payload(allotment["id"], project_type="WATER_DEVELOPMENT",
                              total_cost_cents=400000, agency_share_pct=0.6,
                              permittee_share_pct=0.4,
                              maintenance_responsibility="PERMITTEE"),
            make_adjudicator_headers())),
    ]
    for label, response in refusals:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert response.json()["data"]["error_id"] == ApiErrorId.ERR_UNAUTHORIZED, label

    for label, response in (refusals[1], refusals[3]):
        assert response.json()["data"]["error_id"] not in (
            ApiErrorId.ERR_ASSESSMENT_NOT_FOUND, ApiErrorId.ERR_DECISION_NOT_FOUND), (
            "the never-minted path id is not even looked up: %s" % label)

    specialist = make_specialist_headers()
    scope = {"allotment_id": allotment["id"], "limit": 100}
    assert _total(api_client.list_assessments(specialist, scope)) == 0
    assert _total(api_client.list_decisions(specialist, scope)) == 0
    assert _total(api_client.list_trespass_incidents(specialist, scope)) == 0
    assert _total(api_client.list_projects(specialist, scope)) == 0
    assert get_allotment(allotment["id"])["version"] == version_before, (
        "the refused authorship never bumped the allotment version")

    opened = get_success_data(api_client.create_assessment(assessment_body, specialist), 201)
    assert opened["assessment_status"] == "DRAFT"
    assert opened["author_user_id"] == SPECIALIST_1
    assert opened["remand_count"] == 0
    assert opened["composite_score"] is None
    assert opened["determination"] is None
    assert_pct(opened["recommended_reduction_pct"], 0.0)


def test_the_officers_approval_writes_are_refused_to_every_other_role():
    """Eighteen approval-side writes are refused to the specialist who drafts the same documents, to
    the permittee they concern and to the adjudicator, and every path id and body foreign key in them
    is a never-minted literal that is never once reported as missing: the role gate at priority 3
    precedes both existence checks. The refusal on assessment review and on decision signature is the
    role code and not the segregation code, because priority 3 precedes priority 4. The nineteenth
    call is the contrast that makes the boundary falsifiable: drafting an instruction is shared with
    the specialist, so the identical actor clears the role gate there and fails on the unknown permit
    instead. Nothing was created, and the permittee's own read access is untouched.

    PRD 2.1: "The same code and status are returned when the role named in `X-User-Role` is not among
    the roles authorised for the requested operation, and when a rancher reaches for a record that
    belongs to somebody else."
    PRD 2.1: "An `AuthorizedOfficer` is the deciding official: this role registers allotments,
    pastures, permittees and base properties, issues and renews and transfers permits, issues and
    reduces and voids operating instructions, signs and effectuates decisions, issues and lifts
    closure orders, bills trespass, and approves and allocates range improvement projects."
    PRD 2.1: "This role authors but never approves."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES`, HTTP 403, on assessment
    review, decision signature and appeal decision, exactly as specified in §2.10."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."
    PRD 2.6: "**Body foreign-key existence** — HTTP 404 with the entity-specific code, in the
    declared field order."
    PRD 2.10: "An identifier whose `X-User-Role` is not listed for the operation fails at priority 3
    with `ERR_UNAUTHORIZED` even when that identifier is also the authoring hand — the role gate
    simply gets there first."
    PRD 4: "| POST | `/annual-operating-instructions` | Draft the annual operating instructions for a
    permit and grazing year. | `RangeSpecialist`, `AuthorizedOfficer` |"
    PRD 4: "| POST | `/annual-operating-instructions/{aoiId}/issue` | Issue a drafted instruction and
    raise its preliminary use bill. | `AuthorizedOfficer` |"
    PRD 4: "| GET | `/grazing-bills` | List bills by permittee, instruction, incident, project,
    `bill_type` or `bill_status`. | All four operational roles |"

    Design: Corner/rbac/corner_authorized_officer_exclusives_rejected_for_every_other_role
    """
    rancher = create_permittee(name="Refusal Test Ranch",
                              contact_email="refusal.qb176@example.com")
    rancher_headers = make_permittee_headers(rancher["id"])
    specialist = make_specialist_headers()
    adjudicator = make_adjudicator_headers()
    unknown = NON_EXISTENT_UUID
    full_closure = f.closure_order_payload(
        unknown, order_type="FULL_CLOSURE", effective_start_date="2026-08-10",
        effective_end_date="2026-09-10",
        justification="The specialist attempts to order a closure without a deciding official.")
    del full_closure["reduction_pct"]  # a full closure omits it or sends exactly 1.0

    refusals = [
        ("the specialist registers an allotment", api_client.create_allotment(
            f.allotment_payload(name="Specialist Authored Allotment", admin_unit_code="QB-176",
                                acres=5000, total_permitted_aums=200), specialist)),
        ("the specialist registers a permittee", api_client.create_permittee(
            f.permittee_payload(name="Specialist Authored Ranch",
                                contact_email="spec.ranch.qb176@example.com"), specialist)),
        ("the permittee registers a pasture", api_client.create_pasture(
            unknown, f.pasture_payload(name="Permittee Authored Pasture",
                                       pasture_aum_capacity=100), rancher_headers)),
        ("the permittee registers base property", api_client.create_base_property(
            unknown, f.base_property_payload(base_property_type="LIVESTOCK",
                                             carrying_capacity_aums=200), rancher_headers)),
        ("the specialist files a permit application", api_client.create_permit(
            f.permit_payload(unknown, rancher["id"], unknown, requested_aums=100), specialist)),
        ("the permittee issues its own permit", api_client.issue_permit(unknown, rancher_headers)),
        ("the permittee transfers a permit", api_client.transfer_permit(
            unknown, f.transfer_payload(rancher["id"], unknown, requested_aums=100,
                                        term_start_date="2027-01-01",
                                        term_end_date="2031-12-31"), rancher_headers)),
        ("the specialist issues an instruction", api_client.issue_aoi(unknown, specialist)),
        ("the specialist approves non-use", api_client.approve_nonuse(
            unknown, f.nonuse_payload(nonuse_aums=10, nonuse_reason="DROUGHT"), specialist)),
        ("the specialist accepts the use report",
         api_client.accept_use_report(unknown, specialist)),
        ("the permittee voids its own bill", api_client.void_bill(
            unknown, f.void_payload(void_reason="The permittee attempts to void its own bill."),
            rancher_headers)),
        ("the author reviews its own assessment", api_client.review_assessment(
            unknown, f.review_payload(review_notes="The author attempts to concur with itself."),
            specialist)),
        ("the author signs its own decision", api_client.finalize_decision(
            unknown, f.finalize_payload(
                rationale="The author attempts to sign its own decision."), specialist)),
        ("the adjudicator makes a decision effective",
         api_client.make_decision_effective(unknown, adjudicator)),
        ("the specialist orders a closure",
         api_client.create_closure_order(full_closure, specialist)),
        ("the specialist bills a trespass",
         api_client.bill_trespass_incident(unknown, specialist)),
        ("the adjudicator approves a project", api_client.approve_project(unknown, adjudicator)),
        ("the specialist allocates the cost share",
         api_client.allocate_cost_share(unknown, specialist)),
    ]
    for label, response in refusals:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert response.json()["data"]["error_id"] == ApiErrorId.ERR_UNAUTHORIZED, label

    for label, response in (refusals[11], refusals[12]):
        assert response.json()["data"]["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES, (
            "the role gate answers before the person check: %s" % label)

    shared = api_client.create_aoi(
        f.aoi_payload(unknown, authorized_aums=50, season_start_date="2026-05-01",
                      season_end_date="2026-09-30"), specialist)
    validate_error(shared, ApiErrorId.ERR_PERMIT_NOT_FOUND, 404)

    assert _total(api_client.list_allotments(
        make_officer_headers(), {"admin_unit_code": "QB-176", "limit": 100})) == 0
    assert _total(api_client.list_permits(
        make_officer_headers(), {"permittee_id": rancher["id"], "limit": 100})) == 0
    assert _total(api_client.list_bills(
        rancher_headers, {"permittee_id": rancher["id"], "limit": 100})) == 0, (
        "the permittee's own read access is intact"
    )


def test_docketing_and_deciding_belong_to_the_adjudicator_alone():
    """The same never-minted appeal id separates the role gate from existence. The deciding officer,
    the authoring specialist and a permittee are all refused with the role code; the adjudicator gets
    a not-found for the identical id, which is the only way to see that the four refusals never
    reached the lookup at all. The adjudicator's reads are unscoped in a way a permittee's are not: it
    reads a permittee row it has no relation to, and a list narrowed to that stranger comes back as an
    empty page rather than a refusal.

    PRD 2.1: "An `AppealsAdjudicator` is the independent administrative judge who dockets and decides
    appeals."
    PRD 2.1: "When `X-User-Role` is `AppealsAdjudicator`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity; the server records it as `adjudicator_id` on the case
    it dockets, but never compares it to any entity's `id`."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."
    PRD 3.9: "Docketing is the `AppealsAdjudicator`'s act of taking the case up, and it moves
    `appeal_status` `FILED → UNDER_REVIEW` while stamping `adjudicator_id` with the docketing
    adjudicator's `X-User-ID`."
    PRD 4: "| POST | `/appeal-cases/{appealId}/docket` | Docket a filed appeal for adjudication. |
    `AppealsAdjudicator` |"
    PRD 4: "| POST | `/appeal-cases/{appealId}/decide` | Affirm, reverse, remand or dismiss an appeal
    under review. | `AppealsAdjudicator` |"
    PRD 4: "| GET | `/appeal-cases` | List appeals by decision, appellant, `appeal_status` or
    `stay_granted`. | All four operational roles |"
    PRD 4: "| GET | `/permittees/{permitteeId}` | Fetch one permittee including
    `outstanding_balance_cents` and `permittee_status`. | All four operational roles |"

    Design: Corner/rbac/corner_appeals_adjudicator_alone_dockets_and_decides_others_rejected
    """
    stranger = create_permittee(name="Appellant Only Ranch",
                               contact_email="appellant.only.qb177@example.com")
    unknown = NON_EXISTENT_UUID

    for label, headers in (("the deciding officer", make_officer_headers()),
                           ("the authoring specialist", make_specialist_headers()),
                           ("a permittee", make_permittee_headers(stranger["id"]))):
        refused = api_client.docket_appeal(unknown, headers)
        validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_APPEAL_NOT_FOUND, (
            "%s never reaches the priority-5 lookup" % label)

    validate_error(api_client.decide_appeal(
        unknown, f.appeal_decision_payload(
            "AFFIRM",
            decision_rationale=("The deciding officer attempts to affirm its own decision on "
                                "appeal.")),
        make_officer_headers()), ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api_client.decide_appeal(
        unknown, f.appeal_decision_payload(
            "REVERSE",
            decision_rationale="The appellant attempts to grant its own appeal."),
        make_permittee_headers(stranger["id"])), ApiErrorId.ERR_UNAUTHORIZED, 403)

    adjudicator = make_adjudicator_headers()
    validate_error(api_client.docket_appeal(unknown, adjudicator),
                   ApiErrorId.ERR_APPEAL_NOT_FOUND, 404)

    filed_page, _meta = validate_paginated(
        api_client.list_appeals(adjudicator, {"appeal_status": "FILED", "limit": 100}))
    for appeal in filed_page:
        assert appeal["appeal_status"] == "FILED", "the status filter is honoured"
    assert _total(api_client.list_appeals(
        adjudicator, {"appellant_permittee_id": stranger["id"], "limit": 100})) == 0

    read = get_success_data(api_client.get_permittee(stranger["id"], adjudicator))
    assert read["id"] == stranger["id"], "the adjudicator is not confined to its own rows"


def test_each_shared_operation_is_accepted_from_every_role_that_holds_it():
    """One grazing year exercised by three different hands. The instruction is drafted by the
    specialist and one leg is scheduled by the specialist while the other is scheduled by the officer;
    the two actual-use reports are filed by different roles, one of them the permittee itself; and the
    single final bill is paid in two instalments, the first by the permittee and the second by the
    officer. Every one of those calls carries the same status and the same side effect whichever
    listed role made it, so a gate written as one role per endpoint fails here. The closing control
    shows that shared never means open: the officer, who may pay the bill, may not file the report.

    PRD 2.1: "A `Permittee` also reports actual use on its own scheduled windows (shared with
    `RangeSpecialist`) and records payments against its own bills (shared with `AuthorizedOfficer`)."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 3.4: "The forage a leg represents is computed the moment it is scheduled."
    PRD 3.6: "Step two computes `base_amount_cents` as `billed_aums` multiplied by the grazing fee
    rate of 172 cents per AUM, rounded half-up to a whole cent; that same 172 is recorded on the bill
    as its `fee_rate_cents_per_aum`."
    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`, never from
    the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000 cents, 2,500 cents
    when `base_amount_cents` is at least 50,000 and below 200,000 cents, and 6,000 cents when
    `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents` of 0 and a
    `due_date` of the logical-clock date at issuance plus 30 days."
    PRD 3.6: "When the preliminary bill's `amount_paid_cents` is exactly 0, that bill moves to
    `bill_status` `VOIDED` and a bill of `bill_type` `FINAL_USE` is issued for the final total with
    `superseded_bill_id` set to the voided bill's `id`."
    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 4: "| POST | `/annual-operating-instructions` | Draft the annual operating instructions for a
    permit and grazing year. | `RangeSpecialist`, `AuthorizedOfficer` |"
    PRD 4: "| POST | `/annual-operating-instructions/{aoiId}/use-records` | Schedule a pasture use
    record on a drafted instruction. | `RangeSpecialist`, `AuthorizedOfficer` |"
    PRD 4: "| POST | `/pasture-use-records/{useRecordId}/report-actual-use` | Report actual livestock
    numbers and dates against a scheduled use record. | `Permittee`, `RangeSpecialist` |"
    PRD 4: "| POST | `/grazing-bills/{billId}/payments` | Record a payment of `amount_cents` against a
    bill. | `Permittee`, `AuthorizedOfficer` |"
    PRD 4: "| GET | `/annual-operating-instructions` | List instructions by permit, allotment,
    `grazing_year` or `aoi_status`. | All four operational roles |"

    Design: Corner/rbac/corner_shared_operations_accepted_from_each_listed_role
    """
    officer = make_officer_headers()
    specialist = make_specialist_headers()
    allotment = create_allotment(name="Two Hands Allotment", admin_unit_code="QB-178", acres=8000,
                                 total_permitted_aums=500, required_pasture_rotation_count=2)
    east = create_pasture(allotment["id"], name="Two Hands East", pasture_aum_capacity=300,
                          sequence_order=1)
    west = create_pasture(allotment["id"], name="Two Hands West", pasture_aum_capacity=300,
                          sequence_order=2)
    rancher = create_permittee(name="Two Hands Livestock",
                              contact_email="twohands.qb178@example.com")
    rancher_headers = make_permittee_headers(rancher["id"])
    prop = create_base_property(rancher["id"], carrying_capacity_aums=400,
                               legal_description="T27N R51E Sec 30 NW")
    permit = issue_permit(create_permit(allotment["id"], rancher["id"], prop["id"],
                                       requested_aums=100)["id"])

    aoi = get_success_data(api_client.create_aoi(
        f.aoi_payload(permit["id"], authorized_aums=60, season_start_date="2026-05-01",
                      season_end_date="2026-09-30"), specialist), 201)
    assert aoi["aoi_status"] == "DRAFT"
    assert aoi["authorized_aums"] == 60

    first = get_success_data(api_client.create_use_record(aoi["id"], f.use_record_payload(
        east["id"], planned_entry_date="2026-06-01", planned_exit_date="2026-07-01",
        planned_head_count=30), specialist), 201)
    second = get_success_data(api_client.create_use_record(aoi["id"], f.use_record_payload(
        west["id"], planned_entry_date="2026-07-01", planned_exit_date="2026-07-31",
        planned_head_count=30), officer), 201)
    assert_aums(first["planned_aums"], 30.00)   # 30 head x CATTLE 1.0 x 30 days / 30
    assert_aums(second["planned_aums"], 30.00)

    issued = get_success_data(api_client.issue_aoi(aoi["id"], officer))
    assert issued["aoi_status"] == "ISSUED"
    preliminary = bill_of_type("PRELIMINARY_USE", aoi_id=aoi["id"])
    assert preliminary["total_amount_cents"] == 10320  # 60 x 172, no admin fee under 50,000
    assert preliminary["admin_fee_cents"] == 0
    assert preliminary["fee_rate_cents_per_aum"] == 172
    assert preliminary["due_date"] == "2026-08-31"

    reported_by_rancher = get_success_data(api_client.report_actual_use(
        first["id"], f.report_actual_use_payload(
            actual_entry_date="2026-06-01", actual_exit_date="2026-07-01", actual_head_count=30),
        rancher_headers))
    reported_by_specialist = get_success_data(api_client.report_actual_use(
        second["id"], f.report_actual_use_payload(
            actual_entry_date="2026-07-01", actual_exit_date="2026-07-31", actual_head_count=30),
        specialist))
    for reported in (reported_by_rancher, reported_by_specialist):
        assert reported["record_status"] == "ACTUAL_REPORTED"
        assert_aums(reported["actual_aums"], 30.00)

    billed = get_success_data(api_client.accept_use_report(aoi["id"], officer))
    assert billed["aoi_status"] == "BILLED"
    assert_aums(billed["actual_aums_total"], 60.00)
    assert get_bill(preliminary["id"])["bill_status"] == "VOIDED"
    final = bill_of_type("FINAL_USE", aoi_id=aoi["id"])
    assert final["total_amount_cents"] == 10320
    assert final["superseded_bill_id"] == preliminary["id"]

    outstanding, meta = validate_paginated(api_client.list_bills(
        rancher_headers, {"permittee_id": rancher["id"], "bill_status": "ISSUED", "limit": 100}))
    assert meta["total_count"] == 1, "only the final bill is still ISSUED"
    assert outstanding[0]["id"] == final["id"]

    part = get_success_data(api_client.record_payment(
        final["id"], f.payment_payload(5320), rancher_headers), 201)
    assert part["amount_paid_cents"] == 5320
    assert part["bill_status"] == "ISSUED"
    rest = get_success_data(api_client.record_payment(
        final["id"], f.payment_payload(5000), officer), 201)
    assert rest["amount_paid_cents"] == 10320
    assert rest["bill_status"] == "PAID"

    assert _total(api_client.list_aois(
        make_adjudicator_headers(), {"permit_id": permit["id"], "grazing_year": 2026})) == 1

    validate_error(api_client.report_actual_use(
        first["id"], f.report_actual_use_payload(
            actual_entry_date="2026-06-01", actual_exit_date="2026-07-01", actual_head_count=30),
        officer), ApiErrorId.ERR_UNAUTHORIZED, 403)


def _headers_without_identity(role):
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def _headers_with_blank_identity(role):
    """Headers whose X-User-ID is the exact empty string — never a space or any other whitespace,
    which an HTTP client would reject as an invalid header value before the server ever saw it."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def test_an_absent_a_blank_and_an_entity_less_identity_are_all_refused():
    """The same body is sent four times and lands only once. With no X-User-ID header at all, and with
    the header present but empty, the write is refused; a read is gated exactly the same way; and for
    the entity-backed Permittee role an id that matches no permittee row is an unknown actor rather
    than a rancher who happens to own nothing, so the refusal is a 403 and never a 200 with an empty
    page. The registered officer's identical body then succeeds, and exactly one row bears the code.

    PRD 2.1: "Every request — reads included — must carry two headers."
    PRD 2.1: "If `X-User-ID` is absent, empty, or does not resolve to a known actor, the request fails
    with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "When `X-User-Role` is `Permittee`, `X-User-ID` is the `id` of the acting `Permittee`
    record itself; ownership checks on any resource that references a permittee compare that
    resource's permittee reference to `X-User-ID`."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "The rules are those of §2.1: `X-User-ID` present, non-empty and resolvable; the acting
    role listed for the operation; and a `Permittee` actor confined to rows belonging to its own
    permittee record, including the requirement that a filed appeal's `appellant_permittee_id` equal
    the acting `X-User-ID`."
    PRD 3.1: "Officers and specialists can therefore browse the inventory filtered by
    `allotment_status`, by `health_determination` or by `admin_unit_code`, and read a single allotment
    to see its live ledger and its current `version`."

    Design: Corner/rbac/corner_absent_blank_and_unknown_identity_all_refused
    """
    control = create_permittee(name="Identity Control Ranch",
                              contact_email="identity.qb179@example.com")

    def body(name):
        return f.allotment_payload(name=name, admin_unit_code="QB-179", acres=2000,
                                   total_permitted_aums=80)

    validate_error(api_client.create_allotment(
        body("Headerless Allotment"), _headers_without_identity("AuthorizedOfficer")),
        ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api_client.create_allotment(
        body("Blank Identity Allotment"), _headers_with_blank_identity("AuthorizedOfficer")),
        ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api_client.list_allotments(_headers_with_blank_identity("RangeSpecialist")),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)

    ghost_read = api_client.list_bills(make_permittee_headers(NON_EXISTENT_UUID),
                                      {"permittee_id": control["id"]})
    assert ghost_read.status_code != 200, (
        "an id matching no permittee row is an unknown actor, not an owner of nothing")
    validate_error(ghost_read, ApiErrorId.ERR_UNAUTHORIZED, 403)

    created = get_success_data(api_client.create_allotment(
        body("Identity Control Allotment"), make_officer_headers()), 201)
    assert created["admin_unit_code"] == "QB-179"
    assert _total(api_client.list_allotments(
        make_officer_headers(), {"admin_unit_code": "QB-179", "limit": 100})) == 1, (
        "exactly one of the four attempts created a row")


def test_segregation_of_duties_disqualifies_the_person_and_not_the_capacity():
    """Two orderings pin priority 4 in place. On assessment review the author presenting the officer
    header clears the role gate and is then turned away by the person check, while the same author
    presenting its own specialist header is turned away earlier by the role gate — so the code changes
    with the header even though the person does not, and neither refusal scores the assessment. On
    decision signature the author is refused while the document is still DRAFT, which only holds if
    the person check runs before the state check; the identical call from an independent officer proves
    it by earning the state conflict instead. When every other precondition is finally satisfied the
    author is still refused, and the independent officer signs, leaving the two hands recorded apart.

    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES`, HTTP 403, on assessment
    review, decision signature and appeal decision, exactly as specified in §2.10."
    PRD 2.6: "**Transition legality** — HTTP 409 with the entity-specific state code."
    PRD 2.10: "Three operations enforce this, each comparing `X-User-ID` values only and never roles,
    and each failing with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.10: "On assessment review, the reviewing officer's `X-User-ID` must not equal the
    assessment's `author_user_id`."
    PRD 2.10: "On decision signature, the deciding officer's `X-User-ID` must not equal the decision's
    `authoring_officer_id`."
    PRD 2.10: "Two consequences follow from the fact that this check runs at priority 4, after the
    role gate at priority 3, and inspects identifiers alone."
    PRD 2.10: "And an identifier whose `X-User-Role` **is** listed for the operation fails here with
    `ERR_SEGREGATION_OF_DUTIES` even though its role is impeccable, because the person, not the
    capacity, is what disqualifies it."
    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto
    the allotment's `health_determination`, and bumps the allotment's `version`."
    PRD 3.7: "Multiply `upland_score` by 0.40, `riparian_score` by 0.35 and `water_quality_score` by
    0.25, add the three products, and round the sum half-up to 2 decimal places; the result is
    `composite_score`."
    PRD 3.7: "The `determination` follows by band: `MEETING` when `composite_score` is at least 70,
    `MEETING_WITH_PROBLEMS` when `composite_score` is at least 50 but less than 70, and `NOT_MEETING`
    in every remaining case, that is when it is below 50."
    PRD 3.8: "The new decision lands in `decision_status` `DRAFT` with `nepa_status` `PENDING`,
    `nepa_findings_summary` null, `pre_decision_adjustment_pct` null, `deciding_officer_id` null and
    `effective_date` null unless supplied, and its `authoring_officer_id` is stamped with the authoring
    specialist's `X-User-ID`."
    PRD 3.8: "On success the `nepa_findings_summary` is stored, `nepa_status` becomes `COMPLETE`, and
    the decision moves `DRAFT → PROPOSED` in the same operation, so completing the review and
    proposing the decision are one act rather than two."
    PRD 3.8: "The decision must be in `decision_status` `PROPOSED`, else `ERR_DECISION_STATE_INVALID`."
    PRD 3.8: "The signing officer's `X-User-ID` must differ from `authoring_officer_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "On success `decision_status` becomes `FINAL`, `deciding_officer_id` is stamped with the
    signing officer's `X-User-ID`, and the `rationale` is stored."

    Design: Corner/rbac/corner_segregation_of_duties_rejects_by_person_not_by_role
    """
    allotment = create_allotment(name="One Hand Allotment", admin_unit_code="QB-180", acres=6000,
                                 total_permitted_aums=400, required_pasture_rotation_count=1)
    rancher = create_permittee(name="One Hand Cattle", contact_email="onehand.qb180@example.com")
    prop = create_base_property(rancher["id"], carrying_capacity_aums=300,
                               legal_description="T21N R48E Sec 22 SW")
    permit = create_permit(allotment["id"], rancher["id"], prop["id"], requested_aums=100)

    assessment = get_success_data(api_client.create_assessment(
        f.assessment_payload(allotment["id"], standards_not_met=[],
                             causal_factor_is_livestock=False),
        make_specialist_headers(SPECIALIST_1)), 201)
    assert assessment["author_user_id"] == SPECIALIST_1
    submitted = get_success_data(api_client.submit_assessment(
        assessment["id"], make_specialist_headers(SPECIALIST_1)))
    assert submitted["assessment_status"] == "FIELD_REVIEW"

    # The author wearing the officer hat: the role gate is satisfied, the person is not.
    validate_error(api_client.review_assessment(
        assessment["id"], f.review_payload(
            review_notes="The author concurs with its own field work."),
        make_officer_headers(SPECIALIST_1)), ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    # The same person under its own role header never reaches the person check.
    validate_error(api_client.review_assessment(
        assessment["id"], f.review_payload(
            review_notes="The author concurs under its own role header."),
        make_specialist_headers(SPECIALIST_1)), ApiErrorId.ERR_UNAUTHORIZED, 403)

    untouched = get_assessment(assessment["id"])
    assert untouched["assessment_status"] == "FIELD_REVIEW", "a refused review scores nothing"
    assert untouched["remand_count"] == 0
    assert untouched["composite_score"] is None
    assert untouched["determination"] is None

    finalized = get_success_data(api_client.review_assessment(
        assessment["id"], f.review_payload(
            review_notes="Independent review confirms the indicator scores."),
        make_officer_headers(OFFICER_1)))
    assert finalized["assessment_status"] == "FINALIZED"
    assert finalized["composite_score"] == pytest.approx(80.00, abs=0.005)  # 0.4+0.35+0.25 of 80
    assert finalized["determination"] == "MEETING"
    assert_pct(finalized["recommended_reduction_pct"], 0.0)
    concurred = get_allotment(allotment["id"])
    assert concurred["health_determination"] == "MEETING"

    decision = get_success_data(api_client.create_decision(
        f.decision_payload(allotment["id"], concurred["version"], nepa_level="EA",
                           permit_id=permit["id"],
                           rationale="Authored by the officer who will not be allowed to sign it."),
        make_specialist_headers(OFFICER_2)), 201)
    assert decision["authoring_officer_id"] == OFFICER_2
    assert decision["decision_status"] == "DRAFT"
    assert decision["nepa_status"] == "PENDING"
    assert decision["deciding_officer_id"] is None

    validate_error(api_client.finalize_decision(
        decision["id"], f.finalize_payload(
            rationale="The author attempts to sign while the document is still DRAFT."),
        make_officer_headers(OFFICER_2)), ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    validate_error(api_client.finalize_decision(
        decision["id"], f.finalize_payload(
            rationale="An independent officer attempts to sign while the document is still DRAFT."),
        make_officer_headers(OFFICER_1)), ApiErrorId.ERR_DECISION_STATE_INVALID, 409)

    proposed = get_success_data(api_client.complete_environmental_review(
        decision["id"], f.environmental_review_payload(
            nepa_findings_summary="The environmental assessment finds no significant impact."),
        make_specialist_headers(OFFICER_2)))
    assert proposed["decision_status"] == "PROPOSED"
    assert proposed["nepa_status"] == "COMPLETE"

    validate_error(api_client.finalize_decision(
        decision["id"], f.finalize_payload(
            rationale="The author attempts to sign the proposed decision."),
        make_officer_headers(OFFICER_2)), ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    signed = get_success_data(api_client.finalize_decision(
        decision["id"], f.finalize_payload(
            rationale="The independent deciding officer signs the proposed decision."),
        make_officer_headers(OFFICER_1)))
    assert signed["decision_status"] == "FINAL"
    assert signed["deciding_officer_id"] == OFFICER_1
    assert signed["authoring_officer_id"] == OFFICER_2, "the two hands are recorded separately"
