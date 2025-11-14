import re
import csv
import requests

# ======================================
# 1. URL / API KEY 입력
# ======================================
API_KEY = "AIzaSyAWjJ4aF40ChlNj_W7wGB5Sz8pMHIchRtI"        # ← API KEY 입력
VIDEO_URL = "https://www.youtube.com/watch?v=Lt07GjGEXNE&list=RDLt07GjGEXNE&start_radio=1"    # ← 유튜브 영상 URL 입력


# ======================================
# 2. 영상 ID 추출 함수
# ======================================
def extract_video_id(url: str) -> str:
    """
    유튜브 URL에서 Video ID를 추출한다.
    """
    patterns = [
        r"v=([^&]+)",
        r"youtu\.be/([^?]+)",
        r"youtube\.com/embed/([^?]+)"
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError("유효한 YouTube URL이 아닙니다.")


video_id = extract_video_id(VIDEO_URL)


# ======================================
# 3. 댓글 가져오기 함수
# ======================================
def get_youtube_comments(video_id, api_key, max_results=100):
    """
    YouTube Data API를 사용해 모든 댓글(대댓글 포함)을 가져오는 함수
    """
    comments = []
    api_url = "https://www.googleapis.com/youtube/v3/commentThreads"

    params = {
        "part": "snippet,replies",
        "videoId": video_id,
        "key": api_key,
        "maxResults": max_results,
        "textFormat": "plainText"
    }

    while True:
        response = requests.get(api_url, params=params)
        data = response.json()

        if "error" in data:
            print("API Error:", data["error"]["message"])
            break

        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]

            # 최상위 댓글 기록
            comments.append({
                "author": top["authorDisplayName"],
                "comment": top["textDisplay"],
                "published": top["publishedAt"],
                "likeCount": top["likeCount"],
                "reply_to": ""
            })

            # 대댓글 존재 시 추가
            if "replies" in item:
                for reply in item["replies"].get("comments", []):
                    rep = reply["snippet"]
                    comments.append({
                        "author": rep["authorDisplayName"],
                        "comment": rep["textDisplay"],
                        "published": rep["publishedAt"],
                        "likeCount": rep["likeCount"],
                        "reply_to": top["authorDisplayName"]
                    })

        # 다음 페이지가 없으면 종료
        if "nextPageToken" not in data:
            break

        params["pageToken"] = data["nextPageToken"]

    return comments


# ======================================
# 4. CSV 저장 함수
# ======================================
def save_to_csv(video_id, comments):
    filename = f"comments_{video_id}.csv"

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["author", "comment", "published", "likeCount", "reply_to"]
        )
        writer.writeheader()
        writer.writerows(comments)

    print(f"📁 CSV 저장 완료: {filename}")


# ======================================
# 5. 실행
# ======================================
if __name__ == "__main__":
    print("⏳ 댓글 수집 중...")

    all_comments = get_youtube_comments(video_id, API_KEY)
    print(f"✅ 총 {len(all_comments)}개의 댓글 수집 완료!")

    save_to_csv(video_id, all_comments)
