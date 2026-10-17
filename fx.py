#!/usr/bin/env python3
"""ECB observations -> exact KRW crosses -> deterministic static pages (stdlib only)."""
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from html import escape as e
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SITE_URL = "https://fx.ditoaxis.com"
API = "https://api.frankfurter.dev/v2/providers/ecb/rates"
START = date(2015, 1, 1)
CLIENT = "ca-pub-4557219410513767"
# name, displayed foreign units, singular input unit
CURRENCIES = {
    "USD": ("달러", 1, "달러"), "JPY": ("엔화", 100, "엔"),
    "EUR": ("유로", 1, "유로"), "CNY": ("위안화", 1, "위안"),
    "GBP": ("파운드", 1, "파운드"),
}
QUOTES = {"KRW", "USD", "JPY", "CNY", "GBP"}
ECB_URL = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
TERMS_URL = "https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html"


def iso(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"Invalid observation date: {value!r}")
    return date.fromisoformat(value)


def rate_string(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Rate must be a positive finite number")
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError("Invalid rate") from exc
    if not number.is_finite() or number <= 0 or number > Decimal("1e12"):
        raise ValueError("Rate must be positive, finite and at most 1e12")
    return format(number, "f")


def empty_history() -> dict:
    return {"schema": 1, "base": "EUR", "provider": "ECB", "rates": {}}


def validate_history(history: dict) -> dict:
    if not isinstance(history, dict) or any(history.get(k) != v for k, v in
            (("schema", 1), ("base", "EUR"), ("provider", "ECB"))):
        raise ValueError("Expected schema 1, base EUR, provider ECB")
    rates = history.get("rates")
    if not isinstance(rates, dict):
        raise ValueError("History rates must be an object")
    clean = empty_history()
    today = datetime.now(timezone.utc).date()
    for day, quotes in sorted(rates.items()):
        observed = iso(day)
        if observed < START or observed > today or observed.weekday() >= 5:
            raise ValueError(f"Invalid ECB observation day: {day}")
        if not isinstance(quotes, dict) or not quotes or not set(quotes) <= QUOTES:
            raise ValueError(f"Invalid EUR quotes on {day}")
        clean["rates"][day] = {c: rate_string(v) for c, v in sorted(quotes.items())}
    return clean


def load_history(path: Path) -> dict:
    if not path.exists():
        return empty_history()
    return validate_history(json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal))


def write_history(path: Path, history: dict) -> None:
    """Replace only after every response has validated; preserve the old file on failure."""
    history = validate_history(history)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False) as out:
        temporary = Path(out.name)
        out.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_rows(start: date, end: date) -> list:
    params = {"base": "EUR", "quotes": ",".join(sorted(QUOTES)),
              "from": start.isoformat(), "to": end.isoformat()}
    request = Request(API + "?" + urlencode(params), headers={
        "Accept": "application/json", "User-Agent": "fx-web/1.0 (fx.ditoaxis.com)"})
    with urlopen(request, timeout=45) as response:
        return json.load(response, parse_float=Decimal)


def parse_rows(rows: list, start: date, end: date) -> dict:
    """Validate ECB quotes and omit the API's pre-window boundary observations."""
    if not isinstance(rows, list):
        raise ValueError("Expected a Frankfurter v2 array")
    result = {}
    dropped = 0
    pre_window_day = None
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("base"), str)
                or row["base"].upper() != "EUR"):
            raise ValueError("Expected EUR base in every API row")
        day = row.get("date")
        observed = iso(day)
        if observed > end or (observed >= start and observed.weekday() >= 5):
            raise ValueError(f"Out-of-range or weekend observation: {day}")
        if not isinstance(row.get("quote"), str):
            raise ValueError("Expected a quote currency code")
        quote = row["quote"].upper()
        if quote not in QUOTES:
            raise ValueError(f"Unexpected quote: {quote}")
        value = rate_string(row.get("rate"))
        # Holiday/weekend starts can include the preceding observation. Validate
        # its fields, but never relabel, persist or merge it outside this window.
        if observed < start:
            if (start - observed).days > 7:
                raise ValueError(f"Pre-window observation {day} is more than 7 days before {start}")
            if pre_window_day is not None and observed != pre_window_day:
                raise ValueError(f"Multiple pre-window dates before {start}: {pre_window_day}, {day}")
            pre_window_day = observed
            dropped += 1
            continue
        previous = result.setdefault(day, {}).get(quote)
        if previous is not None and Decimal(previous) != Decimal(value):
            raise ValueError(f"Conflicting duplicate observation: {day}/{quote}")
        result[day][quote] = value
    if dropped:
        print(f"fx-web: Dropped {dropped} pre-window observations before {start} "
              f"(requested {start}..{end})", file=sys.stderr)
    return result


