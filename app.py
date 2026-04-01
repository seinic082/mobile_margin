"""
핸드폰 유통사 마진 비교 대시보드
Mobile Margin Analysis SaaS - Streamlit App
"""

import streamlit as st
import pandas as pd
import json
import base64
import io
import os
import re
from datetime import datetime
from typing import Optional
import anthropic

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="마진 비교기 | 모바일 유통 분석",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 커스텀 CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* 전체 폰트 & 배경 */
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=JetBrains+Mono&display=swap');

html, body, [class*="css"] {
    font-family: 'Noto Sans KR', sans-serif;
}

/* 헤더 */
.main-header {
    background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
    color: white;
    padding: 2rem 2.5rem;
    border-radius: 16px;
    margin-bottom: 1.5rem;
    box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}
.main-header h1 { font-size: 2rem; font-weight: 700; margin: 0; letter-spacing: -0.5px; }
.main-header p  { font-size: 0.95rem; opacity: 0.75; margin: 0.4rem 0 0; }

/* 카드 */
.card {
    background: white;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    border: 1px solid #e8edf3;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    margin-bottom: 1rem;
}
.card-title {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #7b8fa1;
    margin-bottom: 0.4rem;
}
.card-value {
    font-size: 1.9rem;
    font-weight: 700;
    color: #1a2533;
    font-family: 'JetBrains Mono', monospace;
}
.card-value.positive { color: #16a34a; }
.card-value.negative { color: #dc2626; }
.card-sub { font-size: 0.8rem; color: #9aabb9; margin-top: 0.2rem; }

/* 배지 */
.badge-best {
    display: inline-block;
    background: #dcfce7;
    color: #15803d;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 99px;
    letter-spacing: 0.5px;
}
.badge-warning {
    display: inline-block;
    background: #fef9c3;
    color: #a16207;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 99px;
}
.badge-loss {
    display: inline-block;
    background: #fee2e2;
    color: #b91c1c;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 99px;
}

/* 업로드 영역 */
.stFileUploader > div {
    border: 2px dashed #c5d3e0 !important;
    border-radius: 12px !important;
    background: #f8fafc !important;
    transition: all 0.2s;
}
.stFileUploader > div:hover {
    border-color: #3b82f6 !important;
    background: #eff6ff !important;
}

/* 버튼 */
.stButton > button {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    padding: 0.6rem 1.4rem;
    font-size: 0.92rem;
    transition: all 0.2s;
    width: 100%;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #1d4ed8, #1e40af);
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(37,99,235,0.3);
}

/* 사이드바 */
section[data-testid="stSidebar"] {
    background: #0f1923;
}
section[data-testid="stSidebar"] * {
    color: #c8d6e3 !important;
}
section[data-testid="stSidebar"] .stNumberInput label,
section[data-testid="stSidebar"] .stSelectbox label {
    color: #94a8ba !important;
    font-size: 0.82rem;
    font-weight: 500;
}

/* 테이블 */
.stDataFrame {
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #e2e8f0 !important;
}

/* 구분선 */
hr.section-divider {
    border: none;
    border-top: 1px solid #e8edf3;
    margin: 1.5rem 0;
}

/* 알림 박스 */
.info-box {
    background: #eff6ff;
    border-left: 4px solid #3b82f6;
    border-radius: 0 8px 8px 0;
    padding: 0.8rem 1rem;
    font-size: 0.88rem;
    color: #1e3a5f;
    margin-bottom: 1rem;
}

/* 로고 영역 */
.logo-row {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    margin-bottom: 0.5rem;
}
.logo-icon {
    font-size: 2rem;
    line-height: 1;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 상수 & 설정
# ─────────────────────────────────────────────
CARRIERS = ["SKT", "KT", "LGU+"]
ACTIVATION_TYPES = ["MNP (번호이동)", "기변 (기기변경)"]
SUPPORTED_EXTENSIONS = ["jpg", "jpeg", "png", "pdf", "xlsx", "csv", "txt"]

# 통신사 컬러
CARRIER_COLORS = {
    "SKT": "#E63946",
    "KT":  "#2563EB",
    "LGU+": "#7C3AED",
}

# ─────────────────────────────────────────────
# Anthropic 클라이언트 초기화
# ─────────────────────────────────────────────
@st.cache_resource
def get_claude_client():
    api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


# ─────────────────────────────────────────────
# 파일 → base64 변환 유틸
# ─────────────────────────────────────────────
def file_to_base64(uploaded_file) -> str:
    return base64.standard_b64encode(uploaded_file.read()).decode("utf-8")


def get_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png",
        "pdf": "application/pdf",
    }.get(ext, "image/jpeg")


# ─────────────────────────────────────────────
# Claude OCR + 마진 추출
# ─────────────────────────────────────────────
EXTRACTION_PROMPT = """
당신은 한국 이동통신 유통업계 전문가입니다.
첨부된 파일은 유통사의 핸드폰 단가표입니다.

다음 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

{
  "distributor_name": "유통사명",
  "carrier": "SKT 또는 KT 또는 LGU+",
  "currency_unit": "만원 또는 천원",
  "models": [
    {
      "model": "기기명 (예: 아이폰16 Pro, 갤럭시S25)",
      "MNP": {
        "액면": 숫자,
        "TAC": 숫자,
        "마스콜": 숫자,
        "특별1": 숫자,
        "특별2": 숫자,
        "추지": 숫자,
        "GR": 숫자,
        "합계": 숫자
      },
      "기변": {
        "액면": 숫자,
        "TAC": 숫자,
        "마스콜": 숫자,
        "특별1": 숫자,
        "특별2": 숫자,
        "추지": 숫자,
        "GR": 숫자,
        "합계": 숫자
      }
    }
  ]
}

규칙:
- 숫자가 없는 항목은 0으로 기입
- 합계 = 모든 항목의 합산 (없으면 직접 계산)
- currency_unit이 "천원"이면 합계를 10으로 나눠 만원 단위로 통일하지 말 것 (원본 단위 그대로 반환)
- 모델명은 줄임말 없이 최대한 원본 그대로
"""


def extract_margin_from_image(client, uploaded_file) -> Optional[dict]:
    """이미지/PDF 파일에서 마진 정보 추출"""
    uploaded_file.seek(0)
    b64 = file_to_base64(uploaded_file)
    media_type = get_media_type(uploaded_file.name)

    if media_type == "application/pdf":
        content = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            },
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    else:
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            },
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )
    raw = response.content[0].text.strip()
    # JSON 블록 추출
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group())
    return None


