"""Offline contracts for observations, exact arithmetic, updates, and published pages."""

from contextlib import redirect_stderr
from datetime import date
from fractions import Fraction
from html.parser import HTMLParser
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import fx


FIXTURE = Path(__file__).parent / "fixtures" / "history.json"
BOUNDARY_FIXTURE = Path(__file__).parent / "fixtures" / "pre_window_response.json"


def boundary_rows(scenario):
    return json.loads(BOUNDARY_FIXTURE.read_text(encoding="utf-8"))[scenario]


def history():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def api_rows(source, start, end):
    return [
        {"date": day, "base": "EUR", "quote": quote, "rate": value}
        for day, quotes in source["rates"].items() if start <= date.fromisoformat(day) <= end
        for quote, value in quotes.items()
    ]


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.text = []
        self.in_head = False
        self.head_titles = 0
        self.head_scripts = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "head":
            self.in_head = True
        elif tag == "title" and self.in_head:
            self.head_titles += 1
        elif tag == "script" and self.in_head:
            self.head_scripts.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False

    def handle_data(self, data):
        self.text.append(data)

    def attrs(self, tag, **matching):
        return [attrs for name, attrs in self.tags
                if name == tag and all(attrs.get(k) == v for k, v in matching.items())]


class ArithmeticTests(unittest.TestCase):
    def test_exact_crosses_and_jpy_100_units(self):
        data = history()
        usd = dict(fx.series(data, "USD"))["2024-02-22"]
        jpy = dict(fx.series(data, "JPY"))["2024-02-22"]
        self.assertIsInstance(usd, Fraction)
        self.assertEqual(usd, Fraction(143212340, 108347))
        self.assertEqual(jpy, Fraction(14321234, 1623456) * 100)
        self.assertEqual(dict(fx.series(data, "EUR"))["2024-02-22"], Fraction("1432.1234"))
        self.assertNotEqual(usd, Fraction(fx.number(usd).replace(",", "")))

    def test_missing_quotes_weekends_and_unobserved_weekday_are_not_filled(self):
        data = history()
        jpy_days = set(dict(fx.series(data, "JPY")))
        self.assertNotIn("2024-03-04", jpy_days)  # KRW exists, JPY does not.
        self.assertNotIn("2024-04-02", jpy_days)  # JPY exists, KRW does not.
        for currency in fx.CURRENCIES:
            days = set(dict(fx.series(data, currency)))
            self.assertNotIn("2024-03-02", days)
            self.assertNotIn("2024-03-03", days)
            self.assertNotIn("2024-03-05", days)
            self.assertTrue(days <= set(data["rates"]))

    def test_month_average_uses_only_observations_and_exact_values(self):
        points = [p for p in fx.series(history(), "USD") if p[0].startswith("2024-02")]
        stats = fx.monthly_stats(points)
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["average"], (Fraction(143212340, 108347) + 2500) / 3)
        self.assertEqual(stats["low"], ("2024-02-28", Fraction(1250)))
        self.assertEqual(stats["high"], ("2024-02-22", Fraction(143212340, 108347)))

    def test_christmas_holidays_do_not_become_observations(self):
        data = fx.empty_history()
        data["rates"] = {
            "2024-12-24": {"KRW": "1500", "USD": "1.2"},
            "2024-12-27": {"KRW": "1600", "USD": "1.2"},
        }
        points = fx.series(fx.validate_history(data), "USD")
        self.assertEqual([day for day, _ in points], ["2024-12-24", "2024-12-27"])
        self.assertEqual(fx.monthly_stats(points)["count"], 2)
        self.assertEqual(Document(fx.chart(points, "휴일 관측")).attrs("line"), [])

    def test_minimum_and_maximum_ties_use_earliest_day(self):
        points = [("2024-03-06", Fraction(5)), ("2024-03-04", Fraction(5)),
                  ("2024-03-01", Fraction(5))]
        stats = fx.monthly_stats(points)
        self.assertEqual(stats["average"], 5)
        self.assertEqual(stats["low"][0], "2024-03-01")
        self.assertEqual(stats["high"][0], "2024-03-01")

    def test_empty_month_has_no_synthetic_statistics(self):
        self.assertEqual(fx.monthly_stats([]), {"count": 0, "average": None, "low": None, "high": None})

    def test_day_compares_actual_previous_observation_after_weekend(self):
        result = fx.comparison([("2024-03-01", Fraction(10)), ("2024-03-04", Fraction(12))], "day")
        self.assertEqual(result, {"date": "2024-03-01", "delta": Fraction(2), "percent": Fraction(20)})

    def test_week_uses_nearest_earlier_observation_and_reports_date(self):
        points = [("2024-02-29", Fraction(10)), ("2024-03-01", Fraction(20)),
                  ("2024-03-05", Fraction(100)), ("2024-03-11", Fraction(30))]
        result = fx.comparison(points, "week")
        self.assertEqual(result, {"date": "2024-03-01", "delta": Fraction(10), "percent": Fraction(50)})

    def test_year_comparison_clamps_leap_day(self):
        points = [("2023-02-28", Fraction(100)), ("2024-02-28", Fraction(110)),
                  ("2024-02-29", Fraction(120))]
        self.assertEqual(fx.comparison(points, "year"),
                         {"date": "2023-02-28", "delta": Fraction(20), "percent": Fraction(20)})

    def test_missing_or_stale_baselines_have_no_comparison(self):
        self.assertIsNone(fx.comparison([], "day"))
        self.assertIsNone(fx.comparison([("2024-03-01", Fraction(10))], "day"))
        self.assertIsNone(fx.comparison([("2024-02-23", Fraction(10)), ("2024-03-11", Fraction(12))], "week"))
        self.assertIsNone(fx.comparison([("2023-02-17", Fraction(10)), ("2024-02-29", Fraction(12))], "year"))

    def test_chart_never_connects_across_missing_calendar_days(self):
        points = [("2024-02-29", Fraction(10)), ("2024-03-01", Fraction(11)),
                  ("2024-03-04", Fraction(12)), ("2024-03-06", Fraction(13))]
        chart = Document(fx.chart(points, "관측 기록"))
        self.assertEqual(len(chart.attrs("circle")), 4)
        self.assertEqual(len(chart.attrs("line")), 1)

    def test_converter_uses_actual_yen_units_and_unrounded_fraction(self):
        data = {"rates": {"2024-02-22": {"KRW": "1432.1234", "JPY": "162.3456", "USD": "1.08"}}}
        html = fx.converter(data, "JPY", "h1")
        doc = Document(html)
        attrs = doc.attrs("option", value="JPY")[0]
        self.assertIn("selected", attrs)
        self.assertEqual(Fraction(int(attrs["data-numerator"]), int(attrs["data-denominator"])),
                         Fraction(14321234, 1623456))
        self.assertEqual([a["value"] for a in doc.attrs("option")], ["USD", "JPY", "EUR"])
        self.assertEqual(doc.attrs("div", role="status")[0]["aria-live"], "polite")
        self.assertEqual(len(doc.attrs("h1", id="converter-title")), 1)
        self.assertIn("100엔은 약", "".join(doc.text))
        self.assertIn("원화를 엔으로 바꾸기", "".join(doc.text))
        self.assertIn("882.14원", "".join(doc.text))


