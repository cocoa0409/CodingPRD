"""Corner coverage: the embargoed bulletin endpoint.

The time gate one second before opening, confidentiality masking of
suppressed cells with full totals, and entity-backed ownership on grants.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_bulletin,
    assert_same_instant,
    create_stratum,
    get_grant,
    get_single_cell,
    list_grants,
    make_accredited_media_headers,
    read_bulletin,
    set_clock,
    setup_certified_cycle,
    setup_embargoed_release,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    validate_error,
    validate_success,
)

RELEASE_MANAGER = TEST_USERS["release_manager_headers"]


def test_bulletin_one_second_before_embargo_open_rejected(api):
    """PRD §3.9: "the logical clock must have reached the release's `embargo_open_at`, otherwise the read is rejected with `ERR_EMBARGO_NOT_OPEN`."
    PRD §3.9: "its `release_event_id` and `media_outlet_id` recording the pairing, and `first_accessed_at` null until the first read."

    Design: Corner/endpoints/bulletin_one_second_before_embargo_open_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                                  {en1["id"]: 9})
    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z")
    release = staged["release"]
    grant = staged["grants"][0]
    outlet = staged["outlets"][0]
    assert_same_instant(release["embargo_open_at"], "2026-10-01T13:00:00Z")

    set_clock("2026-10-01T12:59:59Z")  # one second before embargo_open_at
    resp = api_client.get_bulletin(
        grant["id"], make_accredited_media_headers(outlet["id"]))
    validate_error(resp, ApiErrorId.ERR_EMBARGO_NOT_OPEN)  # 403

    grant_after = get_grant(grant["id"])
    assert grant_after["grant_status"] == "ISSUED"
    assert grant_after["first_accessed_at"] is None, (
        "the failed read is not an access")


def test_bulletin_masks_suppressed_cells_but_totals_full(api):
    """PRD §3.9: "Confidentiality masking applies at this boundary: for cells suppressed `PRIMARY` or `COMPLEMENTARY`, the bulletin nulls out `employment_estimate` and both seasonally adjusted values, while the industry row totals and size column totals still show the full figures computed from the complete cell set — suppression masks cells, never totals."
    PRD §3.5: "the industry row totals and size column totals are always computed from the full cell set including suppressed cells — suppression never changes a total."

    Design: Corner/endpoints/bulletin_masks_suppressed_cells_but_totals_full
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=3,
        strata=[create_stratum("MANUFACTURING", "SMALL", 30)])
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, _en3 = panel["enrollments"]

    # E1=5, E2=5 accepted; E3 silent (imputed 5 via the stratum-mean
    # fallback) -> cell 150 with 2 respondents -> PRIMARY.
    cycle = setup_certified_cycle(
        "CES", "2026-09", panel["enrollments"],
        {en1["id"]: 5, en2["id"]: 5})
    cell = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell["employment_estimate"] == 150
    assert cell["suppression_status"] == "PRIMARY"

    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z")
    bulletin = read_bulletin(staged["grants"][0]["id"],
                             staged["outlets"][0]["id"])
    assert_bulletin(bulletin)
    assert bulletin["release_status"] == "EMBARGO_OPEN"

    cells = bulletin["cells"]
    assert len(cells) == 1
    assert cells[0]["industry_code"] == "MANUFACTURING"
    assert cells[0]["size_class"] == "SMALL"
    assert cells[0]["employment_estimate"] is None, (
        "the PRIMARY cell is masked in the bulletin")

    totals = bulletin["industry_totals"]
    assert len(totals) == 1
    # The PRD pins the figure ("industry row totals ... still show the full
    # figures computed from the complete cell set") but does not name the
    # per-entry value field, so the row and its figure are located by value.
    assert "MANUFACTURING" in totals[0].values()
    assert 150 in totals[0].values(), (
        "10.0 x (5+5+5 imputed) — the full-cell-set total despite the "
        "masked cell")


def test_bulletin_with_other_outlets_grant_forbidden(api):
    """PRD §3.9: "the caller's `X-User-ID` must equal the grant's `media_outlet_id` (otherwise `ERR_FORBIDDEN`)"
    PRD §2.1: "When `X-User-Role` is `AccreditedMedia`, `X-User-ID` is the `id` of the acting `MediaOutlet`; bulletin access compares the grant's `media_outlet_id` to `X-User-ID`."

    Design: Corner/endpoints/bulletin_with_other_outlets_grant_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    panel = setup_enrolled_panel("CES", count=1)
    en1 = panel["enrollments"][0]
    cycle = setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                                  {en1["id"]: 9})
    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z",
                                     num_outlets=2)
    release = staged["release"]
    o1, o2 = staged["outlets"]
    assert release["active_embargo_grant_count"] == 2, (
        "both accredited outlets received grants")

    g2 = list_grants(release_event_id=release["id"],
                     media_outlet_id=o2["id"])[0]
    resp = api_client.get_bulletin(
        g2["id"], make_accredited_media_headers(o1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403: O1 does not own
    # the grant minted for O2.
