# =========================
# ui/viz/common.py
# =========================
import pandas as pd
import plotly.graph_objects as go
from zoneinfo import ZoneInfo
from schema import TIME_GRID_MIN, Y_GRID_M
import re  # ← 추가

KST = ZoneInfo("Asia/Seoul")

# ---------------------------------------------------------
# 지금(KST) 기준 24시간 전 ~ +6일
#   - x_start: now - 24h
#   - x_end  : now + 6d
# ---------------------------------------------------------
def window_from_now_kst():
    now_kst = pd.Timestamp.now(tz=KST)
    start = (now_kst - pd.Timedelta(days=1)).tz_localize(None)
    end   = (now_kst + pd.Timedelta(days=6)).tz_localize(None)
    now_naive = now_kst.tz_localize(None)
    return start, end, now_naive  # (x0, x1, now)

# ---------------------------------------------------------
# 조회기간 문자열 (그래프/사이드바 표기)
#  - 끝 날짜는 그대로 표기 (원하면 -1초 처리해서 ‘전일’까지로 보이게 바꿀 수 있음)
# ---------------------------------------------------------
def period_str_kr(start: pd.Timestamp, end: pd.Timestamp) -> str:
    return f"{start:%Y년 %m월 %d일} ~ {end:%m월 %d일}"

def _ymax_for_terminal(terminal: str) -> int:
    return 1500 if terminal == "SND" else 1400

def _to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return float(default)

# ---------------------------------------------------------
# 4시간 간격 라벨 생성 (글자만 4h, 보조 눈금은 10분)
#   - 매일 00시는 '00 (27일)' 형식으로 날짜 병기
#   - 기준은 start.normalize()에서 시작
# ---------------------------------------------------------
def build_4h_ticks(start: pd.Timestamp, end: pd.Timestamp):
    vals, texts = [], []
    t = start.normalize()
    while t <= end:
        vals.append(t)
        texts.append(f"00 ({t:%d일})")
        # 같은 날의 04/08/12/16/20시
        for h in (4, 8, 12, 16, 20):
            tt = t + pd.Timedelta(hours=h)
            if tt <= end:
                vals.append(tt)
                texts.append(f"{tt:%H}")
        t += pd.Timedelta(days=1)
    return vals, texts

