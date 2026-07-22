# Contributing

Thanks for helping make data agents safer to ship.

## Good first contributions

- add a deterministic SQL or policy validator
- contribute a failure case to `evals/chaos.yml`
- add metadata support for a documented open schema
- improve error messages or examples
- add a database dialect test
- publish a reproducible benchmark report

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
npm install
npm run build
```

Please keep the core framework-independent. Optional integrations belong behind adapters.

Metadata adapters should return a `Catalog` without leaking credentials or requiring a
network call during import. Agent adapters only need an `ask(question) -> AgentTrace`
method. Please include a fixture-based test so CI does not require access to a live
warehouse or model provider.

New functionality should include a focused test and avoid sending user data to external services by default.
