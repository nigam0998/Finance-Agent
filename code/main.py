"""
main.py — Entry point for the Buy or Wait? financial agent.

Orchestrates the full pipeline:
1. Load all data
2. Extract image amounts (via Gemini Vision)
3. Interpret messages (via Gemini LLM)
4. For each request: build financial state → evaluate plans → format output
5. Write output.csv
6. Evaluate against sample data
7. Generate usage report
"""

import os
import sys
import csv
import time
import json

# Add the repo root to path so imports work
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'code'))

from data_loader import load_all_data, get_request_context
from image_extractor import extract_all_image_amounts
from message_interpreter import interpret_all_messages
from financial_engine import build_financial_state
from plan_evaluator import evaluate_all_plans
from output_formatter import format_output_row
from evaluator import evaluate_against_samples, print_evaluation_report

OUTPUT_FILE = os.path.join(REPO_ROOT, "output.csv")
USAGE_REPORT_FILE = os.path.join(REPO_ROOT, "code", "evaluation", "usage_report.md")


def main():
    """Main entry point."""
    start_time = time.time()
    print("=" * 70)
    print("Buy or Wait? — AI Financial Agent")
    print("=" * 70)

    # Check for API key
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    use_api = bool(api_key)
    if use_api:
        print(f"[OK] API key found. Using Gemini for image extraction and message interpretation.")
    else:
        print("[WARN] No GEMINI_API_KEY found. Using rule-based fallback methods.")

    # Step 1: Load all data
    print("\n[1/6] Loading data...")
    data = load_all_data()
    print(f"  Loaded {len(data['requests'])} requests, {len(data['financial_profiles'])} profiles, "
          f"{len(data['financial_events'])} events")

    # Step 2: Extract image amounts
    print("\n[2/6] Extracting amounts from images...")
    image_amounts, img_token_usage = extract_all_image_amounts(data["images_by_event"], use_api=use_api)
    print(f"  Extracted amounts for {len(image_amounts)} events from images")

    # Step 3: Interpret messages
    print("\n[3/6] Interpreting messages...")
    message_facts, msg_token_usage = interpret_all_messages(data["messages_by_user"], use_api=use_api)
    print(f"  Interpreted messages for {len(message_facts)} users")

    # Step 4: Process each request
    print("\n[4/6] Processing requests...")
    predictions = []
    sample_predictions = []
    sample_ids = set(data["sample_requests"]["request_id"].tolist())

    total_requests = len(data["requests"])
    for idx, (_, row) in enumerate(data["requests"].iterrows()):
        request_id = row["request_id"]
        if (idx + 1) % 25 == 0 or idx == 0:
            print(f"  Processing request {idx + 1}/{total_requests} ({request_id})...")

        try:
            # Build context
            ctx = get_request_context(data, row)

            # Get user-specific message facts
            user_id = row["user_id"]
            user_facts = message_facts.get(user_id, [])

            # Build financial state
            financial_state = build_financial_state(ctx, user_facts, image_amounts)

            # Evaluate plans
            plan_result = evaluate_all_plans(ctx, financial_state, user_facts, image_amounts)

            # Format output
            output_row = format_output_row(
                ctx["request"], ctx["profile"], financial_state, plan_result, use_api=use_api
            )

            predictions.append(output_row)

        except Exception as e:
            print(f"  ERROR processing {request_id}: {e}")
            import traceback
            traceback.print_exc()
            # Add fallback row
            predictions.append({
                "request_id": request_id,
                "amount_safe_to_pay": 0,
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": f"Error processing request: {str(e)[:100]}",
            })

    # Also process sample requests for evaluation
    print("\n  Processing sample requests for evaluation...")
    for _, row in data["sample_requests"].iterrows():
        request_id = row["request_id"]
        try:
            ctx = get_request_context(data, row)
            user_id = row["user_id"]
            user_facts = message_facts.get(user_id, [])
            financial_state = build_financial_state(ctx, user_facts, image_amounts)
            plan_result = evaluate_all_plans(ctx, financial_state, user_facts, image_amounts)
            output_row = format_output_row(
                ctx["request"], ctx["profile"], financial_state, plan_result, use_api=use_api
            )
            sample_predictions.append(output_row)
        except Exception as e:
            print(f"  ERROR processing sample {request_id}: {e}")
            sample_predictions.append({
                "request_id": request_id,
                "amount_safe_to_pay": 0,
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": f"Error: {str(e)[:100]}",
            })

    # Step 5: Write output.csv
    print(f"\n[5/6] Writing output to {OUTPUT_FILE}...")
    _write_output(predictions, OUTPUT_FILE)
    print(f"  [OK] Written {len(predictions)} predictions")

    # Step 6: Evaluate against samples
    print("\n[6/6] Evaluating against sample data...")
    eval_results = evaluate_against_samples(sample_predictions)
    print_evaluation_report(eval_results)

    # Generate usage report
    elapsed = time.time() - start_time
    _write_usage_report(img_token_usage, msg_token_usage, len(predictions), elapsed)
    print(f"\n[OK] Completed in {elapsed:.1f} seconds")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Usage report: {USAGE_REPORT_FILE}")


