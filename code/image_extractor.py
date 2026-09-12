"""
image_extractor.py — Extract financial amounts from images using Gemini Vision API.

Falls back to a cached extraction map if the API is unavailable.
"""

import os
import json
import base64

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image_cache.json")
DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")


def extract_all_image_amounts(images_by_event, use_api=True):
    """
    Extract amounts from all images linked to events with blank amounts.
    
    Args:
        images_by_event: dict of event_id -> image info
        use_api: Whether to try the Gemini API first
    
    Returns:
        dict of event_id -> extracted amount (float)
    """
    # Load cache if exists
    cache = _load_cache()

    results = {}
    to_extract = []

    for event_id, img_info in images_by_event.items():
        if event_id in cache:
            results[event_id] = cache[event_id]
        else:
            to_extract.append((event_id, img_info))

    if to_extract and use_api:
        api_results, token_usage = _extract_via_gemini(to_extract)
        results.update(api_results)
        # Update cache
        cache.update(api_results)
        _save_cache(cache)
        return results, token_usage

    return results, {"input_tokens": 0, "output_tokens": 0, "calls": 0}


def _extract_via_gemini(items):
    """Extract amounts from images using Gemini Vision API."""
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("WARNING: No GEMINI_API_KEY found. Using fallback extraction.")
            return _fallback_extraction(items), {"input_tokens": 0, "output_tokens": 0, "calls": 0}

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.6-flash")

        results = {}
        total_input = 0
        total_output = 0
        total_calls = 0

        for event_id, img_info in items:
            image_path = img_info["image_path"]
            if not os.path.exists(image_path):
                print(f"WARNING: Image not found: {image_path}")
                continue

            try:
                # Read image
                with open(image_path, "rb") as f:
                    img_data = f.read()

                prompt = """Analyze this financial document image (payslip, receipt, invoice, bill, or statement).
Extract the key financial amount from this document. This could be:
- Net Pay / Take Home Pay (for payslips)
- Total Amount / Amount Due (for bills/invoices)
- Transaction Amount (for receipts)
- Refund Amount (for refund notifications)
- Payment Amount (for payment confirmations)

Return ONLY a JSON object with these fields:
{
  "amount": <number>,
  "currency": "<currency_code>",
  "document_type": "<payslip|bill|invoice|receipt|refund|statement|other>",
  "description": "<brief description of what the amount represents>"
}

Return ONLY the JSON, no other text."""

                response = model.generate_content(
                    [prompt, {"mime_type": "image/png", "data": img_data}],
                    generation_config={"temperature": 0.0}
                )

                # Track token usage
                if hasattr(response, "usage_metadata"):
                    total_input += getattr(response.usage_metadata, "prompt_token_count", 0)
                    total_output += getattr(response.usage_metadata, "candidates_token_count", 0)
                total_calls += 1

                # Parse response
                text = response.text.strip()
                # Remove markdown code fences if present
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[: text.rfind("```")]
                text = text.strip()
                if text.startswith("json"):
                    text = text[4:].strip()

                parsed = json.loads(text)
                amount = float(parsed["amount"])
                results[event_id] = amount
                print(f"  Extracted from {img_info['image_id']}: {parsed.get('currency', '?')} {amount} ({parsed.get('description', '')})")

            except Exception as e:
                print(f"  ERROR extracting from {img_info.get('image_id', '?')}: {e}")
                continue

        return results, {"input_tokens": total_input, "output_tokens": total_output, "calls": total_calls}

    except ImportError:
        print("WARNING: google-generativeai not installed. Using fallback extraction.")
        return _fallback_extraction(items), {"input_tokens": 0, "output_tokens": 0, "calls": 0}


def _fallback_extraction(items):
    """Fallback: return empty results (amounts will need manual review)."""
    print("WARNING: No image extraction available. Events with blank amounts will be skipped.")
    return {}


def _load_cache():
    """Load cached extraction results."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_cache(cache):
    """Save extraction results to cache."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        print(f"WARNING: Could not save image cache: {e}")
