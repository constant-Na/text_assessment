import streamlit as st
import pandas as pd
import urllib3
import json
import re
import io

# ==========================================
# [1] 데이터 및 함수 설정 영역
# ==========================================

# 한글 품사와 알파벳 라벨의 연결 
pos_mapping = {
    '명사': 'NNG', '대명사': 'NP', '의존명사': 'NNB', '수사': 'NR',
    '동사': 'VV', '보조동사': 'VX', '형용': 'VA', '형용사': 'VA', '보조형용사': 'VX',
    '관형사': 'MM', '부사': 'MAG', '조사': 'JX', '감탄사': 'IC',
    '접사': 'XSN', '품사없음': 'UNK'
}

@st.cache_data
def load_and_process_word_data(file_path='word_data.xlsx'):
    """어휘 등급 데이터를 불러와 1~5등급 리스트로 변환하는 함수"""
    try:
        word_data = pd.read_excel(file_path)
    except FileNotFoundError:
        return None, None, None, None, None
        
    def generate_word_list(grade_data):
        word_list = []
        어깨번호_추가_단어 = grade_data['어휘'] + grade_data['표준동형어번호수정'].astype(str)
        list_zip = list(zip(어깨번호_추가_단어, grade_data['품사']))
        
        for word, pos in list_zip:
            if word == '이다3':
                word_list.append(('이3', 'VCP'))
            elif word == '아니다0':
                word_list.append(('아니0', 'VCN'))
            else:
                if pd.isna(pos): continue
                clean_pos = str(pos).replace(' ', '')
                if clean_pos == '동사형용사':
                    clean_pos = '동사/형용사'
                
                split_tags = clean_pos.split('/')
                for tag in split_tags:
                    eng_tag = pos_mapping.get(tag, 'UNK')
                    if eng_tag in ['VV', 'VA', 'VX']:
                        word = re.sub(r'다(\d*)$', r'\1', str(word))
                    word_list.append((str(word), eng_tag))
        return word_list

    # 등급별 리스트 생성
    w1 = generate_word_list(word_data[word_data['등급'] == '1등급'])
    w2 = generate_word_list(word_data[word_data['등급'] == '2등급'])
    w3 = generate_word_list(word_data[word_data['등급'] == '3등급'])
    w4 = generate_word_list(word_data[word_data['등급'] == '4등급'])
    w5 = generate_word_list(word_data[word_data['등급'] == '5등급'])
    
    return w1, w2, w3, w4, w5

# ==========================================
# [2] 웹 화면 UI 구성
# ==========================================
st.set_page_config(page_title="자동 평가 도구", layout="wide")
st.title("📝 자연어 처리를 활용한 글쓰기 자동 평가")
st.markdown("**강원도 중등 교과교육 역량강화 직무연수** 실습용 도구입니다.")

# ETRI API 설정 (보안을 위해 화면에서 입력받음)
st.sidebar.header("🔑 ETRI API 설정")
access_key = st.sidebar.text_input("ETRI API Access Key를 입력하세요", type="password")

# 어휘 데이터 로드
word_lists = load_and_process_word_data('word_data.xlsx')
if word_lists[0] is None:
    st.error("⚠️ 서버에 'word_data.xlsx' 파일이 없습니다. 파일을 함께 업로드해 주세요.")
    st.stop()
    
word1_list, word2_list, word3_list, word4_list, word5_list = word_lists

