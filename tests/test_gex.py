"""Unit tests for GEX calculation and parsing."""

import pytest
from datetime import datetime, timedelta

from src.models.option_models import GammaLevel, GammaSnapshot, OptionContract, OptionType
from src.services.gex_calculator import (
    GEXCalculator,
    ExpirationFilter,
    get_next_friday,
    get_two_fridays_from_today,
)
from src.services.option_parser import OptionParser


class TestGEXCalculation:
    """Test GEX calculation logic."""

    def test_calculate_single_gex(self):
        """Test GEX formula calculation for calls (positive)."""
        # Test: Call GEX = +gamma * open_interest * 100 * spot_price^2
        gamma = 0.05
        open_interest = 1000
        spot_price = 500.0

        # For calls (default/no option_type specified)
        gex_call = GEXCalculator._calculate_single_gex(gamma, open_interest, spot_price)
        expected = 0.05 * 1000 * 100 * (500.0**2)

        assert gex_call == expected
        assert gex_call == 1_250_000_000.0

        # For puts (negative)
        gex_put = GEXCalculator._calculate_single_gex(gamma, open_interest, spot_price, OptionType.PUT)
        assert gex_put == -1_250_000_000.0

    def test_calculate_single_gex_zero_spot(self):
        """Test GEX calculation with zero spot price."""
        gex = GEXCalculator._calculate_single_gex(0.05, 1000, 0.0)
        assert gex == 0.0

    def test_calculate_single_gex_negative_gamma(self):
        """Test GEX calculation with negative gamma."""
        gex = GEXCalculator._calculate_single_gex(-0.05, 1000, 500.0)
        assert gex == 0.0

    def test_calculate_gex_full(self):
        """Test full GEX calculation with multiple contracts."""
        contracts = [
            OptionContract(
                ticker="SPY",
                strike=500.0,
                expiration=datetime.now(),
                gamma=0.05,
                open_interest=1000,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=500.0,
                expiration=datetime.now(),
                gamma=0.04,
                open_interest=1200,
                option_type=OptionType.PUT,
            ),
            OptionContract(
                ticker="SPY",
                strike=505.0,
                expiration=datetime.now(),
                gamma=0.03,
                open_interest=800,
                option_type=OptionType.CALL,
            ),
        ]

        spot_price = 502.0
        snapshot = GEXCalculator.calculate_gex(contracts, spot_price)

        # Verify snapshot structure
        assert snapshot.ticker == "SPY"
        assert snapshot.spot_price == 502.0
        assert len(snapshot.levels) == 2

        # Check 500 strike has both call and put (call positive, put negative)
        level_500 = snapshot.levels[500.0]
        assert level_500.call_gex > 0  # Positive (calls)
        assert level_500.put_gex < 0   # Negative (puts)
        assert level_500.total_gex == level_500.call_gex + level_500.put_gex

        # Check 505 strike has only call (positive)
        level_505 = snapshot.levels[505.0]
        assert level_505.call_gex > 0  # Positive (calls)
        assert level_505.put_gex == 0.0

    def test_calculate_gex_empty_contracts(self):
        """Test GEX calculation with no contracts."""
        with pytest.raises(ValueError):
            GEXCalculator.calculate_gex([], 500.0)

    def test_filter_strikes(self):
        """Test strike filtering around ATM."""
        contracts = [
            OptionContract(
                ticker="SPY",
                strike=float(strike),
                expiration=datetime.now(),
                gamma=0.01,
                open_interest=100,
                option_type=OptionType.CALL,
            )
            for strike in range(480, 521)  # 480 to 520 (inclusive)
        ]

        snapshot = GEXCalculator.calculate_gex(contracts, 500.0)
        assert len(snapshot.levels) == 41  # All strikes

        # Filter to ATM ± 20
        filtered = GEXCalculator.filter_strikes(snapshot, range_multiplier=20)
        assert len(filtered.levels) == 41  # 480-520 is 41 strikes
        assert 480.0 in filtered.levels
        assert 520.0 in filtered.levels

    def test_top_strikes(self):
        """Test getting top strikes by gamma."""
        contracts = [
            OptionContract(
                ticker="SPY",
                strike=500.0,
                expiration=datetime.now(),
                gamma=0.10,  # High gamma
                open_interest=1000,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=505.0,
                expiration=datetime.now(),
                gamma=0.05,  # Medium gamma
                open_interest=500,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=510.0,
                expiration=datetime.now(),
                gamma=0.02,  # Low gamma
                open_interest=200,
                option_type=OptionType.CALL,
            ),
        ]

        snapshot = GEXCalculator.calculate_gex(contracts, 502.0)
        top = snapshot.top_strikes(n=2)

        assert len(top) == 2
        # Should be sorted by absolute gamma
        assert top[0][0] == 500.0  # Highest gamma
        assert top[1][0] == 505.0  # Second highest


