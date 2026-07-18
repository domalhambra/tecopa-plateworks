// state.js — compatibility shim. The state object and its derived helpers moved to
// store.js when the wizard became a studio (the mutation choke-point lives there now).
// canvas.js and markers.js still import { state, activeRegion, metresPerPx,
// cropOverviewPx, finalWidthPx } from here, so this re-export keeps them untouched.
// New modules import from store.js directly.
export * from './store.js';
