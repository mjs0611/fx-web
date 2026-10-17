/* All conversions stay in the browser. Only observed dates enter the chart. */
(function () {
  "use strict";
  const decimal = (value) => new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value);
  const converter = document.querySelector("[data-converter]");
  if (converter) {
    const amount = converter.querySelector("#amount");
    const direction = converter.querySelector("#direction");
    const output = converter.querySelector("output");
    const rate = Number(converter.dataset.numerator) / Number(converter.dataset.denominator);
    function convert() {
      const input = Number(amount.value);
      if (amount.value.trim() === "" || !Number.isFinite(input) || input < 0 || input > 1e12) {
        output.textContent = "0부터 1조까지 금액을 입력해주세요.";
        amount.setAttribute("aria-invalid", "true");
        return;
      }
      amount.removeAttribute("aria-invalid");
      const toKRW = direction.value === "to-krw";
      const result = toKRW ? input * rate : input / rate;
      output.textContent = `${decimal(result)}${toKRW ? "원" : ` ${converter.dataset.currency}`}`;
    }
    amount.disabled = false;
    direction.disabled = false;
    amount.addEventListener("input", convert);
    direction.addEventListener("change", convert);
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
