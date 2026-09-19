"""Streamlit viewer: streamlit run app/viewer.py"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from loader import Inbox  # noqa: E402
from src.extractor import BLANK, FIELDS  # noqa: E402
from src.pipeline import analyze_comparison  # noqa: E402

SUBMISSION_PATH = ROOT / "output" / "submission.json"
REASON_TEXT = {
    "missing_attachment": "The SI and/or the BL was not attached.",
    "wrong_doc_type": "The second attachment is not a Bill of Lading.",
    "unreadable": "An attachment could not be read (scanned/empty/corrupt file).",
    "missing_value": "A required field is blank in the source document.",
}

st.set_page_config(page_title="Shipping Doc Checker", layout="wide")


@st.cache_resource
def get_inbox(source: str) -> Inbox:
    if not source.startswith("http") and not Path(source).is_absolute():
        source = str(ROOT / source)
    return Inbox(source)


@st.cache_data(show_spinner="Loading extraction details (cached LLM results)...")
def get_detail(source: str, email_id: str) -> dict:
    inbox = get_inbox(source)
    return analyze_comparison(inbox, inbox.get(email_id))


def build_table(submission: dict, inbox: Inbox) -> pd.DataFrame:
    rows = []
    for email_id, entry in submission.items():
        subject = inbox.get(email_id)["subject"]
        rows.append({
            "email_id": email_id,
            "subject": subject if len(subject) <= 70 else subject[:67] + "...",
            "category": entry["category"],
            "status": entry["status"],
        })
    return pd.DataFrame(rows)


def show_summary(submission: dict) -> None:
    df = pd.DataFrame(submission).T
    st.metric("Total emails processed", len(df))
    cats = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
    for col, cat in zip(st.columns(len(cats)), cats):
        col.metric(cat, int((df["category"] == cat).sum()))
    statuses = ["OK", "MISMATCH", "NEEDS_REVIEW"]
    for col, s in zip(st.columns(len(statuses)), statuses):
        col.metric(s, int((df["status"] == s).sum()))


def show_field_table(detail: dict, defects: list[str]) -> None:
    rows = [{
        "Field": f,
        "SI value": detail["si_fields"].get(f),
        "BL value": detail["bl_fields"].get(f),
        "Result": "MISMATCH" if f in defects else "match",
    } for f in FIELDS]
    df = pd.DataFrame(rows).astype(str)
    styled = df.style.apply(
        lambda r: ["background-color: #ffd6d6; color: #7a0000; font-weight: bold"] * len(r)
        if r["Field"] in defects else [""] * len(r),
        axis=1,
    )
    st.dataframe(styled, hide_index=True, width="stretch")


def show_review(entry: dict, detail: dict) -> None:
    st.warning(f"**Needs a human decision:** {REASON_TEXT[entry['review_reason']]}  \n"
               f"Reason code: `{entry['review_reason']}`")
    if detail.get("si_fields") and detail.get("bl_fields"):
        blank = [f for f in FIELDS if detail["si_fields"].get(f) in (None, BLANK)
                 or detail["bl_fields"].get(f) in (None, BLANK)]
        st.write("Fields blank or absent in a source document: " + (", ".join(blank) or "none"))
        show_field_table(detail, [])
    for label, key in (("SI text (readable)", "si_text"), ("BL text (readable)", "bl_text")):
        if detail.get(key):
            with st.expander(label, expanded=True):
                st.code(detail[key], language=None)
        else:
            st.caption(f"{label}: not available")


def show_detail(source: str, email_id: str, entry: dict) -> None:
    inbox = get_inbox(source)
    email = inbox.get(email_id)
    st.subheader(email["subject"])
    st.write(f"**From:** {email['from']}  \n**Category:** {entry['category']}  \n**Status:** {entry['status']}")
    with st.expander("Email body"):
        st.text(email["body"])
    if entry["category"] != "BL_COMPARISON":
        return
    if not os.environ.get("GEMINI_API_KEY"):
        st.caption("GEMINI_API_KEY not set - only cached extractions can be shown.")
    try:
        detail = get_detail(source, email_id)
    except Exception as e:
        st.error(f"Could not load the SI/BL fields (not cached and the API call failed): {e}")
        return
    if entry["status"] == "NEEDS_REVIEW":
        show_review(entry, detail)
    elif detail["si_fields"]:
        if entry["status"] == "MISMATCH":
            st.error("SI and BL differ on: " + ", ".join(entry["defect_fields"]))
            st.markdown("**SI vs BL comparison**")
        else:
            st.success("All 7 fields match.")
        show_field_table(detail, entry["defect_fields"])


def main() -> None:
    st.title("Shipping document verification")
    source = st.sidebar.text_input("Data source", os.environ.get("INBOX_SOURCE", "data"))
    if st.sidebar.button("Load output/submission.json"):
        if not SUBMISSION_PATH.exists():
            st.error("output/submission.json not found - run `python main.py` first.")
            return
        st.session_state["submission"] = json.loads(SUBMISSION_PATH.read_text(encoding="utf-8"))
    if "submission" not in st.session_state:
        st.info("Click **Load output/submission.json** in the sidebar.")
        return
    submission = st.session_state["submission"]
    show_summary(submission)
    inbox = get_inbox(source)
    df = build_table(submission, inbox)

    c1, c2, c3 = st.columns(3)
    cat = c1.multiselect("Category", sorted(df["category"].unique()))
    stat = c2.multiselect("Status", sorted(df["status"].unique()))
    text = c3.text_input("Search subject / id")
    if cat:
        df = df[df["category"].isin(cat)]
    if stat:
        df = df[df["status"].isin(stat)]
    if text:
        df = df[df["subject"].str.contains(text, case=False) | df["email_id"].str.contains(text, case=False)]

    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row")
    rows = event.selection.rows
    if rows:
        email_id = df.iloc[rows[0]]["email_id"]
        st.divider()
        show_detail(source, email_id, submission[email_id])
    else:
        st.caption("Click a row to see details.")


main()
