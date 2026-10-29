"""Indicators on plain lists. Every function returns a list the same length as
its input, with None during the warm-up, and value[i] uses only data[0..i]
(no look-ahead, so the backtest can use the same code).
"""


def sma(xs, n):
    out = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(xs[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(xs)):
        prev = xs[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def true_range(h, l, c):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def wilder(xs, n):
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    prev = sum(xs[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(xs)):
        prev = (prev * (n - 1) + xs[i]) / n
        out[i] = prev
    return out


def atr(h, l, c, n=14):
    return wilder(true_range(h, l, c), n)


def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    gains = [0.0] + [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    losses = [0.0] + [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    ag = sum(gains[1:n + 1]) / n
    al = sum(losses[1:n + 1]) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def adx(h, l, c, n=14):
    size = len(c)
    out = [None] * size
    if size < 2 * n + 1:
        return out
    pdm, ndm = [0.0], [0.0]
    for i in range(1, size):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    tr = true_range(h, l, c)
    atr_, pdi_s, ndi_s = wilder(tr[1:], n), wilder(pdm[1:], n), wilder(ndm[1:], n)
    dx = []
    for a, p, m in zip(atr_, pdi_s, ndi_s):
        if a is None or a == 0:
            dx.append(None)
            continue
        pdi, ndi = 100 * p / a, 100 * m / a
        dx.append(0.0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi))
    vals = [d for d in dx if d is not None]
    if len(vals) < n:
        return out
    first = dx.index(vals[0])
    smooth = wilder(vals, n)
    for j, s in enumerate(smooth):
        if s is not None:
            out[first + j + 1] = s
    return out


def highest(xs, n):
    out = [None] * len(xs)
    for i in range(n - 1, len(xs)):
        out[i] = max(xs[i - n + 1:i + 1])
    return out


def lowest(xs, n):
    out = [None] * len(xs)
    for i in range(n - 1, len(xs)):
        out[i] = min(xs[i - n + 1:i + 1])
    return out


def rvol(v, n=20):
    """Volume today / average volume of the n bars before today."""
    out = [None] * len(v)
    s = 0.0
    for i in range(len(v)):
        if i >= n:
            avg = s / n
            out[i] = (v[i] / avg) if avg > 0 else None
            s -= v[i - n]
        s += v[i]
    return out


def roc(c, n):
    out = [None] * len(c)
    for i in range(n, len(c)):
        if c[i - n]:
            out[i] = 100.0 * (c[i] / c[i - n] - 1)
    return out


def vwap(h, l, c, v, idx):
    """Cumulative VWAP over the bar indexes in idx (one session). Returns {i: vwap}."""
    out, pv, vv = {}, 0.0, 0.0
    for i in idx:
        tp = (h[i] + l[i] + c[i]) / 3.0
        pv += tp * v[i]
        vv += v[i]
        out[i] = pv / vv if vv > 0 else tp
    return out


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return 100.0 * (a / b - 1)


def slope(xs, i, n=5):
    """% change of a series over n bars ending at i (None if not available)."""
    if i - n < 0 or xs[i] is None or xs[i - n] in (None, 0):
        return None
    return 100.0 * (xs[i] / xs[i - n] - 1)


class Pack(object):
    """All the daily indicators the scanner uses, computed once per symbol."""

    def __init__(self, bars):
        o, h, l, c, v = bars.o, bars.h, bars.l, bars.c, bars.v
        self.bars = bars
        self.ema8 = ema(c, 8)
        self.ema20 = ema(c, 20)
        self.sma50 = sma(c, 50)
        self.sma200 = sma(c, 200)
        self.atr14 = atr(h, l, c, 14)
        self.atr10 = atr(h, l, c, 10)
        self.atr50 = atr(h, l, c, 50)
        self.rsi14 = rsi(c, 14)
        self.rsi2 = rsi(c, 2)
        self.adx14 = adx(h, l, c, 14)
        self.rvol20 = rvol(v, 20)
        self.hi20 = highest(h, 20)
        self.lo20 = lowest(l, 20)
        self.hi55 = highest(h, 55)
        self.lo55 = lowest(l, 55)
        n52 = min(252, len(c))
        self.hi252 = highest(h, n52)
        self.lo252 = lowest(l, n52)
        self.roc20 = roc(c, 20)
        self.roc63 = roc(c, 63)
        self.vol20 = sma(v, 20)
        self.dollar_vol20 = sma([a * b for a, b in zip(c, v)], 20)
