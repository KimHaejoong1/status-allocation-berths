# app.py
# BPTC "T" → "G" 선석배정 현황 시각화 (Streamlit + vis.js)
# Author: ChatGPT (정훈님용)
# License: MIT

import os
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from streamlit_timeline import st_timeline

from db import (
    init_db, SessionLocal, upsert_reference_data,
    create_version_with_assignments, list_versions, load_assignments_df
)
from crawler import fetch_bptc_t
from validate import snap_to_interval, validate_temporal_overlaps, validate_spatial_gap
from timeline_utils import df_to_timeline, timeline_to_df, make_timeline_options
from plot_gantt import render_gantt_g   # ✅ G형 시각화 함수 가져오기


# -----------------------------------------------------------
# 기본 설정
# -----------------------------------------------------------
st.set_page_config(page_title="BPTC 선석배정 Gantt", layout="wide")

# DB 초기화
engine, Base = init_db()
session = SessionLocal()
upsert_reference_data(session)

# -----------------------------------------------------------
# 사이드바
# -----------------------------------------------------------
st.sidebar.title("⚓ BPTC 선석배정 현황(T) → Gantt")

with st.sidebar:
    st.markdown("### 🔹 데이터 소스")
    btn_crawl = st.button("📡 크롤링 실행 (BPTC T)")
    uploaded_quantum = st.file_uploader("양자 결과 CSV 업로드(optional)", type=["csv"])

    st.markdown("---")
    st.markdown("### 🔹 버전 관리")
    versions = list_versions(session)
    version_labels = [
        f"{v['id'][:8]} · {v['source']} · {v['label']} · {v['created_at']:%m-%d %H:%M}"
        for v in versions
    ]
    idx_a = st.selectbox("좌측 버전 A 선택", list(range(len(versions))), format_func=lambda i: version_labels[i] if versions else "없음")
    idx_b = st.selectbox("우측 버전 B 선택", list(range(len(versions))), format_func=lambda i: version_labels[i] if versions else "없음")

    st.markdown("---")
    st.markdown("### 🔹 스코프(편집 범위)")
    today = datetime.now()
    date_from = st.date_input("시작 날짜", value=today.date())
    time_from = st.time_input("시작 시간", value=(today - timedelta(hours=6)).time())
    scope_from = datetime.combine(date_from, time_from)

    date_to = st.date_input("끝 날짜", value=today.date() + timedelta(days=1))
    time_to = st.time_input("끝 시간", value=(today + timedelta(hours=24)).time())
    scope_to = datetime.combine(date_to, time_to)

    scope_berths = st.text_input("선석 필터 (예: B1,B2)", value="")

    st.markdown("---")
    st.markdown("### 🔹 설정")
    snap_choice = st.radio("시간 스냅 단위", ["1h", "30m", "15m"], index=0, horizontal=True)
    min_gap_m = st.number_input("동시 계류 최소 이격(m)", min_value=0, value=30, step=5)

    st.markdown("---")
    do_undo = st.button("↩ 되돌리기 (Undo)", use_container_width=True)
    do_save = st.button("💾 저장 (새 버전)", type="primary", use_container_width=True)


# -----------------------------------------------------------
# 세션 상태 초기화
# -----------------------------------------------------------
if "history" not in st.session_state:
    st.session_state["history"] = []
if "working_df" not in st.session_state:
    st.session_state["working_df"] = pd.DataFrame()

# -----------------------------------------------------------
# 크롤링 버튼 동작
# -----------------------------------------------------------
if btn_crawl:
    with st.spinner("BPTC T 페이지 크롤링 중..."):
        try:
            df_t = fetch_bptc_t()
        except Exception as e:
            st.error(f"❌ 크롤링 실패: {e}")
            st.stop()

        # ✅ 컬럼명 정규화 (vessel, berth, eta, etd)
        df_t.columns = [c.strip().lower() for c in df_t.columns]
        rename_map = {
            "선명": "vessel", "모선명": "vessel", "vessel": "vessel",
            "선석": "berth", "berth": "berth",
            "접안(예정)일시": "eta", "입항예정일시": "eta", "eta": "eta",
            "출항(예정)일시": "etd", "출항예정일시": "etd", "출항일시": "etd", "etd": "etd",
        }
        for k, v in rename_map.items():
            if k in df_t.columns:
                df_t = df_t.rename(columns={k: v})

        required = ["vessel", "berth", "eta", "etd"]
        if not all(c in df_t.columns for c in required):
            st.error(f"⚠️ 크롤링 결과에 필수 컬럼 누락: {df_t.columns.tolist()}")
            st.stop()

        # datetime 변환
        for c in ["eta", "etd"]:
            df_t[c] = pd.to_datetime(df_t[c], errors="coerce")

        df_t = df_t.dropna(subset=required).reset_index(drop=True)
        if df_t.empty:
            st.warning("⚠️ 선박 데이터가 비어 있습니다.")
            st.stop()

        # DB 저장
        vid = create_version_with_assignments(session, df_t, source="crawler:bptc", label="BPTC T 크롤링")
        st.session_state["last_df"] = df_t  # ✅ G 시각화용
        st.success(f"✅ 크롤링 완료 — 새 버전 {vid[:8]} 생성 ({len(df_t)}건)")
        st.rerun()


# -----------------------------------------------------------
# G형 시각화 (선석배정 현황)
# -----------------------------------------------------------
st.markdown("---")
st.header("📊 선석배정 현황(G) 시각화")

colx, coly, colz = st.columns([1,1,1])
with colx:
    g_base = st.date_input("기준일", value=datetime.now().date())
