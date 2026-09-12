"""
data_loader.py — Load and index all CSV data for the Buy or Wait financial agent.
"""

import pandas as pd
import os
from collections import defaultdict

DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")


def load_all_data():
    """Load all CSV files and return a dict of DataFrames and indexed structures."""
    data = {}

    # Load raw DataFrames
    data["requests"] = pd.read_csv(os.path.join(DATASET_DIR, "requests.csv"))
    data["sample_requests"] = pd.read_csv(os.path.join(DATASET_DIR, "sample_requests.csv"))
    data["financial_profiles"] = pd.read_csv(os.path.join(DATASET_DIR, "financial_profiles.csv"))
    data["financial_events"] = pd.read_csv(os.path.join(DATASET_DIR, "financial_events.csv"))
    data["exchange_rates"] = pd.read_csv(os.path.join(DATASET_DIR, "exchange_rates.csv"))
    data["payment_options"] = pd.read_csv(os.path.join(DATASET_DIR, "request_payment_options.csv"))
    data["messages"] = pd.read_csv(os.path.join(DATASET_DIR, "messages.csv"))
    data["images"] = pd.read_csv(os.path.join(DATASET_DIR, "images.csv"))

    # Build indexed structures for efficient lookup
    data["profiles_by_user"] = _index_profiles(data["financial_profiles"])
    data["events_by_user"] = _index_events_by_user(data["financial_events"])
    data["options_by_request"] = _index_options_by_request(data["payment_options"])
    data["messages_by_user"] = _index_messages_by_user(data["messages"])
    data["messages_by_request"] = _index_messages_by_request(data["messages"])
    data["images_by_event"] = _index_images_by_event(data["images"])
    data["images_by_request"] = _index_images_by_request(data["images"])
    data["exchange_rate_lookup"] = _build_exchange_rate_lookup(data["exchange_rates"])

    return data


def _index_profiles(df):
    """Index profiles by user_id."""
    profiles = {}
    for _, row in df.iterrows():
        user_id = row["user_id"]
        profiles[user_id] = {
            "user_id": user_id,
            "home_currency": row["home_currency"],
            "current_available_balance": float(row["current_available_balance"]),
            "minimum_balance_to_keep": float(row["minimum_balance_to_keep"]),
            "financial_priorities": _parse_pipe_list(row.get("financial_priorities", "")),
            "expense_categories_to_protect": _parse_pipe_list(row.get("expense_categories_to_protect", "")),
            "expense_categories_user_is_willing_to_reduce": _parse_pipe_list(row.get("expense_categories_user_is_willing_to_reduce", "")),
            "expense_categories_user_is_willing_to_stop": _parse_pipe_list(row.get("expense_categories_user_is_willing_to_stop", "")),
            "payment_methods_user_will_consider": _parse_pipe_list(row.get("payment_methods_user_will_consider", "")),
            "max_installment_months": _parse_max_installments(row.get("max_installment_months", "")),
        }
    return profiles


def _index_events_by_user(df):
    """Index financial events by user_id, as list of dicts."""
    events = defaultdict(list)
    for _, row in df.iterrows():
        event = {
            "event_id": row["event_id"],
            "user_id": row["user_id"],
            "event_type": row["event_type"],
            "description": str(row.get("description", "")),
            "category": str(row.get("category", "")),
            "direction": row["direction"],
            "amount": _safe_float(row.get("amount")),
            "currency": str(row.get("currency", "")),
            "event_date": str(row.get("event_date", "")),
            "settlement_date": str(row.get("settlement_date", "")),
            "status": str(row.get("status", "")),
            "linked_event_id": str(row.get("linked_event_id", "")) if pd.notna(row.get("linked_event_id")) else "",
            "flexibility": str(row.get("flexibility", "")),
            "minimum_allowed_amount": _safe_float(row.get("minimum_allowed_amount")),
        }
        events[row["user_id"]].append(event)
    return dict(events)


def _index_options_by_request(df):
    """Index payment options by request_id."""
    options = defaultdict(list)
    for _, row in df.iterrows():
        opt = {
            "payment_option_id": row["payment_option_id"],
            "request_id": row["request_id"],
            "payment_method": row["payment_method"],
            "payment_amount": float(row["payment_amount"]),
            "number_of_payments": int(row["number_of_payments"]),
            "first_payment_date": str(row.get("first_payment_date", "")),
            "payment_frequency_days": _safe_int(row.get("payment_frequency_days")),
            "financing_fee": float(row.get("financing_fee", 0)),
            "total_payable_amount": float(row["total_payable_amount"]),
        }
        options[row["request_id"]].append(opt)
    return dict(options)


