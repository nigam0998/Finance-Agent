"""
financial_engine.py — Core financial logic: 90-day forecast, safe amount calculation,
earliest full payment date.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from recurrence import detect_recurring_events, project_recurring_events
from currency import convert_amount


def build_financial_state(ctx, message_facts, image_amounts):
    """
    Build the complete financial state for a request, including 90-day forecast.
    
    Args:
        ctx: Request context from data_loader.get_request_context()
        message_facts: Interpreted message facts for this user
        image_amounts: Extracted image amounts (event_id -> amount)
    
    Returns:
        Dict with forecast data, safe amount, earliest date, etc.
    """
    profile = ctx["profile"]
    events = ctx["events"]
    request = ctx["request"]
    request_date_str = request["request_date"]
    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    home_currency = profile["home_currency"]
    min_balance = profile["minimum_balance_to_keep"]
    current_balance = profile["current_available_balance"]
    requested_amount = request["requested_amount"]
    rate_lookup = ctx["exchange_rate_lookup"]

    # Step 1: Fill in blank amounts from images
    events = _fill_image_amounts(events, image_amounts)

    # Step 2: Apply message-based modifications
    events, salary_overrides = _apply_message_modifications(
        events, message_facts, request_date_str, home_currency, rate_lookup
    )

    # Step 3: Detect recurring patterns
    recurring = detect_recurring_events(events, request_date_str)

    # Step 4: Apply salary overrides from messages
    recurring = _apply_salary_overrides(recurring, salary_overrides, request_date_str)

    # Step 5: Project recurring events forward
    projected = project_recurring_events(recurring, request_date_str, days_ahead=90)

    # Step 6: Convert projected amounts to home currency
    projected = _convert_projected_to_home_currency(projected, home_currency, rate_lookup)

    # Step 7: Add confirmed one-time future events
    scheduled = _get_scheduled_future_events(events, request_date_str, home_currency, rate_lookup)

    # Step 8: Add confirmed income from messages (invoices, salary adjustments)
    message_income = _get_message_income(message_facts, request_date_str, home_currency, rate_lookup)

    # Step 9: Build 90-day daily forecast
    forecast = _build_daily_forecast(
        current_balance, request_date, projected, scheduled, message_income, min_balance
    )

    # Step 10: Calculate amount_safe_to_pay
    amount_safe = _calculate_safe_amount(forecast, min_balance, requested_amount)

    # Step 11: Calculate earliest_date_for_full_payment
    earliest_date = _calculate_earliest_full_payment_date(
        forecast, min_balance, requested_amount, request_date
    )

    return {
        "forecast": forecast,
        "amount_safe_to_pay": amount_safe,
        "earliest_date_for_full_payment": earliest_date,
        "recurring_patterns": recurring,
        "projected_events": projected,
        "scheduled_events": scheduled,
        "message_income": message_income,
        "current_balance": current_balance,
        "min_balance": min_balance,
        "home_currency": home_currency,
    }


def _fill_image_amounts(events, image_amounts):
    """Fill in blank event amounts using image extraction results."""
    updated = []
    for e in events:
        e_copy = dict(e)
        if e_copy["amount"] is None and e_copy["event_id"] in image_amounts:
            e_copy["amount"] = image_amounts[e_copy["event_id"]]
        updated.append(e_copy)
    return updated


def _apply_message_modifications(events, message_facts, request_date_str, home_currency, rate_lookup):
    """
    Apply message-based modifications to events.
    Returns modified events list and salary override info.
    """
    if not message_facts:
        return events, {}

    salary_overrides = {}
    cancelled_events = set()
    modified_events = {}

    for fact in message_facts:
        fact_type = fact.get("fact_type", "OTHER")

        print(f"DEBUG: Processing fact {fact_type}: {fact}")

        if fact.get("cancels_future_income"):
            print(f"DEBUG: Setting income_ended to True")
            salary_overrides["income_ended"] = True
            if fact.get("new_salary_amount"):
                salary_overrides["remaining_amount"] = fact["new_salary_amount"]

        if fact_type == "SALARY_CHANGE":
            salary_overrides["new_amount"] = fact.get("new_salary_amount") or fact.get("amount")
            salary_overrides["effective_date"] = fact.get("effective_date") or fact.get("payment_date")
            salary_overrides["currency"] = fact.get("currency")

        elif fact_type == "FIRST_SALARY":
            salary_overrides["new_amount"] = fact.get("new_salary_amount") or fact.get("amount")
            salary_overrides["payment_date"] = fact.get("payment_date") or fact.get("effective_date")
            salary_overrides["is_first"] = True
            salary_overrides["currency"] = fact.get("currency")

        elif fact_type == "SALARY_REDUCED":
            salary_overrides["temporary_amount"] = fact.get("new_salary_amount") or fact.get("amount")
            salary_overrides["currency"] = fact.get("currency")

        elif fact_type == "SALARY_CONFIRMED":
            salary_overrides["confirmed_amount"] = fact.get("new_salary_amount") or fact.get("amount")
            salary_overrides["payment_date"] = fact.get("payment_date") or fact.get("effective_date")
            salary_overrides["currency"] = fact.get("currency")

        elif fact_type == "INCOME_ENDED":
            salary_overrides["income_ended"] = True
            if fact.get("new_salary_amount"):
                salary_overrides["remaining_amount"] = fact["new_salary_amount"]

        elif fact_type == "PAYROLL_DATE_CHANGE":
            salary_overrides["payment_date"] = fact.get("payment_date")

        elif fact_type == "RENT_INCREASE":
            salary_overrides["rent_increase_pct"] = fact.get("rent_increase_pct")

        elif fact_type in ("REFUND_PENDING", "PAYOUT_PENDING", "BONUS_PENDING", "PRIZE_PENDING"):
            # Mark related event as not countable
            related = fact.get("related_event_id") or fact.get("modifies_event_id")
            if related:
                cancelled_events.add(related)

        elif fact_type == "ACCOUNT_TRANSFER":
            # Mark as net zero - find related events
            related = fact.get("related_event_id") or fact.get("modifies_event_id")
            if related:
                cancelled_events.add(related)

        elif fact_type == "INVESTMENT_UNREALIZED":
            related = fact.get("related_event_id") or fact.get("modifies_event_id")
            if related:
                cancelled_events.add(related)

    # Apply cancellations
    updated_events = []
    for e in events:
        e_copy = dict(e)
        if e_copy["event_id"] in cancelled_events:
            # Mark as cancelled for forecasting purposes
            e_copy["_msg_cancelled"] = True
        updated_events.append(e_copy)

    return updated_events, salary_overrides


def _apply_salary_overrides(recurring, salary_overrides, request_date_str):
    """Apply salary overrides from messages to recurring patterns."""
    if not salary_overrides:
        return recurring

    updated = []
    for pattern in recurring:
        p = dict(pattern)

        # Handle income ended
        if salary_overrides.get("income_ended") and pattern["direction"] == "credit":
            if pattern["event_type"] in ("salary", "income"):
                if salary_overrides.get("remaining_amount"):
                    # One income source ended, update to remaining
                    p["amount"] = salary_overrides["remaining_amount"]
                else:
                    # All income ended, skip this pattern
                    print(f"DEBUG: Skipping pattern {p['description']} because income_ended is True")
                    continue

        # Handle salary change
        if salary_overrides.get("new_amount") and pattern["direction"] == "credit":
            if pattern["event_type"] in ("salary", "income"):
                p["amount"] = salary_overrides["new_amount"]

        # Handle temporary reduction
        if salary_overrides.get("temporary_amount") and pattern["direction"] == "credit":
            if pattern["event_type"] in ("salary", "income"):
                p["amount"] = salary_overrides["temporary_amount"]

        # Handle confirmed amount
        if salary_overrides.get("confirmed_amount") and pattern["direction"] == "credit":
            if pattern["event_type"] in ("salary", "income"):
                p["amount"] = salary_overrides["confirmed_amount"]

        # Handle rent increase
        if salary_overrides.get("rent_increase_pct") and pattern["direction"] == "debit":
            if pattern["category"] in ("rent", "housing"):
                pct = salary_overrides["rent_increase_pct"]
                p["amount"] = round(p["amount"] * (1 + pct / 100), 2)

        updated.append(p)

    # Handle first salary (add new recurring pattern if needed)
    if salary_overrides.get("is_first") and salary_overrides.get("new_amount"):
        # Check if we already have an income pattern
        has_income = any(p["direction"] == "credit" and p["event_type"] in ("salary", "income") for p in updated)
        if not has_income:
            payment_date = salary_overrides.get("payment_date", "")
            if payment_date:
                try:
                    pd_dt = datetime.strptime(payment_date, "%Y-%m-%d")
                    day_of_month = pd_dt.day
                except ValueError:
                    day_of_month = 15

                updated.append({
                    "category": "salary",
                    "description": "Salary (from message)",
                    "direction": "credit",
                    "amount": salary_overrides["new_amount"],
                    "currency": salary_overrides.get("currency"),
                    "day_of_month": day_of_month,
                    "frequency_days": 30,
                    "last_date": datetime.strptime(request_date_str, "%Y-%m-%d") - timedelta(days=1),
                    "last_event": {},
                    "flexibility": "fixed",
                    "minimum_allowed_amount": None,
                    "event_id": "msg_salary",
                    "event_type": "salary",
                    "all_events": [],
                })

    return updated


def _convert_projected_to_home_currency(projected, home_currency, rate_lookup):
    """Convert projected event amounts to home currency if needed."""
    converted = []
    for p in projected:
        p_copy = dict(p)
        if p_copy["currency"] and p_copy["currency"] != home_currency:
            conv_amount = convert_amount(
                p_copy["amount"], p_copy["currency"], home_currency,
                p_copy["date"], rate_lookup
            )
            if conv_amount is not None:
                p_copy["amount"] = conv_amount
                p_copy["currency"] = home_currency
        converted.append(p_copy)
    return converted


def _get_scheduled_future_events(events, request_date_str, home_currency, rate_lookup):
    """Get one-time scheduled/confirmed future events that affect cash flow."""
    scheduled = []
    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    end_date = request_date + timedelta(days=90)

    for e in events:
        # Skip cancelled/failed events
        if e["status"] in ("failed", "cancelled"):
            continue
        # Skip message-cancelled events
        if e.get("_msg_cancelled"):
            continue
        # Skip unrealized investments
        if e["status"] == "unrealized":
            continue
        # Skip already settled events (already in balance)
        if e["status"] == "settled":
            continue
        # Skip pending credits (don't count)
        if e["status"] == "pending" and e["direction"] == "credit":
            continue

        # Get the event date
        event_date_str = e.get("settlement_date") or e.get("event_date", "")
        if not event_date_str:
            continue

        try:
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # Only future events within forecast window
        if event_date <= request_date or event_date > end_date:
            continue

        amount = e["amount"]
        if amount is None:
            continue

        # Convert currency if needed
        if e["currency"] and e["currency"] != home_currency:
            amount = convert_amount(amount, e["currency"], home_currency, event_date_str, rate_lookup)
            if amount is None:
                continue

        scheduled.append({
            "date": event_date_str,
            "amount": amount,
            "direction": e["direction"],
            "category": e.get("category", ""),
            "description": e.get("description", ""),
            "event_id": e["event_id"],
            "event_type": e.get("event_type", ""),
        })

    return scheduled


def _get_message_income(message_facts, request_date_str, home_currency, rate_lookup):
    """Get confirmed income from messages (e.g., confirmed invoices, specific salary dates)."""
    income = []
    if not message_facts:
        return income

    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    end_date = request_date + timedelta(days=90)

    for fact in message_facts:
        if not fact.get("should_count_as_income"):
            continue
        if fact.get("fact_type") in ("INVOICE_CONFIRMED",):
            payment_date = fact.get("payment_date") or fact.get("effective_date")
            amount = fact.get("amount")
            if payment_date and amount:
                try:
                    pd_dt = datetime.strptime(payment_date, "%Y-%m-%d")
                    if request_date < pd_dt <= end_date:
                        # Convert currency if needed
                        if fact.get("currency") and fact["currency"] != home_currency:
                            amount = convert_amount(amount, fact["currency"], home_currency, payment_date, rate_lookup)
                            if amount is None:
                                continue
                        income.append({
                            "date": payment_date,
                            "amount": amount,
                            "direction": "credit",
                            "category": "invoice_income",
                            "description": f"Confirmed invoice: {amount}",
                        })
                except ValueError:
                    continue

    return income


def _build_daily_forecast(current_balance, request_date, projected, scheduled, message_income, min_balance):
    """
    Build day-by-day balance forecast for 90 days.
    
    Returns:
        Dict of date_str -> balance
    """
    forecast = {}
    balance = current_balance

    # Combine all future events
    all_events = defaultdict(list)

    for p in projected:
        all_events[p["date"]].append(p)
    for s in scheduled:
        all_events[s["date"]].append(s)
    for m in message_income:
        all_events[m["date"]].append(m)

    # Build day-by-day
    for day_offset in range(91):
        date = request_date + timedelta(days=day_offset)
        date_str = date.strftime("%Y-%m-%d")

        # Apply events for this day
        for event in all_events.get(date_str, []):
            amount = event["amount"]
            if event["direction"] == "debit":
                balance -= amount
            elif event["direction"] == "credit":
                balance += amount

        forecast[date_str] = round(balance, 2)

    return forecast


def _calculate_safe_amount(forecast, min_balance, requested_amount):
    """
    Calculate the maximum amount safe to pay on request_date.
    
    The user pays X on day 0, which reduces the balance by X for all subsequent days.
    We need: min(forecast[d] for all d) - X >= min_balance
    So: X <= min(forecast[d]) - min_balance
    """
    if not forecast:
        return 0.0

    min_projected = min(forecast.values())
    safe = min_projected - min_balance

    # Clamp to [0, requested_amount]
    safe = max(0, min(safe, requested_amount))
    return round(safe, 2)


def _calculate_earliest_full_payment_date(forecast, min_balance, requested_amount, request_date):
    """
    Find the earliest date D where paying requested_amount on D keeps
    all subsequent balances above min_balance.
    
    For date D, the constraint is:
    min(forecast[d] for d >= D) - requested_amount >= min_balance
    
    We use a suffix-minimum approach.
    """
    if not forecast:
        return None

    # Sort dates
    dates = sorted(forecast.keys())

    # Build suffix minimum array
    n = len(dates)
    suffix_min = [0.0] * n
    suffix_min[-1] = forecast[dates[-1]]
    for i in range(n - 2, -1, -1):
        suffix_min[i] = min(forecast[dates[i]], suffix_min[i + 1])

    # Also need to check dates BEFORE D (they are unaffected by the payment)
    # The payment only affects dates >= D
    # Before D: forecast[d] >= min_balance must hold (this is just the base forecast)
    # On and after D: forecast[d] - requested_amount >= min_balance
    
    # Check prefix constraint: all dates before D must have forecast >= min_balance
    # This should always be true since we haven't made any payment
    # Actually we need to check this because the forecast itself might dip below min_balance
    
    for i in range(n):
        date_str = dates[i]
        # For this candidate date D:
        # All d >= D must have forecast[d] - requested_amount >= min_balance
        # i.e., suffix_min[i] - requested_amount >= min_balance
        # i.e., suffix_min[i] >= min_balance + requested_amount
        
        if suffix_min[i] >= min_balance + requested_amount:
            # Also check that all dates BEFORE D have forecast >= min_balance
            # (since no payment has been made yet on those days)
            prefix_ok = True
            for j in range(i):
                if forecast[dates[j]] < min_balance:
                    prefix_ok = False
                    break
            
            if prefix_ok:
                return date_str

    return None


def recalculate_forecast_with_payment(forecast_base, payment_date_str, payment_amount, request_date):
    """
    Recalculate forecast after making a payment on a specific date.
    The payment reduces balance on and after payment_date.
    
    Args:
        forecast_base: Original daily forecast (dict of date_str -> balance)
        payment_date_str: Date of payment (YYYY-MM-DD)
        payment_amount: Amount of payment
        request_date: The request date (datetime)
    
    Returns:
        New forecast dict
    """
    new_forecast = {}
    for date_str, balance in forecast_base.items():
        if date_str >= payment_date_str:
            new_forecast[date_str] = round(balance - payment_amount, 2)
        else:
            new_forecast[date_str] = balance
    return new_forecast


def recalculate_forecast_with_plan(forecast_base, payment_plan, request_date):
    """
    Recalculate forecast after applying a full payment plan.
    
    Args:
        forecast_base: Original daily forecast
        payment_plan: List of (date_str, amount) tuples
        request_date: The request date (datetime)
    
    Returns:
        New forecast dict
    """
    new_forecast = dict(forecast_base)
    
    for pay_date_str, pay_amount in sorted(payment_plan):
        temp = {}
        for date_str, balance in new_forecast.items():
            if date_str >= pay_date_str:
                temp[date_str] = round(balance - pay_amount, 2)
            else:
                temp[date_str] = balance
        new_forecast = temp
    
    return new_forecast


def check_forecast_safety(forecast, min_balance):
    """Check if all days in the forecast stay above minimum balance."""
    for date_str, balance in forecast.items():
        if balance < min_balance - 0.01:  # Small tolerance for floating point
            return False
    return True


def recalculate_with_spending_changes(
    ctx, message_facts, image_amounts, spending_changes, recurring_patterns
):
    """
    Recalculate the forecast with spending changes applied.
    
    Args:
        spending_changes: List of {"action": "stop"|"reduce_to", "event_id": ..., "new_amount": ...}
    
    Returns:
        Updated financial state
    """
    profile = ctx["profile"]
    request = ctx["request"]
    request_date_str = request["request_date"]
    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    home_currency = profile["home_currency"]
    min_balance = profile["minimum_balance_to_keep"]
    current_balance = profile["current_available_balance"]
    requested_amount = request["requested_amount"]
    rate_lookup = ctx["exchange_rate_lookup"]

    # Apply spending changes to recurring patterns
    modified_recurring = []
    for pattern in recurring_patterns:
        p = dict(pattern)
        for change in spending_changes:
            if change["event_id"] == pattern["event_id"]:
                if change["action"] == "stop":
                    p["amount"] = 0  # Will be filtered out
                elif change["action"] == "reduce_to":
                    p["amount"] = change["new_amount"]
        if p["amount"] > 0:
            modified_recurring.append(p)

    # Re-project with modified patterns
    projected = project_recurring_events(modified_recurring, request_date_str, days_ahead=90)
    projected = _convert_projected_to_home_currency(projected, home_currency, rate_lookup)

    events = _fill_image_amounts(ctx["events"], image_amounts)
    events, _ = _apply_message_modifications(events, message_facts, request_date_str, home_currency, rate_lookup)
    scheduled = _get_scheduled_future_events(events, request_date_str, home_currency, rate_lookup)
    message_income = _get_message_income(message_facts, request_date_str, home_currency, rate_lookup)

    forecast = _build_daily_forecast(
        current_balance, request_date, projected, scheduled, message_income, min_balance
    )

    amount_safe = _calculate_safe_amount(forecast, min_balance, requested_amount)
    earliest_date = _calculate_earliest_full_payment_date(forecast, min_balance, requested_amount, request_date)

    return {
        "forecast": forecast,
        "amount_safe_to_pay": amount_safe,
        "earliest_date_for_full_payment": earliest_date,
        "current_balance": current_balance,
        "min_balance": min_balance,
    }
