"""
recurrence.py — Detect recurring financial events from transaction history.
"""

from datetime import datetime, timedelta
from collections import defaultdict
import statistics


def detect_recurring_events(events, request_date_str):
    """
    Analyze a user's event history to identify recurring expenses and income.
    
    Args:
        events: List of event dicts for a single user
        request_date_str: The request date string (YYYY-MM-DD)
    
    Returns:
        List of recurring event patterns, each with:
        - category, description, direction, amount, currency
        - day_of_month: typical day of the month
        - frequency_days: typical interval between occurrences
        - last_event: the most recent occurrence
        - flexibility, minimum_allowed_amount
        - event_id: the most recent event_id (for spending changes)
    """
    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    
    # Only consider settled events before or on request_date, 
    # PLUS scheduled future income/salary events (since they indicate new recurring amounts)
    eligible = []
    for e in events:
        if e["amount"] is None:
            continue
            
        if e["status"] == "settled" and e["direction"] in ("debit", "credit") and e["event_date"] <= request_date_str:
            eligible.append(e)
        elif e["status"] == "scheduled" and e["direction"] == "credit" and e["event_type"] in ("salary", "income"):
            eligible.append(e)
            
    # Group by (category, description pattern, direction)
    groups = defaultdict(list)
    for e in eligible:
        key = _make_group_key(e)
        groups[key].append(e)
    
    recurring = []
    
    for key, group_events in groups.items():
        # Sort by date
        group_events.sort(key=lambda e: e.get("settlement_date") or e.get("event_date", ""))
        
        if len(group_events) < 2:
            continue
        
        # Calculate intervals
        dates = []
        for e in group_events:
            try:
                d_str = e.get("settlement_date") or e.get("event_date", "")
                dates.append(datetime.strptime(d_str, "%Y-%m-%d"))
            except ValueError:
                continue
        
        if len(dates) < 2:
            continue
        
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        
        if not intervals:
            continue
        
        median_interval = statistics.median(intervals)
        
        # Enforce that it's actually regular: max variance from median shouldn't be too huge
        # For monthly (25-35), allow maybe +/- 10 days max. 
        # For weekly/biweekly, allow maybe +/- 5 days max.
        # But a simple way is: min and max intervals must loosely match the frequency bounds.
        
        # Determine frequency type
        is_recurring = False
        frequency = None
        if 25 <= median_interval <= 35:
            is_recurring = True
            frequency = "monthly"
        elif 6 <= median_interval <= 8:
            is_recurring = True
            frequency = "weekly"
        elif 13 <= median_interval <= 15:
            is_recurring = True
            frequency = "biweekly"
            
        if is_recurring:
            most_recent = group_events[-1]
            recent_date = dates[-1]
            
            # Skip if the most recent occurrence is too old (more than 60 days before request)
            # EXCEPT for scheduled events which are in the future
            days_since_last = (request_date - recent_date).days
            if most_recent["status"] != "scheduled" and days_since_last > 60:
                continue
            
            typical_day = recent_date.day
            typical_amount = most_recent["amount"]
            
            recurring.append({
                "category": most_recent["category"],
                "description": most_recent["description"],
                "direction": most_recent["direction"],
                "amount": typical_amount,
                "currency": most_recent["currency"],
                "day_of_month": typical_day,
                "frequency_days": round(median_interval),
                "frequency_type": frequency,
                "last_date": recent_date,
                "last_event": most_recent,
                "flexibility": most_recent.get("flexibility", "fixed"),
                "minimum_allowed_amount": most_recent.get("minimum_allowed_amount"),
                "event_id": most_recent["event_id"],
                "event_type": most_recent["event_type"],
                "all_events": group_events,
            })
    
    # Also look for single scheduled or very recent income events that should recur
    for key, group_events in groups.items():
        if len(group_events) >= 2:
            continue
            
        e = group_events[0]
        if e["direction"] == "credit" and e["event_type"] in ("salary", "income"):
            try:
                d_str = e.get("settlement_date") or e.get("event_date", "")
                date = datetime.strptime(d_str, "%Y-%m-%d")
                recurring.append({
                    "category": e["category"],
                    "description": e["description"],
                    "direction": e["direction"],
                    "amount": e["amount"],
                    "currency": e["currency"],
                    "day_of_month": date.day,
                    "frequency_days": 30,
                    "last_date": date,
                    "last_event": e,
                    "flexibility": e.get("flexibility", "fixed"),
                    "minimum_allowed_amount": e.get("minimum_allowed_amount"),
                    "event_id": e["event_id"],
                    "event_type": e["event_type"],
                    "all_events": group_events,
                })
            except ValueError:
                pass
    return recurring


