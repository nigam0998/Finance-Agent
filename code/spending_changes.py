"""
spending_changes.py — Identify flexible expenses that can be stopped or reduced.
"""


def find_possible_spending_changes(recurring_patterns, profile):
    """
    Identify flexible recurring expenses that can be stopped or reduced.
    
    Args:
        recurring_patterns: List of recurring event patterns
        profile: User profile dict
    
    Returns:
        List of possible spending changes, each with:
        - action: "stop" or "reduce_to"
        - event_id: the event to change
        - category: the expense category
        - current_amount: current recurring amount
        - new_amount: new amount (0 for stop, minimum_allowed_amount for reduce)
        - savings_per_month: how much is saved per month
    """
    protected = set(profile.get("expense_categories_to_protect", []))
    can_reduce = set(profile.get("expense_categories_user_is_willing_to_reduce", []))
    can_stop = set(profile.get("expense_categories_user_is_willing_to_stop", []))

    changes = []

    for pattern in recurring_patterns:
        if pattern["direction"] != "debit":
            continue

        category = pattern["category"]
        flexibility = pattern.get("flexibility", "fixed")
        event_id = pattern["event_id"]
        amount = pattern["amount"]
        min_amount = pattern.get("minimum_allowed_amount")

        # Cannot change protected categories
        if category in protected:
            continue

        # Cannot change fixed expenses
        if flexibility == "fixed":
            continue

        # Check stoppable expenses
        if flexibility == "stoppable" and category in can_stop:
            changes.append({
                "action": "stop",
                "event_id": event_id,
                "category": category,
                "description": pattern.get("description", ""),
                "current_amount": amount,
                "new_amount": 0,
                "savings_per_month": amount,
            })

        # Check reducible expenses
        if flexibility == "reducible" and category in can_reduce:
            if min_amount is not None and min_amount < amount:
                changes.append({
                    "action": "reduce_to",
                    "event_id": event_id,
                    "category": category,
                    "description": pattern.get("description", ""),
                    "current_amount": amount,
                    "new_amount": min_amount,
                    "savings_per_month": amount - min_amount,
                })

        # Some events can be either stopped or reduced
        # Stoppable expenses in "willing to reduce" categories
        if flexibility == "stoppable" and category in can_reduce and category not in can_stop:
            # Can't stop, but it's stoppable - actually the problem says only stop stoppable ones
            pass

        # Reducible in "willing to stop" - can we stop them? No, reducible means reduce only
        # But check if category matches
        if flexibility == "reducible" and category in can_stop and category not in can_reduce:
            # Reducible but user wants to stop - we can reduce to minimum
            if min_amount is not None and min_amount < amount:
                changes.append({
                    "action": "reduce_to",
                    "event_id": event_id,
                    "category": category,
                    "description": pattern.get("description", ""),
                    "current_amount": amount,
                    "new_amount": min_amount,
                    "savings_per_month": amount - min_amount,
                })

    # Sort by savings (highest first)
    changes.sort(key=lambda c: c["savings_per_month"], reverse=True)

    return changes


def generate_spending_change_combinations(possible_changes, max_changes=3):
    """
    Generate combinations of spending changes, up to max_changes.
    
    Returns list of lists of spending changes.
    """
    if not possible_changes:
        return []

    combinations = []

    # Ensure we don't have both stop and reduce for the same event
    event_ids = set()
    valid_changes = []
    for change in possible_changes:
        if change["event_id"] not in event_ids:
            valid_changes.append(change)
            event_ids.add(change["event_id"])

    # Single changes
    for c in valid_changes[:max_changes]:
        combinations.append([c])

    # Pairs (if enough changes)
    if len(valid_changes) >= 2:
        for i in range(min(len(valid_changes), max_changes)):
            for j in range(i + 1, min(len(valid_changes), max_changes)):
                combinations.append([valid_changes[i], valid_changes[j]])

    # Triples (if enough changes)
    if len(valid_changes) >= 3:
        for i in range(min(len(valid_changes), max_changes)):
            for j in range(i + 1, min(len(valid_changes), max_changes)):
                for k in range(j + 1, min(len(valid_changes), max_changes)):
                    combinations.append([valid_changes[i], valid_changes[j], valid_changes[k]])

    return combinations


def format_spending_changes(changes):
    """Format spending changes as the output string."""
    if not changes:
        return "none"

    parts = []
    for c in changes[:3]:
        if c["action"] == "stop":
            parts.append(f"stop:{c['event_id']}")
        elif c["action"] == "reduce_to":
            parts.append(f"reduce_to:{c['event_id']}:{c['new_amount']}")

    return "|".join(parts) if parts else "none"