with coly:
    g_days = st.slider("표시 일수", 3, 14, 7)
with colz:
    g_editable = st.toggle("드래그&드롭 편집", value=True)

# 표시할 데이터 결정
candidate_df = None
if "last_df" in st.session_state and not st.session_state["last_df"].empty:
    candidate_df = st.session_state["last_df"]
elif 'df_left' in locals() and not df_left.empty:
    candidate_df = df_left

if candidate_df is None or len(candidate_df) == 0:
    st.info("크롤링하거나 버전을 선택하면 Gantt가 표시됩니다.")
else:
    vdf, evt = render_gantt_g(
        candidate_df,
        base_date=pd.Timestamp(g_base),
        days=g_days,
        editable=g_editable,
        snap_choice=snap_choice,
        height="780px",
        key="gantt_main"
    )

    st.caption("Tip: 마우스로 **좌우 드래그**하면 가로 스크롤, **CTRL+휠**로 확대/축소할 수 있습니다.")

    if g_editable and evt:
        st.info("드래그 변경이 감지되었습니다. 아래 버튼으로 새 버전으로 저장할 수 있습니다.")
        if st.button("💾 Gantt 편집 내용 저장(새 버전)"):
            vid = create_version_with_assignments(session, vdf, source="user-edit:gantt", label=f"Gantt편집({snap_choice})")
            st.success(f"저장 완료 — 새 버전 {vid[:8]}")
            st.rerun()


# -----------------------------------------------------------
# 버전 불러오기 (A/B 비교용)
# -----------------------------------------------------------
if versions:
    df_left = load_assignments_df(session, versions[idx_a]["id"])
    df_right = load_assignments_df(session, versions[idx_b]["id"])
else:
    st.info("버전을 먼저 생성하세요 (크롤링 또는 CSV 업로드).")
    df_left = pd.DataFrame(columns=["vessel", "berth", "eta", "etd", "loa_m", "start_meter"])
    df_right = df_left.copy()


# -----------------------------------------------------------
# 범위 필터
# -----------------------------------------------------------
def in_scope(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "eta" not in df.columns or "etd" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    out = df[(df["eta"] < scope_to) & (df["etd"] > scope_from)].copy()
    if scope_berths.strip():
        keeps = [b.strip().upper() for b in scope_berths.split(",") if b.strip()]
        out = out[out["berth"].astype(str).str.upper().isin(keeps)]
    return out

left_scope = in_scope(df_left).reset_index(drop=True)
right_scope = in_scope(df_right).reset_index(drop=True)


# -----------------------------------------------------------
# 좌/우 비교 뷰 (T형 편집용)
# -----------------------------------------------------------
colA, colB = st.columns(2, gap="small")

with colA:
    st.subheader("🧭 A) 편집 대상")
    if st.session_state["working_df"].empty or set(st.session_state["working_df"].columns) != set(df_left.columns):
        st.session_state["working_df"] = left_scope.copy()

    itemsA, groupsA = df_to_timeline(st.session_state["working_df"], editable=True)
    optionsA = make_timeline_options(snap_choice, editable=True, start=scope_from, end=scope_to)
    timeline_eventA = st_timeline(itemsA, groupsA, optionsA, height="560px")

    if isinstance(timeline_eventA, dict) and "id" in timeline_eventA:
        st.session_state["history"].append(st.session_state["working_df"].copy())
        st.session_state["working_df"] = timeline_to_df(st.session_state["working_df"], timeline_eventA, snap_choice)

    with st.expander("자세히 보기 / LOA·start_meter 편집"):
        st.session_state["working_df"] = st.data_editor(
            st.session_state["working_df"],
            column_config={
                "eta": st.column_config.DatetimeColumn("입항(ETA)"),
                "etd": st.column_config.DatetimeColumn("출항(ETD)"),
                "loa_m": st.column_config.NumberColumn("LOA(m)", min_value=0, step=1),
                "start_meter": st.column_config.NumberColumn("시작 위치(m)", min_value=0, step=1),
            },
            width="stretch",
            num_rows="dynamic",
            key="editorA",
        )

    if not st.session_state["working_df"].empty:
        wdf = st.session_state["working_df"].copy()
        wdf["eta"] = wdf["eta"].map(lambda x: snap_to_interval(x, snap_choice))
        wdf["etd"] = wdf["etd"].map(lambda x: snap_to_interval(x, snap_choice))
        v1 = validate_temporal_overlaps(wdf)
        v2 = validate_spatial_gap(wdf, min_gap_m=min_gap_m)
        if v1 or v2:
            st.error("🚫 제약 위반:\n- " + "\n- ".join(v1 + v2))
        else:
            st.success("✅ 제약 위반 없음")

    if do_undo and st.session_state["history"]:
        st.session_state["working_df"] = st.session_state["history"].pop()

    if do_save:
        vid = create_version_with_assignments(session, st.session_state["working_df"], source="user-edit", label=f"수정본({snap_choice})")
        st.success(f"💾 저장 완료 — 새 버전 {vid[:8]}")
        st.session_state["history"].clear()
        st.rerun()

with colB:
    st.subheader("📊 B) 비교 대상 (읽기 전용)")
    itemsB, groupsB = df_to_timeline(right_scope, editable=False)
    optionsB = make_timeline_options(snap_choice, editable=False, start=scope_from, end=scope_to)
    _ = st_timeline(itemsB, groupsB, optionsB, height="560px")

st.caption("🔸 외부(BPTC) 시스템에는 쓰기 요청을 하지 않으며, 사내 DB 사본만 관리합니다.")
