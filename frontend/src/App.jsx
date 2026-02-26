import useOrderbook from "./hooks/useOrderbook";
import Orderbook from "./components/Orderbook";
import RecentTrades from "./components/RecentTrades";
import DepthChart from "./components/DepthChart";
import "./App.css";

function App() {
  const { data, connected } = useOrderbook();

  return (
    <div className="app">
      <div className="left-col">
        <Orderbook data={data} connected={connected} />
      </div>
      <div className="right-col">
        <DepthChart
          bids={data?.bids ?? []}
          asks={data?.asks ?? []}
        />
        <RecentTrades trades={data?.trades ?? []} />
      </div>
    </div>
  );
}

export default App;
