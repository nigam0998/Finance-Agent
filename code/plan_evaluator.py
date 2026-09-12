"""
plan_evaluator.py — Evaluate and rank candidate payment plans according to the problem rules.
"""

from datetime import datetime, timedelta
from financial_engine import (
    recalculate_forecast_with_plan,
    check_forecast_safety,
    recalculate_with_spending_changes,
    build_financial_state,
)
from spending_changes import (
    find_possible_spending_changes,
    generate_spending_change_combinations,
    format_spending_changes,
)


def evaluate_all_plans(ctx, financial_state, message_facts, image_amounts):
    """
    Evaluate all candidate plans and return the best one.
    
    Args:
        ctx: Request context
        financial_state: Output from build_financial_state
        message_facts: Interpreted message facts
        image_amounts: Extracted image amounts
    
    Returns:
        Dict with the recommended plan details:
        - affordability_status
        - recommended_payment_method
        - payment_plan (formatted string)
        - spending_changes_needed (formatted string)
        - amount_safe_to_pay
        - earliest_date_for_full_payment
    """
    request = ctx["request"]
    profile = ctx["profile"]
    payment_options = ctx["payment_options"]

    request_date_str = request["request_date"]
    request_date = datetime.strptime(request_date_str, "%Y-%m-%d")
    requested_amount = request["requested_amount"]
    desired_completion_date_str = request["desired_completion_date"]
    desired_completion_date = datetime.strptime(desired_completion_date_str, "%Y-%m-%d")
    allows_partial = request["allows_partial_payment"]
    user_methods = profile.get("payment_methods_user_will_consider", [])
    max_installment_months = profile.get("max_installment_months")
    min_balance = financial_state["min_balance"]
    forecast_base = financial_state["forecast"]
    amount_safe = financial_state["amount_safe_to_pay"]
    earliest_date = financial_state["earliest_date_for_full_payment"]
    recurring_patterns = financial_state["recurring_patterns"]

    candidates = []

    # ---- CANDIDATE 1: Full payment on request_date (no spending changes) ----
    if "full_payment" in user_methods:
        plan_payments = [(request_date_str, requested_amount)]
        forecast_with_plan = recalculate_forecast_with_plan(forecast_base, plan_payments, request_date)
        is_safe = check_forecast_safety(forecast_with_plan, min_balance)

        if is_safe:
            candidates.append({
                "affordability_status": "affordable_now",
                "recommended_payment_method": "full_payment",
                "payment_plan_raw": plan_payments,
                "payment_plan": f"{request_date_str}:{requested_amount}",
                "earliest_date_for_full_payment": request_date_str,
                "spending_changes_needed": "none",
                "spending_changes_raw": [],
                "completes_by_deadline": True,
                "needs_spending_changes": False,
                "total_payable": requested_amount,
                "start_date": request_date_str,
                "num_payments": 1,
                "payment_option_id": None,
            })

    # ---- CANDIDATE 2: Installments (no spending changes) ----
    if "installments" in user_methods:
        for opt in payment_options:
            if opt["payment_method"] != "installments":
                continue

            # Check max_installment_months
            if max_installment_months is not None:
                if opt["number_of_payments"] > max_installment_months:
                    continue

            # Build payment schedule
            plan_payments = _build_installment_schedule(opt)
            if not plan_payments:
                continue

            # Check if all payments complete by desired_completion_date
            last_payment_date = plan_payments[-1][0]
            completes_by_deadline = last_payment_date <= desired_completion_date_str

            # Check 90-day safety
            forecast_with_plan = recalculate_forecast_with_plan(forecast_base, plan_payments, request_date)
            is_safe = check_forecast_safety(forecast_with_plan, min_balance)

            if is_safe:
                candidates.append({
                    "affordability_status": "affordable_with_plan",
                    "recommended_payment_method": "installments",
                    "payment_plan_raw": plan_payments,
                    "payment_plan": "|".join(f"{d}:{a}" for d, a in plan_payments),
                    "earliest_date_for_full_payment": earliest_date if earliest_date else "",
                    "spending_changes_needed": "none",
                    "spending_changes_raw": [],
                    "completes_by_deadline": completes_by_deadline,
                    "needs_spending_changes": False,
                    "total_payable": opt["total_payable_amount"],
                    "start_date": plan_payments[0][0] if plan_payments else "",
                    "num_payments": len(plan_payments),
                    "payment_option_id": opt["payment_option_id"],
                })

    # ---- CANDIDATE 3: Partial payment (no spending changes) ----
    if allows_partial and "partial_payment" in user_methods:
        if 0 < amount_safe < requested_amount and earliest_date:
            earliest_dt = datetime.strptime(earliest_date, "%Y-%m-%d")
            if earliest_dt <= desired_completion_date:
                remaining = round(requested_amount - amount_safe, 2)
                plan_payments = [
                    (request_date_str, amount_safe),
                    (earliest_date, remaining),
                ]
                forecast_with_plan = recalculate_forecast_with_plan(forecast_base, plan_payments, request_date)
                is_safe = check_forecast_safety(forecast_with_plan, min_balance)

                if is_safe:
                    candidates.append({
                        "affordability_status": "affordable_with_plan",
                        "recommended_payment_method": "partial_payment",
                        "payment_plan_raw": plan_payments,
                        "payment_plan": "|".join(f"{d}:{a}" for d, a in plan_payments),
                        "earliest_date_for_full_payment": earliest_date,
                        "spending_changes_needed": "none",
                        "spending_changes_raw": [],
                        "completes_by_deadline": True,
                        "needs_spending_changes": False,
                        "total_payable": requested_amount,
                        "start_date": request_date_str,
                        "num_payments": 2,
                        "payment_option_id": None,
                    })

    # ---- CANDIDATE 4: Wait (full payment later, no spending changes) ----
    if "full_payment" in user_methods and earliest_date:
        earliest_dt = datetime.strptime(earliest_date, "%Y-%m-%d")
        if earliest_dt > request_date and earliest_dt <= desired_completion_date:
            plan_payments = [(earliest_date, requested_amount)]
            forecast_with_plan = recalculate_forecast_with_plan(forecast_base, plan_payments, request_date)
            is_safe = check_forecast_safety(forecast_with_plan, min_balance)

            if is_safe:
                candidates.append({
                    "affordability_status": "affordable_later",
                    "recommended_payment_method": "wait",
                    "payment_plan_raw": plan_payments,
                    "payment_plan": f"{earliest_date}:{requested_amount}",
                    "earliest_date_for_full_payment": earliest_date,
                    "spending_changes_needed": "none",
                    "spending_changes_raw": [],
                    "completes_by_deadline": True,
                    "needs_spending_changes": False,
                    "total_payable": requested_amount,
                    "start_date": earliest_date,
                    "num_payments": 1,
                    "payment_option_id": None,
                })

    # ---- CANDIDATE 5+: Plans with spending changes ----
    possible_changes = find_possible_spending_changes(recurring_patterns, profile)
    change_combos = generate_spending_change_combinations(possible_changes, max_changes=3)

    for combo in change_combos:
        # Recalculate forecast with spending changes
        changed_state = recalculate_with_spending_changes(
            ctx, message_facts, image_amounts, combo, recurring_patterns
        )
        changed_forecast = changed_state["forecast"]
        changed_safe = changed_state["amount_safe_to_pay"]
        changed_earliest = changed_state["earliest_date_for_full_payment"]
        change_str = format_spending_changes(combo)

        # Full payment with changes
        if "full_payment" in user_methods:
            plan_payments = [(request_date_str, requested_amount)]
            forecast_with_plan = recalculate_forecast_with_plan(changed_forecast, plan_payments, request_date)
            is_safe = check_forecast_safety(forecast_with_plan, min_balance)

            if is_safe:
                candidates.append({
                    "affordability_status": "affordable_with_plan",
                    "recommended_payment_method": "full_payment",
                    "payment_plan_raw": plan_payments,
                    "payment_plan": f"{request_date_str}:{requested_amount}",
                    "earliest_date_for_full_payment": changed_earliest if changed_earliest else request_date_str,
                    "spending_changes_needed": change_str,
                    "spending_changes_raw": combo,
                    "completes_by_deadline": True,
                    "needs_spending_changes": True,
                    "total_payable": requested_amount,
                    "start_date": request_date_str,
                    "num_payments": 1,
                    "payment_option_id": None,
                })

        # Installments with changes
        if "installments" in user_methods:
            for opt in payment_options:
                if opt["payment_method"] != "installments":
                    continue
                if max_installment_months is not None:
                    if opt["number_of_payments"] > max_installment_months:
                        continue

                plan_payments = _build_installment_schedule(opt)
                if not plan_payments:
                    continue

                last_payment_date = plan_payments[-1][0]
                completes_by_deadline = last_payment_date <= desired_completion_date_str

                forecast_with_plan = recalculate_forecast_with_plan(changed_forecast, plan_payments, request_date)
                is_safe = check_forecast_safety(forecast_with_plan, min_balance)

                if is_safe:
                    candidates.append({
                        "affordability_status": "affordable_with_plan",
                        "recommended_payment_method": "installments",
                        "payment_plan_raw": plan_payments,
                        "payment_plan": "|".join(f"{d}:{a}" for d, a in plan_payments),
                        "earliest_date_for_full_payment": changed_earliest if changed_earliest else "",
                        "spending_changes_needed": change_str,
                        "spending_changes_raw": combo,
                        "completes_by_deadline": completes_by_deadline,
                        "needs_spending_changes": True,
                        "total_payable": opt["total_payable_amount"],
                        "start_date": plan_payments[0][0] if plan_payments else "",
                        "num_payments": len(plan_payments),
                        "payment_option_id": opt["payment_option_id"],
                    })

        # Partial payment with changes
        if allows_partial and "partial_payment" in user_methods:
            if 0 < changed_safe < requested_amount and changed_earliest:
                changed_earliest_dt = datetime.strptime(changed_earliest, "%Y-%m-%d")
                if changed_earliest_dt <= desired_completion_date:
                    remaining = round(requested_amount - changed_safe, 2)
                    plan_payments = [
                        (request_date_str, changed_safe),
                        (changed_earliest, remaining),
                    ]
                    forecast_with_plan = recalculate_forecast_with_plan(changed_forecast, plan_payments, request_date)
                    is_safe = check_forecast_safety(forecast_with_plan, min_balance)

                    if is_safe:
                        candidates.append({
                            "affordability_status": "affordable_with_plan",
                            "recommended_payment_method": "partial_payment",
                            "payment_plan_raw": plan_payments,
                            "payment_plan": "|".join(f"{d}:{a}" for d, a in plan_payments),
                            "earliest_date_for_full_payment": changed_earliest,
                            "spending_changes_needed": change_str,
                            "spending_changes_raw": combo,
                            "completes_by_deadline": True,
                            "needs_spending_changes": True,
                            "total_payable": requested_amount,
                            "start_date": request_date_str,
                            "num_payments": 2,
                            "payment_option_id": None,
                        })

    # ---- CANDIDATE: Wait with changes ----
    for combo in change_combos:
        changed_state = recalculate_with_spending_changes(
            ctx, message_facts, image_amounts, combo, recurring_patterns
        )
        changed_earliest = changed_state["earliest_date_for_full_payment"]
        changed_forecast = changed_state["forecast"]
        change_str = format_spending_changes(combo)

        if "full_payment" in user_methods and changed_earliest:
            changed_earliest_dt = datetime.strptime(changed_earliest, "%Y-%m-%d")
            if changed_earliest_dt > request_date and changed_earliest_dt <= desired_completion_date:
                plan_payments = [(changed_earliest, requested_amount)]
                forecast_with_plan = recalculate_forecast_with_plan(changed_forecast, plan_payments, request_date)
                is_safe = check_forecast_safety(forecast_with_plan, min_balance)

                if is_safe:
                    candidates.append({
                        "affordability_status": "affordable_later",
                        "recommended_payment_method": "wait",
                        "payment_plan_raw": plan_payments,
                        "payment_plan": f"{changed_earliest}:{requested_amount}",
                        "earliest_date_for_full_payment": changed_earliest,
                        "spending_changes_needed": change_str,
                        "spending_changes_raw": combo,
                        "completes_by_deadline": True,
                        "needs_spending_changes": True,
                        "total_payable": requested_amount,
                        "start_date": changed_earliest,
                        "num_payments": 1,
                        "payment_option_id": None,
                    })

    # ---- RANK CANDIDATES ----
    if not candidates:
        return _not_recommended(amount_safe, earliest_date, min_balance, profile)

    best = _rank_candidates(candidates)
    return best


