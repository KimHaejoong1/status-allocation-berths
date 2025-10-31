# =========================
# ui/validation.py
# =========================
import streamlit as st
import pandas as pd
from schema import validate_df

# ---------------------------------------------------------
# 유효성 표시
#  - visible=False 이면 아무것도 렌더하지 않음(데이터는 반환)
#  - location="본문(접기)" → 본문 expander에 상세
#  - location="사이드바(요약)" → 사이드바에 개수와 일부만
# ---------------------------------------------------------
def show_validation(name: str, df: pd.DataFrame, visible: bool = True, location: str = "본문(접기)"):
    probs = validate_df(df)

    if not visible:
        return probs

    if location == "사이드바(요약)":
        with st.sidebar:
            if probs:
                st.error(f"{name} 경고 {len(probs)}건")
                # 상위 10개만 미리보기
                preview = pd.DataFrame(probs, columns=["row_or_key", "field", "msg"]).head(10)
                st.dataframe(preview, height=220, use_container_width=True)
                st.caption("상세는 본문 탭의 정규화 테이블 아래에서 확인하세요.")
            else:
                st.success(f"{name} 검증 통과")
        return probs

    # 본문(접기)
    if probs:
        with st.expander(f"⚠ {name} 유효성 경고 {len(probs)}건 보기", expanded=False):
            st.dataframe(pd.DataFrame(probs, columns=["row_or_key", "field", "msg"]), height=240, use_container_width=True)
    else:
        st.success(f"{name} 검증 통과")
    return probs
