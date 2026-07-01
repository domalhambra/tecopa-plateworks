/* @ds-bundle: {"format":3,"namespace":"BadwaterHDDesignSystem_cd9780","components":[{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"Chip","sourcePath":"components/core/Chip.jsx"},{"name":"Eyebrow","sourcePath":"components/core/Eyebrow.jsx"},{"name":"Callout","sourcePath":"components/feedback/Callout.jsx"},{"name":"DeepDive","sourcePath":"components/feedback/DeepDive.jsx"},{"name":"CenterBadge","sourcePath":"components/hd/CenterBadge.jsx"},{"name":"TypeBadge","sourcePath":"components/hd/TypeBadge.jsx"}],"sourceHashes":{"components/core/Badge.jsx":"9a306d26f65d","components/core/Button.jsx":"84c6c0c7e9af","components/core/Card.jsx":"233f087f1c4c","components/core/Chip.jsx":"9d0a02270460","components/core/Eyebrow.jsx":"a50a1f1d50ff","components/feedback/Callout.jsx":"990f2ae022a7","components/feedback/DeepDive.jsx":"8257440a973a","components/hd/CenterBadge.jsx":"78ca36e678ab","components/hd/TypeBadge.jsx":"5ea8fa934815","screens.jsx":"dc884135e90d","ui_kits/badwater-hd/data.jsx":"a2f38b5f0e10","ui_kits/badwater-hd/screens.jsx":"14b02c34d081","ui_kits/badwater-hd/walker.jsx":"40fd0ca33b3e"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.BadwaterHDDesignSystem_cd9780 = window.BadwaterHDDesignSystem_cd9780 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Badge — a small rounded pill for identity and status. The terracotta
 * outline "identity badge" is the canonical use (Type · Profile · Authority);
 * filled and semantic tones cover labels and states.
 */
function Badge({
  tone = 'outline',
  children,
  style,
  ...rest
}) {
  const tones = {
    outline: {
      background: 'transparent',
      color: 'var(--color-accent-text)',
      border: '1px solid var(--color-accent)'
    },
    solid: {
      background: 'var(--color-accent-strong)',
      color: 'var(--color-accent-foreground)',
      border: '1px solid transparent'
    },
    gold: {
      background: 'transparent',
      color: 'var(--color-accent-gold)',
      border: '1px solid var(--color-accent-gold)'
    },
    neutral: {
      background: 'var(--surface-recessed)',
      color: 'var(--color-secondary)',
      border: '1px solid var(--color-border-strong)'
    },
    success: {
      background: 'transparent',
      color: 'var(--color-success)',
      border: '1px solid var(--color-success)'
    }
  };
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 'var(--spacing-3)',
    padding: 'var(--spacing-2) var(--spacing-5)',
    borderRadius: 'var(--radius-round)',
    fontFamily: 'var(--font-family-body)',
    fontSize: 'var(--font-x-small)',
    lineHeight: 1.3,
    fontWeight: 'var(--font-weight-medium)',
    whiteSpace: 'nowrap',
    ...tones[tone],
    ...style
  };
  return /*#__PURE__*/React.createElement("span", _extends({
    style: base
  }, rest), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Button — Badwater HD's primary action control.
 * Terracotta solid for primary actions, a quiet outline for secondary,
 * and a borderless text style for tertiary. Gentle 6px radius, never bubbly.
 */
function Button({
  variant = 'primary',
  size = 'medium',
  as = 'button',
  href,
  disabled = false,
  fullWidth = false,
  children,
  style,
  ...rest
}) {
  const sizes = {
    small: {
      padding: 'var(--spacing-3) var(--spacing-6)',
      fontSize: 'var(--font-x-small)'
    },
    medium: {
      padding: 'var(--spacing-5) var(--spacing-8)',
      fontSize: 'var(--font-small)'
    },
    large: {
      padding: 'var(--spacing-6) var(--spacing-9)',
      fontSize: 'var(--font-h5)'
    }
  };
  const variants = {
    primary: {
      background: 'var(--color-accent-strong)',
      color: 'var(--color-accent-foreground)',
      border: '1px solid transparent'
    },
    secondary: {
      background: 'transparent',
      color: 'var(--color-accent-text)',
      border: '1px solid var(--color-accent)'
    },
    gold: {
      background: 'var(--color-accent-gold)',
      color: 'var(--color-accent-gold-foreground)',
      border: '1px solid transparent'
    },
    ghost: {
      background: 'transparent',
      color: 'var(--color-foreground)',
      border: '1px solid var(--color-border-strong)'
    }
  };
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 'var(--spacing-4)',
    fontFamily: 'var(--font-family-body)',
    fontWeight: 'var(--font-weight-medium)',
    lineHeight: 1,
    textDecoration: 'none',
    borderRadius: 'var(--radius-1)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    width: fullWidth ? '100%' : 'auto',
    transition: 'background 0.15s ease, border-color 0.15s ease, color 0.15s ease',
    ...sizes[size],
    ...variants[variant],
    ...style
  };
  const Tag = as === 'a' || href ? 'a' : 'button';
  const tagProps = Tag === 'a' ? {
    href
  } : {
    disabled
  };
  return /*#__PURE__*/React.createElement(Tag, _extends({
    style: base
  }, tagProps, rest), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Chip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Chip — a compact pill link used for cross-references between entities
 * (gates, channels, lines). Mono type, rounded, neutral until hover where it
 * picks up the terracotta accent. The connective tissue of the atlas.
 */
function Chip({
  as = 'a',
  href,
  active = false,
  children,
  style,
  ...rest
}) {
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 'var(--spacing-3)',
    background: active ? 'var(--color-accent-strong)' : 'var(--surface-recessed)',
    border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border-strong)'}`,
    color: active ? 'var(--color-accent-foreground)' : 'var(--color-foreground)',
    padding: 'var(--spacing-3) var(--spacing-5)',
    borderRadius: 'var(--radius-round)',
    fontFamily: 'var(--font-family-mono)',
    fontSize: 'var(--font-x-small)',
    lineHeight: 1.2,
    textDecoration: 'none',
    whiteSpace: 'nowrap',
    transition: 'border-color 0.15s, color 0.15s',
    cursor: 'pointer',
    ...style
  };
  const Tag = as === 'a' || href ? 'a' : 'span';
  return /*#__PURE__*/React.createElement(Tag, _extends({
    style: base,
    href: Tag === 'a' ? href : undefined
  }, rest), children);
}
Object.assign(__ds_scope, { Chip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Chip.jsx", error: String((e && e.message) || e) }); }

// components/core/Eyebrow.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Eyebrow — the brand's signature label. Uppercase, letter-spaced, small.
 * Accent-colored by default to mark a section; pass tone="muted" for a
 * quieter metadata label.
 */
function Eyebrow({
  tone = 'accent',
  as = 'div',
  children,
  style,
  ...rest
}) {
  const tones = {
    accent: 'var(--color-accent-text)',
    muted: 'var(--color-secondary)',
    gold: 'var(--color-accent-gold)'
  };
  const base = {
    fontFamily: 'var(--font-family-body)',
    fontSize: 'var(--font-x-small)',
    textTransform: 'uppercase',
    letterSpacing: 'var(--tracking-eyebrow)',
    fontWeight: 'var(--font-weight-medium)',
    color: tones[tone] || tones.accent,
    ...style
  };
  const Tag = as;
  return /*#__PURE__*/React.createElement(Tag, _extends({
    style: base
  }, rest), children);
}
Object.assign(__ds_scope, { Eyebrow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Eyebrow.jsx", error: String((e && e.message) || e) }); }

// components/core/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Card — the entity index card. An elevated surface with an optional
 * accent top-rule + label, a titled link, an italic keynote, a one-line
 * mechanism, and a row of cross-reference chips. The atlas's primary unit.
 */
function Card({
  label,
  title,
  href,
  keynote,
  mechanism,
  accent = 'var(--color-accent)',
  chips = [],
  children,
  style,
  ...rest
}) {
  const card = {
    background: 'var(--surface-elevated)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-2)',
    boxShadow: 'var(--card-shadow)',
    padding: 'var(--spacing-6) var(--spacing-7)',
    display: 'flex',
    flexDirection: 'column',
    gap: 'var(--spacing-4)',
    ...style
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: card
  }, rest), label && /*#__PURE__*/React.createElement("div", {
    style: {
      borderTop: `2px solid ${accent}`,
      paddingTop: 'var(--spacing-3)'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Eyebrow, null, label)), title && /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontSize: 'var(--font-h4)',
      fontWeight: 'var(--font-weight-semibold)'
    }
  }, href ? /*#__PURE__*/React.createElement("a", {
    style: {
      color: 'var(--color-contrast)',
      textDecoration: 'none'
    },
    href: href
  }, title) : title), keynote && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontStyle: 'italic',
      fontSize: 'var(--font-small)',
      color: 'var(--color-foreground)',
      opacity: 0.75
    }
  }, keynote), mechanism && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--font-small)',
      lineHeight: 1.45,
      color: 'var(--color-foreground)',
      opacity: 0.9
    }
  }, mechanism), children, chips.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-2)',
      marginTop: 'var(--spacing-3)'
    }
  }, chips.map((c, i) => typeof c === 'string' ? /*#__PURE__*/React.createElement(__ds_scope.Chip, {
    key: i
  }, c) : /*#__PURE__*/React.createElement(__ds_scope.Chip, {
    key: i,
    href: c.href
  }, c.label))));
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Callout.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Callout — a left-bordered aside that breaks reading flow without a box.
 * "context" is the terracotta-ruled background note; "note" is the quiet
 * gold-ruled italic margin remark; "bespoke" is a borderless accent section.
 */
function Callout({
  variant = 'context',
  label,
  children,
  style,
  ...rest
}) {
  const variants = {
    context: {
      background: 'var(--color-background-200)',
      borderLeft: '3px solid var(--color-accent)',
      padding: 'var(--spacing-6) var(--spacing-7)',
      borderRadius: 'var(--radius-1)',
      color: 'var(--color-foreground)',
      fontStyle: 'normal'
    },
    note: {
      background: 'transparent',
      borderLeft: '2px solid var(--color-accent-gold)',
      padding: 'var(--spacing-3) var(--spacing-5)',
      color: 'var(--color-secondary)',
      fontStyle: 'italic'
    },
    bespoke: {
      background: 'transparent',
      borderLeft: '3px solid var(--color-accent)',
      padding: '0 0 0 var(--spacing-7)',
      color: 'var(--color-contrast)',
      fontStyle: 'normal'
    }
  };
  const base = {
    margin: 'var(--spacing-7) 0',
    fontSize: 'var(--font-small)',
    lineHeight: 1.55,
    ...variants[variant],
    ...style
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: base
  }, rest), label && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--font-x-small)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-eyebrow)',
      color: variant === 'note' ? 'var(--color-accent-gold)' : 'var(--color-accent-text)',
      fontWeight: 'var(--font-weight-medium)',
      marginBottom: 'var(--spacing-3)',
      fontStyle: 'normal'
    }
  }, label), children);
}
Object.assign(__ds_scope, { Callout });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Callout.jsx", error: String((e && e.message) || e) }); }

