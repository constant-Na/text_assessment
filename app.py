import streamlit as st
import pandas as pd
import urllib3
from urllib3.util.retry import Retry
import json
import re
import io
from kiwipiepy import Kiwi
from lexicalrichness import LexicalRichness

# ==========================================
# [1] 데이터 및 분석 함수 설정 영역
# ==========================================

kiwi = Kiwi()

pos_mapping = {
    '명사': 'NNG', '대명사': 'NP', '의존명사': 'NNB', '수사': 'NR',
    '동사': 'VV', '보조동사': 'VX', '형용': 'VA', '형용사': 'VA', '보조형용사': 'VX',
    '관형사': 'MM', '부사': 'MAG', '조사': 'JX', '감탄사': 'IC',
    '접사': 'XSN', '품사없음': 'UNK'
}

@st.cache_data
def load_and_process_word_data(file_path='word_data.xlsx'):
    try:
        word_data = pd.read_excel(file_path)
    except FileNotFoundError:
        return None, None, None, None, None
        
    def generate_word_set(grade_data):
        word_list = []
        어깨번호 = grade_data['표준동형어번호수정'].astype('Int64').astype(str).replace('<NA>', '')
        어깨번호_추가_단어 = grade_data['어휘'] + 어깨번호
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
                    w = re.sub(r'다(\d*)$', r'\1', str(word)) if eng_tag in ['VV', 'VA', 'VX'] else str(word)
                    word_list.append((w, eng_tag))
        
        return set(word_list)

    w1 = generate_word_set(word_data[word_data['등급'] == '1등급'])
    w2 = generate_word_set(word_data[word_data['등급'] == '2등급'])
    w3 = generate_word_set(word_data[word_data['등급'] == '3등급'])
    w4 = generate_word_set(word_data[word_data['등급'] == '4등급'])
    w5 = generate_word_set(word_data[word_data['등급'] == '5등급'])
    return w1, w2, w3, w4, w5

# ==========================================
# [2] 어휘 다양성 및 통사적 복잡도 계산 함수 영역
# ==========================================

def calculate_diversity(text):
    if not isinstance(text, str) or not text.strip():
        return 0.0, 0.0
    
    tokens = [token.form for token in kiwi.tokenize(text)]
    if not tokens: return 0.0, 0.0
        
    tokenized_text = " ".join(tokens)
    lex = LexicalRichness(tokenized_text)
    ttr = lex.ttr
    mattr = lex.mattr(window_size=50) if len(tokens) >= 50 else ttr
    return round(ttr, 3), round(mattr, 3)

def is_real_VP(morp_result):
    # 불규칙(-I), 규칙(-R) 기호 먼저 제거
    clean_morp = str(morp_result).replace('-R', '').replace('-I', '')
    tags = set(re.findall(r'/([A-Z]+)', clean_morp))
    return ('VX' not in tags or 'VV' in tags or 'VA' in tags or 'VCP' in tags or 'VCN' in tags)

def calc_embedding_logic(dep, sentence, dep_id2label, clause_list):
    score = 0
    if len(dep.get('mod', [])) == 0:
        score += 1
    else:
        score += 2
        pre_add2_elements = [p['label'] for sub in dep['mod'] for p in sentence.get('dependency', []) if int(sub) == int(p['id'])]
        for clause in clause_list:
            score += pre_add2_elements.count(clause)
            
        for num, elem in zip(dep['mod'], pre_add2_elements):
            if elem in ['VP', 'VNP', 'VP_PRN', 'VNP_PRN', 'VP_SBJ', 'VNP_SBJ', 'VP_OBJ', 'VNP_OBJ', 'VP_CNJ', 'VNP_CNJ', 'VP_MOD', 'VNP_MOD', 'VP_AJT', 'VNP_AJT', 'VP_CMP', 'VNP_CMP']:
                for x in sentence.get('dependency', []):
                    if int(num) == int(x['id']):
                        pre_pre_add2_elements = [dep_id2label.get(int(n), '') for n in x.get('mod', [])]
                        if sum(pre_pre_add2_elements.count(lbl) for lbl in ['VP_SBJ', 'VNP_SBJ', 'X_SBJ', 'NP_SBJ']) >= 2:
                            score += 1
    return score

