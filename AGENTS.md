# Repository instructions

- Maintain the standalone visualization routing API and decision dataclass.
- Keep the module independent from host application imports and chart implementations.
- Preserve confidence thresholds, no-visual decisions, evidence and mark strategy contracts.
- Never commit credentials, user questions/history, or machine-specific paths.
- Run `python -m pytest tests -q` after changes.
