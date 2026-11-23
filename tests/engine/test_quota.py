from sniper.engine.quota import EBAY_DAILY_BUDGET, projected_daily_calls


def test_projected_daily_calls():
    assert projected_daily_calls([300, 300, 300]) == 864
    assert projected_daily_calls([120] * 3) == 2160
    assert projected_daily_calls([7]) == 12343
    assert projected_daily_calls([]) == 0
    assert EBAY_DAILY_BUDGET == 4500
