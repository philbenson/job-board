from job_board.model_key.check_limits import CHECKS_PER_HOUR, CheckLimits

HOUR = 3600.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_one_check_at_a_time_per_person() -> None:
    limits = CheckLimits(clock=Clock())

    assert limits.admit(1) is None
    assert limits.admit(1) == "check-running"
    assert limits.admit(2) is None  # someone else is not held up
    limits.done(1)
    assert limits.admit(1) is None


def test_allows_ten_checks_in_any_rolling_hour() -> None:
    clock = Clock()
    limits = CheckLimits(clock=clock)
    for _ in range(CHECKS_PER_HOUR):
        assert limits.admit(1) is None
        limits.done(1)
        clock.now += 60

    assert limits.admit(1) == "too-many-checks"
    clock.now += HOUR - CHECKS_PER_HOUR * 60  # the first check is now an hour old
    assert limits.admit(1) is None


def test_a_refused_check_is_not_counted() -> None:
    clock = Clock()
    limits = CheckLimits(clock=clock)
    assert limits.admit(1) is None
    for _ in range(CHECKS_PER_HOUR * 2):
        assert limits.admit(1) == "check-running"
    limits.done(1)

    for _ in range(CHECKS_PER_HOUR - 1):
        assert limits.admit(1) is None
        limits.done(1)
    assert limits.admit(1) == "too-many-checks"


def test_forgets_a_person_once_their_last_check_is_an_hour_old() -> None:
    clock = Clock()
    limits = CheckLimits(clock=clock)
    for person in (1, 2, 3):
        assert limits.admit(person) is None
        limits.done(person)
    assert len(limits) == 3

    clock.now += HOUR
    assert limits.admit(4) is None

    assert len(limits) == 1  # only the person checking now
