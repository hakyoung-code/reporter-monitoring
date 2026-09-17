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

# 1. 환경 변수 로드
SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")

# 기자명단 구글 시트 CSV 내보내기 URL
SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

collected_articles = []

def format_date(raw_date_str):
    """ RSS 영문 날짜를 YYYY-MM-DD 형식으로 안전 변환 """
    if not raw_date_str:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        dt = parsedate_to_datetime(raw_date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def fetch_full_text(url):
    """ 
    [1차] 기사 원문 페이지에서 본문 전문 크롤링 시도 
    [2차] 언론사 차단/오류 발생 시 None 반환 (RSS 요약문으로 자동 예외 처리)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 노이즈 태그 제거 (스크립트, 스타일, 헤더, 푸터 등)
            for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'iframe']):
                tag.decompose()
            
            # 본문 기사 텍스트 추출
            paragraphs = soup.find_all('p')
            if paragraphs:
                text = ' '.join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20])
            else:
                text = soup.get_text()
            
            # 공백 정제
            clean_text = re.sub(r'\s+', ' ', text).strip()
            
            # 본문이 100자 이상 추출되었을 경우만 전문으로 인정
            if len(clean_text) >= 100:
                return clean_text
    except Exception:
        pass
    
    return None  # 실패 시 None 반환하여 RSS 요약문 사용

def analyze_article(title, summary_raw, link):
    """ 
    전문 우선 기사 분석 함수 (실패 시 RSS 요약문 활용)
    """
    # 1. 전문 크롤링 시도 및 분석 대상 텍스트 선정
    full_text = fetch_full_text(link)
    
    if full_text:
        source_type = "전문 분석"
        analysis_base_text = f"{title} {full_text}"
    else:
        source_type = "RSS 요약문 분석"
        clean_rss_summary = summary_raw.replace("<b>", "").replace("</b>", "").strip()
        analysis_base_text = f"{title} {clean_rss_summary}"

    text = analysis_base_text
    
    # 2. 기사 어조 (Sentiment) 감정 분석
    neg_keywords = ["논란", "비판", "우려", "적발", "부정", "의혹", "부실", "반발", "충돌", "지적", "손실", "부담", "허점", "갈등", "한계"]
    pos_keywords = ["성과", "개선", "확대", "지원", "호평", "우수", "달성", "협력", "도움", "인정", "신설", "완화", "혜택"]
    
    neg_score = sum(1 for k in neg_keywords if k in text)
    pos_score = sum(1 for k in pos_keywords if k in text)
    
    if neg_score > pos_score and neg_score >= 1:
        sentiment = "부정 (비판/리스크)"
    elif pos_score > neg_score and pos_score >= 1:
        sentiment = "긍정 (성과/진전)"
    else:
        sentiment = "중립 (단순 전달)"

    # 3. 기사 성격(분류) 판별 (확장 키워드 적용)
    article_type = "사실기반 일반기사"
    if any(k in text for k in ["기고", "칼럼", "시론", "포럼", "특별기획", "오피니언", "시각", "데스크"]):
        article_type = "기고/오피니언"
    elif any(k in text for k in ["사설", "기획", "추적", "심층"]):
        article_type = "기획/사설"
    elif any(k in text for k in [
        "보도자료", "알림", "밝혔다", "배포", "자료", "설명했다", 
        "따르면", "발표했다", "전했다", "안내", "안내했다", "덧붙였다", "제공"
    ]):
        article_type = "보도자료 기반"

    # 4. 세부 카테고리 판별
    category = "보건복지 일반"
    if "장기요양" in text or "요양" in text:
        category = "장기요양보험"
    elif "건강보험" in text or "건보" in text:
        category = "건강보험 정책"
    elif "수가" in text or "약가" in text:
        category = "급여/수가 관리"
    elif "재정" in text or "부과" in text:
        category = "보험료/재정 관리"

    # 5. 공단 연관 부서/업무 판별
    department = "기획조정실 / 홍보실"
    if "장기요양" in text:
        department = "요양가입부 / 요양급여실"
    elif "수가" in text or "급여" in text:
        department = "급여관리실 / 약제관리실"
    elif "부과" in text or "징수" in text or "보험료" in text:
        department = "자격부과실 / 징수관리실"
    elif "적발" in text or "사무장병원" in text:
        department = "의료기관지원실 (특사경)"

    # 6. 주요 요약 및 시사점 정제
    if full_text:
        summary_body = full_text[:200] + "..."
    else:
        clean_summary = summary_raw.replace("<b>", "").replace("</b>", "").strip()
        summary_body = clean_summary[:150] + "..." if len(clean_summary) > 150 else clean_summary

    if sentiment == "부정 (비판/리스크)":
        summary_final = f"[리스크 관리 필요 / {source_type}] {summary_body if summary_body else '언론 비판 동향 대응 필요'}"
    else:
        summary_final = f"[{category} / {source_type}] {summary_body if summary_body else '주요 정책 동향 파악'}"

    return sentiment, article_type, category, summary_final, department

def send_to_gas(url, data):
    """ 구글 Apps Script 전송 (타임아웃 30초 설정 및 재시도) """
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
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    
    for _, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        keywords = str(row.get('키워드', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        # 2026년 9월 1일 이후 기사 수집 쿼리
        raw_query = f'"{name}" ({keywords}) after:2026-09-01'
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries:
            published_date = format_date(entry.get('published', ''))
            summary_raw = entry.get('summary', '')
            
            # 전문 우선 기사 분석 실행 (원문 링크 포함 전달)
            sentiment, article_type, category, summary, department = analyze_article(entry.title, summary_raw, entry.link)
            
            # 10개 항목 데이터 구성
            article_info = {
                "media": media,
                "reporter": name,
                "title": entry.title,
                "link": entry.link,
                "published": published_date,
                "sentiment": sentiment,
                "article_type": article_type,
                "category": category,
                "summary": summary,
                "department": department
            }
            collected_articles.append(article_info)
            send_to_gas(GAS_WEBAPP_URL, article_info)

    # 이메일 종합 브리핑 전송
    if collected_articles and SENDER_EMAIL and SENDER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"[일일 모니터링] 기자 명단 신규 기사 종합 브리핑 ({len(collected_articles)}건)"

        body = f"2026년 9월 1일 이후 수집된 기자별 기사 분석 리포트입니다 (총 {len(collected_articles)}건):\n\n"
        for idx, item in enumerate(collected_articles, 1):
            body += f"{idx}. [{item['published']}] [{item['media']} {item['reporter']} 기자]\n"
            body += f"   - 제목: {item['title']}\n"
            body += f"   - 어조/성격: [{item['sentiment']}] | [{item['article_type']}]\n"
            body += f"   - 카테고리/부서: {item['category']} | {item['department']}\n"
            body += f"   - 요약/시사점: {item['summary']}\n"
            body += f"   - 링크: {item['link']}\n\n"

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_bytes())
        server.quit()
        print(f"성공: 총 {len(collected_articles)}건 기사 수집 및 처리 완료!")
    else:
        print("수집된 신규 기사가 없습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
