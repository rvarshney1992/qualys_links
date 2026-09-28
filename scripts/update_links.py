"""Weekly link refresh for the Qualys Portal Hub.

Pulls new items from public Qualys sources, files each one into the matching
links/<module>.csv (or links/public.csv), and logs every addition to
links/whats-new.csv so whats-new.html can show what landed each week.

Sources:
  - Qualys Blog RSS            -> "Blog" category of each matching module
  - Qualys Notifications RSS   -> "Release Notes" / "API" category of each matching module
  - Monthly newsletters (PDF)  -> public.csv "Newsletters"
  - ThreatPROTECT RSS          -> whats-new.csv only (too frequent for the libraries)

A link is never added twice: anything already in any CSV, or ever logged in
whats-new.csv, is skipped. So deleting a misfiled row from a module CSV keeps
it deleted.

Standard library only. Run:  python scripts/update_links.py [--days 14] [--dry-run]
"""

import argparse
import csv
import datetime as dt
import email.utils
import glob
import html
import io
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINKS = os.path.join(ROOT, 'links')
WHATS_NEW = os.path.join(LINKS, 'whats-new.csv')
WHATS_NEW_HEADER = ['week', 'published', 'module', 'title', 'link', 'category', 'source']
UA = 'Mozilla/5.0 (compatible; qualys-links-updater; +https://github.com/rvarshney1992/qualys_links)'
MAX_MODULES_PER_ITEM = 3
MAX_FEED_PAGES = 6

# Module keywords, matched against an item's title and tags. Entries written in
# ALL CAPS (acronyms) match case-sensitively as whole words; everything else is
# case-insensitive. Order inside a list doesn't matter.
MODULE_KEYWORDS = {
    'csam': ['CSAM', 'cybersecurity asset management', 'asset inventory', 'global assetview', 'unmanaged device'],
    'easm': ['EASM', 'external attack surface'],
    'etm': ['ETM', 'enterprise trurisk management', 'trurisk management', 'cyber risk assistant', 'risk operations'],
    'etm-identity': ['etm identity', 'identity security', 'identity risk', 'identity exposure', 'active directory'],
    'certview': ['certview', 'certificate'],
    'vmdr': ['VMDR', 'vulnerability management', 'vulnerability scanning', 'QID', 'QIDs', 'trurisk score'],
    'vmdr-ot': ['VMDR OT', 'operational technology', 'OT security', 'ICS', 'SCADA'],
    'vmdr-mobile': ['vmdr mobile', 'mobile device'],
    'pm': ['patch management', 'trurisk eliminate', 'patch tuesday', 'patching', 'mitigation'],
    'car': ['CAR', 'custom assessment and remediation', 'custom assessment'],
    'roc': ['ROC', 'mROC', 'risk operations center'],
    'pc': ['policy compliance', 'policy audit', 'SCA', 'security configuration assessment', 'CIS benchmark',
           'cyber essentials', 'DISA STIG', 'STIG'],
    'pci': ['PCI', 'PCI DSS', 'ASV'],
    'fim': ['FIM', 'file integrity'],
    'oca': ['OCA', 'out-of-band'],
    'saq': ['SAQ', 'security assessment questionnaire'],
    'totalcloud': ['totalcloud', 'CNAPP', 'CSPM', 'CDR', 'cloud security posture', 'cloud detection', 'cloud workload',
                   'cloud breach', 'cloud breaches', 'IaC', 'AWS', 'Azure', 'GCP'],
    'cs': ['container security', 'container', 'containers', 'kubernetes', 'K8s', 'KCS', 'qscanner'],
    'was': ['WAS', 'web application scanning', 'web app scanning'],
    'totalappsec': ['totalappsec', 'api security', 'application security', 'AppSec'],
    'totalai': ['totalai', 'LLM', 'LLMs', 'AI security', 'generative ai', 'genai', 'AI agents', 'agentic', 'MCP'],
    'saasdr': ['saasdr', 'saas detection', 'SSPM', 'saas security'],
    'edr': ['EDR', 'XDR', 'endpoint detection', 'endpoint protection'],
    'cloud-agent': ['cloud agent', 'qualys agent'],
    'scanner': ['scanner appliance', 'virtual scanner', 'QCSA', 'cloud scanner'],
    'passive-sensor': ['passive sensor', 'passive scanning'],
    'qgs': ['gateway service', 'QGS'],
    'connectors': ['connector', 'connectors'],
    'dashboards': ['unified dashboard', 'dashboard', 'dashboards', 'reporting'],
    'qflow': ['qflow'],
    'admin': ['tagging', 'user management', 'RBAC', 'subscription health', 'app picker', 'administration'],
    'api': ['api notification', 'api best practices', 'qualys api', 'API release'],
    'integrations': ['servicenow', 'splunk', 'sentinel', 'qradar', 'jira', 'ITSM', 'SIEM', 'SOAR'],
}