# ---------------------------------------------------------
# 주간 타임라인 (가로 스크롤용)
#   - x축: now-24h ~ now+7d
#   - 라벨: 4h, 보조눈금: 10min
#   - 빨간 세로선: 현재시간(now)
# ---------------------------------------------------------
def render_timeline_week(df: pd.DataFrame, terminal: str, title: str):
    if df is None:
        df = pd.DataFrame()

    x0, x1, now_x = window_from_now_kst()
    y_max = _ymax_for_terminal(terminal)

    fig = go.Figure()
    df_show = df.sort_values(["start", "berth", "vessel"]).reset_index(drop=True)
    

    # ==== 추가: 상태별 색상 팔레트 ====
    def _color_for_status(status: str, terminal: str) -> str:
        """
        상태별 기본색. 상태 없으면 터미널 기본색.
        - LOAD_PLANNING_DONE       -> Pink  (rgba)
        - DISCHARGE_PLANNING_DONE  -> Blue  (rgba)
        - CRANE_ASSIGNED           -> Yellow(rgba)
        - CRANE_UNASSIGNED         -> Gray  (rgba)
        """
        palette = {
            "LOAD_PLANNING_DONE":      "rgba(236,130,176,0.78)",  # 분홍
            "DISCHARGE_PLANNING_DONE": "rgba(115,158,245,0.78)",  # 파랑
            "CRANE_ASSIGNED":          "rgba(248,202,109,0.78)",  # 노랑
            "CRANE_UNASSIGNED":        "rgba(180,180,186,0.75)",  # 회색
        }
        if status and status in palette:
            return palette[status]
        # 상태가 없으면 기존 터미널 색 유지
        return "rgba(120,160,240,0.7)" if terminal == "SND" else "rgba(240,180,80,0.7)"
    
    def _text_color_for_fill(fill_rgba: str) -> str:
        """
        막대 배경색( rgba(...) )과 대비되도록 라벨 색을 결정.
        알파가 있으면 흰 배경에 합성해 밝기를 추정한 뒤
        밝으면 진한 글씨(거의 검정), 어두우면 흰 글씨를 리턴.
        """
        try:
            nums = re.findall(r"[\d.]+", fill_rgba)
            r, g, b = [float(nums[i]) for i in range(3)]
            a = float(nums[3]) if len(nums) > 3 else 1.0
            # 흰 배경(#fff) 위 합성
            r = 255*(1-a) + r*a
            g = 255*(1-a) + g*a
            b = 255*(1-a) + b*a
            # 상대 휘도(0~1). 임계 0.6 근처에서 가독성 좋음
            lum = 0.2126*(r/255)**2.2 + 0.7152*(g/255)**2.2 + 0.0722*(b/255)**2.2
            return "rgba(15,15,20,0.98)" if lum > 0.6 else "rgba(255,255,255,0.98)"
        except Exception:
            return "rgba(15,15,20,0.98)"
    def _draw_berth_guides(fig, x0, x1, terminal):
        # 선석 범위/라벨 정의 (현재 로직과 동일한 스텝: SND=300m×5, GAM=350m×4)
        if terminal == "SND":
            step = 300
            labels = [f"{i}" for i in range(1, 6)]
        else:
            step = 350
            gam_pairs = [(1, 9), (2, 8), (3, 7), (4, 6)]
            labels = [f"{a}({b})" for a, b in gam_pairs]
        # 밴드 + 레이블 (밴드는 layer='below'로 깔리고, 레이블은 좌측 안쪽에 고정)
        for i, label in enumerate(labels):
            y0 = i * step
            y1 = y0 + step

            # 옅은 배경 밴드(격줄과 충돌 최소화 위해 아주 옅게)
            if i % 2 == 0:  # 한 칸 건너 밝게
                fig.add_shape(
                    type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                    xref="x", yref="y", layer="below",
                    fillcolor="rgba(0,0,0,0.03)", line=dict(width=0)
                )

            # 선석 레이블: 시작 시간선 바로 오른쪽에 살짝 띄워 배치
            fig.add_annotation(
                x=x0 + pd.Timedelta(minutes=20),  # 왼쪽 가장자리에서 20분 안쪽
                y=(y0 + y1) / 2, xref="x", yref="y",
                text=label, showarrow=False, xanchor="left", yanchor="middle",
                font=dict(size=12, color="rgba(30,30,30,0.85)"),
                bgcolor="rgba(255,255,255,0.35)", borderpad=2
            )
    # x0, x1, now_x = window_from_now_kst() 다음 등, 막대 그리기 전에
    _draw_berth_guides(fig, x0, x1, terminal)

    # 막대 + 라벨
    for _, r in df_show.iterrows():
        s, e = r.get("start"), r.get("end")
        if pd.isna(s) or pd.isna(e):
            continue
        # y0=위쪽(숫자 작음), y1=아래쪽(숫자 큼) — (반전 y축에서 시각적 기준)
        y0 = min(_to_float(r.get("f", 0)), _to_float(r.get("e", 0)))
        y1 = max(_to_float(r.get("f", 0)), _to_float(r.get("e", 0)))
        if y0 == y1:
            y1 = y0 + 10.0
        # ✅ 상태 기반 색상
        status = (r.get("plan_status") or "").strip()
        color = _color_for_status(status, terminal)
        tcolor = _text_color_for_fill(color)  # 글자색 

        # 실제 막대(사각형)
        fig.add_shape(
            type="rect", x0=s, x1=e, y0=y0, y1=y1,
            xref="x", yref="y",
            line=dict(width=1, color="rgba(20,20,20,0.6)"),
            fillcolor=color, layer="below"     # ⬅️ 텍스트가 위로 올라와 보임
        )

        # 중앙 라벨: voyage(모선항차) 우선, 없으면 vessel
        voyage = (r.get("voyage") or "").strip()
        berthing = (r.get("berthing") or "").strip()
        center_label = voyage if voyage else (r.get("vessel") or "")
        if center_label and berthing:
            center_label = f"{center_label} ({berthing})"

        # 텍스트 위치 계산 (반전축 고려)
        mid_t = s + (e - s) / 2
        mid_y = (y0 + y1) / 2.0

        def _safe_str(x, default="-"):
            try:
                s = str(x)
                return default if s.lower() in {"nan", "none"} else s
            except Exception:
                return default

        row_id = int(r.get("row_id", _))  # ← 안전 row_id
        note_txt = _safe_str(r.get("note")).strip()
        fig.add_trace(go.Scatter(
            x=[mid_t], y=[mid_y], mode="markers+text", # ✅ 클릭 안정화: 마커+텍스트(마커는 투명)
            marker=dict(size=27, opacity=0.01, color="rgba(0,0,0,0)"),
            text=[center_label],
            textfont=dict(color=tcolor, size=12),  # ✅ 대비되는 글씨색 + 살짝 키움 
            # ✅ 선택 식별용 데이터 
            customdata=[row_id],
            hovertext=(
                f'{r.get("terminal","")}-{r.get("berth","")} / '
                f'Vessel:{r.get("vessel","")}  Voyage:{voyage}<br>'
                f'접안:{berthing or "-"}  검역:{(r.get("quarantine") or "-")}<br>'
                f'{s:%m-%d %H:%M} ~ {e:%m-%d %H:%M}<br>'
                f'구분:{r.get("stype","")} / F:{_to_float(r.get("f")):.0f}m → E:{_to_float(r.get("e")):.0f}m'
                f'<br>참고: {note_txt}'
            ),
            hoverinfo="text",
            showlegend=False,
            textposition="middle center",
        ))

        # 2) 중앙 아래줄: 검역(있을 때만)
        quarantine = (r.get("quarantine") or "").strip()
        if quarantine:
            # '아래' = 반전축에서 y를 약간 크게(+), 막대 범위 안쪽으로
            y_quar = min(mid_y + 18, y1 - 4)  # 너무 내려가면 바깥으로 나가니 클램프
            fig.add_trace(go.Scatter(
                x=[mid_t], y=[y_quar], mode="text",
                text=[quarantine],
                hoverinfo="skip",
                showlegend=False,
                textposition="bottom center",
                textfont=dict(color="rgba(220,30,30,0.95)"),  # ✅ 빨간색 적용
            ))
        # (수정) 막대 높이의 4% 또는 최소 12m만큼 안쪽으로
        inset_ratio = 0.05 if terminal == "SND" else 0.07
        inset_m = max(12.0, inset_ratio * (y1 - y0))
        y_top_inside = min(y0 + inset_m, y1 - 6)  # 절대 범위 밖으로 못 나가게 클램프
        # 좌상단: 시작 '시'만 (예: 17:00 → "17")
        start_hour = int(pd.to_datetime(s).hour)
        fig.add_annotation(
            x=s, y=y_top_inside, xref="x", yref="y",
            text=f"{start_hour}",
            showarrow=False,
            xanchor="left", yanchor="top",
            xshift=3, yshift=0,      # x만 살짝 안쪽, y는 데이터좌표로 안쪽으로 이미 이동
            font=dict(size=11, color="rgba(20,20,20,0.95)")
        )

        # 우상단: 종료 '시'만
        end_hour = int(pd.to_datetime(e).hour)
        fig.add_annotation(
            x=e, y=y_top_inside, xref="x", yref="y",
            text=f"{end_hour}",
            showarrow=False,
            xanchor="right", yanchor="top",
            xshift=-3, yshift=0,
            font=dict(size=11, color="rgba(20,20,20,0.95)")
        )

    # 굵은 보조선: 매일 00시
    day = x0.normalize()
    while day <= x1:
        fig.add_shape(
            type="line", x0=day, x1=day, y0=0, y1=y_max,
            xref="x", yref="y", line=dict(width=2, color="rgba(0,0,0,0.25)"), layer="below"
        )
        day += pd.Timedelta(days=1)

    # 굵은 보조선: Y=0,300,...,1200,(1500)
    def _y_major_ticks(terminal: str):
        """터미널별 굵은 보조선(y) 위치"""
        if terminal == "SND":
            y_max, step = 1500, 300
        else:  # GAM
            y_max, step = 1400, 350
        return list(range(0, y_max + 1, step))

    major_ys = _y_major_ticks(terminal)
    for vy in major_ys:
        fig.add_shape(
            type="line", x0=x0, x1=x1, y0=vy, y1=vy,
            xref="x", yref="y", line=dict(width=2, color="rgba(0,0,0,0.25)"), layer="below"
        )
    
    # 현재시간(빨간 세로선)
    if x0 <= now_x <= x1:
        fig.add_shape(
            type="line", x0=now_x, x1=now_x, y0=0, y1=y_max,
            xref="x", yref="y", line=dict(width=2, color="rgba(220,30,30,0.95)"), layer="above"
        )
        fig.add_annotation(
            x=now_x, y=y_max, xref="x", yref="y",
            text="지금", showarrow=True, arrowhead=2, ax=0, ay=-24,
            font=dict(color="rgba(0,0,0,1)", size=12)
        )

    # 라벨(4h), 보조눈금(10min)
    tickvals, ticktext = build_4h_ticks(x0, x1)
    fig.update_xaxes(
        range=[x0, x1],
        tickvals=tickvals, ticktext=ticktext,
        ticklabelposition="outside", tickfont=dict(size=11),
        ticks="outside", ticklen=6,
        hoverformat="%m-%d %H:%M",
        gridcolor="rgba(0,0,0,0.08)",
        title=f"Time (KST) — snap {TIME_GRID_MIN}min",
        minor=dict(
            dtick=1000 * 60 * 10, showgrid=True,
            gridcolor="rgba(0,0,0,0.06)", ticklen=3
        ),
    )

    fig.update_yaxes(
        range=[y_max, 0], dtick=Y_GRID_M,
        title=f"{terminal} length (m) — snap {Y_GRID_M}m",
        gridcolor="rgba(0,0,0,0.08)", zeroline=False,
    )
    # 가로폭 넉넉 (가로 스크롤로 봄)
    fig.update_layout(
        title=title,
        height=600, width=2600,
        margin=dict(l=40, r=20, t=50, b=40),
        dragmode="pan",
        clickmode="event+select",   # ✅ 클릭 이벤트 확실히
    )

    return fig, (x0, x1)
