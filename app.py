from pathlib import Path

import streamlit as st

from dashboard.data import (
    DEFAULT_DATABASE,
    DatabaseQueryError,
    DatabaseValidationError,
    validate_database,
)
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
    try:
        render_app(database_path, metadata)
    except DatabaseQueryError as exc:
        st.error("The dashboard query could not be completed.")
        st.code(str(exc))
        st.info(
            "If the local database was rebuilt while Streamlit was running, restart "
            "the app and try again. Otherwise rebuild it atomically with: "
            "`.venv/bin/python scripts/build_database.py --force`"
        )
        st.stop()


if __name__ == "__main__":
    main()

