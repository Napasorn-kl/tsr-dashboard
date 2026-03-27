#!/usr/bin/env python3
"""
TSR Dashboard – Data Fetcher
─────────────────────────────
ดึงข้อมูลจาก Google Trends และ YouTube Data API v3
แล้วบันทึกเป็นไฟล์ JSON ใน โฟลเดอร์ data/

วิธีใช้:
  pip install -r requirements.txt

  # ดึงแค่ Google Trends (ไม่ต้อง API Key)
  python fetch_data.py

  # ดึง Google Trends + YouTube
  python fetch_data.py YOUR_YOUTUBE_API_KEY

  # หรือตั้ง environment variable แล้วรัน
  export YOUTUBE_API_KEY=YOUR_KEY
  python fetch_data.py

สร้าง YouTube API Key ได้ที่:
  https://console.cloud.google.com/apis/library/youtube.googleapis.com
  (ฟรี 10,000 units/วัน)
"""

import json, os, sys, time
from datetime import datetime
import requests

# ── Config ────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(OUTPUT_DIR, exist_ok=True)

TREND_KEYWORDS = ['สุราชุมชน', 'สุราท้องถิ่น', 'craft spirits', 'ชุมชนสุรา']
YT_QUERIES     = ['สุราชุมชน', 'สุราท้องถิ่น ไทย', 'community spirits thailand']

# คำที่ต้องมีอย่างน้อย 1 คำ (กรองให้แน่ใจว่าเกี่ยวกับสุราชุมชน)
YT_INCLUDE = ['สุรา', 'เหล้า', 'กลั่น', 'spirits', 'craft', 'ท้องถิ่น', 'ชุมชน', 'คราฟท์', 'สาโท', 'distill', 'community']
# คำที่ต้องไม่มี (ตัดวิดีโอที่ไม่เกี่ยวข้องออก)
YT_EXCLUDE = ['sprite', 'ghost', 'train', 'techno', 'tibet', 'sikh', 'unity', 'รถไฟ', 'ทะเลสาบ', 'asia', 'ทิเบต', 'ซิกข์', 'ancestors']


# ── Google Trends ─────────────────────────────────────────────
def fetch_trends():
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  ❌ ไม่พบ pytrends — รัน: pip install pytrends")
        return None

    print("📊 กำลังดึง Google Trends…")
    pytrends = TrendReq(hl='th-TH', tz=420)  # tz=420 = UTC+7 (Bangkok)
    result   = {}

    # 1) Interest over time (3 months, Thailand)
    try:
        pytrends.build_payload(TREND_KEYWORDS[:4], timeframe='today 3-m', geo='TH')
        df = pytrends.interest_over_time()
        if not df.empty:
            result['interest_over_time'] = {
                'dates': df.index.strftime('%Y-%m-%d').tolist()
            }
            for kw in TREND_KEYWORDS[:4]:
                if kw in df.columns:
                    result['interest_over_time'][kw] = df[kw].tolist()
        print("  ✅ Interest over time")
    except Exception as e:
        print(f"  ⚠️  interest_over_time: {e}")

    time.sleep(2)  # หยุดเพื่อไม่ให้ถูก rate-limit

    # 2) Interest by region
    try:
        pytrends.build_payload([TREND_KEYWORDS[0]], timeframe='today 3-m', geo='TH')
        reg = pytrends.interest_by_region(resolution='REGION', inc_low_vol=True)
        if not reg.empty:
            result['by_region'] = (
                reg[TREND_KEYWORDS[0]]
                .sort_values(ascending=False)
                .head(10)
                .to_dict()
            )
        print("  ✅ Interest by region")
    except Exception as e:
        print(f"  ⚠️  by_region: {e}")

    time.sleep(2)

    # 3) Related queries
    try:
        pytrends.build_payload([TREND_KEYWORDS[0]], timeframe='today 3-m', geo='TH')
        rel = pytrends.related_queries()
        if TREND_KEYWORDS[0] in rel and rel[TREND_KEYWORDS[0]]['top'] is not None:
            result['related_queries'] = (
                rel[TREND_KEYWORDS[0]]['top'].head(10).to_dict('records')
            )
        print("  ✅ Related queries")
    except Exception as e:
        print(f"  ⚠️  related_queries: {e}")

    result['keywords']   = TREND_KEYWORDS[:4]
    result['fetched_at'] = datetime.now().isoformat()
    result['geo']        = 'TH'
    result['timeframe']  = 'today 3-m'
    return result


