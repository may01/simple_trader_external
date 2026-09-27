// Pair page (pair.html?pair=SYMBOL): Live/History toggle driving four
// persistent panels -- the candlestick chart, an order-book panel (bid/ask
// tables + a cumulative depth chart), a recent-trades panel (rolling
// 20-minute price+volume chart in Live mode; the loaded range in History
// mode), and an event log.
//
// Live mode: `GET /pairs/{pair}/history` once for chart/book backfill, then
// open `GET /pairs/{pair}/ws` for the live tail -- two sequential fetches,
// never a third hybrid mode (see specs/2026-09-07-executor-visualiser-design.md,
// "Live and historical are two distinct modes"). The WS `Snapshot` message
// carries current position/reconciliation state only, never a history
// backfill of its own.
//
// History mode: a from/to range against the REST history route only, no WS.

const DEFAULT_BACKFILL_MS = 24 * 60 * 60 * 1000; // 24h lookback for Live's initial backfill and for resync
const MAX_WS_RETRIES = 5;
const RECENT_TRADES_WINDOW_MS = 20 * 60 * 1000; // "Recent Trades" panel's rolling window
const RECENT_TRADES_PRUNE_INTERVAL_MS = 30_000; // keeps the window sliding even with no new trades

const PAIR = new URLSearchParams(location.search).get("pair");

let mode = "live"; // "live" | "history"
let ws = null;
let wsHasOpened = false;
let wsRetryCount = 0;
let chartState = null;
let depthState = null;
// The same book at a tighter window -- see DEPTH_CHART_ZOOM_WINDOW_FRACTION.
let depthZoomState = null;
let tradesChartState = null;
let latestWallSnapshot = null; // most recent WallSnapshotDto -- drives the depth chart's wall lines
let recentTrades = []; // rolling RECENT_TRADES_WINDOW_MS window for the Recent Trades panel
let pruneTimer = null;
let eventSeq = 0;

function $(id) {
  return document.getElementById(id);
}

function showBanner(text, isError) {
  const b = $("banner");
  b.textContent = text || "";
  b.style.display = text ? "block" : "none";
  b.classList.toggle("banner-error", !!isError);
}

// --------------------------------------------------------------------
// position summary + chart overlay
// --------------------------------------------------------------------

/** Renders the Position panel and (re)draws the chart's entry/SL/target
 * lines from a `PairSnapshotDto` -- shared by the initial `GET /pairs`
 * lookup, every WS `Snapshot` message, and resync. */
function renderPositionSummary(snapshot) {
  const el = $("position-summary");
  const open = openPositionOf(snapshot.position.status);
  const healthy = reconciliationHealthy(snapshot.reconciliation);
  const flag = reconciliationFlag(healthy);
  // pair.html ships this element as `class="muted"` for its "Loading..."
  // placeholder. Without dropping that class the real summary -- pair
  // name included -- keeps rendering in secondary grey forever.
  el.classList.remove("muted");
  el.innerHTML =
    `<strong>${escapeHtml(snapshot.pair)}</strong> &mdash; ${escapeHtml(positionStatusText(snapshot.position.status))} ` +
    `<span class="${flag.cls}">${flag.text}</span>`;
  if (chartState) setPositionLines(chartState, open);
}

// --------------------------------------------------------------------
// order book panel
// --------------------------------------------------------------------

function renderBookRows(tbodyId, levels, cls) {
  const tbody = $(tbodyId);
  if (!levels || levels.length === 0) {
    tbody.innerHTML = `<tr><td class="muted" colspan="2">no levels</td></tr>`;
    return;
  }
  tbody.innerHTML = levels
    .slice(0, 15)
    .map((l) => `<tr><td class="${cls}">${escapeHtml(l.price)}</td><td>${escapeHtml(l.qty)}</td></tr>`)
    .join("");
}

/** Renders one reconstructed `OrderBookSnapshotDto` (already full-depth,
 * per `visualizer_backend::order_book_view`/`historical_order_book` --
 * never raw deltas, so no client-side book reconstruction is needed here). */
