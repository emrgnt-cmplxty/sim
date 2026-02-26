import { useMemo } from "react";
import Spread from "./Spread";

function computeLevels(entries, reverse) {
  const display = reverse ? [...entries].reverse() : entries;
  const cumulative = new Array(display.length);
  let total = 0;

  if (reverse) {
    for (let i = display.length - 1; i >= 0; i--) {
      total += display[i][1];
      cumulative[i] = total;
    }
  } else {
    for (let i = 0; i < display.length; i++) {
      total += display[i][1];
      cumulative[i] = total;
    }
  }

  return { display, cumulative, total };
}

function LevelRow({ level, cumTotal, maxTotal, side }) {
  const pct = (cumTotal / maxTotal) * 100;
  return (
    <div className={`ob-row ${side}`}>
      <div
        className={`depth-bar ${side}-bar`}
        style={{ width: `${pct}%` }}
      />
      <span className="price">{level[0].toFixed(2)}</span>
      <span className="size">{level[1].toFixed(4)}</span>
      <span className="total">{cumTotal.toFixed(4)}</span>
    </div>
  );
}

export default function Orderbook({ data, connected }) {
  const { askLevels, bidLevels, maxTotal } = useMemo(() => {
    if (!data) return { askLevels: null, bidLevels: null, maxTotal: 0 };
    const asks = computeLevels(data.asks, true);
    const bids = computeLevels(data.bids, false);
    return {
      askLevels: asks,
      bidLevels: bids,
      maxTotal: Math.max(asks.total, bids.total),
    };
  }, [data]);

  if (!data) {
    return (
      <div className="orderbook">
        <div className="loading">
          {connected ? "Waiting for data..." : "Connecting to server..."}
        </div>
      </div>
    );
  }

  return (
    <div className="orderbook">
      <div className="ob-header">
        <h2>Order Book</h2>
        <span className={`status ${connected ? "connected" : "disconnected"}`}>
          {connected ? "LIVE" : "DISCONNECTED"}
        </span>
      </div>

      <div className="ob-columns">
        <span>Price</span>
        <span>Size</span>
        <span>Total</span>
      </div>

      <div className="ob-asks">
        {askLevels.display.map((level, i) => (
          <LevelRow
            key={level[0]}
            level={level}
            cumTotal={askLevels.cumulative[i]}
            maxTotal={maxTotal}
            side="ask"
          />
        ))}
      </div>

      <Spread spread={data.spread} midPrice={data.midPrice} />

      <div className="ob-bids">
        {bidLevels.display.map((level, i) => (
          <LevelRow
            key={level[0]}
            level={level}
            cumTotal={bidLevels.cumulative[i]}
            maxTotal={maxTotal}
            side="bid"
          />
        ))}
      </div>
    </div>
  );
}
