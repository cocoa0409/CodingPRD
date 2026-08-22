"""Show close-out and lead capture: the single MOVE_OUT transition that shuts a
delivered drayage shipment and an active lead-capture licence at once, badge
deduplication across and within batches against the included-lead threshold, and
the batch that arrives once the licence has already closed."""
from test_helpers import (
    ApiErrorId,
    LEAD,
    TEST_USERS,
    advance_show,
    assert_drayage_shipment,
    assert_lead_capture_license,
    get_shipment,
    ingest_leads,
    make_exhibitor_headers,
    move_crate,
    provision_license,
    receive_shipment,
    register_crate,
    setup_active_license,
    setup_show_ground,
    validate_error,
    validate_paginated,
)

OPS = TEST_USERS["show_operations_headers"]

# The licence every scenario below provisions: two scanners, three bundled leads,
# so the third badge sits exactly on the included-lead boundary.
LICENSE_TERMS = {"device_count": 2, "included_leads": 3}
FIRST_BATCH = ("B1", "B2", "B3")
SECOND_BATCH = ("B3", "B4", "B4")


def _sole_licence_on_booth(api, booth_id):
    """Re-read the booth's one licence through its reverse-reachability listing."""
    rows, _meta = validate_paginated(
        api.list_booth_lead_capture_licenses(booth_id, OPS))
    assert len(rows) == 1, \
        f"Expected exactly one licence listed under the booth, got {len(rows)}"
    assert_lead_capture_license(rows[0])
    return rows[0]


def _on_site_show_with_delivered_freight_and_active_licence():
    """A show at ON_SITE whose single DIRECT_TO_SHOW crate stands on the floor, so
    its shipment has bubbled up to DELIVERED_TO_BOOTH, carrying alongside it a
    two-device licence that has already accepted its first three badges."""
    ground = setup_show_ground(show_status="OPEN_FOR_ORDERS", with_warehouse=True)
    crate = register_crate(ground["exhibitor"]["id"])
    ground["crate"] = crate
    ground["shipment"] = receive_shipment(
        ground["show"]["id"], ground["exhibitor"]["id"], [crate["id"]],
        warehouse_id=ground["warehouse"]["id"],
        channel="DIRECT_TO_SHOW",
        declared_value_coverage=False)
    for status in ("ADVANCE_CLOSED", "MOVE_IN", "ON_SITE"):
        advance_show(ground["show"]["id"], status)
    move_crate(crate["id"], "ON_SHOW_FLOOR")
    licence = provision_license(ground["booth"]["id"], ground["exhibitor"]["id"],
                                **LICENSE_TERMS)
    ground["license"] = ingest_leads(licence["id"], ground["exhibitor"]["id"],
                                     FIRST_BATCH)
    return ground