// components/feedback/DeepDive.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * DeepDive — a disclosure for optional depth, matching the atlas's
 * "hd-deep-dive" surface. A bordered box with a rotating ▸ marker; closed by
 * default so the page stays calm until the reader opts in.
 */
function DeepDive({
  summary,
  defaultOpen = false,
  children,
  style,
  ...rest
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const box = {
    margin: 'var(--spacing-7) 0',
    padding: 'var(--spacing-5) var(--spacing-7)',
    background: 'var(--color-background-200)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-1)',
    fontSize: 'var(--font-small)',
    ...style
  };
  const summaryStyle = {
    cursor: 'pointer',
    fontWeight: 'var(--font-weight-medium)',
    color: 'var(--color-contrast)',
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--spacing-3)',
    listStyle: 'none',
    userSelect: 'none'
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: box
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: summaryStyle,
    onClick: () => setOpen(o => !o)
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-secondary)',
      display: 'inline-block',
      transition: 'transform 0.15s ease',
      transform: open ? 'rotate(90deg)' : 'none'
    }
  }, "\u25B8"), summary), open && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'var(--spacing-5)',
      paddingTop: 'var(--spacing-3)',
      borderTop: '1px solid var(--color-border)',
      color: 'var(--color-foreground)',
      lineHeight: 1.55
    }
  }, children));
}
Object.assign(__ds_scope, { DeepDive });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/DeepDive.jsx", error: String((e && e.message) || e) }); }

// components/hd/CenterBadge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const CENTERS = {
  head: {
    token: '--center-head',
    label: 'Head'
  },
  ajna: {
    token: '--center-ajna',
    label: 'Ajna'
  },
  throat: {
    token: '--center-throat',
    label: 'Throat'
  },
  'g-center': {
    token: '--center-g-center',
    label: 'G Center'
  },
  'heart-ego': {
    token: '--center-heart-ego',
    label: 'Heart / Ego'
  },
  sacral: {
    token: '--center-sacral',
    label: 'Sacral'
  },
  'solar-plexus': {
    token: '--center-solar-plexus',
    label: 'Solar Plexus'
  },
  spleen: {
    token: '--center-spleen',
    label: 'Spleen'
  },
  root: {
    token: '--center-root',
    label: 'Root'
  }
};

/**
 * CenterBadge — names one of the nine Human Design centers with its canonical
 * color. A filled swatch dot plus the center label, optionally noting whether
 * the center is defined or open.
 */
function CenterBadge({
  center = 'sacral',
  state,
  label,
  style,
  ...rest
}) {
  const meta = CENTERS[center] || CENTERS.sacral;
  const color = `var(${meta.token})`;
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 'var(--spacing-4)',
    padding: 'var(--spacing-3) var(--spacing-5) var(--spacing-3) var(--spacing-3)',
    border: '1px solid var(--color-border-strong)',
    borderRadius: 'var(--radius-round)',
    background: 'var(--surface-recessed)',
    fontFamily: 'var(--font-family-body)',
    fontSize: 'var(--font-x-small)',
    color: 'var(--color-foreground)',
    whiteSpace: 'nowrap',
    ...style
  };
  const dot = {
    width: '0.85rem',
    height: '0.85rem',
    borderRadius: 'var(--radius-round)',
    background: state === 'open' ? 'transparent' : color,
    border: `2px solid ${color}`,
    flexShrink: 0
  };
  return /*#__PURE__*/React.createElement("span", _extends({
    style: base
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: dot
  }), label || meta.label, state && /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-secondary)',
      fontSize: 'var(--font-chip)',
      textTransform: 'uppercase',
      letterSpacing: '0.05em'
    }
  }, state));
}
Object.assign(__ds_scope, { CenterBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/hd/CenterBadge.jsx", error: String((e && e.message) || e) }); }

// components/hd/TypeBadge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const TYPES = {
  manifestor: {
    token: '--type-manifestor',
    label: 'Manifestor',
    strategy: 'To Inform'
  },
  generator: {
    token: '--type-generator',
    label: 'Generator',
    strategy: 'To Respond'
  },
  'manifesting-generator': {
    token: '--type-manifesting-generator',
    label: 'Manifesting Generator',
    strategy: 'Respond, then Inform'
  },
  projector: {
    token: '--type-projector',
    label: 'Projector',
    strategy: 'Wait for the Invitation'
  },
  reflector: {
    token: '--type-reflector',
    label: 'Reflector',
    strategy: 'Wait a Lunar Cycle'
  }
};

/**
 * TypeBadge — names one of the five Human Design Types with its aura color.
 * A soft-tinted capsule carrying the type name and, optionally, its strategy.
 * The aura color is drawn through a translucent fill so it reads on either bg.
 */
function TypeBadge({
  type = 'generator',
  showStrategy = false,
  style,
  ...rest
}) {
  const meta = TYPES[type] || TYPES.generator;
  const color = `var(${meta.token})`;
  const base = {
    display: 'inline-flex',
    flexDirection: showStrategy ? 'column' : 'row',
    alignItems: showStrategy ? 'flex-start' : 'center',
    gap: showStrategy ? 'var(--spacing-1)' : 'var(--spacing-4)',
    padding: 'var(--spacing-4) var(--spacing-6)',
    borderRadius: 'var(--radius-2)',
    border: `1px solid ${color}`,
    background: `color-mix(in srgb, ${color} 14%, transparent)`,
    fontFamily: 'var(--font-family-body)',
    ...style
  };
  return /*#__PURE__*/React.createElement("span", _extends({
    style: base
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--spacing-4)',
      fontSize: 'var(--font-small)',
      fontWeight: 'var(--font-weight-semibold)',
      color: 'var(--color-contrast)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: '0.6rem',
      height: '0.6rem',
      borderRadius: 'var(--radius-round)',
      background: color,
      flexShrink: 0
    }
  }), meta.label), showStrategy && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--font-x-small)',
      fontStyle: 'italic',
      color: 'var(--color-secondary)',
      paddingLeft: '1rem'
    }
  }, meta.strategy));
}
Object.assign(__ds_scope, { TypeBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/hd/TypeBadge.jsx", error: String((e && e.message) || e) }); }

// screens.jsx
try { (() => {
// Badwater HD encyclopedia — screen components. Compose the design-system
// primitives from window.BadwaterHDDesignSystem_cd9780.
const DS = window.BadwaterHDDesignSystem_cd9780;
const {
  Button,
  Chip,
  Badge,
  Eyebrow,
  Card,
  Callout,
  DeepDive,
  CenterBadge,
  TypeBadge
} = DS;
const MARK = '../../assets/badwater-mark.svg';

/* ---- Site nav ---------------------------------------------------------- */
function SiteNav({
  chartLoaded,
  onLoadChart,
  scheme,
  onToggleScheme,
  onHome
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-5)',
      padding: 'var(--spacing-4) var(--spacing-7)',
      background: 'var(--surface-elevated)',
      borderBottom: '1px solid var(--color-border)',
      position: 'sticky',
      top: 0,
      zIndex: 50
    }
  }, /*#__PURE__*/React.createElement("a", {
    onClick: onHome,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-4)',
      cursor: 'pointer',
      textDecoration: 'none'
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: MARK,
    alt: "",
    style: {
      width: 22,
      height: 22,
      filter: 'none'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-family-headings)',
      fontWeight: 'var(--font-weight-semibold)',
      fontSize: 'var(--font-h5)',
      color: 'var(--color-contrast)'
    }
  }, "Badwater HD")), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      maxWidth: 360,
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-4)',
      padding: 'var(--spacing-3) var(--spacing-6)',
      background: 'var(--surface-recessed)',
      border: '1px solid var(--color-border-strong)',
      borderRadius: 'var(--radius-round)',
      color: 'var(--color-mute)',
      fontSize: 'var(--font-small)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.7
    }
  }, "\u2315"), /*#__PURE__*/React.createElement("span", null, "Search gates, channels, centers\u2026")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-5)'
    }
  }, chartLoaded ? /*#__PURE__*/React.createElement(Badge, {
    tone: "outline"
  }, "MG \xB7 3/5 \xB7 Sacral") : /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "small",
    onClick: onLoadChart
  }, "+ Add your chart"), /*#__PURE__*/React.createElement("button", {
    onClick: onToggleScheme,
    title: "Toggle color scheme",
    style: {
      background: 'transparent',
      border: '1px solid var(--color-border-strong)',
      borderRadius: 'var(--radius-round)',
      width: 30,
      height: 30,
      color: 'var(--color-secondary)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, scheme === 'light' ? '☾' : '☀')));
}

/* ---- Home -------------------------------------------------------------- */
function HomeScreen({
  chartLoaded,
  onOpenEntity
}) {
  return /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 'var(--container-wide)',
      margin: '0 auto'
    }
  }, chartLoaded ? /*#__PURE__*/React.createElement("section", {
    style: {
      textAlign: 'center',
      padding: 'var(--spacing-10) var(--spacing-7)',
      background: 'linear-gradient(180deg, rgba(212,175,106,0.05), transparent)'
    },
    "data-comment-anchor": "ffb3e12dcc-section-47-9"
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      marginBottom: 'var(--spacing-5)'
    }
  }, "Welcome back"), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: 'var(--font-display)',
      fontWeight: 'var(--font-weight-regular)',
      margin: '0 0 var(--spacing-6)'
    }
  }, "Manifesting Generator ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "\xB7"), " 3/5 ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "\xB7"), " Sacral ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "\xB7"), " Split"), /*#__PURE__*/React.createElement("p", {
    style: {
      maxWidth: 480,
      margin: '0 auto',
      color: 'var(--color-foreground)',
      opacity: 0.8,
      fontSize: 'var(--font-small)',
      lineHeight: 1.6
    }
  }, "Your chart sets your aura, strategy, and authority. The encyclopedia below tracks what is defined, what is open, and how energy moves through you.")) : /*#__PURE__*/React.createElement("section", {
    style: {
      textAlign: 'center',
      padding: 'var(--spacing-10) var(--spacing-7)',
      background: 'var(--surface-recessed)',
      borderBottom: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: 'var(--font-display)',
      color: 'var(--color-contrast)',
      margin: '0 0 var(--spacing-5)'
    }
  }, "An Atlas of Human Design"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 'var(--font-h4)',
      color: 'var(--color-foreground)',
      opacity: 0.85,
      maxWidth: 'var(--container-default)',
      margin: '0 auto var(--spacing-7)',
      lineHeight: 1.5
    }
  }, "The Badwater atlas of Human Design. Browse by topic with the axis pills below, or pick up a thread with the walks further down."), /*#__PURE__*/React.createElement(Button, {
    variant: "primary"
  }, "Load your chart")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 'var(--spacing-5)',
      padding: 'var(--spacing-6) var(--spacing-7)'
    }
  }, /*#__PURE__*/React.createElement(PathwayCard, {
    accent: "var(--color-accent-gold)",
    tone: "var(--color-accent-gold)",
    eyebrow: "Start with the Not-Self",
    copy: "The conditioning story is the way into the system. Begin where the friction is."
  }), /*#__PURE__*/React.createElement(PathwayCard, {
    accent: "var(--pillar-accent-effort)",
    tone: "var(--pillar-accent-effort)",
    eyebrow: "Energy & Effort",
    copy: "Training, recovery, and burnout read through HD and physiology at once. Spend effort on a body signal, not a plan."
  })), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-7) var(--spacing-7) 0',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    tone: "muted",
    style: {
      marginBottom: 'var(--spacing-6)'
    }
  }, "Browse the atlas"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-4)',
      justifyContent: 'center'
    }
  }, window.AXIS_PILLS.map(p => /*#__PURE__*/React.createElement("a", {
    key: p.label,
    href: p.href,
    style: {
      padding: 'var(--spacing-5) var(--spacing-8)',
      borderRadius: 'var(--radius-round)',
      border: '1px solid var(--color-border-strong)',
      borderTop: `2px solid ${p.accent}`,
      background: 'var(--surface-elevated)',
      color: 'var(--color-foreground)',
      fontSize: 'var(--font-small)',
      textDecoration: 'none',
      fontFamily: 'var(--font-family-headings)'
    }
  }, p.label)))), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-9) var(--spacing-7) 0',
      maxWidth: 'var(--container-wide)',
      margin: '0 auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      marginBottom: 'var(--spacing-7)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-h2)',
      color: 'var(--color-contrast)',
      margin: 0
    }
  }, "Find new connections in Human Design")), window.ThreadWalker ? /*#__PURE__*/React.createElement(window.ThreadWalker, null) : null), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-9) var(--spacing-7) var(--spacing-10)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      marginBottom: 'var(--spacing-7)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-h2)',
      color: 'var(--color-contrast)',
      margin: 0
    }
  }, "Pick up a thread")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: 'var(--spacing-6)'
    }
  }, window.WALKS.map((w, i) => /*#__PURE__*/React.createElement(Card, {
    key: i,
    label: w.label,
    title: w.title,
    href: "#",
    keynote: w.keynote,
    mechanism: w.mechanism,
    accent: w.accent,
    chips: w.chips,
    onClick: e => {
      e.preventDefault();
      onOpenEntity();
    },
    style: {
      cursor: 'pointer'
    }
  })))), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-7) var(--spacing-7) var(--spacing-10)',
      textAlign: 'center',
      borderTop: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    tone: "muted",
    style: {
      marginBottom: 'var(--spacing-6)'
    }
  }, "The five types"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-5)',
      justifyContent: 'center'
    }
  }, window.TYPES_GRID.map(t => /*#__PURE__*/React.createElement(TypeBadge, {
    key: t.type,
    type: t.type,
    showStrategy: true
  })))));
}
function PathwayCard({
  accent,
  tone,
  eyebrow,
  copy
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--spacing-5) var(--spacing-7)',
      background: 'var(--surface-elevated)',
      border: '1px solid var(--color-border-strong)',
      borderLeft: `3px solid ${accent}`,
      borderRadius: 'var(--radius-2)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-family-headings)',
      fontSize: 'var(--font-h5)',
      fontWeight: 'var(--font-weight-semibold)',
      color: tone,
      marginBottom: 'var(--spacing-2)'
    }
  }, eyebrow), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--font-small)',
      color: 'var(--color-foreground)',
      lineHeight: 1.5
    }
  }, copy));
}

