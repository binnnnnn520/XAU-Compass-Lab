export type NumericLike = number | string | null | undefined;

export interface ApiError {
  code: string;
  message: string;
  detail?: unknown;
}

interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface HealthData {
  status: string;
  version: string;
  db_connected: boolean;
  redis_connected: boolean;
  timestamp: string;
}

export interface NewsSentimentSummary {
  label: string;
  score: NumericLike;
}

export interface NewsListItemData {
  id: string;
  title: string;
  summary: string | null;
  source_id: string | null;
  source_name: string | null;
  published_at: string;
  status: string;
  sentiment: NewsSentimentSummary | null;
  event_tags: string[];
}

export interface EventListItemData {
  id: string;
  news_id: string;
  tag_type: string;
  tag_value: string;
  relevance_score: NumericLike;
  metadata: Record<string, unknown>;
  created_at: string;
  news_title: string;
  published_at: string;
}

export interface SentimentAggregateData {
  window: string;
  avg_score: NumericLike | null;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  dominant_events: string[];
  calculated_at: string;
}

export interface SignalListItemData {
  id: string;
  strategy_run_id: string;
  strategy_name: string;
  symbol: string;
  signal_time: string;
  direction: string;
  strength: NumericLike;
  confidence: NumericLike;
  price_at_signal: NumericLike;
  reasoning: string;
  source_type: string;
  created_at: string;
}

export interface BacktestCreatePayload {
  strategy_run_id: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  slippage_bps: number;
  commission_bps: number;
}

export interface BacktestCreateResponseData {
  backtest_id: string;
  status: string;
  message: string;
}

export interface BacktestTradeLogItemData {
  side: string;
  entry_time: string;
  exit_time: string;
  quantity: NumericLike;
  entry_price: NumericLike;
  exit_price: NumericLike;
  gross_pnl: NumericLike;
  net_pnl: NumericLike;
  commission: NumericLike;
  slippage_bps: number;
}

export interface BacktestListItemData {
  id: string;
  strategy_run_id: string;
  strategy_name: string;
  start_date: string;
  end_date: string;
  status: string;
  initial_capital: NumericLike;
  final_capital: NumericLike | null;
  total_return: NumericLike | null;
  max_drawdown: NumericLike | null;
  sharpe_ratio: NumericLike | null;
  win_rate: NumericLike | null;
  total_trades: number;
  created_at: string;
  completed_at: string | null;
}

export interface BacktestDetailData extends BacktestListItemData {
  error_message: string | null;
  equity_curve: [string, NumericLike][];
  trade_log: BacktestTradeLogItemData[];
}

export interface PaperOrderData {
  id: string;
  signal_id: string;
  symbol: string;
  side: string;
  order_type: string;
  quantity: NumericLike;
  price: NumericLike;
  limit_price: NumericLike;
  slippage: NumericLike;
  commission: NumericLike;
  status: string;
  reject_reason: string | null;
  filled_at: string | null;
  created_at: string;
}

export interface PaperPositionData {
  id: string;
  symbol: string;
  side: string;
  quantity: NumericLike;
  entry_price: NumericLike;
  current_price: NumericLike;
  unrealized_pnl: NumericLike;
  realized_pnl: NumericLike;
  status: string;
  opened_at: string;
  closed_at: string | null;
  entry_order_id: string | null;
  exit_order_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperAccountData {
  total_equity: NumericLike;
  cash: NumericLike;
  unrealized_pnl: NumericLike;
  realized_pnl: NumericLike;
  open_positions: number;
  today_pnl: NumericLike;
}

export interface RiskEventData {
  id: string;
  event_type: string;
  severity: string;
  trigger_value: NumericLike;
  threshold_value: NumericLike;
  action_taken: string;
  related_order_id: string | null;
  description: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface RiskStatusData {
  trading_enabled: boolean;
  current_drawdown: NumericLike;
  max_drawdown_limit: NumericLike;
  position_count: number;
  position_limit: number;
  circuit_breaker_active: boolean;
  last_risk_event: {
    type: string;
    time: string;
  } | null;
}

const API_BASE_PATH = process.env.NEXT_PUBLIC_API_BASE_PATH ?? "/backend/api/v1";

function buildUrl(path: string, params?: Record<string, string | number | undefined>) {
  const query = new URLSearchParams();

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") {
        query.set(key, String(value));
      }
    }
  }

  const queryString = query.toString();
  return `${API_BASE_PATH}${path}${queryString ? `?${queryString}` : ""}`;
}

async function requestApi<T>(
  path: string,
  init?: RequestInit,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const response = await fetch(buildUrl(path, params), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  let payload: ApiEnvelope<T> | null = null;

  try {
    payload = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new Error(`Unexpected response from ${path}.`);
  }

  if (!response.ok || !payload.success || payload.data === null) {
    const message = payload.error?.message ?? `Request failed for ${path}.`;
    throw new Error(message);
  }

  return payload.data;
}

export function fetchHealth() {
  return requestApi<HealthData>("/health");
}

export function fetchNews(params?: { page?: number; page_size?: number; status?: string }) {
  return requestApi<PaginatedData<NewsListItemData>>("/news", undefined, params);
}

export function fetchSentimentAggregate(window = "4h") {
  return requestApi<SentimentAggregateData>("/sentiment/aggregate", undefined, { window });
}

export function fetchEvents(params?: { page?: number; page_size?: number }) {
  return requestApi<PaginatedData<EventListItemData>>("/events", undefined, params);
}

export function fetchSignals(params?: { page?: number; page_size?: number; direction?: string }) {
  return requestApi<PaginatedData<SignalListItemData>>("/signals", undefined, params);
}

export function fetchBacktests(params?: {
  page?: number;
  page_size?: number;
  status?: string;
  strategy_run_id?: string;
}) {
  return requestApi<PaginatedData<BacktestListItemData>>("/backtest", undefined, params);
}

export function fetchBacktestDetail(backtestId: string) {
  return requestApi<BacktestDetailData>(`/backtest/${backtestId}`);
}

export function createBacktest(payload: BacktestCreatePayload) {
  return requestApi<BacktestCreateResponseData>("/backtest", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchPaperOrders(params?: { page?: number; page_size?: number; status?: string }) {
  return requestApi<PaginatedData<PaperOrderData>>("/paper/orders", undefined, params);
}

export function fetchPaperPositions(params?: { page?: number; page_size?: number; status?: string }) {
  return requestApi<PaginatedData<PaperPositionData>>("/paper/positions", undefined, params);
}

export function fetchPaperAccount() {
  return requestApi<PaperAccountData>("/paper/account");
}

export function fetchRiskEvents(params?: {
  page?: number;
  page_size?: number;
  severity?: string;
  event_type?: string;
}) {
  return requestApi<PaginatedData<RiskEventData>>("/risk/events", undefined, params);
}

export function fetchRiskStatus() {
  return requestApi<RiskStatusData>("/risk/status");
}
