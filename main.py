import os
import urllib.parse
import pandas as pd
import feedparser
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. 환경 변수
SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL") # Apps Script 웹 앱 URL

SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

collected_articles = []

try:
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    
    for _, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        keywords = str(row.get('키워드', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        raw_query = f'"{name}" ({keywords}) when:1d'
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries:
            article_info = {
                "media": media,
                "reporter": name,
                "title": entry.title,
                "link": entry.link,
                "published": entry.get('published', '')
            }
            collected_articles.append(article_info)
            
            # 구글 Apps Script로 기사 데이터 전송 -> 기자별 탭에 기록
            if GAS_WEBAPP_URL:
                try:
                    requests.post(GAS_WEBAPP_URL, json=article_info)
                except Exception as req_err:
                    print(f"시트 전송 실패 ({name}): {req_err}")

    # 이메일 브리핑 전송
    if collected_articles and SENDER_EMAIL and SENDER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"[일일 모니터링] 기자 명단 신규 기사 종합 브리핑 ({len(collected_articles)}건)"

        body = "오늘 수집된 24시간 이내 신규 기사 목록입니다 (구글 시트 기자별 탭에도 자동 기록됨):\n\n"
        for idx, item in enumerate(collected_articles, 1):
            body += f"{idx}. [{item['media']} {item['reporter']} 기자] {item['title']}\n   링크: {item['link']}\n\n"

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_bytes())
        server.quit()
        print(f"성공: 총 {len(collected_articles)}건 브리핑 발송 및 시트 기자별 탭 기록 완료!")
    else:
        print("최근 24시간 이내 신규 기사가 없습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