class ValidationTests(unittest.TestCase):
    def test_normalization_preserves_decimal_precision(self):
        data = history()
        self.assertEqual(fx.validate_history(data)["rates"]["2024-02-22"]["KRW"], "1432.1234")

    def test_invalid_rates_rejected(self):
        for value in (True, False, None, [], {}, "NaN", "Infinity", "-1", "0", "1000000000001", "oops"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fx.rate_string(value)

    def test_history_rejects_wrong_schema_source_and_observation_dates(self):
        cases = []
        for key, value in (("schema", 2), ("base", "USD"), ("provider", "OTHER")):
            item = history()
            item[key] = value
            cases.append(item)
        for day in ("2014-12-31", "2024-03-02", "2024-3-01", "2099-01-01"):
            item = fx.empty_history()
            item["rates"][day] = {"KRW": "1000"}
            cases.append(item)
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                fx.validate_history(item)

    def test_api_rejects_malformed_rows_out_of_range_and_weekends(self):
        good = {"date": "2024-03-01", "base": "EUR", "quote": "KRW", "rate": "1400"}
        variants = [None, {}, [None]]
        for key, value in (("base", None), ("base", 12), ("base", "USD"),
                           ("quote", None), ("quote", 12), ("quote", "XYZ"),
                           ("date", "2024-03-02"), ("date", "2024-03-05"), ("rate", 0),
                           ("rate", "not-a-number")):
            variants.append([{**good, key: value}])
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                fx.parse_rows(rows, date(2024, 3, 1), date(2024, 3, 4))

    def test_pre_window_fixture_is_dropped_and_logged_without_relabeling(self):
        log = io.StringIO()
        with redirect_stderr(log):
            parsed = fx.parse_rows(boundary_rows("backfill"), date(2015, 1, 1), date(2015, 1, 9))
        self.assertEqual(set(parsed), {"2015-01-02", "2015-01-09"})
        self.assertEqual(parsed["2015-01-02"], {"KRW": "1330.25", "USD": "1.2"})
        self.assertIn("Dropped 2 pre-window observations before 2015-01-01", log.getvalue())
        self.assertIn("requested 2015-01-01..2015-01-09", log.getvalue())

    def test_malformed_pre_window_rows_are_still_rejected(self):
        row = boundary_rows("backfill")[0]
        for key, value in (("date", "2014-12-xx"), ("base", "USD"), ("quote", None),
                           ("rate", "oops"), ("rate", "NaN"), ("rate", None)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                fx.parse_rows([{**row, key: value}], date(2015, 1, 1), date(2015, 1, 9))

    def test_single_pre_window_date_at_seven_days_is_allowed_for_multiple_quotes(self):
        rows = [{**row, "date": "2014-12-25"} for row in boundary_rows("backfill")[:2]]
        with redirect_stderr(io.StringIO()) as log:
            parsed = fx.parse_rows(rows + boundary_rows("backfill")[2:], date(2015, 1, 1), date(2015, 1, 9))
        self.assertEqual(set(parsed), {"2015-01-02", "2015-01-09"})
        self.assertIn("Dropped 2 pre-window observations", log.getvalue())

    def test_pre_window_date_more_than_seven_days_old_is_rejected(self):
        rows = boundary_rows("backfill")
        rows[0]["date"] = "2014-12-24"
        with self.assertRaisesRegex(ValueError, "more than 7 days before 2015-01-01"):
            fx.parse_rows(rows, date(2015, 1, 1), date(2015, 1, 9))

    def test_multiple_distinct_pre_window_dates_are_rejected_regardless_of_order(self):
        rows = boundary_rows("backfill")
        rows[0]["date"] = "2014-12-30"
        for response in (rows, list(reversed(rows))):
            with self.subTest(response=response), self.assertRaisesRegex(ValueError, "Multiple pre-window dates"):
                fx.parse_rows(response, date(2015, 1, 1), date(2015, 1, 9))

    def test_boundary_rows_do_not_hide_weekend_future_or_nonnumeric_rows(self):
        boundary = boundary_rows("backfill")[:2]
        good = boundary_rows("backfill")[2]
        for fields in ({"date": "2015-01-03"}, {"date": "2015-01-12"}, {"rate": "oops"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                fx.parse_rows(boundary + [{**good, **fields}], date(2015, 1, 1), date(2015, 1, 9))

    def test_api_conflicting_duplicates_rejected_equal_duplicates_allowed(self):
        row = {"date": "2024-03-01", "base": "EUR", "quote": "KRW", "rate": "1400"}
        parsed = fx.parse_rows([row, {**row, "rate": "1400.0"}], date(2024, 3, 1), date(2024, 3, 1))
        self.assertEqual(list(parsed), ["2024-03-01"])
        self.assertEqual(Fraction(parsed["2024-03-01"]["KRW"]), 1400)
        with self.assertRaises(ValueError):
            fx.parse_rows([row, {**row, "rate": "1401"}], date(2024, 3, 1), date(2024, 3, 1))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "history.json"

    def test_bootstrap_accepts_boundary_fixture_without_storing_2014(self):
        with redirect_stderr(io.StringIO()) as log:
            result = fx.update_history(self.path, today=date(2015, 1, 9),
                                       fetcher=lambda start, end: boundary_rows("backfill"))
        stored = fx.load_history(self.path)
        self.assertEqual(set(stored["rates"]), {"2015-01-02", "2015-01-09"})
        self.assertEqual(result["new_days"], 2)
        self.assertEqual(result["latest"], "2015-01-09")
        self.assertIn("Dropped 2 pre-window observations", log.getvalue())

    def test_incremental_holiday_boundary_preserves_older_records_and_is_idempotent(self):
        source = fx.empty_history()
        source["rates"] = {
            "2024-12-31": {"KRW": "1500", "USD": "1.1"},
            "2025-01-08": {"KRW": "1510", "USD": "1.2"},
        }
        fx.write_history(self.path, source)
        calls = []

        def fetch(start, end):
            calls.append((start, end))
            return boundary_rows("incremental")

        with redirect_stderr(io.StringIO()) as log:
            result = fx.update_history(self.path, today=date(2025, 1, 10), fetcher=fetch)
        self.assertEqual(calls, [(date(2025, 1, 1), date(2025, 1, 10))])
        stored = fx.load_history(self.path)
        self.assertEqual(stored["rates"]["2024-12-31"], source["rates"]["2024-12-31"])
        self.assertNotIn("2025-01-01", stored["rates"])
        self.assertEqual(stored["rates"]["2025-01-08"]["KRW"], "1511")
        self.assertEqual(result["new_days"], 1)
        self.assertEqual(result["corrected_days"], 1)
        self.assertIn("Dropped 2 pre-window observations", log.getvalue())
        before = self.path.read_bytes()
        timestamp = self.path.stat().st_mtime_ns
        with redirect_stderr(io.StringIO()):
            repeated = fx.update_history(self.path, today=date(2025, 1, 11), fetcher=fetch)
        self.assertEqual(calls[-1], (date(2025, 1, 3), date(2025, 1, 11)))
        self.assertFalse(repeated["changed"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)

    def test_only_pre_window_rows_do_not_bypass_empty_response_guard(self):
        fx.write_history(self.path, history())
        before = self.path.read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaisesRegex(ValueError, "Empty response"):
            fx.update_history(self.path, today=date(2025, 1, 13),
                              fetcher=lambda start, end: boundary_rows("incremental")[:2])
        self.assertEqual(self.path.read_bytes(), before)

    def test_unexpected_pre_window_dates_fail_update_without_changing_history(self):
        fx.write_history(self.path, history())
        before = self.path.read_bytes()
        # Incremental from = 2025-01-03. First row would otherwise correct history.
        valid = {"date": "2025-01-10", "base": "EUR", "quote": "KRW", "rate": "9999"}
        for days in (("2025-01-01", "2025-01-02"), ("2024-12-26",)):
            rows = [valid] + [{**valid, "date": day} for day in days]
            with self.subTest(days=days), self.assertRaisesRegex(ValueError, "pre-window|Pre-window"):
                fx.update_history(self.path, today=date(2025, 1, 13), fetcher=lambda start, end: rows)
            self.assertEqual(self.path.read_bytes(), before)

    def test_bootstrap_fetches_calendar_year_chunks_from_2015(self):
        source = fx.empty_history()
        source["rates"] = {day: {"KRW": "1500", "USD": "1.2"}
                           for day in ("2015-01-02", "2016-01-04", "2017-01-02")}
        calls = []

        def fetch(start, end):
            calls.append((start, end))
            return api_rows(source, start, end)

        result = fx.update_history(self.path, today=date(2017, 1, 6), fetcher=fetch)
        self.assertEqual(calls, [(date(2015, 1, 1), date(2015, 12, 31)),
                                 (date(2016, 1, 1), date(2016, 12, 31)),
                                 (date(2017, 1, 1), date(2017, 1, 6))])
        self.assertEqual(result["new_days"], 3)
        self.assertTrue(result["changed"])
        self.assertEqual(fx.load_history(self.path), source)

    def test_weekend_incremental_overlap_is_idempotent_without_rewrite(self):
        fx.write_history(self.path, history())
        before = self.path.read_bytes()
        timestamp = self.path.stat().st_mtime_ns
        calls = []

        def fetch(start, end):
            calls.append((start, end))
            return api_rows(history(), start, end)

        for today in (date(2025, 1, 11), date(2025, 1, 12)):
            result = fx.update_history(self.path, today=today, fetcher=fetch)
            self.assertFalse(result["changed"])
            self.assertEqual(result["new_days"], 0)
            self.assertEqual(result["latest"], "2025-01-10")
        self.assertEqual(calls[0], (date(2025, 1, 3), date(2025, 1, 11)))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)

    def test_incremental_merges_corrections_and_new_observations(self):
        fx.write_history(self.path, history())
        source = history()
        source["rates"]["2025-01-08"]["KRW"] = "1511.123456"
        source["rates"]["2025-01-13"] = {"KRW": "1530", "USD": "1.3"}
        result = fx.update_history(self.path, today=date(2025, 1, 13),
                                   fetcher=lambda start, end: api_rows(source, start, end))
        self.assertEqual(result, {"changed": True, "new_days": 1, "corrected_days": 1, "latest": "2025-01-13"})
        self.assertEqual(fx.load_history(self.path), source)
        self.assertNotIn("2025-01-11", fx.load_history(self.path)["rates"])

    def test_failed_later_chunk_never_writes_partial_backfill(self):
        fx.write_history(self.path, history())
        before = self.path.read_bytes()
        calls = []

        def fail_later(start, end):
            calls.append(start)
            if len(calls) == 2:
                raise OSError("simulated upstream outage")
            return [{"date": "2015-01-02", "base": "EUR", "quote": "KRW", "rate": "1400"}]

        with self.assertRaises(OSError):
            fx.update_history(self.path, today=date(2025, 1, 13), backfill=True, fetcher=fail_later)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_or_suspicious_empty_response_preserves_history(self):
        fx.write_history(self.path, history())
        before = self.path.read_bytes()
        for rows in ([], [{"date": "2025-01-11", "base": "EUR", "quote": "KRW", "rate": "1500"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                fx.update_history(self.path, today=date(2025, 1, 13), fetcher=lambda start, end: rows)
            self.assertEqual(self.path.read_bytes(), before)

    def test_failed_atomic_replace_preserves_original_and_cleans_temporary_file(self):
        fx.write_history(self.path, history())
        before = self.path.read_bytes()
        changed = history()
        changed["rates"]["2025-01-10"]["KRW"] = "1521"
        with patch.object(Path, "replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                fx.write_history(self.path, changed)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


class PageTests(unittest.TestCase):
    def test_month_archive_preserves_all_links_and_only_opens_latest_year(self):
        data = history()
        data['rates']['2023-12-29'] = next(iter(data['rates'].values())).copy()
        body = fx.currency_page(data, 'USD')
        doc = Document(body)
        years = sorted({day[:4] for day, _ in fx.series(data, 'USD')}, reverse=True)
        months = sorted({day[:7] for day, _ in fx.series(data, 'USD')}, reverse=True)
        disclosures = doc.attrs('details')
        self.assertEqual(len(disclosures), len(years))
        self.assertIn('open', disclosures[0])
        self.assertTrue(all('open' not in attrs for attrs in disclosures[1:]))
        month_links = [a['href'] for a in doc.attrs('a') if a['href'].count('/') == 3]
        self.assertEqual(month_links, [f'/usd/{month}/' for month in months])

    def test_month_route_keeps_parent_currency_selected_and_company_return_link(self):
        doc = Document(fx.shell('월별 기록', 'jpy/2024-02/', ''))
        current = [a for a in doc.attrs('a', **{'aria-current': 'page'}) if a['href'].startswith('/')]
        self.assertEqual(current, [{'href': '/jpy/', 'aria-current': 'page'}])
        # Common header marks this service; header menu + footer each link back to the company list.
        self.assertEqual(doc.attrs('a', **{'aria-current': 'page', 'href': 'https://fx.ditoaxis.com/'}), [{'href': 'https://fx.ditoaxis.com/', 'aria-current': 'page'}])
        self.assertEqual(len(doc.attrs('a', href='https://ditoaxis.com/#products')), 2)
        self.assertEqual(len(doc.attrs('nav', **{'class': 'dx-bar'})), 1)
        self.assertNotIn('service-family', fx.shell('월별 기록', 'jpy/2024-02/', ''))
        self.assertEqual(doc.attrs('main', id='main')[0].get('tabindex'), '-1')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "site"

    def test_all_page_titles_canonical_og_and_sitemap_agree(self):
        count = fx.build(history(), self.output)
        files = list(self.output.rglob("*.html"))
        self.assertEqual(count, len(files))
        expected_urls = set()
        titles = set()
        for path in files:
            with self.subTest(path=path):
                relative = path.relative_to(self.output).as_posix()
                url = fx.SITE_URL + "/" + (relative.removesuffix("index.html") if path.name == "index.html" else relative)
                doc = Document(path.read_text(encoding="utf-8"))
                if not doc.attrs("meta", name="robots", content="noindex,follow"):
                    expected_urls.add(url)
                self.assertEqual(doc.attrs("link", rel="canonical"), [{"rel": "canonical", "href": url}])
                self.assertEqual(doc.attrs("meta", property="og:url")[0]["content"], url)
                title = doc.attrs("meta", property="og:title")[0]["content"]
                self.assertTrue(title.strip())
                titles.add(title)
                self.assertEqual(doc.head_titles, 1)
                self.assertIn(title + " | 환율 신호등", doc.text)
                self.assertTrue(doc.attrs("meta", name="description")[0]["content"])
                image = fx.SITE_URL + "/assets/og.png"
                for prop, value in (("og:image", image), ("og:image:width", "1200"),
                                    ("og:image:height", "630"), ("og:image:type", "image/png")):
                    self.assertEqual(doc.attrs("meta", property=prop),
                                     [{"property": prop, "content": value}])
                self.assertTrue(doc.attrs("meta", property="og:image:alt")[0]["content"])
                for name, value in (("twitter:card", "summary_large_image"),
                                    ("twitter:title", title), ("twitter:image", image),
                                    ("twitter:description", doc.attrs("meta", name="description")[0]["content"])):
                    self.assertEqual(doc.attrs("meta", name=name),
                                     [{"name": name, "content": value}])
        self.assertEqual(len(titles), len(files))
        root = ET.fromstring((self.output / "sitemap.xml").read_text())
        urls = [node.text for node in root.findall("{*}url/{*}loc")]
        self.assertEqual(set(urls), expected_urls)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertIn("Sitemap: https://fx.ditoaxis.com/sitemap.xml", (self.output / "robots.txt").read_text())
        self.assertEqual((self.output / "CNAME").read_text(), "fx.ditoaxis.com\n")

    def test_every_generated_html_loads_shared_analytics_once_in_head(self):
        url = "https://ditoaxis.com/m.js"
        tag = '<script defer src="https://ditoaxis.com/m.js"></script>'
        expected = [{"defer": None, "src": url}]
        for label, data, slot in (("empty", fx.empty_history(), ""),
                                  ("fixture", history(), ""),
                                  ("ads", history(), "1234567890")):
            with self.subTest(build=label):
                count = fx.build(data, self.output, slot=slot)
                pages = list(self.output.rglob("*.html"))
                self.assertEqual(len(pages), count)
                self.assertIn(self.output / "404.html", pages)
                for page in pages:
                    with self.subTest(page=page.relative_to(self.output)):
                        source = page.read_text(encoding="utf-8")
                        doc = Document(source)
                        self.assertEqual(source.count(tag), 1)
                        self.assertEqual(doc.attrs("script", src=url), expected)
                        self.assertEqual([attrs for attrs in doc.head_scripts
                                          if attrs.get("src") == url], expected)

    def test_every_generated_html_starts_head_with_csp_meta(self):
        fx.build(history(), self.output, slot="1234567890")
        for page in self.output.rglob("*.html"):
            with self.subTest(page=page.relative_to(self.output)):
                head = page.read_text(encoding="utf-8").split("<head>", 1)[1]
                self.assertTrue(head.startswith('<meta http-equiv="Content-Security-Policy" content="default-src \'self\';'), head[:120])
                csp = head.split('content="', 1)[1].split('"', 1)[0]
                for origin in ("https://cdn.jsdelivr.net", "https://ditoaxis.com/m.js", "https://static.cloudflareinsights.com",
                               "https://pagead2.googlesyndication.com"):
                    self.assertIn(origin, csp)
                self.assertNotIn("frame-ancestors", csp)
                self.assertNotIn("report-", csp)

    def test_not_found_page_and_local_assets_are_available(self):
        fx.build(history(), self.output)
        not_found = Document((self.output / "404.html").read_text())
        self.assertTrue(not_found.attrs("meta", name="robots", content="noindex,follow"))
        self.assertTrue(not_found.attrs("a", href="/"))
        self.assertIn("홈으로 돌아가기", not_found.text)
        self.assertNotIn("/404.html", (self.output / "sitemap.xml").read_text())
        for path in self.output.rglob("*.html"):
            doc = Document(path.read_text())
            self.assertEqual(doc.attrs("link", rel="icon")[0]["href"], "/assets/favicon.svg")
            self.assertEqual(doc.attrs("link", rel="stylesheet")[-1]["href"], "/assets/site.css")
            for attrs in doc.attrs("link") + doc.attrs("script"):
                url = attrs.get("href", attrs.get("src", ""))
                if url.startswith("/"):
                    self.assertTrue((self.output / url.lstrip("/")).is_file(), url)
        icon = ET.fromstring((self.output / "assets" / "favicon.svg").read_text())
        self.assertEqual(icon.tag, "{http://www.w3.org/2000/svg}svg")
        png = (self.output / "assets/og.png").read_bytes()
        self.assertEqual(png, (fx.ROOT / "assets/og.png").read_bytes())
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")),
                         (1200, 630))


    def test_month_pages_show_exact_observed_dates_only(self):
        fx.build(history(), self.output)
        doc = Document((self.output / "jpy" / "2024-03" / "index.html").read_text())
        self.assertIn("2024년 3월 엔화 평균 환율", doc.text)
        self.assertEqual({row["data-date"] for row in doc.attrs("tr") if "data-date" in row},
                         {"2024-03-01", "2024-03-06"})
        for currency in fx.CURRENCIES:
            self.assertFalse((self.output / currency.lower() / "2024-04").exists())

    def test_empty_state_no_fabricated_months_or_indexable_rate_pages(self):
        fx.build(fx.empty_history(), self.output)
        home = (self.output / "index.html").read_text()
        self.assertIn("첫 관측 자료를 기다리고 있어요", home)
        self.assertIn('content="noindex,follow"', home)
        for currency in fx.CURRENCIES:
            page = (self.output / currency.lower() / "index.html").read_text()
            self.assertIn("첫 관측 자료를 기다리고 있어요", page)
            self.assertNotIn("data-converter", page)
            self.assertNotIn('id="chart-data"', page)
        root = ET.fromstring((self.output / "sitemap.xml").read_text())
        urls = {node.text for node in root.findall("{*}url/{*}loc")}
        self.assertEqual(urls, {fx.SITE_URL + "/about/", fx.SITE_URL + "/privacy/"})

    def test_rebuild_removes_orphan_months_preserves_history_and_git(self):
        fx.build(history(), self.output)
        (self.output / "data").mkdir()
        saved = self.output / "data" / "history.json"
        saved.write_text("persisted observations")
        marker = self.output / ".git"
        marker.write_text("worktree marker")
        (self.output / "ads.txt").write_text("old generated subdomain ad record")
        fx.build(fx.empty_history(), self.output)
        self.assertEqual(saved.read_text(), "persisted observations")
        self.assertEqual(marker.read_text(), "worktree marker")
        self.assertEqual(len(list(self.output.rglob("index.html"))), 8)
        self.assertFalse((self.output / "jpy" / "2024-03").exists())
        self.assertFalse((self.output / "ads.txt").exists())

    def test_optional_adsense_unit_omitted_by_default_loader_retained(self):
        fx.build(history(), self.output)
        for page in self.output.rglob("index.html"):
            source = page.read_text()
            doc = Document(source)
            self.assertEqual(len([a for a in doc.attrs("script") if "adsbygoogle.js?client=ca-pub-4557219410513767" in a.get("src", "")]), 1)
            self.assertEqual(doc.attrs("ins"), [])
            self.assertNotIn("data-ad-slot", source)
        fx.build(history(), self.output, slot="1234567890")
        for page in self.output.rglob("index.html"):
            units = Document(page.read_text()).attrs("ins")
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0]["data-ad-slot"], "1234567890")

    def test_invalid_ad_slot_rejected_before_touching_output(self):
        with self.assertRaises(ValueError):
            fx.build(history(), self.output, slot='123" onclick="bad')
        self.assertFalse(self.output.exists())

    def test_build_deterministic_and_cli_reads_optional_slot_environment(self):
        fx.build(history(), self.output)
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        with patch.dict(os.environ, {"ADSENSE_SLOT": ""}):
            self.assertEqual(fx.main(["build", "--history", str(FIXTURE), "--output", str(self.output)]), 0)
        after = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        with patch.dict(os.environ, {"ADSENSE_SLOT": "9876543210"}):
            self.assertEqual(fx.main(["build", "--history", str(FIXTURE), "--output", str(self.output)]), 0)
        self.assertIn('data-ad-slot="9876543210"', (self.output / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
