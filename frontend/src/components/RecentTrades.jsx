export default function RecentTrades({ trades }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="trades-panel">
        <div className="panel-header"><h2>Recent Trades</h2></div>
        <div className="loading">No trades yet...</div>
      </div>
    );
  }

  return (
    <div className="trades-panel">
      <div className="panel-header"><h2>Recent Trades</h2></div>
      <div className="trades-columns">
        <span>Price</span>
        <span>Size</span>
        <span>Time</span>
      </div>
      <div className="trades-list">
        {trades.map((t, i) => {
          const date = new Date(t.timestamp * 1000);
          const time = date.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          });
          return (
            <div className={`trade-row ${t.aggressor}`} key={`${t.timestamp}-${i}`}>
              <span className="trade-price">{t.price.toFixed(2)}</span>
              <span className="trade-qty">{t.qty.toFixed(4)}</span>
              <span className="trade-time">{time}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
