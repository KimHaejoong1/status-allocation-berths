# =========================
# ui/viz/origin.py
# =========================
import json
import pandas as pd
import streamlit as st
import math  # ✅ 추가
from string import Template     # ✅ f-string 대신 사용

from streamlit import components
from streamlit_js_eval import streamlit_js_eval
from ui.viz.common import render_timeline_week, period_str_kr
from schema import snap_time_5min, snap_y_30m, MIN_CLEARANCE_M, validate_df

# ---- 읽기전용 그리기 함수-----
def _plotly_scroll(fig_html: str, height: int = 600, min_width_px: int = 2400):
    wrapper = f"""
    <div style="width:100%; overflow-x:auto; padding-bottom:8px;">
      <div style="width: {min_width_px}px;">
        {fig_html}
      </div>
    </div>
    """
    components.v1.html(wrapper, height=height+60, scrolling=True)

def render_origin_view_static(df_origin: pd.DataFrame, title_prefix: str = ""):
    """읽기 전용(드래그/키 없음) — 위/아래 비교 배치용"""
    st.subheader(f"📊 {title_prefix} 읽기 전용 타임라인 (SND / GAM)")
    tab_snd, tab_gam = st.tabs(["신선대 SND", "감만 GAM"])

    from ui.viz.common import render_timeline_week, period_str_kr

    def _one(terminal: str):
        df_t = df_origin[df_origin["terminal"] == terminal].reset_index(drop=True)
        if df_t.empty:
            st.info(f"{terminal} 데이터가 없습니다.")
            return
        fig, (x0, x1) = render_timeline_week(df_t, terminal=terminal, title="")
        fig.update_layout(title=f"{title_prefix} {terminal} — {period_str_kr(x0, x1)}")
        html = fig.to_html(include_plotlyjs="cdn", full_html=False)
        _plotly_scroll(html, height=600, min_width_px=2400)

    with tab_snd: _one("SND")
    with tab_gam: _one("GAM")

# ---------- 내부 상태 유틸 ----------
def _init_edit_buffers(df_norm: pd.DataFrame):
    if "edit_df" not in st.session_state:
        st.session_state["edit_df"] = df_norm.copy()
    if "orig_df_snapshot" not in st.session_state:
        st.session_state["orig_df_snapshot"] = df_norm.copy()
    if "undo_df" not in st.session_state:
        st.session_state["undo_df"] = None
    if "selected_row_id" not in st.session_state:
        st.session_state["selected_row_id"] = None
    if "edit_logs" not in st.session_state:
        st.session_state["edit_logs"] = []

def _append_log(before, after):
    st.session_state["edit_logs"].append({
        "row_id": before.get("row_id"),
        "vessel": before.get("vessel",""),
        "voyage": before.get("voyage",""),
        "terminal": before.get("terminal",""),
        "berth": before.get("berth",""),
        "start_before": before.get("start"),
        "end_before": before.get("end"),
        "f_before": before.get("f"),
        "e_before": before.get("e"),
        "start_after": after.get("start"),
        "end_after": after.get("end"),
        "f_after": after.get("f"),
        "e_after": after.get("e"),
        "ts": pd.Timestamp.now()
    })


# ---------- 이동 스냅(5분/30m) ----------
def _move_time_5min(row: pd.Series, minutes: int) -> dict:
    s = snap_time_5min(row["start"] + pd.Timedelta(minutes=minutes))
    e = snap_time_5min(row["end"]   + pd.Timedelta(minutes=minutes))
    return {"start": s, "end": e}

def _move_y_30m(row: pd.Series, dy: float) -> dict:
    f0, e0 = float(row.get("f",0)), float(row.get("e",0))
    L = e0 - f0
    mid = (f0 + e0) / 2.0
    new_mid = snap_y_30m(mid + dy)
    return {"f": new_mid - abs(L)/2, "e": new_mid + abs(L)/2}

def _is_finite_num(x) -> bool:
    try:
        v = float(x)
        return not (math.isnan(v) or math.isinf(v))
    except Exception:
        return False

def _ts_equal(a, b) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return pd.Timestamp(a).value == pd.Timestamp(b).value

