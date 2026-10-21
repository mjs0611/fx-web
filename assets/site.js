/* All conversions stay in the browser. Only observed dates enter the chart. */
(function () {
  "use strict";
  const fmt = (value, digits) => new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
  const decimal = (value) => fmt(value, 2);
  const won = (value) => (value >= 1000 ? fmt(Math.round(value), 0) : decimal(value));
  const plain = (value) => new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value);
  const converter = document.querySelector("[data-converter]");
  if (converter) {
    const amount = converter.querySelector("#amount");
    const currency = converter.querySelector("#currency");
    const swap = converter.querySelector("#direction");
    const label = converter.querySelector("#conversion-label");
    const output = converter.querySelector("output");
    const option = () => currency.options[currency.selectedIndex];
    function convert() {
      const picked = option();
      const unit = picked.dataset.unit;
      const toKRW = swap.dataset.direction !== "from-krw";
      // 받침이 있으면 을, 없으면 를 (엔을, 달러를)
      const object = ((unit.charCodeAt(unit.length - 1) - 0xac00) % 28) ? "을" : "를";
      swap.textContent = toKRW ? `원화를 ${unit}${picked.dataset.toward || "로"} 바꾸기` : `${unit}${object} 원화로 바꾸기`;
      const amountLabel = converter.querySelector('label[for="amount"]');
      if (amountLabel) amountLabel.textContent = toKRW ? `바꿀 금액(${unit})` : "바꿀 금액(원)";
      const input = Number(amount.value);
      if (amount.value.trim() === "" || !Number.isFinite(input) || input < 0 || input > 1e12) {
        label.textContent = "";
        output.textContent = "0부터 1조까지 금액을 입력해 주세요.";
        amount.setAttribute("aria-invalid", "true");
        return;
      }
      amount.removeAttribute("aria-invalid");
      const rate = Number(picked.dataset.numerator) / Number(picked.dataset.denominator);
      if (toKRW) {
        label.textContent = `${plain(input)}${unit}${picked.dataset.topic} 약`;
        output.textContent = `${won(input * rate)}원`;
      } else {
        label.textContent = `${plain(input)}원은 약`;
        output.textContent = `${decimal(input / rate)}${unit}`;
      }
    }
    amount.disabled = false;
    currency.disabled = false;
    swap.hidden = false;
    amount.addEventListener("input", convert);
    currency.addEventListener("change", convert);
    swap.addEventListener("click", () => {
      swap.dataset.direction = swap.dataset.direction === "from-krw" ? "to-krw" : "from-krw";
      convert();
    });
    convert();
  }
  const data = document.getElementById("chart-data");
  if (!data) return;
  const points = JSON.parse(data.textContent);
  const chart = document.getElementById("trend-chart");
  const summary = document.getElementById("chart-summary");
  const controls = document.querySelector(".range-buttons");
  const day = (value) => Date.parse(`${value}T00:00:00Z`);
  const svgNS = "http://www.w3.org/2000/svg";
  function svgNode(tag, attrs) {
    const node = document.createElementNS(svgNS, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function scale(left, right) {
    const row = document.createElement("div");
    row.className = "chart-scale";
    for (const text of [left, right]) {
      const span = document.createElement("span");
      span.textContent = text;
      row.append(span);
    }
    return row;
  }
  function draw(days) {
    const cutoff = days ? day(points.at(-1)[0]) - (days - 1) * 86400000 : -Infinity;
    const selected = points.filter(([date]) => day(date) >= cutoff);
    const first = day(selected[0][0]);
    const last = day(selected.at(-1)[0]);
    const rates = selected.map((point) => point[1]);
    const low = Math.min(...rates);
    const high = Math.max(...rates);
    const spread = high - low || Math.max(high * 0.01, 0.01);
    const svg = svgNode("svg", { class: "chart", viewBox: "0 0 900 240", preserveAspectRatio: "none", role: "img", "aria-label": "선택한 기간의 원화 환율" });
    const title = svgNode("title", {});
    title.textContent = `${selected[0][0]}~${selected.at(-1)[0]} · ${selected.length}개 관측`;
    svg.append(title, svgNode("path", { class: "grid", d: "M20 30H880M20 120H880M20 210H880" }));
    const group = svgNode("g", { class: "observations" });
    let previous;
    for (const [date, rate] of selected) {
      const x = 20 + ((day(date) - first) / Math.max(last - first, 86400000)) * 860;
      const y = 210 - ((rate - low) / spread) * 180;
      if (previous && day(date) - day(previous.date) === 86400000) {
        group.append(svgNode("line", { x1: previous.x, y1: previous.y, x2: x, y2: y }));
      }
      const dot = svgNode("circle", { cx: x, cy: y, r: 3 });
      const label = svgNode("title", {});
      label.textContent = `${date}: ${decimal(rate)}원`;
      dot.append(label);
      group.append(dot);
      previous = { x, y, date };
    }
    svg.append(group);
    chart.replaceChildren(scale(`최고 ${decimal(high)}원`, `최저 ${decimal(low)}원`), svg, scale(selected[0][0], selected.at(-1)[0]));
    summary.textContent = `${selected.length}개 관측 · 점은 실제 관측이에요. 빈 날짜는 선으로 잇지 않아요.`;
    controls.querySelectorAll("button").forEach((button) => button.setAttribute("aria-pressed", String(Number(button.dataset.range) === days)));
  }
  controls.hidden = false;
  controls.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-range]");
    if (button) draw(Number(button.dataset.range));
  });
})();
