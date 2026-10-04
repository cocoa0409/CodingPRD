"""Cross-cutting corners: optimistic concurrency, best-effort bulk ingest, the
fixed clock default, and segment size reconciliation at submission."""

from test_helpers import (
    account_with_contract,
    create_approved_segment,
    create_segment,
    get_success_data,
    ingest_category_households,
    make_data_steward_headers,
    read_contract,
    submit_segment,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]


def test_occ_stale_contract_version_on_amend(api):
    """A second amend replaying the pre-amend version is rejected; the allowance stays at fifteen.

    PRD: "If the value does not match the contract's current `version` — because another amendment, suspension, or termination has advanced it since the client last read the contract — the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
    PRD: "Every successful amendment increments the contract's `version` by one."
    Design: Corner/cross_cutting_layers/occ_stale_contract_version_on_amend
    """
    world = account_with_contract(api, name="OCC Co")
    contract = world["contract"]
    original_version = contract["version"]
    amended = get_success_data(api.amend_contract(
        contract["id"],
        factories.amend_payload(original_version, credit_allowance_delta=5),
        ADMIN,
    ))
    assert amended["version"] == original_version + 1
    assert amended["report_credit_allowance"] == 15
    resp = api.amend_contract(
        contract["id"],
        factories.amend_payload(original_version, credit_allowance_delta=5),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.STALE_CONTRACT_VERSION.value, 412)
    observed = read_contract(api, contract["id"])
    assert observed["report_credit_allowance"] == 15


def test_occ_stale_segment_version_on_activation(api):
    """A second activation replaying the approved-time version is rejected.

    PRD: "Creating a segment activation requires `expected_segment_version`, carrying the client's last observed `version` of the target `AudienceSegment`. A mismatch with the segment's current `version` is rejected with `ERR_STALE_SEGMENT_VERSION` (HTTP 412)"
    PRD: "the segment's `version` increments by one because the activation pins it."
    Design: Corner/cross_cutting_layers/occ_stale_segment_version_on_activation
    """
    world = account_with_contract(api, name="OCC2 Co", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 25, "v")
    segment = create_approved_segment(api, world["contract"]["id"], world["analyst_headers"], segment_name="OCC Seg")
    approved_version = segment["version"]
    first = get_success_data(api.create_activation(
        segment["id"],
        factories.activation_payload(approved_version, channels=["COUPON"]),
        world["analyst_headers"],
    ))
    assert first["total_fee_cents"] == 50
    resp = api.create_activation(
        segment["id"],
        factories.activation_payload(approved_version, channels=["COUPON"]),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.STALE_SEGMENT_VERSION.value, 412)


def test_bulk_ingest_partial_rejection(api):
    """Two valid households persist while the malformed third is reported per-item.

    PRD: "the ingest is best-effort: every valid household is persisted — the panel is append-only — and every invalid item is reported back per-item."
    PRD: "The response carries the `ingested_count` and a `rejected` array describing the items that failed validation."
    Design: Corner/cross_cutting_layers/bulk_ingest_partial_rejection
    """
    resp = api.ingest_households(
        [
            factories.household_payload("ok1"),
            factories.household_payload("ok2", category_codes=["DAIRY"]),
            {"recency_days": 5},
        ],
        ADMIN,
    )
    data = get_success_data(resp)
    assert data["ingested_count"] == 2
    rejected = data["rejected"]
    assert len(rejected) == 1
    assert rejected[0]["error_id"] == "ERR_INVALID_REQUEST"
    # The rejected entry references the malformed third item (index 2).
    assert rejected[0].get("index") == 2


def test_clock_default_is_fixed_start(api):
    """With no clock call, a grant whose window ended at 2026-09-01T00:00:00Z is already expired.

    PRD: "At startup, before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`."
    PRD: "the logical clock must be before `valid_until` (a submission at or after the window's end flips the grant to `EXPIRED` and fails with `ERR_GRANT_EXPIRED`)"
    Design: Corner/cross_cutting_layers/clock_default_is_fixed_start
    """
    world = account_with_contract(api, name="Clock Co")
    grant = get_success_data(api.create_grant(
        factories.grant_payload(
            world["account"]["id"],
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2026-09-01T00:00:00Z",
        ),
        world["analyst_headers"],
    ))
    get_success_data(api.approve_grant(grant["id"], make_data_steward_headers("steward-14")))
    resp = api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=1000),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.GRANT_EXPIRED.value, 409)


def test_segment_size_reconciled_at_submit(api):
    """Size three at create becomes five at submit once two more households land.

    PRD: "The segment's `size` is the count of panel households that satisfy every supplied criterion, computed against the full panel at creation and recomputed at every submission."
    Design: Corner/cross_cutting_layers/segment_size_reconciled_at_submit
    """
    world = account_with_contract(api, name="Recon Co", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 3, "n")
    segment = create_segment(api, world["contract"]["id"], world["analyst_headers"], segment_name="Recon")
    assert segment["size"] == 3
    ingest_category_households(api, 2, "n-extra")
    submitted = submit_segment(api, segment["id"], world["analyst_headers"])
    assert submitted["size"] == 5
    assert submitted["status"] == "PENDING_APPROVAL"
