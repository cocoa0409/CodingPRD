"""Document ingestion and publication rules: creation defaults, stored fields,
citation normalization, and the publish payload's constraint gauntlet
(PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_document,
    create_document,
    create_published_document,
    document_payload,
    get_document,
    publish_document,
    reference_entry,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_document_creation_defaults_and_system_fields(api, content_ingester_headers):
    """PRD §3.1: "The new PrimaryDocument is born into a two-dimensional state: its
    `ingestion_status` starts at `RECEIVED` and its `visibility_status` starts at
    `PUBLIC`."
    PRD §3.1: "While the document remains `RECEIVED`, its `normalized_citation` is
    null and its `published_at` is null; the derived citator fields `citator_score`
    and `citator_signal` begin with no qualifying references, so the score reads 0."

    Design: Corner/entities/document_creation_defaults_and_system_fields
    """
    resp = api.create_document(
        document_payload(
            source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
            title="Fresh v. Start", raw_citation_string="1 F.4th 1", decision_date="2026-01-05",
        ),
        content_ingester_headers,
    )
    data = validate_success(resp, 201)
    assert_document(data)
    assert data["ingestion_status"] == "RECEIVED"
    assert data["visibility_status"] == "PUBLIC"
    assert data["citator_signal"] == "GREEN"
    assert data["citator_score"] == 0
    assert data["normalized_citation"] is None
    assert data["published_at"] is None
    assert data["version"] == 1


def test_document_get_returns_stored_fields(api, content_ingester_headers):
    """PRD §3.1: "Reading a single document returns it together with its derived
    citator fields — unless its `visibility_status` is `REMOVED`, in which case the
    read fails with `ERR_DOCUMENT_REMOVED` (HTTP 404) exactly as if the document did
    not exist, and the citing-reference lookup on such a document fails the same
    way."

    Design: Corner/entities/document_get_returns_stored_fields
    """
    created = validate_success(api.create_document(
        document_payload(
            source_type="AGENCY", jurisdiction_code="US", document_type="REGULATION",
            title="Stored Fields Rule", raw_citation_string="88 Fed. Reg. 55",
            decision_date="2026-02-01",
        ),
        content_ingester_headers,
    ), 201)
    data = validate_success(api.get_document(created["id"], content_ingester_headers))
    assert data["title"] == "Stored Fields Rule"
    assert data["raw_citation_string"] == "88 Fed. Reg. 55"
    assert data["decision_date"] == "2026-02-01"
    assert data["source_type"] == "AGENCY"
    assert data["jurisdiction_code"] == "US"


def test_normalized_citation_computed_at_publish(api, content_ingester_headers):
    """PRD §3.1: "Before the transition commits, the publishing document's
    `raw_citation_string` is normalized: leading and trailing whitespace is trimmed,
    the text is uppercased (ASCII), every period character is removed, and every run
    of internal whitespace is collapsed to a single space — so a raw string like
    "123 F.3d  456" emerges as "123 F3D 456"."
    PRD §2.4: "At server startup the clock reads exactly `2026-09-01T00:00:00Z`, and
    it never falls back to wall-clock time."

    Design: Corner/entities/normalized_citation_computed_at_publish
    """
    doc = create_document(
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="Norm v. Cite", raw_citation_string="123 F.3d  456", decision_date="2026-01-15",
    )
    assert doc["normalized_citation"] is None
    published = publish_document(doc["id"], references=[])
    assert published["ingestion_status"] == "PUBLISHED"
    assert published["normalized_citation"] == "123 F3D 456"
    assert published["published_at"].startswith("2026-09-01T00:00:00"), (
        f"published_at must be stamped from the logical clock (startup default "
        f"2026-09-01T00:00:00Z), got {published['published_at']}"
    )


def test_publish_published_document_rejected(api, content_ingester_headers):
    """PRD §3.1: "Publishing a document that is already `PUBLISHED` fails the
    transition's from-state requirement with `ERR_INVALID_STATE` (HTTP 409), and
    per §2.9 the duplicate-citation check fires before the self-citation check,
    which fires before the target-publication check."

    Design: Corner/state_machines/publish_published_document_rejected
    """
    doc_b = create_published_document(
        title="Twice v. Publish B", raw_citation_string="20 F.4th 10", jurisdiction_code="CA9",
    )
    doc_a = create_published_document(
        title="Twice v. Publish A", raw_citation_string="21 F.4th 11", jurisdiction_code="CA9",
        references=[reference_entry(doc_b["id"], "FOLLOWED", "MENTIONED")],
    )
    resp = api.publish_document(doc_a["id"], {"references": []}, content_ingester_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    refs, meta = validate_paginated(
        api.list_citing_references(doc_a["id"], content_ingester_headers, params={"direction": "FROM"})
    )
    assert meta["total_count"] == 1, (
        f"failed publish must create no additional references, got {meta['total_count']}"
    )


def test_duplicate_normalized_citation_rejected(api, content_ingester_headers):
    """PRD §3.1: "That canonical form is stored as `normalized_citation` and must be
    globally unique among all documents that have one; a collision is rejected with
    `ERR_DUPLICATE_CITATION` (HTTP 409)."

    Design: Corner/validations/duplicate_normalized_citation_rejected
    """
    create_published_document(
        title="First v. Dup", raw_citation_string="123 F.3d 456", jurisdiction_code="CA9",
        decision_date="2026-01-01",
    )
    d2 = create_document(
        title="Second v. Dup", raw_citation_string="123 F3d 456", jurisdiction_code="CA9",
        decision_date="2026-02-01",
    )
    resp = api.publish_document(d2["id"], {"references": []}, content_ingester_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CITATION, 409)
    d2_after = get_document(d2["id"])
    assert d2_after["ingestion_status"] == "RECEIVED"
    assert d2_after["normalized_citation"] is None


def test_self_citation_rejected(api, content_ingester_headers):
    """PRD §3.1: "An entry that points back at the publishing document itself is
    rejected with `ERR_SELF_CITATION` (HTTP 422)."

    Design: Corner/validations/self_citation_rejected
    """
    doc_a = create_document(
        title="Self v. Cite", raw_citation_string="70 F.4th 1", jurisdiction_code="CA9",
    )
    resp = api.publish_document(
        doc_a["id"],
        {"references": [reference_entry(doc_a["id"], "FOLLOWED", "CITED")]},
        content_ingester_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SELF_CITATION, 422)
    _, meta = validate_paginated(
        api.list_citing_references(doc_a["id"], content_ingester_headers, params={"direction": "FROM"})
    )
    assert meta["total_count"] == 0


def test_citation_target_not_published_rejected(api, content_ingester_headers):
    """PRD §3.1: "An entry whose target has not yet reached `PUBLISHED` ingestion
    status is rejected with `ERR_CITATION_TARGET_NOT_PUBLISHED` (HTTP 409)."

    Design: Corner/validations/citation_target_not_published_rejected
    """
    doc_b = create_document(
        title="B v. Unpub", raw_citation_string="71 F.4th 2", jurisdiction_code="CA9",
        decision_date="2026-01-01",
    )
    doc_a = create_document(
        title="A v. Early", raw_citation_string="72 F.4th 3", jurisdiction_code="CA9",
        decision_date="2026-02-01",
    )
    resp = api.publish_document(
        doc_a["id"],
        {"references": [reference_entry(doc_b["id"], "FOLLOWED", "CITED")]},
        content_ingester_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CITATION_TARGET_NOT_PUBLISHED, 409)
    assert get_document(doc_a["id"])["ingestion_status"] == "RECEIVED"
