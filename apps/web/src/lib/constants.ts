const PK = "https://den-media.pokellector.com/logos";

// JP release order — lower number = newer. Sets without an entry sort last.
export const SET_RELEASE_ORDER: Record<string, number> = {
  // SV era (newest → oldest)
  SV11W: 0, SV11B: 1,
  SV10: 2,
  SV9A: 3, SV9: 4,
  SV8A: 5, SV8: 6,
  SV7A: 7, SV7: 8,
  SV6A: 9, SV6: 10,
  SV5A: 11, SV5M: 12, SV5K: 13,
  SV4A: 14, SV4M: 15, SV4K: 16,
  SV3A: 17, SV3: 18,
  SV2A: 19, SV2D: 20, SV2P: 21,
  SV1A: 22, SV1V: 23, SV1S: 24,
  // ME era (newest → oldest)
  M4: 0, M3: 1,
  M2A: 2, M2: 3,
  M1S: 4, M1L: 5,
};

export const SET_LOGO_URLS: Record<string, string> = {
  SV1A:  `${PK}/Triple-Beat.logo.366.png`,
  SV1S:  `${PK}/Scarlet-ex.logo.361.png`,
  SV1V:  `${PK}/Violet-ex.logo.362.png`,
  SV2P:  `${PK}/Snow-Hazard.logo.369.png`,
  SV2D:  `${PK}/Clay-Burst.logo.370.png`,
  SV2A:  `${PK}/Pokemon-151.logo.371.png`,
  SV3:   `${PK}/Ruler-of-the-Black-Flame.logo.368.png`,
  SV3A:  `${PK}/Raging-Surf.logo.376.png`,
  SV4A:  `${PK}/Shiny-Treasure-ex.logo.375.png`,
  SV4K:  `${PK}/Ancient-Roar.logo.381.png`,
  SV4M:  `${PK}/Future-Flash.logo.382.png`,
  SV5K:  `${PK}/Wild-Force.logo.386.png`,
  SV5M:  `${PK}/Cyber-Judge.logo.387.png`,
  SV5A:  `${PK}/Crimson-Haze.logo.391.png`,
  SV6:   `${PK}/Mask-of-Change.logo.393.png`,
  SV6A:  `${PK}/Night-Wanderer.logo.398.png`,
  SV7:   `${PK}/Stella-Miracle.logo.401.png`,
  SV7A:  `${PK}/Paradise-Dragona.logo.403.png`,
  SV8:   `${PK}/Super-Electric-Breaker.logo.405.png`,
  SV8A:  `${PK}/Terastal-Festival-ex.logo.406.png`,
  SV9:   `${PK}/Battle-Partners.logo.408.png`,
  SV9A:  `${PK}/Hot-Air-Arena.logo.411.png`,
  SV10:  `${PK}/Glory-of-Team-Rocket.logo.413.png`,
  SV11B: `${PK}/Black-Bolt.logo.414.png`,
  SV11W: `${PK}/White-Flare.logo.415.png`,
  M1L:   `${PK}/Mega-Brave.logo.416.png`,
  M1S:   `${PK}/Mega-Symphonia.logo.417.png`,
  M2:    `${PK}/Inferno-X.logo.425.png`,
  M2A:   `${PK}/MEGA-Dream-ex.logo.427.png`,
  M3:    `${PK}/Munikis-Zero.logo.428.png`,
  M4:    `${PK}/Ninja-Spinner.logo.430.png`,
};

export const ERA_LABELS: Record<string, string> = {
  sv: "Scarlet & Violet",
  me: "Mega Evolution",
};

export const CONDITION_LABELS: Record<string, string> = {
  S: "S",
  A: "A",
  B: "B",
  D: "D",
  new: "New",
  used: "Used",
};

// Rarity sort order — higher = rarer. Unknown rarities default to 99 in the
// sort helper so they always sort to the top when sorting rarest-first.
// MA is the ME-era equivalent of SAR/UR; MUR sits above UR in the newest sets.
export const RARITY_SORT_ORDER: Record<string, number> = {
  C: 0,
  U: 1,
  R: 2,
  RR: 3,
  PR: 4,   // promo — at least as rare as RR in practice
  RRR: 5,
  SR: 6,
  AR: 7,
  SAR: 8,
  MA: 8,   // ME-era top-tier art rare (equivalent to SAR)
  BWR: 8,  // SV11B/W Black & White Rare (equivalent tier to SAR/MA)
  UR: 9,
  MUR: 10,
};
