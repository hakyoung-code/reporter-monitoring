import os
import urllib.parse
import pandas as pd
import feedparser
import smtplib
import requests
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# TF-IDF 및 코사인 유사도 알고리즘 (무료 패키지)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# 1. 환경 변수 로드
SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")

# 기자명단 구글 시트 CSV URL
SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

# -------------------------------------------------------------
# [설정] 보도자료 활용 판정 임계값 & 공단 관련성 필수 키워드
# -------------------------------------------------------------
TFIDF_THRESHOLD = 0.72       # 코사인 유사도 기준 (72% 이상)
SENTENCE_HIT_MIN = 2         # 보도자료 고유 문장 일치 개수 (최소 2개)
MIN_SENTENCE_LEN = 25        # 비교 대상 문장 최소 길이 (25자 이상)

# 공단/건보 연관성 판별 필수 키워드 (채용, 신규직원, 모집 추가)
NHIS_CORE_KEYWORDS = [
    "건보", "강청희", "건강보험", "건보료", "건보공단", "건강보험료", 
    "장기요양", "공단", "수가", "약가", "급여", "신약", "등재", "약제", "의료",
    "노인", "복지", "돌봄", "이사장", "협력", "비급여",
    "포상금", "부당청구", "신고", "적발", "환수", "체납", "보도자료",
    "채용", "신규직원", "공개채용", "모집", "원서접수"
]

collected_articles = []
nhis_press_releases = []

def format_date(raw_date_str):
    if not raw_date_str:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        dt = parsedate_to_datetime(raw_date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def fetch_nhis_press_releases():
    """ 국민건강보험공단 홈페이지 보도자료 게시판 자동 크롤링 """
    press_list = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    board_url = "https://www.nhis.or.kr/nhis/together/wbhaea01600m01.do"
    
    try:
        res = requests.get(board_url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            items = soup.select('.board-list tbody tr, table tr')
            for item in items[:15]:
                title_elem = item.select_one('.subject a, td.title a, a')
                if title_elem:
                    title = title_elem.get_text().strip()
                    if len(title) > 5 and title not in [p['title'] for p in press_list]:
                        press_list.append({"title": title, "content": title})
        print(f"공단 보도자료 {len(press_list)}건 자동 수집 완료")
    except Exception as e:
        print(f"공단 보도자료 크롤링 예외 발생: {e}")
    
    return press_list

def fetch_full_text(url):
    """ 기사 원문 전문 크롤링 (실패 시 None) """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'iframe']):
                tag.decompose()
            
            paragraphs = soup.find_all('p')
            if paragraphs:
                text = ' '.join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20])
            else:
                text = soup.get_text()
            
            clean_text = re.sub(r'\s+', ' ', text).strip()
            if len(clean_text) >= 100:
                return clean_text
    except Exception:
        pass
    return None

def is_nhis_related(text):
    """ 공단/건보 정책 연관성 매칭 검증 """
    return any(kw in text for kw in NHIS_CORE_KEYWORDS)

def check_press_release_usage(article_text, press_list):
    """ TF-IDF 코사인 유사도 + 고유 문장 매칭 분석 """
    if not press_list or not article_text:
        return False, 0.0, 0
    
    max_sim = 0.0
    max_hit_count = 0
    
    for press in press_list:
        press_text = press['content']
        try:
            tfidf = TfidfVectorizer().fit_transform([article_text, press_text])
            sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
            if sim > max_sim:
                max_sim = sim
        except Exception:
            sim = 0.0
        
        sentences = [s.strip() for s in re.split(r'[\.\?\!\n]', press_text) if len(s.strip()) >= MIN_SENTENCE_LEN]
        hit_count = 0
        for sent in sentences:
            if sent in article_text:
                hit_count += 1
                
        if hit_count > max_hit_count:
            max_hit_count = hit_count

    is_press_used = (max_sim >= TFIDF_THRESHOLD) or (max_hit_count >= SENTENCE_HIT_MIN)
    return is_press_used, max_sim, max_hit_count

def extract_matched_keywords(text):
    """ 감지된 주요 키워드 추출 """
    found = [kw for kw in NHIS_CORE_KEYWORDS if kw in text]
    return ", ".join(found) if found else "일반"