class TestMoveOutClosesTheShowsFreightAndLicences:
    """One ON_SITE -> MOVE_OUT edge terminates two different child collections."""

    def test_move_out_closes_both_the_delivered_shipment_and_the_active_licence(self, api):
        """PRD §3.1: "`ON_SITE → MOVE_OUT` is the first transition that cascades."
        PRD §3.1: "Every drayage shipment on this show sitting in `DELIVERED_TO_BOOTH` moves to `CLOSED`, and as each shipment closes its `hold_flag` is forced to false and every booth of that shipment's exhibitor on that show recomputes its posture — which is how a freight hold lifts automatically at tear-down."
        PRD §3.1: "In the same transition, every lead-capture licence on a booth of this show whose `status` is `ACTIVE` moves to `CLOSED` and its `license_total_cents` is frozen at the figure it then holds."
        PRD §3.6: "`CLOSED`, the terminal status, is reached only as a cascade when the show advances into `MOVE_OUT`, and closing forces `hold_flag` to false and recomputes the posture of every booth of that exhibitor on that show."

        Design: Corner/state_machines/show_move_out_closes_delivered_shipment_and_active_license
        """
        ground = _on_site_show_with_delivered_freight_and_active_licence()

        before = get_shipment(ground["shipment"]["id"])
        assert before["status"] == "DELIVERED_TO_BOOTH", \
            ("Precondition: the direct-to-show crate on the floor puts its shipment "
             f"in DELIVERED_TO_BOOTH, got {before['status']}")
        assert ground["license"]["status"] == "ACTIVE", \
            ("Precondition: the first accepted batch made the licence ACTIVE, got "
             f"{ground['license']['status']}")

        advance_show(ground["show"]["id"], "MOVE_OUT")

        shipment = get_shipment(ground["shipment"]["id"])
        assert_drayage_shipment(shipment)
        assert shipment["status"] == "CLOSED", \
            ("MOVE_OUT closes every DELIVERED_TO_BOOTH shipment on the show, got "
             f"{shipment['status']}")
        assert shipment["hold_flag"] is False, \
            ("Closing a shipment forces hold_flag to false, got "
             f"{shipment['hold_flag']}")

        licence = _sole_licence_on_booth(api, ground["booth"]["id"])
        assert licence["status"] == "CLOSED", \
            ("The same MOVE_OUT edge closes every ACTIVE lead-capture licence on a "
             f"booth of this show, got {licence['status']}")
        assert licence["license_total_cents"] == 65000, \
            ("The closed licence keeps the 65000 cents it held at closure, got "
             f"{licence['license_total_cents']}")

    def test_move_out_freezes_the_closed_licence_total_at_the_figure_it_then_held(self, api):
        """PRD §3.1: "In the same transition, every lead-capture licence on a booth of this show whose `status` is `ACTIVE` moves to `CLOSED` and its `license_total_cents` is frozen at the figure it then holds."
        PRD §3.8: "When the show advances into `MOVE_OUT`, an `ACTIVE` licence moves to the terminal `CLOSED` and its `license_total_cents` is frozen at the figure it then holds; a licence still in `PROVISIONED` at that point remains `PROVISIONED` and only closes on the later `MOVE_OUT → CLOSED` show edge."

        Design: Corner/state_machines/show_move_out_closes_delivered_shipment_and_active_license
        """
        ground = _on_site_show_with_delivered_freight_and_active_licence()

        active = ground["license"]
        assert active["status"] == "ACTIVE", \
            f"Precondition: the licence stands ACTIVE, got {active['status']}"
        assert active["license_total_cents"] == 65000, \
            ("Precondition: three badges against three included leads leave the "
             f"licence at 65000 cents, got {active['license_total_cents']}")

        advance_show(ground["show"]["id"], "MOVE_OUT")

        licence = _sole_licence_on_booth(api, ground["booth"]["id"])
        assert licence["status"] == "CLOSED", \
            f"MOVE_OUT drives the ACTIVE licence to terminal CLOSED, got {licence['status']}"
        assert licence["license_total_cents"] == active["license_total_cents"], \
            ("license_total_cents is frozen at the figure held when the show moved "
             f"out, expected {active['license_total_cents']}, got "
             f"{licence['license_total_cents']}")
        assert licence["license_total_cents"] == 65000, \
            f"The frozen figure is 65000 cents, got {licence['license_total_cents']}"
        assert licence["leads_ingested_count"] == 3, \
            ("Closure records no further badges, expected 3, got "
             f"{licence['leads_ingested_count']}")