# ── YouTube Data API v3 ───────────────────────────────────────
def fetch_youtube(api_key):
    print("🎥 กำลังดึง YouTube Data API…")
    BASE      = 'https://www.googleapis.com/youtube/v3'
    result    = {'videos': [], 'fetched_at': datetime.now().isoformat()}
    video_ids = []

    # ค้นหาวิดีโอด้วยแต่ละ query
    for query in YT_QUERIES:
        params = {
            'part':              'snippet',
            'q':                 query,
            'type':              'video',
            'maxResults':        10,
            'regionCode':        'TH',
            'relevanceLanguage': 'th',
            'key':               api_key,
        }
        r = requests.get(f'{BASE}/search', params=params, timeout=10)
        if r.status_code != 200:
            print(f"  ⚠️  search '{query}': {r.status_code} — {r.text[:120]}")
            continue
        for item in r.json().get('items', []):
            vid = item['id'].get('videoId')
            if vid and vid not in video_ids:
                video_ids.append(vid)
        print(f"  🔍 search '{query}' → {len(video_ids)} IDs รวม")

    if not video_ids:
        print("  ⚠️  ไม่พบวิดีโอจาก queries ที่กำหนด")
        return result

    # ดึงสถิติแบบ batch (max 50 ต่อ request)
    for i in range(0, min(len(video_ids), 50), 50):
        batch  = ','.join(video_ids[i:i + 50])
        params = {
            'part': 'snippet,statistics,contentDetails',
            'id':   batch,
            'key':  api_key,
        }
        r = requests.get(f'{BASE}/videos', params=params, timeout=10)
        if r.status_code != 200:
            print(f"  ⚠️  videos stats: {r.status_code}")
            continue
        for item in r.json().get('items', []):
            sn = item.get('snippet', {})
            st = item.get('statistics', {})
            result['videos'].append({
                'id':           item['id'],
                'title':        sn.get('title', ''),
                'channel':      sn.get('channelTitle', ''),
                'published_at': sn.get('publishedAt', '')[:10],
                'thumbnail':    sn.get('thumbnails', {}).get('medium', {}).get('url', ''),
                'views':        int(st.get('viewCount',   0)),
                'likes':        int(st.get('likeCount',   0)),
                'comments':     int(st.get('commentCount',0)),
            })

    # กรองวิดีโอที่ไม่เกี่ยวข้องออก
    def is_relevant(video):
        text = (video['title'] + ' ' + video['channel']).lower()
        has_include = any(kw.lower() in text for kw in YT_INCLUDE)
        has_exclude = any(kw.lower() in text for kw in YT_EXCLUDE)
        return has_include and not has_exclude

    before = len(result['videos'])
    result['videos'] = [v for v in result['videos'] if is_relevant(v)]
    print(f"  🔍 กรองแล้ว: {before} → {len(result['videos'])} วิดีโอ")

    # เรียงตาม views มากสุดก่อน
    result['videos'].sort(key=lambda x: x['views'], reverse=True)
    print(f"  ✅ ดึงได้ {len(result['videos'])} วิดีโอ")
    return result


# ── Main ──────────────────────────────────────────────────────
if __name__ == '__main__':
    api_key = os.environ.get('YOUTUBE_API_KEY') or (
        sys.argv[1] if len(sys.argv) > 1 else ''
    )

    print("=" * 50)
    print("  TSR Dashboard — Data Fetcher")
    print("=" * 50)

    # Google Trends
    trends = fetch_trends()
    if trends:
        path = os.path.join(OUTPUT_DIR, 'trends.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(trends, f, ensure_ascii=False, indent=2)
        print(f"  💾 บันทึก → {path}\n")
    else:
        print("  ⏭️  ข้าม Google Trends\n")

    # YouTube
    if api_key:
        yt   = fetch_youtube(api_key)
        path = os.path.join(OUTPUT_DIR, 'youtube.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(yt, f, ensure_ascii=False, indent=2)
        print(f"  💾 บันทึก → {path}\n")
    else:
        print("⚠️  ไม่มี YouTube API Key — ข้ามขั้นตอนนี้")
        print("   วิธีใส่ key: python fetch_data.py YOUR_API_KEY\n")

    print("=" * 50)
    print("✅ เสร็จสิ้น! เปิด Dashboard เพื่อดูข้อมูล Live")
    print("=" * 50)
