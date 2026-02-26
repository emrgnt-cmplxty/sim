import { useMemo } from "react";

const WIDTH = 380;
const HEIGHT = 220;
const PADDING = { top: 10, right: 10, bottom: 24, left: 10 };
const CHART_W = WIDTH - PADDING.left - PADDING.right;
const CHART_H = HEIGHT - PADDING.top - PADDING.bottom;

function buildSteps(levels, cumulative) {
  // returns [{ price, cumQty }] for the stepped area
  const steps = [];
  for (let i = 0; i < levels.length; i++) {
    const price = levels[i][0];
    const prevQty = i > 0 ? cumulative[i - 1] : 0;
    steps.push({ price, cumQty: prevQty });
    steps.push({ price, cumQty: cumulative[i] });
  }
  return steps;
}

export default function DepthChart({ bids, asks }) {
  const paths = useMemo(() => {
    if (!bids || !asks || bids.length === 0 || asks.length === 0) return null;

    // bids: sorted high→low from backend; asks: sorted low→high
    // cumulative for bids: sum from best bid outward
    const bidCum = [];
    let total = 0;
    for (let i = 0; i < bids.length; i++) {
      total += bids[i][1];
      bidCum[i] = total;
    }

    // cumulative for asks: sum from best ask outward
    const askCum = [];
    total = 0;
    for (let i = 0; i < asks.length; i++) {
      total += asks[i][1];
      askCum[i] = total;
    }

    const maxQty = Math.max(
      bidCum[bidCum.length - 1] || 0,
      askCum[askCum.length - 1] || 0
    );

    // price range: lowest bid to highest ask
    const allPrices = [...bids.map((b) => b[0]), ...asks.map((a) => a[0])];
    const minPrice = Math.min(...allPrices);
    const maxPrice = Math.max(...allPrices);
    const priceRange = maxPrice - minPrice || 1;

    const scaleX = (price) =>
      PADDING.left + ((price - minPrice) / priceRange) * CHART_W;
    const scaleY = (qty) =>
      PADDING.top + CHART_H - (qty / maxQty) * CHART_H;

    // bid steps: reverse so we go left-to-right (low price → high price)
    const bidSteps = buildSteps(
      [...bids].reverse(),
      [...bidCum].reverse()
    );
    // ask steps: already low→high
    const askSteps = buildSteps(asks, askCum);

    const stepsToPath = (steps) =>
      steps
        .map((s, i) => `${i === 0 ? "M" : "L"}${scaleX(s.price)},${scaleY(s.cumQty)}`)
        .join(" ");

    const stepsToFill = (steps) => {
      const line = stepsToPath(steps);
      const first = steps[0];
      const last = steps[steps.length - 1];
      return `${line} L${scaleX(last.price)},${scaleY(0)} L${scaleX(first.price)},${scaleY(0)} Z`;
    };

    // tick labels
    const midPrice = (bids[0][0] + asks[0][0]) / 2;
    const ticks = [minPrice, midPrice, maxPrice];

    return { bidSteps, askSteps, stepsToPath, stepsToFill, scaleX, scaleY, ticks, maxQty };
  }, [bids, asks]);

  if (!paths) {
    return (
      <div className="depth-chart-panel">
        <div className="panel-header"><h2>Depth Chart</h2></div>
        <div className="loading">Waiting for data...</div>
      </div>
    );
  }

  const { bidSteps, askSteps, stepsToPath, stepsToFill, scaleX, scaleY, ticks } = paths;

  return (
    <div className="depth-chart-panel">
      <div className="panel-header"><h2>Depth Chart</h2></div>
      <svg width={WIDTH} height={HEIGHT} className="depth-svg">
        {/* grid line at bottom */}
        <line
          x1={PADDING.left} y1={PADDING.top + CHART_H}
          x2={PADDING.left + CHART_W} y2={PADDING.top + CHART_H}
          stroke="#2b3139" strokeWidth={1}
        />

        {/* bid fill + line */}
        <path d={stepsToFill(bidSteps)} fill="rgba(14, 203, 129, 0.1)" />
        <path d={stepsToPath(bidSteps)} fill="none" stroke="#0ecb81" strokeWidth={1.5} />

        {/* ask fill + line */}
        <path d={stepsToFill(askSteps)} fill="rgba(246, 70, 93, 0.1)" />
        <path d={stepsToPath(askSteps)} fill="none" stroke="#f6465d" strokeWidth={1.5} />

        {/* price axis labels */}
        {ticks.map((price) => (
          <text
            key={price}
            x={scaleX(price)}
            y={HEIGHT - 4}
            textAnchor="middle"
            fill="#848e9c"
            fontSize={10}
          >
            {price.toFixed(2)}
          </text>
        ))}
      </svg>
    </div>
  );
}
