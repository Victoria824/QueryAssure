# Contributing

Thanks for helping make data agents safer to ship.

## Good first contributions

- add a deterministic SQL or policy validator
- contribute a failure case to `evals/chaos.yml`
- add metadata support for a documented open schema
- improve error messages or examples
- add a database dialect test

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

New functionality should include a focused test and avoid sending user data to external services by default.
