"""Customer health rules. Pure functions so they are easy to test at the boundary days."""

from datetime import date

from app.customers.schemas import Health, HealthSettings
from app.invoices.stats import CustomerStats

# When a customer has several tags, the table shows the most important one first.
PRIMARY_ORDER: tuple[Health, ...] = ("dormant", "inactive", "declining", "new", "high_value", "repeat")


def high_value_threshold(period_sales: list[int], top_pct: int) -> int | None:
    """Smallest period-sales value that is in the top N% (at least one customer)."""
    buying = sorted((s for s in period_sales if s > 0), reverse=True)
    if not buying:
        return None
    n = max(1, round(len(buying) * top_pct / 100))
    return buying[n - 1]


def health_tags(
    st: CustomerStats | None, cfg: HealthSettings, today: date, p_from: date, p_to: date,
    hv_threshold: int | None,
) -> list[Health]:  # fmt: skip
    if st is None or st.invoices_all == 0 or st.last_date is None:
        return []
    tags: list[Health] = []
    since = (today - st.last_date).days
    if st.first_date and p_from <= st.first_date <= p_to:
        tags.append("new")
    if st.invoices_all >= cfg.repeat_min_invoices and since < cfg.repeat_recent_days:
        tags.append("repeat")
    if hv_threshold is not None and st.period_sales > 0 and st.period_sales >= hv_threshold:
        tags.append("high_value")
    if st.prev_sales > 0 and st.period_sales < st.prev_sales * (100 - cfg.declining_drop_pct) / 100:
        tags.append("declining")
    if since >= cfg.dormant_days:
        tags.append("dormant")
    elif since >= cfg.inactive_days and st.invoices_all >= cfg.repeat_min_invoices:
        tags.append("inactive")
    return tags


def primary(tags: list[Health]) -> Health | None:
    return next((t for t in PRIMARY_ORDER if t in tags), None)
