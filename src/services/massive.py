"""Massive API service for fetching candlestick data."""

import logging
from datetime import datetime
from typing import Optional

from massive import RESTClient

from src.models.option_models import Candlestick, CandlestickData

logger = logging.getLogger(__name__)


class MassiveAPIError(Exception):
    """Custom exception for Massive API errors."""

    pass


class MassiveService:
    """Service for fetching candlestick data from Massive API."""

    def __init__(self, api_key: str):
        """
        Initialize Massive API service.

        Args:
            api_key: Massive API key for authentication
        """
        self.client = RESTClient(api_key=api_key)
        self.api_key = api_key

    def get_candlesticks(
        self,
        ticker: str,
        timeframe: str = "1minute",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50000,
    ) -> CandlestickData:
        """
        Fetch candlestick data for a given ticker with automatic pagination.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            timeframe: Candlestick timeframe (e.g., '1minute', '5minute', '1hour', '1day')
            from_date: Start date for data (inclusive)
            to_date: End date for data (inclusive)
            limit: Maximum number of candlesticks to fetch (50000 is API max per request)

        Returns:
            CandlestickData object containing candlesticks

        Raises:
            MassiveAPIError: If API request fails
        """
        try:
            candlesticks = []

            logger.info(
                f"Fetching candlesticks for {ticker} with timeframe {timeframe}"
            )

            # Extract multiplier and timespan from timeframe
            multiplier, timespan = self._parse_timeframe(timeframe)

            # Format parameters for API call
            params = {
                "limit": 50000,  # Max allowed per page
                "sort": "asc",
            }

            if from_date:
                params["from_"] = from_date.strftime("%Y-%m-%d")

            if to_date:
                params["to"] = to_date.strftime("%Y-%m-%d")

            logger.debug(f"API Request: ticker={ticker.upper()}, multiplier={multiplier}, timespan={timespan}, params={params}")

            # Use list_aggs which automatically handles pagination
            # Returns an iterator that automatically fetches all pages
            agg_iter = self.client.list_aggs(
                ticker=ticker.upper(),
                multiplier=multiplier,
                timespan=timespan,
                **params,
            )

            # Iterate through all results (pagination handled automatically)
            for result in agg_iter:
                if len(candlesticks) >= limit:
                    break

                try:
                    # Extract candlestick data from result object
                    timestamp = result.timestamp
                    if isinstance(timestamp, (int, float)):
                        # Convert milliseconds to seconds if needed
                        if timestamp > 1e11:  # Likely milliseconds
                            timestamp = timestamp / 1000
                        timestamp_dt = datetime.fromtimestamp(timestamp)
                    else:
                        timestamp_dt = timestamp

                    candlestick = Candlestick(
                        timestamp=timestamp_dt,
                        open=float(result.open),
                        high=float(result.high),
                        low=float(result.low),
                        close=float(result.close),
                        volume=int(result.volume) if result.volume else 0,
                        vwap=float(result.vwap) if hasattr(result, "vwap") and result.vwap else 0.0,
                    )
                    candlesticks.append(candlestick)
                except Exception as e:
                    logger.error(f"Error parsing candlestick: {e}, result type: {type(result)}")
                    logger.debug(f"Result details: {result}")

            logger.info(
                f"Retrieved {len(candlesticks)} candlesticks for {ticker}"
            )

            return CandlestickData(
                ticker=ticker.upper(),
                timeframe=timeframe,
                candlesticks=candlesticks,
            )

        except Exception as e:
            logger.error(f"Error fetching candlesticks: {str(e)}")
            raise MassiveAPIError(f"Failed to fetch candlesticks: {str(e)}") from e

    def get_daily_candlesticks(
        self,
        ticker: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> CandlestickData:
        """
        Convenience method to fetch daily candlestick data.

        Args:
            ticker: Stock ticker symbol
            from_date: Start date for data
            to_date: End date for data

        Returns:
            CandlestickData with daily candlesticks
        """
        return self.get_candlesticks(
            ticker=ticker,
            timeframe="1day",
            from_date=from_date,
            to_date=to_date,
        )

    @staticmethod
    def _parse_timeframe(timeframe: str) -> tuple[int, str]:
        """
        Parse timeframe string to extract multiplier and timespan.

        Args:
            timeframe: Timeframe string (e.g., '1minute', '5minute', '1hour', '4hour', '1day')

        Returns:
            Tuple of (multiplier, timespan)
        """
        timeframe_mapping = {
            "1minute": (1, "minute"),
            "3minute": (3, "minute"),
            "5minute": (5, "minute"),
            "10minute": (10, "minute"),
            "15minute": (15, "minute"),
            "30minute": (30, "minute"),
            "1hour": (1, "hour"),
            "4hour": (4, "hour"),
            "1day": (1, "day"),
            "1week": (1, "week"),
            "1month": (1, "month"),
        }

        multiplier, timespan = timeframe_mapping.get(timeframe.lower(), (1, "day"))
        logger.debug(f"Parsed timeframe {timeframe} to multiplier={multiplier}, timespan={timespan}")
        return multiplier, timespan
