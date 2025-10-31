# BPTC 선석배정 Gantt (Streamlit)

- BPTC "T" 페이지를 크롤링하여 사내 DB(SQLite)에 저장
- vis.js 타임라인 컴포넌트(`streamlit-vis-timeline`)로 Gantt 표시
- 드래그/드롭 & 그룹 이동 → 파이썬으로 이벤트 수신 → 1시간/30m/15m 스냅
- 시간 겹침 + (선택) 30m 이격 검증
- 버전(A/B) 비교, 되돌리기, 저장(새 버전 커밋)

## 빠른 실행
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## 배포
- **Streamlit Cloud**: `requirements.txt` + `packages.txt` 추가. 앱 첫 실행 시 브라우저 바이너리 설치를 위해 `app.py`가 `playwright install chromium`을 한 번 시도합니다.

> 외부(BPTC) 페이지에 **쓰기**는 하지 않습니다(읽기 전용 크롤링).