/* ---- Entity page ------------------------------------------------------- */
function EntityScreen({
  chartLoaded,
  onBack
}) {
  const g = window.GATE_25;
  return /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 'var(--container-wide)',
      margin: '0 auto',
      padding: 'var(--spacing-9) var(--spacing-8)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-secondary)',
      marginBottom: 'var(--spacing-5)'
    }
  }, g.breadcrumb.map((b, i) => /*#__PURE__*/React.createElement("span", {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      margin: '0 var(--spacing-2)',
      color: 'var(--color-mute)'
    }
  }, "\u203A"), i < g.breadcrumb.length - 1 ? /*#__PURE__*/React.createElement("a", {
    onClick: i === 0 ? onBack : undefined,
    style: {
      color: 'var(--color-secondary)',
      textDecoration: 'underline',
      cursor: 'pointer'
    }
  }, b) : /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-contrast)',
      fontWeight: 'var(--font-weight-medium)'
    }
  }, b)))), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: '1.75rem',
      margin: '0 0 var(--spacing-3)'
    }
  }, g.title), /*#__PURE__*/React.createElement("p", {
    style: {
      color: 'var(--color-secondary)',
      fontSize: 'var(--font-small)',
      margin: '0 0 var(--spacing-6)',
      fontStyle: 'italic'
    }
  }, g.subtitle), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-3)',
      marginBottom: 'var(--spacing-9)'
    }
  }, /*#__PURE__*/React.createElement(CenterBadge, {
    center: g.center,
    state: "defined"
  }), /*#__PURE__*/React.createElement(Badge, {
    tone: "gold"
  }, g.keynote), /*#__PURE__*/React.createElement(Chip, null, g.channel)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0,1fr) 16rem',
      gap: 'var(--spacing-9)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0,
      fontSize: '1rem',
      lineHeight: 'var(--leading-prose)',
      maxWidth: '68ch'
    }
  }, chartLoaded && /*#__PURE__*/React.createElement(Callout, {
    variant: "context",
    label: "On your chart"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, g.context)), g.prose.map((para, i) => /*#__PURE__*/React.createElement("p", {
    key: i,
    style: {
      margin: '0 0 var(--spacing-7)'
    }
  }, para)), /*#__PURE__*/React.createElement(DeepDive, {
    summary: "The classical lineage of this gate"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, g.deepDive)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'var(--spacing-9)',
      paddingTop: 'var(--spacing-7)',
      borderTop: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    tone: "muted",
    style: {
      marginBottom: 'var(--spacing-6)',
      display: 'block'
    }
  }, "Reaching gates"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-3)'
    }
  }, g.related.map((c, i) => /*#__PURE__*/React.createElement(Chip, {
    key: i,
    href: "#"
  }, c.label))))), /*#__PURE__*/React.createElement("aside", null, /*#__PURE__*/React.createElement(Callout, {
    variant: "note"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, g.marginNote)))));
}
Object.assign(window, {
  SiteNav,
  HomeScreen,
  EntityScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/badwater-hd/data.jsx
try { (() => {
// Sample data for the Badwater HD encyclopedia UI kit. Content is written in
// the Badwater register (claim-first, no em dashes, no emoji).

const AXIS_PILLS = [{
  label: 'The Design',
  href: '#',
  accent: 'var(--pillar-accent-design)'
}, {
  label: 'The Bodygraph',
  href: '#',
  accent: 'var(--pillar-accent-bodygraph)'
}, {
  label: 'The Wheel',
  href: '#',
  accent: 'var(--pillar-accent-wheel)'
}, {
  label: 'The Not-Self',
  href: '#',
  accent: 'var(--pillar-accent-notself)'
}, {
  label: 'Energy & Effort',
  href: '#',
  accent: 'var(--pillar-accent-effort)'
}, {
  label: 'Reference',
  href: '#',
  accent: 'var(--pillar-accent-reference)'
}];
const TYPES_GRID = [{
  type: 'manifestor',
  strategy: 'To Inform'
}, {
  type: 'generator',
  strategy: 'To Respond'
}, {
  type: 'manifesting-generator',
  strategy: 'Respond, then Inform'
}, {
  type: 'projector',
  strategy: 'Wait for the Invitation'
}, {
  type: 'reflector',
  strategy: 'Wait a Lunar Cycle'
}];
const WALKS = [{
  label: 'Gate 25',
  title: 'The Spirit of the Self',
  keynote: 'Innocence',
  mechanism: 'Universal love that survives any trial. The love of the universe pressed into a single gate.',
  accent: 'var(--center-head)',
  chips: [{
    label: 'G Center'
  }, {
    label: '51–25'
  }]
}, {
  label: 'Channel 34–20',
  title: 'The Channel of Charisma',
  keynote: 'Where thoughts become deeds',
  mechanism: 'Sacral power wired straight to the Throat. Busy by default, magnetic when it responds.',
  accent: 'var(--center-throat)',
  chips: [{
    label: 'Sacral'
  }, {
    label: 'Throat'
  }]
}, {
  label: 'Gate 51',
  title: 'The Gate of Shock',
  keynote: 'Arousing',
  mechanism: 'The thunderclap that initiates. Competition as the engine of individual courage.',
  accent: 'var(--center-head)',
  chips: [{
    label: 'Heart / Ego'
  }, {
    label: '51–25'
  }]
}, {
  label: 'Center',
  title: 'The Sacral',
  keynote: 'Life force, work, response',
  mechanism: 'The motor that powers generators. Defined, it is consistent energy for the right work.',
  accent: 'var(--center-g-center)',
  chips: [{
    label: '9 gates'
  }, {
    label: 'Motor'
  }]
}, {
  label: 'Profile',
  title: '3/5 — Martyr / Heretic',
  keynote: 'Trial and error, then projection',
  mechanism: 'A life of experiments that become wisdom others reach for in a crisis.',
  accent: 'var(--color-accent-gold)',
  chips: [{
    label: 'Line 3'
  }, {
    label: 'Line 5'
  }]
}, {
  label: 'Authority',
  title: 'Sacral Authority',
  keynote: 'The gut sound in the moment',
  mechanism: 'Decisions arrive as an immediate uh-huh or uh-uh. The mind narrates after, it does not decide.',
  accent: 'var(--center-sacral)',
  chips: [{
    label: 'Generators'
  }, {
    label: 'In the now'
  }]
}];
const GATE_25 = {
  breadcrumb: ['Atlas', 'Gates', 'G Center', 'Gate 25'],
  title: 'Gate 25 — The Spirit of the Self',
  subtitle: 'The love of the universe. Universal love that survives any trial.',
  center: 'g-center',
  keynote: 'Innocence',
  channel: '51–25',
  prose: ["Gate 25 sits at the top of the G Center, pointed at the Heart. It is the gate of universal love, which is not the warm personal love of family or romance. It is love without an object. The same care extended to a stranger, a rival, a desert, a fire.", "The mechanism is innocence. Gate 25 meets each trial without the residue of the last one. That is what makes it spirit rather than sentiment. Personal love remembers and keeps score. Universal love forgets, and so it can keep meeting the world clean.", "Wired to Gate 51 through the Channel of Initiation, Gate 25 is what survives the shock. The thunderclap of 51 either breaks you or initiates you. Gate 25 is the innocence that walks through and is still able to love what just struck it."],
  marginNote: "The classical name is the Channel of Initiation. Read it as a wiring diagram, not a verdict.",
  context: "If you have Gate 25 defined, this love is a fixed feature of your design, not a mood you summon. The work is letting it be impersonal rather than forcing it into the shape of personal affection.",
  deepDive: "Ra Uru Hu tied Gate 25 to the I Ching's hexagram of Innocence, the spirit that meets each moment without the calculation of the previous one. The gate's shadow is the demand that love be returned in kind. Its gift is the love that asks for nothing back.",
  related: [{
    label: 'Gate 51'
  }, {
    label: 'Channel 51–25'
  }, {
    label: 'G Center'
  }, {
    label: 'Heart / Ego'
  }, {
    label: 'Line 3'
  }]
};
const BROWSE_GROUPS = [{
  label: 'The Design',
  accent: 'var(--pillar-accent-design)',
  hubHref: '#',
  links: ['Types', 'Authority', 'Strategy', 'Profiles', 'Lines', 'Definition', 'Aura']
}, {
  label: 'The BodyGraph',
  accent: 'var(--pillar-accent-bodygraph)',
  hubHref: '#',
  links: ['Centers', 'Gates', 'Channels', 'Circuits']
}, {
  label: 'The Wheel',
  accent: 'var(--pillar-accent-wheel)',
  hubHref: '#',
  links: ['Quarters', 'Godheads', 'Planets', 'Zodiac Mandala', 'Incarnation Crosses', 'Nodal Mechanics']
}, {
  label: 'The Not-Self',
  accent: 'var(--pillar-accent-notself)',
  hubHref: '#',
  links: ['By Center', 'By Type', 'With Others', 'Practices']
}, {
  label: 'Energy & Effort',
  accent: 'var(--pillar-accent-effort)',
  hubHref: '#',
  links: ['By Type', 'The Signal', 'Under Load', 'Train by Design']
}, {
  label: 'Reference',
  accent: 'var(--pillar-accent-reference)',
  hubHref: '#',
  links: ['Recently Updated']
}];
const EE_HUB = {
  eyebrow: 'Energy Management & Physiology',
  title: 'Spend effort on a signal, not a plan.',
  lead: 'Human Design and endurance physiology arrive at the same operating rule from opposite directions. HD calls the signal Strategy and Authority and calls the failure the Not-Self. Physiology calls the signal autoregulation and calls the failure allostatic debt. This pillar reads training, recovery, and burnout through both lenses at once, holding the science honestly and the chart as a lived practice rather than a fixed blueprint.',
  movements: [{
    num: '01',
    kicker: 'The thesis',
    title: 'Two maps, one instruction',
    lead: "Override the body's present-state signal and run on borrowed capacity, and you improve fast, then stall, then break. HD names that arc the Not-Self. Physiology names it allostatic debt. Both corrections are the same: subtract the overcommitment and let a body-resident signal set the load.",
    more: 'Read the instruction'
  }, {
    num: '02',
    kicker: 'By Type',
    title: 'Five engines, five training doses',
    lead: "A defined Sacral is a sustainable engine when it is responding, carrying a mostly-easy week of real volume read against the Sacral's yes and the morning HRV trend. The non-sacral Types run a smaller, intermittent supply built for bursts and real rest. Prescribe a Generator-shaped training life to a Projector and it breaks the same way an intensity plan breaks a volume-built athlete: an engine pushed on fuel it cannot sustain.",
    more: 'Read by Type',
    links: ['Generator', 'Manifesting Generator', 'Projector', 'Manifestor', 'Reflector']
  }, {
    num: '03',
    kicker: 'The Signal',
    title: 'Authority is autoregulation',
    lead: "Sacral response, the in-the-moment yes or no, is the move endurance coaching calls autoregulation: the body's present state sets the session instead of a number prescribed weeks earlier. Which raises the sharpest practical question for an HD-informed training practice. Is Authority a cleaner readiness read than a wearable's recovery score?",
    more: 'Enter The Signal'
  }, {
    num: '04',
    kicker: 'Under Load',
    title: 'The physiology of the Not-Self',
    lead: "The Root is the adrenal pressure center, and its Not-Self rush to be free of pressure is the same body physiology reads as chronic HPA-axis activation: the flattened cortisol rhythm, the wear of never standing down. Burnout, overtraining, and the long convalescence all live here.",
    more: 'Enter Under Load'
  }, {
    num: '05',
    kicker: 'The practice',
    title: 'Train by design',
    lead: "What the instruction looks like in a training week: reading your own signal, sizing the dose to the engine, and knowing where the science runs out. Some protocols are still open work, the Reflector's most of all.",
    more: 'Enter the practice'
  }]
};
const SEARCH_NODES = [
// Types
{
  label: 'Manifestor',
  kind: 'type',
  keynote: 'To Inform'
}, {
  label: 'Generator',
  kind: 'type',
  keynote: 'To Respond'
}, {
  label: 'Manifesting Generator',
  kind: 'type',
  keynote: 'Respond, then Inform'
}, {
  label: 'Projector',
  kind: 'type',
  keynote: 'Wait for the Invitation'
}, {
  label: 'Reflector',
  kind: 'type',
  keynote: 'Wait a Lunar Cycle'
},
// Authorities
{
  label: 'Emotional Authority',
  kind: 'authority',
  keynote: 'Wait out the wave'
}, {
  label: 'Sacral Authority',
  kind: 'authority',
  keynote: 'The gut response'
}, {
  label: 'Splenic Authority',
  kind: 'authority',
  keynote: 'The quiet in-the-moment knowing'
}, {
  label: 'Ego Authority',
  kind: 'authority',
  keynote: 'What the heart wants'
}, {
  label: 'Self-Projected Authority',
  kind: 'authority',
  keynote: 'Hear yourself talk it out'
},
// Centers
{
  label: 'Head',
  kind: 'center',
  keynote: 'Inspiration & mental pressure'
}, {
  label: 'Ajna',
  kind: 'center',
  keynote: 'Conceptualization'
}, {
  label: 'Throat',
  kind: 'center',
  keynote: 'Manifestation & communication'
}, {
  label: 'G Center',
  kind: 'center',
  keynote: 'Identity, direction, love'
}, {
  label: 'Heart / Ego',
  kind: 'center',
  keynote: 'Willpower'
}, {
  label: 'Sacral',
  kind: 'center',
  keynote: 'Life force & work'
}, {
  label: 'Solar Plexus',
  kind: 'center',
  keynote: 'The emotional wave'
}, {
  label: 'Spleen',
  kind: 'center',
  keynote: 'Intuition & survival'
}, {
  label: 'Root',
  kind: 'center',
  keynote: 'Adrenaline & pressure'
},
// Gates
{
  label: 'Gate 25 — Spirit of the Self',
  kind: 'gate',
  keynote: 'Innocence'
}, {
  label: 'Gate 51 — Shock',
  kind: 'gate',
  keynote: 'Arousing'
}, {
  label: 'Gate 34 — Power',
  kind: 'gate',
  keynote: 'The majesty of the individual'
}, {
  label: 'Gate 20 — The Now',
  kind: 'gate',
  keynote: 'Contemplation into action'
}, {
  label: 'Gate 10 — Behavior of the Self',
  kind: 'gate',
  keynote: 'Love of self'
}, {
  label: 'Gate 1 — Self-Expression',
  kind: 'gate',
  keynote: 'The creative'
}, {
  label: 'Gate 2 — Higher Knowing',
  kind: 'gate',
  keynote: 'The receptive'
},
// Channels
{
  label: 'Channel 34–20 — Charisma',
  kind: 'channel',
  keynote: 'Where thoughts become deeds'
}, {
  label: 'Channel 51–25 — Initiation',
  kind: 'channel',
  keynote: 'The logic of shock'
}, {
  label: 'Channel 10–57 — Perfected Form',
  kind: 'channel',
  keynote: 'Survival on the intuitive now'
},
// Profiles
{
  label: '1/3 — Investigator / Martyr',
  kind: 'profile',
  keynote: 'Foundation through trial'
}, {
  label: '3/5 — Martyr / Heretic',
  kind: 'profile',
  keynote: 'Trial and error, then projection'
}, {
  label: '4/6 — Opportunist / Role Model',
  kind: 'profile',
  keynote: 'Network, then example'
}, {
  label: '6/2 — Role Model / Hermit',
  kind: 'profile',
  keynote: 'The natural example'
},
// Lines
{
  label: 'Line 1 — Investigator',
  kind: 'line',
  keynote: 'Foundation'
}, {
  label: 'Line 3 — Martyr',
  kind: 'line',
  keynote: 'Trial and error'
}, {
  label: 'Line 5 — Heretic',
  kind: 'line',
  keynote: 'Projection'
}];
Object.assign(window, {
  AXIS_PILLS,
  TYPES_GRID,
  WALKS,
  GATE_25,
  BROWSE_GROUPS,
  EE_HUB,
  SEARCH_NODES
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/badwater-hd/data.jsx", error: String((e && e.message) || e) }); }

// ui_kits/badwater-hd/screens.jsx
try { (() => {
// Badwater HD encyclopedia — screen components. Compose the design-system
// primitives from window.BadwaterHDDesignSystem_cd9780.
const DS = window.BadwaterHDDesignSystem_cd9780;
const {
  Button,
  Chip,
  Badge,
  Eyebrow,
  Card,
  Callout,
  DeepDive,
  CenterBadge,
  TypeBadge
} = DS;
const MARK = '../../assets/badwater-mark.svg';
const SEARCH_KIND_LABELS = {
  type: 'Types',
  authority: 'Authorities',
  center: 'Centers',
  gate: 'Gates',
  channel: 'Channels',
  profile: 'Profiles',
  line: 'Lines'
};
const SEARCH_KIND_COLOR = {
  type: 'var(--color-accent-text)',
  authority: 'var(--center-sacral)',
  center: 'var(--center-g-center)',
  channel: 'var(--center-throat)',
  gate: 'var(--center-head)',
  line: 'var(--center-spleen)',
  profile: 'var(--color-accent-gold)'
};

/* ---- Search ------------------------------------------------------------ */
function SearchBar({
  onSelect
}) {
  const [q, setQ] = React.useState('');
  const [open, setOpen] = React.useState(false);
  const [hi, setHi] = React.useState(-1);
  const blurTimer = React.useRef(null);
  const nodes = window.SEARCH_NODES || [];
  const ql = q.trim().toLowerCase();
  const results = ql ? nodes.filter(n => n.label.toLowerCase().includes(ql) || (n.keynote || '').toLowerCase().includes(ql)).slice(0, 8) : [];

  // Group by kind, preserving rank order.
  const groups = [];
  const seen = {};
  results.forEach(n => {
    if (!seen[n.kind]) {
      seen[n.kind] = [];
      groups.push([n.kind, seen[n.kind]]);
    }
    seen[n.kind].push(n);
  });
  const flat = groups.flatMap(([, items]) => items);
  const showDrop = open && ql.length > 0;
  const pick = n => {
    setOpen(false);
    setQ('');
    setHi(-1);
    onSelect && onSelect(n);
  };
  const onKey = e => {
    if (!showDrop) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHi(h => Math.min(h + 1, flat.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHi(h => Math.max(h - 1, -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const t = hi >= 0 ? flat[hi] : flat[0];
      if (t) pick(t);
    } else if (e.key === 'Escape') {
      setOpen(false);
      e.target.blur();
    }
  };
  let flatIdx = -1;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      flex: 1,
      maxWidth: 360
    },
    onBlur: () => {
      blurTimer.current = setTimeout(() => setOpen(false), 150);
    },
    onFocus: () => {
      if (blurTimer.current) clearTimeout(blurTimer.current);
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-4)',
      padding: 'var(--spacing-3) var(--spacing-6)',
      background: 'var(--surface-recessed)',
      border: `1px solid ${showDrop ? 'var(--color-accent)' : 'var(--color-border-strong)'}`,
      borderRadius: 'var(--radius-round)',
      transition: 'border-color 0.15s'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.7,
      color: 'var(--color-mute)'
    }
  }, "\u2315"), /*#__PURE__*/React.createElement("input", {
    value: q,
    onChange: e => {
      setQ(e.target.value);
      setOpen(true);
      setHi(-1);
    },
    onFocus: () => setOpen(true),
    onKeyDown: onKey,
    placeholder: "Search gates, channels, centers\u2026",
    spellCheck: false,
    autoComplete: "off",
    style: {
      flex: 1,
      minWidth: 0,
      background: 'transparent',
      border: 'none',
      outline: 'none',
      color: 'var(--color-foreground)',
      fontSize: 'var(--font-small)',
      fontFamily: 'var(--font-family-body)'
    }
  })), showDrop && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 'calc(100% + 6px)',
      left: 0,
      right: 0,
      zIndex: 100,
      background: 'var(--surface-elevated)',
      border: '1px solid var(--color-border-strong)',
      borderRadius: 'var(--radius-1)',
      boxShadow: '0 6px 20px rgba(0,0,0,0.28)',
      overflow: 'hidden',
      maxHeight: 380,
      overflowY: 'auto'
    }
  }, flat.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--spacing-5) var(--spacing-6)',
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-mute)'
    }
  }, "No matches for \u201C", q.trim(), "\u201D.") : groups.map(([k, items], gi) => /*#__PURE__*/React.createElement("div", {
    key: k
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--spacing-3) var(--spacing-6) var(--spacing-2)',
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-mute)',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      borderTop: gi === 0 ? 'none' : '1px solid var(--color-border)',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-3)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: SEARCH_KIND_COLOR[k],
      flexShrink: 0
    }
  }), SEARCH_KIND_LABELS[k] || k), items.map(n => {
    flatIdx += 1;
    const idx = flatIdx;
    return /*#__PURE__*/React.createElement("div", {
      key: n.label,
      onMouseDown: e => {
        e.preventDefault();
        pick(n);
      },
      onMouseEnter: () => setHi(idx),
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: 'var(--spacing-5)',
        padding: 'var(--spacing-3) var(--spacing-6)',
        cursor: 'pointer',
        background: hi === idx ? 'var(--surface-recessed)' : 'transparent'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--color-foreground)',
        fontSize: 'var(--font-small)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, n.label), n.keynote && /*#__PURE__*/React.createElement("span", {
      style: {
        flexShrink: 0,
        maxWidth: '42%',
        fontSize: 'var(--font-x-small)',
        fontStyle: 'italic',
        color: 'var(--color-mute)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, n.keynote));
  })))));
}

