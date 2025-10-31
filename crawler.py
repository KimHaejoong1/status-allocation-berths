# =========================================================
# crawler.py  (네가 "항상 잘 불러와진다"고 한 원본 로직을 그대로 유지)
# =========================================================
import time
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import quote_plus

# =========================================================
# 도움 함수 
# =========================================================
def _note_status_from_plan_cd(plan_cd: str) -> tuple[str, str]:
    """
    VslMsg의 plan_cd를 사이트와 동일한 문구/상태로 변환
      L -> '적하 프래닝까지 완료', LOAD_PLANNING_DONE
      D -> '양하 프래닝까지 완료', DISCHARGE_PLANNING_DONE
      C -> '크래인배정 완료',     CRANE_ASSIGNED
      else -> '크래인미 배정',    CRANE_UNASSIGNED
    """
    code = (plan_cd or "").strip().upper()
    if code == "L":
        return "적하 프래닝까지 완료", "LOAD_PLANNING_DONE"
    if code == "D":
        return "양하 프래닝까지 완료", "DISCHARGE_PLANNING_DONE"
    if code == "C":
        return "크래인배정 완료", "CRANE_ASSIGNED"
    return "크래인미 배정", "CRANE_UNASSIGNED"


# ---------------------------------------------------------
# 1) 신선대·감만 선석배정 텍스트표 (원본 그대로)
# ---------------------------------------------------------
def get_berth_status(time="3days", route="ALL", berth="A"):
    """
    신선대감만터미널 선석배정 현황 조회
    """
    url = "https://info.bptc.co.kr/Berth_status_text_servlet_sw_kr"
    payload = {
        "v_time": time,
        "ROCD": route,
        "v_oper_cd": "",
        "ORDER": "item1",
        "v_gu": berth,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://info.bptc.co.kr/content/sw/frame/berth_status_text_frame_sw_kr.jsp?p_id=BETX_SH_KR&snb_num=2&snb_div=service",
    }
    res = requests.post(url, data=payload, headers=headers, timeout=20)
    res.encoding = "euc-kr"

    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.find("table")
    if not table:
        return pd.DataFrame()

    headers_list = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cols:
            rows.append(cols)

    return pd.DataFrame(rows, columns=headers_list)

