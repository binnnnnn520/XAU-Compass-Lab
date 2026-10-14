# XAU Compass Web

Frontend operator console for XAU Compass, the 黄金新闻驱动研究与模拟交易系统.

## Environment

- `API_ORIGIN`: backend origin used by the local rewrite. Defaults to `http://127.0.0.1:8000`.
- `NEXT_PUBLIC_API_BASE_PATH`: browser fetch base path. Defaults to `/backend/api/v1`.

## Run

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:3000`.

## Pages

- `/`: dashboard
- `/news`: analyzed news and event tags
- `/signals`: signal feed
- `/backtest`: create and inspect backtests
- `/paper`: paper account, orders, and positions
- `/risk`: risk status and event stream

## Manual smoke walkthrough

1. Verify the dashboard loads health, news, signals, events, and sentiment.
2. Verify the backtest page can list runs and load detail from the existing REST endpoints.
3. Verify the paper trading page renders account metrics, positions, and recent orders from `/api/v1/paper/*`.
4. Verify the risk ops page renders status and event history from `/api/v1/risk/*`.
5. Start the compose stack and confirm Flower is reachable at `http://localhost:5555`.