/* ---- Site nav ---------------------------------------------------------- */
function SiteNav({
  chartLoaded,
  onLoadChart,
  scheme,
  onToggleScheme,
  onHome,
  onSearchSelect
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-5)',
      padding: 'var(--spacing-4) var(--spacing-7)',
      background: 'var(--surface-elevated)',
      borderBottom: '1px solid var(--color-border)',
      position: 'sticky',
      top: 0,
      zIndex: 50
    }
  }, /*#__PURE__*/React.createElement("a", {
    onClick: onHome,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-4)',
      cursor: 'pointer',
      textDecoration: 'none'
    }
  }, /*#__PURE__*/React.createElement("img", {
    src: MARK,
    alt: "",
    style: {
      width: 22,
      height: 22,
      filter: 'none'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-family-headings)',
      fontWeight: 'var(--font-weight-semibold)',
      fontSize: 'var(--font-h5)',
      color: 'var(--color-contrast)'
    }
  }, "Badwater HD")), /*#__PURE__*/React.createElement(SearchBar, {
    onSelect: onSearchSelect
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--spacing-5)'
    }
  }, chartLoaded ? /*#__PURE__*/React.createElement(Badge, {
    tone: "outline"
  }, "MG \xB7 3/5 \xB7 Sacral") : /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "small",
    onClick: onLoadChart
  }, "+ Add your chart"), /*#__PURE__*/React.createElement("button", {
    onClick: onToggleScheme,
    title: "Toggle color scheme",
    style: {
      background: 'transparent',
      border: '1px solid var(--color-border-strong)',
      borderRadius: 'var(--radius-round)',
      width: 30,
      height: 30,
      color: 'var(--color-secondary)',
      cursor: 'pointer',
      fontSize: 14
    }
  }, scheme === 'light' ? '☾' : '☀')));
}

