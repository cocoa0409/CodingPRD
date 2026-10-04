"""Role and segregation corners: role-exclusive denials and entity-backed
ownership checks.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_patient,
    create_physician,
    create_qa_auditor,
    edit_draft,
    grant_consent,
    ready_world,
    submit_review,
)
from test_helpers.test_users import (
    COMPLIANCE,
    make_patient_headers,
    make_physician_headers,
    make_qa_auditor_headers,
)


class TestQaAuditorCannotAttest:
    def test_attest_as_auditor_returns_403(self, client):
        """PRD 3.5: "Attestation is the moment the note enters the legal
        record, and it is gated by five preconditions, evaluated under the
        ordering of §2.9: the caller must be the draft's author"
        PRD 2.1: "A request whose role is authenticated but is not permitted
        for the target endpoint — or which fails an entity-backed ownership
        check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_qa_auditor_cannot_attest_returns_403
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        qa_a = create_qa_auditor(client, employee_code="QA-A-1", specialty_codes=["CARD"])
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        submit_review(client, draft, world["physician"])
        resp = client.attest_draft(
            draft["id"], headers=make_qa_auditor_headers(qa_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestComplianceOfficerCannotEditNote:
    def test_patch_as_compliance_returns_403(self, client):
        """PRD 3.4: "Only the author may work a draft."
        PRD 2.1: "A request whose role is authenticated but is not permitted
        for the target endpoint — or which fails an entity-backed ownership
        check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_compliance_officer_cannot_edit_note_returns_403
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        resp = client.patch_note_draft(
            draft["id"],
            f.patch_note_draft_payload(
                draft["version"], [f.field_update("chief_complaint", "compliance edit")]
            ),
            headers=COMPLIANCE,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestNonAuthorPhysicianAttest:
    def test_other_physician_cannot_attest(self, client):
        """PRD 3.5: "the caller must be the draft's author"
        PRD 2.1: "When `X-User-Role` is `Physician`, `X-User-ID` is the `id`
        of the acting `Physician`; ownership checks on any resource that
        references a `Physician` (for example, an `Encounter`'s
        `physician_id` or a `NoteDraft`'s `author_physician_id`) compare the
        resource's foreign-key field to `X-User-ID`."

        Design: Corner/rbac/corner_non_author_physician_attest_returns_403
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        physician = world["physician"]
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        edit_draft(client, draft, physician, [f.field_update("chief_complaint", "fever")])
        submit_review(client, draft, physician)
        other = create_physician(client, npi="NPI-OTHER-1")
        resp = client.attest_draft(
            draft["id"], headers=make_physician_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestPatientCannotOptOutOtherPatientsConsent:
    def test_opt_out_wrong_patient_returns_403(self, client):
        """PRD 3.2: "A patient opts out of their own consent at any time —
        `X-User-ID` must match the consent's `patient_id`"
        PRD 2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of
        the acting `Patient`; ownership checks on any resource that
        references a `Patient` (for example, an `AmbientConsent`'s
        `patient_id`) compare the resource's foreign-key field to
        `X-User-ID`."

        Design: Corner/rbac/corner_patient_cannot_opt_out_other_patient_consent_returns_403
        """
        patient_a = create_patient(client, mrn="MRN-RB4-A", full_name="Pat A")
        patient_b = create_patient(client, mrn="MRN-RB4-B", full_name="Pat B")
        physician = create_physician(client)
        encounter = create_encounter(client, patient_a, physician)
        consent = grant_consent(client, encounter, patient_a, captured_via="VERBAL")
        resp = client.opt_out_consent(
            consent["id"],
            {"reason": "not my consent"},
            headers=make_patient_headers(patient_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
