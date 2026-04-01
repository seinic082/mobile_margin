"""
핸드폰 단가표 마진 분석 대시보드
사용법: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import io
import os
import json
import tempfile
from pathlib import Path

# ─────────────────────────────────────────
# 페이지 기본 설정 (반드시 첫 번째 st 호출)
# ─────────────────────────────────────────
st.set_page_config(
    page_title="단가표 마진 분석기",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────
# CSS 커스텀 스타일
# ─────────────────────────────────────────
st.markdown("""
<style>
    .best-badge {
        background: #16a34a;
        color: white;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .section-title {
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 8px;
        color: #1e293b;
    }
    div[data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# 유틸: 안전하게 라이브러리 import
# ─────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_easyocr():
    """EasyOCR 리더를 캐싱해서 한 번만 로드."""
    try:
        import easyocr
        return easyocr.Reader(["ko", "en"], gpu=False)
    except ImportError:
        return None


@st.cache_resource(show_spinner=False)
def get_openai_client(api_key: str):
    """OpenAI 클라이언트 초기화."""
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        return None


# ─────────────────────────────────────────
# 핵심 함수: OCR 텍스트 추출
# ─────────────────────────────────────────
def extract_text_from_image(file_bytes: bytes, reader) -> str:
    """이미지 파일에서 OCR로 텍스트 추출."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        results = reader.readtext(tmp_path, detail=0, paragraph=True)
        return "\n".join(results)
    finally:
        os.unlink(tmp_path)


def extract_text_from_pdf(file_bytes: bytes, reader) -> str:
    """PDF -> 이미지 변환 후 OCR 텍스트 추출."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "[오류] PyMuPDF(fitz) 라이브러리가 설치되지 않았습니다."

    texts = []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        doc = fitz.open(tmp_path)
        for page_num in range(min(len(doc), 5)):  # 최대 5페이지
            page = doc[page_num]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("jpeg")
            page_text = extract_text_from_image(img_bytes, reader)
            texts.append(f"[{page_num+1}페이지]\n{page_text}")
        doc.close()
    finally:
        os.unlink(tmp_path)
    return "\n\n".join(texts)


def extract_text_from_xlsx(file_bytes: bytes) -> str:
    """엑셀 파일에서 텍스트 추출 (OCR 불필요)."""
    df = pd.read_excel(io.BytesIO(file_bytes), header=None)
    return df.to_string(index=False)


# ─────────────────────────────────────────
# 핵심 함수: LLM으로 마진 데이터 파싱
# ─────────────────────────────────────────
PARSE_PROMPT = """
너는 핸드폰 유통사 단가표를 분석하는 전문가야.
아래 OCR 텍스트에서 각 기기별로 다음 항목을 추출해줘:

- 기기명 (model)
- 출고가 (msrp): 숫자만
- 공시지원금 (subsidy): 숫자만, 없으면 0
- 리베이트 (rebate): 숫자만, 없으면 0
- 판매장려금 (incentive): 숫자만, 없으면 0
- 통신사 (carrier): SKT/KT/LGU+ 중 하나, 모르면 "미상"

결과는 반드시 아래 JSON 배열 형식으로만 응답해. 다른 말은 하지 마.
[
  {{
    "model": "갤럭시 S25",
    "msrp": 1350000,
    "subsidy": 200000,
    "rebate": 150000,
    "incentive": 50000,
    "carrier": "SKT"
  }}
]

OCR 텍스트:
{ocr_text}
"""


def parse_margin_data_with_llm(ocr_text: str, client, model: str = "gpt-4o") -> list:
    """LLM을 통해 OCR 텍스트에서 마진 데이터 파싱."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": PARSE_PROMPT.format(ocr_text=ocr_text[:6000])}
            ],
            temperature=0,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        # JSON 펜스 제거
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        st.error(f"LLM 응답 파싱 오류: {e}")
        return []
    except Exception as e:
        st.error(f"OpenAI API 오류: {e}")
        return []


# ─────────────────────────────────────────
# 핵심 함수: 마진 계산
# ─────────────────────────────────────────
def calculate_margin(
    records: list,
    distributor_name: str,
    target_margin: int = 0,
    addon_cost: int = 0,
) -> pd.DataFrame:
    """
    마진 계산 공식:
    실수익 = 리베이트 + 판매장려금 - 부가서비스비용
    순마진 = 실수익 - 희망마진 (양수면 목표 달성 가능)
    """
    rows = []
    for r in records:
        rebate = int(r.get("rebate", 0))
        incentive = int(r.get("incentive", 0))
        subsidy = int(r.get("subsidy", 0))
        msrp = int(r.get("msrp", 0))

        gross_profit = rebate + incentive - addon_cost
        net_margin = gross_profit - target_margin
        margin_rate = round(gross_profit / msrp * 100, 1) if msrp > 0 else 0

        rows.append({
            "유통사": distributor_name,
            "기기명": r.get("model", "미상"),
            "통신사": r.get("carrier", "미상"),
            "출고가": msrp,
            "공시지원금": subsidy,
            "리베이트": rebate,
            "판매장려금": incentive,
            "부가서비스비": addon_cost,
            "실수익": gross_profit,
            "순마진": net_margin,
            "마진율(%)": margin_rate,
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────
# 유틸: 엑셀 다운로드 버퍼 생성
# ─────────────────────────────────────────
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="마진비교")
        ws = writer.sheets["마진비교"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)
    return buf.getvalue()


# ─────────────────────────────────────────
# 더미 데이터 생성 (API 없을 때 데모용)
# ─────────────────────────────────────────
def generate_demo_data(distributor_name: str, target_margin: int, addon_cost: int) -> pd.DataFrame:
    import random
    random.seed(hash(distributor_name) % 999)
    models = [
        ("갤럭시 S25", "SKT", 1350000),
        ("갤럭시 S25+", "KT", 1550000),
        ("갤럭시 A55", "LGU+", 650000),
        ("아이폰 16", "SKT", 1350000),
        ("아이폰 16 Pro", "KT", 1650000),
    ]
    records = []
    for model, carrier, msrp in models:
        records.append({
            "model": model,
            "carrier": carrier,
            "msrp": msrp,
            "subsidy": random.randint(100000, 300000),
            "rebate": random.randint(80000, 200000),
            "incentive": random.randint(20000, 80000),
        })
    return calculate_margin(records, distributor_name, target_margin, addon_cost)


# ─────────────────────────────────────────
# 데모 분석 실행 함수
# ─────────────────────────────────────────
def run_demo_analysis(target_margin: int, addon_cost: int):
    """파일 없이 데모 분석 실행."""
    demo_distributors = ["A유통", "B유통", "C유통"]
    all_dfs = []

    with st.spinner("🧪 데모 분석 실행 중..."):
        for name in demo_distributors:
            df = generate_demo_data(name, target_margin, addon_cost)
            all_dfs.append(df)

    combined_df = pd.concat(all_dfs, ignore_index=True)
    display_results(combined_df)


# ─────────────────────────────────────────
# 결과 표시 함수 (재사용 가능)
# ─────────────────────────────────────────
def display_results(combined_df: pd.DataFrame):
    """통합 비교 결과를 화면에 표시."""
    st.markdown('<p class="section-title">🏆 유통사별 통합 비교</p>', unsafe_allow_html=True)

    summary_df = (
        combined_df.groupby("유통사")
        .agg(
            평균실수익=("실수익", "mean"),
            평균순마진=("순마진", "mean"),
            평균마진율=("마진율(%)", "mean"),
            분석기기수=("기기명", "count"),
            목표달성건수=("순마진", lambda x: (x >= 0).sum()),
        )
        .reset_index()
        .sort_values("평균실수익", ascending=False)
    )
    summary_df["목표달성률(%)"] = (
        summary_df["목표달성건수"] / summary_df["분석기기수"] * 100
    ).round(1)

    best_distributor = summary_df.iloc[0]["유통사"]

    # 추천 배너
    st.markdown(f"""
    <div style="background:#f0fdf4; border:1px solid #86efac; border-radius:10px;
                padding:16px; margin:8px 0 16px;">
        <span style="font-size:18px; font-weight:600; color:#15803d;">
            🏆 추천 유통사: {best_distributor}
        </span>
        <span style="margin-left:12px; font-size:14px; color:#166534;">
            평균 실수익 {int(summary_df.iloc[0]['평균실수익']):,}원 &nbsp;·&nbsp;
            마진율 {summary_df.iloc[0]['평균마진율']:.1f}%
        </span>
    </div>
    """, unsafe_allow_html=True)

    # 유통사별 메트릭 카드
    cols = st.columns(len(summary_df))
    for col, (_, row) in zip(cols, summary_df.iterrows()):
        is_best = row["유통사"] == best_distributor
        with col:
            label = f"{'🥇 ' if is_best else ''}{row['유통사']}"
            st.metric(
                label=label,
                value=f"{int(row['평균실수익']):,}원",
                delta=f"순마진 {int(row['평균순마진']):,}원",
            )

    # 요약 테이블
    st.dataframe(
        summary_df.style
            .highlight_max(subset=["평균실수익", "평균순마진", "목표달성률(%)"], color="#dcfce7")
            .format({
                "평균실수익": "{:,.0f}",
                "평균순마진": "{:,.0f}",
                "평균마진율": "{:.1f}%",
                "목표달성률(%)": "{:.1f}%",
            }),
        use_container_width=True,
        hide_index=True,
    )

    # 전체 원시 데이터
    with st.expander("📋 전체 원시 데이터 보기"):
        st.dataframe(
            combined_df.style.format({
                "출고가": "{:,.0f}", "공시지원금": "{:,.0f}",
                "리베이트": "{:,.0f}", "판매장려금": "{:,.0f}",
                "부가서비스비": "{:,.0f}", "실수익": "{:,.0f}",
                "순마진": "{:,.0f}", "마진율(%)": "{:.1f}%",
            }),
            use_container_width=True,
            hide_index=True,
        )

    # 다운로드 버튼
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="⬇️ 전체 비교표 다운로드 (Excel)",
            data=to_excel_bytes(combined_df),
            file_name="단가표_마진분석_전체.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )
    with c2:
        st.download_button(
            label="⬇️ 유통사 요약 다운로드 (Excel)",
            data=to_excel_bytes(summary_df),
            file_name="단가표_마진분석_요약.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ─────────────────────────────────────────
# 메인 앱 UI
# ─────────────────────────────────────────
def main():
    # 헤더
    st.title("📱 단가표 마진 분석 대시보드")
    st.caption("유통사별 단가표를 업로드하면 리베이트·장려금 기준으로 최고 수익 유통사를 분석해 드립니다.")
    st.divider()

    # ── 사이드바 ──
    with st.sidebar:
        st.header("⚙️ 분석 설정")

        st.subheader("1. Anthropic API Key")
        api_key = st.text_input(
            "API 키",
            type="password",
            placeholder="sk-...",
            help="Anthropic 콘솔에서 발급한 키를 입력하세요",
        )
        use_demo = st.checkbox("🧪 데모 데이터로 테스트", value=(not bool(api_key)))

        st.divider()
        st.subheader("2. 마진 조건 입력")
        target_margin = st.number_input(
            "희망 마진 (원)",
            min_value=0, max_value=500000,
            value=50000, step=5000, format="%d",
            help="대당 최소 확보하고 싶은 마진",
        )
        addon_cost = st.number_input(
            "부가서비스 비용 (원)",
            min_value=0, max_value=200000,
            value=0, step=5000, format="%d",
            help="개통 시 부과되는 고정 비용",
        )

        st.divider()
        st.caption(
            "💡 **실수익** = 리베이트 + 판매장려금 - 부가서비스비\n\n"
            "💡 **순마진** = 실수익 - 희망마진\n\n"
            "순마진 ≥ 0 이면 목표 달성 가능"
        )

    # ── 메인: 파일 업로드 ──
    st.markdown('<p class="section-title">📂 단가표 파일 업로드</p>', unsafe_allow_html=True)
    st.info(
        "유통사별로 파일을 업로드하세요. 파일명이 유통사명으로 사용됩니다. "
        "여러 파일을 동시에 올리면 비교 분석됩니다.",
        icon="ℹ️"
    )

    uploaded_files = st.file_uploader(
        "단가표 파일 선택",
        type=["jpg", "jpeg", "png", "pdf", "xlsx", "xls"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    # 파일 없을 때
    if not uploaded_files:
        st.markdown("""
        <div style="border:2px dashed #cbd5e1; border-radius:12px; padding:48px 24px;
                    text-align:center; color:#64748b; margin:16px 0;">
            <div style="font-size:40px; margin-bottom:12px;">📄</div>
            <div style="font-size:16px; font-weight:500;">
                파일을 여기에 드래그 앤 드롭하거나 위 버튼으로 선택하세요
            </div>
            <div style="font-size:13px; margin-top:8px;">JPG · PNG · PDF · XLSX 지원</div>
        </div>
        """, unsafe_allow_html=True)

        if use_demo:
            st.divider()
            st.markdown("**🧪 데모 모드**: 파일 없이 샘플 데이터로 전체 기능을 미리 볼 수 있습니다.")
            if st.button("▶ 데모 분석 실행", type="primary", use_container_width=True):
                run_demo_analysis(target_margin, addon_cost)
        return

    # ── 분석 실행 ──
    st.divider()
    st.markdown(
        f'<p class="section-title">📊 파일별 분석 결과 '
        f'(희망마진 {target_margin:,}원 / 부가서비스 {addon_cost:,}원)</p>',
        unsafe_allow_html=True,
    )

    all_dfs = []
    ocr_reader = None

    needs_ocr = any(
        f.name.lower().endswith((".jpg", ".jpeg", ".png", ".pdf"))
        for f in uploaded_files
    )

    if needs_ocr and not use_demo:
        with st.spinner("🔍 EasyOCR 모델 로딩 중... (최초 1회 1~2분 소요)"):
            ocr_reader = load_easyocr()
        if ocr_reader is None:
            st.error("EasyOCR 로드 실패. `pip install easyocr` 확인 필요.")
            return

    openai_client = None
    if not use_demo and api_key:
        openai_client = get_openai_client(api_key)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, uploaded_file in enumerate(uploaded_files):
        distributor_name = Path(uploaded_file.name).stem
        file_bytes = uploaded_file.read()
        ext = Path(uploaded_file.name).suffix.lower()

        status_text.text(f"⏳ [{i+1}/{len(uploaded_files)}] '{distributor_name}' 분석 중...")

        with st.expander(f"📄 {uploaded_file.name}", expanded=(i == 0)):
            if use_demo or not openai_client:
                df = generate_demo_data(distributor_name, target_margin, addon_cost)
                st.caption("⚠️ 데모 데이터로 표시됩니다.")
            else:
                # 실제 OCR + LLM
                if ext in (".jpg", ".jpeg", ".png"):
                    ocr_text = extract_text_from_image(file_bytes, ocr_reader)
                elif ext == ".pdf":
                    ocr_text = extract_text_from_pdf(file_bytes, ocr_reader)
                elif ext in (".xlsx", ".xls"):
                    ocr_text = extract_text_from_xlsx(file_bytes)
                else:
                    st.warning(f"지원하지 않는 파일 형식: {ext}")
                    continue

                with st.spinner("🤖 LLM 파싱 중..."):
                    records = parse_margin_data_with_llm(ocr_text, openai_client)

                if not records:
                    st.warning("데이터 추출 실패. OCR 원문을 확인하세요.")
                    with st.expander("OCR 원문 보기"):
                        st.text(ocr_text[:2000])
                    progress_bar.progress((i + 1) / len(uploaded_files))
                    continue

                df = calculate_margin(records, distributor_name, target_margin, addon_cost)

            st.dataframe(
                df.style
                    .highlight_max(subset=["실수익", "순마진"], color="#dcfce7")
                    .highlight_min(subset=["실수익", "순마진"], color="#fee2e2")
                    .format({
                        "출고가": "{:,.0f}", "공시지원금": "{:,.0f}",
                        "리베이트": "{:,.0f}", "판매장려금": "{:,.0f}",
                        "부가서비스비": "{:,.0f}", "실수익": "{:,.0f}",
                        "순마진": "{:,.0f}", "마진율(%)": "{:.1f}%",
                    }),
                use_container_width=True,
                hide_index=True,
            )
            all_dfs.append(df)

        progress_bar.progress((i + 1) / len(uploaded_files))

    status_text.text("✅ 분석 완료!")

    if not all_dfs:
        st.warning("분석된 파일이 없습니다.")
        return

    # ── 통합 비교 결과 표시 ──
    st.divider()
    display_results(pd.concat(all_dfs, ignore_index=True))


if __name__ == "__main__":
    main()