/* ---- Home -------------------------------------------------------------- */
function HomeScreen({
  chartLoaded,
  onOpenEntity,
  onOpenEnergy
}) {
  return /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 'var(--container-wide)',
      margin: '0 auto'
    }
  }, chartLoaded ? /*#__PURE__*/React.createElement("section", {
    style: {
      textAlign: 'center',
      padding: 'var(--spacing-10) var(--spacing-7)',
      background: 'radial-gradient(72% 84% at 50% 0%, color-mix(in srgb, var(--color-accent-gold) 12%, transparent) 0%, transparent 62%)'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      marginBottom: 'var(--spacing-5)'
    }
  }, "Welcome back"), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: 'var(--font-display)',
      fontWeight: 'var(--font-weight-regular)',
      margin: '0 0 var(--spacing-6)'
    }
  }, "Manifesting Generator ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "\xB7"), " 3/5 ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "\xB7"), " Sacral ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "\xB7"), " Split"), /*#__PURE__*/React.createElement("p", {
    style: {
      maxWidth: 480,
      margin: '0 auto',
      color: 'var(--color-foreground)',
      opacity: 0.8,
      fontSize: 'var(--font-small)',
      lineHeight: 1.6
    }
  }, "Your chart sets your aura, strategy, and authority. The encyclopedia below tracks what is defined, what is open, and how energy moves through you.")) : /*#__PURE__*/React.createElement("section", {
    style: {
      textAlign: 'center',
      padding: 'var(--spacing-10) var(--spacing-7)',
      background: 'var(--surface-recessed)',
      borderBottom: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: 'var(--font-display)',
      color: 'var(--color-contrast)',
      margin: '0 0 var(--spacing-5)'
    }
  }, "An Atlas of Human Design"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 'var(--font-h4)',
      color: 'var(--color-foreground)',
      opacity: 0.85,
      maxWidth: 'var(--container-default)',
      margin: '0 auto var(--spacing-7)',
      lineHeight: 1.5
    }
  }, "The Badwater atlas of Human Design. Browse by topic with the axis pills below, or pick up a thread with the walks further down."), /*#__PURE__*/React.createElement(Button, {
    variant: "primary"
  }, "Load your chart")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 'var(--spacing-5)',
      padding: 'var(--spacing-6) var(--spacing-7)'
    }
  }, /*#__PURE__*/React.createElement(PathwayCard, {
    accent: "var(--pillar-accent-notself)",
    tone: "var(--pillar-accent-notself)",
    eyebrow: "Start with the Not-Self",
    copy: "The conditioning story is the way into the system. Begin where the friction is."
  }), /*#__PURE__*/React.createElement(PathwayCard, {
    accent: "var(--pillar-accent-effort)",
    tone: "var(--pillar-accent-effort)",
    eyebrow: "Energy & Effort",
    copy: "Training, recovery, and burnout read through HD and physiology at once. Spend effort on a body signal, not a plan.",
    onClick: onOpenEnergy
  })), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-7) var(--spacing-7) 0',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    tone: "muted",
    style: {
      marginBottom: 'var(--spacing-6)'
    }
  }, "Browse the atlas"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-4)',
      justifyContent: 'center'
    }
  }, window.AXIS_PILLS.map(p => /*#__PURE__*/React.createElement("a", {
    key: p.label,
    href: p.href,
    onClick: e => {
      if (p.label === 'Energy & Effort') {
        e.preventDefault();
        onOpenEnergy && onOpenEnergy();
      }
    },
    style: {
      padding: 'var(--spacing-5) var(--spacing-8)',
      borderRadius: 'var(--radius-round)',
      border: '1px solid var(--color-border-strong)',
      borderTop: `2px solid ${p.accent}`,
      background: 'var(--surface-elevated)',
      color: 'var(--color-foreground)',
      fontSize: 'var(--font-small)',
      textDecoration: 'none',
      fontFamily: 'var(--font-family-headings)'
    }
  }, p.label)))), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-9) var(--spacing-7) 0',
      maxWidth: 'var(--container-wide)',
      margin: '0 auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      marginBottom: 'var(--spacing-7)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-h2)',
      color: 'var(--color-contrast)',
      margin: 0
    }
  }, "Find new connections in Human Design")), window.ThreadWalker ? /*#__PURE__*/React.createElement(window.ThreadWalker, null) : null), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-9) var(--spacing-7) var(--spacing-10)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      marginBottom: 'var(--spacing-7)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-h2)',
      color: 'var(--color-contrast)',
      margin: 0
    }
  }, "Pick up a thread")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: 'var(--spacing-6)'
    }
  }, window.WALKS.map((w, i) => /*#__PURE__*/React.createElement(Card, {
    key: i,
    label: /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--spacing-3)',
        whiteSpace: 'nowrap'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: '50%',
        background: w.accent,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        whiteSpace: 'nowrap'
      }
    }, w.label)),
    title: w.title,
    href: "#",
    keynote: w.keynote,
    mechanism: w.mechanism,
    accent: w.accent,
    chips: w.chips,
    onClick: e => {
      e.preventDefault();
      onOpenEntity();
    },
    style: {
      cursor: 'pointer'
    }
  })))), /*#__PURE__*/React.createElement("section", {
    style: {
      padding: 'var(--spacing-7) var(--spacing-7) var(--spacing-10)',
      textAlign: 'center',
      borderTop: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    tone: "muted",
    style: {
      marginBottom: 'var(--spacing-6)'
    }
  }, "The five types"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-5)',
      justifyContent: 'center'
    }
  }, window.TYPES_GRID.map(t => /*#__PURE__*/React.createElement(TypeBadge, {
    key: t.type,
    type: t.type,
    showStrategy: true
  })))));
}
function PathwayCard({
  accent,
  tone,
  eyebrow,
  copy,
  onClick
}) {
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClick,
    style: {
      padding: 'var(--spacing-5) var(--spacing-7)',
      background: 'var(--surface-elevated)',
      border: '1px solid var(--color-border-strong)',
      borderLeft: `3px solid ${accent}`,
      borderRadius: 'var(--radius-2)',
      cursor: onClick ? 'pointer' : 'default'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-family-headings)',
      fontSize: 'var(--font-h5)',
      fontWeight: 'var(--font-weight-semibold)',
      color: tone,
      marginBottom: 'var(--spacing-2)'
    }
  }, eyebrow), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--font-small)',
      color: 'var(--color-foreground)',
      lineHeight: 1.5
    }
  }, copy));
}