def compile_keywords():
    compiled = {}
    for mod, words in MODULE_KEYWORDS.items():
        pats = []
        for w in words:
            flags = 0 if (w.upper() == w or re.search(r'[A-Z]{2,}', w)) else re.IGNORECASE
            pats.append(re.compile(r'(?<![\w-])' + re.escape(w) + r'(?![\w-])', flags))
        compiled[mod] = pats
    return compiled


KEYWORDS = compile_keywords()


def match_modules(text, known):
    hits = []
    for mod, pats in KEYWORDS.items():
        if mod not in known:
            continue
        score = sum(1 for p in pats if p.search(text))
        if score:
            hits.append((score, mod))
    hits.sort(key=lambda h: -h[0])
    return [m for _, m in hits[:MAX_MODULES_PER_ITEM]]


# ---------- IO helpers ----------

def fetch(url, method='GET', timeout=30):
    req = urllib.request.Request(url, method=method, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status, res.headers.get('Content-Type', ''), (res.read() if method == 'GET' else b'')


def norm(url):
    url = url.strip().split('#', 1)[0]
    m = re.match(r'^(https?)://([^/?]+)(.*)$', url, re.IGNORECASE)
    if not m:
        return url.lower()
    scheme, host, rest = m.groups()
    rest = rest.rstrip('/')
    return f'https://{host.lower()}{rest}'


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def append_rows(path, header, rows):
    """Append rows without rewriting the file, keeping its existing line endings."""
    exists = os.path.exists(path)
    eol = '\n'
    if exists:
        with open(path, 'rb') as f:
            data = f.read()
        eol = '\r\n' if b'\r\n' in data else '\n'
        needs_eol = data and not data.endswith(b'\n')
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=eol)
    if not exists:
        w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, '') for h in header])
    with open(path, 'a', encoding='utf-8', newline='') as f:
        if exists and needs_eol:
            f.write(eol)
        f.write(buf.getvalue())


def clean(s):
    s = html.unescape(s or '')
    s = s.replace('™', '').replace('®', '')  # drop (TM)/(R) marks, the CSVs don't use them
    return re.sub(r'\s+', ' ', s).strip()


# ---------- sources ----------

def wordpress_feed(base, cutoff):
    """Yield items from a WordPress RSS feed, newest first, until older than cutoff."""
    for page in range(1, MAX_FEED_PAGES + 1):
        url = base if page == 1 else f'{base}?paged={page}'
        try:
            _, _, body = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return  # ran past the last page
            raise
        root = ET.fromstring(body)
        items = root.findall('./channel/item')
        if not items:
            return
        for it in items:
            pub = email.utils.parsedate_to_datetime(it.findtext('pubDate'))
            if pub < cutoff:
                return
            yield {
                'title': clean(it.findtext('title')),
                'link': (it.findtext('link') or '').strip(),
                'tags': [clean(c.text) for c in it.findall('category') if c.text],
                'published': pub.date().isoformat(),
            }


def blog_items(cutoff, known):
    out = []
    for it in wordpress_feed('https://blog.qualys.com/feed', cutoff):
        text = ' '.join([it['title']] + it['tags'])
        mods = match_modules(text, known)
        threat = any(t.lower().startswith('vulnerabilities and threat research') for t in it['tags'])
        for m in mods:
            out.append({**it, 'module': m, 'category': 'Blog', 'source': 'Qualys Blog'})
        if threat or not mods:
            out.append({**it, 'module': 'public',
                        'category': 'Research & Threat Intel' if threat else 'Qualys Resources',
                        'source': 'Qualys Blog'})
    return out


def notification_items(cutoff, known):
    out = []
    for it in wordpress_feed('https://notifications.qualys.com/feed', cutoff):
        text = ' '.join([it['title']] + it['tags'])
        is_api = bool(re.search(r'\bapi\b', text, re.IGNORECASE))
        mods = match_modules(text, known)
        if is_api and 'api' in known and 'api' not in mods:
            mods.append('api')
        for m in mods:
            out.append({**it, 'module': m, 'category': 'API Notifications' if m == 'api' else 'API' if is_api else 'Release Notes',
                        'source': 'Qualys Notifications'})
        if not mods:
            out.append({**it, 'module': 'public', 'category': 'Platform & Status', 'source': 'Qualys Notifications'})
    return out


