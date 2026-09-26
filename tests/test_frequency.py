import pytest

from halbtax_plus.trips import parse_frequency


@pytest.mark.parametrize("spec,low,high", [
    ("2/w", 104, 104),
    ("2x/w", 104, 104),
    ("2 / week", 104, 104),
    ("0-1/w", 0, 52),
    ("1-2/WEEK", 52, 104),
    ("3/m", 36, 36),
    ("2-3/month", 24, 36),
    ("10/y", 10, 10),
    ("1-2/yr", 1, 2),
    ("4/year", 4, 4),
    ("0-2/w", 0, 104),
])
def test_valid_frequencies(spec, low, high):
    assert parse_frequency(spec) == (low, high)


@pytest.mark.parametrize("spec", [
    "", "2", "abc", "2/x", "2/w/e", "-1/w", "1-2", "w", "2/w @ 10:00",
])
def test_invalid_frequencies_raise(spec):
    with pytest.raises(ValueError):
        parse_frequency(spec)
