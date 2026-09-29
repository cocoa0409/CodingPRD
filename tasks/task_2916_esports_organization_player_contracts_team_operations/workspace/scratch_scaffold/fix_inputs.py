import re,sys
p='/home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations/SCAFFOLD.yaml'
s=open(p).read()
def fix(m):
    inner=m.group(1)
    toks=[t.strip() for t in inner.split(',') if t.strip()]
    out=[]
    for t in toks:
        if t.endswith('?') and not t.startswith('"'):
            t='"%s"'%t
        out.append(t)
    return '    input: ['+', '.join(out)+']'
s=re.sub(r'^    input: \[([^\]]*)\]', fix, s, flags=re.M)
open(p,'w').write(s)
