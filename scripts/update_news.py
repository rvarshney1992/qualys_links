"""Daily cybersecurity news refresh for the Qualys Portal Hub.

Pulls headlines from public security news feeds, tags each one with topic
categories (Vulnerability Management, Ransomware & Malware, ...), and
correlates it with Qualys ThreatPROTECT advisories:

  - CVE match     the story and the advisory name at least one common CVE
  - vendor match  both mention the same vendor/product and were published
                  within CORRELATE_DAYS of each other

CVEs are also checked against the CISA Known Exploited Vulnerabilities
catalog, so stories about actively exploited bugs are flagged.

Output: links/news.json, a rolling window of the last KEEP_DAYS days that
news.html renders. Each run merges new items into the existing file; the
`edition` field is the date of the refresh that first picked an item up,
which is what the page's "Morning briefing" picker groups by.

Standard library only. Run:  python scripts/update_news.py [--days 3] [--dry-run]
"""

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'links', 'news.json')
USER_AGENTS = ['Mozilla/5.0 (compatible; qualys-links-updater; +https://github.com/rvarshney1992/qualys_links)',
               'Mozilla/5.0']
KEEP_DAYS = 14
CORRELATE_DAYS = 10
SUMMARY_LEN = 280

NEWS_FEEDS = [
    ('The Hacker News', 'https://feeds.feedburner.com/TheHackersNews'),
    ('BleepingComputer', 'https://www.bleepingcomputer.com/feed/'),
    ('Dark Reading', 'https://www.darkreading.com/rss.xml'),
    ('Help Net Security', 'https://www.helpnetsecurity.com/feed/'),
    ('The Record', 'https://therecord.media/feed'),
    ('Krebs on Security', 'https://krebsonsecurity.com/feed/'),
    ('CISA Advisories', 'https://www.cisa.gov/cybersecurity-advisories/all.xml'),
    ('Qualys Blog', 'https://blog.qualys.com/feed'),
]
THREATPROTECT_FEED = 'https://threatprotect.qualys.com/feed/'
KEV_URL = 'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'

# Topic categories, matched against title + summary + feed tags. An item can
# land in several; the first match in this order is its primary category.
# ALL-CAPS entries match case-sensitively as whole words, the rest ignore case.
CATEGORIES = {
    'Vulnerability Management': ['CVE', 'vulnerability', 'vulnerabilities', 'zero-day', '0-day', 'flaw', 'flaws',
                                 'patch', 'patches', 'patched', 'security update', 'exploit', 'exploited', 'RCE',
                                 'remote code execution', 'KEV', 'Patch Tuesday', 'bug', 'CVSS', 'advisory'],
    'Ransomware & Malware': ['ransomware', 'malware', 'botnet', 'trojan', 'infostealer', 'stealer', 'backdoor',
                             'loader', 'spyware', 'wiper', 'rootkit', 'RAT', 'worm', 'extortion'],
    'Threat Intel & Actors': ['APT', 'threat actor', 'threat actors', 'nation-state', 'espionage', 'campaign',
                              'hacking group', 'cybercriminals', 'Lazarus', 'state-sponsored', 'hacktivist'],
    'Data Breach': ['breach', 'breached', 'data leak', 'leaked', 'exposed data', 'stolen data', 'data theft',
                    'customer data', 'personal information'],
    'Cloud & Container': ['cloud', 'AWS', 'Azure', 'GCP', 'Kubernetes', 'container', 'containers', 'Docker',
                          'SaaS', 'serverless', 'misconfiguration'],
    'Identity & Access': ['identity', 'credential', 'credentials', 'phishing', 'MFA', 'password', 'passwords',
                          'Okta', 'Active Directory', 'Entra', 'OAuth', 'authentication bypass', 'session hijack'],
    'AI Security': ['AI', 'LLM', 'LLMs', 'GenAI', 'generative AI', 'agentic', 'AI agent', 'AI agents',
                    'prompt injection', 'ChatGPT', 'Copilot', 'MCP'],
    'Supply Chain': ['supply chain', 'supply-chain', 'npm', 'PyPI', 'open source package', 'dependency',
                     'malicious package', 'malicious packages', 'GitHub Actions', 'VS Code extension'],
    'OT & IoT': ['ICS', 'SCADA', 'OT', 'operational technology', 'industrial control', 'IoT', 'PLC', 'firmware'],
    'Compliance & Policy': ['regulation', 'regulator', 'compliance', 'SEC', 'GDPR', 'directive', 'BOD', 'NIST',
                            'law', 'legislation', 'fine', 'fined', 'sanctions', 'policy', 'CISA order', 'NIS2',
                            'DORA', 'PCI DSS', 'privacy'],
}
DEFAULT_CATEGORY = 'General Security'

