import psycopg2
from datetime import datetime
from typing import Dict, Any, List, Optional
import traceback

# TODO: 자신의 PostgreSQL 서버 설정에 맞게 아래 값을 수정해주세요.
DB_CONFIG = {
    "host": "localhost",
    "database": "postgres",
    "user": "postgres",
    "password": "!pearl0605",
    "port": "5432"
}

# --- 데이터 구조 정의 (크롤러에서 넘어오는 형태) ---
VideoData = Dict[str, Any]
CommentData = List[Dict[str, Any]]
MetadataData = Dict[str, Any]


class DBManager:
    """데이터베이스 연결 및 여러 테이블에 대한 CRUD 작업을 관리하는 클래스"""
    def __init__(self):
        """초기화 시 DB 설정을 저장합니다."""
        self.db_config = DB_CONFIG
        self.conn = None

    def connect(self):
        """데이터베이스에 연결합니다."""
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(client_encoding='UTF8', **self.db_config)
            except psycopg2.Error as e:
                print(f"데이터베이스 연결 오류: {e}")
                traceback.print_exc()
                self.conn = None
        return self.conn

    def close(self):
        """데이터베이스 연결을 닫습니다."""
        if self.conn and not self.conn.closed:
            self.conn.close()
            self.conn = None

    # -----------------------------------------------------------
    # [1] KEYWORD_MASTER 처리 (UPSERT)
    # -----------------------------------------------------------
    def insert_keyword(self, keyword_text: str) -> tuple[int, bool] | tuple[None, None]:
        """
        키워드를 KEYWORD_MASTER에 삽입하거나, 이미 존재하면 last_used_time을 업데이트합니다.
        성공 시 (keyword_id, existed_before) 튜플을 반환합니다.
        existed_before는 이 함수 호출 이전에 키워드가 존재했는지 여부를 나타냅니다.
        """
        self.connect()
        if not self.conn:
            return None, None

        now = datetime.now()
        keyword_id = None
        existed_before = False

        try:
            with self.conn.cursor() as cursor:
                # 1. 먼저 키워드가 존재하는지 확인
                cursor.execute("SELECT keyword_id FROM KEYWORD_MASTER WHERE keyword_text = %s;", (keyword_text,))
                if cursor.fetchone():
                    existed_before = True

                # 2. UPSERT 쿼리 실행
                sql = """
                    INSERT INTO KEYWORD_MASTER (keyword_text, last_used_time)
                    VALUES (%s, %s)
                    ON CONFLICT (keyword_text)
                    DO UPDATE SET last_used_time = %s
                    RETURNING keyword_id;
                """
                cursor.execute(sql, (keyword_text, now, now))
                result = cursor.fetchone()
                if result:
                    keyword_id = result[0]
                self.conn.commit()
        except psycopg2.Error as e:
            print(f"키워드 삽입 오류: {e}")
            self.conn.rollback()
            return None, None
        
        return keyword_id, existed_before

    # -----------------------------------------------------------
    # [2] VIDEO_MASTER 처리 (UPSERT)
    # -----------------------------------------------------------
    def insert_or_get_video(self, video_data: VideoData):
        """
        VIDEO_MASTER에 영상을 삽입하거나, 이미 존재하면 제목/채널 제목을 업데이트합니다.
        """
        sql = """
            INSERT INTO VIDEO_MASTER (video_id, video_title, channel_title, upload_time)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (video_id)
            DO UPDATE SET
                video_title = EXCLUDED.video_title,
                channel_title = EXCLUDED.channel_title
            RETURNING video_id;
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (
                video_data['video_id'], 
                video_data['video_title'], 
                video_data.get('channel_title'), 
                video_data['upload_time']
            ))
            cursor.close()
            # print(f"  > VIDEO_MASTER 처리 완료: {video_data['video_id']}")
            return True
        except psycopg2.Error as e:
            print(f"영상 마스터 삽입 오류: {e}")
            raise # 상위 트랜잭션에서 롤백 처리되도록 예외를 발생시킵니다.

    # -----------------------------------------------------------
    # [3] VIDEO_METADATA_LOG 처리 (단순 INSERT)
    # -----------------------------------------------------------
    def insert_video_metadata_log(self, metadata: MetadataData):
        """
        VIDEO_METADATA_LOG에 영상 메타데이터 스냅샷을 단순 삽입합니다. (SCD X)
        """
        sql = """
            INSERT INTO VIDEO_METADATA_LOG 
            (video_id, subscriber_count, view_count, like_count, dislike_count, total_comment_count, collection_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (
                metadata['video_id'],
                metadata.get('subscriber_count'),
                metadata['view_count'],
                metadata.get('like_count'),
                metadata.get('dislike_count'),
                metadata['total_comment_count'],
                metadata['collection_time']
            ))
            cursor.close()
            # print(f"  > VIDEO_METADATA_LOG 처리 완료")
            return True
        except psycopg2.Error as e:
            print(f"메타데이터 로그 삽입 오류: {e}")
            raise

    # -----------------------------------------------------------
    # [4] KEYWORD_VIDEO_MAPPING 처리 (단순 INSERT)
    # -----------------------------------------------------------
    def insert_keyword_video_mapping(self, video_id: str, keyword_id: int, collection_time: datetime):
        """
        KEYWORD_VIDEO_MAPPING 테이블에 키워드-영상 연결 이력을 삽입합니다.
        (PK 충돌 발생 시 무시합니다.)
        """
        sql = """
            INSERT INTO KEYWORD_VIDEO_MAPPING (video_id, keyword_id, collection_time)
            VALUES (%s, %s, %s)
            ON CONFLICT (video_id, keyword_id, collection_time)
            DO NOTHING;
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (video_id, keyword_id, collection_time))
            cursor.close()
            # print(f"  > MAPPING 처리 완료")
            return True
        except psycopg2.Error as e:
            print(f"매핑 테이블 삽입 오류: {e}")
            raise

    # -----------------------------------------------------------
    # [5] COMMENT_MASTER 처리 (SCD Type 2 로직)
    # -----------------------------------------------------------
    def process_comments(self, video_id: str, comments: List[Dict], collection_time: datetime):
        """
        SCD Type 2 로직을 사용하여 COMMENT_MASTER에 댓글을 적재합니다.
        - 신규 댓글은 INSERT
        - 내용이 변경된 댓글은 기존 레코드를 마감(valid_to_time)하고 신규 레코드를 INSERT
        - 변경이 없는 댓글은 무시
        """
        if not comments:
            return

        cursor = self.conn.cursor()

        # 1. DB에서 현재 video_id에 해당하는 최신 댓글 레코드(valid_to_time IS NULL)를 가져옴
        sql_select = "SELECT comment_id, content FROM COMMENT_MASTER WHERE video_id = %s AND valid_to_time IS NULL;"
        cursor.execute(sql_select, (video_id,))
        
        db_comments = {}
        for row in cursor.fetchall():
            db_comments[row[0]] = row[1]
        
        # 2. 크롤링된 댓글과 DB 댓글을 비교하여 변경분(Delta)을 찾음
        comments_to_insert = []
        comment_ids_to_expire = []

        for c in comments:
            comment_id = c['id']
            content = c.get('content', '')

            if comment_id not in db_comments:
                # 신규 댓글: INSERT 목록에 추가
                comments_to_insert.append(c)
            elif content != db_comments[comment_id]:
                # 내용이 변경된 댓글: 만료 목록과 INSERT 목록에 모두 추가
                comment_ids_to_expire.append(comment_id)
                comments_to_insert.append(c)
        
        print(f"  > COMMENT_MASTER: 신규 {len(comments_to_insert) - len(comment_ids_to_expire)}개, 수정 {len(comment_ids_to_expire)}개 댓글 처리")

        # 3. 내용이 변경된 기존 레코드를 마감 처리 (UPDATE)
        if comment_ids_to_expire:
            sql_expire = "UPDATE COMMENT_MASTER SET valid_to_time = %s WHERE video_id = %s AND comment_id = ANY(%s) AND valid_to_time IS NULL;"
            cursor.execute(sql_expire, (collection_time, video_id, comment_ids_to_expire))

        # 4. 신규 및 변경된 레코드를 일괄 삽입 (Bulk INSERT)
        if comments_to_insert:
            sql_insert = """
                INSERT INTO COMMENT_MASTER (
                    comment_id, video_id, user_name, content, parent_comment_id,
                    created_time, collection_time, valid_from_time, valid_to_time
                ) VALUES %s;
            """
            
            # created_time 파싱 (예: "3개월 전" -> datetime)
            # 현재는 단순화를 위해 created_time을 None으로 처리, 추후 파싱 로직 추가 가능
            
            insert_data = [
                (
                    c['id'], video_id, c.get('author'), c.get('content'), c.get('parent_id'),
                    c.get('created_time'), # 파싱된 datetime 객체 사용
                    collection_time, collection_time, None
                ) for c in comments_to_insert
            ]
            
            from psycopg2.extras import execute_values
            execute_values(cursor, sql_insert, insert_data)

        cursor.close()

    # -----------------------------------------------------------
    # [MAIN TRANSACTION] 모든 테이블을 아우르는 메인 트랜잭션 함수
    # -----------------------------------------------------------
    def process_full_data_transaction(self, video_data: VideoData, keyword_id: int, comments: List[Dict]):
        """
        단일 비디오에 대한 모든 데이터(Master, Metadata, Mapping, Comments)를 단일 트랜잭션으로 처리합니다.
        """
        self.connect()
        if not self.conn:
            print("DB 연결 실패로 트랜잭션 중단.")
            return False

        current_time = datetime.now()
        video_id = video_data['video_id']

        # [Debug] request_engine에서 받은 like_count 값을 로그로 출력
        received_like_count = video_data.get('like_count', 'KEY_NOT_FOUND')
        print(f"  > [Debug] Received like_count for video {video_id}: {received_like_count}")

        # 메타데이터 구조 (로그 테이블용)
        metadata_log = {
            'video_id': video_id,
            'subscriber_count': video_data.get('subscriber_count'),
            'view_count': video_data.get('view_count', 0),
            'like_count': video_data.get('like_count'),
            'dislike_count': video_data.get('dislike_count'),
            'total_comment_count': video_data.get('total_comment_count', 0),
            'collection_time': current_time 
        }

        try:
            print(f"\n[트랜잭션 시작] 영상 ID: {video_id}, 키워드 ID: {keyword_id}")
            
            # 1. VIDEO_MASTER (UPSERT)
            self.insert_or_get_video(video_data)

            # 2. VIDEO_METADATA_LOG (INSERT)
            self.insert_video_metadata_log(metadata_log)

            # 3. KEYWORD_VIDEO_MAPPING (INSERT)
            self.insert_keyword_video_mapping(video_id, keyword_id, current_time)

            # 4. COMMENT_MASTER (SCD Type 2)
            self.process_comments(video_id, comments, current_time)

            # 모든 작업 성공 시 커밋
            self.conn.commit()
            print(f" 트랜잭션 성공: 모든 데이터가 DB에 안전하게 저장되었습니다.")
            return True

        except Exception as e:
            print(f" 트랜잭션 오류 발생: {e}")
            self.conn.rollback() # 오류 발생 시 모든 변경사항 롤백
            print(" 롤백 완료: 데이터 일관성을 유지했습니다.")
            return False
        finally:
            self.close()


if __name__ == "__main__":
    print("DBManager 트랜잭션 테스트를 시작합니다...")
    
    # ----------------------------------------
    # A. 테스트 데이터 (크롤러에서 넘어온다고 가정)
    # ----------------------------------------
    test_time = datetime.now().replace(microsecond=0)
    
    # 1. 영상 마스터 데이터
    test_video_data = {
        'video_id': 'TestVideoSCD',
        'video_title': 'PostgreSQL SCD Type 2 마스터 강좌',
        'channel_title': '데이터웨어하우스 스튜디오',
        'upload_time': datetime(2023, 1, 15),
        'subscriber_count': 1000,
        'view_count': 150000,
        'like_count': 5000,
        'dislike_count': 10,
        'total_comment_count': 3
    }
    
    # 2. 댓글 데이터 (1차 수집)
    test_comments_1 = [
        {'id': 'CommentA', 'content': '정말 유익해요!', 'author': '김수강'},
        {'id': 'CommentB', 'content': '이해가 잘 안가네요.', 'author': '이초보'},
        {'id': 'CommentC', 'content': '최고의 강의입니다.', 'author': '박고수'},
    ]
    
    test_keyword_text = "SCD Type 2"
    
    db_manager = DBManager()
    
    try:
        # --- 1차 실행: 신규 데이터 삽입 ---
        print("\n--- 1차 실행: 모든 데이터 신규 삽입 ---")
        keyword_id = db_manager.insert_keyword(test_keyword_text)
        
        if keyword_id:
            success = db_manager.process_full_data_transaction(
                video_data=test_video_data,
                keyword_id=keyword_id,
                comments=test_comments_1
            )
            if success:
                print(f"[성공 결과] 1차 데이터가 DB에 저장되었습니다.")
            else:
                raise Exception("1차 실행 트랜잭션 실패")

        # --- 2차 실행: 댓글 변경분 처리 (SCD Type 2 테스트) ---
        print("\n--- 2차 실행: 댓글 변경분(신규/수정/유지) 처리 ---")
        
        # CommentA: 내용 변경
        # CommentB: 내용 유지
        # CommentD: 신규 추가
        test_comments_2 = [
            {'id': 'CommentA', 'content': '정말 유익해요! 구독했습니다!', 'author': '김수강'},
            {'id': 'CommentB', 'content': '이해가 잘 안가네요.', 'author': '이초보'},
            {'id': 'CommentD', 'content': '새로운 댓글입니다.', 'author': '최신입'},
        ]
        
        if keyword_id:
            success = db_manager.process_full_data_transaction(
                video_data=test_video_data, # 메타데이터는 동일
                keyword_id=keyword_id,
                comments=test_comments_2
            )
            if success:
                print(f"[성공 결과] 2차 변경 데이터(신규1, 수정1, 유지1)가 DB에 반영되었습니다.")
                print("DB에서 CommentA는 2개(이전/현재), B는 1개, C는 1개(마감안됨), D는 1개의 레코드를 가져야 합니다.")

    except Exception as e:
        print(f"테스트 중 예상치 못한 오류: {e}")
        
    finally:
        print("\n테스트 종료.")