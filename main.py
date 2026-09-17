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

# 1. 환경 변수
SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")

SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

collected_articles = []

def format_date(raw_date_str):
    """ 영문 날짜 형식을 YYYY-MM-DD 형식으로 변환 """
    if not raw_date_str:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        dt = parsedate_to_datetime(raw_date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def send_to_gas(url, data):
    """ 구글 Apps Script 전송 (타임아웃 30초 확장 및 리다이렉트 추적) """
    if not url:
        return False
        
    for attempt in range(3):
        try:
            # timeout을 30초로 대폭 늘려 구글의 첫 파일 생성 시간(Lock 대기 시간) 확보
            res = requests.post(url, json=data, timeout=30, allow_redirects=True)
            if "Error" in res.text:
                print(f"⚠️ GAS 응답 오류 ({data['reporter']}): {res.text}")
            else:
                return True
        except Exception as e:
            time.sleep(2)
    print(f"❌ 최종 시트 전송 실패 ({data['reporter']})")
    return False

try:
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    
    for _, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        keywords = str(row.get('키워드', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        # 2026년 9월 1일 이후 기사 수집
        raw_query = f'"{name}" ({keywords}) after:2026-09-01'
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries:
            published_date = format_date(entry.get('published', ''))
            
            article_info = {
                "media": media,
                "reporter": name,
                "title": entry.title,
                "link": entry.link,
                "published": published_date
            }
            collected_articles.append(article_info)
            
            # 구글 시트 웹앱 전송
            send_to_gas(GAS_WEBAPP_URL, article_info)

    # 이메일 전송 처리
    if collected_articles and SENDER_EMAIL and SENDER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"[일일 모니터링] 기자 명단 신규 기사 종합 브리핑 ({len(collected_articles)}건)"

        body = f"2026년 9월 1일 이후 수집된 기자별 기사 목록입니다 (총 {len(collected_articles)}건):\n\n"
        for idx, item in enumerate(collected_articles, 1):
            body += f"{idx}. [{item['published']}] [{item['media']} {item['reporter']} 기자] {item['title']}\n   링크: {item['link']}\n\n"

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_bytes())
        server.quit()
        print(f"성공: 총 {len(collected_articles)}건의 기사 수집 및 처리 완료!")
    else:
        print("수집된 신규 기사가 없습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