def calculate_syntactic_complexity(sentences_data):
    """전체 텍스트의 통사적 복잡도를 산출하고 문장 수로 평균을 냅니다."""
    num_sentences = len(sentences_data)
    if num_sentences == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
        
    total_basic = total_add1 = total_add2 = total_add3 = 0
    clause_list = ['VP_SBJ', 'VNP_SBJ', 'VP_OBJ', 'VNP_OBJ', 'VP_CNJ', 'VNP_CNJ', 'VP_MOD', 'VNP_MOD', 'VP_AJT', 'VNP_AJT', 'VP_CMP', 'VNP_CMP']

    for sentence in sentences_data:
        dependency = sentence.get('dependency', [])
        morp_eval = sentence.get('morp_eval', [])
        dep_id2label = {int(dep['id']): dep['label'] for dep in dependency}
        
        # 1. 기본 형식
        basic_score = 0
        for morp, dep in zip(morp_eval, dependency):
            if ('VP' in dep['label']) or ('VNP' in dep['label']):
                if is_real_VP(morp.get('result', '')):
                    basic_elements = [dep_id2label.get(int(sub), '') for sub in dep.get('mod', [])]
                    basic_score_per_clause = 1
                    if any(x in basic_elements for x in ['VP_OBJ', 'NP_OBJ', 'X_OBJ', 'VNP_OBJ']): basic_score_per_clause += 1
                    if any(x in basic_elements for x in ['AP_CMP', 'X_CMP', 'NP_CMP', 'VP_CMP', 'VNP_CMP']): basic_score_per_clause += 1
                    basic_score += basic_score_per_clause
        if basic_score > 20: basic_score = 20
        total_basic += basic_score

        # 2. 수식 구조
        add1_score = 0
        for dep in dependency:
            if dep['label'] in ['NP_MOD', 'X_MOD', 'DP', 'NP_AJT', 'AP_AJT', 'X_AJT', 'NP_INT', 'IP']: add1_score += 1
            if dep['label'] == 'AP':
                if dep.get('text', '') not in ['없이', '달리', '같이']: add1_score += 1
                elif len(dep.get('mod', [])) == 0: add1_score += 1
            if dep['label'] in ['NP_SBJ', 'NP_OBJ', 'NP_CMP', 'NP_MOD', 'NP_CNJ', 'NP', 'NP_AJT', 'NP_INT']:
                add1_score += [dep_id2label.get(int(x), '') for x in dep.get('mod', [])].count('NP')
        if add1_score >= 14: add1_score = 14
        total_add1 += (add1_score / 2)

        # 3. 내포 구조
        add2_score = 0
        for morp, dep in zip(morp_eval, dependency):
            label = dep['label']
            if label in ['VP_SBJ', 'VNP_SBJ', 'VP_OBJ', 'VNP_OBJ', 'VP_CNJ', 'VNP_CNJ', 'VP_CMP', 'VNP_CMP', 'VP_MOD', 'VNP_MOD', 'VP_AJT', 'VNP_AJT']:
                add2_score += calc_embedding_logic(dep, sentence, dep_id2label, clause_list)
            
            if label == 'AP' and dep.get('text', '') in ['달리', '없이', '같이'] and len(dep.get('mod', [])) >= 1:
                add2_score += calc_embedding_logic(dep, sentence, dep_id2label, clause_list)
            
            if label in clause_list:
                pre_add2_elements = [p['label'] for sub in dep.get('mod', []) for p in dependency if int(sub) == int(p['id'])]
                if sum(pre_add2_elements.count(lbl) for lbl in ['VP_SBJ', 'VNP_SBJ', 'X_SBJ', 'NP_SBJ']) >= 2:
                    add2_score += 2
                    for clause in clause_list: add2_score += pre_add2_elements.count(clause)
                    for num, elem in zip(dep.get('mod', []), pre_add2_elements):
                        if elem in clause_list:
                            for x in dependency:
                                if int(num) == int(x['id']):
                                    pre_pre_add2_elements = [dep_id2label.get(int(n), '') for n in x.get('mod', [])]
                                    if sum(pre_pre_add2_elements.count(lbl) for lbl in ['VP_SBJ', 'VNP_SBJ', 'X_SBJ', 'NP_SBJ']) >= 2: add2_score += 1
        if add2_score > 17: add2_score = 17
        total_add2 += add2_score

        # 4. 접속 구조
        add3_score = 0
        for num, (morp, dep) in enumerate(zip(morp_eval, dependency)):
            if (dep['label'] in ['VP', 'VNP', 'VP_PRN', 'VNP_PRN']) and (dep.get('head') != -1):
                if is_real_VP(morp.get('result', '')):
                    if num < len(morp_eval) - 1:
                        next_morp = morp_eval[num+1].get('result', '')
                        # 불규칙(-I), 규칙(-R) 기호 제거
                        clean_next_morp = str(next_morp).replace('-R', '').replace('-I', '')
                        next_tags = set(re.findall(r'/([A-Z]+)', clean_next_morp))
                        if ('VX' in next_tags) and not any(t in next_tags for t in ['VV', 'VA', 'VCP', 'VCN']):
                            if (dependency[num+1]['label'] in ['VP', 'VNP', 'VP_PRN', 'VNP_PRN']) and (dependency[num+1].get('head') != -1):
                                add3_score += 1
                        else:
                            add3_score += 1
        if add3_score > 7: add3_score = 7
        total_add3 += add3_score

    # [수정] 합산된 총점을 문장 수로 나누어 평균 계산
    avg_basic = total_basic / num_sentences
    avg_add1 = total_add1 / num_sentences
    avg_add2 = total_add2 / num_sentences
    avg_add3 = total_add3 / num_sentences
    avg_sum = avg_basic + avg_add1 + avg_add2 + avg_add3

    return round(avg_basic, 3), round(avg_add1, 3), round(avg_add2, 3), round(avg_add3, 3), round(avg_sum, 3)

