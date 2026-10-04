"""The cancellation cascade and existing-stocks sell-through: hop-by-hop
tolerance/use-site/application/state-registration effects, commodity-matched
amendment auto-rejection, vacatur restore, and the disposal windows and
quantity ceiling (PRD §3.8).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    apply_state_registration,
    assert_disposal_total,
    assert_iso_instant_equal,
    create_registered_product,
    create_tolerance,
    file_method_change_amendment,
    file_new_use_amendment,
    get_amendment,
    get_product,
    get_product_version,
    get_proceeding,
    get_state_registration,
    grant_state_registration,
    hold_hearing,
    initiate_proceeding,
    issue_cancellation_order,
    list_product_tolerances,
    list_product_use_sites,
    make_disposal_payload,
    make_use_site_object,
    record_disposal,
    set_clock,
    setup_cancelled_product,
    vacate_proceeding,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
REVIEWER_B = TEST_USERS["reviewer_2_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]


def _cancel_at(product_id, when, authorized_units=500):
    """Initiate + hear a CANCELLATION, advance the clock, issue the order."""
    proceeding = initiate_proceeding(product_id, "CANCELLATION", "RISK_FINDING",
                                     REVIEWER)
    hold_hearing(proceeding["id"], REVIEWER)
    set_clock(when)
    return issue_cancellation_order(proceeding["id"], issuer_headers=REVIEWER_B,
                                    authorized_units=authorized_units,
                                    stocks_method="FIXED")


def test_cancellation_order_tolerance_revocation_amendment_auto_rejection(api):
    """PRD §3.8: "Hop 3, caused by hop 2's tolerance revocations: every
    `SUBMITTED` amendment of type `NEW_USE` whose payload `commodity_code` equals
    the commodity code of a tolerance just revoked in hop 2 is auto-rejected with
    `decided_at` stamped; all other pending amendments are left untouched."
    PRD §3.8: "every tolerance of the product in `PROPOSED` or `ESTABLISHED`
    becomes `REVOKED`, with `pre_revocation_status` capturing the prior status and
    `revoked_at` stamped"

    Design: Difficulty/transitive_cascade/cancellation_order_tolerance_revocation_amendment_auto_rejection
    """
    ctx = create_registered_product(use_pattern="FOOD_USE")
    product_id = ctx["product"]["id"]
    tolerance_id = ctx["tolerance"]["id"]
    site_id = ctx["use_sites"][0]["id"]

    pv1 = get_product_version(product_id)
    am_new = file_new_use_amendment(
        product_id, registrant_headers=REGISTRANT,
        use_site=make_use_site_object(site_code="CORN", pest_code="CORN_BORER",
                                      max_application_rate_lbs_acre=1.5,
                                      max_applications_per_season=1,
                                      preharvest_interval_days=14),
        commodity_code="CORN", tolerance_ppm=0.1, expected_product_version=pv1)
    am_meth = file_method_change_amendment(
        product_id, site_id, new_method="CHEMIGATION", registrant_headers=REGISTRANT,
        expected_product_version=get_product_version(product_id))
    sreg = apply_state_registration(product_id, "CA", REGISTRANT)
    grant_state_registration(sreg["id"], agency_headers=STATE_AGENCY)

    proceeding = _cancel_at(product_id, "2027-03-01T00:00:00Z")

    # Hop 1: the product falls.
    assert get_product(product_id)["status"] == "CANCELLED"
    assert proceeding["pre_effective_product_status"] == "REGISTERED"

    # Hop 2: tolerance revoked with the marker, use site removed, state
    # registration revoked.
    tol = [t for t in list_product_tolerances(product_id)
           if t["id"] == tolerance_id][0]
    assert tol["status"] == "REVOKED"
    assert tol["pre_revocation_status"] == "ESTABLISHED"
    assert_iso_instant_equal(tol["revoked_at"], "2027-03-01T00:00:00Z",
                             "tolerance.revoked_at")
    site = list_product_use_sites(product_id)[0]
    assert site["status"] == "REMOVED"
    assert get_state_registration(sreg["id"])["status"] == "REVOKED"

    # Hop 3: only the commodity-matched NEW_USE amendment is auto-rejected.
    am_new_after = get_amendment(am_new["id"])
    assert am_new_after["status"] == "REJECTED"
    assert_iso_instant_equal(am_new_after["decided_at"], "2027-03-01T00:00:00Z",
                             "amendment.decided_at")
    assert get_amendment(am_meth["id"])["status"] == "SUBMITTED"


def test_cancellation_then_vacatur_restores_label_universe(api):
    """PRD §3.8: "Vacating an `EFFECTIVE` cancellation performs the documented
    restore, and it is the sole documented exception to the terminality of
    `CANCELLED`: the product returns to the proceeding's
    `pre_effective_product_status`"
    PRD §3.8: "every tolerance whose `pre_revocation_status` is non-null and whose
    `revoked_at` equals the vacated proceeding's `effective_at` returns to its
    `pre_revocation_status`, whether that prior status was `PROPOSED` or
    `ESTABLISHED`, and the marker is cleared"
    PRD §3.8: "Three documented asymmetries are deliberately not restored: state
    registrations stay `REVOKED` or `DENIED`, withdrawn applications stay
    `WITHDRAWN`, and cascade-rejected amendments stay `REJECTED`."

    Design: Difficulty/compensating_invariant/cancellation_then_vacatur_restores_label_universe
    """
    ctx = create_registered_product(use_pattern="FOOD_USE")
    product_id = ctx["product"]["id"]
    tol_corn_id = ctx["tolerance"]["id"]  # ESTABLISHED by the approval cascade
    tol_wheat = create_tolerance(product_id, REGISTRANT, commodity_code="WHEAT",
                                 tolerance_ppm=0.1)  # stays PROPOSED
    site_id = ctx["use_sites"][0]["id"]
    sreg = apply_state_registration(product_id, "CA", REGISTRANT)
    grant_state_registration(sreg["id"], agency_headers=STATE_AGENCY)

    proceeding = _cancel_at(product_id, "2027-03-01T00:00:00Z")

    # Forward action: the whole label universe mutates.
    assert get_product(product_id)["status"] == "CANCELLED"
    tolerances = {t["id"]: t for t in list_product_tolerances(product_id)}
    assert tolerances[tol_corn_id]["status"] == "REVOKED"
    assert tolerances[tol_wheat["id"]]["status"] == "REVOKED"
    assert list_product_use_sites(product_id)[0]["status"] == "REMOVED"
    assert get_state_registration(sreg["id"])["status"] == "REVOKED"

    vacate_proceeding(proceeding["id"], reviewer_headers=REVIEWER,
                      vacatur_reason="court remand: order vacated in full")

    # Compensating action: the conserved multiset returns exactly.
    assert get_proceeding(proceeding["id"])["status"] == "VACATED"
    assert get_product(product_id)["status"] == "REGISTERED"
    tolerances = {t["id"]: t for t in list_product_tolerances(product_id)}
    corn = tolerances[tol_corn_id]
    wheat = tolerances[tol_wheat["id"]]
    assert corn["status"] == "ESTABLISHED", "each tolerance restores its own prior status"
    assert wheat["status"] == "PROPOSED"
    assert corn["pre_revocation_status"] is None
    assert wheat["pre_revocation_status"] is None
    site = [s for s in list_product_use_sites(product_id) if s["id"] == site_id][0]
    assert site["status"] == "ACTIVE"
    assert site["pre_removal_status"] is None

    # Documented asymmetry: the state registration is not restored.
    assert get_state_registration(sreg["id"])["status"] == "REVOKED"


def test_existing_stocks_disposed_total_aggregates(api):
    """PRD §3.8: "The running total `existing_stocks_disposed_units` — the sum of
    `units` over the append-only `existing_stocks_disposals` records, zero when
    the array is empty"
    PRD §3.8: "Each accepted record appends `{disposed_at, units, method}` to
    `existing_stocks_disposals` with `disposed_at` stamped from the clock, and the
    total is recomputed."

    Design: Corner/calculations/existing_stocks_disposed_total_aggregates
    """
    ctx = create_registered_product()
    proceeding = _cancel_at(ctx["product"]["id"], "2027-03-01T00:00:00Z",
                            authorized_units=500)
    set_clock("2027-04-01T00:00:00Z")

    record_disposal(proceeding["id"], 200, "DESTRUCTION", REVIEWER)
    after = record_disposal(proceeding["id"], 150, "SALE", REVIEWER)

    assert after["existing_stocks_disposed_units"] == 350
    assert_disposal_total(after)
    records = after["existing_stocks_disposals"]
    assert len(records) == 2, "append-only log keeps both records in order"
    assert_iso_instant_equal(records[0]["disposed_at"], "2027-04-01T00:00:00Z",
                             "disposed_at")
    assert (records[0]["units"], records[0]["method"]) == (200, "DESTRUCTION")
    assert (records[1]["units"], records[1]["method"]) == (150, "SALE")
    # Remaining capacity: 500 authorized - 350 disposed = 150 units.
    assert 500 - after["existing_stocks_disposed_units"] == 150


def test_sale_after_sale_window_but_within_use_window_split(api):
    """PRD §3.8: "`SALE` and `RETURN` disposals are accepted only while the clock
    is at or before `allow_sale_until`; every method is accepted only while the
    clock is at or before `allow_use_until`; a disposal outside its window fails
    `ERR_EXISTING_STOCKS_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/sale_after_sale_window_but_within_use_window_split
    """
    ctx = create_registered_product()
    proceeding = _cancel_at(ctx["product"]["id"], "2027-03-01T00:00:00Z",
                            authorized_units=500)
    # FIXED: allow_sale_until 2028-02-29, allow_use_until 2029-02-28.
    set_clock("2028-06-01T00:00:00Z")

    resp = api_client.record_disposal(
        proceeding["id"], make_disposal_payload(25, "SALE"), REVIEWER)
    validate_error(resp, ApiErrorId.ERR_EXISTING_STOCKS_WINDOW_CLOSED)

    after = record_disposal(proceeding["id"], 25, "DESTRUCTION", REVIEWER)
    assert after["existing_stocks_disposed_units"] == 25


def test_disposal_of_exactly_remaining_quantity_succeeds_then_next_unit_fails(api):
    """PRD §3.8: "The running total `existing_stocks_disposed_units` — the sum of
    `units` over the append-only `existing_stocks_disposals` records, zero when
    the array is empty — may never exceed `existing_stocks_authorized_units`, and
    a record that would push it past the ceiling fails
    `ERR_EXISTING_STOCKS_QUANTITY_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/disposal_of_exactly_remaining_quantity_succeeds_then_next_unit_fails
    """
    ctx = create_registered_product()
    proceeding = _cancel_at(ctx["product"]["id"], "2027-03-01T00:00:00Z",
                            authorized_units=500)
    set_clock("2027-04-01T00:00:00Z")

    record_disposal(proceeding["id"], 300, "DESTRUCTION", REVIEWER)
    after = record_disposal(proceeding["id"], 200, "SALE", REVIEWER)
    # Equality with the authorized quantity is allowed.
    assert after["existing_stocks_disposed_units"] == 500
    assert after["existing_stocks_disposed_units"] == after[
        "existing_stocks_authorized_units"]

    resp = api_client.record_disposal(
        proceeding["id"], make_disposal_payload(1, "DESTRUCTION"), REVIEWER)
    validate_error(resp, ApiErrorId.ERR_EXISTING_STOCKS_QUANTITY_EXCEEDED)
    assert get_proceeding(proceeding["id"])["existing_stocks_disposed_units"] == 500