class TestLeadBatchDedupeAndOverageThreshold:
    """Badges are deduplicated across and within batches before overage is billed."""

    def test_first_batch_at_the_included_lead_boundary_bills_no_overage(self, api):
        """PRD §3.8: "The licence is born `PROVISIONED` with an empty `ingested_badge_ids` array, `leads_ingested_count` at 0, `billable_overage_leads` at 0, `lead_overage_cents` at 0, and `license_total_cents` already computed."
        PRD §3.8: "The first batch that accepts at least one badge id advances the licence `PROVISIONED → ACTIVE`."
        PRD §3.8: "`billable_overage_leads` is that count minus `included_leads`, floored at zero — a count exactly equal to `included_leads` yields zero overage."
        PRD §3.8: "`license_total_cents` is `device_count` multiplied by 32500 cents per device, plus `lead_overage_cents`."

        Design: Corner/calculations/lead_batch_dedupe_and_overage_threshold
        """
        ground = setup_show_ground(show_status="ON_SITE")
        provisioned = provision_license(ground["booth"]["id"],
                                        ground["exhibitor"]["id"], **LICENSE_TERMS)

        assert_lead_capture_license(provisioned)
        assert provisioned["status"] == "PROVISIONED", \
            f"A new licence is born PROVISIONED, got {provisioned['status']}"
        assert provisioned["ingested_badge_ids"] == [], \
            f"A new licence carries no badges, got {provisioned['ingested_badge_ids']}"
        assert provisioned["license_total_cents"] == 65000, \
            ("Two devices are already priced at provisioning, expected 65000, got "
             f"{provisioned['license_total_cents']}")

        boundary = ingest_leads(provisioned["id"], ground["exhibitor"]["id"],
                                FIRST_BATCH)

        assert_lead_capture_license(boundary)
        assert boundary["status"] == "ACTIVE", \
            ("The first accepted batch advances PROVISIONED -> ACTIVE, got "
             f"{boundary['status']}")
        assert boundary["leads_ingested_count"] == 3, \
            f"Three fresh badges give a count of 3, got {boundary['leads_ingested_count']}"
        assert boundary["billable_overage_leads"] == 0, \
            ("A count exactly equal to the three included leads yields zero overage, "
             f"got {boundary['billable_overage_leads']}")
        assert boundary["lead_overage_cents"] == 0, \
            ("Zero overage leads bill nothing at "
             f"{LEAD['LEAD_OVERAGE_CENTS']} cents apiece, got "
             f"{boundary['lead_overage_cents']}")
        assert boundary["license_total_cents"] == 65000, \
            ("At the boundary the total is still the two-device fee alone, expected "
             f"65000, got {boundary['license_total_cents']}")

    def test_second_batch_dedupes_within_and_across_batches_and_bills_one_overage_lead(self, api):
        """PRD §3.8: "Badge ids are deduplicated against `ingested_badge_ids`, which holds every badge id ever accepted on this licence in first-seen order."
        PRD §3.8: "Ids from the request that are not already present are appended in request order; ids already present are silently skipped and raise no error, and duplicates within a single request body are collapsed with the first occurrence winning."
        PRD §3.8: "`leads_ingested_count` is then the number of entries in `ingested_badge_ids`."
        PRD §3.8: "`billable_overage_leads` is that count minus `included_leads`, floored at zero — a count exactly equal to `included_leads` yields zero overage."
        PRD §3.8: "`lead_overage_cents` is `billable_overage_leads` multiplied by 150 cents per overage lead."
        PRD §3.8: "`license_total_cents` is `device_count` multiplied by 32500 cents per device, plus `lead_overage_cents`."

        Design: Corner/calculations/lead_batch_dedupe_and_overage_threshold
        """
        ground = setup_active_license(badge_ids=FIRST_BATCH,
                                      license_overrides=LICENSE_TERMS)

        second = ingest_leads(ground["license"]["id"], ground["exhibitor"]["id"],
                              SECOND_BATCH, captured_at="2026-09-21T13:00:00Z")

        assert_lead_capture_license(second)
        assert second["ingested_badge_ids"] == ["B1", "B2", "B3", "B4"], \
            ("B3 repeats an earlier badge and B4 repeats within the body, so only B4 "
             f"is appended, got {second['ingested_badge_ids']}")
        assert second["leads_ingested_count"] == 4, \
            ("Six submitted badge ids deduplicate to four distinct ones, got "
             f"{second['leads_ingested_count']}")
        assert second["billable_overage_leads"] == 1, \
            ("Four badges against three included leads bill exactly one overage "
             f"lead, got {second['billable_overage_leads']}")
        assert second["lead_overage_cents"] == 150, \
            ("One overage lead bills at "
             f"{LEAD['LEAD_OVERAGE_CENTS']} cents, expected 150, got "
             f"{second['lead_overage_cents']}")
        assert second["license_total_cents"] == 65150, \
            ("The two-device fee plus one overage lead is 65150 cents, got "
             f"{second['license_total_cents']}")
        assert second["status"] == "ACTIVE", \
            f"A second batch leaves an ACTIVE licence ACTIVE, got {second['status']}"

        stored = _sole_licence_on_booth(api, ground["booth"]["id"])
        assert stored["leads_ingested_count"] == 4, \
            ("The stored licence carries the deduplicated count of 4, got "
             f"{stored['leads_ingested_count']}")
        assert stored["billable_overage_leads"] == 1, \
            f"The stored licence bills one overage lead, got {stored['billable_overage_leads']}"
        assert stored["lead_overage_cents"] == 150, \
            f"The stored overage charge is 150 cents, got {stored['lead_overage_cents']}"
        assert stored["license_total_cents"] == 65150, \
            f"The stored licence total is 65150 cents, got {stored['license_total_cents']}"


