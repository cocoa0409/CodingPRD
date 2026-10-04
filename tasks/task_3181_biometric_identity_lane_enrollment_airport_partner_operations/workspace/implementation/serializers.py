"""Entity -> API view serializers. Entities are stored as plain dicts already
shaped for output, so serialization is a shallow copy with no surprises."""


def present(entity):
    if entity is None:
        return None
    return dict(entity)


def present_list(items):
    return [dict(e) for e in items]
