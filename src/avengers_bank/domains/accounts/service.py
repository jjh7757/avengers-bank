class AccountService:
    # TODO: open_checking / open_deposit / open_savings
    #       - product_service로 상품 종류 검증
    #       - 계좌번호 발급은 여기 한 곳에서만 (account_repository.exists_by_account_num으로 중복 검사)
    # TODO: get_my_accounts(db, current_user) — 3종 합쳐서 반환
    # TODO: get_account / get_histories — 본인 계좌가 아니면 ForbiddenException
    # TODO: update_account — 별칭, 이체 한도 변경
    pass


account_service = AccountService()
