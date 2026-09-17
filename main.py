import os
import urllib.parse
import pandas as pd
import feedparser
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. 환경 변수 확인
SENDER_EMAIL = os.environ.get("MY_EMAIL")
SENDER_PASSWORD = os.environ.get("MY_APP_PASSWORD")
RECEIVER_EMAIL = "poii77725@gmail.com"
GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL")

print("=== [시스템 진단 시작] ===")
print(f"1. 이메일 설정 확인: {'OK' if SENDER_EMAIL and SENDER_PASSWORD else '미설정(Secrets 확인 필요)'}")
print(f"2. Apps Script URL 등록 확인: {'OK' if GAS_WEBAPP_URL else '미설정(GAS_WEBAPP_URL Secrets 확인 필요)'}")

SPREADSHEET_ID = "1WBUcXZ0Sj9UJMo_vzlkNhFdbsNLDroaK81f0OiKnyX0"
SHEET_NAME_ENCODED = urllib.parse.quote("기자명단")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME_ENCODED}"

collected_articles = []

try:
    print("\n3. 구글 시트 기자명단 읽기 시도 중...")
    reporters_df = pd.read_csv(SHEET_URL, encoding='utf-8')
    print(f"   └ 총 {len(reporters_df)}명의 기자 정보를 가져왔습니다.")
    
    for idx, row in reporters_df.iterrows():
        media = str(row.get('언론사', '')).strip()
        name = str(row.get('기자이름', '')).strip()
        keywords = str(row.get('키워드', '')).strip()
        
        if not name or name == 'nan':
            continue
            
        print(f"\n[기자 탐색 시작] {media} {name} 기자 (키워드: {keywords})")
        
        # 테스트를 위해 when:1d 옵션을 빼고 수집 (즉시 탭 생성을 확인하기 위함)
        raw_query = f'"{name}" ({keywords})'
        encoded_query = urllib.parse.quote(raw_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        print(f"   └ 구글 뉴스 RSS 탐색 결과: 총 {len(feed.entries)}건 발견")
        
        # 최근 2개 기사만 수집 및 시트 전송
        for entry in feed.entries[:2]:
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
                    res = requests.post(GAS_WEBAPP_URL, json=article_info, timeout=10)
                    print(f"   ➔ 시트 데이터 전송 응답 코드: {res.status_code} | 결과 내용: {res.text.strip()}")
                except Exception as req_err:
                    print(f"   ❌ 시트 전송 중 오류 발생 ({name}): {req_err}")
            else:
                print("   ❌ GAS_WEBAPP_URL 설정이 없어 구글 시트로 전송하지 못했습니다.")

    # 4. 이메일 브리핑 전송
    if collected_articles and SENDER_EMAIL and SENDER_PASSWORD:
        print("\n4. 종합 브리핑 이메일 전송 중...")
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"[일일 모니터링] 기자 명단 신규 기사 종합 브리핑 ({len(collected_articles)}건)"

        body = "오늘 수집된 기사 목록입니다 (구글 시트 기자별 탭 전송 시도됨):\n\n"
        for idx, item in enumerate(collected_articles, 1):
            body += f"{idx}. [{item['media']} {item['reporter']} 기자] {item['title']}\n   링크: {item['link']}\n\n"

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_bytes())
        server.quit()
        print(f"   └ 성공: 총 {len(collected_articles)}건 이메일 발송 완료!")
    else:
        print("\n4. 수집된 기사가 없거나 메일 계정 설정(Secrets) 미완료로 이메일을 발송하지 않았습니다.")

except Exception as e:
    print(f"\n❌ 전반적 오류 발생: {e}")

print("\n=== [시스템 진단 종료] ===")
