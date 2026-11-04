import { useEffect, useState } from 'react'

import { ApiError } from '../api/client'

/**
 * 화면 진입 시 데이터를 불러오는 공통 훅.
 * load는 useCallback으로 감싸서 넘긴다. load가 바뀌면(예: 다른 계좌 id) 다시 불러온다.
 */
export function useLoad<T>(load: () => Promise<T>) {
  const [result, setResult] = useState<{ load: () => Promise<T>; data: T | null; error: string | null } | null>(null)

  useEffect(() => {
    let alive = true
    load().then(
      (data) => alive && setResult({ load, data, error: null }),
      (e) => alive && setResult({ load, data: null, error: e instanceof ApiError ? e.message : '불러오지 못했어요.' }),
    )
    return () => {
      alive = false
    }
  }, [load])

  const current = result?.load === load ? result : null // 아직 이번 load의 결과가 없으면 로딩 중
  return { data: current?.data ?? null, error: current?.error ?? null, loading: current === null }
}
