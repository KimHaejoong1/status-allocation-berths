# app.py — 부산항 선석배정 현황 · 업로드/크롤러 병행 · 편집/시각화
# -----------------------------------------------------------------------------
# 핵심 요약
# - 두 데이터 세트(크롤러, 업로드)를 동시에 관리하고 비교(표: 좌/우, 그래프: 위/아래).
# - 시각화는 "정규화 데이터" 기준, 화면엔 원본 테이블만 노출(정규화 테이블은 숨김).
# - 그래프 편집(드래그/WASD)은 "편집 대상(active_source)"에만 적용.
# - 저장 한 번으로 그래프 즉시 반영(st.rerun).
# - 조회/불러오기 직후에는 테이블만 보이고(시각화 비노출), "시각화하기"나 "저장"을 누르면 보이도록(show_viz).
# -----------------------------------------------------------------------------

import streamlit as st
import pandas as pd

from crawler import collect_berth_info
from schema import normalize_df, ensure_row_id, sync_raw_with_norm
from ui.sidebar import build_sidebar
from ui.validation import show_validation
from ui.table import show_table
from ui.viz.origin import render_origin_view, render_origin_view_static


# -----------------------------------------------------------------------------
# 페이지/헤더
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="부산항 선석배정 현황(사이트) · 편집/시각화",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("⚓ 부산항 선석배정 현황 — 사이트 데이터 업로드 · 검증 · 시각화")


# -----------------------------------------------------------------------------
# 유틸 함수: 세션 키 보장/초기화
# -----------------------------------------------------------------------------
def _ensure_ss(key: str, default):
    """
    세션 상태(st.session_state)에 키가 없거나 None일 경우, 기본값으로 초기화합니다.
    - 모든 세션 키 초기화에 사용 (DataFrame/리스트/부울 등)
    """
    if key not in st.session_state or st.session_state[key] is None:
        st.session_state[key] = default


def _init_all_session_keys():
    """
    본 앱에서 사용하는 모든 세션 키를 한 번에 초기화합니다.
    - 크롤러/업로드: 원본(raw), 정규화(df), 편집버퍼(edit_df_*), 스냅샷(snapshot_*), 되돌리기(undo_*), 로그(logs_*)
    - 전역 플래그: show_viz(시각화 보이기), active_source(편집 대상)
    """
    defaults = {
        # 크롤러 세트
        "crawl_raw": pd.DataFrame(),
        "crawl_df": pd.DataFrame(),
        "edit_df_crawl": pd.DataFrame(),
        "snapshot_crawl": pd.DataFrame(),
        "undo_df_crawl": None,
        "logs_crawl": [],
        # 업로드 세트
        "upload_raw": pd.DataFrame(),
        "upload_df": pd.DataFrame(),
        "edit_df_upload": pd.DataFrame(),
        "snapshot_upload": pd.DataFrame(),
        "undo_df_upload": None,
        "logs_upload": [],
        # 전역
        "show_viz": False,
        "active_source": "crawl",  # 기본: 크롤러
    }
    for k, v in defaults.items():
        _ensure_ss(k, v)


# -----------------------------------------------------------------------------
# 핸들러: 데이터 획득(크롤러/업로드)
# -----------------------------------------------------------------------------
def handle_crawl_fetch(add_dims: bool):
    """
    [크롤러 조회] 버튼 클릭 시 호출됩니다.
    - 원본 수집 → ensure_row_id → normalize_df → 각 세트(crawl_*)에 저장
    - 시각화는 닫고(테이블만 보이게) show_viz=False
    """
    with st.spinner("크롤러로 데이터를 가져오는 중입니다..."):
        raw = collect_berth_info(add_bp=True, add_dims=add_dims)
        raw = ensure_row_id(raw)
        norm = ensure_row_id(normalize_df(raw))

        st.session_state["crawl_raw"] = raw.copy()
        st.session_state["crawl_df"] = norm.copy()
        st.session_state["edit_df_crawl"] = norm.copy()
        st.session_state["snapshot_crawl"] = norm.copy()
        st.session_state["undo_df_crawl"] = None
        st.session_state["logs_crawl"] = []

        st.session_state["active_source"] = "crawl"
        st.session_state["show_viz"] = False  # 조회 직후엔 테이블만
        st.success(f"조회 완료: 원본 {len(raw)}건 / 정규화 {len(norm)}건")


