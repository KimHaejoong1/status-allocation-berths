# =========================
# ui/sidebar.py
# =========================
import streamlit as st

def _init_state():
    if "show_direct" not in st.session_state:
        st.session_state["show_direct"] = False
    if "active_source" not in st.session_state:
        st.session_state["active_source"] = "crawl"  # 기본은 크롤러
# ---------------------------------------------------------
# 사이드 바 설정
# ---------------------------------------------------------
def build_sidebar():
    _init_state()
    with st.sidebar:
        # ---------------------------------------------------------
        # 상단 타이틀/설정
        # ---------------------------------------------------------
        st.header("설정")
        st.caption("A) 크롤러로 바로 조회 · 시각화  /  B) 파일 업로드 후 불러오기 · 시각화")

        # ---------------------------------------------------------
        # (A) 조회/시각화 — 크롤러 사용
        # ---------------------------------------------------------
        st.subheader("A) 크롤러 조회/시각화")
        add_dims = st.toggle("VesselFinder 길이/폭 포함 (느릴 수 있음)", value=False)
        col = st.columns(2)
        with col[0]:
            run_crawl = st.button("조회하기 🚢", use_container_width=True)
        with col[1]:
            run_viz_crawl = st.button("시각화 하기 📊", use_container_width=True)

        # ---------------------------------------------------------
        # (B) 토글 버튼: '직접 파일 넣기' 섹션 열기/닫기
        # ---------------------------------------------------------
        st.divider()
        st.subheader("B) 직접 파일 넣기")
        open_direct = st.button("직접 파일 넣기 ⤵", use_container_width=True)
        if open_direct:
            st.session_state["show_direct"] = True

        origin_file = None
        run_load = False
        run_viz = False
        if st.session_state["show_direct"]:
            st.markdown("---")
            st.subheader("파일 업로드")
            origin_file = st.file_uploader("양자 데이터 업로드 (CSV/XLSX)", type=["csv", "xlsx"])
            col1, col2 = st.columns(2)
            with col1:
                run_load = st.button("불러오기 📥", use_container_width=True)
            with col2:
                run_viz = st.button("시각화 📊", use_container_width=True)
            st.caption("※ 닫으려면 아래 버튼을 클릭하세요.")
            if st.button("닫기 ⤴", use_container_width=True):
                st.session_state["show_direct"] = False


        # ---------------------------------------------------------
        # 편집/저장 컨트롤 (유효성 위쪽)
        # ---------------------------------------------------------
        st.divider()
        st.subheader("편집 · 저장")
        colx = st.columns([1,1])
        with colx[0]:
            cmd_undo = st.button("되돌리기(1회)", use_container_width=True)
        with colx[1]:
            cmd_save = st.button("저장", use_container_width=True, type="primary")
        # ✅ 두 세트가 모두 있을 때만 '편집 대상' 노출
        has_crawl  = bool(st.session_state.get("crawl_df") is not None and not getattr(st.session_state.get("crawl_df"), "empty", True))
        has_upload = bool(st.session_state.get("upload_df") is not None and not getattr(st.session_state.get("upload_df"), "empty", True))
        active_source = st.session_state.get("active_source", "crawl")
        if has_crawl and has_upload:
            src_label = st.radio(
                "편집 대상 데이터", options=["크롤러", "업로드"],
                index=(0 if active_source=="crawl" else 1),
                horizontal=True
            )
            active_source = "crawl" if src_label=="크롤러" else "upload"
            st.session_state["active_source"] = active_source

        # ---------------------------------------------------------
        # 유효성 경고 표시 옵션
        # ---------------------------------------------------------
        st.divider()
        st.subheader("유효성 경고 표시")
        show_validation = st.toggle("유효성 경고 보기", value=True)
        val_location = st.radio("표시 위치", options=["본문(접기)", "사이드바(요약)"],
                                index=0, horizontal=True, disabled=not show_validation)
        
        # ---------------------------------------------------------
        # 도움말
        # ---------------------------------------------------------
        st.divider()
        st.subheader("도움말")
        st.markdown(
            "- 두 세트가 있을 때는 **편집 대상만** 드래그&키 이동 가능(다른 하나는 읽기 전용).\n"
            "- 그래프 편집과 원본 테이블 편집은 **동시에 하지 마세요** (둘 중 하나만).\n"
            "- **저장**: 원본 테이블 값 변경\n"
            "- **초기화는 ‘조회하기’로** 새로 받아오면 원본으로 돌아갑니다."
            
        )

    # 컨트롤 값 반환
    return {
        "add_dims": add_dims,
        "run_crawl": run_crawl,
        "run_viz_crawl": run_viz_crawl,
        "origin_file": origin_file,
        "run_load": run_load,
        "run_viz": run_viz,
        "cmd_undo": cmd_undo,
        "cmd_save": cmd_save,
        "show_validation": show_validation,
        "val_location": val_location,
        "active_source": active_source,   # ✅ 추가
    }
