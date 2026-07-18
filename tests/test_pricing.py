"""Pricing engine tests.

Expected values are taken from the cached results of the dealership's
Simple_Calculator_2026.xlsx 'Primary' sheet, so these tests pin the engine
to the spreadsheet it replaces.
"""

import pytest

from loaner_platform.models import ModelProgram, RateBook, VAutoVehicle
from loaner_platform.pricing import excel_round, price_unit

DISCOUNT_CHART = [
    (0, 0.0), (1000, 0.0), (4000, 800.0), (5000, 1600.0),
    (6000, 2500.0), (7500, 3500.0), (10000, 5900.0), (15000, 6900.0),
]


@pytest.fixture
def ratebook():
    programs = {
        "2025 BMW 2 Series 228 xDrive Gran Coupe": ModelProgram(
            "2025 BMW 2 Series 228 xDrive Gran Coupe", 0.00095, 0.57, 1000, True),
        "2025 BMW 4 Series 430i xDrive": ModelProgram(
            "2025 BMW 4 Series 430i xDrive", 0.002, 0.54, 0, True),
        "2025 BMW 7 Series 750e xDrive": ModelProgram(
            "2025 BMW 7 Series 750e xDrive", 0.0013, 0.53, 5750, False),
        "2026 BMW 2 Series M235i xDrive": ModelProgram(
            "2026 BMW 2 Series M235i xDrive", 0.00095, 0.57, 0, True),
        "2026 MINI Cooper S": ModelProgram(
            "2026 MINI Cooper S", 0.0022, 0.58, 1000, True),
    }
    return RateBook(programs=programs, discount_chart=DISCOUNT_CHART)


def vehicle(stock, model, odo, list_price, msrp, cost=None):
    return VAutoVehicle(stock, model, "Test Color", odo, "ABCD1234",
                        None, list_price, cost, msrp)


def test_excel_round_half_away_from_zero():
    assert excel_round(408.5) == 409
    assert excel_round(408.4) == 408
    assert excel_round(-2.5) == -3


class TestKnownUnits:
    """Each case mirrors a real row from the Primary sheet."""

    def test_pb3255(self, ratebook):
        u = price_unit(vehicle("PB3255", "2025 BMW 2 Series 228 xDrive Gran Coupe",
                               9355, 38323, 45475), ratebook)
        assert u.sale_price == pytest.approx(38322.5)
        assert u.term == 39
        assert u.residual_amount == pytest.approx(23707.0)
        assert u.lease_payment == 408

    def test_pb3031(self, ratebook):
        u = price_unit(vehicle("PB3031", "2025 BMW 4 Series 430i xDrive",
                               14237, 47043, 57970), ratebook)
        assert u.sale_price == pytest.approx(47043)
        assert u.lease_payment == 641

    def test_pb3423_low_miles_36_month(self, ratebook):
        u = price_unit(vehicle("PB3423", "2025 BMW 7 Series 750e xDrive",
                               150, 104990, 113890), ratebook)
        assert u.term == 36
        assert u.sale_price == pytest.approx(104989.65)
        assert u.lease_payment == 1293

    def test_pb3817_under_500_miles_residual_bonus(self, ratebook):
        # (odo - 500) goes negative below 500 miles, raising the residual.
        u = price_unit(vehicle("PB3817", "2026 BMW 2 Series M235i xDrive",
                               2, 50422, 53925), ratebook)
        assert u.residual_amount == pytest.approx(30861.75)
        assert u.lease_payment == 579


class TestGuards:
    def test_over_program_miles(self, ratebook):
        u = price_unit(vehicle("PB0001", "2025 BMW 4 Series 430i xDrive",
                               16000, 40000, 50000), ratebook)
        assert u.status == "over_miles"
        assert u.lease_payment is None

    def test_unknown_model(self, ratebook):
        u = price_unit(vehicle("PB0002", "2019 BMW X9", 5000, 40000, 50000), ratebook)
        assert u.status == "no_program"

    def test_missing_msrp(self, ratebook):
        u = price_unit(vehicle("PB0003", "2026 MINI Cooper S", 5000, 40000, None), ratebook)
        assert u.status == "no_msrp"

    def test_base_suffix_falls_back_to_program(self, ratebook):
        u = price_unit(vehicle("PM4351", "2026 MINI Cooper S Base",
                               254, 37390, 37390), ratebook)
        assert u.status == "ok"
        assert u.lease_payment is not None

    def test_miles_default_uses_greater_reading(self, ratebook):
        v = vehicle("PB0004", "2026 MINI Cooper S", 3000, 40000, 42000)
        u = price_unit(v, ratebook, tsd_miles=4200)
        assert u.odometer == 4200
        assert u.mileage_updated is True
        # mileage adj crosses the 4000 breakpoint only with the TSD reading
        assert u.mileage_adj == 800.0


def test_discount_chart_range_lookup(ratebook):
    assert ratebook.mileage_discount(0) == 0
    assert ratebook.mileage_discount(3999) == 0
    assert ratebook.mileage_discount(4000) == 800
    assert ratebook.mileage_discount(9999) == 3500
    assert ratebook.mileage_discount(14237) == 5900
    assert ratebook.mileage_discount(20000) == 6900
