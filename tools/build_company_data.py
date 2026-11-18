#!/usr/bin/env python3
"""Builds company-data.json for the "Search by Companies" tab.

Reads every repo listed in company-sources.json (already cloned into ./repos/<id>), whatever its CSV layout,
and merges them without inflating counts:
  * a question is identified by platform + problem slug from its link (lc:two-sum, gfg:...), never by title alone;
  * every (question, company) pair from every repo is kept;
  * each repo's record is stored separately (frequency + most recent window + that repo's snapshot date),
    so nothing is added up or overwritten; the page shows the newest record and lists the rest.
Usage: python3 tools/build_company_data.py [repos_dir] [output_file]
"""
import csv, json, os, re, subprocess, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, 'company-sources.json')))
REPOS = sys.argv[1] if len(sys.argv) > 1 else 'repos'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'company-data.json'
ALIAS, NAMES = CFG.get('company_aliases', {}), CFG.get('company_names', {})

def ckey(name):
    k = re.sub(r'[^a-z0-9]+', '', name.lower())
    return ALIAS.get(k, k)

def window_days(fname):
    """Days covered by a CSV's time window; 0 = all time (no recency info), 9999 = older than six months."""
    f = re.sub(r'[^a-z]', '', os.path.splitext(fname)[0].lower())
    if 'thirty' in f or '30' in fname: return 30
    if 'morethansix' in f: return 9999
    if 'sixty' in f: return 60
    if 'three' in f or 'ninety' in f: return 90
    if 'six' in f: return 180
    if 'year' in f: return 365
    if f.endswith('all') or 'alltime' in f: return 0
    return None

def qkey(url):
    u = (url or '').strip()
    m = re.search(r'leetcode\.(?:com|cn)/problems/([^/?#\s]+)', u)
    if m: return 'lc:' + m.group(1).lower()
    m = re.search(r'geeksforgeeks\.org/problems/([^/?#\s]+)', u)
    if m: return 'gfg:' + re.sub(r'\d+$', '', m.group(1).lower()).strip('-') or m.group(1).lower()
    return None

def col(row, *names):
    for n in names:
        for k in row:
            if k and k.strip().lower() == n: return (row[k] or '').strip()
    return ''

MONTHS = {m: i for i, m in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'], 1)}
def readme_date(path):
    for fn in os.listdir(path):
        if fn.lower().startswith('readme'):
            t = open(os.path.join(path, fn), encoding='utf-8', errors='replace').read()
            m = re.search(r'snapshot as of\W*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\s+(\d{4})', t, re.I)
            if m: return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    return None

def as_of(src, path):
    """Snapshot date of a repo: a fixed date, the date stated in its README, or its last commit date."""
    v = src.get('as_of', 'commit')
    if v == 'readme': v = readme_date(path) or 'commit'
    if v != 'commit': return v
    try: return subprocess.check_output(['git', '-C', path, 'log', '-1', '--format=%cs'], text=True).strip()
    except Exception: return date.today().isoformat()

Q, COMP, REC, sources = {}, {}, {}, []
for si, src in enumerate(CFG['sources']):
    root = os.path.join(REPOS, src['id'])
    snap = as_of(src, root)
    sources.append({'id': src['id'], 'repo': src['repo'], 'as_of': snap})
    files = 0
    for comp_dir in sorted(os.listdir(root)):
        cpath = os.path.join(root, comp_dir)
        if not os.path.isdir(cpath) or comp_dir.startswith('.') or comp_dir in ('src', 'docs', 'scripts'): continue
        for fn in sorted(os.listdir(cpath)):
            if not fn.lower().endswith('.csv'): continue
            w = window_days(fn)
            if w is None: continue
            files += 1
            ck = ckey(comp_dir)
            nice = NAMES.get(ck) or (comp_dir if comp_dir != comp_dir.lower() else comp_dir.replace('-', ' ').title())
            if ck not in COMP or (NAMES.get(ck) is None and comp_dir != comp_dir.lower()): COMP[ck] = nice
            with open(os.path.join(cpath, fn), encoding='utf-8', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    url = col(row, 'url', 'link', 'problem link', 'question link')
                    k = qkey(url)
                    if not k: continue
                    title = re.sub(r'^\s*(?:lc\s*)?\d+\s*[.)-]\s*', '', col(row, 'title', 'name', 'problem', 'question'))
                    title = re.sub(r'\s*-\s*leetcode\s*$', '', title, flags=re.I)
                    num = col(row, 'id', 'question id', 'number', 'frontend id')
                    diff = col(row, 'difficulty')[:1].upper()
                    try: freq = float(col(row, 'frequency %', 'frequency', 'freq').rstrip('%') or 0)
                    except ValueError: freq = 0.0
                    q = Q.setdefault(k, {'n': None, 't': '', 'd': ''})
                    if num.isdigit() and not q['n']: q['n'] = int(num)
                    if title and not q['t']: q['t'] = title
                    if diff in 'EMH' and diff and not q['d']: q['d'] = diff
                    r = REC.setdefault((k, ck, si), {'all': None, 'win': None, 'wf': 0.0})
                    if w == 0: r['all'] = max(r['all'] or 0, freq)
                    else:
                        if r['win'] is None or w < r['win']: r['win'] = w
                        r['wf'] = max(r['wf'], freq)
    print(f"{src['id']}: {files} CSV files, snapshot {snap}", file=sys.stderr)

# compact output: questions, companies, then per question a flat list of [company, source, freq*10, window]
qkeys = sorted(Q, key=lambda k: (Q[k]['n'] or 10**9, k))
qi = {k: i for i, k in enumerate(qkeys)}
ckeys = sorted(COMP, key=lambda c: COMP[c].lower())
cidx = {c: i for i, c in enumerate(ckeys)}
assoc = [[] for _ in qkeys]
for (k, ck, si), r in REC.items():
    f = r['all'] if r['all'] is not None else r['wf']
    assoc[qi[k]] += [cidx[ck], si, round(f * 10), r['win'] or 0]
out = {
    'built': date.today().isoformat(),
    'sources': sources,
    'companies': [COMP[c] for c in ckeys],
    'q': [[k, Q[k]['n'] or 0, Q[k]['t'] or k.split(':', 1)[1].replace('-', ' ').title(), Q[k]['d']] for k in qkeys],
    'a': assoc,
}
json.dump(out, open(OUT, 'w'), separators=(',', ':'), ensure_ascii=False)
pairs = len({(k, ck) for k, ck, _ in REC})
print(f"{len(qkeys)} questions, {len(ckeys)} companies, {pairs} question-company pairs, {len(REC)} source records -> {OUT} ({os.path.getsize(OUT)//1024} KB)", file=sys.stderr)