class TestOptionParser:
    """Test option data parsing."""

    def test_parse_option_chain(self):
        """Test parsing Schwab option chain data."""
        # Schwab API returns callExpDateMap and putExpDateMap with nested structure
        raw_data = {
            "callExpDateMap": {
                "2026-02-17:2": {
                    "500.0": [
                        {
                            "gamma": 0.05,
                            "openInterest": 1000,
                            "bid": 5.0,
                            "ask": 5.10,
                            "last": 5.05,
                            "volatility": 0.25,
                            "expirationDate": "2026-02-17T21:00:00.000+00:00",
                        },
                    ],
                    "505.0": [
                        {
                            "gamma": 0.03,
                            "openInterest": 800,
                            "bid": 3.0,
                            "ask": 3.10,
                            "volatility": 0.20,
                            "expirationDate": "2026-02-17T21:00:00.000+00:00",
                        },
                    ],
                },
            },
            "putExpDateMap": {
                "2026-02-17:2": {
                    "500.0": [
                        {
                            "gamma": 0.04,
                            "openInterest": 1200,
                            "bid": 3.5,
                            "ask": 3.60,
                            "volatility": 0.22,
                            "expirationDate": "2026-02-17T21:00:00.000+00:00",
                        },
                    ],
                },
            },
        }

        contracts = OptionParser.parse_option_chain("SPY", raw_data)

        assert len(contracts) == 3
        assert contracts[0].ticker == "SPY"
        assert any(c.strike == 500.0 and c.option_type == OptionType.CALL for c in contracts)
        assert any(c.strike == 500.0 and c.option_type == OptionType.PUT for c in contracts)
        assert any(c.strike == 505.0 and c.option_type == OptionType.CALL for c in contracts)

    def test_parse_contract(self):
        """Test parsing single contract."""
        data = {
            "gamma": 0.05,
            "openInterest": 1000,
            "bid": 5.0,
            "ask": 5.10,
            "lastPrice": 5.05,
            "impliedVolatility": 0.25,
            "expirationDate": 1709251200000,
        }

        contract = OptionParser._parse_contract("SPY", 500.0, OptionType.CALL, data)

        assert contract is not None
        assert contract.ticker == "SPY"
        assert contract.strike == 500.0
        assert contract.option_type == OptionType.CALL
        assert contract.gamma == 0.05
        assert contract.open_interest == 1000
        assert contract.bid == 5.0
        assert contract.ask == 5.10

    def test_parse_contract_missing_fields(self):
        """Test parsing with missing optional fields."""
        data = {"gamma": 0.05, "openInterest": 1000}

        contract = OptionParser._parse_contract("SPY", 500.0, OptionType.CALL, data)

        assert contract is not None
        assert contract.gamma == 0.05
        assert contract.bid == 0.0
        assert contract.ask == 0.0

    def test_parse_contract_invalid_data(self):
        """Test parsing with invalid data."""
        data = {"gamma": "invalid", "openInterest": "not_a_number"}

        contract = OptionParser._parse_contract("SPY", 500.0, OptionType.CALL, data)

        assert contract is None

    def test_extract_spot_price(self):
        """Test extracting spot price from data."""
        data = {"lastPrice": 502.50, "mark": 502.45}

        spot = OptionParser.extract_spot_price(data)

        assert spot == 502.50

    def test_extract_spot_price_fallback_to_midpoint(self):
        """Test extracting spot price falls back to bid/ask midpoint if lastPrice unavailable."""
        data = {"bid": 500.0, "ask": 502.0}

        spot = OptionParser.extract_spot_price(data)

        assert spot == 501.0  # Midpoint of bid/ask

    def test_extract_spot_price_not_found(self):
        """Test extracting spot price returns None when unavailable."""
        data = {"impliedVolatility": 0.25, "gamma": 0.05}

        spot = OptionParser.extract_spot_price(data)

        assert spot is None


