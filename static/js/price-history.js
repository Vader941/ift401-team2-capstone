(() => {
    const chartSection = document.querySelector("[data-price-history-endpoint]");
    const button = document.getElementById("price-history-refresh");
    const svg = document.querySelector("#price-history-chart svg");
    const status = document.getElementById("price-history-status");
    const asOf = document.getElementById("price-history-as-of");
    const tableBody = document.getElementById("price-history-table-body");
    if (!chartSection || !button || !svg || !status || !asOf || !tableBody) return;
    const ns = "http://www.w3.org/2000/svg";
    let previousPayload = null;
    let hasLoaded = false;
    const timeFormatter = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York", month: "short", day: "numeric",
        year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"
    });
    const dateFormatter = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York", month: "short", day: "numeric"
    });
    const moneyFormatter = new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2, maximumFractionDigits: 2
    });

    function node(name, attrs = {}, label = "") {
        const item = document.createElementNS(ns, name);
        Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, value));
        if (label) item.textContent = label;
        return item;
    }

    function draw(points) {
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        if (!points.length) {
            svg.append(node("text", { x: 400, y: 160, "text-anchor": "middle", class: "chart-empty" }, "No recorded price history yet"));
            return;
        }
        const W = 800, H = 320, left = 72, right = 20, top = 16, bottom = 48;
        const values = points.map(point => Number(point.price)).filter(Number.isFinite);
        const times = points.map(point => Date.parse(point.timestamp)).filter(Number.isFinite);
        if (!values.length || !times.length) return;
        let min = Math.min(...values), max = Math.max(...values);
        const spread = max - min || Math.max(Math.abs(max) * 0.02, 0.01);
        min -= spread * 0.12;
        max += spread * 0.12;
        const first = Math.min(...times), last = Math.max(...times);
        const x = t => left + (last === first ? 0.5 : (t - first) / (last - first)) * (W - left - right);
        const y = value => top + (max - value) / (max - min) * (H - top - bottom);

        for (let i = 0; i <= 4; i++) {
            const value = min + (max - min) * i / 4;
            const yy = y(value);
            svg.append(node("line", { x1: left, y1: yy, x2: W - right, y2: yy, class: "chart-grid" }));
            svg.append(node("text", { x: left - 10, y: yy + 4, "text-anchor": "end", class: "chart-axis-label" }, `$${moneyFormatter.format(value)}`));
        }
        svg.append(node("line", { x1: left, y1: top, x2: left, y2: H - bottom, class: "chart-axis" }));
        svg.append(node("line", { x1: left, y1: H - bottom, x2: W - right, y2: H - bottom, class: "chart-axis" }));
        svg.append(node("text", { x: 16, y: 150, transform: "rotate(-90 16 150)", "text-anchor": "middle", class: "chart-title" }, "Price (USD)"));
        svg.append(node("text", { x: (left + W - right) / 2, y: H - 6, "text-anchor": "middle", class: "chart-title" }, "Observation time (ET)"));

        const path = points.map((point, index) => `${index ? "L" : "M"}${x(Date.parse(point.timestamp)).toFixed(2)},${y(Number(point.price)).toFixed(2)}`).join(" ");
        svg.append(node("path", { d: path, class: "chart-line" }));
        if (points.length === 1) {
            svg.append(node("circle", {
                cx: x(Date.parse(points[0].timestamp)), cy: y(Number(points[0].price)), r: 5,
                class: "chart-point"
            }));
        }
        const tickCount = Math.min(3, points.length);
        for (let i = 0; i < tickCount; i++) {
            const point = points[Math.round(i * (points.length - 1) / Math.max(tickCount - 1, 1))];
            svg.append(node("text", { x: x(Date.parse(point.timestamp)), y: H - bottom + 22, "text-anchor": "middle", class: "chart-axis-label" }, dateFormatter.format(new Date(point.timestamp))));
        }
    }

    function updateTable(points) {
        tableBody.replaceChildren();
        if (!points.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 2;
            cell.textContent = "No recorded price history yet.";
            row.append(cell);
            tableBody.append(row);
            return;
        }
        points.slice().reverse().slice(0, 25).forEach(point => {
            const row = document.createElement("tr");
            const when = document.createElement("td");
            const price = document.createElement("td");
            when.textContent = timeFormatter.format(new Date(point.timestamp));
            price.className = "text-end";
            price.textContent = `$${moneyFormatter.format(Number(point.price))}`;
            row.append(when, price);
            tableBody.append(row);
        });
    }

    async function refresh() {
        button.disabled = true;
        status.textContent = "Loading recorded observations…";
        try {
            const response = await fetch(chartSection.dataset.priceHistoryEndpoint, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
                cache: "no-store"
            });
            if (!response.ok) throw new Error("Unable to load price history.");
            const data = await response.json();
            if (String(data.stock_id) !== chartSection.dataset.stockId
                || data.symbol !== document.getElementById("stock-heading").textContent.trim()) {
                throw new Error("The returned history did not match this stock.");
            }
            const signature = JSON.stringify(data.points);
            draw(data.points);
            updateTable(data.points);
            const latest = data.display_data_as_of
                ? timeFormatter.format(new Date(data.display_data_as_of))
                : null;
            asOf.textContent = latest ? `As of ${latest} (ET)` : "As of — ET";
            if (!data.points.length) {
                status.textContent = "No recorded price observations are available yet.";
            } else if (hasLoaded && signature === previousPayload) {
                status.textContent = "No new recorded price observations since the last refresh.";
            } else {
                status.textContent = hasLoaded ? "Chart updated with the latest recorded observations." : `${data.points.length} recorded observation${data.points.length === 1 ? "" : "s"} loaded.`;
            }
            previousPayload = signature;
            hasLoaded = true;
        } catch (error) {
            status.textContent = `${error.message} Try Refresh again.`;
        } finally {
            button.disabled = false;
        }
    }

    button.addEventListener("click", refresh);
    refresh();
})();