def _num_equal(a, b, eps=1e-6) -> bool:
    if not _is_finite_num(a) and not _is_finite_num(b):
        return True
    if not _is_finite_num(a) or not _is_finite_num(b):
        return False
    return abs(float(a) - float(b)) < eps

def _apply_move(df: pd.DataFrame, row_id: int, dmin=0, dy=0.0) -> pd.DataFrame:
    out = df.copy()
    idx_arr = out.index[out["row_id"] == row_id]
    if len(idx_arr) == 0:
        return out
    idx = idx_arr[0]
    row = out.loc[idx]

    # 기존 값
    s0, e0 = row.get("start"), row.get("end")
    f0, e1 = row.get("f"), row.get("e")

    # 후보 값(초기엔 기존값)
    s1, e2 = s0, e0
    f1, e3 = f0, e1

    changed = False

    # 시간 이동 (start/end가 유효할 때만)
    if dmin != 0 and (pd.notna(s0) and pd.notna(e0)):
        s1 = snap_time_5min(pd.to_datetime(s0) + pd.Timedelta(minutes=dmin))
        e2 = snap_time_5min(pd.to_datetime(e0) + pd.Timedelta(minutes=dmin))
        if (not _ts_equal(s0, s1)) or (not _ts_equal(e0, e2)):
            changed = True

    # 세로 이동 (f/e가 유효할 때만)
    if dy != 0 and _is_finite_num(f0) and _is_finite_num(e1):
        L = float(e1) - float(f0)
        if _is_finite_num(L) and abs(L) > 0:
            mid = (float(f0) + float(e1)) / 2.0
            new_mid = snap_y_30m(mid + float(dy))
            f1 = new_mid - abs(L) / 2.0
            e3 = new_mid + abs(L) / 2.0
            if (not _num_equal(f0, f1)) or (not _num_equal(e1, e3)):
                changed = True

    # 실제 변화 없으면 그대로 반환(로그 없음)
    if not changed:
        return out

    before = dict(row)
    out.at[idx, "start"] = s1
    out.at[idx, "end"] = e2
    out.at[idx, "f"] = f1
    out.at[idx, "e"] = e3
    after = dict(out.loc[idx])

    _append_log(before, after)       # ✅ 진짜 바뀐 경우에만
    st.session_state["undo_df"] = df.copy()
    return out

