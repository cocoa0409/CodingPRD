"""Entity creation defaults, not-found behavior, validation basics, and RBAC."""
from test_helpers import (
    ADMIN,
    CS,
    FO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_supplier,
    create_customer,
    create_property,
    create_supplier,
    get_success_data,
    make_customer_headers,
    reset_clock,
    setup_accepted_booking,
    open_complaint,
    validate_error,
    validate_paginated,
    validate_success,
    create_rate_window,
    build_user_headers,
)


class TestSupplierCreation:
    def test_supplier_create_returns_declared_defaults(self):
        """PRD §2.5: "Each supplier is onboarded with a
        `parity_protection_enabled` flag (defaulting to `true` when omitted)
        recording its participation in this protection."
        PRD §3.1: "A new supplier begins in `ACTIVE` status and may later move
        `ACTIVE → SUSPENDED → ACTIVE` or `ACTIVE → TERMINATED` (the latter also
        permitted directly from `SUSPENDED`)."

        Design: Corner/entities/supplier_create_returns_declared_defaults_and_version_one
        """
        reset_clock()
        resp = api_client.create_supplier(
            {
                "legal_name": "Beacon Lodging Group",
                "opaque_commission_pct": 0.15,
                "concealment_discount_min_pct": 0.12,
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_supplier(data)
        assert data["parity_protection_enabled"] is True
        assert data["status"] == "ACTIVE"
        assert isinstance(data["version"], int)


class TestNotFound:
    def test_customer_get_unknown_id_returns_customer_not_found(self):
        """PRD §2.8: "Existence of path identifiers, validated strictly
        left-to-right along the URL; the first nonexistent identifier yields
        its resource-specific not-found error (for example
        `ERR_SUPPLIER_NOT_FOUND`, `ERR_OPAQUE_BID_NOT_FOUND`,
        `ERR_SETTLEMENT_BATCH_NOT_FOUND`)."

        Design: Corner/entities/customer_get_unknown_id_returns_customer_not_found
        """
        reset_clock()
        resp = api_client.get_customer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


class TestPropertyValidation:
    def test_star_rating_out_of_range_rejected(self):
        """PRD §3.1: "Each property records its `supplier_id`, the publicly
        recognizable `brand_name` (which the opaque channel never reveals
        pre-purchase), an integer `star_rating` from 1 to 5 inclusive, the
        `neighborhood_code` locating the property within a disclosure zone, the
        `amenity_codes` the property could disclose, and the
        `published_rate_cents` — the public retail nightly rate in cents
        against which every opaque discount is measured."

        Design: Corner/entities/property_create_with_star_rating_out_of_range_returns_invalid_request
        """
        reset_clock()
        supplier = create_supplier()
        for bad_rating in (0, 6):
            resp = api_client.create_property(
                {
                    "supplier_id": supplier["id"],
                    "brand_name": f"P{bad_rating}",
                    "star_rating": bad_rating,
                    "neighborhood_code": "NB19",
                    "amenity_codes": [],
                    "published_rate_cents": 10000,
                },
                ADMIN,
            )
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api_client.list_properties(ADMIN, params={"supplier_id": supplier["id"]})
        )
        assert rows == [], f"no property may be created with an out-of-range star_rating, got {rows}"


class TestRateWindowListing:
    def test_list_filters_by_property_and_status_with_pagination(self):
        """PRD §2.3: "List endpoints accept two query parameters. `limit` is
        the maximum number of items to return; when omitted it defaults to 10,
        and it must be at least 1 and at most 100. `offset` is the number of
        items to skip from the beginning of the sorted result set; it defaults
        to 0. Unless otherwise specified, every list endpoint returns resources
        sorted by `created_at` in ascending order. The `meta` object of every
        list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/rate_windows_list_filters_by_property_and_status_with_pagination
        """
        reset_clock()
        supplier = create_supplier()
        prop = create_property(supplier["id"], neighborhood_code="NB17")
        w1 = create_rate_window(prop["id"])
        create_rate_window(
            prop["id"],
            check_in_date="2026-10-06T00:00:00Z",
            check_out_date="2026-10-10T00:00:00Z",
        )
        create_rate_window(
            prop["id"],
            check_in_date="2026-10-11T00:00:00Z",
            check_out_date="2026-10-15T00:00:00Z",
        )
        # Close one window so two remain OPEN.
        get_success_data(api_client.close_rate_window(
            w1["id"], {"expected_rate_window_version": w1["version"]}, ADMIN
        ))

        rows, meta = validate_paginated(api_client.list_rate_windows(
            ADMIN, params={"property_id": prop["id"], "status": "OPEN", "limit": 1, "offset": 0}
        ))
        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        rows, meta = validate_paginated(api_client.list_rate_windows(
            ADMIN, params={"property_id": prop["id"], "status": "OPEN", "limit": 1, "offset": 1}
        ))
        assert len(rows) == 1
        assert meta["has_more"] is False

        rows, meta = validate_paginated(api_client.list_rate_windows(
            ADMIN, params={"property_id": prop["id"]}
        ))
        assert len(rows) == 3
        assert meta["total_count"] == 3


class TestBidBodyForeignKeys:
    def test_unknown_customer_id_on_bid_create_returns_customer_not_found(self):
        """PRD §2.8: "Existence of foreign keys supplied in the request body,
        validated in the endpoint's input declaration order (for example, the
        `supplier_id` on a new property, the `property_id` on a new rate
        window, the `booking_id` on a new complaint case), each yielding the
        corresponding not-found error such as `ERR_PROPERTY_NOT_FOUND`,
        `ERR_RATE_WINDOW_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, or
        `ERR_BOOKING_NOT_FOUND`."

        Design: Corner/entities/opaque_bid_body_fk_customer_checked_before_neighborhood_zone
        """
        reset_clock()
        resp = api_client.create_opaque_bid(
            {
                "customer_id": NON_EXISTENT_UUID,
                "neighborhood_code": "NOSUCH",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-04T00:00:00Z",
                "offer_mode": "FIXED",
            },
            make_customer_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


class TestAuthAndRbac:
    def test_missing_auth_header_returns_400_before_any_other_check(self):
        """PRD §2.1: "Every request carries two mandatory HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
        capacity in which they act. A request missing either header, or
        carrying a malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any
        other check runs."

        Design: Corner/validations/missing_auth_header_returns_400_before_any_other_check
        """
        reset_clock()
        resp = api_client.get_supplier(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_customer_cannot_create_supplier(self):
        """PRD §2.1: "An authenticated caller whose role is not on the
        authorized list for the operation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.1: "A `PlatformAdmin` registers each participating supplier with
        its corporate `legal_name`, the `opaque_commission_pct` the platform
        retains on opaque remittance, the `concealment_discount_min_pct`
        defining the minimum discount fraction below the property's published
        reference rate that the supplier requires for any opaque fill, and
        optionally `parity_protection_enabled`."

        Design: Corner/roles/customer_cannot_create_supplier
        """
        reset_clock()
        customer = create_customer()
        resp = api_client.create_supplier(
            {
                "legal_name": "Rogue",
                "opaque_commission_pct": 0.15,
                "concealment_discount_min_pct": 0.10,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_finance_ops_cannot_resolve_complaint(self):
        """PRD §2.1: "An authenticated caller whose role is not on the
        authorized list for the operation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.5: "A `CustomerService` operator then works the case through
        `OPEN → UNDER_REVIEW` via a start-review action, and from
        `UNDER_REVIEW` either to `RESOLVED` or to `REJECTED`."

        Design: Corner/roles/finance_ops_cannot_resolve_complaint
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB36")
        case = open_complaint(customer, booking, category="OTHER", description="x")
        get_success_data(api_client.start_review_complaint_case(case["id"], CS))

        resp = api_client.resolve_complaint_case(
            case["id"],
            {"resolution": "GOODWILL_CREDIT", "goodwill_credit_cents": 1000},
            FO,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        refreshed = get_success_data(api_client.get_complaint_case(case["id"], ADMIN))
        assert refreshed["status"] == "UNDER_REVIEW"


class TestRateWindowDateRange:
    def test_rate_window_create_with_equal_dates_returns_invalid_date_range(self):
        """PRD §3.1: "The same date-range discipline applies here as
        everywhere: the window's `check_out_date` must be strictly after its
        `check_in_date`, and a violation is rejected with
        `ERR_INVALID_DATE_RANGE` (HTTP 400)."

        Design: Corner/errors/err_invalid_date_range_on_rate_window_create
        """
        reset_clock()
        supplier = create_supplier()
        prop = create_property(supplier["id"], neighborhood_code="NB35")
        resp = api_client.create_rate_window(
            {
                "property_id": prop["id"],
                "check_in_date": "2026-10-01T00:00:00Z",
                "check_out_date": "2026-10-01T00:00:00Z",
                "opaque_rate_cents": 15000,
                "rooms_allocated": 5,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