def threatprotect_items(cutoff):
    return [{**it, 'module': 'threatprotect', 'category': 'ThreatPROTECT', 'source': 'ThreatPROTECT'}
            for it in wordpress_feed('https://threatprotect.qualys.com/feed/', cutoff)]


def newsletter_items(today):
    """Probe the predictable newsletter PDF URLs for this month and last month."""
    out = []
    first = today.replace(day=1)
    for d in (first, (first - dt.timedelta(days=1)).replace(day=1)):
        month, year = d.strftime('%B'), d.year
        slug = f'{month.lower()}-{year}'
        for kind, url in (
            ('Product Newsletter', f'https://docs.qualys.com/en/newsletters/content-experience/{slug}-newsletter.pdf'),
            ('TRU Newsletter', f'https://docs.qualys.com/en/newsletters/threat-research-unit/tru-{slug}-newsletter.pdf'),
        ):
            try:
                status, ctype, _ = fetch(url, method='HEAD')
            except urllib.error.HTTPError:
                continue
            if status == 200 and 'pdf' in ctype.lower():
                out.append({'title': f'{kind}: {month} {year}', 'link': url, 'module': 'public',
                            'category': 'Newsletters', 'source': 'Qualys Newsletters',
                            'published': d.isoformat()})
    return out


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--days', type=int, default=14, help='look back this many days (default 14; duplicates are skipped)')
    ap.add_argument('--dry-run', action='store_true', help='print what would be added without writing')
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc)
    cutoff = today - dt.timedelta(days=args.days)
    week = today.date().isoformat()
    known = {r['id'] for r in read_rows(os.path.join(ROOT, 'modules.csv')) if r.get('id')}

    # Every link already on the hub, per module, plus everything ever logged.
    seen_global = set()
    seen_by_module = {}
    for path in glob.glob(os.path.join(LINKS, '*.csv')):
        mod = os.path.splitext(os.path.basename(path))[0]
        if mod == 'whats-new':
            continue
        links = {norm(r.get('link', '')) for r in read_rows(path) if r.get('link')}
        seen_by_module[mod] = links
        seen_global |= links
    logged = {(r['module'], norm(r['link'])) for r in read_rows(WHATS_NEW)}

    candidates, errors = [], []
    for name, fn in (
        ('blog', lambda: blog_items(cutoff, known)),
        ('notifications', lambda: notification_items(cutoff, known)),
        ('newsletters', lambda: newsletter_items(today.date())),
        ('threatprotect', lambda: threatprotect_items(cutoff)),
    ):
        try:
            got = fn()
            print(f'{name}: {len(got)} candidate rows')
            candidates += got
        except Exception as e:  # one broken source shouldn't block the others
            errors.append(f'{name}: {e}')
            print(f'WARNING {name} failed: {e}', file=sys.stderr)

    additions = {}
    log = []
    for c in candidates:
        if not c['title'] or not c['link'].startswith('http'):
            continue
        key = (c['module'], norm(c['link']))
        if key in logged:
            continue
        if c['module'] != 'threatprotect':
            if key[1] in seen_by_module.get(c['module'], set()):
                continue
            # A link that is already filed somewhere else on the hub only goes to public.csv if it is truly new.
            if c['module'] == 'public' and key[1] in seen_global:
                continue
            additions.setdefault(c['module'], []).append(c)
            seen_by_module.setdefault(c['module'], set()).add(key[1])
        logged.add(key)
        log.append({**c, 'week': week})

    for mod, rows in sorted(additions.items()):
        print(f'  + {mod}: {len(rows)}')
        for r in rows:
            print(f'      [{r["category"]}] {r["title"]}')
    print(f'{len(log)} new entries in total')

    if not args.dry_run and log:
        for mod, rows in additions.items():
            append_rows(os.path.join(LINKS, f'{mod}.csv'), ['title', 'link', 'category'], rows)
        append_rows(WHATS_NEW, WHATS_NEW_HEADER, log)

    if errors and not candidates:
        sys.exit('every source failed:\n' + '\n'.join(errors))


if __name__ == '__main__':
    main()
