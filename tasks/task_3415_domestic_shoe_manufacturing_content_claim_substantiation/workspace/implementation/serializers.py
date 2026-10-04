"""Entity -> public JSON dict.

Strips internal fields (any key starting with "_") and injects computed
read-only fields where the entity defines them (factory skill coverage).
"""
import calcs


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def factory(ent):
    d = pub(ent)
    cert, pipe = calcs.skill_coverage(ent)
    d["skill_coverage_certified_pct"] = cert
    d["skill_coverage_pipeline_pct"] = pipe
    return d