class TestGammaLevel:
    """Test GammaLevel model."""

    def test_total_gex_calculation(self):
        """Test total_gex property (positive calls, negative puts)."""
        level = GammaLevel(strike=500.0, call_gex=1_000_000.0, put_gex=-500_000.0)

        assert level.total_gex == 500_000.0

    def test_total_gex_zero(self):
        """Test total_gex when both are zero."""
        level = GammaLevel(strike=500.0)

        assert level.total_gex == 0.0


class TestExpirationFiltering:
    """Test expiration date filtering."""

    def test_next_friday_calculation(self):
        """Test next Friday calculation."""
        next_friday = get_next_friday()

        # Verify it's a Friday (weekday 4)
        assert next_friday.weekday() == 4

        # Verify it's in the future
        assert next_friday.date() >= datetime.now().date()

    def test_two_fridays_calculation(self):
        """Test two Fridays from today calculation."""
        two_fridays = get_two_fridays_from_today()
        next_friday = get_next_friday()

        # Should be 7 days after next Friday
        assert (two_fridays.date() - next_friday.date()).days == 7

        # Should be a Friday
        assert two_fridays.weekday() == 4

    def test_filter_by_expiration_today(self):
        """Test filtering for today's expirations."""
        today = datetime.now()
        tomorrow = today + timedelta(days=1)

        contracts = [
            OptionContract(
                ticker="SPY",
                strike=500.0,
                expiration=today,
                gamma=0.05,
                open_interest=1000,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=505.0,
                expiration=tomorrow,
                gamma=0.03,
                open_interest=800,
                option_type=OptionType.CALL,
            ),
        ]

        filtered = GEXCalculator.filter_by_expiration(contracts, ExpirationFilter.TODAY)

        assert len(filtered) == 1
        assert filtered[0].strike == 500.0

    def test_filter_by_expiration_next_friday(self):
        """Test filtering for next Friday or earlier."""
        today = datetime.now()
        next_friday = get_next_friday()
        day_after_friday = next_friday + timedelta(days=1)

        contracts = [
            OptionContract(
                ticker="SPY",
                strike=500.0,
                expiration=today,
                gamma=0.05,
                open_interest=1000,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=505.0,
                expiration=next_friday,
                gamma=0.03,
                open_interest=800,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=510.0,
                expiration=day_after_friday,
                gamma=0.02,
                open_interest=600,
                option_type=OptionType.CALL,
            ),
        ]

        filtered = GEXCalculator.filter_by_expiration(
            contracts, ExpirationFilter.NEXT_FRIDAY
        )

        # Should include today and next Friday, but not after
        assert len(filtered) == 2
        assert any(c.strike == 500.0 for c in filtered)
        assert any(c.strike == 505.0 for c in filtered)
        assert not any(c.strike == 510.0 for c in filtered)

    def test_filter_by_expiration_two_fridays(self):
        """Test filtering for two Fridays or earlier."""
        today = datetime.now()
        next_friday = get_next_friday()
        two_fridays = get_two_fridays_from_today()
        day_after_two_fridays = two_fridays + timedelta(days=1)

        contracts = [
            OptionContract(
                ticker="SPY",
                strike=500.0,
                expiration=today,
                gamma=0.05,
                open_interest=1000,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=505.0,
                expiration=next_friday,
                gamma=0.03,
                open_interest=800,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=510.0,
                expiration=two_fridays,
                gamma=0.02,
                open_interest=600,
                option_type=OptionType.CALL,
            ),
            OptionContract(
                ticker="SPY",
                strike=515.0,
                expiration=day_after_two_fridays,
                gamma=0.01,
                open_interest=400,
                option_type=OptionType.CALL,
            ),
        ]

        filtered = GEXCalculator.filter_by_expiration(
            contracts, ExpirationFilter.TWO_FRIDAYS
        )

        # Should include everything up to two Fridays
        assert len(filtered) == 3
        assert not any(c.strike == 515.0 for c in filtered)