function renderBook(snapshot) {
  if (!snapshot) {
    renderBookRows("book-bids", [], "bid");
    renderBookRows("book-asks", [], "ask");
    updateDepthChart(depthState, null);
    updateDepthChart(depthZoomState, null, DEPTH_CHART_ZOOM_WINDOW_FRACTION);
    return;
  }
  const bids = [...snapshot.bids].sort((a, b) => (num(b.price) ?? 0) - (num(a.price) ?? 0));
  const asks = [...snapshot.asks].sort((a, b) => (num(a.price) ?? 0) - (num(b.price) ?? 0));
  renderBookRows("book-bids", bids, "bid");
  renderBookRows("book-asks", asks, "ask");
  // Same snapshot, two windows: the wide view for shape, the tight one
  // for the size actually sitting at the spread.
  updateDepthChart(depthState, snapshot);
  updateDepthChart(depthZoomState, snapshot, DEPTH_CHART_ZOOM_WINDOW_FRACTION);
}

/** Redraws both depth charts' wall lines from `latestWallSnapshot`. Kept
 * separate from `renderBook`/`updateDepthChart`: the book and the wall
 * snapshot arrive on independent live messages, so a `Walls` update must
 * not wait for the next `Book` message to show up. */
function redrawDepthWallLines() {
  const lines = wallLinesFromSnapshot(latestWallSnapshot);
  setDepthChartWalls(depthState, lines);
  setDepthChartWalls(depthZoomState, lines);
}

// --------------------------------------------------------------------
// recent-trades panel (rolling RECENT_TRADES_WINDOW_MS window)
// --------------------------------------------------------------------

/** Adds `trades` to the rolling window, drops anything older than
 * `RECENT_TRADES_WINDOW_MS`, and redraws. Called from both the history
 * backfill (seeding the window) and every live `Trade` message -- a full
 * redraw each time, not an incremental append, since the window is small
 * (see `setTradesChartData`'s doc comment). */
function recordTrades(trades) {
  recentTrades.push(...trades);
  pruneRecentTrades();
}

function pruneRecentTrades() {
  const cutoff = Date.now() - RECENT_TRADES_WINDOW_MS;
  const before = recentTrades.length;
  recentTrades = recentTrades.filter((t) => t.ts >= cutoff);
  if (recentTrades.length !== before || mode === "live") {
    setTradesChartData(tradesChartState, recentTrades);
  }
}

// --------------------------------------------------------------------
// event log panel
// --------------------------------------------------------------------

function resetLog() {
  $("log").innerHTML = "";
  eventSeq = 0;
}

/** Appends log entries. `PositionStateEventDto` carries no timestamp of its
 * own on the wire (neither the WS `Position` variant nor
 * `HistoryResponseDto.events` -- see dto.rs), so entries are numbered in
 * arrival/storage order rather than showing a fabricated clock time. */
function appendLogEntries(events, prefix) {
  const log = $("log");
  for (const e of events) {
    const li = document.createElement("li");
    eventSeq += 1;
    li.textContent = `#${eventSeq}${prefix ? " " + prefix : ""} ${eventSummary(e)}`;
    log.appendChild(li);
  }
  log.scrollTop = log.scrollHeight;
}

// --------------------------------------------------------------------
// history fetch (backfill for both Live's initial load / resync, and History mode)
// --------------------------------------------------------------------

async function loadHistoryBackfill(fromMs, toMs) {
  const data = await API.history(PAIR, fromMs, toMs);
  setChartHistory(chartState, data.candles);
  // The whole recorded wall series for the range -- one snapshot per
  // candle interval, drawn as dots at each wall's own price.
  setWallSnapshots(chartState, data.walls || []);
  // The depth chart's wall lines only need the latest snapshot in range
  // (not the whole series) -- `data.walls` need not arrive time-sorted,
  // same caveat `setWallSnapshots` itself documents.
  const sortedWalls = [...(data.walls || [])].sort((a, b) => a.ts - b.ts);
  latestWallSnapshot = sortedWalls.length ? sortedWalls[sortedWalls.length - 1] : null;
  redrawDepthWallLines();
  // `data.book` is the single final reconstructed snapshot for the range
  // (or null/absent if the range had no book data) -- no longer an array,
  // see HistoryResponseDto's doc comment.
  renderBook(data.book || null);
  resetLog();
  appendLogEntries(data.events);
  // Recent Trades panel: seeded with the whole fetched range here -- Live
  // mode narrows this to the actual rolling 20-minute window right after
  // (see `enterLiveMode`); History mode leaves it as "trades in the
  // range you asked for", consistent with the rest of the page.
  recentTrades = data.trades;
  setTradesChartData(tradesChartState, recentTrades);
  return data;
}

