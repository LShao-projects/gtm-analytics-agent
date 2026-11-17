from pathlib import Path

import streamlit as st

from dashboard.data import DEFAULT_DATABASE, DatabaseValidationError, validate_database
from dashboard.ui import render_app


st.set_page_config(
    page_title="Maven Revenue Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    database_path = Path(DEFAULT_DATABASE)
    try:
        metadata = validate_database(database_path)
    except DatabaseValidationError as exc:
        st.error("The dashboard data source is unavailable.")
        st.code(str(exc))
        st.info("Rebuild it atomically from the included CSVs with: `.venv/bin/python scripts/build_database.py --force`")
        st.stop()
    render_app(database_path, metadata)


if __name__ == "__main__":
    main()