/* ---- Entity page ------------------------------------------------------- */
function EntityScreen({
  chartLoaded,
  onBack
}) {
  const g = window.GATE_25;
  return /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 'var(--container-wide)',
      margin: '0 auto',
      padding: 'var(--spacing-9) var(--spacing-8)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-secondary)',
      marginBottom: 'var(--spacing-5)'
    }
  }, g.breadcrumb.map((b, i) => /*#__PURE__*/React.createElement("span", {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      margin: '0 var(--spacing-2)',
      color: 'var(--color-mute)'
    }
  }, "\u203A"), i < g.breadcrumb.length - 1 ? /*#__PURE__*/React.createElement("a", {
    onClick: i === 0 ? onBack : undefined,
    style: {
      color: 'var(--color-secondary)',
      textDecoration: 'underline',
      cursor: 'pointer'
    }
  }, b) : /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-contrast)',
      fontWeight: 'var(--font-weight-medium)'
    }
  }, b)))), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: '1.75rem',
      margin: '0 0 var(--spacing-3)'
    }
  }, g.title), /*#__PURE__*/React.createElement("p", {
    style: {
      color: 'var(--color-secondary)',
      fontSize: 'var(--font-small)',
      margin: '0 0 var(--spacing-6)',
      fontStyle: 'italic'
    }
  }, g.subtitle), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-3)',
      marginBottom: 'var(--spacing-9)'
    }
  }, /*#__PURE__*/React.createElement(CenterBadge, {
    center: g.center,
    state: "defined"
  }), /*#__PURE__*/React.createElement(Badge, {
    tone: "gold"
  }, g.keynote), /*#__PURE__*/React.createElement(Chip, null, g.channel)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0,1fr) 16rem',
      gap: 'var(--spacing-9)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0,
      fontSize: '1rem',
      lineHeight: 'var(--leading-prose)',
      maxWidth: '68ch'
    }
  }, chartLoaded && /*#__PURE__*/React.createElement(Callout, {
    variant: "context",
    label: "On your chart"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, g.context)), g.prose.map((para, i) => /*#__PURE__*/React.createElement("p", {
    key: i,
    style: {
      margin: '0 0 var(--spacing-7)'
    }
  }, para)), /*#__PURE__*/React.createElement(DeepDive, {
    summary: "The classical lineage of this gate"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, g.deepDive)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'var(--spacing-9)',
      paddingTop: 'var(--spacing-7)',
      borderTop: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    tone: "muted",
    style: {
      marginBottom: 'var(--spacing-6)',
      display: 'block'
    }
  }, "Reaching gates"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-3)'
    }
  }, g.related.map((c, i) => /*#__PURE__*/React.createElement(Chip, {
    key: i,
    href: "#"
  }, c.label))))), /*#__PURE__*/React.createElement("aside", null, /*#__PURE__*/React.createElement(Callout, {
    variant: "note"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, g.marginNote)))));
}

/* ---- Site footer ------------------------------------------------------- */
function SiteFooter({
  scheme,
  onToggleScheme
}) {
  const pill = {
    display: 'inline-block',
    background: 'transparent',
    border: '1px solid var(--color-border-strong)',
    color: 'var(--color-foreground)',
    padding: 'var(--spacing-3) var(--spacing-7)',
    borderRadius: 'var(--radius-2)',
    fontSize: 'var(--font-x-small)',
    textDecoration: 'none',
    cursor: 'pointer'
  };
  return /*#__PURE__*/React.createElement("footer", {
    style: {
      background: 'var(--surface-elevated)',
      padding: 'var(--spacing-9) var(--spacing-7)',
      borderTop: '1px solid var(--color-border)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--spacing-9)'
    }
  }, /*#__PURE__*/React.createElement("nav", {
    style: {
      maxWidth: 960,
      width: '100%',
      margin: '0 auto'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-x-small)',
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      color: 'var(--color-secondary)',
      margin: '0 0 var(--spacing-7)',
      fontWeight: 'var(--font-weight-semibold)',
      textAlign: 'center'
    }
  }, "Browse the Atlas"), /*#__PURE__*/React.createElement("div", null, window.BROWSE_GROUPS.map((g, gi) => /*#__PURE__*/React.createElement("div", {
    key: g.label,
    style: {
      display: 'grid',
      gridTemplateColumns: 'minmax(150px, 210px) 1fr',
      gap: 'var(--spacing-7)',
      alignItems: 'baseline',
      padding: 'var(--spacing-6) 0',
      borderTop: gi === 0 ? 'none' : '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: g.hubHref,
    onClick: e => e.preventDefault(),
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--spacing-4)',
      fontFamily: 'var(--font-family-headings)',
      fontSize: 'var(--font-h5)',
      fontWeight: 'var(--font-weight-semibold)',
      color: g.accent,
      textDecoration: 'none',
      lineHeight: 1.2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 9,
      height: 9,
      borderRadius: '50%',
      background: g.accent,
      flexShrink: 0
    }
  }), g.label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'baseline',
      gap: '2px 0',
      fontSize: 'var(--font-small)',
      lineHeight: 1.5
    }
  }, g.links.map((l, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: l
  }, i > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-mute)',
      margin: '0 var(--spacing-4)'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      color: 'var(--color-foreground)',
      textDecoration: 'none',
      whiteSpace: 'nowrap'
    }
  }, l)))))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--spacing-7)',
      alignItems: 'center',
      textAlign: 'center',
      borderTop: '1px solid var(--color-border)',
      paddingTop: 'var(--spacing-9)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      justifyContent: 'center',
      gap: 'var(--spacing-3)'
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "#",
    style: pill,
    onClick: e => e.preventDefault()
  }, "About Badwater"), /*#__PURE__*/React.createElement("a", {
    href: "#",
    style: pill,
    onClick: e => e.preventDefault()
  }, "Edit your chart")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: {
      color: 'var(--color-foreground)',
      fontSize: 'var(--font-small)',
      margin: '0 0 var(--spacing-5)',
      maxWidth: 420
    }
  }, "I also write about Human Design, travel, and whatever else is on my mind in my blog. You can join with the button below."), /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      display: 'inline-block',
      background: 'var(--color-accent-strong)',
      color: 'var(--color-accent-foreground)',
      padding: 'var(--spacing-5) var(--spacing-8)',
      borderRadius: 'var(--radius-1)',
      textDecoration: 'none',
      fontWeight: 'var(--font-weight-medium)',
      fontSize: 'var(--font-small)'
    }
  }, "Subscribe to my newsletter")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--spacing-4)',
      alignItems: 'center',
      color: 'var(--color-mute)',
      fontSize: 'var(--font-x-small)'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onToggleScheme,
    style: {
      background: 'transparent',
      border: '1px solid var(--color-border-strong)',
      borderRadius: 'var(--radius-round)',
      padding: 'var(--spacing-2) var(--spacing-6)',
      color: 'var(--color-secondary)',
      cursor: 'pointer',
      fontSize: 'var(--font-x-small)'
    }
  }, scheme === 'light' ? '☾ Dark' : '☀ Light'), /*#__PURE__*/React.createElement("span", null, "Badwater HD: An atlas of Human Design"))));
}

