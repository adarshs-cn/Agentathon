import { createContext, useContext } from 'react';

// The shared simulation state (overview numbers, sim clock, live feed). Provided by SimProvider.
export const SimCtx = createContext(null);

export function useSim() {
  const v = useContext(SimCtx);
  if (!v) throw new Error('useSim must be used inside <SimProvider>');
  return v;
}
