class CardService:
    # TODO: issue_credit / issue_debit
    #       - product_service로 상품 종류 검증
    #       - 연결할 checking_account_id가 본인 계좌인지 확인
    # TODO: get_my_cards / get_card / get_histories — 본인 카드가 아니면 ForbiddenException
    # TODO: pay(db, card_type, card_id, data, current_user)
    #   async with db.begin():
    #       체크카드: 연결 계좌 잔액 검사 → 출금 → CheckingAccountHistory 저장
    #       공통: CardHistory 저장 + accumulated_amount 증가
    pass


card_service = CardService()
