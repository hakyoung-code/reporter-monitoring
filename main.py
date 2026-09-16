import os
import urllib.parse
import pandas as pd
import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. 환경 변수 (GitHub Secrets)
SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"  # 알림받을 이메일 주소

# 2. 구글 시트 ID 연동
SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

collected_articles = []

try:
    # 구글 시트에서 기자 명단 읽어오기
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    
    for _, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        keywords = str(row.get('키워드', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        # [수정] when:1d 옵션을 추가하여 최근 24시간 이내 신규 기사만 수집
        raw_query = f'"{name}" ({keywords}) when:1d'
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        
        # 최근 24시간 내 발행된 신규 기사 추출
        for entry in feed.entries:
            collected_articles.append({
                "media": media,
                "reporter": name,
                "title": entry.title,
                "link": entry.link
            })

    # 이메일 전송 처리
    if collected_articles and SENDER_EMAIL and SENDER_PASSWORD:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        
        subject_text = f"[일일 모니터링] 기자 명단 신규 기사 종합 브리핑 ({len(collected_articles)}건)"
        msg['Subject'] = subject_text

        body = "오늘 수집된 24시간 이내 신규 기사 목록입니다:\n\n"
        for idx, item in enumerate(collected_articles, 1):
            body += f"{idx}. [{item['media']} {item['reporter']} 기자] {item['title']}\n   링크: {item['link']}\n\n"

        text_part = MIMEText(body, 'plain', 'utf-8')
        msg.attach(text_part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_bytes())
        server.quit()
        print(f"성공: 총 {len(collected_articles)}건의 신규 기사 브리핑 이메일 발송 완료!")
    else:
        print("최근 24시간 이내에 발행된 신규 기사가 없습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
