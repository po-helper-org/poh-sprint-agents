"""Прогноз «успеет ли инициатива к дате»: Monte Carlo по недельному темпу (ADR 0001).

Дата по среднему темпу сбывается примерно в половине случаев, поэтому отвечаем вероятностью:
много раз перевыбираем фактическое число закрытых за неделю задач и смотрим, когда кончится
остаток. Неделя — пн–вс; неделя до срока считается, только если она закончилась до него.
Только stdlib, детерминированно при одном seed.
"""
import math
import random
from datetime import date, timedelta

TRIALS = 10_000
MIN_POINTS = 7      # меньше недель истории — прогноза нет (Magennis: минимум 7)
THIN_POINTS = 10    # 7–9 недель — «ориентировочно» (Vacanti: от ~10)
MAX_WEEKS = 156     # дальше трёх лет — «не закончится»


def week_monday(d):
    return d - timedelta(days=d.weekday())


def sunday_of(monday, n):
    """Воскресенье n-й недели, считая неделю monday первой."""
    return monday + timedelta(weeks=n, days=-1)


def weeks_until(monday, deadline):
    """Сколько недель, начиная с monday, целиком заканчиваются не позже deadline."""
    return max(0, ((deadline - monday).days + 1) // 7)


def weekly_throughput(done_dates, monday, window=12, since=None):
    """Закрытия по полным неделям перед monday: не больше window недель и не раньше недели since."""
    first = monday - timedelta(weeks=window)
    if since:
        first = max(first, week_monday(since))
    weeks = max(0, (monday - first).days // 7)
    counts = [0] * weeks
    for d in done_dates:
        if d and first <= d < monday:
            counts[(d - first).days // 7] += 1
    return counts


def _rank(sorted_values, p):
    """Значение по ближайшему рангу: не больше него — p% выборки."""
    return sorted_values[max(0, math.ceil(p / 100 * len(sorted_values)) - 1)]


def forecast(remaining, samples, monday, deadline, growth=0.0, trials=TRIALS, seed=0,
             min_points=MIN_POINTS, max_weeks=MAX_WEEKS):
    """Шанс закрыть remaining задач к deadline и даты, к которым закроем с вероятностью 50/85/95%.

    growth — насколько может вырасти остаток: каждый прогон умножает его на случайное из [1, 1+growth].
    howMany85 — сколько задач закроем к deadline в 85% прогонов; okUntil — последний понедельник,
    с которого ещё можно начать (после простоя) и успеть с шансом не меньше 50%.
    """
    if remaining <= 0:
        return {'status': 'done', 'points': len(samples)}
    if len(samples) < min_points or not any(samples):
        return {'status': 'no_data', 'points': len(samples)}
    rng = random.Random(seed)
    left = weeks_until(monday, deadline)
    weeks = []
    for _ in range(trials):
        target = math.ceil(remaining * rng.uniform(1.0, 1.0 + growth)) if growth else remaining
        done, w = 0, 0
        while done < target and w <= max_weeks:
            done += rng.choice(samples)
            w += 1
        weeks.append(w)
    weeks.sort()
    totals = sorted(sum(rng.choice(samples) for _ in range(left)) for _ in range(trials))

    def date_at(p):
        w = _rank(weeks, p)
        return sunday_of(monday, w) if w <= max_weeks else None

    def chance_with_delay(k):
        return sum(1 for w in weeks if w + k <= left) / trials

    ok_until = None
    for k in range(left + 1):
        if chance_with_delay(k) >= 0.5:
            ok_until = monday + timedelta(weeks=k)
    mean = sum(samples) / len(samples)
    return {
        'status': 'ok' if len(samples) >= THIN_POINTS else 'thin', 'points': len(samples),
        'chance': chance_with_delay(0), 'weeksLeft': left,
        'p50': date_at(50), 'p85': date_at(85), 'p95': date_at(95),
        'howMany85': totals[int(0.15 * trials)] if left else 0,
        'okUntil': ok_until,
        'linear': sunday_of(monday, math.ceil(remaining / mean)),
    }
