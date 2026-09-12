"""Debug script to trace financial calculations for specific requests."""

import os, sys
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_loader import load_all_data, get_request_context
from message_interpreter import interpret_all_messages
from image_extractor import extract_all_image_amounts
from financial_engine import build_financial_state
from recurrence import detect_recurring_events, project_recurring_events

def debug_request(request_id_to_debug):
    data = load_all_data()
    
    # Find the request in sample_requests
    sample = data["sample_requests"]
    row = sample[sample["request_id"] == request_id_to_debug].iloc[0]
    
    print(f"\n{'='*60}")
    print(f"Debugging: {request_id_to_debug}")
    print(f"User: {row['user_id']}")
    print(f"Request Date: {row['request_date']}")
    print(f"Requested Amount: {row['requested_amount']}")
    print(f"Expected amount_safe_to_pay: {row['amount_safe_to_pay']}")
    print(f"Expected status: {row['affordability_status']}")
    print(f"Expected method: {row['recommended_payment_method']}")
    print(f"Expected earliest_date: {row.get('earliest_date_for_full_payment', '')}")
    print(f"{'='*60}")
    
    ctx = get_request_context(data, row)
    profile = ctx["profile"]
    
    print(f"\nProfile:")
    print(f"  Balance: {profile['current_available_balance']}")
    print(f"  Min Balance: {profile['minimum_balance_to_keep']}")
    print(f"  Currency: {profile['home_currency']}")
    print(f"  Methods: {profile['payment_methods_user_will_consider']}")
    print(f"  Can stop: {profile['expense_categories_user_is_willing_to_stop']}")
    print(f"  Can reduce: {profile['expense_categories_user_is_willing_to_reduce']}")
    
    # Get events
    events = ctx["events"]
    request_date = str(row["request_date"])
    
    # Count event types
    settled_debits = [e for e in events if e["status"] == "settled" and e["direction"] == "debit" and e["event_date"] <= request_date]
    settled_credits = [e for e in events if e["status"] == "settled" and e["direction"] == "credit" and e["event_date"] <= request_date]
    
    print(f"\nEvents summary:")
    print(f"  Total events: {len(events)}")
    print(f"  Settled debits before request: {len(settled_debits)}")
    print(f"  Settled credits before request: {len(settled_credits)}")
    
    # Detect recurring patterns
    recurring = detect_recurring_events(events, request_date)
    print(f"\nRecurring patterns detected: {len(recurring)}")
    for r in recurring:
        print(f"  {r['category']} | {r['description'][:40]} | {r['direction']} | {r['amount']} {r['currency']} | day {r['day_of_month']} | flex: {r['flexibility']}")
    
    # Interpret messages
    message_facts, _ = interpret_all_messages(data["messages_by_user"], use_api=False)
    user_facts = message_facts.get(row["user_id"], [])
    print(f"\nMessage facts for user: {len(user_facts)}")
    for f in user_facts:
        print(f"  {f['fact_type']}: {f.get('description', '')}")
    
    # Image amounts
    image_amounts, _ = extract_all_image_amounts(data["images_by_event"], use_api=False)
    
    # Build financial state
    state = build_financial_state(ctx, user_facts, image_amounts)
    
    print(f"\nFinancial State:")
    print(f"  amount_safe_to_pay: {state['amount_safe_to_pay']}")
    print(f"  earliest_date_for_full_payment: {state['earliest_date_for_full_payment']}")
    
    # Show forecast min/max
    forecast = state["forecast"]
    dates = sorted(forecast.keys())
    min_bal = min(forecast.values())
    min_date = [d for d in dates if forecast[d] == min_bal][0]
    
    print(f"\nForecast (90 days from {request_date}):")
    print(f"  Start: {forecast[dates[0]]}")
    print(f"  Min: {min_bal} on {min_date}")
    print(f"  End: {forecast[dates[-1]]}")
    print(f"  Safe = min - min_balance = {min_bal} - {profile['minimum_balance_to_keep']} = {min_bal - profile['minimum_balance_to_keep']}")
    
    # Show projected events
    projected = state["projected_events"]
    print(f"\nProjected events ({len(projected)}):")
    for p in projected[:20]:
        print(f"  {p['date']} | {p['direction']} | {p['amount']} | {p['category']} | {p['description'][:40]}")

    # Show first 15 days of forecast
    print(f"\nDaily forecast (first 30 days):")
    for d in dates[:30]:
        print(f"  {d}: {forecast[d]:.2f}")

if __name__ == "__main__":
    req = sys.argv[1] if len(sys.argv) > 1 else "request_01"
    debug_request(req)
