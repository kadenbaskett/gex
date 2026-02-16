"""Parse option data from Schwab streaming API."""

import logging
from datetime import datetime

from src.models.option_models import OptionContract, OptionType

logger = logging.getLogger(__name__)


class OptionParser:
    """Parse option contracts from Schwab API responses."""

    @staticmethod
    def parse_option_chain(
        ticker: str, raw_option_data
    ) -> list[OptionContract]:
        """
        Parse option chain data from Schwab API response.

        Response structure:
        {
          "callExpDateMap": {
            "2026-02-17:2": {
              "657.0": [{contract}, {contract}],
              "658.0": [{contract}]
            }
          },
          "putExpDateMap": { ... }
        }

        Args:
            ticker: Stock ticker symbol
            raw_option_data: Raw option data from Schwab API (dict or Response object)

        Returns:
            List of OptionContract objects
        """
        contracts = []

        try:
            # Handle Response objects from schwab-py
            if hasattr(raw_option_data, "json"):
                raw_option_data = raw_option_data.json()
            elif not isinstance(raw_option_data, dict):
                logger.debug(f"Unexpected data type: {type(raw_option_data)}")
                return contracts

            # Process calls from callExpDateMap
            call_exp_map = raw_option_data.get("callExpDateMap", {})
            for exp_date_str, exp_data in call_exp_map.items():
                if not isinstance(exp_data, dict):
                    continue

                for strike_str, contracts_list in exp_data.items():
                    try:
                        strike = float(strike_str)

                        # contracts_list is a list of option contracts
                        if isinstance(contracts_list, list):
                            for contract_data in contracts_list:
                                contract = OptionParser._parse_contract(
                                    ticker, strike, OptionType.CALL, contract_data
                                )
                                if contract:
                                    contracts.append(contract)
                    except (ValueError, KeyError, TypeError) as e:
                        logger.debug(f"Failed to parse call {strike_str}: {e}")
                        continue

            # Process puts from putExpDateMap
            put_exp_map = raw_option_data.get("putExpDateMap", {})
            for exp_date_str, exp_data in put_exp_map.items():
                if not isinstance(exp_data, dict):
                    continue

                for strike_str, contracts_list in exp_data.items():
                    try:
                        strike = float(strike_str)

                        # contracts_list is a list of option contracts
                        if isinstance(contracts_list, list):
                            for contract_data in contracts_list:
                                contract = OptionParser._parse_contract(
                                    ticker, strike, OptionType.PUT, contract_data
                                )
                                if contract:
                                    contracts.append(contract)
                    except (ValueError, KeyError, TypeError) as e:
                        logger.debug(f"Failed to parse put {strike_str}: {e}")
                        continue

            logger.info(f"Successfully parsed {len(contracts)} option contracts")

        except Exception as e:
            logger.error(f"Error parsing option chain: {e}")

        return contracts

    @staticmethod
    def _parse_contract(
        ticker: str, strike: float, option_type: OptionType, data: dict
    ) -> OptionContract | None:
        """
        Parse a single option contract from Schwab API response.

        Args:
            ticker: Stock ticker
            strike: Strike price
            option_type: CALL or PUT
            data: Option data dictionary

        Returns:
            OptionContract or None if parsing fails (including missing gamma data)
        """
        try:
            # Parse gamma - skip contracts with no data (-999.0)
            gamma = float(data.get("gamma", -999.0))
            if gamma < 0:  # -999.0 or other negative = no data, skip this contract
                logger.debug(f"Skipping {option_type} ${strike}: no gamma data (gamma={gamma})")
                return None

            # Parse open interest
            open_interest = int(data.get("openInterest", 0))

            # Parse expiration date (ISO format string from Schwab)
            expiration_str = data.get("expirationDate", "")
            if expiration_str:
                # Parse ISO format: "2026-02-17T21:00:00.000+00:00"
                try:
                    expiration = datetime.fromisoformat(expiration_str.replace("+00:00", ""))
                except:
                    expiration = datetime.now()
            else:
                expiration = datetime.now()

            # Parse pricing data
            bid = float(data.get("bid", 0.0))
            ask = float(data.get("ask", 0.0))
            last_price = float(data.get("last", 0.0))  # "last" not "lastPrice"
            mark = float(data.get("mark", 0.0))

            # Use mark if available, else last
            if mark > 0:
                last_price = mark

            # Parse implied volatility
            volatility = float(data.get("volatility", 0.0))
            if volatility < 0:  # -999.0 means no data
                volatility = 0.0

            return OptionContract(
                ticker=ticker,
                strike=strike,
                expiration=expiration,
                gamma=gamma,
                open_interest=open_interest,
                option_type=option_type,
                bid=bid,
                ask=ask,
                last_price=last_price,
                implied_volatility=volatility,
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.debug(f"Failed to parse contract for {ticker} {strike} {option_type}: {e}")
            return None

    @staticmethod
    def extract_spot_price(raw_data) -> float | None:
        """
        Extract spot price from Schwab response.

        Prefers lastPrice from nested structures, falls back to bid/ask midpoint.

        Args:
            raw_data: Raw data from Schwab API (dict or Response object)

        Returns:
            Spot price or None if not found
        """
        try:
            # Handle Response objects
            if hasattr(raw_data, "json"):
                raw_data = raw_data.json()
            elif not isinstance(raw_data, dict):
                return None

            spot_price = 0.0

            # Try nested quote structure (ticker response)
            for key, value in raw_data.items():
                if isinstance(value, dict):
                    # Try quote.lastPrice (nested quote data)
                    if "quote" in value and isinstance(value["quote"], dict):
                        spot_price = float(value["quote"].get("lastPrice", 0) or value["quote"].get("mark", 0))
                        if spot_price > 0:
                            return spot_price

                    # Try extended.lastPrice
                    if "extended" in value and isinstance(value["extended"], dict):
                        spot_price = float(value["extended"].get("lastPrice", 0))
                        if spot_price > 0:
                            return spot_price

                    # Try direct lastPrice
                    if "lastPrice" in value:
                        spot_price = float(value["lastPrice"])
                        if spot_price > 0:
                            return spot_price

            # Fallback: try top-level fields
            if "lastPrice" in raw_data:
                return float(raw_data["lastPrice"])

            if "mark" in raw_data:
                return float(raw_data["mark"])

            # Fallback to bid/ask midpoint
            if "bid" in raw_data and "ask" in raw_data:
                bid = float(raw_data["bid"])
                ask = float(raw_data["ask"])
                return (bid + ask) / 2

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Failed to extract spot price: {e}")

        return None
