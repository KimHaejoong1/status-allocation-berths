# =========================
# schema.py
# =========================
import re
import numpy as np
import pandas as pd
from dateutil import parser

# ---------------------------------------------------------
# 상수 정의
# ---------------------------------------------------------
SND_BERTHS = set(range(1, 6))    # 신선대 1~5
GAM_BERTHS = set(range(6, 10))   # 감만 6~9
Y_GRID_M = 30                    # 세로(선석 내 m) 스냅 단위
MIN_CLEARANCE_M = 30             # 선박 간 최소 이격(m)
TIME_GRID_MIN = 10               # 가로(시간) 스냅 단위(분)

# ---------------------------------------------------------
# 한글 원본 → 표준 컬럼 매핑 (요청한 컬럼만 사용)
#   - 입항 예정일시, 작업완료 일시, 모선항차, 선박명, 구분, 선석, bp, f, e
# ---------------------------------------------------------
KOR_MAP = {
    "입항 예정일시": "start",
    "입항예정일시": "start",          
    "출항일시": "end",
    "출항 일시": "end",            
    "모선항차": "voyage",
    "선박명": "vessel",
    "구분": "stype",
    "선석": "berth",
    "bp": "bp",
    "f": "f",
    "e": "e",
    "접안": "berthing",     
    "검역": "quarantine",   
}

# 표준 출력 순서
STD_ORDER = ["terminal", "berth", "vessel", "voyage", "start", "end", "stype", "bp", "f", "e", "berthing", "quarantine","y_m"]

# ---------------------------------------------------------
# 유틸
# ---------------------------------------------------------
# 바꿔치기할 함수
def _infer_terminal_from_berth(b: int) -> str:
    """선석 번호만 보고 터미널 추론: 1~5=SND, 6~9=GAM, 그 외는 빈값"""
    try:
        bi = int(b)
    except Exception:
        return ""
    if 1 <= bi <= 5:
        return "SND"
    if 6 <= bi <= 9:
        return "GAM"
    return ""

def _coerce_datetime(x):
    """
    관대한 날짜 파서:
      - None/NaN/빈문자/대시류/N/A → NaT
      - 엑셀 직렬값(정수/실수, 대략 20000~80000 범위) → to_datetime(origin='1899-12-30', unit='D')
      - 그 외 문자열 → 구분자/한글단위 정리 후 pandas.to_datetime(errors='coerce')
      - Timestamp는 그대로 반환
    """
    # 결측/None
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return pd.NaT

    # 이미 Timestamp
    if isinstance(x, pd.Timestamp):
        return x

    # 문자열 전처리
    if isinstance(x, str):
        s = x.strip()
        if s == "" or s in {"-", "—", "N/A", "NA", "null", "None"}:
            return pd.NaT
        # 2025.10.29 / 2025/10/29 → 2025-10-29
        s_norm = re.sub(r"[./]", "-", s)
        # '년 월 일 시 분' 같은 한글 단위 제거/공백 정리 (숫자만 유지되게)
        s_norm = re.sub(r"[년월일시분초]", "-", s_norm)
        s_norm = re.sub(r"\s+", " ", s_norm).strip("- ").strip()
        # pandas 파싱 시도
        ts = pd.to_datetime(s_norm, errors="coerce", utc=False)
        return ts if not pd.isna(ts) else pd.NaT

    # 숫자형: 엑셀 직렬값 가능성
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        xf = float(x)
        # 1954~2120년대 대략 커버
        if 20000 <= xf <= 80000:
            try:
                return pd.to_datetime(xf, origin="1899-12-30", unit="D")
            except Exception:
                return pd.NaT
        # UNIX epoch(초/밀리초)일 수도 있지만 여기서는 보수적으로 NaT
        return pd.NaT

    # 마지막 방어선
    try:
        return pd.to_datetime(x, errors="coerce")
    except Exception:
        return pd.NaT

