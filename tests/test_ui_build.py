"""A UI-only release must never fetch or replace the published observations."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import fx

spec = importlib.util.spec_from_file_location('rebuild_ui', fx.ROOT / 'ops/rebuild_ui.py')
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
FIXTURE = Path(__file__).parent / 'fixtures/history.json'


class UiBuildTests(unittest.TestCase):
    def site(self, root):
        site = Path(root) / 'site'
        data = fx.load_history(FIXTURE)
        fx.build(data, site)
        (site / 'data').mkdir()
        (site / 'data/history.json').write_bytes(FIXTURE.read_bytes())
        return site

    def test_uses_only_existing_observations_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as root, patch.object(fx, 'fetch_rows') as fetch:
            site = self.site(root)
            before = ui.preserved_files(site)
            with patch.dict(ui.os.environ, {'ADSENSE_SLOT': ''}):
                ui.rebuild(site)
                ui.rebuild(site)
            self.assertEqual(ui.preserved_files(site), before)
            fetch.assert_not_called()

    def test_missing_or_empty_history_never_bootstraps(self):
        with tempfile.TemporaryDirectory() as root, patch.object(fx, 'build') as build:
            site = Path(root)
            with self.assertRaises(RuntimeError):
                ui.rebuild(site)
            (site / 'index.html').write_text('existing')
            (site / 'data').mkdir()
            (site / 'data/history.json').write_text(json.dumps(fx.empty_history()))
            with self.assertRaises(RuntimeError):
                ui.rebuild(site)
            build.assert_not_called()

    def test_adds_share_image_to_an_existing_published_site(self):
        with tempfile.TemporaryDirectory() as root, patch.object(fx, 'fetch_rows') as fetch:
            site = self.site(root)
            for asset in ('assets/og.png',):
                (site / asset).unlink()
            before = ui.preserved_files(site)
            with patch.dict(ui.os.environ, {'ADSENSE_SLOT': ''}):
                ui.rebuild(site)
            self.assertEqual(ui.preserved_files(site), before)
            for asset in ('assets/og.png',):
                self.assertEqual((site / asset).read_bytes(), (fx.ROOT / asset).read_bytes())
            fetch.assert_not_called()

    def test_adds_json_ld_to_a_site_published_without_it(self):
        import re
        with tempfile.TemporaryDirectory() as root, patch.object(fx, 'fetch_rows') as fetch:
            site = self.site(root)
            pattern = r'\n<script type="application/ld\+json">.*?</script>'
            for page in site.rglob('*.html'):
                page.write_text(re.sub(pattern, '', page.read_text(), flags=re.S))
            self.assertNotIn('application/ld+json', (site / 'index.html').read_text())
            with patch.dict(ui.os.environ, {'ADSENSE_SLOT': ''}):
                ui.rebuild(site)
            for page in site.rglob('*.html'):
                self.assertEqual(page.read_text().count('<script type="application/ld+json">'), 1)
            fetch.assert_not_called()

    def test_data_or_financial_content_change_stops_publication(self):
        for mutation in ['data', 'content']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                site = self.site(root)
                def corrupt(*args):
                    target = site / ('data/history.json' if mutation == 'data' else 'index.html')
                    target.write_text(target.read_text() + (' ' if mutation == 'data' else '<table>changed</table>'))
                with patch.object(fx, 'build', side_effect=corrupt), self.assertRaises(RuntimeError):
                    ui.rebuild(site)
