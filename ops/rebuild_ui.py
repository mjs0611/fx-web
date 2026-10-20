"""Rebuild existing published observations only; fail closed on any data change."""
import hashlib
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fx


def preserved_files(site):
    return {str(p.relative_to(site)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in site.rglob('*') if p.is_file() and '.git' not in p.relative_to(site).parts
            and p.suffix != '.html' and str(p.relative_to(site)) not in
            ('assets/site.css', 'assets/site.js', 'assets/og.png')}


def financial_content(site):
    # Exact published table/chart/amount/converter/prose/advertising markup.
    patterns = [r'<table\b.*?</table>', r'<script[^>]*id="chart-data".*?</script>',
                r'<p class="rate".*?</p>', r'<section class="converter"[^>]*>',
                r'<article class="prose".*?</article>', r'<ins\b[^>]*>']
    return {str(p.relative_to(site)): [re.findall(pattern, p.read_text(), re.S) for pattern in patterns]
            for p in site.rglob('*.html')}


def rebuild(site=fx.ROOT / 'site'):
    site = Path(site)
    history_path = site / 'data/history.json'
    if not history_path.is_file() or not (site / 'index.html').is_file():
        raise RuntimeError('A restored published site and history are required; no bootstrap in UI-only mode')
    history = fx.load_history(history_path)
    if not history['rates']:
        raise RuntimeError('Published observations are empty; refusing UI-only deployment')
    before = preserved_files(site)
    content = financial_content(site)
    fx.build(history, site, os.environ.get('ADSENSE_SLOT', ''))
    if preserved_files(site) != before:
        raise RuntimeError('Published data, domain or other non-UI files changed; refusing publication')
    if financial_content(site) != content:
        raise RuntimeError('Published financial or advertising content changed; refusing publication')
    print(f'UI-only build verified: {len(content)} pages; published data and financial content unchanged')


if __name__ == '__main__':
    rebuild()