# ---------------------------------------------------------
# 2) G 화면에서 BP(Bitt) 정보 (원본 그대로)
# ---------------------------------------------------------
def get_all_bp_data(date=None):
    """
    한 날짜의 모든 BP(Bitt) + 참고(note) + 상태(plan_status)
    { (ship_cd, call_no): {"bitt": "...(F: n, E: m)", "note": "...", "plan_status": "..."} }
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    url = "https://info.bptc.co.kr/content/sw/jsp/berth_g_sw_kr.jsp"
    params = {
        "p_id": "BEGR_SH_KR",
        "snb_num": "2",
        "pop_ok": "Y",
        "PAR": "",
        "v_dt": date,
        "sub": "+%C8%AE+%C0%CE+",
    }
    headers = {
        "Referer": "https://info.bptc.co.kr/content/sw/frame/berth_g_frame_sw_kr.jsp?p_id=BEGR_SH_KR&snb_num=2&snb_div=service",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    res = requests.get(url, params=params, headers=headers, timeout=20)
    res.encoding = "euc-kr"

    soup = BeautifulSoup(res.text, "html.parser")
    bp_dict = {}

    layer1_sections = soup.find_all("section", id="layer1")
    if not layer1_sections:
        return bp_dict
    PLAN_NOTE = {
        "L": ("LOAD_PLANNING_DONE",      "적하 프래닝까지 완료"),
        "D": ("DISCHARGE_PLANNING_DONE", "양하 프래닝까지 완료"),
        "C": ("CRANE_ASSIGNED",          "크래인배정 완료"),
    }

    for layer1 in layer1_sections:
        for a_tag in layer1.find_all("a"):
            href = a_tag.get("href", "")
            m = re.search(
                r"VslMsg\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'\)",
                href,
            )
            if not m:
                continue
            ship_cd = m.group(2)
            call_no = m.group(4)
            plan_cd  = m.group(8)
            bitt    = m.group(11)
            note, plan_status = _note_status_from_plan_cd(plan_cd)

            bp_dict[(ship_cd, call_no)] = {
                "bitt": bitt,             # 예: "111 ( F: 1, E: 143)"
                "note": note,             # 예: "양하 프래닝까지 완료"
                "plan_status": plan_status
            }
    return bp_dict

def parse_bp(bp_str):
    """
    예: '110 ( F: 1, E: 142)' -> (110, 1, 142)
    """
    if not bp_str or pd.isna(bp_str):
        return (None, None, None)
    m = re.search(r"(\d+)\s*\(\s*F:\s*(\d+)\s*,\s*E:\s*(\d+)\)", bp_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (None, None, None)

def add_bp_to_dataframe(df, date=None):
    if "모선항차" not in df.columns:
        return df

    bp_map = get_all_bp_data(date)
    bp_list, f_list, e_list, note_list, status_list = [], [], [], [], []

    for _, row in df.iterrows():
        mocen = str(row["모선항차"]) if pd.notna(row["모선항차"]) else ""
        parts = mocen.split("-")
        if len(parts) >= 2:
            ship_cd, call_no = parts[0], parts[1]
            info = bp_map.get((ship_cd, call_no))
            if isinstance(info, dict):
                bp_str = info.get("bitt")
                note   = info.get("note", "")
                status = info.get("plan_status", "")
            else:
                # 과거 문자열만 반환하던 케이스와 호환
                bp_str = info
                note, status = "", ""
            bp, f, e = parse_bp(bp_str)
        else:
            bp, f, e, note, status = (None, None, None, "", "")

        bp_list.append(bp); f_list.append(f); e_list.append(e)
        note_list.append(note); status_list.append(status)

    df["bp"], df["f"], df["e"] = bp_list, f_list, e_list
    df["note"] = note_list
    df["plan_status"] = status_list
    return df

# ---------------------------------------------------------
# 3) VesselFinder 길이/폭 (네가 주신 원본 그대로)
#    ※ default로는 호출 안 함 (느려질 수 있으니 옵션화)
# ---------------------------------------------------------
_vf_session = requests.Session()
_vf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.vesselfinder.com/",
})
_dims_cache = {}

def get_vessel_dimensions(name: str, debug=False):
    key = name.strip().lower()
    if key in _dims_cache:
        return _dims_cache[key]
    try:
        search_url = f"https://www.vesselfinder.com/vessels?name={quote_plus(name)}"
        r = _vf_session.get(search_url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        L = B = None
        for cell in soup.find_all("td", class_="v6"):
            t = cell.get_text(strip=True)
            m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", t)
            if m:
                L = float(m.group(1)); B = float(m.group(2)); break
        _dims_cache[key] = (L, B)
        return (L, B)
    except Exception:
        _dims_cache[key] = (None, None)
        return (None, None)
    finally:
        time.sleep(0.4)

def enrich_with_length_beam(df: pd.DataFrame, ship_name_column="선박명", debug=False):
    out = df.copy()
    if ship_name_column not in out.columns:
        out["Length(m)"] = None
        out["Beam(m)"] = None
        return out
    Ls, Bs = [], []
    for idx, name in enumerate(out[ship_name_column].astype(str).fillna(""), 1):
        L, B = get_vessel_dimensions(name, debug=(debug and idx == 1))
        Ls.append(L); Bs.append(B)
    out["Length(m)"] = Ls
    out["Beam(m)"]   = Bs
    return out

# ---------------------------------------------------------
# 4) 통합 수집 (A/B/ALL, BP 추가, VF 추가는 옵션)
# ---------------------------------------------------------
def collect_berth_info(time="3days", route="ALL", berth="A", add_bp=True, add_dims=False, debug=False):
    """
    time: "oneday" | "3days" | "1week" | "2week"
    berth: "A" | "B" | "ALL"
    """
    if berth == "ALL":
        df_a = get_berth_status(time=time, route=route, berth="A")
        df_b = get_berth_status(time=time, route=route, berth="B")
        df = pd.concat([df_a, df_b], ignore_index=True)
    else:
        df = get_berth_status(time=time, route=route, berth=berth)

    if df.empty:
        return pd.DataFrame({"알림": ["데이터를 가져올 수 없습니다."]})

    if add_dims:
        df = enrich_with_length_beam(df, ship_name_column="선박명", debug=debug)

    if add_bp:
        df = add_bp_to_dataframe(df)

    return df
