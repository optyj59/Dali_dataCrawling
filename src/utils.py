import csv
from datetime import datetime, timezone
import os

# data/keywords.csv 파일의 절대 경로를 설정합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORD_FILE_PATH = os.path.join(BASE_DIR, '..', 'data', 'keywords.csv')

def check_and_add_keyword(input_keyword: str):
    """
    입력된 키워드가 파일에 있는지 확인하고, 없으면 추가합니다.
    해당 키워드의 텍스트와 마지막 사용 시간을 반환합니다.
    """
    try:
        with open(KEYWORD_FILE_PATH, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            keywords = list(reader)
    except FileNotFoundError:
        # 파일이 없으면 새로 만들 준비를 합니다.
        keywords = []

    # 키워드 존재 여부 확인
    found_keyword = None
    for keyword in keywords:
        if keyword['keyword_text'] == input_keyword:
            found_keyword = keyword
            break

    if found_keyword:
        # 키워드가 존재할 경우
        print(f"기존 키워드입니다: '{input_keyword}' (마지막 사용: {found_keyword.get('last_used_time') or 'N/A'})")
        return found_keyword['keyword_text'], found_keyword.get('last_used_time')
    else:
        # 키워드가 존재하지 않을 경우
        print(f"새로운 키워드입니다: '{input_keyword}'. 파일에 추가합니다.")
        new_keyword = {'keyword_text': input_keyword, 'last_used_time': ''}
        keywords.append(new_keyword)
        
        # 파일을 다시 씁니다.
        try:
            with open(KEYWORD_FILE_PATH, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['keyword_text', 'last_used_time'])
                writer.writeheader()
                writer.writerows(keywords)
        except IOError:
            print(f"오류: {KEYWORD_FILE_PATH} 파일에 쓰는 중 문제가 발생했습니다.")
            return None, None
            
        return new_keyword['keyword_text'], None


def update_keyword_time(keyword_to_update: str):
    """
    지정된 키워드의 last_used_time을 현재 시간으로 갱신합니다.
    """
    try:
        with open(KEYWORD_FILE_PATH, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            keywords = list(reader)
    except FileNotFoundError:
        print(f"오류: {KEYWORD_FILE_PATH} 파일을 찾을 수 없습니다.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    
    updated = False
    for keyword in keywords:
        if keyword['keyword_text'] == keyword_to_update:
            keyword['last_used_time'] = now_iso
            updated = True
            break
    
    if not updated:
        print(f"오류: '{keyword_to_update}' 키워드를 파일에서 찾을 수 없습니다.")
        return

    try:
        with open(KEYWORD_FILE_PATH, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['keyword_text', 'last_used_time'])
            writer.writeheader()
            writer.writerows(keywords)
        print(f"'{keyword_to_update}' 키워드의 last_used_time을 {now_iso}로 업데이트했습니다.")
    except IOError:
        print(f"오류: {KEYWORD_FILE_PATH} 파일에 쓰는 중 문제가 발생했습니다.")