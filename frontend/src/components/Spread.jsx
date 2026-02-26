export default function Spread({ spread, midPrice }) {
  return (
    <div className="spread-row">
      <span className="mid-price">{midPrice.toFixed(2)}</span>
      <span className="spread-label">Spread: {spread.toFixed(2)}</span>
    </div>
  );
}
