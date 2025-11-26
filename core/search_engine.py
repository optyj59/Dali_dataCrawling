import requests
import json
import re
import time
from typing import Dict, List, Any, Optional


def search_dict(dic: Any, search_key: str):
    """
    중첩된 dict/list 구조에서 특정 key를 DFS로 모두 탐색
    """
    stack = [dic]
    while stack:
        current_item = stack.pop()
        if isinstance(current_item, dict):
            for key, value in current_item.items():
                if key == search_key:
                    yield value
                stack.append(value)
        elif isinstance(current_item, list):
            for value in current_item:
                stack.append(value)


class YouTubeSearcher:
    """
    requests + ytInitialData + ytcfg.set 를 이용해
    YouTube 검색 결과에서 영상 URL/제목/조회수 등을 가져오는 검색 엔진.

    - HTML 안에 있는 ytInitialData & ytcfg JSON만 활용
    """

    BASE_SEARCH_URL = "https://www.youtube.com/results"

    def __init__(self):
        self.session = requests.Session()
        # UA & 언어 설정 (필요 시 변경 가능)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.seen_ids = set()

    # ------------------------------
    # 내부: ytInitialData, ytcfg 추출
    # ------------------------------
    def _extract_yt_objects(self, html: str) -> (Dict, Dict):
        """
        HTML 문자열에서
        - var ytInitialData = {...};
        - ytcfg.set({...});
        부분을 잘라서 JSON으로 로드
        """
        tar_init = "var ytInitialData = "
        tar_cfg = "ytcfg.set({"

        i_init = html.find(tar_init)
        i_cfg = html.find(tar_cfg)

        if i_init == -1 or i_cfg == -1:
            raise RuntimeError("ytInitialData 또는 ytcfg.set 을 HTML에서 찾지 못했습니다.")

        # ytInitialData 잘라내기
        j_init = html.find("};", i_init)
        ytinit_str = html[i_init + len(tar_init): j_init + 1]
        ytinit = json.loads(ytinit_str)

        # ytcfg.set({...}) 잘라내기
        j_cfg = html.find(");", i_cfg)
        ytcfg_str = html[i_cfg + len(tar_cfg) - 1: j_cfg]  # -1 해서 '{' 포함
        ytcfg = json.loads(ytcfg_str)

        return ytinit, ytcfg

    # ------------------------------
    # 내부: videoRenderer에서 정보 뽑기
    # ------------------------------
    def _parse_videos_from_json(
        self,
        data: Dict,
        limit: int,
    ) -> List[Dict]:
        """
        JSON 블럭에서 videoRenderer들을 찾아
        (video_id, title, view_text 등)을 추출한다.
        """
        results = []

        for vr in search_dict(data, "videoRenderer"):
            video_id = vr.get("videoId")
            if not video_id or video_id in self.seen_ids:
                continue

            # 제목
            title = (
                vr.get("title", {})
                  .get("runs", [{}])[0]
                  .get("text", "")
            )

            # 조회수 텍스트 (예: '조회수 1.3만회' 또는 '1.3K views')
            vc = vr.get("viewCountText", {})
            view_text = vc.get("simpleText") or vc.get("runs", [{}])[0].get("text", "")

            # 채널명
            channel = ""
            byline = vr.get("longBylineText") or vr.get("ownerText")
            if byline and "runs" in byline and byline["runs"]:
                channel = byline["runs"][0].get("text", "")

            results.append({
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": title,
                "view_text": view_text,
                "channel": channel,
            })
            self.seen_ids.add(video_id)

            if len(results) >= limit:
                break

        return results

    # ------------------------------
    # 내부: continuationEndpoint 목록 추출
    # ------------------------------
    def _collect_continuation_endpoints(self, data: Dict) -> List[Dict]:
        """
        JSON 구조 전체에서 continuationItemRenderer → continuationEndpoint 를 찾아 리스트로 반환.
        """
        endpoints = []
        for item in search_dict(data, "continuationItemRenderer"):
            ep = item.get("continuationEndpoint")
            if not ep:
                continue
            endpoints.append(ep)
        return endpoints

    # ------------------------------
    # 퍼블릭 메서드: 검색 수행
    # ------------------------------
    def search(
        self,
        keyword: str,
        limit: int = 50,
        max_pages: int = 10,
        sleep_sec: float = 0.3,
    ) -> List[Dict]:
        """
        키워드로 YouTube 검색을 수행하고,
        최대 `limit` 개의 동영상 정보를 반환한다.
        - 여러 페이지(continuation)를 따라가며 수집
        - max_pages: continuation API 호출 최대 횟수 제한
        """
        print(f"[INFO] 검색 시작: '{keyword}' (목표: {limit}개, 최대 페이지: {max_pages})")
        self.seen_ids.clear() # 새 검색 시작 시 초기화

        # 1) 첫 페이지 GET
        params = {"search_query": keyword}
        resp = self.session.get(self.BASE_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()

        ytinit, ytcfg = self._extract_yt_objects(resp.text)

        # 2) 첫 페이지에서 비디오 수집
        videos: List[Dict] = []

        first_page_videos = self._parse_videos_from_json(ytinit, limit)
        videos.extend(first_page_videos)
        print(f"[INFO] 첫 페이지에서 {len(first_page_videos)}개 수집 (누적 {len(videos)}개)")

        if len(videos) >= limit:
            return videos[:limit]

        # 3) continuation endpoints 수집
        endpoints = self._collect_continuation_endpoints(ytinit)
        visited_tokens = set()

        page_count = 0

        while endpoints and len(videos) < limit and page_count < max_pages:
            page_count += 1
            endpoint = endpoints.pop()

            token = endpoint.get("continuationCommand", {}).get("token")
            api_url_path = endpoint.get("commandMetadata", {}).get("webCommandMetadata", {}).get("apiUrl")
            if not token or not api_url_path:
                continue

            if token in visited_tokens:
                continue
            visited_tokens.add(token)

            api_url = "https://www.youtube.com" + api_url_path

            payload = {
                "context": ytcfg["INNERTUBE_CONTEXT"],
                "continuation": token,
            }

            try:
                print(f"[INFO] 페이지 {page_count} 요청: {api_url}")
                r = self.session.post(
                    api_url,
                    params={"key": ytcfg["INNERTUBE_API_KEY"]},
                    json=payload,
                    timeout=10,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"[WARN] continuation 요청 실패: {e}")
                break

            # 3-1) 이 페이지에서 비디오 수집
            new_videos = self._parse_videos_from_json(data, limit - len(videos))
            videos.extend(new_videos)
            print(f"[INFO] continuation 페이지에서 {len(new_videos)}개 추가 (누적 {len(videos)}개)")

            if len(videos) >= limit:
                break

            # 3-2) 다음 continuation endpoints 추가 수집
            new_endpoints = self._collect_continuation_endpoints(data)
            endpoints.extend(new_endpoints)

            # 서버 부하/봇 차단 피하기 위해 약간의 쉬는 시간
            time.sleep(sleep_sec)

        print(f"[INFO] 검색 종료: 총 {len(videos)}개 수집")
        return videos[:limit]


# ------------------------------
# 단독 실행용 테스트 코드
# ------------------------------
if __name__ == "__main__":
    keyword = "파이썬 강좌"
    limit = 50

    searcher = YouTubeSearcher()
    results = searcher.search(keyword, limit=limit)

    print(f"\n--- '{keyword}' 검색 결과 상위 {len(results)}개 ---")
    for i, v in enumerate(results, start=1):
        print(f"{i}. {v['title']}")
        print(f"   채널: {v['channel']}")
        print(f"   URL  : {v['url']}")
        print(f"   조회수 텍스트: {v['view_text']}")

    print(f"\n--- 최종 수집된 video_id (총 {len(searcher.seen_ids)}개) ---")
    # 보기 좋게 정렬하여 출력
    sorted_ids = sorted(list(searcher.seen_ids))
    for video_id in sorted_ids:
        print(video_id)