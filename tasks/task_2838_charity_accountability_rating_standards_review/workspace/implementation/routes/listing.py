"""Shared list helpers: default ordering and windowing."""

from response import ok_list


def by_created_at(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def respond(ctx, items):
    total = len(items)
    window = items[ctx.offset: ctx.offset + ctx.limit]
    return ok_list(window, ctx.limit, ctx.offset, total)


def int_arg(args, name):
    raw = args.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return -10 ** 12
