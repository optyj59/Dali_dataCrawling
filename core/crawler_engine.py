import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re
import csv
from datetime import datetime
import os

class CrawlerEngine:
    BASE_URL = "https://www.youtube.com/watch?v="

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None

    async def initialize(self):
        print("Playwright를 초기화합니다...")
        # headless=False로 설정하여 브라우저 동작을 눈으로 확인할 수 있습니다. (디버깅 용이)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        print("Playwright 초기화 완료.")
 
    async def get_video_metadata(self, video_id: str):
        """
        영상 페이지에서 메타데이터 (조회수, 댓글 수 등)를 추출합니다.
        """
        video_url = self.BASE_URL + video_id
        print(f"영상 메타데이터 수집 중: {video_url}")
        await self.page.goto(video_url)
        await self.page.wait_for_load_state('networkidle')

        # 페이지를 약간 아래로 스크롤하여 댓글 섹션 로드를 유도합니다.
        await self.page.evaluate("window.scrollTo(0, 500)")
        
        # 댓글 섹션의 핵심 요소가 나타날 때까지 대기
        try:
            await self.page.wait_for_selector("ytd-comments-header-renderer .count-text", timeout=10000)
        except Exception:
            print("경고: 댓글 섹션 로드에 실패했습니다.")

        # Beautiful Soup 파싱을 위한 HTML 콘텐츠 추출
        html_content = await self.page.content()
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- 메타데이터 추출 로직 (이전 코드 유지) ---
        def parse_count(text):
            text = text.lower().replace(',', '')
            text = re.sub(r'(views|조회수|댓글)\s*', '', text)
            value = re.search(r'[\d,.]+', text)
            if not value: return 0
            value = value.group()
            
            if 'k' in text or '천' in text: return int(float(value) * 1000)
            if 'm' in text or '백만' in text: return int(float(value) * 1000000)
            if '만' in text: return int(float(value) * 10000)
            try: return int(float(value))
            except ValueError: return 0
            
        view_count_text = '0'
        tooltip_element = soup.select_one('tp-yt-paper-tooltip.ytd-watch-info-text')
        if tooltip_element:
            tooltip_content = tooltip_element.select_one('#tooltip')
            if tooltip_content:
                tooltip_text = tooltip_content.text.strip()
                match = re.search(r'조회수 ([\d,]+)회', tooltip_text)
                if match: view_count_text = match.group(1)

        upload_date_element = soup.select_one('meta[itemprop="uploadDate"]')
        upload_date_text = upload_date_element['content'] if upload_date_element and 'content' in upload_date_element.attrs else ''
        
        comment_count_text = '0'
        count_element = soup.select_one("ytd-comments-header-renderer .count-text")
        if count_element:
            comment_count_text = count_element.text
        # --- 메타데이터 추출 로직 끝 ---
        
        metadata = {
            'upload_date': upload_date_text,
            'view_count': parse_count(view_count_text),
            'comment_count': parse_count(comment_count_text)
        }
        return metadata
    
    async def extract_comments_no_reply(self, video_id: str):
        video_url = self.BASE_URL + video_id
        print(f"[INFO] 시작: 최상위 댓글 수집 (답글 미포함) {video_url}")

        if self.page.url != video_url:
            await self.page.goto(video_url, wait_until="load")

        # 초기 스크롤
        await self.page.evaluate("window.scrollTo(0, 600)")
        await self.page.wait_for_selector("ytd-comment-thread-renderer", timeout=20000)
        print("[INFO] 댓글 섹션 로드 완료")

        # ---------------------------------------------------
        # STEP 1 — 과감 스크롤 기반 최상위 댓글 완전 로딩
        # ---------------------------------------------------
        print("[INFO] STEP 1: 최상위 댓글 로딩 시작 (과감 스크롤 + STALL 유지)")

        STALL = 0
        STALL_LIMIT = 5  # 기존 구조 유지

        while True:
            prev_count = await self.page.evaluate(
                "document.querySelectorAll('ytd-comment-thread-renderer').length"
            )

            for _ in range(3):     # “한 라운드”에서 3번 정도 big scroll
                await self.page.evaluate("window.scrollBy(0, 1000)")  
                await asyncio.sleep(0.20)  # 너무 짧게 하면 로딩 타이밍 놓침

            # ------------------------------
            # 댓글 thread 수 증가 확인
            # ------------------------------
            new_count = await self.page.evaluate(
                "document.querySelectorAll('ytd-comment-thread-renderer').length"
            )

            if new_count == prev_count:
                STALL += 1
                print(f"[SCROLL] 증가 없음 (stall {STALL}/{STALL_LIMIT})")
            else:
                STALL = 0  # 증가했으면 stall 초기화

            # ------------------------------
            # 종료 조건: 더 이상 로드되지 않음
            # ------------------------------
            if STALL >= STALL_LIMIT:
                print("[INFO] 최상위 댓글 완전 로드 완료 (STALL 종료)")
                break
        
        print("\n[INFO] STEP 2: HTML 파싱 및 최상위 댓글 추출")
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")

        comments = []
        processed_ids = set()

        # top-level 댓글만 파싱
        for thread in soup.select("ytd-comment-thread-renderer"):

            # -------- top-level --------
            # 각 thread의 첫번째 ytd-comment-view-model이 최상위 댓글
            top = thread.select_one("ytd-comment-view-model")
            if top:
                time_link = top.select_one('#published-time-text a')
                href = time_link.get('href') if time_link else None
                cid, pid = None, None

                if href:
                    m = re.search(r'&lc=([\w.-]+)', href)
                    if m:
                        fid = m.group(1)
                        # 최상위 댓글은 ID에 '.'이 없음
                        if '.' not in fid:
                            cid = fid
                        else:
                            # '.'이 있으면 답글이므로 건너뜀
                            continue
                
                # href가 없는 댓글 등 예외 상황을 고려하여 cid가 있을 때만 처리
                if cid and cid not in processed_ids:
                    comments.append({
                        "id": cid,
                        "parent_id": None, # 최상위 댓글은 parent_id가 없음
                        "author": (top.select_one("#author-text") or {}).text.strip(),
                        "content": (top.select_one("#content-text") or {}).text.strip(),
                        "likes": (top.select_one("#vote-count-middle") or {}).text.strip() or "0",
                        "created_time": time_link.text.strip() if time_link else "",
                    })
                    processed_ids.add(cid)

        print(f"[INFO] 총 수집된 최상위 댓글 수: {len(comments)}")
        return comments


    async def extract_comments(self, video_id: str):
        """
        초고속 / 안정 완전수집 버전 (reply 증가량 기반 종료)
        1) 모든 top-level thread 로딩 (stall 기반)
        2) reply 버튼을 전역에서 모두 클릭하되,
           reply DOM 증가량이 0이면 즉시 종료
        3) HTML 파싱
        """
        video_url = self.BASE_URL + video_id
        print(f"[INFO] 시작: 댓글 수집 (reply 증가량 기반 완전수집) {video_url}")

        if self.page.url != video_url:
            await self.page.goto(video_url, wait_until="load")

        # 초기 스크롤
        await self.page.evaluate("window.scrollTo(0, 600)")
        await self.page.wait_for_selector("ytd-comment-thread-renderer", timeout=20000)
        print("[INFO] 댓글 섹션 로드 완료")

        # ---------------------------------------------------
        # STEP 1 — 과감 스크롤 기반 최상위 댓글 완전 로딩
        # ---------------------------------------------------
        print("[INFO] STEP 1: 최상위 댓글 로딩 시작 (과감 스크롤 + STALL 유지)")

        STALL = 0
        STALL_LIMIT = 5  # 기존 구조 유지

        while True:
            prev_count = await self.page.evaluate(
                "document.querySelectorAll('ytd-comment-thread-renderer').length"
            )

            for _ in range(3):     # “한 라운드”에서 3번 정도 big scroll
                await self.page.evaluate("window.scrollBy(0, 1000)")  
                await asyncio.sleep(0.20)  # 너무 짧게 하면 로딩 타이밍 놓침

            # ------------------------------
            # 댓글 thread 수 증가 확인
            # ------------------------------
            new_count = await self.page.evaluate(
                "document.querySelectorAll('ytd-comment-thread-renderer').length"
            )

            if new_count == prev_count:
                STALL += 1
                print(f"[SCROLL] 증가 없음 (stall {STALL}/{STALL_LIMIT})")
            else:
                STALL = 0  # 증가했으면 stall 초기화

            # ------------------------------
            # 종료 조건: 더 이상 로드되지 않음
            # ------------------------------
            if STALL >= STALL_LIMIT:
                print("[INFO] 최상위 댓글 완전 로드 완료 (STALL 종료)")
                break
        # ---------------------------------------------------
        # STEP 2 — 답글 보기 버튼 일괄 클릭 → 이어서 답글 더보기 반복 오픈
        # ---------------------------------------------------
        print("\n[INFO] STEP 2: 답글 전체 오픈 시작")

        # ---------------------------------------------------
        # (1) 1차: reply “답글 보기” 버튼을 일괄적으로 먼저 클릭
        # ---------------------------------------------------
        print("[REPLIES] 1차: '답글 보기' 버튼 일괄 클릭 시도")

        # 닫힌 상태의 reply 컨테이너에서 '답글 보기' 버튼 찾기
        initial_reply_buttons = await self.page.query_selector_all(
            "ytd-comment-thread-renderer:has(ytd-comment-replies-renderer[hidden]) "
            "ytd-button-renderer#more-replies:not([disabled])"
        )

        # 이미 reply 영역이 열린 thread 내부에서 또 존재하는 more-replies
        opened_reply_buttons = await self.page.query_selector_all(
            "ytd-comment-replies-renderer:not([hidden]) ytd-button-renderer#more-replies:not([disabled])"
        )

        candidate_buttons = initial_reply_buttons + opened_reply_buttons
        print(f"[REPLIES] 1차 후보 reply 버튼: {len(candidate_buttons)}개")

        # '숨기기' 버튼 제외
        buttons_to_click = []
        for btn in candidate_buttons:
            try:
                txt = await btn.inner_text()
                if "숨기기" not in txt and "Hide" not in txt:
                    buttons_to_click.append(btn)
            except:
                pass

        print(f"[REPLIES] 실제 클릭할 '답글 보기' 버튼: {len(buttons_to_click)}개")

        for btn in buttons_to_click:
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(0.15)
            except Exception as e:
                print(f"[WARN] reply 보기 버튼 클릭 실패 (무시): {e}")

        # 클릭 후 DOM 안정화 대기
        print("[REPLIES] 1차 클릭 완료. DOM 안정화 대기 2초...")
        await asyncio.sleep(2)


        # ---------------------------------------------------
        # (2) 2차: continuation-item 기반 “답글 더보기” 반복 오픈
        # ---------------------------------------------------
        print("\n[REPLIES] 2차: continuation-item 기반 반복 reply 열기 시작")

        round_count = 0
        while True:
            round_count += 1

            continuations = await self.page.query_selector_all(
                "ytd-comment-replies-renderer ytd-continuation-item-renderer"
            )

            print(f"[REPLIES] 라운드 {round_count}: continuation-item {len(continuations)}개 발견")

            if not continuations:
                print("[REPLIES] 더 이상 continuation-item 없음 → reply 완전 오픈 완료")
                break

            for cont in continuations:
                try:
                    await cont.scroll_into_view_if_needed()
                    button = await cont.query_selector("ytd-button-renderer button")
                    if button:
                        await button.click()
                        await asyncio.sleep(0.20)
                except Exception as e:
                    print(f"[WARN] continuation-item 클릭 실패: {e}")

            # DOM 업데이트 대기
            await asyncio.sleep(0.5)

        print("[REPLIES] STEP 2 완료 → HTML 파싱 단계로 이동")

        # ---------------------------------------------------
        # STEP 3 — HTML 파싱
        # ---------------------------------------------------
        print("\n[INFO] STEP 3: HTML 파싱 시작")

        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")

        comments = []
        processed_ids = set()

        # top-level + replies 모두 파싱
        for thread in soup.select("ytd-comment-thread-renderer"):

            # -------- top-level --------
            top = thread.select_one("ytd-comment-view-model")
            if top:
                time_link = top.select_one('#published-time-text a')
                href = time_link.get('href') if time_link else None
                cid, pid = None, None

                if href:
                    m = re.search(r'&lc=([\w.-]+)', href)
                    if m:
                        fid = m.group(1)
                        if '.' in fid:
                            pid, cid = fid.split('.', 1)
                        else:
                            cid = fid

                if cid and cid not in processed_ids:
                    comments.append({
                        "id": cid,
                        "parent_id": pid,
                        "author": (top.select_one("#author-text") or {}).text.strip(),
                        "content": (top.select_one("#content-text") or {}).text.strip(),
                        "likes": (top.select_one("#vote-count-middle") or {}).text.strip() or "0",
                        "created_time": time_link.text.strip() if time_link else "",
                    })
                    processed_ids.add(cid)

            # -------- replies --------
            for reply in thread.select("ytd-comment-replies-renderer ytd-comment-view-model"):
                time_link = reply.select_one('#published-time-text a')
                href = time_link.get('href') if time_link else None
                rid, pid = None, None

                if href:
                    m = re.search(r'&lc=([\w.-]+)', href)
                    if m:
                        fid = m.group(1)
                        if '.' in fid:
                            pid, rid = fid.split('.', 1)
                        else:
                            rid = fid

                if rid and rid not in processed_ids:
                    comments.append({
                        "id": rid,
                        "parent_id": pid,
                        "author": (reply.select_one("#author-text") or {}).text.strip(),
                        "content": (reply.select_one("#content-text") or {}).text.strip(),
                        "likes": (reply.select_one("#vote-count-middle") or {}).text.strip() or "0",
                        "created_time": time_link.text.strip() if time_link else "",
                    })
                    processed_ids.add(rid)

        print(f"[INFO] 총 수집된 댓글 수(답글 포함): {len(comments)}")
        return comments


    def mask_pii(self, text: str) -> str:
        """
        간단한 PII 마스킹을 적용합니다. (이메일, 전화번호)
        """
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_MASKED]', text)
        text = re.sub(r'\d{2,3}-\d{3,4}-\d{4}', '[PHONE_MASKED]', text)
        return text

    async def close(self):
        print("Playwright를 종료합니다...")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("Playwright 종료 완료.")
