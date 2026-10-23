/* All conversions stay in the browser. Only observed dates enter the chart. */
(function () {
  "use strict";
  const formats = new Map();
  const fmt = (value, digits) => {
    if (!formats.has(digits)) formats.set(digits, new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: digits }));
    return formats.get(digits).format(value);
  };
  const decimal = (value) => fmt(value, 2);
  const won = (value) => (value >= 1000 ? fmt(Math.round(value), 0) : decimal(value));
  const plain = (value) => new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value);
  const motion = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  const easing = "cubic-bezier(.22,1,.36,1)";
  const running = new Map();
  function animate(element, frames, duration, delay = 0) {
    if (!element || !element.animate || motion.matches) return;
    const previous = running.get(element);
    if (previous && typeof getComputedStyle === "function") {
      const current = getComputedStyle(element);
      frames[0] = { transform: current.transform, opacity: current.opacity };
    }
    if (previous) previous.cancel();
    const animation = element.animate(frames, { duration, delay, easing });
    running.set(element, animation);
    animation.onfinish = () => running.delete(element);
  }
  const converter = document.querySelector("[data-converter]");
  let finishCount = () => {};
  if (converter) {
    const amount = converter.querySelector("#amount");
    const currency = converter.querySelector("#currency");
    const swap = converter.querySelector("#direction");
    const label = converter.querySelector("#conversion-label");
    const output = converter.querySelector("output");
    const counter = converter.querySelector("[data-counter]");
    const swapLabel = converter.querySelector("[data-swap-label]") || swap;
    const icon = converter.querySelector(".swap-icon");
    let frame = 0;
    let displayed = 0;
    let target = 0;
    let turns = 0;
    finishCount = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      displayed = target;
      if (counter) counter.textContent = output.textContent;
    };
    function showResult(value, format) {
      // The real output always contains the final value, never the intermediate count.
      output.textContent = format(value);
      if (!counter) return;
      output.classList.add("is-counted");
      counter.hidden = false;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      target = value;
      if (motion.matches || typeof requestAnimationFrame !== "function" || value === displayed) {
        finishCount();
        return;
      }
      const from = displayed;
      let start;
      counter.textContent = format(from);
      function tick(now) {
        if (start === undefined) start = now;
        const progress = Math.min((now - start) / 600, 1);
        displayed = from + (value - from) * (1 - Math.pow(1 - progress, 4));
        counter.textContent = format(displayed);
        frame = progress < 1 ? requestAnimationFrame(tick) : 0;
        if (!frame) finishCount();
      }
      frame = requestAnimationFrame(tick);
    }
    const option = () => currency.options[currency.selectedIndex];
    function convert() {
      const picked = option();
      const unit = picked.dataset.unit;
      const toKRW = swap.dataset.direction !== "from-krw";
      // 받침이 있으면 을, 없으면 를 (엔을, 달러를)
      const object = ((unit.charCodeAt(unit.length - 1) - 0xac00) % 28) ? "을" : "를";
      swapLabel.textContent = toKRW ? `원화를 ${unit}${picked.dataset.toward || "로"} 바꾸기` : `${unit}${object} 원화로 바꾸기`;
      const amountLabel = converter.querySelector('label[for="amount"]');
      if (amountLabel) amountLabel.textContent = toKRW ? `바꿀 금액(${unit})` : "바꿀 금액(원)";
      const input = Number(amount.value);
      if (amount.value.trim() === "" || !Number.isFinite(input) || input < 0 || input > 1e12) {
        label.textContent = "";
        finishCount();
        output.textContent = "0부터 1조까지 금액을 입력해 주세요.";
        if (counter) counter.textContent = output.textContent;
        amount.setAttribute("aria-invalid", "true");
        return;
      }
      amount.removeAttribute("aria-invalid");
      const rate = Number(picked.dataset.numerator) / Number(picked.dataset.denominator);
      if (toKRW) {
        label.textContent = `${plain(input)}${unit}${picked.dataset.topic} 약`;
        showResult(input * rate, (value) => `${won(value)}원`);
      } else {
        label.textContent = `${plain(input)}원은 약`;
        showResult(input / rate, (value) => `${decimal(value)}${unit}`);
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
      if (icon) icon.style.transform = `rotate(${++turns * 180}deg)`;
      // The two values pass in opposite directions as their units change.
      animate(amount, [{ transform: "translateY(18px)", opacity: .35 }, { transform: "translateY(0)", opacity: 1 }], 260);
      animate(converter.querySelector(".result"), [{ transform: "translateY(-18px)", opacity: .35 }, { transform: "translateY(0)", opacity: 1 }], 260);
    });
    convert();
  }

  const navigation = document.querySelector(".currencies");
  if (navigation) {
    const links = Array.from(navigation.querySelectorAll("a"));
    let selected = navigation.querySelector("[aria-current]") || (converter ? links[0] : null);
    const indicator = document.createElement("span");
    indicator.className = "currency-indicator";
    indicator.setAttribute("aria-hidden", "true");
    indicator.hidden = !selected;
    navigation.append(indicator);
    navigation.classList.add("has-indicator");
    let lastTransform;
    function position(link, from) {
      if (!link) return;
      const bounds = link.getBoundingClientRect();
      const origin = navigation.getBoundingClientRect();
      const transform = `translateX(${bounds.left - origin.left}px) scaleX(${bounds.width})`;
      indicator.style.transform = transform;
      indicator.hidden = false;
      if (from && from !== transform) animate(indicator, [{ transform: from }, { transform }], 300);
      lastTransform = transform;
    }
    let previous;
    try {
      previous = links.find((link) => link.getAttribute("href") === sessionStorage.getItem("fx-previous-currency"));
      sessionStorage.removeItem("fx-previous-currency");
    } catch (_) { /* Navigation still works when storage is unavailable. */ }
    if (previous) position(previous);
    position(selected, lastTransform);
    if (selected) selected.setAttribute("data-selected", "");
    navigation.addEventListener("click", (event) => {
      const link = event.target.closest("a");
      if (!links.includes(link) || event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      try { sessionStorage.setItem("fx-previous-currency", selected ? selected.getAttribute("href") : link.getAttribute("href")); } catch (_) {}
      if (selected) selected.removeAttribute("data-selected");
      selected = link;
      selected.setAttribute("data-selected", "");
      position(selected, lastTransform);
      // Native links retain navigation, new-tab gestures and browser history.
    });
    if (typeof ResizeObserver === "function") new ResizeObserver(() => position(selected)).observe(navigation);
    if (document.fonts) document.fonts.ready.then(() => position(selected));
  }

  if (typeof IntersectionObserver === "function" && !motion.matches) {
    const observer = new IntersectionObserver((entries) => {
      entries.filter((entry) => entry.isIntersecting).forEach((entry, index) => {
        const element = entry.target;
        const delay = index * 50;
        observer.unobserve(element);
        element.style.animationDelay = `${delay}ms`;
        element.classList.remove("reveal-pending");
        element.classList.add("reveal-enter");
        element.querySelectorAll(".signal-position").forEach((dot) => {
          animate(dot, [{ transform: `translateX(${dot.dataset.average}%)` }, { transform: `translateX(${dot.dataset.today}%)` }], 650, delay);
        });
      });
    }, { threshold: .15 });
    document.querySelectorAll(".currency-group, .archive-links > div").forEach((element) => {
      element.classList.add("reveal-pending");
      element.addEventListener("animationend", () => element.classList.remove("reveal-enter"), { once: true });
      // Keyboard focus must never land in content waiting for a reveal.
      element.addEventListener("focusin", () => {
        element.classList.remove("reveal-pending", "reveal-enter");
        observer.unobserve(element);
      });
      observer.observe(element);
    });
    motion.addEventListener?.("change", (event) => {
      if (!event.matches) return;
      observer.disconnect();
      document.querySelectorAll(".reveal-pending, .reveal-enter").forEach((element) => element.classList.remove("reveal-pending", "reveal-enter"));
    });
  }
  motion.addEventListener?.("change", (event) => {
    if (!event.matches) return;
    finishCount();
    running.forEach((animation) => animation.cancel());
    running.clear();
  });
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
