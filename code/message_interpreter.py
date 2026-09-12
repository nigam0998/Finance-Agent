"""
message_interpreter.py — Interpret financial messages to extract structured facts.

Uses Gemini LLM for interpretation, with caching and fallback parsing.
"""

import os
import json
import re

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "message_cache.json")


def interpret_all_messages(messages_by_user, use_api=True):
    """
    Interpret all messages and extract structured financial facts.
    
    Returns:
        dict of user_id -> list of financial facts
        token_usage dict
    """
    cache = _load_cache()
    results = {}
    to_interpret = []
    
    for user_id, msgs in messages_by_user.items():
        user_facts = []
        for msg in msgs:
            msg_id = msg["message_id"]
            if msg_id in cache:
                user_facts.append(cache[msg_id])
            else:
                to_interpret.append(msg)
        if user_facts:
            results[user_id] = user_facts

    token_usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    if to_interpret:
        if use_api:
            api_facts, token_usage = _interpret_via_gemini(to_interpret)
        else:
            api_facts = _interpret_via_rules(to_interpret)

        # Merge results
        for fact in api_facts:
            msg_id = fact.get("message_id", "")
            user_id = fact.get("user_id", "")
            cache[msg_id] = fact
            if user_id not in results:
                results[user_id] = []
            results[user_id].append(fact)

        _save_cache(cache)

    return results, token_usage


def _interpret_via_gemini(messages):
    """Interpret messages using Gemini LLM in batches."""
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("WARNING: No GEMINI_API_KEY. Using rule-based message interpretation.")
            return _interpret_via_rules(messages), {"input_tokens": 0, "output_tokens": 0, "calls": 0}

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.6-flash")

        all_facts = []
        total_input = 0
        total_output = 0
        total_calls = 0

        # Process in batches of 10
        batch_size = 10
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            batch_text = ""
            for idx, msg in enumerate(batch):
                batch_text += f"\n--- MESSAGE {idx + 1} ---\n"
                batch_text += f"message_id: {msg['message_id']}\n"
                batch_text += f"user_id: {msg['user_id']}\n"
                batch_text += f"request_id: {msg.get('request_id', '')}\n"
                batch_text += f"related_event_id: {msg.get('related_event_id', '')}\n"
                batch_text += f"sent_at: {msg.get('sent_at', '')}\n"
                batch_text += f"source_type: {msg.get('source_type', '')}\n"
                batch_text += f"message_text: {msg.get('message_text', '')}\n"

            prompt = f"""Analyze these financial messages and extract structured facts from each.
For each message, determine what financial information it conveys. Common types:

1. SALARY_CHANGE: salary amount changed (new_amount, effective_date)
2. SALARY_CONFIRMED: salary confirmed for a specific date (amount, payment_date)
3. FIRST_SALARY: first salary from new employer (amount, payment_date)
4. SALARY_REDUCED: temporary salary reduction (new_amount, reason)
5. INCOME_ENDED: employment/contract ended, no more income
6. BONUS_PENDING: bonus/commission pending, NOT confirmed (do not count)
7. INVOICE_CONFIRMED: freelance invoice confirmed for payment (amount, expected_date)
8. INVOICE_PENDING: invoice still pending approval (do not count)
9. REFUND_PENDING: refund initiated but not yet received (do not count as income)
10. PRIZE_SETTLED: prize/lottery proceeds received in account (amount, already_settled=true)
11. PRIZE_PENDING: prize verified but not yet paid (do not count)
12. RENT_INCREASE: lease renewed with rent increase (percentage or new_amount)
13. ACCOUNT_TRANSFER: internal transfer between own accounts (net zero effect)
14. PAYOUT_PENDING: gig/freelance payout pending (do not count until settled)
15. INVESTMENT_UNREALIZED: portfolio value changed but no cash (ignore for cash flow)
16. PAYMENT_RECEIVED: payment received with details (amount, date)
17. PAYROLL_DATE_CHANGE: salary payment date changed (new_date)
18. CHILDCARE_EXPENSE_NEW: new recurring expense starting (amount, start_date)
19. OTHER: any other relevant financial fact

For each message, return a JSON object. Return a JSON array of all message interpretations.

Each object should have:
{{
  "message_id": "<message_id>",
  "user_id": "<user_id>",
  "related_event_id": "<event_id or empty>",
  "fact_type": "<one of the types above>",
  "amount": <number or null>,
  "currency": "<currency code or null>",
  "effective_date": "<YYYY-MM-DD or null>",
  "description": "<brief summary of the fact>",
  "should_count_as_income": <true/false>,
  "should_count_as_expense": <true/false>,
  "cancels_future_income": <true/false>,
  "modifies_event_id": "<event_id this modifies, or null>",
  "rent_increase_pct": <percentage or null>,
  "new_salary_amount": <number or null>,
  "payment_date": "<YYYY-MM-DD or null>"
}}

Messages:
{batch_text}

Return ONLY the JSON array, no other text."""

            try:
                response = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.0}
                )

                if hasattr(response, "usage_metadata"):
                    total_input += getattr(response.usage_metadata, "prompt_token_count", 0)
                    total_output += getattr(response.usage_metadata, "candidates_token_count", 0)
                total_calls += 1

                text = response.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[: text.rfind("```")]
                text = text.strip()
                if text.startswith("json"):
                    text = text[4:].strip()

                facts = json.loads(text)
                if isinstance(facts, list):
                    all_facts.extend(facts)
                elif isinstance(facts, dict):
                    all_facts.append(facts)

            except Exception as e:
                print(f"  ERROR interpreting batch: {e}")
                # Fallback to rules for this batch
                all_facts.extend(_interpret_via_rules(batch))

        return all_facts, {"input_tokens": total_input, "output_tokens": total_output, "calls": total_calls}

    except ImportError:
        print("WARNING: google-generativeai not installed. Using rule-based interpretation.")
        return _interpret_via_rules(messages), {"input_tokens": 0, "output_tokens": 0, "calls": 0}


