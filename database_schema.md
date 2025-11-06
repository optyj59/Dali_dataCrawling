// Database Schema: YouTube Comment Data Warehouse (PostgreSQL) - Hybrid SCD Model

// 1. 키워드 마스터 테이블 (변경 없음)
Table KEYWORD_MASTER {
  keyword_id integer [pk] // 키워드의 고유 ID
  keyword_text varchar(255) [not null] // 키워드 내용
  last_used_time timestamp // 마지막 크롤링 작업에 사용된 시점
}

// 2. 영상 마스터 테이블 (변경 없음)
Table VIDEO_MASTER {
  video_id varchar(20) [pk] // 유튜브 영상의 고유 ID
  video_title varchar(255) [not null] // 영상 제목
  channel_title varchar(255) // 채널 제목
  upload_time timestamp [not null] // 영상 업로드 시간
}

// 3. 영상 메타 정보 테이블 (변경 없음)
Table VIDEO_METADATA_HISTORY {
  metadata_id serial [pk] // 메타 정보 레코드의 고유 ID
  video_id varchar(20) [not null]
  subscriber_count integer // 채널 구독자 숫자
  view_count integer [not null] // 조회수
  like_count integer // 좋아요 숫자
  dislike_count integer // 싫어요 숫자
  total_comment_count integer // 전체 댓글 숫자
  
  // SCD Type 2 필드
  valid_from_time timestamp [not null] // 이 레코드가 유효해진 시점 (수집 시점)
  valid_to_time timestamp // 이 레코드가 만료된 시점 (Null이면 현재 유효)
}

// 4. 키워드-영상 매핑 테이블 (변경 없음)
Table KEYWORD_VIDEO_MAPPING {
  video_id varchar(20) [not null]
  keyword_id integer [not null]
  collection_time timestamp [not null] // 이 키워드로 이 영상이 수집 대상으로 지정된 시점
}

// 5. 댓글 마스터 테이블 (SCD Type 2 유지 - 숫자 정보 제거)
Table COMMENT_MASTER {
  comment_record_id serial [pk] // 댓글 레코드의 고유 ID (SCD 레코드 식별)
  comment_id varchar(50) [not null] // 유튜브 댓글의 고유 ID
  video_id varchar(20) [not null] // 해당 댓글이 달린 영상 ID
  user_name varchar(255) // 사용자 이름
  content text [not null] // 댓글 내용
  parent_comment_id varchar(50) // 대댓글일 경우 원글 댓글 ID
  
  // 시간 정보
  created_time timestamp [not null] // 댓글이 작성된 시간
  collection_time timestamp [not null] // 댓글이 수집된 시점
  
  // SCD Type 2 필드
  valid_from_time timestamp [not null] // 이 레코드가 유효해진 시점 (content 변경 시)
  valid_to_time timestamp // 이 레코드가 만료된 시점
  
  Note: "좋아요/싫어요 수 제거. 댓글 내용/삭제 등 본질적 변화만 SCD Type 2로 추적하여 부하 경감."
}

// 6. 댓글 활동 로그 테이블 (신규 - 숫자 정보 분리)
Table COMMENT_ACTIVITY_LOG {
  activity_id serial [pk] // 활동 로그 레코드의 고유 ID
  comment_id varchar(50) [not null] // 댓글 마스터와 연결되는 자연 키
  collection_time timestamp [not null] // 활동 정보가 수집된 시점 (복합 키의 일부)
  like_count integer // 좋아요 숫자 (SCD Type 2 제외)
  dislike_count integer // 싫어요 숫자 (SCD Type 2 제외)

  Note: "잦은 변동 정보 분리 저장. 좋아요 수 변경 시 COMMENT_MASTER는 변경 없이 이 테이블에 경량 레코드만 INSERT."
}

// 관계 설정 (Ref)
Ref: KEYWORD_VIDEO_MAPPING.keyword_id > KEYWORD_MASTER.keyword_id
Ref: KEYWORD_VIDEO_MAPPING.video_id > VIDEO_MASTER.video_id
Ref: VIDEO_METADATA_HISTORY.video_id > VIDEO_MASTER.video_id
Ref: COMMENT_MASTER.video_id > VIDEO_MASTER.video_id
Ref: COMMENT_ACTIVITY_LOG.comment_id > COMMENT_MASTER.comment_id // 신규 관계

Ref: "COMMENT_MASTER"."user_name" < "COMMENT_MASTER"."content"