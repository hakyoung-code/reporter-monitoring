import os
import urllib.parse
import pandas as pd
import feedparser
import smtplib
import requests
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")

SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

collected_articles = []

def format_date(raw_date_str):
    if not raw_date_str:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        dt = parsedate_to_datetime(raw_date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def analyze_article(title, summary_raw):
    """ 기사 제목과 요약문 기반 어조(긍정/부정/중립), 성격, 카테고리, 연관부서 분석 """
    text = f"{title} {summary_raw}"
    
    # 1. 기사 어조 (Sentiment) 감정 분석
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

    # 2. 기사 성격(분류) 판별
    article_type = "사실기반 일반기사"
    if any(k in text for k in ["보도자료", "알림", "밝혔다", "배포"]):
        article_type = "보도자료 기반"
    elif any(k in text for k in ["기고", "칼럼", "시론", "포럼", "특별기획", "오피니언", "시각", "데스크"]):
        article_type = "기고/오피니언"
    elif any(k in text for k in ["사설", "기획", "추적", "심층"]):
        article_type = "기획/사설"

    # 3. 세부 카테고리 판별
    category = "보건복지 일반"
    if "장기요양" in text or "요양" in text:
        category = "장기요양보험"
    elif "건강보험" in text or "건보" in text:
        category = "건강보험 정책"
    elif "수가" in text or "약가" in text:
        category = "급여/수가 관리"
    elif "재정" in text or "부과" in text:
        category = "보험료/재정 관리"

    # 4. 공단 연관 부서/업무 판별
    department = "기획조정실 / 홍보실"
    if "장기요양" in text:
        department = "요양가입부 / 요양급여실"
    elif "수가" in text or "급여" in text:
        department = "급여관리실 / 약제관리실"
    elif "부과" in text or "징수" in text or "보험료" in text:
        department = "자격부과실 / 징수관리실"
    elif "적발" in text or "사무장병원" in text:
        department = "의료기관지원실 (특사경)"

    # 5. 주요 요약 및 시사점 정제
    clean_summary = summary_raw.replace("<b>", "").replace("</b>", "").strip()
    if len(clean_summary) > 150:
        clean_summary = clean_summary[:150] + "..."
    
    if sentiment == "부정 (비판/리스크)":
        summary_final = f"[리스크 관리 필요] {clean_summary if clean_summary else '언론 비판 동향에 대한 공단 차원의 언론 대응 논리 및 사실관계 확인 필요'}"
    else:
        summary_final = clean_summary if clean_summary else f"[{category}] 관련 정책 동향 파악 필요"

    return sentiment, article_type, category, summary_final, department

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
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    
    for _, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        keywords = str(row.get('키워드', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        raw_query = f'"{name}" ({keywords}) after:2026-09-01'
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries:
            published_date = format_date(entry.get('published', ''))
            summary_raw = entry.get('summary', '')
            
            # 어조, 성격, 카테고리, 요약, 연관부서 종합 분석
            sentiment, article_type, category, summary, department = analyze_article(entry.title, summary_raw)
            
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

    # 이메일 종합 브리핑 발송
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

except Exception as e:
    print(f"오류 발생: {e}")
