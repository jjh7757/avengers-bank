class TransferService:
    # 이 도메인은 테이블이 없다. 계좌 데이터는 accounts.repository를 통해 읽고 쓴다.
    #
    # TODO: transfer(db, data, current_user) — 입출금 → 입출금 이체
    #   async with db.begin():
    #       1. 보내는 계좌가 본인 것인지 확인 (ForbiddenException)
    #       2. 받는 계좌 찾기 (NotFoundException)
    #       3. 잔액, 1회 한도, 1일 한도 검사 (BadRequestException)
    #       4. 양쪽 balance 변경
    #       5. 양쪽 CheckingAccountHistory 한 줄씩 저장
    # TODO: pay_savings — 입출금 → 적금 납입 (입출금 History + 적금 History)
    # TODO: pay_deposit — 입출금 → 예금 입금 (입출금 History + 예금 History)
    pass


transfer_service = TransferService()
