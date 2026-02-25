"""Gamma exposure calculation service."""

import logging
from datetime import datetime, timedelta
from enum import Enum

from src.models.option_models import GammaLevel, GammaSnapshot, OptionContract, OptionType

logger = logging.getLogger(__name__)


class ExpirationFilter(str, Enum):
    """Expiration date filter options."""

    TODAY = "today"
    NEXT_FRIDAY = "next-friday"
    TWO_FRIDAYS = "two-fridays"
    ALL = "all"


def get_next_friday() -> datetime:
    """Get the next Friday from today."""
    today = datetime.now().date()
    days_until_friday = (4 - today.weekday()) % 7  # 4 = Friday
    if days_until_friday == 0:
        days_until_friday = 7  # If today is Friday, get next Friday
    return datetime.combine(today + timedelta(days=days_until_friday), datetime.min.time())


def get_two_fridays_from_today() -> datetime:
    """Get the Friday two weeks from today."""
    next_friday = get_next_friday()
    return next_friday + timedelta(days=7)


class GEXCalculator:
    """Calculate gamma exposure levels from option contracts."""

    @staticmethod
    def calculate_gex(
        contracts: list[OptionContract], spot_price: float
    ) -> GammaSnapshot:
        """
        Calculate gamma exposure for all option contracts.

        Call GEX = +gamma * open_interest * 100 * spot_price^2 (positive)
        Put GEX = -gamma * open_interest * 100 * spot_price^2 (negative)

        Positive GEX = Bullish zone (dealers long gamma, reduce volatility)
        Negative GEX = Bearish zone (dealers short gamma, amplify volatility)

        Args:
            contracts: List of option contracts (with valid gamma data)
            spot_price: Current spot price of underlying

        Returns:
            GammaSnapshot with gamma exposure by strike (mixed positive/negative)
        """
        if not contracts:
            raise ValueError("No contracts with valid gamma data provided for GEX calculation")

        logger.info(f"Calculating GEX for {len(contracts)} contracts with valid gamma data")

        # Get ticker from first contract
        ticker = contracts[0].ticker

        # Group by strike and calculate GEX
        gamma_levels: dict[float, GammaLevel] = {}

        for contract in contracts:
            if contract.strike not in gamma_levels:
                gamma_levels[contract.strike] = GammaLevel(strike=contract.strike)

            level = gamma_levels[contract.strike]

            # Calculate gamma exposure
            gex = GEXCalculator._calculate_single_gex(
                gamma=contract.gamma,
                open_interest=contract.open_interest,
                spot_price=spot_price,
                option_type=contract.option_type,
            )

            # Assign to appropriate option type
            if contract.option_type == OptionType.CALL:
                level.call_gex = gex
            else:
                level.put_gex = gex

        return GammaSnapshot(
            ticker=ticker,
            timestamp=datetime.now(),
            spot_price=spot_price,
            levels=gamma_levels,
        )

    @staticmethod
    def _calculate_single_gex(gamma: float, open_interest: int, spot_price: float, option_type: OptionType = None) -> float:
        """
        Calculate GEX for a single option.

        Calls: GEX = +gamma * open_interest * 100 * spot_price^2 (positive)
        Puts: GEX = -gamma * open_interest * 100 * spot_price^2 (negative)

        Positive GEX = Bullish zone (dealers long gamma, reduce volatility)
        Negative GEX = Bearish zone (dealers short gamma, amplify volatility)

        Args:
            gamma: Option gamma value (0-1 range)
            open_interest: Number of contracts
            spot_price: Current spot price
            option_type: OptionType.CALL or OptionType.PUT (used to determine sign)

        Returns:
            Gamma exposure value (positive for calls, negative for puts)
        """
        if spot_price <= 0:
            logger.warning(f"Invalid spot price: {spot_price}")
            return 0.0

        if gamma < 0:
            logger.warning(f"Negative gamma: {gamma}")
            gamma = 0.0

        # Base GEX calculation
        gex = gamma * open_interest * 100 * (spot_price**2)

        # Apply sign based on option type
        # Calls are positive, puts are negative
        if option_type == OptionType.PUT:
            gex = -gex

        return gex

    @staticmethod
    def filter_strikes(snapshot: GammaSnapshot, range_multiplier: int = 20) -> GammaSnapshot:
        """
        Filter strikes to ATM ± range.

        Args:
            snapshot: Current gamma snapshot
            range_multiplier: Number of strikes to keep above/below ATM

        Returns:
            Filtered snapshot
        """
        spot = snapshot.spot_price

        # Filter levels
        filtered_levels = {
            strike: level
            for strike, level in snapshot.levels.items()
            if abs(strike - spot) <= range_multiplier
        }

        snapshot.levels = filtered_levels
        return snapshot

    @staticmethod
    def filter_by_expiration(
        contracts: list[OptionContract], expiration_filter: ExpirationFilter
    ) -> list[OptionContract]:
        """
        Filter contracts by expiration date.

        Args:
            contracts: List of option contracts
            expiration_filter: Which expiration to include

        Returns:
            Filtered list of contracts
        """
        if expiration_filter == ExpirationFilter.TODAY:
            cutoff_date = datetime.now().date()
            return [
                c
                for c in contracts
                if c.expiration.date() == cutoff_date
            ]

        elif expiration_filter == ExpirationFilter.NEXT_FRIDAY:
            cutoff_date = get_next_friday().date()
            return [
                c
                for c in contracts
                if c.expiration.date() <= cutoff_date
            ]

        elif expiration_filter == ExpirationFilter.TWO_FRIDAYS:
            cutoff_date = get_two_fridays_from_today().date()
            return [
                c
                for c in contracts
                if c.expiration.date() <= cutoff_date
            ]

        elif expiration_filter == ExpirationFilter.ALL:
            return contracts

        return contracts
