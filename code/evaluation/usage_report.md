# Token Usage and Cost Report

## Summary

- **Run date**: 2026-09-12 22:47:42
- **Total requests processed**: 250
- **Total runtime**: 55.0 seconds

## Model Usage

| Model | Provider | Calls | Input Tokens | Output Tokens | Total Tokens |
|-------|----------|-------|-------------|---------------|-------------|
| gemini-2.5-flash (images) | Google | 6 | 7502 | 331 | 7833 |
| **Total** | | **6** | **7502** | **331** | **7833** |

## Cost Estimate

- **Estimated total cost**: $0.0013
- **Estimated per-request cost**: $0.000005
- **Average tokens per request**: 31

## Notes

- Image extraction: Gemini 2.5 Flash Vision API for 16 financial document images
- Message interpretation: Gemini 2.5 Flash for ~216 financial messages (batched)
- All financial calculations (forecasting, safety checks, plan evaluation) are deterministic Python
- Results are cached to avoid redundant API calls on re-runs