def _index_messages_by_user(df):
    """Index messages by user_id."""
    msgs = defaultdict(list)
    for _, row in df.iterrows():
        msg = _parse_message_row(row)
        msgs[row["user_id"]].append(msg)
    return dict(msgs)


def _index_messages_by_request(df):
    """Index messages by request_id (only those with request_id)."""
    msgs = defaultdict(list)
    for _, row in df.iterrows():
        if pd.notna(row.get("request_id")) and str(row.get("request_id", "")).strip():
            msg = _parse_message_row(row)
            msgs[row["request_id"]].append(msg)
    return dict(msgs)


def _parse_message_row(row):
    return {
        "message_id": row["message_id"],
        "user_id": row["user_id"],
        "request_id": str(row.get("request_id", "")) if pd.notna(row.get("request_id")) else "",
        "related_event_id": str(row.get("related_event_id", "")) if pd.notna(row.get("related_event_id")) else "",
        "sent_at": str(row.get("sent_at", "")),
        "source_type": str(row.get("source_type", "")),
        "message_text": str(row.get("message_text", "")),
    }


def _index_images_by_event(df):
    """Index images by related_event_id."""
    imgs = {}
    for _, row in df.iterrows():
        event_id = str(row.get("related_event_id", ""))
        if event_id:
            imgs[event_id] = {
                "image_id": row["image_id"],
                "user_id": row["user_id"],
                "request_id": str(row.get("request_id", "")) if pd.notna(row.get("request_id")) else "",
                "related_event_id": event_id,
                "image_path": os.path.join(DATASET_DIR, "media", "images", f"{row['image_id']}.png"),
            }
    return imgs


def _index_images_by_request(df):
    """Index images by request_id."""
    imgs = defaultdict(list)
    for _, row in df.iterrows():
        if pd.notna(row.get("request_id")) and str(row.get("request_id", "")).strip():
            img = {
                "image_id": row["image_id"],
                "user_id": row["user_id"],
                "request_id": str(row["request_id"]),
                "related_event_id": str(row.get("related_event_id", "")) if pd.notna(row.get("related_event_id")) else "",
                "image_path": os.path.join(DATASET_DIR, "media", "images", f"{row['image_id']}.png"),
            }
            imgs[row["request_id"]].append(img)
    return dict(imgs)


def _build_exchange_rate_lookup(df):
    """Build a lookup: (rate_date, from_currency, to_currency) -> rate."""
    lookup = {}
    for _, row in df.iterrows():
        key = (str(row["rate_date"]), str(row["from_currency"]), str(row["to_currency"]))
        lookup[key] = float(row["rate"])
    return lookup


def _parse_pipe_list(val):
    """Parse a pipe-separated list string."""
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan":
        return []
    return [x.strip() for x in str(val).split("|") if x.strip()]


def _parse_max_installments(val):
    """Parse max_installment_months, which can be blank or a number."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        s = str(val).strip()
        if s == "" or s.lower() == "nan":
            return None
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _safe_float(val):
    """Convert to float safely, return None if not possible."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    """Convert to int safely, return None if not possible."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def get_request_context(data, request_row):
    """
    Build the full context for a single request.
    Returns a dict with all relevant data for processing.
    """
    request_id = request_row["request_id"]
    user_id = request_row["user_id"]

    ctx = {
        "request": {
            "request_id": request_id,
            "user_id": user_id,
            "request_date": str(request_row["request_date"]),
            "request_type": str(request_row["request_type"]),
            "requested_amount": float(request_row["requested_amount"]),
            "desired_completion_date": str(request_row["desired_completion_date"]),
            "allows_partial_payment": str(request_row["allows_partial_payment"]).lower() == "true",
            "request_text": str(request_row.get("request_text", "")),
        },
        "profile": data["profiles_by_user"].get(user_id, {}),
        "events": data["events_by_user"].get(user_id, []),
        "payment_options": data["options_by_request"].get(request_id, []),
        "messages": data["messages_by_user"].get(user_id, []),
        "request_messages": data["messages_by_request"].get(request_id, []),
        "request_images": data["images_by_request"].get(request_id, []),
        "images_by_event": data["images_by_event"],
        "exchange_rate_lookup": data["exchange_rate_lookup"],
    }
    return ctx
