.PHONY: smoke test ui

# Run curl smoke against an already-running server (see scripts/smoke_test.sh header).
smoke:
	bash scripts/smoke_test.sh

# Local Streamlit chat UI (requires pip install -e ".[ui]" and a running backend).
ui:
	streamlit run ui/streamlit_app.py

test:
	pytest -q