def extract_margin_from_text(client, text_content: str) -> Optional[dict]:
    """텍스트/CSV/XLSX에서 마진 정보 추출"""
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"{EXTRACTION_PROMPT}\n\n아래는 파일 내용입니다:\n\n{text_content[:6000]}",
            }
        ],
    )
    raw = response.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group())
    return None


def normalize_to_man(value: float, currency_unit: str) -> float:
    """천원 단위를 만원으로 변환"""
    if currency_unit == "천원":
        return round(value / 10, 2)
    return value


def process_uploaded_file(client, uploaded_file) -> Optional[dict]:
    """파일 종류별 처리"""
    ext = uploaded_file.name.rsplit(".", 1)[-1].lower()

    if ext in ["jpg", "jpeg", "png", "pdf"]:
        return extract_margin_from_image(client, uploaded_file)

    elif ext == "xlsx":
        df = pd.read_excel(uploaded_file)
        return extract_margin_from_text(client, df.to_string(index=False))

    elif ext == "csv":
        df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
        return extract_margin_from_text(client, df.to_string(index=False))

    elif ext == "txt":
        text = uploaded_file.read().decode("utf-8-sig", errors="ignore")
        return extract_margin_from_text(client, text)

    return None


# ─────────────────────────────────────────────
# 마진 비교 테이블 빌더
# ─────────────────────────────────────────────
def build_comparison_df(
    results: list[dict],
    extra_cost: float,
    desired_margin: float,
    activation_type: str,   # "MNP" or "기변"
) -> pd.DataFrame:
    """
    results: process_uploaded_file 결과 리스트
    extra_cost: 부가서비스 비용 (만원)
    desired_margin: 희망 마진 (만원)
    """
    act_key = "MNP" if "MNP" in activation_type else "기변"

    # 전체 모델명 수집
    all_models: set[str] = set()
    for r in results:
        for m in r.get("models", []):
            all_models.add(m["model"])

    rows = []
    for model in sorted(all_models):
        row = {"모델": model}
        best_total = -999
        best_dist = ""

        for r in results:
            dist = r.get("distributor_name", "알수없음")
            unit = r.get("currency_unit", "만원")

            model_data = next(
                (m for m in r.get("models", []) if m["model"] == model), None
            )
            if model_data is None:
                row[f"{dist}_합계"] = "-"
                row[f"{dist}_실수령"] = "-"
                row[f"{dist}_충족"] = "-"
                continue

            act_data = model_data.get(act_key, {})
            raw_total = act_data.get("합계", 0) or 0
            total_man = normalize_to_man(raw_total, unit)

            net = total_man - extra_cost
            meets = "✅" if net >= desired_margin else "❌"

            row[f"{dist}_합계"] = round(total_man, 1)
            row[f"{dist}_실수령"] = round(net, 1)
            row[f"{dist}_충족"] = meets

            if total_man > best_total:
                best_total = total_man
                best_dist = dist

        row["최고유통사"] = best_dist
        rows.append(row)

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# 엑셀 다운로드 생성
# ─────────────────────────────────────────────
def build_excel(results: list[dict], df_compare: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_compare.to_excel(writer, sheet_name="마진비교", index=False)

        for r in results:
            dist = r.get("distributor_name", "유통사")[:20]
            rows = []
            for m in r.get("models", []):
                for act in ["MNP", "기변"]:
                    d = m.get(act, {})
                    rows.append({
                        "모델": m["model"], "구분": act,
                        "액면": d.get("액면", 0), "TAC": d.get("TAC", 0),
                        "마스콜": d.get("마스콜", 0), "특별1": d.get("특별1", 0),
                        "특별2": d.get("특별2", 0), "추지": d.get("추지", 0),
                        "GR": d.get("GR", 0), "합계": d.get("합계", 0),
                    })
            pd.DataFrame(rows).to_excel(writer, sheet_name=dist, index=False)

    return output.getvalue()


# ─────────────────────────────────────────────
# 요약 지표 카드
# ─────────────────────────────────────────────
def metric_card(title: str, value: str, sub: str = "", is_positive: bool = True):
    css_class = "positive" if is_positive else "negative"
    st.markdown(f"""
    <div class="card">
        <div class="card-title">{title}</div>
        <div class="card-value {css_class}">{value}</div>
        <div class="card-sub">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 사이드바 — 설정 패널
# ─────────────────────────────────────────────
def render_sidebar():
    st.sidebar.markdown("## ⚙️ 분석 설정")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 비교 조건")

    activation_type = st.sidebar.selectbox(
        "활성화 유형", ACTIVATION_TYPES, index=0
    )
    extra_cost = st.sidebar.number_input(
        "부가서비스 비용 (만원)", min_value=0.0, max_value=20.0,
        value=3.0, step=0.5,
        help="가입 시 필수 부가서비스 등 공제 비용"
    )
    desired_margin = st.sidebar.number_input(
        "희망 최소 마진 (만원)", min_value=0.0, max_value=30.0,
        value=5.0, step=0.5,
        help="이 금액 이상이면 ✅, 미만이면 ❌ 표시"
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    <div style="font-size:0.75rem; color:#4a6174; line-height:1.6;">
    📌 <strong>단위 안내</strong><br>
    • 기본 단위: <strong>만원</strong><br>
    • PS부산 등 천원 단가표는 자동 변환<br><br>
    📌 <strong>지원 파일</strong><br>
    JPG / PNG / PDF / XLSX / CSV / TXT
    </div>
    """, unsafe_allow_html=True)

    return activation_type, extra_cost, desired_margin


# ─────────────────────────────────────────────
# 메인 UI
# ─────────────────────────────────────────────
def main():
    # 헤더
    st.markdown("""
    <div class="main-header">
        <div class="logo-row">
            <span class="logo-icon">📱</span>
            <div>
                <h1>모바일 마진 비교기</h1>
                <p>유통사별 단가표를 업로드하면 마진을 자동 분석·비교합니다</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # API 키 — Streamlit Secrets에서만 로드 (점주에게 노출 안 됨)
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("⚠️ 서비스 설정 오류입니다. 운영자에게 문의해주세요.")
        st.stop()

    # 사이드바
    activation_type, extra_cost, desired_margin = render_sidebar()

    # 세션 초기화
    if "results" not in st.session_state:
        st.session_state.results = []
    if "df_compare" not in st.session_state:
        st.session_state.df_compare = None

    # ── 파일 업로드 영역 ──────────────────────────
    st.markdown("### 📂 단가표 파일 업로드")
    st.markdown(
        '<div class="info-box">💡 여러 유통사 파일을 한 번에 올리면 자동으로 비교합니다. '
        '(JPG, PNG, PDF, XLSX, CSV, TXT 지원)</div>',
        unsafe_allow_html=True,
    )

    uploaded_files = st.file_uploader(
        "파일을 드래그하거나 클릭해서 선택하세요",
        type=SUPPORTED_EXTENSIONS,
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        analyze_btn = st.button("🔍 마진 분석 시작", use_container_width=True)
    with col_clear:
        if st.button("🗑️ 초기화", use_container_width=True):
            st.session_state.results = []
            st.session_state.df_compare = None
            st.rerun()

    # ── 분석 실행 ────────────────────────────────
    if analyze_btn:
        if not uploaded_files:
            st.warning("⚠️ 파일을 먼저 업로드해주세요.")
            st.stop()

        client = anthropic.Anthropic(api_key=api_key)
        st.session_state.results = []

        progress_bar = st.progress(0, text="분석 준비 중...")
        total = len(uploaded_files)

        for i, f in enumerate(uploaded_files):
            progress_bar.progress(
                (i + 1) / total,
                text=f"📄 분석 중: {f.name} ({i+1}/{total})"
            )
            with st.spinner(f"  ↳ Claude가 {f.name}을 읽는 중..."):
                try:
                    result = process_uploaded_file(client, f)
                    if result:
                        result["_filename"] = f.name
                        st.session_state.results.append(result)
                    else:
                        st.warning(f"⚠️ {f.name}: 데이터를 추출하지 못했습니다.")
                except Exception as e:
                    st.error(f"❌ {f.name} 처리 오류: {e}")

        progress_bar.empty()

        if st.session_state.results:
            st.session_state.df_compare = build_comparison_df(
                st.session_state.results,
                extra_cost, desired_margin, activation_type
            )
            st.success(f"✅ {len(st.session_state.results)}개 파일 분석 완료!")
        else:
            st.error("분석된 데이터가 없습니다. 파일 형식을 확인해주세요.")

    # ── 결과 표시 ────────────────────────────────
    results = st.session_state.results

    # 인터랙티브: 설정 변경 시 즉시 재계산
    if results and st.session_state.df_compare is not None:
        df = build_comparison_df(results, extra_cost, desired_margin, activation_type)
        st.session_state.df_compare = df

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("### 📊 분석 결과")

        # 요약 카드
        dist_names = [r.get("distributor_name", "?") for r in results]
        carriers = list(set(r.get("carrier", "?") for r in results))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_card("분석된 유통사", f"{len(results)}곳", ", ".join(dist_names[:3]))
        with col2:
            metric_card("비교 통신사", f"{len(carriers)}개", " | ".join(carriers))
        with col3:
            model_count = len(df)
            metric_card("비교 기기 수", f"{model_count}종")
        with col4:
            act_label = "번호이동" if "MNP" in activation_type else "기기변경"
            metric_card("분석 유형", act_label, f"부가비용 -{extra_cost}만원")

        # 유통사별 현황 배지
        st.markdown("**유통사 현황**")
        badge_row = ""
        for r in results:
            name = r.get("distributor_name", "?")
            carrier = r.get("carrier", "?")
            color = CARRIER_COLORS.get(carrier, "#6b7280")
            model_cnt = len(r.get("models", []))
            badge_row += (
                f'<span style="display:inline-block;background:{color}15;border:1px solid {color}40;'
                f'color:{color};border-radius:8px;padding:4px 12px;margin:4px;font-size:0.82rem;font-weight:600;">'
                f'{name} <span style="opacity:0.7">({carrier} · {model_cnt}종)</span></span>'
            )
        st.markdown(badge_row, unsafe_allow_html=True)

        # 비교 테이블
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f"#### 📋 마진 비교표 — {activation_type} 기준")
        st.markdown(
            f'<div class="info-box">희망 마진 <strong>{desired_margin}만원</strong> 기준 / '
            f'부가서비스 공제 <strong>{extra_cost}만원</strong></div>',
            unsafe_allow_html=True,
        )

        # 컬럼 색상 포맷
        def color_cell(val):
            if val == "✅":
                return "background-color: #dcfce7; color: #15803d; font-weight: bold;"
            elif val == "❌":
                return "background-color: #fee2e2; color: #b91c1c; font-weight: bold;"
            elif isinstance(val, (int, float)) and val < 0:
                return "color: #b91c1c;"
            return ""

        styled_df = df.style.applymap(color_cell)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # 최고 유통사 하이라이트
        if "최고유통사" in df.columns:
            best_counts = df["최고유통사"].value_counts()
            st.markdown("**📈 기기별 최고 마진 유통사 집계**")
            best_cols = st.columns(len(best_counts))
            for idx, (dist, cnt) in enumerate(best_counts.items()):
                with best_cols[idx]:
                    st.markdown(f"""
                    <div class="card" style="text-align:center;">
                        <div class="card-title">🏆 {dist}</div>
                        <div class="card-value positive">{cnt}종</div>
                        <div class="card-sub">최고 마진 기기</div>
                    </div>
                    """, unsafe_allow_html=True)

        # 개별 유통사 상세
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("#### 🔎 유통사별 상세 마진 내역")

        tabs = st.tabs([r.get("distributor_name", f"유통사{i+1}") for i, r in enumerate(results)])
        for tab, r in zip(tabs, results):
            with tab:
                unit = r.get("currency_unit", "만원")
                carrier = r.get("carrier", "?")
                act_key = "MNP" if "MNP" in activation_type else "기변"

                rows = []
                for m in r.get("models", []):
                    d = m.get(act_key, {})
                    raw_total = d.get("합계", 0) or 0
                    total_man = normalize_to_man(raw_total, unit)
                    net = total_man - extra_cost

                    rows.append({
                        "모델": m["model"],
                        "액면": d.get("액면", 0), "TAC": d.get("TAC", 0),
                        "마스콜": d.get("마스콜", 0), "특별1": d.get("특별1", 0),
                        "특별2": d.get("특별2", 0), "추지": d.get("추지", 0),
                        "GR": d.get("GR", 0),
                        f"합계({unit})": raw_total,
                        "합계(만원)": round(total_man, 1),
                        "실수령마진": round(net, 1),
                        "충족": "✅" if net >= desired_margin else "❌",
                    })

                if rows:
                    detail_df = pd.DataFrame(rows)
                    color = CARRIER_COLORS.get(carrier, "#6b7280")
                    st.markdown(
                        f'<span style="background:{color}20;color:{color};border-radius:6px;'
                        f'padding:3px 10px;font-size:0.82rem;font-weight:700;">{carrier}</span>',
                        unsafe_allow_html=True,
                    )
                    st.dataframe(
                        detail_df.style.applymap(color_cell),
                        use_container_width=True, hide_index=True
                    )
                else:
                    st.info("데이터가 없습니다.")

        # 다운로드
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown("#### 💾 결과 다운로드")
        excel_bytes = build_excel(results, df)
        today = datetime.now().strftime("%Y%m%d_%H%M")
        col_dl, _ = st.columns([2, 3])
        with col_dl:
            st.download_button(
                label="📥 엑셀 다운로드 (.xlsx)",
                data=excel_bytes,
                file_name=f"마진비교_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    elif not results:
        # 초기 안내
        st.markdown("""
        <div class="card" style="text-align:center;padding:3rem;">
            <div style="font-size:3rem;margin-bottom:1rem;">📂</div>
            <div style="font-size:1.1rem;font-weight:600;color:#374151;">단가표 파일을 업로드해주세요</div>
            <div style="color:#9ca3af;margin-top:0.5rem;font-size:0.9rem;">
                유통사별 파일을 여러 개 올리면 한 번에 비교됩니다
            </div>
        </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
