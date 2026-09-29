import re,sys
prd=open('workspace/PRD.md').read()
req=[l for l in open('workspace/scratch_prd/required_names.txt').read().split("\n") if l]
toks=set(re.findall(r'`([^`\n]+)`',prd))
missing=[r for r in req if r not in toks]
print("REQUIRED",len(req),"MISSING",len(missing))
print(missing)
# contract 3
s3=prd.index('## 3. Business Logic')
s4=prd.index('## 4. Endpoint Definitions')
sec3=prd[s3:s4]
t3=re.findall(r'`([^`\n]+)`',sec3)
bad=[t for t in t3 if t.startswith('/') or t.upper() in {'GET','POST','PUT','PATCH','DELETE','OPTIONS'} or re.match(r'^(GET|POST|PUT|PATCH|DELETE)\s+/',t)]
print("SEC3 tokens",len(t3),"violations",bad)
# errors present
import yaml
d=yaml.safe_load(open('SCAFFOLD.yaml'))
errs=[e['id'] for e in d['errors']]
s2=prd.index('## 2. Global')
body=prd[s2:s4]
noerr=[e for e in errs if e not in body]
print("errors not in §2/§3:",noerr)
# roles/states
states=set()
for sm in d['state_machines']:
    states.add(sm['initial_state']); states.update(sm.get('terminal_states') or [])
    for t in sm['transitions']: states.add(t['from']); states.add(t['to'])
print("states missing:",[s for s in sorted(states) if s not in toks])
enums=set()
for e in d['entities']:
    for f in e['fields']:
        if f.get('type')=='enum' and f.get('constraints'):
            for v in f['constraints'].split('|'): enums.add(v.strip())
print("enum values missing:",[v for v in sorted(enums) if v not in toks])
print("roles missing:",[r['name'] for r in d['roles'] if r['name'] not in toks])
