"""Corner coverage — reverse-FK list endpoints reach children (PRD §2.6, §2.3,
§4).
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    create_site, create_supply_contract_payload, create_planned_station,
    MANAGER, COMPLIANCE, BILLING,
)


def test_fk_reverse_reachability_subresources(api):
    """PRD §2.6: "Resources nest: a site owns assessments, supply contracts,
    stations, conversion plans, service agreements, downtime reports, invoices,
    incentive claims, and training records; a station owns permits and fueling
    events; a conversion plan owns conversion events; an invoice owns line
    items."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/fk_reverse_reachability_subresources
    """
    site = create_site(code="S-EP1")
    contract = get_success_data(api.create_supply_contract(
        site["id"], create_supply_contract_payload(
            supply_mode="PIPELINE", base_price_per_kg=2.5,
            reliability_sla_pct=99.0, committed_monthly_kg=10), MANAGER))
    station = create_planned_station(
        site["id"], station_code="ST-EP", capacity_kg_per_day=100,
        storage_capacity_kg=300, construction_start="2026-10-01",
        construction_end="2026-11-01")
    permit = get_success_data(api.create_permit(
        station["id"], {"permit_type": "CONSTRUCTION",
                        "issued_date": "2026-10-01", "expiry_date": "2027-01-01"},
        MANAGER))

    permits, _m = validate_paginated(api.list_permits(station["id"], COMPLIANCE))
    assert [p["id"] for p in permits] == [permit["id"]]

    contracts, _m = validate_paginated(api.list_supply_contracts(site["id"], BILLING))
    assert [c["id"] for c in contracts] == [contract["id"]]

    invoices, meta = validate_paginated(api.list_contract_invoices(contract["id"], BILLING))
    assert invoices == []
    assert meta["total_count"] == 0

    stations, _m = validate_paginated(api.list_stations(site["id"], MANAGER))
    assert [s["id"] for s in stations] == [station["id"]]