/* ---- Energy & Effort pillar hub ---------------------------------------- */
function EnergyEffortHub({
  onBack,
  onOpenEntity
}) {
  const h = window.EE_HUB;
  const A = 'var(--pillar-accent-effort)';
  const kicker = {
    fontSize: '0.72rem',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: A,
    fontWeight: 600,
    margin: '0 0 var(--spacing-2)'
  };
  const moreLink = {
    display: 'inline-block',
    marginTop: 'var(--spacing-5)',
    fontWeight: 600,
    color: A,
    textDecoration: 'none',
    fontSize: 'var(--font-small)'
  };
  return /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 960,
      margin: '0 auto',
      padding: 'var(--spacing-7) var(--spacing-7) var(--spacing-10)',
      borderTop: `3px solid ${A}`
    }
  }, /*#__PURE__*/React.createElement("nav", {
    style: {
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-secondary)',
      margin: 'var(--spacing-6) 0 var(--spacing-8)'
    }
  }, /*#__PURE__*/React.createElement("a", {
    onClick: onBack,
    style: {
      color: 'var(--color-secondary)',
      textDecoration: 'underline',
      cursor: 'pointer'
    }
  }, "Home"), /*#__PURE__*/React.createElement("span", {
    style: {
      margin: '0 var(--spacing-2)',
      color: 'var(--color-mute)'
    }
  }, "\u203A"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-contrast)',
      fontWeight: 'var(--font-weight-medium)'
    }
  }, "Energy & Effort")), /*#__PURE__*/React.createElement("header", {
    style: {
      margin: '0 0 var(--spacing-10)'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: kicker
  }, h.eyebrow), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontSize: 'clamp(2rem, 5vw, 3rem)',
      lineHeight: 1.05,
      margin: '0 0 var(--spacing-5)',
      color: 'var(--color-contrast)',
      maxWidth: '18ch'
    }
  }, h.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: '1.15rem',
      lineHeight: 1.55,
      color: 'var(--color-foreground)',
      maxWidth: '56ch',
      margin: 0
    }
  }, h.lead)), /*#__PURE__*/React.createElement(Callout, {
    variant: "bespoke",
    label: "On your chart",
    style: {
      margin: '0 0 var(--spacing-10)'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, "You read as a ", /*#__PURE__*/React.createElement("strong", null, "Manifesting Generator"), " with a defined Sacral. That is the sustainable engine described in movement two. Read these against your morning signal, not a fixed plan.")), h.movements.map(m => /*#__PURE__*/React.createElement("section", {
    key: m.num,
    style: {
      margin: 'var(--spacing-10) 0'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      ...kicker,
      color: 'var(--color-muted)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: A
    }
  }, m.num), " \xA0 ", m.kicker), /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-h2)',
      lineHeight: 1.2,
      margin: '0 0 var(--spacing-4)',
      color: 'var(--color-contrast)'
    }
  }, m.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: '1.02rem',
      lineHeight: 1.6,
      color: 'var(--color-foreground)',
      maxWidth: '64ch',
      margin: '0 0 var(--spacing-2)'
    }
  }, m.lead), m.links && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--spacing-4) var(--spacing-6)',
      marginTop: 'var(--spacing-5)'
    }
  }, m.links.map(l => /*#__PURE__*/React.createElement("a", {
    key: l,
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontWeight: 600,
      color: A,
      textDecoration: 'none',
      fontSize: 'var(--font-small)'
    }
  }, l))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'var(--spacing-6)'
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => {
      e.preventDefault();
      onOpenEntity && onOpenEntity();
    },
    style: {
      ...moreLink,
      marginTop: 0
    }
  }, m.more, " \u2192")))), /*#__PURE__*/React.createElement("section", {
    style: {
      marginTop: 'var(--spacing-10)',
      paddingTop: 'var(--spacing-7)',
      borderTop: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontSize: 'var(--font-h2)',
      color: 'var(--color-contrast)',
      margin: 0
    }
  }, "Read in order"), /*#__PURE__*/React.createElement("ol", {
    style: {
      listStyle: 'none',
      padding: 0,
      margin: 'var(--spacing-6) 0 0',
      counterReset: 'ee'
    }
  }, h.movements.map(m => /*#__PURE__*/React.createElement("li", {
    key: m.num,
    style: {
      display: 'flex',
      gap: 'var(--spacing-5)',
      alignItems: 'baseline',
      marginBottom: 'var(--spacing-5)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-family-mono)',
      fontSize: 'var(--font-x-small)',
      color: A,
      flexShrink: 0
    }
  }, m.num), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontWeight: 600,
      color: 'var(--color-foreground)',
      textDecoration: 'none'
    }
  }, m.title), /*#__PURE__*/React.createElement("p", {
    style: {
      color: 'var(--color-secondary)',
      margin: '2px 0 0',
      fontSize: 'var(--font-small)',
      maxWidth: '64ch'
    }
  }, m.kicker)))))));
}
Object.assign(window, {
  SiteNav,
  HomeScreen,
  EntityScreen,
  SiteFooter,
  EnergyEffortHub
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/badwater-hd/screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/badwater-hd/walker.jsx
try { (() => {
// Thread Walker — interactive recreation of the homepage graph-walker.
// A small hand-authored slice of the Human Design graph so walking actually
// works: click a neighbor pill (or a node in the force map) to walk to it,
// click a trail tile to jump back, "New thread" to reset.
const WALK_NODES = {
  'type:generator': {
    label: 'Generator',
    kind: 'type',
    keynote: 'To Respond',
    n: ['authority:sacral', 'channel:34-20', 'center:sacral', 'type:mg']
  },
  'type:mg': {
    label: 'Manifesting Generator',
    kind: 'type',
    keynote: 'Respond, then Inform',
    n: ['type:generator', 'channel:34-20', 'center:throat', 'profile:3-5']
  },
  'authority:sacral': {
    label: 'Sacral Authority',
    kind: 'authority',
    keynote: 'The gut sound in the moment',
    n: ['type:generator', 'center:sacral']
  },
  'center:sacral': {
    label: 'The Sacral',
    kind: 'center',
    keynote: 'Life force, work, response',
    n: ['gate:5', 'gate:34', 'channel:34-20', 'type:generator', 'authority:sacral']
  },
  'center:throat': {
    label: 'The Throat',
    kind: 'center',
    keynote: 'Manifestation, communication',
    n: ['channel:34-20', 'gate:20', 'center:g']
  },
  'center:g': {
    label: 'The G Center',
    kind: 'center',
    keynote: 'Identity, direction, love',
    n: ['gate:25', 'gate:10', 'center:throat', 'channel:51-25']
  },
  'center:heart': {
    label: 'The Heart / Ego',
    kind: 'center',
    keynote: 'Willpower, the ego',
    n: ['gate:51', 'channel:51-25']
  },
  'channel:34-20': {
    label: '34-20: Charisma',
    kind: 'channel',
    keynote: 'Where thoughts become deeds',
    n: ['gate:34', 'gate:20', 'center:sacral', 'center:throat']
  },
  'channel:51-25': {
    label: '51-25: Initiation',
    kind: 'channel',
    keynote: 'The logic of shock',
    n: ['gate:51', 'gate:25', 'center:g', 'center:heart']
  },
  'gate:34': {
    label: '34: Power',
    kind: 'gate',
    keynote: 'The majesty of the individual',
    n: ['channel:34-20', 'center:sacral', 'line:1']
  },
  'gate:20': {
    label: '20: The Now',
    kind: 'gate',
    keynote: 'Contemplation into action',
    n: ['channel:34-20', 'center:throat', 'line:1']
  },
  'gate:25': {
    label: '25: Spirit of the Self',
    kind: 'gate',
    keynote: 'Innocence',
    n: ['channel:51-25', 'center:g', 'gate:51', 'line:3']
  },
  'gate:51': {
    label: '51: Shock',
    kind: 'gate',
    keynote: 'Arousing',
    n: ['channel:51-25', 'center:heart', 'gate:25', 'line:3']
  },
  'gate:10': {
    label: '10: Behavior of the Self',
    kind: 'gate',
    keynote: 'Love of self',
    n: ['center:g', 'line:5']
  },
  'gate:5': {
    label: '5: Fixed Rhythms',
    kind: 'gate',
    keynote: 'Waiting, timing, ritual',
    n: ['center:sacral', 'line:2']
  },
  'line:1': {
    label: 'Line 1 — Investigator',
    kind: 'line',
    keynote: 'Foundation',
    n: ['gate:34', 'gate:20']
  },
  'line:2': {
    label: 'Line 2 — Hermit',
    kind: 'line',
    keynote: 'Natural, called out',
    n: ['gate:5']
  },
  'line:3': {
    label: 'Line 3 — Martyr',
    kind: 'line',
    keynote: 'Trial and error',
    n: ['gate:25', 'gate:51', 'profile:3-5']
  },
  'line:5': {
    label: 'Line 5 — Heretic',
    kind: 'line',
    keynote: 'Projection, the savior',
    n: ['gate:10', 'profile:3-5']
  },
  'profile:3-5': {
    label: '3/5 — Martyr / Heretic',
    kind: 'profile',
    keynote: 'Experiments that become wisdom',
    n: ['line:3', 'line:5', 'type:mg']
  }
};
const KIND_LABELS = {
  type: 'Types',
  authority: 'Authorities',
  center: 'Centers',
  channel: 'Channels',
  gate: 'Gates',
  line: 'Lines',
  profile: 'Profiles'
};
const KIND_COLOR = {
  type: 'var(--color-accent-text)',
  authority: 'var(--center-sacral)',
  center: 'var(--center-g-center)',
  channel: 'var(--center-throat)',
  gate: 'var(--center-head)',
  line: 'var(--center-spleen)',
  profile: 'var(--color-accent-gold)'
};
const FAN_CAP = 4;
const SEED = 'type:mg';
const tileBase = {
  background: 'var(--surface-elevated)',
  border: '1px solid var(--color-border-strong)',
  color: 'var(--color-foreground)',
  padding: '2px 8px',
  borderRadius: 'var(--radius-1)',
  fontSize: 'var(--font-x-small)',
  cursor: 'pointer',
  fontFamily: 'var(--font-family-mono)',
  transition: 'border-color 0.15s, background 0.15s',
  lineHeight: 1.5,
  whiteSpace: 'nowrap'
};
const lbl = {
  fontSize: 'var(--font-x-small)',
  color: 'var(--color-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em'
};
function ThreadWalker() {
  const [current, setCurrent] = React.useState(SEED);
  const [trail, setTrail] = React.useState([]);
  const [expanded, setExpanded] = React.useState({});
  const node = WALK_NODES[current];
  const walkTo = id => {
    if (id === current) return;
    setTrail(t => [...t, current]);
    setCurrent(id);
    setExpanded({});
  };
  const jumpBack = i => {
    setCurrent(trail[i]);
    setTrail(t => t.slice(0, i));
    setExpanded({});
  };
  const reset = () => {
    setCurrent(SEED);
    setTrail([]);
    setExpanded({});
  };
  const onNodeClick = id => {
    const i = trail.indexOf(id);
    if (i >= 0) jumpBack(i);else walkTo(id);
  };

  // Group neighbors by kind, in encounter order.
  const groups = [];
  const seen = {};
  node.n.forEach(id => {
    const k = WALK_NODES[id].kind;
    if (!seen[k]) {
      seen[k] = [];
      groups.push([k, seen[k]]);
    }
    seen[k].push(id);
  });
  const visibleFan = groups.flatMap(([k, items]) => expanded[k] ? items : items.slice(0, FAN_CAP));
  const kindsPresent = [...new Set([current, ...trail, ...visibleFan].map(id => WALK_NODES[id].kind))];
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: 'var(--surface-recessed)',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-2)',
      padding: 'var(--spacing-5)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--spacing-4)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: '4px 6px',
      paddingBottom: 'var(--spacing-3)',
      borderBottom: '1px solid var(--color-border)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      ...lbl,
      paddingRight: 'var(--spacing-2)'
    }
  }, "Trail"), trail.length === 0 ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--font-small)',
      color: 'var(--color-muted)',
      fontStyle: 'italic'
    }
  }, "Walk to a neighbor to start your trail.") : trail.map((id, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => jumpBack(i),
    style: {
      ...tileBase,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      borderColor: KIND_COLOR[WALK_NODES[id].kind]
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: KIND_COLOR[WALK_NODES[id].kind],
      flexShrink: 0
    }
  }), WALK_NODES[id].label), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--color-muted)',
      fontSize: 'var(--font-x-small)'
    }
  }, "\u2192"))), trail.length > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      ...tileBase,
      cursor: 'default',
      background: 'transparent',
      borderStyle: 'dashed',
      color: 'var(--color-accent-gold)'
    }
  }, "now")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      width: '100%',
      height: 320,
      background: 'var(--color-background-100)',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-1)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement(ForceMap, {
    current: current,
    trail: trail,
    fan: visibleFan,
    onNodeClick: onNodeClick
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 12,
      left: 12,
      maxWidth: 240,
      background: 'color-mix(in srgb, var(--surface-elevated) 86%, transparent)',
      backdropFilter: 'blur(3px)',
      border: '1px solid var(--color-border-strong)',
      borderRadius: 'var(--radius-1)',
      padding: '10px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: lbl
  }, "Current node"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      background: 'var(--color-accent-gold)',
      color: 'var(--color-accent-gold-foreground)',
      padding: '3px 9px',
      borderRadius: 'var(--radius-1)',
      fontSize: 'var(--font-x-small)',
      fontFamily: 'var(--font-family-mono)',
      fontWeight: 600
    }
  }, node.label)), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-foreground)',
      fontStyle: 'italic',
      lineHeight: 1.4
    }
  }, node.keynote), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      color: 'var(--color-accent-text)',
      fontSize: 'var(--font-x-small)',
      textDecoration: 'none',
      borderBottom: '1px dotted var(--color-accent)'
    }
  }, "Go to page \u2192"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--font-x-small)',
      color: 'var(--color-muted)'
    }
  }, node.n.length, " connections"))), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 9,
      left: 12,
      right: 12,
      display: 'flex',
      gap: '12px',
      flexWrap: 'nowrap',
      overflow: 'hidden'
    }
  }, kindsPresent.map(k => /*#__PURE__*/React.createElement("span", {
    key: k,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      fontSize: 'var(--font-chip)',
      color: 'var(--color-secondary)',
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      whiteSpace: 'nowrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: KIND_COLOR[k]
    }
  }), KIND_LABELS[k]))), /*#__PURE__*/React.createElement("button", {
    onClick: reset,
    style: {
      position: 'absolute',
      top: 12,
      right: 12,
      background: 'color-mix(in srgb, var(--surface-elevated) 86%, transparent)',
      border: '1px solid var(--color-border-strong)',
      color: 'var(--color-secondary)',
      padding: '4px 12px',
      borderRadius: 'var(--radius-1)',
      fontSize: 'var(--font-x-small)',
      cursor: 'pointer',
      backdropFilter: 'blur(3px)'
    }
  }, "New thread")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    style: {
      ...lbl,
      display: 'block',
      marginBottom: 'var(--spacing-3)'
    }
  }, "Walk to a neighbor"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))',
      gap: 'var(--spacing-5)'
    }
  }, groups.map(([k, items]) => {
    const isExp = !!expanded[k];
    const shown = isExp ? items : items.slice(0, FAN_CAP);
    const hidden = items.length - shown.length;
    return /*#__PURE__*/React.createElement("div", {
      key: k
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        ...lbl,
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        marginBottom: 'var(--spacing-2)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 7,
        height: 7,
        borderRadius: '50%',
        background: KIND_COLOR[k]
      }
    }), KIND_LABELS[k], " ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--color-muted)'
      }
    }, "(", items.length, ")")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 4
      }
    }, shown.map(id => /*#__PURE__*/React.createElement("button", {
      key: id,
      onClick: () => walkTo(id),
      style: {
        ...tileBase,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        color: 'var(--color-contrast)',
        borderColor: KIND_COLOR[k],
        background: `color-mix(in srgb, ${KIND_COLOR[k]} 15%, var(--surface-elevated))`
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: KIND_COLOR[k],
        flexShrink: 0
      }
    }), WALK_NODES[id].label)), hidden > 0 && /*#__PURE__*/React.createElement("button", {
      onClick: () => setExpanded(e => ({
        ...e,
        [k]: true
      })),
      style: {
        ...tileBase,
        borderStyle: 'dashed',
        color: 'var(--color-muted)'
      }
    }, "+", hidden), isExp && items.length > FAN_CAP && /*#__PURE__*/React.createElement("button", {
      onClick: () => setExpanded(e => ({
        ...e,
        [k]: false
      })),
      style: {
        ...tileBase,
        borderStyle: 'dashed',
        color: 'var(--color-muted)'
      }
    }, "less")));
  }))));
}

