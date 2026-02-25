"""Pydantic models for option data."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OptionType(str, Enum):
    """Option type enumeration."""

    CALL = "CALL"
    PUT = "PUT"


class OptionContract(BaseModel):
    """Represents a single option contract."""

    ticker: str
    strike: float
    expiration: datetime
    gamma: float
    open_interest: int
    option_type: OptionType
    bid: float = 0.0
    ask: float = 0.0
    last_price: float = 0.0
    implied_volatility: float = 0.0


class GammaLevel(BaseModel):
    """Gamma exposure for a single strike."""

    strike: float
    call_gex: float = 0.0
    put_gex: float = 0.0

    @property
    def total_gex(self) -> float:
        """Calculate total gamma exposure."""
        return self.call_gex + self.put_gex


class GammaSnapshot(BaseModel):
    """Snapshot of all gamma levels at a point in time."""

    ticker: str
    timestamp: datetime
    spot_price: float
    levels: dict[float, GammaLevel] = Field(default_factory=dict)

    def top_strikes(self, n: int = 10) -> list[tuple[float, float]]:
        """Get top N strikes by absolute gamma exposure."""
        sorted_strikes = sorted(
            self.levels.items(), key=lambda x: abs(x[1].total_gex), reverse=True
        )
        return [(strike, level.total_gex) for strike, level in sorted_strikes[:n]]


class Candlestick(BaseModel):
    """Represents OHLCV candlestick data."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float = 0.0


class CandlestickData(BaseModel):
    """Container for candlestick data from Massive API."""

    ticker: str
    timeframe: str
    candlesticks: list[Candlestick] = Field(default_factory=list)
