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

    def test_data_or_financial_content_change_stops_publication(self):
        for mutation in ['data', 'content']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                site = self.site(root)
                def corrupt(*args):
                    target = site / ('data/history.json' if mutation == 'data' else 'index.html')
                    target.write_text(target.read_text() + (' ' if mutation == 'data' else '<table>changed</table>'))
                with patch.object(fx, 'build', side_effect=corrupt), self.assertRaises(RuntimeError):
                    ui.rebuild(site)