def handle_file_load(upload_file):
    """
    [불러오기] 버튼 클릭 시 호출됩니다.
    - 업로드 원본 로드(CSV/XLSX) → ensure_row_id → normalize_df → 각 세트(upload_*)에 저장
    - 시각화는 닫고(테이블만 보이게) show_viz=False
    """
    if upload_file is None:
        st.warning("먼저 CSV/XLSX 파일을 업로드하세요.")
        return

    with st.spinner("파일을 불러오는 중입니다..."):
        if upload_file.name.endswith(".xlsx"):
            raw = pd.read_excel(upload_file)
        else:
            raw = pd.read_csv(upload_file)

        raw = ensure_row_id(raw)
        norm = ensure_row_id(normalize_df(raw))

        st.session_state["upload_raw"] = raw.copy()
        st.session_state["upload_df"] = norm.copy()
        st.session_state["edit_df_upload"] = norm.copy()
        st.session_state["snapshot_upload"] = norm.copy()
        st.session_state["undo_df_upload"] = None
        st.session_state["logs_upload"] = []

        st.session_state["show_viz"] = False  # 불러오기 직후엔 테이블만
        st.success(f"파일 불러오기 완료: 원본 {len(raw)}건 / 정규화 {len(norm)}건")


# -----------------------------------------------------------------------------
# 편집 컨텍스트 바인딩/해제
# -----------------------------------------------------------------------------
def _bind_edit_context(source: str):
    """
    편집 대상 세트(source: 'crawl'|'upload')를 공용 키로 바인딩합니다.
    - render_origin_view(인터랙티브 시각화)는 edit_df / orig_df_snapshot / undo_df / edit_logs 키를 사용하므로,
      선택된 세트의 버퍼/스냅샷/되돌리기/로그를 공용 키로 매핑해줍니다.
    """
    if source == "crawl":
        st.session_state["edit_df"] = st.session_state["edit_df_crawl"].copy()
        st.session_state["orig_df_snapshot"] = st.session_state["snapshot_crawl"].copy()
        st.session_state["undo_df"] = st.session_state["undo_df_crawl"]
        st.session_state["edit_logs"] = st.session_state["logs_crawl"]
    else:
        st.session_state["edit_df"] = st.session_state["edit_df_upload"].copy()
        st.session_state["orig_df_snapshot"] = st.session_state["snapshot_upload"].copy()
        st.session_state["undo_df"] = st.session_state["undo_df_upload"]
        st.session_state["edit_logs"] = st.session_state["logs_upload"]


def _persist_edit_context(source: str):
    """
    공용 편집 키를 다시 해당 세트로 되돌려 저장합니다.
    - 인터랙티브 시각화에서 사용자가 이동/드래그/키 조작을 하면 edit_df 등이 갱신되므로,
      그 결과를 세트별 키(edit_df_* / snapshot_* / undo_df_* / logs_*)로 되돌려 반영합니다.
    """
    if source == "crawl":
        st.session_state["edit_df_crawl"] = st.session_state["edit_df"].copy()
        st.session_state["snapshot_crawl"] = st.session_state["orig_df_snapshot"].copy()
        st.session_state["undo_df_crawl"] = st.session_state["undo_df"]
        st.session_state["logs_crawl"] = st.session_state["edit_logs"]
    else:
        st.session_state["edit_df_upload"] = st.session_state["edit_df"].copy()
        st.session_state["snapshot_upload"] = st.session_state["orig_df_snapshot"].copy()
        st.session_state["undo_df_upload"] = st.session_state["undo_df"]
        st.session_state["logs_upload"] = st.session_state["edit_logs"]