# ---------- HTML wrapper: (키, 클릭) 수집 ----------
def _plotly_scroll_interactive(fig_html: str, terminal: str, height: int = 600, min_width_px: int = 2400):
    key_ns = "viz_key"
    click_ns = f"viz_click_{terminal}"
    drag_ns = f"viz_drag_{terminal}"

    tpl = Template("""
    <div style="width:100%; overflow-x:auto; padding-bottom:8px;">
      <style>
        .modebar, .modebar-container { left: 8px !important; right: auto !important; top: 6px !important; }
        .modebar { background: rgba(255,255,255,0.6); border-radius: 6px; }
      </style>
      <div class="plot-wrap" style="width: ${minw}px;">
        ${html}
      </div>
      <script>
      (function(){
        function setLS(k,v){
          try{ localStorage.setItem(k,v); }catch(_){}
          try{ window.parent && window.parent.localStorage && window.parent.localStorage.setItem(k,v); }catch(_){}
          try{ window.top && window.top.localStorage && window.top.localStorage.setItem(k,v); }catch(_){}
        }
        function removeLS(k){
          try{ localStorage.removeItem(k); }catch(_){}
          try{ window.parent && window.parent.localStorage && window.parent.localStorage.removeItem(k); }catch(_){}
          try{ window.top && window.top.localStorage && window.top.localStorage.removeItem(k); }catch(_){}
        }

        let lastRowId = null;
        let dragState = { active:false, rowId:null, sx:0, sy:0 };

        function bindPlot(gd){
          if (!gd || gd.__bound) return;
          gd.__bound = true;

          // 클릭(선택)
          gd.on('plotly_click', function(data){
            try{
              const p = data && data.points && data.points[0];
              if (!p) return;
              const ev = data.event || {};
              lastRowId = (p.customdata ?? null);   // ✅ 클릭만 해도 대상 고정
              const payload = {
                x: p.x, y: p.y,
                row_id: (p.customdata ?? null),
                shift: !!ev.shiftKey
              };
              setLS('${click}', JSON.stringify(payload));
            }catch(e){}
          });

          // hover로 현재 row_id 추적
          gd.on('plotly_hover', function(data){
            try{
              const p = data && data.points && data.points[0];
              if (!p) return;
              if (p.customdata !== undefined && p.customdata !== null) {
                lastRowId = p.customdata;
              }
            }catch(e){}
          });

          // 실제 드래그 바인딩
          const plot = gd.querySelector('.cartesianlayer .plot');
          if (!plot || plot.__dragBound) return;
          plot.__dragBound = true;

          plot.addEventListener('mousedown', function(ev){
            if (lastRowId === null) return;   // 라벨 위가 아니면 무시
            dragState.active = true;
            dragState.rowId = lastRowId;
            dragState.sx = ev.clientX;
            dragState.sy = ev.clientY;
          });

          window.addEventListener('mouseup', function(ev){
            if (!dragState.active) return;
            dragState.active = false;

            // 축/플롯 영역 가져오기
            try{
              const rect = plot.getBoundingClientRect();
              const dx = ev.clientX - dragState.sx;
              const dy = ev.clientY - dragState.sy;

              // x(시간) 스케일: 분/픽셀
              const xr = (gd._fullLayout && gd._fullLayout.xaxis && gd._fullLayout.xaxis.range) ? gd._fullLayout.xaxis.range : null;
              const yr = (gd._fullLayout && gd._fullLayout.yaxis && gd._fullLayout.yaxis.range) ? gd._fullLayout.yaxis.range : null;

              if (!xr || !yr || !rect.width || !rect.height) return;

              // Plotly는 x축이 datetime일 때 range가 Date/숫자(ms) 혼용 → ms로 환산
              const t0 = (new Date(xr[0])).getTime ? (new Date(xr[0])).getTime() : Number(xr[0]);
              const t1 = (new Date(xr[1])).getTime ? (new Date(xr[1])).getTime() : Number(xr[1]);
              const msSpan = Math.abs(t1 - t0);
              const minPerPx = (msSpan / 60000.0) / rect.width;

              // y축은 [ymax, 0] (반전). span은 절대값으로
              const y0 = Number(yr[0]), y1 = Number(yr[1]);
              const mSpan = Math.abs(y0 - y1);
              const mPerPx = mSpan / rect.height;

              // 픽셀 이동량 → 데이터 이동량
              let dmin = Math.round((dx * minPerPx) / 5) * 5;    // 5분 스냅
              let dym  = Math.round((dy * mPerPx) / 30) * 30;    // 30m 스냅 (아래로 끌면 +)

              if (dmin !== 0 || dym !== 0) {
                setLS('${drag}', JSON.stringify({ row_id: dragState.rowId, dmin: dmin, dy: dym }));
                setTimeout(function(){ removeLS('${drag}'); }, 1000);
              }
            }catch(e){}
          });
        }

        (function waitPlot(n){
          const root = document.currentScript.parentElement;
          const gd = root.querySelector('.js-plotly-plot');
          if (gd && gd.data && gd.data.length){
            bindPlot(gd);
            gd.on('plotly_afterplot', ()=>bindPlot(gd));
          } else {
            if (n < 80) setTimeout(()=>waitPlot(n+1), 150);
          }
        })(0);

        if (!window.__vizKeyHandler){
          window.__vizKeyHandler = function(e){
            const k = e.key;
            const ok = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','a','d','w','s','A','D','W','S','Escape'];
            if (ok.indexOf(k) >= 0){ 
              try{ localStorage.setItem('viz_key', k); }catch(_){}
              try{ window.parent && window.parent.localStorage && window.parent.localStorage.setItem('viz_key', k); }catch(_){}
              try{ window.top && window.top.localStorage && window.top.localStorage.setItem('viz_key', k); }catch(_){}
            }
          };
          window.addEventListener('keydown', window.__vizKeyHandler, false);
        }

        // 누수 방지
        setTimeout(function(){ try{ localStorage.removeItem('${click}'); }catch(_){}} , 2000);
      })();
      </script>
    </div>
    """)

    wrapper = tpl.substitute(minw=min_width_px, html=fig_html, click=click_ns, drag=drag_ns)
    components.v1.html(wrapper, height=height+60, scrolling=True)

