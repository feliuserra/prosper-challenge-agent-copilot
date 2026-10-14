#
# The one test detection uses (#58): is a proportion higher than (a multiple of) its
# baseline? Every signal is a proportion, so the same test serves all of them. Pure
# Python, so the detector needs no numerical library.
#
# The test is conditional on the events seen on both sides: given k1 + k2 events, k1
# is binomial with p = r*n1 / (r*n1 + n2) when the rate is exactly r times the
# baseline's. It is exact for small counts, normal (with a continuity correction) for
# large ones. It treats events as rare (Poisson); for common ones, such as a 25%
# hang-up rate, it is conservative: it flags less, never more.
#

import math

# Below this many expected events (or non-events) the exact tail is summed: the normal
# approximation overstates how unlikely a small count is (a quiet clinic's 17 transfers
# out of 148 calls against a 4.8% fleet: p = 0.00008 by the z-test, 0.001 exactly).
SMALL = 30


def p_greater(k1: int, n1: int, k2: int, n2: int, ratio: float = 1.0) -> float:
    """One-sided p-value that the rate k1/n1 is more than `ratio` times the baseline k2/n2."""
    events = k1 + k2
    if n1 <= 0 or n2 <= 0 or events == 0:
        return 1.0
    share = ratio * n1 / (ratio * n1 + n2)
    mean = events * share
    if k1 <= mean or min(mean, events - mean) >= SMALL:
        sd = math.sqrt(events * share * (1 - share))
        return 0.5 * math.erfc((k1 - 0.5 - mean) / sd / math.sqrt(2)) if sd else float(k1 <= mean)
    return binomial_tail(k1, events, share)


def binomial_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X binomial(n, p), summed in log space from k up."""
    if k <= 0:
        return 1.0
    if k > n or p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    log_p, log_q = math.log(p), math.log1p(-p)
    first = _log_choose(n, k) + k * log_p + (n - k) * log_q
    total, term = 1.0, 0.0  # terms relative to the first one, which is the largest (k > mean)
    for x in range(k + 1, n + 1):
        term += math.log(n - x + 1) - math.log(x) + log_p - log_q
        step = math.exp(term)
        total += step
        if step < 1e-15 * total:
            break
    return min(1.0, math.exp(first) * total)


def holm(pvalues: list[float]) -> list[float]:
    """Holm-adjusted p-values: compare each with alpha. Controls the chance of any false
    alarm among the tests, whatever their dependence."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
