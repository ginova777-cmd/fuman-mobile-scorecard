from __future__ import annotations

import math
import random
from datetime import date

import pandas as pd

from backtest_engine import connect


random.seed(42)


def make_prices() -> pd.DataFrame:
    rows = []
    tickers = ["AAPL", "MSFT", "NVDA", "TSM", "AMD"]
    dates = pd.bdate_range(date(2025, 1, 2), periods=180)

    for ticker_index, ticker in enumerate(tickers):
        price = 90 + ticker_index * 35
        for i, trade_date in enumerate(dates):
            drift = 0.0007 + ticker_index * 0.0001
            seasonal = math.sin(i / 9 + ticker_index) * 0.008
            noise = random.uniform(-0.018, 0.018)
            price = max(10, price * (1 + drift + seasonal + noise))
            open_price = price * (1 + random.uniform(-0.006, 0.006))
            close = price
            high = max(open_price, close) * (1 + random.uniform(0.002, 0.016))
            low = min(open_price, close) * (1 - random.uniform(0.002, 0.016))
            rows.append(
                {
                    "trade_date": trade_date.date(),
                    "ticker": ticker,
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": random.randint(2_000_000, 80_000_000),
                }
            )

    return pd.DataFrame(rows)


def make_signals(prices: pd.DataFrame) -> pd.DataFrame:
    signals = []
    strategies = ["momentum_breakout", "volume_surge", "pullback_reversal"]

    for ticker, ticker_prices in prices.groupby("ticker"):
        sample = ticker_prices.iloc[12:-8:9]
        for index, row in sample.iterrows():
            strategy = strategies[index % len(strategies)]
            score = 60 + (index % 37)
            signals.append(
                {
                    "signal_date": row["trade_date"],
                    "ticker": ticker,
                    "strategy": strategy,
                    "score": float(score),
                    "reason": f"sample {strategy} signal",
                }
            )

    return pd.DataFrame(signals)


def main() -> None:
    prices = make_prices()
    signals = make_signals(prices)
    con = connect()
    con.execute("delete from trades")
    con.execute("delete from signals")
    con.execute("delete from prices")
    con.register("prices_df", prices)
    con.register("signals_df", signals)
    con.execute("insert into prices select * from prices_df")
    con.execute("insert into signals select * from signals_df")
    con.close()
    print(f"Seeded {len(prices)} prices and {len(signals)} signals.")


if __name__ == "__main__":
    main()