def project_recurring_events(recurring_patterns, request_date_str, days_ahead=90):
    """
    Project recurring events forward from request_date for the specified number of days.
    
    Args:
        recurring_patterns: Output from detect_recurring_events
        request_date_str: Start date (YYYY-MM-DD)
        days_ahead: Number of days to project (default 90)
    
    Returns:
        List of projected events, each with:
        - date (YYYY-MM-DD), amount, direction, category, description, etc.
    """
    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    end_date = request_date + timedelta(days=days_ahead)
    
    projected = []
    
    for pattern in recurring_patterns:
        amount = pattern["amount"]
        last_date = pattern["last_date"]
        freq_type = pattern.get("frequency_type", "monthly")
        
        if freq_type == "monthly":
            day_of_month = pattern["day_of_month"]
            current = _next_monthly_date(request_date, day_of_month)
            if last_date.year == current.year and last_date.month == current.month:
                if current.month == 12:
                    next_month = datetime(current.year + 1, 1, 1)
                else:
                    next_month = datetime(current.year, current.month + 1, 1)
                current = _clamp_day(next_month, day_of_month)
        else:
            # Weekly or biweekly
            freq_days = pattern.get("frequency_days", 7 if freq_type == "weekly" else 14)
            current = last_date + timedelta(days=freq_days)
            # Advance until it is after request_date
            while current <= request_date:
                current += timedelta(days=freq_days)
        
        while current <= end_date:
            projected.append({
                "date": current.strftime("%Y-%m-%d"),
                "amount": amount,
                "direction": pattern["direction"],
                "category": pattern["category"],
                "description": pattern["description"],
                "currency": pattern["currency"],
                "event_id": pattern["event_id"],
                "event_type": pattern["event_type"],
                "flexibility": pattern["flexibility"],
                "minimum_allowed_amount": pattern.get("minimum_allowed_amount"),
                "is_projected": True,
            })
            
            if freq_type == "monthly":
                if current.month == 12:
                    next_month = datetime(current.year + 1, 1, 1)
                else:
                    next_month = datetime(current.year, current.month + 1, 1)
                current = _clamp_day(next_month, pattern["day_of_month"])
            else:
                current += timedelta(days=pattern.get("frequency_days", 7))
    
    # Sort by date
    projected.sort(key=lambda e: e["date"])
    return projected


def _make_group_key(event):
    """Create a grouping key for an event based on its category and type."""
    cat = event.get("category", "")
    event_type = event.get("event_type", "")
    direction = event.get("direction", "")
    
    # For salary/income, group by event_type to avoid double counting
    # (e.g., "First prorated salary" vs "Next confirmed salary")
    if event_type in ("salary", "income"):
        return (cat, "SALARY_OR_INCOME", direction, event_type)
        
    desc = _normalize_description(event.get("description", ""))
    return (cat, desc, direction, event_type)


def _normalize_description(desc):
    """Normalize description for grouping (remove variable parts)."""
    # Keep the core description, removing variable amounts or dates
    import re
    # Remove specific amounts
    desc = re.sub(r'[\d,.]+', '', desc)
    # Remove extra whitespace
    desc = ' '.join(desc.split())
    return desc.strip()


def _next_monthly_date(from_date, day_of_month):
    """Get the next occurrence of a specific day of month on or after from_date."""
    try:
        target = from_date.replace(day=day_of_month)
    except ValueError:
        # Day doesn't exist in this month (e.g., 31 in February)
        target = _last_day_of_month(from_date)
    
    if target < from_date:
        # Move to next month
        if from_date.month == 12:
            next_month = from_date.replace(year=from_date.year + 1, month=1, day=1)
        else:
            next_month = from_date.replace(month=from_date.month + 1, day=1)
        target = _clamp_day(next_month, day_of_month)
    
    return target


def _clamp_day(date, day_of_month):
    """Set the day of month, clamping to the last day if necessary."""
    import calendar
    max_day = calendar.monthrange(date.year, date.month)[1]
    return date.replace(day=min(day_of_month, max_day))


def _last_day_of_month(date):
    """Get the last day of the month for a given date."""
    import calendar
    max_day = calendar.monthrange(date.year, date.month)[1]
    return date.replace(day=max_day)
