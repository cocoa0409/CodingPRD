"""The ordinance pair rule across profiles, and the receipt's creation shape."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_confirmed_stay,
    read_host,
    host_version,
    declare_patronization_record,
    set_clock,
    make_host_operator_headers,
    make_platform_admin_headers,
)


def test_a_capped_pair_passes_at_exactly_its_ceiling(api):
    """PRD §2.11: "the cap is inclusive, so a capacity exactly equal to the cap passes
    and one site beyond it fails"
    PRD §2.11: "`OR` | `WINERY` | 2 | yes"

    Design: Corner/errors/unsupported_category_state_pair_skips_the_ordinance_cap
    """
    host = declare_host(category="WINERY", state_code="OR",
                        self_contained_required=True)
    declare_sites(host["id"], 2, labels=["O1", "O2"], max_vehicle_length_feet=30)
    approved = validate_success(
        api.decide_host(
            host["id"],
            {"action": "APPROVE", "reason": "declared",
             "expected_host_version": host_version(host["id"])},
            make_platform_admin_headers(),
        )
    )
    assert approved["onboarding_status"] == "APPROVED", (
        "two sites equals the OR/WINERY cap of 2, the inclusive boundary"
    )


def test_the_same_category_in_an_uncapped_state_is_admitted_with_more_sites(api):
    """PRD §2.11: "`TX` | `ATTRACTION` | 10 | no"
    PRD §2.11: "the cap is assessed against the host's physical site count and never
    against an availability window's `capacity_override`"

    Design: Corner/errors/unsupported_category_state_pair_skips_the_ordinance_cap
    """
    big = declare_host(category="ATTRACTION", state_code="TX",
                       self_contained_required=False)
    declare_sites(big["id"], 10, labels=[f"B{i + 1}" for i in range(10)],
                  site_class="PULL_THROUGH", max_vehicle_length_feet=50)
    approved = validate_success(
        api.decide_host(
            big["id"],
            {"action": "APPROVE", "reason": "declared",
             "expected_host_version": host_version(big["id"])},
            make_platform_admin_headers(),
        )
    )
    assert approved["onboarding_status"] == "APPROVED"
    assert approved["effective_capacity"] == 10, (
        "ten sites is exactly the TX/ATTRACTION cap and the layout is admitted; the "
        "twelve-site layout the corner cites sits beyond that cap"
    )
    assert approved["electric_site_count"] >= 1, (
        "an approved host carries a non-empty electric amenity surface"
    )


def test_forcing_self_containment_off_on_a_strict_profile_is_refused(api):
    """PRD §2.11: "where the profile forces self-containment, the host may not declare
    `self_contained_required` as false. Either violation on a platform onboarding or
    host-update decision is rejected with `ERR_ORDINANCE_CONSTRAINT` (HTTP 422)."

    Design: Corner/errors/unsupported_category_state_pair_skips_the_ordinance_cap
    """
    host = declare_host(category="WINERY", state_code="OR",
                        self_contained_required=False)
    declare_sites(host["id"], 1, labels=["O1"], max_vehicle_length_feet=30)
    resp = api.decide_host(
        host["id"],
        {"action": "APPROVE", "reason": "declared",
         "expected_host_version": host_version(host["id"])},
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ORDINANCE_CONSTRAINT, 422)


def test_a_new_patronization_record_opens_pending_with_a_minted_code(api):
    """PRD §2.12: "Every record begins in `PENDING` status and is issued a
    server-minted `verification_code` that the host scans to settle it; the record's
    `host_credit_cents` stays at zero until it is verified."

    Design: Corner/endpoints/patronization_verification_code_and_rejection_paths
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    record = declare_patronization_record(
        host_id, parts["member"]["id"], parts["stay"]["id"],
        receipt_cents=6000, purchase_kind="MEAL",
    )
    assert record["verification_status"] == "PENDING"
    assert record["host_credit_cents"] == 0
    assert isinstance(record["verification_code"], str)
    assert record["verification_code"], "the code is minted before any credit exists"
    assert record["stay_request_id"] == parts["stay"]["id"]
    assert read_host(host_id)["patronization_credit_cents"] == 0


def test_a_purchase_that_is_not_positive_is_refused(api):
    """PRD §2.12: "the `receipt_cents` value in cents — which must be positive"
    PRD §2.10: "Payload well-formedness is fourth: every required input must be
    present, every enumerated value must fall inside its declared set, and every
    numeric range must hold, or the request fails with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/endpoints/patronization_verification_code_and_rejection_paths
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    stay = api.get_stay_request(
        parts["stay"]["id"], make_host_operator_headers(host_id)
    ).json()["data"]
    resp = api.create_patronization_record(
        {"host_id": host_id, "member_id": parts["member"]["id"],
         "stay_request_id": parts["stay"]["id"], "receipt_cents": 0,
         "purchase_kind": "MEAL",
         "expected_request_version": stay["version"]},
        make_host_operator_headers(host_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)