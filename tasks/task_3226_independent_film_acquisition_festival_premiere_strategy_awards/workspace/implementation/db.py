# In-memory data store. Starts empty on every boot; no seeding.

stores = {
    "films": {},
    "territories": {},
    "festivals": {},
    "premiere_slots": {},
    "offers": {},
    "deals": {},
    "rights_grants": {},
    "release_plans": {},
    "market_screenings": {},
    "awards_campaigns": {},
    "campaign_spends": {},
    "talent_obligations": {},
    "statements": {},
}

# Logical clock (ISO string). Startup default per PRD section 2.6.
logical_clock = "2026-09-01T00:00:00Z"
