import csv
import json
import re
import collections
import glob
import os
d = sorted(glob.glob('audit_output_full/*'))[-1]
rows = list(csv.DictReader(open(d + '/findings.csv', encoding='utf-8-sig')))
mid = json.load(open('all_mids.json'))
import sys
# usage: python make_scope_tables.py "<ga4 account name part>" "<gtm account name part>"
_ga4_word, _gtm_word = (sys.argv + ['', ''])[1:3]
RUST = lambda a: _ga4_word.lower() in a.lower() if _ga4_word else False   # GA4 + GTM accounts matching word 1
FIFTH = lambda a: _gtm_word.lower() in a.lower() if _gtm_word else False  # GTM accounts matching word 2

def num(s):
    m = re.match(r'(\d+)', s or '')
    return int(m.group(1)) if m else 0

# ---------- GA4 (accounts matching word 1)
by = collections.OrderedDict()
for r in rows:
    if r['scope'] == 'GA4' and RUST(r['account']):
        by.setdefault(r['entity_id'], {'name': r['entity'], 'acct': r['account']})[r['check']] = (r['status'], r['detail'])
ga = []
for pid, v in by.items():
    ev = v['Events last 30d'][1]
    events = '0' if ev.startswith('no events') else ev.split()[0]
    ke = v['Key events'][1]
    kecount = ke.split(':')[0]
    kf = v.get('Key events firing', ('', ''))[1]
    fired = 'n/a' if events == '0' else ('none fire' if kf.startswith('no hits') and len(kf.split(',')) >= len(ke.split(':', 1)[-1].split(',')) else ('all fire' if not kf else 'some fire'))
    ga.append(dict(account=v['acct'], property=v['name'], id=pid, events_30d=events, key_events=kecount,
                   key_events_status=fired, retention='14 mo' if 'FOURTEEN' in v['Data retention'][1] else '2 mo',
                   streams=v['Data streams'][1][:0] or ('none' if v['Data streams'][0] == 'FAIL' else 'ok'),
                   signals='on' if 'ENABLED' in v['Google Signals'][1] else 'off',
                   ads=v['Google Ads links'][1].split()[0], bq=v['BigQuery links'][1].split()[0],
                   unassigned=v.get('Unassigned traffic', ('', ''))[1].replace(' of sessions', '')))

# ---------- GTM
g = collections.OrderedDict()
for r in rows:
    if r['scope'] == 'GTM' and (RUST(r['account']) or FIFTH(r['account'])):
        g.setdefault(r['entity_id'], {'name': r['entity'], 'acct': r['account']})[r['check']] = (r['status'], r['detail'])
gt = []
for cid, v in g.items():
    pvd = v['Published version'][1]
    m = re.search(r': (\d+) tags, (\d+) triggers, (\d+) variables', pvd)
    tags, trg, var = (int(m[1]), int(m[2]), int(m[3])) if m else (0, 0, 0)
    def n(chk):
        s, dd = v.get(chk, ('PASS', ''))
        return num(dd) if s in ('WARN', 'FAIL') else 0
    ids = v['GA4 IDs referenced'][1].split()
    known = 'none' if not ids else ('yes' if all(i in mid for i in ids) else 'no')
    flags = []
    if v['Universal Analytics remnants'][0] == 'FAIL': flags.append('UA')
    if v.get('Tags present', ('PASS',))[0] == 'WARN': flags.append('empty')
    for lbl, chk in [('paused', 'Paused tags'), ('unused trig', 'Unused triggers'), ('unused var', 'Unused variables'),
                     ('hardcoded ID', 'Hardcoded GA4 IDs in tags'), ('dup', 'Duplicate tags'), ('no trigger', 'Tags with no firing trigger')]:
        k = n(chk)
        if k: flags.append(f'{lbl} {k}')
    if v['Custom HTML tags'][0] == 'WARN': flags.append(f"html {num(v['Custom HTML tags'][1])}")
    if v['Default/test tag names'][0] == 'WARN': flags.append('test names')
    gt.append(dict(account=v['acct'], container=re.sub(r' \((web|amp|android,ios|ios|android)\)$', '', v['name']), id=cid, tags=tags, triggers=trg,
                   variables=var, ga4_ids=' '.join(ids), ga4_id_in_audited_property=known, flags='; '.join(flags) or '-'))

os.makedirs('scope_tables', exist_ok=True)
for name, data in [('ga4_properties.csv', ga), ('gtm_containers.csv', gt)]:
    with open('scope_tables/' + name, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, list(data[0].keys())); w.writeheader(); w.writerows(data)

def esc(s): return str(s).replace('|', '/')
# markdown
with open('scope_tables/ga4.md', 'w', encoding='utf-8') as f:
    f.write('| Account | Property | ID | Events (30d) | Key events | Key event status | Retention | Streams | Signals | Ads links | BigQuery | Unassigned |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n')
    for x in sorted(ga, key=lambda x: (x['account'], -int(x['events_30d']))):
        f.write('| ' + ' | '.join(esc(x[k]) for k in ['account', 'property', 'id', 'events_30d', 'key_events', 'key_events_status', 'retention', 'streams', 'signals', 'ads', 'bq', 'unassigned'])  + ' |\n')
def gtm_md(sel, fn):
    with open('scope_tables/' + fn, 'w', encoding='utf-8') as f:
        f.write('| Container | ID | Tags | GA4 ID in audited property | Issues |\n| --- | --- | --- | --- | --- |\n')
        for x in sel:
            f.write(f"| {esc(x['container'])} | {x['id']} | {x['tags']} | {x['ga4_id_in_audited_property']} | {esc(x['flags'])} |\n")
rust = [x for x in gt if RUST(x['account'])]
fifth = [x for x in gt if FIFTH(x['account'])]
fifth.sort(key=lambda x: x['container'].lower())
gtm_md(rust, 'gtm_rust.md')
gtm_md(fifth[:100], 'gtm_5q_a.md'); gtm_md(fifth[100:], 'gtm_5q_b.md')
print(len(ga), len(rust), len(fifth))
