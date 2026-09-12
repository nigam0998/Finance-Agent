"""
output_formatter.py — Format output rows and generate explanations.
"""

import os
import json


def format_output_row(request, profile, financial_state, plan_result, use_api=False):
    """
    Format a single output row for the CSV.
    
    Returns:
        Dict with the output columns.
    """
    request_id = request["request_id"]
    requested_amount = request["requested_amount"]
    amount_safe = financial_state["amount_safe_to_pay"]
    home_currency = profile["home_currency"]
    min_balance = profile["minimum_balance_to_keep"]

    # Get the plan details
    affordability_status = plan_result["affordability_status"]
    recommended_method = plan_result["recommended_payment_method"]
    payment_plan = plan_result["payment_plan"]
    earliest_date = plan_result.get("earliest_date_for_full_payment", "")
    spending_changes = plan_result.get("spending_changes_needed", "none")

    # For affordable_now, earliest must equal request_date
    if affordability_status == "affordable_now":
        earliest_date = request["request_date"]

    # For not_affordable, earliest is empty
    if affordability_status == "not_affordable":
        earliest_date = ""

    # Generate explanation
    explanation = _generate_explanation(
        request, profile, financial_state, plan_result,
        amount_safe, affordability_status, recommended_method,
        payment_plan, earliest_date, spending_changes
    )

    return {
        "request_id": request_id,
        "amount_safe_to_pay": amount_safe,
        "affordability_status": affordability_status,
        "recommended_payment_method": recommended_method,
        "payment_plan": payment_plan,
        "earliest_date_for_full_payment": earliest_date,
        "spending_changes_needed": spending_changes,
        "decision_explanation": explanation,
    }


def _generate_explanation(request, profile, financial_state, plan_result,
                          amount_safe, status, method, plan, earliest, changes):
    """Generate a concise decision explanation."""
    home_currency = profile["home_currency"]
    min_balance = profile["minimum_balance_to_keep"]
    requested_amount = request["requested_amount"]
    request_date = request["request_date"]

    amt_str = _format_amount(requested_amount, home_currency)
    min_str = _format_amount(min_balance, home_currency)
    safe_str = _format_amount(amount_safe, home_currency)

    if status == "affordable_now" and method == "full_payment":
        return f"Pay {amt_str} today. This leaves at least {min_str} available over the next 90 days."

    elif status == "affordable_with_plan" and method == "full_payment":
        if changes and changes != "none":
            change_desc = _describe_changes(plan_result.get("spending_changes_raw", []))
            return f"{change_desc}, then pay {amt_str} today. This leaves at least {min_str} available."
        return f"Pay {amt_str} today. This leaves at least {min_str} available."

    elif status == "affordable_with_plan" and method == "installments":
        payments = plan_result.get("payment_plan_raw", [])
        if payments:
            per_payment = _format_amount(payments[0][1], home_currency)
            num = len(payments)
            start = payments[0][0]
            explanation = f"Use {num} installments of {per_payment}, starting {start}."
            if changes and changes != "none":
                change_desc = _describe_changes(plan_result.get("spending_changes_raw", []))
                explanation = f"{change_desc}, then use {num} installments of {per_payment}, starting {start}."
            explanation += f" This leaves at least {min_str} available."
            return explanation
        return f"Use installments to pay {amt_str}. This leaves at least {min_str} available."

    elif status == "affordable_with_plan" and method == "partial_payment":
        payments = plan_result.get("payment_plan_raw", [])
        if len(payments) == 2:
            first_amt = _format_amount(payments[0][1], home_currency)
            second_amt = _format_amount(payments[1][1], home_currency)
            second_date = payments[1][0]
            return (f"Pay {first_amt} today and the remaining {second_amt} on {second_date}. "
                    f"This completes the full request and keeps the {min_str} minimum protected.")
        return f"Pay partial amount now and the rest later."

    elif status == "affordable_later" and method == "wait":
        if earliest:
            return (f"Pay {amt_str} in full on {earliest}. "
                    f"Paying earlier would take the balance below the {min_str} minimum.")
        return f"Wait until sufficient funds are available to pay {amt_str} safely."

    elif status == "not_affordable":
        if amount_safe > 0:
            return (f"Do not proceed with the {amt_str} request. "
                    f"Although {safe_str} is available today, "
                    f"the full amount cannot be completed safely within 90 days.")
        return (f"Do not make this payment by {request['desired_completion_date']}. "
                f"None of the available options keeps the {min_str} minimum protected.")

    return f"Recommendation: {method}. Amount safe: {safe_str}."


def _format_amount(amount, currency):
    """Format an amount with currency."""
    if amount is None:
        return f"{currency} 0"
    # Format with commas for thousands
    if amount == int(amount):
        formatted = f"{int(amount):,}"
    else:
        formatted = f"{amount:,.2f}"
    return f"{currency} {formatted}"


def _describe_changes(changes):
    """Describe spending changes in natural language."""
    if not changes:
        return ""

    parts = []
    for c in changes:
        if c["action"] == "stop":
            desc = c.get("description", c.get("category", "expense"))
            parts.append(f"Stop the {desc.lower()}")
        elif c["action"] == "reduce_to":
            desc = c.get("description", c.get("category", "expense"))
            parts.append(f"Reduce the {desc.lower()} to {c['new_amount']}")

    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1].lower()}"
    else:
        return ", ".join(parts[:-1]) + f" and {parts[-1].lower()}"