# 파일 업로드 컴포넌트
uploaded_file = st.file_uploader("학생들의 글이 정리된 엑셀(.xlsx) 파일을 업로드해 주세요.", type=['xlsx'])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    st.subheader("1. 업로드된 데이터 미리보기")
    st.dataframe(df.head(3))
    
    text_column = st.selectbox("학생들의 글이 포함된 열(Column)을 선택하세요.", df.columns)
    
    if st.button("ETRI API로 어휘 등급 분석 시작"):
        if not access_key:
            st.warning("👈 좌측 사이드바에 ETRI API Access Key를 먼저 입력해 주세요.")
        else:
            with st.spinner("ETRI API와 통신하며 텍스트를 분석하고 있습니다. 잠시만 기다려 주세요..."):
                
                openApiURL = "http://epretx.etri.re.kr:8000/api/WiseNLU"
                analysisCode = "dparse"
                http = urllib3.PoolManager()
                
                result1_list, result2_list, result3_list = [], [], []
                result4_list, result5_list, rank_list = [], [], []
                
                # 프로그레스 바 추가 (분석 진행 상황 시각화)
                progress_bar = st.progress(0)
                total_rows = len(df)
                
                for idx, text in enumerate(df[text_column]):
                    if not isinstance(text, str) or not text.strip():
                        result1_list.append(0); result2_list.append(0); result3_list.append(0)
                        result4_list.append(0); result5_list.append(0); rank_list.append(0)
                        progress_bar.progress((idx + 1) / total_rows)
                        continue

                    requestJson = {
                        "argument": {
                            "text": text,
                            "analysis_code": analysisCode
                        }
                    }

                    try:
                        response = http.request(
                            "POST",
                            openApiURL,
                            headers={"Content-Type": "application/json; charset=UTF-8", "Authorization": access_key},
                            body=json.dumps(requestJson)
                        )
                        
                        morphological_analysis = json.loads(response.data.decode('utf-8'))
                        
                        analyze_result = []
                        for sent in morphological_analysis['return_object']['sentence']:
                            for morp in sent['WSD']:
                                analyze_result.append((morp['text'] + morp['scode'][1:], morp['type']))

                        # 매칭 카운트 계산
                        result1, result2, result3, result4, result5 = [], [], [], [], []
                        for wp in analyze_result:
                            if wp in word1_list: result1.append(wp)
                            elif wp in word2_list: result2.append(wp)
                            elif wp in word3_list: result3.append(wp)
                            elif wp in word4_list: result4.append(wp)
                            elif wp in word5_list: result5.append(wp)

                        total_matched = len(result1) + len(result2) + len(result3) + len(result4) + len(result5)
                        
                        # 분모가 0이 되는 오류(ZeroDivisionError) 방지
                        if total_matched > 0:
                            rank = ((len(result1) * 1) + (len(result2) * 2) + (len(result3) * 3) + 
                                    (len(result4) * 4) + (len(result5) * 5)) / total_matched
                        else:
                            rank = 0

                        result1_list.append(len(result1))
                        result2_list.append(len(result2))
                        result3_list.append(len(result3))
                        result4_list.append(len(result4))
                        result5_list.append(len(result5))
                        rank_list.append(round(rank, 3))
                        
                    except Exception as e:
                        # 통신 오류나 파싱 오류 발생 시 예외 처리
                        result1_list.append(0); result2_list.append(0); result3_list.append(0)
                        result4_list.append(0); result5_list.append(0); rank_list.append(-1)
                        st.error(f"오류 발생 (Row {idx+1}): {str(e)}")
                    
                    # 진행률 업데이트
                    progress_bar.progress((idx + 1) / total_rows)

                # 분석 결과를 DataFrame에 병합
                df['1등급 어휘 개수'] = result1_list
                df['2등급 어휘 개수'] = result2_list
                df['3등급 어휘 개수'] = result3_list
                df['4등급 어휘 개수'] = result4_list
                df['5등급 어휘 개수'] = result5_list
                df['어휘 등급 평균'] = rank_list
                
                st.success("분석이 완료되었습니다!")
                
                st.subheader("2. 분석 결과 확인")
                st.dataframe(df)
                
                # 결과 다운로드
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False, sheet_name='분석결과')
                
                st.download_button(
                    label="📊 분석 결과 엑셀 파일로 다운로드",
                    data=output.getvalue(),
                    file_name="학생글_어휘등급_분석결과.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )