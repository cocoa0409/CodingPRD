import yaml
d=yaml.safe_load(open('SCAFFOLD.yaml'))
out=[]
out.append("")
out.append("## 4. Endpoint Definitions")
out.append("")
out.append("Creation endpoints return HTTP 201 with the created resource; every other successful operation, including state transitions, computed reads and list reads, returns HTTP 200 with the affected or requested resource. The table below is the authoritative mapping from method and path to authorised roles; request payloads, response contents and side effects are not repeated here and must be taken from the narratives in §2 and §3.")
out.append("")
out.append("| Method | Path | Description | Authorized Role(s) |")
out.append("| --- | --- | --- | --- |")
for ep in d['endpoints']:
    desc=ep['description'].strip().replace('|','/')
    out.append("| %s | `%s` | %s | %s |"%(ep['method'],ep['path'],desc,", ".join("`%s`"%r for r in ep['roles'])))
out.append("")
out.append("## 5. Error Code Catalogue")
out.append("")
out.append("Every rejection carries one of the identifiers below in the `error_id` field of the error envelope described in §2.2, with the HTTP status shown. The conditions that trigger each identifier are not repeated here; they are stated where the rule they enforce is described, and their relative precedence is fixed by the thirteen bands of §2.6.")
out.append("")
out.append("| Error ID | HTTP Status Code |")
out.append("| --- | --- |")
for e in d['errors']:
    out.append("| `%s` | %s |"%(e['id'],e['http']))
open('workspace/scratch_prd/tables.md','w').write("\n".join(out)+"\n")
print(len(out))
