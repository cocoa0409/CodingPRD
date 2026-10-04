"""Certificates: publication lifecycle, supersede, withdrawal, OCC, RBAC."""
from test_helpers import (
    ApiErrorId, assert_certificate, create_draft_certificate, get_lot,
    make_certification_officer_headers, make_inventory_manager_headers,
    make_metrologist_headers, publish_certificate, setup_value_assignment_lot,
    validate_error, validate_paginated, validate_success, withdraw_certificate,
)


def test_certificate_expiration_computed_from_validity_days(api):
    """PRD §3.4: "Publishing stamps `published_at` with the current logical
    clock, sets `expiration_date` to `published_at` plus `validity_days` days,
    and records the acting officer as `publisher_user_id`."
    PRD §2.4: "Before any explicit adjustment, the logical clock starts at
    exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time."

    Design: Corner/entities/certificate_expiration_computed_from_validity_days
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C5")
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-C5",
                                    validity_days=30)
    published = publish_certificate(cert["id"], officer_id="co-2")
    assert_certificate(published)
    assert published["published_at"] == "2026-09-01T00:00:00Z"
    assert published["expiration_date"] == "2026-10-01T00:00:00Z"
    assert published["publisher_user_id"] == "co-2"


def test_certificate_terminal_lockdown_rejected(api):
    """PRD §3.4: "only from `DRAFT`, with any other certificate state answered
    by `ERR_INVALID_CERTIFICATE_STATE`" and "Both `SUPERSEDED` and `WITHDRAWN`
    are terminal for the certificate."

    Design: Corner/state_machines/certificate_terminal_lockdown_rejected
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C11")
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-C11")
    publish_certificate(cert["id"])
    withdrawn = withdraw_certificate(cert["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    resp = api.transition_certificate(cert["id"], {"to": "PUBLISHED"},
                                      make_certification_officer_headers("co-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATE_STATE)


def test_certificate_supersede_on_republication(api):
    """PRD §3.4: "Any previously `PUBLISHED` certificate for the same lot is
    automatically moved to `SUPERSEDED`, and the new certificate's
    `supersedes_certificate_id` points at it, so at most one certificate per lot
    is ever `PUBLISHED`."

    Design: Corner/state_machines/certificate_supersede_on_republication
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C12")
    lot_id = ctx["lot"]["id"]
    cert_a = publish_certificate(
        create_draft_certificate(lot_id, certificate_code="CERT-C12A")["id"])
    cert_b = create_draft_certificate(lot_id, certificate_code="CERT-C12B",
                                      value_assignment_variant="UNWEIGHTED_MEAN",
                                      validity_days=60)
    published_b = publish_certificate(cert_b["id"])
    assert published_b["status"] == "PUBLISHED"
    assert published_b["supersedes_certificate_id"] == cert_a["id"]
    certs, _meta = validate_paginated(
        api.list_lot_certificates(lot_id, make_certification_officer_headers("co-1")))
    by_code = {c["certificate_code"]: c["status"] for c in certs}
    assert by_code["CERT-C12A"] == "SUPERSEDED"
    assert by_code["CERT-C12B"] == "PUBLISHED"


def test_metrologist_cannot_publish_certificate(api):
    """PRD §2.1: "a request whose role is not among them — or whose role is not
    permitted for the specific transition target named in a transition request —
    is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/metrologist_cannot_publish_certificate
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C42")
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-C42")
    resp = api.transition_certificate(cert["id"], {"to": "PUBLISHED"},
                                      make_metrologist_headers("met-9"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_publish_by_method_analyst_violates_segregation_rejected(api):
    """PRD §3.4: "Publication is the institutional act of record, performed by a
    `CertificationOfficer` who is not the analyst of any `ACCEPTED` method on the
    lot — a publisher who is draws `ERR_SEGREGATION_OF_DUTIES_VIOLATION`".

    Design: Corner/rbac/publish_by_method_analyst_violates_segregation_rejected
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C45")
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-C45")
    resp = api.transition_certificate(cert["id"], {"to": "PUBLISHED"},
                                      make_certification_officer_headers("met-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)


def test_enter_distribution_without_published_certificate_rejected(api):
    """PRD §3.5: "An `InventoryManager` moves a `CERTIFIED` lot into
    `IN_DISTRIBUTION` only behind a certificate that is `PUBLISHED` and whose
    `expiration_date` lies strictly after the current logical clock; without one
    the transition is refused with `ERR_NO_PUBLISHED_CERTIFICATE`".

    Design: Corner/validations/enter_distribution_without_published_certificate_rejected
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C34")
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-C34")
    publish_certificate(cert["id"])
    withdraw_certificate(cert["id"])
    resp = api.transition_material_lot(ctx["lot"]["id"], {"to": "IN_DISTRIBUTION"},
                                       make_inventory_manager_headers())
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_CERTIFICATE)


def test_occ_stale_lot_version_certificate_create_rejected(api):
    """PRD §2.7: "Certificate creation must carry `expected_lot_version`, the
    client-side copy of the lot's `version`; a mismatch with the lot's current
    `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/complexity_layers/occ_stale_lot_version_certificate_create_rejected
    """
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-C49")
    lot_id = ctx["lot"]["id"]
    stale_version = 1  # creation version; the homogeneity transition advanced it
    assert get_lot(lot_id)["version"] == stale_version + 1
    payload = {
        "lot_id": lot_id, "certificate_code": "CERT-C49",
        "value_assignment_variant": "WEIGHTED_MEAN", "uncertainty_components": [],
        "validity_days": 30, "expected_lot_version": stale_version,
    }
    resp = api.create_certificate(payload, make_certification_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
