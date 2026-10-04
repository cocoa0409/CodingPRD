# Shared brief — authoring SCAFFOLD_CORNER_DESIGN.yaml fragments (§1.9 breadth index)

You are authoring the **§1.9 Scaffold Corner Design** breadth index for a PRD-benchmark scaffold.
The scaffold (`SCAFFOLD.yaml`, §1.1–§1.7) is **already complete and frozen** — do NOT modify it.
You author index entries that *point into* it.

## Files

- Frozen scaffold: `SCAFFOLD.yaml` (read it; never edit)
- Authoritative spec: `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/SKILL.md`
  - §1.9 — lines ~671–717 (schema, per-instance contract, `excluded_because:` stubs, §1.5 ladder)
  - §1.8 — lines ~562–670 (the 7-point per-instance contract that §1.9 inherits IN FULL)
- Taxonomy: `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/references/claim-extraction-guide.md`
  — its nine section headings ARE §1.9's `section:` values; its per-section table ROW LABELS ARE
  §1.9's `claim_type:` values. Do not invent new section or claim_type names.
- Validator: `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py`
- Sibling §1.8 file (already complete, 9 rules × 2 instances): `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
  — read it so your `excluded_because:` stubs cite REAL `difficulty_instance` names.

## Output shape

Write ONE fragment file per assigned section group, e.g. `_frag_corner_entities.yaml`:

```yaml
scaffold_corner_design:
  - section: state_machines            # exactly one of the guide's nine section names
    instances:
      - name: <unique_lower_snake_case>
        claim_type: invalid_transition  # a row label from that section's guide table
        grounds: [state_machines.Booking.transitions.CANCELLED_to_CANCELLED]
        distinguishing_aspect: "ONE falsifiable sentence."
        test_recipe:
          setup: ["<precondition prose>"]
          setup_api_calls: [ <structured calls, same form as §1.8> ]
          trigger: [ <structured call> ]
          assert: ["<one observable per line, literal values>"]

      - name: error_subscription_inactive_on_create_booking   # already covered by §1.8 → STUB
        claim_type: violation_to_error
        grounds: [errors[ERR_SUBSCRIPTION_INACTIVE]]
        excluded_because:
          difficulty_instance: cross_entity_state_dependency / booking_requires_subscription_active_or_grace
          rationale: "Asserted as the failure path of the named §1.8 instance."
        # NO test_recipe — forbidden on stubs.
```

`name` MUST be unique across the union of §1.8 and §1.9.

## The inherited 7-point contract (condensed — read §1.8's full text)

1. `grounds:` MUST resolve to real declared elements: `calculations.<name>`,
   `state_machines.<Entity>.<FROM>_to_<TO>`, `validations[priority=<N>]`,
   `entities.<Entity>.fields.<name>`, `errors[ERR_X]`, `concurrency_rules[<rule_id>]`, endpoint paths.
2. `setup` + `setup_api_calls` + `trigger` + `assert` MUST reproduce the scenario from **empty DB**
   using only §1.5 endpoints. No wall-clock waits — use the clock-set endpoint.
3. `setup_api_calls:` is **mandatory and structured** for every non-stub instance. Each entry:
   `{call: "POST /path", payload: {...}, as: <Role>, as_user_id: <id-or-${var}>, captures: {...}}`.
3a. **Literal lock** — payload values MUST be literals whenever determinable at authoring time.
   `${var}` ONLY for values that can only come from a prior response.
3b. Every `captures:` jsonpath MUST reference a field that endpoint's §1.5 `output:` declares.
3c. Every `expected_*_version` payload value MUST be a `${var}` or an expression over one — never a
   bare literal.
4. `distinguishing_aspect` — ONE falsifiable sentence.
6. `assert:` lines cite exact field names and **literal values**.
7. Any assert referencing a formula-derived number MUST be a literal you computed by EXECUTING the
   formula in Python against the scaffold's declared constants. Never an expression or estimate.

## Coverage duty

§1.9 is the BREADTH probe: enumerate every testable claim §1.1–§1.7 declares that §1.8 does not
already cover. Two hard coverage requirements from the guide:

- **Every error code in §1.6 must be triggerable by at least one instance** — either a real recipe
  in your section, or an `excluded_because:` stub citing a real §1.8 instance name.
- **Every state machine's invalid transitions / terminal lockdown / initial state**, every entity's
  required-fields and defaults, and every role's denial surface must be enumerated.

Emit `excluded_because:` stubs freely where §1.8 already covers the corner — but the cited
`difficulty_instance` MUST exist by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and the rationale
must name which assertion covers it. Skipping a row that NEITHER §1.8 NOR §1.9 covers is a gap.

## Hard constraints

- Every `${var}` MUST be bound by a `captures:` on an EARLIER line of the SAME instance.
- Every `call:` must resolve to a §1.5 endpoint (method + path) with a conforming payload shape.
- Do NOT read any sibling task under `/home/ubuntu/github/CodingPRD/tasks/` other than this task.
- Use the guide's `section:` and `claim_type:` names verbatim.

## Output budget — CRITICAL

This endpoint caps output per message and silently truncates oversized tool calls. Emit exactly
**ONE tool call per assistant message**, and write **ONE INSTANCE per message**: first message
writes the fragment with the section header + instance 1; each later message `Edit`-appends one
more instance. Never batch two tool calls into one message.

## Verify before finishing

```
cd /home/ubuntu/github/CodingPRD/tasks/task_3348_railcar_manufacturing_lease_fleet_conversion
python3 -c "import yaml;d=yaml.safe_load(open('_frag_corner_X.yaml'))['scaffold_corner_design'];print([(b['section'],len(b['instances'])) for b in d])"
```
