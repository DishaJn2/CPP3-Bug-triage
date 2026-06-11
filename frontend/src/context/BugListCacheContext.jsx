import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const BugListCacheContext = createContext(null)

const EMPTY_CACHE = {
  bugs: [],
  groups: [],
  flatRows: [],
  total: 0,
  page: 1,
  searchTerm: '',
  filters: {
    severity: '',
    source: '',
    status: 'open',
    activePill: 'All',
  },
  sourcesOnline: 0,
  isPartial: false,
  cacheStatus: null,
  lastFetched: 0,
  lastSynced: null,
}

export function BugListCacheProvider({ children }) {
  const [cache, setCache] = useState(EMPTY_CACHE)

  const updateCache = useCallback((next) => {
    setCache((prev) => ({
      ...prev,
      ...next,
      filters: {
        ...prev.filters,
        ...(next.filters || {}),
      },
    }))
  }, [])

  const value = useMemo(() => ({ cache, updateCache }), [cache, updateCache])

  return (
    <BugListCacheContext.Provider value={value}>
      {children}
    </BugListCacheContext.Provider>
  )
}

export const useBugListCache = () => useContext(BugListCacheContext)
