import asyncio
import pandas as pd
from playwright.async_api import async_playwright

async def scrape_google_trends():
    """
    Scrapes the top 50 daily search trends from Google Trends for South Korea.
    - Uses Playwright for headless browsing.
    - Handles pagination to load all 50 trends.
    - Saves the results to a CSV file.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print("구글 트렌드 접속 중...")
        try:
            await page.goto("https://trends.google.com/trending?geo=KR", wait_until="load", timeout=60000)
        except Exception as e:
            print(f"페이지 접속에 실패했습니다: {e}")
            await browser.close()
            return

        all_trends = []
        seen_keywords = set() # 중복 체크를 위한 집합(set)

        # Google Trends 페이지의 HTML 구조에 의존하는 CSS 선택자입니다.
        # 페이지 구조가 변경되면 스크립트가 오작동할 수 있습니다.
        ROW_SELECTOR = 'tr[role="row"]'
        TITLE_SELECTOR = 'div.mZ3RIc'
        COUNT_SELECTOR = 'div.qNpYPd'

        async def extract_visible_trends():
            """Extracts trend data from the currently visible rows on the page."""
            rows = await page.query_selector_all(ROW_SELECTOR)
            for row in rows:
                try:
                    title_el = await row.query_selector(TITLE_SELECTOR)
                    if not title_el:
                        continue
                        
                    keyword = (await title_el.inner_text()).strip()

                    # 중복 수집 방지 (더 효율적인 방식으로)
                    if keyword and keyword not in seen_keywords:
                        count_el = await row.query_selector(COUNT_SELECTOR)
                        count_info = (await count_el.inner_text()).strip() if count_el else "정보 없음"
                        
                        all_trends.append({
                            "순위": len(all_trends) + 1,
                            "검색어": keyword,
                            "검색량": count_info
                        })
                        seen_keywords.add(keyword)
                except Exception as e:
                    print(f"행 데이터 추출 중 오류 발생: {e}")
                    continue

        # 1. 첫 페이지 (1~25위) 수집
        print("1~25위 데이터 수집 중...")
        try:
            await page.wait_for_selector(TITLE_SELECTOR, timeout=10000) # 검색어가 나타날 때까지 대기
            await extract_visible_trends()
        except Exception as e:
            print(f"초기 데이터 로딩 실패: {e}. 페이지 구조가 변경되었을 수 있습니다.")
            await browser.close()
            return


        # 2. '다음 페이지' 버튼 클릭 (26~50위 로드)
        # 이 선택자 역시 페이지 구조 변경에 취약합니다.
        NEXT_BUTTON_SELECTOR = 'button[jsname="ViaHrd"]'
        if await page.query_selector(NEXT_BUTTON_SELECTOR):
            print("다음 페이지(26~50위) 로딩 중...")
            await page.click(NEXT_BUTTON_SELECTOR)
            
            # 페이지 전환 및 새로운 데이터 로딩 대기
            # 고정된 시간 대신 네트워크 활동이 끝날 때까지 기다려 더 안정적입니다.
            await page.wait_for_load_state("load", timeout=10000)
            
            print("26~50위 데이터 수집 중...")
            await extract_visible_trends()
        else:
            print("다음 페이지 버튼을 찾지 못했습니다. (오늘의 트렌드가 25개 미만일 수 있습니다)")

        await browser.close()

        if not all_trends:
            print("데이터를 수집하지 못했습니다. 클래스명이나 페이지 구조를 다시 확인해주세요.")
            return

        # 결과 저장 (최대 50개)
        df = pd.DataFrame(all_trends[:50])
        
        output_filename = "google_trends_kr_50.csv"
        df.to_csv(output_filename, index=False, encoding="utf-8-sig")
        
        print("-" * 30)
        print(f"총 {len(df)}개의 검색어를 '{output_filename}' 파일에 저장했습니다.")
        print("-" * 30)
        print("수집된 데이터 샘플 (상위 10개):")
        print(df.head(10))


if __name__ == "__main__":
    # Python 3.8+ 에서는 ProactorEventLoop is not supported on Windows 오류가 발생할 수 있어
    # 다음과 같이 정책을 설정하거나 asyncio.run()을 사용합니다.
    # asyncio.run()은 내부적으로 루프를 관리해주므로 보통은 문제가 없습니다.
    try:
        asyncio.run(scrape_google_trends())
    except KeyboardInterrupt:
        print("\n사용자에 의해 프로그램이 중단되었습니다.")