def analyze_article(title, summary_raw, link, press_list):
    full_text = fetch_full_text(link)
    
    if full_text:
        source_type = "전문 분석"
        analysis_base_text = f"{title} {full_text}"
    else:
        source_type = "RSS 요약문 분석"
        clean_rss_summary = summary_raw.replace("<b>", "").replace("</b>", "").strip()
        analysis_base_text = f"{title} {clean_rss_summary}"

    text = analysis_base_text
    
    # 0. 감지 키워드 추출
    keywords_found = extract_matched_keywords(text)
    
    # 1. 단독/특종 기사 제목 태그 감지
    title_tags = ["[단독]", "<단독>", "【단독】", "단독:", "[특종]"]
    is_exclusive = False
    if any(tag in title for tag in title_tags):
        is_exclusive = True
    elif any(k in text for k in ["단독 보도", "최초 보도", "단독 취재", "단독 입수"]):
        is_exclusive = True

    # 2. 보도자료 활용 여부 판정
    is_press_used, sim_score, hit_count = check_press_release_usage(text, press_list)
    sim_percent = int(sim_score * 100)
    
    # 3. 기사 성격(분류) 판별
    base_type = "사실기반 일반기사"
    if any(k in text for k in ["기고", "칼럼", "시론", "포럼", "특별기획", "오피니언", "시각", "데스크"]):
        base_type = "기고/오피니언"
    elif any(k in text for k in ["사설", "기획", "추적", "심층"]):
        base_type = "기획/사설"
    elif is_press_used or any(k in text for k in ["보도자료", "알림", "밝혔다", "배포", "설명했다", "발표했다", "전했다", "포상금", "공개채용", "원서접수"]):
        if is_press_used:
            base_type = f"보도자료 기반 (유사도 {sim_percent}% / 문장일치 {hit_count}건)"
        else:
            base_type = "보도자료 기반"

    if is_exclusive:
        article_type = f"🔥 [단독] {base_type}"
    else:
        article_type = base_type

    # 4. 감정 분석
    pos_keywords = ["호조", "성장", "수상", "최대 실적", "흑자", "신기록", "돌파", "협약", "선정", "기부", "호평", "확대", "출시", "포상", "채용"]
    neg_keywords = ["논란", "리콜", "소송", "적자", "하락", "부진", "제재", "과징금", "압수수색", "사고", "결함", "구설", "해임", "의혹", "부당청구"]
    
    pos_score = sum(1 for k in pos_keywords if k in text)
    neg_score = sum(1 for k in neg_keywords if k in text)
    
    if neg_score > pos_score and neg_score >= 1:
        sentiment = "부정 (비판/리스크)"
    elif pos_score > neg_score and pos_score >= 1:
        sentiment = "긍정 (성과/진전)"
    else:
        sentiment = "중립 (단순 전달)"

    # 5. 세부 카테고리 판별
    category = "보건복지 일반"
    if any(k in text for k in ["채용", "신규직원", "공개채용", "원서접수"]):
        category = "인사/채용 공고"
    elif "부당청구" in text or "신고" in text or "포상금" in text or "특사경" in text:
        category = "의료지원 / 수사·환수"
    elif "장기요양" in text or "요양" in text or "노인" in text or "돌봄" in text:
        category = "장기요양보험"
    elif "건강보험" in text or "건보" in text:
        category = "건강보험 정책"
    elif "수가" in text or "약가" in text or "신약" in text or "비급여" in text:
        category = "급여/수가 관리"
    elif "재정" in text or "부과" in text:
        category = "보험료/재정 관리"

    # 6. [조직도 기반] 공단 연관 부서/업무 정밀 매핑
    department = "기획조정실 / 홍보실"
    if any(k in text for k in ["채용", "신규직원", "공개채용", "원서접수", "인사"]):
        department = "인력지원실 / 인사혁신실"
    elif any(k in text for k in ["부당청구", "포상금", "신고", "사무장병원", "특사경", "재난적의료비", "의료급여"]):
        department = "의료지원실"
    elif any(k in text for k in ["약가", "신약", "약제", "등재"]):
        department = "약제관리실"
    elif any(k in text for k in ["부과", "자격", "소득정산"]):
        department = "자격부과실"
    elif any(k in text for k in ["징수", "건보료", "보험료", "체납"]):
        department = "통합징수실"
    elif any(k in text for k in ["수가", "수가협상", "급여", "적정진료"]):
        department = "보험급여실 / 급여관리실"
    elif any(k in text for k in ["장기요양", "요양원", "요양급여", "노인", "돌봄"]):
        department = "요양기획실 / 요양급여실"
    elif any(k in text for k in ["복지용구", "요양기관", "요양평가"]):
        department = "요양자원실 / 요양심사실"
    elif any(k in text for k in ["건강검진", "검진", "만성질환"]):
        department = "건강검진실 / 건강지원사업실"
    elif any(k in text for k in ["통합돌봄", "커뮤니티케어"]):
        department = "통합돌봄실"
    elif any(k in text for k in ["빅데이터", "마이데이터", "인공지능", "AI"]):
        department = "빅데이터운영실 / NHIS인공지능실"

    # 7. 요약 및 시사점 정제
    if full_text:
        summary_body = full_text[:200] + "..."
    else:
        clean_summary = summary_raw.replace("<b>", "").replace("</b>", "").strip()
        summary_body = clean_summary[:150] + "..." if len(clean_summary) > 150 else clean_summary

    if sentiment == "부정 (비판/리스크)":
        summary_final = f"[⚠️ 리스크 관리 / {source_type}] {summary_body if summary_body else '언론 비판 동향 대응 필요'}"
    else:
        summary_final = f"[{category} / {source_type}] {summary_body if summary_body else '주요 정책 동향 파악'}"

    return sentiment, article_type, category, summary_final, department, full_text, keywords_found