# -----------------------------------------------------------------------------
# 사이드바 액션 처리: 시각화/되돌리기/저장
# -----------------------------------------------------------------------------
def handle_sidebar_actions(ctrl: dict):
    """
    사이드바의 '시각화하기/되돌리기/저장' 액션을 처리합니다.
    - 시각화하기: show_viz=True
    - 되돌리기(1회): 편집 대상 세트의 undo 버퍼 적용 + 로그 1건 제거 + 즉시 리렌더
    - 저장: 편집 대상 세트의 edit_df → df로 반영, 원본 raw에도 sync, 스냅샷/로그/undo 정리, show_viz=True, 즉시 리렌더
    """
    # 시각화 열기
    if ctrl["run_viz_crawl"] or ctrl["run_viz"]:
        st.session_state["show_viz"] = True

    # 되돌리기(편집 대상)
    if ctrl["cmd_undo"]:
        src = ctrl["active_source"]
        if src == "crawl":
            buf = st.session_state.get("undo_df_crawl")
            if buf is not None and not getattr(buf, "empty", True):
                st.session_state["edit_df_crawl"] = buf.copy()
                st.session_state["undo_df_crawl"] = None
                if st.session_state["logs_crawl"]:
                    st.session_state["logs_crawl"].pop()
                st.info("되돌리기 완료(크롤러 데이터).")
                st.rerun()
        else:
            buf = st.session_state.get("undo_df_upload")
            if buf is not None and not getattr(buf, "empty", True):
                st.session_state["edit_df_upload"] = buf.copy()
                st.session_state["undo_df_upload"] = None
                if st.session_state["logs_upload"]:
                    st.session_state["logs_upload"].pop()
                st.info("되돌리기 완료(업로드 데이터).")
                st.rerun()

    # 저장(편집 대상)
    if ctrl["cmd_save"]:
        src = ctrl["active_source"]
        if src == "crawl":
            # 정규화 편집본 → 세트 갱신
            st.session_state["crawl_df"] = st.session_state["edit_df_crawl"].copy()
            # 원본 동기화
            if not st.session_state["crawl_raw"].empty and "row_id" in st.session_state["crawl_raw"].columns:
                st.session_state["crawl_raw"] = sync_raw_with_norm(
                    st.session_state["crawl_raw"], st.session_state["crawl_df"]
                )
            # 스냅샷/로그/되돌리기 초기화
            st.session_state["snapshot_crawl"] = st.session_state["crawl_df"].copy()
            st.session_state["logs_crawl"] = []
            st.session_state["undo_df_crawl"] = None
            st.session_state["show_viz"] = True
            st.success("저장 완료(크롤러 세트 반영).")
            st.rerun()
        else:
            st.session_state["upload_df"] = st.session_state["edit_df_upload"].copy()
            if not st.session_state["upload_raw"].empty and "row_id" in st.session_state["upload_raw"].columns:
                st.session_state["upload_raw"] = sync_raw_with_norm(
                    st.session_state["upload_raw"], st.session_state["upload_df"]
                )
            st.session_state["snapshot_upload"] = st.session_state["upload_df"].copy()
            st.session_state["logs_upload"] = []
            st.session_state["undo_df_upload"] = None
            st.session_state["show_viz"] = True
            st.success("저장 완료(업로드 세트 반영).")
            st.rerun()


