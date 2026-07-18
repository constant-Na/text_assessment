import streamlit as st
import pandas as pd
import requests
import io
from kiwipiepy import Kiwi
from lexicalrichness import LexicalRichness

# ==========================================
# [0] 사전 준비 및 모델 초기화
# ==========================================
# 형태소 분석기 Kiwi 초기화 (앱 실행 시 한 번만 로드)
@st.cache_resource
def load_kiwi():
    return Kiwi()

kiwi = load_kiwi()

# 단어 등급 데이터 로드 (서버 폴더에 word_data.xlsx가 있다고 가정)
# 실제 환경에서는 파일 경로나 이름을 선생님의 데이터에 맞게 수정해 주세요.
@st.cache_data
def load_word_data():
    try:
        # 데이터에 '등급', '어휘', '표준동형어번호', '품사' 열이 존재한다고 가정
        return pd.read_excel('word_data.xlsx')
    except Exception as e:
        st.warning("word_data.xlsx 파일을 찾을 수 없어 어휘 등급 분석이 제한될 수 있습니다.")
        return pd.DataFrame(columns=['등급', '어휘', '표준동형어번호', '품사'])

word_df = load_word_data()

# ==========================================
# [1] 분석 함수 정의
# ==========================================
def calculate_diversity(text):
    """Kiwi를 활용한 TTR 및 MATTR 계산 함수"""
    if not isinstance(text, str) or not text.strip():
        return 0.0, 0.0
    
    result = []
    result_for_ld = []
    
    # 형태소 분석 및 토큰 추출
    for token in kiwi.tokenize(text):
        result.append((token.form, token.tag))
        result_for_ld.append(f"{token.form}/{token.tag}")
    
    token_count = len(result)
    type_count = len(set(result)) # 중복 제거
    
    # 1. TTR 계산
    ttr = type_count / token_count if token_count > 0 else 0.0
    
    # 2. MATTR 계산
    result_for_ld_str = " ".join(result_for_ld)
    lex = LexicalRichness(result_for_ld_str, tokenizer=lambda x: x.split())
    
    mattr = 0.0
    try:
        # 텍스트의 총 토큰 수가 window_size(50) 이상일 때만 계산 (에러 방지)
        if token_count >= 50:
            mattr = lex.mattr(window_size=50)
        else:
            mattr = ttr # 50단어 미만일 경우 기본 TTR로 대체
    except Exception:
        pass
        
    return round(ttr, 4), round(mattr, 4)

def analyze_with_etri(text, access_key):
    """ETRI API를 활용한 형태소 분석 및 어휘 등급 산출 함수"""
    if not isinstance(text, str) or not text.strip() or not access_key:
        return None
        
    openApiURL = "http://aiopen.etri.re.kr:8000/WiseNLU"
    requestJson = {
        "argument": {
            "text": text,
            "analysis_code": "morp" # 형태소 분석 코드
        }
    }
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Authorization": access_key
    }
    
    try:
        response = requests.post(openApiURL, headers=headers, json=requestJson)
        if response.status_code != 200:
            return "API 통신 오류"
            
        data = response.json()
        sentences = data.get("return_object", {}).get("sentence", [])
        
        grade_sum = 0
        match_count = 0
        
        # ETRI 분석 결과에서 형태소 추출 후 word_df와 대조
        for sentence in sentences:
            for morp in sentence.get("morp", []):
                lemma = morp.get("lemma")
                tag = morp.get("type")
                
                # word_data에서 어휘와 품사가 일치하는 항목 검색 (동형어 번호는 생략하거나 조건에 추가 가능)
                matched_rows = word_df[(word_df['어휘'] == lemma) & (word_df['품사'] == tag)]
                
                if not matched_rows.empty:
                    # 매칭된 단어의 등급 합산 (등급이 숫자로 되어 있다고 가정)
                    grade = matched_rows.iloc[0]['등급']
                    if isinstance(grade, (int, float)):
                        grade_sum += grade
                        match_count += 1
                        
        # 평균 어휘 등급 산출
        avg_grade = grade_sum / match_count if match_count > 0 else 0
        return round(avg_grade, 2)
        
    except Exception as e:
        return f"분석 실패: {str(e)}"

# ==========================================
# [2] 웹 화면 UI 구성
# ==========================================
st.set_page_config(page_title="자동 평가 도구", layout="wide")

st.title("📝 자연어 처리를 활용한 글쓰기 자동 평가")
st.markdown("**강원도 중등 교과교육 역량강화 직무연수** 실습용 웹 애플리케이션입니다.")

# ETRI API 키 입력 (사이드바 또는 메인 화면)
st.info("💡 ETRI API를 활용한 어휘 등급 분석을 위해 발급받은 API 키를 입력해 주세요.")
etri_key = st.text_input("ETRI API Key", type="password", placeholder="ETRI API 키를 붙여넣으세요.")

# 파일 업로드 컴포넌트
uploaded_file = st.file_uploader("학생들의 글이 정리된 엑셀(.xlsx) 파일을 업로드해 주세요.", type=['xlsx', 'csv'])

if uploaded_file is not None:
    # 확장자에 따른 파일 읽기
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
        
    st.subheader("1. 업로드된 데이터")
    st.dataframe(df.head())
    
    # 텍스트 열 선택
    text_column = st.selectbox("학생들의 작문 텍스트가 포함된 열(Column)을 선택하세요.", df.columns)
    
    if st.button("언어 자질 분석 시작하기"):
        if not etri_key:
            st.warning("ETRI API 키가 입력되지 않아 어휘 다양성(Kiwi)만 분석됩니다.")
            
        with st.spinner("텍스트를 분석하고 있습니다. 잠시만 기다려 주세요..."):
            
            # [3] 데이터 분석 실행
            # 1. TTR 및 MATTR 계산 (Kiwi 활용)
            ttr_mattr_results = df[text_column].apply(calculate_diversity)
            df['TTR (어휘 다양성)'] = [res[0] for res in ttr_mattr_results]
            df['MATTR (이동평균 어휘 다양성)'] = [res[1] for res in ttr_mattr_results]
            
            # 2. 어휘 등급 평균 계산 (ETRI 활용)
            if etri_key:
                df['평균 어휘 등급 (ETRI)'] = df[text_column].apply(lambda x: analyze_with_etri(x, etri_key))
            
            st.success("분석이 성공적으로 완료되었습니다!")
            
            # 결과 출력
            st.subheader("2. 분석 결과 확인")
            st.dataframe(df)
            
            # [4] 결과 다운로드
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='분석결과')
            
            st.download_button(
                label="📊 분석 결과 엑셀 파일로 다운로드",
                data=output.getvalue(),
                file_name="학생글_분석결과_언어자질.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )