"""
evaluator.py — Evaluate predictions against sample ground truth.
"""

import pandas as pd
import os
import math

DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")


def evaluate_against_samples(predictions, sample_df=None):
    """
    Compare predictions against sample_requests.csv ground truth.
    
    Args:
        predictions: List of prediction dicts (output rows)
        sample_df: Optional DataFrame of sample_requests with ground truth
    
    Returns:
        Dict with evaluation metrics
    """
    if sample_df is None:
        sample_path = os.path.join(DATASET_DIR, "sample_requests.csv")
        sample_df = pd.read_csv(sample_path)

    # Build lookup from predictions
    pred_lookup = {p["request_id"]: p for p in predictions}

    # Get sample request_ids
    sample_ids = set(sample_df["request_id"].tolist())

    results = {
        "total_samples": len(sample_ids),
        "matched": 0,
        "status_correct": 0,
        "method_correct": 0,
        "amount_close": 0,
        "date_correct": 0,
        "plan_correct": 0,
        "details": [],
    }

    for _, row in sample_df.iterrows():
        req_id = row["request_id"]
        if req_id not in pred_lookup:
            results["details"].append({
                "request_id": req_id,
                "status": "MISSING",
                "notes": "No prediction found",
            })
            continue

        pred = pred_lookup[req_id]
        results["matched"] += 1
        detail = {"request_id": req_id, "errors": []}

        # Compare affordability_status
        expected_status = str(row.get("affordability_status", ""))
        pred_status = str(pred.get("affordability_status", ""))
        if expected_status == pred_status:
            results["status_correct"] += 1
            detail["status"] = "✓"
        else:
            detail["status"] = f"✗ (expected={expected_status}, got={pred_status})"
            detail["errors"].append(f"status: {expected_status} vs {pred_status}")

        # Compare recommended_payment_method
        expected_method = str(row.get("recommended_payment_method", ""))
        pred_method = str(pred.get("recommended_payment_method", ""))
        if expected_method == pred_method:
            results["method_correct"] += 1
            detail["method"] = "✓"
        else:
            detail["method"] = f"✗ (expected={expected_method}, got={pred_method})"
            detail["errors"].append(f"method: {expected_method} vs {pred_method}")

        # Compare amount_safe_to_pay (within 5% tolerance)
        try:
            expected_amount = float(row.get("amount_safe_to_pay", 0))
            pred_amount = float(pred.get("amount_safe_to_pay", 0))
            if expected_amount == 0:
                amount_ok = pred_amount == 0
            else:
                pct_diff = abs(pred_amount - expected_amount) / expected_amount
                amount_ok = pct_diff <= 0.05
            if amount_ok:
                results["amount_close"] += 1
                detail["amount"] = "✓"
            else:
                detail["amount"] = f"✗ (expected={expected_amount}, got={pred_amount})"
                detail["errors"].append(f"amount: {expected_amount} vs {pred_amount}")
        except (ValueError, TypeError):
            detail["amount"] = "✗ (parse error)"
            detail["errors"].append("amount: parse error")

        # Compare earliest_date_for_full_payment
        expected_date = str(row.get("earliest_date_for_full_payment", "")).strip()
        pred_date = str(pred.get("earliest_date_for_full_payment", "")).strip()
        if expected_date.lower() == "nan":
            expected_date = ""
        if pred_date.lower() == "nan":
            pred_date = ""
        if expected_date == pred_date:
            results["date_correct"] += 1
            detail["date"] = "✓"
        else:
            detail["date"] = f"✗ (expected={expected_date}, got={pred_date})"
            detail["errors"].append(f"date: {expected_date} vs {pred_date}")

        # Compare payment_plan (structural)
        expected_plan = str(row.get("payment_plan", "none")).strip()
        pred_plan = str(pred.get("payment_plan", "none")).strip()
        if _plans_match(expected_plan, pred_plan):
            results["plan_correct"] += 1
            detail["plan"] = "✓"
        else:
            detail["plan"] = f"✗ (expected={expected_plan[:50]}, got={pred_plan[:50]})"
            detail["errors"].append(f"plan mismatch")

        detail["num_errors"] = len(detail["errors"])
        results["details"].append(detail)

    # Summary stats
    n = results["total_samples"]
    if n > 0:
        results["status_accuracy"] = results["status_correct"] / n
        results["method_accuracy"] = results["method_correct"] / n
        results["amount_accuracy"] = results["amount_close"] / n
        results["date_accuracy"] = results["date_correct"] / n
        results["plan_accuracy"] = results["plan_correct"] / n
        results["overall_score"] = (
            results["status_accuracy"] * 0.25 +
            results["method_accuracy"] * 0.25 +
            results["amount_accuracy"] * 0.20 +
            results["date_accuracy"] * 0.15 +
            results["plan_accuracy"] * 0.15
        )

    return results


def _plans_match(expected, predicted):
    """Check if two payment plans match structurally."""
    if expected.lower() == "none" and predicted.lower() == "none":
        return True
    if expected.lower() == "none" or predicted.lower() == "none":
        return False

    # Parse both plans
    expected_parts = expected.split("|")
    predicted_parts = predicted.split("|")

    if len(expected_parts) != len(predicted_parts):
        return False

    for e, p in zip(expected_parts, predicted_parts):
        try:
            e_date, e_amount = e.split(":")
            p_date, p_amount = p.split(":")
            if e_date.strip() != p_date.strip():
                return False
            e_val = float(e_amount.strip())
            p_val = float(p_amount.strip())
            if e_val == 0:
                if p_val != 0:
                    return False
            else:
                if abs(p_val - e_val) / e_val > 0.05:
                    return False
        except (ValueError, IndexError):
            return False

    return True


def print_evaluation_report(results):
    """Print a formatted evaluation report."""
    print("\n" + "=" * 70)
    print("EVALUATION REPORT")
    print("=" * 70)
    print(f"Total samples: {results['total_samples']}")
    print(f"Matched: {results['matched']}")
    print()
    print(f"Status accuracy:  {results.get('status_accuracy', 0):.1%} ({results['status_correct']}/{results['total_samples']})")
    print(f"Method accuracy:  {results.get('method_accuracy', 0):.1%} ({results['method_correct']}/{results['total_samples']})")
    print(f"Amount accuracy:  {results.get('amount_accuracy', 0):.1%} ({results['amount_close']}/{results['total_samples']})")
    print(f"Date accuracy:    {results.get('date_accuracy', 0):.1%} ({results['date_correct']}/{results['total_samples']})")
    print(f"Plan accuracy:    {results.get('plan_accuracy', 0):.1%} ({results['plan_correct']}/{results['total_samples']})")
    print(f"Overall score:    {results.get('overall_score', 0):.1%}")
    print()

    # Show errors
    errors = [d for d in results["details"] if d.get("num_errors", 0) > 0 or d.get("status") == "MISSING"]
    if errors:
        print(f"Requests with errors ({len(errors)}):")
        for d in errors:
            if d.get("status") == "MISSING":
                print(f"  {d['request_id']}: MISSING")
            else:
                print(f"  {d['request_id']}: {', '.join(d.get('errors', []))}")
    else:
        print("All samples matched perfectly!")

    print("=" * 70)