# -----------------------------------------------------------------------------
# 시각화/검증 블록
# -----------------------------------------------------------------------------
def render_visualizations_and_validation(ctrl: dict):
    """
    상단 시각화 블록과 검증(정규화 DF 기준)을 그립니다.
    - show_viz=True일 때만 시각화 노출
    - 두 세트가 있으면 [위: 편집 대상(인터랙티브), 아래: 읽기 전용]으로 배치
    - 검증은 편집 대상 세트의 정규화 DF 기준으로 사이드바/본문 요약만 표시(테이블은 숨김)
    """
    has_crawl = not st.session_state["crawl_df"].empty
    has_upload = not st.session_state["upload_df"].empty

    if not st.session_state["show_viz"]:
        return

    if not has_crawl and not has_upload:
        st.warning("시각화할 데이터가 없습니다. 먼저 ‘조회하기/불러오기’를 실행하세요.")
        return

    # 검증(정규화 DF 기준) — 편집 대상만
    if ctrl["show_validation"]:
        src = ctrl["active_source"]
        df_for_validation = st.session_state["crawl_df"] if src == "crawl" else st.session_state["upload_df"]
        if not df_for_validation.empty:
            show_validation("정규화 검증", df_for_validation, visible=True, location=ctrl["val_location"])

    # 시각화(위/아래 또는 단일)
    if has_crawl and has_upload:
        st.subheader("📊 비교 시각화 (위: 편집 대상, 아래: 읽기 전용)")
        src = ctrl["active_source"]
        if src == "crawl":
            _bind_edit_context("crawl")
            render_origin_view(st.session_state["crawl_df"])    # 인터랙티브
            _persist_edit_context("crawl")
            st.markdown("---")
            render_origin_view_static(st.session_state["upload_df"], title_prefix="업로드")
        else:
            _bind_edit_context("upload")
            render_origin_view(st.session_state["upload_df"])   # 인터랙티브
            _persist_edit_context("upload")
            st.markdown("---")
            render_origin_view_static(st.session_state["crawl_df"], title_prefix="크롤러")
    else:
        # 단일 세트만 존재하는 경우
        if has_crawl:
            _bind_edit_context("crawl")
            render_origin_view(st.session_state["crawl_df"])
            _persist_edit_context("crawl")
        else:
            _bind_edit_context("upload")
            render_origin_view(st.session_state["upload_df"])
            _persist_edit_context("upload")


# -----------------------------------------------------------------------------
# 원본 테이블 블록(좌/우 비교, 편집 대상만 수정 가능)
# -----------------------------------------------------------------------------
def _render_raw_panel(source_key: str, label: str, editable: bool):
    """
    원본 테이블 1패널을 렌더링합니다.
    - editable=True (편집 대상)일 때만 '수정하기/되돌리기/저장(표→그래프)' 버튼 노출
    - 저장 시: 원본 → 정규화 갱신 → 그래프/편집버퍼/스냅샷 갱신 → 즉시 리렌더
    """
    df_raw = st.session_state[f"{source_key}_raw"]
    if df_raw.empty:
        st.info(f"{label} 원본 데이터가 없습니다.")
        return

    key_prefix = f"raw_{source_key}"
    if f"{key_prefix}_mode" not in st.session_state:
        st.session_state[f"{key_prefix}_mode"] = False
    if f"{key_prefix}_buffer" not in st.session_state:
        st.session_state[f"{key_prefix}_buffer"] = df_raw.copy()
    if f"{key_prefix}_snapshot" not in st.session_state:
        st.session_state[f"{key_prefix}_snapshot"] = df_raw.copy()

    if editable:
        cols = st.columns([1, 1, 1])
        with cols[0]:
            if st.button("수정하기", disabled=st.session_state[f"{key_prefix}_mode"], use_container_width=True, key=f"editbtn-{source_key}"):
                st.session_state[f"{key_prefix}_mode"] = True
                st.session_state[f"{key_prefix}_buffer"] = df_raw.copy()
                st.session_state[f"{key_prefix}_snapshot"] = df_raw.copy()
                # 반대편 편집 모드 강제 해제(동시 편집 방지)
                other = "upload" if source_key == "crawl" else "crawl"
                st.session_state[f"raw_{other}_mode"] = False

        with cols[1]:
            undo_btn = st.button("되돌리기(표)", use_container_width=True, disabled=not st.session_state[f"{key_prefix}_mode"], key=f"undobtn-{source_key}")
        with cols[2]:
            save_btn = st.button("저장(표→그래프)", type="primary", use_container_width=True, disabled=not st.session_state[f"{key_prefix}_mode"], key=f"savebtn-{source_key}")

        if st.session_state[f"{key_prefix}_mode"]:
            st.warning("현재 **원본 테이블 편집 모드**입니다. 그래프 편집은 잠시 중지하세요.")
            edited = st.data_editor(st.session_state[f"{key_prefix}_buffer"], use_container_width=True, height=360, key=f"editor-{source_key}")

            if undo_btn:
                st.session_state[f"{key_prefix}_buffer"] = st.session_state[f"{key_prefix}_snapshot"].copy()
                st.info("표 되돌리기 완료.")

            if save_btn:
                # 원본 반영 → 정규화 갱신 → 그래프/편집버퍼 갱신
                st.session_state[f"{source_key}_raw"] = edited.copy()
                new_norm = ensure_row_id(normalize_df(st.session_state[f"{source_key}_raw"]))
                st.session_state[f"{source_key}_df"] = new_norm.copy()
                st.session_state[f"edit_df_{source_key}"] = new_norm.copy()
                st.session_state[f"snapshot_{source_key}"] = new_norm.copy()
                # 편집/되돌리기/로그 초기화
                st.session_state[f"undo_df_{source_key}"] = None
                st.session_state[f"logs_{source_key}"] = []
                # 저장하면 시각화 열고, 즉시 반영
                st.session_state["show_viz"] = True
                st.session_state[f"{key_prefix}_mode"] = False
                st.success(f"{label} 표 저장 완료(그래프 갱신).")
                st.rerun()
        else:
            show_table(df_raw, f"📋 {label} 원본")
    else:
        # 읽기 전용 패널
        show_table(df_raw, f"📋 {label} 원본 (읽기 전용)")


