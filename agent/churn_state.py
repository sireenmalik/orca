"""
ORCA v2 demo — Churn Forecast state.

Holds the dashboard-flavor churn data for the Churn Forecast tab. NOT a
real churn prediction engine — the numbers are hand-tuned so Act 1
approval produces a visible cliff on slice-A. Read the tab's
``cohorts`` array for the per-slice rows, the derived ``at_risk_total``
/ ``revenue_at_risk_usd`` for the top summary cards, and
``time_series`` for the right-column chart.

Lifecycle
    phase == "baseline"  — what the demo starts on (session skew has
                           been growing in the background for hours)
    phase == "recovered" — after Act 1 deploy completes, slice-A drops
                           from 423 → 14 at-risk and AMBER → GREEN

Reset (global or churn-only) returns phase to "baseline" and restores
every field to its seed value.
"""
from __future__ import annotations

from datetime import datetime

# ─── Baseline cohort data ─────────────────────────────────────────────
# Numbers sum to 847 at-risk subscribers and $4.1M ARR exposed — the
# demo's opening summary. slice-A Enterprise is the star of Act 1;
# slice-D MVNO's high $/sub reflects wholesale contracts.

COHORTS_BASELINE = [
    {
        "id":                "slice-a",
        "name":              "slice-A Enterprise",
        "is_star":           True,
        "subscribers_total": 842,
        "at_risk":           423,
        "at_risk_pct":       50.2,
        "arr_exposed_usd":   1_200_000,
        "status":            "amber",
        "sparkline":         [18, 28, 42, 65, 110, 180, 260, 340, 423],
        "note":              "Session skew + QER drift → p99 climbing",
    },
    {
        "id":                "slice-b",
        "name":              "slice-B Consumer",
        "is_star":           False,
        "subscribers_total": 15_000,
        "at_risk":           280,
        "at_risk_pct":       1.9,
        "arr_exposed_usd":   420_000,
        "status":            "green",
        "sparkline":         [265, 270, 278, 282, 280, 276, 279, 281, 280],
        "note":              "Stable — baseline fluctuation",
    },
    {
        "id":                "slice-c",
        "name":              "slice-C IoT",
        "is_star":           False,
        "subscribers_total": 50_000,
        "at_risk":           120,
        "at_risk_pct":       0.24,
        "arr_exposed_usd":   180_000,
        "status":            "green",
        "sparkline":         [112, 116, 118, 120, 122, 119, 121, 120, 120],
        "note":              "Stable — healthy",
    },
    {
        "id":                "slice-d",
        "name":              "slice-D MVNO wholesale",
        "is_star":           False,
        "subscribers_total": 25_000,
        "at_risk":           24,
        "at_risk_pct":       0.10,
        "arr_exposed_usd":   2_300_000,
        "status":            "amber",
        "sparkline":         [20, 21, 22, 23, 24, 24, 23, 24, 24],
        "note":              "High $/subscriber — watchlist",
    },
]

# Slice-A time-series: last 24h at 3h resolution, value = at-risk count.
# Climb pattern 80 → 423 tells the "growing for hours" story.
TIME_SERIES_BASELINE = [
    {"t_hours_ago": 24, "at_risk": 80},
    {"t_hours_ago": 21, "at_risk": 88},
    {"t_hours_ago": 18, "at_risk": 102},
    {"t_hours_ago": 15, "at_risk": 135},
    {"t_hours_ago": 12, "at_risk": 188},
    {"t_hours_ago": 9,  "at_risk": 255},
    {"t_hours_ago": 6,  "at_risk": 340},
    {"t_hours_ago": 3,  "at_risk": 395},
    {"t_hours_ago": 0,  "at_risk": 423},   # "now"
]

# What slice-A looks like after Act 1 deploy completes.
SLICE_A_RECOVERED = {
    "at_risk":         14,
    "at_risk_pct":     1.7,
    "arr_exposed_usd": 40_000,
    "status":          "green",
    "sparkline":       [260, 340, 395, 423, 14],   # the cliff
    "note":            "Recovered — QER restored, sessions rebalanced",
}

# Appended to the time-series on recovery — produces the visible cliff.
TIME_SERIES_RECOVERY_POINT = {"t_hours_ago": -0.05, "at_risk": 14}


# ─── State ────────────────────────────────────────────────────────────

_state: dict = {
    "cohorts":          [dict(c) for c in COHORTS_BASELINE],
    "time_series":      list(TIME_SERIES_BASELINE),
    "phase":            "baseline",
    "transitioned_at":  None,
    # Pinned star-cohort context shown in the bottom revenue callout band
    "callout": {
        "cohort":           "slice-A Enterprise",
        "subscribers":      842,
        "arr_usd":          2_400_000,
        "sla_commitment":   "15ms N3 one-way",
    },
}


def _compute_totals(cohorts: list) -> dict:
    at_risk_total = sum(c["at_risk"] for c in cohorts)
    revenue_at_risk = sum(c["arr_exposed_usd"] for c in cohorts)
    # Forecast confidence: stylistic — a touch higher after recovery (less
    # uncertainty because the dominant risk factor just resolved).
    conf = 92 if at_risk_total < 500 else 87
    return {
        "at_risk_total":       at_risk_total,
        "revenue_at_risk_usd": revenue_at_risk,
        "forecast_confidence": conf,
    }


def get_state() -> dict:
    return {
        "cohorts":         [dict(c) for c in _state["cohorts"]],
        "time_series":     list(_state["time_series"]),
        "phase":           _state["phase"],
        "transitioned_at": _state["transitioned_at"],
        "callout":         dict(_state["callout"]),
        **_compute_totals(_state["cohorts"]),
    }


def reset() -> None:
    _state["cohorts"]         = [dict(c) for c in COHORTS_BASELINE]
    _state["time_series"]     = list(TIME_SERIES_BASELINE)
    _state["phase"]           = "baseline"
    _state["transitioned_at"] = None


def trigger_slice_a_recovery() -> dict:
    """Called after Act 1 deploy completes. Flips slice-A to recovered
    values and appends a drop point to the time-series. Returns the new
    state so the caller can broadcast it."""
    for c in _state["cohorts"]:
        if c["id"] == "slice-a":
            c.update(SLICE_A_RECOVERED)
            break
    _state["time_series"]     = list(TIME_SERIES_BASELINE) + [TIME_SERIES_RECOVERY_POINT]
    _state["phase"]           = "recovered"
    _state["transitioned_at"] = datetime.utcnow().isoformat() + "Z"
    return get_state()
