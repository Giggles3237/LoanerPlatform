from loaner_platform.parsers import base_stock_number


def test_base_stock_number():
    assert base_stock_number("PB3626R") == "PB3626"
    assert base_stock_number("PB3626") == "PB3626"
    assert base_stock_number("pm4351r") == "PM4351"
