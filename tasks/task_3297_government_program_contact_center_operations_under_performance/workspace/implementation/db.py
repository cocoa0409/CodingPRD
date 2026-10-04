"""In-memory data store. Each entity is a dict keyed by id. Empty at boot."""

contracts = {}
service_levels = {}
agents = {}
certifications = {}
course_completions = {}
queues = {}
calls = {}
quality_reviews = {}
coaching_plans = {}
knowledge_articles = {}
training_courses = {}
surge_windows = {}
incidents = {}
invoices = {}
invoice_lines = {}
cure_periods = {}

STORES = {
    "contracts": contracts,
    "service_levels": service_levels,
    "agents": agents,
    "certifications": certifications,
    "course_completions": course_completions,
    "queues": queues,
    "calls": calls,
    "quality_reviews": quality_reviews,
    "coaching_plans": coaching_plans,
    "knowledge_articles": knowledge_articles,
    "training_courses": training_courses,
    "surge_windows": surge_windows,
    "incidents": incidents,
    "invoices": invoices,
    "invoice_lines": invoice_lines,
    "cure_periods": cure_periods,
}
