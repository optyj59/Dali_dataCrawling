import requests
import json
import time
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import os


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

    def _parse_yt_number(self, s: str) -> int:
        """
        '1,234', '1.23만', '12.3억' 등의 YouTube 형식 숫자를 int로 변환.
        """
        if not s:
            return 0
        
        s = s.lower().strip()
        s = s.replace(',', '')

        # 숫자와 단위를 문자열 어디에서든 찾기 위한 정규표현식
        match = re.search(r'([\d\.]+)(천|만|억|조)?', s)
        if not match:
            return 0

        num_part_str = match.group(1)
        unit_part = match.group(2)

        try:
            num = float(num_part_str)
        except ValueError:
            return 0

        multiplier = 1
        if unit_part == '천':
            multiplier = 1_000
        elif unit_part == '만':
            multiplier = 10_000
        elif unit_part == '억':
            multiplier = 100_000_000
        elif unit_part == '조':
            multiplier = 1_000_000_000_000

        return int(num * multiplier)

    # ------------------------------
    # watch HTML 에서 ytInitialData, ytcfg.set 추출
    # ------------------------------

    def _parse_relative_time(self, time_str: str) -> datetime:
        """
        '3일 전', '1시간 전', '2023. 1. 1.' 등의 시간을 절대 시간으로 변환합니다.
        """
        now = datetime.now()
        time_str = time_str.strip()

        try:
            if "년 전" in time_str:
                years = int(re.search(r'(\d+)', time_str).group(1))
                return now.replace(year=now.year - years)
            elif "개월 전" in time_str:
                months = int(re.search(r'(\d+)', time_str).group(1))
                # 월 계산은 복잡하므로 단순화
                total_months = now.year * 12 + now.month - months
                new_year = total_months // 12
                new_month = total_months % 12 + 1
                return now.replace(year=new_year, month=new_month)
            elif "주 전" in time_str:
                weeks = int(re.search(r'(\d+)', time_str).group(1))
                return now - timedelta(weeks=weeks)
            elif "일 전" in time_str:
                days = int(re.search(r'(\d+)', time_str).group(1))
                return now - timedelta(days=days)
            elif "시간 전" in time_str:
                hours = int(re.search(r'(\d+)', time_str).group(1))
                return now - timedelta(hours=hours)
            elif "분 전" in time_str:
                minutes = int(re.search(r'(\d+)', time_str).group(1))
                return now - timedelta(minutes=minutes)
            elif "초 전" in time_str:
                seconds = int(re.search(r'(\d+)', time_str).group(1))
                return now - timedelta(seconds=seconds)
            elif "방금 전" in time_str or "Just now" in time_str:
                return now
            else:
                # '2023. 10. 2.' 와 같은 형식 시도
                match = re.search(r'(\d{4})\. (\d{1,2})\. (\d{1,2})\.', time_str)
                if match:
                    return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except (ValueError, AttributeError):
             # 파싱 실패 시 현재 시간 반환
            return now
        
        # 모든 조건에 맞지 않으면 현재 시간 반환
        return now

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
        created_time_str = properties.get("publishedTime", "")
        if not created_time_str:
            # 구구조
            if "publishedTimeText" in entity:
                pruns = entity["publishedTimeText"].get("runs", [])
                if pruns:
                    created_time_str = pruns[0].get("text", "")
        
        # 상대 시간 문자열을 절대 datetime 객체로 변환
        created_time = collection_time # 기본값
        if created_time_str:
            try:
                created_time = self._parse_relative_time(created_time_str)
            except Exception:
                # 파싱 실패 시 collection_time 사용
                pass



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
    def get_all_comments(self, video_id: str, min_views: int = 0, min_comments: int = 0) -> Tuple[Dict, List[Dict]]:
        url = self.BASE_URL + video_id
        print(f"[INFO] 댓글 크롤링 시작: {url}")

        # 1) watch HTML GET
        res = self.session.get(url, timeout=10)
        res.raise_for_status()
        html = res.text

        ytinit, ytcfg = self._extract_yt_objects(html)

        # =================================================================
        # STEP 2: 초기 요청으로 '최신순' 정렬 토큰 확보 (2-step)
        # =================================================================
        
        # 2a. ytInitialData에서 기본 '인기순' 토큰 찾기
        section = next(search_dict(ytinit.get("contents", {}), "itemSectionRenderer"), None)
        if not section:
            print("[ERROR] 초기 댓글 섹션(itemSectionRenderer)을 찾지 못했습니다.")
            return {}, []

        default_renderer = next(search_dict(section, "continuationItemRenderer"), None)
        if not default_renderer:
            print("[ERROR] 초기 토큰(continuationItemRenderer)을 찾지 못했습니다.")
            return {}, []

        # 2b. '인기순'으로 딱 한 번 요청해서 댓글 UI 데이터 확보
        print("[INFO] 정렬 메뉴를 얻기 위해 초기 요청(인기순)을 보냅니다...")
        endpoint = default_renderer["continuationEndpoint"]
        api_url = "https://www.youtube.com" + endpoint["commandMetadata"]["webCommandMetadata"]["apiUrl"]
        token = endpoint["continuationCommand"]["token"]
        
        payload = {"context": ytcfg["INNERTUBE_CONTEXT"], "continuation": token}
        resp = self.session.post(api_url, params={"key": ytcfg["INNERTUBE_API_KEY"]}, json=payload, timeout=10)
        resp.raise_for_status()
        initial_comment_data = resp.json()

        # ----------------------------------------
        # 0. 비디오 메타데이터 추출 (API 호출 이후)
        # API 응답에 최신 정보가 있을 수 있으므로 여기서 추출합니다.
        # ----------------------------------------
        primary_info_initial = next(search_dict(ytinit, "videoPrimaryInfoRenderer"), None)
        primary_info_updated = next(search_dict(initial_comment_data, "videoPrimaryInfoRenderer"), None)
        primary_info = primary_info_updated or primary_info_initial # 업데이트된 정보가 있으면 그것을 사용

        video_title = ""
        view_count = 0
        like_count = 0
        
        if primary_info:
            video_title = primary_info.get("title", {}).get("runs", [{}])[0].get("text", "")
            
            view_count_text = (
                primary_info.get("viewCount", {})
                .get("videoViewCountRenderer", {})
                .get("viewCount", {})
                .get("simpleText", "")
            )
            view_count = self._parse_yt_number(view_count_text)

            # 좋아요 수 (ViewModel 우선, Renderer 폴백)
            # 1. 최신 ViewModel 구조 탐색
            view_model = next(search_dict(primary_info, "segmentedLikeDislikeButtonViewModel"), None)
            if view_model:
                button_view_model = next(search_dict(view_model, "buttonViewModel"), None)
                if button_view_model:
                    # 1순위: 'title' 필드 (e.g., "693" 또는 "5.1천")
                    title_text = button_view_model.get("title", "")
                    if title_text:
                        like_count = self._parse_yt_number(title_text)

                    # 2순위: 'accessibilityText' 필드 (대체 텍스트)
                    if like_count == 0:
                        accessibility_text = button_view_model.get("accessibilityText", "")
                        if accessibility_text:
                            like_count = self._parse_yt_number(accessibility_text)

            # 2. ViewModel 구조가 없는 경우, 이전 Renderer 구조 재시도 (Fallback)
            if like_count == 0:
                like_renderer = next(search_dict(primary_info, "segmentedLikeDislikeButtonRenderer"), None)
                if like_renderer:
                    tooltip = like_renderer.get("likeButton", {}).get("toggleButtonRenderer", {}).get("defaultTooltip", "")
                    if tooltip:
                        like_count = self._parse_yt_number(tooltip)

            # 3. 최후의 보루
            if like_count == 0:
                 like_button = next(search_dict(primary_info, "likeButton"), None)
                 if like_button:
                    like_text = like_button.get("toggleButtonRenderer", {}).get("defaultText", {}).get("simpleText", "")
                    like_count = self._parse_yt_number(like_text)

        # 채널 정보 등 나머지 메타데이터 추출 (ytInitialData에서만 가져옴)
        secondary_info = next(search_dict(ytinit, "videoSecondaryInfoRenderer"), None)
        channel_title = ""
        upload_time_str = ""
        subscriber_count = 0
        if secondary_info:
            owner_renderer = secondary_info.get("owner", {}).get("videoOwnerRenderer", {})
            channel_title = owner_renderer.get("title", {}).get("runs", [{}])[0].get("text", "")
            upload_time_str = owner_renderer.get("publishedTimeText", {}).get("simpleText", "")
            subscriber_count_text = owner_renderer.get("subscriberCountText", {}).get("simpleText", "")
            subscriber_count = self._parse_yt_number(subscriber_count_text)

        upload_time = None
        try:
            match = re.search(r'(\d{4})\. (\d{1,2})\. (\d{1,2})\.', upload_time_str)
            if match:
                upload_time = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            else:
                # '3개월 전' 같은 상대 시간 처리
                upload_time = self._parse_relative_time(upload_time_str)
        except Exception:
            upload_time = datetime.now()

        video_data = {
            'video_id': video_id,
            'video_title': video_title,
            'channel_title': channel_title,
            'upload_time': upload_time,
            'view_count': view_count,
            'like_count': like_count,
            'dislike_count': 0,
            'subscriber_count': subscriber_count,
            'total_comment_count': 0 # 필터링 후 업데이트 예정
        }

        # 2c. 반환된 데이터에서 '최신순' 토큰 찾기
        sort_menu = next(search_dict(initial_comment_data, "sortFilterSubMenuRenderer"), None)
        newest_first_endpoint = None
        if sort_menu and 'subMenuItems' in sort_menu:
            for item in sort_menu['subMenuItems']:
                if not item.get('selected'): # 'selected=false'인 것이 '최신순'
                    newest_first_endpoint = item.get('serviceEndpoint')
                    break
        
        # 2d. '최신순' 토큰으로 엔드포인트 리스트 설정
        if newest_first_endpoint:
            print("[INFO] '최신순' 정렬 토큰을 성공적으로 찾았습니다. 크롤링을 시작합니다.")
            endpoints = [newest_first_endpoint]
        else:
            print("[ERROR] 초기 응답에서 '최신순' 정렬 옵션을 찾지 못했습니다. 크롤링을 중단합니다.")
            return video_data, []

        # ----------------------------------------
        # 1. 조회수 필터링
        # ----------------------------------------
        if min_views > 0:
            print(f"[INFO] 현재 영상 조회수: {view_count} (필터: {min_views})")
            '''
            if view_count < min_views:
                print(f"[WARN] 조회수({view_count})가 설정된 값({min_views})보다 낮아 댓글을 수집하지 않습니다.")
                return video_data, [] # 메타데이터는 반환
            '''
            


        # =================================================================
        # STEP 3: '최신순' 토큰으로 본격적인 댓글 수집 시작
        # =================================================================
        all_comments: List[Dict] = []
        seen_ids = set()
        round_count = 0

        # 첫 요청(2단계)에서 받은 댓글도 수집 대상에 포함
        initial_comments = self._parse_comments_from_response(initial_comment_data, video_id)
        print(f"[INFO] 초기 요청에서 댓글 {len(initial_comments)}개 확보")
        for c in initial_comments:
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                all_comments.append(c)


        while endpoints:
            round_count += 1
            endpoint = endpoints.pop()

            api_url = (
                "https://www.youtube.com"
                + endpoint["commandMetadata"]["webCommandMetadata"]["apiUrl"]
            )
            token = endpoint["continuationCommand"]["token"]

            print(f"[INFO] continuation {round_count} (최신순): {api_url[:50]}...")

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
                
                total_comments_from_api = self._parse_yt_number(comment_count_str)
                print(f"[INFO] 전체 댓글 수: {total_comments_from_api} (필터: {min_comments})")

                # video_data에 최종 댓글 수 업데이트
                video_data['total_comment_count'] = total_comments_from_api


                if total_comments_from_api < min_comments:
                    print(f"[WARN] 댓글 수({total_comments_from_api})가 설정된 값({min_comments})보다 낮아 추가 수집을 중단합니다.")
                    return video_data, all_comments  # 현재까지 수집된 첫 페이지만 반환
            # ----------------------------------------

            # 4) 다음 continuation endpoint 수집 
            new_endpoints = []
            reload_items = list(search_dict(data, "reloadContinuationItemsCommand"))
            append_items = list(search_dict(data, "appendContinuationItemsAction"))
            actions = reload_items + append_items

            for action in actions:
                # 타겟이 comments-section인 것만
                if action.get("targetId") != "comments-section":
                    continue
                for item in action.get("continuationItems", []):
                    for ep in search_dict(item, "continuationEndpoint"):
                        new_endpoints.append(ep)

            if not new_endpoints and not endpoints:
                print("[WARN] 다음 continuation token을 찾지 못했습니다. 마지막 응답을 'core/logs/last_response.json'에 저장합니다.")
                os.makedirs('core/logs', exist_ok=True)
                with open('core/logs/last_response.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

            endpoints.extend(new_endpoints)
            time.sleep(0.25)  # 서버 부하 방지용

        print(f"[INFO] 최종 댓글 수집 완료: 총 {len(all_comments)}개")
        
        # video_data에 최종 댓글 수 업데이트
        video_data['total_comment_count'] = len(all_comments)

        return video_data, all_comments

if __name__ == "__main__":
    vid = "yG17BZQHh8I"  # 테스트용
    engine = RequestCommentEngineA()
    # comments = engine.get_all_comments(vid, min_views=100, min_comments=5) # 주석 처리 또는 제거
    
    # 변경된 반환 타입에 맞게 호출
    video_data, comments = engine.get_all_comments(vid, min_views=100, min_comments=5)

    print(f"\n--- 총 {len(comments)}개 ---")
    print("\n--- 비디오 메타데이터 ---")
    for k, v in video_data.items():
        print(f"{k}: {v}")
    
    print("\n--- 첫 10개 댓글 ---")
    for c in comments[:10]:
        print(c)