# ---------- 상호작용 렌더 ----------
def render_origin_view(df_origin: pd.DataFrame):
    """
    - 중앙 라벨 클릭으로 선택
    - Shift+클릭: 선택된 막대를 해당 좌표로 이동(드래그-드롭 대용)
    - 키보드: WASD/방향키 (5분/30m)
    - 변경은 st.session_state['edit_df']에 수행, 로그는 st.session_state['edit_logs']
    """
    _init_edit_buffers(df_origin)
    # after ✅ 최신 스냅샷 그대로 사용
    st.session_state["edit_df"] = df_origin.copy()
    df_edit = st.session_state["edit_df"]

    st.subheader("📊 편집 가능한 타임라인 (SND / GAM)")
    st.caption("· 클릭: 선택  · 더블 클릭: 관점 원상 복귀  · Shift+클릭: 해당 위치로 이동(드롭)  · WASD/←↑↓→: 5분/30m 이동  · 스냅: 5분/30m  · esc: 클릭해제")

    tab_snd, tab_gam = st.tabs(["신선대 SND", "감만 GAM"])

    def _render_one(terminal: str):
        df_all = st.session_state.get("edit_df")
        if df_all is None or not isinstance(df_all, pd.DataFrame) or df_all.empty:
            st.info(f"{terminal} 데이터가 없습니다.")
            return

        df_t = df_all[df_all["terminal"] == terminal].reset_index(drop=True)
        if df_t.empty:
            st.info(f"{terminal} 데이터가 없습니다.")
            return

        # 선택 상태 배너 자리(그래프 위)
        sel_line = st.empty()

        # 그림 생성
        fig, (x0, x1) = render_timeline_week(df_t, terminal=terminal, title="")
        fig.update_layout(title=f"{terminal} — {period_str_kr(x0, x1)}")
        html = fig.to_html(include_plotlyjs="cdn", full_html=False)
        _plotly_scroll_interactive(html, terminal=terminal, height=600, min_width_px=2400)

        # 이벤트 읽기
        key = streamlit_js_eval(
            js_expressions="localStorage.getItem('viz_key')",
            need_return=True, key=f"keyread-{terminal}"
        )
        click_json = streamlit_js_eval(
            js_expressions=f"localStorage.getItem('viz_click_{terminal}')",
            need_return=True, key=f"clickread-{terminal}"
        )

        # 클릭 처리: 선택/드롭 이동
        if click_json:
            try:
                payload = json.loads(click_json)
                rid = payload.get("row_id")
                if rid is not None:
                    st.session_state["selected_row_id"] = int(rid)

                # Shift+클릭 이동 (5분/30m 스냅)
                if payload.get("shift") and rid is not None:
                    rid = int(rid)
                    i = st.session_state["edit_df"].index[st.session_state["edit_df"]["row_id"] == rid]
                    if len(i):
                        idx = i[0]
                        s = pd.to_datetime(st.session_state["edit_df"].loc[idx, "start"])
                        e = pd.to_datetime(st.session_state["edit_df"].loc[idx, "end"])
                        if pd.notna(s) and pd.notna(e):
                            mid_old = s + (e - s) / 2
                            new_x = pd.to_datetime(payload["x"])
                            # 5분 단위로 반올림 이동량
                            diff_min = (new_x - mid_old).total_seconds() / 60.0
                            dmin = int(round(diff_min / 5.0) * 5)

                            # y 이동 (유효할 때만)
                            f0 = st.session_state["edit_df"].loc[idx, "f"]
                            e0 = st.session_state["edit_df"].loc[idx, "e"]
                            dy = 0.0
                            try:
                                if _is_finite_num(f0) and _is_finite_num(e0):
                                    mid_y_old = (float(f0) + float(e0)) / 2.0
                                    new_y = float(payload["y"])
                                    dy = new_y - mid_y_old
                            except Exception:
                                dy = 0.0

                            st.session_state["edit_df"] = _apply_move(st.session_state["edit_df"], rid, dmin=dmin, dy=dy)
            except Exception:
                pass
            # 사용 후 정리
            streamlit_js_eval(
                js_expressions=f"localStorage.removeItem('viz_click_{terminal}')",
                need_return=False, key=f"clickclear-{terminal}"
            )
        # ✅ 드래그 완료 payload 처리(픽셀→데이터 델타를 JS에서 계산해 전달)
        drag_json = streamlit_js_eval(
            js_expressions=f"localStorage.getItem('viz_drag_{terminal}')",
            need_return=True, key=f"dragread-{terminal}"
        )
        if drag_json and drag_json not in ("null", "undefined"):
            try:
                payload = json.loads(drag_json)
                rid = payload.get("row_id")
                dmin = int(payload.get("dmin") or 0)
                dy   = float(payload.get("dy") or 0.0)
                if rid is not None and (dmin != 0 or abs(dy) > 0.0):
                    st.session_state["selected_row_id"] = int(rid)   # 드래그한 항목 선택 유지
                    st.session_state["edit_df"] = _apply_move(st.session_state["edit_df"], int(rid), dmin=dmin, dy=dy)
            except Exception:
                pass
            # 사용 후 정리
            streamlit_js_eval(
                js_expressions=f"localStorage.removeItem('viz_drag_{terminal}')",
                need_return=False, key=f"dragclear-{terminal}"
            )
        # 키보드 처리 (선택된 막대 있을 때만)
        if key:
            key = str(key)
            rid = st.session_state.get("selected_row_id")
            if rid is not None:
                if key in ["ArrowLeft","a","A"]:
                    st.session_state["edit_df"] = _apply_move(st.session_state["edit_df"], rid, dmin=-5)
                elif key in ["ArrowRight","d","D"]:
                    st.session_state["edit_df"] = _apply_move(st.session_state["edit_df"], rid, dmin=+5)
                elif key in ["ArrowUp","w","W"]:
                    st.session_state["edit_df"] = _apply_move(st.session_state["edit_df"], rid, dy=-30.0)
                elif key in ["ArrowDown","s","S"]:
                    st.session_state["edit_df"] = _apply_move(st.session_state["edit_df"], rid, dy=+30.0)
                elif key in ["Escape"]:
                    st.session_state["selected_row_id"] = None

            streamlit_js_eval(
                js_expressions="localStorage.removeItem('viz_key')",
                need_return=False, key=f"keyclear-{terminal}"
            )

        # 간단 검증 경고
        probs = validate_df(st.session_state["edit_df"])
        if any(p[0] == "clearance" for p in probs):
            st.warning(f"동시간대 선박 간 최소 이격 {MIN_CLEARANCE_M}m 위반 항목이 있습니다.")

        # 선택 상태 배너
        rid = st.session_state.get("selected_row_id")
        msg = "선택 없음"
        if rid is not None:
            sel = st.session_state["edit_df"]
            sel = sel[(sel["row_id"] == rid) & (sel["terminal"] == terminal)]
            if not sel.empty:
                r = sel.iloc[0]
                def _fmt(ts):
                    return pd.to_datetime(ts).strftime('%m-%d %H:%M') if pd.notna(ts) else '-'
                msg = (
                    f"**선택됨:** {r.get('terminal','')}-{int(r.get('berth',0))} · "
                    f"{r.get('vessel','') or '-'} · {r.get('voyage','') or '-'} · "
                    f"{_fmt(r.get('start'))} ~ {_fmt(r.get('end'))} · "
                    f"F:{float(r.get('f',0)):.0f}m → E:{float(r.get('e',0)):.0f}m"
                )
        sel_line.info(msg)


    with tab_snd:
        _render_one("SND")
    with tab_gam:
        _render_one("GAM")