def update_history(path: Path, *, today: date | None = None, backfill=False,
                   fetcher=fetch_rows) -> dict:
    today = today or datetime.now(timezone.utc).date()
    old = load_history(path)
    dates = sorted(old["rates"])
    # Re-read an overlap for provider corrections and late arriving observations.
    start = START if backfill or not dates else max(START, iso(dates[-1]) - timedelta(days=7))
    if today < start or (dates and today < iso(dates[-1])):
        raise ValueError("Update end precedes stored history")
    merged = {d: dict(q) for d, q in old["rates"].items()}
    cursor = start
    while cursor <= today:
        end = min(today, date(cursor.year, 12, 31))
        fetched = parse_rows(fetcher(cursor, end), cursor, end)
        if not fetched and (end - cursor).days >= 7:
            raise ValueError(f"Empty response for {cursor}..{end}; retained history")
        for day, quotes in fetched.items():
            merged.setdefault(day, {}).update(quotes)
        cursor = end + timedelta(days=1)
    new = validate_history({**empty_history(), "rates": merged})
    changed = new != old
    if changed:
        write_history(path, new)
    return {"changed": changed, "new_days": len(set(merged) - set(old["rates"])),
            "corrected_days": sum(merged[d] != old["rates"][d] for d in old["rates"]),
            "latest": max(merged, default=None)}


def series(history: dict, currency: str) -> list[tuple[str, Fraction]]:
    multiplier = CURRENCIES[currency][1]
    points = []
    for day, quotes in sorted(history["rates"].items()):
        if "KRW" not in quotes or (currency != "EUR" and currency not in quotes):
            continue
        denominator = Fraction(quotes[currency]) if currency != "EUR" else Fraction(1)
        points.append((day, Fraction(quotes["KRW"]) / denominator * multiplier))
    return points


def monthly_stats(points: list[tuple[str, Fraction]]) -> dict:
    if not points:
        return {"count": 0, "average": None, "low": None, "high": None}
    ordered = sorted(points)
    return {"count": len(points), "average": sum(v for _, v in points) / len(points),
            "low": min(ordered, key=lambda p: p[1]), "high": max(ordered, key=lambda p: p[1])}


def comparison(points, period: str):
    if len(points) < 2:
        return None
    latest_day, latest = points[-1]
    current = iso(latest_day)
    if period == "day":
        baseline = points[-2]
    else:
        if period == "week":
            target = current - timedelta(days=7)
        elif period == "year":
            target = current.replace(year=current.year - 1,
                                     day=min(current.day, calendar.monthrange(current.year - 1, current.month)[1]))
        else:
            raise ValueError("Unknown comparison period")
        # Weekend/holiday comparison uses a labeled actual date, not a new observation.
        candidates = [p for p in points if target - timedelta(days=7) <= iso(p[0]) <= target]
        if not candidates:
            return None
        baseline = candidates[-1]
    return {"date": baseline[0], "delta": latest - baseline[1],
            "percent": (latest / baseline[1] - 1) * 100}


def number(value: Fraction, signed=False) -> str:
    with localcontext() as ctx:
        ctx.prec = 40
        amount = Decimal(value.numerator) / Decimal(value.denominator)
        # Avoid confusing -0.00 after rounding solely for display.
        amount = amount.quantize(Decimal(".01"))
        if amount == 0:
            amount = abs(amount)
        return format(amount, "+,.2f" if signed else ",.2f")


def ko_day(day: str) -> str:
    value = iso(day)
    return f"{value.year}년 {value.month}월 {value.day}일"


def ko_month(month: str) -> str:
    return f"{int(month[:4])}년 {int(month[5:])}월"


