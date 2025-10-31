# =========================
# ui/table.py
# =========================
import streamlit as st
import pandas as pd

# ---------------------------------------------------------
# 테이블 공통 표시
# ---------------------------------------------------------
def show_table(df: pd.DataFrame, title: str):
    st.subheader(title)
    st.dataframe(df, use_container_width=True, height=520)