// --------------------------------------------------------------------
// live WS
// --------------------------------------------------------------------

function tearDownWs() {
  if (ws) {
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
    try {
      ws.close();
    } catch (_err) {
      // already closed/closing -- nothing to do
    }
    ws = null;
  }
}

/** Handles a server `Resync` message: per the design, a `Lagged` on the
 * server's internal fan-out means some live events were dropped, so the
 * client re-fetches `GET /pairs` (fresh position/reconciliation) plus a
 * fresh history window, rather than trying to patch a specific gap. The
 * existing WS connection is left open -- only the *data*, not the socket,
 * needs resyncing. */
async function handleResync() {
  showBanner("Resynchronizing after a gap in the live feed...");
  try {
    const pairs = await API.pairs();
    const snap = pairs.find((p) => p.pair === PAIR);
    if (snap) renderPositionSummary(snap);
    const now = Date.now();
    await loadHistoryBackfill(now - DEFAULT_BACKFILL_MS, now);
    pruneRecentTrades(); // same 24h-backfill-to-20min narrowing as enterLiveMode
    showBanner("");
  } catch (err) {
    showBanner(`Resync failed: ${err.message}`, true);
  }
}

function onLiveMessage(evt) {
  let msg;
  try {
    msg = JSON.parse(evt.data);
  } catch (_err) {
    return; // not valid JSON -- ignore rather than crash the page
  }
  switch (msg.type) {
    case "Snapshot":
      // `LiveMessage::Snapshot(PairSnapshotDto)` is internally tagged, so
      // `pair`/`position`/`reconciliation` are flattened alongside `type`
      // on this same object -- `msg` itself already has the shape
      // `renderPositionSummary` expects.
      renderPositionSummary(msg);
      break;
    case "Candle":
      applyLiveCandle(chartState, msg);
      break;
    case "Trade":
      recordTrades([msg]);
      break;
    case "Walls":
      // `LiveMessage::Walls(WallSnapshotDto)` is internally tagged, so
      // `ts`/`walls` sit alongside `type` on this same object.
      appendWallSnapshot(chartState, msg);
      latestWallSnapshot = msg;
      redrawDepthWallLines();
      break;
    case "Book":
      renderBook(msg);
      break;
    case "Position": {
      // `LiveMessage::Position(PositionStateEventDto)` merges the inner
      // enum's own `{"VariantName": {...}}` map into this object alongside
      // `type` -- the variant key is whatever's left after `type`.
      const key = Object.keys(msg).find((k) => k !== "type");
      if (key) appendLogEntries([{ [key]: msg[key] }], "(live)");
      break;
    }
    case "Resync":
      handleResync();
      break;
    default:
      console.warn("unknown live message type", msg.type);
  }
}

function connectWs() {
  tearDownWs();
  wsHasOpened = false;
  const socket = new WebSocket(API.wsUrl(PAIR));
  ws = socket;

  socket.onopen = () => {
    wsHasOpened = true;
    wsRetryCount = 0;
    showBanner("");
  };

  socket.onmessage = onLiveMessage;

  socket.onclose = () => {
    if (mode !== "live" || ws !== socket) return; // superseded by a mode switch or a fresh connect
    if (!wsHasOpened) {
      // Handshake was rejected (503 -- executor not currently live, per
      // `routes::pair_ws`). The browser WebSocket API never exposes that
      // status code directly; "onclose fired before onopen ever did" is
      // the only observable signal. Per the brief: show this clearly, do
      // NOT loop retrying on our own -- the user drives retry via the
      // Live button.
      showBanner("Executor is not currently live -- WebSocket unavailable. Click “Live” to retry.", true);
      return;
    }
    // A connection that *had* been working just dropped -- reconnect with
    // capped exponential backoff (design: "client reconnects with
    // backoff"), never an unbounded loop.
    if (wsRetryCount < MAX_WS_RETRIES) {
      wsRetryCount += 1;
      const delayMs = Math.min(1000 * 2 ** wsRetryCount, 30000);
      showBanner(`Connection lost -- retrying in ${Math.round(delayMs / 1000)}s (attempt ${wsRetryCount}/${MAX_WS_RETRIES})...`, true);
      setTimeout(() => {
        if (mode === "live") enterLiveMode();
      }, delayMs);
    } else {
      showBanner("Connection lost repeatedly. Click “Live” to retry manually.", true);
    }
  };

  socket.onerror = () => {
    // `onclose` always follows `onerror` for a WebSocket -- nothing extra
    // to do here beyond letting `onclose` above handle it.
  };
}