def delta_cell(value) -> str:
    if value is None:
        return '<span class="muted">비교 자료 대기</span>'
    direction = "up" if value["delta"] > 0 else "down" if value["delta"] < 0 else "flat"
    return (f'<span class="{direction}">{number(value["percent"], True)}%</span>'
            f'<small>{number(value["delta"], True)}원</small>'
            f'<small>{e(value["date"])} 기준</small>')


def chart(points, label: str) -> str:
    if not points:
        return '<p class="empty">관측 자료가 쌓이면 그래프를 볼 수 있어요.</p>'
    first, last = iso(points[0][0]), iso(points[-1][0])
    values = [float(v) for _, v in points]
    low, high = min(values), max(values)
    spread = high - low or max(high * .01, .01)
    xy = [(20 + (iso(d) - first).days / max((last - first).days, 1) * 860,
           210 - (float(v) - low) / spread * 180) for d, v in points]
    # No interpolated observations or connecting lines over missing calendar days.
    lines = ''.join(f'<line x1="{xy[i-1][0]:.2f}" y1="{xy[i-1][1]:.2f}" '
                    f'x2="{xy[i][0]:.2f}" y2="{xy[i][1]:.2f}"/>'
                    for i in range(1, len(points)) if (iso(points[i][0]) - iso(points[i-1][0])).days == 1)
    dots = ''.join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3"><title>{day}: {number(v)}원</title></circle>'
                   for (day, v), (x, y) in zip(points, xy))
    return (f'<div class="chart-scale"><span>최고 {number(max(v for _, v in points))}원</span>'
            f'<span>최저 {number(min(v for _, v in points))}원</span></div>'
            f'<svg class="chart" viewBox="0 0 900 240" preserveAspectRatio="none" role="img" aria-label="{e(label)}">'
            f'<title>{e(label)} · {points[0][0]}~{points[-1][0]} · {len(points)}개 관측</title>'
            '<path class="grid" d="M20 30H880M20 120H880M20 210H880"/>'
            f'<g class="observations">{lines}{dots}</g></svg>'
            f'<div class="chart-scale"><span>{points[0][0]}</span><span>{points[-1][0]}</span></div>')


