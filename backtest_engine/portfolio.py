"""Simple portfolio and trade tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Trade:
    symbol: str
    direction: str  # "long" or "short"
    entry_date: datetime
    entry_price: float
    shares: float
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy: str = ""
    exit_date: datetime | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    pnl_amount: float | None = None
    status: str = "open"

    def close(self, exit_date: datetime, exit_price: float) -> None:
        self.exit_date = exit_date
        self.exit_price = exit_price
        if self.direction == "long":
            self.pnl_pct = (exit_price / self.entry_price - 1.0) * 100.0
        else:
            self.pnl_pct = (self.entry_price / exit_price - 1.0) * 100.0
        self.pnl_amount = self.shares * self.entry_price * (self.pnl_pct / 100.0)
        self.status = "closed"


@dataclass
class Portfolio:
    initial_cash: float = 100_000.0
    cash: float = 100_000.0
    transaction_cost_pct: float = 0.001
    max_positions: int = 10
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    def total_value(self, prices: dict[str, float]) -> float:
        position_value = 0.0
        for trade in self.open_trades():
            price = prices.get(trade.symbol, trade.entry_price)
            if trade.direction == "short":
                position_value += trade.shares * (2 * trade.entry_price - price)
            else:
                position_value += trade.shares * price
        return self.cash + position_value

    def open_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.status == "open"]

    def can_open_position(self) -> bool:
        return len(self.open_trades()) < self.max_positions

    def open_trade(
        self,
        symbol: str,
        direction: str,
        entry_date: datetime,
        entry_price: float,
        position_size_pct: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        strategy: str = "",
        risk_per_trade_pct: float | None = None,
    ) -> Trade | None:
        if not self.can_open_position():
            return None
        if position_size_pct <= 0:
            return None

        gross_amount = self.initial_cash * position_size_pct
        if risk_per_trade_pct is not None and stop_loss is not None:
            risk_per_share = abs(entry_price - stop_loss)
            if risk_per_share <= 0:
                return None
            risk_budget = self.initial_cash * risk_per_trade_pct
            shares = risk_budget / risk_per_share
            gross_amount = shares * entry_price

        cost = gross_amount * self.transaction_cost_pct
        if gross_amount + cost > self.cash:
            return None

        shares = gross_amount / entry_price
        self.cash -= gross_amount + cost

        trade = Trade(
            symbol=symbol,
            direction=direction,
            entry_date=entry_date,
            entry_price=entry_price,
            shares=shares,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy,
        )
        self.trades.append(trade)
        return trade

    def close_trade(self, symbol: str, exit_date: datetime, exit_price: float) -> None:
        for trade in self.open_trades():
            if trade.symbol == symbol:
                trade.close(exit_date, exit_price)
                if trade.direction == "short":
                    gross_amount = trade.shares * trade.entry_price
                    proceeds = gross_amount + (trade.shares * (trade.entry_price - exit_price))
                else:
                    proceeds = trade.shares * exit_price
                cost = abs(proceeds) * self.transaction_cost_pct
                self.cash += proceeds - cost
                return

    def record_equity(self, date: datetime, prices: dict[str, float]) -> None:
        self.equity_curve.append(
            {
                "date": date,
                "cash": self.cash,
                "total_value": self.total_value(prices),
                "open_positions": len(self.open_trades()),
            }
        )

    def apply_stop_take(self, prices: dict[str, float], date: datetime) -> None:
        for trade in list(self.open_trades()):
            price = prices.get(trade.symbol)
            if price is None:
                continue
            if trade.stop_loss is not None:
                if trade.direction == "long" and price <= trade.stop_loss:
                    self.close_trade(trade.symbol, date, price)
                elif trade.direction == "short" and price >= trade.stop_loss:
                    self.close_trade(trade.symbol, date, price)
            if trade.take_profit is not None and trade.status == "open":
                if trade.direction == "long" and price >= trade.take_profit:
                    self.close_trade(trade.symbol, date, price)
                elif trade.direction == "short" and price <= trade.take_profit:
                    self.close_trade(trade.symbol, date, price)
