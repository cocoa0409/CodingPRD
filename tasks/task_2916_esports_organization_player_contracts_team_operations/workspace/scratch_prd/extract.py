import yaml, json, re, sys
p='/home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations/SCAFFOLD.yaml'
d=yaml.safe_load(open(p))
fields=set()
efields={}
for e in d['entities']:
    efields[e['name']]=[f['name'] for f in e['fields']]
    for f in e['fields']: fields.add(f['name'])
inputs=set(); qp=set()
for ep in d['endpoints']:
    for i in (ep.get('input') or []):
        i=str(i).rstrip('?')
        inputs.add(i)
        if ep['method']=='GET': qp.add(i)
    out=ep.get('output')
    if isinstance(out,dict):
        for k in out: inputs.add(k)
print("ENTITY FIELDS", len(fields))
print("INPUTS", len(inputs))
print(json.dumps({'entities':efields,'inputs':sorted(inputs),'query':sorted(qp)},indent=1))
print("counts: endpoints",len(d['endpoints']),"errors",len(d['errors']),"calcs",len(d['calculations']),"validations",len(d['validations']),"roles",len(d['roles']),"sm",len(d['state_machines']))
allnames=sorted(fields|inputs)
open('/home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations/workspace/scratch_prd/required_names.txt','w').write("\n".join(allnames))
print("TOTAL REQUIRED", len(allnames))
