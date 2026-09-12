# Finance Agent

An AI-powered financial agent that decides whether a user can safely afford a requested expense.

## Overview
A user may ask: "Can I afford this laptop?"
The agent considers more than the user's current balance. It accounts for recurring expenses, pending payments, essential spending, confirmed income, payment options, and relevant information found in messages or images.

For every request, the agent decides whether the user should pay in full, pay partially, use installments, wait, or not proceed. The recommendation is highly personalized. Two users with the same balance may receive different recommendations based on their financial history, commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

## Core Features
*   **Contextual Financial Modeling:** Separates recurring expenses from one-time events, reserves pending transactions, counts confirmed salary only on its settlement date, and de-duplicates repeated representations of the same event.
*   **Generative AI Integration:** Uses the Gemini Generative AI models (e.g., Gemini 3.6 Flash and Vision) to interpret unstructured financial messages and extract payment amounts from uploaded document images (such as payroll letters, statements, bills, and receipts).
*   **Deterministic Safety Checks:** Forecasts forward and generates a plan that keeps the balance above the minimum at every step. Verifies deterministically—bounds, plan feasibility, schedule match, flexible-only spending changes—before making a recommendation.
*   **Flexible Adjustments:** Capable of suggesting spending changes (stopping or reducing flexible expenses) if it allows the user to afford a desired purchase.

## Architecture
The agent is divided into distinct execution phases:
1.  **Data Loading:** Loads raw CSV datasets representing users, requests, accounts, exchange rates, and unstructured attachments.
2.  **Generative AI Extraction:** Batches unformatted messages and images to the Gemini API for structured JSON extraction.
3.  **Financial Engine:** Constructs a rigorous mathematical simulation of the user's past and future cash flow.
4.  **Plan Evaluator:** Iterates through possible payment options (Full Payment, Partial Payment, Installments, Wait) to recommend the most optimal path without violating financial constraints.
5.  **Output Generation:** Produces a standardized CSV of personalized financial recommendations.

## Running the Agent

### Prerequisites
*   Python 3.8+
*   `google-generativeai` package
*   A valid Gemini API Key

### Usage
Set your Gemini API key in your environment:
```bash
export GEMINI_API_KEY="your_api_key_here"
```

Run the orchestration script:
```bash
python code/main.py
```

The system will generate an `output.csv` file containing the predictions and a usage report located at `code/evaluation/usage_report.md` tracking the AI token consumption.


