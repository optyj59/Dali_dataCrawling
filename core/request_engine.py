import requests
import json
import time
import re
from typing import Any, Dict, List, Optional
from datetime import datetime


def search_dict(dic: Any, search_key: str):
    """
    중첩 JSON(dict/list) 전체를 DFS로 돌면서 특정 key를 가진 value를 yield.
    """
    stack = [dic]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == search_key:
                    yield v
                stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                stack.append(v)


class RequestCommentEngineA:
    BASE_URL = "https://www.youtube.com/watch?v="

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    " AppleWebKit/537.36 (KHTML, like Gecko)"
                    " Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

    # ------------------------------
    # watch HTML 에서 ytInitialData, ytcfg.set 추출
    # ------------------------------
    def _extract_yt_objects(self, html: str):
    # --- ytInitialData 추출 ---
        init_match = re.search(r"ytInitialData\"\s*:\s*({.*?})\s*,\s*\"ytInitialPlayerResponse", html)
        if not init_match:
            init_match = re.search(r"var ytInitialData = ({.*?});", html)

        if not init_match:
            raise RuntimeError("ytInitialData 못 찾음")

        ytinit = json.loads(init_match.group(1))

        # --- ytcfg.set 추출 ---
        cfg_match = re.search(r"ytcfg\.set\(\s*({.*?})\s*\)", html)
        if not cfg_match:
            raise RuntimeError("ytcfg.set JSON 못 찾음")

        ytcfg = json.loads(cfg_match.group(1))

        return ytinit, ytcfg

    def _parse_str_to_int(self, s: str) -> int:
        """ "조회수 1,234회" 같은 문자열에서 숫자만 뽑아서 int로 변환 """
        if not s:
            return 0
        
        digits = re.findall(r'\d+', s)
        if not digits:
            return 0
        
        return int("".join(digits))

    # ------------------------------
    # 새 구조의 commentEntityPayload → 표준 dict
    # ------------------------------
    def _parse_comment_from_entity(self, entity: Dict, video_id: str, collection_time: datetime) -> Optional[Dict]:
        """
        mutation.payload.commentEntityPayload 1개를 표준 dict로 변환.
        신구조와 구구조를 모두 호환하려고 시도.
        """
        properties = entity.get("properties", {})
        toolbar = entity.get("toolbar", {})
        author_info = entity.get("author", {})

        # --- 댓글 ID ---
        cid = (
            entity.get("commentId")
            or entity.get("id")
            or entity.get("commentKey")
            or properties.get("commentId")
        )
        if not cid:
            # ID 없으면 댓글 아님
            return None

        # --- Parent ID (대댓글용) ---
        parent_id = entity.get("parentCommentId")
        if not parent_id and "." in cid:
            parent_id = cid.split(".", 1)[0]
        
        # --- 내용 ---
        text = ""
        content_obj = properties.get("content", {})
        if isinstance(content_obj, dict):
            # 신구조: entity.properties.content.content
            text = content_obj.get("content", "")

        if not text:
            # 구구조: entity.content.runs[].text
            content_obj = entity.get("content", {})
            if isinstance(content_obj, dict):
                runs = content_obj.get("runs", [])
                text = "".join(r.get("text", "") for r in runs)

        if not text:
            # 구구조2: entity.originalContent.runs[].text
            content_obj = entity.get("originalContent", {})
            if isinstance(content_obj, dict):
                runs = content_obj.get("runs", [])
                text = "".join(r.get("text", "") for r in runs)

        # --- 작성자 ---
        author = author_info.get("displayName", "")
        if not author:
            # 구구조
            author = entity.get("authorDisplayName", "")
        if not author and "authorText" in entity:
            # 구구조 2
            aruns = entity["authorText"].get("runs", [])
            if aruns:
                author = aruns[0].get("text", "")

        # --- 좋아요 수 ---
        likes = 0
        likes_str = toolbar.get("likeCountA11y", "") # e.g. "좋아요 12개"
        if likes_str:
            like_digits = re.findall(r'\d+', likes_str)
            if like_digits:
                likes = int("".join(like_digits))
        else:
            # 구구조
            if "likeCount" in entity:
                likes = entity.get("likeCount") or 0
            elif "voteCount" in entity:
                vc = entity.get("voteCount", {})
                if isinstance(vc, dict):
                    s = vc.get("simpleText") or "0"
                    s = s.replace(",", "").strip()
                    if s.isdigit():
                        likes = int(s)

        # --- 답글 수 (이 댓글에 달린) ---
        reply_count = 0
        reply_str = toolbar.get("replyCountA11y", "") # e.g. "답글 5개"
        if reply_str:
            reply_digits = re.findall(r'\d+', reply_str)
            if reply_digits:
                reply_count = int("".join(reply_digits))

        # --- 답글 깊이 (0=최상위, 1=대댓글, 2=대대댓글) ---
        reply_level = properties.get("replyLevel", 0)

        # --- 작성 시각 ---
        created_time = properties.get("publishedTime", "")
        if not created_time:
            # 구구조
            if "publishedTimeText" in entity:
                pruns = entity["publishedTimeText"].get("runs", [])
                if pruns:
                    created_time = pruns[0].get("text", "")

        return {
            "id": cid,
            "parent_id": parent_id,
            "video_id": video_id,
            "author": author,
            "content": text,
            "likes": likes,
            "created_time": created_time,
            "collection_time": collection_time,
            "reply_count": reply_count,
            "reply_level": reply_level,
        }

    # ------------------------------
    # 단일 next 응답에서 댓글 뽑기
    # ------------------------------
    def _parse_comments_from_response(self, data: Dict, video_id: str) -> List[Dict]:
        """
        단일 next 응답(data)에서 댓글 리스트 추출.
        1순위: frameworkUpdates.entityBatchUpdate.mutations[].payload.commentEntityPayload
        2순위: 구버전 commentRenderer (혹시 섞여 들어오는 경우)
        """
        results: List[Dict] = []
        collection_time = datetime.now()

        # 1) 새 구조
        fb = (
            data.get("frameworkUpdates", {})
            .get("entityBatchUpdate", {})
        )
        mutations = fb.get("mutations", []) if isinstance(fb, dict) else []

        for mut in mutations:
            payload = mut.get("payload") or {}
            entity = payload.get("commentEntityPayload")
            
            if not entity:
                continue
            c = self._parse_comment_from_entity(entity, video_id, collection_time)
            if c:
                results.append(c)

        # 2) 옛날 구조 commentRenderer도 혹시 있으면 같이 먹기
        for cr in search_dict(data, "commentRenderer"):
            fake_entity = {
                "commentId": cr.get("commentId"),
                "authorText": cr.get("authorText"),
                "content": cr.get("contentText"),
                "voteCount": cr.get("voteCount"),
                "publishedTimeText": cr.get("publishedTimeText"),
            }
            c = self._parse_comment_from_entity(fake_entity, video_id, collection_time)
            if c:
                results.append(c)

        return results

    # ------------------------------
    # 전체 댓글 수집 메인 함수
    # ------------------------------
    def get_all_comments(self, video_id: str, min_views: int = 0, min_comments: int = 0) -> List[Dict]:
        url = self.BASE_URL + video_id
        print(f"[INFO] 댓글 크롤링 시작: {url}")

        # 1) watch HTML GET
        res = self.session.get(url, timeout=10)
        res.raise_for_status()
        html = res.text

        ytinit, ytcfg = self._extract_yt_objects(html)

        # ----------------------------------------
        # 1. 조회수 필터링
        # ----------------------------------------
        if min_views > 0:
            view_count_str = ""
            # ytInitialData에서 videoPrimaryInfoRenderer를 탐색
            primary_info = next(search_dict(ytinit, "videoPrimaryInfoRenderer"), None)
            if primary_info:
                view_count_str = (
                    primary_info.get("viewCount", {})
                    .get("videoViewCountRenderer", {})
                    .get("viewCount", {})
                    .get("simpleText", "")
                )
            
            view_count = self._parse_str_to_int(view_count_str)
            print(f"[INFO] 현재 영상 조회수: {view_count} (필터: {min_views})")

            if view_count < min_views:
                print(f"[WARN] 조회수({view_count})가 설정된 값({min_views})보다 낮아 댓글을 수집하지 않습니다.")
                return []
        # ----------------------------------------



        # 2) 초기 comments continuation endpoint 찾기 (스승님 방식 그대로)
        section = next(search_dict(ytinit.get("contents", {}), "itemSectionRenderer"), None)
        renderer = next(search_dict(section, "continuationItemRenderer"), None) if section else None

        if not renderer:
            print("[WARN] 초기 comments continuationItemRenderer를 찾지 못했습니다.")
            return []

        endpoints = [renderer["continuationEndpoint"]]

        all_comments: List[Dict] = []
        seen_ids = set()
        round_count = 0

        while endpoints:
            round_count += 1
            endpoint = endpoints.pop()

            api_url = (
                "https://www.youtube.com"
                + endpoint["commandMetadata"]["webCommandMetadata"]["apiUrl"]
            )
            token = endpoint["continuationCommand"]["token"]

            print(f"[INFO] continuation {round_count}: {api_url}")

            payload = {
                "context": ytcfg["INNERTUBE_CONTEXT"],
                "continuation": token,
            }

            resp = self.session.post(
                api_url,
                params={"key": ytcfg["INNERTUBE_API_KEY"]},
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            # 3) 이번 응답에서 댓글 파싱
            new_comments = []
            for c in self._parse_comments_from_response(data, video_id):
                if c["id"] in seen_ids:
                    continue
                seen_ids.add(c["id"])
                new_comments.append(c)

            print(f"[INFO] 라운드 {round_count} → 새로운 댓글 {len(new_comments)}개")
            all_comments.extend(new_comments)

            # ----------------------------------------
            # 2. 댓글 수 필터링 (첫 응답에서만 실행)
            # ----------------------------------------
            if round_count == 1 and min_comments > 0:
                comment_count_str = ""
                header = next(search_dict(data, "commentsHeaderRenderer"), None)
                if header:
                    runs = header.get("countText", {}).get("runs", [])
                    if len(runs) > 1: # '댓글 ' + '503' + '개' 구조이므로 2번째 요소(index 1)에 숫자가 있음
                        comment_count_str = runs[1].get("text", "")
                
                total_comments = self._parse_str_to_int(comment_count_str)
                print(f"[INFO] 전체 댓글 수: {total_comments} (필터: {min_comments})")

                if total_comments < min_comments:
                    print(f"[WARN] 댓글 수({total_comments})가 설정된 값({min_comments})보다 낮아 추가 수집을 중단합니다.")
                    return all_comments  # 현재까지 수집된 첫 페이지만 반환
            # ----------------------------------------

            # 4) 다음 continuation endpoint 수집 (스승님 로직 스타일)
            reload_items = list(search_dict(data, "reloadContinuationItemsCommand"))
            append_items = list(search_dict(data, "appendContinuationItemsAction"))
            actions = reload_items + append_items

            for action in actions:
                # 타겟이 comments-section인 것만
                if action.get("targetId") != "comments-section":
                    continue
                for item in action.get("continuationItems", []):
                    for ep in search_dict(item, "continuationEndpoint"):
                        endpoints.append(ep)

            time.sleep(0.25)  # 서버 부하 방지용

        print(f"[INFO] 최종 댓글 수집 완료: 총 {len(all_comments)}개")
        return all_comments


if __name__ == "__main__":
    vid = "FbXQmI7IkZg"  # 테스트용
    engine = RequestCommentEngineA()
    comments = engine.get_all_comments(vid, min_views=100, min_comments=5)

    print(f"\n--- 총 {len(comments)}개 ---")
    for c in comments[:10]:
        print(c)