# ==========================================
# [3] 웹 화면 UI 구성 및 메인 실행부
# ==========================================
st.set_page_config(page_title="자동 평가 도구", layout="wide")
st.title("📝 자연어 처리를 활용한 글쓰기 자동 평가")
st.markdown("**강원도 중등 교과교육 역량강화 직무연수** 실습용 도구입니다.")

st.sidebar.header("🔑 ETRI API 설정")
access_key = st.sidebar.text_input("ETRI API Access Key를 입력하세요", type="password")

word_sets = load_and_process_word_data('word_data.xlsx')
if word_sets[0] is None:
    st.error("⚠️ 서버에 'word_data.xlsx' 파일이 없습니다. 파일을 함께 업로드해 주세요.")
    st.stop()
    
word1_set, word2_set, word3_set, word4_set, word5_set = word_sets

uploaded_file = st.file_uploader("학생들의 글이 정리된 엑셀(.xlsx) 파일을 업로드해 주세요.", type=['xlsx'])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    st.subheader("1. 업로드된 데이터 미리보기")
    st.dataframe(df.head(3))
    
    text_column = st.selectbox("학생들의 글이 포함된 열(Column)을 선택하세요.", df.columns)
    
    if st.button("자동 평가 분석 시작"):
        if not access_key:
            st.warning("👈 좌측 사이드바에 ETRI API Access Key를 먼저 입력해 주세요.")
        else:
            with st.spinner("1/2: 어휘 다양성(TTR/MATTR)을 계산하고 있습니다..."):
                ttr_mattr_results = df[text_column].apply(calculate_diversity)
                df['TTR (어휘 다양성)'] = [res[0] for res in ttr_mattr_results]
                df['MATTR (이동평균 어휘 다양성)'] = [res[1] for res in ttr_mattr_results]

            with st.spinner("2/2: ETRI API와 통신하며 어휘 등급 및 통사적 복잡도를 분석하고 있습니다..."):
                openApiURL = "http://epretx.etri.re.kr:8000/api/WiseNLU"
                analysisCode = "dparse"
                
                retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
                http = urllib3.PoolManager(retries=retries, timeout=urllib3.Timeout(connect=5.0, read=30.0))
                
                r1_list, r2_list, r3_list, r4_list, r5_list, rank_list = [], [], [], [], [], []
                syn_basic, syn_add1, syn_add2, syn_add3, syn_sum = [], [], [], [], []
                
                progress_bar = st.progress(0)
                total_rows = len(df)
                
                for idx, text in enumerate(df[text_column]):
                    if not isinstance(text, str) or not text.strip():
                        r1_list.append(0); r2_list.append(0); r3_list.append(0); r4_list.append(0); r5_list.append(0); rank_list.append(0)
                        syn_basic.append(0); syn_add1.append(0); syn_add2.append(0); syn_add3.append(0); syn_sum.append(0)
                        progress_bar.progress((idx + 1) / total_rows)
                        continue

                    requestJson = {"argument": {"text": text, "analysis_code": analysisCode}}

                    try:
                        response = http.request(
                            "POST", openApiURL, 
                            headers={"Content-Type": "application/json; charset=UTF-8", "Authorization": access_key}, 
                            body=json.dumps(requestJson)
                        )
                        morphological_analysis = json.loads(response.data.decode('utf-8'))
                        sentences_data = morphological_analysis.get('return_object', {}).get('sentence', [])
                        
                        # [A] 어휘 등급 매칭
                        analyze_result = []
                        for sent in sentences_data:
                            for morp in sent.get('WSD', []):
                                # 불규칙(-I), 규칙(-R) 기호 제거 후 사전에 매핑
                                clean_type = morp['type'].replace('-R', '').replace('-I', '')
                                analyze_result.append((morp['text'] + morp['scode'][1:], clean_type))

                        count1 = count2 = count3 = count4 = count5 = 0
                        for wp in analyze_result:
                            if wp in word1_set: count1 += 1
                            elif wp in word2_set: count2 += 1
                            elif wp in word3_set: count3 += 1
                            elif wp in word4_set: count4 += 1
                            elif wp in word5_set: count5 += 1

                        total_matched = count1 + count2 + count3 + count4 + count5
                        rank = ((count1 * 1) + (count2 * 2) + (count3 * 3) + (count4 * 4) + (count5 * 5)) / total_matched if total_matched > 0 else 0

                        r1_list.append(count1); r2_list.append(count2); r3_list.append(count3)
                        r4_list.append(count4); r5_list.append(count5); rank_list.append(round(rank, 3))
                        
                        # [B] 통사적 복잡도 계산
                        t_basic, t_add1, t_add2, t_add3, t_sum = calculate_syntactic_complexity(sentences_data)
                        syn_basic.append(t_basic); syn_add1.append(t_add1); syn_add2.append(t_add2); syn_add3.append(t_add3); syn_sum.append(t_sum)
                        
                    except Exception as e:
                        r1_list.append(0); r2_list.append(0); r3_list.append(0); r4_list.append(0); r5_list.append(0); rank_list.append(-1)
                        syn_basic.append(0); syn_add1.append(0); syn_add2.append(0); syn_add3.append(0); syn_sum.append(0)
                        st.error(f"오류 발생 (Row {idx+1}): {str(e)}")
                    
                    progress_bar.progress((idx + 1) / total_rows)

                df['1등급 어휘 개수'] = r1_list; df['2등급 어휘 개수'] = r2_list; df['3등급 어휘 개수'] = r3_list
                df['4등급 어휘 개수'] = r4_list; df['5등급 어휘 개수'] = r5_list; df['어휘 등급 평균'] = rank_list
                
                # [수정] 엑셀 컬럼명에 '(평균)' 명시
                df['기본 형식 복잡도(평균)'] = syn_basic; df['수식 구조 복잡도(평균)'] = syn_add1; df['내포 구조 복잡도(평균)'] = syn_add2
                df['접속 구조 복잡도(평균)'] = syn_add3; df['통사적 복잡도 총합(평균)'] = syn_sum
                
                st.success("분석이 완료되었습니다!")
                st.subheader("2. 최종 종합 분석 결과 확인")
                st.dataframe(df)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False, sheet_name='종합분석결과')
                
                st.download_button(
                    label="📊 종합 분석 결과 엑셀 파일로 다운로드",
                    data=output.getvalue(),
                    file_name="학생글_자동평가_종합분석결과.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )