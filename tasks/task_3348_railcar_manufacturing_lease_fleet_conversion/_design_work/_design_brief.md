# Shared brief — authoring SCAFFOLD_DIFFICULTY_DESIGN.yaml fragments

You are extending the **§1.8 Scaffold Difficulty Design** index for a PRD-benchmark scaffold.
The scaffold itself (`SCAFFOLD.yaml`, §1.1–§1.7) is **already complete and frozen** — you must NOT
modify it. You only author index entries that *point into* it.

## Files

- Frozen scaffold: `SCAFFOLD.yaml` (read it; do not edit it)
- Authoritative spec: `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/SKILL.md`
  - §0.5 Difficulty Rules — lines ~185–219 (authoritative for each rule's min count and
    differentiation clause)
  - §1.8 schema + per-instance contract — lines ~562–670 (the 7-point contract)
- Validator: `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py`
  (run it after merging; it checks every `setup_api_calls` / `trigger` call conforms to §1.5)

## Output

Write ONE fragment file per rule block you are assigned, e.g. `_frag_r3.yaml`, shaped exactly:

```yaml
scaffold_difficulty_design:
  - rule_id: <the exact rule_id from §0.5>
    instances:
      - name: <unique_lower_snake_case>
        grounds: [...]
        distinguishing_aspect: "..."
        test_recipe:
          setup: [...]
          setup_api_calls: [...]
          trigger: [...]
          assert: [...]
```

A fragment file holds ONLY your assigned `rule_id` blocks. Do not include other rules.

## The seven-point contract (condensed from §1.8 — read the full text)

1. `grounds:` entries MUST resolve to real declared elements: `calculations.<name>`,
   `state_machines.<Entity>.<FROM>_to_<TO>`, `validations[priority=<N>]`,
   `entities.<Entity>.fields.<name>`, `concurrency_rules[<rule_id>]`.
2. `setup` + `setup_api_calls` + `trigger` + `assert` MUST reproduce the scenario from **empty DB**
   using only §1.5 endpoints. No wall-clock waits — time-gated setups use the clock-set endpoint.
3. `setup_api_calls:` is **mandatory and structured** — each entry a call object:
   `{call: "POST /path", payload: {...}, as: <Role>, as_user_id: <id-or-${var}>, captures: {...}}`.
   Prose strings are forbidden.
3a. **Literal lock**: payload values MUST be literals whenever determinable at authoring time.
   `${var}` is ONLY for values that can only come from a prior response (server-minted ids,
   server-stamped timestamps, server-issued tokens).
3b. Every `captures:` jsonpath MUST reference a field the §1.5 endpoint declares in its `output:`.
3c. Any `expected_*_version` payload value MUST be a `${var}` (or expression over one), never a
   bare literal.
4. `distinguishing_aspect` MUST be ONE falsifiable sentence naming the specific distinction §0.5
   requires of that `rule_id`.
5. `name` MUST be unique across the whole file and stable.
6. `assert:` lines cite exact field names and **literal values**.
7. Any assert referencing a formula-derived number MUST be a literal you actually computed by
   executing the formula as code (write a short Python snippet against the formula and its
   `constants:`, run it, paste the literal). Never an expression, estimate, or "let the tests
   compute it".

## Hard constraints

- Every `${var}` used in a payload / `as_user_id` / path template MUST be bound by a `captures:`
  on an EARLIER line of the SAME instance. Unbound placeholders are a hard failure.
- Every `call:` must resolve to an endpoint actually declared in §1.5 (method + path), and every
  payload field must conform to that endpoint's `input:` schema. Run the validator to confirm.
- Do NOT weaken a rule to make it easier: each §0.5 rule's differentiation clause (different entity
  domain, different error-category pair, different interval semantics, …) MUST be honoured.
- Do NOT read any sibling task under `/home/ubuntu/github/CodingPRD/tasks/` other than this task
  directory itself.

## Output budget — CRITICAL

This model endpoint caps output per message and silently truncates oversized tool calls.
Emit **exactly ONE tool call per assistant message**, and write **one instance per message**:
first message writes the fragment file with the rule header + instance 1, subsequent messages
`Edit` the file to append instance 2. Never batch two tool calls into one message.

## Verify before you finish

```
cd /home/ubuntu/github/CodingPRD/tasks/task_3348_railcar_manufacturing_lease_fleet_conversion
python3 -c "import yaml;d=yaml.safe_load(open('_frag_rN.yaml'));print([ (b['rule_id'], len(b['instances'])) for b in d['scaffold_difficulty_design']])"
```
