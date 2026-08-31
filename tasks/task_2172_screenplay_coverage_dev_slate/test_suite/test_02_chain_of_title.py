"""Underlying material, filed chain-of-title documents and the rights ladder."""

from test_helpers import (
    ApiErrorId,
    assert_envelope_meta,
    assert_literary_property,
    assert_rights_chain_document,
    create_property,
    fetch_property,
    file_document,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    BA_APPROVER,
    EDITOR_ASSIGN,
)


def test_create_literary_property_returns_derived_defaults(api):
    """PRD 3.1: "A freshly registered property starts with `rights_chain_status` of
    `UNVERIFIED`, `verified_document_count` of 0, `tracking_tier` of `NONE`, and
    `encumbrance_count` of 0."
    PRD 2.4: "Most resources additionally carry `updated_at`, in the same ISO 8601
    UTC format with three fractional digits, and `version`, an integer that begins at
    1 when the row is created and increments by exactly 1 on every mutation of that
    row — including mutations the row suffers as a side effect of an operation aimed
    at some other resource."

    Design: Corner/entities/create_literary_property_returns_derived_defaults
    """
    resp = api.create_literary_property(
        {
            "title": "First Light",
            "material_type": "ORIGINAL_PITCH",
            "source_author_name": "A. Okafor",
            "genre": "DOCUMENTARY",
            "logline": "A pitch with nothing behind it yet.",
        },
        EDITOR_ASSIGN,
    )
    data = validate_success(resp, 201)
    assert_literary_property(data)
    assert_envelope_meta(resp.json(), "object")

    assert data["rights_chain_status"] == "UNVERIFIED"
    assert data["verified_document_count"] == 0
    assert data["tracking_tier"] == "NONE"
    assert data["encumbrance_count"] == 0
    assert data["version"] == 1


def test_get_literary_property_unknown_id_returns_not_found(api):
    """PRD 2.6: "Every resource id embedded in the URL is resolved left to right, and
    the first unresolvable segment decides the error: `ERR_PROPERTY_NOT_FOUND`,
    `ERR_SUBMISSION_NOT_FOUND`, `ERR_RELEASE_FORM_NOT_FOUND`, `ERR_READER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_BOARD_ENTRY_NOT_FOUND`,
    `ERR_OPTION_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_WRITER_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND` or `ERR_DOCUMENT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/get_literary_property_unknown_id_returns_not_found
    """
    resp = api.get_literary_property(
        "00000000-0000-4000-8000-000000000001", EDITOR_ASSIGN
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)
    assert resp.json()["response_type"] == "error"


def test_rights_chain_document_is_append_only(api):
    """PRD 2.4: "Two resource types are append-only records rather than mutable state
    and therefore carry only `id` and `created_at`: chain-of-title documents and
    committee ballots. Neither exposes `updated_at` and neither exposes `version`; do
    not emit those fields for them."
    PRD 3.1: "Among the live documents, the verified ones are those whose `verified`
    flag is true; `verified_document_count` is simply how many there are."

    Design: Corner/entities/rights_chain_document_is_immutable_no_version_no_update_endpoint
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(
        genre="DOCUMENTARY", title="Append Only", material_type="BOOK"
    )
    document = file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)

    resp = api.get_rights_chain_document(document["id"], BA_APPROVER)
    data = validate_success(resp, 200)
    assert_rights_chain_document(data)

    assert "updated_at" not in data, "a chain-of-title document has no updated_at"
    assert "version" not in data, "a chain-of-title document has no version"
    assert data["superseded"] is False

    stored_property = fetch_property(prop["id"])
    assert stored_property["rights_chain_status"] == "PARTIAL"
    assert stored_property["verified_document_count"] == 1


def test_rights_document_supersede_marks_predecessor_and_excludes_it(api):
    """PRD 3.1: "When a document is filed naming a predecessor, the predecessor's
    `superseded` flag is set to true; a document's own `superseded` flag is true
    exactly when some other document carries `supersedes_document_id` equal to that
    document's `id`, and it starts false."
    PRD 3.1: "The derivation considers only *live* documents — those whose
    `superseded` flag is false; a superseded document is invisible to every part of
    this calculation, both to the dispute scan and to the verified counts."

    Design: Corner/entities/rights_document_self_referential_supersede_marks_predecessor
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Replacement Papers", material_type="PLAY")
    original = file_document(
        prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True, notes="Original."
    )

    resp = api.file_rights_document(
        prop["id"],
        {
            "doc_type": "CHAIN_OF_TITLE",
            "executed_on": "2026-04-01",
            "verified": True,
            "supersedes_document_id": original["id"],
            "notes": "Corrected chain.",
        },
        BA_APPROVER,
    )
    replacement = validate_success(resp, 201)

    assert validate_success(
        api.get_rights_chain_document(original["id"], BA_APPROVER)
    )["superseded"] is True
    assert replacement["superseded"] is False
    assert replacement["supersedes_document_id"] == original["id"]

    stored_property = fetch_property(prop["id"])
    assert stored_property["verified_document_count"] == 1, (
        "the superseded original is invisible to the verified count"
    )
    assert stored_property["rights_chain_status"] == "PARTIAL"

    rows, meta = validate_paginated(
        api.list_rights_chain_documents(
            BA_APPROVER, {"supersedes_document_id": original["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == replacement["id"]


def test_rights_chain_clear_requires_both_types_and_three_verified_documents(api):
    """PRD 3.1: "Otherwise, if the verified document types include both
    `CHAIN_OF_TITLE` and `COPYRIGHT_CERT`, and the verified document count is at least
    three, the property is `CLEAR`."
    PRD 3.1: "Otherwise, if at least one live document is verified, the property is
    `PARTIAL`."

    Design: Corner/calculations/rights_chain_clear_requires_both_types_and_three_verified_docs
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="HORROR", title="Almost Clear", material_type="BOOK")
    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)
    file_document(prop["id"], "COPYRIGHT_CERT", "2026-01-16", True)
    file_document(prop["id"], "CLEARANCE_OPINION", "2026-01-17", False)

    before = fetch_property(prop["id"])
    assert before["verified_document_count"] == 2
    assert before["rights_chain_status"] == "PARTIAL", (
        "two verified documents fall one short of the CLEAR floor"
    )

    fourth = validate_success(
        api.file_rights_document(
            prop["id"],
            {"doc_type": "WGA_REGISTRATION", "executed_on": "2026-01-18", "verified": True},
            BA_APPROVER,
        ),
        201,
    )

    after = fetch_property(prop["id"])
    assert after["verified_document_count"] == 3
    assert after["rights_chain_status"] == "CLEAR"
    assert fourth["superseded"] is False

    _, meta = validate_paginated(
        api.list_property_rights_documents(prop["id"], BA_APPROVER)
    )
    assert meta["total_count"] == 4