def _write_output(predictions, output_file):
    """Write predictions to output.csv."""
    fieldnames = [
        "request_id", "amount_safe_to_pay", "affordability_status",
        "recommended_payment_method", "payment_plan",
        "earliest_date_for_full_payment", "spending_changes_needed",
        "decision_explanation"
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pred in predictions:
            writer.writerow(pred)


def _write_usage_report(img_usage, msg_usage, num_requests, elapsed):
    """Write the usage report."""
    total_input = img_usage.get("input_tokens", 0) + msg_usage.get("input_tokens", 0)
    total_output = img_usage.get("output_tokens", 0) + msg_usage.get("output_tokens", 0)
    total_calls = img_usage.get("calls", 0) + msg_usage.get("calls", 0)
    total_tokens = total_input + total_output

    # Estimate cost (Gemini 2.5 Flash pricing: ~$0.15/1M input, ~$0.60/1M output)
    est_cost = (total_input * 0.15 / 1_000_000) + (total_output * 0.60 / 1_000_000)

    os.makedirs(os.path.dirname(USAGE_REPORT_FILE), exist_ok=True)

    with open(USAGE_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("# Token Usage and Cost Report\n\n")
        f.write("## Summary\n\n")
        f.write(f"- **Run date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **Total requests processed**: {num_requests}\n")
        f.write(f"- **Total runtime**: {elapsed:.1f} seconds\n\n")

        f.write("## Model Usage\n\n")
        f.write("| Model | Provider | Calls | Input Tokens | Output Tokens | Total Tokens |\n")
        f.write("|-------|----------|-------|-------------|---------------|-------------|\n")

        if img_usage.get("calls", 0) > 0:
            f.write(f"| gemini-2.5-flash (images) | Google | {img_usage['calls']} | "
                    f"{img_usage['input_tokens']} | {img_usage['output_tokens']} | "
                    f"{img_usage['input_tokens'] + img_usage['output_tokens']} |\n")

        if msg_usage.get("calls", 0) > 0:
            f.write(f"| gemini-2.5-flash (messages) | Google | {msg_usage['calls']} | "
                    f"{msg_usage['input_tokens']} | {msg_usage['output_tokens']} | "
                    f"{msg_usage['input_tokens'] + msg_usage['output_tokens']} |\n")

        f.write(f"| **Total** | | **{total_calls}** | **{total_input}** | "
                f"**{total_output}** | **{total_tokens}** |\n\n")

        f.write("## Cost Estimate\n\n")
        f.write(f"- **Estimated total cost**: ${est_cost:.4f}\n")
        if num_requests > 0:
            f.write(f"- **Estimated per-request cost**: ${est_cost / num_requests:.6f}\n")
        f.write(f"- **Average tokens per request**: {total_tokens / max(num_requests, 1):.0f}\n\n")

        f.write("## Notes\n\n")
        f.write("- Image extraction: Gemini 2.5 Flash Vision API for 16 financial document images\n")
        f.write("- Message interpretation: Gemini 2.5 Flash for ~216 financial messages (batched)\n")
        f.write("- All financial calculations (forecasting, safety checks, plan evaluation) are deterministic Python\n")
        f.write("- Results are cached to avoid redundant API calls on re-runs\n")


if __name__ == "__main__":
    main()
