"""Corner queue: cross_cutting_layers — optimistic concurrency on the two
version-guarded loan writes (modification create, settlement apply)."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    apply_settlement_payload,
    list_receivable_data,
    list_tranche_data,
    loan_version,
    modification_request_payload,
    read_loan,
    report_settlement,
    setup_active_loan,
    validate_error,
    validate_success,
)


def test_occ_modification_create_stale_version(api):
    """PRD §2.7: "`POST /disaster-relief/loans/{id}/modification-requests` — creating a modification request against a loan requires the request body field `expected_loan_version`, carrying the `version` of the loan the client last observed."
    PRD §2.7: "In both cases the field is non-optional. If the presented value does not equal the loan's current `version` — because another writer has advanced the loan since the client last read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting loan state it has not observed."
    PRD §3.8: "Creating it bumps the loan's `version` by 1, and if a predecessor request on the same loan is still `SUBMITTED` the newer create supersedes it: the predecessor is moved to `DENIED` automatically, with no deciding officer recorded."

    Design: Corner/cross_cutting_layers/occ_modification_create_stale_version
    """
    ctx = setup_active_loan()
    loan_id = ctx["loan"]["id"]
    v_obs = ctx["loan"]["version"]

    # First create with the observed version succeeds and bumps the loan.
    resp = api.create_modification_request(
        loan_id,
        modification_request_payload(26000000, v_obs, reason="first"),
        ctx["applicant_headers"])
    m1 = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_modification_request"])
    assert m1["status"] == "SUBMITTED"

    # Second create still carrying the now-stale version is rejected.
    resp = api.create_modification_request(
        loan_id,
        modification_request_payload(28000000, v_obs, reason="stale second"),
        ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    rows = validate_success(
        api.list_modification_requests(loan_id, ctx["approver_headers"]),
        EXPECTED_SUCCESS_STATUS["list_modification_requests"])
    assert [row["id"] for row in rows] == [m1["id"]]
    # The rejected write changed nothing: exactly one version bump total.
    assert read_loan(ctx)["version"] == v_obs + 1


def test_occ_settlement_apply_stale_version(api):
    """PRD §2.7: "`POST /disaster-relief/insurance-settlements/{id}/apply` — applying an insurance settlement requires the request body field `expected_loan_version`, again carrying the client's last observed loan `version`."
    PRD §2.7: "In both cases the field is non-optional. If the presented value does not equal the loan's current `version` — because another writer has advanced the loan since the client last read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting loan state it has not observed."
    PRD §3.8: "Third, the new commitment is the smaller of `approved_amount_cents` and the new net loss, and the loan's `commitment_amount_cents` is set to it."

    Design: Corner/cross_cutting_layers/occ_settlement_apply_stale_version
    """
    ctx = setup_active_loan()  # approved 20000000, nothing released
    loan_id = ctx["loan"]["id"]
    s1 = report_settlement(ctx, 1000000,
                           received_date="2026-11-10T00:00:00Z")
    s2 = report_settlement(ctx, 500000,
                           received_date="2026-11-12T00:00:00Z")
    v_obs = loan_version(ctx)

    # S1 applies with the observed version: total insurance 5000000
    # (verification) + 1000000 = 6000000; new net = 25000000 - 6000000 =
    # 19000000; commitment = min(20000000, 19000000) = 19000000.
    resp = api.apply_insurance_settlement(
        s1["id"], apply_settlement_payload(v_obs), ctx["servicing_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["apply_insurance_settlement"])
    loan = read_loan(ctx)
    assert loan["commitment_amount_cents"] == 19000000
    # Nothing released: the waterfall's target is 19000000 - 0 = 19000000,
    # so stage 3 (the first descending tranche whose cancellation would drop
    # the un-released sum below target) is reduced by the 1000000 clawback;
    # excess is zero, so no receivable is generated.
    assert [t["amount_cents"] for t in list_tranche_data(ctx)] == [
        2500000, 8750000, 7750000]
    assert list_receivable_data(ctx) == []

    # S2 with the same stale version is rejected and stays REPORTED.
    resp = api.apply_insurance_settlement(
        s2["id"], apply_settlement_payload(v_obs), ctx["servicing_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows = validate_success(
        api.list_insurance_settlements(loan_id, ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_insurance_settlements"])
    s2_row = [row for row in rows if row["id"] == s2["id"]][0]
    assert s2_row["status"] == "REPORTED"
    assert read_loan(ctx)["commitment_amount_cents"] == 19000000
