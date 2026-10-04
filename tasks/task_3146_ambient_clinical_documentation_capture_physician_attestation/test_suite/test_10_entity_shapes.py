"""Entity shape corners: creation defaults, required fields, enum and
system-field rejection, not-found, attestation append-only shape, and
note-field seeding at draft creation.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_draft,
    ready_world,
    world_with_attested_draft,
)
from test_helpers.test_users import ADMIN


class TestPatientCreationDefaultsAndEnvelope:
    def test_defaults_applied_and_envelope_shape(self, client):
        """PRD 3.1: "A patient registration supplies the medical record
        number `mrn` (unique across all patients), the `full_name`, and an
        optional `default_ambient_opt_in` boolean (default true) that records
        the patient's standing preference about ambient recording."
        PRD 2.4: "`version` is an integer that starts at its initial value
        at creation and increments by exactly 1 on every mutation of the
        resource"
        PRD 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/entities/corner_patient_creation_defaults_and_envelope
        """
        resp = client.create_patient(
            {"mrn": "MRN-EN1-1", "full_name": "Pat En1"}, headers=ADMIN
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        data = body["data"]
        assert data["default_ambient_opt_in"] is True
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestPhysicianMissingRequiredNpi:
    def test_missing_npi_returns_400(self, client):
        """PRD 3.1: "A physician registration supplies the National Provider
        Identifier `npi` (unique), the `full_name`, and a `specialty_code`
        such as CARD, FM, or ORTHO, which drives template selection and QA
        routing."

        Design: Corner/entities/corner_physician_creation_missing_required_npi_returns_400
        """
        resp = client.create_physician(
            {"full_name": "No Npi", "specialty_code": "CARD"}, headers=ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestTemplateFieldSpecEnumRejected:
    def test_importance_outside_enum_rejected(self, client):
        """PRD 3.1: "A note template registration supplies the
        `specialty_code` it serves, a human-readable `template_version` label
        (unique together with the specialty code), and `field_specs` — an
        ordered array of objects, each with a `key`, an `importance` of
        `CRITICAL`, `MAJOR`, or `MINOR`, and a `required` flag."

        Design: Corner/entities/corner_template_field_spec_enum_rejected
        """
        resp = client.create_note_template(
            {
                "specialty_code": "CARD",
                "template_version": "bad1",
                "field_specs": [
                    {"key": "chief_complaint", "importance": "HUGE", "required": True}
                ],
            },
            headers=ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestPatientUnknownFieldInputRejected:
    def test_client_supplied_id_rejected(self, client):
        """PRD 2.4: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/corner_patient_unknown_field_input_rejected
        """
        resp = client.create_patient(
            {
                "mrn": "MRN-EN4-1",
                "full_name": "Pat En4",
                "id": "00000000-0000-0000-0000-000000000000",
            },
            headers=ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestEncounterGetNotFound:
    def test_get_missing_encounter_returns_404(self, client):
        """PRD 2.8: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first path identifier that does not resolve to an existing
        resource; deeper identifiers are not examined once an earlier one
        fails."

        Design: Corner/entities/corner_encounter_get_not_found_returns_404
        """
        resp = client.get_encounter(NON_EXISTENT_UUID, headers=ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestAttestationAppendOnlyImmutability:
    def test_attestation_row_shape_and_content(self, client):
        """PRD 2.4: "One resource is deliberately exempt from the full set:
        an `Attestation` is an append-only legal-record entry and carries
        only `id` and `created_at`."
        PRD 3.5: "its `attestation_type` is `INITIAL` when the draft's
        `amendment_count` is zero and `AMENDMENT` for every re-attestation
        after an amend cycle"

        Design: Corner/entities/corner_attestation_append_only_immutability
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        rows, _meta = validate_paginated(
            client.list_draft_attestations(
                world["draft"]["id"], headers=world["physician_headers"]
            )
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["attestation_type"] == "INITIAL"
        assert row["completeness_at_attestation"] == 100
        assert is_valid_uuid(row["id"])
        assert is_iso8601_timestamp(row["created_at"])
        assert "version" not in row, "append-only row carries no version"
        assert "updated_at" not in row, "append-only row carries no updated_at"


class TestNoteFieldsSeededFromTemplate:
    def test_fields_seeded_one_per_spec(self, client):
        """PRD 3.4: "then seeds one `NoteField` row per entry in the
        template's `field_specs`: each field's `field_key` and `importance`
        and `required` flag are copied from the spec, its `field_value`
        starts null, its `source` starts `SYSTEM`, and `validated` starts
        false."
        PRD 3.4: "If any missing field is `CRITICAL`, the result is capped
        at 49 no matter how small the arithmetic penalty."

        Design: Corner/entities/corner_notefields_seeded_from_template_at_draft_creation
        """
        world = ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("ros", "MINOR", False),
            ],
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        fields, _meta = validate_paginated(
            client.list_note_fields(draft["id"], headers=world["physician_headers"])
        )
        assert len(fields) == 2, "one NoteField row per field_spec"
        by_key = {row["field_key"]: row for row in fields}
        assert by_key["chief_complaint"]["importance"] == "CRITICAL"
        assert by_key["chief_complaint"]["required"] is True
        assert by_key["ros"]["importance"] == "MINOR"
        assert by_key["ros"]["required"] is False
        for row in fields:
            assert row["field_value"] is None
            assert row["source"] == "SYSTEM"
            assert row["validated"] is False
        assert draft["completeness_score"] == 49, (
            "only the required CRITICAL field is missing: raw 75 capped at 49"
        )