# Vendors / products used for fuzzy correlation when there is no shared CVE.
VENDORS = [
    'Microsoft', 'Windows', 'Exchange', 'SharePoint', 'Outlook', 'Office', 'Azure', 'Entra', 'Google', 'Chrome',
    'Android', 'Apple', 'iOS', 'macOS', 'Safari', 'Mozilla', 'Firefox', 'Cisco', 'Citrix', 'NetScaler', 'Fortinet',
    'FortiOS', 'FortiGate', 'FortiWeb', 'Palo Alto', 'PAN-OS', 'GlobalProtect', 'Check Point', 'Ivanti', 'SonicWall',
    'Juniper', 'F5', 'BIG-IP', 'VMware', 'vCenter', 'ESXi', 'Broadcom', 'Oracle', 'SAP', 'NetWeaver', 'Adobe',
    'Atlassian', 'Confluence', 'Jira', 'GitLab', 'GitHub', 'Jenkins', 'Apache', 'Tomcat', 'Struts', 'Log4j', 'OpenSSL',
    'OpenSSH', 'Linux', 'Linux kernel', 'Red Hat', 'Ubuntu', 'Docker', 'Kubernetes', 'WordPress', 'Drupal', 'Joomla',
    'Zimbra', 'Veeam', 'SolarWinds', 'MOVEit', 'Progress', 'Zyxel', 'D-Link', 'TP-Link', 'Netgear', 'QNAP', 'Synology',
    'ConnectWise', 'ScreenConnect', 'Kaseya', 'Splunk', 'Salesforce', 'ServiceNow', 'Okta', 'Zoom', 'Samsung',
    'Qualcomm', 'Intel', 'AMD', 'NVIDIA', 'Arm', 'HPE', 'Aruba', 'Dell', 'Lenovo', 'IBM', 'Siemens', 'Schneider Electric',
    'Rockwell', 'Hikvision', 'Trend Micro', 'Sophos', 'CrowdStrike', 'SentinelOne', 'Commvault', 'Craft CMS', 'Roundcube',
    'Erlang', 'Next.js', 'React', 'Node.js', 'PHP', 'Python', 'Git', 'Chromium', 'WinRAR', '7-Zip', 'Notepad++',
]
# Vendor words that are too common on their own to prove two stories are related.
WEAK_VENDORS = {'Windows', 'Office', 'Google', 'Microsoft', 'Linux', 'Apple', 'Python', 'PHP', 'Git', 'React', 'Arm',
                'Progress', 'Intel'}


def pattern(word):
    flags = 0 if (word.upper() == word or re.search(r'[A-Z]{2,}', word)) else re.IGNORECASE
    return re.compile(r'(?<![\w-])' + re.escape(word) + r'(?![\w-])', flags)


CAT_PATTERNS = {c: [pattern(w) for w in ws] for c, ws in CATEGORIES.items()}
VENDOR_PATTERNS = [(v, pattern(v)) for v in VENDORS]
CVE_RE = re.compile(r'CVE-\d{4}-\d{4,7}', re.IGNORECASE)


# ---------- helpers ----------