def _interpret_via_rules(messages):
    """Rule-based message interpretation as fallback."""
    facts = []
    for msg in messages:
        text = msg.get("message_text", "").lower()
        fact = {
            "message_id": msg["message_id"],
            "user_id": msg["user_id"],
            "related_event_id": msg.get("related_event_id", ""),
            "fact_type": "OTHER",
            "amount": None,
            "currency": None,
            "effective_date": None,
            "description": "",
            "should_count_as_income": False,
            "should_count_as_expense": False,
            "cancels_future_income": False,
            "modifies_event_id": msg.get("related_event_id"),
            "rent_increase_pct": None,
            "new_salary_amount": None,
            "payment_date": None,
        }

        # Salary increase/change
        salary_match = re.search(r'(?:salary|gaji).{0,50}(?:increased?|naik|changed?|berubah).{0,30}(?:to|menjadi)\s+(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
        if salary_match:
            amount = _parse_amount(salary_match.group(1))
            fact["fact_type"] = "SALARY_CHANGE"
            fact["new_salary_amount"] = amount
            fact["amount"] = amount
            date_match = re.search(r'(?:from|mulai|applies? from)\s+(\d{4}-\d{2}-\d{2})', text)
            if date_match:
                fact["effective_date"] = date_match.group(1)
                fact["payment_date"] = date_match.group(1)
            fact["should_count_as_income"] = True
            fact["description"] = f"Salary changed to {amount}"

        # First salary
        elif re.search(r'first salary|gaji pertama', text):
            amount_match = re.search(r'(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if amount_match:
                amount = _parse_amount(amount_match.group(1))
                fact["fact_type"] = "FIRST_SALARY"
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                date_match = re.search(r'(?:confirmed?.{0,20}(?:date|for)|credit date is|dikonfirmasi untuk)\s+(\d{4}-\d{2}-\d{2})', text)
                if date_match:
                    fact["payment_date"] = date_match.group(1)
                    fact["effective_date"] = date_match.group(1)
                fact["should_count_as_income"] = True
                fact["description"] = f"First salary: {amount}"

        # Salary reduced
        elif re.search(r'salary.{0,20}(?:reduced|temporary|sementara)', text) or re.search(r'temporary.{0,20}(?:pay|salary)', text):
            amount_match = re.search(r'(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if amount_match:
                amount = _parse_amount(amount_match.group(1))
                fact["fact_type"] = "SALARY_REDUCED"
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                fact["should_count_as_income"] = True
                fact["description"] = f"Salary temporarily reduced to {amount}"

        # Regular salary confirmed
        elif re.search(r'regular salary|gaji rutin|confirmed salary|gaji.*dikonfirmasi', text):
            amount_match = re.search(r'(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if amount_match:
                amount = _parse_amount(amount_match.group(1))
                fact["fact_type"] = "SALARY_CONFIRMED"
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if date_match:
                    fact["payment_date"] = date_match.group(1)
                    fact["effective_date"] = date_match.group(1)
                fact["should_count_as_income"] = True
                fact["description"] = f"Salary confirmed: {amount}"

        # Employment/contract ended
        elif re.search(r'(?:contract|employment).{0,20}ended|berakhir|no.{0,30}income.{0,20}confirmed|no regular salary', text):
            fact["fact_type"] = "INCOME_ENDED"
            fact["cancels_future_income"] = True
            fact["description"] = "Income source ended"
            # Check for remaining salary
            remain_match = re.search(r'remaining.{0,30}salary.{0,10}(?:is|of)\s+(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if remain_match:
                amount = _parse_amount(remain_match.group(1))
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                fact["should_count_as_income"] = True
                fact["description"] = f"One income ended, remaining salary: {amount}"

        # Income ended (Indonesian)
        elif re.search(r'sumber pendapatan.{0,30}berakhir|sisa gaji', text):
            fact["fact_type"] = "INCOME_ENDED"
            remain_match = re.search(r'(?:sisa gaji|remaining).{0,30}(?:adalah|is)\s+(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if remain_match:
                amount = _parse_amount(remain_match.group(1))
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                fact["should_count_as_income"] = True
            fact["description"] = "Income source ended"

        # Invoice confirmed
        elif re.search(r'(?:invoice|faktur).{0,30}(?:approved|confirmed|disetujui)', text):
            amount_match = re.search(r'(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if amount_match:
                amount = _parse_amount(amount_match.group(1))
                fact["fact_type"] = "INVOICE_CONFIRMED"
                fact["amount"] = amount
                date_match = re.search(r'(?:settlement|expected|diperkirakan).{0,20}(\d{4}-\d{2}-\d{2})', text)
                if date_match:
                    fact["payment_date"] = date_match.group(1)
                    fact["effective_date"] = date_match.group(1)
                fact["should_count_as_income"] = True
                fact["description"] = f"Invoice confirmed: {amount}"

        # Payout pending (gig work)
        elif re.search(r'payout.{0,20}(?:pending|still pending)|pembayaran.{0,30}tertunda', text):
            fact["fact_type"] = "PAYOUT_PENDING"
            fact["should_count_as_income"] = False
            fact["cancels_future_income"] = True
            fact["description"] = "Payout pending - do not count"

        # Refund pending
        elif re.search(r'refund.{0,30}(?:initiated|processing|not.*reached)', text):
            fact["fact_type"] = "REFUND_PENDING"
            fact["should_count_as_income"] = False
            fact["description"] = "Refund pending - do not count"

        # Prize settled
        elif re.search(r'prize.{0,30}(?:reached|received|credited)', text):
            fact["fact_type"] = "PRIZE_SETTLED"
            fact["description"] = "Prize already settled in account"

        # Prize pending
        elif re.search(r'prize.{0,30}(?:verified|processing|pending)', text):
            fact["fact_type"] = "PRIZE_PENDING"
            fact["should_count_as_income"] = False
            fact["description"] = "Prize pending - do not count"

        # Rent increase
        elif re.search(r'(?:lease|rent).{0,30}(?:increase|renewal)|sewa.{0,30}naik', text):
            pct_match = re.search(r'(\d+)%', text)
            if pct_match:
                fact["fact_type"] = "RENT_INCREASE"
                fact["rent_increase_pct"] = float(pct_match.group(1))
                fact["description"] = f"Rent increases by {pct_match.group(1)}%"

        # Internal transfer (net zero)
        elif re.search(r'transfer between.{0,20}(?:your|own).{0,10}accounts|transfer antar rekening', text):
            fact["fact_type"] = "ACCOUNT_TRANSFER"
            fact["description"] = "Internal transfer - net zero"

        # Investment unrealized
        elif re.search(r'portfolio.{0,30}(?:value|market).{0,30}(?:increased|changed)|no.{0,20}units.{0,20}sold', text):
            fact["fact_type"] = "INVESTMENT_UNREALIZED"
            fact["should_count_as_income"] = False
            fact["description"] = "Unrealized investment gain - ignore"

        # Bonus/commission pending
        elif re.search(r'(?:bonus|commission|komisi).{0,30}(?:pending|awaiting|menunggu|not.*approved)', text):
            fact["fact_type"] = "BONUS_PENDING"
            fact["should_count_as_income"] = False
            fact["description"] = "Bonus/commission pending - do not count"

        # Payroll date change
        elif re.search(r'salary.{0,20}(?:expected|now expected|scheduled).{0,20}(\d{4}-\d{2}-\d{2})', text):
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
            if date_match:
                fact["fact_type"] = "PAYROLL_DATE_CHANGE"
                fact["payment_date"] = date_match.group(1)
                fact["effective_date"] = date_match.group(1)
                fact["description"] = f"Salary date changed to {date_match.group(1)}"

        # Payment received (for images/receipts)
        elif re.search(r'payment.{0,20}(?:was received|received)', text):
            fact["fact_type"] = "PAYMENT_RECEIVED"
            fact["description"] = "Payment received confirmation"

        # Regular salary with one-time arrears
        elif re.search(r'(?:regular salary|gaji rutin).{0,50}(?:arrears|tunggakan)', text):
            # Extract regular salary
            salary_match = re.search(r'(?:regular salary|gaji rutin).{0,30}(?:is|of|adalah)\s+(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            arrears_match = re.search(r'(?:arrears|tunggakan).{0,30}(?:of|sebesar)\s+(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if salary_match:
                fact["fact_type"] = "SALARY_CONFIRMED"
                amount = _parse_amount(salary_match.group(1))
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                fact["should_count_as_income"] = True
                if arrears_match:
                    arrears = _parse_amount(arrears_match.group(1))
                    fact["description"] = f"Salary confirmed: {amount}, plus one-time arrears: {arrears}"
                else:
                    fact["description"] = f"Salary confirmed: {amount}"

        # Foreign currency salary
        elif re.search(r'salary.{0,30}(?:confirmed|dikonfirmasi).{0,30}(?:[A-Z]{3})', text):
            amount_match = re.search(r'(?:[A-Z]{3}\s+)?([0-9,.]+)', text)
            if amount_match:
                amount = _parse_amount(amount_match.group(1))
                # Try to find currency
                curr_match = re.search(r'(USD|EUR|INR|ZAR|IDR)\s+[0-9]', text)
                if curr_match:
                    fact["currency"] = curr_match.group(1)
                fact["fact_type"] = "SALARY_CONFIRMED"
                fact["amount"] = amount
                fact["new_salary_amount"] = amount
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if date_match:
                    fact["payment_date"] = date_match.group(1)
                fact["should_count_as_income"] = True
                fact["description"] = f"Foreign salary confirmed: {amount}"

        # Childcare/new expense
        elif re.search(r'childcare|new.{0,20}recurring.{0,20}payment', text):
            fact["fact_type"] = "CHILDCARE_EXPENSE_NEW"
            fact["should_count_as_expense"] = True
            fact["description"] = "New recurring expense (childcare)"

        # Employment ended
        elif re.search(r'employment has ended|tidak ada.{0,30}gaji', text):
            fact["fact_type"] = "INCOME_ENDED"
            fact["cancels_future_income"] = True
            fact["description"] = "Employment ended - no more salary"

        facts.append(fact)

    return facts


def _parse_amount(s):
    """Parse amount string, removing commas and converting to float."""
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None


def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        print(f"WARNING: Could not save message cache: {e}")
