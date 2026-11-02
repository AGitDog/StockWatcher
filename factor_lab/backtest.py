"""Portfolio simulation for the factor ranking, compared with a buy-and-hold ETF.

Design choices that keep the result honest:

* Signals are taken at the month-end close and executed at the next trading day close.
* Transaction costs apply to every trade.
* German taxation: Abgeltungssteuer plus Solidaritaetszuschlag is withheld on each
  realised gain like a German broker does, with a loss pot carried into later years
  and the annual Sparer-Pauschbetrag. Individual stocks get no partial exemption.
* The benchmark ETF is taxed once at the end, with the 30 percent Teilfreistellung
  for equity funds. The Vorabpauschale is ignored, which slightly favours the ETF.
* Both sides are liquidated at the end so the after-tax wealth is comparable.

The strategy equity curve already contains the tax withheld on each sale. The
benchmark equity curve is pre-tax because the ETF pays tax only when sold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .evaluation import deflated_sharpe_ratio, sharpe_ratio
from .factors import (
    DEFAULT_FACTOR_WEIGHTS,
    TRADING_DAYS_PER_YEAR,
    composite_score,
    compute_factor_panel,
    month_end_dates,
)

# 25 percent Abgeltungssteuer plus 5.5 percent Solidaritaetszuschlag, without church tax.
TAX_RATE_DE = 0.26375
SPARER_PAUSCHBETRAG = 1000.0
ETF_TEILFREISTELLUNG = 0.30


@dataclass
class BacktestConfig:
    top_n: int = 20
    weighting: str = "equal"  # "equal" or "inverse_vol"
    factor_weights: dict[str, float] | None = None
    rebalance_months: int = 1
    max_sector_weight: float | None = None
    sectors: dict[str, str] | None = None
    transaction_cost_pct: float = 0.001
    trend_filter: bool = True
    trend_ma_days: int = 200
    risk_off_exposure: float = 0.5
    apply_tax: bool = True
    tax_rate: float = TAX_RATE_DE
    tax_allowance: float = SPARER_PAUSCHBETRAG
    etf_partial_exemption: float = ETF_TEILFREISTELLUNG
    initial_capital: float = 100_000.0
    min_universe: int = 30
    n_trials: int = 1


@dataclass
class FactorBacktestResult:
    config: BacktestConfig
    equity: pd.DataFrame
    metrics: dict[str, float]
    benchmark_metrics: dict[str, float]
    rebalances: pd.DataFrame
    holdings: dict[pd.Timestamp, list[str]] = field(default_factory=dict)

    @property
    def excess_cagr_after_tax(self) -> float:
        return self.metrics["cagr_after_tax"] - self.benchmark_metrics["cagr_after_tax"]


class GermanTaxAccount:
    """Withholds capital gains tax per sale with a loss pot and annual allowance."""

    def __init__(self, rate: float, allowance: float) -> None:
        self.rate = rate
        self.allowance = allowance
        self.year: int | None = None
        self.ytd_gain = 0.0
        self.loss_carry = 0.0  # always <= 0
        self.paid_ytd = 0.0
        self.total_paid = 0.0

    def _roll_to(self, year: int) -> None:
        if self.year is None:
            self.year = year
            return
        if year == self.year:
            return
        net = self.ytd_gain + self.loss_carry
        self.loss_carry = min(0.0, net)
        self.ytd_gain = 0.0
        self.paid_ytd = 0.0
        self.year = year

    def realize(self, year: int, gain: float) -> float:
        """Book a realised gain or loss and return the tax payment (negative = refund)."""
        self._roll_to(year)
        self.ytd_gain += gain
        due = self.rate * max(0.0, self.ytd_gain + self.loss_carry - self.allowance)
        payment = due - self.paid_ytd
        self.paid_ytd = due
        self.total_paid += payment
        return payment


def _cap_sector_weights(weights: pd.Series, sectors: dict[str, str], cap: float) -> pd.Series:
    """Limit each known sector to ``cap`` of the invested weight and redistribute the rest.

    Symbols without a known sector are not capped and can receive excess weight.
    If the cap cannot be met because there are too few sectors, the excess stays in cash.
    """
    weights = weights.astype(float).copy()
    total = float(weights.sum())
    if total <= 0 or cap <= 0:
        return weights
    labels = pd.Series({symbol: sectors.get(symbol) or "" for symbol in weights.index})
    limit = cap * total
    capped: set[str] = set()
    for _ in range(50):
        sector_sum = weights.groupby(labels).sum()
        over = [sector for sector, value in sector_sum.items() if sector and value > limit + 1e-12]
        if not over:
            break
        excess = 0.0
        for sector in over:
            members = labels[labels == sector].index
            current = float(weights[members].sum())
            weights[members] *= limit / current
            excess += current - limit
            capped.add(sector)
        receivers = ~labels.isin(capped)
        receiver_sum = float(weights[receivers].sum())
        if receiver_sum <= 0:
            break
        weights[receivers] += excess * weights[receivers] / receiver_sum
    return weights


def _equity_metrics(values: pd.Series) -> dict[str, float]:
    values = values.dropna()
    if len(values) < 2 or values.iloc[0] <= 0:
        return {"cagr": float("nan"), "volatility": float("nan"), "sharpe": float("nan"), "max_drawdown": float("nan")}
    days = (values.index[-1] - values.index[0]).days
    years = max(days / 365.25, 1e-9)
    daily = values.pct_change().dropna()
    vol = float(daily.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily) > 1 else float("nan")
    sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily) > 1 and daily.std(ddof=1) > 0 else float("nan")
    drawdown = values / values.cummax() - 1.0
    return {
        "cagr": float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0),
        "volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
    }


def monthly_returns(values: pd.Series) -> pd.Series:
    values = values.dropna()
    month_end = values.groupby([values.index.year, values.index.month]).last()
    month_end.index = month_end_dates(values.index)
    return month_end.pct_change().dropna()


def _cagr(start_value: float, end_value: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).days / 365.25, 1e-9)
    if start_value <= 0 or end_value <= 0:
        return float("nan")
    return float((end_value / start_value) ** (1.0 / years) - 1.0)


def run_factor_backtest(
    close: pd.DataFrame,
    benchmark_close: pd.Series,
    config: BacktestConfig | None = None,
    scores: pd.DataFrame | None = None,
) -> FactorBacktestResult:
    """Simulate a monthly top-N factor portfolio against a buy-and-hold benchmark."""
    config = config or BacktestConfig()
    close = close.sort_index()
    prices = close.ffill()
    benchmark_close = benchmark_close.sort_index().reindex(prices.index).ffill()
    signal_dates = month_end_dates(prices.index)

    if scores is None:
        weights = config.factor_weights or DEFAULT_FACTOR_WEIGHTS
        factor_values = compute_factor_panel(prices, signal_dates, list(weights))
        scores = composite_score(factor_values, weights)
    scores = scores.reindex(signal_dates)

    log_returns = np.log(prices).diff()
    volatility = (log_returns.rolling(TRADING_DAYS_PER_YEAR, min_periods=int(TRADING_DAYS_PER_YEAR * 0.8)).std() * math.sqrt(TRADING_DAYS_PER_YEAR)).reindex(signal_dates)
    trend_ma = benchmark_close.rolling(config.trend_ma_days, min_periods=config.trend_ma_days).mean()

    tradable = [d for d in signal_dates if scores.loc[d].notna().sum() >= config.min_universe]
    tradable = tradable[:: max(int(config.rebalance_months), 1)]
    index_positions = {d: prices.index.get_loc(d) for d in tradable}
    schedule = [(d, prices.index[index_positions[d] + 1]) for d in tradable if index_positions[d] + 1 < len(prices.index)]
    if not schedule:
        raise ValueError("Zu wenig Historie fuer einen Backtest: keine handelbaren Rebalancing-Termine.")

    tax = GermanTaxAccount(config.tax_rate if config.apply_tax else 0.0, config.tax_allowance)
    cost_rate = config.transaction_cost_pct
    symbols = prices.columns
    shares = pd.Series(0.0, index=symbols)
    basis = pd.Series(0.0, index=symbols)
    cash = float(config.initial_capital)
    total_costs = 0.0
    records: list[dict[str, Any]] = []
    holdings: dict[pd.Timestamp, list[str]] = {}
    equity_parts: list[pd.Series] = []
    exposure_parts: list[pd.Series] = []

    for k, (signal_date, exec_date) in enumerate(schedule):
        px = prices.loc[exec_date]
        held_value = float((shares * px.fillna(0.0)).sum())
        value = cash + held_value

        bench_now = benchmark_close.loc[signal_date]
        ma_now = trend_ma.loc[signal_date]
        risk_off = bool(config.trend_filter and pd.notna(ma_now) and pd.notna(bench_now) and bench_now < ma_now)
        exposure = config.risk_off_exposure if risk_off else 1.0

        eligible = scores.loc[signal_date].dropna()
        eligible = eligible[px.reindex(eligible.index).notna() & (px.reindex(eligible.index) > 0)]
        selected = eligible.sort_values(ascending=False).head(config.top_n).index
        if config.weighting == "inverse_vol":
            inv = 1.0 / volatility.loc[signal_date].reindex(selected)
            inv = inv.replace([np.inf, -np.inf], np.nan).fillna(inv.median() if inv.notna().any() else 1.0)
            target_w = inv / inv.sum()
        else:
            target_w = pd.Series(1.0 / len(selected), index=selected) if len(selected) else pd.Series(dtype=float)
        if config.max_sector_weight and config.sectors:
            target_w = _cap_sector_weights(target_w, config.sectors, config.max_sector_weight)
        target_w = target_w * exposure

        current_value = shares * px.fillna(0.0)
        target_value = pd.Series(0.0, index=symbols)
        target_value[target_w.index] = target_w * value
        est_cost = cost_rate * float((target_value - current_value).abs().sum())
        target_value[target_w.index] = target_w * max(value - est_cost, 0.0)
        delta = target_value - current_value

        # Sells first, so realised gains and the resulting tax are known before buying.
        realized = 0.0
        sell_turnover = 0.0
        for symbol in delta[delta < -1e-9].index:
            price = float(px[symbol])
            if shares[symbol] <= 0 or not price > 0:
                continue
            closing = target_value[symbol] <= 1e-9
            sold = shares[symbol] if closing else min(-delta[symbol] / price, shares[symbol])
            fraction = sold / shares[symbol]
            proceeds = sold * price
            fee = cost_rate * proceeds
            basis_part = basis[symbol] * fraction
            realized += proceeds - fee - basis_part
            shares[symbol] -= sold
            basis[symbol] -= basis_part
            if closing:
                shares[symbol] = 0.0
                basis[symbol] = 0.0
            cash += proceeds - fee
            total_costs += fee
            sell_turnover += proceeds
        tax_payment = tax.realize(exec_date.year, realized) if realized != 0.0 else 0.0
        cash -= tax_payment

        buys = delta[delta > 1e-9]
        need = float(buys.sum()) * (1.0 + cost_rate)
        scale = min(1.0, cash / need) if need > 0 else 0.0
        buy_turnover = 0.0
        for symbol, amount in buys.items():
            amount *= scale
            price = float(px[symbol])
            fee = cost_rate * amount
            shares[symbol] += amount / price
            basis[symbol] += amount + fee
            cash -= amount + fee
            total_costs += fee
            buy_turnover += amount

        holdings[signal_date] = list(selected)
        records.append({
            "signal_date": signal_date,
            "exec_date": exec_date,
            "risk_off": risk_off,
            "exposure": exposure,
            "positions": int((shares > 0).sum()),
            "turnover": (sell_turnover + buy_turnover) / value if value > 0 else 0.0,
            "realized_gain": realized,
            "tax_payment": tax_payment,
            "portfolio_value": value,
        })

        segment_end = schedule[k + 1][1] if k + 1 < len(schedule) else prices.index[-1]
        segment = prices.loc[exec_date:segment_end]
        if k + 1 < len(schedule):
            segment = segment.iloc[:-1]
        held = shares[shares > 0]
        segment_values = segment[held.index].fillna(0.0).values @ held.values + cash if len(held) else pd.Series(cash, index=segment.index).values
        equity_parts.append(pd.Series(segment_values, index=segment.index))
        exposure_parts.append(pd.Series(exposure, index=segment.index))

    strategy_equity = pd.concat(equity_parts)
    strategy_equity = strategy_equity[~strategy_equity.index.duplicated(keep="last")]
    start_date = schedule[0][1]
    end_date = prices.index[-1]

    # Liquidate everything at the end to compare after-tax wealth.
    final_px = prices.loc[end_date]
    final_realized = 0.0
    final_cash = cash
    for symbol in shares[shares > 0].index:
        proceeds = float(shares[symbol] * final_px[symbol])
        fee = cost_rate * proceeds
        final_realized += proceeds - fee - float(basis[symbol])
        final_cash += proceeds - fee
        total_costs += fee
    final_tax = tax.realize(end_date.year, final_realized) if final_realized != 0.0 else 0.0
    final_after_tax = final_cash - final_tax

    # Benchmark: buy once, hold, sell once at the end.
    bench_series = benchmark_close.loc[start_date:end_date].dropna()
    if bench_series.empty:
        raise ValueError("Keine Benchmark-Kurse im Backtest-Zeitraum.")
    bench_units = config.initial_capital * (1.0 - cost_rate) / float(bench_series.iloc[0])
    bench_equity = bench_series * bench_units
    bench_proceeds = float(bench_equity.iloc[-1]) * (1.0 - cost_rate)
    bench_gain = bench_proceeds - config.initial_capital
    bench_tax = 0.0
    if config.apply_tax and bench_gain > 0:
        taxable = bench_gain * (1.0 - config.etf_partial_exemption)
        bench_tax = config.tax_rate * max(0.0, taxable - config.tax_allowance)
    bench_after_tax = bench_proceeds - bench_tax

    equity = pd.DataFrame({"strategy": strategy_equity, "benchmark": bench_equity}).ffill()
    equity["exposure"] = pd.concat(exposure_parts).groupby(level=0).last()
    rebalances = pd.DataFrame(records)

    strat_monthly = monthly_returns(equity["strategy"])
    metrics = _equity_metrics(equity["strategy"])
    metrics.update({
        "final_value_pre_tax": float(equity["strategy"].iloc[-1]),
        "final_value_after_tax": float(final_after_tax),
        "cagr_after_tax": _cagr(config.initial_capital, final_after_tax, start_date, end_date),
        "taxes_paid": float(tax.total_paid),
        "costs_paid": float(total_costs),
        "avg_turnover": float(rebalances["turnover"].mean()) if not rebalances.empty else 0.0,
        "share_risk_off": float(rebalances["risk_off"].mean()) if not rebalances.empty else 0.0,
        "n_rebalances": int(len(rebalances)),
        "monthly_sharpe": sharpe_ratio(strat_monthly, 12),
        "deflated_sharpe": deflated_sharpe_ratio(strat_monthly, config.n_trials),
        "start": start_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d"),
    })
    benchmark_metrics = _equity_metrics(equity["benchmark"])
    benchmark_metrics.update({
        "final_value_pre_tax": float(bench_equity.iloc[-1]),
        "final_value_after_tax": float(bench_after_tax),
        "cagr_after_tax": _cagr(config.initial_capital, bench_after_tax, start_date, end_date),
        "taxes_paid": float(bench_tax),
    })
    excess = (strat_monthly - monthly_returns(equity["benchmark"])).dropna()
    metrics["deflated_sharpe_excess"] = deflated_sharpe_ratio(excess, config.n_trials)

    return FactorBacktestResult(
        config=config,
        equity=equity,
        metrics=metrics,
        benchmark_metrics=benchmark_metrics,
        rebalances=rebalances,
        holdings=holdings,
    )
