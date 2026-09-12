"""
currency.py — Currency conversion utilities using the fixed exchange rates.
"""

from datetime import datetime, timedelta


def convert_amount(amount, from_currency, to_currency, settlement_date, rate_lookup):
    """
    Convert an amount from one currency to another using the exchange rate lookup.
    
    Args:
        amount: The amount to convert
        from_currency: Source currency code
        to_currency: Target currency code
        settlement_date: Date string (YYYY-MM-DD) for rate lookup
        rate_lookup: Dict of (date, from, to) -> rate
    
    Returns:
        Converted amount in to_currency, or None if no rate found.
    """
    if from_currency == to_currency:
        return amount
    if amount is None:
        return None

    # Try direct lookup with the exact date first
    rate = _find_rate(from_currency, to_currency, settlement_date, rate_lookup)
    if rate is not None:
        return round(amount * rate, 2)

    # Try inverse lookup
    inv_rate = _find_rate(to_currency, from_currency, settlement_date, rate_lookup)
    if inv_rate is not None and inv_rate != 0:
        return round(amount / inv_rate, 2)

    # Try chaining through common intermediaries (USD, EUR)
    for mid in ["USD", "EUR", "ZAR", "INR", "IDR"]:
        if mid == from_currency or mid == to_currency:
            continue
        rate1 = _find_rate(from_currency, mid, settlement_date, rate_lookup)
        rate2 = _find_rate(mid, to_currency, settlement_date, rate_lookup)
        if rate1 is not None and rate2 is not None:
            return round(amount * rate1 * rate2, 2)
        # Try inverse of first leg
        inv_rate1 = _find_rate(mid, from_currency, settlement_date, rate_lookup)
        if inv_rate1 is not None and inv_rate1 != 0 and rate2 is not None:
            return round(amount / inv_rate1 * rate2, 2)
        # Try inverse of second leg
        inv_rate2 = _find_rate(to_currency, mid, settlement_date, rate_lookup)
        if rate1 is not None and inv_rate2 is not None and inv_rate2 != 0:
            return round(amount * rate1 / inv_rate2, 2)
        # Both inverse
        if inv_rate1 is not None and inv_rate1 != 0 and inv_rate2 is not None and inv_rate2 != 0:
            return round(amount / inv_rate1 / inv_rate2, 2)

    # Fallback: return None if no conversion found
    return None


def _find_rate(from_currency, to_currency, settlement_date, rate_lookup):
    """
    Find exchange rate, trying the exact date first, then nearby dates.
    """
    # Try exact date
    key = (settlement_date, from_currency, to_currency)
    if key in rate_lookup:
        return rate_lookup[key]

    # Try nearby dates (within same month, then +/- 1 month)
    try:
        dt = datetime.strptime(settlement_date, "%Y-%m-%d")
    except ValueError:
        return None

    # Try the 15th of the same month (rates are typically on the 15th)
    same_month_15 = dt.replace(day=15).strftime("%Y-%m-%d")
    key = (same_month_15, from_currency, to_currency)
    if key in rate_lookup:
        return rate_lookup[key]

    # Try previous month's 15th
    prev_month = dt.replace(day=1) - timedelta(days=1)
    prev_month_15 = prev_month.replace(day=15).strftime("%Y-%m-%d")
    key = (prev_month_15, from_currency, to_currency)
    if key in rate_lookup:
        return rate_lookup[key]

    # Try next month's 15th
    if dt.month == 12:
        next_month_15 = dt.replace(year=dt.year + 1, month=1, day=15).strftime("%Y-%m-%d")
    else:
        next_month_15 = dt.replace(month=dt.month + 1, day=15).strftime("%Y-%m-%d")
    key = (next_month_15, from_currency, to_currency)
    if key in rate_lookup:
        return rate_lookup[key]

    # Search all dates for this currency pair, pick the closest
    best_rate = None
    best_dist = float("inf")
    for (rd, fc, tc), rate in rate_lookup.items():
        if fc == from_currency and tc == to_currency:
            try:
                rd_dt = datetime.strptime(rd, "%Y-%m-%d")
                dist = abs((rd_dt - dt).days)
                if dist < best_dist:
                    best_dist = dist
                    best_rate = rate
            except ValueError:
                continue

    return best_rate