def send_to_gas(url, data):
    if not url:
        return False
    for attempt in range(3):
        try:
            res = requests.post(url, json=data, timeout=30, allow_redirects=True)
            if "Error" not in res.text:
                return True
        except Exception:
            time.sleep(2)
    return False

try:
    # 1. 공단 보도자료 사전 크롤링
    nhis_press_releases = fetch_nhis_press_releases()
    
    # 2. 명단 구글 시트 읽기
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    print(f"구글 시트 읽기 성공 (총 {len(reporters_df)}행)")
    
    for _, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        # BBS 등 약칭 언론사 검색 누락 방지 처리
        if media and media != 'nan':
            raw_query = f'{media} "{name}" when:1y'
        else:
            raw_query = f'"{name}" when:1y'
            
        print(f"\n[모니터링 대상] {media} {name} 기자")
        print(f" -> 검색 쿼리: {raw_query}")
        
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        print(f" -> 구글 뉴스 RSS 발견 기사: {len(feed.entries)}건")
        
        for entry in feed.entries:
            published_date = format_date(entry.get('published', ''))
            summary_raw = entry.get('summary', '')
            
            # 기사 분석 수행
            sentiment, article_type, category, summary, department, full_text, keywords_found = analyze_article(
                entry.title, summary_raw, entry.link, nhis_press_releases
            )
            
            # 공단/건보 정책 연관성 검증
            text_for_check = f"{entry.title} {summary_raw} {full_text if full_text else ''}"
            if not is_nhis_related(text_for_check):
                print(f"  └ [제외: 공단/건보 무관 기사] {entry.title}")
                continue
            
            article_info = {
                "published": published_date,       # 1. 게재일
                "media": media,                   # 2. 언론사
                "reporter": name,                 # 3. 기자명
                "title": entry.title,             # 4. 기사제목
                "keywords_found": keywords_found, # 5. 키워드
                "article_type": article_type,     # 6. 기사 성격
                "sentiment": sentiment,           # 7. 기사 어조
                "category": category,             # 8. 세부 카테고리
                "summary": summary,               # 9. 요약
                "department": department,         # 10. 공단 연관 부서/업무 (인력지원실 매핑)
                "link": entry.link                # 11. 원문링크
            }
            collected_articles.append(article_info)
            success = send_to_gas(GAS_WEBAPP_URL, article_info)
            if success:
                print(f"  └ [시트 발췌 성공] {entry.title}")
            else:
                print(f"  └ [시트 전송 실패] {entry.title}")

    # 3. 이메일 종합 브리핑 전송
    if collected_articles and SENDER_EMAIL and SENDER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"[일일 모니터링] 지정 기자 기사 발췌 리포트 ({len(collected_articles)}건)"

        body = f"지정 기자별 공단 연관 기사 수집 리포트입니다 (총 {len(collected_articles)}건):\n\n"
        for idx, item in enumerate(collected_articles, 1):
            body += f"{idx}. [{item['published']}] [{item['media']} {item['reporter']} 기자]\n"
            body += f"   - 기사제목: {item['title']}\n"
            body += f"   - 감지 키워드: {item['keywords_found']}\n"
            body += f"   - 성격/어조: [{item['article_type']}] | [{item['sentiment']}]\n"
            body += f"   - 카테고리/부서: {item['category']} | {item['department']}\n"
            body += f"   - 요약: {item['summary']}\n"
            body += f"   - 원문링크: {item['link']}\n\n"

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_bytes())
        server.quit()
        print(f"\n성공: 총 {len(collected_articles)}건 수집 및 전송 완료!")
    else:
        print("\n수집된 신규 기사가 없습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
