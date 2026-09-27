# MEXC futures API — field notes (2026-09-25)

Read from `https://www.mexc.com/api-docs/futures/` through WebFetch, which summarizes each page. Confirm anything load-bearing against a capture (G0/M3 fixtures in `crates/exchange_adapter_mexc/tests/fixtures/captured/`).

- **Host:** `api.mexc.com` for REST, `wss://contract.mexc.com/edge` for websocket.
- **Signing:** HMAC-SHA256 of `accessKey + Request-Time + paramString`.
  - GET/DELETE: params sorted and `&`-joined.
  - POST: the raw JSON body.
  - Null params and path params are left out of the signature.
- **Recv-Window:** in seconds, max 60, default 10.
- **Envelope:** `{"success","code","data"}`; errors carry `message`.
- **Ids:** order, plan and deal ids come back as JSON strings, even where the tables say long.

## Orders

**Place order:** `POST /api/v1/private/order/create`. Rate limit 4/2s.
- Params: `symbol`, `price`, `vol`, `side` (1 open long / 2 close short / 3 open short / 4 close long), `type` (1 limit, 2 post-only, 3 IOC, 4 FOK, 5 market), `openType` (1 isolated, 2 cross), `leverage` (open only), `positionMode` (1 hedge, 2 one-way), `reduceOnly` (one-way only), `externalOid` (≤ 32).
- Response `data`: `orderId` (string).

**Cancel orders:** `POST /api/v1/private/order/cancel`.
- Body: `{"orderIds":[..]}`, at most 50.
- Response `data`: `[{orderId, errorCode, errorMsg}]`. Examples: 2040 not exist, 2041 cannot cancel.

**Get order by id:** `GET /api/v1/private/order/get/{orderId}`.
- `state`: 1 pending, 2 unfilled/open, 3 filled, 4 canceled, 5 invalid.
- Fields: `dealVol`, `dealAvgPrice`, `externalOid`, `side`, `vol`, `price`, `orderType`, `errorCode`, `createTime`, `updateTime`.

**Get order by client id:** `GET /api/v1/private/order/external/{symbol}/{externalOid}`.
- Not found (G0 capture): `{"success":true,"code":0}` with no `data`.

**Fills for an order:** `GET /api/v1/private/order/deal_details/{orderId}`.
- Array of `id`, `symbol`, `side`, `vol`, `price`, `fee`, `feeCurrency`, `profit`, `isTaker` / `taker` (the name is inconsistent across the docs), `orderId`, `timestamp`.

**Open orders:** `GET /api/v1/private/order/list/open_orders?page_num&page_size<=100`.
- Account-wide; no symbol is documented. G0 also got a 200 from `/open_orders/{symbol}`.

## Plan (trigger) orders

**Place:** `POST /api/v1/private/planorder/place/v2`.
- Params: `triggerPrice`, `triggerType` (1 ≥, 2 ≤), `executeCycle` (1 = 24 h, 2 = 7 d), `orderType` (1..5), `trend` (1 last, 2 fair, 3 index), `positionMode`, `reduceOnly`.

**Cancel:** `POST /api/v1/private/planorder/cancel`.
- Body: bare array `[{symbol, orderId}]`. No per-item result is documented.

**List:** `GET /api/v1/private/planorder/list/orders`.
- `start_time` / `end_time` are required; `page_num` / `page_size` ≤ 100.
- `state`: 1 untriggered, 2 canceled, 3 executed, 4 invalidated/expired, 5 failed.
- `orderId` is the spawned order's id after execution.

**Change price:** `POST /api/v1/private/planorder/change_price`. Rate limit 4/2s.
- Params: `symbol`, `orderId`, `triggerPrice`, `price`, `orderType`, `triggerType`, `trend`.

## Positions, leverage, account

**Change leverage:** `POST /api/v1/private/position/change_leverage`. Rate limit 10/10s.
- With a position: `positionId` + `leverage`.
- Without one: `symbol`, `leverage`, `openType`, `positionType` (1 long, 2 short).

**Open positions:** `GET /api/v1/private/position/open_positions?symbol`.
- Fields: `positionId`, `positionType`, `openType`, `state` (1 holding, 2 system-held, 3 closed), `holdVol`, `openAvgPrice`, `holdAvgPrice`, `liquidatePrice`, `im`, `oim`, `leverage`, `unRealizedPnl`.

**Risk limits:** `GET /api/v1/private/account/risk_limit?symbol`.
- `data` is keyed by symbol: `[{positionType, level, maxVol, maxLeverage, mmr, imr}]`.

**Public:**
- `GET /api/v1/contract/depth/{symbol}?limit=`: `asks` / `bids` as `[[price, orderCount, qty]]`, plus `version`.
- `fair_price/{symbol}`, `index_price/{symbol}`.
- `depth_commits/{symbol}/1000`: recovery for missed depth updates.

## Websocket

**Keepalive:** send `{"method":"ping"}` every 10–20 s; the reply is `{"channel":"pong"}`. The server drops the connection after 60 s without a ping.

**Depth:** `{"method":"sub.depth","param":{"symbol"}}` → `push.depth` with `data{asks,bids,version}`.
- Incremental and absolute: a quantity of 0 removes the level.
- Apply only versions greater than the local one; on a gap, re-snapshot or use `depth_commits`.

**Deals:** `sub.deal` → `push.deal`, whose `data` is an array of `{p, v, T (1 buy / 2 sell), O, M, t, i}`. `compress:false` turns off aggregation.

**Login:** `{"method":"login","subscribe":false,"param":{"apiKey","reqTime","signature"}}` → `rs.login` / `rs.error`.
- The docs put `subscribe` at the **top level**. The G0 probe sent it inside `param` and still logged in, so it is unconfirmed which one is honoured.

**Filter:** `{"method":"personal.filter","param":{"filters":[{"filter":"order","rules":[symbols]}]}}`.
- Keys: `order`, `order.deal`, `position`, `plan.order`, `asset`, …

**Private push channels:**
- `push.personal.order`: state 1 pending, 2 open, 3 filled, 4 canceled, 5 invalid.
- `push.personal.order.deal`: carries `isTaker`.
- `push.personal.position`, `push.personal.asset`.
- `push.personal.plan.order`: `orderId` is the spawned id, 0 before execution.

## Error codes

- **Auth:** 401 not logged in; 402 key expired; 406 IP not whitelisted; 602 signature failed.
- **Throttling:** 510 too frequent; 2037 trading too frequent.
- **Permissions:** 701 / 702 read / write not enabled.
- **Contract:** 1001 contract does not exist; 1002 not activated.
- **Price:** 2003 / 2004 outside the band; 2007 price error.
- **Balance and leverage:** 2005 insufficient balance; 2006 leverage out of range.
- **Position:** 2008 not enough to close; 2009 position does not exist.
- **Quantity:** 2011 quantity error (G0); 2015 precision.
- **Limits:** 2013 cancel count; 2016 trigger count.
- **Leverage changes:** 2019 blocked by open orders; 2021 leverage ≠ position.
- **Client id:** 2030 `externalOid` too long; 2042 duplicate order id.
- **Orders:** 2040 order does not exist; 2041 cannot cancel; 2043 order does not match position.