// --------------------------------------------------------------------
// mode switching
// --------------------------------------------------------------------

function startTradePruning() {
  stopTradePruning();
  pruneTimer = setInterval(pruneRecentTrades, RECENT_TRADES_PRUNE_INTERVAL_MS);
}

function stopTradePruning() {
  if (pruneTimer) {
    clearInterval(pruneTimer);
    pruneTimer = null;
  }
}

async function enterLiveMode() {
  mode = "live";
  $("mode-live-btn").classList.add("active");
  $("mode-history-btn").classList.remove("active");
  $("history-controls").style.display = "none";
  showBanner("Loading…");
  try {
    const now = Date.now();
    await loadHistoryBackfill(now - DEFAULT_BACKFILL_MS, now);
    // The 24h backfill just seeded `recentTrades` with far more than 10
    // minutes' worth -- narrow it to the actual rolling window Live mode
    // shows (loadHistoryBackfill itself doesn't know which mode it's
    // called from).
    pruneRecentTrades();
    startTradePruning();
    showBanner("");
    connectWs();
  } catch (err) {
    showBanner(`Failed to load initial data: ${err.message}`, true);
  }
}

function enterHistoryMode() {
  mode = "history";
  tearDownWs();
  stopTradePruning();
  $("mode-live-btn").classList.remove("active");
  $("mode-history-btn").classList.add("active");
  $("history-controls").style.display = "flex";
  showBanner("");
}

async function loadHistoryRange() {
  const fromVal = $("history-from").value;
  const toVal = $("history-to").value;
  if (!fromVal) {
    showBanner('Select a "from" date/time first.', true);
    return;
  }
  const fromMs = new Date(fromVal).getTime();
  const toMs = toVal ? new Date(toVal).getTime() : Date.now();
  if (Number.isNaN(fromMs) || (toVal && Number.isNaN(toMs))) {
    showBanner("Invalid date/time.", true);
    return;
  }
  showBanner("Loading…");
  try {
    await loadHistoryBackfill(fromMs, toMs);
    showBanner("");
  } catch (err) {
    showBanner(`Failed to load history: ${err.message}`, true);
  }
}

// --------------------------------------------------------------------
// init
// --------------------------------------------------------------------

async function init() {
  if (!PAIR) {
    showBanner("No pair specified in the URL (expected ?pair=SYMBOL).", true);
    return;
  }
  document.title = `${PAIR} — Executor Visualiser`;
  $("pair-title").textContent = PAIR;
  chartState = createPairChart($("chart"));
  renderChartLegend($("chart-legend"));
  depthState = createDepthChart($("depth-chart"));
  depthZoomState = createDepthChart($("depth-chart-zoom"));
  tradesChartState = createTradesChart($("trades-chart"));
  renderTradesLegend($("trades-legend"));

  $("mode-live-btn").addEventListener("click", () => {
    wsRetryCount = 0;
    enterLiveMode();
  });
  $("mode-history-btn").addEventListener("click", enterHistoryMode);
  $("history-load-btn").addEventListener("click", loadHistoryRange);

  try {
    const pairs = await API.pairs();
    const snap = pairs.find((p) => p.pair === PAIR);
    if (snap) {
      renderPositionSummary(snap);
    } else {
      showBanner(`Pair "${PAIR}" is not configured on this server.`, true);
    }
  } catch (err) {
    showBanner(`Failed to load pair status: ${err.message}`, true);
  }

  await enterLiveMode();
}

document.addEventListener("DOMContentLoaded", init);