# ---------------------------------------------------------
# 정규화
# ---------------------------------------------------------
def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    원본 테이블을 표준 스키마로 통일
      - 컬럼명 표준화(KOR_MAP)
      - berth 정수화, terminal 추론
      - 문자열 기본 처리(vessel/voyage/stype 등)
      - start/end 관대 파싱(_coerce_datetime)
      - bp/f/e 숫자화, y_m=bp
      - STD_ORDER만 노출
    """
    out = df.copy()

    # 1) 한글 → 표준 컬럼명
    rename_map = {k: v for k, v in KOR_MAP.items() if k in out.columns}
    out.rename(columns=rename_map, inplace=True)

    # 2) 선석 → 정수
    if "berth" in out:
        out["berth"] = (
            out["berth"]
            .astype(str)
            .str.extract(r"(\d+)", expand=False)
            .astype(float)
            .fillna(0)
            .astype(int)
        )
    else:
        out["berth"] = 0

    # 3) terminal 유추 (항상 생성)
    out["terminal"] = out["berth"].apply(_infer_terminal_from_berth)

    # 4) 문자열 컬럼 기본 처리
    for col in ["vessel", "voyage", "stype", "remark", "berthing", "quarantine"]:
        if col not in out:
            out[col] = ""
        out[col] = out[col].astype(str).str.strip()

    # 5) 시간 파싱 (시리즈 안전)
    if "start" in out:
        out["start"] = out["start"].apply(_coerce_datetime)
    else:
        out["start"] = pd.Series(pd.NaT, index=out.index)

    if "end" in out:
        out["end"] = out["end"].apply(_coerce_datetime)
    else:
        out["end"] = pd.Series(pd.NaT, index=out.index)

    # 6) 숫자 컬럼(bp,f,e)
    for col in ["bp", "f", "e"]:
        if col not in out:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")

    # 7) y_m (세로 m 위치): bp 있으면 bp, 없으면 0
    out["y_m"] = out["bp"].fillna(0).astype(float)

    # 8) 표준 컬럼만 노출 (없으면 자동 제외)
    std = [c for c in STD_ORDER if c in out.columns]

    # 크롤러 보강치수 보존
    extras = [c for c in ["Length(m)", "Beam(m)", "note", "plan_status"] if c in out.columns]
    out = out[std + extras]
    return out

# ---------------------------------------------------------
# 검증
# ---------------------------------------------------------
def _overlap(a_start, a_end, b_start, b_end) -> bool:
    """시간 구간 중첩 여부"""
    if pd.isna(a_start) or pd.isna(a_end) or pd.isna(b_start) or pd.isna(b_end):
        return False
    return not (a_end <= b_start or b_end <= a_start)

def validate_df(df: pd.DataFrame) -> list[tuple]:
    """
    유효성 검사:
      - terminal in {SND,GAM}
      - 선석 범위(SND:1~5, GAM:6~9)
      - start < end
      - 동일 (terminal, berth) 내 시간 중첩 금지
      - 동일 (terminal, berth) 내 동시에 머무는 선박 간 y_m 이격 >= MIN_CLEARANCE_M
    """
    problems: list[tuple] = []

    # 행 단위 검사
    for i, r in df.iterrows():
        t = r.get("terminal")
        b = int(r.get("berth", 0))
        s = r.get("start")
        e = r.get("end")

        if t not in {"SND", "GAM"}:
            problems.append((i, "terminal", "터미널 값 오류(SND/GAM)"))
        if t == "SND" and b not in SND_BERTHS:
            problems.append((i, "berth", "신선대 선석 범위(1~5) 위반"))
        if t == "GAM" and b not in GAM_BERTHS:
            problems.append((i, "berth", "감만 선석 범위(6~9) 위반"))
        if pd.isna(s) or pd.isna(e) or s >= e:
            problems.append((i, "time", "시작/종료 시간 오류"))

    # 그룹(terminal, berth)별 시간/간격 검사
    for (t, b), g in df.groupby(["terminal", "berth"]):
        g = g.sort_values("start").reset_index(drop=True)
        # 시간 중첩
        if (g["start"].shift(-1) < g["end"]).any():
            problems.append(("overlap", f"{t}-{b}", "동일 선석 시간 중첩"))

        # 같은 시간에 머무는 선박 간 y_m 간격 검사
        n = len(g)
        for i in range(n):
            for j in range(i + 1, n):
                if _overlap(g.loc[i, "start"], g.loc[i, "end"], g.loc[j, "start"], g.loc[j, "end"]):
                    d = abs(float(g.loc[i, "y_m"]) - float(g.loc[j, "y_m"]))
                    if d < MIN_CLEARANCE_M:
                        problems.append(
                            ("clearance", f"{t}-{b}", f"동시 계류 간 최소 이격 {MIN_CLEARANCE_M}m 위반 (Δ={d:.1f}m)")
                        )
    return problems

# ---------------------------------------------------------
# 스냅(시간 5분 / 세로 30m)
# ---------------------------------------------------------
def snap_time_5min(ts: pd.Timestamp) -> pd.Timestamp:
    if pd.isna(ts):
        return ts
    base = ts.replace(second=0, microsecond=0)
    minutes = base.hour * 60 + base.minute
    snapped = round(minutes / 5) * 5   # ← 5분 그리드
    h, m = divmod(snapped, 60)
    day_offset, h = divmod(h, 24)
    return (base.normalize()
            + pd.to_timedelta(day_offset, "D")
            + pd.to_timedelta(h, "H")
            + pd.to_timedelta(m, "m"))


def snap_y_30m(y_m: float) -> float:
    """세로 m 좌표를 30m 그리드로 스냅"""
    try:
        y_m = float(y_m)
    except Exception:
        return 0.0
    return round(y_m / Y_GRID_M) * Y_GRID_M

# ===== (추가) row_id 보장 =====
def ensure_row_id(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "row_id" not in out.columns:
        out.insert(0, "row_id", range(len(out)))
    return out


# ===== (추가) 정규화 ↔ 원본 동기화 =====
#  - normalize_df와 동일 순서라고 가정하지 않고, row_id 기준으로 반영
#  - KOR_MAP 역매핑을 사용해 가능한 컬럼만 원본에 반영
def sync_raw_with_norm(raw_df: pd.DataFrame, norm_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df is None or norm_df is None:
        return raw_df
    if "row_id" not in raw_df.columns or "row_id" not in norm_df.columns:
        # row_id가 없으면 안전하게 건드리지 않음
        return raw_df.copy()

    out = raw_df.copy()
    # 역매핑: 표준컬럼 -> 가능한 한글 컬럼 후보(여럿일 수 있음)
    inv = {}
    for k, v in KOR_MAP.items():
        inv.setdefault(v, []).append(k)

    # 표준 → 원본 반영 후보
    std_cols = ["start","end","voyage","vessel","stype","berth","bp","f","e","berthing","quarantine"]
    g = norm_df.set_index("row_id")
    for rid, row in g.iterrows():
        if rid not in out["row_id"].values:
            continue
        mask = out["row_id"] == rid
        for std_col in std_cols:
            if std_col not in row.index:
                continue
            val = row.get(std_col)
            # 원본 컬럼 후보들 중 존재하는 첫 번째에 씀
            for kor_col in inv.get(std_col, []):
                if kor_col in out.columns:
                    out.loc[mask, kor_col] = val
                    break
    return out