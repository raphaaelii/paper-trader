import os
from datetime import datetime, timedelta, timezone

import requests

KEY = os.environ["ALPACA_KEY"]
SECRET = os.environ["ALPACA_SECRET"]
HEADERS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}

TRADE_URL = "https://paper-api.alpaca.markets/v2"  # paper = fake money only
DATA_URL = "https://data.alpaca.markets/v2"

# ---- Settings you can change ----
SYMBOLS = ["SPY", "QQQ"]   # what to trade
BAR_MINUTES = 5            # size of each price bar
FAST = 9                   # short average (number of bars)
SLOW = 21                  # long average (number of bars)
BUFFER = 0.0005            # 0.05% gap needed to act (reduces flip-flopping)
POSITION_FRACTION = 0.25   # use 25% of account per symbol
# ---------------------------------


def get(url, **params):
    return requests.get(url, headers=HEADERS, params=params, timeout=30)


def get_closes(symbol):
    """Closing prices of finished 5-minute bars, oldest to newest."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = get(
        f"{DATA_URL}/stocks/{symbol}/bars",
        timeframe=f"{BAR_MINUTES}Min", start=start, limit=1000,
        adjustment="split", feed="iex", sort="asc",
    )
    r.raise_for_status()
    closes = []
    for bar in r.json().get("bars") or []:
        opened = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        if opened + timedelta(minutes=BAR_MINUTES) <= now:  # skip unfinished bar
            closes.append(float(bar["c"]))
    return closes


def average(values, n):
    return sum(values[-n:]) / n


def main():
    clock = get(f"{TRADE_URL}/clock").json()
    if not clock["is_open"]:
        print("Market is closed. Nothing to do.")
        return

    equity = float(get(f"{TRADE_URL}/account").json()["equity"])
    print(f"Account equity: ${equity:,.2f}")

    for symbol in SYMBOLS:
        try:
            closes = get_closes(symbol)
            if len(closes) < SLOW:
                print(f"{symbol}: not enough price data yet, skipping.")
                continue

            fast, slow = average(closes, FAST), average(closes, SLOW)
            holding = get(f"{TRADE_URL}/positions/{symbol}").status_code == 200
            pending = get(f"{TRADE_URL}/orders", status="open", symbols=symbol).json()
            print(f"{symbol}: price={closes[-1]:.2f} fast={fast:.2f} slow={slow:.2f} holding={holding}")

            if pending:
                print(f"{symbol}: an order is already pending, skipping.")
            elif fast > slow * (1 + BUFFER) and not holding:
                amount = round(equity * POSITION_FRACTION, 2)
                r = requests.post(
                    f"{TRADE_URL}/orders", headers=HEADERS, timeout=30,
                    json={"symbol": symbol, "notional": str(amount), "side": "buy",
                          "type": "market", "time_in_force": "day"},
                )
                print(f"{symbol}: BUY ${amount} -> {r.status_code} {r.text[:200]}")
            elif fast < slow * (1 - BUFFER) and holding:
                r = requests.delete(f"{TRADE_URL}/positions/{symbol}", headers=HEADERS, timeout=30)
                print(f"{symbol}: SELL everything -> {r.status_code} {r.text[:200]}")
            else:
                print(f"{symbol}: no change.")
        except requests.RequestException as error:
            print(f"{symbol}: API error: {error}")
        except (KeyError, ValueError, TypeError) as error:
            print(f"{symbol}: data error: {error}")


if __name__ == "__main__":
    main()