def fetch(url, timeout=40):
    """GET url. News CDNs disagree on which clients they 403, so try each UA, then curl."""
    last = None
    for ua in USER_AGENTS:
        req = urllib.request.Request(url, headers={'User-Agent': ua, 'Accept': '*/*'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            last = e
    # Some (cisa.gov) reject Python's TLS client outright but serve curl fine.
    if not shutil.which('curl'):
        raise last
    return subprocess.run(['curl', '-sfL', '--max-time', str(timeout), '-A', USER_AGENTS[-1], url],
                          check=True, capture_output=True).stdout


def text_of(s):
    s = re.sub(r'<[^>]+>', ' ', html.unescape(s or ''))
    s = html.unescape(s).replace('™', '').replace('®', '')
    return re.sub(r'\s+', ' ', s).strip()


def shorten(s, n=SUMMARY_LEN):
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(' ', 1)[0].rstrip(',;:.')
    return cut + '…'


def norm(url):
    url = url.strip().split('#', 1)[0]
    url = re.sub(r'[?&]utm_[^&]*', '', url)
    return re.sub(r'^http://', 'https://', url).rstrip('/').lower()


def parse_date(s):
    s = (s or '').strip()
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def local(tag):
    return tag.rsplit('}', 1)[-1]


def child(el, *names):
    """First child whose tag is one of names, tried in order. (Elements with no children are falsy, so no `or`.)"""
    for name in names:
        for c in el:
            if local(c.tag) == name:
                return c
    return None


def children(el, name):
    return [c for c in el if local(c.tag) == name]


def parse_feed(body):
    """Yield dicts from an RSS 2.0 or Atom feed."""
    root = ET.fromstring(body)
    entries = root.findall('./channel/item') or [e for e in root if local(e.tag) == 'entry']
    for e in entries:
        title_el = child(e, 'title')
        title = text_of(title_el.text if title_el is not None else '')
        link_el = child(e, 'link')
        link = ''
        if link_el is not None:
            link = (link_el.text or link_el.get('href') or '').strip()
        date_el = child(e, 'pubDate', 'published', 'updated', 'date')
        desc_el = child(e, 'description', 'summary')
        full_el = child(e, 'encoded', 'content')
        desc = text_of(desc_el.text if desc_el is not None else '')
        full = text_of(full_el.text if full_el is not None else '')
        tags = [text_of(c.text or c.get('term') or '') for c in children(e, 'category')]
        yield {
            'title': title,
            'link': link,
            'published': parse_date(date_el.text if date_el is not None else ''),
            'summary': desc or full,
            'body': ' '.join([desc, full]),
            'tags': [t for t in tags if t],
        }


def categorize(text):
    cats = [c for c, pats in CAT_PATTERNS.items() if any(p.search(text) for p in pats)]
    return cats or [DEFAULT_CATEGORY]


def vendors_in(text):
    return sorted({v for v, p in VENDOR_PATTERNS if p.search(text)})


def cves_in(text):
    return sorted({c.upper() for c in CVE_RE.findall(text)})


# ---------- sources ----------

def collect(source, url, cutoff):
    horizon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    out = []
    for it in parse_feed(fetch(url)):
        if not it['title'] or not it['link'].startswith('http') or not it['published'] or it['published'] < cutoff:
            continue
        if it['published'] > horizon:  # event listings dated weeks ahead
            continue
        text = ' '.join([it['title'], it['summary'], ' '.join(it['tags'])])
        out.append({
            'title': it['title'],
            'link': it['link'],
            'source': source,
            'published': it['published'].astimezone(dt.timezone.utc).isoformat(timespec='minutes'),
            'summary': shorten(it['summary']),
            'categories': categorize(text),
            'cves': cves_in(' '.join([it['title'], it['body']])),
            # Vendors from the title and summary only; body text mentions too many in passing.
            'vendors': vendors_in(' '.join([it['title'], it['summary']])),
        })
    return out


def load_kev():
    data = json.loads(fetch(KEV_URL, timeout=60))
    return {v['cveID'].upper(): {'added': v.get('dateAdded', ''), 'due': v.get('dueDate', ''),
                                 'ransomware': v.get('knownRansomwareCampaignUse', '') == 'Known'}
            for v in data.get('vulnerabilities', [])}


# ---------- correlation ----------

def correlate(news, advisories):
    """Link each story to the advisories it relates to, strongest match first."""
    adv_time = {a['id']: dt.datetime.fromisoformat(a['published']) for a in advisories}
    for a in advisories:
        a['related'] = []
    by_id = {a['id']: a for a in advisories}
    for n in news:
        n_time = dt.datetime.fromisoformat(n['published'])
        n_cves, n_vendors = set(n['cves']), set(n['vendors'])
        links = []
        for a in advisories:
            shared_cves = sorted(n_cves & set(a['cves']))
            if shared_cves:
                links.append((0, a['id'], 'cve', shared_cves))
                continue
            if abs((n_time - adv_time[a['id']]).days) > CORRELATE_DAYS:
                continue
            shared = n_vendors & set(a['vendors'])
            strong = shared - WEAK_VENDORS
            # A single common word like "Microsoft" isn't enough; need a specific product or two shared names.
            if strong or len(shared) >= 2:
                links.append((1, a['id'], 'vendor', sorted(shared)))
        links.sort()
        n['advisories'] = [{'id': aid, 'match': kind, 'on': on} for _, aid, kind, on in links[:3]]
        for _, aid, kind, on in links:
            by_id[aid]['related'].append({'link': n['link'], 'match': kind})


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--days', type=int, default=3, help='look back this many days (default 3; duplicates are merged)')
    ap.add_argument('--dry-run', action='store_true', help='print a summary without writing links/news.json')
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    edition = now.date().isoformat()
    cutoff = now - dt.timedelta(days=args.days)
    keep_after = now - dt.timedelta(days=KEEP_DAYS)

    old = {'news': [], 'advisories': []}
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            old = json.load(f)

    errors, fresh_news = [], []
    for source, url in NEWS_FEEDS:
        try:
            got = collect(source, url, cutoff)
            print(f'{source}: {len(got)} items')
            fresh_news += got
        except Exception as e:  # one broken feed shouldn't block the others
            errors.append(f'{source}: {e}')
            print(f'WARNING {source} failed: {e}', file=sys.stderr)

    fresh_adv = []
    try:
        # Advisories are fetched with the full retention window so correlations have something to match against.
        fresh_adv = collect('ThreatPROTECT', THREATPROTECT_FEED, keep_after)
        print(f'ThreatPROTECT: {len(fresh_adv)} advisories')
    except Exception as e:
        errors.append(f'ThreatPROTECT: {e}')
        print(f'WARNING ThreatPROTECT failed: {e}', file=sys.stderr)

    try:
        kev = load_kev()
        print(f'CISA KEV: {len(kev)} CVEs')
    except Exception as e:
        kev = None
        errors.append(f'CISA KEV: {e}')
        print(f'WARNING CISA KEV failed: {e}', file=sys.stderr)

    def merge(old_items, new_items):
        """Keep the first-seen edition of anything already known; refresh everything else."""
        merged = {}
        for it in old_items:
            merged[norm(it['link'])] = it
        added = 0
        for it in new_items:
            key = norm(it['link'])
            if key in merged:
                it['edition'] = merged[key].get('edition', edition)
            else:
                it['edition'] = edition
                added += 1
            merged[key] = it
        items = [it for it in merged.values() if dt.datetime.fromisoformat(it['published']) >= keep_after]
        items.sort(key=lambda it: it['published'], reverse=True)
        return items, added

    news, news_added = merge(old.get('news', []), fresh_news)
    advisories, adv_added = merge(old.get('advisories', []), fresh_adv)
    for i, a in enumerate(advisories):
        a['id'] = f'tp{i}'
    correlate(news, advisories)

    old_kev = {c: k for it in old.get('news', []) + old.get('advisories', []) for c, k in it.get('kev', {}).items()}
    for it in news + advisories:
        if kev is not None:
            it['kev'] = {c: kev[c] for c in it['cves'] if c in kev}
        else:  # KEV fetch failed: keep what we knew
            it['kev'] = {c: old_kev[c] for c in it['cves'] if c in old_kev}

    linked = sum(1 for n in news if n['advisories'])
    print(f'{news_added} new stories, {adv_added} new advisories; {len(news)} stories kept, '
          f'{linked} correlated with ThreatPROTECT')
    if args.dry_run:
        for a in advisories[:10]:
            print(f'  [{a["published"][:10]}] {a["title"]}  <- {len(a["related"])} stories')
        return

    if not fresh_news and not fresh_adv:
        sys.exit('every source failed:\n' + '\n'.join(errors))

    out = {
        'updated': now.isoformat(timespec='minutes'),
        'edition': edition,
        'errors': errors,
        'news': news,
        'advisories': advisories,
    }
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write('\n')


if __name__ == '__main__':
    main()
