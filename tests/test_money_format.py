from corredores.services.money_format import format_money


def test_format_money_thousands_comma():
    assert format_money(1234) == "1,234.00"
    assert format_money("2480.5") == "2,480.50"
    assert format_money(0) == "0.00"
    assert format_money(None) == "0.00"
    assert format_money(-1500.25) == "-1,500.25"
