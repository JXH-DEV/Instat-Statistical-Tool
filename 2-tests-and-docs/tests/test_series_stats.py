"""The statistics behind the findings, checked against values worked out another way: a series built to have a known growth rate, a
known season, a known jump. Where the expected number is not obvious it is computed here with numpy or a textbook identity, not with the
program's own formula."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from instatkit.analysis.series import best_mean_shift, compute_series_stats, linear_trend, robust_outliers, seasonality
from instatkit.semantics.periods import make_half, make_month, make_quarter, make_year


def months(n, start=(2020, 1)):
    y, m = start
    out = []
    for _ in range(n):
        out.append(make_month(y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# --- the straight-line trend ---
def test_an_exact_line_has_the_slope_and_a_perfect_fit():
    up = linear_trend(5 + 2 * np.arange(8.0), log=False)
    assert (up.slope, up.r2, up.direction, up.n, up.annualised, up.log) == (pytest.approx(2.0), pytest.approx(1.0), "rising", 8, None, False)
    assert up.t_stat == math.inf
    assert linear_trend(40 - 3 * np.arange(8.0), log=False).direction == "falling"


def test_slope_fit_and_t_value_agree_with_the_textbook_formulas():
    y = np.array([1.0, 3, 2, 5, 4, 6, 5, 8])
    t = np.arange(8.0)
    r = np.corrcoef(t, y)[0, 1]
    trend = linear_trend(y, log=False)
    assert trend.slope == pytest.approx(np.polyfit(t, y, 1)[0])
    assert trend.r2 == pytest.approx(r ** 2)
    assert trend.t_stat == pytest.approx(r * math.sqrt((len(y) - 2) / (1 - r ** 2)))       # the t of a correlation is the t of the slope
    assert trend.direction == "rising"


def test_a_slope_that_could_be_chance_is_flat():
    y = np.array([5.0, 7, 4, 6, 5, 7, 4, 6])
    trend = linear_trend(y, log=False)
    assert abs(trend.t_stat) < 2 and trend.direction == "flat"
    assert linear_trend(np.array([5.0, 7, 4, 6, 5, 7, 4, 6, 5, 7, 4, 6]) + np.arange(12) * 2.0, log=False).direction == "rising"


def test_a_constant_series_has_no_trend_and_no_fit():
    trend = linear_trend(np.full(10, 7.0), log=False)
    assert (trend.slope, trend.r2, trend.direction) == (0.0, 0.0, "flat")


def test_too_few_points_or_no_time_spread_give_no_trend():
    assert linear_trend(np.array([1.0, 2, 3]), log=False) is None
    assert linear_trend(np.array([1.0, 2, 3, 4]), log=False) is not None
    assert linear_trend(np.array([1.0, 2, 3, 4]), log=False, t=np.full(4, 5.0)) is None


def test_a_log_trend_gives_the_yearly_growth_rate():
    y = 100 * 1.01 ** np.arange(24)
    monthly = linear_trend(y, log=True, lag=12)
    assert monthly.log and monthly.slope == pytest.approx(math.log(1.01))
    assert monthly.annualised == pytest.approx((1.01 ** 12 - 1) * 100)                       # 12.6825 % a year
    assert linear_trend(y, log=True, lag=4).annualised == pytest.approx((1.01 ** 4 - 1) * 100)
    assert linear_trend(y, log=True).annualised is None                                      # no calendar, no yearly rate


def test_a_decline_has_a_negative_yearly_rate():
    y = 100 * 0.99 ** np.arange(24)
    assert linear_trend(y, log=True, lag=12).annualised == pytest.approx((0.99 ** 12 - 1) * 100)


def test_a_series_that_touches_zero_is_fitted_in_levels_not_logs():
    trend = linear_trend(np.array([0.0, 1, 2, 3, 4, 5]), log=True, lag=12)
    assert not trend.log and trend.annualised is None and trend.slope == pytest.approx(1.0)


def test_positions_in_time_make_the_slope_per_period_when_months_are_missing():
    t = np.array([0.0, 1, 2, 3, 6, 7, 8])
    assert linear_trend(10 + 3 * t, log=False, t=t).slope == pytest.approx(3.0)


# --- seasonality ---
PATTERN = np.array([0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7])            # twelve factors that average 1


def test_a_repeating_yearly_pattern_is_found_with_its_peak_trough_and_size():
    y = np.tile(100 * PATTERN, 4)
    s = seasonality(y, np.tile(np.arange(12), 4), 12)
    assert s.multiplicative and s.lag == 12
    assert s.strength == pytest.approx(1.0)
    assert (s.peak, s.trough) == (5, 11)
    assert s.amplitude == pytest.approx(60.0)                                                  # 130 against 70, as a share of the level


def test_a_pattern_around_zero_is_additive():
    base = np.array([-5.0, -3, 0, 3, 5, 3, 0, -3, -5, -2, 1, 2])
    s = seasonality(np.tile(base, 4), np.tile(np.arange(12), 4), 12)
    assert not s.multiplicative
    assert (s.peak, s.trough, s.amplitude) == (4, 0, pytest.approx(10.0))


def test_a_quarterly_pattern():
    s = seasonality(np.tile([90.0, 100, 110, 100], 5), np.tile(np.arange(4), 5), 4)
    assert (s.peak, s.trough, s.lag) == (2, 0, 4) and s.amplitude == pytest.approx(20.0)


def test_noise_weakens_the_season_without_removing_it():
    rng = np.random.default_rng(3)
    y = np.tile(100 * PATTERN, 5) + rng.normal(0, 4, 60)
    s = seasonality(y, np.tile(np.arange(12), 5), 12)
    assert 0.5 < s.strength < 1.0 and s.peak in (4, 5, 6)


def test_no_season_is_reported_without_enough_regular_data():
    season = np.tile(np.arange(12), 3)
    assert seasonality(np.tile(100 * PATTERN, 3), season, 12) is not None                      # three full years is the minimum
    assert seasonality(np.tile(100 * PATTERN, 3)[:-1], season[:-1], 12) is None
    assert seasonality(np.tile(100 * PATTERN, 3), season, 1) is None
    gap = np.tile(100 * PATTERN, 4)
    gap[10] = np.nan
    assert seasonality(gap, np.tile(np.arange(12), 4), 12) is None
    assert seasonality(np.full(48, 5.0), np.tile(np.arange(12), 4), 12) is None                 # nothing varies


# --- unusual values ---
CALM = [10, 11, 10, 12, 11, 10, 11, 12, 10, 11, 10, 11, 12, 10, 11, 10, 12, 11, 10]


def test_one_wild_value_is_found_with_its_modified_z_score():
    x = np.array(CALM + [60.0])
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    found = robust_outliers(x)
    assert [i for i, _ in found] == [19]
    assert found[0][1] == pytest.approx(0.6745 * (60 - med) / mad)


def test_values_either_side_are_found_and_the_wildest_comes_first():
    x = np.array(CALM + [60.0, -30.0])
    assert [i for i, _ in robust_outliers(x)] == [20, 19] or [i for i, _ in robust_outliers(x)] == [19, 20]
    z = dict(robust_outliers(x))
    assert [i for i, _ in robust_outliers(x)] == sorted(z, key=lambda i: -abs(z[i]))
    assert z[19] > 0 > z[20]


def test_a_stricter_threshold_finds_fewer_and_nan_is_never_an_outlier():
    x = np.array(CALM + [60.0])
    assert robust_outliers(x, threshold=1000) == []
    with_gap = np.array(CALM + [60.0, np.nan])
    assert [i for i, _ in robust_outliers(with_gap)] == [19]


def test_ten_observations_are_needed():
    assert robust_outliers(np.array([10.0, 11, 10, 12, 11, 10, 11, 12, 10, 500])) != []
    assert robust_outliers(np.array([10.0, 11, 10, 12, 11, 10, 11, 12, 500])) == []
    assert robust_outliers(np.array([10.0, 11, 10, 12, 11, 10, 11, 12, 10, 500, np.nan, np.nan])) != []
    assert robust_outliers(np.array([10.0, 11, 10, 12, 11, 10, 11, 12, np.nan, 500, np.nan, np.nan])) == []


def test_when_most_values_are_equal_the_mean_deviation_stands_in_for_the_median_one():
    x = np.array([5.0] * 14 + [50.0])
    assert [i for i, _ in robust_outliers(x)] == [14]
    mean_dev = np.mean(np.abs(x - 5.0))
    assert robust_outliers(x)[0][1] == pytest.approx((50 - 5) / (1.253314 * mean_dev))
    assert robust_outliers(np.full(15, 5.0)) == []


# --- a lasting jump ---
def noise(n):
    return np.array([0.0, 0.2, -0.2] * n)[:n]


def test_a_jump_in_level_is_located_at_its_first_new_period():
    x = np.r_[10 + noise(12), 20 + noise(12)]
    k, before, after, t = best_mean_shift(x)
    assert k == 12 and before == pytest.approx(x[:12].mean()) and after == pytest.approx(x[12:].mean()) and t > 4


def test_a_drop_has_a_negative_t():
    x = np.r_[20 + noise(12), 10 + noise(12)]
    assert best_mean_shift(x)[3] < -4


def test_a_jump_right_after_the_first_segment_or_right_before_the_last_is_still_found():
    assert best_mean_shift(np.r_[0 + noise(4), 10 + noise(10)])[0] == 4
    assert best_mean_shift(np.r_[0 + noise(10), 10 + noise(4)])[0] == 10


def test_no_jump_is_reported_in_noise_or_in_a_short_or_incomplete_series():
    assert best_mean_shift(10 + noise(24)) is None
    jump = np.r_[0 + noise(5), 10 + noise(5)]
    assert best_mean_shift(jump) is not None and best_mean_shift(jump[:-1]) is None          # ten values are the least
    with_gap = np.r_[10 + noise(12), 20 + noise(12)]
    with_gap[3] = np.nan
    assert best_mean_shift(with_gap) is None


def test_a_jump_must_be_big_compared_with_the_ordinary_spread():
    wobble = np.array([1.0, -1.0] * 200)
    assert best_mean_shift(wobble + np.r_[np.zeros(200), np.full(200, 0.5)]) is None          # significant, but half a standard deviation
    assert best_mean_shift(wobble + np.r_[np.zeros(200), np.full(200, 1.0)]) is not None


# --- everything about one series ---
def test_a_series_with_fewer_than_two_values_has_no_statistics():
    assert compute_series_stats(months(3), np.array([np.nan, 5.0, np.nan])) is None
    assert compute_series_stats(months(3), np.array([np.nan, 5.0, 6.0])) is not None


def steady(n=36, rate=0.01):
    return months(n), 100 * (1 + rate) ** np.arange(n)


def test_a_steady_monthly_rise_has_known_changes_and_growth_rates():
    periods, values = steady()
    st = compute_series_stats(periods, values)
    assert (st.n, st.first, st.last, st.latest_period, st.freq) == (36, "2020-01", "2022-12", "2022-12", "M")
    assert st.latest == pytest.approx(values[-1]) and st.prev == pytest.approx(values[-2]) and st.prev_period == "2022-11"
    assert st.change_abs == pytest.approx(values[-1] - values[-2]) and st.change_pct == pytest.approx(1.0)
    assert (st.yoy_period, st.yoy) == ("2021-12", pytest.approx(values[-13]))
    assert st.yoy_pct == pytest.approx((1.01 ** 12 - 1) * 100) and st.yoy_abs == pytest.approx(values[-1] - values[-13])
    assert st.trend.annualised == pytest.approx((1.01 ** 12 - 1) * 100) and st.trend.direction == "rising"
    years = (date(2022, 12, 1) - date(2020, 1, 1)).days / 365.25
    assert st.cagr == pytest.approx(((values[-1] / values[0]) ** (1 / years) - 1) * 100)
    assert st.record == "high" and st.missing == 0 and st.pct_changes
    assert st.min_value == pytest.approx(100.0)


def test_a_missing_last_figure_means_the_latest_is_the_one_before():
    periods, values = steady()
    values[-1] = np.nan
    st = compute_series_stats(periods, values)
    assert (st.n, st.latest_period, st.prev_period) == (35, "2022-11", "2022-10")


def test_a_missing_figure_a_year_earlier_gives_no_year_on_year_change():
    periods, values = steady()
    values[-13] = np.nan
    st = compute_series_stats(periods, values)
    assert st.yoy is None and st.yoy_pct is None and st.yoy_period is None
    assert st.missing == 1


def test_year_on_year_needs_the_same_period_to_exist():
    periods, values = steady(11)
    assert compute_series_stats(periods, values).yoy is None                                  # eleven months: no December a year earlier
    periods, values = steady(13)
    assert compute_series_stats(periods, values).yoy_period == "2020-01"


def test_a_change_from_zero_has_no_percentage():
    st = compute_series_stats(months(14), np.r_[np.full(12, 0.0), 5.0, 8.0])
    assert st.prev == 5.0 and st.change_pct == pytest.approx(60.0)
    st = compute_series_stats(months(14), np.r_[np.full(12, 3.0), 0.0, 8.0])
    assert st.prev == 0.0 and st.change_pct is None


def test_gaps_are_counted_and_stop_the_season_from_being_estimated():
    periods = months(48)
    values = np.tile(100 * PATTERN, 4)
    assert compute_series_stats(periods, values).seasonality is not None
    values[20] = np.nan
    st = compute_series_stats(periods, values)
    assert st.missing == 1 and st.seasonality is None


def test_a_season_needs_three_years_and_is_found_with_exactly_three():
    values = np.tile(100 * PATTERN, 3)
    assert compute_series_stats(months(36), values).seasonality is not None
    assert compute_series_stats(months(35), values[:-1]).seasonality is None


def test_quarterly_and_half_yearly_seasons_use_their_own_calendar():
    quarters = [make_quarter(2018 + i // 4, i % 4 + 1) for i in range(20)]
    st = compute_series_stats(quarters, np.tile([90.0, 100, 110, 100], 5))
    assert (st.freq, st.seasonality.peak, st.seasonality.trough, st.seasonality.lag) == ("Q", 2, 0, 4)
    halves = [make_half(2016 + i // 2, i % 2 + 1) for i in range(16)]
    st = compute_series_stats(halves, np.tile([90.0, 110], 8))
    assert (st.freq, st.seasonality.peak, st.seasonality.trough, st.seasonality.lag) == ("H", 1, 0, 2)


def test_yearly_series_have_no_season_and_the_year_before_is_the_previous_value():
    years = [make_year(2010 + i) for i in range(10)]
    st = compute_series_stats(years, np.arange(10.0) * 5 + 100)
    assert st.seasonality is None and (st.yoy_period, st.yoy) == ("2018", 140.0)


def test_mixed_frequencies_have_no_calendar():
    st = compute_series_stats([make_month(2020, 1), make_month(2020, 2), make_year(2020), make_year(2021)], np.array([1.0, 2, 3, 4]))
    assert st.freq is None and st.yoy is None and st.missing == 0


def test_records_and_how_long_ago_the_last_better_value_was():
    rising = compute_series_stats(months(10), np.arange(10.0) + 1)
    assert (rising.record, rising.highest_since, rising.lowest_since) == ("high", None, None)
    falling = compute_series_stats(months(10), 20.0 - np.arange(10.0))
    assert falling.record == "low"
    short = compute_series_stats(months(7), np.arange(7.0) + 1)
    assert short.record is None                                                              # a record needs a history of eight
    tie = compute_series_stats(months(10), np.r_[np.arange(9.0), 8.0])
    assert tie.record is None                                                                # equal to the old maximum is not above it
    mid = compute_series_stats(months(11), np.array([1.0, 2, 9, 3, 3, 4, 4, 5, 5, 6, 7]))
    assert mid.record is None and mid.highest_since == "2020-03" and mid.lowest_since is None
    low = compute_series_stats(months(11), np.array([5.0, 4, 1, 6, 6, 5, 5, 4, 4, 3, 2]))
    assert low.record is None and low.lowest_since == "2020-03" and low.highest_since is None


def test_a_better_value_less_than_four_periods_back_is_not_worth_mentioning():
    st = compute_series_stats(months(10), np.array([1.0, 2, 3, 9, 3, 4, 5, 6, 7, 8]))
    assert st.highest_since == "2020-04"                                                     # the 9, five periods before the 8
    st = compute_series_stats(months(10), np.array([1.0, 2, 3, 4, 5, 9, 3, 4, 5, 8]))
    assert st.highest_since == "2020-06"                                                     # four periods back is enough
    st = compute_series_stats(months(10), np.array([1.0, 2, 3, 4, 5, 6, 9, 3, 4, 8]))
    assert st.highest_since is None                                                          # three is too recent to say "highest since"
    st = compute_series_stats(months(10), np.array([9.0, 8, 7, 6, 5, 1, 6, 7, 8, 2]))
    assert st.lowest_since == "2020-06" and st.record is None
    st = compute_series_stats(months(10), np.array([9.0, 8, 7, 6, 5, 6, 1, 7, 8, 2]))
    assert st.lowest_since is None


def test_a_spike_is_reported_with_its_period_and_size():
    periods = months(30)
    values = 100 + np.array([0.0, 1, -1] * 10)
    values[17] = 140.0
    st = compute_series_stats(periods, values)
    assert [o.period for o in st.outliers][0] == "2021-06"
    spike = st.outliers[0]
    assert spike.value == 140.0 and spike.change == pytest.approx((140 - values[16]) / values[16] * 100)


def test_a_rate_is_described_in_points_not_percent():
    values = 5 + np.array([0.0, 0.1, -0.1] * 10)
    values[17] = 9.0
    st = compute_series_stats(months(30), values, kind="rate")
    by_period = {o.period: o.change for o in st.outliers}
    assert not st.pct_changes
    assert by_period["2021-06"] == pytest.approx(9.0 - values[16])                         # the rise into the spike, in points
    assert by_period["2021-07"] == pytest.approx(values[18] - 9.0)                         # and the fall back


def test_a_lasting_jump_in_a_rate_is_found_at_its_first_period():
    values = np.r_[5 + noise(12), 9 + noise(12)]
    st = compute_series_stats(months(24), values, kind="rate")
    assert st.shift is not None and st.shift.period == "2021-01" and not st.shift.on_changes
    assert st.shift.before == pytest.approx(values[:12].mean()) and st.shift.after == pytest.approx(values[12:].mean())


def test_a_change_in_the_speed_of_growth_is_found_in_the_changes():
    monthly_rates = np.r_[0.2 + 0.05 * noise(11), 5 + 0.05 * noise(12)]                    # per cent a month: slow, then fast from the 13th month
    values = 100 * np.r_[1.0, np.cumprod(1 + monthly_rates / 100)]
    st = compute_series_stats(months(24), values)
    assert st.shift is not None and st.shift.on_changes and st.shift.period == "2021-01"
    assert st.shift.before == pytest.approx(0.2, abs=0.05) and st.shift.after == pytest.approx(5.0, abs=0.05)


def test_a_short_series_is_not_searched_for_a_jump():
    values = np.r_[5 + noise(7), 9 + noise(8)]
    assert compute_series_stats(months(15), values, kind="rate").shift is None
    assert compute_series_stats(months(16), np.r_[5 + noise(8), 9 + noise(8)], kind="rate").shift is not None


def test_compound_growth_needs_two_years_of_history():
    assert compute_series_stats(months(24), 100 * 1.01 ** np.arange(24)).cagr is None        # 23 months
    assert compute_series_stats(months(26), 100 * 1.01 ** np.arange(26)).cagr is not None    # 25 months: two years and a day
    assert compute_series_stats(months(36), 100 * 1.01 ** np.arange(36), kind="rate").cagr is None
    assert compute_series_stats(months(36), np.r_[-1.0, 100 * 1.01 ** np.arange(35)]).cagr is None


# --- boundaries the first version of these tests left open ---
def test_a_last_value_just_above_the_previous_low_or_below_the_previous_high_is_not_a_record():
    near_low = compute_series_stats(months(10), np.array([5.0, 6, 7, 6, 5, 4, 5, 6, 2, 3]))
    assert near_low.record is None                                                            # 3 is above the 2 of the month before
    near_high = compute_series_stats(months(10), np.array([5.0, 4, 3, 4, 5, 6, 5, 4, 9, 8]))
    assert near_high.record is None
    assert compute_series_stats(months(10), np.array([5.0, 6, 7, 6, 5, 4, 5, 6, 3, 2])).record == "low"
    assert compute_series_stats(months(10), np.array([5.0, 4, 3, 4, 5, 6, 5, 4, 8, 9])).record == "high"


def quarters(n, start=2020):
    return [make_quarter(start + k // 4, k % 4 + 1) for k in range(n)]


def test_from_fifteen_quarters_a_seasonal_series_is_compared_with_last_years_quarter():
    pattern = np.array([100.0, 140, 90, 60])

    def series(n):
        v = np.array([pattern[k % 4] * (1 + 0.02 * (k // 4)) + [0, 1, -1, 0.5][k % 4] * 0.3 for k in range(n)])
        v[13] *= 1.5                                                                         # the second quarter of 2023 is 50 % too high
        return v

    assert compute_series_stats(quarters(14), series(14)).outliers == []                     # the usual swing hides it from quarter-on-quarter changes
    st = compute_series_stats(quarters(15), series(15))
    assert [o.period for o in st.outliers] == ["2023-Q2"]
    assert st.outliers[0].change == pytest.approx(series(15)[13] / series(15)[9] * 100 - 100)       # against 2022-Q2, not against the quarter before


def test_the_size_of_a_jump_is_compared_with_the_sample_standard_deviation():
    wobble = np.random.default_rng(3).normal(0, 1, 400)

    def jump_of(step):
        x = wobble + np.r_[np.zeros(200), np.full(200, step)]
        _, before, after, _ = best_mean_shift(x, min_t=0, min_effect=0)
        return x, abs(after - before)

    step = 1.0
    for _ in range(200):                                                                     # find the step whose jump is 0.05 % above 0.75 standard deviations
        x, jump = jump_of(step)
        step *= 0.75 * np.std(x, ddof=1) * 1.0005 / jump
    x, jump = jump_of(step)
    n = len(x)
    assert 0.75 * np.std(x, ddof=1) < jump < 0.75 * np.std(x, ddof=1) * math.sqrt((n - 1) / (n - 2))      # between n - 1 and n - 2 in the divisor
    assert best_mean_shift(x) is not None
    assert best_mean_shift(jump_of(step * 0.99)[0]) is None


# --- a season has to be real ---
def test_a_pattern_in_every_year_predicts_the_years_it_was_not_made_from():
    assert seasonality(np.tile(100 * PATTERN, 4), np.tile(np.arange(12), 4), 12).held_out == pytest.approx(1.0)
    assert seasonality(np.tile([90.0, 100, 110, 100], 5), np.tile(np.arange(4), 5), 4).held_out == pytest.approx(1.0)


@pytest.mark.parametrize("years, lag, at_most", [(3, 12, 8), (4, 12, 3), (5, 4, 14), (8, 4, 6)])
def test_noise_alone_is_rarely_called_a_season(years, lag, at_most):
    """Twelve monthly averages of three years of noise explain about half of its variation by chance alone, so a season must also predict the
    cycles it was not made from. Before that check, three quarters of such series (and, with 4 quarters a year, a fifth to a half) passed;
    what is left is the chance that three or five cycles of four seasons agree by luck."""
    rng = np.random.default_rng(1)
    season = np.tile(np.arange(lag), years)
    found = sum(seasonality(100 * (1 + rng.normal(0, 0.01, years * lag)), season, lag) is not None for _ in range(200))
    assert found <= at_most


def test_a_smooth_kink_with_a_little_noise_is_not_a_season():
    rng = np.random.default_rng(2)
    season = np.tile(np.arange(12), 4)
    found = 0
    for _ in range(100):
        y = np.r_[100 + 0.5 * np.arange(24), 111.5 + np.arange(1, 25)] * (1 + rng.normal(0, 0.002, 48))
        found += seasonality(y, season, 12) is not None
    assert found <= 3


def test_weak_but_regular_seasons_are_still_found():
    rng = np.random.default_rng(4)
    season = np.tile(np.arange(12), 4)
    found = sum(seasonality((100 + 0.3 * np.arange(48)) * (1 + 0.03 * np.sin(2 * np.pi * np.arange(48) / 12) + rng.normal(0, 0.01, 48)),
                            season, 12) is not None for _ in range(50))
    assert found == 50


# --- unusual changes inside a regime ---
def test_the_first_months_of_a_new_regime_are_a_change_of_pattern_not_unusual_months():
    values = np.r_[100 + 0.5 * np.arange(24), 111.5 + np.arange(1, 25)]                     # a steady rise that becomes twice as steep
    periods = months(48)
    st = compute_series_stats(periods, values)
    assert st.shift is not None and st.shift.on_changes and st.outliers == []
    assert [p.label for p in periods].index(st.shift.period) == st.shift.at + 1


def test_a_real_spike_is_still_found_inside_the_new_regime():
    slow = 100 * np.cumprod(1 + (0.2 + 0.05 * noise(24)) / 100)
    fast = slow[-1] * np.cumprod(1 + (3 + 0.05 * noise(24)) / 100)
    values = np.r_[slow, fast]
    values[40:] *= 1.15
    st = compute_series_stats(months(48), values)
    assert st.shift is not None and st.shift.on_changes
    assert [o.period for o in st.outliers] == ["2023-05"] and st.outliers[0].change == pytest.approx(18.4, abs=0.1)


def test_a_short_new_regime_is_not_a_run_of_unusual_months():
    """Compared with the whole history, twelve months of 3 % growth after three years of 0.2 % are all 'unusual'."""
    slow = 100 * np.cumprod(1 + (0.2 + 0.02 * noise(36)) / 100)
    fast = slow[-1] * np.cumprod(1 + (3 + 0.02 * noise(12)) / 100)
    st = compute_series_stats(months(48), np.r_[slow, fast])
    assert st.shift is not None and st.shift.on_changes
    assert st.outliers == []


# --- the answers do not depend on the unit the numbers are written in ---
@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e3])
def test_a_jump_is_judged_against_the_spread_whatever_the_unit(scale):
    """A series of ratios between 0 and 1 and the same series in thousands must give the same verdict."""
    wobble = np.array([1.0, -1.0] * 200) * scale
    small = np.r_[np.zeros(200), np.full(200, 0.5 * scale)]
    big = np.r_[np.zeros(200), np.full(200, 1.0 * scale)]
    assert best_mean_shift(wobble + small) is None
    assert best_mean_shift(wobble + big) is not None


def test_a_growth_rate_is_found_for_values_between_zero_and_one():
    y = 0.2 * 1.01 ** np.arange(24)
    trend = linear_trend(y, log=True, lag=12)
    assert trend.log and trend.annualised == pytest.approx((1.01 ** 12 - 1) * 100)
    assert linear_trend(np.r_[y[:-1], 0.0], log=True, lag=12).log is False                      # a zero ends the logarithms


def test_the_centred_average_exists_for_a_series_exactly_one_window_long():
    from instatkit.analysis.series import _centered_ma

    out = _centered_ma(np.arange(13.0), 12)
    assert out[6] == pytest.approx(6.0) and np.isnan(np.delete(out, 6)).all()
    out = _centered_ma(np.arange(5.0), 4)
    assert out[2] == pytest.approx(2.0) and np.isnan(np.delete(out, 2)).all()
    out = _centered_ma(np.arange(3.0), 3)
    assert out[1] == pytest.approx(1.0)
    assert np.isnan(_centered_ma(np.arange(12.0), 12)).all()                                 # one value short: no average at all


def test_the_amplitude_of_multiplicative_seasons_is_measured_around_a_mean_of_one():
    """Seasonal factors multiplied by 8 % monthly growth. The amplitude is worked out here with the textbook steps: ratio to a centred
    2x12 moving average, the mean ratio of each month, then divided by the mean of the twelve."""
    factors = np.array([0.6, 0.7, 0.9, 1.0, 1.2, 1.5, 1.6, 1.4, 1.1, 0.9, 0.6, 0.5])
    factors = factors / factors.mean()
    y = np.array([factors[t % 12] * 1.08 ** t for t in range(48)])
    season = np.arange(48) % 12
    window = np.r_[0.5, np.ones(11), 0.5] / 12
    average = np.full(48, np.nan)
    average[6:42] = np.convolve(y, window, mode="valid")
    ratio = y / average
    index = np.array([np.nanmean(ratio[season == s]) for s in range(12)])
    index = index / index.mean()
    found = seasonality(y, season, 12)
    assert found is not None and found.multiplicative
    assert found.amplitude == pytest.approx((index.max() - index.min()) * 100)
    assert (found.peak, found.trough) == (int(index.argmax()), int(index.argmin())) == (6, 11)


# --- records that tie, and series that reach zero ---
def test_a_tie_with_an_earlier_value_is_still_the_highest_since_then():
    st = compute_series_stats(months(10), np.array([8.0, 1, 2, 3, 4, 5, 6, 7, 3, 8]))
    assert st.record is None and st.highest_since == "2020-01"
    st = compute_series_stats(months(10), np.array([1.0, 9, 8, 7, 6, 5, 4, 3, 5, 1]))
    assert st.record is None and st.lowest_since == "2020-01"


def test_a_series_that_reaches_zero_has_changes_in_units_not_percent():
    reaches_zero_last = compute_series_stats(months(12), np.r_[np.arange(5.0, 16.0), 0.0])
    assert not reaches_zero_last.pct_changes
    zero_inside = compute_series_stats(months(12), np.r_[5.0, 6, 0, 7, 8, 9, 10, 11, 12, 13, 14, 15])
    assert not zero_inside.pct_changes
    assert compute_series_stats(months(12), np.arange(1.0, 13.0) + 4).pct_changes
