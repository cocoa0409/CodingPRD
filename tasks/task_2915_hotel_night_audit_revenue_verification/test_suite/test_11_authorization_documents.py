"""Approval paperwork: closed inclusive coverage intervals and their overlap scope.

Covers PRD section 3.2 (filing, reviewing and revoking approval paperwork), whose
coverage intervals are closed at both ends — deliberately unlike the half-open
settlement shift windows of PRD section 3.5.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_row_count, single
from test_helpers.test_users import AUDITOR, FRONT_DESK, REVENUE_MANAGER


def _comp_stay_with_active_paperwork_for_the_first_three_days(api):
    """A three-night comp stay covered by an ACTIVE COMP_ROOM waiver over 08-01 to 08-03."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-IVL1",
        guest_name="Yun Kade",
        room_number="1301",
        nights_count=3,
        contracted_rate_amount=200.00,
        rate_plan_code="COMP",
        market_segment="COMP",
        is_comp=True,
        scheduled_checkout_at="2026-08-04T11:00:00.000Z",
    )
    document = fx.create_authorization_document(
        api,
        prop["id"],
        FRONT_DESK,
        doc_type="COMP_ROOM",
        folio_id=folio["id"],
        document_reference="COMP-A",
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-03",
    )
    active = fx.review_document(api, document["id"], "APPROVE", REVENUE_MANAGER)
    return prop, bd, folio, active


def test_paperwork_that_merely_touches_the_previous_interval_overlaps(api):
    """Both endpoints are inclusive, so a document starting on the day the last one ends collides.

    PRD section 3.2 forbids a second document with the same `folio_id` and `doc_type`,
    whose status is PENDING or ACTIVE, from occupying an overlapping interval — and because
    both endpoints are inclusive, two documents that merely touch do overlap, so filing is
    rejected with ERR_AUTHORIZATION_INTERVAL_OVERLAP (HTTP 409). Starting one day later
    clears the existing interval and is accepted, answering 201.

    Design: Difficulty/resource_temporal_overlap/authorization_document_closed_interval_rejects_touching_endpoints
    """
    prop, _bd, folio, _active = _comp_stay_with_active_paperwork_for_the_first_three_days(api)

    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                doc_type="COMP_ROOM",
                folio_id=folio["id"],
                document_reference="COMP-B",
                valid_from_date="2026-08-03",
                valid_to_date="2026-08-05",
            ),
            FRONT_DESK,
        ),
        E.ERR_AUTHORIZATION_INTERVAL_OVERLAP,
    )
    assert_row_count(
        validate_success(
            api.list_authorization_documents(AUDITOR, folio_id=folio["id"], doc_type="COMP_ROOM")
        ),
        1,
        "COMP_ROOM documents",
    )

    accepted = validate_success(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                doc_type="COMP_ROOM",
                folio_id=folio["id"],
                document_reference="COMP-C",
                valid_from_date="2026-08-04",
                valid_to_date="2026-08-06",
            ),
            FRONT_DESK,
        ),
        201,
    )
    assert_fields(accepted, {"status": "PENDING"})
    assert_row_count(
        validate_success(
            api.list_authorization_documents(AUDITOR, folio_id=folio["id"], doc_type="COMP_ROOM")
        ),
        2,
        "COMP_ROOM documents",
    )


def test_overlap_is_scoped_to_the_document_type_and_binds_while_still_pending(api):
    """A different type may reuse the interval; an unreviewed one of the same type still blocks it.

    PRD section 3.2 scopes the overlap test to the pair of `folio_id` and `doc_type`, so a
    RATE_OVERRIDE — which additionally requires `authorized_rate_amount` — may occupy exactly
    the COMP_ROOM interval. Yet the test admits PENDING as well as ACTIVE documents, so that
    unreviewed RATE_OVERRIDE blocks a second one that touches it, and a malformed interval whose
    `valid_from_date` follows its `valid_to_date` is rejected with ERR_SHIFT_WINDOW_INVALID
    (HTTP 422).

    Design: Difficulty/resource_temporal_overlap/authorization_document_closed_interval_rejects_touching_endpoints
    """
    prop, _bd, folio, _active = _comp_stay_with_active_paperwork_for_the_first_three_days(api)

    override = validate_success(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                doc_type="RATE_OVERRIDE",
                folio_id=folio["id"],
                authorized_rate_amount=200.00,
                document_reference="RO-A",
                valid_from_date="2026-08-01",
                valid_to_date="2026-08-03",
            ),
            FRONT_DESK,
        ),
        201,
    )
    assert_fields(override, {"status": "PENDING", "doc_type": "RATE_OVERRIDE"})

    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                doc_type="RATE_OVERRIDE",
                folio_id=folio["id"],
                authorized_rate_amount=200.00,
                document_reference="RO-B",
                valid_from_date="2026-08-03",
                valid_to_date="2026-08-04",
            ),
            FRONT_DESK,
        ),
        E.ERR_AUTHORIZATION_INTERVAL_OVERLAP,
    )

    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                doc_type="RATE_OVERRIDE",
                folio_id=folio["id"],
                authorized_rate_amount=200.00,
                document_reference="RO-C",
                valid_from_date="2026-08-09",
                valid_to_date="2026-08-08",
            ),
            FRONT_DESK,
        ),
        E.ERR_SHIFT_WINDOW_INVALID,
    )

    remaining = validate_success(
        api.list_authorization_documents(AUDITOR, folio_id=folio["id"], doc_type="RATE_OVERRIDE")
    )
    assert_row_count(remaining, 1, "RATE_OVERRIDE documents")
    assert_fields(single(remaining), {"document_reference": "RO-A"})
