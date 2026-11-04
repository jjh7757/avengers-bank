class AccountRepository:
    # TODO: save(db, account), save_history(db, history)
    # TODO: find_*_by_id(db, account_id) — 입출금·예금·적금 각각
    # TODO: find_all_by_user_id(db, user_id) — 3개 테이블 조회
    # TODO: find_checking_by_account_num(db, account_num) — 이체 받는 계좌 찾기
    # TODO: exists_by_account_num(db, account_num) — 3개 테이블 모두 검사 (계좌번호 중복 방지)
    # TODO: find_histories(db, account_type, account_id)
    # TODO: sum_today_transfer_amount(db, checking_account_id) — 1일 이체 한도 검사용
    pass


account_repository = AccountRepository()