/* Force-directed mini-map: lays out the current node, the trail leading into
   it, and the visible fan, drawing every real edge among them so the canvas
   reads as a connected web. A lightweight stand-in for the d3-force map. */
function ForceMap({
  current,
  trail,
  fan,
  onNodeClick
}) {
  const W = 760,
    H = 320,
    cx = W / 2,
    cy = H / 2;
  const key = current + '|' + trail.join(',') + '|' + fan.join(',');
  const {
    pos,
    edges,
    ids
  } = React.useMemo(() => {
    const ids = [...new Set([current, ...trail, ...fan])];
    const hash = s => {
      let h = 0;
      for (let i = 0; i < s.length; i++) h = h * 31 + s.charCodeAt(i) >>> 0;
      return h;
    };
    const pos = {};
    ids.forEach(id => {
      const h = hash(id);
      const a = h % 628 / 100;
      const r = id === current ? 0 : 70 + h % 90;
      pos[id] = {
        x: cx + Math.cos(a) * r,
        y: cy + Math.sin(a) * r,
        vx: 0,
        vy: 0
      };
    });
    const edges = [];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i],
          b = ids[j];
        if (WALK_NODES[a].n.includes(b) || WALK_NODES[b].n.includes(a)) edges.push([a, b]);
      }
    }
    const L = 116,
      kRep = 7400,
      kSpr = 0.045,
      kGrav = 0.006,
      damp = 0.86,
      pad = 46;
    for (let it = 0; it < 180; it++) {
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const A = pos[ids[i]],
            B = pos[ids[j]];
          let dx = A.x - B.x,
            dy = A.y - B.y;
          let d2 = dx * dx + dy * dy || 0.01;
          let d = Math.sqrt(d2);
          const f = kRep / d2;
          const fx = dx / d * f,
            fy = dy / d * f;
          A.vx += fx;
          A.vy += fy;
          B.vx -= fx;
          B.vy -= fy;
        }
      }
      edges.forEach(([a, b]) => {
        const A = pos[a],
          B = pos[b];
        let dx = B.x - A.x,
          dy = B.y - A.y;
        let d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = (d - L) * kSpr;
        const fx = dx / d * f,
          fy = dy / d * f;
        A.vx += fx;
        A.vy += fy;
        B.vx -= fx;
        B.vy -= fy;
      });
      ids.forEach(id => {
        const P = pos[id];
        if (id === current) {
          P.x = cx;
          P.y = cy;
          P.vx = 0;
          P.vy = 0;
          return;
        }
        P.vx += (cx - P.x) * kGrav;
        P.vy += (cy - P.y) * kGrav;
        P.vx *= damp;
        P.vy *= damp;
        P.x += P.vx;
        P.y += P.vy;
      });
    }
    // Fit pass: scale + center the laid-out graph so it fills the canvas
    // regardless of node count (a few nodes spread wide, many pack in).
    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    ids.forEach(id => {
      const P = pos[id];
      minX = Math.min(minX, P.x);
      maxX = Math.max(maxX, P.x);
      minY = Math.min(minY, P.y);
      maxY = Math.max(maxY, P.y);
    });
    const bw = maxX - minX || 1,
      bh = maxY - minY || 1;
    const tx0 = 96,
      tx1 = W - 64,
      ty0 = 84,
      ty1 = H - 50;
    const sx = Math.min(2.9, (tx1 - tx0) / bw),
      sy = Math.min(2.5, (ty1 - ty0) / bh);
    const bcx = (minX + maxX) / 2,
      bcy = (minY + maxY) / 2;
    const tcx = (tx0 + tx1) / 2,
      tcy = (ty0 + ty1) / 2;
    ids.forEach(id => {
      const P = pos[id];
      P.x = tcx + (P.x - bcx) * sx;
      P.y = tcy + (P.y - bcy) * sy;
    });
    return {
      pos,
      edges,
      ids
    };
  }, [key]);
  const short = s => s.length > 16 ? s.slice(0, 15) + '…' : s;
  const trailSet = new Set(trail);
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${W} ${H}`,
    preserveAspectRatio: "xMidYMid meet",
    style: {
      position: 'absolute',
      inset: 0,
      width: '100%',
      height: '100%'
    }
  }, edges.map(([a, b], i) => /*#__PURE__*/React.createElement("line", {
    key: i,
    x1: pos[a].x,
    y1: pos[a].y,
    x2: pos[b].x,
    y2: pos[b].y,
    stroke: "var(--color-border-strong)",
    strokeWidth: "1"
  })), ids.map(id => {
    const p = pos[id],
      nd = WALK_NODES[id],
      isCur = id === current,
      isTrail = trailSet.has(id);
    return /*#__PURE__*/React.createElement("g", {
      key: id,
      style: {
        cursor: isCur ? 'default' : 'pointer'
      },
      onClick: () => !isCur && onNodeClick(id)
    }, /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: isCur ? 10 : 6.5,
      fill: isCur ? 'var(--color-accent-gold)' : isTrail ? 'var(--color-background-300)' : KIND_COLOR[nd.kind],
      stroke: isTrail ? KIND_COLOR[nd.kind] : 'var(--color-background-100)',
      strokeWidth: isTrail ? 1.5 : 2
    }), /*#__PURE__*/React.createElement("text", {
      x: p.x,
      y: p.y + (p.y < cy ? -12 : 19),
      textAnchor: "middle",
      fontSize: isCur ? 11 : 9.5,
      fontWeight: isCur ? 600 : 400,
      fontFamily: "var(--font-family-mono)",
      fill: isCur ? 'var(--color-contrast)' : 'var(--color-secondary)'
    }, short(nd.label)));
  }));
}
Object.assign(window, {
  ThreadWalker
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/badwater-hd/walker.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Chip = __ds_scope.Chip;

__ds_ns.Eyebrow = __ds_scope.Eyebrow;

__ds_ns.Callout = __ds_scope.Callout;

__ds_ns.DeepDive = __ds_scope.DeepDive;

__ds_ns.CenterBadge = __ds_scope.CenterBadge;

__ds_ns.TypeBadge = __ds_scope.TypeBadge;

})();
