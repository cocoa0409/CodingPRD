"""Role authorization, exclusive writes and segregation of duties.

Every request in this system carries X-User-ID and X-User-Role; the role is
checked against the endpoint's authorized-role list before any business gate
is consulted, and label approval additionally reads the stored author id.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_brand_admin_headers,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
    assert_second_precision_instant,
    DEFAULT_GRAPH,
    care_results_payload,
    care_test_payload,
    import_shipment_payload,
    draft_determination,
    draft_permanent_label,
    file_shipment,
    label_payload_for,
    read_audit,
    read_finding,
    read_label,
    read_style,
    record_disposition,
    reserve_care_test,
    set_clock,
    setup_audit_with_findings,
    setup_label_ready_style,
    submit_label,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
LAB = TEST_USERS["accredited_lab_headers"]
SPECIALIST = TEST_USERS["labeling_specialist_headers"]
APPROVER = TEST_USERS["labeling_approver_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

ADMIN_USER_ID = ADMIN["X-User-ID"]


# --- file-local setup helpers ---------------------------------------------

def _remediated_care_finding():
    """One audit over a brand carrying a single CARE_UNSUBSTANTIATED finding of
    100 units, all 100 released by a disposition, so the finding is REMEDIATED."""
    _brand_id, _style_id, audit, findings = setup_audit_with_findings(
        finding_specs=[{"finding_code": "CARE_UNSUBSTANTIATED",
                        "units_affected": 100}])
    finding = record_disposition(findings[0]["id"], units_released=100)
    return audit, finding


def _pending_label_awaiting_fiber_evidence():
    """A PENDING_APPROVAL permanent label whose style has no fiber-content
    evidence at all, so the earliest content gate it can reach is the fiber one."""
    bundle = setup_label_ready_style(skip_fiber=True, skip_origin=True,
                                     graph=DEFAULT_GRAPH)
    bundle["determination"] = draft_determination(bundle["style"]["id"])
    bundle["style"] = read_style(bundle["style"]["id"])
    label = submit_label(draft_permanent_label(bundle)["id"])
    return bundle, label


def _pending_label_authored_by(user_id, headers=None):
    """A fully substantiated style plus a PENDING_APPROVAL permanent label whose
    authored_by_user_id is `user_id`."""
    bundle = setup_label_ready_style()
    author_headers = headers or make_headers(user_id, "LabelingSpecialist")
    label = draft_permanent_label(bundle, headers=author_headers)
    return bundle, submit_label(label["id"], headers=author_headers)


def _bare_style():
    """Registry + brand + style with a declared fiber array and no evidence."""
    return setup_label_ready_style(skip_fiber=True, skip_origin=True,
                                   skip_care=True)


# --- verification is the Auditor's exclusive act ---------------------------

def test_compliance_admin_cannot_verify_a_remediated_finding(api):
    """PRD 2.1: "A `ComplianceAdmin` is the platform's own compliance operator. It owns the market-requirement registry, the brand registry, the logical clock and the legal pinning of an origin determination, and it may stand in for most operational roles across every brand — but it is deliberately barred from approving a label and from verifying an audit finding, so that no single role can both author compliance evidence and bless it."

    PRD 2.1: "Once the caller is authenticated, the service compares the acting role against the list of roles authorized for the invoked endpoint in §4; a role that is not listed there is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/only_the_auditor_may_verify_a_remediated_finding
    """
    audit, finding = _remediated_care_finding()
    assert finding["state"] == "REMEDIATED", (
        f"Setup expected the finding to be REMEDIATED, got {finding['state']}")
    assert finding["units_unresolved"] == 0, (
        "A complete disposition must drive units_unresolved to 0, got "
        f"{finding['units_unresolved']}")

    resp = api.verify_finding(finding["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = read_finding(finding["id"])
    assert unchanged["state"] == "REMEDIATED", (
        "A refused verification must leave the finding in REMEDIATED, got "
        f"{unchanged['state']}")
    assert unchanged["verified_at"] is None, (
        "A refused verification must not stamp verified_at, got "
        f"{unchanged['verified_at']}")
    assert read_audit(audit["id"])["state"] == "IN_REVIEW", (
        "A refused verification must not move the parent audit")


def test_auditor_verification_closes_the_finding_and_stamps_the_clock(api):
    """PRD 3.9: "The first hop stamps `verified_at` from the logical clock and moves the finding to `CLOSED`."

    Design: Corner/rbac/only_the_auditor_may_verify_a_remediated_finding
    """
    _audit, finding = _remediated_care_finding()
    moment = "2026-08-10T12:00:00Z"
    assert set_clock(moment) == moment, "The clock endpoint echoes the value it set"

    data = validate_success(api.verify_finding(finding["id"], AUDITOR), 200)
    assert data["state"] == "CLOSED", (
        f"The Auditor's verification must close the finding, got {data['state']}")
    assert_second_precision_instant(data["verified_at"], "verified_at")
    assert data["verified_at"] == moment, (
        f"verified_at must be stamped from the logical clock {moment}, got "
        f"{data['verified_at']}")


def test_verification_rolls_the_audit_up_without_touching_units_in_scope(api):
    """PRD 3.9: "`units_in_scope` sums `units_affected` over **every** finding of the audit with no state filter at all, which is what makes it invariant under disposition, verification and reopening."

    Design: Corner/rbac/only_the_auditor_may_verify_a_remediated_finding
    """
    audit, finding = _remediated_care_finding()
    validate_success(api.verify_finding(finding["id"], AUDITOR), 200)

    rolled = read_audit(audit["id"])
    assert rolled["open_finding_count"] == 0, (
        "A CLOSED finding leaves the open set, so open_finding_count must reach 0, "
        f"got {rolled['open_finding_count']}")
    assert rolled["critical_finding_count"] == 0, (
        f"Expected critical_finding_count 0, got {rolled['critical_finding_count']}")
    assert rolled["units_in_scope"] == 100, (
        "units_in_scope has no state filter and must still count the closed "
        f"finding's 100 affected units, got {rolled['units_in_scope']}")
    assert rolled["state"] == "PENDING_CLOSURE", (
        "An IN_REVIEW audit whose open-finding count reaches 0 moves to "
        f"PENDING_CLOSURE, got {rolled['state']}")


# --- approval is the LabelingApprover's exclusive write --------------------

def test_owning_brand_admin_cannot_approve_its_own_label(api):
    """PRD 3.6: "Approval is the single point at which everything this system knows is brought to bear, and only a `LabelingApprover` may perform it."

    Design: Corner/rbac/a_brand_admin_cannot_approve_a_label_spec
    """
    bundle, label = _pending_label_awaiting_fiber_evidence()
    owner_headers = make_brand_admin_headers(bundle["brand"]["id"])

    resp = api.approve_label_spec(label["id"], owner_headers)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = read_label(label["id"])
    assert unchanged["state"] == "PENDING_APPROVAL", (
        "A refused approval must leave the artifact in PENDING_APPROVAL, got "
        f"{unchanged['state']}")
    assert unchanged["approved_by_user_id"] is None, (
        "A refused approval must not stamp approved_by_user_id, got "
        f"{unchanged['approved_by_user_id']}")


def test_compliance_admin_cannot_approve_a_label_either(api):
    """PRD 2.1: "A `ComplianceAdmin` is the platform's own compliance operator. It owns the market-requirement registry, the brand registry, the logical clock and the legal pinning of an origin determination, and it may stand in for most operational roles across every brand — but it is deliberately barred from approving a label and from verifying an audit finding, so that no single role can both author compliance evidence and bless it."

    Design: Corner/rbac/a_brand_admin_cannot_approve_a_label_spec
    """
    _bundle, label = _pending_label_awaiting_fiber_evidence()

    resp = api.approve_label_spec(label["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    assert read_label(label["id"])["state"] == "PENDING_APPROVAL", (
        "The ComplianceAdmin's refused approval must leave the artifact pending")


def test_only_the_permitted_role_reaches_the_approval_ladder(api):
    """PRD 3.6: "The style's `substantiation_state` must be `FIBER_SUBSTANTIATED`, or the approval is rejected with `ERR_FIBER_NOT_SUBSTANTIATED`."

    PRD 2.7 places role authorization at rung 2 and fiber substantiation at rung 11, so the same call from the permitted role reports the content defect that the refused roles never reach.

    Design: Corner/rbac/a_brand_admin_cannot_approve_a_label_spec
    """
    bundle, label = _pending_label_awaiting_fiber_evidence()
    assert bundle["style"]["substantiation_state"] != "FIBER_SUBSTANTIATED", (
        "Setup expected a style without fiber-content evidence, got "
        f"{bundle['style']['substantiation_state']}")

    validate_error(api.approve_label_spec(label["id"],
                                          make_brand_admin_headers(bundle["brand"]["id"])),
                   ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.approve_label_spec(label["id"], APPROVER),
                   ApiErrorId.ERR_FIBER_NOT_SUBSTANTIATED, 422)

    assert read_label(label["id"])["state"] == "PENDING_APPROVAL", (
        "Neither the role refusal nor the content refusal moves the artifact")


# --- four exclusive writes attempted by the role that most wants them ------

def test_accredited_lab_cannot_issue_an_origin_determination(api):
    """PRD 3.3: "Issuing is reserved to a `ComplianceAdmin`, who supplies the `method` to pin — either `SUBSTANTIAL_TRANSFORMATION` or `YARN_FORWARD`."

    Design: Corner/rbac/an_accredited_lab_cannot_issue_a_determination_and_a_specialist_cannot_post_results
    """
    bundle = setup_label_ready_style(skip_fiber=True, skip_origin=True,
                                     skip_care=True, graph=DEFAULT_GRAPH)
    determination = draft_determination(bundle["style"]["id"])
    assert determination["state"] == "DRAFT", (
        f"Setup expected a DRAFT determination, got {determination['state']}")

    resp = api.issue_origin_determination(
        determination["id"], {"method": "SUBSTANTIAL_TRANSFORMATION"}, LAB)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = validate_success(
        api.get_origin_determination(determination["id"], ADMIN), 200)
    assert unchanged["state"] == "DRAFT", (
        "A refused issuance must leave the determination in DRAFT, got "
        f"{unchanged['state']}")
    assert unchanged["determined_country"] is None, (
        "A refused issuance must not derive determined_country, got "
        f"{unchanged['determined_country']}")
    assert unchanged["method_pinned"] is None, (
        f"A refused issuance must not pin a method, got {unchanged['method_pinned']}")


def test_labeling_specialist_cannot_post_laboratory_results(api):
    """PRD 3.4: "Only an `AccreditedLab` — or a `ComplianceAdmin` standing in for one — may reserve a bench, and only an `AccreditedLab` may post measurements."

    Design: Corner/rbac/an_accredited_lab_cannot_issue_a_determination_and_a_specialist_cannot_post_results
    """
    bundle = _bare_style()
    lab_test = reserve_care_test(bundle["style"]["id"], wash_temp_c=30)
    assert lab_test["state"] == "BENCH_RESERVED", (
        f"Setup expected a BENCH_RESERVED run, got {lab_test['state']}")

    resp = api.post_lab_test_results(lab_test["id"], care_results_payload(), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = validate_success(api.get_lab_test(lab_test["id"], ADMIN), 200)
    assert unchanged["state"] == "BENCH_RESERVED", (
        "A refused results posting must leave the run in BENCH_RESERVED, got "
        f"{unchanged['state']}")
    assert unchanged["dimensional_change_pct"] is None, (
        "A refused results posting must store no measurement, got "
        f"{unchanged['dimensional_change_pct']}")
    assert unchanged["valid_until"] is None, (
        "A refused results posting must not stamp the validity horizon, got "
        f"{unchanged['valid_until']}")


def test_brand_admin_cannot_decide_the_marking_review_of_its_own_entry(api):
    """PRD 3.8: "Only a `CustomsOfficer` decides a marking review, and only from `ENTRY_FILED`; a review of any other state is rejected with `ERR_SHIPMENT_STATE_INVALID`."

    Design: Corner/rbac/an_accredited_lab_cannot_issue_a_determination_and_a_specialist_cannot_post_results
    """
    bundle = _bare_style()
    brand_id = bundle["brand"]["id"]
    shipment = file_shipment(brand_id, bundle["style"]["id"])

    resp = api.marking_review(shipment["id"], {"outcome": "COMPLIANT"},
                              make_brand_admin_headers(brand_id))
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = validate_success(api.get_import_shipment(shipment["id"], ADMIN), 200)
    assert unchanged["marking_state"] == "ENTRY_FILED", (
        "A refused marking review must leave the entry in ENTRY_FILED, got "
        f"{unchanged['marking_state']}")
    assert unchanged["review_decided_at"] is None, (
        "A refused marking review must not stamp review_decided_at, got "
        f"{unchanged['review_decided_at']}")
    assert unchanged["penalty_assessed_usd"] == 0, (
        "A refused marking review must assess nothing, got "
        f"{unchanged['penalty_assessed_usd']}")


def test_customs_officer_cannot_file_the_entry_it_would_review(api):
    """PRD 2.1: "A `CustomsOfficer` is the border authority and the sole role that may decide a marking review; it cannot file entries, cannot file corrections and cannot touch labels."

    Design: Corner/rbac/an_accredited_lab_cannot_issue_a_determination_and_a_specialist_cannot_post_results
    """
    bundle = _bare_style()
    payload = import_shipment_payload(bundle["brand"]["id"], bundle["style"]["id"])

    resp = api.create_import_shipment(payload, CUSTOMS)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    _rows, meta = validate_paginated(api.list_import_shipments(ADMIN))
    assert meta["total_count"] == 0, (
        "A refused filing must create no customs entry, got total_count "
        f"{meta['total_count']}")


# --- segregation of duties reads the stored author id ----------------------

def test_the_author_cannot_approve_its_own_label_wearing_the_approver_role(api):
    """PRD 2.1: "The one authorization rule that reads a stored identifier is segregation of duties on label approval: the `X-User-ID` of the approving `LabelingApprover` must differ from the `authored_by_user_id` recorded on the artifact. If they are the same operator, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_author_of_a_label_cannot_approve_it_even_wearing_the_approver_role
    """
    _bundle, label = _pending_label_authored_by("user-dual-1")
    assert label["authored_by_user_id"] == "user-dual-1", (
        "Setup expected user-dual-1 to be recorded as the author, got "
        f"{label['authored_by_user_id']}")

    resp = api.approve_label_spec(label["id"],
                                  make_headers("user-dual-1", "LabelingApprover"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    unchanged = read_label(label["id"])
    assert unchanged["state"] == "PENDING_APPROVAL", (
        "A duty-segregation refusal must leave the artifact pending, got "
        f"{unchanged['state']}")
    assert unchanged["approved_by_user_id"] is None, (
        "A duty-segregation refusal must not stamp approved_by_user_id, got "
        f"{unchanged['approved_by_user_id']}")


def test_a_different_operator_in_the_same_role_approves_the_same_row(api):
    """PRD 3.6: "When every gate clears, the artifact moves from `PENDING_APPROVAL` to `APPROVED`, `approved_by_user_id` is set to the acting operator's `X-User-ID`, the style's `label_readiness` is recomputed, and the `version` of both the artifact and the style is incremented by 1."

    Design: Corner/rbac/the_author_of_a_label_cannot_approve_it_even_wearing_the_approver_role
    """
    _bundle, label = _pending_label_authored_by("user-dual-1")

    validate_error(api.approve_label_spec(
        label["id"], make_headers("user-dual-1", "LabelingApprover")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    approved = validate_success(api.approve_label_spec(
        label["id"], make_headers("user-appr-1", "LabelingApprover")), 200)
    assert approved["state"] == "APPROVED", (
        "The identical row approved by a different X-User-ID in the identical role "
        f"must reach APPROVED, got {approved['state']}")
    assert approved["approved_by_user_id"] == "user-appr-1", (
        "approved_by_user_id must record the acting approver, got "
        f"{approved['approved_by_user_id']}")


def test_a_revision_lap_does_not_launder_the_authorship_conflict(api):
    """PRD 3.5: "In both cases `content_hash` is recomputed, `authored_by_user_id` is set to the acting operator's `X-User-ID` — which re-arms the segregation-of-duties check for the next approval attempt — a hangtag additionally has its `consistency_state` recomputed against its parent, and the artifact's `version` is incremented by 1."

    Design: Corner/rbac/the_author_of_a_label_cannot_approve_it_even_wearing_the_approver_role
    """
    _bundle, label = _pending_label_authored_by("user-dual-1")
    author_specialist = make_headers("user-dual-1", "LabelingSpecialist")
    author_approver = make_headers("user-dual-1", "LabelingApprover")

    validate_error(api.approve_label_spec(label["id"], author_approver),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    sent_back = validate_success(api.request_revision_label_spec(
        label["id"], "tighten the placement wording",
        make_headers("user-appr-1", "LabelingApprover")), 200)
    assert sent_back["state"] == "REVISION_REQUESTED", (
        f"Expected REVISION_REQUESTED, got {sent_back['state']}")

    edited = validate_success(api.update_label_spec(
        label["id"], {"iron_code": "IRON_MEDIUM"}, author_specialist), 200)
    assert edited["state"] == "DRAFT", (
        f"An edited REVISION_REQUESTED artifact returns to DRAFT, got {edited['state']}")
    assert edited["authored_by_user_id"] == "user-dual-1", (
        "The edit re-stamps authorship onto the acting operator, got "
        f"{edited['authored_by_user_id']}")

    resubmitted = validate_success(
        api.submit_label_spec(label["id"], author_specialist), 200)
    assert resubmitted["state"] == "PENDING_APPROVAL", (
        f"Expected PENDING_APPROVAL after the re-submit, got {resubmitted['state']}")

    validate_error(api.approve_label_spec(label["id"], author_approver),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    approved = validate_success(api.approve_label_spec(
        label["id"], make_headers("user-appr-1", "LabelingApprover")), 200)
    assert approved["state"] == "APPROVED", (
        "The second lap is still approvable by a different operator, got "
        f"{approved['state']}")


def test_duty_segregation_is_evaluated_after_the_state_check(api):
    """PRD 2.1: "Because this check needs the loaded row, it is evaluated after existence and state checks, but it remains an authorization decision rather than a business rule."

    PRD 3.6: "The artifact must be in `PENDING_APPROVAL`; any other state is rejected with `ERR_LABEL_STATE_INVALID`."

    Design: Corner/rbac/the_author_of_a_label_cannot_approve_it_even_wearing_the_approver_role
    """
    bundle = setup_label_ready_style()
    author_specialist = make_headers("user-dual-1", "LabelingSpecialist")
    label = draft_permanent_label(bundle, headers=author_specialist)
    assert label["state"] == "DRAFT", (
        f"Setup expected an unsubmitted DRAFT, got {label['state']}")
    assert label["authored_by_user_id"] == "user-dual-1", (
        f"Setup expected user-dual-1 as author, got {label['authored_by_user_id']}")

    resp = api.approve_label_spec(label["id"],
                                  make_headers("user-dual-1", "LabelingApprover"))
    validate_error(resp, ApiErrorId.ERR_LABEL_STATE_INVALID, 409)


# --- the ComplianceAdmin standing in for the label author ------------------

def test_compliance_admin_drafts_a_label_and_is_recorded_as_its_author(api):
    """PRD 3.5: "A `LabelingSpecialist` (or a `ComplianceAdmin`) drafts a permanent label against a `style_id`, and the payload is the entire printed artifact."

    PRD 3.5: "A newly drafted permanent label lands in state `DRAFT` with `parent_label_spec_id` null, `consistency_state` at `NOT_APPLICABLE`, `approved_by_user_id`, `revision_note`, `withdrawn_reason`, `effective_from` and `effective_to` all null, and `authored_by_user_id` set to the acting operator's `X-User-ID`."

    Design: Corner/rbac/a_compliance_admin_may_author_and_submit_a_label_on_the_brands_behalf
    """
    bundle = setup_label_ready_style()

    data = validate_success(
        api.create_label_spec(label_payload_for(bundle), ADMIN), 201)
    assert data["state"] == "DRAFT", (
        f"A drafted permanent label lands in DRAFT, got {data['state']}")
    assert data["artifact_type"] == "PERMANENT_LABEL", (
        f"Drafting directly yields a PERMANENT_LABEL, got {data['artifact_type']}")
    assert data["authored_by_user_id"] == ADMIN_USER_ID, (
        "authored_by_user_id must record the acting ComplianceAdmin's X-User-ID "
        f"{ADMIN_USER_ID}, got {data['authored_by_user_id']}")
    assert data["approved_by_user_id"] is None, (
        f"A fresh draft has no approver, got {data['approved_by_user_id']}")


def test_compliance_admin_may_submit_the_label_it_authored(api):
    """PRD 3.5: "The artifact must be in `DRAFT`, and it must — if it is a permanent label — already carry both a non-null `origin_determination_id` and a non-null `care_test_id`. On success it moves from `DRAFT` to `PENDING_APPROVAL` and its `version` is incremented by 1."

    Design: Corner/rbac/a_compliance_admin_may_author_and_submit_a_label_on_the_brands_behalf
    """
    bundle = setup_label_ready_style()
    label = validate_success(
        api.create_label_spec(label_payload_for(bundle), ADMIN), 201)

    submitted = validate_success(api.submit_label_spec(label["id"], ADMIN), 200)
    assert submitted["state"] == "PENDING_APPROVAL", (
        "The ComplianceAdmin's submit must move the artifact to PENDING_APPROVAL, "
        f"got {submitted['state']}")
    assert submitted["version"] == label["version"] + 1, (
        f"Expected version {label['version'] + 1} after the submit, got "
        f"{submitted['version']}")

    approved = validate_success(api.approve_label_spec(label["id"], APPROVER), 200)
    assert approved["state"] == "APPROVED", (
        "An admin-authored artifact is approvable by a different operator, got "
        f"{approved['state']}")


def test_admin_authorship_bars_that_same_operator_from_approving(api):
    """PRD 2.1: "The one authorization rule that reads a stored identifier is segregation of duties on label approval: the `X-User-ID` of the approving `LabelingApprover` must differ from the `authored_by_user_id` recorded on the artifact. If they are the same operator, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/a_compliance_admin_may_author_and_submit_a_label_on_the_brands_behalf
    """
    bundle = setup_label_ready_style()
    label = validate_success(
        api.create_label_spec(label_payload_for(bundle), ADMIN), 201)
    validate_success(api.submit_label_spec(label["id"], ADMIN), 200)

    resp = api.approve_label_spec(
        label["id"], make_headers(ADMIN_USER_ID, "LabelingApprover"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    assert read_label(label["id"])["state"] == "PENDING_APPROVAL", (
        "The refused approval leaves the admin-authored artifact pending")


def test_compliance_admin_may_reserve_a_bench_but_not_post_the_measurement(api):
    """PRD 3.4: "Only an `AccreditedLab` — or a `ComplianceAdmin` standing in for one — may reserve a bench, and only an `AccreditedLab` may post measurements."

    Design: Corner/rbac/a_compliance_admin_may_author_and_submit_a_label_on_the_brands_behalf
    """
    bundle = _bare_style()
    reserved = validate_success(api.create_lab_test(
        care_test_payload(bundle["style"]["id"], wash_temp_c=30), ADMIN), 201)
    assert reserved["state"] == "BENCH_RESERVED", (
        "The ComplianceAdmin may stand in for the laboratory when reserving, got "
        f"{reserved['state']}")

    refused = api.post_lab_test_results(
        reserved["id"], care_results_payload(), ADMIN)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    passed = validate_success(api.post_lab_test_results(
        reserved["id"], care_results_payload(), LAB), 200)
    assert passed["state"] == "PASSED", (
        "Only the AccreditedLab writes the measurement, and this one passes, got "
        f"{passed['state']}")