def render_raw_tables(ctrl: dict):
    """
    원본 테이블 UI를 그립니다.
    - 두 세트가 있으면 좌/우 반반 비교(편집 대상만 수정 가능)
    - 하나만 있으면 해당 세트만 보여줌(수정 가능)
    """
    has_crawl = not st.session_state["crawl_df"].empty
    has_upload = not st.session_state["upload_df"].empty

    if has_crawl and has_upload:
        st.subheader("📄 원본 데이터 비교 (좌: 크롤러 / 우: 업로드)")
        c1, c2 = st.columns(2)
        with c1:
            _render_raw_panel("crawl", "크롤러", editable=(ctrl["active_source"] == "crawl"))
        with c2:
            _render_raw_panel("upload", "업로드", editable=(ctrl["active_source"] == "upload"))
    elif has_crawl:
        st.subheader("📄 원본 데이터(크롤러)")
        _render_raw_panel("crawl", "크롤러", editable=True)
    elif has_upload:
        st.subheader("📄 원본 데이터(업로드)")
        _render_raw_panel("upload", "업로드", editable=True)
    else:
        st.info("좌측 사이드바에서 ‘조회하기’ 또는 ‘불러오기’를 먼저 실행하세요.")


# -----------------------------------------------------------------------------
# 실행 흐름
# -----------------------------------------------------------------------------
def main():
    """
    앱 메인 실행 함수.
    1) 사이드바 렌더 및 컨트롤 수집
    2) 세션 키 초기화
    3) 조회/불러오기 처리
    4) 사이드바 액션(시각화/되돌리기/저장) 처리
    5) 시각화(위/아래 비교) + 검증 요약
    6) 원본 테이블(좌/우 비교) 렌더
    """
    ctrl = build_sidebar()
    _init_all_session_keys()

    # A) 조회/불러오기
    if ctrl["run_crawl"]:
        try:
            handle_crawl_fetch(add_dims=ctrl["add_dims"])
        except Exception as e:
            st.error(f"오류: {e}")

    if ctrl["run_load"]:
        try:
            handle_file_load(ctrl["origin_file"])
        except Exception as e:
            st.error(f"파일 불러오기 실패: {e}")

    # B) 사이드바 액션 (시각화/되돌리기/저장)
    handle_sidebar_actions(ctrl)

    # C) 상단 시각화 + 검증
    render_visualizations_and_validation(ctrl)

    # D) 원본 테이블(좌/우 비교)
    render_raw_tables(ctrl)


# 진입점
if __name__ == "__main__":
    main()