def daily_table(points, unit: str) -> str:
    if not points:
        return '<p class="empty">관측 자료를 기다리고 있어요.</p>'
    rows = ''.join(f'<tr data-date="{day}"><th scope="row"><time datetime="{day}">{day}</time></th>'
                   f'<td>{number(value)}원</td></tr>' for day, value in reversed(points))
    return (f'<table class="daily"><caption>{e(unit)} 기준 · 관측한 날짜만 표시해요</caption>'
            '<thead><tr><th scope="col">관측일</th><th scope="col">원화 환율</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def converter(currency: str, points) -> str:
    if not points:
        return '<section><h2>원화로 계산하기</h2><p class="empty">환율 자료가 들어오면 계산할 수 있어요.</p></section>'
    day, value = points[-1]
    unit = CURRENCIES[currency][2]
    # JS gets the unrounded fraction, including JPY's divisor; input is real foreign units.
    rate = value / CURRENCIES[currency][1]
    return f'''<section class="converter" data-converter data-numerator="{rate.numerator}" data-denominator="{rate.denominator}" data-currency="{currency}">
<h2>원화로 계산하기</h2><p class="muted">{ko_day(day)} 참고 환율로 계산해요.</p>
<div class="converter-fields"><div><label for="amount">금액</label><input id="amount" type="number" inputmode="decimal" min="0" max="1000000000000" step="any" value="100" disabled></div>
<div><label for="direction">계산 방향</label><select id="direction" disabled><option value="to-krw">{unit} → 원</option><option value="from-krw">원 → {unit}</option></select></div></div>
<output id="conversion" aria-live="polite">계산기를 준비하고 있어요.</output>
<p class="muted">수수료와 환율 우대는 포함하지 않아요. {'엔 금액을 입력해요. 100엔 표시 환율을 100으로 나눠 계산해요.' if currency == 'JPY' else ''}</p>
<noscript><p>계산기를 쓰려면 자바스크립트를 켜주세요. 1{unit} = {number(rate)}원이에요.</p></noscript></section>'''


ABOUT = f'''<article class="prose"><h1>환율을 모으는 기준</h1>
<h2>하루 한 번 발표하는 참고 환율</h2><p><a href="https://frankfurter.dev/">Frankfurter</a>의 ECB 전용 API에서
<a href="{ECB_URL}">유럽중앙은행(ECB) 기준 환율</a>을 받아요. 은행에서 환전할 때 적용하는 환율이나 실시간 시세가 아니에요.
ECB는 보통 영업일 16:00 중부유럽 시간 무렵에 발표해요. 발표와 수집 사이에는 차이가 있을 수 있어요.</p>
<h2>원화 환율 계산</h2><p>원자료는 1EUR당 각 통화 금액이에요. 같은 관측일의 EUR→KRW를 EUR→외화로 나누면 외화 1단위의 원화 금액이 나와요.
엔화는 여기에 100을 곱해 100엔 기준으로 보여줘요. 유로는 EUR→KRW 값을 그대로 사용해요.</p>
<p>원자료의 소수 자릿수를 보존하고, 계산 중간에는 표시용 반올림을 하지 않아요. 표에서는 소수 둘째 자리까지 보여줘요.
원화 환산·증감률·월평균·그래프는 운영자가 계산한 가공 정보이며 ECB가 직접 발표한 값이 아니에요.</p>
<h2>빈 날짜와 비교 기준</h2><p>2015년부터 관측 자료를 모아요. 주말·휴일과 자료가 빠진 날짜에는 값을 만들거나 앞선 값을 채우지 않아요.
최신 환율에도 실제 관측일을 붙여요. 자료가 없는 날짜를 휴일이라고 단정하지 않아요.</p>
<p>전일 비교는 직전 관측일 기준이에요. 1주 전은 7일 전, 1년 전은 전년 같은 날짜를 기준으로 해요(2월 29일은 전년 2월 28일).
그날 관측이 없으면 그 이전 7일 안의 가장 가까운 관측을 쓰고, 실제 비교일을 표시해요. 이 범위에도 자료가 없으면 비교를 보류해요.</p>
<h2>월평균과 그래프</h2><p>월평균은 해당 월에 수집한 관측값의 산술평균이에요. 달력의 모든 날짜로 나누지 않아요.
최저·최고가 여러 번이면 첫 관측일을 표시해요. 월이 지났어도 원자료가 빠질 수 있어 관측 수와 수집 범위를 함께 보여줘요.
그래프의 점은 실제 관측이며 빈 날짜 사이를 선으로 잇지 않아요. 1개월·3개월·1년 범위는 마지막 관측일부터 30일·90일·365일이에요.</p>
<h2>출처와 재사용</h2><p>자료 제공: Frankfurter / European Central Bank. 원자료는 <a href="{ECB_URL}">ECB 웹사이트에서 무료로 받을 수 있어요</a>.
<a href="{TERMS_URL}">ECB 재사용 조건과 면책 안내</a>에 따라 출처를 밝히고, 원자료를 정확히 전달하며, 가공 여부를 표시해요.
정보를 유료 문서에 넣어 재배포한다면 구매 전과 자료 이용 때마다 원자료가 무료라는 점을 알려야 해요. 상업적 링크는 ECB 페이지를 프레임 안에 넣지 않고 열어야 해요.</p>
<h2>운영과 문의</h2><p>운영자는 디토엑시스예요. 자료에 문제가 있으면 <a href="mailto:help.ditoaxis@gmail.com">help.ditoaxis@gmail.com</a>으로 알려주세요.</p>
<p>이 사이트는 정보 제공용입니다. 실제 거래 조건은 이용하는 금융기관에서 확인해야 합니다.</p></article>'''

PRIVACY = '''<article class="prose"><h1>개인정보처리방침</h1>
<p>운영자: 디토엑시스 · 문의: <a href="mailto:help.ditoaxis@gmail.com">help.ditoaxis@gmail.com</a></p>
<h2>계산기와 접속 정보</h2><p>이 사이트는 회원가입을 받지 않습니다. 계산기에 입력한 금액은 브라우저 안에서 계산하며 운영자 서버로 보내거나 별도 저장하지 않습니다.
사이트는 GitHub Pages에서 제공합니다. 호스팅 제공자는 서비스 운영과 보안을 위해 IP 주소 등 접속 정보를 처리할 수 있습니다.
자세한 내용은 <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub 개인정보처리방침</a>에서 확인할 수 있습니다.</p>
<h2>Google AdSense</h2><p>이 사이트는 Google AdSense 광고 스크립트를 사용합니다. Google과 광고 파트너는 광고 제공·측정 및 개인 맞춤 광고를 위해 쿠키, IP 주소, 기기·브라우저 정보 등을 처리할 수 있습니다.
광고 단위가 표시되지 않아도 광고 스크립트 요청은 발생할 수 있습니다.
<a href="https://policies.google.com/technologies/partner-sites">Google의 파트너 사이트 정보 사용 안내</a>와
<a href="https://policies.google.com/privacy">Google 개인정보처리방침</a>에서 처리 목적·보관·권리 행사 방법을 확인할 수 있습니다.</p>
<p><a href="https://myadcenter.google.com/">Google 광고 설정</a>에서 개인 맞춤 광고를 관리하거나 브라우저 설정에서 쿠키를 차단·삭제할 수 있습니다.</p>
<h2>문의 정보</h2><p>이메일 문의를 보내면 발신 주소와 문의 내용을 답변 목적으로 처리하며, 목적 달성 후 불필요한 정보를 삭제합니다. 열람·삭제 요청은 위 문의 주소로 보낼 수 있습니다.</p>
</article>'''


def shell(title: str, path: str, body: str, slot="", noindex=False) -> str:
    canonical = SITE_URL + "/" + path
    description = title + ". ECB 참고 환율의 실제 관측일과 원화 환산 기록을 확인해요."
    links = ''.join(f'<a href="/{c.lower()}/"'+ (' aria-current="page"' if path == c.lower()+'/' else '') + f'>{c}</a>' for c in CURRENCIES)
    ad = (f'<aside class="ad-slot" aria-label="광고"><p>광고</p><ins class="adsbygoogle" '
          f'data-ad-client="{CLIENT}" data-ad-slot="{e(slot)}" data-ad-format="auto" '
          'data-full-width-responsive="true"></ins></aside>'
          '<script>(window.adsbygoogle=window.adsbygoogle||[]).push({});</script>') if slot else ''
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} | 환율 기록</title><meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}"><meta property="og:url" content="{e(canonical)}">
<meta property="og:type" content="website"><meta property="og:locale" content="ko_KR"><meta property="og:site_name" content="환율 기록">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(description)}">
{'<meta name="robots" content="noindex,follow">' if noindex else ''}
<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
<link rel="stylesheet" href="/assets/site.css"><script src="/assets/site.js" defer></script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={CLIENT}" crossorigin="anonymous"></script>
</head><body><a class="skip" href="#main">본문으로 이동</a><div class="wrap">
<header><a class="brand" href="/">환율 기록<span>원화로 읽는 세계 통화</span></a><a href="/about/">집계 기준</a></header>
<nav class="currencies" aria-label="통화 선택">{links}</nav><main id="main">{body}{ad}</main>
<footer><p>ECB 참고 환율 · 하루 한 번 발표 · 은행 환율·실시간 시세와 달라요.</p>
<p>출처: <a href="https://frankfurter.dev/">Frankfurter</a> · <a href="{ECB_URL}">ECB</a> · 원화 환산·통계는 가공 정보예요.</p>
<nav aria-label="사이트 안내"><a href="/about/">집계 기준과 재사용 조건</a><a href="/privacy/">개인정보처리방침</a></nav></footer></div></body></html>'''


def home(history: dict) -> str:
    latest = max(history["rates"], default=None)
    body = '<div class="heading"><p class="eyebrow">ECB 참고 환율 · 원화</p><h1>오늘 확인하는 환율</h1>'
    body += (f'<p>최근 관측일 <strong>{ko_day(latest)}</strong></p>' if latest else '<p class="empty">첫 관측 자료를 기다리고 있어요.</p>')
    body += '<p class="muted">하루 한 번 발표하는 ECB 참고 환율이에요. 은행 환율·실시간 시세와 달라요.</p></div>'
    body += '<table class="comparison"><caption>통화별 원화 환율과 변화 · 비교 기준일을 함께 확인해요</caption><thead><tr><th scope="col">통화</th><th scope="col">원화 환율</th><th scope="col">직전 관측일 대비</th><th scope="col">1주 전 대비</th><th scope="col">1년 전 대비</th></tr></thead><tbody>'
    for c, (name, multiplier, unit) in CURRENCIES.items():
        points = series(history, c)
        has_current = points and points[-1][0] == latest
        cells = ''.join(f'<td data-label="{label}">{delta_cell(comparison(points, period) if has_current else None)}</td>' for period, label in [('day', '직전 관측일 대비'), ('week', '1주 전 대비'), ('year', '1년 전 대비')])
        value = number(points[-1][1]) + '원' if has_current else '자료 대기'
        body += f'<tr><th scope="row"><a href="/{c.lower()}/"><span class="code">{c}</span>{name}</a><small>{multiplier}{unit} 기준</small></th><td data-label="원화 환율"><strong>{value}</strong></td>{cells}</tr>'
    body += '</tbody></table><p class="muted">자료가 없는 날은 값을 채우지 않아요. 직전·주간·연간 비교 방법은 <a href="/about/">집계 기준</a>에서 확인할 수 있어요.</p>'
    body += '<section><h2>월별 환율 찾아보기</h2><p>통화를 선택하면 월별 평균·최저·최고와 매일의 기록을 볼 수 있어요.</p><div class="archive-links">'
    for c, (name, _, _) in CURRENCIES.items():
        months = sorted({d[:7] for d, _ in series(history, c)}, reverse=True)[:3]
        body += f'<div><h3>{name}</h3>' + (''.join(f'<a href="/{c.lower()}/{m}/">{ko_month(m)}</a>' for m in months) or '<p class="muted">기록을 기다리고 있어요.</p>') + '</div>'
    return body + '</div></section>'


def currency_page(history: dict, currency: str) -> str:
    name, multiplier, unit = CURRENCIES[currency]
    points = series(history, currency)
    body = f'<div class="heading"><p class="eyebrow">{currency} / KRW · {multiplier}{unit} 기준</p><h1>{name} 환율</h1>'
    body += (f'<p class="rate">{number(points[-1][1])}<span>원</span></p><p>최근 관측일 <strong>{ko_day(points[-1][0])}</strong></p>'
             if points else '<p class="empty">첫 관측 자료를 기다리고 있어요.</p>')
    body += '<p class="muted">ECB 참고 환율이에요. 실제 환전 금액은 은행에서 확인해주세요.</p></div>'
    body += '<div class="detail-grid"><section class="trend"><h2>환율 흐름</h2>'
    body += '<div class="range-buttons" role="group" aria-label="그래프 기간" hidden>'
    body += ''.join(f'<button type="button" data-range="{days}" aria-pressed="{str(days == 90).lower()}">{label}</button>' for days, label in [(30, '1개월'), (90, '3개월'), (365, '1년'), (0, '전체')]) + '</div>'
    recent = [p for p in points if iso(p[0]) >= iso(points[-1][0]) - timedelta(days=89)] if points else []
    body += f'<div id="trend-chart">{chart(recent, name + " 원화 환율")}</div>'
    body += '<p class="muted" id="chart-summary" aria-live="polite">점은 실제 관측이에요. 빈 날짜는 선으로 잇지 않아요.</p></section>'
    body += converter(currency, points) + '</div>'
    if points:
        payload = json.dumps([[d, float(v)] for d, v in points], separators=(',', ':'))
        body += f'<script type="application/json" id="chart-data">{payload}</script>'
    body += f'<section><h2>최근 관측 기록</h2>{daily_table(points[-20:], f"{multiplier}{unit}")}</section>'
    body += '<section><h2>월별 평균 환율</h2><div class="month-links">'
    months = sorted({d[:7] for d, _ in points}, reverse=True)
    body += ''.join(f'<a href="/{currency.lower()}/{month}/">{ko_month(month)}</a>' for month in months) or '<p class="empty">관측 자료가 쌓이면 월별 기록을 볼 수 있어요.</p>'
    return body + '</div></section>'


def month_page(currency: str, month: str, points) -> str:
    name, multiplier, unit = CURRENCIES[currency]
    stats = monthly_stats(points)
    heading = f'{ko_month(month)} {name} 평균 환율'
    body = f'<div class="heading"><a href="/{currency.lower()}/">← {name} 환율 전체 보기</a><h1>{heading}</h1><p>{multiplier}{unit} 기준 · ECB 참고 환율</p></div>'
    body += f'<div class="stats"><div><span>평균</span><strong>{number(stats["average"])}원</strong></div>'
    for key, label in [('low', '최저'), ('high', '최고')]:
        day, value = stats[key]
        body += f'<div><span>{label}</span><strong>{number(value)}원</strong><small>{ko_day(day)}</small></div>'
    body += f'</div><p>{stats["count"]}개 관측 · 수집 범위 {ko_day(points[0][0])}~{ko_day(points[-1][0])}</p>'
    body += '<p class="muted">이 달에 수집한 관측값만 집계했어요. 월말 이전이거나 자료가 추가되면 통계가 달라질 수 있어요.</p>'
    body += f'<section><h2>이 달의 흐름</h2>{chart(points, heading)}</section><section><h2>날짜별 환율</h2>{daily_table(points, f"{multiplier}{unit}")}</section>'
    return body


def build(history: dict, output: Path, slot="") -> int:
    history = validate_history(history)
    if slot and not re.fullmatch(r"\d+", slot):
        raise ValueError("ADSENSE_SLOT must contain digits only")
    output.mkdir(parents=True, exist_ok=True)
    # Only clean generated currency pages. Never remove persisted data or the branch's .git.
    for currency in CURRENCIES:
        folder = output / currency.lower()
        if folder.exists():
            shutil.rmtree(folder)
    (output / "assets").mkdir(exist_ok=True)
    for filename in ("site.css", "site.js", "favicon.svg"):
        shutil.copyfile(ROOT / "assets" / filename, output / "assets" / filename)
    pages = [("", "오늘 환율 · 달러·엔화·유로 원화 비교", home(history), not history["rates"]),
             ("about/", "집계 기준과 출처", ABOUT, False), ("privacy/", "개인정보처리방침", PRIVACY, False)]
    for currency, (name, _, _) in CURRENCIES.items():
        points = series(history, currency)
        pages.append((currency.lower() + "/", name + " 환율 · 추이와 원화 계산기", currency_page(history, currency), not points))
        for month in sorted({d[:7] for d, _ in points}):
            monthly = [p for p in points if p[0].startswith(month)]
            pages.append((f'{currency.lower()}/{month}/', f'{ko_month(month)} {name} 평균 환율', month_page(currency, month, monthly), False))
    for path, title, body, noindex in pages:
        destination = output / path / "index.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(shell(title, path, body, slot, noindex), encoding="utf-8")
    (output / "404.html").write_text(shell(
        "페이지를 찾을 수 없어요", "404.html",
        '<div class="heading"><p class="eyebrow">404</p><h1>페이지를 찾을 수 없어요</h1>'
        '<p>주소가 바뀌었거나 없는 페이지예요. 홈에서 통화별 환율을 찾아볼 수 있어요.</p>'
        '<p><a href="/">홈으로 돌아가기</a></p></div>', noindex=True), encoding="utf-8")
    urls = ''.join(f'<url><loc>{SITE_URL}/{path}</loc></url>\n' for path, _, _, noindex in pages if not noindex)
    (output / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + '</urlset>\n', encoding="utf-8")
    (output / "robots.txt").write_text(f'User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n', encoding="utf-8")
    (output / "CNAME").write_text('fx.ditoaxis.com\n', encoding="utf-8")
    (output / ".nojekyll").write_text('', encoding="utf-8")
    # Remove the previous generated subdomain file on rebuild, too.
    (output / "ads.txt").unlink(missing_ok=True)
    return len(pages) + 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser("update", help="Fetch ECB observations (bootstrap from 2015 if empty)")
    update.add_argument("--history", type=Path, default=Path("site/data/history.json"))
    update.add_argument("--backfill", action="store_true", help="Re-fetch from 2015, merging with stored records")
    render = sub.add_parser("build", help="Build static pages without network access")
    render.add_argument("--history", type=Path, default=Path("site/data/history.json"))
    render.add_argument("--output", type=Path, default=Path("site"))
    args = parser.parse_args(argv)
    try:
        if args.command == "update":
            print(json.dumps(update_history(args.history, backfill=args.backfill), sort_keys=True))
        else:
            count = build(load_history(args.history), args.output, os.environ.get("ADSENSE_SLOT", "").strip())
            print(f"Built {count} pages in {args.output}")
    except (ValueError, OSError, ArithmeticError) as exc:
        print(f"fx-web: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
