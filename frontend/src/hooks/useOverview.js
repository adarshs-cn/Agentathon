// The overview data now lives in a shared context (one stream for the whole app).
// This re-export keeps the original hook name working.
export { useSim as useOverview } from '../context/simState';