def _build_installment_schedule(opt):
    """Build installment payment dates and amounts from a payment option."""
    try:
        first_date = datetime.strptime(opt["first_payment_date"], "%Y-%m-%d")
        num_payments = opt["number_of_payments"]
        amount_per = opt["payment_amount"]
        freq_days = opt["payment_frequency_days"]

        if freq_days is None or freq_days <= 0:
            return None

        schedule = []
        for i in range(num_payments):
            pay_date = first_date + timedelta(days=i * freq_days)
            schedule.append((pay_date.strftime("%Y-%m-%d"), round(amount_per, 2)))

        return schedule
    except (ValueError, TypeError, KeyError):
        return None


def _rank_candidates(candidates):
    """
    Rank candidates according to the problem's priority rules:
    1. Completes by desired_completion_date
    2. No spending changes needed
    3. Minimize total amount paid
    4. Start payment earlier
    5. Use fewer payments
    6. Lowest payment_option_id as final tie-breaker
    """
    def sort_key(c):
        return (
            0 if c["completes_by_deadline"] else 1,
            0 if not c["needs_spending_changes"] else 1,
            c["total_payable"],
            c["start_date"],
            c["num_payments"],
            c.get("payment_option_id") or "zzz",
        )

    candidates.sort(key=sort_key)
    return candidates[0]


def _not_recommended(amount_safe, earliest_date, min_balance, profile):
    """Return the not_recommended fallback result."""
    return {
        "affordability_status": "not_affordable",
        "recommended_payment_method": "not_recommended",
        "payment_plan": "none",
        "payment_plan_raw": [],
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "none",
        "spending_changes_raw": [],
        "completes_by_deadline": False,
        "needs_spending_changes": False,
        "total_payable": 0,
        "start_date": "",
        "num_payments": 0,
        "payment_option_id": None,
    }