class TestLeadBatchAfterLicenceClosed:
    """A badge batch tendered after tear-down closed the licence is refused."""

    def test_batch_on_a_licence_closed_by_move_out_is_refused_with_license_closed(self, api):
        """PRD §3.8: "Batches are only accepted while the booth's show is `ON_SITE` or `MOVE_OUT` — otherwise `ERR_SHOW_NOT_ACCEPTING` — while the booth is not `FROZEN` — otherwise `ERR_BOOTH_FROZEN` — and while the licence itself is not `CLOSED`, a batch arriving after closure being refused with `ERR_LICENSE_CLOSED`."
        PRD §2.9: "The lead-capture licence is still open — otherwise `ERR_LICENSE_CLOSED` (409)."
        PRD §3.8: "When the show advances into `MOVE_OUT`, an `ACTIVE` licence moves to the terminal `CLOSED` and its `license_total_cents` is frozen at the figure it then holds; a licence still in `PROVISIONED` at that point remains `PROVISIONED` and only closes on the later `MOVE_OUT → CLOSED` show edge."

        Design: Corner/validations/lead_batch_after_license_closed_rejected
        """
        ground = setup_active_license(badge_ids=FIRST_BATCH,
                                      license_overrides=LICENSE_TERMS)
        advance_show(ground["show"]["id"], "MOVE_OUT")

        response = api.ingest_lead_batch(
            ground["license"]["id"],
            {"badge_ids": ["B9"], "captured_at": "2026-09-24T12:00:00Z"},
            make_exhibitor_headers(ground["exhibitor"]["id"]))

        validate_error(response, ApiErrorId.ERR_LICENSE_CLOSED, 409)

    def test_the_refused_batch_leaves_the_closed_licence_untouched(self, api):
        """PRD §3.8: "Batches are only accepted while the booth's show is `ON_SITE` or `MOVE_OUT` — otherwise `ERR_SHOW_NOT_ACCEPTING` — while the booth is not `FROZEN` — otherwise `ERR_BOOTH_FROZEN` — and while the licence itself is not `CLOSED`, a batch arriving after closure being refused with `ERR_LICENSE_CLOSED`."
        PRD §3.8: "`leads_ingested_count` is then the number of entries in `ingested_badge_ids`."
        PRD §3.1: "In the same transition, every lead-capture licence on a booth of this show whose `status` is `ACTIVE` moves to `CLOSED` and its `license_total_cents` is frozen at the figure it then holds."

        Design: Corner/validations/lead_batch_after_license_closed_rejected
        """
        ground = setup_active_license(badge_ids=FIRST_BATCH,
                                      license_overrides=LICENSE_TERMS)
        advance_show(ground["show"]["id"], "MOVE_OUT")

        response = api.ingest_lead_batch(
            ground["license"]["id"],
            {"badge_ids": ["B9"], "captured_at": "2026-09-24T12:00:00Z"},
            make_exhibitor_headers(ground["exhibitor"]["id"]))
        validate_error(response, ApiErrorId.ERR_LICENSE_CLOSED, 409)

        licence = _sole_licence_on_booth(api, ground["booth"]["id"])
        assert licence["status"] == "CLOSED", \
            f"The refused batch leaves the licence CLOSED, got {licence['status']}"
        assert licence["leads_ingested_count"] == 3, \
            ("The rejected badge is not recorded, so the count stays frozen at 3, got "
             f"{licence['leads_ingested_count']}")
        assert "B9" not in licence["ingested_badge_ids"], \
            ("The rejected badge never enters ingested_badge_ids, got "
             f"{licence['ingested_badge_ids']}")
        assert licence["license_total_cents"] == 65000, \
            ("The frozen total stays at 65000 cents, got "
             f"{licence['license_total_cents']}")
